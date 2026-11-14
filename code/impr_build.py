"""Real-impression evaluation, step 1: the fixed sample and the profile slices (same rule as sample.py).
Evaluation clicks: every (impression, clicked article) of the validation cohort on 2023-05-25 .. 2023-05-31 (UTC date of impression_time; 25 May starts at 07:00).
Per day exactly N clicks are kept by KEY (sample.choose: the N smallest splitmix64 keys, order independent). The candidate set of a click is its impression slate
(article_ids_inview) minus the other articles clicked in the same impression; the order of the slate is NOT stored (the site's own ranking must not be a feature).
Profile slices: for every sampled user, the last 300 clicks before the end of the day, from the history reads of the main store (up to 25 May 06:59) and from the
user's own earlier impression clicks, merged by time. Writes data/ebnerd/store/impr/{clicks_d=D.parquet, profiles_d=D.parquet} and results/impressions/build.json.
Run:  python impr_build.py <root> [--n 20000]
"""
import argparse, datetime as dt, glob, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import polars as pl

from sample import choose

DAYS = [f"2023-05-{d}" for d in range(25, 32)]


def atomic(df, path):
    df.write_parquet(path + ".tmp", compression="zstd")
    os.replace(path + ".tmp", path)


def main(root, n):
    st = os.path.join(root, "data/ebnerd/store")
    out = os.path.join(st, "impr")
    os.makedirs(out, exist_ok=True)
    beh = pl.scan_parquet(os.path.join(root, "data/ebnerd/large/validation/behaviors.parquet")).select("user_id", "impression_time", "article_ids_inview", "article_ids_clicked")
    chosen, users, stats = {}, set(), []
    for d in DAYS:
        day = beh.filter(pl.col("impression_time").dt.date() == pl.lit(d).str.to_date()).collect()
        ex = (day.with_columns(pl.col("impression_time").dt.epoch("s").cast(pl.Int32).alias("t"), pl.col("article_ids_clicked").alias("clk"))
                 .explode("article_ids_clicked").drop_nulls("article_ids_clicked")
                 .select(pl.col("user_id").alias("user"), pl.col("article_ids_clicked").cast(pl.Int32).alias("article"), "t", pl.col("article_ids_inview").alias("inview"), "clk"))
        ex = ex.sort(["user", "article", "t"])
        pos = choose(ex.select("user", "article", "t"), n)
        s = ex[pos]
        slates = [[a for a in iv if a == art or a not in set(clk)] for iv, clk, art in zip(s["inview"].to_list(), s["clk"].to_list(), s["article"].to_list())]
        c = s.select("user", "article", "t").with_columns(pl.Series("slate", slates, dtype=pl.List(pl.Int32)))
        chosen[d] = c
        users |= set(c["user"].to_list())
        stats.append({"day": d, "clicks_in_day": ex.height, "kept": c.height, "slate_median": float(np.median([len(x) for x in slates]))})
        print(stats[-1], flush=True)
    ulist = np.array(sorted(users), dtype=np.uint32)
    hist = (pl.scan_parquet(glob.glob(os.path.join(st, "clicks_by_day", "day=*", "*.parquet"))).filter(pl.col("user").is_in(ulist)).select("user", "article", pl.col("t").cast(pl.Int64)).collect(engine="streaming"))
    imp = (beh.filter(pl.col("user_id").is_in(ulist)).select(pl.col("user_id").alias("user"), pl.col("impression_time").dt.epoch("s").cast(pl.Int64).alias("t"), "article_ids_clicked")
              .explode("article_ids_clicked").drop_nulls("article_ids_clicked").select("user", pl.col("article_ids_clicked").cast(pl.Int32).alias("article"), "t").collect(engine="streaming"))
    allp = pl.concat([hist.select("user", "article", "t"), imp.select("user", "article", "t")]).unique().sort(["user", "t"])
    for d in DAYS:
        end = int(dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc).timestamp()) + 86400
        us = chosen[d]["user"].unique().to_numpy()
        p = allp.filter(pl.col("user").is_in(us) & (pl.col("t") < end)).group_by("user", maintain_order=True).tail(300).select("user", "article", pl.col("t").cast(pl.Int32)).sort(["user", "t"])
        atomic(chosen[d].sort(["user", "article", "t"]), os.path.join(out, f"clicks_d={d}.parquet"))
        atomic(p, os.path.join(out, f"profiles_d={d}.parquet"))
        stats[DAYS.index(d)]["profile_rows"] = p.height
    os.makedirs(os.path.join(root, "results/impressions"), exist_ok=True)
    pth = os.path.join(root, "results/impressions/build.json")
    json.dump({"n": n, "days": stats}, open(pth + ".tmp", "w"), indent=1)
    os.replace(pth + ".tmp", pth)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--n", type=int, default=20000)
    a = ap.parse_args()
    main(os.path.abspath(a.root), a.n)
