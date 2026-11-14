"""How narrow are our intervals? The study's intervals resample CLICKS inside each day. Readers repeat and days differ, so this recomputes the headline numbers with
  click       resample clicks inside each day (the existing method)
  reader      resample READERS inside each day (all clicks of a reader move together)
  day         resample the evaluation DAYS (each day taken as one number)
  reader+day  resample days, and inside each chosen day use a reader-resample (two stage)
B = 1000, seeded; days enter with equal weight as in analyze.py. Quantities (EB-NeRD):
  decay (control rebuilt the day before minus frozen, same clicks): word A lag 7 and 13, meaning A lag 7, genre alone A lag 7
  differences on the same clicks: recency + genre minus recency (B, lag 1 and 7), recency + genre minus recency + category prior (B, lag 1), trending 1 h minus recency (B)
Writes results/cluster_ci/intervals.csv (atomic).   Run:  python cluster_ci.py <root> [--B 1000]
"""
import argparse, csv, datetime as dt, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import monitor as M
from analyze import SEED, counts, load_day

D = lambda d, k: str(dt.date.fromisoformat(d) - dt.timedelta(days=k))
# name, source, mode, scorer(s), regime, lag; fit date of a cell is chosen per mode
SPECS = [
    ("word A: MRR lost at lag 7", "results/decay_matrix", "decay", ("word",), "A", 7),
    ("word A: MRR lost at lag 13", "results/decay_matrix", "decay", ("word",), "A", 13),
    ("meaning A: MRR lost at lag 7", "results/decay_matrix", "decay", ("meaning",), "A", 7),
    ("genre A: MRR lost at lag 7", "results/genre", "decay", ("genre",), "A", 7),
    ("recency+genre minus recency, B, lag 1", "results/s2_perm", "diff", ("fuse_genre", "recency"), "B", 1),
    ("recency+genre minus recency, B, lag 7", "results/s2_perm", "diff", ("fuse_genre", "recency"), "B", 7),
    ("recency+genre minus recency+category prior, B, lag 1", "results/s2_perm", "diff", ("fuse_genre", "fuse_genre_prior"), "B", 1),
    ("trending 1 h minus recency, B", "results/s7_trend", "fixed", ("trend_h1", "recency"), "B", 0),
]


def day_value(spec, cols_by_src, d):
    name, src, mode, sc, regime, lag = spec
    cols = cols_by_src[src]
    if mode == "decay":
        c, f = cols.get((D(d, 1), sc[0], regime)), cols.get((D(d, lag), sc[0], regime))
        return None if c is None or f is None else c["mrr"] - f["mrr"]
    fit = D(d, lag) if mode == "diff" else "2023-05-10"
    x, y = cols.get((fit, sc[0], regime)), cols.get((fit, sc[1], regime))
    return None if x is None or y is None else x["mrr"] - y["mrr"]


def main(root, B):
    days = [str(dt.date(2023, 5, 11) + dt.timedelta(days=i)) for i in range(14)]
    srcs = sorted({s[1] for s in SPECS})
    per = {s[0]: [] for s in SPECS}                       # per spec: list over days of (mean, click replicates, reader replicates, n)
    for di, d in enumerate(days):
        cols_by_src, key = {}, None
        for src in srcs:
            p = os.path.join(root, src)
            mf = M.read_manifest(os.path.join(p, "manifest.jsonl"))
            fits = sorted(r["unit"].split("=")[1] for r in mf)
            c, pool, k = load_day(p, d, fits)
            cols_by_src[src] = c
            if key is None:
                key, n = k, len(pool)
            else:
                assert key.equals(k), f"click sets differ between sources on {d}"
        Wc = counts(di, n, B)
        users = key["user"].to_numpy()
        uniq, inv = np.unique(users, return_inverse=True)
        rng = np.random.default_rng(np.random.SeedSequence([SEED, 91, di]))
        draws = rng.integers(0, len(uniq), (B, len(uniq)))
        cu = np.zeros((B, len(uniq)), dtype=np.float32)
        for b in range(B):
            cu[b] = np.bincount(draws[b], minlength=len(uniq))
        Wu = cu[:, inv]
        for spec in SPECS:
            v = day_value(spec, cols_by_src, d)
            if v is None:
                continue
            per[spec[0]].append((float(v.mean()), Wc @ v / n, (Wu @ v) / np.maximum(Wu.sum(1), 1), n))
    rows = []
    rng = np.random.default_rng(np.random.SeedSequence([SEED, 92]))
    for spec in SPECS:
        v = per[spec[0]]
        k = len(v)
        pt = np.mean([a[0] for a in v])
        click = np.mean([a[1] for a in v], axis=0)
        reader = np.mean([a[2] for a in v], axis=0)
        means = np.array([a[0] for a in v])
        day = np.array([means[rng.integers(0, k, k)].mean() for _ in range(B)])
        both = np.array([np.mean([v[j][2][rng.integers(0, B)] for j in rng.integers(0, k, k)]) for _ in range(B)])
        q = lambda x: [round(float(t), 6) for t in np.percentile(x, [2.5, 97.5])]
        rows.append([spec[0], k, sum(a[3] for a in v), round(float(pt), 6), *q(click), *q(reader), *q(day), *q(both)])
    out = os.path.join(root, "results/cluster_ci")
    os.makedirs(out, exist_ok=True)
    tmp = os.path.join(out, "intervals.csv.tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["quantity", "days", "n_clicks", "value", "click_lo", "click_hi", "reader_lo", "reader_hi", "day_lo", "day_hi", "reader_day_lo", "reader_day_hi"])
        w.writerows(rows)
    os.replace(tmp, os.path.join(out, "intervals.csv"))
    for r in rows:
        print(r)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--B", type=int, default=1000)
    a = ap.parse_args()
    main(os.path.abspath(a.root), a.B)
