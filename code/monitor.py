"""Monitoring for units of work (stage-plan section 2.5).

A unit (a bucket, a day, a fit date, a cell) is wrapped in `Unit`. It records phase times, a 1 Hz trace of
RSS / CPU / threads / IO, and it guards memory, swap growth and free disk. A breach aborts the unit by raising
`GuardBreach` at the next `check()`; a gross breach (RSS over 1.25 x the cap) ends the process with exit code 75.
Outputs must be written to a temporary name and renamed (`atomic_write`), so an abort leaves no partial result.

The module has no dependency beyond psutil and the standard library.
"""
import hashlib, json, os, shutil, threading, time
from contextlib import contextmanager

import psutil

GB = 1 << 30
EXIT_ABORT = 75


class GuardBreach(RuntimeError):
    pass


def swap_used_bytes():
    return psutil.swap_memory().used


def file_sha256(path, block=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(block):
            h.update(chunk)
    return h.hexdigest()


def atomic_write(path, writer):
    """writer(tmp_path) writes the file; it is renamed only when the writer returns."""
    tmp = f"{path}.tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    writer(tmp)
    os.replace(tmp, path)


def append_manifest(path, row):
    """One JSON line, appended with O_APPEND so concurrent units never interleave a line."""
    line = (json.dumps(row, sort_keys=True) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def read_manifest(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(x) for x in f if x.strip()]


def manifest_fingerprint(path):
    """Hash of the manifest content, sorted by line, so the order units finished in does not matter."""
    rows = sorted(json.dumps(r, sort_keys=True) for r in read_manifest(path))
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def require_upstream(manifest_path, expected_units=None, expected_fingerprint=None):
    """The handshake: refuse to run on a missing, incomplete or changed upstream."""
    rows = read_manifest(manifest_path)
    if not rows:
        raise GuardBreach(f"upstream manifest missing or empty: {manifest_path}")
    if expected_units is not None:
        have = {r["unit"] for r in rows}
        missing = sorted(set(expected_units) - have)
        if missing:
            raise GuardBreach(f"upstream incomplete, missing units: {missing[:5]}")
    fp = manifest_fingerprint(manifest_path)
    if expected_fingerprint is not None and fp != expected_fingerprint:
        raise GuardBreach("upstream manifest changed since it was read: results built on it are stale")
    return fp


def check_finite(arr, name="array"):
    import numpy as np
    a = np.asarray(arr)
    if a.dtype.kind == "f" and not np.isfinite(a).all():
        raise GuardBreach(f"non-finite values in {name}")


class Unit:
    def __init__(self, stage, unit, trace_dir=None, manifest=None, rss_cap_gb=None, disk_dir=".",
                 min_free_gb=6.0, swap_growth_gb=1.0, interval=1.0, hard_factor=1.25):
        self.stage, self.unit_id = stage, str(unit)
        self.trace_dir, self.manifest = trace_dir, manifest
        self.cap = None if rss_cap_gb is None else int(rss_cap_gb * GB)
        self.disk_dir, self.min_free = disk_dir, int(min_free_gb * GB)
        self.swap_growth, self.interval, self.hard = int(swap_growth_gb * GB), interval, hard_factor
        self.phases, self.trace, self.extra = {}, [], {}
        self.proc = psutil.Process()
        self._stop, self._breach, self._peak = threading.Event(), None, 0

    # ---- guards
    def check(self):
        if self._breach:
            raise GuardBreach(self._breach)

    def _sample(self):
        io0 = self.proc.io_counters() if hasattr(self.proc, "io_counters") else None
        swap0 = swap_used_bytes()
        t0 = time.time()
        while not self._stop.wait(self.interval):
            rss = self.proc.memory_info().rss
            self._peak = max(self._peak, rss)
            io = self.proc.io_counters() if io0 else None
            self.trace.append((round(time.time() - t0, 2), rss, self.proc.cpu_percent(None),
                               self.proc.num_threads(), io.read_bytes if io else 0, io.write_bytes if io else 0))
            why = None
            if self.cap and rss > self.hard * self.cap:
                os.write(2, f"[monitor] {self.stage}/{self.unit_id}: RSS {rss/GB:.1f} GB over {self.hard} x cap, exiting\n".encode())
                os._exit(EXIT_ABORT)
            if self.cap and rss > self.cap:
                why = f"RSS {rss/GB:.2f} GB above the cap {self.cap/GB:.2f} GB"
            elif swap_used_bytes() - swap0 > self.swap_growth:
                why = "swap grew by more than the allowed amount"
            elif shutil.disk_usage(self.disk_dir).free < self.min_free:
                why = "free disk below the guard"
            if why:
                self._breach = why

    @contextmanager
    def phase(self, name):
        t = time.perf_counter()
        try:
            yield
        finally:
            self.phases[name] = round(self.phases.get(name, 0.0) + time.perf_counter() - t, 3)

    def __enter__(self):
        if shutil.disk_usage(self.disk_dir).free < self.min_free:
            raise GuardBreach("free disk below the guard before the unit started")
        self._t0 = time.perf_counter()
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, et, ev, tb):
        self._stop.set()
        self._thread.join()
        self._peak = max(self._peak, self.proc.memory_info().rss)
        wall = round(time.perf_counter() - self._t0, 3)
        if et is None and self._breach:
            raise GuardBreach(self._breach)      # a breach seen after the last check() must not be swallowed
        if et is None:
            row = {"stage": self.stage, "unit": self.unit_id, "status": "ok", "seconds": wall,
                   "phases": self.phases, "peak_rss_gb": round(self._peak / GB, 3), "pid": os.getpid(), **self.extra}
            if self.trace_dir:
                os.makedirs(self.trace_dir, exist_ok=True)
                with open(os.path.join(self.trace_dir, f"{self.stage}_{self.unit_id}.json"), "w") as f:
                    json.dump({"cols": ["s", "rss", "cpu", "threads", "read_bytes", "write_bytes"], "rows": self.trace}, f)
            if self.manifest:
                append_manifest(self.manifest, row)
            self.row = row
            return False
        # a failed or aborted unit writes no manifest line, so a restart redoes it
        return False
