#!/bin/bash
# =============================================================================
# setup_ada_env.sh -- create the venv and install packages for the IRE
# temporal-decay project on Ada.
#
# Run this ON THE LOGIN NODE, NOT via sbatch: Ada's compute nodes have no
# internet access (same constraint called out in the Assignment-3 run_ada.sh
# this is modelled on), so pip installs and the one-off Hugging Face model
# download below must happen here, before anything is submitted to the queue.
#
# Usage:  bash setup_ada_env.sh
# Re-run any time to update packages -- venv creation and pip installs are
# idempotent.
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------- EDIT ME ---
PROJECT_ROOT="${PROJECT_ROOT:-/home2/cs4406.16/IRE-Term-Project}"  # same PROJECT_ROOT run_ada.sh should use
PYTHON_BIN="${PYTHON_BIN:-python3}"                                 # module-load a specific python first if Ada needs it
TORCH_CUDA_TAG="${TORCH_CUDA_TAG:-cu118}"   # check `nvidia-smi` on a GPU node for the driver's CUDA version; change if it doesn't match
# -----------------------------------------------------------------------------

CODE_DIR="$PROJECT_ROOT/code"
cd "$CODE_DIR"

# module load statements some Ada login nodes need; uncomment/edit as needed
# module load python/3.10
# module load cuda/11.8

echo "== creating venv at $CODE_DIR/.venv =="
"$PYTHON_BIN" -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip

echo "== installing CPU / data packages (numpy, scipy, polars, psutil) =="
# used across code/: core.py, scorers.py (scipy.sparse, scipy.stats), the
# *_store.py / *_to_parquet.py converters (polars), monitor.py (psutil)
pip install numpy scipy polars psutil

echo "== installing torch (CUDA $TORCH_CUDA_TAG) and transformers =="
# only embed.py (T1d) needs these -- the frozen multilingual MiniLM encoder
pip install torch --index-url "https://download.pytorch.org/whl/$TORCH_CUDA_TAG"
pip install transformers

echo "== sanity check =="
python -c "
import numpy, scipy, polars, psutil, torch, transformers
print('numpy', numpy.__version__)
print('scipy', scipy.__version__)
print('polars', polars.__version__)
print('psutil', psutil.__version__)
print('torch', torch.__version__, '| cuda available:', torch.cuda.is_available())
print('transformers', transformers.__version__)
"

# -----------------------------------------------------------------------------
# embed.py (T1d) hardcodes local_files_only=True when loading the MiniLM
# model (see code/embed.py: AutoModel.from_pretrained(MODEL, local_files_only=True)).
# Compute nodes have no internet, so the weights must already be sitting in
# the Hugging Face cache before any sbatch job runs embed.py. Fetch them here.
#
# This assumes the HF cache directory (~/.cache/huggingface by default) lives
# on storage shared between the login node and compute nodes -- true for a
# normal /home2 mount on Ada, but confirm if you're unsure.
# -----------------------------------------------------------------------------
echo "== pre-downloading the frozen MiniLM encoder into the Hugging Face cache =="
python - <<'PY'
from transformers import AutoModel, AutoTokenizer
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
AutoTokenizer.from_pretrained(MODEL)
AutoModel.from_pretrained(MODEL)
print("cached OK")
PY

echo
echo "== done =="
echo "Activate later with:  source $CODE_DIR/.venv/bin/activate"
echo "run_ada.sh should source the same venv, not conda -- see the note below."
