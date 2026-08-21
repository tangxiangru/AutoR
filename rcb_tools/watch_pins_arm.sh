#!/bin/bash
# Score `full40_pins` as it finishes, then print the table. Detached, resumable.
#
# Scores each task as soon as its own run is over rather than waiting for the batch,
# because `score_arm.py` refuses a workspace whose `_meta.json` still says `running` and
# skips one it has already scored. So a poll costs nothing for work already done.
#
# Judge is gpt-5.1 and only gpt-5.1: judge choice has been measured to move a score by
# ~16 points, so a number carrying a different judge is not a smaller number, it is an
# incomparable one.
set -u
TOOLS="$HOME/rcb_tools"
LOG="$HOME/rcb_results/pins_watch.log"
ARM=full40_pins
OUT=gpt51_pins
log() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> "$LOG"; }

log "watcher up; arm=$ARM out=$OUT"
while true; do
  # Both arrays feeding this arm are named `autorpin*`. The runner itself lives on the
  # compute nodes, so there is nothing about it to count from here; the queue is the
  # only signal, and when it is empty the batch is over.
  LIVE=$(squeue -u "$USER" -h -o "%j" | grep -cE '^autorpin' || true)

  python3 "$TOOLS/score_arm.py" "$ARM" "$OUT" >> "$LOG" 2>&1 || log "score pass returned nonzero"
  # Count real scores, not files. `score_arm.py` writes `{"total_score": null, "error":
  # "still running"}` for every task it cannot score yet, so counting files reported a
  # fully-scored arm on the first pass, twenty minutes into a run with no reports on
  # disk at all. It does re-score those later -- only a non-null total is final to it --
  # so the placeholders were harmless and the counter was not.
  SCORED=$(python3 -c "
import glob, json
n = 0
for f in glob.glob('$HOME/rcb_results/$OUT/*.json'):
    try:
        if isinstance(json.load(open(f)).get('total_score'), (int, float)):
            n += 1
    except Exception:
        pass
print(n)
")
  DONE=$(ls -d /rmeng_data/robtang/rcb_runs/$ARM/*/report/report.md 2>/dev/null | wc -l)
  log "live_elements=$LIVE reports=$DONE scored=$SCORED"

  if [ "$LIVE" -eq 0 ]; then
    log "no live elements and no runner; final scoring pass"
    python3 "$TOOLS/score_arm.py" "$ARM" "$OUT" >> "$LOG" 2>&1 || true
    break
  fi
  sleep 900
done

log "=== final ==="
python3 - >> "$LOG" 2>&1 <<'PY'
import glob, json, statistics as st
from pathlib import Path
vals = {}
for f in glob.glob('/home/robtang_google_com/rcb_results/gpt51_pins/*.json'):
    j = json.load(open(f))
    if isinstance(j.get('total_score'), (int, float)) and j.get('total_weight'):
        vals[Path(f).stem] = j['total_score'] / j['total_weight']
print(f'n={len(vals)}')
if vals:
    print(f'mean {st.mean(vals.values()):.2f}  median {st.median(vals.values()):.2f}')
    for t, v in sorted(vals.items(), key=lambda kv: kv[1]):
        print(f'  {t:<20} {v:6.2f}')
print('baselines, same judge and window: AutoR 2ffaeb4 31.35, bare Claude Code 31.53')
PY
log "watcher done"
