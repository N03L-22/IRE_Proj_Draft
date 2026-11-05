"""T4 scorers. Each has fit(corpus, window_start_day, r_end_day, ...) -> state and score(...) -> (N, P) float32,
NaN = unscorable. Fit uses only events up to the end of the fit day. All scorers see the same cell context."""
import re, time

import numpy as np
import scipy.sparse as sp

from core import M_CAP

TOKEN = re.compile(r"\w+", re.UNICODE)


class Recency:
    name = "recency"

    def fit(self, corpus, **kw):
        return self

    def score(self, ctx):
        return np.where(ctx.valid, ctx.cand_pub.astype(np.float32), np.nan)      # newer is higher

    def target_scorable(self, ctx):
        return np.ones(len(ctx.keys), dtype=bool)


class Popularity:
    name = "popularity"

    def fit(self, corpus, win_user, win_article, **kw):
        self.count = np.zeros(len(corpus.article), dtype=np.float32)
        r = corpus.row(win_article)
        r = r[r >= 0]
        self.count += np.bincount(r, minlength=len(corpus.article)).astype(np.float32)
        return self

    def score(self, ctx):
        c = self.count[ctx.cand_rows]
        return np.where(ctx.valid & (c > 0), c, np.nan)

    def target_scorable(self, ctx):
        return self.count[ctx.target_row] > 0


