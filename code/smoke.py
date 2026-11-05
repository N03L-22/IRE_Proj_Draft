"""T4 smoke test on one fit date and one evaluation day: every scorer against a seeded shuffle, in both regimes,
with the control (fit the day before), fit seconds, score time, memory and the share each scorer can score.
Run:  python smoke.py <root> [--fit 2023-05-16] [--day 2023-05-18]"""
import argparse, datetime as dt, json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import monitor as M
from cell import fit_all, score_cell, load_sample
from core import Corpus, metrics_from_ranks, boot_ci, paired_ci
from scorers import Recency, Popularity, Meaning, BM25, CoClick

ap = argparse.ArgumentParser()
ap.add_argument("root"); ap.add_argument("--fit", default="2023-05-16"); ap.add_argument("--day", default="2023-05-18")
ap.add_argument("--only", default=None)
a = ap.parse_args()
corpus = Corpus(a.root, "ebnerd", load_text=True)
scorers = [Recency(), Popularity(), Meaning(), BM25(), CoClick()]
if a.only:
    scorers = [s for s in scorers if s.name in a.only.split(",")]
clicks, prof = load_sample(corpus, a.day)
ctrl = str(dt.date.fromisoformat(a.day) - dt.timedelta(days=1))
res = {}
os.makedirs(os.path.join(a.root, "results/metrics"), exist_ok=True)
with M.Unit("t4_smoke", f"{a.fit}_{a.day}", manifest=os.path.join(a.root, "results/metrics/t4_manifest.jsonl"), disk_dir=a.root, rss_cap_gb=14) as u:
    for tag, fit in (("frozen", a.fit), ("control", ctrl)):
        with u.phase(f"fit_{tag}"):
            fitted, r_end, nwin = fit_all(corpus, fit, scorers)
        for regime in ("A", "B"):
            with u.phase(f"score_{tag}_{regime}"):
                res[(tag, regime)] = score_cell(corpus, fitted, r_end, a.day, regime, scorers, clicks, prof)
        res[(tag, "fit")] = {n: fitted[n][1] for n in fitted}
        res[(tag, "state")] = {"window_clicks": nwin, "coclick_items": fitted["clickhist"][0].n_items if "clickhist" in fitted else None,
                               "coclick_users": fitted["clickhist"][0].n_users if "clickhist" in fitted else None}
n = res[("frozen", "A")]["n"]
print(f"fit {a.fit}, evaluation day {a.day}, control fit {ctrl}; clicks sampled {res[('frozen','A')]['n_total']}, in pool {n}, excluded {res[('frozen','A')]['n_excluded']}")
print("median pool size", int(np.median(res[("frozen", "A")]["pool"])), "| strata shares S0/S1/S2:",
      [round(float((res[("frozen", "A")]["stratum"] == k).mean()), 3) for k in (0, 1, 2)])
print("fit seconds (frozen):", {k: round(v, 2) for k, v in res[("frozen", "fit")].items()}, res[("frozen", "state")])
names = [s.name for s in scorers] + ["shuffle"]
shuf = metrics_from_ranks(res[("frozen", "A")]["scorers"]["shuffle"]["rank"], res[("frozen", "A")]["pool"])
print("\nscorer      regime tag      MRR [95% CI]                recall@10 [95% CI]          scorable  MRR - shuffle [95% CI]   score s")
for name in names:
    for tag in ("frozen", "control"):
        for regime in ("A", "B"):
            r = res[(tag, regime)]
            m = metrics_from_ranks(r["scorers"][name]["rank"], r["pool"])
            mr, lo, hi, _ = boot_ci(m["mrr"]); rc, rlo, rhi, _ = boot_ci(m["recall10"])
            d, dl, dh, _ = paired_ci(m["mrr"], shuf["mrr"]) if name != "shuffle" else (0, 0, 0, 0)
            print(f"{name:11s} {regime}      {tag:8s} {mr:.4f} [{lo:.4f}, {hi:.4f}]   {rc:.4f} [{rlo:.4f}, {rhi:.4f}]   {r['scorers'][name]['scorable'].mean():.3f}     {d:+.4f} [{dl:+.4f}, {dh:+.4f}]   {r['scorers'][name]['seconds']:.1f}")
print("\nOn the clicks each scorer CAN score (same clicks for the shuffle), frozen fit:")
print("scorer      regime  n scorable   MRR scorer   MRR shuffle   difference [95% CI]")
summary = {}
for name in names[:-1]:
    for regime in ("A", "B"):
        r = res[("frozen", regime)]
        m = metrics_from_ranks(r["scorers"][name]["rank"], r["pool"])["mrr"]
        z = metrics_from_ranks(r["scorers"]["shuffle"]["rank"], r["pool"])["mrr"]
        k = r["scorers"][name]["scorable"]
        if k.sum() > 30:
            d, dl, dh, nn = paired_ci(m[k], z[k])
            print(f"{name:11s} {regime}       {int(k.sum()):6d}      {m[k].mean():.4f}       {z[k].mean():.4f}       {d:+.4f} [{dl:+.4f}, {dh:+.4f}]")
        summary[f"{name}_{regime}"] = {"scorable_share": float(k.mean()), "mrr": float(m.mean())}
json.dump({"fit": a.fit, "day": a.day, "fit_seconds": res[("frozen", "fit")], "score_seconds_per_20k_clicks": {n_: res[("frozen", "A")]["scorers"][n_]["seconds"] for n_ in names},
           "state": res[("frozen", "state")], "peak_rss_gb": u.row["peak_rss_gb"], "phases": u.row["phases"], "summary": summary,
           "median_pool": int(np.median(res[("frozen", "A")]["pool"])), "n_in_pool": n},
          open(os.path.join(a.root, "results/metrics/t4_smoke.json"), "w"), indent=1)
print("\nphases (s):", u.row["phases"], "peak RSS GB", u.row["peak_rss_gb"], "| profile truncation (A):", res[("frozen", "A")]["profile_trunc"])
