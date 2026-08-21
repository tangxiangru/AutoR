#!/bin/bash
#SBATCH --job-name=autorpins
#SBATCH --partition=eval
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=40
#SBATCH --mem=320G
#SBATCH --time=40:00:00
#SBATCH --array=1-8%8
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/autorpins-%a-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/autorpins-%a-%A.out
#
# Eight nodes, five tasks each, so all forty run at once.
#
# `--cpus-per-task=40` is doing the node selection and is asking for essentially the
# whole machine. The small nodes are 4 CPU / 31 GB and cannot satisfy it, so this only
# lands on c3nodeset (44 CPU / 341 GB); and because two elements cannot both fit 40 of
# 44 CPUs, each element gets a node to itself. That matters for the memory: one AutoR
# task was OOM-killed at 31 GB in an earlier batch, so 30 GB per concurrent task sat on
# the failure threshold rather than clear of it. 320 GB over five tasks is 64 GB each --
# twice the observed kill point -- and 8 CPUs each. Four CPUs and 21 GB are left to the
# node so a reservation or a stray daemon cannot make this unschedulable.
#
# `run_arm.py` claims each task with an atomic mkdir before starting it, so two array
# elements handed overlapping slices cannot both run the same task. The slicing below is
# disjoint anyway; the lock is what makes a resubmit safe.
#
# No `--stage-timeout`: the adapter's 14400 s default applies, which is what the 31.35
# arm ran under. A benchmark comparison is a claim about two configurations, and 1800 s
# is a budget change of the same size as the effect being looked for.
set -u
SLICE=5
START=$(( (SLURM_ARRAY_TASK_ID - 1) * SLICE + 1 ))
END=$(( START + SLICE - 1 ))
mapfile -t TASKS < <(sed -n "${START},${END}p" /home/robtang_google_com/rcb_tools/tasks40.txt)

# The SHA is echoed by the same script that starts the run: a benchmark result names the
# tree it measured or it names nothing.
PIN=/home/robtang_google_com/autor-pinned251
echo "[$(date '+%F %T')] node=$(hostname) cpus=$(nproc) mem=$(free -g | awk '/^Mem:/{print $2}')G"
echo "[$(date '+%F %T')] pin=$(git -C "$PIN" rev-parse --short HEAD) dirty=$(git -C "$PIN" status --porcelain | wc -l)"
echo "[$(date '+%F %T')] element ${SLURM_ARRAY_TASK_ID}: lines ${START}-${END} -> ${TASKS[*]}"

export RCB_MAX_CONCURRENT=$SLICE
exec python3 /home/robtang_google_com/rcb_tools/run_arm.py autor_pins "${TASKS[@]}"
