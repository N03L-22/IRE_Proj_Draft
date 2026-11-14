"""Resumable stage queue for the extension runs. Run the same command again after any interruption; it never redoes finished work.
Two lanes run side by side: "heavy" (the big grids, one at a time, memory bound) and "light" (analysis scripts and data builds). A lane holds a lock file, so a
second invocation (for example after new stages were added) cannot start a lane that is already running.
A stage is done when its own completion check passes (every expected fit date is in its manifest, or its output file exists), not because a flag was written.
Inside a grid stage qrun.py also skips finished cells, so an interrupted stage loses at most the fit dates in flight.
State: results/queue/state.jsonl (append only), logs: results/queue/logs/<stage>.log, stop cleanly after the current stage: touch results/queue/STOP.
Run:  python queue_run.py <root> [--lane heavy|light|all] [--only S2,S3] [--list]
"""
import argparse, datetime as dt, fcntl, json, os, shutil, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
FITS = ("2023-05-10", "2023-05-23")
LAST = "2023-05-24"
MIN_FREE_GB = 20
WAIT = False


def days(a, b):
    a, b = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    return [str(a + dt.timedelta(days=i)) for i in range((b - a).days + 1)]


def grid(sid, out, scorers, workers, fits=FITS, extra=(), desc=""):
    return dict(id=sid, lane="heavy", desc=desc, kind="grid", out=out, fits=days(*fits),
                cmd=["qrun.py", ".", "--stage", sid, "--fits", *fits, "--last", LAST, "--out", out, "--scorers", scorers, "--workers", str(workers), *extra])


def ngrid(sid, out, name, fits, last, scorers, workers, step=1, extra=(), needs=(), desc=""):
    return dict(id=sid, lane="heavy", desc=desc, kind="grid", out=out, fits=days(*fits)[::step], needs=list(needs),
                cmd=["qrun.py", ".", "--stage", sid, "--name", name, "--fits", *fits, "--fit-step", str(step), "--last", last, "--out", out, "--scorers", scorers, "--workers", str(workers), *extra])


def impr(sid, out, scorers, workers, mode, desc):
    return dict(id=sid, lane="heavy", desc=desc, kind="grid", out=out, fits=days("2023-05-17", "2023-05-24"), needs=["results/impressions/build.json"],
                cmd=["impr_run.py", ".", "--stage", sid, "--out", out, "--scorers", scorers, "--workers", str(workers), "--mode", mode])


def script(sid, lane, desc, script_name, outputs, args=(), needs=(), after=()):
    return dict(id=sid, lane=lane, desc=desc, kind="script", outputs=list(outputs), script=script_name, needs=list(needs), after=list(after), cmd=[script_name, ".", *args])


