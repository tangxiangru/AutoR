#!/bin/bash
#SBATCH --job-name=autorhead
#SBATCH --partition=eval
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=320G
#SBATCH --time=40:00:00
#SBATCH --array=1-8%8
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/autorhead-%a-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/autorhead-%a-%A.out
#
# Eight nodes, five tasks each, rather than forty nodes holding one apiece.
#
#  Sized from measurement, not from a guess. `sstat` over six of these elements at 24 h:
# # AveCPU/elapsed = 20.6 cores against 40 requested, MaxRSS 336 GB. Five concurrent AutoR
# # tasks are therefore ~4 cores and ~67 GB each -- they spend their time waiting on a
# # model API, not computing.
# #
# # The previous 40-core request was not a CPU estimate at all. It was a node selector: two
# # elements cannot both fit 40 of 44 cores, so asking for 40 guaranteed one element per
# # node, which is what the 320 GB actually needed. That is the antipattern -- reserving a
# # whole node with a CPU number when the constraint is memory -- and on a 656-core
# # partition it held 116 cores this job never used.
# #
# # `--exclusive` says the real thing: give me the node, and the accounting shows the cores
# # the job actually draws instead of a number chosen to win a scheduling argument.
# set -u
SLICE=5
START=$(( (SLURM_ARRAY_TASK_ID - 1) * SLICE + 1 ))
END=$(( START + SLICE - 1 ))
mapfile -t TASKS < <(sed -n "${START},${END}p" /home/robtang_google_com/rcb_tools/tasks40.txt)

echo "[$(date '+%F %T')] node=$(hostname) cpus=$(nproc) mem=$(free -g | awk '/^Mem:/{print $2}')G"
echo "[$(date '+%F %T')] element ${SLURM_ARRAY_TASK_ID}: lines ${START}-${END} -> ${TASKS[*]}"

export RCB_MAX_CONCURRENT=$SLICE
exec python3 /home/robtang_google_com/rcb_tools/run_arm.py autor_head "${TASKS[@]}"
