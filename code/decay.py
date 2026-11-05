"""T6: the decay matrix. Unit = one fit date r: fit every scorer once on the 7-day window ending on r, then score the
sampled clicks of every later evaluation day d in both regimes (A frozen profiles, B live profiles).
Each cell writes <out>/r=R/d=D/part.parquet (long format: regime, scorer, user, article, t, rank, scorable, stratum,
pool) and the unit appends one manifest line with the shard hashes, seconds and peak memory.
Run:  python decay.py <root> --fits 2023-05-10 2023-05-23 --last 2023-05-24 [--workers 2] [--out results/decay_matrix]
"""
import argparse, datetime as dt, glob, multiprocessing as mp, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import polars as pl

import monitor as M
from cell import fit_all, score_cell, load_sample
from core import Corpus, WINDOW
from scorers import Recency, Popularity, Meaning, BM25, CoClick

ALL = {"recency": Recency, "popularity": Popularity, "meaning": Meaning, "word": BM25, "clickhist": CoClick}
CAP_GB = 8.0


def days_between(a, b):
    a, b = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    return [str(a + dt.timedelta(days=i)) for i in range((b - a).days + 1)]


def shard(out, d):
    """long-format frame of one cell, sorted so the bytes depend on the data only."""
    parts = []
    for regime, res in out.items():
        n = res["n"]
        for name, s in res["scorers"].items():
            parts.append(pl.DataFrame({
                "regime": [regime] * n, "scorer": [name] * n, "user": res["user"], "article": res["article"], "t": res["t"],
                "rank": s["rank"].astype(np.int32), "scorable": s["scorable"], "stratum": res["stratum"], "pool": res["pool"].astype(np.int32)}))
    return pl.concat(parts).sort(["regime", "scorer", "user", "article", "t"])


def fit_unit(args):
    root, r, last, out_dir, names, manifest, name, window, clicked_only = args
    corpus = Corpus(root, name, load_text=True, clicked_only=clicked_only)
    scorers = [ALL[n]() for n in names]
    days = days_between(str(dt.date.fromisoformat(r) + dt.timedelta(days=1)), last)
    cells = []
    with M.Unit("t6", f"r={r}", trace_dir=os.path.join(root, out_dir, "trace"), rss_cap_gb=CAP_GB, disk_dir=root) as u:
        with u.phase("fit"):
            fitted, r_end, nwin = fit_all(corpus, r, scorers)
        for d in days:
            clicks, prof = load_sample(corpus, d)
            with u.phase("score"):
                res = {}
                for regime in ("A", "B"):
                    x = score_cell(corpus, fitted, r_end, d, regime, scorers, clicks, prof, window)
                    res[regime] = x
            u.check()
            df = shard(res, d)
            M.check_finite(df["rank"].to_numpy().astype(np.float64), "rank")
            assert df["rank"].min() >= 1 and (df["rank"] <= df["pool"]).all(), "rank outside 1..pool"
            p = os.path.join(root, out_dir, f"r={r}", f"d={d}")
            os.makedirs(p, exist_ok=True)
            f = os.path.join(p, "part.parquet")
            M.atomic_write(f, lambda q, df=df: df.write_parquet(q, compression="zstd"))
            cells.append({"d": d, "rows": df.height, "sha256": M.file_sha256(f), "n_in_pool": res["A"]["n"], "n_excluded": res["A"]["n_excluded"], "n_reread": res["A"]["n_reread"]})
        u.extra.update(window_clicks=nwin, cells=cells, scorers=names,
                       fit_seconds={k: round(v[1], 3) for k, v in fitted.items()})
    M.append_manifest(os.path.join(root, out_dir, "manifest.jsonl"), u.row)
    return r


def run(root, fits, last, out_dir="results/decay_matrix", workers=2, names=None, order=None, name="ebnerd", window=WINDOW, clicked_only=False):
    names = names or list(ALL)
    os.makedirs(os.path.join(root, out_dir), exist_ok=True)
    mf = os.path.join(root, out_dir, "manifest.jsonl")
    for f in glob.glob(os.path.join(root, out_dir, "**", "*.tmp"), recursive=True):
        os.remove(f)
    done = {r["unit"] for r in M.read_manifest(mf)}
    todo = [f for f in fits if f"r={f}" not in done]
    if order:
        todo = [todo[i] for i in order]
    jobs = [(root, r, last, out_dir, names, mf, name, window, clicked_only) for r in todo]
    with mp.get_context("spawn").Pool(min(workers, len(jobs) or 1)) as pool:
        for r in pool.imap_unordered(fit_unit, jobs):
            print("done fit", r, flush=True)
    return todo


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--fits", nargs=2, required=True); ap.add_argument("--last", required=True)
    ap.add_argument("--workers", type=int, default=2); ap.add_argument("--out", default="results/decay_matrix")
    ap.add_argument("--scorers", default=None); ap.add_argument("--name", default="ebnerd"); ap.add_argument("--window-h", type=int, default=48); ap.add_argument("--clicked-only", action="store_true")
    a = ap.parse_args()
    run(a.root, days_between(*a.fits), a.last, a.out, a.workers, a.scorers.split(",") if a.scorers else None, name=a.name, window=a.window_h * 3600, clicked_only=a.clicked_only)
