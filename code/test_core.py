import os, tempfile, unittest

import numpy as np
import polars as pl

from core import Corpus, candidate_matrix, ranks_of_target, build_profiles, metrics_from_ranks, WINDOW
from scorers import BM25, CoClick, Popularity


def make_corpus(pubs, texts=None):
    root = tempfile.mkdtemp()
    st = os.path.join(root, "data/toy/store")
    os.makedirs(st)
    n = len(pubs)
    pl.DataFrame({"article": list(range(n)), "pub": pubs, "text": texts or [f"w{i}" for i in range(n)]}).write_parquet(
        os.path.join(st, "articles.parquet"))
    return Corpus(root, "toy", load_text=True)


class CoreTests(unittest.TestCase):
    def test_pool_is_publish_time_window_only(self):
        c = make_corpus([0, 100, 200, 300, 400])
        lo, hi = c.pools(np.array([310]), window=150)
        ids, rows, valid = candidate_matrix(c, lo, hi)
        self.assertEqual(sorted(ids[0][valid[0]].tolist()), [2, 3])         # pub 200, 300: (160, 310]
        lo, hi = c.pools(np.array([300]), window=150)                       # pub <= t includes equality
        self.assertEqual(c.sorted_id[lo[0]:hi[0]].tolist(), [2, 3])

    def test_rank_counts_strictly_better_and_keyed_ties(self):
        S = np.array([[3.0, 2.0, 1.0, np.nan, np.nan]], dtype=np.float32)
        valid = np.ones((1, 5), bool)
        ids = np.arange(5)[None, :]
        keys = np.array([123], dtype=np.uint64)
        self.assertEqual(ranks_of_target(S, valid, np.array([0]), keys, ids)[0], 1)
        self.assertEqual(ranks_of_target(S, valid, np.array([2]), keys, ids)[0], 3)
        r3 = ranks_of_target(S, valid, np.array([3]), keys, ids)[0]
        r4 = ranks_of_target(S, valid, np.array([4]), keys, ids)[0]
        self.assertEqual(sorted([r3, r4]), [4, 5])                           # the two unscorable tie below, in a fixed order
        self.assertEqual(r3, ranks_of_target(S, valid, np.array([3]), keys, ids)[0])      # same every run

    def test_ranks_do_not_depend_on_row_order(self):
        rng = np.random.default_rng(1)
        S = rng.normal(size=(50, 30)).astype(np.float32); S[rng.random(S.shape) < 0.5] = np.nan
        valid = np.ones_like(S, bool); ids = np.tile(np.arange(30), (50, 1)); tg = rng.integers(0, 30, 50)
        keys = rng.integers(0, 2 ** 63, 50).astype(np.uint64)
        a = ranks_of_target(S, valid, tg, keys, ids)
        p = rng.permutation(50)
        b = ranks_of_target(S[p], valid[p], tg[p], keys[p], ids[p])
        self.assertTrue((a[p] == b).all())

    def test_shuffle_baseline_is_random_not_biased(self):
        rng = np.random.default_rng(2)
        n, P = 20000, 100
        S = np.full((n, P), np.nan, dtype=np.float32); valid = np.ones((n, P), bool)
        ids = np.tile(np.arange(P), (n, 1)); tg = rng.integers(0, P, n)
        keys = rng.integers(0, 2 ** 63, n).astype(np.uint64)
        r = ranks_of_target(S, valid, tg, keys, ids)
        self.assertAlmostEqual(r.mean(), (P + 1) / 2, delta=1.0)

    def test_profiles_regime_B_never_contains_the_click_or_the_future(self):
        prof = pl.DataFrame({"user": [1] * 6, "article": [10, 11, 12, 13, 14, 15], "t": [10, 20, 30, 40, 50, 60]}).sort(["user", "t"])
        pid, _ = build_profiles(np.array([1]), np.array([40]), prof, r_end=25, regime="B", M=3)
        self.assertEqual(pid[0].tolist(), [10, 11, 12])        # clicks at t = 10, 20, 30 only
        pid, _ = build_profiles(np.array([1]), np.array([40]), prof, r_end=25, regime="A", M=3)
        self.assertEqual(pid[0].tolist(), [-1, 10, 11])                                         # frozen at r_end: t = 10, 20
        pid, _ = build_profiles(np.array([1]), np.array([30]), prof, r_end=100, regime="B", M=5)
        self.assertEqual(pid[0].tolist(), [-1, -1, -1, 10, 11])                                 # strictly before t = 30: the click at 30 is excluded

    def test_coclick_cosine_matches_brute_force(self):
        c = make_corpus([0] * 4)
        user = np.array([1, 1, 2, 2, 3, 3]); art = np.array([0, 1, 0, 1, 0, 2])
        m = CoClick(min_readers=1).fit(c, win_user=user, win_article=art)
        X = np.zeros((3, 3)); w = 1 / np.log1p(2)
        for u, a in zip(user, art):
            X[u - 1, a] = w
        C = X.T @ X; d = np.sqrt(np.diag(C)); cos = C / np.outer(d, d); np.fill_diagonal(cos, 0)
        np.testing.assert_allclose(m.cos, cos[:3, :3], rtol=1e-5)
        self.assertEqual(m._col(np.array([3, 0]))[0], -1)                    # an article not clicked in the window is unscorable

    def test_bm25_new_words_have_no_weight_and_frozen_idf(self):
        c = make_corpus([0, 0, 500], ["apple pie", "apple tart", "zebra zebra"])
        m = BM25().fit(c, r_end_t=100)                                       # fit sees articles 0 and 1 only
        W = m.W.toarray()
        self.assertEqual(float(W[2].sum()), 0.0)                             # 'zebra' was never seen: weight 0
        self.assertGreater(float(W[0].sum()), 0.0)

    def test_popularity_counts_only_the_window(self):
        c = make_corpus([0, 0, 0])
        m = Popularity().fit(c, win_user=np.array([1, 2, 3]), win_article=np.array([0, 0, 1]))
        self.assertEqual(m.count.tolist(), [2.0, 1.0, 0.0])

    def test_metrics(self):
        m = metrics_from_ranks(np.array([1, 2, 11]), np.array([100, 100, 100]))
        np.testing.assert_allclose(m["mrr"], [1, 0.5, 1 / 11])
        self.assertEqual(m["recall10"].tolist(), [1, 1, 0])


