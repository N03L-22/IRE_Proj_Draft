"""Extension scorers (EB-NeRD). Nothing in the existing files is changed; qrun.py registers these into decay.ALL.

genre_perm / fuse_genre_perm   the genre scorer fed another reader's profile (a deterministic permutation keyed by the click keys): the null for "is the gain personal?"
genre_prior / fuse_genre_prior every reader gets the same category mix (the mix of all profile clicks in the cell): the null for "is the gain just popular categories?"
fuse_click_recency / fuse_pop_recency   hybrid: RRF (K = 60, equal weights, nothing tuned) of click history, or popularity, with recency. A candidate the click-based
                               component cannot score keeps only its recency term, so recency is the automatic fallback.
trend_h1 ... trend_h24         live trending (trend_w10, trend_w30: 10 and 30 minute windows; trend_h1_dN: the hour window ends N minutes before the click): the number of clicks an article received from ALL readers in the last h hours before the click (strictly before t,
                               so the click itself is never counted). It is not fitted, so regimes A and B are identical. Zero clicks = tied at the bottom.
"""
import glob, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import polars as pl

import decay
from genre import Genre
from sample import splitmix64
from scorers import BM25, CoClick, Fusion, Meaning, Popularity, Recency

PERM_SEED = np.uint64(0xA5A5F00D1234ABCD)


class GenrePerm(Genre):
    """each click is scored with the profile of its neighbour in a fixed pseudo-random order of the cell's clicks (never its own)."""
    name = "genre_perm"

    def _share(self, ctx):
        n = len(ctx.keys)
        order = np.argsort(splitmix64(ctx.keys.astype(np.uint64) ^ PERM_SEED), kind="stable")
        src = np.empty(n, dtype=np.int64)
        src[order] = order[(np.arange(n) + 1) % n]
        c = type("C", (), {})()
        c.profile_rows = ctx.profile_rows[src]
        return Genre._share(self, c)


class GenrePrior(Genre):
    name = "genre_prior"

    def _share(self, ctx):
        pr = ctx.profile_rows[ctx.profile_rows >= 0]
        cat = self.code[pr]
        cat = cat[cat >= 0]
        mix = (np.bincount(cat, minlength=self.K) / max(len(cat), 1)).astype(np.float32)
        n = ctx.profile_rows.shape[0]
        return np.tile(mix, (n, 1)), np.ones(n, dtype=bool)


class FuseGenrePerm(Fusion):
    name = "fuse_genre_perm"

    def __init__(self):
        self.parts = [GenrePerm(), Recency()]


class FuseGenrePrior(Fusion):
    name = "fuse_genre_prior"

    def __init__(self):
        self.parts = [GenrePrior(), Recency()]


class FuseClickRecency(Fusion):
    name = "fuse_click_recency"

    def __init__(self):
        self.parts = [CoClick(), Recency()]


class FusePopRecency(Fusion):
    name = "fuse_pop_recency"

    def __init__(self):
        self.parts = [Popularity(), Recency()]


class SiteOrder:
    """the site's own ranking: the position of an article in the impression slate (first = best). Only meaningful with real slates (impr_run.py, slate mode)."""
    name = "site_order"

    def fit(self, corpus, **kw):
        return self

    def score(self, ctx):
        assert getattr(ctx, "slate_mode", False), "site_order needs impression slates"
        S = np.tile(-np.arange(ctx.valid.shape[1], dtype=np.float32), (ctx.valid.shape[0], 1))
        S[~ctx.valid] = np.nan
        return S

    def target_scorable(self, ctx):
        return np.ones(len(ctx.keys), dtype=bool)


# ---- live trending ---------------------------------------------------------------------------------------------------------------
_TREND = {"key": None}


def _click_index(st, d0, d1):
    """composite sorted keys (article << 31) + (t - T0) of every click on the days d0..d1, cached for the latest range only."""
    key = (st, d0, d1)
    if _TREND["key"] != key:
        files = [f for d in sorted(glob.glob(os.path.join(st, "clicks_by_day", "day=*"))) if d0 <= d.split("=")[1] <= d1 for f in glob.glob(os.path.join(d, "*.parquet"))]
        c = pl.scan_parquet(files).select("article", "t").collect(engine="streaming")
        t = c["t"].to_numpy().astype(np.int64)
        t0 = int(t.min())
        k = (c["article"].to_numpy().astype(np.int64) << 31) + (t - t0)
        k.sort()
        _TREND.update(key=key, K=k, T0=t0)
    return _TREND["K"], _TREND["T0"]


