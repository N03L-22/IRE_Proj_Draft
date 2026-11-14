"""Generic resumable grid runner (one fit date per unit, as decay.py), for the extension stages. Nothing in the existing files is changed.
Differences from decay.run: the pool window, the fit window and the lags are parameters; a finished CELL is never recomputed (its part.parquet is atomic, so
its existence means it is complete); the corpus loads text only when a scorer needs it; and with --topk each cell also writes part_topk.parquet with the age of
the 10 articles a scorer would show (the experience of the reader, not just the rank of the clicked article).
Same shard format as decay.py, so analyze.py reads the output unchanged. Resume = run the same command again.
Run:  python qrun.py <root> --stage NAME --fits 2023-05-10 2023-05-23 --last 2023-05-24 --out results/NAME --scorers a,b,c
        [--workers 6] [--pool-window-h 48] [--fit-window-days 7] [--lags 1,3,7,13] [--topk] [--cap-gb 8]
"""
import argparse, datetime as dt, glob, multiprocessing as mp, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import polars as pl

import monitor as M
import decay
import extras  # noqa: F401  (registers the extension scorers into decay.ALL; also in every spawned worker)
import genre  # noqa: F401
from cell import build_ctx, fit_all, stratum, day_start
from core import Corpus, ranks_of_target, target_vs_pool
from sample import splitmix64
from scorers import BM25


def load_sample(corpus, day):                      # as cell.load_sample, from the folder named in SAMPLE_DIR (default: sample)
    s = os.path.join(corpus.st, os.environ.get("SAMPLE_DIR", "sample"))
    return (pl.read_parquet(os.path.join(s, f"clicks_d={day}.parquet")).sort(["user", "article", "t"]), pl.read_parquet(os.path.join(s, f"profiles_d={day}.parquet")))


def sample_clicks(corpus, day):                    # number of clicks in a day's sample; None when the file is not there (never treated as a gap)
    p = os.path.join(corpus.st, os.environ.get("SAMPLE_DIR", "sample"), f"clicks_d={day}.parquet")
    return int(pl.scan_parquet(p).select(pl.len()).collect().item()) if os.path.exists(p) else None


def needs_text(scorers):
    def uses(s):
        return isinstance(s, BM25) or any(uses(p) for p in getattr(s, "parts", None) or [])
    return any(uses(s) for s in scorers)


def top10_stats(S, c, r_end):
    """age (hours) of the top-10 articles in each pool, ties broken by the same keyed shuffle as the ranks."""
    n, P = S.shape
    out = {k: np.empty(n, dtype=np.float32) for k in ("age1_h", "med10_h", "over24", "new10", "poolmed_h")}
    for k in range(0, n, 1000):
        sl = slice(k, k + 1000)
        S2 = np.where(np.isnan(S[sl]) | ~c.valid[sl], -np.inf, S[sl])
        with np.errstate(over="ignore"):
            u = splitmix64(c.keys[sl, None] ^ (c.cand_ids[sl].astype(np.uint64) * np.uint64(0xD6E8FEB86659FD93)))
        i1 = np.argsort(u, axis=1, kind="stable")
        s_sorted = np.take_along_axis(S2, i1, axis=1)
        i2 = np.argsort(-s_sorted, axis=1, kind="stable")
        order = np.take_along_axis(i1, i2, axis=1)[:, :10]
        age = (c.t[sl, None] - c.cand_pub[sl]) / 3600.0
        valid = np.take_along_axis(c.valid[sl], order, axis=1)
        a10 = np.where(valid, np.take_along_axis(age, order, axis=1), np.nan)
        new = np.where(valid, np.take_along_axis(c.cand_pub[sl], order, axis=1) >= r_end, np.nan)
        with np.errstate(all="ignore"):
            out["age1_h"][sl] = a10[:, 0]
            out["med10_h"][sl] = np.nanmedian(a10, axis=1)
            out["over24"][sl] = np.nanmean(a10 > 24, axis=1)
            out["new10"][sl] = np.nanmean(new, axis=1)
            out["poolmed_h"][sl] = np.nanmedian(np.where(c.valid[sl], age, np.nan), axis=1)
    return out


