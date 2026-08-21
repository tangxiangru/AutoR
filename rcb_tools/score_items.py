#!/usr/bin/env python3
"""Re-score named tasks and keep the judge's per-item verdicts.

    python3 score_items.py <arm-dir> <out-dir> <task> [task ...]

`score_arm.py` keeps only the total and a count of items, which is all a leaderboard
needs and nothing a diagnosis can use: "this run scored 23.2" does not say which of the
four checklist entries it missed. This writes the full `items` list, so a lagging task can
be read against the rubric it was actually judged on.

Separate from `score_arm.py` rather than a flag on it because the two answer different
questions and cache into different directories -- a totals file and an items file for the
same task must not be able to disagree about which run produced them, and they cannot if
neither overwrites the other.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
from score_arm import pick_workspace  # noqa: E402


def main(argv: list[str]) -> int:
    arm, out_name, *tasks = argv
    root = common.RUNS / arm
    # A missing runs directory is a caller error, not forty missing workspaces. Without
    # this, every task below resolves to `{"error": "no workspace"}` and the run exits 0,
    # so a caller that passes the wrong name -- run_arm.py's arm key `topology_linear`
    # where the directory is `topo_linear` -- gets a full set of plausible-looking error
    # stubs and no signal at all. That happened, silently, for the whole topology
    # ablation. Per-task "no workspace" stays a stub because a single unfinished task
    # genuinely is one; the directory not existing never is.
    if not root.is_dir():
        near = sorted(p.name for p in common.RUNS.iterdir()
                      if p.is_dir() and arm.split("_")[-1] in p.name)
        print(f"{root} does not exist. Pass the runs-directory name, not an arm key."
              + (f" Did you mean: {', '.join(near)}?" if near else ""), file=sys.stderr)
        return 2
    out = common.RESULTS / out_name
    out.mkdir(parents=True, exist_ok=True)
    score_mod = common.judged_scorer()
    judge_model = getattr(score_mod.LLMAgent, "DEFAULT_MODEL", None) or getattr(
        sys.modules.get("gpt51_judge"), "DEFAULT_MODEL", "unrecorded")

    def one(task: str) -> str:
        dest = out / f"{task}.json"
        if dest.exists() and json.loads(dest.read_text()).get("items"):
            return f"  {task}: cached"
        ws = pick_workspace(root, task)
        if ws is None or not (ws / "_meta.json").exists():
            dest.write_text(json.dumps({"task": task, "error": "no workspace"}, indent=1))
            return f"  {task}: no workspace"
        try:
            result = score_mod.score_workspace(str(ws))
            if result.get("error"):
                raise RuntimeError(result["error"])
        except Exception as exc:  # noqa: BLE001
            dest.write_text(json.dumps({"task": task, "error": f"{type(exc).__name__}: {exc}"}, indent=1))
            return f"  {task}: {type(exc).__name__}"
        items = result.get("items") or []
        dest.write_text(json.dumps({
            "task": task, "run_id": ws.name,
            # Same reason as score_arm.py: a score whose judge is recorded only by the
            # output directory's name is a score nobody can check. Taken from the class
            # `judged_scorer()` installed, so it tracks the code that produced the number.
            "judge_model": judge_model, "judge_recorded_by": "score_items",
            "total_score": result.get("total_score"),
            "items": items,
        }, indent=1))
        zeros = sum(1 for i in items if not i.get("score"))
        return f"  {task}: {result.get('total_score')}  ({zeros}/{len(items)} items at 0)"

    with ThreadPoolExecutor(max_workers=8) as ex:
        for line in ex.map(one, tasks):
            print(line, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
