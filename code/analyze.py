"""T7 and T8: read the decay-matrix shards, write the decay curves with paired bootstrap intervals, the fresh-versus-decayed
split, and the rebuild-schedule replay.

Pairing: for each evaluation day d the clicks are the same for every fit date and scorer (the sample and the pool rule do not
depend on the fit), so one resample-count matrix per day (seeded by SeedSequence([SEED, day index])) is shared by every cell of
that day. A decay is mean(control) - mean(frozen) on the same resampled clicks. Days enter a lag's average with equal weight;
the intervals resample clicks inside each day (the days themselves are taken as given).
Run:  python analyze.py <root> [--src results/decay_matrix] [--out results/rq1_rq2] [--rq3 results/rq3] [--B 1000]
"""
import argparse, csv, datetime as dt, glob, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import polars as pl

import monitor as M
from core import metrics_from_ranks

SEED = 20261029
METRICS = ["mrr", "recall10", "auc", "ndcg5"]
KS = [1, 2, 3, 5, 7, 14]


def load_day(src, d, fits):
    """metric columns for every (fit date, scorer, regime) of evaluation day d; clicks in one fixed order."""
    cols, strata, pool, key = {}, None, None, None
    for r in fits:
        p = os.path.join(src, f"r={r}", f"d={d}", "part.parquet")
        if not os.path.exists(p):
            continue
        x = pl.read_parquet(p)
        for (regime, scorer), g in x.partition_by(["regime", "scorer"], as_dict=True).items():
            g = g.sort(["user", "article", "t"])
            k = g.select("user", "article", "t")
            if key is None:
                key = k
            assert key.equals(k), "the clicks of a day differ between cells"
            m = metrics_from_ranks(g["rank"].to_numpy(), g["pool"].to_numpy())
            cols[(r, scorer, regime)] = {**m, "scorable": g["scorable"].to_numpy().astype(np.float64), "stratum": g["stratum"].to_numpy()}
            pool = g["pool"].to_numpy()
    return cols, pool, key


def counts(day_index, n, B):
    rng = np.random.default_rng(np.random.SeedSequence([SEED, day_index]))
    W = np.zeros((B, n), dtype=np.float32)
    idx = rng.integers(0, n, (B, n))
    for b in range(B):
        W[b] = np.bincount(idx[b], minlength=n)
    return W


