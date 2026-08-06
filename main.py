from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.approval_agent import AutomatedReviewer
from src.review_panel import (
    DEFAULT_PANEL,
    ReviewPanel,
    apply_model_assignments,
    load_persona,
    resolve_roles,
)
from src.intake import ResourceEntry, classify_resource, collect_resource_paths_from_ui
from src.manager import ResearchManager
from src.operator import ClaudeOperator
from src.operator_codex import CodexOperator
from src.operator_protocol import OperatorProtocol
from src.terminal_ui import TerminalUI
from src.web_search import (
    assess_search_readiness,
    resolve_web_search_context,
    web_search_notice,
)
from src.utils import (
    CODEX_SANDBOX_CHOICES,
    DEFAULT_CODEX_SANDBOX,
    DEFAULT_OUTPUT_FORMAT,
    DEFAULT_VENUE,
    WEB_SEARCH_MODE_CHOICES,
    OUTPUT_FORMAT_CLI_CHOICES,
    MAX_STAGE_ATTEMPTS,
    STAGES,
    build_run_paths,
    load_run_config,
    normalize_web_search_mode,
    resolve_output_format,
    resolve_stage,
    resolve_venue_key,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AutoR research workflow runner")
    parser.add_argument(
        "--goal",
        help="Research goal. If omitted, the goal is collected from terminal input.",
    )
    parser.add_argument(
        "--goal-file",
        metavar="PATH",
        help="Read the research goal from a file instead of --goal or terminal input. "
             "Useful for unattended runs whose goal is too long for a shell argument.",
    )
    parser.add_argument(
        "--runs-dir",
        default="runs",
        help="Directory used to store run artifacts. Defaults to runs/ under the repo root.",
    )
    parser.add_argument(
        "--fake-operator",
        action="store_true",
        help="Use a fake operator for local validation instead of invoking Claude.",
    )
    parser.add_argument(
        "--model",
        help=(
            "Model alias or full model name for the selected operator backend. "
            "Defaults to 'sonnet' for Claude runs, 'default' for Codex runs, "
            "and preserves the existing run model when resuming."
        ),
    )
    parser.add_argument(
        "--operator",
        choices=["claude", "codex"],
        help="Execution backend. Defaults to 'claude' for new runs and preserves the existing backend when resuming.",
    )
    parser.add_argument(
        "--codex-sandbox",
        choices=sorted(CODEX_SANDBOX_CHOICES),
        help=(
            "Codex CLI sandbox mode for Codex-backed execution. Defaults to "
            f"'{DEFAULT_CODEX_SANDBOX}' and is preserved when resuming. "
            "Use 'danger-full-access' only when you intentionally need unrestricted local/SSH execution."
        ),
    )
    parser.add_argument(
        "--approval-mode",
        choices=["manual", "agent"],
        help="Approval controller. Defaults to manual and preserves the existing run setting when resuming.",
    )
    parser.add_argument(
        "--full-auto",
        action="store_true",
        help="Shortcut for --approval-mode agent plus --unattended. AutoR will use a strict reviewer "
             "agent instead of waiting for manual approval, and will never block on terminal input.",
    )
    parser.add_argument(
        "--unattended",
        action="store_true",
        help="Never block on terminal input. Interactive prompts become hard errors instead of "
             "waiting for a human, and an exhausted stage is auto-skipped rather than aborting the run. "
             "Implied by --full-auto and by --approval-mode agent.",
    )
    parser.add_argument(
        "--max-auto-skips",
        type=int,
        default=3,
        help="In unattended mode, the maximum number of stages that may be auto-skipped after "
             "exhausting their retry budget before the run aborts. Defaults to 3.",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=1,
        help=(
            "How many times Stages 03-06 may run. A round ends when Stage 06 declares "
            "whether the run converged, needs a better design, needs a new hypothesis, or "
            "should be abandoned. Defaults to 1, which keeps the single-pass behaviour; the "
            "decision is recorded either way, so a one-round run still says whether it "
            "converged or merely stopped. Raise it to let a refuted hypothesis lead to a "
            "second round."
        ),
    )
    parser.add_argument(
        "--review-panel",
        action="store_true",
        help="Replace the single reviewer agent with a deliberating panel of role-differentiated "
             "reviewers (PI, domain expert, methodologist, reproducibility engineer, adversarial "
             "reviewer). They review independently, then cross-examine, then a chair synthesizes "
             "one decision. A blocking objection cannot be approved over. Implies "
             "--approval-mode agent.",
    )
    parser.add_argument(
        "--panel-roles",
        nargs="+",
        metavar="ROLE",
        help="Seat only these roles on the panel, in this order: "
             + ", ".join(role.key for role in DEFAULT_PANEL)
             + ". The first seat chairs unless the PI is present. Defaults to all five.",
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
        "--panel-rounds",
        type=int,
        default=2,
        help="Maximum deliberation rounds. Round 1 is always independent; later rounds are only "
             "run when the panel disagreed. Defaults to 2.",
    )
    parser.add_argument(
        "--persona",
        metavar="PATH",
        help="Path to a markdown description of the researcher the panel is standing in for "
             "(their priorities, standards, risk tolerance). Injected into every panelist so the "
             "simulated humans hold a consistent bar instead of improvising one per stage.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=MAX_STAGE_ATTEMPTS,
        help="Attempts allowed per stage before AutoR escalates or auto-skips. Each retry "
             "re-runs the stage with the previous attempt's validation errors attached. "
             f"Defaults to {MAX_STAGE_ATTEMPTS}.",
    )
    parser.add_argument(
        "--review-operator",
        choices=["claude", "codex"],
        help="Backend used by the automated reviewer. Defaults to the execution backend.",
    )
    parser.add_argument(
        "--review-model",
        help="Model alias or full model name for the automated reviewer backend. Defaults to the reviewer backend default.",
    )
    parser.add_argument(
        "--web-search",
        choices=list(WEB_SEARCH_MODE_CHOICES),
        help=(
            "How operators should search the web. 'gemini' routes searches through the Gemini "
            "API's Google Search grounding via tools/web_search.py, which is required on "
            "deployments where the built-in WebSearch tool is disabled (for example Claude Code "
            "on Vertex AI). 'native' leaves the backend's own search tool in charge. 'auto' "
            "(default) uses Gemini when a Gemini API key is available and falls back to native."
        ),
    )
    parser.add_argument(
        "--output-format",
        choices=list(OUTPUT_FORMAT_CLI_CHOICES),
        help=(
            "Final deliverable produced by Stage 07. 'markdown' (the default) writes a "
            "standalone report to workspace/report/report.md with PNG figures under "
            "workspace/report/images/, which is what automated research benchmarks such as "
            "ResearchClawBench score. 'latex' keeps the submission-oriented paper package: "
            "main.tex, sections/*.tex, a bibliography, and a compiled PDF. "
            f"Defaults to '{DEFAULT_OUTPUT_FORMAT}' for new runs and preserves the existing "
            "run setting when resuming."
        ),
    )
    parser.add_argument(
        "--final-stage",
        metavar="STAGE",
        help="Stop after this stage slug or number instead of running the whole workflow "
             "(for example '07_writing' or '7'). Useful when only the manuscript or report is "
             "needed and the dissemination package is not.",
    )
    parser.add_argument(
        "--venue",
        help=(
            "Target venue profile for Stage 07 writing. "
            f"Defaults to '{DEFAULT_VENUE}' for new runs and preserves the existing run venue when resuming. "
            "Examples: neurips_2025, nature, nature_communications, jmlr."
        ),
    )
    parser.add_argument(
        "--resume-run",
        help="Resume an existing run by run_id under runs/. Use 'latest' to resume the most recent run.",
    )
    parser.add_argument(
        "--redo-stage",
        help="When resuming a run, restart from this stage slug or stage number (for example '06_analysis' or '6').",
    )
    parser.add_argument(
        "--resources",
        nargs="+",
        metavar="PATH",
        help="Paths to resource files or directories to include in the run "
             "(PDFs, code repos, datasets, .bib files, notes).",
    )
    parser.add_argument(
        "--skip-intake",
        action="store_true",
        help="Skip the Claude-driven Socratic intake stage.",
    )
    parser.add_argument(
        "--rollback-stage",
        help="When resuming a run, roll back to this stage and mark downstream stages stale before continuing.",
    )
    parser.add_argument(
        "--research-diagram",
        action="store_true",
        help="After the writing stage, generate a method illustration diagram using "
             "the Gemini API and insert it into the report (report.md in markdown mode, "
             "method.tex in latex mode).",
    )
    parser.add_argument(
        "--project-root",
        metavar="PATH",
        help="Path to an existing project repository. AutoR will scan it to infer "
             "current project state and recommend a re-entry stage.",
    )
    parser.add_argument(
        "--paper-corpus",
        metavar="PATH",
        help="Path to a directory of the user's own prior papers (PDFs, LaTeX, BibTeX, notes). "
             "AutoR will analyze them to build a researcher profile that seeds downstream stages.",
    )
    parser.add_argument(
        "--stage-timeout",
        type=int,
        default=14400,
        help="Maximum seconds per stage attempt before timeout. Defaults to 14400 (4 hours).",
    )
    return parser.parse_args()


def default_model_for_operator(operator_name: str) -> str:
    return "default" if operator_name == "codex" else "sonnet"


def create_operator(
    operator_name: str,
    *,
    model: str,
    codex_sandbox: str,
    fake_mode: bool,
    ui: TerminalUI,
    stage_timeout: int,
) -> OperatorProtocol:
    if operator_name == "codex":
        return CodexOperator(
            model=model,
            codex_sandbox=codex_sandbox,
            fake_mode=fake_mode,
            ui=ui,
            stage_timeout=stage_timeout,
        )
    return ClaudeOperator(model=model, fake_mode=fake_mode, ui=ui, stage_timeout=stage_timeout)


def create_reviewer(
    backend_name: str,
    *,
    model: str,
    fake_mode: bool,
    ui: TerminalUI,
    stage_timeout: int,
    panel_roles: list[str] | None = None,
    panel_models: list[str] | None = None,
    use_panel: bool = False,
    persona_text: str = "",
    deliberation_rounds: int = 2,
):
    """Build the approval gate: one reviewer, or a panel that deliberates first.

    Both satisfy the same ``review_stage`` contract, so the manager never learns which it got.
    """
    if use_panel:
        return ReviewPanel(
            apply_model_assignments(resolve_roles(panel_roles), panel_models),
            backend_name=backend_name,
            model=model,
            fake_mode=fake_mode,
            ui=ui,
            stage_timeout=stage_timeout,
            persona_text=persona_text,
            deliberation_rounds=deliberation_rounds,
        )
    return AutomatedReviewer(
        backend_name,
        model=model,
        fake_mode=fake_mode,
        ui=ui,
        stage_timeout=stage_timeout,
    )


def resolve_resume_run(runs_dir: Path, value: str) -> Path:
    if value == "latest":
        candidates = sorted(path for path in runs_dir.iterdir() if path.is_dir())
        if not candidates:
            raise FileNotFoundError(f"No runs found in {runs_dir}")
        return candidates[-1]

    run_root = runs_dir / value
    if not run_root.exists() or not run_root.is_dir():
        raise FileNotFoundError(f"Run not found: {run_root}")
    return run_root


def resolve_unattended(args: argparse.Namespace) -> bool:
    """Decide whether this invocation is allowed to block on terminal input.

    `--full-auto`, `--approval-mode agent` and `--review-panel` all replace the human approval
    gate with an agent, so none of them has anyone left to answer a prompt.
    """
    return bool(
        args.unattended
        or args.full_auto
        or getattr(args, "review_panel", False)
        or args.approval_mode == "agent"
    )


def resolve_goal(args: argparse.Namespace, *, unattended: bool) -> str:
    if args.goal and args.goal_file:
        raise ValueError("--goal and --goal-file are mutually exclusive.")

    if args.goal_file:
        goal = Path(args.goal_file).expanduser().read_text(encoding="utf-8").strip()
        if not goal:
            raise ValueError(f"Goal file is empty: {args.goal_file}")
        return goal

    if args.goal:
        return args.goal.strip()

    if unattended:
        raise ValueError(
            "Unattended runs cannot prompt for a research goal. Pass --goal or --goal-file."
        )

    return read_user_goal()


def read_user_goal() -> str:
    print("Enter your research goal. Finish with an empty line on a new line:")
    lines: list[str] = []

    while True:
        prompt = "> " if not lines else ""
        try:
            line = input(prompt)
        except EOFError:
            break

        if not line.strip():
            if lines:
                break
            continue

        lines.append(line.rstrip())

    goal = "\n".join(lines).strip()
    if not goal:
        raise ValueError("Research goal cannot be empty.")
    return goal


def _build_resource_entries(paths: list[str]) -> list[ResourceEntry]:
    """Classify CLI --resources into ResourceEntry objects."""
    entries: list[ResourceEntry] = []
    for p in paths:
        path = Path(p).expanduser().resolve()
        rtype, ddir = classify_resource(path)
        entries.append(
            ResourceEntry(
                source_path=str(path),
                resource_type=rtype,
                dest_dir=ddir,
                dest_relative="",
                description="",
            )
        )
    return entries


def resolve_search_context(ui: TerminalUI, *, mode: str, operator: str, codex_sandbox: str) -> str | None:
    """Decide the search path, announce it, and refuse a request that cannot work.

    Called once per branch rather than once up front, because the answer depends on the
    operator and sandbox -- and on resume those come from run_config, which is not read
    until inside the branch.
    """
    readiness = assess_search_readiness(operator=operator, codex_sandbox=codex_sandbox)
    notice, level = web_search_notice(mode, readiness=readiness)
    ui.show_status(notice, level=level)
    if mode == "gemini" and readiness.hard_blocker:
        raise ValueError(
            f"--web-search gemini cannot work here: {readiness.hard_blocker} "
            "Fix it, or use --web-search auto to fall back to native search."
        )
    return resolve_web_search_context(mode, readiness=readiness)


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent
    runs_dir = repo_root / args.runs_dir
    unattended = resolve_unattended(args)
    persona_text = load_persona(args.persona)
    ui = TerminalUI(interactive=not unattended)
    ui.show_banner()

    if args.resume_run:
        start_stage = resolve_stage(args.redo_stage)
        rollback_stage = resolve_stage(args.rollback_stage)
        final_stage = resolve_stage(args.final_stage)
        if start_stage is not None and rollback_stage is not None:
            raise ValueError("--redo-stage and --rollback-stage are mutually exclusive.")
        entry_stage = start_stage or rollback_stage
        if final_stage is not None and entry_stage is not None and final_stage.number < entry_stage.number:
            raise ValueError(
                f"--final-stage {final_stage.slug} is before the requested entry stage "
                f"{entry_stage.slug}; there would be nothing to run."
            )
        run_root = resolve_resume_run(runs_dir, args.resume_run)
        paths = build_run_paths(run_root)
        existing_config = load_run_config(paths)
        existing_operator = str(existing_config.get("operator") or "claude").strip().lower()
        operator_name = (args.operator or existing_config.get("operator") or "claude").strip().lower()
        existing_model = existing_config.get("model")
        if args.model:
            model = args.model
        elif args.operator and operator_name != existing_operator:
            model = default_model_for_operator(operator_name)
        else:
            model = (existing_model if existing_model != "unknown" else None) or default_model_for_operator(operator_name)
        codex_sandbox = args.codex_sandbox or existing_config.get("codex_sandbox") or DEFAULT_CODEX_SANDBOX
        approval_mode = (
            "agent"
            if (args.full_auto or args.review_panel)
            else (args.approval_mode or existing_config.get("approval_mode") or "manual")
        )
        if approval_mode == "agent":
            unattended = True
            ui.interactive = False
        review_operator = (args.review_operator or existing_config.get("review_operator") or operator_name).strip().lower()
        existing_review_model = existing_config.get("review_model")
        if args.review_model:
            review_model = args.review_model
        elif args.review_operator:
            review_model = default_model_for_operator(review_operator)
        else:
            review_model = (
                existing_review_model if existing_review_model != "unknown" else None
            ) or default_model_for_operator(review_operator)
        venue = resolve_venue_key(args.venue or existing_config["venue"])
        output_format = resolve_output_format(args.output_format or existing_config.get("output_format"))
        web_search_mode = normalize_web_search_mode(args.web_search or existing_config.get("web_search"))
        web_search_context = resolve_search_context(
            ui, mode=web_search_mode, operator=operator_name, codex_sandbox=codex_sandbox
        )
        operator = create_operator(
            operator_name,
            model=model,
            codex_sandbox=codex_sandbox,
            fake_mode=args.fake_operator,
            ui=ui,
            stage_timeout=args.stage_timeout,
        )
        reviewer = None
        if approval_mode == "agent":
            reviewer = create_reviewer(
                review_operator,
                model=review_model,
                fake_mode=args.fake_operator,
                ui=ui,
                stage_timeout=args.stage_timeout,
                use_panel=args.review_panel,
                panel_roles=args.panel_roles,
                panel_models=args.panel_models,
                persona_text=persona_text,
                deliberation_rounds=args.panel_rounds,
            )
        manager = ResearchManager(
            project_root=repo_root,
            runs_dir=runs_dir,
            operator=operator,
            ui=ui,
            reviewer=reviewer,
            approval_mode=approval_mode,
            review_operator=review_operator,
            review_model=review_model,
            unattended=unattended,
            max_auto_skips=args.max_auto_skips,
            max_rounds=args.max_rounds,
            max_stage_attempts=args.max_attempts,
            web_search_context=web_search_context,
            web_search_mode=web_search_mode,
        )
        return 0 if manager.resume_run(
            run_root,
            start_stage=start_stage or rollback_stage,
            venue=venue,
            rollback_stage=rollback_stage,
            research_diagram=args.research_diagram,
            output_format=output_format,
            final_stage=final_stage,
        ) else 1

    operator_name = (args.operator or "claude").strip().lower()
    model = args.model or default_model_for_operator(operator_name)
    codex_sandbox = args.codex_sandbox or DEFAULT_CODEX_SANDBOX
    approval_mode = "agent" if (args.full_auto or args.review_panel) else (args.approval_mode or "manual")
    review_operator = (args.review_operator or operator_name).strip().lower()
    review_model = args.review_model or default_model_for_operator(review_operator)
    venue = resolve_venue_key(args.venue or DEFAULT_VENUE)
    output_format = resolve_output_format(args.output_format or DEFAULT_OUTPUT_FORMAT)
    web_search_mode = normalize_web_search_mode(args.web_search)
    web_search_context = resolve_search_context(
        ui, mode=web_search_mode, operator=operator_name, codex_sandbox=codex_sandbox
    )
    final_stage = resolve_stage(args.final_stage)
    operator = create_operator(
        operator_name,
        model=model,
        codex_sandbox=codex_sandbox,
        fake_mode=args.fake_operator,
        ui=ui,
        stage_timeout=args.stage_timeout,
    )
    reviewer = None
    if approval_mode == "agent":
        reviewer = create_reviewer(
            review_operator,
            model=review_model,
            fake_mode=args.fake_operator,
            ui=ui,
            stage_timeout=args.stage_timeout,
            use_panel=args.review_panel,
            panel_roles=args.panel_roles,
            panel_models=args.panel_models,
            persona_text=persona_text,
            deliberation_rounds=args.panel_rounds,
        )
    manager = ResearchManager(
        project_root=repo_root,
        runs_dir=runs_dir,
        operator=operator,
        ui=ui,
        reviewer=reviewer,
        approval_mode=approval_mode,
        review_operator=review_operator,
        review_model=review_model,
        unattended=unattended,
        max_auto_skips=args.max_auto_skips,
        max_rounds=args.max_rounds,
        max_stage_attempts=args.max_attempts,
        web_search_context=web_search_context,
        web_search_mode=web_search_mode,
    )

    goal = resolve_goal(args, unattended=unattended)
    skip_intake = args.skip_intake or not sys.stdin.isatty()

    # Collect resources: from --resources flag, and optionally from interactive prompt.
    # The interactive prompt is skipped unattended even on a TTY: RCB-style harnesses hand the
    # agent the launching terminal's stdin, so this prompt would otherwise silently block.
    resources: list[ResourceEntry] = []
    if args.resources:
        resources = _build_resource_entries(args.resources)
    if not skip_intake and not unattended and sys.stdin.isatty():
        resources = collect_resource_paths_from_ui(ui, initial_resources=args.resources)

    project_root_arg = Path(args.project_root).expanduser().resolve() if args.project_root else None
    paper_corpus = Path(args.paper_corpus).expanduser().resolve() if args.paper_corpus else None

    return 0 if manager.run(
        goal,
        venue=venue,
        resources=resources or None,
        skip_intake=skip_intake,
        research_diagram=args.research_diagram,
        project_root=project_root_arg,
        paper_corpus=paper_corpus,
        output_format=output_format,
        final_stage=final_stage,
    ) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
