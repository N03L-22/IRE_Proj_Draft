#!/bin/bash
# =============================================================================
# run_ada.sh -- SLURM submission script for the Ada cluster (IRE temporal-
# decay project). Modelled on the Assignment-3 run_ada.sh for this account
# (cs4406.16): same venv pattern, same resource limits, same "submit each
# part separately" structure, since the full pipeline does not fit in one
# 6h job.
#
# Submit from inside code/'s parent (this file lives at the project root)
# with:
#   sbatch run_ada.sh part1     T1 stores (ebnerd/npr/adressa) + T1d embeddings (GPU)
#   sbatch run_ada.sh part2     T2/T6h samples + T3 model-free + T4 smoke + T5 gate
#   sbatch run_ada.sh part3     T6 main decay matrix (EB-NeRD, base scorers)
#   sbatch run_ada.sh part4     T6 fusion + fusion-weight-sweep decay matrices
#   sbatch run_ada.sh part5     T6 never-clicked sensitivity + T9 NPR decay matrix
#   sbatch run_ada.sh part6     T6h hourly decay matrix
#   sbatch run_ada.sh part7     T7/T8/T9 analysis, sim_gap, sweep readout, volume check
#   sbatch run_ada.sh           (no arg) runs all parts in one job -- only
#                                 realistic with QUICK_TEST=true below; the
#                                 full grid will not fit in one 6h allocation
#
# Parts must be submitted in order (each reads the previous part's output
# off shared storage); chain them with
#   sbatch --dependency=afterok:<jobid> run_ada.sh partN
# if you don't want to wait for each to finish by hand.
#
# RESUME: every stage below is backed by a manifest and skips finished units
# (stage-plan.md 2.1's resume rule), so if a part is killed at the 6h wall
# limit, resubmitting the exact same `sbatch run_ada.sh partN` continues
# from the unit that was in flight -- never resubmit with a different date
# range mid-part, or the "done" bookkeeping won't line up.
#
# IMPORTANT: Ada's compute nodes have no internet access. Before submitting
# part1, (a) copy the raw datasets onto Ada under $PROJECT_ROOT/data/ via
# scp/rsync, and (b) run setup_ada_env.sh ON THE LOGIN NODE -- it creates the
# venv and pre-downloads the frozen MiniLM encoder that part1's embed.py
# step needs (embed.py hardcodes local_files_only=True, so it cannot fetch
# the model itself). logs/ must already exist under the project root.
# =============================================================================

#SBATCH --job-name=ire-decay
#SBATCH --output=logs/output_%x_%j.out
#SBATCH --error=logs/error_%x_%j.err
#SBATCH --gres=gpu:1
#SBATCH --time=06:00:00           # near this account's wall-clock max; see note above about splitting into parts
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4         # this account's cpu-per-task limit
#SBATCH --mem=28G                 # just under this account's mem limit, leaves a little headroom

set -euo pipefail

# ---------------------------------------------------------------- EDIT ME ---
PROJECT_ROOT="${PROJECT_ROOT:-/home2/cs4406.16/IRE-Term-Project}"   # same path setup_ada_env.sh uses
QUICK_TEST=false   # true = tiny date ranges, for a fast end-to-end sanity run of a part before the real one
# -----------------------------------------------------------------------------

CODE_DIR="$PROJECT_ROOT/code"
LOG_DIR="$PROJECT_ROOT/logs"
cd "$CODE_DIR"

# Determinism contract (stage-plan.md 2.1): parallelism must come from the
# multiprocessing worker pools below (--workers N), never from a multi-
# threaded BLAS -- a thread count that varies with allocation would change
# floating-point summation order and break the "same bytes on any worker
# count" guarantee that T5 tests. Do NOT set these to SLURM_CPUS_PER_TASK.
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1

echo "== activating venv =="
source "$CODE_DIR/.venv/bin/activate"

echo "== sanity check: raw data present =="
for p in data/ebnerd/large data/npr/raw; do
  [ -d "$PROJECT_ROOT/$p" ] || { echo "MISSING $PROJECT_ROOT/$p -- copy the raw dataset onto Ada before submitting" >&2; exit 1; }
done

mkdir -p "$LOG_DIR"

# ---- worker counts, sized to this account's 4 cpus / 28G mem -------------
WORKERS_STORE=4          # T1a/b/c (ebnerd_store.py, other_stores.py), CAP_GB=2.0/worker -> fine at 4
WORKERS_SAMPLE=4          # T2 sample.py
WORKERS_SAMPLE_H=3       # T6h sample_hourly.py
WORKERS_DECAY=3          # T6 decay.py: CAP_GB=8.0/worker, so 3*8=24G stays under the 28G mem limit
WORKERS_DECAYH=2         # T6h decayh.py: same per-worker memory as decay.py, kept lower since units run longer
WORKERS_SIMGAP=3         # sim_gap.py
B_BOOT=1000              # bootstrap replicates for every *_analyze.py / analyze*.py script

