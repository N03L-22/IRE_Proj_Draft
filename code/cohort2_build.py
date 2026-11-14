"""Second reader cohort: the click store of EB-NeRD's TRAIN users (their timestamped reading history, 27 Apr to 18 May 2023), built with the unchanged slice code of
ebnerd_store.py into data/ebnerd_c2/store (the same shape as the validation cohort's store). The raw history is linked in, not copied; articles and embeddings are the same
files as the main store (copied / linked), since the article set is shared. Different readers, earlier weeks: a replication of the main matrix on independent data.
Run:  python cohort2_build.py <root> [--workers 6] [--slices 48]
"""
import argparse, json, multiprocessing as mp, os, shutil, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import polars as pl

import ebnerd_store as E
import monitor as M


def main(root, workers, slices):
    main_st = os.path.join(root, "data/ebnerd/store")
    base = os.path.join(root, "data/ebnerd_c2")
    raw, st = os.path.join(base, "raw"), os.path.join(base, "store")
    os.makedirs(os.path.join(raw, "validation"), exist_ok=True)       # process_slice reads <raw>/validation/history.parquet: here it is the train users' history
    os.makedirs(st, exist_ok=True)
    link = os.path.join(raw, "validation/history.parquet")
    if not os.path.lexists(link):
        os.symlink(os.path.relpath(os.path.join(root, "data/ebnerd/large/train/history.parquet"), os.path.dirname(link)), link)
    if not os.path.exists(os.path.join(st, "articles.parquet")):
        shutil.copy2(os.path.join(main_st, "articles.parquet"), os.path.join(st, "articles.parquet"))
    for f in ("emb_ids.npy", "emb_minilm.npy"):
        dst = os.path.join(st, f)
        if not os.path.lexists(dst):
            os.symlink(os.path.relpath(os.path.join(main_st, f), st), dst)
    E.clean_partials(st)
    manifest = os.path.join(st, "manifest.jsonl")
    done = {r["unit"] for r in M.read_manifest(manifest)}
    n_rows = pl.scan_parquet(link).select(pl.len()).collect().item()
    todo = [(raw, st, i, off, n, manifest) for i, off, n in E.slice_bounds(n_rows, slices) if f"slice{i:02d}" not in done]
    for _, _, i, _, _, _ in todo:                                       # parts of an unfinished slice are removed first, as in ebnerd_store.build
        for dp, _, fs in os.walk(os.path.join(st, "clicks_by_day")):
            for f in fs:
                if f == f"part-{i:02d}.parquet":
                    os.remove(os.path.join(dp, f))
    with mp.get_context("spawn").Pool(workers) as pool:
        for u in pool.imap_unordered(E.process_slice, todo):
            print("done", u, flush=True)
    rows = M.read_manifest(manifest)
    assert {r["unit"] for r in rows} == {f"slice{i:02d}" for i, _, _ in E.slice_bounds(n_rows, slices)}, "incomplete"
    info = {"slices": len(rows), "history_rows": n_rows, "rows_out": sum(r.get("rows_out", 0) for r in rows), "duplicates": sum(r.get("duplicates", 0) for r in rows)}
    tmp = os.path.join(st, "build_done.json.tmp")
    json.dump(info, open(tmp, "w"), indent=1)
    os.replace(tmp, os.path.join(st, "build_done.json"))
    print(info)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--workers", type=int, default=6); ap.add_argument("--slices", type=int, default=48)
    a = ap.parse_args()
    main(os.path.abspath(a.root), a.workers, a.slices)
