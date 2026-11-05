import json, os, tempfile, time, unittest

import numpy as np

import monitor as M


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_ok_unit_writes_manifest_and_trace(self):
        man = os.path.join(self.d, "m.jsonl")
        with M.Unit("t", "u1", trace_dir=self.d, manifest=man, disk_dir=self.d, min_free_gb=0.001, interval=0.05) as u:
            with u.phase("work"):
                time.sleep(0.2)
        rows = M.read_manifest(man)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["unit"], "u1")
        self.assertGreaterEqual(rows[0]["phases"]["work"], 0.2)
        tr = json.load(open(os.path.join(self.d, "t_u1.json")))
        self.assertGreaterEqual(len(tr["rows"]), 2)

    def test_memory_cap_aborts_without_manifest_line(self):
        man = os.path.join(self.d, "m.jsonl")
        base = M.psutil.Process().memory_info().rss / M.GB
        with self.assertRaises(M.GuardBreach):
            with M.Unit("t", "big", manifest=man, rss_cap_gb=base + 0.15, disk_dir=self.d, min_free_gb=0.001, interval=0.05, hard_factor=100) as u:
                x = np.ones(int(0.3 * M.GB / 8))      # about 0.3 GB, above the cap, below 1.25 x cap
                for _ in range(40):
                    time.sleep(0.05)
                    u.check()
        self.assertEqual(M.read_manifest(man), [])
        del x

    def test_breach_after_last_check_is_still_raised(self):
        base = M.psutil.Process().memory_info().rss / M.GB
        with self.assertRaises(M.GuardBreach):
            with M.Unit("t", "late", rss_cap_gb=base + 0.1, disk_dir=self.d, min_free_gb=0.001, interval=0.05, hard_factor=100):
                x = np.ones(int(0.3 * M.GB / 8))
                time.sleep(0.5)                  # no check() call before the block ends
        del x

    def test_gross_breach_exits_process_with_code_75(self):
        import subprocess, sys
        code = ("import monitor as M, numpy as np, time\n"
                "base = M.psutil.Process().memory_info().rss / M.GB\n"
                "with M.Unit('t', 'g', rss_cap_gb=base + 0.05, disk_dir='.', min_free_gb=0.001, interval=0.05) as u:\n"
                "    x = np.ones(int(0.5 * M.GB / 8)); time.sleep(2)\n")
        r = subprocess.run([sys.executable, "-c", code], cwd=os.path.dirname(os.path.abspath(__file__)))
        self.assertEqual(r.returncode, M.EXIT_ABORT)

    def test_low_disk_refuses_to_start(self):
        with self.assertRaises(M.GuardBreach):
            with M.Unit("t", "d", disk_dir=self.d, min_free_gb=10 ** 6):
                pass

    def test_nan_detected(self):
        with self.assertRaises(M.GuardBreach):
            M.check_finite(np.array([1.0, np.nan], dtype="float32"), "scores")
        M.check_finite(np.array([1, 2], dtype="int32"))

    def test_atomic_write_leaves_nothing_on_failure(self):
        p = os.path.join(self.d, "o.bin")

        def bad(tmp):
            open(tmp, "w").write("half")
            raise OSError("boom")
        with self.assertRaises(OSError):
            M.atomic_write(p, bad)
        self.assertFalse(os.path.exists(p))

    def test_handshake_detects_changed_and_missing_upstream(self):
        man = os.path.join(self.d, "up.jsonl")
        with self.assertRaises(M.GuardBreach):
            M.require_upstream(man)
        M.append_manifest(man, {"unit": "a", "rows": 1})
        M.append_manifest(man, {"unit": "b", "rows": 2})
        fp = M.require_upstream(man, expected_units=["a", "b"])
        with self.assertRaises(M.GuardBreach):
            M.require_upstream(man, expected_units=["a", "b", "c"])
        M.append_manifest(man, {"unit": "c", "rows": 3})
        with self.assertRaises(M.GuardBreach):
            M.require_upstream(man, expected_fingerprint=fp)

    def test_fingerprint_ignores_completion_order(self):
        a, b = os.path.join(self.d, "a"), os.path.join(self.d, "b")
        for r in ({"unit": "x"}, {"unit": "y"}):
            M.append_manifest(a, r)
        for r in ({"unit": "y"}, {"unit": "x"}):
            M.append_manifest(b, r)
        self.assertEqual(M.manifest_fingerprint(a), M.manifest_fingerprint(b))

    def test_monitor_overhead_small(self):
        def work():
            s = 0
            for i in range(3_000_000):
                s += i
            return s
        t = time.perf_counter(); work(); base = time.perf_counter() - t
        t = time.perf_counter()
        with M.Unit("t", "o", disk_dir=self.d, min_free_gb=0.001, interval=1.0):
            work()
        mon = time.perf_counter() - t
        self.assertLess(mon, base * 1.10 + 0.05)


if __name__ == "__main__":
    unittest.main()
