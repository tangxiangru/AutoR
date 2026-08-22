#!/bin/bash
#SBATCH --job-name=a3abl
#SBATCH --partition=a3
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --time=40:00:00
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/%x-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/%x-%A.out
#
# The whole arm on one a3 node. Launch with ARM set:
#
#     sbatch --job-name=a3main40 --export=ALL,ARM=autor_main40 slurm_ablation40_a3.sbatch
#     sbatch --job-name=a3abl40  --export=ALL,ARM=autor_abl40  slurm_ablation40_a3.sbatch
#
# ---------------------------------------------------------------------------
# Why a3, and why no --cpus-per-task
# ---------------------------------------------------------------------------
# `a3` is OverSubscribe=EXCLUSIVE: the job gets the whole node whatever it asks for, so a
# CPU number here would be decoration. One node is 208 cores and 1.86 TiB, which holds all
# forty tasks at once -- the eval route runs them 16 at a time behind a 40 GiB-per-element
# memory limit, and forty concurrent AutoR tasks were measured drawing 86.6% of ONE core in
# total. The constraint is memory, and 1.86 TiB against a measured single-task peak of
# 5.2-28.0 GiB (median 21.6) leaves the whole arm comfortable in one cgroup.
#
# ---------------------------------------------------------------------------
# Running alongside the eval array is deliberate, not a duplicate
# ---------------------------------------------------------------------------
# The same arm is queued on `eval` as a 40-element array. `run_arm.py` claims each task
# before starting it -- a task whose workspace already holds a scoreable report, or whose
# `_agent_output.jsonl` was touched in the last 1800 s, logs `SKIP: claimed by another
# launcher` and is not run again. So whichever scheduler frees up first does the work and
# the other walks past it. Nothing is scored twice and nothing is paid for twice.
#
# a3 was fully allocated at submit time (2912/2912, three other users, 11 jobs pending), so
# this sits in the queue until a node drains. That is the point: it costs nothing to wait,
# and if a node frees the arm finishes in one pass instead of three.
# ---------------------------------------------------------------------------

set -uo pipefail

ARM=${ARM:?set ARM=autor_main40 or ARM=autor_abl40}
case "$ARM" in
  autor_main40) TREE=/home/robtang_google_com/autor-main40 ;;
  autor_abl40)  TREE=/home/robtang_google_com/autor-abl40 ;;
  *) echo "unknown arm $ARM"; exit 1 ;;
esac

TASKS=$(cd /home/robtang_google_com/RCB/tasks && ls -d */ | tr -d / | sort | tr '\n' ' ')
export RCB_MAX_CONCURRENT=${RCB_MAX_CONCURRENT:-40}

echo "host      : $(hostname)   nproc $(nproc)   mem $(free -g | awk '/^Mem:/{print $2}')G"
echo "arm       : $ARM"
# A benchmark run measures the clone it was launched from, so the SHA is printed at launch
# rather than read off the tree afterwards.
echo "checkout  : $TREE @ $(git -C "$TREE" rev-parse --short HEAD 2>/dev/null)"
echo "skills    : $(ls "$TREE/src/skills" | wc -l)   pins: $(python3 -c "import json;d=json.load(open('$TREE/configs/task_skill_pins.json'));print(sum(len(v) for k,v in d.items() if not k.startswith('_')))")"
echo "tasks     : $(echo $TASKS | wc -w)   concurrency: $RCB_MAX_CONCURRENT"
echo

( while sleep 600; do
    printf 'load %s  rss %sG  agents %s\n' "$(cut -d' ' -f1 /proc/loadavg)" \
      "$(ps -u "$USER" -o rss= --no-headers 2>/dev/null | awk '{s+=$1} END{printf "%.0f", s/1048576}')" \
      "$(pgrep -fc rcb_agent.py || echo 0)"
  done ) &
WATCH=$!
trap 'kill $WATCH 2>/dev/null' EXIT

python3 /home/robtang_google_com/rcb_tools/run_arm.py "$ARM" $TASKS