CHEAP = "recency,genre,fuse_genre,genre_perm,genre_prior,fuse_genre_perm,fuse_genre_prior"
CORE = "recency,popularity,word,meaning,genre,fuse_genre"
STAGES = [
    # ---- heavy lane: one grid at a time
    grid("S2", "results/s2_perm", CHEAP, 6, desc="permutation and prior checks for the genre gain, full grid"),
    grid("S7", "results/s7_trend", "recency,trend_h1,trend_h3,trend_h6,trend_h12,trend_h24", 4, fits=("2023-05-10", "2023-05-10"),
         desc="live trending baseline (not fitted: one fit date covers every day)"),
    grid("S7b", "results/s7b_trend_delay", "recency,trend_w10,trend_w30,trend_h1,trend_h1_d5,trend_h1_d15,trend_h1_d30,trend_h1_d60,trend_h1_d180,trend_h1_d360", 2, fits=("2023-05-10", "2023-05-10"),
         desc="trending: shorter windows and delayed counts (how fast a live click signal goes stale)"),
    grid("S3a", "results/s3_pool24", CORE, 6, extra=["--pool-window-h", "24"], desc="pool window 24 h"),
    grid("S3b", "results/s3_pool72", CORE, 4, extra=["--pool-window-h", "72"], desc="pool window 72 h"),
    grid("S4a", "results/s4_fit3", CORE, 6, extra=["--fit-window-days", "3"], desc="fit window 3 days"),
    grid("S4b", "results/s4_fit5", CORE, 6, extra=["--fit-window-days", "5"], desc="fit window 5 days"),
    grid("S4c", "results/s4_fit10", CORE, 6, fits=("2023-05-13", "2023-05-23"), extra=["--fit-window-days", "10"], desc="fit window 10 days, fit dates from 13 May"),
    grid("S5", "results/s5_hybrid", "recency,popularity,clickhist,fuse_click_recency,fuse_pop_recency", 2, desc="hybrid with recency fallback"),
    grid("S6", "results/s6_topk", "recency,popularity,clickhist,word,meaning,genre,fuse_genre,trend_h3", 2, extra=["--topk", "--lags", "1,3,7,13"],
         desc="age of the top-10 articles each scorer would show"),
    grid("S4d", "results/s4_fit3_click", "popularity,clickhist", 2, extra=["--fit-window-days", "3", "--lags", "1,3,7"], desc="click-based signals, fit window 3 days"),
    grid("S4e", "results/s4_fit5_click", "popularity,clickhist", 2, extra=["--fit-window-days", "5", "--lags", "1,3,7"], desc="click-based signals, fit window 5 days"),
    # ---- parameter sweeps inside each model type, and a second dataset
    grid("S11", "results/s11_params", "recency,word,word_k06,word_k20,word_b03,word_b09,meaning,meaning_rw5,meaning_rw15", 6, desc="BM25 k1 and b, recency-weighted meaning profile (defaults inside as a check)"),
    grid("S9a", "results/s9_cap10", "recency,word,meaning,genre,fuse_genre", 6, extra=["--profile-cap", "10"], desc="profile memory 10 clicks"),
    grid("S9b", "results/s9_cap25", "recency,word,meaning,genre,fuse_genre", 6, extra=["--profile-cap", "25"], desc="profile memory 25 clicks"),
    grid("S9c", "results/s9_cap100", "recency,word,meaning,genre,fuse_genre", 6, extra=["--profile-cap", "100"], desc="profile memory 100 clicks"),
    grid("S9d", "results/s9_cap200", "recency,word,meaning,genre,fuse_genre", 6, extra=["--profile-cap", "200"], desc="profile memory 200 clicks"),
    ngrid("S10", "results/s10_npr_trend", "npr", ("2023-03-10", "2023-03-23"), "2023-03-24", "recency,popularity,trend_h1,trend_h3,trend_h6,trend_h12,trend_h24,genre,fuse_genre,genre_prior,fuse_genre_prior", 4, desc="live trending and genre on the second dataset (NPR)"),
    ngrid("S12b", "results/s12_npr_long", "npr", ("2023-01-10", "2023-04-02"), "2023-04-30", "recency,popularity,word,meaning,clickhist,genre,fuse_genre", 3, step=3, extra=["--lags", "1,4,7,13,28", "--first-day", "2023-01-18"],
          needs=["data/npr/store/sample/clicks_d=2023-04-30.parquet"], desc="NPR over the whole Jan-Apr span, lags up to 28 days"),
    # ---- second reader cohort (train users), Adressa decay run, sample size and seed
    script("S13a", "heavy", "second cohort: click store of the train users", "cohort2_build.py", ["data/ebnerd_c2/store/build_done.json"], args=("--workers", "6")),
    dict(id="S13b", lane="heavy", desc="second cohort: evaluation samples", kind="script", script="sample.py", needs=["data/ebnerd_c2/store/build_done.json"], after=["S13a"],
         outputs=[f"data/ebnerd_c2/store/sample/clicks_d={d}.parquet" for d in days("2023-05-05", "2023-05-15")],
         cmd=["sample.py", ".", "ebnerd_c2", "2023-05-05", "2023-05-15", "--workers", "4"]),
    ngrid("S13c", "results/s13_c2", "ebnerd_c2", ("2023-05-04", "2023-05-14"), "2023-05-15", "recency,popularity,word,meaning,genre,fuse_genre,genre_prior,fuse_genre_prior,trend_h1,trend_h3", 6,
          needs=["data/ebnerd_c2/store/sample/clicks_d=2023-05-15.parquet"], desc="second cohort, decay matrix"),
    ngrid("S13d", "results/s13_c2_click", "ebnerd_c2", ("2023-05-04", "2023-05-14"), "2023-05-15", "clickhist,fuse_click_recency", 2, extra=["--cap-gb", "10.5"],
          needs=["data/ebnerd_c2/store/sample/clicks_d=2023-05-15.parquet"], desc="second cohort, click history"),
    dict(id="S14a", lane="heavy", desc="Adressa: evaluation samples", kind="script", script="sample.py", needs=[],
         outputs=[f"data/adressa/store/sample/clicks_d={d}.parquet" for d in days("2017-01-09", "2017-03-31")],
         cmd=["sample.py", ".", "adressa", "2017-01-09", "2017-03-31", "--workers", "4"]),
    ngrid("S14b", "results/s14_adressa", "adressa", ("2017-01-08", "2017-03-24"), "2017-03-31", "recency,popularity,word,meaning,clickhist,genre,fuse_genre,trend_h1,trend_h3,trend_h6,trend_h12,trend_h24", 4,
          step=3, extra=["--lags", "1,4,7,13,28"], needs=["data/adressa/store/sample/clicks_d=2017-03-31.parquet"], desc="Adressa decay matrix (90 days, lags up to 28)"),
    dict(id="S16a", lane="heavy", desc="sample with another seed (11), same size", kind="script", script="sample_alt.py", needs=[],
         outputs=[f"data/ebnerd/store/sample_s11/clicks_d={d}.parquet" for d in days("2023-05-11", "2023-05-24")],
         cmd=["sample_alt.py", ".", "ebnerd", "2023-05-11", "2023-05-24", "--tag", "s11", "--n", "20000", "--seed", "11", "--workers", "4"]),
    grid("S16b", "results/s16_seed11", "recency,popularity,word,meaning,genre,fuse_genre", 6, extra=["--sample-dir", "sample_s11"], desc="decay matrix on the seed-11 sample"),
    dict(id="S16c", lane="heavy", desc="sample four times as large (80,000 clicks a day, same seed: contains the main sample)", kind="script", script="sample_alt.py", needs=[],
         outputs=[f"data/ebnerd/store/sample_n80k/clicks_d={d}.parquet" for d in days("2023-05-11", "2023-05-24")],
         cmd=["sample_alt.py", ".", "ebnerd", "2023-05-11", "2023-05-24", "--tag", "n80k", "--n", "80000", "--seed", "20261029", "--workers", "4"]),
    grid("S16d", "results/s16_n80k", "recency,word,meaning,genre,fuse_genre", 3, extra=["--sample-dir", "sample_n80k", "--lags", "1,3,7"], desc="decay matrix on the 80,000-click sample"),
    # ---- real-impression evaluation (cohort impressions 25-31 May; the slate is the candidate set)
    impr("S8c", "results/impr_slate", "recency,popularity,word,meaning,genre,genre_prior,fuse_genre,fuse_genre_prior,fuse_recency,fuse_wmrg,site_order", 6, "slate", "impression slates as candidates"),
    impr("S8d", "results/impr_pool", "recency,popularity,word,meaning,genre,genre_prior,fuse_genre,fuse_genre_prior,fuse_recency,fuse_wmrg", 6, "pool", "same clicks, 48 h pool as candidates"),
    impr("S8e", "results/impr_slate_click", "clickhist,fuse_click_recency,fuse_pop_recency", 2, "slate", "click-based signals on slates"),
    impr("S8f", "results/impr_pool_click", "clickhist,fuse_click_recency,fuse_pop_recency", 2, "pool", "click-based signals, pool"),
    script("S8g", "heavy", "impression analysis: levels, staleness loss, paired comparisons", "impr_analyze.py", ["results/impressions/paired_comparisons.csv"], after=["S8c", "S8d", "S8e", "S8f"]),
    # ---- light lane: analyses and builds (each script lives in code/ and writes its outputs atomically)
    script("S8a", "light", "real-impression feasibility counts", "impr_feasibility.py", ["results/impressions/feasibility.json"]),
    script("S8b", "light", "real-impression sample and profile build", "impr_build.py", ["results/impressions/build.json"]),
    dict(id="S12a", lane="light", desc="NPR evaluation samples for the whole span", kind="script", script="sample.py", needs=[],
         outputs=[f"data/npr/store/sample/clicks_d={d}.parquet" for d in days("2023-01-18", "2023-04-30")],
         cmd=["sample.py", ".", "npr", "2023-01-18", "2023-04-30", "--src-only", "--workers", "4"]),
    script("S1d", "light", "decay in all four metrics", "metric_robustness.py", ["results/metric_robustness/decay_by_metric.csv"]),
    script("S1e", "light", "intervals by click, reader, day and reader+day", "cluster_ci.py", ["results/cluster_ci/intervals.csv"]),
    script("S1a", "light", "click lift by article age, half-lives, per category", "age_lift.py", ["results/age_lift/lift_by_age.csv"]),
    script("S1b", "light", "half-life fits of the existing decay curves", "halflife_fits.py", ["results/halflife/fits.csv"]),
    script("S1c", "light", "decay by weekday, hour of day and reader activity", "segment_cuts.py", ["results/segments/decay_by_segment.csv"]),
]


