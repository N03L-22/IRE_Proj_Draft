"""T2: the fixed evaluation sample and the profile slices (option D, click-forward).

For each evaluation day d a click is eligible when its article has a publish time and the click is 0..72 h after it.
Exactly N eligible clicks are kept, chosen by KEY, not by a random stream: the N smallest values of
splitmix64(mix(user, article, t) xor seed). That choice is order-independent and identical for any worker count.
For every sampled user the slice also holds their last CAP clicks before the end of day d (regime A and B are
computed later by a time mask), and the manifest counts every click that was not eligible.
Writes <root>/data/<name>/store/sample/{clicks_d=DAY.parquet, profiles_d=DAY.parquet} and sample_manifest.jsonl.
Run:  python sample.py <root> ebnerd 2023-05-11 2023-05-24 [--n 20000] [--workers 7]
"""
import argparse, datetime as dt, glob, json, multiprocessing as mp, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import polars as pl

import monitor as M

SEED = 20261029
WINDOW_H = 72
CAP = 300
U64 = np.uint64


def splitmix64(x):
    x = x.astype(U64)
    with np.errstate(over="ignore"):
        x = x + U64(0x9E3779B97F4A7C15)
        z = x
        z = (z ^ (z >> U64(30))) * U64(0xBF58476D1CE4E5B9)
        z = (z ^ (z >> U64(27))) * U64(0x94D049BB133111EB)
        return z ^ (z >> U64(31))


def click_key(user, article, t, seed=SEED):
    with np.errstate(over="ignore"):
        x = (user.astype(U64) * U64(0x9E3779B97F4A7C15)) ^ (article.astype(U64) * U64(0xC2B2AE3D27D4EB4F)) \
            ^ (t.astype(np.int64).astype(U64) * U64(0x165667B19E3779F9))
    return splitmix64(x ^ U64(seed))


def choose(c, n, seed=SEED):
    """c: polars frame with user, article, t. Returns the row positions of the n smallest keys (ties by values)."""
    k = click_key(c["user"].to_numpy(), c["article"].to_numpy(), c["t"].to_numpy(), seed)
    if len(k) <= n:
        return np.arange(len(k))
    order = np.lexsort((c["t"].to_numpy(), c["article"].to_numpy(), c["user"].to_numpy(), k))
    return np.sort(order[:n])


def day_unit(args):
    root, name, day, n, seed = args[:5]
    src_only = len(args) > 5 and args[5]
    st = os.path.join(root, f"data/{name}/store")
    out = os.path.join(st, "sample")
    os.makedirs(out, exist_ok=True)
    with M.Unit("t2", day, trace_dir=os.path.join(st, "trace"), rss_cap_gb=4, disk_dir=st) as u:
        with u.phase("read"):
            c = pl.read_parquet(glob.glob(os.path.join(st, "clicks_by_day", f"day={day}", "*.parquet")))
        total = c.height
        no_pub = int(c["pub"].is_null().sum())
        age = (c["t"].cast(pl.Int64) - c["pub"].cast(pl.Int64))
        neg = int((age < 0).sum())
        old = int((age > WINDOW_H * 3600).sum())
        ok = (age >= 0) & (age <= WINDOW_H * 3600)
        if src_only:                         # NPR: the evaluation clicks are the clicks of the impressions (src 1)
            ok = ok & (c["src"] == 1)
        elig = c.filter(ok).sort(["user", "article", "t"])
        with u.phase("choose"):
            pos = choose(elig, n, seed)
            s = elig[pos]
        u.check()
        end = int(dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp()) + 86400
        users = s["user"].unique()
        with u.phase("profiles"):
            files = [f for d in sorted(glob.glob(os.path.join(st, "clicks_by_day", "day=*"))) if d.split("=")[1] <= day
                     for f in glob.glob(os.path.join(d, "*.parquet"))]
            p = (pl.scan_parquet(files).select("user", "article", "t").filter(pl.col("user").is_in(users.implode()))
                 .collect(engine="streaming")
                 .sort(["user", "t", "article"]).group_by("user", maintain_order=True).tail(CAP))
        u.check()
        with u.phase("write"):
            M.atomic_write(os.path.join(out, f"clicks_d={day}.parquet"), lambda q: s.write_parquet(q, compression="zstd"))
            M.atomic_write(os.path.join(out, f"profiles_d={day}.parquet"), lambda q: p.write_parquet(q, compression="zstd"))
        u.extra.update(clicks_total=total, no_pub=no_pub, negative_age=neg, older_than_window=old, eligible=elig.height,
                       sampled=s.height, profile_rows=p.height, users=int(users.len()),
                       sample_sha256=M.file_sha256(os.path.join(out, f"clicks_d={day}.parquet")),
                       profile_sha256=M.file_sha256(os.path.join(out, f"profiles_d={day}.parquet")), seed=seed, n=n)
    M.append_manifest(os.path.join(out, "sample_manifest.jsonl"), u.row)
    return day


def run(root, name, d0, d1, n=20000, workers=7, seed=SEED, src_only=False):
    out = os.path.join(root, f"data/{name}/store/sample")
    os.makedirs(out, exist_ok=True)
    for f in glob.glob(os.path.join(out, "*.tmp")):
        os.remove(f)
    a, b = dt.date.fromisoformat(d0), dt.date.fromisoformat(d1)
    days = [str(a + dt.timedelta(days=i)) for i in range((b - a).days + 1)]
    done = {r["unit"] for r in M.read_manifest(os.path.join(out, "sample_manifest.jsonl"))}
    todo = [(root, name, d, n, seed, src_only) for d in days if d not in done]
    with mp.get_context("spawn").Pool(workers) as pool:
        for d in pool.imap_unordered(day_unit, todo):
            print("done", d, flush=True)
    return days


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("name"); ap.add_argument("d0"); ap.add_argument("d1")
    ap.add_argument("--n", type=int, default=20000); ap.add_argument("--workers", type=int, default=7)
    ap.add_argument("--src-only", action="store_true")
    a = ap.parse_args()
    print(run(a.root, a.name, a.d0, a.d1, a.n, a.workers, src_only=a.src_only))
