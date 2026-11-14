"""Item side of the decay: how fast does an article's pull on readers fall with its age? Model-free, from the click store only.
Cohort: articles published 2023-05-06 .. 2023-05-19 (UTC), so each is observed for its first 120 h inside the store (clicks run to 2023-05-25).
rate(a) = clicks received at age a hours (bucket [a, a+1)) per article, averaged over the cohort; lift(a) = rate(a) / mean rate over ages 0..47.
Half-time = hours from the peak until the smoothed rate first falls to half the peak (linear interpolation; NaN if it does not within 48 h).
Fitted half-life = from a log-linear fit of the rate between the peak and 48 h. Intervals: bootstrap over articles (B = 300, seeded).
The store holds the validation users' history reads (a fixed cohort of readers), so these are the clicks of that cohort.
Writes results/age_lift/{halflife_by_group.csv, lift_by_age.csv}; the last file marks completion.
Run:  python age_lift.py <root>
"""
import csv, datetime as dt, glob, os, sys

import numpy as np
import polars as pl

HOURS, AGES, B, SEED = 72, 48, 300, 20261029
GROUPS_MIN_ARTICLES = 150


def atomic_csv(path, header, rows):
    tmp = path + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)
    os.replace(tmp, path)


def stats(rate):
    """rate: (72,) clicks per article per hour bucket -> dict of the summary numbers."""
    sm = np.convolve(rate, np.ones(3) / 3, mode="same")
    sm[0] = (rate[0] + rate[1]) / 2
    p = int(np.argmax(sm[:AGES]))
    half = 0.5 * sm[p]
    t_half = np.nan
    for a in range(p + 1, AGES):
        if sm[a] <= half:
            t_half = a - 1 + (sm[a - 1] - half) / max(sm[a - 1] - sm[a], 1e-12)
            break
    ok = np.arange(p, AGES)[rate[p:AGES] > 0]
    fit_hl = np.nan
    if len(ok) >= 5:
        slope = np.polyfit(ok, np.log(rate[ok]), 1)[0]
        fit_hl = np.log(2) / -slope if slope < 0 else np.inf
    tot = rate[:AGES].sum()
    return dict(peak=p + 0.5, t_half=t_half, fit_hl=fit_hl, share6=rate[:6].sum() / tot, share24=rate[:24].sum() / tot, lift=rate / rate[:AGES].mean())


def main(root):
    st = os.path.join(root, "data/ebnerd/store")
    out = os.path.join(root, "results/age_lift")
    os.makedirs(out, exist_ok=True)
    lo = int(dt.datetime(2023, 5, 6, tzinfo=dt.timezone.utc).timestamp())
    hi = int(dt.datetime(2023, 5, 20, tzinfo=dt.timezone.utc).timestamp())
    arts = pl.read_parquet(os.path.join(st, "articles.parquet"), columns=["article", "pub", "category"]).filter((pl.col("pub") >= lo) & (pl.col("pub") < hi)).sort("article")
    names = (pl.read_parquet(os.path.join(root, "data/ebnerd/large/articles.parquet"), columns=["category", "category_str"])
             .group_by("category", "category_str").len().sort(["category", "len"], descending=[False, True]).group_by("category", maintain_order=True).first())
    nm = dict(zip(names["category"].to_list(), names["category_str"].to_list()))
    cohort = arts.lazy()
    clicks = (pl.scan_parquet(glob.glob(os.path.join(st, "clicks_by_day", "day=*", "*.parquet"))).select("article", "t")
              .join(cohort.select("article", "pub"), on="article", how="inner")
              .with_columns(((pl.col("t").cast(pl.Int64) - pl.col("pub").cast(pl.Int64)) // 3600).alias("age"))
              .filter((pl.col("age") >= 0) & (pl.col("age") < HOURS)).group_by("article", "age").len().collect(engine="streaming"))
    ids = arts["article"].to_numpy()
    pos = {int(a): i for i, a in enumerate(ids)}
    M = np.zeros((len(ids), HOURS))
    M[[pos[int(a)] for a in clicks["article"].to_list()], clicks["age"].to_numpy()] = clicks["len"].to_numpy()
    cat = arts["category"].to_numpy()
    groups = {"all": np.ones(len(ids), dtype=bool)}
    cats, cnt = np.unique(cat[~np.isnan(cat.astype(float))], return_counts=True)
    for c, k in sorted(zip(cats, cnt), key=lambda x: -x[1]):
        if k >= GROUPS_MIN_ARTICLES:
            groups[f"{nm.get(int(c), c)} ({int(c)})"] = cat == c
    rng = np.random.default_rng(np.random.SeedSequence([SEED, 31]))
    hl_rows, lift_rows = [], []
    for g, m in groups.items():
        X = M[m]
        n = len(X)
        pt = stats(X.mean(0))
        bs = [stats(X[rng.integers(0, n, n)].mean(0)) for _ in range(B)]
        q = lambda k: np.nanpercentile([b[k] for b in bs], [2.5, 97.5]) if not np.all(np.isnan([b[k] for b in bs])) else (np.nan, np.nan)
        hl_rows.append([g, n, int(X.sum()), pt["peak"], round(pt["t_half"], 2), *np.round(q("t_half"), 2), round(pt["fit_hl"], 2), *np.round(q("fit_hl"), 2),
                        round(pt["share6"], 4), *np.round(q("share6"), 4), round(pt["share24"], 4), *np.round(q("share24"), 4)])
        rt = np.stack([X[rng.integers(0, n, n)].mean(0) for _ in range(B)])
        lf = np.stack([b["lift"] for b in bs])
        r0 = X.mean(0)
        rl, rh = np.percentile(rt, [2.5, 97.5], axis=0)
        ll, lh = np.percentile(lf, [2.5, 97.5], axis=0)
        for a in range(HOURS):
            lift_rows.append([g, a, round(float(r0[a]), 5), round(float(rl[a]), 5), round(float(rh[a]), 5), round(float(pt["lift"][a]), 4), round(float(ll[a]), 4), round(float(lh[a]), 4)])
    atomic_csv(os.path.join(out, "halflife_by_group.csv"),
               ["group", "n_articles", "n_clicks", "peak_age_h", "t_half_h", "t_half_lo", "t_half_hi", "fit_half_life_h", "fit_lo", "fit_hi", "share_first6h", "share6_lo", "share6_hi",
                "share_first24h", "share24_lo", "share24_hi"], hl_rows)
    atomic_csv(os.path.join(out, "lift_by_age.csv"), ["group", "age_h", "rate", "rate_lo", "rate_hi", "lift", "lift_lo", "lift_hi"], lift_rows)
    print("groups", len(groups), "articles", len(ids))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
