#!/usr/bin/env python3
"""Score one arm's workspaces with the gpt-5.1 judge. Resumable, and honest about failure.

    python3 score_arm.py <arm-dir-name> <out-dir-name> [task ...]

Three traps this exists to avoid, each of which has already produced a wrong number here:

* `score.py` records a judge that failed to answer as `score: 0`, indistinguishable from a
  genuine zero. A run with any failed item is reported unusable, never as a zero.
* A run still in flight has `status: running` in `_meta.json`. Scoring one measures nothing.
* `score.py` returns `{"error": ...}` rather than raising when its config is incomplete.
  That is re-raised here, so a misconfiguration cannot be silently filed as "no score".
"""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402


MIN_SCOREABLE_BYTES = 1200


def pick_workspace(root: Path, task: str) -> Path | None:
    """The best workspace for a task, not merely the newest.

    A task can have several. The /tmp sweep killed a batch mid-flight, leaving orphans whose
    `_meta.json` still says "running" -- and one of them, Chemistry_000, holds a complete
    28 KB report the agent had already finished writing. The relaunch made a second, newer
    workspace for the same task. Taking the newest would score the relaunch even if it
    failed and left nothing, discarding a real report that was sitting right there and
    recording a 0.

    That error has a direction. Both arms are affected, but the control arm is the one being
    re-run after the sweep, so a rule that silently prefers an empty newer directory
    penalises the control and flatters AutoR -- the one way this comparison must not be
    wrong. So: a completed run with a scoreable report wins; among those, the newest. Only
    when none qualifies does it fall back to the newest of whatever exists, so a genuinely
    empty task still reports as empty rather than vanishing.
    """
    matches = sorted(root.glob(f"{task}_*"))
    if not matches:
        return None

    def scoreable(ws: Path) -> bool:
        meta, report = ws / "_meta.json", ws / "report" / "report.md"
        if not (meta.exists() and report.exists()):
            return False
        if report.stat().st_size < MIN_SCOREABLE_BYTES:
            return False
        try:
            return json.loads(meta.read_text()).get("status") == "completed"
        except (OSError, json.JSONDecodeError):
            return False

    good = [ws for ws in matches if scoreable(ws)]
    if good:
        return good[-1]

    # Nothing finished cleanly. Falling back to the newest would hand the judge whichever
    # directory happens to sort last, and after a relaunch that is an empty one -- so a task
    # holding a real 28 KB report from a killed run would score 0. Prefer the largest report
    # instead: a report the agent actually wrote is better evidence of what the arm produced
    # than an empty directory that is merely more recent. Ties and the no-report case fall
    # through to the newest, so an arm that produced nothing still reports nothing.
    def report_size(ws: Path) -> int:
        report = ws / "report" / "report.md"
        return report.stat().st_size if report.exists() else 0

    biggest = max(matches, key=lambda ws: (report_size(ws), ws.name))
    return biggest if report_size(biggest) >= MIN_SCOREABLE_BYTES else matches[-1]


def approved_stages(ws: Path) -> int:
    """How many stages the reviewer approved, from the run's own manifest.

    This used to count `.md` files under `.autor/*/stages`, excluding `.tmp.md` and
    `.skip_stub.md`, which is a count of stage files written and not a count of stages
    approved. Two things make those different numbers. An auto-skipped stage does not
    always write the stub suffix -- every run in `full40_gpt54` has zero
    `.skip_stub.md` files and two plain `NN_name.md` for two stages the manifest marks
    `status: skipped, approved: false` -- and the glob is over `.autor/*/stages`, so a
    run that was resumed counts every generation it ever had.

    Sampled across 24 workspaces in four arms on 2026-08-20, the file count disagreed
    with the manifest in **22 of them**, always upward: `full40_gpt54` reported 2 against
    0 approved, `full40/Chemistry_001` 6 against 3, `full40_skills/Chemistry_000` 6
    against 1. Every score file carrying an `approved_stages` field written before this
    is carrying that other quantity under this name.

    `run_manifest.json` is the reviewer's own record and needs no inference. A workspace
    without one returns 0 rather than guessing from the filesystem.
    """
    total = 0
    manifests = sorted((ws / ".autor").glob("*/run_manifest.json"))
    if not manifests:
        return 0
    try:
        payload = json.loads(manifests[-1].read_text())
    except (OSError, json.JSONDecodeError):
        return 0
    for stage in payload.get("stages", []):
        if stage.get("approved"):
            total += 1
    return total


def arm_tasks(root: Path) -> set[str]:
    """The task names an arm directory holds, cut at the launcher's own timestamp.

    A workspace is `<task>_<YYYYmmdd>_<HHMMSS>`, and a dead one gets a hand-added suffix
    saying why: `Astronomy_000_20260817_232502_DEAD_launcher_gone`. `rsplit("_", 2)` counts
    underscores from the right, so the suffix shifts the cut and the "task" becomes
    `Astronomy_000_20260817_232502_DEAD` -- a task that does not exist, handed its own row
    and its own score file. Seven such directories are on disk, which is why `gpt51_skills`
    holds 46 files and `gpt51_v220` holds 41 for forty-task arms. They score `null` today,
    so no mean is wrong yet; the day one of those directories gains a completed report it
    becomes a forty-first task.

    The timestamp is the one part of the name the launcher generates, so cut there, and say
    out loud when a name has none. A silent exclusion is worse than the silent invention it
    replaces.
    """
    names: set[str] = set()
    unparseable: list[str] = []
    for path in root.glob("*_2026*"):
        if not path.is_dir():
            continue
        match = re.match(r"(.+?)_\d{8}_\d{6}(?:_.+)?$", path.name)
        if match:
            names.add(match.group(1))
        else:
            unparseable.append(path.name)
    if unparseable:
        print(f"  ignored {len(unparseable)} unparseable workspace name(s): "
              f"{sorted(unparseable)}", flush=True)
    return names