class Meaning:
    """cosine between the candidate embedding and the mean embedding of the profile (frozen encoder: nothing to fit)."""
    name = "meaning"

    def fit(self, corpus, **kw):
        self.E = corpus.embeddings()
        return self

    def _profile_vectors(self, ctx, rows):
        out = np.zeros((rows.shape[0], self.E.shape[1]), dtype=np.float32)
        have = np.zeros(rows.shape[0], dtype=bool)
        for k in range(0, rows.shape[0], 2000):
            r = rows[k:k + 2000]
            m = r >= 0
            g = np.asarray(self.E[np.where(m, r, 0)])            # (n, M, d)
            g = g * m[..., None]
            s = g.sum(1)
            cnt = m.sum(1)
            nz = cnt > 0
            s[nz] /= cnt[nz, None]
            n = np.linalg.norm(s, axis=1, keepdims=True)
            out[k:k + 2000] = s / np.maximum(n, 1e-12)
            have[k:k + 2000] = nz
        return out, have

    def score(self, ctx):
        q, have = self._profile_vectors(ctx, ctx.profile_rows)
        self.have = have
        S = np.full(ctx.valid.shape, np.nan, dtype=np.float32)
        step = int(max(50, min(1000, 3e8 // (ctx.valid.shape[1] * self.E.shape[1]))))      # bounds the (n, P, d) block at about 1.2 GB
        for k in range(0, len(q), step):
            idx = np.minimum(ctx.cand_rows[k:k + step], len(self.E) - 1)
            C = np.asarray(self.E[idx])                              # (n, P, d)
            S[k:k + step] = np.einsum("npd,nd->np", C, q[k:k + step])
        S[~have] = np.nan
        S[~ctx.valid] = np.nan
        return S

    def target_scorable(self, ctx):
        return self.have


class BM25:
    """word matching: the candidate's BM25 weights (idf and average length frozen at the fit day) against the bag of
    words of the profile. A word never seen by the fit has weight 0."""
    name = "word"

    def __init__(self, k1=1.2, b=0.75):
        self.k1, self.b = k1, b

    def fit(self, corpus, r_end_t, **kw):
        if not hasattr(corpus, "_tf"):
            toks = [TOKEN.findall((t or "").lower()) for t in corpus.text]
            vocab = {w: i for i, w in enumerate(sorted({w for d in toks for w in d}))}   # sorted: deterministic
            ind, col, val = [0], [], []
            for d in toks:
                cnt = {}
                for w in d:
                    j = vocab[w]
                    cnt[j] = cnt.get(j, 0) + 1
                for j in sorted(cnt):
                    col.append(j); val.append(cnt[j])
                ind.append(len(col))
            corpus._tf = sp.csr_matrix((np.array(val, dtype=np.float32), np.array(col, dtype=np.int32), np.array(ind)),
                                       shape=(len(toks), len(vocab)))
            corpus._dl = np.asarray(corpus._tf.sum(1)).ravel()
        tf, dl = corpus._tf, corpus._dl
        fit_rows = np.where((corpus.pub >= 0) & (corpus.pub < r_end_t))[0]
        sub = tf[fit_rows]
        df = np.bincount(sub.indices, minlength=tf.shape[1]).astype(np.float64)
        N = len(fit_rows)
        idf = np.where(df > 0, np.log1p((N - df + 0.5) / (df + 0.5)), 0.0)
        avgdl = dl[fit_rows].mean()
        W = tf.copy().astype(np.float32)
        rows = np.repeat(np.arange(W.shape[0]), np.diff(W.indptr))
        norm = self.k1 * (1 - self.b + self.b * dl[rows] / avgdl)
        W.data = (idf[W.indices] * W.data * (self.k1 + 1) / (W.data + norm)).astype(np.float32)
        self.W, self.tf = W, tf
        return self

    def score(self, ctx):
        n, P = ctx.valid.shape
        S = np.full((n, P), np.nan, dtype=np.float32)
        prow = ctx.profile_rows
        have = (prow >= 0).any(1)
        for k in range(0, n, 2000):
            sl = slice(k, k + 2000)
            r = prow[sl]
            m = r >= 0
            ii = np.repeat(np.arange(r.shape[0]), m.sum(1))
            sel = sp.csr_matrix((np.ones(m.sum(), dtype=np.float32), (ii, r[m])), shape=(r.shape[0], self.tf.shape[0]))
            Q = sel @ self.tf                                         # (n, V) term counts of the profile
            cr = ctx.cand_rows[sl]
            u, inv = np.unique(np.where(ctx.valid[sl], cr, 0), return_inverse=True)
            D = (Q @ self.W[u].T).toarray()                           # (n, |union|)
            S[sl] = np.take_along_axis(D, inv.reshape(cr.shape), axis=1)
        S[~have] = np.nan
        S[~ctx.valid] = np.nan
        self.have = have
        return S

    def target_scorable(self, ctx):
        return self.have


class CoClick:
    """click history: item-item cosine of co-clicks in the fit window, readers damped by 1/log(1+items).
    A candidate that was not clicked in the window is unscorable."""
    name = "clickhist"

    def __init__(self, min_readers=5):
        self.min_readers = min_readers

    def fit(self, corpus, win_user, win_article, **kw):
        import polars as pl
        df = pl.DataFrame({"u": win_user, "a": win_article}).unique()
        # an article read by fewer than MIN_READERS readers has no usable co-click row (a design parameter, logged)
        df = df.join(df.group_by("a").len().filter(pl.col("len") >= self.min_readers).select("a"), on="a", how="inner")
        df = df.join(df.group_by("u").len().filter(pl.col("len") >= 2).select("u"), on="u", how="inner")   # one item: no pair
        u, a = df["u"].to_numpy(), df["a"].to_numpy().astype(np.int64)
        items, ii = np.unique(a, return_inverse=True)
        users, ui = np.unique(u, return_inverse=True)
        deg = np.bincount(ui).astype(np.float64)
        w = (1.0 / np.log1p(deg))[ui].astype(np.float32)
        X = sp.csr_matrix((w, (ui, ii)), shape=(len(users), len(items)))
        C = (X.T @ X).toarray().astype(np.float32)                    # Sum over readers of w_u^2
        d = np.sqrt(np.diag(C))
        C /= np.maximum(d[:, None] * d[None, :], 1e-12)
        np.fill_diagonal(C, 0.0)
        self.cos, self.items = C, items
        self.col = np.full(corpus.row_of.shape[0] + 1, -1, dtype=np.int64)
        valid_ids = items[(items >= 0) & (items < len(self.col))]
        self.col[valid_ids] = np.searchsorted(items, valid_ids)
        self.n_users, self.n_items = len(users), len(items)
        return self

    def _col(self, ids):
        ids = np.asarray(ids)
        out = np.full(ids.shape, -1, dtype=np.int64)
        ok = (ids >= 0) & (ids < len(self.col))
        out[ok] = self.col[ids[ok]]
        return out

    def score(self, ctx):
        n, P = ctx.valid.shape
        S = np.full((n, P), np.nan, dtype=np.float32)
        pc = self._col(ctx.profile_ids)
        ccol = self._col(ctx.cand_ids)
        self.tcol = self._col(ctx.target_id)
        for k in range(0, n, 1000):
            sl = slice(k, k + 1000)
            r = pc[sl]
            m = r >= 0
            ii = np.repeat(np.arange(r.shape[0]), m.sum(1))
            sel = sp.csr_matrix((np.ones(m.sum(), dtype=np.float32), (ii, r[m])), shape=(r.shape[0], self.n_items))
            D = sel @ self.cos                                         # (n, items), dense
            cc = ccol[sl]
            vals = np.take_along_axis(D, np.maximum(cc, 0), axis=1)
            S[sl] = np.where((cc >= 0) & ctx.valid[sl], vals, np.nan)
        return S

    def target_scorable(self, ctx):
        return self.tcol >= 0
