"""Tests for adressa_to_parquet.py. Run: python -I -m unittest test_adressa_to_parquet (from this folder)."""
import glob
import io
import json
import os
import shutil
import tarfile
import tempfile
import unittest

import polars as pl

import adressa_to_parquet as C

EVENTS = [
    {"eventId": 1, "userId": "cx:u1", "time": 1483225202, "activeTime": 8, "sessionStart": False,
     "sessionStop": False, "url": "http://adressa.no", "deviceType": "Mobile", "country": "no"},
    {"eventId": 2, "userId": "cx:u2", "time": 1483225300, "id": "a" * 40, "title": "Nyttårsbilder æøå",
     "category1": "nyheter|trondheim", "keywords": "a,b", "publishtime": "2016-12-31T17:13:57.000Z",
     "author": ["x y", "z"], "profile": [{"item": "k", "groups": [{"count": 1, "group": "concept", "weight": 0.5}]}],
     "canonicalUrl": "http://x/y.ece", "activeTime": 3.0, "somethingNew": {"n": [1, 2]}},
    {"eventId": 3, "userId": "cx:u1", "time": 1483225400, "query": "politinytt", "region": "oslo"},
]


def make_archive(path, members):
    """members: list of (name, list of event dicts or raw bytes)."""
    with tarfile.open(path, "w:gz") as tar:
        for name, content in members:
            data = content if isinstance(content, bytes) else b"".join(
                json.dumps(e, ensure_ascii=False).encode() + b"\n" for e in content)
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def read_day(out, day):
    parts = sorted(glob.glob(os.path.join(out, day + "-*.parquet")))
    return pl.concat([pl.read_parquet(p) for p in parts]) if parts else None


def restore(row):
    """Parquet row (dict) -> the original event dict, for fidelity checks."""
    e = {}
    for k in C.INT_KEYS + C.BOOL_KEYS:
        if row[k] is not None:
            e[k] = row[k]
    for k in C.STR_KEYS:
        if row[k] is not None:
            e[k] = json.loads(row[k]) if k in ("author", "profile") else row[k]
    if row["extra"] is not None:
        e.update(json.loads(row["extra"]))
    return e


class ConverterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="adressa-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.arc = os.path.join(self.tmp, "a.tar.gz")
        self.out = os.path.join(self.tmp, "out")

    def test_round_trip_edge_cases(self):
        make_archive(self.arc, [("20170101", EVENTS)])
        C.run(self.arc, self.out)
        df = read_day(self.out, "20170101")
        self.assertEqual(df.height, 3)
        self.assertEqual(df.columns, list(C.COLUMNS))
        got = [restore(r) for r in df.iter_rows(named=True)]
        want = [dict(e) for e in EVENTS]
        want[1]["activeTime"] = 3  # 3.0 is stored as the integer 3
        self.assertEqual(got, want)

    def test_schema_is_fixed_even_when_a_column_is_all_null(self):
        make_archive(self.arc, [("20170101", [EVENTS[0]]), ("20170102", [EVENTS[2]])])
        C.run(self.arc, self.out)
        d1, d2 = read_day(self.out, "20170101"), read_day(self.out, "20170102")
        self.assertEqual(d1.schema, d2.schema)
        self.assertEqual(dict(d1.schema), C.SCHEMA)
        self.assertEqual(d1["title"].null_count(), 1)

    def test_blank_lines_are_counted_not_rows(self):
        raw = json.dumps(EVENTS[0]).encode() + b"\n\n" + json.dumps(EVENTS[2]).encode() + b"\n"
        make_archive(self.arc, [("20170101", raw)])
        C.run(self.arc, self.out)
        rec = C.load_manifest(os.path.join(self.out, "manifest.jsonl"))["20170101"]
        self.assertEqual((rec["rows"], rec["blank_lines"], rec["lines"]), (2, 1, 3))

    def test_chunking_preserves_order_and_count(self):
        events = [{"eventId": i, "userId": "u%d" % i, "time": 1000 + i} for i in range(10)]
        make_archive(self.arc, [("20170101", events)])
        old = C.CHUNK_ROWS
        C.CHUNK_ROWS = 3
        self.addCleanup(setattr, C, "CHUNK_ROWS", old)
        C.run(self.arc, self.out)
        self.assertEqual(len(glob.glob(os.path.join(self.out, "20170101-*.parquet"))), 4)
        self.assertEqual(read_day(self.out, "20170101")["eventId"].to_list(), list(range(10)))

    def test_bad_values_stop_the_run(self):
        bad = [
            {"eventId": "x", "time": 1},
            {"eventId": True, "time": 1},
            {"eventId": 1, "time": 1.5},
            {"eventId": 1, "sessionStart": "yes"},
            {"eventId": 1, "sessionStart": 1},
        ]
        for i, ev in enumerate(bad):
            arc = os.path.join(self.tmp, "b%d.tar.gz" % i)
            make_archive(arc, [("20170101", [ev])])
            with self.assertRaises(ValueError, msg=repr(ev)):
                C.run(arc, os.path.join(self.tmp, "ob%d" % i))
        for i, raw in enumerate([b"{not json}\n", b"[1,2]\n", b'"text"\n']):
            arc = os.path.join(self.tmp, "r%d.tar.gz" % i)
            make_archive(arc, [("20170101", raw)])
            with self.assertRaises(ValueError, msg=repr(raw)):
                C.run(arc, os.path.join(self.tmp, "or%d" % i))

    def test_failed_day_is_not_in_the_manifest(self):
        make_archive(self.arc, [("20170101", EVENTS), ("20170102", [{"eventId": "bad"}])])
        with self.assertRaises(ValueError):
            C.run(self.arc, self.out)
        self.assertEqual(list(C.load_manifest(os.path.join(self.out, "manifest.jsonl"))), ["20170101"])

    def test_unexpected_member_names_are_refused(self):
        for name in ("../evil", "2017010", "20170101/x", "abcdefgh", "20170101.json"):
            arc = os.path.join(self.tmp, "m.tar.gz")
            make_archive(arc, [(name, EVENTS)])
            with self.assertRaises(ValueError, msg=name):
                C.run(arc, os.path.join(self.tmp, "om"))
        self.assertEqual(os.listdir(self.tmp).count("evil"), 0)

    def test_resume_skips_finished_days_and_clears_partials(self):
        make_archive(self.arc, [("20170101", EVENTS), ("20170102", EVENTS), ("20170103", EVENTS)])
        self.assertEqual(C.run(self.arc, self.out, limit_days=1), 1)
        os.makedirs(self.out, exist_ok=True)
        stray = os.path.join(self.out, "20170102-007.parquet")  # a crashed day: a part file with no manifest line
        shutil.copy(os.path.join(self.out, "20170101-000.parquet"), stray)
        self.assertEqual(C.run(self.arc, self.out), 2)
        man = C.load_manifest(os.path.join(self.out, "manifest.jsonl"))
        self.assertEqual(sorted(man), ["20170101", "20170102", "20170103"])
        for d in man:
            self.assertEqual(read_day(self.out, d).height, 3)
        with open(os.path.join(self.out, "manifest.jsonl")) as f:
            self.assertEqual(len(f.readlines()), 3)
        self.assertEqual([n for n in os.listdir(self.out) if n.startswith(".tmp")], [])

    def test_only_filter(self):
        make_archive(self.arc, [("20170101", EVENTS), ("20170102", EVENTS)])
        C.run(self.arc, self.out, only={"20170102"})
        self.assertIsNone(read_day(self.out, "20170101"))
        self.assertEqual(read_day(self.out, "20170102").height, 3)

    def test_coercion_counters(self):
        ev = {"eventId": 1, "author": ["a"], "title": 5}
        make_archive(self.arc, [("20170101", [ev])])
        C.run(self.arc, self.out)
        rec = C.load_manifest(os.path.join(self.out, "manifest.jsonl"))["20170101"]
        self.assertEqual((rec["listlike_to_json"], rec["scalar_to_str"]), (1, 1))

    def test_disk_guard(self):
        make_archive(self.arc, [("20170101", EVENTS)])
        old = C.MIN_FREE_BYTES
        C.MIN_FREE_BYTES = 10**18
        self.addCleanup(setattr, C, "MIN_FREE_BYTES", old)
        with self.assertRaises(RuntimeError):
            C.run(self.arc, self.out)
        self.assertEqual(glob.glob(os.path.join(self.out, "*.parquet")), [])


if __name__ == "__main__":
    unittest.main()
