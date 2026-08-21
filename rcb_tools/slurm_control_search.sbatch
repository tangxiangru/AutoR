#!/usr/bin/env bash
#SBATCH --job-name=ccsearch
#SBATCH --partition=eval
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=24
#SBATCH --time=24:00:00
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/ccsearch-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/ccsearch-%A.out
#
# Re-run the twelve tasks that got new task-scoped skills, paired against the v220 arm.
#
# ---------------------------------------------------------------------------
# Why 8 CPUs and not 208
# ---------------------------------------------------------------------------
# An AutoR task is API-bound: it spends its wall clock waiting on Vertex, not computing.
# Measured on slurm2-a3nodeset1-1 while 43 `rcb_agent.py` processes were live on it:
#
#     nproc                     208
#     /proc/loadavg (1 min)     6.47
#     pgrep -fc rcb_agent.py    43
#
# 43 concurrent tasks drawing 6.47 cores is about 0.15 of a core each, so this job's twelve
# need roughly two. Eight is the headroom for the scorer, the Python starts and the odd
# burst, and it is still twenty-six times smaller than the allocation the same work has been
# taking. The sibling sbatch (`slurm_autor_skills_a3.sbatch`) names no `--cpus-per-task` at
# all, which is how a partition default handed it the whole node.
#
# `eval` rather than `a3` for the same reason: nothing here wants a big node.
#
# The real ceiling is the Vertex per-base-model quota, not cores. Forty concurrent opus runs
# have been observed with zero RESOURCE_EXHAUSTED, so RCB_MAX_CONCURRENT is set at the task
# count rather than throttled below it.
# ---------------------------------------------------------------------------

set -uo pipefail

ARM=${ARM:-control_search}
TASKS=""   # empty = all forty

export RCB_MAX_CONCURRENT=${RCB_MAX_CONCURRENT:-40}

echo "host        : $(hostname)"
echo "cpus alloc  : ${SLURM_CPUS_PER_TASK:-?}   nproc: $(nproc)"
echo "arm         : $ARM"
echo "concurrency : $RCB_MAX_CONCURRENT"
echo "checkout    : $(git -C /home/robtang_google_com/autor-skills161 rev-parse --short HEAD 2>/dev/null)"
echo "skills      : $(ls /home/robtang_google_com/autor-skills161/src/skills 2>/dev/null | wc -l)"
echo "tasks       : $(echo $TASKS | wc -w)"
echo

# Report what the job actually drew, so the next person sizing this has a measurement
# rather than this comment.
( while sleep 300; do
    printf 'load %s  rcb_agent %s\n' "$(cut -d' ' -f1 /proc/loadavg)" "$(pgrep -fc rcb_agent.py || echo 0)"
  done ) &
WATCH=$!
trap 'kill $WATCH 2>/dev/null' EXIT

python3 /home/robtang_google_com/rcb_tools/run_arm.py "$ARM" $TASKS
