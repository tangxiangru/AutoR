#!/bin/bash
#SBATCH --job-name=firepair
#SBATCH --partition=eval
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=180G
#SBATCH --time=12:00:00
#SBATCH --array=1-7%7
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/firepair-%a-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/firepair-%a-%A.out
#
# The generalisation test. 35 FIRE-Bench tasks x two skill packs, five tasks per array
# element, both arms of a task on the same node so they share whatever the node is doing.
#
# FIRE-Bench kills each agent at 3600 s, so a cell is bounded by construction and five
# tasks x two arms is at most ten hours of agent time per element; 12 h of wall covers it.
#
# 4 cores and 180 GB, from the ResearchClawBench measurement: five concurrent AutoR tasks
# peaked at 260 GB and drew about two cores. Ten concurrent one-hour cells are lighter than
# that, and 180 GB still keeps one element to a node on the small machines.
set -u
SLICE=5
START=$(( (SLURM_ARRAY_TASK_ID - 1) * SLICE + 1 ))
END=$(( START + SLICE - 1 ))
mapfile -t TASKS < <(sed -n "${START},${END}p" /home/robtang_google_com/rcb_tools/fire_tasks.txt)
echo "[$(date '+%F %T')] node=$(hostname) element ${SLURM_ARRAY_TASK_ID}: ${TASKS[*]}"
export FIRE_MAX_CONCURRENT=10
exec python3 /home/robtang_google_com/rcb_tools/fire_pair.py run "${TASKS[@]}"
