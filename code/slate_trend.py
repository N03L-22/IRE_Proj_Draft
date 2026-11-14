"""Live trending on real impression slates (the gap left by impr_run.py: the history store that feeds the Trend scorer ends 2023-05-25 06:59, while the slates are
2023-05-25 07:00 .. 05-31). The click stream for these days is every click in the validation impressions (all readers of the cohort, article_ids_clicked at impression_time),
joined to the history reads up to 06:59 so that a window which starts before 07:00 on 25 May is complete. A candidate's score is its number of clicks in the window before
the click (strictly before t; the click itself is never counted); nothing is fitted, so one fit date (2023-05-24) covers every day. Same clicks, slates, already-read rule
and tie-break as impr_run.py --mode slate, so the ranks pair with results/impr_slate click for click. The stream has fewer clicks than the history reads used on the
pool (see results/s17_trend_slate/index.json), which is stated wherever the number is quoted.
Run:  python slate_trend.py <root> [--stage S17] [--out results/s17_trend_slate] [--scorers a,b] [--cap-gb 8]
"""
import argparse, glob, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import polars as pl

import extras
import impr_run                      # patches qrun.load_sample and qrun.build_ctx for slate mode (also in every spawned worker)
import qrun
from core import WINDOW

NAMES = "recency,trend_w10,trend_w30,trend_h1,trend_h3,trend_h24,trend_h1_d30"
HISTORY_DAYS = ("2023-05-24", "2023-05-25")
_IDX = {}


def clicks_path(st):
    return os.path.join(st, "impr", "trend_clicks.parquet")


def build_clicks(root):
    """(article, t) of the click stream: history reads of 24-25 May (the store ends 25 May 06:59) plus every validation impression click from 25 May. Atomic; skipped when present."""
    st = os.path.join(root, "data/ebnerd/store")
    out = clicks_path(st)
    if os.path.exists(out):
        return out
    hist = (pl.scan_parquet([f for d in HISTORY_DAYS for f in glob.glob(os.path.join(st, "clicks_by_day", f"day={d}", "*.parquet"))])
              .select(pl.col("article").cast(pl.Int32), pl.col("t").cast(pl.Int64)).collect(engine="streaming"))
    beh = pl.scan_parquet(os.path.join(root, "data/ebnerd/large/validation/behaviors.parquet")).select("impression_time", "article_ids_clicked")
    imp = (beh.filter(pl.col("impression_time") >= pl.lit("2023-05-25").str.to_datetime())
              .select(pl.col("impression_time").dt.epoch("s").cast(pl.Int64).alias("t"), pl.col("article_ids_clicked").alias("article"))
              .explode("article").drop_nulls("article").select(pl.col("article").cast(pl.Int32), "t").collect(engine="streaming"))
    assert hist["t"].max() < imp["t"].min(), "the history reads and the impression clicks overlap in time"
    allc = pl.concat([hist, imp])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    allc.write_parquet(out + ".tmp", compression="zstd")
    os.replace(out + ".tmp", out)
    meta = {"history_rows": hist.height, "history_last_t": int(hist["t"].max()), "impression_rows": imp.height, "impression_first_t": int(imp["t"].min()), "impression_last_t": int(imp["t"].max())}
    os.makedirs(os.path.join(root, "results/s17_trend_slate"), exist_ok=True)
    json.dump(meta, open(os.path.join(root, "results/s17_trend_slate/index.json"), "w"), indent=1)
    return out


def slate_index(st, d0, d1):
    """replaces extras._click_index: composite sorted keys (article << 31) + (t - T0) of the click stream above (the day range asked for is ignored: the file holds exactly 24 May - 31 May)."""
    if "K" not in _IDX:
        c = pl.read_parquet(clicks_path(st))
        t = c["t"].to_numpy().astype(np.int64)
        t0 = int(t.min())
        k = (c["article"].to_numpy().astype(np.int64) << 31) + (t - t0)
        k.sort()
        _IDX.update(K=k, T0=t0)
    return _IDX["K"], _IDX["T0"]


extras._click_index = slate_index

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--stage", default="S17"); ap.add_argument("--out", default="results/s17_trend_slate")
    ap.add_argument("--scorers", default=NAMES); ap.add_argument("--cap-gb", type=float, default=8.0)
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    build_clicks(root)
    print(qrun.run(root, a.stage, ["2023-05-24"], impr_run.LAST, a.out, a.scorers.split(","), 1, WINDOW, 7, None, False, a.cap_gb, first_day=impr_run.FIRST), "units run")
