#!/bin/bash
# Second tier of a two-tier memory plan: re-run whatever the cheap tier could not finish,
# with enough memory that the tail fits.
#
#     rescue_arm.sh <arm> <workspace-root-name> [mem_mb]
#     rescue_arm.sh autor_main40 full40_main40 98304
#
# Set DRY=1 to print the rescue set and submit nothing. There is no such thing as a
# harmless trial run of this script otherwise: called before the cheap tier has finished,
# every task looks unfinished and it cheerfully submits the whole arm at 96 GiB. That
# happened once (job 49911, cancelled within the minute), which is why the flag exists and
# why the watcher is the only thing that should call it without one.
#
# ---------------------------------------------------------------------------
# Why two tiers instead of one memory number
# ---------------------------------------------------------------------------
# Measured across 40 live elements of the `autora9c` arm under a 64 GiB cap -- so the
# maximum is observed, not censored the way the old 28 GiB cap censored its own:
#
#     median 3.2 GiB    p75 14.8    p90 19.8    max 49.6
#
# The distribution is not centred, it is a spike with a long tail. Sizing every element for
# the tail (40-64 GiB) means most of the reservation is never touched and the array cannot
# schedule -- which is exactly what happened: 270 idle cores on `eval` and the array pending
# on (Resources). Sizing every element for the body (24 GiB) schedules immediately and kills
# the top ~10%.
#
# So: run the body cheap, then rescue the tail expensive. The rescue set is small by
# construction, so it can afford a reservation nobody would grant to forty elements.
#
# A task qualifies for rescue if it has NO scoreable report -- report.md missing or under
# MIN_SCOREABLE_BYTES. That is deliberately narrower than "was OOM-killed": OOM-killed
# SUBPROCESSES are a background condition of this benchmark on this cluster and show up in
# 6/40, 7/44 and 10/41 transcripts across three different arms. Re-running every run that
# shows a kill trace would be re-rolling the dice on one arm only. A missing deliverable is
# the line that can be drawn evenly, because there is no measurement there to bias.
# ---------------------------------------------------------------------------

set -uo pipefail

ARM=${1:?arm name, e.g. autor_main40}
ROOT_NAME=${2:?workspace root name, e.g. full40_main40}
MEM=${3:-98304}

RUNS=/rmeng_data/robtang/rcb_runs/$ROOT_NAME
MIN=1200

need=()
for task in $(cd /home/robtang_google_com/RCB/tasks && ls -d */ | tr -d / | sort); do
  best=0
  for d in "$RUNS/${task}_"*/; do
    [ -d "$d" ] || continue
    s=$(stat -c%s "$d/report/report.md" 2>/dev/null || echo 0)
    [ "$s" -gt "$best" ] && best=$s
  done
  [ "$best" -lt "$MIN" ] && need+=("$task")
done

if [ ${#need[@]} -eq 0 ]; then
  echo "nothing to rescue in $ROOT_NAME"
  exit 0
fi

echo "rescue set for $ROOT_NAME (${#need[@]} task(s), ${MEM}M): ${need[*]}"
if [ "${DRY:-0}" != "0" ]; then
  echo "DRY=1, nothing submitted"
  exit 0
fi
printf '%s\n' "${need[@]}" > "/home/robtang_google_com/rcb_results/rescue_${ROOT_NAME}.txt"

sbatch --job-name="rsc${ROOT_NAME: -6}" \
       --partition=eval --nodes=1 --ntasks=1 --cpus-per-task=4 \
       --mem="${MEM}M" --time=24:00:00 \
       --array="1-${#need[@]}" \
       --output=/home/robtang_google_com/rcb_results/slurm/%x-%a-%A.out \
       --error=/home/robtang_google_com/rcb_results/slurm/%x-%a-%A.out \
       --wrap "set -uo pipefail
mapfile -t T < /home/robtang_google_com/rcb_results/rescue_${ROOT_NAME}.txt
TASK=\${T[\$((SLURM_ARRAY_TASK_ID - 1))]}
echo \"rescue: \$TASK on \$(hostname), mem \${SLURM_MEM_PER_NODE}M\"
export RCB_MAX_CONCURRENT=1
python3 /home/robtang_google_com/rcb_tools/run_arm.py $ARM \"\$TASK\""
