#!/bin/bash
#SBATCH --job-name=pinabl
#SBATCH --partition=airs
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=36:00:00
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/pinabl-%a-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/pinabl-%a-%A.out
#
# The pin layer, on against off. Two worktrees at f0f469c differing in exactly one file.
#
# ---------------------------------------------------------------------------
# What is being tested, and why it is the uncomfortable one
# ---------------------------------------------------------------------------
# `configs/task_skill_pins.json` is a lookup table keyed on ResearchClawBench task ids: 27 of
# the forty tasks carry 280 entries between them, and every entry was derived from that
# task's own scored per-criterion losses. That is fitting to the test set, and
# `docs/rcb-skill-routing-arm.md` already says the comparison that would isolate it does not
# exist. The in-flight main40/abl40 ablation removes skill *directories* and leaves the table
# live on both sides, so it does not touch this layer.
#
# Two things sharpen it. The pack does not transfer: on the only out-of-sample corpus here,
# with zero pins, the skill-carrying arm is behind. And the in-flight main40/abl40 partial
# result is negative on the pinned tasks and flat on the unpinned ones, which is the shape a
# lookup table produces when it is not helping.
#
# ---------------------------------------------------------------------------
# One variable, and it is checkable before the run
# ---------------------------------------------------------------------------
# `diff -rq --exclude=.git --exclude=__pycache__ autor-pinson autor-pinsoff` reports exactly
# one differing file. `pins_off`'s table is empty, and an empty table degrades cleanly rather
# than raising: `load_task_pins` returns {} and `pins_for(any task)` returns nothing.
# Measured on both trees before launch: pins_on gives Astronomy_000 13 pins and
# Chemistry_003 14; pins_off gives 0 and 0.
#
# The variable is the *announcement*, not the availability. Most of the pack is still
# selected by discipline and by `applies_when` on both sides; what a pin does is force a
# skill into the stage prompt by name.
#
# ---------------------------------------------------------------------------
# Pre-specified analysis, including a negative control
# ---------------------------------------------------------------------------
# PRIMARY: the paired difference over the 27 pinned tasks.
# NEGATIVE CONTROL: the 13 unpinned tasks, where the manipulation is provably inert -- the
# installed set and the prompt bytes are identical on both sides. If those 13 move, then
# something other than the pin layer differed and the arm is void. Declaring this before the
# run is the point: it is the one reading that can refuse the result.
#
# Do NOT try to tell the arms apart from `run_config.json`. It has never carried
# `skill_pins` -- a later writer drops the key -- so the durable marker is `agent_cmd` in
# `_meta.json`, which names the worktree.
#
# Resources, partition, wall clock and per-element submission: see `slurm_xrev.sbatch`,
# which explains each and is the same shape.
#
#   for i in $(seq 1 80); do sbatch --array=$i slurm_pins.sbatch; sleep 0.3; done
set -u
LINE=$(( (SLURM_ARRAY_TASK_ID + 1) / 2 ))
TASK=$(sed -n "${LINE}p" /home/robtang_google_com/rcb_tools/tasks40.txt)
if [ $(( SLURM_ARRAY_TASK_ID % 2 )) -eq 1 ]; then
  ARM=pins_on;  PIN=/home/robtang_google_com/autor-pinson
else
  ARM=pins_off; PIN=/home/robtang_google_com/autor-pinsoff
fi

echo "[$(date '+%F %T')] node=$(hostname) part=${SLURM_JOB_PARTITION:-?} cpus=$(nproc) mem=$(free -g | awk '/^Mem:/{print $2}')G"
echo "[$(date '+%F %T')] pin=$(git -C "$PIN" rev-parse --short HEAD) dirty=$(git -C "$PIN" status --porcelain | wc -l)"
# Self-check: pins_on must print 53 task keys in the table, pins_off must print 0. A run
# whose table is not what its arm name says is not evidence about anything.
echo "[$(date '+%F %T')] pintable_task_keys=$(grep -coE '\"[A-Za-z]+_[0-9]{3}\"' "$PIN"/configs/task_skill_pins.json)"
echo "[$(date '+%F %T')] element ${SLURM_ARRAY_TASK_ID} -> line ${LINE} task ${TASK} arm ${ARM}"

export RCB_MAX_CONCURRENT=1
exec python3 /home/robtang_google_com/rcb_tools/run_arm.py "${ARM}" "${TASK}"
