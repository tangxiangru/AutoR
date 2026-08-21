#!/bin/bash
#SBATCH --job-name=autor161
#SBATCH --partition=eval,a3
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=40:00:00
#SBATCH --array=1-40%40
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/autor161-%a-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/autor161-%a-%A.out
#
# `95861bd` (#270, forty task-scoped skills) over all forty tasks. It was previously run
# over only the twelve tasks those skills were written from, and eleven of those twelve
# died without a report -- the root holds one scoreable run, `Earth_000`. So this is a
# fresh arm rather than a completion, and `run_arm.py` will skip `Earth_000` on its own
# because it already carries a report above `MIN_SCOREABLE_BYTES`.
#
# ---------------------------------------------------------------------------
# Why both partitions, and what it costs
# ---------------------------------------------------------------------------
# `--partition=eval,a3` lets Slurm place each element wherever capacity appears first.
# a3 is fourteen 208-CPU / 1817 GB nodes and is currently held entirely by three other
# users; eval is twelve 44-CPU / 341 GB nodes plus the small ones this cannot land on.
# Neither has room for forty elements today, so the array drains as either frees.
#
# The cost is a within-arm node-class confound: an a3 element and a c3 element are not the
# same machine. It does not touch the scores -- the work is one agent process waiting on an
# API, and nothing in the scoring reads a clock -- but **any per-task wall clock taken off
# this arm is uninterpretable**, and it must not be paired against another arm on time.
#
# ---------------------------------------------------------------------------
# 4 CPU / 64 GB, measured rather than guessed
# ---------------------------------------------------------------------------
# Measured on a node running five of these concurrently: load average 3.52 over 44 CPUs,
# so **0.8 CPU per task** in steady state. Resident memory sampled across three live tasks
# was 12.5-21.8 GB. The task is one agent waiting on an API for most of its eighteen hours;
# CPU is not what limits it.
#
# Memory is. Across every AutoR RCB job on this cluster: 28 GB killed 8 of 157 elements,
# a whole 31 GB c3small node killed 7 of 55, 48 GB killed 1 of 38, and 64 GB has killed
# none of 39. So the peak sits above 28 GB and below 48, and 64 GB is the first tier with
# no observed kill. 4 CPU is five times the measured steady-state draw, which is headroom
# for the bursts when the agent runs its own numerical experiment.
#
# One task per element, not five packed into one: an element that dies takes its whole
# slice with it, and that is how the `bb32a8c` arm lost two tasks outright.
set -u
TASK=$(sed -n "${SLURM_ARRAY_TASK_ID}p" /home/robtang_google_com/rcb_tools/tasks40.txt)

PIN=/home/robtang_google_com/autor-skills161
echo "[$(date '+%F %T')] node=$(hostname) part=${SLURM_JOB_PARTITION:-?} cpus=$(nproc) mem=$(free -g | awk '/^Mem:/{print $2}')G"
echo "[$(date '+%F %T')] pin=$(git -C "$PIN" rev-parse --short HEAD) dirty=$(git -C "$PIN" status --porcelain | wc -l) skills=$(ls "$PIN"/src/skills | wc -l)"
echo "[$(date '+%F %T')] element ${SLURM_ARRAY_TASK_ID} -> ${TASK}"

export RCB_MAX_CONCURRENT=1
exec python3 /home/robtang_google_com/rcb_tools/run_arm.py autor_skills161 "${TASK}"
