"""Per lag: how similar is the clicked article to the user's profile, against the other published articles in its pool?
Per (scorer, regime, lag): mean target score, mean pool score (the mean over clicks of each click's pool mean), their gap, and the
standardised gap z = (target - pool mean) / pool sd (comparable across scorers; BM25 and cosine have different scales).
Intervals: bootstrap over clicks (B=1000). Clicks at one lag come from different evaluation days, so they do not repeat;
users do repeat, so the intervals are slightly narrow. Strata (S0 seen, S1 missed, S2 new today) are split for regime A at lags 1, 3, 7, 13.
The change with lag is NOT read off this table (each lag has different evaluation days): paired(), below, compares the same clicks
scored at lag 1 and at lag L (same evaluation day, fit one day before against fit L days before) and writes sim_gap_paired.csv.
Run:  python sim_gap_analyze.py <root> [--src results/sim_gap] [--out results/sim_gap/sim_gap_by_lag.csv] [--B 1000]
"""
import argparse, csv, datetime as dt, glob, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import polars as pl

from sample import SEED

STAT = ["tgt", "pool", "gap", "z"]
STRATA_LAGS = (1, 3, 7, 13)


def load(root, src):
    parts = []
    for f in sorted(glob.glob(os.path.join(root, src, "r=*", "d=*", "part.parquet"))):
        r, d = f.split("/")[-3][2:], f.split("/")[-2][2:]
        lag = (dt.date.fromisoformat(d) - dt.date.fromisoformat(r)).days
        parts.append(pl.read_parquet(f).filter(pl.col("tgt").is_not_nan() & pl.col("tgt").is_not_null()).with_columns(pl.lit(lag).alias("lag")))
    return pl.concat(parts)


def stats(g):
    tgt, mu, sd = g["tgt"].to_numpy(), g["pool_mean"].to_numpy(), g["pool_sd"].to_numpy()
    ok = sd > 0
    z = np.where(ok, (tgt - mu) / np.where(ok, sd, 1), np.nan)
    return np.stack([tgt, mu, tgt - mu, z])                                  # (4, n)


def boot(X, B, key):
    rng = np.random.default_rng(np.random.SeedSequence([SEED, 77, key]))
    n = X.shape[1]
    Xz = np.where(np.isnan(X[3]), 0, X[3])
    okz = ~np.isnan(X[3])
    out = np.empty((B, 4))
    for b in range(B):
        i = rng.integers(0, n, n)
        out[b, :3] = X[:3, i].mean(1)
        out[b, 3] = Xz[i].sum() / max(okz[i].sum(), 1)
    return out


def point(X):
    return np.array([*X[:3].mean(1), np.nanmean(X[3])])


def run(root, src, out, B):
    df = load(root, src)
    rows, keys = [], 0
    for (scorer, regime, lag), g in sorted(df.partition_by(["scorer", "regime", "lag"], as_dict=True).items(), key=lambda kv: kv[0]):
        X = stats(g)
        p, bt = point(X), boot(X, B, keys)
        keys += 1
        rows.append((scorer, regime, lag, "all", g.height, p, bt))
        if regime == "A" and lag in STRATA_LAGS:
            for s in (0, 1, 2):
                m = (g["stratum"] == s).to_numpy()
                if m.sum() >= 200:
                    Xs = X[:, m]
                    rows.append((scorer, regime, lag, f"S{s}", int(m.sum()), point(Xs), boot(Xs, B, keys)))
                    keys += 1
    hdr = ["scorer", "regime", "lag", "stratum", "n"] + [f"{s}{e}" for s in STAT for e in ("", "_lo", "_hi")]
    os.makedirs(os.path.dirname(os.path.join(root, out)), exist_ok=True)
    with open(os.path.join(root, out), "w", newline="") as f:
        w = csv.writer(f); w.writerow(hdr)
        for scorer, regime, lag, st, n, p, bt in rows:
            lo, hi = np.percentile(bt, [2.5, 97.5], axis=0)
            r = [scorer, regime, lag, st, n]
            for k in range(4):
                r += [round(float(p[k]), 6), round(float(lo[k]), 6), round(float(hi[k]), 6)]
            w.writerow(r)
    return len(rows)


def paired(root, src, out, B):
    """same clicks (same day, user, article, t), lag 1 against lag L: mean of (z at lag L - z at lag 1) and of the raw gap difference."""
    parts = []
    for f in sorted(glob.glob(os.path.join(root, src, "r=*", "d=*", "part.parquet"))):
        r, d = f.split("/")[-3][2:], f.split("/")[-2][2:]
        lag = (dt.date.fromisoformat(d) - dt.date.fromisoformat(r)).days
        g = pl.read_parquet(f).filter(pl.col("tgt").is_not_nan() & pl.col("tgt").is_not_null() & (pl.col("pool_sd") > 0))
        parts.append(g.with_columns(pl.lit(lag).alias("lag"), pl.lit(d).alias("d"),
                                    ((pl.col("tgt") - pl.col("pool_mean")) / pl.col("pool_sd")).alias("z"),
                                    (pl.col("tgt") - pl.col("pool_mean")).alias("gap")).select("scorer", "regime", "lag", "d", "user", "article", "t", "z", "gap"))
    df = pl.concat(parts)
    one = df.filter(pl.col("lag") == 1).rename({"z": "z1", "gap": "gap1"}).drop("lag")
    rows, key = [], 0
    for (scorer, regime, lag), g in sorted(df.filter(pl.col("lag") > 1).partition_by(["scorer", "regime", "lag"], as_dict=True).items(), key=lambda kv: kv[0]):
        j = g.join(one, on=["scorer", "regime", "d", "user", "article", "t"], how="inner")
        dz, dg = (j["z"] - j["z1"]).to_numpy(), (j["gap"] - j["gap1"]).to_numpy()
        n = len(dz)
        rng = np.random.default_rng(np.random.SeedSequence([SEED, 78, key])); key += 1
        bz, bg = np.empty(B), np.empty(B)
        for b in range(B):
            i = rng.integers(0, n, n)
            bz[b], bg[b] = dz[i].mean(), dg[i].mean()
        rows.append([scorer, regime, lag, n, round(float(dz.mean()), 6), *[round(float(q), 6) for q in np.percentile(bz, [2.5, 97.5])],
                     round(float(dg.mean()), 6), *[round(float(q), 6) for q in np.percentile(bg, [2.5, 97.5])]])
    with open(os.path.join(root, out), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scorer", "regime", "lag", "n_paired", "dz", "dz_lo", "dz_hi", "dgap", "dgap_lo", "dgap_hi"]); w.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--src", default="results/sim_gap"); ap.add_argument("--out", default="results/sim_gap/sim_gap_by_lag.csv")
    ap.add_argument("--B", type=int, default=1000)
    a = ap.parse_args()
    print(run(a.root, a.src, a.out, a.B))
    print(paired(a.root, a.src, os.path.join(os.path.dirname(a.out), "sim_gap_paired.csv"), a.B))
