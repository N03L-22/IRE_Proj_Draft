"""The decay analysis of analyze.py (levels, decay by lag with paired bootstrap, fresh-versus-decayed strata, accuracy on known) for any grid directory, WITHOUT the rebuild-schedule
replay (which needs every fit date and lag). Control = the same scorer fitted the day before the click, so a decay row exists only where that cell exists.
Run:  python analyze_only.py <root> --src results/s3_pool24 --out results/s3_pool24_analysis [--B 1000]
"""
import argparse, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import analyze

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("--src", required=True); ap.add_argument("--out", required=True); ap.add_argument("--B", type=int, default=1000)
    a = ap.parse_args()
    rows = analyze.analyse(os.path.abspath(a.root), a.src, a.out, a.B)[0]
    print(len(rows), "rows")
