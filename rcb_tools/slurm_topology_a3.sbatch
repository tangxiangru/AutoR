#!/bin/bash
#SBATCH --job-name=topoA3
#SBATCH --partition=a3
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --time=24:00:00
#SBATCH --array=1-4%4
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/topoA3-%a-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/topoA3-%a-%A.out
#
# The same ablation as slurm_topology_ablation.sbatch, shaped for whole a3 machines, and
# opportunistic: if a3 frees a node this runs at once, and if it never does this sits in
# the queue costing nothing. Safe to run alongside the eval array because `run_arm.py`
# claims each (arm, task) with an atomic mkdir under the arm's own root -- whichever
# launcher reaches a unit first runs it and the other skips, which is how job 39413's
# elements exited in one second each when their tasks were already taken.
#
# The unit is a (task, arm) pair member, numbered exactly as the eval array numbers them,
# so element k here covers units 20k-19..20k -- ten whole pairs, both arms of each. A
# slice that split a pair across elements could leave one arm of a task run and the other
# not, and an unpaired task is dropped from the paired difference entirely.
#
# 24 hours, not the 20 that killed the last multi-task-per-element array here: a task
# takes 9-15 hours and twenty of them share a node, so the element's clock is the slowest
# task plus contention. This is the shape whose walltime has to be watched, which is the
# other reason the eval array is one task per element and is the primary.
set -u
SLICE=20
START=$(( (SLURM_ARRAY_TASK_ID - 1) * SLICE + 1 ))
END=$(( START + SLICE - 1 ))

PIN=/home/robtang_google_com/autor-topology
echo "[$(date '+%F %T')] node=$(hostname) cpus=$(nproc) mem=$(free -g | awk '/^Mem:/{print $2}')G"
echo "[$(date '+%F %T')] pin=$(git -C "$PIN" rev-parse --short HEAD) dirty=$(git -C "$PIN" status --porcelain | wc -l)"

for UNIT in $(seq "$START" "$END"); do
  LINE=$(( (UNIT + 1) / 2 ))
  TASK=$(sed -n "${LINE}p" /home/robtang_google_com/rcb_tools/tasks40.txt)
  if [ $(( UNIT % 2 )) -eq 1 ]; then ARM=topology_adaptive; else ARM=topology_linear; fi
  echo "[$(date '+%F %T')] unit ${UNIT} -> ${TASK} ${ARM}"
  RCB_MAX_CONCURRENT=1 python3 /home/robtang_google_com/rcb_tools/run_arm.py "${ARM}" "${TASK}" &
done
wait
