"""Live trending baseline (S7): MRR and top-10 hit rate of trend_h{1,3,6,12,24} against recency, per day and averaged over the 14 evaluation days.
Trending is not fitted, so every fit date gives the same ranks and one fit date (10 May) covers all days. Same bootstrap rules as analyze.py (one shared count
matrix per day, days equal weight). Also pairs trend_h3 with fuse_genre read from results/s2_perm (cell fit = day - 1, same clicks).
Writes results/s7_trend/analysis.csv.   Run:  python trend_compare.py <root> [--B 1000]
"""
import argparse, csv, datetime as dt, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from analyze import counts, load_day

FIT = "2023-05-10"
DAYS = [str(dt.date(2023, 5, 11) + dt.timedelta(days=i)) for i in range(14)]


def main(root, B):
    src = os.path.join(root, "results/s7_trend")
    s2 = os.path.join(root, "results/s2_perm")
    acc = {}
    trends = [f"trend_h{h}" for h in (1, 3, 6, 12, 24)]
    for di, d in enumerate(DAYS):
        cols, pool, key = load_day(src, d, [FIT])
        n = len(pool)
        W = counts(di, n, B)
        prev = str(dt.date.fromisoformat(d) - dt.timedelta(days=1))
        c2, _, k2 = load_day(s2, d, [prev])
        assert key.equals(k2), "click sets differ between S7 and S2"
        pairs = [(t, "recency", cols[(FIT, t, "B")], cols[(FIT, "recency", "B")]) for t in trends]
        pairs += [("trend_h3", "fuse_genre", cols[(FIT, "trend_h3", "B")], c2[(prev, "fuse_genre", "B")]), ("fuse_genre", "recency", c2[(prev, "fuse_genre", "B")], cols[(FIT, "recency", "B")])]
        for x, y, cx, cy in pairs:
            for m in ("mrr", "recall10"):
                v = cx[m] - cy[m]
                acc.setdefault((x, y, m), []).append((cx[m].mean(), cy[m].mean(), v.mean(), W @ v / n, n))
    rows = []
    for (x, y, m), v in sorted(acc.items()):
        lo, hi = np.percentile(np.mean([a[3] for a in v], axis=0), [2.5, 97.5])
        rows.append([f"{x} - {y}", m, len(v), sum(a[4] for a in v), *[round(float(np.mean([a[i] for a in v])), 6) for i in (0, 1, 2)], round(float(lo), 6), round(float(hi), 6)])
    tmp = os.path.join(src, "analysis.csv.tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["pair", "metric", "days", "n_clicks", "mean_x", "mean_y", "diff", "diff_lo", "diff_hi"]); w.writerows(rows)
    os.replace(tmp, os.path.join(src, "analysis.csv"))
    for r in rows:
        print(r)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--B", type=int, default=1000)
    a = ap.parse_args()
    main(os.path.abspath(a.root), a.B)
