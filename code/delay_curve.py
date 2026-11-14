"""How fast does a live click signal go stale (stage S7b)? MRR and top-10 hit rate of the trending baselines against recency, 14 evaluation days (trending is not fitted, so one fit
date, 10 May, covers every day): windows of 10 min, 30 min, 1 h, and the 1 h window ending 5, 15, 30, 60, 180, 360 minutes BEFORE the click. Paired on the same clicks, one shared count
matrix per day (analyze.counts), days with equal weight. Writes results/s7b_trend_delay/analysis.csv (atomic).   Run:  python delay_curve.py <root> [--B 1000]
"""
import argparse, csv, datetime as dt, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from analyze import counts, load_day

FIT = "2023-05-10"
DAYS = [str(dt.date(2023, 5, 11) + dt.timedelta(days=i)) for i in range(14)]


def main(root, B):
    src = os.path.join(root, "results/s7b_trend_delay")
    acc = {}
    for di, d in enumerate(DAYS):
        cols, pool, key = load_day(src, d, [FIT])
        n = len(pool)
        W = counts(di, n, B)
        names = sorted({s for (_, s, rg) in cols if rg == "B"})
        for s in names:
            for m in ("mrr", "recall10"):
                x, y = cols[(FIT, s, "B")][m], cols[(FIT, "recency", "B")][m]
                for tag, v in (("level", x), ("minus recency", x - y)):
                    acc.setdefault((s, m, tag), []).append((float(v.mean()), W @ v / n, n))
    rows = []
    for (s, m, tag), v in sorted(acc.items()):
        lo, hi = np.percentile(np.mean([a[1] for a in v], axis=0), [2.5, 97.5])
        rows.append([s, m, tag, len(v), sum(a[2] for a in v), round(float(np.mean([a[0] for a in v])), 6), round(float(lo), 6), round(float(hi), 6)])
    tmp = os.path.join(src, "analysis.csv.tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["scorer", "metric", "quantity", "days", "n_clicks", "value", "lo", "hi"]); w.writerows(rows)
    os.replace(tmp, os.path.join(src, "analysis.csv"))
    for r in rows:
        if r[1] == "mrr" and r[2] == "minus recency":
            print(r[0].ljust(14), "%.4f [%.4f, %.4f]" % (r[5], r[6], r[7]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--B", type=int, default=1000)
    a = ap.parse_args()
    main(os.path.abspath(a.root), a.B)