ANALYSE = ["S3a", "S3b", "S4a", "S4b", "S4c", "S4d", "S4e", "S5", "S9a", "S9b", "S9c", "S9d", "S11", "S10", "S12b", "S13c", "S13d", "S14b", "S16b", "S16d"]
for _s in [x for x in STAGES if x["id"] in ANALYSE]:
    STAGES.append(script("A_" + _s["id"], "light", "decay analysis of " + _s["out"], "analyze_only.py", [_s["out"] + "_analysis/decay_by_lag.csv"], args=("--src", _s["out"], "--out", _s["out"] + "_analysis"), after=[_s["id"]]))
STAGES.append(script("A_S6", "light", "what the reader sees: age of the top-10", "topk_analyze.py", ["results/s6_topk_analysis/topk_by_lag.csv"], after=["S6"]))
STAGES.append(script("A_S7b", "light", "freshness delay curve of live trending", "delay_curve.py", ["results/s7b_trend_delay/analysis.csv"], after=["S7b"]))
PRIORITY = ["S7b", "S3b", "S8c", "S8d", "S8e", "S8f", "S8g", "S11", "S9a", "S9b", "S9c", "S9d", "S10", "S16a", "S16b", "S13a", "S13b", "S13c", "S13d", "S14a", "S14b", "S12b", "S16c", "S16d", "S6", "S4d", "S4e"]
STAGES.sort(key=lambda s: PRIORITY.index(s["id"]) if s["id"] in PRIORITY else -1)        # stable: the rest keep their order and run first; the listed ones run in this order


