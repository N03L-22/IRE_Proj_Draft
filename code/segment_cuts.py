"""Does decay differ for different readers or times? Cuts of the existing decay matrix (results/decay_matrix), no new scoring.
Segments (the evaluation clicks of each day are labelled, then the cells are restricted to the segment):
  day type        weekday or weekend of the evaluation day
  click hour      UTC hour block of the click: 00-05, 06-11, 12-17, 18-23 (EB-NeRD times are assumed UTC)
  reader activity profile clicks before the click: under 10, 10-49, 50 or more (the profile slice is capped at 300)
  subscriber      is_subscriber of the reader in the validation impressions (a reader with no impression is "unknown")
Quantities, regime A: MRR at lag 1 (recency, word, meaning); decay at lags 3 and 7 for word and meaning (control rebuilt the day before minus frozen, same clicks);
coverage of click history at lag 1. Days enter with equal weight and the intervals resample clicks inside each day with one shared count matrix per day
(analyze.counts), exactly as analyze.py. Writes results/segments/decay_by_segment.csv (atomic).
Run:  python segment_cuts.py <root> [--B 1000]
"""
import argparse, csv, datetime as dt, glob, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import polars as pl

import monitor as M
from analyze import counts, load_day

DECAY_LAGS = (3, 7)


def labels(root, d, key):
    """one array per segment dimension, aligned with the key frame (user, article, t) of the day."""
    st = os.path.join(root, "data/ebnerd/store")
    t = key["t"].to_numpy().astype(np.int64)
    day = dt.date.fromisoformat(d)
    hour = (t % 86400) // 3600
    prof = pl.read_parquet(os.path.join(st, "sample", f"profiles_d={d}.parquet")).sort(["user", "t"])
    pu, pt = prof["user"].to_numpy(), prof["t"].to_numpy().astype(np.int64)
    uu, s0 = np.unique(pu, return_index=True)
    e0 = np.append(s0[1:], len(pu))
    where = {int(u): (int(a), int(b)) for u, a, b in zip(uu, s0, e0)}
    act = np.zeros(len(t), dtype=np.int64)
    for i, (u, ti) in enumerate(zip(key["user"].to_numpy(), t)):
        se = where.get(int(u))
        if se:
            act[i] = int(np.searchsorted(pt[se[0]:se[1]], ti, side="left"))
    return {
        "day type": np.where(np.full(len(t), day.weekday() >= 5), "weekend", "weekday"),
        "click hour (UTC)": np.select([hour < 6, hour < 12, hour < 18], ["00-05", "06-11", "12-17"], "18-23"),
        "reader activity": np.select([act < 10, act < 50], ["under 10 clicks", "10-49 clicks"], "50+ clicks"),
    }


def main(root, B):
    src = "results/decay_matrix"
    mf = M.read_manifest(os.path.join(root, src, "manifest.jsonl"))
    fits = sorted(r["unit"].split("=")[1] for r in mf)
    all_days = sorted({c["d"] for r in mf for c in r["cells"]})
    sub = (pl.scan_parquet(os.path.join(root, "data/ebnerd/large/validation/behaviors.parquet")).group_by("user_id").agg(pl.col("is_subscriber").max().alias("sub")).collect())
    submap = dict(zip(sub["user_id"].to_list(), sub["sub"].to_list()))
    acc = {}
    for di, d in enumerate(all_days):
        dd = dt.date.fromisoformat(d)
        need = {str(dd - dt.timedelta(days=L)) for L in (1, *DECAY_LAGS)}
        use = [r for r in fits if r in need]
        cols, pool, key = load_day(os.path.join(root, src), d, use)
        n = len(pool)
        lab = labels(root, d, key)
        lab["subscriber"] = np.array(["subscriber" if submap.get(int(u)) is True else ("not subscriber" if int(u) in submap else "unknown") for u in key["user"].to_numpy()])
        W = counts(di, n, B)
        ctrl = str(dd - dt.timedelta(days=1))
        for dim, arr in lab.items():
            for val in np.unique(arr):
                m = (arr == val).astype(np.float64)
                if m.sum() < 30:
                    continue
                den = W @ m
                def add(name, scorer, v, lagv):
                    rep = (W @ (v * m)) / np.maximum(den, 1)
                    acc.setdefault((dim, val, scorer, name, lagv), []).append((float((v * m).sum() / m.sum()), rep, int(m.sum())))
                for s in ("recency", "word", "meaning"):
                    c1 = cols.get((ctrl, s, "A"))
                    if c1 is not None:
                        add("MRR, lag 1", s, c1["mrr"], 1)
                    for L in DECAY_LAGS:
                        f = cols.get((str(dd - dt.timedelta(days=L)), s, "A"))
                        if f is not None and c1 is not None and s != "recency":
                            add(f"MRR lost, lag {L}", s, c1["mrr"] - f["mrr"], L)
                c1 = cols.get((ctrl, "clickhist", "A"))
                if c1 is not None:
                    add("coverage, lag 1", "clickhist", c1["scorable"], 1)
    rows = []
    for (dim, val, scorer, name, lagv), v in sorted(acc.items()):
        pt = np.mean([x[0] for x in v])
        lo, hi = np.percentile(np.mean([x[1] for x in v], axis=0), [2.5, 97.5])
        rows.append([dim, val, scorer, name, len(v), sum(x[2] for x in v), round(float(pt), 6), round(float(lo), 6), round(float(hi), 6)])
    out = os.path.join(root, "results/segments")
    os.makedirs(out, exist_ok=True)
    tmp = os.path.join(out, "decay_by_segment.csv.tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["dimension", "segment", "scorer", "quantity", "cells", "n_clicks", "value", "lo", "hi"]); w.writerows(rows)
    os.replace(tmp, os.path.join(out, "decay_by_segment.csv"))
    print(len(rows), "rows")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--B", type=int, default=1000)
    a = ap.parse_args()
    main(os.path.abspath(a.root), a.B)
