#!/bin/bash
#SBATCH --job-name=autora9c
#SBATCH --partition=eval
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=5
#SBATCH --mem=64G
#SBATCH --time=40:00:00
#SBATCH --array=1-40%40
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/autora9c-%a-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/autora9c-%a-%A.out
#
# Current `main` (a9c2b48, #264) over all forty tasks, to pair against the `bb32a8c` arm.
#
# ---------------------------------------------------------------------------
# One task per array element, which is a change from every previous launcher
# ---------------------------------------------------------------------------
# `slurm_autor_pins.sbatch` packed five tasks into one element holding a whole node, and
# `slurm_autor_pins_small.sbatch` put one task on a 31 GB node. Both shapes cost that arm
# real tasks:
#
#   * Five OF the thirty small elements were killed OUT_OF_MEMORY (exit 0:125). None of the
#     twelve elements on a big node died. 31 GB shared with the OS, dockerd and journald is
#     under what a task peaks at; 64 GB exclusive is not.
#   * When an element dies it takes its whole slice with it. `run_arm.py`'s claim takeover
#     can rescue an orphan, but only while some other launcher is still alive to notice.
#     Two tasks (Earth_003, Life_002) were killed after the rest of the array had exited,
#     so nothing took them and they sat `running` for eleven hours holding the batch open.
#
# One task per element fixes both: an OOM kills exactly one task, and the other 39 elements
# are still around to take its claim. It also schedules far better. A 320 GB element needs a
# whole free node, so only four could start today; a 64 GB element fits wherever 64 GB is
# free, and twenty-seven start immediately against the same cluster state.
#
# 64 GB is not a guess. It is what the a3 elements and the big-node half both ran at, twelve
# tasks between them with zero kills, against 5/30 at ~27 GB effective. The request also does
# the node selection for free: c3smallnodeset is 31408 MB, so no element can ever land on the
# node class that did the killing.
#
# ---------------------------------------------------------------------------
# What is held fixed against the arm this is paired with
# ---------------------------------------------------------------------------
# `run_arm.py`'s `autor_a9c` command is byte-identical to `autor_pins` except for the
# checkout path: same `--model opus --review-model opus --web-search gemini`, and no
# `--stage-timeout`, so both take the adapter's 14400 s default. A benchmark comparison is a
# claim about two configurations, and the last time a stage timeout differed between arms it
# moved the score by about as much as the effect being measured.
#
# CPUs are not held fixed and cannot be: the paired arm ran 8 CPUs per task on big nodes and
# 4 on small ones, so it has no single value to match. 5 is above the 4 that completed 25
# tasks there. If a per-task timing is ever read off this arm, that is the confound to name.
set -u
TASK=$(sed -n "${SLURM_ARRAY_TASK_ID}p" /home/robtang_google_com/rcb_tools/tasks40.txt)

PIN=/home/robtang_google_com/autor-pin-a9c2b48
echo "[$(date '+%F %T')] node=$(hostname) cpus=$(nproc) mem=$(free -g | awk '/^Mem:/{print $2}')G"
echo "[$(date '+%F %T')] pin=$(git -C "$PIN" rev-parse --short HEAD) dirty=$(git -C "$PIN" status --porcelain | wc -l) skills=$(ls "$PIN"/src/skills | wc -l)"
echo "[$(date '+%F %T')] element ${SLURM_ARRAY_TASK_ID} -> ${TASK}"

export RCB_MAX_CONCURRENT=1
exec python3 /home/robtang_google_com/rcb_tools/run_arm.py autor_a9c "${TASK}"
