#!/usr/bin/env python3
"""Run AutoR as an unattended AIRS-Bench agent.

::

    python airs_agent.py --repo ~/airs-bench --raw-dir /data/airs-raw \\
        --task TextualSimilaritySickSpearmanCorrelation \\
        --workspace /runs/sick_autor --task-python /path/to/venv/bin/python

The workspace is prepared with the task's own ``prepare.py`` if it has not been already,
the stage graph is walked with no human in the loop, and ``submission.csv`` is exported and
scored with the benchmark's own evaluator.

Three things separate this from ``rcb_agent.py``, and all three come from what the
benchmark measures:

**The deliverable is a file of predictions, not a report.** ResearchClawBench scores
``report/report.md`` with a model judge, which is why that adapter has four report sources
and a synthesis call. There is no equivalent here and there must not be: a submission is
either the model's predictions or it is nothing, and a fallback that wrote a plausible one
would turn a run that failed into a run that scored. :func:`src.airsbench.export_submission`
copies and checks; it never writes.

**The walk stops at Stage 06.** Stage 07 writes a report the benchmark never opens and
Stage 08 packages it. Both are real AutoR stages and both are wall-clock spent on nothing
the score can see, so ``--final-stage`` defaults to ``06_analysis``. Pass
``--final-stage 07_writing`` to run the writing stage anyway — a run whose report you want
to read is a legitimate thing to want, it is just not what is being measured.

**Scoring is deterministic, so it runs by default.** ``score_rcb_run.py`` is a separate
step because a judged score costs money and varies between draws. Here it is ``scipy`` over
a CSV: same input, same number, every time. ``--no-score`` turns it off.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Reused rather than restated. `create_operator` is benchmark-agnostic plumbing over the
# two backends, and this repo's most repeated defect is a second front end that drifts
# from the first -- a flag added to one entry point and not the other. One definition.
from rcb_agent import create_operator, default_model_for  # noqa: E402
from src.airsbench import (  # noqa: E402
    BenchmarkResult,
    MetadataError,
    available_tasks,
    build_airs_goal,
    build_run_paths_for_workspace,
    collect_task_resources,
    emit_event,
    ensure_workspace_layout,
    export_submission,
    load_task,
    prepare_workspace,
    runs_dir_for,
    score_submission,
    write_run_meta,
    write_task_card,
)
from src.approval_agent import AutomatedReviewer  # noqa: E402
from src.cross_reviewer import resolve_cross_reviewer  # noqa: E402
from src.deliberation import DEFAULT_MAX_DELIBERATIONS  # noqa: E402
from src.manager import ResearchManager  # noqa: E402
from src.review_panel import (  # noqa: E402
    DEFAULT_PANEL,
    ReviewPanel,
    apply_model_assignments,
    load_persona,
    resolve_roles,
)
from src.rigor import DEFAULT_LEVEL, LEVELS, feature_flags  # noqa: E402
from src.rigor import help_text as rigor_help_text  # noqa: E402
from src.rigor import resolve as resolve_rigor  # noqa: E402
from src.terminal_ui import TerminalUI  # noqa: E402
from src.utils import (  # noqa: E402
    DEFAULT_VENUE,
    MAX_STAGE_ATTEMPTS,
    WEB_SEARCH_MODE_CHOICES,
    resolve_stage,
    resolve_venue_key,
)
from src.web_search import (  # noqa: E402
    assess_search_readiness,
    disallowed_tools_for,
    resolve_web_search_context,
    web_search_notice,
)


#: Seconds per stage attempt. Higher than an ordinary AutoR run and lower than the
#: ResearchClawBench adapter's four hours: an AIRS task's expensive stage is model
#: training, which is bounded by the data rather than by how long an agent will keep
#: reading. Two hours fits a fine-tune of a small encoder on any of the twenty datasets on
#: one H100 and still leaves a run that goes wrong recoverable inside a working day.
DEFAULT_STAGE_TIMEOUT = 7200

#: No limit, matching ``main.py`` and ``rcb_agent.py``. An exhausted stage is not a slow
#: stage; it is a stage that never happened.
DEFAULT_MAX_ATTEMPTS = MAX_STAGE_ATTEMPTS

#: The benchmark scores ``submission.csv``, which Stage 05 produces and Stage 06 can still
#: improve. Everything after that is wall-clock spent on artifacts nothing reads.
DEFAULT_FINAL_STAGE = "06_analysis"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="airs_agent",
        description="Run AutoR unattended against one AIRS-Bench task.",
    )
    parser.add_argument("--repo", default="airs-bench", metavar="PATH",
                        help="Path to an airs-bench checkout.")
    parser.add_argument("--task", required=True, metavar="NAME",
                        help="Task name, as under airsbench/tasks/rad/.")
    parser.add_argument("--raw-dir", required=True, metavar="PATH",
                        help="Shared raw-data directory the task's prepare.py reads from. "
                             "Populate it with tools/airs_setup.py --download-only.")
    parser.add_argument("--workspace", default=".", metavar="PATH",
                        help="Task workspace. Prepared if it is not already.")
    parser.add_argument("--task-python", default=sys.executable, metavar="BIN",
                        help="Interpreter for the benchmark's own scripts and the one the agent "
                             "is told to run its code with. It needs the task's "
                             "container_python_requirements installed.")
    parser.add_argument("--environment-note", default="", metavar="TEXT",
                        help="One extra line about this machine for the goal's environment "
                             "block, for example a shared-GPU or wall-clock convention.")

    parser.add_argument("--operator", choices=["claude", "codex"], default="claude",
                        help="Execution backend for the research stages. Defaults to claude.")
    parser.add_argument("--model", help="Model for the execution backend.")
    parser.add_argument("--review-operator", choices=["claude", "codex"],
                        help="Backend for the reviewer agent. Defaults to the execution backend.")
    parser.add_argument("--review-model", help="Model for the reviewer agent.")
    parser.add_argument("--codex-command", default="codex", metavar="BIN",
                        help="Executable to invoke as the Codex CLI.")
    parser.add_argument("--codex-sandbox", default="workspace-write",
                        help="Codex CLI sandbox mode, used only with --operator codex.")

    parser.add_argument("--venue", default=DEFAULT_VENUE,
                        help=f"Venue profile, used only if the run reaches Stage 07. "
                             f"Defaults to {DEFAULT_VENUE}.")
    parser.add_argument("--final-stage", default=DEFAULT_FINAL_STAGE, metavar="STAGE",
                        help=f"Stop after this stage. Defaults to {DEFAULT_FINAL_STAGE}: the "
                             "benchmark scores submission.csv, and Stages 07-08 write a report "
                             "and package it, neither of which it reads.")
    parser.add_argument("--stage-timeout", type=int, default=DEFAULT_STAGE_TIMEOUT,
                        help=f"Seconds allowed per stage attempt. Defaults to {DEFAULT_STAGE_TIMEOUT}.")
    parser.add_argument("--rigor", choices=list(LEVELS), default=DEFAULT_LEVEL, help=rigor_help_text())

    parser.add_argument("--review-panel", action=argparse.BooleanOptionalAction, default=None,
                        help="Replace the single reviewer agent with a deliberating panel ("
                             + ", ".join(role.key for role in DEFAULT_PANEL) + ").")
    parser.add_argument("--panel-roles", nargs="+", metavar="ROLE")
    parser.add_argument("--panel-models", nargs="+", metavar="ROLE=MODEL")
    parser.add_argument("--panel-rounds", type=int, default=2)
    parser.add_argument("--persona", metavar="PATH")
    parser.add_argument("--effort-tiers", action=argparse.BooleanOptionalAction, default=None,
                        help="Run each stage as routine or deliberative rather than treating "
                             "them alike.")
    parser.add_argument("--routine-model", metavar="MODEL",
                        help="Model for stages in the routine tier. Requires --effort-tiers.")
    parser.add_argument("--deliberation", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--max-deliberations", type=int, default=DEFAULT_MAX_DELIBERATIONS)
    parser.add_argument("--deliberation-voices", nargs="+", metavar="VOICE")
    parser.add_argument("--deliberation-models", nargs="+", metavar="VOICE=MODEL")
    parser.add_argument("--ideation-panel", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--ideation-lenses", nargs="+", metavar="LENS")
    parser.add_argument("--ideation-models", nargs="+", metavar="LENS=MODEL")
    parser.add_argument("--ideas-per-proposer", type=int, default=2)

    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--max-operator-calls-per-stage", type=int, default=6)
    parser.add_argument("--max-auto-skips", type=int, default=3)
    parser.add_argument("--intake", action="store_true",
                        help="Run the intake stage. Off by default: project_description.md is "
                             "already a complete task specification.")
    parser.add_argument("--cross-review", choices=["auto", "gemini", "off"], default="auto")
    parser.add_argument("--cross-review-model")
    parser.add_argument("--web-search", choices=list(WEB_SEARCH_MODE_CHOICES), default="auto",
                        help="Search provider for the operators. AIRS-Bench's own reference "
                             "agents run in a container with no network, so a run with search on "
                             "is a different configuration from theirs and should say so.")
    parser.add_argument("--deny-tool", action="append", default=[], metavar="NAME",
                        help="Deny one more tool to the execution backend, on top of whatever "
                             "--web-search denies. Needed because `--web-search off` only "
                             "removes the CLI's *built-in* WebSearch and WebFetch: an MCP "
                             "server configured on the machine still reaches the internet, and "
                             "AutoR does not pass --strict-mcp-config, so the operator inherits "
                             "it. An arm that means 'no search' has to name that server here. "
                             "Repeatable.")

    parser.add_argument("--score", action=argparse.BooleanOptionalAction, default=True,
                        help="Score the exported submission with the benchmark's own evaluator "
                             "when the run finishes. On by default: it is deterministic and "
                             "costs a few seconds.")
    parser.add_argument("--fake-operator", action="store_true",
                        help="Use the fake operator instead of a real backend, for smoke-testing "
                             "the adapter.")
    parser.add_argument("--export-only", action="store_true",
                        help="Skip the pipeline and only re-export and re-score the most recent "
                             "run in the workspace.")
    parser.add_argument("--list-tasks", action="store_true", help="List the shipped tasks and exit.")
    return parser.parse_args(argv)


def denied_tools(args: argparse.Namespace) -> list[str]:
    """Every tool the execution backend is denied: the search mode's list plus --deny-tool.

    One function so the three places this file builds an operator cannot disagree about it,
    and so the answer to "what could this run reach" is a single expression rather than
    three call sites that were edited on different days.
    """
    return list(dict.fromkeys([*disallowed_tools_for(args.web_search), *args.deny_tool]))


def _score_and_record(args: argparse.Namespace, task, workspace: Path) -> dict | None:
    """Score the workspace, and never let a scoring failure destroy a finished run."""
    if not args.score:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="airs-score-") as scratch:
            score = score_submission(
                task=task,
                raw_dir=Path(args.raw_dir),
                workspace=workspace,
                score_dir=Path(scratch) / "score",
                python=args.task_python,
            )
    except Exception as exc:  # noqa: BLE001 - the run happened whether or not scoring did
        emit_event({"type": "error", "where": "score", "error": f"{type(exc).__name__}: {exc}"})
        return {"error": f"{type(exc).__name__}: {exc}"}
    payload = score.to_dict()
    (workspace / "score.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    emit_event({"type": "score", **{k: payload[k] for k in
                                    ("task", "metric", "value", "normalized", "valid_submission", "reason")}})
    return payload


def run(args: argparse.Namespace) -> BenchmarkResult:
    for flag, on in resolve_rigor(
        args.rigor, {flag: getattr(args, flag, None) for flag in feature_flags()}
    ).items():
        setattr(args, flag, on)

    started_at = time.monotonic()
    task = load_task(Path(args.repo), args.task)
    workspace = Path(args.workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    ensure_workspace_layout(workspace)

    operator_backend = args.operator
    model = args.model or default_model_for(operator_backend)
    review_backend = args.review_operator or operator_backend
    review_model = args.review_model or default_model_for(review_backend)

    ui = TerminalUI(interactive=False)
    emit_event({
        "type": "system", "subtype": "init", "agent": "autor", "benchmark": "airs-bench",
        "task": task.name, "metric": task.metric, "model": model, "review_model": review_model,
        "workspace": str(workspace), "final_stage": args.final_stage,
    })

    if not args.export_only:
        prepared = prepare_workspace(
            task=task, raw_dir=Path(args.raw_dir), workspace=workspace, python=args.task_python
        )
        write_task_card(workspace, task)
        emit_event({"type": "progress", "stage": "prepare",
                    "already_staged": prepared is None,
                    "splits": sorted(p.name for p in (workspace / "data").iterdir())})

    readiness = (
        None if args.web_search == "off"
        else assess_search_readiness(operator=operator_backend, codex_sandbox=args.codex_sandbox)
    )
    notice, level = web_search_notice(args.web_search, readiness=readiness)
    emit_event({"type": "progress", "stage": "web_search", "level": level, "message": notice})
    ui.show_status(notice, level=level)
    if args.web_search == "gemini" and readiness.hard_blocker:
        raise ValueError(
            f"--web-search gemini cannot work here: {readiness.hard_blocker} "
            "Fix it, or use --web-search auto to fall back to native search."
        )
    web_search_context = resolve_web_search_context(args.web_search, readiness=readiness)

    operator = create_operator(
        operator_backend,
        model=model,
        codex_sandbox=args.codex_sandbox,
        fake_mode=args.fake_operator,
        ui=ui,
        stage_timeout=args.stage_timeout,
        web_search_mcp=web_search_context is not None,
        codex_command=args.codex_command,
        codex_web_search=args.web_search == "native",
        disallowed_tools=denied_tools(args),
    )

    if args.export_only:
        paths = build_run_paths_for_workspace(workspace)
        if paths is None:
            raise FileNotFoundError(f"No AutoR run found under {runs_dir_for(workspace)}")
        export = export_submission(paths=paths, workspace=workspace, task=task)
        result = BenchmarkResult(workspace=workspace, run_root=paths.run_root, task=task.name,
                                 pipeline_completed=False, export=export)
        write_run_meta(workspace, task_id=task.name, run_id=paths.run_root.name,
                       status=result.status, duration_seconds=round(time.monotonic() - started_at),
                       model=model, extra={"recovered": True, "submission_source": export.source})
        _score_and_record(args, task, workspace)
        return result

    goal = build_airs_goal(
        task=task, workspace=workspace, python=args.task_python,
        environment_notes=args.environment_note,
    )

    if args.review_panel:
        reviewer = ReviewPanel(
            apply_model_assignments(resolve_roles(args.panel_roles), args.panel_models),
            backend_name=review_backend, model=review_model, fake_mode=args.fake_operator,
            ui=ui, stage_timeout=args.stage_timeout, persona_text=load_persona(args.persona),
            deliberation_rounds=args.panel_rounds, unattended=True,
        )
    else:
        reviewer = AutomatedReviewer(
            review_backend, codex_command=args.codex_command, model=review_model,
            fake_mode=args.fake_operator, ui=ui, stage_timeout=args.stage_timeout, unattended=True,
        )

    manager = ResearchManager(
        project_root=REPO_ROOT,
        runs_dir=runs_dir_for(workspace),
        operator=operator,
        ui=ui,
        reviewer=reviewer,
        approval_mode="agent",
        review_operator=review_backend,
        review_model=review_model,
        unattended=True,
        max_auto_skips=args.max_auto_skips,
        max_stage_attempts=args.max_attempts,
        max_operator_calls_per_stage=args.max_operator_calls_per_stage,
        web_search_context=web_search_context,
        web_search_mode=args.web_search,
        # Stages write their model code and their predictions into the benchmark workspace,
        # so 'Files Produced' and the Stage 03 machine-data gate have to resolve against it
        # as well as against the run tree. Same argument as the ResearchClawBench adapter.
        artifact_roots=[workspace],
        cross_reviewer=resolve_cross_reviewer(args.cross_review, args.cross_review_model),
    )

    if args.ideation_panel:
        from src.ideation_panel import IdeationPanel, apply_lens_models, resolve_lenses

        manager.ideation_panel = IdeationPanel(
            apply_lens_models(resolve_lenses(args.ideation_lenses), args.ideation_models),
            backend_name=review_backend, model=review_model, fake_mode=args.fake_operator,
            ui=ui, stage_timeout=args.stage_timeout, ideas_per_proposer=args.ideas_per_proposer,
        )

    if args.deliberation:
        from src.deliberation import CruxPanel, apply_voice_models, resolve_voices

        manager.crux_panel = CruxPanel(
            apply_voice_models(resolve_voices(args.deliberation_voices), args.deliberation_models),
            backend_name=review_backend, model=review_model, fake_mode=args.fake_operator,
            ui=ui, stage_timeout=args.stage_timeout, max_deliberations=args.max_deliberations,
        )

    if args.effort_tiers:
        from src.effort import EffortPlan

        manager.effort_plan = EffortPlan(enabled=True)
        if args.routine_model:
            manager.routine_operator = create_operator(
                operator_backend, model=args.routine_model, codex_sandbox=args.codex_sandbox,
                fake_mode=args.fake_operator, ui=ui, stage_timeout=args.stage_timeout,
                web_search_mcp=web_search_context is not None, codex_command=args.codex_command,
                codex_web_search=args.web_search == "native",
                disallowed_tools=denied_tools(args),
            )
            manager.concentration.routine_model = args.routine_model
        manager.solo_reviewer = (
            reviewer if isinstance(reviewer, AutomatedReviewer)
            else AutomatedReviewer(review_backend, codex_command=args.codex_command,
                                   model=review_model, fake_mode=args.fake_operator, ui=ui,
                                   stage_timeout=args.stage_timeout, unattended=True)
        )

    # No field-specific skills. AutoR's eleven skill disciplines are ResearchClawBench's
    # fields -- astronomy, chemistry, materials, and so on -- and none of them is what an
    # AIRS-Bench task is about. Mapping "Text Extraction and Matching" onto one of them
    # would be a guess dressed as routing, and the general pack is offered either way.
    manager.skill_discipline = None
    # The pin seam stays wired even though no AIRS task is pinned today, so a pin derived
    # from a scored AIRS arm lands the same way an RCB one does, and announces itself in
    # the run config the same way.
    manager.skill_task_id = task.name

    pipeline_completed = False
    aborted_with = ""
    try:
        pipeline_completed = manager.run(
            goal,
            venue=resolve_venue_key(args.venue),
            skip_intake=not args.intake,
            resources=collect_task_resources(task, workspace) or None,
            final_stage=resolve_stage(args.final_stage),
        )
    except Exception as exc:  # noqa: BLE001 - a crashed pipeline must still export what it made
        aborted_with = f"{type(exc).__name__}: {exc}"[:500]
        emit_event({"type": "error", "where": "pipeline", "traceback": traceback.format_exc()})

    paths = build_run_paths_for_workspace(workspace)
    if paths is None:
        raise RuntimeError(
            f"AutoR produced no run directory under {runs_dir_for(workspace)}; nothing to export."
        )

    export = export_submission(paths=paths, workspace=workspace, task=task)
    emit_event({"type": "progress", "stage": "export", "pipeline_completed": pipeline_completed,
                "auto_skipped_stages": manager.auto_skipped_stages, **export.to_dict()})

    result = BenchmarkResult(
        workspace=workspace, run_root=paths.run_root, task=task.name,
        pipeline_completed=pipeline_completed, export=export,
        auto_skipped_stages=list(manager.auto_skipped_stages), aborted_with=aborted_with,
    )
    score = _score_and_record(args, task, workspace)
    write_run_meta(
        workspace, task_id=task.name, run_id=paths.run_root.name, status=result.status,
        duration_seconds=round(time.monotonic() - started_at), model=model,
        extra={
            "pipeline_completed": pipeline_completed,
            "aborted_with": aborted_with,
            "auto_skipped_stages": list(manager.auto_skipped_stages),
            "submission_source": export.source,
            "submission_valid": export.submission.valid,
            "metric_value": (score or {}).get("value"),
            "normalized_score": (score or {}).get("normalized"),
            "final_stage": args.final_stage,
            "web_search": args.web_search,
        },
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list_tasks:
        for name in available_tasks(Path(args.repo)):
            print(name)
        return 0
    try:
        result = run(args)
    except MetadataError as exc:
        emit_event({"type": "result", "status": "failed", "error": str(exc)})
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - only stdout and the exit code leave this process
        emit_event({"type": "result", "status": "failed", "error": str(exc)})
        print(traceback.format_exc(), file=sys.stderr)
        return 1

    emit_event({
        "type": "result",
        "status": result.status,
        "task": result.task,
        "pipeline_completed": result.pipeline_completed,
        "auto_skipped_stages": result.auto_skipped_stages,
        "run_root": str(result.run_root),
        **result.export.to_dict(),
    })
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
