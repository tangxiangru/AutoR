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
import contextlib
import json
import signal
import sys
import time
import traceback
from pathlib import Path
from typing import Iterator, Sequence

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
from src.rigor import DEFAULT_LEVEL, LEVELS, feature_flags  # noqa: E402
from src.rigor import help_text as rigor_help_text  # noqa: E402
from src.rigor import resolve as resolve_rigor  # noqa: E402
from src.stage_graph import StageGraph  # noqa: E402
from src.utils import (  # noqa: E402
    DEFAULT_STAGE_GRAPH,
    STAGE_GRAPH_CHOICES,
    BENCHMARK_MIN_REPORT_FIGURES,
    DEFAULT_OUTPUT_FORMAT,
    MAX_STAGE_ATTEMPTS,
    DEFAULT_VENUE,
    OUTPUT_FORMAT_CLI_CHOICES,
    WEB_SEARCH_MODE_CHOICES,
    resolve_output_format,
    resolve_stage,
    resolve_venue_key,
)
from src.cross_reviewer import resolve_cross_reviewer
from src.web_search import (  # noqa: E402
    assess_search_readiness,
    disallowed_tools_for,
    resolve_web_search_context,
    web_search_notice,
)


#: The harness enforces no wall clock of its own — neither the UI runner nor the batch CLI
#: puts a timeout on the agent subprocess — so a stage is only ever cut short by this value.
#: Clipping it buys nothing back except a thinner report.
DEFAULT_STAGE_TIMEOUT = 14400
#: No limit, matching ``main.py``. The comment this replaces argued that eight is "more
#: retries than the interactive default" — and it was, until the interactive default became
#: *none*. The benchmark path kept the old ceiling, so the change that removed the budget
#: landed on the entry point nobody benchmarks and missed the one that produces every score.
#:
#: What that cost is measured. Of the six tasks where AutoR lost most heavily to bare Claude
#: Code, **all six auto-skipped two or three stages** after "bounded retries were exhausted",
#: and Stage 03 was skipped in five of the six. An exhausted stage is not a slow stage; it is
#: a stage that never happened, and the report is then written standing on nothing.
DEFAULT_MAX_ATTEMPTS = MAX_STAGE_ATTEMPTS
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
    parser.add_argument(
        "--stage-graph",
        choices=list(STAGE_GRAPH_CHOICES),
        default=DEFAULT_STAGE_GRAPH,
        help=(
            "How the run moves between stages, the same choice `main.py` offers. "
            f"Defaults to '{DEFAULT_STAGE_GRAPH}'. 'linear' restores the strict 01-through-08 "
            "sequence and is the control arm for the topology this system's stated "
            "contribution is: `docs/framework.md` §6.7 says the ablation is 'one flag and has "
            "still never been passed', and it could not be passed here, because this entry "
            "point did not have it. Every one of the 398 archived benchmark run configs reads "
            "`adaptive`, and none of them chose it."
        ),
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
        "--codex-command",
        default="codex",
        metavar="BIN",
        help="Executable to invoke as the Codex CLI. Defaults to `codex`. Point it at a "
             "wrapper to run the benchmark against a different endpoint or model without "
             "touching this machine's own codex configuration: the operator is an agent "
             "harness, so the binary is the only place a different backend can be selected.",
    )
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
        "--rigor",
        choices=list(LEVELS),
        default=DEFAULT_LEVEL,
        help=rigor_help_text(),
    )
    parser.add_argument(
        "--review-panel",
        action=argparse.BooleanOptionalAction,
        default=None,
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
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Run each stage as routine or deliberative rather than treating them alike. A "
             "routine stage gets a lean prompt, a single reviewer, and no escalation offer; a "
             "deliberative one gets everything configured. Each stage declares what the next "
             "needs, and a routine stage that keeps failing is promoted automatically.",
    )
    parser.add_argument(
        "--routine-model",
        metavar="MODEL",
        help="Model for stages running in the routine tier, so the strong model is kept for "
             "the few steps whose output the rest of the run inherits. Requires "
             "--effort-tiers; without it every stage is deliberative and this does nothing.",
    )
    parser.add_argument(
        "--deliberation",
        action=argparse.BooleanOptionalAction,
        default=None,
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
        action=argparse.BooleanOptionalAction,
        default=None,
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
             "stage with the previous attempt's validation errors attached. **Omitted, the "
             "default, means no limit**, the same as main.py: exhausting the budget does not "
             "stop the run, it skips the stage and writes a report standing on nothing.",
    )
    parser.add_argument(
        "--max-operator-calls-per-stage",
        type=int,
        default=6,
        help="Operator calls one stage may cost across every visit -- first attempt, "
             "reviewer-directed retries, polish rounds and repairs alike -- before the run "
             "settles for what it has. Unlike --max-attempts this does not reset when the "
             "stage is re-entered, and exhausting it promotes the stage rather than skipping "
             "it. Defaults to 6.",
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
        # Derived rather than restated. This list was written out by hand and had already
        # stopped agreeing with the one `main.py` offers and `normalize_web_search_mode`
        # stores, so a mode added to the constant reached one front end and not the other.
        choices=list(WEB_SEARCH_MODE_CHOICES),
        default="auto",
        help="Search provider for the operators. 'gemini' is required where the built-in "
             "WebSearch tool is disabled, such as Claude Code on Vertex AI. 'off' offers no "
             "search tool and denies WebSearch and WebFetch to the CLI. Defaults to auto.",
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
        "--min-report-figures",
        type=int,
        default=None,
        help=f"Distinct figures report/images/ must hold before Stage 07 can be approved. "
             f"Defaults to {BENCHMARK_MIN_REPORT_FIGURES}. Clamped to [1, MAX_REPORT_FIGURES]. "
             "The judge is shown a fixed set of the first MAX_REPORT_FIGURES images, and most "
             "runs stop well under it, so this is the knob for an arm that tests whether "
             "filling the window is worth anything.",
    )
    parser.add_argument(
        "--skills-dir",
        default=None,
        help="Directory to load the agent skill pack from, instead of <repo>/src/skills. "
             "For arms that measure a different pack: the pack becomes an argument the "
             "artifact records rather than an edit to a worktree nobody can pin.",
    )
    parser.add_argument(
        "--withhold-skills",
        default=None,
        help="Skills this run is denied whatever the field filter, the predicates or the pin "
             "table say. A comma-separated list of names, or @PATH to read one name per line "
             "(blank lines and # comments ignored). This is the control arm of any experiment "
             "about skills.",
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
    codex_command: str = "codex",
    codex_web_search: bool = False,
    disallowed_tools: Sequence[str] = (),
):
    if backend == "codex":
        return CodexOperator(
            model=model,
            codex_sandbox=codex_sandbox,
            fake_mode=fake_mode,
            ui=ui,
            stage_timeout=stage_timeout,
            command=codex_command,
            # `native` means "the operator's own search tool". For codex that tool is served
            # by the Responses API, so it works from inside the sandbox; AutoR's Gemini
            # helper is a local subprocess and does not.
            web_search=codex_web_search,
        )
    return ClaudeOperator(
        model=model,
        fake_mode=fake_mode,
        ui=ui,
        stage_timeout=stage_timeout,
        web_search_mcp=web_search_mcp,
        disallowed_tools=disallowed_tools,
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
    for flag, on in resolve_rigor(
        args.rigor, {flag: getattr(args, flag, None) for flag in feature_flags()}
    ).items():
        setattr(args, flag, on)
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

    # Not assessed under `off`: the assessment exists to say what a run that is going to
    # search can search with, and this one is not. Looking anyway would only produce a
    # sentence about a credential nothing was going to use.
    readiness = (
        None if args.web_search == "off"
        else assess_search_readiness(
            operator=operator_backend,
            codex_sandbox=args.codex_sandbox,
        )
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
        codex_command=args.codex_command,
        codex_web_search=args.web_search == "native",
        disallowed_tools=disallowed_tools_for(args.web_search),
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
            # The benchmark adapter is unattended by construction. `docs/review-panel.md`
            # documents `rcb_agent.py --review-panel`, which is the exact context the
            # unreadable-verdict fallback was found in.
            unattended=True,
        )
    else:
        reviewer = AutomatedReviewer(
            review_backend,
            codex_command=args.codex_command,
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
        max_operator_calls_per_stage=args.max_operator_calls_per_stage,
        web_search_context=web_search_context,
        web_search_mode=args.web_search,
        # Stages are told to keep code/, outputs/ and report/images/ up to date in the
        # benchmark workspace, so 'Files Produced' must resolve against it too. Three gates
        # now read what this becomes (`ResearchManager.artifact_dirs`), not just the
        # summary check: the Stage 03 machine-data gate, the Stage 06 check that every
        # planned figure's `source_artifact` exists, and the Stage 07 check that every
        # planned figure was published. Dropping this argument would not merely lose a
        # convenience — it would turn a compliant benchmark run, whose results and figures
        # live outside the run tree by contract, into three false refusals.
        artifact_roots=[workspace],
        # The benchmark's own instructions ask every agent for "data overview, main results,
        # and validation/comparison plots" -- three distinct questions -- and 27 of its 40
        # tasks carry two or more image criteria. A one-figure report clears AutoR's ordinary
        # gate while forfeiting criteria it never addressed.
        # Measured over 541 scored runs, with task and arm fixed effects, a published figure
        # is worth about +0.79 benchmark points -- and 423 of those runs published fewer than
        # the MAX_REPORT_FIGURES the judge is handed, median twelve. The slope is partly a
        # proxy for run quality (the image-criterion slope is +0.72 against +0.41 on text),
        # so it is an upper bound and not a promise. It is still the largest effect anyone
        # has measured here, which is why the floor is now an argument: an arm can raise it
        # and find out, and `run_config.json` records which arm did.
        min_report_figures=benchmark_figure_floor(args.min_report_figures),
        cross_reviewer=resolve_cross_reviewer(args.cross_review, args.cross_review_model),
        # `StageGraph.named` rather than `main.py`'s `resolve_graph`, which additionally
        # lets the cross-run archive pick a topology. A benchmark arm must be the
        # configuration it says it is: an archive that steered one run's topology and not
        # another's would put a variable in the comparison that no flag records.
        stage_graph=StageGraph.named(args.stage_graph),
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
        # `--routine-model` was declared here and read nowhere, so the one flag whose whole
        # job is to keep the strong model for the stages that need it did nothing on the
        # only path where tiering is unconditionally on. `main.configure_effort` has always
        # built the routine operator and recorded the model; this file parsed the flag and
        # dropped it, which is the two-front-ends divergence this repo keeps finding rather
        # than a missing feature.
        if args.routine_model:
            manager.routine_operator = create_operator(
                # The execution backend, not the reviewer's: this operator runs stages.
                operator_backend,
                model=args.routine_model,
                codex_sandbox=args.codex_sandbox,
                fake_mode=args.fake_operator,
                ui=ui,
                stage_timeout=args.stage_timeout,
                web_search_mcp=web_search_context is not None,
                codex_command=args.codex_command,
                codex_web_search=args.web_search == "native",
                disallowed_tools=disallowed_tools_for(args.web_search),
            )
            manager.concentration.routine_model = args.routine_model
        # `unattended=True` like every other reviewer this file builds. Without it the
        # routine-tier fallback is the one reviewer in an unattended run that still treats a
        # transport failure as grounds to abort, because attended is the constructor default
        # and this was the only construction that did not say otherwise.
        manager.solo_reviewer = (
            reviewer if isinstance(reviewer, AutomatedReviewer)
            else AutomatedReviewer(review_backend, codex_command=args.codex_command, model=review_model,
                                   fake_mode=args.fake_operator, ui=ui,
                                   stage_timeout=args.stage_timeout,
                                   unattended=True)
        )

    # ResearchClawBench task ids are `<Field>_<nnn>`, so the run's field is known before it
    # starts. Handing it to the manager narrows the field-specific skills to the one field
    # this study is in; without it every run is offered advice about nine fields it is not in.
    _task_id = infer_task_id(workspace) or ""
    manager.skill_discipline = _task_id.rsplit("_", 1)[0].casefold() if "_" in _task_id else None
    # The only place an identifier enters routing. Everything else AutoR routes on is
    # derived from the task statement; a pin is derived from a previous run's score, so
    # it needs the name of the task that produced it. `configs/task_skill_pins.json`.
    manager.skill_task_id = _task_id or None
    manager.skill_benchmark = "researchclawbench"
    # The pack itself, as an argument. Until this existed the only way to measure a
    # different pack was to delete files in a worktree, which is how the best-scoring arm
    # on the board came to exist as a dirty checkout with no SHA that nobody can re-run.
    if args.skills_dir:
        skills_dir = Path(args.skills_dir).expanduser()
        if not skills_dir.is_dir():
            raise SystemExit(f"--skills-dir: not a directory: {skills_dir}")
        manager.skills_dir = skills_dir
    manager.skill_withhold = read_withheld_skills(args.withhold_skills)

    pipeline_completed = False
    aborted_with = ""
    with _sigterm_as_exception():
        try:
            pipeline_completed = manager.run(
                goal,
                venue=resolve_venue_key(args.venue),
                skip_intake=not args.intake,
                output_format=output_format,
                resources=collect_reference_resources(workspace) or None,
                final_stage=resolve_stage(args.final_stage),
            )
        except Exception as exc:  # noqa: BLE001 - a crashed pipeline must still export what it produced
            # Exporting the salvage is right. Reporting the salvage as a finished run is
            # not, and that is what happened until this line existed: the exception was
            # recorded in `_agent_output.jsonl` and nowhere a downstream reader looks.
            aborted_with = f"{type(exc).__name__}: {exc}"[:500]
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
    result = BenchmarkResult(
        workspace=workspace,
        run_root=paths.run_root,
        pipeline_completed=pipeline_completed,
        export=export,
        auto_skipped_stages=list(manager.auto_skipped_stages),
        aborted_with=aborted_with,
    )
    # Written once, after the result exists, because the result is the only thing that
    # knows whether the walk finished -- and `status` is the field every downstream
    # reader gates on. `run_arm.py` skips a task whose meta says `completed`, and
    # `score_arm.py` scores one; both were being handed `completed` for a run that had
    # stopped at Stage 03 of 7.
    write_run_meta(
        workspace,
        task_id=infer_task_id(workspace),
        run_id=paths.run_root.name,
        status=result.status,
        duration_seconds=round(time.monotonic() - started_at),
        model=model,
        extra={
            "report_source": export.report_source,
            "pipeline_completed": pipeline_completed,
            "aborted_with": aborted_with,
        },
    )
    return result


class Terminated(Exception):
    """The scheduler asked this run to stop.

    Raised out of a ``SIGTERM`` handler so a kill takes the same path a crash already
    takes: export whatever the run produced, record ``aborted``, write ``_meta.json``.
    An ordinary :class:`Exception`, deliberately -- the point is to be caught by the
    handler that already exists around :meth:`Manager.run`.
    """


@contextlib.contextmanager
def _sigterm_as_exception() -> Iterator[None]:
    """Make a scheduler kill produce a verdict instead of silence.

    A run that is killed never writes a terminal status, so ``_meta.json`` keeps the
    ``running`` the harness wrote at launch -- forever, since nothing revisits it. Both
    readers gate on that field: ``run_arm.py`` will not resume the task and the scoring
    driver will not score it. The workspace is then indistinguishable from one still in
    flight, and the arm silently loses a task rather than reporting a failed one.

    It cost a real measurement. On the `full40_pins` arm, Earth_003 hit its 40 h wall
    during Stage 07 holding a finished 45 KB report and eleven figures. The scoring pass
    logged ``scoreable workspaces: 39`` and named nothing it had dropped; the arm was
    written up at n=39 for two days with the fortieth deliverable complete on disk.

    Slurm sends ``SIGTERM`` and waits ``KillWait`` (30 s by default) before ``SIGKILL``,
    which is enough to export a report that has already been written. If it is not, the
    export is partial and the status still says what happened -- both better than a
    workspace that claims to be running.

    Restores the previous handler on the way out, and does nothing at all off the main
    thread, where :func:`signal.signal` is not available.
    """
    def _raise(signum: int, _frame: object) -> None:
        raise Terminated(f"signal {signum} (SIGTERM); the scheduler ended this run")

    try:
        previous = signal.signal(signal.SIGTERM, _raise)
    except ValueError:  # not the main thread; nothing to install
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)




def benchmark_figure_floor(requested: int | None) -> int:
    """The figure floor a benchmark run gets, given what the caller asked for.

    Unasked, a benchmark run keeps :data:`BENCHMARK_MIN_REPORT_FIGURES` rather than AutoR's
    ordinary floor of one: the benchmark's own instructions ask every agent for "data
    overview, main results, and validation/comparison plots", and 27 of its 40 tasks carry
    two or more image criteria, so a one-figure report clears the ordinary gate while
    forfeiting criteria it never addressed.

    A caller may raise it. `resolve_min_report_figures` clamps the result into
    ``[1, MAX_REPORT_FIGURES]`` downstream, so a value past the window the judge sees cannot
    turn the gate into busywork.
    """
    return BENCHMARK_MIN_REPORT_FIGURES if requested is None else requested


def read_withheld_skills(spec: str | None) -> frozenset[str]:
    """The skills this run is denied, from a comma list or ``@file``.

    A file, because the useful ablation names forty-odd skills and a command line that long
    stops being readable in `_meta.json` -- which is where anyone later reconstructs what an
    arm actually ran. Blank lines and `#` comments are allowed so the file can say why.

    Unknown names are not an error here. `install_run_skills` applies the set by exclusion,
    so a name matching nothing withholds nothing, and the run config records the set that
    was asked for beside the pack digest that resulted -- which is the pair a reader needs
    to tell "withheld nothing" from "asked for nothing".
    """
    if not spec:
        return frozenset()
    text = spec.strip()
    if text.startswith("@"):
        try:
            raw = Path(text[1:]).expanduser().read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise SystemExit(f"--withhold-skills: cannot read {text[1:]}: {exc}") from exc
        names = [line.split("#", 1)[0].strip() for line in raw.splitlines()]
    else:
        names = [part.strip() for part in text.split(",")]
    return frozenset(n for n in names if n)


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
            "status": result.status,
            "pipeline_completed": result.pipeline_completed,
            "auto_skipped_stages": result.auto_skipped_stages,
            "run_root": str(result.run_root),
            **result.export.to_dict(),
        }
    )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