def score_cell_ext(corpus, fitted, r_end, d, regime, scorers, clicks, prof, window, topk, cap=None):
    """cell.score_cell plus the top-10 statistics; the rank / scorable / stratum columns are computed exactly as there."""
    c = build_ctx(corpus, clicks, prof, r_end, regime, window, *([cap] if cap else []))
    assert regime != "A" or len(c.t) == 0 or int(c.t.min()) >= r_end, "a click before the fit end: the old profile would contain the click itself"
    out = {"user": c.user, "article": c.target_id, "t": c.t, "n": len(c.t), "n_total": c.n_total, "n_excluded": c.n_excluded, "n_reread": c.n_reread,
           "profile_trunc": c.profile_trunc, "stratum": stratum(corpus, c, r_end, day_start(d) + corpus.off), "pool": c.pool, "scorers": {}}
    tk = {}
    for s in scorers:
        sc = fitted[s.name][0]
        t0 = time.perf_counter()
        S = sc.score(c)
        M.check_finite(np.where(np.isnan(S), 0, S), s.name)
        rk = ranks_of_target(S, c.valid, c.tgt_col, c.keys, c.cand_ids)
        out["scorers"][s.name] = {"rank": rk, "scorable": sc.target_scorable(c), "seconds": time.perf_counter() - t0}
        if topk:
            tk[s.name] = top10_stats(S, c, r_end)
    z = np.full(c.valid.shape, np.nan, dtype=np.float32)
    out["scorers"]["shuffle"] = {"rank": ranks_of_target(z, c.valid, c.tgt_col, c.keys, c.cand_ids), "scorable": np.zeros(len(c.t), dtype=bool), "seconds": 0.0}
    if topk:
        tk["shuffle"] = top10_stats(z, c, r_end)
    return out, tk


def tk_shard(res, tk):
    parts = []
    for regime, d in tk.items():
        base = res[regime]
        for name, s in d.items():
            parts.append(pl.DataFrame({"regime": [regime] * base["n"], "scorer": [name] * base["n"], "user": base["user"], "article": base["article"], "t": base["t"], **s}))
    return pl.concat(parts).sort(["regime", "scorer", "user", "article", "t"])


