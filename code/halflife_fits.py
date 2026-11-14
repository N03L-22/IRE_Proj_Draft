"""Time-scale summaries of the decay curves we already have (no new scoring): one number per curve, with an interval, read from the result CSVs.
  coverage_half_h    hours after the freeze until click-history coverage falls to half its value at 1 h (the point curve and its lower and upper interval curves,
                     linear interpolation between hourly points)
  unseen_50pct_h     hours until half of the next clicks go to articles published after the freeze (per dataset, same method)
  loss_pct_lag7/13   MRR lost with a frozen profile as a share of the lag-1 level, with the interval of the loss
  days_to_5pct       lags until the loss reaches 5% of the lag-1 level (point and interval curves; '>13' if it does not within the grid)
Writes results/halflife/fits.csv (atomic).
Run:  python halflife_fits.py <root>
"""
import csv, os, sys

import numpy as np


def cross(x, y, level, falling=True):
    """first x where the curve y crosses level (linear interpolation); NaN if it never does."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    for i in range(1, len(x)):
        a, b = y[i - 1], y[i]
        if (falling and a > level >= b) or (not falling and a < level <= b):
            return float(x[i - 1] + (a - level) / (a - b) * (x[i] - x[i - 1]))
    return float("nan")


def read(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def main(root):
    res = os.path.join(root, "results")
    rows = []
    # coverage half-time, click history, frozen profile, EB-NeRD hourly
    h = sorted([x for x in read(f"{res}/rq_hourly/decay_by_hour.csv") if x["scorer"] == "clickhist" and x["regime"] == "A" and x["metric"] == "mrr"], key=lambda x: int(x["hours_since_fit"]))
    hrs = [int(x["hours_since_fit"]) for x in h]
    pt, lo, hi = ([float(x[k]) for x in h] for k in ("coverage", "coverage_lo", "coverage_hi"))
    half = 0.5 * pt[0]
    rows.append(["coverage_half_h", "click history, EB-NeRD", round(cross(hrs, pt, half), 2), round(cross(hrs, lo, 0.5 * lo[0]), 2), round(cross(hrs, hi, 0.5 * hi[0]), 2),
                 "hours until coverage is half of its 1 h value; 40 cells per hour offset"])
    # unseen share, 50 %
    u = read(f"{res}/rq0/unseen_share_by_hour.csv")
    for ds in ("EB-NeRD", "Adressa", "NPR"):
        d = sorted([x for x in u if x["dataset"] == ds], key=lambda x: int(x["hours_since_fit"]))
        hh = [int(x["hours_since_fit"]) for x in d]
        p = cross(hh, [float(x["share"]) for x in d], 0.5, falling=False)
        a = cross(hh, [float(x["ci_hi"]) for x in d], 0.5, falling=False)       # the upper curve crosses earlier
        b = cross(hh, [float(x["ci_lo"]) for x in d], 0.5, falling=False)
        rows.append(["unseen_50pct_h", ds, round(p, 2), round(a, 2), round(b, 2), f"hours until half of the next clicks go to articles newer than the freeze; fit days {d[0]['n_fit_days']}"])
    # daily decay as a share of the lag-1 level, frozen profile
    series = [("word", "word matching", f"{res}/rq1_rq2/decay_by_lag.csv"), ("meaning", "meaning matching", f"{res}/rq1_rq2/decay_by_lag.csv"),
              ("genre", "genre alone", f"{res}/genre_analysis/rq1_rq2/decay_by_lag.csv"), ("fuse_genre", "recency + genre", f"{res}/genre_analysis/rq1_rq2/decay_by_lag.csv")]
    for key, label, path in series:
        r = sorted([x for x in read(path) if x["scorer"] == key and x["regime"] == "A" and x["metric"] == "mrr" and int(x["lag_days"]) <= 13], key=lambda x: int(x["lag_days"]))
        lag = [int(x["lag_days"]) for x in r]
        lvl1 = float(r[0]["level"])
        dp, dl, dh = ([float(x[k]) / lvl1 for x in r] for k in ("decay", "decay_lo", "decay_hi"))
        n = {int(x["lag_days"]): x["n_clicks"] for x in r}
        for L in (7, 13):
            i = lag.index(L)
            rows.append([f"loss_pct_lag{L}", f"{label}, frozen profile, EB-NeRD", round(100 * dp[i], 2), round(100 * dl[i], 2), round(100 * dh[i], 2), f"share of the lag-1 MRR level {lvl1:.4f}; n = {n[L]} clicks"])
        t = [cross(lag, c, 0.05) if True else 0 for c in (dp, dh, dl)]            # rising loss: use falling=False below
        t = [cross(lag, c, 0.05, falling=False) for c in (dp, dh, dl)]
        rows.append(["days_to_5pct", f"{label}, frozen profile, EB-NeRD", *[(round(v, 2) if v == v else ">13") for v in t], "lag at which the loss reaches 5% of the lag-1 level; '>13' = not within the grid"])
    out = os.path.join(res, "halflife")
    os.makedirs(out, exist_ok=True)
    tmp = os.path.join(out, "fits.csv.tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["quantity", "series", "value", "lo", "hi", "method"]); w.writerows(rows)
    os.replace(tmp, os.path.join(out, "fits.csv"))
    for r in rows:
        print(r[:5])


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
