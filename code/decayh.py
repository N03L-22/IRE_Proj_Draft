"""T6h: the hourly fast axis. Unit = one clock hour b: fit every scorer on the 7 days of clicks before b, then score the sampled
clicks of hour buckets. Hour b is a *frozen fit* when it is one of the fit times (every 3 h of the block): its model scores the
buckets b, b+1 h, ... b+23 h (offset 1..24 hours since the fit). Every hour is also the *control* of its own bucket: the model
fitted at the start of an hour scores that hour (offset 1), so the control of (fit r, offset h) is the offset-1 cell of unit r+(h-1) h.
Writes <out>/r=<fit time>/h=<offset>/part.parquet (same long format as T6) and one manifest line per unit.
Run:  python decayh.py <root> --first 2023-05-17 --last 2023-05-22 --fit-days 2023-05-17 2023-05-21 [--step 3] [--workers 2]
"""
import argparse, datetime as dt, glob, multiprocessing as mp, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import polars as pl

import monitor as M
from cell import score_cell
from core import Corpus
from decay import ALL, shard, CAP_GB
from scorers import Recency

H = 3600


def ts(day, hour=0):
    return int(dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp()) + hour * H


def window_clicks_t(corpus, b, days=7):
    lo, hi = b - days * 86400, b
    d0 = str(dt.datetime.fromtimestamp(lo, dt.timezone.utc).date())
    d1 = str(dt.datetime.fromtimestamp(hi - 1, dt.timezone.utc).date())
    files = [f for d in sorted(glob.glob(os.path.join(corpus.st, "clicks_by_day", "day=*"))) if d0 <= d.split("=")[1] <= d1
             for f in glob.glob(os.path.join(d, "*.parquet"))]
    return (pl.scan_parquet(files).filter((pl.col("t") >= lo) & (pl.col("t") < hi)).select("user", "article")
            .collect(engine="streaming"))


def load_day(corpus, day):
    s = os.path.join(corpus.st, "sample_h")
    return (pl.read_parquet(os.path.join(s, f"clicks_d={day}.parquet")), pl.read_parquet(os.path.join(s, f"profiles_d={day}.parquet")))


def unit(args):
    root, b, frozen, out_dir, names, manifest, first_b, last_b = args
    corpus = Corpus(root, "ebnerd", load_text=True)
    scorers = [ALL[n]() for n in names]
    tag = dt.datetime.fromtimestamp(b, dt.timezone.utc).strftime("%Y-%m-%dT%H")
    offsets = range(1, 25) if frozen else [1]
    cells, cache = [], {}
    with M.Unit("t6h", f"r={tag}", trace_dir=os.path.join(root, out_dir, "trace"), rss_cap_gb=CAP_GB, disk_dir=root) as u:
        with u.phase("fit"):
            win = window_clicks_t(corpus, b)
            fitted = {}
            for s in scorers:
                import time
                t0 = time.perf_counter()
                fitted[s.name] = (s.fit(corpus, win_user=win["user"].to_numpy(), win_article=win["article"].to_numpy().astype(np.int64), r_end_t=b),
                                  time.perf_counter() - t0)
            nwin = win.height
            del win
        for h in offsets:
            s0 = b + (h - 1) * H
            if s0 > last_b:
                break
            day = str(dt.datetime.fromtimestamp(s0, dt.timezone.utc).date())
            if day not in cache:
                cache = {day: load_day(corpus, day)}
            clicks, prof = cache[day]
            m = ((clicks["t"] >= s0) & (clicks["t"] < s0 + H)).to_numpy()
            clicks = clicks.filter(pl.Series(m))
            with u.phase("score"):
                res = {rg: score_cell(corpus, fitted, b, None, rg, scorers, clicks, prof, d_start=s0) for rg in ("A", "B")}
            u.check()
            df = shard(res, None)
            M.check_finite(df["rank"].to_numpy().astype(np.float64), "rank")
            assert df["rank"].min() >= 1 and (df["rank"] <= df["pool"]).all(), "rank outside 1..pool"
            p = os.path.join(root, out_dir, f"r={tag}", f"h={h:02d}")
            os.makedirs(p, exist_ok=True)
            f = os.path.join(p, "part.parquet")
            M.atomic_write(f, lambda q, df=df: df.write_parquet(q, compression="zstd"))
            cells.append({"h": h, "rows": df.height, "sha256": M.file_sha256(f), "n_in_pool": res["A"]["n"], "n_excluded": res["A"]["n_excluded"], "n_reread": res["A"]["n_reread"]})
        u.extra.update(window_clicks=nwin, cells=cells, frozen=bool(frozen), scorers=names,
                       fit_seconds={k: round(v[1], 3) for k, v in fitted.items()})
    M.append_manifest(os.path.join(root, out_dir, "manifest.jsonl"), u.row)
    return tag


def run(root, first, last, fit_days, step=3, out_dir="results/decay_hourly", workers=2, names=None):
    names = names or list(ALL)
    os.makedirs(os.path.join(root, out_dir), exist_ok=True)
    mf = os.path.join(root, out_dir, "manifest.jsonl")
    for f in glob.glob(os.path.join(root, out_dir, "**", "*.tmp"), recursive=True):
        os.remove(f)
    done = {r["unit"] for r in M.read_manifest(mf)}
    f0, f1 = ts(fit_days[0]), ts(fit_days[1]) + 23 * H
    first_b, last_b = ts(first), ts(last) + 23 * H
    jobs = []
    for b in range(first_b, last_b + H, H):
        tag = dt.datetime.fromtimestamp(b, dt.timezone.utc).strftime("%Y-%m-%dT%H")
        if f"r={tag}" in done:
            continue
        frozen = f0 <= b <= f1 and ((b - f0) // H) % step == 0
        jobs.append((root, b, frozen, out_dir, names, mf, first_b, last_b))
    jobs.sort(key=lambda j: (not j[2], j[1]))          # the long (frozen) units first, so the workers finish together
    with mp.get_context("spawn").Pool(workers) as pool:
        for tag in pool.imap_unordered(unit, jobs):
            print("done", tag, flush=True)
    return len(jobs)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--first", required=True); ap.add_argument("--last", required=True)
    ap.add_argument("--fit-days", nargs=2, required=True); ap.add_argument("--step", type=int, default=3)
    ap.add_argument("--workers", type=int, default=2); ap.add_argument("--out", default="results/decay_hourly")
    ap.add_argument("--scorers", default=None)
    a = ap.parse_args()
    print(run(a.root, a.first, a.last, a.fit_days, a.step, a.out, a.workers, a.scorers.split(",") if a.scorers else None))
