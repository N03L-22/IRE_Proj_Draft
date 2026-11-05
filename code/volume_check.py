"""Exploratory: does decay on an evaluation day move with that day's volume? Per day d (lag 3, regime B): the loss of a frozen model against
the control (MRR) and the share of clicks it can score, against the articles published on d and the clicks on d (UTC days).
14 days only: Spearman rho with a bootstrap interval over days; an exploratory check, not a test.
Run:  python volume_check.py <root>
"""
import csv, datetime as dt, glob, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, polars as pl
from analyze import load_day
from scipy.stats import spearmanr

root = sys.argv[1]
src = os.path.join(root, "results/decay_matrix")
st = os.path.join(root, "data/ebnerd/store")
art = pl.read_parquet(os.path.join(st, "articles.parquet"), columns=["article", "pub"]).drop_nulls("pub")
pubday = art.with_columns(pl.from_epoch("pub").dt.date().cast(pl.Utf8).alias("d")).group_by("d").len().to_dict(as_series=False)
npub = dict(zip(pubday["d"], pubday["len"]))
nclk = {os.path.basename(p).split("=")[1]: pl.scan_parquet(os.path.join(p, "*.parquet")).select(pl.len()).collect().item() for p in glob.glob(os.path.join(st, "clicks_by_day", "day=*"))}
LAG = 3
rows = []
for d in [str(dt.date(2023, 5, 11) + dt.timedelta(days=i)) for i in range(14)]:
    dd = dt.date.fromisoformat(d)
    r, ctrl = str(dd - dt.timedelta(days=LAG)), str(dd - dt.timedelta(days=1))
    cols, pool, _ = load_day(src, d, [r, ctrl])
    if (r, "word", "B") not in cols:
        continue
    o = {"day": d, "published_that_day": npub.get(d, 0), "clicks_that_day": nclk.get(d, 0)}
    for sc in ("word", "meaning", "clickhist"):
        f, c = cols[(r, sc, "B")], cols[(ctrl, sc, "B")]
        o[f"{sc}_mrr_lost"] = float(c["mrr"].mean() - f["mrr"].mean()); o[f"{sc}_scorable"] = float(f["scorable"].mean())
    rows.append(o)
os.makedirs(os.path.join(root, "results/volume"), exist_ok=True)
with open(os.path.join(root, "results/volume/volume_check.csv"), "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
rng = np.random.default_rng(20261029)
out = []
for x in ("published_that_day", "clicks_that_day"):
    for y in ("word_mrr_lost", "meaning_mrr_lost", "clickhist_mrr_lost", "clickhist_scorable"):
        a, b = np.array([q[x] for q in rows], float), np.array([q[y] for q in rows], float)
        if len(set(b)) < 2:
            print(f"{x:20s} {y:20s} constant (all {b[0]:.4g}); no correlation"); continue
        rho = spearmanr(a, b)[0]
        bs = []
        for _ in range(2000):
            i = rng.integers(0, len(a), len(a))
            if len(set(a[i])) > 1 and len(set(b[i])) > 1:
                bs.append(spearmanr(a[i], b[i])[0])
        out.append((x, y, len(a), rho, *np.percentile(bs, [2.5, 97.5])))
        print(f"{x:20s} {y:20s} n={len(a)} rho={rho:+.2f} [{out[-1][4]:+.2f}, {out[-1][5]:+.2f}]")
print("published per day", [q["published_that_day"] for q in rows]); print("clicks per day (M)", [round(q["clicks_that_day"]/1e6,1) for q in rows])
