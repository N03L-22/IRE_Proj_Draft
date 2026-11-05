"""T1b (NPR) and T1c (Adressa): compact click stores in the same shape as the EB-NeRD store.

  <root>/data/<name>/store/articles.parquet                    article Int32, pub Int32 (epoch s, UTC), text, category
  <root>/data/<name>/store/clicks_by_day/day=YYYY-MM-DD/part-NN.parquet   user UInt32, article Int32, t Int32, pub Int32
  <root>/data/<name>/store/manifest.jsonl, ids_users.parquet, ids_articles.parquet

Ids are mapped to integers by the sorted order of the full id set (deterministic). The day is the dataset's own
local day: NPR UTC minus 3 h (Brasilia), Adressa the day file (Norwegian local time). NPR clicks are the clicked item
of each impression (src = 1) plus the timestamped history lists, de-duplicated (src = 0).
Run:  python other_stores.py <root> npr|adressa [--workers 8]
"""
import argparse, glob, json, multiprocessing as mp, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import polars as pl

import monitor as M

CAP_GB = 2.0


def save(df, path):
    M.atomic_write(path, lambda p: df.write_parquet(p, compression="zstd"))


def write_days(st, g, part, u):
    """g has columns day, user, article, t, pub; one file per day."""
    n = 0
    for (day,), x in g.partition_by("day", as_dict=True, maintain_order=False).items():
        d = os.path.join(st, "clicks_by_day", f"day={day}")
        os.makedirs(d, exist_ok=True)
        cols = ["user", "article", "t", "pub"] + (["src"] if "src" in x.columns else [])
        x = x.drop("day").select(cols).sort(["t", "user", "article"])
        M.check_finite(x["t"].to_numpy(), "t")
        save(x, os.path.join(d, f"part-{part}.parquet"))
        n += 1
    return n


def clean(st):
    for dp, _, fs in os.walk(st):
        for f in fs:
            if f.endswith(".tmp"):
                os.remove(os.path.join(dp, f))