class Trend:
    """count of clicks in [t - delay - window, t - delay): window and delay in seconds; the default delay 0 is the live trending baseline."""
    def __init__(self, hours=None, window_s=None, delay_s=0, name=None):
        self.win = window_s if window_s is not None else int(hours * 3600)
        self.delay = delay_s
        self.name = name or f"trend_h{hours}"

    def fit(self, corpus, **kw):
        self.st = corpus.st
        return self

    def score(self, ctx):
        import datetime as dt
        day = lambda s: str(dt.datetime.fromtimestamp(int(s), dt.timezone.utc).date())
        tmin, tmax = int(ctx.t.min()), int(ctx.t.max())
        K, T0 = _click_index(self.st, day(tmin - 2 * 86400), day(tmax + 86400))      # +1 day after: a local-day partition (NPR) can run past the UTC date; only clicks before t are counted
        t = ctx.t.astype(np.int64)[:, None]
        a = ctx.cand_ids.astype(np.int64) << 31
        hi = np.searchsorted(K, a + (t - self.delay - T0), side="left")
        lo = np.searchsorted(K, a + (t - self.delay - self.win - T0), side="left")
        S = (hi - lo).astype(np.float32)
        S[~ctx.valid] = np.nan
        self.tgt = S[np.arange(len(S)), ctx.tgt_col] > 0
        return S

    def target_scorable(self, ctx):
        return self.tgt


class MeaningRW(Meaning):
    """meaning matching with a recency-weighted profile: the click j positions back counts 0.5 ** (j / half_life); the mean vector is of weighted embeddings."""
    def __init__(self, half_life, name):
        self.hl, self.name = half_life, name

    def _profile_vectors(self, ctx, rows):
        out = np.zeros((rows.shape[0], self.E.shape[1]), dtype=np.float32)
        have = np.zeros(rows.shape[0], dtype=bool)
        M = rows.shape[1]
        w = (0.5 ** ((M - 1 - np.arange(M)) / self.hl)).astype(np.float32)
        for k in range(0, rows.shape[0], 2000):
            r = rows[k:k + 2000]
            m = r >= 0
            g = np.asarray(self.E[np.where(m, r, 0)]) * (m * w)[..., None]
            s = g.sum(1)
            den = (m * w).sum(1)
            nz = den > 0
            s[nz] /= den[nz, None]
            out[k:k + 2000] = s / np.maximum(np.linalg.norm(s, axis=1, keepdims=True), 1e-12)
            have[k:k + 2000] = nz
        return out, have


class BM25Var(BM25):
    def __init__(self, k1, b, name):
        super().__init__(k1, b)
        self.name = name


TREND_HOURS = (1, 3, 6, 12, 24)
decay.ALL["site_order"] = SiteOrder
for _c in (GenrePerm, GenrePrior, FuseGenrePerm, FuseGenrePrior, FuseClickRecency, FusePopRecency):
    decay.ALL[_c.name] = _c
for _n, _k1, _b in (("word_k06", 0.6, 0.75), ("word_k20", 2.0, 0.75), ("word_b03", 1.2, 0.3), ("word_b09", 1.2, 0.9)):     # BM25 parameters (default k1 1.2, b 0.75)
    decay.ALL[_n] = (lambda n=_n, k=_k1, b=_b: BM25Var(k, b, n))
for _n, _hl in (("meaning_rw5", 5), ("meaning_rw15", 15)):
    decay.ALL[_n] = (lambda n=_n, h=_hl: MeaningRW(h, n))
for _h in TREND_HOURS:
    decay.ALL[f"trend_h{_h}"] = (lambda h=_h: Trend(h))
for _m in (10, 30):                                   # shorter windows
    decay.ALL[f"trend_w{_m}"] = (lambda m=_m: Trend(window_s=m * 60, name=f"trend_w{m}"))
for _d in (5, 15, 30, 60, 180, 360):                  # a one-hour window that ends _d minutes before the click: how fast does a live click signal go stale?
    decay.ALL[f"trend_h1_d{_d}"] = (lambda d=_d: Trend(window_s=3600, delay_s=d * 60, name=f"trend_h1_d{d}"))
