"""Extension (EB-NeRD only): does a genre-affinity signal add anything? Nothing in the existing files is changed.
Genre = the article's `category` field (32 values, no nulls in the store). The reader's profile is the share of each category among the
profile clicks (the same profile_rows every other scorer sees: regime A frozen at the fit day, regime B live, last M_CAP clicks); a candidate
scores the profile share of its own category. Many candidates tie (same category); ties are broken by the keyed shuffle in core.ranks_of_target.
A click with an empty profile gets no score. Components are registered into decay.ALL so decay.run is used unchanged (same shards, same
resume rule: a finished fit date is in the manifest and is skipped; unfinished work is redone).
Run:  python genre.py <root> --fits 2023-05-10 2023-05-23 --last 2023-05-24 [--workers 6] [--out results/genre] [--scorers recency,genre,fuse_genre,...]
"""
import argparse, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import polars as pl

import decay
from scorers import BM25, Fusion, Meaning, Recency


class Genre:
    name = "genre"

    def fit(self, corpus, **kw):
        a = pl.read_parquet(os.path.join(corpus.st, "articles.parquet"), columns=["article", "category"]).sort("article")
        assert (a["article"].to_numpy().astype(np.int64) == corpus.article).all(), "category rows are not in corpus order"
        col = a["category"]
        if col.dtype == pl.String:                                                   # NPR and Adressa: text categories; null or empty = no category
            arr = col.fill_null("").to_numpy().astype(str)
            ok = arr != ""
            u, inv = np.unique(arr[ok], return_inverse=True)
            self.code = np.full(len(arr), -1, dtype=np.int64)
            self.code[ok] = inv
            self.K = len(u)
            return self
        c = col.fill_null(-1).to_numpy().astype(np.int64)
        u = np.unique(c[c >= 0])
        self.code = np.where(c >= 0, np.searchsorted(u, np.maximum(c, 0)), -1)       # 0..K-1, -1 = no category
        self.K = len(u)
        return self

    def _share(self, ctx):
        pr = ctx.profile_rows
        pc = np.where(pr >= 0, self.code[np.maximum(pr, 0)], -1)
        tot = (pc >= 0).sum(1)
        share = np.zeros((len(pc), self.K), dtype=np.float32)
        for k in range(self.K):
            share[:, k] = (pc == k).sum(1)
        share /= np.maximum(tot, 1)[:, None]
        return share, tot > 0

    def score(self, ctx):
        share, have = self._share(ctx)
        self.have = have
        cc = self.code[ctx.cand_rows]
        S = np.take_along_axis(share, np.maximum(cc, 0), axis=1)
        S[(cc < 0) | ~ctx.valid | ~have[:, None]] = np.nan
        return S

    def target_scorable(self, ctx):
        _, have = self._share(ctx)
        return have & (self.code[ctx.target_row] >= 0)


class FuseGenre(Fusion):
    """RRF (K = 60, equal weights, nothing tuned) of genre and recency."""
    name = "fuse_genre"

    def __init__(self):
        self.parts = [Genre(), Recency()]


class FuseWMRG(Fusion):
    """the report's word + meaning + recency fusion with genre added as a fourth component (equal weights, K = 60)."""
    name = "fuse_wmrg"

    def __init__(self):
        self.parts = [BM25(), Meaning(), Recency(), Genre()]


for _c in (Genre, FuseGenre, FuseWMRG):
    decay.ALL[_c.name] = _c

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--fits", nargs=2, required=True); ap.add_argument("--last", required=True)
    ap.add_argument("--workers", type=int, default=4); ap.add_argument("--out", default="results/genre")
    ap.add_argument("--scorers", default="recency,genre,fuse_genre,fuse_recency,fuse_wmrg")
    a = ap.parse_args()
    decay.run(a.root, decay.days_between(*a.fits), a.last, a.out, a.workers, a.scorers.split(","))
