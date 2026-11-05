"""T1a gates and input report for the EB-NeRD store (stage-plan 2.4 A).

Checks: manifest completeness, row reconciliation with the source history, per-day counts, publish-time coverage,
impossible ages, age quantiles, the hourly histogram (time zone and the 01:00 gap), and the reproduction of the
07:00 unseen-share curve of log P28.  Writes <root>/data/ebnerd/store/input_report.json.
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import polars as pl

import monitor as M

root = sys.argv[1]
st = os.path.join(root, "data/ebnerd/store")
raw = os.path.join(root, "data/ebnerd/large")
rep, fails = {}, []

rows = M.read_manifest(os.path.join(st, "manifest.jsonl"))
rep["units"] = len(rows)
rep["rows_in_manifest"] = sum(r["rows_in"] for r in rows)
rep["duplicates_removed"] = sum(r["duplicates"] for r in rows)
rep["peak_rss_gb_max"] = max(r["peak_rss_gb"] for r in rows)
rep["unit_seconds"] = {"min": min(r["seconds"] for r in rows), "max": max(r["seconds"] for r in rows)}

src = pl.scan_parquet(f"{raw}/validation/history.parquet").select(pl.col("article_id_fixed").list.len().sum()).collect().item()
rep["source_clicks"] = int(src)
if rep["rows_in_manifest"] != src:
    fails.append("rows_in_manifest != source clicks")

lf = pl.scan_parquet(f"{st}/clicks_by_day/*/*.parquet", hive_partitioning=True)
n = lf.select(pl.len()).collect().item()
rep["store_clicks"] = n
if n != src - rep["duplicates_removed"]:
    fails.append("store rows != source minus duplicates")

d = lf.group_by("day").agg(pl.len().alias("clicks"), pl.col("user").n_unique().alias("users"),
                           pl.col("pub").is_null().sum().alias("no_pub")).sort("day").collect()
rep["days"] = [{"day": str(r["day"]), "clicks": r["clicks"], "users": r["users"], "no_pub": r["no_pub"]} for r in d.iter_rows(named=True)]
rep["first_day"], rep["last_day"] = str(d["day"].min()), str(d["day"].max())
if rep["first_day"] < "2023-04-26" or rep["last_day"] > "2023-06-02":
    fails.append("click days outside the dataset span")

c = lf.select("user", "article", "t", "pub").collect()
rep["users"] = int(c["user"].n_unique())
rep["null_pub_share"] = float(c["pub"].is_null().mean())
age = ((c["t"].cast(pl.Int64) - c["pub"].cast(pl.Int64)) / 3600).drop_nulls()
rep["negative_age_share"] = float((age < 0).mean())
rep["age_hours_quantiles_50_85_95"] = [float(age.quantile(q)) for q in (0.5, 0.85, 0.95)]
rep["share_within_24h_48h"] = [float(((age >= 0) & (age <= h)).mean()) for h in (24, 48)]
if rep["negative_age_share"] > 0.05:
    fails.append("more than 5 % impossible ages")

# hourly histogram: time zone and the gap near 01:00
hr = (c["t"].cast(pl.Int64) % 86400 // 3600).to_numpy()
hist = np.bincount(hr, minlength=24)
rep["clicks_by_hour_of_day"] = [int(x) for x in hist]
rep["quietest_hours"] = [int(h) for h in np.argsort(hist)[:3]]
dh = c.with_columns((pl.col("t").cast(pl.Int64) // 3600).alias("h")).group_by("h").agg(pl.len().alias("n")).sort("h")
full = np.arange(dh["h"].min(), dh["h"].max() + 1)
cnt = np.zeros(len(full), dtype=np.int64)
cnt[dh["h"].to_numpy() - full[0]] = dh["n"].to_numpy()
med = np.median(cnt[cnt > 0])
rep["hours_in_span"] = int(len(full))
rep["hours_with_zero_clicks"] = int((cnt == 0).sum())
rep["hours_under_10pct_of_median"] = [str(np.datetime64(int(h) * 3600, "s")) for h, k in zip(full, cnt) if k < 0.1 * med][:40]

# P28 reproduction: 07:00 fit on 10..22 May, validation history, articles published 2023 or later
j = c.filter(pl.col("pub") >= 1672531200)      # 2023-01-01 UTC, as in P28
t = j["t"].to_numpy().astype(np.int64)
p = j["pub"].to_numpy().astype(np.int64)
o = np.argsort(t, kind="stable"); t, p = t[o], p[o]
import datetime as dt
N = np.zeros(48); W = np.zeros(48)
for day in range(10, 23):
    r = int(dt.datetime(2023, 5, day, 7, tzinfo=dt.timezone.utc).timestamp())
    lo, hi = np.searchsorted(t, [r + 1, r + 48 * 3600 + 1])
    hh = np.ceil((t[lo:hi] - r) / 3600).astype(int) - 1
    N += np.bincount(hh, minlength=48)[:48]
    W += np.bincount(hh[p[lo:hi] > r], minlength=48)[:48]
curve = (W / N)
rep["p28_reproduction_pct_at_1_2_3_6_h"] = [round(100 * curve[h - 1], 1) for h in (1, 2, 3, 6)]
if [round(100 * curve[h - 1], 1) for h in (1, 2, 3, 6)] != [19.5, 59.7, 77.2, 90.8]:
    fails.append("07:00 curve does not reproduce log P28")

rep["failed_gates"] = fails
json.dump(rep, open(f"{st}/input_report.json", "w"), indent=1)
print(json.dumps({k: v for k, v in rep.items() if k not in ("days", "clicks_by_hour_of_day")}, indent=1))
print("clicks by hour of day:", rep["clicks_by_hour_of_day"])
