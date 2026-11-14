"""Reads a grid written by ablate.py: the decay analysis of analyze.py for every variant (decay_by_lag.csv, ...), and the paired differences of each drop-one hybrid against the
full hybrid on the same clicks: MRR level and decay (control minus frozen), per regime and lag, with the same shared-resample bootstrap (one count matrix per day, days equal weight).
A negative level difference means the dropped signal was helping; a positive decay difference means the hybrid without it loses more by waiting.
Writes <out>/decay_by_lag.csv (and the other analyze.py tables) and <out>/ablation_vs_full.csv.
Run:  python ablate_analyze.py <root> --src results/s18_ablation --out results/s18_ablation_analysis [--B 1000]
"""
import argparse, csv, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import analyze

FULL = "abl_full"
VARIANTS = ["abl_no_word", "abl_no_meaning", "abl_no_click", "abl_no_recency"]


def pair_rows(acc, metric):
    """acc[(lag, scorer, regime, metric)] = list over days of (decay, decay replicates, level, level replicates, n)."""
    rows = []
    for (lag, scorer, regime, m), full in sorted(acc.items()):
        if scorer != FULL or m != metric:
            continue
        for var in VARIANTS:
            v = acc.get((lag, var, regime, m))
            if v is None or len(v) != len(full):
                continue
            f_dec, v_dec = np.mean([x[0] for x in full]), np.mean([x[0] for x in v])
            f_lvl, v_lvl = np.mean([x[2] for x in full]), np.mean([x[2] for x in v])
            dec_rep = np.mean([x[1] for x in v], axis=0) - np.mean([x[1] for x in full], axis=0)
            lvl_rep = np.mean([x[3] for x in v], axis=0) - np.mean([x[3] for x in full], axis=0)
            dl, dh = np.percentile(dec_rep, [2.5, 97.5])
            ll, lh = np.percentile(lvl_rep, [2.5, 97.5])
            rows.append([var, regime, metric, lag, len(full), sum(x[4] for x in full),
                         round(float(f_lvl), 6), round(float(v_lvl), 6), round(float(v_lvl - f_lvl), 6), round(float(ll), 6), round(float(lh), 6),
                         round(float(f_dec), 6), round(float(v_dec), 6), round(float(v_dec - f_dec), 6), round(float(dl), 6), round(float(dh), 6)])
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--src", required=True); ap.add_argument("--out", required=True); ap.add_argument("--B", type=int, default=1000)
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    acc = analyze.analyse(root, a.src, a.out, a.B)[6]
    hdr = ["variant", "regime", "metric", "lag_days", "cells", "n_clicks", "level_full", "level_variant", "level_diff", "level_diff_lo", "level_diff_hi",
           "decay_full", "decay_variant", "decay_diff", "decay_diff_lo", "decay_diff_hi"]
    rows = pair_rows(acc, "mrr")
    with open(os.path.join(root, a.out, "ablation_vs_full.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(hdr); w.writerows(rows)
    print(len(rows), "rows")
