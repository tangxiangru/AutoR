#!/bin/bash
#SBATCH --job-name=topoabl
#SBATCH --partition=eval
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=16G
#SBATCH --time=24:00:00
#SBATCH --array=1-80
#SBATCH --exclude=eval-w[1-9]
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/topoabl-%a-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/topoabl-%a-%A.out
#
# The ablation `docs/framework.md` §6.7 says the document owes: `--stage-graph adaptive`
# against `--stage-graph linear`, same model, same judge, same forty tasks, paired.
#
# Until #293 the flag did not exist on `rcb_agent.py` at all, so the "control arm [that]
# has still never been passed" could not have been. All 398 archived benchmark run configs
# read `adaptive` and none of them chose it.
#
# **The two arms are one checkout and one argument apart.** `ARMS["topology_adaptive"]` and
# `ARMS["topology_linear"]` in run_arm.py are byte-identical command strings but for the
# value after `--stage-graph`; both name /home/robtang_google_com/autor-topology, pinned at
# f0f469c (main 5737676 plus the memory isolation below). Diff them before quoting any
# delta -- a benchmark comparison is a claim about two configurations, and the last time
# one was quoted here the arms differed in a stage timeout as well as in the code.
#
# **The arms must not share a memory store, and the first attempt did.** Claude Code's
# auto-memory store is keyed on an ancestor of the working directory, so every run under
# /rmeng_data/robtang shared one `MEMORY.md` loaded into each agent at session start. On
# 2026-08-19 that store took 378 writes while the first attempt ran, 29 of them named
# after a specific task in tasks40.txt. Both arms run the same forty tasks, so whichever
# arm reached a task first wrote notes the other read -- a channel that makes each arm
# partly a copy of the other and shrinks the very difference this ablation measures.
# Pin f0f469c passes `--settings '{"autoMemoryEnabled": false}'` on **every seat**; verified on the binary
# from /rmeng_data/robtang, where the unflagged run reports the shared path and the
# flagged run has no `memory_paths` key at all. The first attempt's 58 workspaces are kept
# at rcb_runs/topo_{adaptive,linear}_v1_shared_memory and must not be scored as this one.
#
# **The second attempt closed one seat and left the reviewer open.** Pin 99fd73e passed the
# flag through the front end's own operator, but `AutomatedReviewer` builds a second
# `ClaudeOperator` of its own. Measured 9.5 hours into that attempt over all 80 workspaces:
# of 4,513 recorded CLI invocations 2,752 carried the flag and 1,761 did not, and the split
# was exact -- every stage call had it, every `review_start` lacked it. All 80 workspaces
# reached the store and the traffic was one-directional (adaptive wrote 10, linear 0), on
# notes about the review mechanism itself. f0f469c moves the choice to a process-wide
# default so every seat inherits it. Those 80 workspaces are kept at
# rcb_runs/topo_{adaptive,linear}_v2_reviewer_open and must not be scored either.
#
# **`eval-w[1-9]` cannot authenticate to Vertex, and a run there looks like a finished
# run.** An element that lands on one dies in ~290s with `403 ACCESS_TOKEN_SCOPE_
# INSUFFICIENT` on its first model call, zero stages, and still writes a 183-byte
# `report/report.md` saying "Incomplete run" -- an artifact a scorer will happily read as
# an attempt worth zero. Measured 2026-08-19 over 80 elements: 72 of 77 on eval-w6..w9
# failed this way, 0 of 3 on the `slurm2-c3*` nodes did, and a paired probe in a fresh
# allocation on `slurm2-c3smallnodeset-29` answered `ok` both with and without the memory
# isolation flag, so the flag is not the cause. Excluded rather than retried: the failure
# is instant and total, so retrying on the same node just burns the element again.
#
# **Submitted as eighty one-element jobs, not one throttled array.** `--array=1-80%40`
# sat pending for hours; the same script submitted per element (`sbatch --array=$i`)
# had 58 tasks claimed within fifteen minutes, because the scheduler can backfill eighty
# independent one-CPU jobs into gaps it cannot fit a throttled block into.
#
# **Odd/even interleaves the pair.** Element 2k-1 runs task k adaptive and element 2k runs
# task k linear, so a task's two arms enter the queue adjacent and start together. Box load
# and any drift in the model endpoint then land on both sides of every pair rather than on
# whichever arm ran overnight. That is the alternating control this box has needed before.
#
# **One task per element, 1 CPU, 40 hours.** Not 20: the last arm launched here was sliced
# 20-tasks-per-element with a 20-hour cap and its elements were killed at exactly 20:00:11
# with 34 of 40 workspaces holding a report and only one of them scored. A task takes 9-15
# hours, an element here runs exactly one, and 24 hours is 1.6x the observed maximum for
# one. Not 40 either: a 40-hour element cannot be backfilled into any gap, and the first
# submission of this array was scheduled two days out on a partition with 259 idle CPUs.
# The cap has to be generous against one task and small enough that the scheduler can
# place it. 1 CPU because the work is `claude` plus a Gemini search and
# spends its life blocked on the network.
#
# **16G, and the 40G it replaces was a guess.** 40G was inherited from a single task
# OOM-killed at 31G. Measured on a live node instead: a task's `claude` process holds
# ~0.3 GB RSS, and a node running twelve of them was using 12 GB of its 346 GB. The 40G
# reservation was over a hundred times the typical need, and reserving it eighty times is
# why this array's first submission was scheduled two days out on a partition whose big
# nodes had 38 CPUs idle and AllocMem at 338 of 349 GB -- the memory was not in use, it
# was reserved, largely by my own arms. 16G is sixteen times the observed usage and lets
# twenty tasks share a node. A task that genuinely needs more is killed and recorded, and
# `run_arm.py` leaves its claim recoverable; two days of queue is not recoverable.
set -u
LINE=$(( (SLURM_ARRAY_TASK_ID + 1) / 2 ))
TASK=$(sed -n "${LINE}p" /home/robtang_google_com/rcb_tools/tasks40.txt)
if [ $(( SLURM_ARRAY_TASK_ID % 2 )) -eq 1 ]; then ARM=topology_adaptive; else ARM=topology_linear; fi

PIN=/home/robtang_google_com/autor-topology
echo "[$(date '+%F %T')] node=$(hostname) cpus=$(nproc) mem=$(free -g | awk '/^Mem:/{print $2}')G"
echo "[$(date '+%F %T')] pin=$(git -C "$PIN" rev-parse --short HEAD) dirty=$(git -C "$PIN" status --porcelain | wc -l)"
echo "[$(date '+%F %T')] element ${SLURM_ARRAY_TASK_ID} -> line ${LINE} task ${TASK} arm ${ARM}"

export RCB_MAX_CONCURRENT=1
exec python3 /home/robtang_google_com/rcb_tools/run_arm.py "${ARM}" "${TASK}"
