"""Genre extension: paired differences between two scorers on the SAME clicks, per lag, with bootstrap intervals.
For each evaluation day the clicks are fixed, so scorer X (fit r) and scorer Y (same fit r) are scored on identical clicks; one resample-count
matrix per day (analyze.counts, seeded by the day index) is shared by every pair, and days enter a lag's average with equal weight, exactly as in
analyze.py. Writes <out>/genre_vs_baselines.csv: pair, regime, metric, lag, cells, n_clicks, mean of X, mean of Y, X - Y with its interval.
Run:  python genre_compare.py <root> [--src results/genre] [--out results/genre_analysis] [--B 1000]
"""
import argparse, csv, datetime as dt, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import monitor as M
from analyze import counts, load_day

PAIRS = [("fuse_genre", "recency"), ("fuse_wmrg", "fuse_recency"), ("fuse_wmrg", "recency"), ("genre", "shuffle")]
LAGS = (1, 3, 7, 13)
METRICS = ["mrr", "recall10"]


def run(root, src, out, B, pairs=None, fname="genre_vs_baselines.csv"):
    pairs = pairs or PAIRS
    manifest = M.read_manifest(os.path.join(root, src, "manifest.jsonl"))
    fits = sorted(r["unit"].split("=")[1] for r in manifest)
    all_days = sorted({c["d"] for r in manifest for c in r["cells"]})
    acc = {}
    for di, d in enumerate(all_days):
        cols, pool, key = load_day(os.path.join(root, src), d, fits)
        n = len(pool)
        W = counts(di, n, B)
        for r in fits:
            lag = (dt.date.fromisoformat(d) - dt.date.fromisoformat(r)).days
            if lag not in LAGS:
                continue
            for regime in ("A", "B"):
                for x, y in pairs:
                    cx, cy = cols.get((r, x, regime)), cols.get((r, y, regime))
                    if cx is None or cy is None:
                        continue
                    for m in METRICS:
                        v = cx[m] - cy[m]
                        acc.setdefault((x, y, regime, m, lag), []).append((cx[m].mean(), cy[m].mean(), v.mean(), W @ v / n, n))
    rows = []
    for (x, y, regime, m, lag), v in sorted(acc.items()):
        rep = np.mean([a[3] for a in v], axis=0)
        lo, hi = np.percentile(rep, [2.5, 97.5])
        rows.append([f"{x} - {y}", regime, m, lag, len(v), sum(a[4] for a in v), round(float(np.mean([a[0] for a in v])), 6),
                     round(float(np.mean([a[1] for a in v])), 6), round(float(np.mean([a[2] for a in v])), 6), round(float(lo), 6), round(float(hi), 6)])
    os.makedirs(os.path.join(root, out), exist_ok=True)
    with open(os.path.join(root, out, fname), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pair", "regime", "metric", "lag_days", "cells", "n_clicks", "mean_x", "mean_y", "diff", "diff_lo", "diff_hi"])
        w.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--src", default="results/genre"); ap.add_argument("--out", default="results/genre_analysis")
    ap.add_argument("--B", type=int, default=1000); ap.add_argument("--pairs", default=None, help="x-y,x-y"); ap.add_argument("--file", default="genre_vs_baselines.csv")
    a = ap.parse_args()
    print(run(a.root, a.src, a.out, a.B, [tuple(p.split("-")) for p in a.pairs.split(",")] if a.pairs else None, a.file))
