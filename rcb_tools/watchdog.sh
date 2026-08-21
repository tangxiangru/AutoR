#!/bin/bash
# Keep the two benchmark arms running across anything that kills them.
#
# A VSCode disconnect is not the risk: both arms already have PPID 1, no controlling
# terminal, and SIGHUP ignored. The risks that have actually bitten are a /tmp sweep, which
# reclaimed the checkout mid-batch and took both batches with it, and node recycling.
#
# Safe to run on a timer because run_arm.py is resumable: a task whose workspace already
# holds a completed, scoreable report is skipped, so a relaunch costs nothing for work
# already done and only picks up what is missing. That is also why this restarts the arms
# rather than trying to preserve a process -- there is no state in the process worth saving.
set -u
LOG="$HOME/rcb_results/watchdog.log"
TOOLS="$HOME/rcb_tools"
log() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> "$LOG"; }

# Someone is already working: nothing to do.
if pgrep -f "run_arm[.]py" > /dev/null || pgrep -f "chain_arms[.]sh" > /dev/null; then
  exit 0
fi

# The checkout the arms need. A /tmp sweep cannot reach it, but a missing one means the
# relaunch would fail in a way that looks like "the batch finished".
if [ ! -d /rmeng_data/robtang/rcb/ResearchClawBench/tasks ]; then
  log "RCB checkout missing -- not relaunching; re-clone it first"
  exit 1
fi

count_done() {  # $1 = arm dir
  local n=0 d
  for d in "/rmeng_data/robtang/rcb_runs/$1"/*_2026*/; do
    [ -f "$d/report/report.md" ] || continue
    [ "$(stat -c %s "$d/report/report.md")" -ge 1200 ] && n=$((n+1))
  done
  echo "$n"
}

ctrl=$(count_done control_bare_cc)
autor=$(count_done full40)
if [ "$ctrl" -ge 40 ] && [ "$autor" -ge 40 ]; then
  log "both arms have 40 scoreable reports; nothing to restart"
  exit 0
fi

log "no arm running (control $ctrl/40, autor $autor/40) -- relaunching the chain"
setsid nohup "$TOOLS/chain_arms.sh" >> "$HOME/rcb_results/chain_arms.log" 2>&1 &
