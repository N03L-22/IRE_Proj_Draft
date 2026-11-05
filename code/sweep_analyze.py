"""Weight sweep of the fusion, tuned and reported on separate days (two interleaved folds, swapped).
Rule, fixed before the results were seen: on the tuning fold, a setting's score is its MRR level averaged over lags 1, 2, 3, 5, 7 and
over both profile regimes; the best score is the chosen setting. It is then reported on the other fold only, with its decay and intervals.
Run:  python sweep_analyze.py <root> [--B 1000]
"""
import argparse, csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from analyze import analyse
import monitor as M
from scorers import SWEEP, sweep_name

LAGS = ("1", "2", "3", "5", "7")


def table(path):
    return [r for r in csv.DictReader(open(path))]


def main(root, B):
    days = sorted({c["d"] for r in M.read_manifest(os.path.join(root, "results/fusion_sweep/decay_matrix/manifest.jsonl")) for c in r["cells"]})
    folds = {"E": set(days[0::2]), "O": set(days[1::2])}
    srcs = {"sweep": "results/fusion_sweep/decay_matrix", "main": "results/decay_matrix", "fusion": "results/fusion/decay_matrix"}
    res = {}
    for f, ds in folds.items():
        for k, src in srcs.items():
            out = f"results/fusion_sweep/fold_{f}_{k}"
            analyse(root, src, out, B, only_days=ds)
            res[(f, k)] = table(os.path.join(root, out, "decay_by_lag.csv"))
    names = [sweep_name(c) for c in SWEEP]
    rows, chosen = [], {}
    for tune, test in (("E", "O"), ("O", "E")):
        sc = {}
        for n in names:
            v = [float(r["level"]) for r in res[(tune, "sweep")] if r["scorer"] == n and r["metric"] == "mrr" and r["lag_days"] in LAGS]
            sc[n] = float(np.mean(v))
        for n in names:
            rows.append(["tuning fold " + tune, n, round(sc[n], 6)])
        chosen[tune] = max(sc, key=sc.get)
        print(f"tune on {tune} ({len(folds[tune])} days): best {chosen[tune]} {sc[chosen[tune]]:.5f}; worst {min(sc, key=sc.get)} {min(sc.values()):.5f}")
        for n in sorted(names, key=lambda n: -sc[n])[:4]:
            print("   ", n, round(sc[n], 5))
    with open(os.path.join(root, "results/fusion_sweep/tuning_scores.csv"), "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["fold", "setting", "mean_mrr_lags_1_2_3_5_7_regimes_A_B"]); w.writerows(rows)
    out = []
    for tune, test in (("E", "O"), ("O", "E")):
        for k, name in (("sweep", chosen[tune]), ("main", "recency"), ("main", "word"), ("fusion", "fuse_content")):
            for r in res[(test, k)]:
                if r["scorer"] == name and r["metric"] in ("mrr", "recall10") and r["lag_days"] in ("1", "3", "7", "13"):
                    out.append([f"tuned on {tune}, reported on {test}", name, r["regime"], r["metric"], r["lag_days"], r["n_clicks"], r["level"], r["level_lo"], r["level_hi"], r["decay"], r["decay_lo"], r["decay_hi"]])
    with open(os.path.join(root, "results/fusion_sweep/test_report.csv"), "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["split", "scorer", "regime", "metric", "lag", "n_clicks", "level", "level_lo", "level_hi", "decay", "decay_lo", "decay_hi"]); w.writerows(out)
    return chosen


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("root"); ap.add_argument("--B", type=int, default=1000)
    a = ap.parse_args()
    print(main(a.root, a.B))
