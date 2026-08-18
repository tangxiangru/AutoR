#!/usr/bin/env python3
"""Run one arm of an AIRS-Bench comparison: AutoR, or the same CLI with no AutoR.

::

    python tools/airs_arm.py --arm autor --tasks TextualSimilaritySickSpearmanCorrelation \\
        --root /runs/airs --repo ~/airs-bench --raw-dir /data/airs-raw \\
        --task-python /path/to/venv/bin/python --model opus --wall-clock 10800

    python tools/airs_arm.py --arm bare  --tasks ... (identical flags)

**The point of this file is that the two arms differ in one thing.** Both are given the
brief :func:`src.airsbench.build_task_brief` composes — the same task text, the same
workspace contract, the same scoring rule, the same environment block, byte for byte. Both
run the same CLI binary against the same model with the same tool restrictions, in a
workspace prepared by the same ``prepare.py``. Both are killed at the same wall clock and
both record whether they were. The AutoR arm additionally walks the stage graph and gets
:data:`src.airsbench.AUTOR_STAGE_NOTE` appended to its brief; that is the whole difference,
and it is the thing under test.

That discipline is not decoration. The last time this repo published an AutoR-versus-bare
margin, the two arms had been given different per-stage budgets and 28 of 40 AutoR runs hit
theirs, which made the headline number unusable. So every arm writes ``arm_manifest.json``
recording the exact command, the wall-clock cap, whether it was hit, and the code version —
and ``--compare`` refuses to print a delta between two arms whose manifests disagree on any
of them.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.airsbench import (  # noqa: E402
    AirsTask,
    build_task_brief,
    expected_rows_for,
    export_submission,
    load_task,
    prepare_workspace,
    rows_disagreement,
    score_submission,
    write_run_meta,
    write_task_card,
)
from src.utils import code_version  # noqa: E402


ARMS = ("autor", "bare")

#: Raised for both arms. The Claude CLI kills a stream that has been silent for this long,
#: and what silence means for a research agent is thinking — so the default removes the
#: hard questions rather than the slow ones. The knob is milliseconds and clamps at
#: 1,800,000; the ``BYTE_``-prefixed variant is a different thing and changes nothing here.
STREAM_IDLE_TIMEOUT_MS = "1800000"

#: Seconds between ``SIGTERM`` and ``SIGKILL`` for a run that overran its wall clock. Long
#: enough for a CLI to flush its stream and close its log, short enough that an arm of forty
#: tasks does not spend an hour dying.
KILL_GRACE_SECONDS = 20


#: Routes to the held-out labels that exist on an un-containerised machine, counted in every
#: arm's stream log after the run. AIRS-Bench's own agents cannot take any of them — their
#: container has no network and no copy of the raw data — so a run here is only comparable
#: with theirs if none of these fired. The check is a count, not a verdict: ``load_dataset``
#: also appears in the task's own project description, which the agent will quote back.
#: Reading the surrounding line is the second step and this only tells you whether there is
#: one to read.
DEFAULT_AUDIT_PATTERNS = (
    "hf_hub_download",
    "snapshot_download",
    "test_with_labels",
    "huggingface.co/datasets",
    "evaluate_prepare",
)


@dataclass
class RunRecord:
    task: str
    arm: str
    workspace: str
    command: list[str]
    exit_code: int | None = None
    duration_seconds: float = 0.0
    wall_clock_cap: int = 0
    hit_wall_clock: bool = False
    submission_valid: bool = False
    submission_rows: int | None = None
    metric: str = ""
    value: float | None = None
    normalized: float | None = None
    reason: str = ""
    error: str = ""
    #: pattern -> occurrences in this run's stream log. Empty means the log was unreadable,
    #: which is not the same as clean and is reported as ``audit_log_missing``.
    audit: dict[str, int] = field(default_factory=dict)
    #: The same patterns, counted only inside the agent's own tool inputs. A non-zero entry
    #: here is the agent reaching for something; a non-zero entry in ``audit`` alone is
    #: usually the path appearing in output the agent read.
    audit_tool_use: dict[str, int] = field(default_factory=dict)
    audit_log_missing: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


#: Tool calls whose input names a path or a URL. A mention of a private path anywhere in a
#: stream log is usually incidental -- ``ps`` prints the arm runner's own command line,
#: which carries ``--raw-dir``, and every agent that looks for its stale jobs sees it. A
#: mention inside one of *these* is the agent reaching for it.
PATH_BEARING_TOOLS = ("Bash", "Read", "Write", "Edit", "Glob", "Grep", "NotebookEdit")


def audit_tool_calls(log_path: Path, patterns: list[str]) -> dict[str, int]:
    """Count patterns inside the agent's own tool inputs, not anywhere in the stream.

    This is the half of the audit that distinguishes *saw* from *used*. Measured on the
    first arm run: two tasks' logs mentioned the private raw-data directory four times each
    and the tool-call scan found zero, because every mention came from ``ps`` output the
    agent had asked for while hunting its own stale jobs. Counting text alone would have
    made a clean run look like a compromised one -- and, worse, made the *next* compromised
    one indistinguishable from ordinary noise.
    """
    counts = {pattern: 0 for pattern in patterns if pattern}
    try:
        raw = log_path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return counts
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for block in content or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            if block.get("name") not in PATH_BEARING_TOOLS:
                continue
            blob = json.dumps(block.get("input") or {})
            for pattern in counts:
                counts[pattern] += blob.count(pattern)
    return counts


def audit_stream(log_path: Path, patterns: list[str]) -> tuple[dict[str, int], bool]:
    """Count each pattern in a stream log, reading bytes rather than shelling out to grep.

    A stream log carries whatever the agent printed, which on these runs has included NUL
    bytes; ``grep`` treats such a file as binary and prints nothing, and an empty count from
    a refusal is indistinguishable from an empty count from a clean run. Decoding with
    ``errors="replace"`` cannot refuse.
    """
    try:
        text = log_path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return {}, True
    return {pattern: text.count(pattern) for pattern in patterns if pattern}, False


def arm_environment(base: dict[str, str] | None = None) -> dict[str, str]:
    """The environment both arms run under. One function so it cannot drift between them."""
    env = dict(base if base is not None else os.environ)
    env.setdefault("CLAUDE_STREAM_IDLE_TIMEOUT_MS", STREAM_IDLE_TIMEOUT_MS)
    return env


def bare_command(*, workspace: Path, model: str, cli: str, disallowed_tools: list[str]) -> list[str]:
    """The bare CLI invocation, mirroring what :meth:`src.operator.ClaudeOperator` builds.

    Mirrored deliberately rather than shared: the operator's version threads session state,
    MCP config and resume through it, none of which a single-shot control arm has. What must
    match is the flag surface the model sees, and it does — same permission mode, same
    prompt-from-file form, same stream format, same denials.
    """
    command = [
        cli,
        "--model", model,
        "--permission-mode", "bypassPermissions",
        "--dangerously-skip-permissions",
    ]
    if disallowed_tools:
        command += ["--disallowed-tools", ",".join(disallowed_tools)]
    command += [
        "--session-id", str(uuid.uuid4()),
        "-p", f"@{workspace / 'PROMPT.md'}",
        "--output-format", "stream-json",
        "--verbose",
    ]
    return command


def autor_command(
    *,
    task: AirsTask,
    workspace: Path,
    args: argparse.Namespace,
) -> list[str]:
    command = [
        sys.executable, str(REPO_ROOT / "airs_agent.py"),
        "--repo", str(Path(args.repo).expanduser().resolve()),
        "--raw-dir", str(Path(args.raw_dir).expanduser().resolve()),
        "--task", task.name,
        "--workspace", str(workspace),
        "--task-python", args.task_python,
        "--model", args.model,
        "--stage-timeout", str(args.stage_timeout),
        "--final-stage", args.final_stage,
        "--rigor", args.rigor,
        "--web-search", args.web_search,
        "--no-score",
    ]
    for tool in args.deny_tool:
        command += ["--deny-tool", tool]
    if args.review_model:
        command += ["--review-model", args.review_model]
    if args.environment_note:
        command += ["--environment-note", args.environment_note]
    return command


def denied_tools(args: argparse.Namespace) -> list[str]:
    """What both arms are denied. Symmetric by construction: one list, two consumers.

    ``--web-search off`` removes only the CLI's built-in ``WebSearch`` and ``WebFetch``. A
    machine-level MCP server is still connected and still reaches the internet — the first
    smoke run of this file came back with ``mcp__ai4ai-web-search__web_search`` in its tool
    list under ``off`` — so an arm that claims no search has to name that server too, with
    ``--deny-tool``. It is recorded in the manifest either way, because "which tools" is
    part of what makes two arms the same configuration.
    """
    base = ["WebSearch", "WebFetch"] if args.web_search == "off" else []
    return list(dict.fromkeys([*base, *args.deny_tool]))


def audit_patterns(args: argparse.Namespace) -> list[str]:
    """Everything counted in a stream log: the private paths, the hub routes, and extras.

    The raw-data directory and the benchmark checkout are added here rather than by the
    caller because forgetting them is the failure this audit exists to catch, and a default
    that has to be remembered is not one.
    """
    paths = [str(Path(args.raw_dir).expanduser().resolve()),
             str(Path(args.repo).expanduser().resolve())]
    return list(dict.fromkeys([*paths, *DEFAULT_AUDIT_PATTERNS, *args.audit_pattern]))


def run_until(
    command: list[str], *, cwd: Path, log, timeout: int
) -> tuple[int | None, bool]:
    """Run *command* under a wall clock, and take its whole process tree with it.

    ``subprocess.run(timeout=...)`` kills the direct child and nothing below it. Every
    command here launches an agent CLI which launches more processes, so a timeout under
    that call leaves the agent running: it keeps spending, it keeps holding a GPU, and --
    the part that corrupts a result rather than merely wasting one -- it keeps writing
    ``submission.csv`` while the arm is exporting and scoring the file it just stopped
    producing. The arm's own timeout would race the agent it thinks it killed.

    So the child gets its own process group and the group is signalled: ``SIGTERM``, a
    grace period, then ``SIGKILL``. Returns ``(exit code, hit the wall clock)``, with the
    exit code ``None`` when the wall clock is what ended it -- an exit code from a process
    we killed says nothing about the run.
    """
    process = subprocess.Popen(  # noqa: S603 - composed by the caller, not user text
        command, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT, text=True,
        env=arm_environment(), start_new_session=True,
    )
    try:
        return process.wait(timeout=timeout), False
    except subprocess.TimeoutExpired:
        _signal_group(process, signal.SIGTERM)
        try:
            process.wait(timeout=KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            _signal_group(process, signal.SIGKILL)
            process.wait()
        return None, True


def _signal_group(process: subprocess.Popen, sig: int) -> None:
    """Signal the child's whole group, tolerating a group that has already gone."""
    try:
        os.killpg(os.getpgid(process.pid), sig)
    except (ProcessLookupError, PermissionError):
        process.send_signal(sig)


