#!/bin/bash
#SBATCH --job-name=rcbgap
#SBATCH --partition=a3,eval
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=64G
#SBATCH --time=40:00:00
#SBATCH --array=1-6%6
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/rcbgap-%a-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/rcbgap-%a-%A.out
#
# The six tasks no queued job covers: full40_pins is missing three and its rescue array
# takes two of them; full40_skills is missing eight and the skills re-run takes three.
# Submitting the rest as their own array rather than widening someone else's, so a job
# that fails here cannot take a task another element had already claimed.
#
# --partition=a3,eval, and 2 CPUs
# ------------------------------
# a3 is 2912/0/0/2912 right now, so asking for it alone would only queue. Naming both
# lets the scheduler take whichever frees first, which is what "use a3 when it is idle"
# actually means for work that has to finish either way.
#
# Two CPUs because this work is API-bound, not compute-bound. Measured by the sibling
# sbatch on slurm2-a3nodeset1-1 with 43 live `rcb_agent.py` processes: nproc 208,
# loadavg 6.47 — three per cent. Cores requested and not used are cores no other element
# can be placed on, and the pending a3 array asks for one apiece for the same reason.
#
# 64 GB and not `--mem=0` on a 31 GB node: five elements of the c3small pins array were
# killed OUT_OF_MEMORY there, and zero on c3nodeset or a3nodeset. The kill was a property
# of the node class, so this asks for headroom rather than for whatever the node has.
set -u
LINE=$(sed -n "${SLURM_ARRAY_TASK_ID}p" /home/robtang_google_com/rcb_tools/gapfill_tasks.txt)
ARM=${LINE%% *}; TASK=${LINE##* }
echo "[$(date '+%F %T')] node=$(hostname) part=${SLURM_JOB_PARTITION} cpus=$(nproc) mem=$(free -g|awk '/^Mem:/{print $2}')G"
echo "[$(date '+%F %T')] element ${SLURM_ARRAY_TASK_ID} -> arm=${ARM} task=${TASK}"
export RCB_MAX_CONCURRENT=1
exec python3 /home/robtang_google_com/rcb_tools/run_arm.py "${ARM}" "${TASK}"
