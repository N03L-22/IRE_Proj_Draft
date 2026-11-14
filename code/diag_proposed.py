"""The proposal's diagnostics (section 6.4) on the corrected main run, EB-NeRD, same clicks and same paired bootstrap as analyze.py.
  unseen terms (word matching): share of the clicked article's distinct words that no article published before the fit end contains
      (exactly the words the frozen BM25 gives weight 0: its idf is built from the articles with pub < r_end). Level at the fit, level at the
      control (fit the day before), and the extra caused by staleness = frozen - control.
  embedding drift (meaning matching): cosine between the clicked article's embedding and the centroid of the articles published in the 7 days before
      the fit end (the fit window's length); drift = control cosine - frozen cosine.
  zero-click share (co-click history): 1 - scorable share of the frozen click-history scorer (regime A); reported by lag, not correlated (it is 100% from lag 3).
Each is set beside the MRR lost of the matching scorer (decay = control - frozen on the same clicks, as analyze.py) and correlated with it:
  across lags 2 to 13 (lag-level means; Spearman, interval over click resamples) and across the 90 day-by-lag cells after removing each lag's mean
  (Spearman, interval over cells). Days enter a lag with equal weight; intervals resample clicks inside each day, with analyze.py's shared counts.
Writes <out>/by_lag.csv, cells.csv, correlation.csv.
Run:  python -I diag_proposed.py <root> [--src results/decay_matrix] [--out results/diag_proposed] [--B 1000]
"""
import argparse, csv, datetime as dt, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from scipy.stats import rankdata

import monitor as M
from analyze import counts, load_day
from cell import day_start
from core import Corpus
from scorers import TOKEN

WEEK = 7 * 86400


def term_clock(corpus):
    """CSR of each article's distinct word ids, and the first publish time of every word (min pub over the articles that contain it)."""
    vocab, indptr, indices = {}, [0], []
    for t in corpus.text:
        ids = sorted({vocab.setdefault(w, len(vocab)) for w in TOKEN.findall((t or "").lower())})
        indices.extend(ids)
        indptr.append(len(indices))
    indptr, indices = np.array(indptr, dtype=np.int64), np.array(indices, dtype=np.int64)
    first = np.full(len(vocab), np.iinfo(np.int64).max, dtype=np.int64)
    arow = np.repeat(np.arange(len(corpus.pub)), np.diff(indptr))
    ok = corpus.pub[arow] >= 0
    np.minimum.at(first, indices[ok], corpus.pub[arow][ok])
    return indptr, indices, first


def per_article(corpus, rows, Ts):
    """for the corpus rows: unseen-term share at each time T, and cosine to the centroid of the articles published in [T - 7 days, T)."""
    indptr, indices, first = term_clock(corpus)
    E = np.asarray(corpus.embeddings(), dtype=np.float32)
    E = E / np.maximum(np.linalg.norm(E, axis=1, keepdims=True), 1e-12)
    C = []
    for T in Ts:
        m = (corpus.pub >= T - WEEK) & (corpus.pub < T)
        c = E[m].mean(0)
        C.append(c / np.linalg.norm(c))
    cos = E[rows] @ np.array(C, dtype=np.float32).T
    oov = np.full((len(rows), len(Ts)), np.nan, dtype=np.float64)
    ntypes = np.zeros(len(rows), dtype=np.int64)
    for i, a in enumerate(rows):
        fp = np.sort(first[indices[indptr[a]:indptr[a + 1]]])
        ntypes[i] = len(fp)
        if len(fp):
            oov[i] = 1.0 - np.searchsorted(fp, Ts, side="left") / len(fp)
    ok = (corpus.pub[rows] >= 0) & (ntypes > 0)
    return oov, cos, ok


def ci(rep):
    return [float(x) for x in np.percentile(rep, [2.5, 97.5])]


def spearman_rows(X, y):
    """Spearman of every row of X against y (ranks, then Pearson)."""
    rx = np.apply_along_axis(rankdata, 1, X)
    ry = rankdata(y)
    rx = rx - rx.mean(1, keepdims=True)
    ry = ry - ry.mean()
    return (rx @ ry) / np.sqrt((rx ** 2).sum(1) * (ry ** 2).sum())


