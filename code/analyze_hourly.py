"""T6h analysis: decay against hours since the fit, with paired bootstrap intervals.
A bucket is one clock hour s. Its clicks are the same for every cell that scores it (one sample per hour), so one resample-count
matrix per bucket (SeedSequence([SEED, 1, bucket index])) is shared by all cells of that bucket. The cell (fit r, offset h) is
compared with the control of its bucket: the model fitted at the start of that hour (unit s, offset 1). Decay = control - frozen.
Run:  python analyze_hourly.py <root> [--src results/decay_hourly] [--out results/rq_hourly] [--B 1000]
"""
import argparse, csv, datetime as dt, os, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import polars as pl

import monitor as M
from analyze import counts, SEED
from core import metrics_from_ranks

H = 3600
METRICS = ["mrr", "recall10"]


def tag_ts(tag):
    return int(dt.datetime.strptime(tag, "%Y-%m-%dT%H").replace(tzinfo=dt.timezone.utc).timestamp())


def cell(src, tag, h):
    x = pl.read_parquet(os.path.join(src, f"r={tag}", f"h={h:02d}", "part.parquet"))
    out = {}
    for (regime, scorer), g in x.partition_by(["regime", "scorer"], as_dict=True).items():
        g = g.sort(["user", "article", "t"])
        m = metrics_from_ranks(g["rank"].to_numpy(), g["pool"].to_numpy())
        out[(scorer, regime)] = {**m, "scorable": g["scorable"].to_numpy().astype(np.float64)}
    return out, len(g)


def analyse(root, src, out, B):
    src = os.path.join(root, src)
    mf = M.read_manifest(os.path.join(src, "manifest.jsonl"))
    units = {r["unit"].split("=")[1]: r for r in mf}
    frozen = {t: [c["h"] for c in r["cells"]] for t, r in units.items() if r["frozen"]}
    cells = defaultdict(list)                                    # bucket start -> [(fit tag, offset)]
    for t, hs in frozen.items():
        for h in hs:
            cells[tag_ts(t) + (h - 1) * H].append((t, h))
    acc, known, cov = defaultdict(list), defaultdict(list), defaultdict(list)
    for bi, s in enumerate(sorted(cells)):
        ctrl_tag = dt.datetime.fromtimestamp(s, dt.timezone.utc).strftime("%Y-%m-%dT%H")
        if ctrl_tag not in units:
            continue
        ctrl, n = cell(src, ctrl_tag, 1)
        W = counts(10_000 + bi, n, B)
        rc = {(k, m): W @ v[m] / n for k, v in ctrl.items() for m in METRICS}
        for t, h in cells[s]:
            fz, n2 = cell(src, t, h)
            assert n2 == n, "bucket clicks differ between cells"
            for key, c in fz.items():
                cc = ctrl[key]
                for m in METRICS:
                    rf = W @ c[m] / n
                    acc[(h, *key, m)].append((cc[m].mean() - c[m].mean(), rc[(key, m)] - rf, c[m].mean(), rf))
                kk = c["scorable"]
                cov[(h, *key)].append((kk.mean(), W @ kk / n))
                if kk.sum() >= 30:
                    row = {}
                    for m in METRICS:
                        d = np.maximum(W @ kk, 1)
                        row[m] = ((c[m] * kk).sum() / kk.sum(), (cc[m] * kk).sum() / kk.sum(), (W @ (c[m] * kk)) / d, (W @ (cc[m] * kk)) / d)
                    known[(h, *key)].append(row)
    os.makedirs(os.path.join(root, out), exist_ok=True)
    rows = []
    for (h, scorer, regime, m), v in sorted(acc.items()):
        d = np.mean([x[0] for x in v]); rep = np.mean([x[1] for x in v], axis=0)
        lv = np.mean([x[2] for x in v]); lrep = np.mean([x[3] for x in v], axis=0)
        cv = np.mean([x[0] for x in cov[(h, scorer, regime)]]); crep = np.mean([x[1] for x in cov[(h, scorer, regime)]], axis=0)
        r = [scorer, regime, m, h, len(v), round(float(lv), 6), *[round(float(q), 6) for q in np.percentile(lrep, [2.5, 97.5])],
             round(float(d), 6), *[round(float(q), 6) for q in np.percentile(rep, [2.5, 97.5])],
             round(float(cv), 4), *[round(float(q), 4) for q in np.percentile(crep, [2.5, 97.5])]]
        kv = known.get((h, scorer, regime))
        if kv and m in kv[0]:
            f0, c0 = np.mean([x[m][0] for x in kv]), np.mean([x[m][1] for x in kv])
            rf = np.mean([x[m][2] for x in kv], axis=0); rcc = np.mean([x[m][3] for x in kv], axis=0)
            r += [round(float(f0), 6), round(float(c0), 6), round(float(c0 - f0), 6), *[round(float(q), 6) for q in np.percentile(rcc - rf, [2.5, 97.5])]]
        else:
            r += [""] * 5
        rows.append(r)
    hdr = ["scorer", "regime", "metric", "hours_since_fit", "cells", "level", "level_lo", "level_hi", "decay", "decay_lo", "decay_hi",
           "coverage", "coverage_lo", "coverage_hi", "known_frozen", "known_control", "known_decay", "known_decay_lo", "known_decay_hi"]
    with open(os.path.join(root, out, "decay_by_hour.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(hdr); w.writerows(rows)
    return len(rows), sum(len(v) for v in cells.values())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--src", default="results/decay_hourly"); ap.add_argument("--out", default="results/rq_hourly")
    ap.add_argument("--B", type=int, default=1000)
    a = ap.parse_args()
    print(analyse(a.root, a.src, a.out, a.B))
