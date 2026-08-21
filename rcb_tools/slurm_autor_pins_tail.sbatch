#!/bin/bash
#SBATCH --job-name=autorpinT
#SBATCH --partition=eval
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=40
#SBATCH --mem=320G
#SBATCH --time=30:00:00
#SBATCH --array=2-2
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/autorpinT-%a-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/autorpinT-%a-%A.out
#
# The last two tasks, each in its own allocation.
#
# Both have now died three ways, and twice to the same cause. Earth_003 was OOM-killed on
# a 31 GB small node, then restarted as an `srun --overlap` step inside another element's
# allocation and killed when that element's own task finished; Life_002 went the same way
# on an a3 node. An overlap step is capacity you already hold, which is why it starts
# instantly -- and it lives only as long as the job hosting it, which is not a property
# you want on the task that is holding up the arm.
#
# So: a real allocation each. `--cpus-per-task=40` selects a c3nodeset (44 CPU / 341 GB)
# and gives the task the machine, which also puts Earth_003 an order of magnitude clear of
# the 31 GB it was killed at.
set -u
TASK=$(sed -n "$(( SLURM_ARRAY_TASK_ID == 1 ? 12 : 23 ))p" /home/robtang_google_com/rcb_tools/tasks40.txt)

PIN=/home/robtang_google_com/autor-pinned251
echo "[$(date '+%F %T')] node=$(hostname) cpus=$(nproc) mem=$(free -g|awk '/^Mem:/{print $2}')G class=big-solo"
echo "[$(date '+%F %T')] pin=$(git -C "$PIN" rev-parse --short HEAD) dirty=$(git -C "$PIN" status --porcelain | wc -l)"
echo "[$(date '+%F %T')] element ${SLURM_ARRAY_TASK_ID} -> ${TASK}"

export RCB_MAX_CONCURRENT=1
exec python3 /home/robtang_google_com/rcb_tools/run_arm.py autor_pins "${TASK}"
