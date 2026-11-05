"""T5: the gate before T6. Determinism, resume, pool and day checks on the real stores, and the planted-decay tests on
synthetic worlds with a known turnover. Scratch output goes to <root>/results/_t5/ (inside the project) and is removed.
Run (from code/, not with -I):  python test_t5.py <root>      (the real-data tests are skipped if <root> is missing)
"""
import datetime as dt, glob, hashlib, json, os, shutil, sys, time, unittest

import numpy as np
import polars as pl

import decay, sample
import monitor as M
from core import Corpus, candidate_matrix, metrics_from_ranks, WINDOW
from cell import build_ctx, load_sample, day_start

ROOT = os.environ.get("T5_ROOT") or (sys.argv[1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]) else None)
SCR = os.path.join(ROOT, "results/_t5") if ROOT else None
FAST = ["recency", "popularity", "word", "meaning"]


def hashes(out):
    return {os.path.relpath(f, out): M.file_sha256(f) for f in sorted(glob.glob(os.path.join(out, "r=*/d=*/part.parquet")))}


def clean(*p):
    shutil.rmtree(os.path.join(SCR, *p), ignore_errors=True)


@unittest.skipUnless(ROOT, "needs the project root")
class RealData(unittest.TestCase):
    fits = ["2023-05-10", "2023-05-11"]

    def run_grid(self, tag, workers, order=None):
        out = f"results/_t5/{tag}"
        clean(tag)
        decay.run(ROOT, self.fits, "2023-05-12", out, workers, FAST, order)
        return os.path.join(ROOT, out)

    def test_serial_parallel_order_resume(self):
        a = hashes(self.run_grid("serial", 1))
        self.assertEqual(len(a), 3)                                   # (10,11) (10,12) (11,12)
        b = hashes(self.run_grid("parallel", 2))
        c = hashes(self.run_grid("reversed", 2, order=[1, 0]))
        self.assertEqual(a, b)
        self.assertEqual(a, c)
        # resume: a unit killed after writing some shards (no manifest line) is redone and gives the same bytes
        out = os.path.join(ROOT, "results/_t5/serial")
        victim = os.path.join(out, "r=2023-05-10/d=2023-05-12/part.parquet")
        os.remove(victim)
        mf = os.path.join(out, "manifest.jsonl")
        rows = [r for r in M.read_manifest(mf) if r["unit"] != "r=2023-05-10"]
        with open(mf, "w") as fh:
            fh.write("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
        decay.run(ROOT, self.fits, "2023-05-12", "results/_t5/serial", 1, FAST)
        self.assertEqual(hashes(out), a)
        self.assertEqual(len(M.read_manifest(mf)), 2)
        # recency has no fit state: its cell (r, d) must equal the control cell exactly (gap 0)
        f = pl.read_parquet(os.path.join(out, "r=2023-05-10/d=2023-05-12/part.parquet")).filter(pl.col("scorer") == "recency")
        g = pl.read_parquet(os.path.join(out, "r=2023-05-11/d=2023-05-12/part.parquet")).filter(pl.col("scorer") == "recency")
        self.assertTrue(f.select("regime", "user", "article", "t", "rank").equals(g.select("regime", "user", "article", "t", "rank")))
        # per-click ranks stay in 1..pool and metrics in [0, 1]
        self.assertTrue(((f["rank"] >= 1) & (f["rank"] <= f["pool"])).all())
        # strata partition the clicks and the stratum terms sum exactly to the overall mean
        x = pl.read_parquet(os.path.join(out, "r=2023-05-10/d=2023-05-12/part.parquet")).filter((pl.col("scorer") == "word") & (pl.col("regime") == "A"))
        m = (1.0 / x["rank"].to_numpy())
        s = x["stratum"].to_numpy()
        self.assertEqual(set(np.unique(s)), {0, 1, 2} & set(np.unique(s)))
        self.assertAlmostEqual(sum((s == k).mean() * m[s == k].mean() for k in np.unique(s)), m.mean(), places=12)
        clean("serial"); clean("parallel"); clean("reversed")

    def test_sample_hash_is_stable(self):
        mf = M.read_manifest(os.path.join(ROOT, "data/ebnerd/store/sample/sample_manifest.jsonl"))
        self.assertEqual(len(mf), 14)
        for r in mf:
            self.assertEqual(M.file_sha256(os.path.join(ROOT, f"data/ebnerd/store/sample/clicks_d={r['unit']}.parquet")), r["sample_sha256"])

    def test_pool_and_mutation(self):
        c = Corpus(ROOT, "ebnerd")
        clicks, prof = load_sample(c, "2023-05-18")
        ctx = build_ctx(c, clicks, prof, day_start("2023-05-16") + 86400, "B")
        n = len(ctx.t)
        pub = ctx.cand_pub
        self.assertTrue((pub[ctx.valid] <= np.repeat(ctx.t, ctx.valid.sum(1))).all())          # nothing after the click
        self.assertTrue((pub[ctx.valid] > np.repeat(ctx.t, ctx.valid.sum(1)) - WINDOW).all())  # nothing older than 48 h
        self.assertTrue(ctx.valid[np.arange(n), ctx.tgt_col].all())                            # the clicked article is in its pool
        self.assertEqual(ctx.n_total - ctx.n_excluded, n)
        # mutation: let the pool include articles published after the click; the same check must fail
        lo, hi = c.pools(ctx.t)
        ids, rows, valid = candidate_matrix(c, lo, np.minimum(hi + 5, len(c.sorted_pub)))
        p2 = c.sorted_pub[np.minimum(lo[:, None] + np.arange(valid.shape[1]), len(c.sorted_pub) - 1)]
        self.assertFalse((p2[valid] <= np.repeat(ctx.t, valid.sum(1))).all())

    def test_already_read_rule_on_real_clicks(self):
        c = Corpus(ROOT, "ebnerd")
        clicks, prof = load_sample(c, "2023-05-18")
        a = build_ctx(c, clicks, prof, day_start("2023-05-16") + 86400, "A")
        b = build_ctx(c, clicks, prof, day_start("2023-05-12") + 86400, "B")
        self.assertTrue((a.valid == b.valid).all() and (a.t == b.t).all())            # the evaluation set does not depend on the cell
        from core import build_profiles
        hist, _ = build_profiles(a.user, a.t, prof, 0, "B", 300)
        self.assertFalse((hist == a.target_id[:, None]).any())                         # no re-read is evaluated
        inhist = (a.cand_ids[:, :, None] == hist[:, None, :]).any(2) & a.valid
        self.assertEqual(int(inhist.sum()), 0)                                          # no history article is a candidate
        self.assertGreater(a.n_reread, 0)
        print(f"\nre-reads left out on 2023-05-18: {a.n_reread} of {a.n_total} sampled clicks ({100 * a.n_reread / a.n_total:.1f} %)")

    def test_day_edges(self):
        for name, off in (("ebnerd", 0), ("npr", -3 * 3600), ("adressa", None)):
            st = os.path.join(ROOT, f"data/{name}/store/clicks_by_day")
            for d in sorted(glob.glob(os.path.join(st, "day=*")))[1:3]:
                day = d.split("=")[1]
                t = pl.read_parquet(glob.glob(os.path.join(d, "*.parquet"))[0], columns=["t"])["t"]
                if off is None:        # Adressa: the file's own local day; require one 24 h span
                    self.assertLess(t.max() - t.min(), 86400 + 3600)
                else:
                    lo = day_start(day) - off
                    self.assertGreaterEqual(t.min(), lo)
                    self.assertLess(t.max(), lo + 86400)

    def test_monitor_overhead(self):
        def work():
            a = np.random.default_rng(0).normal(size=(1500, 1500))
            t = time.perf_counter()
            for _ in range(60):
                a @ a
            return time.perf_counter() - t
        work()
        plain = min(work() for _ in range(5))
        def wrapped():
            with M.Unit("t5", "overhead", rss_cap_gb=20, disk_dir=ROOT):
                return work()
        mon = min(wrapped() for _ in range(5))
        print(f"\nmonitor overhead: plain {plain:.2f}s, wrapped {mon:.2f}s, {100 * (mon / plain - 1):+.2f} %")
        self.assertLess(mon / plain, 1.02)


# ----------------------------------------------------------------------------- planted worlds
BASE = int(dt.datetime(2023, 5, 1, tzinfo=dt.timezone.utc).timestamp())
DAYS = [str(dt.date(2023, 5, 1) + dt.timedelta(days=i)) for i in range(9)]


def write_world(name, turnover, seed=5, users=3000, per_day=12, life_h=12):
    root = os.path.join(SCR, name)
    shutil.rmtree(root, ignore_errors=True)
    st = os.path.join(root, f"data/{name}/store")
    os.makedirs(st)
    rng = np.random.default_rng(seed)
    if turnover:                                       # 8 new articles an hour, 2 per category, each lives life_h hours
        hrs = np.arange(-life_h, 24 * len(DAYS))
        pub = np.repeat(BASE + hrs * 3600, 8)
        cat = np.tile(np.repeat(np.arange(4), 2), len(hrs))
    else:                                              # 40 articles, all published long before the log starts
        pub = np.full(1000, BASE - 100 * 86400)
        cat = np.repeat(np.arange(4), 250)
    n = len(pub)
    words = ["sport", "money", "music", "travel"]
    text = [f"{words[c]} item{i}" for i, c in enumerate(cat)]
    pl.DataFrame({"article": np.arange(n, dtype=np.int32), "pub": pub.astype(np.int32), "text": text, "category": cat.astype(str)}) \
        .write_parquet(os.path.join(st, "articles.parquet"))
    u = np.repeat(np.arange(users), per_day)
    for k, day in enumerate(DAYS):
        t = BASE + k * 86400 + rng.integers(0, 86400, len(u))
        ucat = u % 4
        a = np.empty(len(u), dtype=np.int64)
        for c in range(4):
            m = ucat == c
            if turnover:        # hour h of the click, an article published k hours earlier (k < life_h), one of the 2 of the category
                th = (t[m] - BASE) // 3600
                k = rng.integers(0, life_h, m.sum())
                a[m] = (th - k + life_h) * 8 + c * 2 + rng.integers(0, 2, m.sum())
            else:
                pool = np.where(cat == c)[0]
                a[m] = pool[rng.integers(0, len(pool), m.sum())]
        d = os.path.join(st, "clicks_by_day", f"day={day}")
        os.makedirs(d)
        pl.DataFrame({"user": u.astype(np.uint32), "article": a.astype(np.int32), "t": t.astype(np.int32), "pub": pub[a].astype(np.int32)}) \
            .sort(["t", "user", "article"]).write_parquet(os.path.join(d, "part-00.parquet"))
    return root


def make_samples(root, name, days, n=5000):
    for d in days:
        sample.day_unit((root, name, d, n, sample.SEED))


def per_click(out, r, d):
    return pl.read_parquet(os.path.join(out, f"r={r}/d={d}/part.parquet"))


def mrr_gap(out, r, d, scorer, regime="A"):
    f = per_click(out, r, d).filter((pl.col("scorer") == scorer) & (pl.col("regime") == regime))
    c = per_click(out, str(dt.date.fromisoformat(d) - dt.timedelta(days=1)), d).filter((pl.col("scorer") == scorer) & (pl.col("regime") == regime))
    j = f.join(c, on=["user", "article", "t"], suffix="_c")
    x = (1.0 / j["rank_c"].to_numpy()) - (1.0 / j["rank"].to_numpy())
    return x.mean(), x.std() / np.sqrt(len(x)), len(x)


@unittest.skipUnless(ROOT, "needs the project root")
class Planted(unittest.TestCase):
    names = ["recency", "popularity", "word", "clickhist"]

    def test_planted_turnover_is_recovered(self):
        root = write_world("planted", True)
        make_samples(root, "planted", DAYS[2:])
        decay.run(root, DAYS[2:5], DAYS[-1], "res", 1, self.names, name="planted", window=12 * 3600)    # pool = the articles still being read
        out = os.path.join(root, "res")
        # one day after the fit, the planted share of clicks on articles the fit saw is ~25 % (see below)
        pc = per_click(out, DAYS[3], DAYS[4]).filter((pl.col("scorer") == "popularity") & (pl.col("regime") == "A"))
        s0 = float((pc["stratum"] == 0).mean())
        self.assertAlmostEqual(s0, 0.25, delta=0.05)          # the continuous-time value; re-reads (left out) shift it a little
        # independent recomputation from the raw synthetic clicks: drop re-reads, share of articles published before the fit end
        raw = pl.concat([pl.read_parquet(f) for f in sorted(glob.glob(os.path.join(root, "data/planted/store/clicks_by_day/*/*.parquet")))])
        smp = pl.read_parquet(os.path.join(root, f"data/planted/store/sample/clicks_d={DAYS[4]}.parquet")).select("user", "article", "t", "pub")
        first = raw.group_by("user", "article").agg(pl.col("t").min().alias("t0"))
        smp = smp.join(first, on=["user", "article"], how="left").filter(pl.col("t") <= pl.col("t0"))      # not clicked before
        r_end = day_start(DAYS[3]) + 86400
        self.assertAlmostEqual(float((smp["pub"] < r_end).mean()), s0, places=9)
        self.assertAlmostEqual(float(pc["scorable"].mean()), s0, delta=0.02)      # popularity can score exactly the seen articles
        # two or more days after the fit nothing clicked is in the fit window: no seen clicks, nothing scorable
        pc2 = per_click(out, DAYS[2], DAYS[5]).filter((pl.col("scorer").is_in(["popularity", "clickhist"])))
        self.assertEqual(int((pc2["stratum"] == 0).sum()), 0)
        self.assertEqual(int(pc2["scorable"].sum()), 0)
        # recency does not decay at all
        self.assertEqual(mrr_gap(out, DAYS[3], DAYS[5], "recency")[0], 0.0)
        # click history decays: frozen two days back vs rebuilt yesterday, a gap clearly above zero
        g, se, n = mrr_gap(out, DAYS[2], DAYS[4], "clickhist")
        print(f"\nplanted turnover: seen share one day after the fit {100 * s0:.1f} % (planted 25), click-history gap {g:.4f} +- {1.96 * se:.4f} (n={n})")
        self.assertGreater(g - 3 * se, 0)
        shutil.rmtree(root)

    def test_zero_turnover_gives_zero_decay(self):
        root = write_world("zero", False)
        old = sample.WINDOW_H
        sample.WINDOW_H = 10 ** 6                       # all articles are old; the 72 h eligibility rule must not apply here
        try:
            make_samples(root, "zero", DAYS[2:])
        finally:
            sample.WINDOW_H = old
        decay.run(root, DAYS[2:7], DAYS[-1], "res", 1, self.names, name="zero", window=10 ** 9)
        out = os.path.join(root, "res")
        worst = 0.0
        for r, d in ((DAYS[2], DAYS[4]), (DAYS[2], DAYS[5]), (DAYS[3], DAYS[5]), (DAYS[2], DAYS[6])):
            for sc in self.names:
                for regime in ("A", "B"):
                    g, se, n = mrr_gap(out, r, d, sc, regime)
                    worst = max(worst, abs(g) / max(se, 1e-9))
                    self.assertLess(abs(g), 3.5 * max(se, 1e-9) + 1e-12, (r, d, sc, regime, g, se))
        print(f"\nzero turnover: largest |gap| over its standard error, all scorers and lags: {worst:.2f}")
        shutil.rmtree(root)


if __name__ == "__main__":
    if ROOT:
        os.makedirs(SCR, exist_ok=True)
    sys.argv = [sys.argv[0]]
    try:
        unittest.main(verbosity=2, exit=False)
    finally:
        if SCR:
            shutil.rmtree(SCR, ignore_errors=True)
