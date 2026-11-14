"""Sample-size and seed sensitivity: the evaluation sample of sample.py with another seed and/or size, written to data/<name>/store/sample_<tag>/.
Identical rules to sample.py (eligible = article with a publish time, click 0..72 h after it; the N smallest splitmix64 keys; profile slice = the user's last 300 clicks up to the end
of the day). The same seed with a larger N contains the original sample (the N smallest keys are nested). Resume: days whose two files exist are skipped.
Run:  python sample_alt.py <root> <name> <d0> <d1> --tag s11 --n 20000 --seed 11 [--workers 4]
"""
import argparse, datetime as dt, glob, multiprocessing as mp, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import polars as pl

import monitor as M
from sample import CAP, WINDOW_H, choose


def day_unit(a):
    root, name, day, n, seed, tag = a
    st = os.path.join(root, f"data/{name}/store")
    out = os.path.join(st, f"sample_{tag}")
    os.makedirs(out, exist_ok=True)
    fc, fp = os.path.join(out, f"clicks_d={day}.parquet"), os.path.join(out, f"profiles_d={day}.parquet")
    if os.path.exists(fc) and os.path.exists(fp):
        return day
    with M.Unit("sample_alt", f"{tag}:{day}", trace_dir=os.path.join(st, "trace"), rss_cap_gb=4, disk_dir=st):
        c = pl.read_parquet(glob.glob(os.path.join(st, "clicks_by_day", f"day={day}", "*.parquet")))
        age = c["t"].cast(pl.Int64) - c["pub"].cast(pl.Int64)
        elig = c.filter((age >= 0) & (age <= WINDOW_H * 3600)).sort(["user", "article", "t"])
        s = elig[choose(elig, n, seed)]
        users = s["user"].unique()
        files = [f for d in sorted(glob.glob(os.path.join(st, "clicks_by_day", "day=*"))) if d.split("=")[1] <= day for f in glob.glob(os.path.join(d, "*.parquet"))]
        p = (pl.scan_parquet(files).select("user", "article", "t").filter(pl.col("user").is_in(users.implode())).collect(engine="streaming")
             .sort(["user", "t", "article"]).group_by("user", maintain_order=True).tail(CAP))
        M.atomic_write(fp, lambda q: p.write_parquet(q, compression="zstd"))
        M.atomic_write(fc, lambda q: s.write_parquet(q, compression="zstd"))      # last: marks the day complete
    return day


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("name"); ap.add_argument("d0"); ap.add_argument("d1")
    ap.add_argument("--tag", required=True); ap.add_argument("--n", type=int, required=True); ap.add_argument("--seed", type=int, required=True); ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    x, y = dt.date.fromisoformat(a.d0), dt.date.fromisoformat(a.d1)
    days = [str(x + dt.timedelta(days=i)) for i in range((y - x).days + 1)]
    for f in glob.glob(os.path.join(a.root, f"data/{a.name}/store/sample_{a.tag}", "*.tmp")):
        os.remove(f)
    with mp.get_context("spawn").Pool(a.workers) as pool:
        for d in pool.imap_unordered(day_unit, [(a.root, a.name, d, a.n, a.seed, a.tag) for d in days]):
            print("done", d, flush=True)
