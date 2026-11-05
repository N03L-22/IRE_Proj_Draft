"""T1a: compact store for EB-NeRD large (option D: the validation users' history clicks).

Reads  <root>/data/ebnerd/large/{articles.parquet, validation/history.parquet}
Writes <root>/data/ebnerd/store/{articles.parquet, clicks_by_day/day=YYYY-MM-DD/part-NN.parquet,
                                 manifest.jsonl, input_report.json}

A unit is a fixed slice of the history rows (users never span slices), so the output does not depend on the
number of workers. Each part is sorted by (t, user, article). The day is the calendar date of the stored timestamp.
Run:  python ebnerd_store.py <project_root> [--workers 8] [--slices 16]
"""
import argparse, json, multiprocessing as mp, os, shutil, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # this code folder, so that `python -I` still finds monitor

import polars as pl

import monitor as M

SLICES = 16
CAP_GB = 2.0


def paths(root):
    raw = os.path.join(root, "data/ebnerd/large")
    st = os.path.join(root, "data/ebnerd/store")
    return raw, st


def build_articles(raw, st):
    a = pl.read_parquet(os.path.join(raw, "articles.parquet"),
                        columns=["article_id", "title", "subtitle", "published_time", "category"])
    n0 = a.height
    a = a.with_columns(
        pl.col("published_time").dt.epoch("s").cast(pl.Int64).alias("pub_raw"),
        (pl.col("title").fill_null("") + " " + pl.col("subtitle").fill_null("")).str.strip_chars().alias("text"))
    # an implausible publish year (the 1993 outlier) becomes a null publish time, and is counted
    bad = a.filter(pl.col("published_time").dt.year() < 2000).height
    a = a.with_columns(pl.when(pl.col("published_time").dt.year() < 2000).then(None).otherwise(pl.col("pub_raw"))
                       .cast(pl.Int32).alias("pub"))
    out = a.select(pl.col("article_id").alias("article"), "pub", "text", "category").sort("article")
    assert out["article"].n_unique() == out.height, "duplicate article ids"
    M.atomic_write(os.path.join(st, "articles.parquet"), lambda p: out.write_parquet(p, compression="zstd"))
    return {"articles": n0, "implausible_publish_year": bad, "null_publish_time": int(out["pub"].null_count())}


def slice_bounds(n_rows, slices):
    step = -(-n_rows // slices)
    return [(i, i * step, min(step, n_rows - i * step)) for i in range(slices) if i * step < n_rows]


def process_slice(args):
    raw, st, i, off, n, manifest = args
    unit = f"slice{i:02d}"
    with M.Unit("t1a", unit, trace_dir=os.path.join(st, "trace"), manifest=None, rss_cap_gb=CAP_GB, disk_dir=st) as u:
        with u.phase("read"):
            h = (pl.scan_parquet(os.path.join(raw, "validation/history.parquet"))
                 .select(pl.col("user_id").alias("user"), pl.col("article_id_fixed").alias("article"),
                         pl.col("impression_time_fixed").alias("ts"))
                 .slice(off, n).collect())
        u.check()
        with u.phase("explode"):
            c = h.explode(["article", "ts"]).with_columns(
                pl.col("ts").dt.epoch("s").cast(pl.Int32).alias("t")).drop("ts")
            n_in = c.height
            c = c.drop_nulls().unique(subset=["user", "article", "t"])
            dup = n_in - c.height
        u.check()
        arts = pl.read_parquet(os.path.join(st, "articles.parquet"), columns=["article", "pub"])
        with u.phase("join"):
            c = c.join(arts, on="article", how="left").with_columns(pl.col("article").cast(pl.Int32))
            c = c.with_columns(pl.from_epoch(pl.col("t").cast(pl.Int64), time_unit="s").dt.date().alias("day"))
        u.check()
        files = 0
        with u.phase("write"):
            for (day,), g in c.partition_by("day", as_dict=True, maintain_order=False).items():
                d = os.path.join(st, "clicks_by_day", f"day={day}")
                os.makedirs(d, exist_ok=True)
                g = g.drop("day").select("user", "article", "t", "pub").sort(["t", "user", "article"])
                M.check_finite(g["t"].to_numpy(), "t")
                M.atomic_write(os.path.join(d, f"part-{i:02d}.parquet"), lambda p, g=g: g.write_parquet(p, compression="zstd"))
                files += 1
        u.extra.update(rows_in=n_in, rows_out=c.height, duplicates=dup, files=files, users=int(h.height))
    M.append_manifest(manifest, u.row)
    return unit


def clean_partials(st):
    for dp, _, fs in os.walk(st):
        for f in fs:
            if f.endswith(".tmp"):
                os.remove(os.path.join(dp, f))


def build(root, workers=8, slices=SLICES):
    raw, st = paths(root)
    os.makedirs(st, exist_ok=True)
    clean_partials(st)
    manifest = os.path.join(st, "manifest.jsonl")
    done = {r["unit"] for r in M.read_manifest(manifest)}
    arts = build_articles(raw, st)
    n_rows = pl.scan_parquet(os.path.join(raw, "validation/history.parquet")).select(pl.len()).collect().item()
    todo = [(raw, st, i, off, n, manifest) for i, off, n in slice_bounds(n_rows, slices) if f"slice{i:02d}" not in done]
    # a finished-looking slice must not exist as parts without a manifest line: remove such parts first
    for _, _, i, _, _, _ in todo:
        for dp, _, fs in os.walk(os.path.join(st, "clicks_by_day")):
            for f in fs:
                if f == f"part-{i:02d}.parquet":
                    os.remove(os.path.join(dp, f))
    t = time.time()
    ctx = mp.get_context("spawn")
    with ctx.Pool(workers) as pool:
        for u in pool.imap_unordered(process_slice, todo):
            print("done", u, round(time.time() - t), "s", flush=True)
    rows = M.read_manifest(manifest)
    assert {r["unit"] for r in rows} == {f"slice{i:02d}" for i, _, _ in slice_bounds(n_rows, slices)}, "incomplete"
    return arts, rows, n_rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--slices", type=int, default=SLICES)
    a = ap.parse_args()
    arts, rows, n_rows = build(a.root, a.workers, a.slices)
    print(json.dumps(arts), "units", len(rows), "history rows", n_rows)