def log_dir(root):
    return os.path.join(root, "results/queue")


def event(root, **kw):
    os.makedirs(log_dir(root), exist_ok=True)
    kw["t"] = dt.datetime.now().isoformat(timespec="seconds")
    with open(os.path.join(log_dir(root), "state.jsonl"), "a") as f:
        f.write(json.dumps(kw) + "\n")


def is_done(root, s):
    if s["kind"] == "grid":
        mf = os.path.join(root, s["out"], "manifest.jsonl")
        if not os.path.exists(mf):
            return False
        have = {json.loads(l)["unit"] for l in open(mf) if l.strip() and json.loads(l).get("status") == "ok"}
        return all(f"r={r}" in have for r in s["fits"])
    return all(os.path.exists(os.path.join(root, o)) for o in s["outputs"])


def ready(s, root=None):
    if s["kind"] != "grid" and not os.path.exists(os.path.join(HERE, s["script"])):
        return False
    if root is None:
        return True
    BY_ID = {x["id"]: x for x in STAGES}
    return all(os.path.exists(os.path.join(root, n)) for n in s.get("needs", [])) and all(is_done(root, BY_ID[a]) for a in s.get("after", []))


def run_stage(root, s):
    if shutil.disk_usage(root).free < MIN_FREE_GB * 2**30:
        event(root, stage=s["id"], event="refused", why="free disk below guard")
        return False
    os.makedirs(os.path.join(log_dir(root), "logs"), exist_ok=True)
    t0 = time.time()
    event(root, stage=s["id"], event="start", desc=s["desc"])
    with open(os.path.join(log_dir(root), "logs", f"{s['id']}.log"), "a") as lg:
        lg.write(f"\n=== {dt.datetime.now().isoformat(timespec='seconds')} start {s['id']} ===\n")
        lg.flush()
        rc = subprocess.call([sys.executable, "-I", os.path.join(HERE, s["cmd"][0]), *s["cmd"][1:]], cwd=root, stdout=lg, stderr=subprocess.STDOUT)
    ok = rc == 0 and is_done(root, s)
    event(root, stage=s["id"], event="done" if ok else "fail", rc=rc, seconds=round(time.time() - t0, 1))
    return ok


