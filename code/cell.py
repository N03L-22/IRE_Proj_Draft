"""One cell of the decay matrix: fit all scorers at a fit date, score one evaluation day's sampled clicks."""
import datetime as dt, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import polars as pl

import monitor as M
from core import (HIST_CAP, Corpus, candidate_matrix, ranks_of_target, metrics_from_ranks, build_profiles, WINDOW, M_CAP)
from sample import click_key, SEED
from scorers import Recency, Popularity, Meaning, BM25, CoClick


def day_start(day):
    return int(dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp())


class Ctx:
    pass


def load_sample(corpus, day):
    s = os.path.join(corpus.st, "sample")
    return (pl.read_parquet(os.path.join(s, f"clicks_d={day}.parquet")).sort(["user", "article", "t"]),
            pl.read_parquet(os.path.join(s, f"profiles_d={day}.parquet")))


def build_ctx(corpus, clicks, prof, r_end, regime, window=WINDOW, M=M_CAP):
    c = Ctx()
    user, art, t = clicks["user"].to_numpy(), clicks["article"].to_numpy().astype(np.int64), clicks["t"].to_numpy().astype(np.int64)
    lo, hi = corpus.pools(t, window)
    trow = corpus.row(art)
    tpos = np.where(trow >= 0, corpus.pos_of_row[np.maximum(trow, 0)], -1)
    inpool = (tpos >= lo) & (tpos < hi) & (trow >= 0)
    # already-read rule (the same for every cell, scorer and regime): history = the user's clicks strictly before t. A click whose
    # target is in its history is a re-read and is left out; history articles are removed from the click's candidate pool.
    hist, _ = build_profiles(user, t, prof, 0, "B", HIST_CAP)
    reread = (hist == art[:, None]).any(1)
    keep = np.where(inpool & ~reread)[0]
    c.n_reread = int((inpool & reread).sum())
    c.n_total, c.n_excluded = len(t), int(len(t) - len(keep))
    user, art, t, lo, hi, tpos, trow = user[keep], art[keep], t[keep], lo[keep], hi[keep], tpos[keep], trow[keep]
    c.user, c.t, c.target_id, c.target_row = user, t, art, trow
    c.keys = click_key(user, art, t)
    c.cand_ids, c.cand_rows, c.valid = candidate_matrix(corpus, lo, hi)
    hist = hist[keep]
    for k in range(0, len(keep), 500):                                  # chunked: (rows, pool, history) booleans
        sl = slice(k, k + 500)
        c.valid[sl] &= ~(c.cand_ids[sl, :, None] == hist[sl, None, :]).any(2)
    c.cand_pub = corpus.sorted_pub[np.minimum(lo[:, None] + np.arange(c.valid.shape[1]), len(corpus.sorted_pub) - 1)]
    c.tgt_col = tpos - lo
    c.pool = c.valid.sum(1)
    pid, trunc = build_profiles(user, t, prof, r_end, regime, M)
    c.profile_ids, c.profile_trunc = pid, trunc
    c.profile_rows = np.where(pid >= 0, corpus.row(pid), -1)
    c.profile_ids = np.where(c.profile_rows >= 0, pid, -1)
    return c


def stratum(corpus, c, r_end, d_start):
    """0 = published by the end of fit day r (seen), 1 = after r and before day d (missed), 2 = on day d (new today)."""
    p = corpus.pub[c.target_row]
    return np.where(p < r_end, 0, np.where(p < d_start, 1, 2)).astype(np.int8)


def fit_all(corpus, r, scorers, window_days=7):
    r_end = day_start(r) + 86400 + corpus.off
    d0 = str(dt.date.fromisoformat(r) - dt.timedelta(days=window_days - 1))
    win = corpus.window_clicks(d0, r)
    st = {}
    for s in scorers:
        t0 = time.perf_counter()
        kw = dict(win_user=win["user"].to_numpy(), win_article=win["article"].to_numpy().astype(np.int64), r_end_t=r_end)
        st[s.name] = (s.fit(corpus, **kw), time.perf_counter() - t0)
    return st, r_end, win.height


def score_cell(corpus, fitted, r_end, d, regime, scorers, clicks, prof, window=WINDOW, d_start=None):
    c = build_ctx(corpus, clicks, prof, r_end, regime, window)
    out = {"user": c.user, "article": c.target_id, "t": c.t, "n": len(c.t), "n_total": c.n_total, "n_excluded": c.n_excluded, "n_reread": c.n_reread, "profile_trunc": c.profile_trunc,
           "stratum": stratum(corpus, c, r_end, day_start(d) + corpus.off if d_start is None else d_start), "pool": c.pool, "scorers": {}}
    for s in scorers:
        sc = fitted[s.name][0]
        t0 = time.perf_counter()
        S = sc.score(c)
        M.check_finite(np.where(np.isnan(S), 0, S), s.name)
        rk = ranks_of_target(S, c.valid, c.tgt_col, c.keys, c.cand_ids)
        out["scorers"][s.name] = {"rank": rk, "scorable": sc.target_scorable(c), "seconds": time.perf_counter() - t0}
    z = np.full(c.valid.shape, np.nan, dtype=np.float32)            # the seeded shuffle: nothing is scorable
    out["scorers"]["shuffle"] = {"rank": ranks_of_target(z, c.valid, c.tgt_col, c.keys, c.cand_ids),
                                 "scorable": np.zeros(len(c.t), dtype=bool), "seconds": 0.0}
    return out
