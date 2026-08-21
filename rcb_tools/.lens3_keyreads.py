#!/usr/bin/env python3
"""Per-run count of tool calls that actually opened the shared memory store.

Distinguishes "the string appeared somewhere in the log" from "a Read/Grep/Glob call
named the file", which is the count docs/framework.md's table is built from.
"""
import json
import re
import sys
from pathlib import Path

ROOTS = [Path(p) for p in sys.argv[1:]]
MEMDIR = "-rmeng-data-robtang/memory"
READERS = {"Read", "Grep", "Glob", "Bash"}


def key_for(task: str) -> str:
    return "rcb-" + task.lower().replace("_", "-") + "-target-paper"


for root in ROOTS:
    print(f"### {root}")
    for ws in sorted(root.iterdir()):
        if not ws.is_dir() or ws.name.startswith("."):
            continue
        task = re.sub(r"_\d{8}_\d{6}$", "", ws.name)
        key = key_for(task)
        logs = list(ws.glob(".autor/*/logs_raw.jsonl")) or [ws / "_agent_output.jsonl"]
        own = idx = memdir = 0
        for lg in logs:
            if not lg.exists():
                continue
            with open(lg, "rb") as fh:
                for raw in fh:
                    if MEMDIR.encode() not in raw and key.encode() not in raw:
                        continue
                    try:
                        ev = json.loads(raw.decode("utf-8", "replace"))
                    except Exception:
                        continue
                    msg = ev.get("message") or {}
                    content = msg.get("content") if isinstance(msg, dict) else None
                    if not isinstance(content, list):
                        continue
                    for blk in content:
                        if not isinstance(blk, dict) or blk.get("type") != "tool_use":
                            continue
                        if blk.get("name") not in READERS:
                            continue
                        s = json.dumps(blk.get("input", {}))
                        if MEMDIR in s:
                            memdir += 1
                        if key in s:
                            own += 1
                        if "rcb-target-papers-index" in s:
                            idx += 1
        print(f"{task:22s} own_key_calls={own:3d} index_calls={idx:3d} memdir_calls={memdir:3d}")
    print()
