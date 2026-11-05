"""T3: the model-free stage (RQ0), from the stores.

Unseen share(h) = share of clicks in (r, r + h hours] on articles published after the fit instant r.
Fit instant = `hour`:00 local time on each fit day. 95 % bootstrap interval over fit days. Reproduces log P30 (07:00)
and P32 (all fit hours) and writes results/rq0/{unseen_share_by_hour.csv, unseen_share_by_fit_hour.csv, age_at_click.json}.
Run:  python modelfree.py <root>
"""
import csv, datetime as dt, glob, json, os, sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import polars as pl

import monitor as M

H = 48
SPEC = {
    "EB-NeRD": ("ebnerd", "UTC", dt.date(2023, 5, 10), dt.date(2023, 5, 22), "pub >= 2023-01-01, as in P28"),
    "Adressa": ("adressa", "Europe/Oslo", dt.date(2017, 1, 8), dt.date(2017, 3, 28), "clicks with a publish time"),
    "NPR": ("npr", "America/Sao_Paulo", dt.date(2022, 12, 2), dt.date(2023, 3, 28), "impression clicks only (src = 1), as in P30"),
}
P30 = {"EB-NeRD": [19.5, 77.2, 90.8, 95.4, 96.2, 97.4], "Adressa": [6.4, 24.8, 48.5, 73.2, 87.8, 93.7],
       "NPR": [1.0, 3.2, 15.5, 49.8, 85.6, 94.0]}
HOURS = [1, 3, 6, 12, 24, 48]


def load(root, key):
    lf = pl.scan_parquet(os.path.join(root, f"data/{key}/store/clicks_by_day/*/*.parquet"))
    if key == "ebnerd":
        lf = lf.filter(pl.col("pub") >= 1672531200)
    if key == "npr":
        lf = lf.filter(pl.col("src") == 1)
    d = lf.drop_nulls("pub").select(pl.col("t").cast(pl.Int64), pl.col("pub").cast(pl.Int64)).collect().sort("t")
    return d["t"].to_numpy(), d["pub"].to_numpy()


def curve(t, pub, fit_days, tz, hour):
    n = np.zeros((len(fit_days), H)); new = np.zeros((len(fit_days), H))
    for i, d in enumerate(fit_days):
        r = int(dt.datetime(d.year, d.month, d.day, hour, tzinfo=ZoneInfo(tz)).timestamp())
        lo, hi = np.searchsorted(t, [r + 1, r + H * 3600 + 1])
        hh = np.ceil((t[lo:hi] - r) / 3600).astype(int) - 1
        n[i] = np.bincount(hh, minlength=H)[:H]
        new[i] = np.bincount(hh[pub[lo:hi] > r], minlength=H)[:H]
    return n, new


def summarise(name, n, new, seed, B=2000):
    rng = np.random.default_rng(seed)          # seeded by dataset and fit hour, so the result is reproducible
    F = n.shape[0]
    pt = new.sum(0) / n.sum(0)
    bs = np.empty((B, H))
    for b in range(B):
        ix = rng.integers(0, F, F)
        bs[b] = new[ix].sum(0) / n[ix].sum(0)
    lo, hi = np.percentile(bs, [2.5, 97.5], axis=0)
    return [(name, h + 1, int(n[:, h].sum()), pt[h], lo[h], hi[h], F) for h in range(H)]


def fit_days_in(t, tz, d0, d1, hour):
    out = []
    for k in range((d1 - d0).days + 1):
        d = d0 + dt.timedelta(days=k)
        r = int(dt.datetime(d.year, d.month, d.day, hour, tzinfo=ZoneInfo(tz)).timestamp())
        if t[0] <= r and r + H * 3600 <= t[-1]:
            out.append(d)
    return out


def main(root):
    out = os.path.join(root, "results/rq0")
    os.makedirs(out, exist_ok=True)
    rows07, rows_all, age, fails = [], [], {}, []
    for name, (key, tz, d0, d1, note) in SPEC.items():
        with M.Unit("t3", key, manifest=os.path.join(out, "manifest.jsonl"), rss_cap_gb=12, disk_dir=out) as u:
            with u.phase("load"):
                t, p = load(root, key)
            a = (t - p) / 3600
            age[name] = {"clicks": int(len(t)), "median_h": float(np.median(a[a >= 0])), "within_24h": float(((a >= 0) & (a <= 24)).mean()),
                         "within_48h": float(((a >= 0) & (a <= 48)).mean()), "negative_share": float((a < 0).mean()), "corpus": note}
            with u.phase("curves"):
                for hour in (0, 3, 6, 7, 9, 12, 15, 18, 21):
                    fd = fit_days_in(t, tz, d0, d1, hour)
                    n, new = curve(t, p, fd, tz, hour)
                    k = n.sum(1) > 0
                    rows = summarise(f"{name}|fit{hour:02d}", n[k], new[k], seed=hash((key, hour)) & 0 or (hour * 1000 + len(key)))
                    rows_all += rows
                    if hour == 7:
                        rows07 += [(name, *r[1:]) for r in rows]
            M.check_finite(np.array([r[3] for r in rows_all]), "shares")
            got = [round(100 * [r for r in rows07 if r[0] == name and r[1] == h][0][3], 1) for h in HOURS]
            u.extra.update(unseen_pct_at_1_3_6_12_24_48_h=got, fit_days_07=len(fit_days_in(t, tz, d0, d1, 7)))
            if any(abs(g - e) > 0.15 for g, e in zip(got, P30[name])):
                fails.append(f"{name}: {got} vs P30 {P30[name]}")
        print(name, u.row["unseen_pct_at_1_3_6_12_24_48_h"], "P30:", P30[name], flush=True)
    with open(os.path.join(out, "unseen_share_by_hour.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["dataset", "hours_since_fit", "n_clicks", "share", "ci_lo", "ci_hi", "n_fit_days"])
        for r in rows07: w.writerow([r[0], r[1], r[2], "%.4f" % r[3], "%.4f" % r[4], "%.4f" % r[5], r[6]])
    with open(os.path.join(out, "unseen_share_by_fit_hour.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["dataset|fit_hour", "hours_since_fit", "n_clicks", "share", "ci_lo", "ci_hi", "n_fit_days"])
        for r in rows_all: w.writerow([r[0], r[1], r[2], "%.4f" % r[3], "%.4f" % r[4], "%.4f" % r[5], r[6]])
    json.dump(age, open(os.path.join(out, "age_at_click.json"), "w"), indent=1)
    print("reproduction failures:", fails or "none")
    return fails


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1]) else 0)
