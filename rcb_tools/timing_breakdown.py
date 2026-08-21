"""Where the wall clock goes in an AutoR run.

`logs_raw.jsonl` interleaves two things: `_meta` markers the harness writes when it starts
an operator or reviewer call, and the operator's own streamed events, each carrying a
`timestamp`. A marker opens a segment; the segment closes at the next marker. Attributing
the wall time between them to (stage, mode) is the only breakdown available -- nothing in
the run records durations directly.

Reads the file as text and regexes the two fields it needs. Full json.loads on 4358 lines
of a 56 MB file, times 39 workspaces times two arms, is the difference between two minutes
and forty.
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

TS = re.compile(r'"timestamp":\s*"([^"]+)"')
META = re.compile(r'"_meta":\s*\{"stage":\s*"([^"]*)",\s*"attempt":\s*(\d+),\s*"mode":\s*"([^"]*)"')


def _parse(ts: str) -> float | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def timeline(path: Path) -> list[tuple[str, str, int, float]]:
    """(stage, mode, attempt, timestamp) for every marker, plus a final ('END','',0,t)."""
    out: list[tuple[str, str, int, float]] = []
    last = None
    pending = None
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = META.search(line[:400])
            if m:
                # The marker line itself has no timestamp; the first event after it does.
                pending = (m.group(1), m.group(3), int(m.group(2)))
                continue
            t = TS.search(line)
            if not t:
                continue
            when = _parse(t.group(1))
            if when is None:
                continue
            last = when
            if pending is not None:
                out.append((*pending, when))
                pending = None
    if last is not None:
        out.append(("END", "", 0, last))
    return out


def one_run(ws: str) -> dict | None:
    root = Path(ws)
    logs = sorted(root.glob(".autor/*/logs_raw.jsonl"))
    if not logs:
        return None
    tl: list[tuple[str, str, int, float]] = []
    for f in logs:
        tl.extend(timeline(f))
    tl.sort(key=lambda r: r[3])
    if len(tl) < 2:
        return None
    per: dict[tuple[str, str], float] = {}
    calls: dict[tuple[str, str], int] = {}
    for (stage, mode, _a, t0), (_s2, _m2, _a2, t1) in zip(tl, tl[1:]):
        if stage == "END":
            continue
        d = t1 - t0
        if d < 0 or d > 6 * 3600:      # a gap that long is a stall, not a call
            d = min(max(d, 0.0), 6 * 3600)
        per[(stage, mode)] = per.get((stage, mode), 0.0) + d
        calls[(stage, mode)] = calls.get((stage, mode), 0) + 1
    span = tl[-1][3] - tl[0][3]
    return {"task": root.name.split("_2026")[0], "span": span,
            "per": {f"{k[0]}|{k[1]}": v for k, v in per.items()},
            "calls": {f"{k[0]}|{k[1]}": v for k, v in calls.items()}}


if __name__ == "__main__":
    arm = sys.argv[1]
    wss = [str(p) for p in sorted(Path(f"/rmeng_data/robtang/rcb_runs/{arm}").glob("*_2026*")) if p.is_dir()]
    with ProcessPoolExecutor(max_workers=8) as ex:
        rows = [r for r in ex.map(one_run, wss) if r]
    Path(f"/home/robtang_google_com/rcb_results/timing_{arm}.json").write_text(
        json.dumps(rows, indent=1), encoding="utf-8")
    print(f"{arm}: {len(rows)} runs")