def run_one(task: AirsTask, args: argparse.Namespace) -> RunRecord:
    workspace = Path(args.root).expanduser().resolve() / args.arm / task.name
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        prepare_workspace(
            task=task, raw_dir=Path(args.raw_dir), workspace=workspace, python=args.task_python
        )
    except Exception as exc:  # noqa: BLE001 - one task that cannot be staged is one task
        # Not raised. A twenty-task arm that dies because the nineteenth dataset would not
        # download has thrown away eighteen runs to report one setup problem, and the arm
        # is hours of wall clock. The record says the task was never attempted, which is a
        # different thing from a run that produced no submission.
        print(f"[{args.arm}] {task.name}: NOT STAGED -- {type(exc).__name__}: {exc}", flush=True)
        return RunRecord(task=task.name, arm=args.arm, workspace=str(workspace), command=[],
                         wall_clock_cap=args.wall_clock, reason="workspace could not be staged",
                         error=f"prepare: {type(exc).__name__}: {exc}")
    write_task_card(workspace, task)

    brief = build_task_brief(
        task=task, workspace=workspace, python=args.task_python,
        environment_notes=args.environment_note,
        expected_rows=expected_rows_for(task, workspace),
        declared_rows_note=rows_disagreement(task, workspace),
    )
    # Written for both arms. For `bare` it is the prompt; for `autor` it is the brief the
    # goal was composed from, kept beside the run so the two can be diffed after the fact.
    (workspace / "PROMPT.md").write_text(brief, encoding="utf-8")

    disallowed = denied_tools(args)
    command = (
        bare_command(workspace=workspace, model=args.model, cli=args.cli, disallowed_tools=disallowed)
        if args.arm == "bare"
        else autor_command(task=task, workspace=workspace, args=args)
    )

    record = RunRecord(task=task.name, arm=args.arm, workspace=str(workspace),
                       command=command, wall_clock_cap=args.wall_clock)
    log_path = workspace / f"{args.arm}_stream.jsonl"
    started = time.monotonic()
    print(f"[{args.arm}] {task.name}: start", flush=True)
    try:
        with log_path.open("w", encoding="utf-8") as log:
            record.exit_code, record.hit_wall_clock = run_until(
                command, cwd=workspace, log=log, timeout=args.wall_clock
            )
    except Exception as exc:  # noqa: BLE001 - one task failing must not end the arm
        record.error = f"{type(exc).__name__}: {exc}"
    record.duration_seconds = round(time.monotonic() - started, 1)
    record.audit, record.audit_log_missing = audit_stream(log_path, audit_patterns(args))
    record.audit_tool_use = audit_tool_calls(log_path, audit_patterns(args))

    # Export before scoring, and for both arms: the bare arm writes straight to the
    # contract path, the AutoR arm may have left the submission in its run tree.
    from src.airsbench import build_run_paths_for_workspace

    paths = build_run_paths_for_workspace(workspace) if args.arm == "autor" else None
    export = export_submission(paths=paths, workspace=workspace, task=task)
    record.submission_valid = export.submission.valid
    record.submission_rows = export.submission.rows

    try:
        with tempfile.TemporaryDirectory(prefix="airs-score-") as scratch:
            score = score_submission(
                task=task, raw_dir=Path(args.raw_dir), workspace=workspace,
                score_dir=Path(scratch) / "score", python=args.task_python,
            )
        record.metric = score.metric
        record.value = score.value
        record.normalized = score.normalized
        record.reason = score.reason
        (workspace / "score.json").write_text(
            json.dumps(score.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001 - a scoring failure is not a run failure
        record.error = (record.error + " | " if record.error else "") + f"score: {exc}"

    write_run_meta(
        workspace, task_id=task.name, run_id=workspace.name, status=(
            "completed" if record.submission_valid else "incomplete"
        ),
        duration_seconds=int(record.duration_seconds), model=args.model,
        agent_name="AutoR" if args.arm == "autor" else "bare-claude-code",
        extra={"arm": args.arm, "hit_wall_clock": record.hit_wall_clock,
               "wall_clock_cap": args.wall_clock, "exit_code": record.exit_code},
    )
    print(f"[{args.arm}] {task.name}: {record.duration_seconds:.0f}s "
          f"valid={record.submission_valid} value={record.value} ns={record.normalized}", flush=True)
    return record


def arm_manifest(args: argparse.Namespace, records: list[RunRecord]) -> dict[str, object]:
    scored = [r for r in records if r.normalized is not None]
    return {
        "arm": args.arm,
        "model": args.model,
        # Recorded even when it is a default, because it is not the same default: the
        # execution model comes from --model and the reviewer's comes from the backend
        # (`sonnet` for claude), so an arm run with `--model opus` and nothing else is
        # opus executing and sonnet reviewing. That is a configuration, and a score from
        # it is not a score from opus reviewing.
        "review_model": args.review_model or "(backend default: sonnet for claude)",
        "cli": args.cli,
        "repo": str(Path(args.repo).expanduser().resolve()),
        "code_version": code_version(),
        "wall_clock_cap": args.wall_clock,
        "stage_timeout": args.stage_timeout,
        "final_stage": args.final_stage,
        "rigor": args.rigor,
        "web_search": args.web_search,
        "denied_tools": denied_tools(args),
        "task_python": args.task_python,
        "tasks": [r.task for r in records],
        "runs": [r.to_dict() for r in records],
        "audit_patterns": audit_patterns(args),
        "audit_totals": {
            pattern: sum(r.audit.get(pattern, 0) for r in records)
            for pattern in audit_patterns(args)
        },
        "audit_tool_use_totals": {
            pattern: sum(r.audit_tool_use.get(pattern, 0) for r in records)
            for pattern in audit_patterns(args)
        },
        "audit_logs_missing": sum(1 for r in records if r.audit_log_missing),
        "valid_submissions": sum(1 for r in records if r.submission_valid),
        "hit_wall_clock": sum(1 for r in records if r.hit_wall_clock),
        "mean_normalized": (sum(r.normalized for r in scored) / len(scored)) if scored else None,
        "mean_normalized_over_all_tasks": (
            sum(r.normalized or 0.0 for r in records) / len(records) if records else None
        ),
    }


#: Manifest fields that must agree before a delta between two arms means anything. A
#: difference in any of them makes the comparison a comparison of configurations.
COMPARABLE_FIELDS = ("model", "cli", "wall_clock_cap", "web_search", "denied_tools",
                     "task_python", "tasks", "repo")

#: Not in :data:`COMPARABLE_FIELDS` on purpose. The bare arm has no reviewer at all, so the
#: AutoR arm's reviewer model can never match it and requiring it to would make every
#: comparison read as incomparable. It is in the manifest so a reader can see it.
NONCOMPARABLE_RECORDED_FIELDS = ("review_model", "stage_timeout", "final_stage", "rigor")


def compare(left: dict, right: dict) -> str:
    lines = [f"{'':32}{left['arm']:>14}{right['arm']:>14}"]
    mismatched = [f for f in COMPARABLE_FIELDS if left.get(f) != right.get(f)]
    by_task_left = {r["task"]: r for r in left["runs"]}
    by_task_right = {r["task"]: r for r in right["runs"]}
    shared = [t for t in left["tasks"] if t in by_task_right]

    for task in shared:
        a, b = by_task_left[task], by_task_right[task]
        lines.append(
            f"{task[:32]:32}{_fmt(a['normalized']):>14}{_fmt(b['normalized']):>14}"
        )
    paired = [(by_task_left[t]["normalized"], by_task_right[t]["normalized"]) for t in shared]
    both = [(x, y) for x, y in paired if x is not None and y is not None]
    lines.append("")
    lines.append(f"{'tasks with both scored':32}{len(both):>14}{'':>14}")
    if both:
        lines.append(
            f"{'mean normalized':32}"
            f"{sum(x for x, _ in both) / len(both):>14.4f}"
            f"{sum(y for _, y in both) / len(both):>14.4f}"
        )
        delta = sum(y - x for x, y in both) / len(both)
        lines.append(f"{'paired mean difference':32}{delta:>+14.4f}  ({right['arm']} - {left['arm']})")
    lines.append(f"{'valid submissions':32}{left['valid_submissions']:>14}{right['valid_submissions']:>14}")
    lines.append(f"{'hit wall clock':32}{left['hit_wall_clock']:>14}{right['hit_wall_clock']:>14}")
    reached = sorted(
        {p for side in (left, right)
         for p, n in (side.get("audit_tool_use_totals") or {}).items() if n}
    )
    mentioned = sorted(
        {p for side in (left, right) for p, n in (side.get("audit_totals") or {}).items() if n}
    )
    if reached:
        lines.append("")
        lines.append("Named inside a tool call — the agent reached for these: " + ", ".join(reached))
    if [p for p in mentioned if p not in reached]:
        lines.append("")
        lines.append("Mentioned in the stream but in no tool call (usually `ps` output): "
                     + ", ".join(p for p in mentioned if p not in reached))
    recorded = [
        f"{field}: {left.get(field)!r} vs {right.get(field)!r}"
        for field in NONCOMPARABLE_RECORDED_FIELDS
        if left.get(field) != right.get(field)
    ]
    if recorded:
        lines.append("")
        lines.append("Differs by construction, not a defect (the bare arm has no stage graph "
                     "and no reviewer): " + "; ".join(recorded))
    if mismatched:
        lines.append("")
        lines.append("THESE ARMS ARE NOT COMPARABLE. The manifests disagree on: "
                     + ", ".join(mismatched))
        lines.append("A difference between them is a difference between two configurations, "
                     "not a measurement of the scaffold.")
    if len(both) < 6:
        lines.append("")
        lines.append(f"{len(both)} paired task(s). Too few for the difference above to be "
                     "anything but a description of these runs.")
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "--" if value is None else f"{value:.4f}"


def merge_manifests(manifests: list[dict]) -> dict:
    """Combine per-task arm manifests -- one per slurm array task -- into one.

    An arm run as a job array is nineteen processes that never see each other, so each
    writes a manifest describing one task. Merging is not concatenation: the point of an
    arm manifest is that every run in it was the *same configuration*, and nineteen
    independently-submitted array tasks are exactly where that stops being true. So the
    shards are checked against each other on :data:`COMPARABLE_FIELDS` minus ``tasks``, and
    a disagreement is an error rather than a footnote -- there is no honest way to average
    across it.
    """
    if not manifests:
        raise ValueError("nothing to merge")
    arms = {m.get("arm") for m in manifests}
    if len(arms) != 1:
        raise ValueError(f"manifests span more than one arm: {sorted(arms)}")
    head = manifests[0]
    for field in COMPARABLE_FIELDS:
        if field == "tasks":
            continue
        values = {json.dumps(m.get(field), sort_keys=True) for m in manifests}
        if len(values) != 1:
            raise ValueError(
                f"shards disagree on {field!r}: {sorted(values)}. They are not one arm."
            )

    runs: list[dict] = []
    seen: set[str] = set()
    for manifest in manifests:
        for run in manifest.get("runs", []):
            if run["task"] in seen:
                raise ValueError(f"{run['task']} appears in more than one shard")
            seen.add(run["task"])
            runs.append(run)
    runs.sort(key=lambda run: run["task"])

    scored = [r for r in runs if r.get("normalized") is not None]
    patterns = sorted({p for m in manifests for p in (m.get("audit_patterns") or [])})
    merged = dict(head)
    merged.update({
        "tasks": [run["task"] for run in runs],
        "runs": runs,
        "shards": len(manifests),
        "valid_submissions": sum(1 for r in runs if r.get("submission_valid")),
        "hit_wall_clock": sum(1 for r in runs if r.get("hit_wall_clock")),
        "audit_patterns": patterns,
        "audit_totals": {p: sum((r.get("audit") or {}).get(p, 0) for r in runs) for p in patterns},
        "audit_tool_use_totals": {
            p: sum((r.get("audit_tool_use") or {}).get(p, 0) for r in runs) for p in patterns
        },
        "audit_logs_missing": sum(1 for r in runs if r.get("audit_log_missing")),
        "mean_normalized": (sum(r["normalized"] for r in scored) / len(scored)) if scored else None,
        "mean_normalized_over_all_tasks": (
            sum(r.get("normalized") or 0.0 for r in runs) / len(runs) if runs else None
        ),
    })
    return merged


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="airs_arm", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arm", choices=ARMS, help="Which arm to run.")
    parser.add_argument("--tasks", nargs="+", metavar="NAME", default=[])
    parser.add_argument("--root", metavar="PATH", help="Arm root; workspaces go under <root>/<arm>/<task>/.")
    parser.add_argument("--repo", default="airs-bench", metavar="PATH")
    parser.add_argument("--raw-dir", metavar="PATH")
    parser.add_argument("--task-python", default=sys.executable, metavar="BIN")
    parser.add_argument("--cli", default="claude", metavar="BIN", help="Agent CLI binary.")
    parser.add_argument("--model", default="opus")
    parser.add_argument("--review-model", default=None, help="AutoR arm only.")
    parser.add_argument("--wall-clock", type=int, default=10800, metavar="SECONDS",
                        help="Hard cap per task, applied identically to both arms. Defaults to 3h.")
    parser.add_argument("--stage-timeout", type=int, default=3600, metavar="SECONDS",
                        help="AutoR arm only: seconds per stage attempt.")
    parser.add_argument("--final-stage", default="06_analysis", help="AutoR arm only.")
    parser.add_argument("--rigor", default="standard", help="AutoR arm only.")
    parser.add_argument("--web-search", default="auto", choices=["auto", "native", "gemini", "off"])
    parser.add_argument("--environment-note", default="")
    parser.add_argument("--deny-tool", action="append", default=[], metavar="NAME",
                        help="Deny one more tool to both arms. Repeatable.")
    parser.add_argument("--audit-pattern", action="append", default=[], metavar="TEXT",
                        help="Extra string to count in each run's stream log after the fact. "
                             "The raw-data directory and the airs-bench checkout are audited "
                             "automatically, as are the hub download entry points.")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--merge", nargs="+", metavar="MANIFEST",
                        help="Merge per-task arm manifests -- one per slurm array task -- into "
                             "one arm manifest written to --merge-out, and exit.")
    parser.add_argument("--merge-out", metavar="PATH")
    parser.add_argument("--compare", nargs=2, metavar="MANIFEST",
                        help="Print a paired comparison of two arm manifests and exit.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.merge:
        shards = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.merge]
        merged = merge_manifests(shards)
        out = Path(args.merge_out) if args.merge_out else Path("arm_manifest.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        mean = merged["mean_normalized"]
        print(f"[{merged['arm']}] merged {merged['shards']} shard(s), "
              f"{len(merged['tasks'])} task(s), {merged['valid_submissions']} valid, "
              f"mean normalized over scored {mean if mean is None else round(mean, 4)} -> {out}")
        return 0
    if args.compare:
        left = json.loads(Path(args.compare[0]).read_text(encoding="utf-8"))
        right = json.loads(Path(args.compare[1]).read_text(encoding="utf-8"))
        print(compare(left, right))
        return 0

    missing = [name for name, value in
               (("--arm", args.arm), ("--root", args.root), ("--raw-dir", args.raw_dir)) if not value]
    if missing or not args.tasks:
        print("Required: --arm, --root, --raw-dir, --tasks" + (f" (missing {missing})" if missing else ""),
              file=sys.stderr)
        return 2

    tasks = [load_task(Path(args.repo), name) for name in args.tasks]
    root = Path(args.root).expanduser().resolve() / args.arm
    root.mkdir(parents=True, exist_ok=True)

    records: list[RunRecord] = []
    if args.concurrency > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = {pool.submit(run_one, task, args): task for task in tasks}
            for future in concurrent.futures.as_completed(futures):
                records.append(future.result())
        records.sort(key=lambda record: args.tasks.index(record.task))
    else:
        for task in tasks:
            records.append(run_one(task, args))

    manifest = arm_manifest(args, records)
    manifest_path = root / "arm_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n[{args.arm}] wrote {manifest_path}")
    print(f"[{args.arm}] valid submissions {manifest['valid_submissions']}/{len(records)}, "
          f"mean normalized over scored {manifest['mean_normalized']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
