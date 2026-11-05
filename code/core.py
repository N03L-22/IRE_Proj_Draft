"""T4 core: the corpus (articles in publish order), candidate pools, profiles, ranking and metrics (option D).

A click (user, article, t) is scored by ranking its article among the pool: articles published at or before t and
within WINDOW seconds before t. The pool is a contiguous range of the publish-sorted article list, defined from
publish times only. Unscorable candidates tie; ties are broken by a hash keyed by the click and the candidate, so a
tie is random but identical on every run and for every worker count.
"""
import glob, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import polars as pl

from sample import splitmix64, click_key, SEED

U64 = np.uint64
WINDOW = 48 * 3600
M_CAP = 50
HIST_CAP = 300        # the already-read history is the whole profile slice


class Corpus:
    def __init__(self, root, name, load_text=False, clicked_only=False):
        self.root, self.name = root, name
        self.off = 3 * 3600 if name == "npr" else 0      # a local day starts this many seconds after UTC midnight (NPR: UTC-3)
        self.st = os.path.join(root, f"data/{name}/store")
        a = pl.read_parquet(os.path.join(self.st, "articles.parquet"), columns=["article", "pub"] + (["text"] if load_text else []))
        a = a.sort("article")
        self.article = a["article"].to_numpy().astype(np.int64)            # corpus order: by article id
        self.pub = a["pub"].fill_null(-1).to_numpy().astype(np.int64)      # -1 = no publish time: never in a pool
        if clicked_only:                                                 # sensitivity only: an article never clicked anywhere is never in a pool
            seen = pl.scan_parquet(os.path.join(self.st, "clicks_by_day", "day=*", "*.parquet")).select("article").unique().collect(engine="streaming")["article"].to_numpy().astype(np.int64)
            self.pub = np.where(np.isin(self.article, seen), self.pub, -1)
        self.text = a["text"].to_list() if load_text else None
        mx = int(self.article.max())
        self.row_of = np.full(mx + 2, -1, dtype=np.int64)
        self.row_of[self.article] = np.arange(len(self.article))
        ok = np.where(self.pub >= 0)[0]
        o = ok[np.lexsort((self.article[ok], self.pub[ok]))]
        self.sorted_rows = o                                             # corpus rows in (pub, article) order
        self.sorted_pub = self.pub[o]
        self.sorted_id = self.article[o]
        self.pos_of_row = np.full(len(self.article), -1, dtype=np.int64)
        self.pos_of_row[o] = np.arange(len(o))

    def row(self, article_ids):
        a = np.asarray(article_ids, dtype=np.int64)
        r = np.full(a.shape, -1, dtype=np.int64)
        ok = (a >= 0) & (a < len(self.row_of))
        r[ok] = self.row_of[a[ok]]
        return r

    def embeddings(self):
        ids = np.load(os.path.join(self.st, "emb_ids.npy"))
        E = np.load(os.path.join(self.st, "emb_minilm.npy"), mmap_mode="r")
        assert (ids.astype(np.int64) == self.article).all(), "embedding rows are not in article order"
        return E

    def window_clicks(self, d_first, d_last):
        """user, article of every click on the calendar days d_first..d_last (inclusive, 'YYYY-MM-DD')."""
        files = [f for d in sorted(glob.glob(os.path.join(self.st, "clicks_by_day", "day=*")))
                 if d_first <= d.split("=")[1] <= d_last for f in glob.glob(os.path.join(d, "*.parquet"))]
        return pl.scan_parquet(files).select("user", "article").collect(engine="streaming")

    def pools(self, t, window=WINDOW):
        lo = np.searchsorted(self.sorted_pub, t - window, side="right")
        hi = np.searchsorted(self.sorted_pub, t, side="right")
        return lo, hi


def candidate_matrix(corpus, lo, hi):
    P = int((hi - lo).max()) if len(lo) else 0
    pos = lo[:, None] + np.arange(P)[None, :]
    valid = pos < hi[:, None]
    ids = corpus.sorted_id[np.minimum(pos, len(corpus.sorted_id) - 1)]
    rows = corpus.sorted_rows[np.minimum(pos, len(corpus.sorted_id) - 1)]
    return ids, rows, valid


def ranks_of_target(S, valid, tgt_col, keys, cand_ids):
    """1-based rank of the target column in every row. NaN = unscorable (ties at the bottom, keyed shuffle)."""
    N = S.shape[0]
    S2 = np.where(np.isnan(S), -np.inf, S)
    ar = np.arange(N)
    tt = S2[ar, tgt_col]
    gt = (S2 > tt[:, None]) & valid
    eq = (S2 == tt[:, None]) & valid
    with np.errstate(over="ignore"):
        u = splitmix64(keys[:, None] ^ (cand_ids.astype(U64) * U64(0xD6E8FEB86659FD93)))
    ut = u[ar, tgt_col]
    before = eq & (u < ut[:, None])
    return 1 + gt.sum(1) + before.sum(1)


def metrics_from_ranks(rank, pool):
    rank = rank.astype(np.float64)
    return {"mrr": 1.0 / rank, "recall10": (rank <= 10).astype(np.float64),
            "auc": (pool - rank) / np.maximum(pool - 1, 1), "ndcg5": np.where(rank <= 5, 1.0 / np.log2(rank + 1), 0.0)}


def boot_ci(x, B=1000, seed=7, alpha=0.05):
    rng = np.random.default_rng(seed)
    n = len(x)
    m = np.empty(B)
    for b in range(B):
        m[b] = x[rng.integers(0, n, n)].mean()
    lo, hi = np.percentile(m, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(x.mean()), float(lo), float(hi), n


def paired_ci(x, y, B=1000, seed=7):
    """interval of mean(x) - mean(y) with one shared resample draw (paired)."""
    return boot_ci(np.asarray(x) - np.asarray(y), B, seed)


def build_profiles(clicks_user, clicks_t, prof, r_end, regime, M=M_CAP):
    """Last M profile article ids per click, -1 padded, oldest first.
    prof: polars frame (user, article, t) sorted by user, t. regime 'A': clicks before r_end; 'B': clicks strictly before t."""
    pu, pa, pt = prof["user"].to_numpy(), prof["article"].to_numpy().astype(np.int64), prof["t"].to_numpy().astype(np.int64)
    uu, start = np.unique(pu, return_index=True)
    end = np.append(start[1:], len(pu))
    where = {int(u): (int(s), int(e)) for u, s, e in zip(uu, start, end)}
    out = np.full((len(clicks_user), M), -1, dtype=np.int64)
    trunc = 0
    cache = {}
    for i, (u, t) in enumerate(zip(clicks_user, clicks_t)):
        se = where.get(int(u))
        if se is None:
            continue
        s, e = se
        lim = r_end if regime == "A" else int(t)
        c = s + int(np.searchsorted(pt[s:e], lim, side="left"))      # rows with time < lim
        k = min(M, c - s)
        if k:
            out[i, M - k:] = pa[c - k:c]
        if regime == "A" and e - s >= 300 and pt[s] >= r_end:
            trunc += 1
    return out, trunc
