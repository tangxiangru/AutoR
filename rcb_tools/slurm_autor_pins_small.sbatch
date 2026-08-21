#!/bin/bash
#SBATCH --job-name=autorpinS
#SBATCH --partition=eval
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=0
#SBATCH --time=40:00:00
#SBATCH --array=11-40%25
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/autorpinS-%a-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/autorpinS-%a-%A.out
#
# The second half of the same arm, on the small nodes, one task each.
#
# Why this exists: eight c3nodeset machines are held by an older array, so the 8x5
# submission (slurm_autor_pins.sbatch) could only place two of its elements. This picks
# up tasks 11-40 on c3smallnodeset, which is 4 CPU / 31408 MB and cannot satisfy the
# `--cpus-per-task=40` the big-node script uses for node selection.
#
# **These runs are not resourced like the other ten.** A task here gets 4 CPUs and one
# node's 31 GB; a task on a big node gets 8 CPUs and 64 GB. One AutoR task was OOM-killed
# at 31 GB in an earlier batch, so this sits on the failure threshold rather than clear of
# it, and `--mem=0` is here to take every byte the node has rather than leave a margin
# this cannot afford. Any per-task comparison across the two halves is confounded by the
# resource split; the node is echoed below so the split is recoverable at scoring time.
#
# Array index == line number in tasks40.txt, so element 11 runs task 11. Safe to overlap
# with the big-node array: `run_arm.py` claims each task with an atomic mkdir under the
# shared arm root, so whichever launcher reaches a task first runs it and the other skips.
set -u
TASK=$(sed -n "${SLURM_ARRAY_TASK_ID}p" /home/robtang_google_com/rcb_tools/tasks40.txt)

PIN=/home/robtang_google_com/autor-pinned251
echo "[$(date '+%F %T')] node=$(hostname) cpus=$(nproc) mem=$(free -g | awk '/^Mem:/{print $2}')G class=small"
echo "[$(date '+%F %T')] pin=$(git -C "$PIN" rev-parse --short HEAD) dirty=$(git -C "$PIN" status --porcelain | wc -l)"
echo "[$(date '+%F %T')] element ${SLURM_ARRAY_TASK_ID} -> ${TASK}"

export RCB_MAX_CONCURRENT=1
exec python3 /home/robtang_google_com/rcb_tools/run_arm.py autor_pins "${TASK}"
