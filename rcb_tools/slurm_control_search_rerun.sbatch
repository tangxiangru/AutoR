#!/bin/bash
#SBATCH --job-name=ccsrerun
#SBATCH --partition=eval
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=80G
#SBATCH --time=24:00:00
#SBATCH --array=1-3
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/%x-%a-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/%x-%a-%A.out
#
# Re-run the three `control_search` tasks that finished with a zero-byte report.md.
#
# ---------------------------------------------------------------------------
# Why these three and not the other five
# ---------------------------------------------------------------------------
# Job 45637 ended OUT_OF_MEMORY with 37 oom_kill events, and six of its forty transcripts
# carry a SIGKILL trace. The tempting move is to re-run all six. That would bias the
# comparison, because OOM-killed subprocesses are a background condition of this benchmark
# on this cluster and not a property of this arm:
#
#     control_search_g37   6/40 transcripts show a kill
#     control_bare_cc      7/44
#     full40_v220         10/41   (its own Slurm job logged 11 OUT_OF_MEMORY elements)
#
# Every arm is stressed at about the same rate, so re-rolling one arm's stressed runs is
# re-rolling until the number improves. The line that can be drawn evenly is a MISSING
# DELIVERABLE: a run with no report at all produced no measurement, and there is nothing to
# bias in its favour because there is nothing there. That is these three.
#
# One of them matters more than the missing score suggests. Material_003 was scored 19.65
# off a zero-byte report.md -- the RCB scorer found something else to grade -- so leaving it
# alone does not leave a gap in the arm, it leaves a wrong number in it.
#
# 80 GiB rather than the 40 the other arrays use: these are the runs that ran out, and the
# cost of a second failure is another nine hours.
# ---------------------------------------------------------------------------

set -uo pipefail

TASKS=(Information_001 Material_003 Neuroscience_001)
TASK=${TASKS[$((SLURM_ARRAY_TASK_ID - 1))]}

export RCB_MAX_CONCURRENT=1

echo "host  : $(hostname)   cpus ${SLURM_CPUS_PER_TASK}   mem ${SLURM_MEM_PER_NODE}M"
echo "arm   : control_search   task: $TASK"
echo

python3 /home/robtang_google_com/rcb_tools/run_arm.py control_search "$TASK"
