#!/usr/bin/env python3
"""Run AutoR as a FIRE-Bench agent, under FIRE-Bench's clock, in one of two arms.

`FIRE-Bench <https://github.com/maitrix-org/FIRE-Bench>`_ hands an agent a research
question and a sandbox, expects it to design and run its own experiments, and scores the
conclusion it states -- by atomic claim, against the conclusion the paper's authors
wrote. :mod:`src.firebench` holds what was measured about the benchmark; this file is the
front end.

Plug it into the harness by dropping ``agents/autor/run.py`` into a FIRE-Bench checkout
(one is shipped in ``templates/firebench_agent_run.py``) and running::

    bash run_experiment.sh --agents autor --tasks cot_in_planning --models opus

or drive it directly, which is what a trial does::

    python3 fire_agent.py --bench-root ~/FIRE-Bench --task cot_in_planning \\
        --profile pipeline --model opus --deadline-seconds 3600

**Two arms, and the difference between them is the pipeline and nothing else.**

``--profile direct``
    One operator call. The backend CLI with its tools, given the goal, left to work. This
    is not "one API call": it can write code, run it and iterate, which is what
    FIRE-Bench's own ``agents/claude`` baseline is and therefore what a paired difference
    has to be measured against. Same model, same denied tools, same sandbox, same goal
    text, same deadline.

``--profile pipeline``
    AutoR's stage walk, Stage 02 through Stage 05, then one synthesis call. Everything
    the direct arm has, plus hypothesis generation, study design, implementation,
    experimentation, and a reviewer between each of them.

**Why the walk stops at Stage 05.** Two independent reasons, either of which alone would
be enough. Stage 06 is the first stage whose gate demands figures, and
``resolve_min_report_figures`` clamps the floor to at least one, so there is no
configuration in which an image-free benchmark clears it -- and FIRE-Bench scores no
images at all. And the harness kills the process at 3600 s: a measured
ResearchClawBench run of this same pipeline took 27,005 s. The analysis Stage 06 would
have done is one synthesis call here, which costs a call instead of a stage, a reviewer
and a figure.

**Why the walk starts at Stage 02, and browsing is denied by default.** Every FIRE-Bench
task is the rediscovery of a published finding whose paper is on the open web with its
conclusion in the abstract. Stage 01 is a literature survey. A run that does a literature
survey on this benchmark is running a search for the answer key, and the number it
produces is not a measurement of research ability. ``--web-search off`` is the default
here for the same reason, and ``_meta.json`` records the denial per seat so the claim is
checkable rather than asserted.

**What the exit code means.** Not "the pipeline said it finished". Six clauses over the
same dictionary that is written to ``_meta.json`` -- :data:`src.firebench.FIRE_EXIT_CLAUSES`
-- so any holder of the artifact can recompute the verdict. A conclusion has to exist, be
inside the length band, not be this adapter's own fallback, have reached the log file the
evaluator reads, carry no content refusal, and follow a procedure that ran to completion.

**The deadline is the design, not a flag.** :class:`src.firebench.Deadline` owns the
total; per-stage timeouts are slices of what is left, a reserve is held back that only
the publisher may spend, and a watcher thread republishes the scored line every time the
conclusion on disk improves. A run killed by the harness mid-stage is therefore scored on
the best conclusion it had actually written, rather than on nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.approval_agent import AutomatedReviewer  # noqa: E402
from src.cross_reviewer import resolve_cross_reviewer  # noqa: E402
from src.evolution import EvolutionConfig  # noqa: E402
from src.firebench import (  # noqa: E402
    CONCLUSION_FILENAME,
    DEFAULT_FINAL_STAGE,
    DEFAULT_FIRST_STAGE,
    FIRE_CONCLUSION_STAGE,
    ConclusionSynthesizer,
    Deadline,
    DirectConclusionWriter,
    FireRunResult,
    FireTask,
    append_log,
    available_tasks,
    bench_root_from,
    build_fire_goal,
    build_fire_meta,
    conclusion_content_refusals,
    conclusion_length_refusals,
    conclusion_path_for,
    ensure_fire_workspace,
    export_conclusion,
    mirror_run_artifacts,
    fire_runs_dir_for,
    fire_workspace_name,
    load_task,
    log_path_for,
    preview_task_inputs,
    open_log,
    publish_conclusion_line,
    stage_task_inputs,
    write_fire_meta,
)
from src.bench_call import read_transcript_witness, stages_approved_in  # noqa: E402
from src.manager import ResearchManager  # noqa: E402
from src.operator import ClaudeOperator  # noqa: E402
from src.operator_codex import CodexOperator  # noqa: E402
from src.rcb import emit_event  # noqa: E402
from src.stage_graph import StageGraph  # noqa: E402
from src.terminal_ui import TerminalUI  # noqa: E402
from src.utils import (  # noqa: E402
    DEFAULT_OUTPUT_FORMAT,
    STAGES,
    build_run_paths,
    create_run_root,
    ensure_run_layout,
    read_text,
    resolve_stage,
    resolve_output_format,
    write_text,
)
from src.web_search import disallowed_tools_for  # noqa: E402

#: The harness's own limit, from ``FIRE-Bench/run_agent.py``:
#: ``subprocess.run(cmd, env=env, timeout=3600)``. It is the default here rather than a
#: number this adapter chose: an adapter that assumed more time than the harness allows
#: would be tuned for a run that never happens.
DEFAULT_DEADLINE_SECONDS = 3600

#: Held back from the walk for the synthesis call and the publish. Measured against the
#: sibling benchmark's synthesis latencies (mean 120 s, max 290 s for a single answer
#: call) with room for one retry and the export.
DEFAULT_RESERVE_SECONDS = 480

#: How often the watcher looks for a better conclusion on disk. Twenty seconds is
#: negligible against a 3600 s budget and small against the window in which a SIGKILL
#: could land between the agent writing the file and the run publishing it.
WATCH_INTERVAL_SECONDS = 20

#: Backend defaults. ``opus`` rather than ``sonnet`` -- AutoR's own default -- because
#: ``sonnet`` is the alias that is quota-exhausted on the deployment this was built
#: against, and a benchmark front end whose default 429s is a front end nobody can run.
#: Probe before trusting it; the alias resolves through the CLI's own configuration.
DEFAULT_CLAUDE_MODEL = "opus"
DEFAULT_CODEX_MODEL = "default"


def default_model_for(backend: str) -> str:
    return DEFAULT_CODEX_MODEL if backend == "codex" else DEFAULT_CLAUDE_MODEL


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fire_agent",
        description="Run AutoR unattended against one FIRE-Bench task.",
    )
    parser.add_argument(
        "--bench-root",
        default=os.environ.get("FIREBENCH_ROOT", ""),
        metavar="PATH",
        help="FIRE-Bench checkout. Defaults to $FIREBENCH_ROOT.",
    )
    parser.add_argument(
        "--task",
        default=os.environ.get("TASK_ID", ""),
        help="Task id, e.g. cot_in_planning. Defaults to $TASK_ID, which is what the "
             "harness sets.",
    )
    parser.add_argument("--split", choices=["verified", "unverified"], default=None,
                        help="Which split to look in. Defaults to searching verified first.")
    parser.add_argument("--list-tasks", action="store_true", help="Print the task ids and exit.")
    parser.add_argument(
        "--profile",
        choices=["direct", "pipeline"],
        default="pipeline",
        help="direct: one agentic operator call (the control arm). "
             "pipeline: AutoR's stage walk plus one synthesis call. Defaults to pipeline.",
    )
    parser.add_argument(
        "--workspace",
        default="",
        metavar="PATH",
        help="Sandbox directory. Created if absent. Defaults to "
             "$FIREBENCH_RUNS_DIR/<task>__<profile>__<stamp>, and $FIREBENCH_RUNS_DIR "
             "defaults to ~/fire-bench-runs. **Deliberately outside the checkout**: the "
             "stock harness puts the sandbox in <checkout>/runs/, which leaves "
             "../../benchmark/papers/<task>/conclusion.txt two directories from an agent "
             "running with --dangerously-skip-permissions.",
    )
    parser.add_argument("--log-file", default="", metavar="PATH",
                        help="Where to write the log the evaluator scores. Defaults to "
                             "<bench-root>/log/<agent-id>/<model>/<task>/<stamp>/log.log.")
    parser.add_argument("--agent-id", default=os.environ.get("AGENT_ID", "autor"),
                        help="Agent id in the log path and the log header. Defaults to $AGENT_ID.")
    parser.add_argument("--model", default=os.environ.get("LLM_MODEL", "") or None,
                        help=f"Model for the execution backend. Defaults to $LLM_MODEL, then "
                             f"{DEFAULT_CLAUDE_MODEL}.")
    parser.add_argument("--review-model", default=None, help="Model for the reviewer. Defaults to --model.")
    parser.add_argument("--operator", choices=["claude", "codex"], default="claude")
    parser.add_argument("--review-operator", choices=["claude", "codex"], default=None)
    parser.add_argument("--codex-command", default="codex")
    parser.add_argument("--codex-sandbox", default="workspace-write")

    parser.add_argument("--deadline-seconds", type=int, default=DEFAULT_DEADLINE_SECONDS,
                        help=f"Total wall clock, matching the harness. Default {DEFAULT_DEADLINE_SECONDS}.")
    parser.add_argument("--reserve-seconds", type=int, default=DEFAULT_RESERVE_SECONDS,
                        help=f"Held back for synthesis and publishing. Default {DEFAULT_RESERVE_SECONDS}.")
    parser.add_argument("--first-stage", default=DEFAULT_FIRST_STAGE)
    parser.add_argument("--final-stage", default=DEFAULT_FINAL_STAGE)
    parser.add_argument("--max-attempts", type=int, default=2,
                        help="Attempts per stage. Small on purpose: AutoR's own default is "
                             "unbounded, and an unbounded retry inside a hard deadline spends "
                             "the whole budget on one stage and leaves no conclusion.")
    parser.add_argument("--max-operator-calls-per-stage", type=int, default=4)
    parser.add_argument("--max-auto-skips", type=int, default=1)
    parser.add_argument("--web-search", default="off",
                        choices=["auto", "gemini", "native", "off"],
                        help="Default off: the answer to every task in this benchmark is in the "
                             "abstract of a paper on the open web.")
    parser.add_argument("--cross-review", default="off", choices=["auto", "gemini", "off"],
                        help="Default off. A second model family in the loop is a second thing "
                             "changing between the arms.")
    parser.add_argument("--cross-review-model", default=None)
    parser.add_argument("--output-format", default=DEFAULT_OUTPUT_FORMAT)
    parser.add_argument("--attempt-index", type=int, default=0,
                        help="Which repeat of this (task, profile) pair this is. Recorded only.")
    parser.add_argument("--print-goal", action="store_true",
                        help="Print the goal contract and exit, leaving no workspace behind.")
    parser.add_argument("--fake-operator", action="store_true",
                        help="Exercise the plumbing without calling a backend. Never produces a "
                             "scoreable conclusion, by construction.")
    return parser.parse_args(list(argv) if argv is not None else None)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def create_operator(
    backend: str,
    *,
    model: str,
    codex_sandbox: str,
    codex_command: str,
    fake_mode: bool,
    ui: TerminalUI,
    stage_timeout: int,
    disallowed_tools: Sequence[str],
) -> Any:
    if backend == "codex":
        return CodexOperator(
            command=codex_command,
            model=model,
            sandbox=codex_sandbox,
            fake_mode=fake_mode,
            ui=ui,
            stage_timeout=stage_timeout,
        )
    return ClaudeOperator(
        model=model,
        fake_mode=fake_mode,
        ui=ui,
        stage_timeout=stage_timeout,
        web_search_mcp=False,
        disallowed_tools=disallowed_tools,
    )


def operator_seats(operator: Any, manager: ResearchManager | None) -> dict[str, tuple[str, ...]]:
    """What each seat is actually carrying, read off the objects that were built.

    Read back rather than copied from the request because a backend without the knob
    (``CodexOperator`` has no ``disallowed_tools``) applies nothing, and a record that
    carried only the request would claim a denial that never happened.
    """
    seats: dict[str, tuple[str, ...]] = {
        "executor": tuple(getattr(operator, "disallowed_tools", ()) or ())
    }
    reviewer = getattr(manager, "reviewer", None) if manager is not None else None
    if reviewer is not None:
        seats["reviewer"] = tuple(getattr(reviewer, "disallowed_tools", ()) or ())
    return seats


def tools_denied_on_every_seat(seats: Mapping[str, Sequence[str]]) -> tuple[str, ...]:
    if not seats:
        return ()
    common: set[str] | None = None
    order: list[str] = []
    for tools in seats.values():
        for name in tools:
            if name not in order:
                order.append(name)
        common = set(tools) if common is None else (common & set(tools))
    return tuple(name for name in order if common and name in common)


def build_manager(
    args: argparse.Namespace,
    *,
    workspace: Path,
    operator: Any,
    ui: TerminalUI,
    review_backend: str,
    review_model: str,
    disallowed_tools: Sequence[str],
) -> ResearchManager:
    """The smallest manager that can still run an experiment.

    Everything that would be a second thing changing between the arms is off: one round,
    a linear stage graph with routing disabled, no evolution, no archive, no cross
    reviewer. What is left on is the thing being measured -- the stages and the reviewer
    between them.
    """
    reviewer = AutomatedReviewer(
        review_backend,
        codex_command=args.codex_command,
        model=review_model,
        fake_mode=args.fake_operator,
        ui=ui,
        stage_timeout=operator.stage_timeout,
        unattended=True,
        disallowed_tools=disallowed_tools,
    )
    return ResearchManager(
        project_root=REPO_ROOT,
        runs_dir=fire_runs_dir_for(workspace),
        operator=operator,
        ui=ui,
        reviewer=reviewer,
        approval_mode="agent",
        review_operator=review_backend,
        review_model=review_model,
        unattended=True,
        max_auto_skips=args.max_auto_skips,
        max_rounds=1,
        max_stage_attempts=args.max_attempts,
        max_operator_calls_per_stage=args.max_operator_calls_per_stage,
        web_search_context=None,
        web_search_mode=args.web_search,
        # The sandbox, not the run tree. Three gates resolve "Files Produced" against
        # this; without it a run that correctly wrote its results into the sandbox is
        # refused for having produced nothing.
        artifact_roots=[workspace],
        stage_graph=StageGraph.linear(),
        routing_mode="off",
        evolution=EvolutionConfig(rounds=0),
        archive=None,
        cross_reviewer=resolve_cross_reviewer(args.cross_review, args.cross_review_model),
    )


# ---------------------------------------------------------------------------
# The watcher
# ---------------------------------------------------------------------------


class ConclusionWatcher(threading.Thread):
    """Republish the scored line every time the conclusion on disk gets better.

    The harness sends SIGKILL at 3600 s and does not wait. Without this, a run that had
    written a perfectly good conclusion at minute 40 and was killed at minute 60 while
    polishing a figure is scored on nothing -- the publish happens at the end of
    :func:`run`, and the end of :func:`run` never arrived.

    It only ever *appends*, because the evaluator reads the last line: a later, better
    conclusion wins, and there is never a window in which the file has no result line.
    It publishes only text that passes the same refusals the exporter applies, so it
    cannot promote a half-written file or this adapter's own fallback.
    """

    def __init__(self, *, workspace: Path, log_file: Path, interval: float = WATCH_INTERVAL_SECONDS) -> None:
        super().__init__(name="fire-conclusion-watcher", daemon=True)
        self.workspace = workspace
        self.log_file = log_file
        self.interval = interval
        self._stop = threading.Event()
        self.published: list[str] = []
        self.lock = threading.Lock()

    def stop(self) -> None:
        self._stop.set()

    def publish_if_better(self) -> bool:
        target = conclusion_path_for(self.workspace)
        if not target.is_file():
            return False
        body = read_text(target).strip()
        if not body:
            return False
        with self.lock:
            if self.published and self.published[-1] == body:
                return False
            if conclusion_length_refusals(body) or conclusion_content_refusals(body):
                return False
            line = json.dumps({"result": body}, ensure_ascii=False)
            with self.log_file.open("a", encoding="utf-8") as handle:
                handle.write("\n" + line + "\n")
            self.published.append(body)
        emit_event({"type": "progress", "stage": "watcher", "message": "published interim conclusion",
                    "chars": len(body)})
        return True

    def run(self) -> None:  # noqa: D102 - threading.Thread
        while not self._stop.wait(self.interval):
            try:
                self.publish_if_better()
            except Exception:  # noqa: BLE001 - a watcher that crashes the run is worse than no watcher
                emit_event({"type": "error", "where": "watcher", "traceback": traceback.format_exc()})


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def _stamp() -> str:
    return time.strftime("%Y%m%d%H%M%S")


def _stages_between(first: str, final: str) -> list[str]:
    start = resolve_stage(first)
    end = resolve_stage(final)
    return [s.slug for s in STAGES if start.number <= s.number <= end.number]


def resolve_workspace(args: argparse.Namespace, task_id: str, stamp: str) -> Path:
    if args.workspace:
        return Path(args.workspace).expanduser().resolve()
    root = Path(os.environ.get("FIREBENCH_RUNS_DIR", "~/fire-bench-runs")).expanduser().resolve()
    return root / fire_workspace_name(task_id, args.profile, stamp=stamp)


def run(args: argparse.Namespace) -> FireRunResult:
    deadline = Deadline(total_seconds=args.deadline_seconds, reserve_seconds=args.reserve_seconds)
    stamp = _stamp()

    bench_root = bench_root_from(args.bench_root or Path.cwd())
    if args.list_tasks:
        for name in available_tasks(bench_root, args.split or "verified"):
            print(name)
        return FireRunResult(workspace=bench_root, meta={"status": "printed", "listed_tasks": True})
    if not args.task:
        raise SystemExit("No task. Pass --task or set TASK_ID.")
    task: FireTask = load_task(bench_root, args.task, args.split)

    workspace = resolve_workspace(args, task.task_id, stamp)
    operator_backend = args.operator
    model = args.model or default_model_for(operator_backend)
    review_backend = args.review_operator or operator_backend
    review_model = args.review_model or model

    if args.print_goal:
        staged = preview_task_inputs(task, utils_src=bench_root / "utils")
    else:
        ensure_fire_workspace(workspace)
        staged = stage_task_inputs(task, workspace, utils_src=bench_root / "utils")

    model_catalog = _probe_model_catalog(bench_root)
    goal = build_fire_goal(
        task,
        workspace,
        model_catalog=model_catalog,
        deadline_seconds=args.deadline_seconds,
        staged=staged,
    )
    if args.print_goal:
        print(goal)
        return FireRunResult(workspace=workspace, meta={"status": "printed", "printed_goal": True})

    log_file = (
        Path(args.log_file).expanduser().resolve()
        if args.log_file
        else log_path_for(
            bench_root,
            agent_id=args.agent_id,
            llm_model=model,
            task_id=task.task_id,
            timestamp=stamp,
        )
    )
    open_log(log_file, agent_id=args.agent_id, task_id=task.task_id, llm_model=model)

    ui = TerminalUI(output_stream=sys.stdout, interactive=False)
    emit_event(
        {
            "type": "system",
            "subtype": "init",
            "agent": "autor-firebench",
            "profile": args.profile,
            "task": task.task_id,
            "split": task.split,
            "model": model,
            "review_model": review_model,
            "workspace": str(workspace),
            "log_file": str(log_file),
            "deadline_seconds": args.deadline_seconds,
        }
    )

    disallowed_tools = tuple(disallowed_tools_for(args.web_search))
    pipeline = args.profile == "pipeline"
    stage_slugs = _stages_between(args.first_stage, args.final_stage) if pipeline else []
    # The direct arm is one call, so it gets the whole budget minus the reserve. The
    # pipeline arm slices what is left across the stages it still has to run; the
    # reviewer shares its stage's slice, which is why the slice is not the whole budget
    # divided by the stage count and then handed to both.
    stage_timeout = deadline.stage_slice(max(1, len(stage_slugs)))
    operator = create_operator(
        operator_backend,
        model=model,
        codex_sandbox=args.codex_sandbox,
        codex_command=args.codex_command,
        fake_mode=args.fake_operator,
        ui=ui,
        stage_timeout=int(deadline.remaining_before_reserve) if not pipeline else stage_timeout,
        disallowed_tools=disallowed_tools,
    )

    watcher = ConclusionWatcher(workspace=workspace, log_file=log_file)
    watcher.start()

    pipeline_completed = False
    auto_skipped: list[str] = []
    stages_approved: list[str] = []
    direct_conclusion: str | None = None
    deadline_hit = False
    manager: ResearchManager | None = None
    paths = None

    try:
        if pipeline:
            manager = build_manager(
                args,
                workspace=workspace,
                operator=operator,
                ui=ui,
                review_backend=review_backend,
                review_model=review_model,
                disallowed_tools=disallowed_tools,
            )
            pipeline_completed, deadline_hit = _run_walk_under_deadline(
                manager,
                goal=goal,
                args=args,
                deadline=deadline,
                operator=operator,
                stage_slugs=stage_slugs,
            )
            auto_skipped = list(manager.auto_skipped_stages)
            run_root = (
                manager.last_run_paths.run_root
                if manager.last_run_paths is not None
                else _latest_run_root(fire_runs_dir_for(workspace))
            )
            if run_root is not None:
                paths = build_run_paths(run_root)
                stages_approved = stages_approved_in(paths)
        else:
            paths = _fresh_run_tree(fire_runs_dir_for(workspace), goal)
            direct_conclusion = DirectConclusionWriter(operator)(
                paths=paths, workspace=workspace, goal=goal
            )
            pipeline_completed = direct_conclusion is not None or conclusion_path_for(workspace).is_file()
            deadline_hit = deadline.expired()
    except Exception:  # noqa: BLE001 - a crashed arm must still publish what it produced
        emit_event({"type": "error", "where": args.profile, "traceback": traceback.format_exc()})

    watcher.stop()
    # Before the synthesis call, not after: the prompt lists the run's result files, and
    # a pipeline arm writes them into the run tree rather than the sandbox.
    mirrored = mirror_run_artifacts(workspace, paths)

    conclusion = export_conclusion(
        workspace=workspace,
        paths=paths,
        direct_conclusion=direct_conclusion,
        stages_approved=stages_approved,
        synthesize=(ConclusionSynthesizer(operator) if pipeline and not args.fake_operator else None),
        question=task.instruction,
    )
    body = read_text(conclusion.path).strip() if conclusion.path.is_file() else ""
    published = publish_conclusion_line(log_file, conclusion, body=body)
    if not published and watcher.published:
        # The exporter refused, but the watcher had already published something the same
        # rules accepted earlier -- a conclusion the agent wrote and then overwrote with
        # something worse, most often a half-finished rewrite interrupted by the clock.
        # The line is already the last one in the log, so the run is scoreable on it; what
        # this does is stop `_meta.json` from saying it is not.
        published = True
        conclusion = conclusion.__class__(
            path=conclusion.path,
            source="watcher",
            chars=len(watcher.published[-1]),
            sha256=conclusion.sha256,
            refusals=conclusion.refusals,
        )
        body = watcher.published[-1]

    _append_trajectory(log_file, paths)

    meta = build_fire_meta(
        workspace=workspace,
        task=task,
        profile=args.profile,
        model=model,
        review_model=review_model,
        operator=operator_backend,
        conclusion=conclusion,
        conclusion_body=body,
        log_file=log_file,
        log_result_line_written=published,
        pipeline_completed=pipeline_completed,
        auto_skipped_stages=auto_skipped,
        stages_approved=stages_approved,
        disallowed_tools=tools_denied_on_every_seat(operator_seats(operator, manager)),
        disallowed_tools_by_seat=operator_seats(operator, manager),
        witness=read_transcript_witness(paths),
        run_id=paths.run_root.name if paths is not None else "",
        deadline=deadline,
        deadline_hit=deadline_hit,
        staged=staged,
        fake_operator=args.fake_operator,
        extra={
            "bench_root": str(bench_root),
            "stage_slugs": stage_slugs,
            "stage_timeout_seconds": stage_timeout if pipeline else None,
            "attempt_index": args.attempt_index,
            "watcher_publishes": len(watcher.published),
            "mirrored_artifacts": mirrored,
            "model_catalog": model_catalog,
        },
    )
    write_fire_meta(workspace, meta)
    return FireRunResult(workspace=workspace, meta=meta)


def _probe_model_catalog(bench_root: Path) -> dict[str, Any] | None:
    """Ask the benchmark's own helper what it can reach, without importing it.

    A subprocess rather than an import: ``utils/llm_inference.py`` pulls in ``openai``,
    ``anthropic`` and (in the shipped version) ``transformers`` at module scope, and the
    adapter has no business inheriting that -- or crashing when one of them is absent on
    a box where the *agent's* interpreter would have had it.
    """
    script = (
        "import json,sys;"
        "sys.path.insert(0, %r);"
        "from utils.llm_inference import available_models;"
        "print(json.dumps(available_models()))" % str(bench_root)
    )
    try:
        import subprocess

        out = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(bench_root),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if out.returncode == 0 and out.stdout.strip():
            return json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001 - the catalogue is advice, not a precondition
        pass
    return None


def _run_walk_under_deadline(
    manager: ResearchManager,
    *,
    goal: str,
    args: argparse.Namespace,
    deadline: Deadline,
    operator: Any,
    stage_slugs: Sequence[str],
) -> tuple[bool, bool]:
    """Run the stage walk in a worker thread and stop waiting when the budget is spent.

    The walk is not interruptible from outside -- ``ResearchManager.run`` is a
    straight-line call -- so the deadline is enforced by *not waiting for it*, and by the
    per-stage timeout the operator already honours (a ``threading.Timer`` that terminates
    then kills the subprocess). Leaving the thread running as a daemon rather than trying
    to kill it is deliberate: the process is about to exit anyway, and a half-killed stage
    writing into the run tree while the exporter reads it is worse than one that is
    ignored.
    """
    outcome: dict[str, Any] = {"completed": False}

    def _walk() -> None:
        try:
            outcome["completed"] = manager.run(
                goal,
                skip_intake=True,
                output_format=resolve_output_format(args.output_format),
                resources=None,
                start_stage=resolve_stage(args.first_stage),
                final_stage=resolve_stage(args.final_stage),
            )
        except Exception:  # noqa: BLE001 - recorded, then exported around
            emit_event({"type": "error", "where": "pipeline", "traceback": traceback.format_exc()})

    thread = threading.Thread(target=_walk, name="fire-stage-walk", daemon=True)
    thread.start()
    # Re-slice as stages complete: a stage that finished early hands its unspent seconds
    # to the ones after it, which is the difference between four stages that each fit and
    # four stages that collectively fit.
    while thread.is_alive():
        thread.join(timeout=min(30.0, max(1.0, deadline.remaining_before_reserve)))
        if not thread.is_alive():
            break
        if deadline.expired():
            emit_event(
                {
                    "type": "progress",
                    "stage": "deadline",
                    "message": "walk stopped at the reserve boundary",
                    **deadline.snapshot(),
                }
            )
            # The walk thread is a daemon and dies with the interpreter, but the backend
            # it is blocked on is a *subprocess* and does not. Left alone it keeps
            # streaming, keeps spending quota, and outlives the run that launched it.
            reap_backend_children()
            return bool(outcome["completed"]), True
        remaining = max(1, len(stage_slugs) - _stages_written(manager))
        operator.stage_timeout = deadline.stage_slice(remaining)
    return bool(outcome["completed"]), False


def _stages_written(manager: ResearchManager) -> int:
    """How many stages have actually produced a summary.

    Counted off disk rather than from ``auto_skipped_stages``, which was the first
    version of this line and is a different quantity: a walk in which nothing is skipped
    reports zero forever, so every stage after the first was handed the same slice as the
    first and the last one got whatever was left, which was nothing.

    ``.tmp.md`` is excluded -- it is the in-progress write, so counting it would give the
    running stage its own slice back mid-flight.
    """
    paths = getattr(manager, "last_run_paths", None)
    if paths is None or not paths.stages_dir.is_dir():
        return 0
    return len([p for p in paths.stages_dir.glob("*.md") if not p.name.endswith(".tmp.md")])


def reap_backend_children() -> None:
    """Terminate this process's own descendants before the interpreter exits.

    Only descendants of this pid, read out of ``/proc``, and only ever ``SIGTERM``
    followed by ``SIGKILL`` on the ones that ignore it. Deliberately not ``pkill -f
    claude``: another session's benchmark is running on this box at any given time, and a
    pattern kill would take a stranger's four-hour measurement with it.
    """
    import signal

    me = os.getpid()
    children: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text(encoding="utf-8").rsplit(")", 1)[-1].split()
            children[int(entry.name)] = int(fields[1])
        except (OSError, IndexError, ValueError):
            continue
    descendants: list[int] = []
    frontier = [me]
    while frontier:
        parent = frontier.pop()
        for pid, ppid in children.items():
            if ppid == parent and pid not in descendants and pid != me:
                descendants.append(pid)
                frontier.append(pid)
    for pid in descendants:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            continue
    if descendants:
        time.sleep(3)
        for pid in descendants:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                continue
    emit_event({"type": "progress", "stage": "reap", "terminated": len(descendants)})


def _fresh_run_tree(runs_dir: Path, goal: str):
    paths = build_run_paths(create_run_root(runs_dir))
    ensure_run_layout(paths)
    write_text(paths.user_input, goal)
    return paths


def _latest_run_root(runs_dir: Path) -> Path | None:
    if not runs_dir.exists():
        return None
    candidates = sorted(path for path in runs_dir.iterdir() if path.is_dir())
    return candidates[-1] if candidates else None


#: How much of the raw backend stream is copied into the scored log file. The evaluator
#: never reads it -- it takes the last line -- but FIRE-Bench's error-analysis pass does,
#: and a log with no trajectory in it cannot be error-analysed. Bounded because the
#: streams run to megabytes.
TRAJECTORY_TAIL_BYTES = 400_000


def _append_trajectory(log_file: Path, paths) -> None:
    """Copy the tail of the run's raw stream into the log, sanitised.

    Sanitised by :func:`src.firebench.sanitise_log_body`, which is the only thing standing
    between this and the evaluator scoring a slice of the trajectory instead of the
    conclusion: its extractor prefers an OpenHands ``final_thought=`` match, then a
    three-timestamp heuristic, and only then the last line.

    Appended *before* the result line is not possible -- the result line is written first
    by the publisher -- so this appends after it and then re-appends the result line, in
    that order. The last line of the file is always the conclusion.
    """
    if paths is None or not paths.logs_raw.is_file():
        return
    last_line = ""
    if log_file.is_file():
        lines = [line for line in log_file.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
        last_line = lines[-1] if lines else ""
    try:
        raw = paths.logs_raw.read_bytes()[-TRAJECTORY_TAIL_BYTES:].decode("utf-8", errors="replace")
    except OSError:
        return
    append_log(log_file, "\n--- AutoR trajectory (tail, sanitised) ---")
    append_log(log_file, raw)
    if last_line.startswith('{"result"'):
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write("\n" + last_line + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run(args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - the harness only sees the exit code
        emit_event({"type": "result", "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        traceback.print_exc(file=sys.stderr)
        return 1
    if result.meta.get("status") == "printed":
        return 0
    emit_event({"type": "result", **result.to_dict()})
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
