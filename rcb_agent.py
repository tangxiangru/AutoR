#!/usr/bin/env python3
"""Run AutoR as an unattended ResearchClawBench agent.

Register it in ResearchClawBench's ``evaluation/agents.json``::

    "autor": {
      "label": "AutoR",
      "icon": "A",
      "logo": "/static/logos/autor.svg",
      "cmd": "python3 /abs/path/to/AutoR/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT>"
    }

The harness substitutes ``<WORKSPACE>`` with the absolute workspace path and ``<PROMPT>``
with the contents of the generated ``INSTRUCTIONS.md``. Both can also be omitted when
running by hand: the workspace defaults to the current directory and the instructions
default to ``<workspace>/INSTRUCTIONS.md``.

Nothing here ever reads stdin. Any prompt that would block raises
:class:`src.terminal_ui.UnattendedInputError` instead of hanging the benchmark.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.approval_agent import AutomatedReviewer  # noqa: E402
from src.review_panel import (
    DEFAULT_PANEL,
    ReviewPanel,
    apply_model_assignments,
    load_persona,
    resolve_roles,
)  # noqa: E402
from src.manager import ResearchManager  # noqa: E402
from src.operator import ClaudeOperator  # noqa: E402
from src.operator_codex import CodexOperator  # noqa: E402
from src.rcb import (  # noqa: E402
    BenchmarkResult,
    collect_reference_resources,
    infer_task_id,
    write_run_meta,
    ReportSynthesizer,
    build_benchmark_goal,
    build_run_paths_for_workspace,
    emit_event,
    ensure_workspace_layout,
    export_run,
    resolve_instructions,
    runs_dir_for,
)
from src.terminal_ui import TerminalUI  # noqa: E402
from src.deliberation import DEFAULT_MAX_DELIBERATIONS  # noqa: E402
from src.utils import (  # noqa: E402
    DEFAULT_OUTPUT_FORMAT,
    DEFAULT_VENUE,
    OUTPUT_FORMAT_CLI_CHOICES,
    resolve_output_format,
    resolve_stage,
    resolve_venue_key,
)
from src.cross_reviewer import resolve_cross_reviewer
from src.web_search import (  # noqa: E402
    assess_search_readiness,
    resolve_web_search_context,
    web_search_notice,
)


#: The harness enforces no wall clock of its own — neither the UI runner nor the batch CLI
#: puts a timeout on the agent subprocess — so a stage is only ever cut short by this value.
#: Clipping it buys nothing back except a thinner report.
DEFAULT_STAGE_TIMEOUT = 14400
#: More retries than the interactive default: every retry re-runs the stage with its
#: validation errors attached, and an exhausted stage is auto-skipped, which costs real score.
DEFAULT_MAX_ATTEMPTS = 8
#: The benchmark scores report/report.md, which Stage 07 writes. Everything after it is
#: wall-clock spent on artifacts the judge never opens.
DEFAULT_FINAL_STAGE = "07_writing"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rcb_agent",
        description="Run AutoR unattended against a ResearchClawBench workspace.",
    )
    parser.add_argument(
        "--workspace",
        default=".",
        metavar="PATH",
        help="Benchmark workspace directory. Defaults to the current working directory, "
             "which is what the harness sets it to.",
    )
    parser.add_argument(
        "--prompt",
        help="Benchmark instructions as a literal string. This is what <PROMPT> expands to.",
    )
    parser.add_argument(
        "--prompt-file",
        metavar="PATH",
        help="Read the benchmark instructions from a file. "
             "Defaults to <workspace>/INSTRUCTIONS.md when neither flag is given.",
    )
    parser.add_argument(
        "--operator",
        choices=["claude", "codex"],
        default="claude",
        help="Execution backend for the research stages. Defaults to claude.",
    )
    parser.add_argument("--model", help="Model for the execution backend. Defaults to the backend default.")
    parser.add_argument(
        "--review-operator",
        choices=["claude", "codex"],
        help="Backend for the reviewer agent that replaces the human approval gate. "
             "Defaults to the execution backend.",
    )
    parser.add_argument("--review-model", help="Model for the reviewer agent. Defaults to the backend default.")
    parser.add_argument(
        "--codex-sandbox",
        default="workspace-write",
        help="Codex CLI sandbox mode, used only with --operator codex.",
    )
    parser.add_argument(
        "--venue",
        default=DEFAULT_VENUE,
        help=f"Venue profile for Stage 07 writing. Defaults to {DEFAULT_VENUE}.",
    )
    parser.add_argument(
        "--output-format",
        choices=list(OUTPUT_FORMAT_CLI_CHOICES),
        default=DEFAULT_OUTPUT_FORMAT,
        help="Deliverable Stage 07 produces. 'markdown' writes report/report.md directly, which "
             "is the file the benchmark scores; 'latex' produces the paper package instead and "
             "leaves the report to the export step. "
             f"Defaults to {DEFAULT_OUTPUT_FORMAT}.",
    )
    parser.add_argument(
        "--final-stage",
        default=DEFAULT_FINAL_STAGE,
        metavar="STAGE",
        help="Stop after this stage. Defaults to "
             f"{DEFAULT_FINAL_STAGE}: the benchmark scores report/report.md, and Stage 08 "
             "(dissemination) only produces posters, slides and release notes that the judge "
             "never reads. Pass '08_dissemination' to run the full workflow.",
    )
    parser.add_argument(
        "--stage-timeout",
        type=int,
        default=DEFAULT_STAGE_TIMEOUT,
        help=f"Seconds allowed per stage attempt. Defaults to {DEFAULT_STAGE_TIMEOUT}. "
             "The benchmark harness imposes no timeout of its own, so this is the only thing "
             "that can cut a stage short.",
    )
    parser.add_argument(
        "--review-panel",
        action="store_true",
        help="Replace the single reviewer agent with a deliberating panel of role-differentiated "
             "reviewers ("
             + ", ".join(role.key for role in DEFAULT_PANEL)
             + "). They review independently, cross-examine, then a chair decides; a blocking "
             "objection cannot be approved over.",
    )
    parser.add_argument(
        "--panel-roles",
        nargs="+",
        metavar="ROLE",
        help="Seat only these panel roles, in this order. Defaults to all of them.",
    )
    parser.add_argument(
        "--panel-models",
        nargs="+",
        metavar="ROLE=MODEL",
        help="Assign a model per panel seat, as role=model or role=backend:model "
             "(for example: pi=opus skeptic=codex:default). Seats left unassigned use the "
             "reviewer default. Heterogeneity is the lever with the best evidence behind it: "
             "five prompts against one model are five correlated reads wearing five hats.",
    )
    parser.add_argument(
        "--effort-tiers",
        action="store_true",
        help="Run each stage as routine or deliberative rather than treating them alike. A "
             "routine stage gets a lean prompt, a single reviewer, and no escalation offer; a "
             "deliberative one gets everything configured. Each stage declares what the next "
             "needs, and a routine stage that keeps failing is promoted automatically.",
    )
    parser.add_argument(
        "--deliberation",
        action="store_true",
        help="Let a stage stop and pull in a panel when it hits a genuine crux. The agent "
             "names the question, finishes with its working answer, and a focused panel "
             "resolves it for the next pass. Most steps are execution; this is for the few "
             "that are not.",
    )
    parser.add_argument(
        "--max-deliberations",
        type=int,
        default=DEFAULT_MAX_DELIBERATIONS,
        help="Cruxes a run may escalate before the budget is refused. Scarcity is what makes "
             f"'think hard here' mean anything. Defaults to {DEFAULT_MAX_DELIBERATIONS}.",
    )
    parser.add_argument(
        "--deliberation-voices",
        nargs="+",
        metavar="VOICE",
        help="Seat only these voices: theorist, empiricist, critic, pragmatist.",
    )
    parser.add_argument(
        "--deliberation-models",
        nargs="+",
        metavar="VOICE=MODEL",
        help="Assign a model per voice, as voice=model or voice=backend:model.",
    )
    parser.add_argument(
        "--ideation-panel",
        action="store_true",
        help="Widen Stage 02's hypotheses with a panel of proposers working from distinct "
             "lenses (mechanism, contrarian, adjacent field, null/artifact, regime). They "
             "propose blind to each other; candidates are deduplicated, scored on novelty, "
             "feasibility and relevance, and handed to the stage as material to choose from. "
             "It decides nothing.",
    )
    parser.add_argument(
        "--ideation-lenses",
        nargs="+",
        metavar="LENS",
        help="Seat only these ideation lenses. Defaults to all five.",
    )
    parser.add_argument(
        "--ideation-models",
        nargs="+",
        metavar="LENS=MODEL",
        help="Assign a model per ideation lens, as lens=model or lens=backend:model.",
    )
    parser.add_argument(
        "--ideas-per-proposer",
        type=int,
        default=2,
        help="Candidate hypotheses each proposer may return. Defaults to 2.",
    )
    parser.add_argument(
        "--panel-rounds",
        type=int,
        default=2,
        help="Maximum deliberation rounds. Later rounds run only on disagreement. Defaults to 2.",
    )
    parser.add_argument(
        "--persona",
        metavar="PATH",
        help="Markdown description of the researcher the panel stands in for, injected into "
             "every panelist so the simulated humans hold one consistent bar.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=DEFAULT_MAX_ATTEMPTS,
        help="Attempts allowed per stage before it is auto-skipped. Each retry re-runs the "
             f"stage with the previous attempt's validation errors attached. Defaults to "
             f"{DEFAULT_MAX_ATTEMPTS}.",
    )
    parser.add_argument(
        "--max-auto-skips",
        type=int,
        default=3,
        help="How many stages may be auto-skipped after exhausting retries before aborting. Defaults to 3.",
    )
    parser.add_argument(
        "--intake",
        action="store_true",
        help="Run the intake stage. Off by default: the benchmark instructions are already "
             "a complete task specification, so intake only costs wall-clock time.",
    )
    parser.add_argument(
        "--cross-review",
        choices=["auto", "gemini", "off"],
        default="auto",
        help="Independent second opinion on each approval from a different model family. "
             "Can veto an approval, never override a refusal.",
    )
    parser.add_argument(
        "--cross-review-model",
        help="Model for the cross-model reviewer. Defaults to gemini-3.1-pro-preview.",
    )
    parser.add_argument(
        "--web-search",
        choices=["auto", "gemini", "native"],
        default="auto",
        help="Search provider for the operators. 'gemini' is required where the built-in "
             "WebSearch tool is disabled, such as Claude Code on Vertex AI.",
    )
    parser.add_argument(
        "--no-synthesis",
        action="store_true",
        help="Skip the operator-backed report synthesis pass and use only the deterministic "
             "fallback when the pipeline did not write report/report.md itself.",
    )
    parser.add_argument(
        "--fake-operator",
        action="store_true",
        help="Use the fake operator instead of a real backend. For smoke-testing the adapter.",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Skip the pipeline and only re-export the most recent run in the workspace into "
             "the benchmark deliverables. Useful after an interrupted run.",
    )
    return parser.parse_args(argv)


def default_model_for(backend: str) -> str:
    return "default" if backend == "codex" else "sonnet"


def create_operator(
    backend: str,
    *,
    model: str,
    codex_sandbox: str,
    fake_mode: bool,
    ui: TerminalUI,
    stage_timeout: int,
    web_search_mcp: bool = False,
):
    if backend == "codex":
        return CodexOperator(
            model=model,
            codex_sandbox=codex_sandbox,
            fake_mode=fake_mode,
            ui=ui,
            stage_timeout=stage_timeout,
        )
    return ClaudeOperator(
        model=model,
        fake_mode=fake_mode,
        ui=ui,
        stage_timeout=stage_timeout,
        web_search_mcp=web_search_mcp,
    )


def _recorded_duration(workspace: Path, started_at: float) -> int:
    """Keep a duration already on record rather than overwriting it with the export's.

    A recovered run took as long as the run did. Replacing that with the seconds this
    export took would report a multi-hour run as a ten-second one, and the leaderboard
    derives cost from duration.
    """
    meta_path = workspace / "_meta.json"
    if meta_path.exists():
        try:
            existing = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
        if isinstance(existing, dict) and existing.get("duration_seconds"):
            return int(existing["duration_seconds"])

    # A run killed by a signal never recorded its own duration, so fall back to how
    # long the run tree was being written for. Reporting this export's few seconds
    # instead would put a multi-hour run on the leaderboard at zero cost, since cost
    # per task is derived from duration.
    measured = _run_tree_duration(workspace)
    if measured is not None:
        return measured
    return round(time.monotonic() - started_at)


def _run_tree_duration(workspace: Path) -> int | None:
    """Wall-clock span of the AutoR run tree, from oldest to newest file.

    An estimate, and deliberately a conservative one: it cannot see time spent before
    the first file was written or after the last. Better than zero, and never larger
    than the truth.
    """
    runs_root = runs_dir_for(workspace)
    if not runs_root.exists():
        return None
    stamps = [
        path.stat().st_mtime
        for path in runs_root.rglob("*")
        if path.is_file()
    ]
    if len(stamps) < 2:
        return None
    span = round(max(stamps) - min(stamps))
    return span if span > 0 else None


def run(args: argparse.Namespace) -> BenchmarkResult:
    started_at = time.monotonic()
    workspace = Path(args.workspace).expanduser().resolve()
    if not workspace.exists():
        raise FileNotFoundError(f"Benchmark workspace does not exist: {workspace}")
    ensure_workspace_layout(workspace)

    operator_backend = args.operator
    model = args.model or default_model_for(operator_backend)
    review_backend = args.review_operator or operator_backend
    review_model = args.review_model or default_model_for(review_backend)

    # stdout carries the harness's run log, so the UI must never try to read from stdin.
    ui = TerminalUI(interactive=False)
    emit_event(
        {
            "type": "system",
            "subtype": "init",
            "agent": "autor",
            "model": model,
            "review_model": review_model,
            "output_format": resolve_output_format(args.output_format),
            "workspace": str(workspace),
        }
    )

    readiness = assess_search_readiness(
        operator=operator_backend,
        codex_sandbox=args.codex_sandbox,
    )
    notice, level = web_search_notice(args.web_search, readiness=readiness)
    emit_event({"type": "progress", "stage": "web_search", "level": level, "message": notice})
    ui.show_status(notice, level=level)
    if args.web_search == "gemini" and readiness.hard_blocker:
        # The benchmark scores a report, and a keyless search tool produces one built on
        # citations the agent had to invent. Refuse the run instead of spending hours on it.
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
    )
    synthesizer = None if args.no_synthesis else ReportSynthesizer(operator)

    if args.export_only:
        paths = build_run_paths_for_workspace(workspace)
        if paths is None:
            raise FileNotFoundError(f"No AutoR run found under {runs_dir_for(workspace)}")
        export = export_run(
            paths=paths,
            workspace=workspace,
            pipeline_completed=False,
            synthesize=synthesizer,
        )
        # A recovered run needs the same record as a normal one, or the recovery is
        # only half a recovery: `evaluation.score` and the leaderboard importer both
        # refuse a workspace whose status is still "running". This is the path taken
        # after a run is killed rather than returning — exactly when the metadata was
        # never written — so leaving it out made --export-only unable to produce a
        # scoreable workspace, which is the only reason it exists.
        write_run_meta(
            workspace,
            task_id=infer_task_id(workspace),
            run_id=paths.run_root.name,
            status="completed" if export.report_path.exists() else "failed",
            duration_seconds=_recorded_duration(workspace, started_at),
            model=model,
            extra={"report_source": export.report_source, "recovered": True},
        )
        return BenchmarkResult(
            workspace=workspace,
            run_root=paths.run_root,
            pipeline_completed=False,
            export=export,
        )

    instructions = resolve_instructions(
        prompt=args.prompt,
        prompt_file=args.prompt_file,
        workspace=workspace,
    )
    output_format = resolve_output_format(args.output_format)
    goal = build_benchmark_goal(workspace, instructions, output_format=output_format)

    if args.review_panel:
        reviewer = ReviewPanel(
            apply_model_assignments(resolve_roles(args.panel_roles), args.panel_models),
            backend_name=review_backend,
            model=review_model,
            fake_mode=args.fake_operator,
            ui=ui,
            stage_timeout=args.stage_timeout,
            persona_text=load_persona(args.persona),
            deliberation_rounds=args.panel_rounds,
        )
    else:
        reviewer = AutomatedReviewer(
            review_backend,
            model=review_model,
            fake_mode=args.fake_operator,
            ui=ui,
            stage_timeout=args.stage_timeout,
            # The benchmark run has no human to interpret an unreadable verdict, and
            # aborting at Stage 01 forfeits the task outright.
            unattended=True,
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
        web_search_context=web_search_context,
        web_search_mode=args.web_search,
        # Stages are told to keep code/, outputs/ and report/images/ up to date in the
        # benchmark workspace, so 'Files Produced' must resolve against it too.
        artifact_roots=[workspace],
        cross_reviewer=resolve_cross_reviewer(args.cross_review, args.cross_review_model),
    )

    if args.ideation_panel:
        from src.ideation_panel import IdeationPanel, apply_lens_models, resolve_lenses

        manager.ideation_panel = IdeationPanel(
            apply_lens_models(resolve_lenses(args.ideation_lenses), args.ideation_models),
            backend_name=review_backend,
            model=review_model,
            fake_mode=args.fake_operator,
            ui=ui,
            stage_timeout=args.stage_timeout,
            ideas_per_proposer=args.ideas_per_proposer,
        )

    if args.deliberation:
        from src.deliberation import CruxPanel, apply_voice_models, resolve_voices

        manager.crux_panel = CruxPanel(
            apply_voice_models(resolve_voices(args.deliberation_voices), args.deliberation_models),
            backend_name=review_backend,
            model=review_model,
            fake_mode=args.fake_operator,
            ui=ui,
            stage_timeout=args.stage_timeout,
            max_deliberations=args.max_deliberations,
        )

    if args.effort_tiers:
        from src.effort import EffortPlan

        manager.effort_plan = EffortPlan(enabled=True)
        manager.solo_reviewer = (
            reviewer if isinstance(reviewer, AutomatedReviewer)
            else AutomatedReviewer(review_backend, model=review_model,
                                   fake_mode=args.fake_operator, ui=ui,
                                   stage_timeout=args.stage_timeout)
        )

    pipeline_completed = False
    try:
        pipeline_completed = manager.run(
            goal,
            venue=resolve_venue_key(args.venue),
            skip_intake=not args.intake,
            output_format=output_format,
            resources=collect_reference_resources(workspace) or None,
            final_stage=resolve_stage(args.final_stage),
        )
    except Exception:  # noqa: BLE001 - a crashed pipeline must still export what it produced
        emit_event({"type": "error", "where": "pipeline", "traceback": traceback.format_exc()})

    paths = build_run_paths_for_workspace(workspace)
    if paths is None:
        raise RuntimeError(
            f"AutoR produced no run directory under {runs_dir_for(workspace)}; nothing to export."
        )

    emit_event(
        {
            "type": "progress",
            "stage": "export",
            "pipeline_completed": pipeline_completed,
            "auto_skipped_stages": manager.auto_skipped_stages,
        }
    )
    export = export_run(
        paths=paths,
        workspace=workspace,
        pipeline_completed=pipeline_completed,
        auto_skipped_stages=manager.auto_skipped_stages,
        synthesize=synthesizer,
    )
    write_run_meta(
        workspace,
        task_id=infer_task_id(workspace),
        run_id=paths.run_root.name,
        # The harness scores the report, so a report is what "completed" means here.
        status="completed" if export.report_path.exists() else "failed",
        duration_seconds=round(time.monotonic() - started_at),
        model=model,
        extra={"report_source": export.report_source, "pipeline_completed": pipeline_completed},
    )
    return BenchmarkResult(
        workspace=workspace,
        run_root=paths.run_root,
        pipeline_completed=pipeline_completed,
        export=export,
        auto_skipped_stages=list(manager.auto_skipped_stages),
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run(args)
    except Exception as exc:  # noqa: BLE001 - the harness only sees stdout and the exit code
        emit_event({"type": "result", "status": "failed", "error": str(exc)})
        print(traceback.format_exc(), file=sys.stderr)
        return 1

    emit_event(
        {
            "type": "result",
            "status": "completed" if result.exit_code == 0 else "failed",
            "pipeline_completed": result.pipeline_completed,
            "auto_skipped_stages": result.auto_skipped_stages,
            "run_root": str(result.run_root),
            **result.export.to_dict(),
        }
    )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
