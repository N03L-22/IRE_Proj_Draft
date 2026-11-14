"""Checks for ablate.py: each variant equals the plain reciprocal rank fusion of the components it keeps, a component of weight 0 makes nothing scorable, and the
shared component ranks are computed once per click context.   Run:  python -c "import sys; sys.path.insert(0, 'code'); import unittest, test_ablate; unittest.main(module=test_ablate)" """
import unittest

import numpy as np

import ablate
from scorers import Fusion


class Stub:
    def __init__(self, S, ok):
        self.S, self.ok, self.calls = S, ok, 0

    def score(self, ctx):
        self.calls += 1
        return self.S

    def target_scorable(self, ctx):
        return self.ok


class Ctx:
    pass


def make(seed=0, n=40, P=12):
    rng = np.random.default_rng(seed)
    ctx = Ctx()
    ctx.valid = rng.random((n, P)) < 0.85
    ctx.keys = np.arange(n)
    parts = []
    for j in range(4):
        S = rng.normal(size=(n, P)).astype(np.float32)
        S[rng.random((n, P)) < 0.1 * j] = np.nan               # some pairs unscorable, more in the later components
        S[rng.random(n) < 0.15 * j] = np.nan                   # some rows with no score at all
        S[~ctx.valid] = np.nan
        parts.append(Stub(S, ~np.isnan(S).all(1)))
    return ctx, parts


class AblateTests(unittest.TestCase):
    def test_variants_equal_plain_fusion_of_kept_components(self):
        ctx, parts = make()
        for name, w in ablate.VARIANTS.items():
            v = ablate.AblFusion(name, w)
            v.parts = parts
            ablate.AblFusion._cache.update(ctx=None, R=None)
            ref = Fusion()
            ref.parts = [p for p, wi in zip(parts, w) if wi > 0]
            a, b = v.score(ctx), ref.score(ctx)
            self.assertTrue(np.array_equal(np.isnan(a), np.isnan(b)), name)
            self.assertTrue(np.allclose(a[~np.isnan(a)], b[~np.isnan(b)], rtol=1e-6), name)
            self.assertTrue(np.array_equal(v.target_scorable(ctx), ref.target_scorable(ctx)), name)

    def test_component_ranks_are_shared(self):
        ctx, parts = make(1)
        ablate.AblFusion._cache.update(ctx=None, R=None)
        vs = []
        for name, w in ablate.VARIANTS.items():
            v = ablate.AblFusion(name, w)
            v.parts = parts
            vs.append(v)
        for v in vs:
            v.score(ctx)
        self.assertEqual([p.calls for p in parts], [1, 1, 1, 1])

    def test_removed_component_does_not_make_rows_scorable(self):
        ctx, parts = make(2)
        for p in parts[1:]:
            p.S[:5] = np.nan                                    # rows 0-4 are scored by component 0 alone
            p.ok = ~np.isnan(p.S).all(1)
        parts[0].S[:5] = np.where(ctx.valid[:5], 1.0, np.nan)
        parts[0].ok = ~np.isnan(parts[0].S).all(1)
        v = ablate.AblFusion("abl_no_word", ablate.VARIANTS["abl_no_word"])
        v.parts = parts
        ablate.AblFusion._cache.update(ctx=None, R=None)
        self.assertTrue(np.isnan(v.score(ctx)[:5]).all())
        self.assertFalse(v.target_scorable(ctx)[:5].any())


if __name__ == "__main__":
    unittest.main()
