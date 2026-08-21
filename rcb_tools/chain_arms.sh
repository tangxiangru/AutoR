#!/bin/bash
# control pass 1 -> control retry pass -> AutoR arm.
#
# The retry pass is not optional. Earth_003's first control run died with
# `terminal_reason: api_error` ("Connection lost mid-response") after 136s -- a transport
# failure, not an agent failure. Left alone it becomes a 0 for the control arm, and that
# bias points toward AutoR, which is the one direction this comparison must not be wrong
# in. run_arm.py's resume skips only workspaces holding a completed, scoreable report, so a
# second pass retries exactly the failures and pays for nothing else.
#
# One script rather than two chained ones: two would race in the window between pass 1
# exiting and pass 2 registering, and the AutoR arm would start over the top of the retry.
log() { echo "[$(date '+%m-%d %H:%M:%S')] $*"; }

while pgrep -f "run_arm[.]py control" > /dev/null; do sleep 60; done
log "control pass 1 done; retry pass for transport failures"
python3 /home/robtang_google_com/rcb_tools/run_arm.py control

log "control arm complete; starting AutoR arm"
exec python3 /home/robtang_google_com/rcb_tools/run_arm.py autor
