#!/usr/bin/env python3
"""How many skills a run actually opened, per arm.

    python3 skill_reads.py <arm-dir> [<arm-dir> ...]

The number the pack is judged on. `install_run_skills` reports what a run was *offered*
and the pin table reports what it was *told to read*; neither is what happened. The only
record of that is the `Skill` tool call in `logs_raw.jsonl`.

Two exclusions, both load-bearing. The MCP tools (`autor-search`, `autor-write`,
`ai4ai-web-search`) arrive through the same tool and are called thousands of times a run;
counting them turns "1 skill read" into "157 skills read" and has done, in a draft of this
measurement. And a name that is not in the pack is not a pack skill -- Claude Code ships
its own bundles into the same listing, and they compete for the same attention but say
nothing about whether *this* pack is being read.
"""
from __future__ import annotations

import json
import re
import statistics as st
import sys
from collections import Counter
from pathlib import Path

RUNS = Path("/rmeng_data/robtang/rcb_runs")
MCP = {"autor-search", "autor-write", "ai4ai-web-search", "web-search"}
CALL = re.compile(r'"(?:skill|name)":\s*"([a-z0-9-]{6,})"')


def pack_names(workspace: Path) -> set[str]:
    """What this run was offered, read off the run's own skills directory.

    Read per run rather than from the repository: the pack a run was offered is the pack
    it had, and the checkout has moved several times during these arms.
    """
    for d in list(workspace.glob(".autor/*/.claude/skills")) + list(
        workspace.glob(".autor/*/workspace/.claude/skills")
    ):
        return {p.name for p in d.iterdir() if p.is_dir()}
    return set()


def one(workspace: Path) -> tuple[int, Counter] | None:
    offered = pack_names(workspace)
    if not offered:
        return None
    used: Counter = Counter()
    for log in workspace.glob(".autor/*/logs_raw.jsonl"):
        with log.open(errors="replace") as fh:
            for line in fh:
                if '"Skill"' not in line:
                    continue
                for m in CALL.finditer(line[:3000]):
                    name = m.group(1)
                    if name in MCP or name not in offered:
                        continue
                    used[name] += 1
    return len(offered), used


def main(argv: list[str]) -> int:
    for arm in argv:
        rows = []
        every: Counter = Counter()
        for ws in sorted((RUNS / arm).glob("*_2026*")):
            if "DEAD" in ws.name or not ws.is_dir():
                continue
            r = one(ws)
            if r is None:
                continue
            offered, used = r
            rows.append((ws.name.split("_2026")[0], offered, len(used), sum(used.values())))
            every.update(used)
        if not rows:
            print(f"{arm}: nothing to read")
            continue
        opened = [r[2] for r in rows]
        print(f"\n=== {arm}   n={len(rows)}")
        print(f"  offered   median {st.median(r[1] for r in rows):.0f}")
        print(f"  OPENED    median {st.median(opened):.0f}   mean {st.mean(opened):.2f}"
              f"   max {max(opened)}")
        print(f"  calls     median {st.median(r[3] for r in rows):.0f}   total {sum(r[3] for r in rows)}")
        dist = Counter(opened)
        print(f"  distribution {dict(sorted(dist.items()))}")
        print(f"  opened none  {dist[0]}/{len(rows)} = {dist[0] / len(rows) * 100:.0f}%")
        print(f"  distinct skills opened across the arm: {len(every)}")
        for name, count in every.most_common(10):
            print(f"     {count:>4}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