def main(argv: list[str]) -> int:
    arm, out_name, *only = argv
    root = common.RUNS / arm
    out = common.RESULTS / out_name
    out.mkdir(parents=True, exist_ok=True)
    score_mod = common.judged_scorer()
    # Read off the class `judged_scorer` actually installed, not off a constant here, so
    # that swapping the judge cannot leave this label behind pointing at the old one.
    judge_model = getattr(score_mod.LLMAgent, "DEFAULT_MODEL", None) or getattr(
        sys.modules.get("gpt51_judge"), "DEFAULT_MODEL", "unrecorded")

    tasks = sorted(arm_tasks(root))
    if only:
        tasks = [t for t in tasks if t in only]
    print(f"{arm}: {len(tasks)} task(s) to consider -> {out}", flush=True)

    def one(task: str) -> dict:
        dest = out / f"{task}.json"
        if dest.exists():
            cached = json.loads(dest.read_text())
            # Only a real score is final. "still running" and transport failures were being
            # cached like results, so a task scored once mid-flight was never scored again --
            # four completed control runs sat unscored behind a cache entry that said None.
            if cached.get("total_score") is not None:
                return cached
        ws = pick_workspace(root, task)
        if ws is None:
            row = {"task": task, "total_score": None, "error": "no workspace"}
        elif not (ws / "_meta.json").exists():
            row = {"task": task, "total_score": None, "error": "no _meta.json"}
        elif (_status := (_meta := json.loads((ws / "_meta.json").read_text())).get("status")) != "completed":
            # `running` is the in-flight case this file was written for. `aborted` is the
            # one that cost a real number: a run whose stage walk was ended by an
            # exception still exports a report -- the adapter salvages what exists -- and
            # that report scores like any other. Life_002 on the `full40_pins` arm died at
            # Stage 03 of 7 and was scored 22.6 into a 40-task mean. Only `completed` is
            # scoreable; everything else says why it is not, by name.
            _why = {
                "running": "still running",
                "aborted": "run aborted: the stage walk was ended by an exception",
                # Not "no substantive report". That asserts something about the artifact
                # that nothing here looked at, and it is false twice over on disk:
                # full40_skills/Math_002_20260817_232503 is `failed` with a 21,691 B report
                # (a synthesized fallback over zero approved stages), and
                # full40_abl40/Life_000_20260819_034351 was `failed` with 46,603 B, 15
                # figures and all seven stages approved -- it raised in `export_run` after
                # the deliverable existed. Refusing to score both is right; describing both
                # as a missing report sent a reader looking for a file that is there.
                "failed": f"run reported failure (exit_code {_meta.get('exit_code')})",
            }.get(_status, f"status={_status!r}")
            _report = ws / "report" / "report.md"
            row = {"task": task, "total_score": None, "error": _why,
                   "report_bytes": _report.stat().st_size if _report.is_file() else 0,
                   "approved_stages": approved_stages(ws)}
        else:
            try:
                result = score_mod.score_workspace(str(ws))
                if result.get("error"):
                    raise RuntimeError(result["error"])
                items = result.get("items") or []
                failed = sum(1 for i in items
                             if "Failed to parse scoring response" in str(i.get("reasoning", "")))
                report = ws / "report" / "report.md"
                meta = json.loads((ws / "_meta.json").read_text())
                row = {
                    "task": task, "run_id": ws.name,
                    "total_score": None if failed else result.get("total_score"),
                    "failed_items": failed, "items": len(items),
                    # `model` is the AGENT's model, read off the run's _meta.json. It is
                    # not the judge, and for two months these files carried no judge
                    # field at all -- the judge was asserted only by the output
                    # directory being called `gpt51_*`, which is a filename, not a
                    # measurement. A score whose judge is unrecorded cannot be quoted:
                    # on identical artifacts Gemini 2.5 Flash scored 37.0 where Claude
                    # Opus scored 20.8. Recorded here from the judge object actually
                    # installed by `common.judged_scorer()`, so it cannot drift from the
                    # code path that produced the number.
                    "judge_model": judge_model, "judge_recorded_by": "score_arm",
                    "model": meta.get("model"), "code_version": meta.get("code_version"),
                    "duration_seconds": meta.get("duration_seconds"),
                    "approved_stages": approved_stages(ws),
                    "report_bytes": report.stat().st_size if report.exists() else 0,
                    "images": len(list((ws / "report" / "images").glob("*.png"))),
                }
            except Exception as exc:  # noqa: BLE001
                row = {"task": task, "total_score": None, "error": f"{type(exc).__name__}: {exc}"}
        dest.write_text(json.dumps(row, indent=2))
        print(f"  {task}: {row.get('total_score')}"
              + (f"  ({row['error']})" if row.get("error") else ""), flush=True)
        return row

    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(one, tasks))
    usable = [r for r in rows if r.get("total_score") is not None]
    print(f"\nscored {len(usable)}/{len(rows)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
