#!/bin/bash
#SBATCH --job-name=autorpinA
#SBATCH --partition=eval
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=40:00:00
#SBATCH --array=37-40
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/autorpinA-%a-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/autorpinA-%a-%A.out
#
# Partition: `eval`, not `a3`. `a3` is OverSubscribe=EXCLUSIVE, so a job there takes the
# whole 208-core node whatever --cpus-per-task says -- measured: this file already asked for
# 8 and squeue reported CPUS=208. An AutoR task is API-bound, not compute-bound: on
# slurm2-a3nodeset1-1, 43 concurrent rcb_agent.py processes drew a 1-minute load of 6.47,
# about 0.15 of a core each. `eval` is OverSubscribe=NO and hands over what is asked for.
#
# The tail of the same arm, on the a3 partition, because the eval partition is full and
# a3 had idle machines.
#
# **No GPU is requested.** AutoR is a CPU and API workload -- it drives an agent CLI and
# waits on a model endpoint -- so a `--gres=gpu` here would hold eight accelerators doing
# nothing and block the work a3 exists for. Not requesting them leaves all eight per node
# available while these run.
#
# 8 CPU / 64 GB deliberately matches the c3nodeset half of this arm rather than helping
# itself to a share of a 208-CPU, 1.8 TB machine. The arm is already split across two
# resource classes, which confounds any per-task comparison across the split; a third
# class would make it worse for no gain, since nothing here is CPU-bound at 8.
#
# Array index == line number in tasks40.txt. Overlaps safely with the eval-partition
# arrays: `run_arm.py` claims each task with an atomic mkdir under the shared arm root,
# so whichever launcher reaches a task first runs it and the others skip.
set -u
TASK=$(sed -n "${SLURM_ARRAY_TASK_ID}p" /home/robtang_google_com/rcb_tools/tasks40.txt)

PIN=/home/robtang_google_com/autor-pinned251
echo "[$(date '+%F %T')] node=$(hostname) cpus=$(nproc) mem=$(free -g | awk '/^Mem:/{print $2}')G class=a3-nogpu"
echo "[$(date '+%F %T')] pin=$(git -C "$PIN" rev-parse --short HEAD) dirty=$(git -C "$PIN" status --porcelain | wc -l)"
echo "[$(date '+%F %T')] element ${SLURM_ARRAY_TASK_ID} -> ${TASK}"

export RCB_MAX_CONCURRENT=1
exec python3 /home/robtang_google_com/rcb_tools/run_arm.py autor_pins "${TASK}"
