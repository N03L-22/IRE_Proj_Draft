"""Real-impression evaluation, step 3: read the slate and pool grids (results/impr_slate*, results/impr_pool*), same bootstrap rules as analyze.py
(one shared count matrix per evaluation day, days with equal weight, clicks resampled inside a day).
There is no control rebuilt the day before (the click store ends 25 May 06:59), so staleness is read as: the freshest available model for each evaluation day is the fit of
2023-05-24; loss(k) = MRR(fit 24 May) - MRR(fit 24 May - k) on the same clicks of the same day, k = 1..7.
Writes results/impressions/{level_by_mode.csv, staleness_loss.csv, paired_comparisons.csv}; the last one marks completion.
Run:  python impr_analyze.py <root> [--B 1000]
"""
import argparse, csv, datetime as dt, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import monitor as M
from analyze import counts, load_day

FITS = [str(dt.date(2023, 5, 17) + dt.timedelta(days=i)) for i in range(8)]
DAYS = [str(dt.date(2023, 5, 25) + dt.timedelta(days=i)) for i in range(7)]
FRESH = "2023-05-24"
METRICS = ["mrr", "recall10", "auc", "ndcg5"]
MODES = {"slate": ["results/impr_slate", "results/impr_slate_click"], "pool": ["results/impr_pool", "results/impr_pool_click"]}
PAIRS = [("recency", "shuffle"), ("genre", "shuffle"), ("meaning", "shuffle"), ("word", "shuffle"), ("genre", "recency"), ("fuse_genre", "recency"), ("fuse_genre", "genre"),
         ("fuse_genre", "fuse_genre_prior"), ("genre", "genre_prior"), ("fuse_wmrg", "fuse_recency"), ("fuse_click_recency", "recency"), ("fuse_pop_recency", "recency")]


def load(root, mode, d):
    cols, key, pool = {}, None, None
    for src in MODES[mode]:
        p = os.path.join(root, src)
        if not os.path.isdir(p):
            continue
        c, pl_, k = load_day(p, d, FITS)
        for kk, v in c.items():
            cols.setdefault(kk, v)
        if key is None:
            key, pool = k, pl_
        else:
            assert key.equals(k), "click sets of the two sources differ"
    return cols, pool, key


def main(root, B):
    out = os.path.join(root, "results/impressions")
    lev, loss, pair = {}, {}, {}
    for mode in MODES:
        for di, d in enumerate(DAYS):
            cols, pool, key = load(root, mode, d)
            if not cols:
                continue
            n = len(pool)
            W = counts(di, n, B)
            for (r, scorer, regime), c in cols.items():
                if r != FRESH:
                    continue
                for m in METRICS:
                    lev.setdefault((mode, regime, scorer, m), []).append((c[m].mean(), W @ c[m] / n, n))
                    for r2 in FITS:
                        k = (dt.date.fromisoformat(FRESH) - dt.date.fromisoformat(r2)).days
                        c2 = cols.get((r2, scorer, regime))
                        if k >= 1 and c2 is not None and m in ("mrr", "auc"):
                            v = c[m] - c2[m]
                            loss.setdefault((mode, regime, scorer, m, k), []).append((v.mean(), W @ v / n, n))
            for regime in ("A", "B"):
                for x, y in PAIRS:
                    cx, cy = cols.get((FRESH, x, regime)), cols.get((FRESH, y, regime))
                    if cx is None or cy is None:
                        continue
                    for m in ("mrr", "auc"):
                        v = cx[m] - cy[m]
                        pair.setdefault((mode, regime, f"{x} - {y}", m), []).append((v.mean(), W @ v / n, n))
    def summarise(d, header, keyfmt, fname):
        rows = []
        for k, v in sorted(d.items()):
            rep = np.mean([a[1] for a in v], axis=0)
            lo, hi = np.percentile(rep, [2.5, 97.5])
            rows.append([*keyfmt(k), len(v), sum(a[2] for a in v), round(float(np.mean([a[0] for a in v])), 6), round(float(lo), 6), round(float(hi), 6)])
        tmp = os.path.join(out, fname + ".tmp")
        with open(tmp, "w", newline="") as f:
            w = csv.writer(f); w.writerow(header + ["days", "n_clicks", "value", "lo", "hi"]); w.writerows(rows)
        os.replace(tmp, os.path.join(out, fname))
    summarise(lev, ["mode", "regime", "scorer", "metric"], lambda k: list(k), "level_by_mode.csv")
    summarise(loss, ["mode", "regime", "scorer", "metric", "fit_older_by_days"], lambda k: list(k), "staleness_loss.csv")
    summarise(pair, ["mode", "regime", "pair", "metric"], lambda k: list(k), "paired_comparisons.csv")
    print(len(lev), len(loss), len(pair))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--B", type=int, default=1000)
    a = ap.parse_args()
    main(os.path.abspath(a.root), a.B)
