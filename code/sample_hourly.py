"""T6h sample: for every clock hour of the block, N clicks chosen by key (the T2 rule) among the clicks whose article is
0..72 h old, and for the users of that day the last CAP clicks before the end of the day. One file pair per day, written to
<root>/data/ebnerd/store/sample_h/{clicks_d=DAY.parquet, profiles_d=DAY.parquet} (the clicks carry all 24 hourly buckets).
Run:  python sample_hourly.py <root> 2023-05-17 2023-05-22 [--n 5000] [--workers 6]
"""
import argparse, datetime as dt, glob, multiprocessing as mp, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import polars as pl

import monitor as M
from sample import choose, SEED, WINDOW_H, CAP


def day_unit(args):
    root, name, day, n, seed = args
    st = os.path.join(root, f"data/{name}/store")
    out = os.path.join(st, "sample_h")
    os.makedirs(out, exist_ok=True)
    with M.Unit("t6h_sample", day, rss_cap_gb=5, disk_dir=st) as u:
        c = pl.read_parquet(glob.glob(os.path.join(st, "clicks_by_day", f"day={day}", "*.parquet")))
        age = (c["t"].cast(pl.Int64) - c["pub"].cast(pl.Int64))
        elig = c.filter((age >= 0) & (age <= WINDOW_H * 3600)).sort(["user", "article", "t"])
        elig = elig.with_columns((pl.col("t") // 3600).alias("hb"))
        parts = []
        for (hb,), g in elig.partition_by("hb", as_dict=True, maintain_order=True).items():
            parts.append(g[choose(g, n, seed)])
        s = pl.concat(parts).drop("hb").sort(["user", "article", "t"])
        end = int(dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp()) + 86400
        users = s["user"].unique()
        files = [f for d in sorted(glob.glob(os.path.join(st, "clicks_by_day", "day=*"))) if d.split("=")[1] <= day
                 for f in glob.glob(os.path.join(d, "*.parquet"))]
        p = (pl.scan_parquet(files).select("user", "article", "t").filter(pl.col("user").is_in(users.implode()))
             .collect(engine="streaming").sort(["user", "t", "article"]).group_by("user", maintain_order=True).tail(CAP))
        u.check()
        M.atomic_write(os.path.join(out, f"clicks_d={day}.parquet"), lambda q: s.write_parquet(q, compression="zstd"))
        M.atomic_write(os.path.join(out, f"profiles_d={day}.parquet"), lambda q: p.write_parquet(q, compression="zstd"))
        u.extra.update(eligible=elig.height, sampled=s.height, users=int(users.len()), profile_rows=p.height, n=n, seed=seed,
                       sample_sha256=M.file_sha256(os.path.join(out, f"clicks_d={day}.parquet")))
    M.append_manifest(os.path.join(out, "manifest.jsonl"), u.row)
    return day


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("d0"); ap.add_argument("d1")
    ap.add_argument("--n", type=int, default=5000); ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    d0, d1 = dt.date.fromisoformat(a.d0), dt.date.fromisoformat(a.d1)
    days = [str(d0 + dt.timedelta(days=i)) for i in range((d1 - d0).days + 1)]
    out = os.path.join(a.root, "data/ebnerd/store/sample_h")
    for f in glob.glob(os.path.join(out, "*.tmp")):
        os.remove(f)
    done = {r["unit"] for r in M.read_manifest(os.path.join(out, "manifest.jsonl"))}
    with mp.get_context("spawn").Pool(a.workers) as pool:
        for d in pool.imap_unordered(day_unit, [(a.root, "ebnerd", d, a.n, SEED) for d in days if d not in done]):
            print("done", d, flush=True)
