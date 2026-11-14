"""Real-impression evaluation, feasibility counts (read-only). EB-NeRD validation behaviours hold the impression slates (article_ids_inview) and the clicks
(article_ids_clicked) of OUR reader cohort for 2023-05-25 07:00 .. 2023-06-01 07:00, i.e. after the history reads that the main store holds end (2023-05-25 06:59).
Per day: impressions, clicks, slate size, share of clicked and of slate articles known to the store with a publish time.
Writes results/impressions/feasibility.json (atomic).   Run:  python impr_feasibility.py <root>
"""
import json, os, sys

import numpy as np
import polars as pl


def main(root):
    st = os.path.join(root, "data/ebnerd/store")
    arts = pl.read_parquet(os.path.join(st, "articles.parquet"), columns=["article", "pub"]).filter(pl.col("pub").is_not_null())
    known = set(arts["article"].to_list())
    b = pl.scan_parquet(os.path.join(root, "data/ebnerd/large/validation/behaviors.parquet")).select("user_id", "impression_time", "article_ids_inview", "article_ids_clicked")
    out = {"days": []}
    for d in range(25, 32):
        lo, hi = f"2023-05-{d} 00:00:00", None
        day = b.filter(pl.col("impression_time").dt.date() == pl.lit(f"2023-05-{d}").str.to_date()).collect()
        n = day.height
        slate = day["article_ids_inview"].list.len().to_numpy()
        cl = day.select(pl.col("article_ids_clicked").explode().alias("a")).drop_nulls()["a"].to_numpy()
        inv = day.select(pl.col("article_ids_inview").explode().alias("a")).drop_nulls()["a"].to_numpy()
        out["days"].append({"day": f"2023-05-{d}", "impressions": n, "users": day["user_id"].n_unique(), "clicks": int(len(cl)), "slate_median": float(np.median(slate)), "slate_p90": float(np.percentile(slate, 90)),
                            "clicked_known_pub": float(np.mean([int(a) in known for a in cl[:200000]])), "slate_known_pub": float(np.mean([int(a) in known for a in inv[:500000]]))})
    out["note"] = "history reads in the store end 2023-05-25 06:59; impressions start 2023-05-25 07:00; 25 May is a partial day"
    os.makedirs(os.path.join(root, "results/impressions"), exist_ok=True)
    p = os.path.join(root, "results/impressions/feasibility.json")
    json.dump(out, open(p + ".tmp", "w"), indent=1)
    os.replace(p + ".tmp", p)
    for r in out["days"]:
        print(r)


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