if __name__ == "__main__":
    unittest.main()


class AlreadyReadTests(unittest.TestCase):
    """the click's own history is never a candidate, and a re-read is not evaluated (same for every cell)."""

    def build(self, history_ids, target, t_click=1000):
        from cell import build_ctx
        c = make_corpus([100, 200, 300, 400, 500, 600])
        prof = pl.DataFrame({"user": [1] * len(history_ids), "article": history_ids,
                             "t": [10 * (i + 1) for i in range(len(history_ids))]}).sort(["user", "t"])
        clicks = pl.DataFrame({"user": [1], "article": [target], "t": [t_click]})
        return c, build_ctx(c, clicks, prof, r_end=0, regime="B", window=10 ** 6)

    def test_history_articles_leave_the_pool(self):
        c, x = self.build([0, 1], 5)
        self.assertEqual(sorted(x.cand_ids[0][x.valid[0]].tolist()), [2, 3, 4, 5])
        self.assertEqual(int(x.pool[0]), 4)

    def test_a_reread_is_dropped_and_counted(self):
        c, x = self.build([0, 5], 5)
        self.assertEqual(len(x.t), 0)
        self.assertEqual(x.n_reread, 1)

    def test_pool_does_not_depend_on_regime(self):
        from cell import build_ctx
        c, a = self.build([0, 1], 5)
        prof = pl.DataFrame({"user": [1, 1], "article": [0, 1], "t": [10, 20]}).sort(["user", "t"])
        clicks = pl.DataFrame({"user": [1], "article": [5], "t": [1000]})
        b = build_ctx(c, clicks, prof, r_end=15, regime="A", window=10 ** 6)       # frozen profile sees only article 0
        self.assertTrue((a.valid == b.valid).all())


class FusionTests(unittest.TestCase):
    class Part:
        def __init__(self, S, ok):
            self.S, self.ok = S, ok
        def score(self, ctx):
            return self.S
        def target_scorable(self, ctx):
            return self.ok

    def ctx(self, valid):
        from types import SimpleNamespace
        return SimpleNamespace(valid=valid, keys=np.arange(valid.shape[0]))

    def make(self, parts):
        from scorers import FuseContent
        f = FuseContent()
        f.parts = parts
        return f

    def test_ties_share_a_rank_and_an_unscorable_row_is_nan(self):
        nan = np.nan
        a = np.array([[1.0, 0.0, 0.0, 0.0], [nan] * 4], dtype=np.float32)
        b = np.array([[0.0, 0.0, 0.0, 2.0], [nan] * 4], dtype=np.float32)
        valid = np.ones((2, 4), dtype=bool)
        f = self.make([self.Part(a, np.array([True, False])), self.Part(b, np.array([True, False]))])
        S = f.score(self.ctx(valid))
        self.assertTrue(np.isnan(S[1]).all())
        self.assertAlmostEqual(S[0, 1], S[0, 2])                   # tied candidates stay tied
        self.assertAlmostEqual(S[0, 1], S[0, 1] * 1.0)
        self.assertGreater(S[0, 0], S[0, 1])
        self.assertGreater(S[0, 3], S[0, 1])
        self.assertEqual(f.target_scorable(self.ctx(valid)).tolist(), [True, False])

    def test_a_component_that_cannot_score_a_row_adds_nothing(self):
        a = np.array([[3.0, 1.0, 2.0]], dtype=np.float32)
        b = np.full((1, 3), np.nan, dtype=np.float32)
        S = self.make([self.Part(a, np.array([True])), self.Part(b, np.array([False]))]).score(self.ctx(np.ones((1, 3), dtype=bool)))
        self.assertEqual(np.argsort(-S[0]).tolist(), [0, 2, 1])
