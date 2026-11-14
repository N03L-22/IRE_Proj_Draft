"""Is the decay an artefact of the metric? The same frozen-profile loss at lags 7 and 13, read in all four metrics (MRR, top-10 hit rate, AUC, nDCG@5), as a share of
the lag-1 level, with the interval of the loss. Read from results/rq1_rq2/decay_by_lag.csv and results/genre_analysis/rq1_rq2/decay_by_lag.csv; nothing is recomputed.
Writes results/metric_robustness/decay_by_metric.csv (atomic).   Run:  python metric_robustness.py <root>
"""
import csv, os, sys


def main(root):
    rows = []
    for path in ("results/rq1_rq2/decay_by_lag.csv", "results/genre_analysis/rq1_rq2/decay_by_lag.csv"):
        r = list(csv.DictReader(open(os.path.join(root, path))))
        for sc in ("word", "meaning", "genre", "fuse_genre"):
            for m in ("mrr", "recall10", "auc", "ndcg5"):
                x = {int(a["lag_days"]): a for a in r if a["scorer"] == sc and a["regime"] == "A" and a["metric"] == m}
                if 1 not in x:
                    continue
                l1 = float(x[1]["level"])
                for L in (7, 13):
                    a = x[L]
                    rows.append([sc, m, L, a["n_clicks"], round(l1, 5), round(float(a["decay"]), 6), round(float(a["decay_lo"]), 6), round(float(a["decay_hi"]), 6),
                                 round(100 * float(a["decay"]) / l1, 2), round(100 * float(a["decay_lo"]) / l1, 2), round(100 * float(a["decay_hi"]) / l1, 2)])
    out = os.path.join(root, "results/metric_robustness")
    os.makedirs(out, exist_ok=True)
    tmp = os.path.join(out, "decay_by_metric.csv.tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scorer", "metric", "lag_days", "n_clicks", "level_lag1", "loss", "loss_lo", "loss_hi", "loss_pct_of_lag1", "pct_lo", "pct_hi"])
        w.writerows(rows)
    os.replace(tmp, os.path.join(out, "decay_by_metric.csv"))
    for r in rows:
        if r[2] == 7:
            print(r[0].ljust(11), r[1].ljust(9), "lag 7: %.1f%% [%.1f, %.1f]" % (r[8], r[9], r[10]))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
