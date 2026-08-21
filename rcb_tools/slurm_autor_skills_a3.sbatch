#!/bin/bash
#SBATCH --job-name=autorsklA
#SBATCH --partition=eval
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --time=20:00:00
#SBATCH --array=1-2%2
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/autorsklA-%a-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/autorsklA-%a-%A.out
#
# Partition: `eval` at 8 CPUs, and the reasoning that used to say `a3` is kept below
# because it was sound on its own terms and its premise is what changed.
#
# What this job actually draws, measured on slurm2-a3nodeset1-1 while it held a 208-core
# node: `nproc` 208, one-minute load 6.47, and `pgrep -fc rcb_agent.py` 43. Forty-three
# concurrent tasks on 6.47 cores is about 0.15 of a core each, so this element's work fits
# in single digits. `a3` is `OverSubscribe=EXCLUSIVE`, so a job there takes all 208 whatever
# it asks for -- the sibling `slurm_autor_pins_a3.sbatch` already asked for 8 and `squeue`
# reported CPUS=208.
#
# The original argument, which was not wrong: eval sat at 653/656 CPUs allocated with
# `OverSubscribe=NO`, so nothing could be packed into it, while a3 had whole idle machines.
# Taking an exclusive node nobody else could use was the better trade at that moment.
#
# What changed is the reading of "allocated". eval is allocated to the brim and barely
# *used* -- forty-core jobs on it drawing one or two. Sizing this at 8 and queueing on eval
# is the honest request; if it will not schedule, that is a queue worth seeing rather than
# one to route around by taking a 208-core machine for seven cores of work.
#
# `--time=20:00:00` rather than 40 because a task in the previous arm took 9-15 hours and a
# shorter ceiling is what lets the backfill scheduler place this at all.
#
# Two elements cover all forty tasks. `run_arm.py` claims each task with an atomic mkdir,
# so this is safe alongside the packed eval array and the original 8x5: whichever
# launcher reaches a task first runs it, the rest skip.
set -u
SLICE=20
START=$(( (SLURM_ARRAY_TASK_ID - 1) * SLICE + 1 ))
END=$(( START + SLICE - 1 ))
mapfile -t TASKS < <(sed -n "${START},${END}p" /home/robtang_google_com/rcb_tools/tasks40.txt)

PIN=/home/robtang_google_com/autor-pinned-skills
echo "[$(date '+%F %T')] node=$(hostname) cpus=$(nproc) mem=$(free -g | awk '/^Mem:/{print $2}')G class=a3"
echo "[$(date '+%F %T')] pin=$(git -C "$PIN" rev-parse --short HEAD) dirty=$(git -C "$PIN" status --porcelain | wc -l)"
echo "[$(date '+%F %T')] element ${SLURM_ARRAY_TASK_ID}: lines ${START}-${END} -> ${TASKS[*]}"

export RCB_MAX_CONCURRENT=$SLICE
exec python3 /home/robtang_google_com/rcb_tools/run_arm.py autor_skills "${TASKS[@]}"
