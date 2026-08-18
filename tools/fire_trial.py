#!/usr/bin/env python3
"""Run a FIRE-Bench arm matrix and score it. One plan in, one scorecard out.

::

    python3 tools/fire_trial.py plan  --out ~/fire-trial/plan.json \\
        --tasks cot_in_planning premise_order_effects --arms autor-pipeline autor-direct claude-stock
    python3 tools/fire_trial.py run   --plan ~/fire-trial/plan.json --concurrency 6
    python3 tools/fire_trial.py score --plan ~/fire-trial/plan.json --draws 3
    python3 tools/fire_trial.py report --plan ~/fire-trial/plan.json

**Three arms, because two of them are needed to attribute a difference to anything.**

``autor-pipeline``
    ``fire_agent.py --profile pipeline``. The stage walk.
``autor-direct``
    ``fire_agent.py --profile direct``. One agentic operator call with *the same goal
    text*, the same model, the same denied tools, the same sandbox and the same deadline.
    Pipeline minus direct is the pipeline's effect and nothing else.
``claude-stock``
    The benchmark's own ``agents/claude/run.py``, given the raw ``instruction.txt``.
    Direct minus stock is the goal contract's effect -- the scoring guidance, the model
    catalogue, the length target. Without this arm, a pipeline that beat the published
    baseline could be a pipeline that worked or a prompt that told the model how the
    grader works, and the run cannot say which.

**Nothing here averages a single draw.** The judge's measured range on one identical log
was 43 F1 points, and the benchmark's own published baselines carry standard deviations
of 23-25 F1 across tasks. So the report prints, per arm, the per-task median over judge
draws *and* the spread across tasks, and it prints the paired per-task differences rather
than a difference of means: a mean over five tasks whose individual sds are 25 says
almost nothing, while the sign of a per-task pair says a little.

**A run that produced no conclusion is not a zero.** It is reported in its own column.
Averaging it in as 0.0 is the same defect as scoring a judge failure as a low score, and
it is the one that flatters whichever arm crashes less rather than the one that reasons
better.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.trial_driver import foreign_runs, write_json  # noqa: E402

ARMS = {
    "autor-pipeline": {"kind": "autor", "profile": "pipeline"},
    "autor-direct": {"kind": "autor", "profile": "direct"},
    "claude-stock": {"kind": "stock", "agent": "claude"},
}

#: Matches ``FIRE-Bench/run_agent.py``'s own ``TIME_LIMIT``. Every arm gets the same one,
#: which is the only reason the arms are comparable at all.
DEFAULT_DEADLINE = 3600


def make_plan(args: argparse.Namespace) -> dict[str, Any]:
    unknown = [arm for arm in args.arms if arm not in ARMS]
    if unknown:
        raise SystemExit(f"Unknown arm(s): {unknown}. Known: {sorted(ARMS)}")
    return {
        "schema": "fire_trial/1",
        "bench_root": str(Path(args.bench_root).expanduser().resolve()),
        "runs_root": str(Path(args.runs_root).expanduser().resolve()),
        "tasks": list(args.tasks),
        "arms": list(args.arms),
        "model": args.model,
        "deadline_seconds": args.deadline_seconds,
        "repeats": args.repeats,
        "autor_root": str(REPO_ROOT),
        "cells": [
            {
                "task": task,
                "arm": arm,
                "repeat": repeat,
                "id": f"{task}__{arm}__r{repeat}",
            }
            for task in args.tasks
            for arm in args.arms
            for repeat in range(args.repeats)
        ],
    }


def cell_dir(plan: dict, cell: dict) -> Path:
    return Path(plan["runs_root"]) / cell["id"]


def launch(plan: dict, cell: dict) -> dict:
    root = cell_dir(plan, cell)
    root.mkdir(parents=True, exist_ok=True)
    log_file = root / "log.log"
    stdout_file = root / "stdout.log"
    arm = ARMS[cell["arm"]]
    env = os.environ.copy()
    env.setdefault("TMPDIR", "/tmp")
    # Shell environment, not configuration: a launcher that does not re-export these
    # falls back to a 300 s floor and kills any call whose model thinks for five minutes
    # before its first token.
    env["CLAUDE_STREAM_IDLE_TIMEOUT_MS"] = "1800000"
    env["CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS"] = "1800000"

    if arm["kind"] == "autor":
        command = [
            sys.executable,
            str(Path(plan["autor_root"]) / "fire_agent.py"),
            "--bench-root", plan["bench_root"],
            "--task", cell["task"],
            "--profile", arm["profile"],
            "--model", plan["model"],
            "--review-model", plan["model"],
            "--agent-id", cell["arm"],
            "--deadline-seconds", str(plan["deadline_seconds"]),
            "--workspace", str(root / "ws"),
            "--log-file", str(log_file),
        ]
        cwd = plan["bench_root"]
    else:
        command = [sys.executable, str(Path(plan["bench_root"]) / "agents" / arm["agent"] / "run.py")]
        env.update({"AGENT_ID": cell["arm"], "TASK_ID": cell["task"], "LLM_MODEL": plan["model"]})
        cwd = plan["bench_root"]

    started = time.time()
    # A process group per cell, torn down with SIGTERM before SIGKILL.
    #
    # `subprocess.run(timeout=...)` was the first version and it is wrong twice.
    # It calls `Popen.kill()`, so the agent never gets a SIGTERM and never runs the
    # handler that publishes what it had -- which is the whole reason both agents have
    # one. And it kills only the direct child, so the backend CLI underneath it is
    # orphaned and keeps streaming, on somebody else's quota, after the cell is recorded
    # as finished. The group is this cell's own descendants and nothing else: another
    # session's benchmark runs on this box continuously, and a pattern kill would take it.
    with open(stdout_file, "w", encoding="utf-8") as handle:
        child = subprocess.Popen(
            command, env=env, cwd=cwd, stdout=handle, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            # The harness's own limit plus a minute: the adapter is supposed to land
            # inside the deadline by itself, and a cell that needs longer is a cell whose
            # deadline handling failed, which is a result rather than something to
            # accommodate.
            returncode = child.wait(timeout=plan["deadline_seconds"] + 60)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            for signum, grace in ((15, 30), (9, 5)):
                try:
                    os.killpg(os.getpgid(child.pid), signum)
                except (ProcessLookupError, PermissionError):
                    break
                try:
                    child.wait(timeout=grace)
                    break
                except subprocess.TimeoutExpired:
                    continue
            returncode = child.returncode if child.returncode is not None else -9

    # The stock arm chooses its own log path; find it rather than assume it.
    if arm["kind"] == "stock":
        found = sorted(
            (Path(plan["bench_root"]) / "log" / cell["arm"] / plan["model"] / cell["task"]).glob("*/log.log"),
            key=lambda p: p.stat().st_mtime,
        )
        if found:
            log_file = found[-1]

    record = {
        **cell,
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "seconds": round(time.time() - started, 1),
        "log_file": str(log_file),
        "log_exists": log_file.is_file(),
        "workspace": str(root / "ws") if arm["kind"] == "autor" else "",
    }
    meta = root / "ws" / "_meta.json"
    if meta.is_file():
        try:
            payload = json.loads(meta.read_text(encoding="utf-8"))
            record["meta"] = {
                key: payload.get(key)
                for key in (
                    "status", "conclusion_source", "conclusion_chars", "conclusion_text",
                    "log_result_line_written", "pipeline_completed", "stages_approved",
                    "auto_skipped_stages", "deadline_hit", "exit_clause_failures",
                    "elapsed_seconds", "backend_calls", "output_tokens_total",
                )
            }
        except json.JSONDecodeError:
            record["meta"] = {"status": "unreadable"}
    write_json(root / "run.json", record)
    return record


def do_run(args: argparse.Namespace) -> int:
    plan = json.loads(Path(args.plan).expanduser().read_text(encoding="utf-8"))
    Path(plan["runs_root"]).mkdir(parents=True, exist_ok=True)
    others = foreign_runs()
    if others:
        print(f"[note] {len(others)} AutoR-backed process(es) already running; not touching them:")
        for line in others[:5]:
            print("   ", line[:160])
    pending = [
        cell for cell in plan["cells"]
        if args.force or not (cell_dir(plan, cell) / "run.json").is_file()
    ]
    print(f"[plan] {len(plan['cells'])} cells, {len(pending)} to run, concurrency {args.concurrency}")
    done = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(launch, plan, cell): cell for cell in pending}
        for future in as_completed(futures):
            cell = futures[future]
            try:
                record = future.result()
            except Exception as exc:  # noqa: BLE001 - one dead cell must not kill the matrix
                print(f"[fail] {cell['id']}: {type(exc).__name__}: {exc}", flush=True)
                continue
            done += 1
            status = (record.get("meta") or {}).get("status", "-")
            print(
                f"[{done}/{len(pending)}] {cell['id']}: rc={record['returncode']} "
                f"status={status} {record['seconds']}s log={'yes' if record['log_exists'] else 'NO'}",
                flush=True,
            )
    return 0


def _score_cell(plan: dict, cell: dict, scorer: Path, draws: int) -> str:
    root = cell_dir(plan, cell)
    record = json.loads((root / "run.json").read_text(encoding="utf-8"))
    summary_path = root / "_score" / "summary.json"
    if not record.get("log_exists"):
        write_json(summary_path, {"task": cell["task"], "draws": 0, "scored": 0,
                                  "not_scored": {"no_log": 1}})
        return f"  {cell['id']}: no log"
    completed = subprocess.run(
        [
            sys.executable, str(scorer),
            "--bench-root", plan["bench_root"],
            "--log-file", record["log_file"],
            "--task", cell["task"],
            "--draws", str(draws),
            "--out-dir", str(root / "_score"),
        ],
        capture_output=True, text=True,
    )
    line = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""
    return f"  {cell['id']}: rc={completed.returncode} {line[:120]}"


def do_score(args: argparse.Namespace) -> int:
    plan = json.loads(Path(args.plan).expanduser().read_text(encoding="utf-8"))
    scorer = Path(plan["autor_root"]) / "tools" / "score_fire_run.py"
    cells = [
        cell for cell in plan["cells"]
        if (cell_dir(plan, cell) / "run.json").is_file()
        and (args.force or not (cell_dir(plan, cell) / "_score" / "summary.json").is_file())
    ]
    print(f"[score] {len(cells)} cells x {args.draws} draws, concurrency {args.concurrency}")
    # Concurrent across cells, serial within one. The judge is a remote LLM pipeline and
    # a cell's draws are a sample of *it*, so they must not race each other for the same
    # rate limit and come back as transport errors -- which is the one failure this tool
    # is careful not to record as a score.
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futures = {pool.submit(_score_cell, plan, cell, scorer, args.draws): cell for cell in cells}
        for future in as_completed(futures):
            try:
                print(future.result(), flush=True)
            except Exception as exc:  # noqa: BLE001 - one dead cell must not kill the pass
                print(f"  {futures[future]['id']}: {type(exc).__name__}: {exc}", flush=True)
    return 0


def _median_f1(summary: dict, metric: str = "f1") -> float | None:
    block = summary.get(metric)
    if isinstance(block, dict) and block.get("median") is not None:
        return float(block["median"])
    return None


def do_report(args: argparse.Namespace) -> int:
    plan = json.loads(Path(args.plan).expanduser().read_text(encoding="utf-8"))
    table: dict[tuple[str, str], dict] = {}
    for cell in plan["cells"]:
        root = cell_dir(plan, cell)
        summary_path = root / "_score" / "summary.json"
        run_path = root / "run.json"
        entry: dict[str, Any] = {"id": cell["id"]}
        if run_path.is_file():
            record = json.loads(run_path.read_text(encoding="utf-8"))
            entry["seconds"] = record.get("seconds")
            entry["meta"] = record.get("meta") or {}
        if summary_path.is_file():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            entry["scored"] = summary.get("scored", 0)
            entry["not_scored"] = summary.get("not_scored", {})
            for metric in ("precision", "recall", "f1"):
                entry[metric] = _median_f1(summary, metric)
            entry["conclusion"] = summary.get("conclusion")
        table[(cell["task"], cell["arm"])] = entry

    report: dict[str, Any] = {"plan": {k: plan[k] for k in ("tasks", "arms", "model", "deadline_seconds")},
                              "per_task": {}, "per_arm": {}, "paired": {}}
    for task in plan["tasks"]:
        report["per_task"][task] = {arm: table.get((task, arm), {}) for arm in plan["arms"]}
    for arm in plan["arms"]:
        values = [table.get((task, arm), {}).get("f1") for task in plan["tasks"]]
        got = [v for v in values if v is not None]
        report["per_arm"][arm] = {
            "tasks": len(plan["tasks"]),
            "scored_tasks": len(got),
            "f1_median": round(statistics.median(got), 2) if got else None,
            "f1_mean": round(statistics.mean(got), 2) if got else None,
            "f1_sd": round(statistics.stdev(got), 2) if len(got) > 1 else None,
            "f1_values": got,
            "unscored_tasks": [t for t, v in zip(plan["tasks"], values) if v is None],
        }
    if len(plan["arms"]) >= 2:
        base = plan["arms"][-1]
        for arm in plan["arms"][:-1]:
            pairs = [
                (task, table[(task, arm)].get("f1"), table[(task, base)].get("f1"))
                for task in plan["tasks"]
                if table.get((task, arm)) and table.get((task, base))
            ]
            complete = [(t, a, b) for t, a, b in pairs if a is not None and b is not None]
            deltas = [a - b for _, a, b in complete]
            report["paired"][f"{arm} - {base}"] = {
                "complete_pairs": len(complete),
                "incomplete_pairs": len(pairs) - len(complete),
                "per_task": {t: round(a - b, 2) for t, a, b in complete},
                "median_delta": round(statistics.median(deltas), 2) if deltas else None,
                "wins": sum(1 for d in deltas if d > 0),
                "losses": sum(1 for d in deltas if d < 0),
                "ties": sum(1 for d in deltas if d == 0),
            }
    out = Path(args.out).expanduser() if args.out else Path(plan["runs_root"]) / "report.json"
    write_json(out, report)
    print(json.dumps({"per_arm": report["per_arm"], "paired": report["paired"]}, indent=2))
    print(f"[written] {out}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fire_trial")
    sub = parser.add_subparsers(dest="command", required=True)

    plan_cmd = sub.add_parser("plan")
    plan_cmd.add_argument("--out", required=True)
    plan_cmd.add_argument("--bench-root", default=str(Path.home() / "FIRE-Bench"))
    plan_cmd.add_argument("--runs-root", default=str(Path.home() / "fire-trial"))
    plan_cmd.add_argument("--tasks", nargs="+", required=True)
    plan_cmd.add_argument("--arms", nargs="+", default=list(ARMS))
    plan_cmd.add_argument("--model", default="opus")
    plan_cmd.add_argument("--deadline-seconds", type=int, default=DEFAULT_DEADLINE)
    plan_cmd.add_argument("--repeats", type=int, default=1)

    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("--plan", required=True)
    run_cmd.add_argument("--concurrency", type=int, default=4)
    run_cmd.add_argument("--force", action="store_true")

    score_cmd = sub.add_parser("score")
    score_cmd.add_argument("--plan", required=True)
    score_cmd.add_argument("--draws", type=int, default=3)
    score_cmd.add_argument("--concurrency", type=int, default=4)
    score_cmd.add_argument("--force", action="store_true")

    report_cmd = sub.add_parser("report")
    report_cmd.add_argument("--plan", required=True)
    report_cmd.add_argument("--out", default="")

    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "plan":
        plan = make_plan(args)
        write_json(Path(args.out).expanduser(), plan)
        print(f"[written] {args.out}: {len(plan['cells'])} cells")
        return 0
    if args.command == "run":
        return do_run(args)
    if args.command == "score":
        return do_score(args)
    return do_report(args)


if __name__ == "__main__":
    raise SystemExit(main())