def fit_unit(a):
    root, r, last, out_dir, names, manifest, stage, pool_w, fit_w, lags, topk, cap, name, first_day, pcap = a
    days = [d for d in decay.days_between(str(dt.date.fromisoformat(r) + dt.timedelta(days=1)), last)
            if (lags is None or (dt.date.fromisoformat(d) - dt.date.fromisoformat(r)).days in lags) and (first_day is None or d >= first_day)]
    cell_path = lambda d: os.path.join(root, out_dir, f"r={r}", f"d={d}", "part.parquet")
    todo = [d for d in days if not os.path.exists(cell_path(d))]
    cells = []
    corpus = Corpus(root, name, load_text=needs_text([decay.ALL[n]() for n in names]))
    scorers = [decay.ALL[n]() for n in names]
    gap = [d for d in days if sample_clicks(corpus, d) == 0]     # a day with no clicks at all (NPR 2023-01-20, 2023-04-27) has nothing to score: no cell
    days = [d for d in days if d not in gap]
    todo = [d for d in todo if d not in gap]
    with M.Unit(stage, f"r={r}", trace_dir=os.path.join(root, out_dir, "trace"), rss_cap_gb=cap, disk_dir=root) as u:
        fitted, r_end, nwin = None, None, None
        if todo:
            with u.phase("fit"):
                fitted, r_end, nwin = fit_all(corpus, r, scorers, window_days=fit_w)
        for d in days:
            f = cell_path(d)
            if d in todo:
                clicks, prof = load_sample(corpus, d)
                with u.phase("score"):
                    res, tks = {}, {}
                    for regime in ("A", "B"):
                        res[regime], tks[regime] = score_cell_ext(corpus, fitted, r_end, d, regime, scorers, clicks, prof, pool_w, topk, pcap)
                u.check()
                df = decay.shard(res, d)
                M.check_finite(df["rank"].to_numpy().astype(np.float64), "rank")
                assert df["rank"].min() >= 1 and (df["rank"] <= df["pool"]).all(), "rank outside 1..pool"
                os.makedirs(os.path.dirname(f), exist_ok=True)
                if topk:
                    tdf = tk_shard(res, tks)
                    M.atomic_write(os.path.join(os.path.dirname(f), "part_topk.parquet"), lambda q, tdf=tdf: tdf.write_parquet(q, compression="zstd"))
                M.atomic_write(f, lambda q, df=df: df.write_parquet(q, compression="zstd"))     # last: its existence marks the cell complete
                extra = {"n_in_pool": res["A"]["n"], "n_excluded": res["A"]["n_excluded"], "n_reread": res["A"]["n_reread"]}
            else:
                x = pl.read_parquet(f, columns=["regime", "scorer", "pool"])
                extra = {"n_in_pool": int(x.filter((pl.col("regime") == "A") & (pl.col("scorer") == names[0])).height), "resumed": True}
            cells.append({"d": d, "rows": int(pl.scan_parquet(f).select(pl.len()).collect().item()), "sha256": M.file_sha256(f), **extra})
        u.extra.update(window_clicks=nwin, cells=cells, scorers=names, pool_window_h=pool_w // 3600, fit_window_days=fit_w, lags=sorted(lags) if lags else None, profile_cap=pcap,
                       fit_seconds={k: round(v[1], 3) for k, v in (fitted or {}).items()})
    M.append_manifest(manifest, u.row)
    return r


def run(root, stage, fits, last, out_dir, names, workers, pool_w, fit_w, lags, topk, cap, name="ebnerd", first_day=None, profile_cap=None):
    os.makedirs(os.path.join(root, out_dir), exist_ok=True)
    mf = os.path.join(root, out_dir, "manifest.jsonl")
    for f in glob.glob(os.path.join(root, out_dir, "**", "*.tmp"), recursive=True):
        os.remove(f)
    done = {r["unit"] for r in M.read_manifest(mf)}
    jobs = [(root, r, last, out_dir, names, mf, stage, pool_w, fit_w, lags, topk, cap, name, first_day, profile_cap) for r in fits if f"r={r}" not in done]
    with mp.get_context("spawn").Pool(min(workers, len(jobs) or 1)) as pool:
        for r in pool.imap_unordered(fit_unit, jobs):
            print("done fit", r, flush=True)
    return len(jobs)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--stage", required=True); ap.add_argument("--fits", nargs=2, required=True); ap.add_argument("--last", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--scorers", required=True); ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--pool-window-h", type=int, default=48); ap.add_argument("--fit-window-days", type=int, default=7)
    ap.add_argument("--lags", default=None); ap.add_argument("--first-day", default=None); ap.add_argument("--sample-dir", default="sample"); ap.add_argument("--profile-cap", type=int, default=None); ap.add_argument("--name", default="ebnerd"); ap.add_argument("--fit-step", type=int, default=1); ap.add_argument("--topk", action="store_true"); ap.add_argument("--cap-gb", type=float, default=8.0)
    a = ap.parse_args()
    os.environ["SAMPLE_DIR"] = a.sample_dir
    lags = None if a.lags is None else {int(x) for x in a.lags.split(",")}
    print(run(a.root, a.stage, decay.days_between(*a.fits)[::a.fit_step], a.last, a.out, a.scorers.split(","), a.workers, a.pool_window_h * 3600, a.fit_window_days, lags, a.topk, a.cap_gb, name=a.name, first_day=a.first_day, profile_cap=a.profile_cap), "units run")