def analyse(root, src, out, B):
    manifest = M.read_manifest(os.path.join(root, src, "manifest.jsonl"))
    fits = sorted(r["unit"].split("=")[1] for r in manifest)
    days = sorted({c["d"] for r in manifest for c in r["cells"]})
    os.makedirs(os.path.join(root, out), exist_ok=True)
    # per (lag, scorer, regime, metric): list over days of (mean control, mean frozen, replicate arrays)
    acc, lev, scor, strata_rows, byday, known = {}, {}, {}, [], {}, {}
    n_clicks = {}
    for di, d in enumerate(days):
        cols, pool, key = load_day(os.path.join(root, src), d, fits)
        n = len(pool)
        n_clicks[d] = n
        W = counts(di, n, B)
        ctrl_fit = str(dt.date.fromisoformat(d) - dt.timedelta(days=1))
        reps = {(k, m): W @ v[m] / n for k, v in cols.items() for m in METRICS}        # one product per cell and metric
        for (r, scorer, regime), c in cols.items():
            lag = (dt.date.fromisoformat(d) - dt.date.fromisoformat(r)).days
            cc = cols.get((ctrl_fit, scorer, regime))
            if cc is None:
                continue
            for m in METRICS:
                rep_f, rep_c = reps[((r, scorer, regime), m)], reps[((ctrl_fit, scorer, regime), m)]
                acc.setdefault((lag, scorer, regime, m), []).append((cc[m].mean() - c[m].mean(), rep_c - rep_f, c[m].mean(), rep_f, n))
                byday[(scorer, regime, m, d, lag)] = (c[m].mean(), rep_f)
            scor.setdefault((lag, scorer, regime), []).append(c["scorable"].mean())
            # on the clicks the frozen model can score at all (the same clicks for the control): accuracy apart from coverage
            kk = c["scorable"]
            if kk.sum() >= 30:
                den = W @ kk / n
                row = {"cov": (kk.mean(), W @ kk / n)}
                for m in ("mrr", "recall10"):
                    f_ = (W @ (c[m] * kk)) / np.maximum(W @ kk, 1)
                    c_ = (W @ (cc[m] * kk)) / np.maximum(W @ kk, 1)
                    row[m] = ((c[m] * kk).sum() / kk.sum(), (cc[m] * kk).sum() / kk.sum(), f_, c_)
                known.setdefault((lag, scorer, regime), []).append(row)
            if m == METRICS[-1]:
                pass
            # fresh versus decayed: strata are those of the frozen fit; the terms pi_s (ctrl - frozen) sum exactly to the gap
            s = c["stratum"]
            for k in (0, 1, 2):
                msk = s == k
                if msk.any():
                    strata_rows.append((lag, scorer, regime, d, k, float(msk.mean()), float(c["mrr"][msk].mean()), float(cc["mrr"][msk].mean()),
                                        float(msk.mean() * (cc["mrr"][msk].mean() - c["mrr"][msk].mean()))))
            total = sum(float((s == k).mean() * (cc["mrr"][s == k].mean() - c["mrr"][s == k].mean())) for k in (0, 1, 2) if (s == k).any())
            assert abs(total - (cc["mrr"].mean() - c["mrr"].mean())) < 1e-12, "strata terms do not sum to the gap"
    rows = []
    for (lag, scorer, regime, m), v in sorted(acc.items()):
        delta = np.mean([x[0] for x in v])
        rep = np.mean([x[1] for x in v], axis=0)
        lvl = np.mean([x[2] for x in v])
        lvl_rep = np.mean([x[3] for x in v], axis=0)
        lo, hi = np.percentile(rep, [2.5, 97.5])
        l0, l1 = np.percentile(lvl_rep, [2.5, 97.5])
        rows.append([scorer, regime, m, lag, len(v), sum(x[4] for x in v), round(float(lvl), 6), round(float(l0), 6), round(float(l1), 6),
                     round(float(delta), 6), round(float(lo), 6), round(float(hi), 6),
                     round(float(np.mean(scor[(lag, scorer, regime)])), 4)])
    hdr = ["scorer", "regime", "metric", "lag_days", "cells", "n_clicks", "level", "level_lo", "level_hi", "decay", "decay_lo", "decay_hi", "scorable_share"]
    with open(os.path.join(root, out, "decay_by_lag.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(hdr); w.writerows(rows)
    # strata table pooled over the days of a lag
    sr = pl.DataFrame(strata_rows, schema=["lag_days", "scorer", "regime", "day", "stratum", "share", "mrr_frozen", "mrr_control", "term"], orient="row")
    sp = (sr.group_by(["scorer", "regime", "lag_days", "stratum"]).agg(pl.col("share").mean(), pl.col("mrr_frozen").mean(), pl.col("mrr_control").mean(), pl.col("term").mean())
          .sort(["scorer", "regime", "lag_days", "stratum"]))
    sp.write_csv(os.path.join(root, out, "decay_by_stratum.csv"))
    kr = []
    for (lag, scorer, regime), v in sorted(known.items()):
        o = [scorer, regime, lag, len(v)]
        cov = np.mean([x["cov"][0] for x in v]); rep = np.mean([x["cov"][1] for x in v], axis=0)
        o += [round(float(cov), 4), *[round(float(q), 4) for q in np.percentile(rep, [2.5, 97.5])]]
        for m in ("mrr", "recall10"):
            f0, c0 = np.mean([x[m][0] for x in v]), np.mean([x[m][1] for x in v])
            rf = np.mean([x[m][2] for x in v], axis=0); rc = np.mean([x[m][3] for x in v], axis=0)
            dl, dh = np.percentile(rc - rf, [2.5, 97.5])
            fl, fh = np.percentile(rf, [2.5, 97.5])
            o += [round(float(f0), 6), round(float(fl), 6), round(float(fh), 6), round(float(c0), 6),
                  round(float(c0 - f0), 6), round(float(dl), 6), round(float(dh), 6)]
        kr.append(o)
    kh = ["scorer", "regime", "lag_days", "cells", "coverage", "coverage_lo", "coverage_hi"]
    for m in ("mrr", "recall10"):
        kh += [f"{m}_frozen", f"{m}_frozen_lo", f"{m}_frozen_hi", f"{m}_control", f"{m}_decay", f"{m}_decay_lo", f"{m}_decay_hi"]
    with open(os.path.join(root, out, "decay_on_known.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(kh); w.writerows(kr)
    # sanity: a scorer against itself pairs to exactly zero
    zero = [abs(x[0] - x[0]) for v in acc.values() for x in v][:1]
    return rows, hdr, days, fits, n_clicks, manifest, acc, byday


def replay(root, manifest, out, days, byday, B):
    """RQ3: for rebuild interval k, day d uses the latest rebuild at or before the day before d. Cell lookup, no refit."""
    os.makedirs(os.path.join(root, out), exist_ok=True)
    fit_s = {}
    for r in manifest:
        for k, v in r["fit_seconds"].items():
            fit_s.setdefault(k, []).append(v)
    first_d = dt.date.fromisoformat(min(r["unit"].split("=")[1] for r in manifest))
    scorers = sorted({k[0] for k in byday})
    out_rows = []
    for scorer in scorers:
        for regime in ("A", "B"):
            for k in KS:
                vals, reps, lags = [], [], []
                for d in days:
                    dd = dt.date.fromisoformat(d)
                    j = ((dd - dt.timedelta(days=1)) - first_d).days // k            # the latest rebuild at or before d-1
                    lag = (dd - (first_d + dt.timedelta(days=j * k))).days
                    x = byday.get((scorer, regime, "mrr", d, lag))
                    if x is None:
                        continue
                    vals.append(x[0]); reps.append(x[1]); lags.append(lag)
                lo, hi = np.percentile(np.mean(reps, axis=0), [2.5, 97.5])
                rebuilds = int(np.ceil(len(days) / k))
                out_rows.append([scorer, regime, k, round(float(np.mean(vals)), 6), round(float(lo), 6), round(float(hi), 6),
                                 rebuilds, round(rebuilds * float(np.mean(fit_s.get(scorer, [0.0]))), 2), round(float(np.mean(lags)), 2), len(vals)])
    with open(os.path.join(root, out, "schedule.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scorer", "regime", "interval_days", "mrr", "mrr_lo", "mrr_hi", "rebuilds", "fit_seconds_total", "mean_staleness_days", "days"])
        w.writerows(out_rows)
    json.dump({"peak_rss_gb_fit_unit": max(r["peak_rss_gb"] for r in manifest),
               "fit_seconds_mean": {k: round(float(np.mean(v)), 3) for k, v in fit_s.items()}},
              open(os.path.join(root, out, "cost.json"), "w"), indent=1)
    return out_rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--src", default="results/decay_matrix"); ap.add_argument("--out", default="results/rq1_rq2")
    ap.add_argument("--rq3", default="results/rq3"); ap.add_argument("--B", type=int, default=1000)
    a = ap.parse_args()
    with M.Unit("t7", "analysis", manifest=os.path.join(a.root, a.out, "manifest.jsonl") if os.path.isdir(os.path.join(a.root, a.out)) else None,
                disk_dir=a.root, rss_cap_gb=12) as u:
        rows, hdr, days, fits, n_clicks, manifest, acc, byday = analyse(a.root, a.src, a.out, a.B)
        rq3 = replay(a.root, manifest, a.rq3, days, byday, a.B)
        u.extra.update(cells=len(manifest), days=len(days), B=a.B)
    print("rows", len(rows), "schedule rows", len(rq3))
