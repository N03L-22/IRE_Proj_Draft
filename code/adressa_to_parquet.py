"""Stream the Adressa three-month tarball into per-day parquet files.

The archive is read once, in stream mode, and is never extracted: member bytes go from the gzip stream to
parquet chunks. Output names are built from a validated 8-digit member name, never from archive paths.

Layout written under --out:
    YYYYMMDD-000.parquet, YYYYMMDD-001.parquet, ...   chunks of one day, rows in file order
    manifest.jsonl                                    one line per finished day (rows, parts, counters)

Every input key is kept. Keys outside the schema go to the `extra` column as JSON text, so nothing is dropped
silently. A value of the wrong type stops the run instead of being guessed at.

Caveat: `author` and `profile` hold JSON text when the source was a list or object and the plain string when it
was a string, so the two cases differ only by a leading `[` or `{`. Parse only values that start with one.
"""
import argparse
import json
import os
import re
import shutil
import sys
import tarfile
import time

import polars as pl

INT_KEYS = ("eventId", "time", "activeTime")
BOOL_KEYS = ("sessionStart", "sessionStop")
STR_KEYS = (
    "userId", "url", "referrerUrl", "referrerHostClass", "referrerSearchEngine", "referrerSocialNetwork",
    "referrerQuery", "query", "deviceType", "os", "country", "region", "city",
    "id", "canonicalUrl", "title", "category1", "keywords", "publishtime", "author", "profile",
)
KEYS = INT_KEYS + BOOL_KEYS + STR_KEYS
COLUMNS = KEYS + ("extra",)
SCHEMA = {k: pl.Int64 for k in INT_KEYS}
SCHEMA.update({k: pl.Boolean for k in BOOL_KEYS})
SCHEMA.update({k: pl.Utf8 for k in STR_KEYS})
SCHEMA["extra"] = pl.Utf8

DAY_NAME = re.compile(r"^\d{8}$")
CHUNK_ROWS = 400_000
MIN_FREE_BYTES = 6 * 1024**3


class Coercions:
    """Counts values that were not already the expected type, so the run can report them."""

    def __init__(self):
        self.listlike_to_json = 0
        self.scalar_to_str = 0

    def as_dict(self):
        return {"listlike_to_json": self.listlike_to_json, "scalar_to_str": self.scalar_to_str}


def _int(key, v):
    if isinstance(v, bool):
        raise ValueError("%s: bool where an integer was expected: %r" % (key, v))
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    raise ValueError("%s: not an integer: %r" % (key, v))


def _str(v, co):
    if isinstance(v, str):
        return v
    if isinstance(v, (list, dict)):
        co.listlike_to_json += 1
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    co.scalar_to_str += 1
    return json.dumps(v, ensure_ascii=False)


def normalise(event, co):
    """One parsed JSON object -> list of values in COLUMNS order. Raises ValueError on a surprise."""
    if not isinstance(event, dict):
        raise ValueError("event is not an object: %r" % (event,))
    row = []
    for k in INT_KEYS:
        v = event.get(k)
        row.append(None if v is None else _int(k, v))
    for k in BOOL_KEYS:
        v = event.get(k)
        if v is not None and not isinstance(v, bool):
            raise ValueError("%s: not a bool: %r" % (k, v))
        row.append(v)
    for k in STR_KEYS:
        v = event.get(k)
        row.append(None if v is None else _str(v, co))
    extra = {k: v for k, v in event.items() if k not in KEYS}
    row.append(json.dumps(extra, ensure_ascii=False, separators=(",", ":")) if extra else None)
    return row


def _frame(rows):
    cols = list(zip(*rows)) if rows else [()] * len(COLUMNS)
    return pl.DataFrame({c: pl.Series(c, list(cols[i]), dtype=SCHEMA[c]) for i, c in enumerate(COLUMNS)})


def convert_member(fileobj, day, out_dir, co):
    """Convert one day's JSON lines to parquet chunks. Returns (rows, parts, blank_lines, lines_total)."""
    rows, parts, n, blank, lines = [], 0, 0, 0, 0

    def flush():
        nonlocal rows, parts
        if not rows:
            return
        tmp = os.path.join(out_dir, ".tmp-%s-%03d.parquet" % (day, parts))
        _frame(rows).write_parquet(tmp, compression="zstd")
        os.replace(tmp, os.path.join(out_dir, "%s-%03d.parquet" % (day, parts)))
        parts += 1
        rows = []

    for line in fileobj:
        lines += 1
        if not line.strip():
            blank += 1
            continue
        try:
            event = json.loads(line)
            rows.append(normalise(event, co))
        except ValueError as exc:  # JSONDecodeError is a ValueError
            raise ValueError("%s line %d: %s" % (day, lines, exc)) from None
        n += 1
        if len(rows) >= CHUNK_ROWS:
            flush()
    flush()
    return n, parts, blank, lines


def load_manifest(path):
    done = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    done[rec["day"]] = rec
    return done


def clean_partial(out_dir, day):
    for name in os.listdir(out_dir):
        if name.startswith(day + "-") or name.startswith(".tmp-" + day + "-"):
            os.remove(os.path.join(out_dir, name))


def run(archive, out_dir, only=None, limit_days=None):
    os.makedirs(out_dir, exist_ok=True)
    manifest_path = os.path.join(out_dir, "manifest.jsonl")
    done = load_manifest(manifest_path)
    converted = 0
    with tarfile.open(archive, "r|gz") as tar:
        for member in tar:
            name = member.name
            if not DAY_NAME.match(name) or not member.isfile():
                raise ValueError("unexpected archive member %r; refusing to continue" % (name,))
            if only is not None and name not in only:
                continue
            if name in done:
                print("skip %s (already in manifest)" % name, flush=True)
                continue
            free = shutil.disk_usage(out_dir).free
            if free < MIN_FREE_BYTES:
                raise RuntimeError("only %.1f GB free; stopping before %s" % (free / 1e9, name))
            clean_partial(out_dir, name)
            co, t0 = Coercions(), time.time()
            rows, parts, blank, lines = convert_member(tar.extractfile(member), name, out_dir, co)
            rec = {"day": name, "rows": rows, "parts": parts, "blank_lines": blank, "lines": lines,
                   "member_bytes": member.size, "seconds": round(time.time() - t0, 1), **co.as_dict()}
            with open(manifest_path, "a") as f:
                f.write(json.dumps(rec) + "\n")
            print(json.dumps(rec), flush=True)
            converted += 1
            if limit_days is not None and converted >= limit_days:
                break
    return converted


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("archive")
    ap.add_argument("out")
    ap.add_argument("--only", nargs="*", help="convert just these day names, e.g. 20170101")
    ap.add_argument("--limit-days", type=int)
    a = ap.parse_args()
    n = run(a.archive, a.out, set(a.only) if a.only else None, a.limit_days)
    print("converted %d day(s)" % n)
