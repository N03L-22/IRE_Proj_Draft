"""What the reader sees (stage S6): for each scorer, regime and lag, the age of the articles it would show, from the per-click top-10 statistics that qrun.py --topk wrote
(age of the top article, median age of the top 10, share of the top 10 older than 24 h, share of the top 10 published after the fit, median age of the whole pool, for reference).
Days enter with equal weight; intervals resample clicks with one shared count matrix per day (analyze.counts). Writes results/s6_topk_analysis/topk_by_lag.csv (atomic).
Run:  python topk_analyze.py <root> [--src results/s6_topk] [--B 1000]
"""
import argparse, csv, datetime as dt, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import polars as pl

import monitor as M
from analyze import counts

COLS = ["age1_h", "med10_h", "over24", "new10", "poolmed_h"]


def main(root, src, B):
    mf = M.read_manifest(os.path.join(root, src, "manifest.jsonl"))
    fits = sorted(r["unit"].split("=")[1] for r in mf)
    all_days = sorted({c["d"] for r in mf for c in r["cells"]})
    acc = {}
    for di, d in enumerate(all_days):
        W, n0 = None, None
        for r in fits:
            f = os.path.join(root, src, f"r={r}", f"d={d}", "part_topk.parquet")
            if not os.path.exists(f):
                continue
            lag = (dt.date.fromisoformat(d) - dt.date.fromisoformat(r)).days
            x = pl.read_parquet(f)
            for (regime, scorer), g in x.partition_by(["regime", "scorer"], as_dict=True).items():
                n = g.height
                if W is None:
                    W, n0 = counts(di, n, B), n
                assert n == n0, "cells of a day differ in size"
                for c in COLS:
                    v = g[c].to_numpy().astype(np.float64)
                    ok = ~np.isnan(v)
                    acc.setdefault((scorer, regime, lag, c), []).append((float(v[ok].mean()), (W @ np.where(ok, v, 0)) / np.maximum(W @ ok.astype(np.float64), 1), n))
    rows = []
    for (scorer, regime, lag, c), v in sorted(acc.items()):
        lo, hi = np.percentile(np.mean([a[1] for a in v], axis=0), [2.5, 97.5])
        rows.append([scorer, regime, lag, c, len(v), sum(a[2] for a in v), round(float(np.mean([a[0] for a in v])), 4), round(float(lo), 4), round(float(hi), 4)])
    out = os.path.join(root, "results/s6_topk_analysis")
    os.makedirs(out, exist_ok=True)
    tmp = os.path.join(out, "topk_by_lag.csv.tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["scorer", "regime", "lag_days", "quantity", "cells", "n_clicks", "value", "lo", "hi"]); w.writerows(rows)
    os.replace(tmp, os.path.join(out, "topk_by_lag.csv"))
    print(len(rows), "rows")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--src", default="results/s6_topk"); ap.add_argument("--B", type=int, default=1000)
    a = ap.parse_args()
    main(os.path.abspath(a.root), a.src, a.B)
