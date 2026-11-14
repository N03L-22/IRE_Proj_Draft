"""Real-impression evaluation, step 2: the fit-date grid of qrun.py with the candidate set taken from the impression slate (--mode slate) or, for the same
clicks, from the 48 h pool as in the main study (--mode pool). Everything else is unchanged: same scorers, same fit rule (history reads up to the fit date),
same already-read rule (a click whose article is in the reader's own earlier clicks is dropped and history articles are removed from the candidates), same keyed
tie-break; the slate ORDER is used by one scorer only, the site_order baseline (the site's own ranking). Fits 2023-05-17 .. 2023-05-24, evaluation days 2023-05-25 .. 2023-05-31 (lags 1 to 14).
Slate mode also drops a click whose slate has fewer than 2 usable candidates. Resume = run again (cells already on disk are skipped).
Run:  python impr_run.py <root> --stage S8c --out results/impr_slate --scorers a,b --mode slate [--workers 6] [--cap-gb 8]
"""
import argparse, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import polars as pl

import cell
import qrun
from core import HIST_CAP, M_CAP, WINDOW, build_profiles
from sample import click_key

FITS = ("2023-05-17", "2023-05-24")
LAST, FIRST = "2023-05-31", "2023-05-25"


def load_sample_impr(corpus, day):
    s = os.path.join(corpus.st, "impr")
    return pl.read_parquet(os.path.join(s, f"clicks_d={day}.parquet")), pl.read_parquet(os.path.join(s, f"profiles_d={day}.parquet"))


def build_ctx_impr(corpus, clicks, prof, r_end, regime, window=WINDOW, M=M_CAP):
    if os.environ.get("IMPR_MODE") == "pool":
        return cell.build_ctx(corpus, clicks.select("user", "article", "t"), prof, r_end, regime, WINDOW, M)
    c = cell.Ctx()
    c.slate_mode = True
    user = clicks["user"].to_numpy()
    art = clicks["article"].to_numpy().astype(np.int64)
    t = clicks["t"].to_numpy().astype(np.int64)
    slates = clicks["slate"].to_list()
    n, P = len(user), max(len(s) for s in slates)
    ids = np.full((n, P), -1, dtype=np.int64)
    for i, s in enumerate(slates):
        ids[i, :len(s)] = s
    rows = corpus.row(ids)
    pub = np.where(rows >= 0, corpus.pub[np.maximum(rows, 0)], -1)
    valid = (ids >= 0) & (rows >= 0) & (pub >= 0)
    hit = ids == art[:, None]
    tgt = hit.argmax(1)
    has_t = hit.any(1) & valid[np.arange(n), tgt]
    hist, _ = build_profiles(user, t, prof, 0, "B", HIST_CAP)
    reread = (hist == art[:, None]).any(1)
    c.n_reread = int((has_t & reread).sum())
    for k in range(0, n, 500):                                          # history articles leave the candidates (the target is not among them: re-reads are dropped)
        sl = slice(k, k + 500)
        valid[sl] &= ~(ids[sl, :, None] == hist[sl, None, :]).any(2)
    pool = valid.sum(1)
    keep = has_t & ~reread & (pool >= 2)
    c.n_total, c.n_excluded = n, int(n - keep.sum())
    ids0 = int(corpus.article[0])
    c.user, c.t, c.target_id = user[keep], t[keep], art[keep]
    c.target_row = corpus.row(art)[keep]
    c.keys = click_key(user, art, t)[keep]
    c.valid = valid[keep]
    c.cand_ids = np.where(valid, ids, ids0)[keep]
    c.cand_rows = np.where(valid, rows, 0)[keep]
    c.cand_pub = np.where(valid, pub, 0)[keep]
    c.tgt_col, c.pool = tgt[keep], pool[keep]
    pid, trunc = build_profiles(c.user, c.t, prof, r_end, regime, M)
    c.profile_ids, c.profile_trunc = pid, trunc
    c.profile_rows = np.where(pid >= 0, corpus.row(pid), -1)
    c.profile_ids = np.where(c.profile_rows >= 0, pid, -1)
    return c


qrun.load_sample = load_sample_impr          # also runs in every spawned worker (the main module is re-imported there)
qrun.build_ctx = build_ctx_impr

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--stage", required=True); ap.add_argument("--out", required=True); ap.add_argument("--scorers", required=True)
    ap.add_argument("--mode", choices=["slate", "pool"], required=True); ap.add_argument("--workers", type=int, default=4); ap.add_argument("--cap-gb", type=float, default=8.0)
    a = ap.parse_args()
    os.environ["IMPR_MODE"] = a.mode
    print(qrun.run(a.root, a.stage, qrun.decay.days_between(*FITS), LAST, a.out, a.scorers.split(","), a.workers, WINDOW, 7, None, False, a.cap_gb, first_day=FIRST), "units run")