# ----------------------------------------------------------------------------- NPR
def npr_unit(args):
    raw, st, f, i, manifest = args
    with M.Unit("t1b", f"file{i}", trace_dir=os.path.join(st, "trace"), rss_cap_gb=CAP_GB, disk_dir=st) as u:
        with u.phase("read"):
            b = pl.read_parquet(f, columns=["userId", "impressionTimestamp", "clickedItem", "history", "timestampHistory"])
            um = pl.read_parquet(os.path.join(st, "ids_users.parquet"))
            am = pl.read_parquet(os.path.join(st, "ids_articles.parquet"))
            ar = pl.read_parquet(os.path.join(st, "articles.parquet"), columns=["article", "pub"])
        u.check()
        with u.phase("clicks"):
            imp = (b.select("userId", pl.col("clickedItem").alias("a"), (pl.col("impressionTimestamp") // 1000).alias("t"))
                   .drop_nulls().with_columns(pl.lit(1, dtype=pl.Int8).alias("src")))
            his = (b.select("userId", pl.col("history").alias("a"), (pl.col("timestampHistory")).alias("t"))
                   .explode(["a", "t"]).drop_nulls().with_columns((pl.col("t") // 1000))
                   .unique(subset=["userId", "a", "t"]).with_columns(pl.lit(0, dtype=pl.Int8).alias("src")))
            n_hist, n_imp = his.height, imp.height
            c = pl.concat([his, imp]).sort("src", descending=True).unique(subset=["userId", "a", "t"], keep="first")
            dup = n_hist + n_imp - c.height
            c = (c.join(um, on="userId", how="inner").join(am, left_on="a", right_on="id", how="inner")
                 .join(ar, on="article", how="left")
                 .with_columns(pl.col("t").cast(pl.Int32), pl.col("user").cast(pl.UInt32),
                               pl.from_epoch(pl.col("t") - 3 * 3600, time_unit="s").dt.date().alias("day")))
        u.check()
        with u.phase("write"):
            files = write_days(st, c, f"{i:02d}", u)
        u.extra.update(rows_in=n_hist + n_imp, rows_out=c.height, duplicates=dup, impression_clicks=n_imp, files=files)
    M.append_manifest(manifest, u.row)
    return i


def merge_day(args):
    """Users span the input files, so exact duplicates across parts are removed per day (days are independent)."""
    day_dir, = args
    parts = sorted(glob.glob(os.path.join(day_dir, "part-*.parquet")))
    if len(parts) == 1 and parts[0].endswith("part-00.parquet"):
        return 0, 0
    c = pl.concat([pl.read_parquet(p) for p in parts])
    n0 = c.height
    if "src" in c.columns:      # an impression click (src 1) wins over the same event seen in a history list
        c = c.sort("src", descending=True)
    c = c.unique(subset=["user", "article", "t"], keep="first").sort(["t", "user", "article"])
    out = os.path.join(day_dir, "merged.parquet")
    save(c, out)
    for p in parts:
        os.remove(p)
    os.replace(out, os.path.join(day_dir, "part-00.parquet"))
    return n0, c.height


def npr(root, workers):
    raw = os.path.join(root, "data/npr/raw")
    st = os.path.join(root, "data/npr/store")
    os.makedirs(st, exist_ok=True)
    clean(st)
    a = pl.read_parquet(os.path.join(raw, "articles/articles/articles_wobody_wourl.parquet"))
    a = a.sort("newsId").with_row_index("article").with_columns(pl.col("article").cast(pl.Int32))
    art = a.select("article", (pl.col("publishDate").dt.epoch("s")).cast(pl.Int32).alias("pub"),
                   pl.col("title").fill_null("").alias("text"), pl.col("topics").list.first().alias("category"))
    save(art, os.path.join(st, "articles.parquet"))
    save(a.select(pl.col("newsId").alias("id"), "article"), os.path.join(st, "ids_articles.parquet"))
    files = sorted(glob.glob(os.path.join(raw, "behaviors/behaviors_*.parquet")))
    users = pl.concat([pl.read_parquet(f, columns=["userId"]).unique() for f in files]).unique().sort("userId")
    users = users.with_row_index("user").with_columns(pl.col("user").cast(pl.UInt32))
    save(users, os.path.join(st, "ids_users.parquet"))
    manifest = os.path.join(st, "manifest.jsonl")
    done = {r["unit"] for r in M.read_manifest(manifest)}
    todo = [(raw, st, f, i, manifest) for i, f in enumerate(files) if f"file{i}" not in done]
    for _, _, _, i, _ in todo:
        for dp, _, fs in os.walk(os.path.join(st, "clicks_by_day")):
            for fn in fs:
                if fn == f"part-{i:02d}.parquet":
                    os.remove(os.path.join(dp, fn))
    with mp.get_context("spawn").Pool(min(workers, len(todo) or 1)) as p:
        for i in p.imap_unordered(npr_unit, todo):
            print("done file", i, flush=True)
    days = sorted(glob.glob(os.path.join(st, "clicks_by_day", "day=*")))
    with mp.get_context("spawn").Pool(workers) as p:
        res = p.map(merge_day, [(d,) for d in days])
    removed = sum(a - b for a, b in res)
    M.append_manifest(manifest, {"stage": "t1b", "unit": "merge_days", "status": "ok", "duplicates_removed_across_files": removed})
    print("cross-file duplicates removed", removed)
    return len(files)


# ----------------------------------------------------------------------------- Adressa
def adressa_day(args):
    raw, st, day, files, manifest = args
    with M.Unit("t1c", day, trace_dir=os.path.join(st, "trace"), rss_cap_gb=CAP_GB, disk_dir=st) as u:
        with u.phase("read"):
            c = (pl.scan_parquet(files).filter(pl.col("id").is_not_null())
                 .select("userId", pl.col("id").alias("a"), pl.col("time").cast(pl.Int64).alias("t"),
                         pl.col("publishtime").str.to_datetime("%Y-%m-%dT%H:%M:%S%.fZ", time_zone="UTC", strict=False)
                         .dt.epoch("s").alias("pubs")).collect())
            um = pl.read_parquet(os.path.join(st, "ids_users.parquet"))
            am = pl.read_parquet(os.path.join(st, "ids_articles.parquet"))
        u.check()
        n_in = c.height
        with u.phase("join"):
            c = (c.join(um, on="userId", how="inner").join(am, left_on="a", right_on="id", how="inner")
                 .select("user", "article", pl.col("t").cast(pl.Int32), pl.col("pubs").cast(pl.Int32).alias("pub")))
            c = c.unique(subset=["user", "article", "t"])     # a day holds every event of its (user, article, second)
            c = c.with_columns(pl.lit(day).str.strptime(pl.Date, "%Y%m%d").alias("day"))
        u.check()
        with u.phase("write"):
            write_days(st, c, "00", u)
        u.extra.update(rows_in=n_in, rows_out=c.height, duplicates=n_in - c.height, files=1)
    M.append_manifest(manifest, u.row)
    return day


def adressa(root, workers):
    pq = os.path.join(root, "data/adressa/parquet")
    st = os.path.join(root, "data/adressa/store")
    os.makedirs(st, exist_ok=True)
    clean(st)
    allf = sorted(glob.glob(os.path.join(pq, "*.parquet")))
    byday = {}
    for f in allf:
        m = re.search(r"/(\d{8})-\d+\.parquet$", f)
        byday.setdefault(m.group(1), []).append(f)
    lf = pl.scan_parquet(allf).filter(pl.col("id").is_not_null())
    # ids: sorted order of the full id sets, one pass over three columns
    u = lf.select("userId").unique().sort("userId").collect(engine="streaming")
    u = u.with_row_index("user").with_columns(pl.col("user").cast(pl.UInt32))
    save(u, os.path.join(st, "ids_users.parquet"))
    ev = (lf.select(pl.col("id"), pl.col("time").cast(pl.Int64), pl.col("title"), pl.col("category1"),
                    pl.col("publishtime").str.to_datetime("%Y-%m-%dT%H:%M:%S%.fZ", time_zone="UTC", strict=False)
                    .dt.epoch("s").alias("pubs")).collect(engine="streaming").sort(["id", "time"]))
    art = (ev.group_by("id", maintain_order=True)
           .agg(pl.col("pubs").drop_nulls().last().alias("pub"), pl.col("title").drop_nulls().last().alias("text"),
                pl.col("category1").drop_nulls().last().alias("category"))
           .sort("id").with_row_index("article").with_columns(pl.col("article").cast(pl.Int32)))
    del ev
    save(art.select(pl.col("id"), "article"), os.path.join(st, "ids_articles.parquet"))
    save(art.select("article", pl.col("pub").cast(pl.Int32), pl.col("text").fill_null(""), "category"), os.path.join(st, "articles.parquet"))
    manifest = os.path.join(st, "manifest.jsonl")
    done = {r["unit"] for r in M.read_manifest(manifest)}
    todo = [(pq, st, d, fs, manifest) for d, fs in sorted(byday.items()) if d not in done]
    for _, _, d, _, _ in todo:
        p = os.path.join(st, "clicks_by_day", f"day={d[:4]}-{d[4:6]}-{d[6:]}", "part-00.parquet")
        if os.path.exists(p):
            os.remove(p)
    with mp.get_context("spawn").Pool(workers) as p:
        for d in p.imap_unordered(adressa_day, todo):
            pass
    return len(byday)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("which", choices=["npr", "adressa"])
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    t = time.time()
    n = npr(a.root, a.workers) if a.which == "npr" else adressa(a.root, a.workers)
    print(a.which, "units", n, "seconds", round(time.time() - t))