def run(root, src, out, B):
    t0 = time.time()
    manifest = M.read_manifest(os.path.join(root, src, "manifest.jsonl"))
    fits = sorted(r["unit"].split("=")[1] for r in manifest)
    all_days = sorted({c["d"] for r in manifest for c in r["cells"]})
    corpus = Corpus(root, "ebnerd", load_text=True)
    Tdays = sorted({str(dt.date.fromisoformat(r) + dt.timedelta(days=1)) for r in fits} | set(all_days))
    Ts = np.array([day_start(d) + corpus.off for d in Tdays], dtype=np.int64)        # the fit of day r ends at the start of day r + 1
    Ti = {d: i for i, d in enumerate(Tdays)}
    # the clicked articles of every evaluation day (one fixed click order per day, as analyze.load_day)
    day_data = {}
    for di, d in enumerate(all_days):
        cols, pool, key = load_day(os.path.join(root, src), d, fits)
        day_data[d] = (di, cols, len(pool), corpus.row(key["article"].to_numpy()))
    ur = np.unique(np.concatenate([v[3] for v in day_data.values()]))
    ur = ur[ur >= 0]
    oov, cos, ok_art = per_article(corpus, ur, Ts)
    print(f"prepared {len(ur)} clicked articles, {len(Tdays)} fit times, {time.time() - t0:.0f} s", flush=True)
    acc = {}                    # (lag, name) -> list over days of (point, replicate array)
    cells = []
    for d in all_days:
        di, cols, n, rows = day_data[d]
        W = counts(di, n, B)
        ui = np.clip(np.searchsorted(ur, rows), 0, len(ur) - 1)
        valid = ((rows >= 0) & (ur[ui] == rows) & ok_art[ui]).astype(np.float64)
        wv = W @ valid
        ctrl = str(dt.date.fromisoformat(d) - dt.timedelta(days=1))
        tc = Ti[d]
        def mean_of(v):
            return float((v * valid).sum() / valid.sum()), (W @ (v * valid)) / np.maximum(wv, 1)
        for r in fits:
            lag = (dt.date.fromisoformat(d) - dt.date.fromisoformat(r)).days
            if lag < 1 or (ctrl, "word", "A") not in cols or (r, "word", "A") not in cols:
                continue
            tr = Ti[str(dt.date.fromisoformat(r) + dt.timedelta(days=1))]
            row = {"n_valid": int(valid.sum())}
            vals = {"oov_frozen": oov[ui, tr], "oov_control": oov[ui, tc], "cos_frozen": cos[ui, tr], "cos_control": cos[ui, tc]}
            for k, v in vals.items():
                row[k] = mean_of(np.nan_to_num(v))
            row["oov_extra"] = mean_of(np.nan_to_num(vals["oov_frozen"] - vals["oov_control"]))
            row["drift"] = mean_of(np.nan_to_num(vals["cos_control"] - vals["cos_frozen"]))
            for sc, rg in (("word", "A"), ("word", "B"), ("meaning", "A"), ("meaning", "B"), ("clickhist", "A")):
                cc, c = cols[(ctrl, sc, rg)]["mrr"], cols[(r, sc, rg)]["mrr"]
                row[f"mrr_lost_{sc}_{rg}"] = (float(cc.mean() - c.mean()), (W @ cc - W @ c) / n)
            sc_ = cols[(r, "clickhist", "A")]["scorable"]
            row["nonscorable_clickhist"] = (float(1 - sc_.mean()), 1 - (W @ sc_) / n)
            for k, v in row.items():
                if k != "n_valid":
                    acc.setdefault((lag, k), []).append(v)
            acc.setdefault((lag, "n_valid"), []).append((row["n_valid"], None))
            cells.append({"d": d, "lag": lag, "n_valid": row["n_valid"], **{k: v[0] for k, v in row.items() if k != "n_valid"}})
        print(f"day {d} done, {time.time() - t0:.0f} s", flush=True)
    names = ["oov_frozen", "oov_control", "oov_extra", "cos_frozen", "cos_control", "drift", "nonscorable_clickhist",
             "mrr_lost_word_A", "mrr_lost_word_B", "mrr_lost_meaning_A", "mrr_lost_meaning_B", "mrr_lost_clickhist_A"]
    lags = sorted({k[0] for k in acc})
    by_lag, lag_pt, lag_rep = [], {}, {}
    for lag in lags:
        r_ = {"lag": lag, "cells": len(acc[(lag, "n_valid")]), "n_valid": int(sum(x[0] for x in acc[(lag, "n_valid")]))}
        for k in names:
            v = acc[(lag, k)]
            pt = float(np.mean([x[0] for x in v]))
            rep = np.mean([x[1] for x in v], axis=0)
            lo, hi = ci(rep)
            r_[k], r_[k + "_lo"], r_[k + "_hi"] = pt, lo, hi
            lag_pt[(lag, k)], lag_rep[(lag, k)] = pt, rep
        by_lag.append(r_)
    pairs = [("oov_extra", "mrr_lost_word_A"), ("oov_extra", "mrr_lost_word_B"), ("drift", "mrr_lost_meaning_A"),
             ("drift", "mrr_lost_meaning_B")]       # the zero-click share of click history is 100% from lag 3: saturated, no correlation defined
    use = [l for l in lags if 2 <= l <= 13]                                              # the lags of the report; lag 14 is one cell
    rng = np.random.default_rng(20261029)
    corr = []
    for x, y in pairs:
        yp = np.array([lag_pt[(l, y)] for l in use])
        if np.ptp(yp) == 0:
            corr.append({"diagnostic": x, "against": y, "level": "lag", "spearman": "", "lo": "", "hi": "", "points": len(use), "note": "the loss is exactly 0 at every lag: nothing to correlate"})
            continue
        xp = np.array([lag_pt[(l, x)] for l in use])
        rho = float(spearman_rows(xp[None], yp)[0])
        X = np.stack([lag_rep[(l, x)] for l in use], axis=1)                          # (B, lags)
        Y = np.stack([lag_rep[(l, y)] for l in use], axis=1)
        rr = np.array([spearman_rows(X[b][None], Y[b])[0] for b in range(X.shape[0])])
        lo, hi = ci(rr[np.isfinite(rr)])
        corr.append({"diagnostic": x, "against": y, "level": "lag", "spearman": rho, "lo": lo, "hi": hi, "points": len(use), "note": "lag-level means, lags 2 to 13; interval over click resamples; both rise with the lag, so this is not independent evidence"})
        cx = np.array([c[x] for c in cells if 2 <= c["lag"] <= 13])
        cy = np.array([c[y] for c in cells if 2 <= c["lag"] <= 13])
        cl = np.array([c["lag"] for c in cells if 2 <= c["lag"] <= 13])
        rx_ = cx - np.array([cx[cl == l].mean() for l in cl])
        ry_ = cy - np.array([cy[cl == l].mean() for l in cl])
        rho2 = float(spearman_rows(rx_[None], ry_)[0])
        bs = []
        for _ in range(2000):
            i = rng.integers(0, len(rx_), len(rx_))
            if np.ptp(rx_[i]) > 0 and np.ptp(ry_[i]) > 0:
                bs.append(spearman_rows(rx_[i][None], ry_[i])[0])
        lo2, hi2 = ci(np.array(bs))
        corr.append({"diagnostic": x, "against": y, "level": "cell", "spearman": rho2, "lo": lo2, "hi": hi2, "points": len(rx_), "note": "day-by-lag cells after removing each lag's mean; interval over cells"})
    os.makedirs(os.path.join(root, out), exist_ok=True)
    def write(name, rows):
        keys = list(rows[0].keys())
        def w(q):
            with open(q, "w", newline="") as f:
                cw = csv.DictWriter(f, fieldnames=keys)
                cw.writeheader()
                cw.writerows(rows)
        M.atomic_write(os.path.join(root, out, name), w)
    write("by_lag.csv", by_lag)
    write("cells.csv", cells)
    write("correlation.csv", corr)
    print(f"written {out}: by_lag {len(by_lag)} rows, cells {len(cells)}, correlation {len(corr)}; {time.time() - t0:.0f} s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--src", default="results/decay_matrix"); ap.add_argument("--out", default="results/diag_proposed"); ap.add_argument("--B", type=int, default=1000)
    a = ap.parse_args()
    run(a.root, a.src, a.out, a.B)
