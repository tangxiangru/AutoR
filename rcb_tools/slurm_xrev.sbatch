#!/bin/bash
#SBATCH --job-name=xrev
#SBATCH --partition=airs
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=36:00:00
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/xrev-%a-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/xrev-%a-%A.out
#
# The cross-model veto, on against off. One checkout, one argument, forty tasks, paired.
#
# ---------------------------------------------------------------------------
# The claim, and why nothing has ever priced it
# ---------------------------------------------------------------------------
# `src/cross_reviewer.py` defends switching this on by default:
#
#     "It is a veto, never an override, so adding it can only make the gate stricter.
#      That is what makes it safe to enable by default."
#
# The first clause is a structural invariant and `tests/test_cross_reviewer.py` already
# holds it. The second is a different kind of statement -- a claim about outcomes -- and it
# is reached from the first by assuming strictness is free. Verified against the archive:
# `--cross-review` appears in ZERO of the `agent_cmd` strings across every `_meta.json`
# under /rmeng_data/robtang/rcb_runs, so every scored run on this cluster took the argparse
# default `auto`, including the 32.19 that is currently the best number here.
#
# It is not a dormant feature. Twelve sampled `full40_pins` runs carry 387 vetoes between
# them, about 32 per run. On a pipeline whose own account of its losses is stages skipped
# for want of attempts, a gate that spends attempts to be stricter buys a report that is
# reviewed LESS. That is the thing this arm prices.
#
# ---------------------------------------------------------------------------
# One variable
# ---------------------------------------------------------------------------
# ARMS["xrev_on"] and ARMS["xrev_off"] are byte-identical but for the value after
# `--cross-review`, and both name /home/robtang_google_com/autor-xrev at f0f469c. Diff the
# two `agent_cmd` strings before quoting any delta -- the last delta quoted off this box had
# a stage timeout hiding inside it.
#
# A fresh pair rather than pairing against the in-flight `topo_adaptive`, which is the same
# SHA and the same command minus the flag and therefore looks free. It is not: it runs at a
# different allocation, and it sits on a branch that moved twice mid-ablation. Eighty
# elements is cheap against the free capacity.
#
# ---------------------------------------------------------------------------
# 4 CPU / 64 GB, airs only, 36 h
# ---------------------------------------------------------------------------
# The kill ladder from `slurm_autor_skills161.sbatch`: 28 GB killed 8 of 157 elements,
# 31 GB killed 7 of 55, 48 GB killed 1 of 38, 64 GB killed none of 39. At 64 GB most of
# eval's idle nodes are 4-core/31 GB and cannot host an element at all, so airs is where the
# memory is. Staying off `eval-w[1-9]` also avoids the 403 SCOPE_INSUFFICIENT trap, where a
# run dies in ~290 s and still writes a 183-byte report a scorer reads as a zero.
#
# 36 h rather than 24: the OFF side is strictly shorter because it removes the veto's
# attempts, so a cap tight enough to censor only the ON side would be this arm's own
# conclusion leaking into its budget.
#
# ---------------------------------------------------------------------------
# Odd/even, and one element per submission
# ---------------------------------------------------------------------------
# Element 2k-1 runs task k with the veto and element 2k runs task k without, so a task's two
# sides enter the queue adjacent and meet the same box. Submit per element rather than as
# one `%N` block:
#
#   for i in $(seq 1 80); do sbatch --array=$i slurm_xrev.sbatch; sleep 0.3; done
#
# ---------------------------------------------------------------------------
# Reading it
# ---------------------------------------------------------------------------
# The score is the noisy part -- one task, one draw carries about 8.5 points. The
# high-powered readings are paired integer counts over forty pairs and do not depend on it:
# vetoes (must be 0 on the OFF side), total attempts, auto-skipped stages, operator calls,
# and how long each side took.
set -u
LINE=$(( (SLURM_ARRAY_TASK_ID + 1) / 2 ))
TASK=$(sed -n "${LINE}p" /home/robtang_google_com/rcb_tools/tasks40.txt)
if [ $(( SLURM_ARRAY_TASK_ID % 2 )) -eq 1 ]; then ARM=xrev_on; else ARM=xrev_off; fi

PIN=/home/robtang_google_com/autor-xrev
echo "[$(date '+%F %T')] node=$(hostname) part=${SLURM_JOB_PARTITION:-?} cpus=$(nproc) mem=$(free -g | awk '/^Mem:/{print $2}')G"
echo "[$(date '+%F %T')] pin=$(git -C "$PIN" rev-parse --short HEAD) dirty=$(git -C "$PIN" status --porcelain | wc -l)"
echo "[$(date '+%F %T')] element ${SLURM_ARRAY_TASK_ID} -> line ${LINE} task ${TASK} arm ${ARM}"

export RCB_MAX_CONCURRENT=1
exec python3 /home/robtang_google_com/rcb_tools/run_arm.py "${ARM}" "${TASK}"
