"""Drop-one ablation of the four-signal hybrid (proposal section 6.3): reciprocal rank fusion (K = 60, equal weights, nothing tuned) of word matching (BM25), meaning
matching, co-click history and newest first, and the four hybrids that each leave one signal out. The four components are fitted once per fit date and ranked once per
click context; each variant is one weighted sum of those ranks. A component of weight 0 is left out completely (it neither adds a term nor makes a click scorable).
Same grid, pool, regimes, samples and already-read rule as qrun.py (the output is read by analyze.py unchanged).
Run:  python ablate.py <root> --stage S18 --out results/s18_ablation [--workers 2] [--cap-gb 10]
"""
import argparse, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import decay
import qrun
from core import WINDOW
from scorers import BM25, CoClick, Fusion, Meaning, Recency

COMPONENTS = ("word", "meaning", "click", "recency")
VARIANTS = {"abl_full": (1, 1, 1, 1), "abl_no_word": (0, 1, 1, 1), "abl_no_meaning": (1, 0, 1, 1), "abl_no_click": (1, 1, 0, 1), "abl_no_recency": (1, 1, 1, 0)}


class AblFusion(Fusion):
    K = 60
    _shared = {"key": None, "parts": None}
    _cache = {"ctx": None, "R": None}

    def __init__(self, name, w):
        self.name, self.weights = name, list(map(float, w))
        self.parts = [BM25(), Meaning(), CoClick(), Recency()]           # unfitted: lets qrun see that the text is needed; fit() replaces them by the shared fitted ones

    def fit(self, corpus, **kw):
        key = (id(corpus), kw.get("r_end_t"))
        if AblFusion._shared["key"] != key:
            parts = [BM25(), Meaning(), CoClick(), Recency()]
            for p in parts:
                p.fit(corpus, **kw)
            AblFusion._shared.update(key=key, parts=parts)
            AblFusion._cache.update(ctx=None, R=None)
        self.parts = AblFusion._shared["parts"]
        return self

    def _ranks(self, ctx):
        if AblFusion._cache["ctx"] is not ctx:
            AblFusion._cache.update(ctx=ctx, R=Fusion._ranks(self, ctx))      # the components' own scorable state now belongs to this ctx
        return AblFusion._cache["R"]

    def score(self, ctx):
        R = self._ranks(ctx)
        tot = np.zeros(ctx.valid.shape, dtype=np.float64)
        any_ = np.zeros(ctx.valid.shape[0], dtype=bool)
        for r, w in zip(R, self.weights):
            if w <= 0:
                continue
            a = r > 0
            tot += np.where(a, w / (self.K + r.astype(np.float64)), 0.0)
            any_ |= a.any(1)
        return np.where(ctx.valid & any_[:, None], tot, np.nan).astype(np.float32)

    def target_scorable(self, ctx):
        ok = np.zeros(len(ctx.keys), dtype=bool)
        for p, w in zip(self.parts, self.weights):
            if w > 0:
                ok |= p.target_scorable(ctx)
        return ok


for _n, _w in VARIANTS.items():
    decay.ALL[_n] = (lambda n=_n, w=_w: AblFusion(n, w))            # also in every spawned worker (this main module is re-imported there)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--stage", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=2); ap.add_argument("--cap-gb", type=float, default=10.0)
    ap.add_argument("--fits", nargs=2, default=["2023-05-10", "2023-05-23"]); ap.add_argument("--last", default="2023-05-24")
    a = ap.parse_args()
    print(qrun.run(os.path.abspath(a.root), a.stage, decay.days_between(*a.fits), a.last, a.out, list(VARIANTS), a.workers, WINDOW, 7, None, False, a.cap_gb), "units run")