def lane(root, name, only):
    lock = open(os.path.join(log_dir(root), f"lane_{name}.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | (0 if WAIT else fcntl.LOCK_NB))
    except OSError:
        print(f"lane {name}: already running, left alone")
        return
    failed, noted, idle_since = set(), set(), None
    while True:
        progressed, waiting = False, False
        for s in STAGES:
            if s["lane"] != name or (only and s["id"] not in only) or s["id"] in failed:
                continue
            if os.path.exists(os.path.join(log_dir(root), "STOP")):
                event(root, event="stop", lane=name)
                return
            if is_done(root, s):
                if s["id"] not in noted:
                    noted.add(s["id"])
                    event(root, stage=s["id"], event="skip", why="already done")
                continue
            if not ready(s, root):
                waiting = True                                  # blocked on a file, a stage of the other lane, or a script not written yet
                continue
            progressed = True
            if not run_stage(root, s):
                failed.add(s["id"])
        if not waiting:
            return
        if progressed:
            idle_since = None
        else:
            idle_since = idle_since or time.time()
            if time.time() - idle_since > 90 * 60:              # nothing ran for 90 minutes: stop waiting (a stage it depends on probably failed)
                event(root, event="gave_up_waiting", lane=name)
                return
            time.sleep(30)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--lane", default="all"); ap.add_argument("--only", default=None); ap.add_argument("--list", action="store_true"); ap.add_argument("--wait", action="store_true"); ap.add_argument("--keep-stop", action="store_true")
    a = ap.parse_args()
    WAIT = a.wait
    root = os.path.abspath(a.root)
    only = set(a.only.split(",")) if a.only else None
    if a.list:
        for s in STAGES:
            print(f"{s['id']:5} {s['lane']:6} {'done' if is_done(root, s) else ('pending' if ready(s, root) else 'not ready'):12} {s['desc']}")
        sys.exit(0)
    os.makedirs(log_dir(root), exist_ok=True)
    if not a.keep_stop and os.path.exists(os.path.join(log_dir(root), "STOP")):          # STOP stops the drivers that are running; a fresh start clears it (unless --keep-stop)
        os.remove(os.path.join(log_dir(root), "STOP"))
    lanes = ["heavy", "light"] if a.lane == "all" else [a.lane]
    th = [threading.Thread(target=lane, args=(root, n, only)) for n in lanes]
    [t.start() for t in th]
    [t.join() for t in th]
    print("queue pass finished; run again to resume anything unfinished")
