#!/bin/bash
#SBATCH --job-name=autorsklP
#SBATCH --partition=eval
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=40G
#SBATCH --time=40:00:00
#SBATCH --array=1-40%40
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/autorsklP-%a-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/autorsklP-%a-%A.out
#
# The same arm as slurm_autor_skills.sbatch, sized to start now instead of at 08:55.
#
# Why: that script asks for 40 of a node's 44 CPUs and 320 GB, which is a node-selection
# device rather than a resource need -- an AutoR task is `claude` plus a Gemini search
# call, so it spends its life blocked on the network. The cluster was at 3564/3568 CPUs
# allocated when this was written, so "essentially a whole machine, times eight" could
# not be placed and slurm scheduled it ten hours out.
#
# One CPU per element, one task per element, so an element fits in any single free CPU
# and the array backfills continuously as the `full40_pins` arm retires tasks. The trade
# is that a task now shares its node's CPUs with whatever else is there; that costs
# nothing on a workload that is not CPU-bound, and it is the only shape that runs tonight.
#
# `--mem=40G` rather than 64: it is above the 31 GB at which a task was OOM-killed in an
# earlier batch, and small enough that eight fit in one c3nodeset node's 341 GB. It does
# mean this cannot land on c3smallnodeset (31 GB total), so the pool is the twelve
# c3nodeset machines -- where memory is not the binding constraint, CPUs are.
#
# Safe to run alongside the 8x5 array and any other launcher: `run_arm.py` claims each
# task with an atomic mkdir under the shared arm root, so whichever reaches a task first
# runs it and the others skip.
set -u
TASK=$(sed -n "${SLURM_ARRAY_TASK_ID}p" /home/robtang_google_com/rcb_tools/tasks40.txt)

PIN=/home/robtang_google_com/autor-pinned-skills
echo "[$(date '+%F %T')] node=$(hostname) cpus=$(nproc) mem=$(free -g | awk '/^Mem:/{print $2}')G class=packed"
echo "[$(date '+%F %T')] pin=$(git -C "$PIN" rev-parse --short HEAD) dirty=$(git -C "$PIN" status --porcelain | wc -l)"
echo "[$(date '+%F %T')] element ${SLURM_ARRAY_TASK_ID} -> ${TASK}"

export RCB_MAX_CONCURRENT=1
exec python3 /home/robtang_google_com/rcb_tools/run_arm.py autor_skills "${TASK}"
