#!/bin/bash
#SBATCH --job-name=autorpinR
#SBATCH --partition=eval
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=5
#SBATCH --mem=64G
#SBATCH --time=40:00:00
#SBATCH --array=1-2%2
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/autorpinR-%a-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/autorpinR-%a-%A.out
#
# The two tasks the small-node half of this arm lost to the OOM killer.
#
# What happened, so the same submission is not made again. `slurm_autor_pins_small.sbatch`
# runs one task per c3small node at 4 CPU / 31 GB with `--mem=0`, and its own header says
# that sits "on the failure threshold rather than clear of it" because an AutoR task had
# already been OOM-killed at 31 GB once. It was right. Of the 30 elements it placed,
# **five were killed OUT_OF_MEMORY** (37305_15, _17, _20, _25, _28, exit 0:125). Zero of
# the twelve elements on c3nodeset or a3nodeset died. The kill is a property of the node
# class, not of the task.
#
# Three of those five had already handed their task to another element through the claim
# takeover and cost nothing. Two did not, because by the time they died the rest of the
# array had exited and no launcher was left to take over:
#
#   Earth_003   killed twice, at 3 accepted stages, idle 11.5 h when this was written
#   Life_002    killed once,  at 6 accepted stages, idle  3.1 h
#
# Both are re-run from Stage 01, not resumed. A resumed run has an interruption in its
# history that the other 38 do not, and the arm is a claim about one configuration run
# forty times; 17 h of compute is cheaper than a footnote saying two rows are a different
# thing. `run_arm.py` starts a fresh workspace on takeover, so this needs no cleanup: the
# claim directory exists but neither task is `finished` (no report.md) or `live` (no
# `_agent_output.jsonl` written inside 1800 s), which is exactly the TAKE branch.
#
# Sized at 64 GB / 5 CPU, not the 320 GB / 40 CPU this first asked for. The first version
# ran for eighteen minutes and was cancelled: reserving a whole node for one task starved
# the forty-element `autora9c` array of 512 GB, which is eight tasks that could have been
# running. 64 GB is what the a3 and big-node halves both ran at with zero kills, and the
# request still cannot land on c3smallnodeset (31408 MB), which is the node class that did
# the killing. Over-reserving is not free on a shared partition; it is paid by the next
# job in the queue, which here was mine.
#
# Cancelling required deleting the two workspaces that first attempt created. `run_arm.py`
# only takes over a claim when nothing is `live`, and live means an `_agent_output.jsonl`
# written inside 1800 s -- which a just-cancelled run has. Resubmitting without clearing
# them would have SKIPped both tasks and quietly left the arm at 38.
#
# The job name has to keep the `autorpin` prefix: the scoring watcher decides the batch is
# over by counting `squeue` lines that start with it, and a rescue it cannot see would let
# it publish a 38-task table as if it were the whole arm.
set -u
LINE=$(sed -n "${SLURM_ARRAY_TASK_ID}p" /home/robtang_google_com/rcb_tools/rescue_tasks.txt)

PIN=/home/robtang_google_com/autor-pinned251
echo "[$(date '+%F %T')] node=$(hostname) cpus=$(nproc) mem=$(free -g | awk '/^Mem:/{print $2}')G class=big-rescue"
echo "[$(date '+%F %T')] pin=$(git -C "$PIN" rev-parse --short HEAD) dirty=$(git -C "$PIN" status --porcelain | wc -l)"
echo "[$(date '+%F %T')] element ${SLURM_ARRAY_TASK_ID} -> ${LINE}"

export RCB_MAX_CONCURRENT=1
exec python3 /home/robtang_google_com/rcb_tools/run_arm.py autor_pins "${LINE}"