# ---- date ranges (from the final report / stage-plan) ---------------------
if [ "$QUICK_TEST" = true ]; then
  EB_FIT0=2023-05-10; EB_FIT1=2023-05-12; EB_LAST=2023-05-13
  EB_SAMPLE0=2023-05-11; EB_SAMPLE1=2023-05-13
  HOUR_FIRST=2023-05-17; HOUR_LAST=2023-05-18; HOUR_FITDAY0=2023-05-17; HOUR_FITDAY1=2023-05-17
  NPR_FIT0=2023-03-10; NPR_FIT1=2023-03-12; NPR_LAST=2023-03-13
  NPR_SAMPLE0=2023-03-11; NPR_SAMPLE1=2023-03-13
else
  EB_FIT0=2023-05-10; EB_FIT1=2023-05-23; EB_LAST=2023-05-24
  EB_SAMPLE0=2023-05-11; EB_SAMPLE1=2023-05-24
  HOUR_FIRST=2023-05-17; HOUR_LAST=2023-05-22; HOUR_FITDAY0=2023-05-17; HOUR_FITDAY1=2023-05-21
  NPR_FIT0=2023-03-10; NPR_FIT1=2023-03-23; NPR_LAST=2023-03-24
  NPR_SAMPLE0=2023-03-11; NPR_SAMPLE1=2023-03-24
fi

step() { echo; echo "=== $(date '+%F %T') :: $* ==="; }
run()  { local name="$1"; shift; echo "+ $*" | tee -a "$LOG_DIR/$name.log"; "$@" 2>&1 | tee -a "$LOG_DIR/$name.log"; }

# =============================================================================
# part1 -- unit tests, T1 stores, T1d embeddings (GPU)
# =============================================================================
part1() {
  step "unit tests"
  run test_monitor python test_monitor.py
  run test_core    python test_core.py
  run test_adressa python -I -m unittest test_adressa_to_parquet

  step "T1a: EB-NeRD store"
  run t1a_store  python ebnerd_store.py "$PROJECT_ROOT" --workers "$WORKERS_STORE"
  run t1a_report python ebnerd_report.py "$PROJECT_ROOT"

  step "T1b: NPR store"
  run t1b_store python other_stores.py "$PROJECT_ROOT" npr --workers "$WORKERS_STORE"

  step "T1c: Adressa store (optional -- turnover measure only)"
  if [ -d "$PROJECT_ROOT/data/adressa/parquet" ]; then
    run t1c_store python other_stores.py "$PROJECT_ROOT" adressa --workers "$WORKERS_STORE"
  elif [ -f "$PROJECT_ROOT/data/three_month.tar.gz" ]; then
    run t1c_convert python adressa_to_parquet.py "$PROJECT_ROOT/data/three_month.tar.gz" "$PROJECT_ROOT/data/adressa/parquet"
    run t1c_store   python other_stores.py "$PROJECT_ROOT" adressa --workers "$WORKERS_STORE"
  else
    echo "No Adressa data found -- skipping (optional in this study)."
  fi

  step "T1d: embeddings (GPU)"
  run t1d_embed python -P embed.py "$PROJECT_ROOT" ebnerd npr $( [ -d "$PROJECT_ROOT/data/adressa/store" ] && echo adressa )
}

# =============================================================================
# part2 -- T2/T6h samples, T3 model-free, T4 smoke, T5 gate
# =============================================================================
part2() {
  step "T2: EB-NeRD sample"
  run t2_sample python sample.py "$PROJECT_ROOT" ebnerd "$EB_SAMPLE0" "$EB_SAMPLE1" --workers "$WORKERS_SAMPLE"

  step "T2: NPR sample (impression clicks only)"
  run t2_sample_npr python sample.py "$PROJECT_ROOT" npr "$NPR_SAMPLE0" "$NPR_SAMPLE1" --src-only --workers "$WORKERS_SAMPLE"

  step "T6h: hourly sample"
  run t6h_sample python sample_hourly.py "$PROJECT_ROOT" "$HOUR_FIRST" "$HOUR_LAST" --workers "$WORKERS_SAMPLE_H"

  step "T3: model-free RQ0"
  run t3_modelfree python modelfree.py "$PROJECT_ROOT"

  step "T4: smoke test"
  run t4_smoke python smoke.py "$PROJECT_ROOT"

  step "T5: leakage / determinism gate (fails the job if it doesn't pass)"
  run t5_gate python test_t5.py "$PROJECT_ROOT"
}

# =============================================================================
# part3 -- T6 main decay matrix
# =============================================================================
part3() {
  step "T6: main decay matrix (EB-NeRD, base scorers)"
  run t6_main python decay.py "$PROJECT_ROOT" --fits "$EB_FIT0" "$EB_FIT1" --last "$EB_LAST" \
    --workers "$WORKERS_DECAY" --out results/decay_matrix
}

