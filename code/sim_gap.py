"""Similarity of the clicked article against the other published articles in its pool, per lag (word and meaning scorers only).
Same grid as decay.py (unit = fit date r, evaluation days d > r, regimes A and B, same sampled clicks); score_cell(stats=True)
adds the clicked article's raw score and the mean and spread of the other scorable pool articles' scores.
Writes <out>/r=R/d=D/part.parquet and one manifest line per unit.
Run:  python sim_gap.py <root> --fits 2023-05-10 2023-05-23 --last 2023-05-24 [--workers 4] [--out results/sim_gap]
"""
import argparse, glob, multiprocessing as mp, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import polars as pl

import monitor as M
from cell import fit_all, score_cell, load_sample
from core import Corpus, WINDOW
from decay import ALL, CAP_GB, days_between

NAMES = ["meaning", "word"]


def shard(out):
    parts = []
    for regime, res in out.items():
        n = res["n"]
        for name in NAMES:
            s = res["scorers"][name]
            parts.append(pl.DataFrame({
                "regime": [regime] * n, "scorer": [name] * n, "user": res["user"], "article": res["article"], "t": res["t"],
                "stratum": res["stratum"], "pool": res["pool"].astype(np.int32), "scorable": s["scorable"],
                "tgt": s["tgt"], "pool_mean": s["pool_mean"], "pool_sd": s["pool_sd"], "k": s["k"].astype(np.int32)}))
    return pl.concat(parts).sort(["regime", "scorer", "user", "article", "t"])


def fit_unit(args):
    root, r, last, out_dir, manifest = args
    corpus = Corpus(root, "ebnerd", load_text=True)
    scorers = [ALL[n]() for n in NAMES]
    days = days_between(str((np.datetime64(r) + 1).astype(str)), last)
    cells = []
    with M.Unit("sim_gap", f"r={r}", trace_dir=os.path.join(root, out_dir, "trace"), rss_cap_gb=CAP_GB, disk_dir=root) as u:
        with u.phase("fit"):
            fitted, r_end, nwin = fit_all(corpus, r, scorers)
        for d in days:
            clicks, prof = load_sample(corpus, d)
            with u.phase("score"):
                res = {rg: score_cell(corpus, fitted, r_end, d, rg, scorers, clicks, prof, WINDOW, stats=True) for rg in ("A", "B")}
            u.check()
            df = shard(res)
            p = os.path.join(root, out_dir, f"r={r}", f"d={d}")
            os.makedirs(p, exist_ok=True)
            f = os.path.join(p, "part.parquet")
            M.atomic_write(f, lambda q, df=df: df.write_parquet(q, compression="zstd"))
            cells.append({"d": d, "rows": df.height, "sha256": M.file_sha256(f), "n_in_pool": res["A"]["n"]})
        u.extra.update(window_clicks=nwin, cells=cells, scorers=NAMES)
    M.append_manifest(manifest, u.row)
    return r


def run(root, fits, last, out_dir="results/sim_gap", workers=4):
    os.makedirs(os.path.join(root, out_dir), exist_ok=True)
    mf = os.path.join(root, out_dir, "manifest.jsonl")
    for f in glob.glob(os.path.join(root, out_dir, "**", "*.tmp"), recursive=True):
        os.remove(f)
    done = {r["unit"] for r in M.read_manifest(mf)}
    jobs = [(root, r, last, out_dir, mf) for r in fits if f"r={r}" not in done]
    with mp.get_context("spawn").Pool(min(workers, len(jobs) or 1)) as pool:
        for r in pool.imap_unordered(fit_unit, jobs):
            print("done fit", r, flush=True)
    return len(jobs)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--fits", nargs=2, required=True); ap.add_argument("--last", required=True)
    ap.add_argument("--workers", type=int, default=4); ap.add_argument("--out", default="results/sim_gap")
    a = ap.parse_args()
    print(run(a.root, days_between(*a.fits), a.last, a.out, a.workers))
