#!/bin/bash
#SBATCH --job-name=abl40
#SBATCH --partition=eval
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=40G
#SBATCH --time=40:00:00
#SBATCH --array=1-40%16
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/%x-%a-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/%x-%a-%A.out
#
# One task per array element. Launch with ARM set:
#
#     sbatch --job-name=main40 --export=ARM=autor_main40 slurm_ablation40.sbatch
#     sbatch --job-name=abl40  --export=ARM=autor_abl40  slurm_ablation40.sbatch
#
# ---------------------------------------------------------------------------
# Why one task per element and not twelve in one cgroup
# ---------------------------------------------------------------------------
# The sibling job packing twelve AutoR tasks into a single 61.3 GiB cgroup ran at 100% of
# its limit for hours: memory.current 61.1 GiB, total_rss 50.8 GiB, memory.failcnt 24.4
# million. It survived only because a third of the usage was reclaimable page cache. One
# task per element removes the shared limit entirely -- a task that grows can only OOM
# itself, and the other 39 keep going.
#
# 40 GiB per element is sized from the baseline arm's own measurement: single-task peak RSS
# ran 5.2-28.0 GiB, median 21.6, with two elements killed at a 28 GiB cap. 40 clears the
# observed maximum with room, and 8 of these fit on a 349 GiB eval node.
#
# 4 CPUs, not 40. An AutoR task waits on a model API; it does not compute. 40 concurrent
# agent processes measured 86.6% of one core in total on this cluster. The `%16` throttle
# is the neighbourly part: 16 x 4 = 64 cores held at a time out of 656, against a partition
# that already had ~80 jobs queued. The watcher below prints what was actually drawn, so
# the next person sizing this has a measurement rather than this paragraph.
# ---------------------------------------------------------------------------

set -uo pipefail

ARM=${ARM:?set ARM=autor_main40 or ARM=autor_abl40}
TASKS=$(cd /home/robtang_google_com/RCB/tasks && ls -d */ | tr -d / | sort)
TASK=$(echo "$TASKS" | sed -n "${SLURM_ARRAY_TASK_ID}p")
[ -n "$TASK" ] || { echo "no task at index $SLURM_ARRAY_TASK_ID"; exit 0; }

case "$ARM" in
  autor_main40) TREE=/home/robtang_google_com/autor-main40 ;;
  autor_abl40)  TREE=/home/robtang_google_com/autor-abl40 ;;
  *) echo "unknown arm $ARM"; exit 1 ;;
esac

export RCB_MAX_CONCURRENT=1

echo "host      : $(hostname)   cpus ${SLURM_CPUS_PER_TASK}   mem ${SLURM_MEM_PER_NODE}M"
echo "arm       : $ARM"
echo "task      : $TASK  (index $SLURM_ARRAY_TASK_ID)"
# A benchmark run measures the clone it was launched from, so the SHA goes in the log at
# launch rather than being read off the tree afterwards.
echo "checkout  : $TREE @ $(git -C "$TREE" rev-parse --short HEAD 2>/dev/null)"
echo "skills    : $(ls "$TREE/src/skills" | wc -l)   pins: $(python3 -c "import json;print(sum(len(v) for v in json.load(open('$TREE/configs/task_skill_pins.json')).values()))")"
echo

( while sleep 600; do
    printf 'load %s  rss %sG\n' "$(cut -d' ' -f1 /proc/loadavg)" \
      "$(ps -u "$USER" -o rss= --no-headers 2>/dev/null | awk '{s+=$1} END{printf "%.1f", s/1048576}')"
  done ) &
WATCH=$!
trap 'kill $WATCH 2>/dev/null' EXIT

python3 /home/robtang_google_com/rcb_tools/run_arm.py "$ARM" "$TASK"
