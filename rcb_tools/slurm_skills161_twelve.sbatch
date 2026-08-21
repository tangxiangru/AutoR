#!/bin/bash
#SBATCH --job-name=skl12
#SBATCH --partition=eval,a3,airs
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=40:00:00
#SBATCH --array=1-12%12
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/skl12-%a-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/skl12-%a-%A.out
#
# The twelve tasks of `full40_skills161`, re-run at the same per-task allocation as the other
# twenty-eight so the arm is one configuration instead of two.
#
# ---------------------------------------------------------------------------
# What this replaces, and why it was thrown away
# ---------------------------------------------------------------------------
# Job 45382 ran these twelve inside ONE 8-CPU / 61 GB cgroup at concurrency 12 -- about 5 GB
# per task against a measured per-task peak of 12.5-21.8 GB. It survived eighteen hours and
# reached stages 4-7 of 8 without an OOM, so it was not failing; it was simply not the same
# machine the other twenty-eight tasks got, and a forty-task mean assembled from both would
# be a mean over two resource configurations. Sibling `slurm_autor_skills161.sbatch` explains
# why 4 CPU / 64 GB is the tier with no observed kill: 28 GB killed 8 of 157 elements, 48 GB
# killed 1 of 38, 64 GB killed none of 39.
#
# Those eighteen hours are not deleted. The twelve workspaces are at
# /rmeng_data/robtang/rcb_runs/_abandoned_skills161_cgroup/, outside the arm root so
# `pick_workspace`'s `{task}_*` glob cannot reach them, and their `.claims` entries were
# removed by hand -- which is the gesture `run_arm.py` documents for a task that needs
# re-running.
#
# One element per task, not twelve packed into one, for the reason the sibling gives: an
# element that dies takes its whole slice with it.
#
# ---------------------------------------------------------------------------
# Three partitions, because a job only runs where it asked to
# ---------------------------------------------------------------------------
# This first went out as `--partition=eval,a3` and sat in `(Priority)` while `airs` had
# 850 cores showing idle. That is not the scheduler being unfair: a partition is not a
# shared pool, and a job Slurm has never been told may use `airs` will not be placed there
# no matter how empty it is. `airs` nodes are 32 cores / 126 GB, so a 4-CPU / 64 GB element
# fits two to a node.
#
# `sinfo`'s idle column is also not free capacity. 820 of those 850 cores were `planned` --
# held while the scheduler accumulates nodes for a queued multi-node job. Backfill would
# normally slot short work into the gap, but it cannot when the blocking job's TimeLimit is
# UNLIMITED, because there is no finish time to compare against.
set -u
TASK=$(sed -n "${SLURM_ARRAY_TASK_ID}p" /home/robtang_google_com/rcb_tools/tasks12_rerun.txt)

PIN=/home/robtang_google_com/autor-skills161
echo "[$(date '+%F %T')] node=$(hostname) part=${SLURM_JOB_PARTITION:-?} cpus=$(nproc) mem=$(free -g | awk '/^Mem:/{print $2}')G"
echo "[$(date '+%F %T')] pin=$(git -C "$PIN" rev-parse --short HEAD) dirty=$(git -C "$PIN" status --porcelain | wc -l) skills=$(ls "$PIN"/src/skills | wc -l)"
echo "[$(date '+%F %T')] element ${SLURM_ARRAY_TASK_ID} -> ${TASK}"

export RCB_MAX_CONCURRENT=1
exec python3 /home/robtang_google_com/rcb_tools/run_arm.py autor_skills161 "${TASK}"
