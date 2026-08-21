#!/usr/bin/env python3
"""Everything one lagging task's diagnosis needs, in one file per task.

    python3 task_dossier.py <out-dir> <task> [task ...]

An agent asked to explain why a task lost has to read four things that live four places:
the hidden rubric, the two arms' per-item verdicts, what each arm actually shipped, and
what its stages did on the way. Assembling that per agent means each one re-derives the
paths, and one that gets a path wrong reports a finding about a file it never opened.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

TASKS = Path("/rmeng_data/robtang/rcb/ResearchClawBench/tasks")
RUNS = Path("/rmeng_data/robtang/rcb_runs")
RESULTS = Path("/home/robtang_google_com/rcb_results")
SKIP = (".tmp.md", ".skip_stub.md")


def workspace(arm: str, task: str) -> Path | None:
    hits = sorted(p for p in (RUNS / arm).glob(f"{task}_2026*") if p.is_dir() and "DEAD" not in p.name)
    return hits[-1] if hits else None


def read(path: Path, limit: int) -> str:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return "(unreadable)"
    return text if len(text) <= limit else text[:limit] + f"\n\n[... {len(text) - limit} more chars]"


def dossier(task: str) -> dict:
    out: dict = {"task": task}
    info = TASKS / task / "task_info.json"
    if info.exists():
        out["task_info"] = json.loads(info.read_text())
    check = TASKS / task / "target_study" / "checklist.json"
    if check.exists():
        out["rubric"] = json.loads(check.read_text())

    for arm, key in (("full40_v220", "autor"), ("control_bare_cc", "control")):
        ws = workspace(arm, task)
        if ws is None:
            out[key] = {"error": "no workspace"}
            continue
        rec: dict = {"workspace": str(ws)}
        rep = ws / "report" / "report.md"
        rec["report"] = read(rep, 60_000) if rep.exists() else "(no report)"
        rec["report_bytes"] = rep.stat().st_size if rep.exists() else 0
        rec["figures"] = sorted(p.name for p in (ws / "report" / "images").glob("*")) \
            if (ws / "report" / "images").exists() else []
        if key == "autor":
            stages = {}
            for d in ws.glob(".autor/*/stages"):
                for p in sorted(d.glob("[0-9]*.md")):
                    if any(p.name.endswith(s) for s in SKIP):
                        continue
                    stages[p.stem] = read(p, 14_000)
            rec["stages"] = stages
            plan = list(ws.glob(".autor/*/report_plan.json")) or list(ws.glob(".autor/*/workspace/results/report_plan.json"))
            if plan:
                rec["report_plan"] = read(plan[0], 6_000)
        out[key] = rec

    for src, key in (("items_v220", "autor_items"), ("items_control", "control_items")):
        f = RESULTS / src / f"{task}.json"
        if f.exists():
            out[key] = json.loads(f.read_text())
    return out


def main(argv: list[str]) -> int:
    out_dir = Path(argv[0]); out_dir.mkdir(parents=True, exist_ok=True)
    for task in argv[1:]:
        d = dossier(task)
        p = out_dir / f"{task}.json"
        p.write_text(json.dumps(d, indent=1))
        print(f"  {task}: {p.stat().st_size/1024:.0f} KB"
              f"  rubric {len(d.get('rubric') or [])} items"
              f"  stages {len(d.get('autor',{}).get('stages') or {})}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