# =============================================================================
# part4 -- T6 fusion + weight-sweep decay matrices
# =============================================================================
part4() {
  step "T6: fusion decay matrix (content fusion, content+recency)"
  run t6_fusion python decay.py "$PROJECT_ROOT" --fits "$EB_FIT0" "$EB_FIT1" --last "$EB_LAST" \
    --workers "$WORKERS_DECAY" --out results/fusion/decay_matrix --scorers fuse_content,fuse_recency

  step "T6: fusion weight-sweep decay matrix"
  run t6_sweep python decay.py "$PROJECT_ROOT" --fits "$EB_FIT0" "$EB_FIT1" --last "$EB_LAST" \
    --workers "$WORKERS_DECAY" --out results/fusion_sweep/decay_matrix --scorers sweep
}

# =============================================================================
# part5 -- T6 never-clicked sensitivity + T9 NPR decay matrix
# =============================================================================
part5() {
  step "T6: never-clicked sensitivity run"
  run t6_clickedonly python decay.py "$PROJECT_ROOT" --fits "$EB_FIT0" "$EB_FIT1" --last "$EB_LAST" \
    --workers "$WORKERS_DECAY" --out results/sens_clicked_only/decay_matrix --clicked-only

  step "T9: NPR decay matrix"
  run t9_npr python decay.py "$PROJECT_ROOT" --fits "$NPR_FIT0" "$NPR_FIT1" --last "$NPR_LAST" \
    --workers "$WORKERS_DECAY" --out results/npr/decay_matrix --name npr
}

# =============================================================================
# part6 -- T6h hourly decay matrix
# =============================================================================
part6() {
  step "T6h: hourly decay matrix"
  run t6h python decayh.py "$PROJECT_ROOT" --first "$HOUR_FIRST" --last "$HOUR_LAST" \
    --fit-days "$HOUR_FITDAY0" "$HOUR_FITDAY1" --step 3 --workers "$WORKERS_DECAYH"
}

# =============================================================================
# part7 -- T7/T8/T9 analysis, sim_gap, fusion-sweep readout, volume check
# =============================================================================
part7() {
  step "T7/T8: main analysis"
  run t7_main python analyze.py "$PROJECT_ROOT" --src results/decay_matrix --out results/rq1_rq2 --rq3 results/rq3 --B "$B_BOOT"

  step "T7/T8: fusion analysis"
  run t7_fusion python analyze.py "$PROJECT_ROOT" --src results/fusion/decay_matrix --out results/fusion/rq1_rq2 --rq3 results/fusion/rq3 --B "$B_BOOT"

  step "T7/T8: never-clicked sensitivity analysis"
  run t7_clickedonly python analyze.py "$PROJECT_ROOT" --src results/sens_clicked_only/decay_matrix --out results/sens_clicked_only/rq1_rq2 --rq3 results/sens_clicked_only/rq3 --B "$B_BOOT"

  step "T9: NPR analysis"
  run t9_npr_analyze python analyze.py "$PROJECT_ROOT" --src results/npr/decay_matrix --out results/npr/rq1_rq2 --rq3 results/npr/rq3 --B "$B_BOOT"

  step "T6h analysis: hourly decay"
  run t7_hourly python analyze_hourly.py "$PROJECT_ROOT" --src results/decay_hourly --out results/rq_hourly --B "$B_BOOT"

  step "sim_gap: clicked-vs-pool similarity"
  run simgap python sim_gap.py "$PROJECT_ROOT" --fits "$EB_FIT0" "$EB_FIT1" --last "$EB_LAST" \
    --workers "$WORKERS_SIMGAP" --out results/sim_gap
  run simgap_analyze python sim_gap_analyze.py "$PROJECT_ROOT" --src results/sim_gap --out results/sim_gap/sim_gap_by_lag.csv --B "$B_BOOT"

  step "fusion sweep: tune/test readout"
  run sweep_analyze python sweep_analyze.py "$PROJECT_ROOT" --B "$B_BOOT"

  step "volume check (exploratory)"
  run volume_check python volume_check.py "$PROJECT_ROOT"

  step "ALL ANALYSIS DONE"
  echo "Results are under $PROJECT_ROOT/results/ ; per-stage logs are under $LOG_DIR/"
}

# ---- dispatch ---------------------------------------------------------------
case "${1:-all}" in
  part1) part1 ;;
  part2) part2 ;;
  part3) part3 ;;
  part4) part4 ;;
  part5) part5 ;;
  part6) part6 ;;
  part7) part7 ;;
  all)
    echo "WARNING: running every part in one job. This will almost certainly" >&2
    echo "exceed the 6h wall limit unless QUICK_TEST=true. Prefer submitting" >&2
    echo "part1..part7 separately (see the header comment)." >&2
    part1; part2; part3; part4; part5; part6; part7
    ;;
  *) echo "usage: sbatch run_ada.sh [part1|part2|part3|part4|part5|part6|part7]" >&2; exit 2 ;;
esac
