from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import shutil
import sys
from pathlib import Path
from typing import TextIO

from .bootstrap import (
    bootstrap_profile_exists,
    format_corpus_for_prompt,
    format_corpus_stats_for_log,
    format_profile_for_prompt,
    missing_bootstrap_profile_artifacts,
    scan_corpus,
)
from .approval_agent import AutomatedReviewer, ReviewDecision
from .cross_reviewer import GeminiCrossReviewer
from .obligations import (
    discharge_obligations,
    format_for_stage_prompt,
    ledger_summary,
    load_ledger,
    note_deferrals,
    record_obligations,
)
from .review_policy import load_policy, policy_summary, record_correction
from .project_bootstrap import (
    format_project_context_for_prompt,
    format_project_scan_for_prompt,
    format_scan_stats_for_log,
    load_recommended_entry_stage,
    load_stage_assessments,
    project_bootstrap_exists,
    recommend_entry_stage,
    save_project_bootstrap,
    save_recommended_entry_stage,
    scan_project,
)
from .intake import (
    IntakeContext,
    QATurn,
    ResourceEntry,
    format_intake_for_prompt,
    format_resources_for_intake_prompt,
    ingest_resources,
    load_intake_context,
    parse_intake_clarification_question,
    save_intake_context
)
from .artifact_index import format_artifact_index_for_prompt, write_artifact_index
from .experiment_manifest import format_experiment_manifest_for_prompt, write_experiment_manifest
from .hypothesis_manifest import write_hypothesis_manifest
from .prompt_fragments import compose_stage_template
from .validity_review import ValidityReviewer, format_findings_for_prompt
from .research_rounds import (
    ROUND_CLOSING_STAGE_NUMBER,
    read_round_decision,
    format_round_status,
    format_rounds_for_prompt,
    load_rounds,
    record_round,
    resume_stage_slug_for,
)
from .preregistration import (
    amend_preregistration,
    format_outcomes_for_prompt,
    format_preregistration_for_prompt,
    freeze_preregistration,
    load_preregistration,
)
from .run_skills import install_run_skills
from .manifest import (
    ensure_run_manifest,
    format_manifest_status,
    initialize_run_manifest,
    load_run_manifest,
    mark_stage_approved_manifest,
    mark_stage_skipped_manifest,
    mark_stage_failed_manifest,
    mark_stage_human_review_manifest,
    mark_stage_running_manifest,
    rebuild_memory_from_manifest,
    rollback_to_stage,
    sync_stage_session_id,
    update_manifest_run_status,
)
from .operator_protocol import OperatorProtocol
from .evolution import EvolutionConfig, EvolutionController
from .router import StageRouter, format_decision
from .stage_graph import (
    FINISH as GRAPH_FINISH,
    GraphState,
    StageGraph,
    enter as graph_enter,
    format_route,
    leave as graph_leave,
    load_graph_state,
    save_graph_state,
    stage_for_slug,
)
from .diagram_gen import post_writing_diagram_hook
from .terminal_ui import TerminalUI
from .platform.foundry import generate_paper_package, generate_release_package
from .ideation_panel import (
    IdeationPanel,
    format_pool_for_prompt,
    load_idea_pool,
    measure_adoption,
    record_idea_pool,
)
from .writing_manifest import (
    build_writing_manifest,
    format_manifest_for_prompt,
    generate_layout_review,
    generate_report_review,
)
from .utils import (
    DEFAULT_REFINEMENT_SUGGESTIONS,
    DEFAULT_ROUTING_MODE,
    DEFAULT_STAGE_GRAPH,
    FIXED_STAGE_OPTIONS,
    INTAKE_STAGE,
    MAX_STAGE_ATTEMPTS,
    STAGES,
    RunPaths,
    StageSpec,
    append_approved_stage_summary,
    approved_stage_numbers,
    approved_stage_summaries,
    append_log_entry,
    build_decision_ledger_context,
    build_handoff_context,
    build_hypothesis_context,
    build_continuation_prompt,
    build_prompt,
    build_run_paths,
    canonicalize_stage_markdown,
    create_run_root,
    ensure_run_config,
    ensure_run_layout,
    format_stage_template,
    format_venue_for_prompt,
    filtered_approved_memory,
    initialize_memory,
    initialize_run_config,
    load_prompt_template,
    mark_stage_execution_started,
    extract_revision_delta,
    strip_revision_delta,
    strip_markdown_section,
    parse_refinement_suggestions,
    read_attempt_count,
    read_polish_count,
    read_text,
    required_stage_output_template,
    selected_output_format,
    truncate_text,
    validate_stage_artifacts,
    validate_stage_markdown,
    write_attempt_count,
    write_polish_count,
    write_stage_handoff,
    write_text,
)


class ResearchManager:
    def __init__(
        self,
        project_root: Path,
        runs_dir: Path,
        operator: OperatorProtocol,
        output_stream: TextIO = sys.stdout,
        ui: TerminalUI | None = None,
        reviewer: AutomatedReviewer | None = None,
        approval_mode: str = "manual",
        review_operator: str | None = None,
        review_model: str | None = None,
        unattended: bool = False,
        max_auto_skips: int = 3,
        max_rounds: int = 1,
        max_stage_attempts: int = MAX_STAGE_ATTEMPTS,
        web_search_context: str | None = None,
        web_search_mode: str | None = None,
        artifact_roots: list[Path] | None = None,
        stage_graph: StageGraph | None = None,
        routing_mode: str = DEFAULT_ROUTING_MODE,
        evolution: EvolutionConfig | None = None,
        graph_max_steps: int | None = None,
        graph_max_visits: int | None = None,
        archive_steer: bool = False,
        cross_reviewer: GeminiCrossReviewer | None = None,
    ) -> None:
        self.project_root = project_root
        self.runs_dir = runs_dir
        self.operator = operator
        self.reviewer = reviewer
        self.prompt_dir = self.project_root / "src" / "prompts"
        self.skills_dir = self.project_root / "src" / "skills"
        self.output_stream = output_stream
        self.ui = ui or TerminalUI(output_stream=output_stream)
        self.approval_mode = "agent" if reviewer is not None else "manual"
        if approval_mode == "manual" and reviewer is None:
            self.approval_mode = "manual"
        self.review_operator = review_operator or getattr(reviewer, "backend_name", getattr(operator, "backend_name", "claude"))
        self.review_model = review_model or getattr(reviewer, "model", getattr(operator, "model", "unknown"))
        self.last_run_paths: RunPaths | None = None
        self._jump_reason: str = ""
        self._redo_start_stage: StageSpec | None = None
        self._research_diagram: bool = False
        self._final_stage: StageSpec | None = None
        self.ideation_panel: IdeationPanel | None = None
        self._jump_target_stage: StageSpec | None = None
        self.unattended = unattended
        self.max_auto_skips = max_auto_skips
        #: How many times Stages 03-06 may run. 1 keeps the historical
        #: single-pass behaviour; the round decision is recorded either way,
        #: so a one-round run still says whether it converged or just stopped.
        self.max_rounds = max(1, int(max_rounds))
        # Retries are the cheapest quality lever there is: each one re-runs the stage with the
        # previous attempt's validation errors attached. The ceiling exists to bound a runaway
        # loop, not to save money, so callers with time to spend should raise it.
        self.max_stage_attempts = max_stage_attempts
        self.auto_skipped_stages: list[str] = []
        self.web_search_context = web_search_context
        # The *mode* is recorded in run_config so a resume reconciles it the way it does
        # every other backend selection, instead of silently re-deciding from whatever
        # credentials happen to be in the environment that day.
        self.web_search_mode = web_search_mode
        # Extra roots a stage may legitimately write to, beyond the run tree. A benchmark
        # workspace is one: its output contract points stages at paths outside runs/.
        self.artifact_roots = artifact_roots or []
        # A veto-only second opinion from a different model family. Never overrides a
        # refusal, so enabling it can only make the gate stricter.
        self.cross_reviewer = cross_reviewer
        # Where a stage's machine-readable output may legitimately land outside the run
        # tree. The benchmark's read-only data/ is excluded on purpose: it is always
        # populated, so counting it would make the stage-03 gate vacuous.
        self.artifact_dirs: dict[str, list[Path]] = {
            "data": [root / "outputs" for root in self.artifact_roots],
            "results": [root / "outputs" for root in self.artifact_roots],
            "figures": [root / "report" / "images" for root in self.artifact_roots],
        }
        # The stages are a graph. A caller that names no topology gets the adaptive
        # one, which can go back when a later stage shows an earlier one was wrong.
        # `StageGraph.linear()` is still a real graph through the same walk, so the
        # strict sequence keeps being exercised by every test of either.
        self.stage_graph = stage_graph or StageGraph.named(DEFAULT_STAGE_GRAPH)
        self.graph_max_steps = graph_max_steps
        self.graph_max_visits = graph_max_visits
        self.router = StageRouter(
            operator=operator,
            mode=routing_mode,
            fake_mode=bool(getattr(operator, "fake_mode", False)),
        )
        # Measuring is on unless a caller turns it off: scoring a draft and running
        # the ratchet spends no backend call, and the property it buys — the draft
        # that gets promoted is the best one the run produced rather than the last
        # one — is the whole reason any of this exists.
        requested_evolution = evolution if evolution is not None else EvolutionConfig()
        # A fake operator cannot improve anything: it emits the same scripted draft
        # whatever the directive says, so every round would be bought, measured as a
        # regression and reverted. Applied here rather than at the CLI so the number
        # the operator *asked* for is what reaches run_config.json — zeroing it there
        # would mean resuming a fake run with a real backend silently inherited a
        # budget of nothing.
        evolution_config = (
            replace(requested_evolution, rounds=0)
            if getattr(operator, "fake_mode", False)
            else requested_evolution
        )
        self.evolution = (
            EvolutionController(
                evolution_config,
                artifact_dirs=self.artifact_dirs,
                artifact_roots=self.artifact_roots,
            )
            if evolution_config.enabled
            else None
        )
        # What gets written into run_config.json, so `--resume-run` continues the
        # same walk. Derived from the manager's own settings rather than re-read
        # from the CLI: the two would otherwise disagree whenever a caller built a
        # manager directly, and the run would resume as something it never was.
        self._walk_settings = {
            "stage_graph": self.stage_graph.name,
            "routing_mode": self.router.mode,
            "evolve_rounds": requested_evolution.rounds if requested_evolution.measure else 0,
            "evolve_measure": requested_evolution.measure,
            "archive_steer": archive_steer,
        }

    def run(
        self,
        user_goal: str,
        venue: str | None = None,
        resources: list[ResourceEntry] | None = None,
        skip_intake: bool = False,
        research_diagram: bool = False,
        project_root: Path | None = None,
        paper_corpus: Path | None = None,
        output_format: str | None = None,
        final_stage: StageSpec | None = None,
    ) -> bool:
        self._research_diagram = research_diagram
        self._final_stage = final_stage
        paths = self._create_run(
            user_goal, venue=venue, resources=resources, output_format=output_format
        )
        self.ui.show_run_started(paths.run_root.as_posix(), self.operator.model, venue or "default")
        self._announce_approval_mode()

        # Run Claude-driven intake stage unless skipped
        if not skip_intake:
            intake_approved = self._run_intake(paths)
            if not intake_approved:
                append_log_entry(paths.logs, "run_aborted", "Run aborted during intake.")
                update_manifest_run_status(
                    paths,
                    run_status="cancelled",
                    last_event="run.cancelled",
                    current_stage_slug=INTAKE_STAGE.slug,
                )
                self.ui.show_status("Run aborted.", level="warn")
                return False

        # Run project repo bootstrap if provided
        bootstrap_start_stage: StageSpec | None = None
        if project_root is not None:
            bootstrap_result = self._run_project_bootstrap(paths, project_root)
            if bootstrap_result is None:
                append_log_entry(paths.logs, "run_aborted", "Run aborted during project bootstrap.")
                self.ui.show_status("Run aborted.", level="warn")
                return False
            bootstrap_start_stage = bootstrap_result

        # Run bootstrap from paper corpus if provided
        if paper_corpus is not None:
            bootstrap_approved = self._run_bootstrap(paths, paper_corpus)
            if not bootstrap_approved:
                append_log_entry(paths.logs, "run_aborted", "Run aborted during bootstrap.")
                self.ui.show_status("Run aborted.", level="warn")
                return False

        return self._run_from_paths(paths, start_stage=bootstrap_start_stage)

    def resume_run(
        self,
        run_root: Path,
        start_stage: StageSpec | None = None,
        rollback_stage: StageSpec | None = None,
        venue: str | None = None,
        research_diagram: bool = False,
        output_format: str | None = None,
        final_stage: StageSpec | None = None,
    ) -> bool:
        self._research_diagram = research_diagram
        self._final_stage = final_stage
        paths = build_run_paths(run_root)
        ensure_run_layout(paths)
        # Reinstalled on resume so a run picks up skill edits without needing a
        # fresh run directory.
        self._install_skills(paths)
        config = ensure_run_config(
            paths,
            model=self.operator.model,
            venue=venue,
            operator=getattr(self.operator, "backend_name", "claude"),
            approval_mode=self.approval_mode,
            review_operator=self.review_operator,
            review_model=self.review_model,
            codex_sandbox=getattr(self.operator, "codex_sandbox", None),
            output_format=output_format,
            walk=self._walk_settings,
            web_search=self.web_search_mode,
        )
        ensure_run_manifest(paths)
        if not paths.user_input.exists():
            raise FileNotFoundError(f"Missing user_input.txt in run: {run_root}")
        if not paths.memory.exists():
            raise FileNotFoundError(f"Missing memory.md in run: {run_root}")

        if rollback_stage is not None:
            self._print(self._format_rollback_preview(paths, rollback_stage))
            rollback_to_stage(paths, rollback_stage)
            start_stage = rollback_stage

        append_log_entry(
            paths.logs,
            "run_resume",
            f"Resumed run at: {paths.run_root}"
            + (f"\nRequested start stage: {start_stage.stage_title}" if start_stage else "")
            + (f"\nRequested rollback stage: {rollback_stage.stage_title}" if rollback_stage else "")
            + f"\nVenue: {config['venue']}"
            + f"\nOutput format: {config['output_format']}",
        )
        self.ui.show_run_started(
            paths.run_root.as_posix(),
            self.operator.model,
            config["venue"],
            resumed=True,
        )
        self._announce_approval_mode()
        if start_stage:
            self.ui.show_status(f"Restarting from {start_stage.stage_title}", level="warn")
        return self._run_from_paths(paths, start_stage=start_stage)

    def _run_from_paths(self, paths: RunPaths, start_stage: StageSpec | None = None) -> bool:
        """Walk the stage graph until it reaches ``finish`` or nothing is open.

        The default topology has one edge out of every node, so this reproduces the
        old sequential walk exactly; ``--stage-graph adaptive`` adds the backward
        moves. Both go through this loop rather than through a linear path and a
        graph path, because a second walk implementation is a second place for the
        approval, abort and resume semantics to be subtly different.
        """
        # Exposed so a caller that owns an archive can find the run it just drove
        # without re-deriving the run id from the runs directory, which would pick
        # the wrong one whenever two runs start in the same second.
        self.last_run_paths = paths
        entry = self._graph_entry_stage(paths, start_stage)
        if entry is None:
            return self._complete_run(paths)

        state = load_graph_state(
            paths, max_steps=self.graph_max_steps, max_visits=self.graph_max_visits
        )
        stage: StageSpec | None = entry

        while stage is not None:
            if state.steps >= state.max_steps:
                state.halted_because = (
                    f"the run reached the {state.max_steps}-step limit for this graph"
                )
                save_graph_state(paths, state)
                self.ui.show_status(state.halted_because, level="warn")
                break

            graph_enter(paths, state, stage)
            self._jump_target_stage = None
            self._jump_reason = ""
            approved = self._run_stage(paths, stage)

            # Three things reach this seam: `/back <stage>`, a rollback after retry
            # exhaustion, and a research round that decided to refine its design or
            # change its hypothesis. All of them outrank the router — the move is
            # already made by the time the walk sees it — and all of them are
            # recorded on the route as the revisits they are.
            if self._jump_target_stage is not None:
                target = self._jump_target_stage
                graph_leave(
                    paths,
                    state,
                    chose=target.slug,
                    kind="revisit",
                    reason=self._jump_reason or "The run was redirected to an earlier stage.",
                    default_choice="",
                    agent_directed=False,
                    score_total=None,
                )
                stage = target
                continue

            if not approved:
                append_log_entry(
                    paths.logs,
                    "run_aborted",
                    f"Run aborted during {stage.stage_title}.",
                )
                update_manifest_run_status(
                    paths,
                    run_status="cancelled",
                    last_event="run.cancelled",
                    current_stage_slug=stage.slug,
                )
                save_graph_state(paths, state)
                self._print("Run aborted.")
                return False

            stage = self._advance_from(paths, state, stage)

        save_graph_state(paths, state)
        return self._complete_run(paths, state=state)

    def _complete_run(self, paths: RunPaths, state: "GraphState | None" = None) -> bool:
        route = format_route(state) if state is not None else ""
        append_log_entry(
            paths.logs,
            "run_complete",
            "All stages approved." + (f"\nRoute: {route}" if route else ""),
        )
        update_manifest_run_status(
            paths,
            run_status="completed",
            last_event="run.completed",
            current_stage_slug=None,
            completed_at=datetime.now().isoformat(timespec="seconds"),
        )
        if route and self.stage_graph.name != "linear":
            self.ui.show_status(f"Route taken: {route}", level="info")
        self._print("All stages approved. Run complete.")
        return True

    def _graph_entry_stage(self, paths: RunPaths, start_stage: StageSpec | None) -> StageSpec | None:
        """Where the walk starts: the requested stage, or the first unsettled one."""
        pending = self._select_stages_for_run(paths, start_stage)
        return pending[0] if pending else None

    def _advance_from(
        self,
        paths: RunPaths,
        state: "GraphState",
        stage: StageSpec,
    ) -> StageSpec | None:
        """Choose and take the edge out of an approved stage."""
        score = None
        if self.evolution is not None:
            score = self.evolution.finalize_stage(paths, stage)

        decision = self.router.choose(
            paths=paths,
            stage=stage,
            graph=self.stage_graph,
            state=state,
            score=score,
            final_stage=self._final_stage,
        )
        graph_leave(
            paths,
            state,
            chose=decision.target,
            kind=decision.kind,
            reason=decision.reason,
            default_choice=decision.default_target,
            agent_directed=decision.agent_directed,
            score_total=score.total if score is not None else None,
        )
        if decision.agent_directed or decision.refusal:
            self.ui.show_status(format_decision(decision), level="info")

        if decision.finished:
            return None

        target = stage_for_slug(decision.target)
        if target is None:
            return None

        if decision.kind == "revisit":
            # Re-entering a stage invalidates everything downstream of it. The
            # manifest already knows how to say so; skipping this would leave a
            # later stage's approved summary in memory describing work that the
            # revisit is about to replace.
            self._print(self._format_rollback_preview(paths, target))
            rollback_to_stage(
                paths,
                target,
                reason=f"Graph revisit from {stage.slug}: {decision.reason}",
            )
            return target

        return self._skip_settled(paths, state, target)

    def _skip_settled(
        self,
        paths: RunPaths,
        state: "GraphState",
        target: StageSpec,
    ) -> StageSpec | None:
        """Follow advance edges past stages a resumed run already settled.

        `--resume-run` used to get this from `_select_stages_for_run` filtering the
        list up front. A graph walk decides one move at a time, so the same rule has
        to be applied at the move: an advance edge into an already-approved stage
        moves through it rather than running it again.
        """
        seen: set[str] = set()
        current: StageSpec | None = target
        while current is not None and current.slug not in seen:
            seen.add(current.slug)
            manifest = ensure_run_manifest(paths)
            entry = next((item for item in manifest.stages if item.slug == current.slug), None)
            if entry is None or not entry.settled:
                return current
            move = self.stage_graph.default_move(
                paths, current.slug, state, final_stage=self._final_stage
            )
            if move is None or move.target == GRAPH_FINISH:
                return None
            current = stage_for_slug(move.target)
        return current

    def _build_idea_pool(self, paths: RunPaths, stage: StageSpec, attempt_no: int) -> str:
        """Widen Stage 02's candidate pool before it writes anything.

        Best-effort: a panel that cannot be reached must not stop the stage from generating
        hypotheses the ordinary way, because the pool is material rather than a dependency.
        """
        assert self.ideation_panel is not None
        try:
            pool = self.ideation_panel.build_pool(paths=paths, stage=stage, attempt_no=attempt_no)
        except Exception as exc:  # noqa: BLE001 - the stage proceeds without the pool
            append_log_entry(paths.logs, f"{stage.slug} idea_pool_failed", str(exc))
            self.ui.show_status(f"Ideation panel failed: {exc}", level="warn")
            return "The ideation panel did not run. Generate hypotheses as usual.\n"

        record_idea_pool(paths, pool, stage, attempt_no)
        return format_pool_for_prompt(pool)

    def _measure_pool_adoption(self, paths: RunPaths, stage: StageSpec, stage_markdown: str) -> None:
        """Record which pooled hypotheses the approved stage actually built on.

        Runs whether or not this run seated an ideation panel — a pool written by an earlier
        resumed attempt still deserves its outcome measured. Best-effort throughout: the
        stage is already approved, and nothing here may unapprove it.
        """
        try:
            pool = load_idea_pool(paths)
            if pool is None or not pool.distinct:
                return
            record_idea_pool(paths, measure_adoption(pool, stage_markdown), stage, 0)
        except Exception as exc:  # noqa: BLE001 - measurement must not disturb an approval
            append_log_entry(paths.logs, f"{stage.slug} idea_pool_adoption_failed", str(exc))

    def _generate_writing_review(self, paths: RunPaths) -> dict[str, object]:
        """Produce the Stage 07 triage artifact that matches this run's output format.

        Both variants land in workspace/artifacts and are re-read by the next attempt's prompt,
        so a failed gate always comes back with the specific defect attached.
        """
        if selected_output_format(paths) == "markdown":
            return generate_report_review(paths)
        return generate_layout_review(paths)

    def _create_run(
        self,
        user_goal: str,
        venue: str | None = None,
        resources: list[ResourceEntry] | None = None,
        output_format: str | None = None,
    ) -> RunPaths:
        run_root = create_run_root(self.runs_dir)
        paths = build_run_paths(run_root)
        ensure_run_layout(paths)
        self._install_skills(paths)
        write_text(paths.user_input, user_goal)

        # Ingest any pre-provided resources into workspace
        intake_summary: str | None = None
        if resources:
            updated = ingest_resources(resources, paths)
            ctx = IntakeContext(goal=user_goal, original_goal=user_goal, resources=updated)
            save_intake_context(paths, ctx)
            intake_summary = format_intake_for_prompt(ctx)

        initialize_memory(paths, user_goal, intake_summary=intake_summary)
        config = initialize_run_config(
            paths,
            model=self.operator.model,
            venue=venue,
            operator=getattr(self.operator, "backend_name", "claude"),
            approval_mode=self.approval_mode,
            review_operator=self.review_operator,
            review_model=self.review_model,
            codex_sandbox=getattr(self.operator, "codex_sandbox", None),
            output_format=output_format,
            walk=self._walk_settings,
            web_search=self.web_search_mode,
        )
        initialize_run_manifest(paths)
        write_artifact_index(paths)
        write_experiment_manifest(paths)
        append_log_entry(paths.logs, "run_start", f"Run root: {paths.run_root}")
        append_log_entry(
            paths.logs,
            "run_config",
            (
                f"Model: {config['model']}\n"
                f"Venue: {config['venue']}\n"
                f"Output format: {config['output_format']}\n"
                f"Stage graph: {config['stage_graph']} (routing: {config['routing_mode']}, "
                f"evolve rounds: {config['evolve_rounds']})\n"
                f"Approval mode: {config['approval_mode']}\n"
                f"Review backend: {config['review_operator']}\n"
                f"Review model: {config['review_model']}\n"
                f"Codex sandbox: {config.get('codex_sandbox', 'workspace-write')}"
            ),
        )
        return paths

    def _select_stages_for_run(
        self,
        paths: RunPaths,
        start_stage: StageSpec | None,
    ) -> list[StageSpec]:
        # A run that only has to produce a scored deliverable has no reason to pay for the
        # stages after it; the caller says where the deliverable is finished.
        last = self._final_stage.number if self._final_stage is not None else STAGES[-1].number

        if start_stage is not None:
            return [stage for stage in STAGES if start_stage.number <= stage.number <= last]

        manifest = ensure_run_manifest(paths)
        pending: list[StageSpec] = []
        for stage in STAGES:
            if stage.number > last:
                break
            entry = next(entry for entry in manifest.stages if entry.slug == stage.slug)
            if entry.settled:
                continue
            pending.append(stage)

        return pending

    # ------------------------------------------------------------------
    # Intake stage (Claude-driven Socratic Q&A, runs before Stage 01)
    # ------------------------------------------------------------------

    def _run_intake(self, paths: RunPaths) -> bool:
        """Run the Claude-driven intake stage.

        Uses the same operator execution pattern as ``_run_stage`` but keeps
        the first manual review pass intake-specific: the three refinement
        items are treated as user clarification questions, not stage
        improvement suggestions.

        On approval the intake summary is saved to ``intake_context.json``
        and appended to run memory so all downstream stages can see it.
        """
        stage = INTAKE_STAGE

        # Skip if intake was already approved (e.g. on resume)
        intake_stage_file = paths.stage_file(stage)
        if intake_stage_file.exists():
            self.ui.show_status("Intake already approved, skipping.", level="info")
            return True

        attempt_no = 1
        revision_feedback: str | None = None
        continue_session = False
        intake_qa_turns: list[QATurn] = []
        mark_stage_execution_started(paths, stage)

        while True:
            if attempt_no > self.max_stage_attempts:
                self.ui.show_status(
                    f"{stage.stage_title} failed after {self.max_stage_attempts} attempts. Escalating to user.",
                    level="error",
                )
                append_log_entry(paths.logs, f"{stage.slug} max_attempts_exceeded",
                                 f"Stopped after {self.max_stage_attempts} attempts.")
                return False
            self.ui.show_stage_start(stage.stage_title, attempt_no, continue_session)
            prompt = self._build_stage_prompt(paths, stage, revision_feedback, continue_session)
            append_log_entry(paths.logs, f"{stage.slug} attempt {attempt_no} prompt", prompt)

            result = self.operator.run_stage(stage, prompt, paths, attempt_no, continue_session=continue_session)
            append_log_entry(
                paths.logs,
                f"{stage.slug} attempt {attempt_no} result",
                (
                    f"success: {result.success}\n"
                    f"exit_code: {result.exit_code}\n"
                    f"session_id: {result.session_id or '(unknown)'}\n"
                    f"stage_file_path: {result.stage_file_path}\n\n"
                    "stdout:\n"
                    f"{result.stdout or '(empty)'}\n\n"
                    "stderr:\n"
                    f"{result.stderr or '(empty)'}"
                ),
            )

            # If no stage file was produced, try repair (same as regular stages)
            if not result.stage_file_path.exists():
                self.ui.show_status(
                    f"Stage summary draft missing for {stage.stage_title}. Running repair attempt...",
                    level="warn",
                )
                repair_result = self.operator.repair_stage_summary(
                    stage=stage, original_prompt=prompt,
                    original_result=result, paths=paths, attempt_no=attempt_no,
                )
                result = repair_result

            if not result.stage_file_path.exists():
                fallback_text = "\n\n".join(
                    part for part in [result.stdout, result.stderr] if part
                )
                result = self._materialize_missing_stage_draft(
                    paths=paths, stage=stage, attempt_no=attempt_no,
                    source="intake attempt and repair", fallback_text=fallback_text,
                )

            stage_markdown = read_text(result.stage_file_path)

            # Extract and display revision delta before showing the full summary
            delta = extract_revision_delta(stage_markdown)
            if delta and attempt_no >= 2:
                self.ui.show_revision_delta(delta, attempt_no)
            stage_markdown = strip_revision_delta(stage_markdown)
            write_text(result.stage_file_path, stage_markdown)

            suggestions = parse_refinement_suggestions(stage_markdown)

            if self.reviewer is None and attempt_no == 1:
                clarification_feedback, turns = self._collect_intake_clarifications(
                    paths=paths,
                    stage=stage,
                    attempt_no=attempt_no,
                    suggestions=suggestions,
                )
                intake_qa_turns.extend(turns)
                revision_feedback = clarification_feedback
                continue_session = True
                attempt_no += 1
                continue

            if self.reviewer is None:
                choice, auto_feedback = self._collect_intake_final_decision(
                    paths=paths,
                    stage=stage,
                    attempt_no=attempt_no,
                    stage_markdown=stage_markdown,
                )
            else:
                choice, auto_feedback = self._collect_review_decision(
                    paths=paths,
                    stage=stage,
                    attempt_no=attempt_no,
                    stage_markdown=stage_markdown,
                    suggestions=suggestions,
                )

            if choice in {"1", "2", "3"}:
                selected = suggestions[int(choice) - 1]
                revision_feedback = (
                    "Continue the current stage conversation and improve the existing work. "
                    "Do not discard correct completed parts. Address this refinement request:\n"
                    f"{selected}"
                )
                continue_session = True
                attempt_no += 1
                continue

            if choice == "4":
                custom_feedback = auto_feedback or self._read_multiline_feedback()
                revision_feedback = (
                    "Continue the current stage conversation and improve the existing work. "
                    "Preserve correct completed parts unless the feedback requires changing them. "
                    "Address this user feedback:\n"
                    f"{custom_feedback}"
                )
                append_log_entry(paths.logs, f"{stage.slug} attempt {attempt_no} custom_feedback", custom_feedback)
                continue_session = True
                attempt_no += 1
                continue

            if choice == "5":
                # Promote and save intake context
                final_path = paths.stage_file(stage)
                shutil.copyfile(result.stage_file_path, final_path)
                append_log_entry(
                    paths.logs,
                    f"{stage.slug} attempt {attempt_no} promoted",
                    f"Promoted intake summary.\ndraft: {result.stage_file_path}\nfinal: {final_path}",
                )
                self._save_intake_from_approved_stage(paths, stage_markdown, intake_qa_turns)
                self.ui.show_status(f"Approved {stage.stage_title}.", level="success")
                return True

            if choice == "6":
                return False

    def _collect_intake_clarifications(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        suggestions: list[str],
    ) -> tuple[str, list[QATurn]]:
        self.ui.show_status(
            (
                "Stage 0 produced an initial intake brief. Answer the clarification questions "
                "one by one; the revised brief will be shown next."
            ),
            level="info",
        )
        turns: list[QATurn] = []
        feedback_lines = [
            "Continue the intake conversation and update the intake brief using the user's clarifications.",
            "Do not ask these same Stage 0 intake questions again in the next review.",
            "Produce a revised intake brief that is ready for user approval unless a new issue is truly blocking.",
            "",
            "User clarifications:",
        ]

        for index, suggestion in enumerate(suggestions, start=1):
            parsed = parse_intake_clarification_question(suggestion)
            answer = self.ui.choose_intake_clarification_answer(
                question=parsed.question,
                options=parsed.options,
                index=index,
                total=len(suggestions),
            )
            if answer is None:
                answer_text = "Skipped as non-critical."
            else:
                answer_text = answer
            turns.append(QATurn(question=parsed.question, answer=answer_text))
            feedback_lines.extend([f"- Q: {parsed.question}", f"  A: {answer_text}"])

        extra_feedback = self.ui.read_optional_multiline_feedback(
            title="Additional Intake Guidance",
            instructions=(
                "Optionally add any extra requirement, constraint, resource note, or correction. "
                "Press Enter immediately to skip."
            ),
        )
        if extra_feedback:
            turns.append(QATurn(question="Additional intake guidance", answer=extra_feedback))
            feedback_lines.extend(["", "Additional user guidance:", extra_feedback])

        feedback = "\n".join(feedback_lines).strip()
        append_log_entry(
            paths.logs,
            f"{stage.slug} attempt {attempt_no} clarification_answers",
            feedback,
        )
        return feedback, turns

    def _collect_intake_final_decision(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        stage_markdown: str,
    ) -> tuple[str, str | None]:
        review_markdown = strip_markdown_section(
            strip_markdown_section(stage_markdown, "Suggestions for Refinement"),
            "Your Options",
        )
        self.ui.panel(
            f"{stage.stage_title} | Intake Brief",
            review_markdown.rstrip().splitlines(),
            color=self.ui.FG_BLUE,
        )
        choice = self.ui.choose_intake_final_action()
        append_log_entry(paths.logs, f"{stage.slug} attempt {attempt_no} user_choice", f"choice: {choice}")
        return choice, None

    def _save_intake_from_approved_stage(
        self,
        paths: RunPaths,
        stage_markdown: str,
        qa_transcript: list[QATurn] | None = None,
    ) -> None:
        """Persist the approved intake stage output into intake_context.json and memory."""
        existing_ctx = load_intake_context(paths)
        goal = read_text(paths.user_input).strip()
        existing_turns = existing_ctx.qa_transcript if existing_ctx else []

        # Merge: keep any pre-ingested resources, store the stage output as notes
        ctx = IntakeContext(
            goal=goal,
            original_goal=existing_ctx.original_goal if existing_ctx else goal,
            resources=existing_ctx.resources if existing_ctx else [],
            qa_transcript=[*existing_turns, *(qa_transcript or [])],
            notes=stage_markdown,
        )
        save_intake_context(paths, ctx)

        # Append intake summary to memory so downstream stages see it
        intake_text = format_intake_for_prompt(ctx)
        if intake_text:
            append_approved_stage_summary(paths.memory, INTAKE_STAGE, stage_markdown)

    # ------------------------------------------------------------------
    # Project repo bootstrap (scan existing repo → infer stage)
    # ------------------------------------------------------------------

    PROJECT_BOOTSTRAP_STAGE = StageSpec(number=-1, slug="project_bootstrap", display_name="Project Repo Bootstrap")

    def _run_project_bootstrap(self, paths: RunPaths, project_root: Path) -> StageSpec | None:
        """Scan an existing project repo and run Claude to infer project state.

        Returns the recommended start StageSpec, or None if the user aborts.
        """
        stage = self.PROJECT_BOOTSTRAP_STAGE

        if project_bootstrap_exists(paths):
            self.ui.show_status("Project bootstrap already exists, skipping scan.", level="info")
            entry = load_recommended_entry_stage(paths)
            if entry is not None:
                for s in STAGES:
                    if s.number == entry:
                        return s
            self.ui.show_status("Bootstrap entry stage metadata missing. Defaulting to Stage 01.", level="warn")
            return STAGES[0]

        self.ui.show_status(f"Scanning project repo: {project_root}", level="info")
        try:
            scan_result = scan_project(project_root)
        except (FileNotFoundError, NotADirectoryError) as exc:
            self.ui.show_status(f"Project bootstrap error: {exc}", level="error")
            return None

        self.ui.show_status(
            f"Scanned {scan_result.total_files} files. "
            f"Code: {scan_result.code_state.status}, "
            f"Experiments: {scan_result.experiment_state.status}, "
            f"Writing: {scan_result.writing_state.status}. "
            f"Heuristic entry: Stage {scan_result.recommended_entry_stage:02d}.",
            level="info",
        )
        append_log_entry(paths.logs, "project_bootstrap_start", format_scan_stats_for_log(scan_result))

        save_project_bootstrap(paths, scan_result)
        scan_prompt_section = format_project_scan_for_prompt(scan_result)

        attempt_no = 1
        revision_feedback: str | None = None
        continue_session = False

        while True:
            if attempt_no > self.max_stage_attempts:
                self.ui.show_status(
                    f"{stage.stage_title} failed after {self.max_stage_attempts} attempts. Escalating to user.",
                    level="error",
                )
                append_log_entry(paths.logs, f"project_bootstrap max_attempts_exceeded",
                                 f"Stopped after {self.max_stage_attempts} attempts.")
                return None
            self.ui.show_stage_start(stage.stage_title, attempt_no, continue_session)
            prompt = self._build_project_bootstrap_prompt(
                paths, stage, scan_prompt_section, project_root, revision_feedback, continue_session,
            )
            append_log_entry(paths.logs, f"project_bootstrap attempt {attempt_no} prompt", prompt)

            result = self.operator.run_stage(stage, prompt, paths, attempt_no, continue_session=continue_session)
            append_log_entry(
                paths.logs,
                f"project_bootstrap attempt {attempt_no} result",
                (
                    f"success: {result.success}\n"
                    f"session_id: {result.session_id or '(unknown)'}\n"
                    f"stage_file_path: {result.stage_file_path}\n\n"
                    "stdout:\n"
                    f"{result.stdout or '(empty)'}\n\n"
                    "stderr:\n"
                    f"{result.stderr or '(empty)'}"
                ),
            )

            if not result.stage_file_path.exists():
                self.ui.show_status(
                    "Project bootstrap draft missing. Running repair attempt...",
                    level="warn",
                )
                repair_result = self.operator.repair_stage_summary(
                    stage=stage, original_prompt=prompt,
                    original_result=result, paths=paths, attempt_no=attempt_no,
                )
                result = repair_result

            if not result.stage_file_path.exists():
                fallback_text = "\n\n".join(
                    part for part in [result.stdout, result.stderr] if part
                )
                result = self._materialize_missing_stage_draft(
                    paths=paths, stage=stage, attempt_no=attempt_no,
                    source="project bootstrap attempt and repair", fallback_text=fallback_text,
                )

            stage_markdown = read_text(result.stage_file_path)

            delta = extract_revision_delta(stage_markdown)
            if delta and attempt_no >= 2:
                self.ui.show_revision_delta(delta, attempt_no)
            stage_markdown = strip_revision_delta(stage_markdown)
            write_text(result.stage_file_path, stage_markdown)

            suggestions = parse_refinement_suggestions(stage_markdown)
            choice, auto_feedback = self._collect_review_decision(
                paths=paths,
                stage=stage,
                attempt_no=attempt_no,
                stage_markdown=stage_markdown,
                suggestions=suggestions,
            )

            if choice in {"1", "2", "3"}:
                selected = suggestions[int(choice) - 1]
                revision_feedback = (
                    "Continue the project bootstrap conversation and improve the stage assessments. "
                    "Do not discard correct parts. Address this refinement request:\n"
                    f"{selected}"
                )
                continue_session = True
                attempt_no += 1
                continue

            if choice == "4":
                custom_feedback = auto_feedback or self._read_multiline_feedback()
                revision_feedback = (
                    "Continue the project bootstrap conversation and improve the stage assessments. "
                    "Preserve correct parts unless the feedback requires changing them. "
                    "Address this user feedback:\n"
                    f"{custom_feedback}"
                )
                append_log_entry(paths.logs, f"project_bootstrap attempt {attempt_no} custom_feedback", custom_feedback)
                continue_session = True
                attempt_no += 1
                continue

            if choice == "5":
                final_path = paths.stage_file(stage)
                shutil.copyfile(result.stage_file_path, final_path)
                append_log_entry(
                    paths.logs,
                    "project_bootstrap_promoted",
                    f"Promoted project bootstrap summary.\ndraft: {result.stage_file_path}\nfinal: {final_path}",
                )
                corrected_assessments = load_stage_assessments(paths) or scan_result.stage_assessments
                entry_stage_num = recommend_entry_stage(corrected_assessments)
                save_recommended_entry_stage(paths, entry_stage_num)
                self._adopt_project_bootstrap_baseline(paths, corrected_assessments, entry_stage_num)
                append_log_entry(paths.logs, "project_bootstrap_approved", "Project bootstrap approved.")
                self.ui.show_status("Approved project bootstrap.", level="success")

                for s in STAGES:
                    if s.number == entry_stage_num:
                        self.ui.show_status(
                            f"Starting from {s.stage_title} based on project bootstrap.",
                            level="info",
                        )
                        return s
                return STAGES[0]

            if choice == "6":
                return None

    # ------------------------------------------------------------------
    # Bootstrap stage (paper corpus → researcher profile)
    # ------------------------------------------------------------------

    BOOTSTRAP_STAGE = StageSpec(number=-1, slug="bootstrap", display_name="Paper Corpus Bootstrap")

    def _run_bootstrap(self, paths: RunPaths, corpus_path: Path) -> bool:
        """Scan the user's paper corpus and run Claude to extract a researcher profile.

        Uses the same operator + approval loop so the user can review and refine
        the extracted profile before downstream stages use it as context.
        """
        stage = self.BOOTSTRAP_STAGE

        if bootstrap_profile_exists(paths):
            self.ui.show_status("Bootstrap profile already exists, skipping.", level="info")
            return True

        self.ui.show_status(f"Scanning paper corpus: {corpus_path}", level="info")
        try:
            corpus_manifest = scan_corpus(corpus_path)
        except (FileNotFoundError, NotADirectoryError) as exc:
            self.ui.show_status(f"Bootstrap error: {exc}", level="error")
            return False

        if not corpus_manifest.papers:
            self.ui.show_status("No extractable files found in paper corpus. Skipping bootstrap.", level="warn")
            return True

        stats = corpus_manifest.stats
        self.ui.show_status(
            f"Found {stats['total_papers']} paper(s), {stats['unique_references']} unique references. "
            f"Running profile extraction...",
            level="info",
        )
        append_log_entry(paths.logs, "bootstrap_start", format_corpus_stats_for_log(corpus_manifest))

        corpus_prompt_section = format_corpus_for_prompt(corpus_manifest)

        attempt_no = 1
        revision_feedback: str | None = None
        continue_session = False

        while True:
            if attempt_no > self.max_stage_attempts:
                self.ui.show_status(
                    f"{stage.stage_title} failed after {self.max_stage_attempts} attempts. Escalating to user.",
                    level="error",
                )
                append_log_entry(paths.logs, f"bootstrap max_attempts_exceeded",
                                 f"Stopped after {self.max_stage_attempts} attempts.")
                return False
            self.ui.show_stage_start(stage.stage_title, attempt_no, continue_session)
            prompt = self._build_bootstrap_prompt(paths, stage, corpus_prompt_section, revision_feedback, continue_session)
            append_log_entry(paths.logs, f"bootstrap attempt {attempt_no} prompt", prompt)

            result = self.operator.run_stage(stage, prompt, paths, attempt_no, continue_session=continue_session)
            append_log_entry(
                paths.logs,
                f"bootstrap attempt {attempt_no} result",
                (
                    f"success: {result.success}\n"
                    f"session_id: {result.session_id or '(unknown)'}\n"
                    f"stage_file_path: {result.stage_file_path}\n\n"
                    "stdout:\n"
                    f"{result.stdout or '(empty)'}\n\n"
                    "stderr:\n"
                    f"{result.stderr or '(empty)'}"
                ),
            )

            if not result.stage_file_path.exists():
                self.ui.show_status(
                    "Bootstrap summary draft missing. Running repair attempt...",
                    level="warn",
                )
                repair_result = self.operator.repair_stage_summary(
                    stage=stage, original_prompt=prompt,
                    original_result=result, paths=paths, attempt_no=attempt_no,
                )
                result = repair_result

            if not result.stage_file_path.exists():
                fallback_text = "\n\n".join(
                    part for part in [result.stdout, result.stderr] if part
                )
                result = self._materialize_missing_stage_draft(
                    paths=paths, stage=stage, attempt_no=attempt_no,
                    source="bootstrap attempt and repair", fallback_text=fallback_text,
                )

            stage_markdown = read_text(result.stage_file_path)

            suggestions = parse_refinement_suggestions(stage_markdown)
            choice, auto_feedback = self._collect_review_decision(
                paths=paths,
                stage=stage,
                attempt_no=attempt_no,
                stage_markdown=stage_markdown,
                suggestions=suggestions,
            )

            if choice in {"1", "2", "3"}:
                selected = suggestions[int(choice) - 1]
                revision_feedback = (
                    "Continue the bootstrap conversation and improve the researcher profile. "
                    "Do not discard correct completed parts. Address this refinement request:\n"
                    f"{selected}"
                )
                continue_session = True
                attempt_no += 1
                continue

            if choice == "4":
                custom_feedback = auto_feedback or self._read_multiline_feedback()
                revision_feedback = (
                    "Continue the bootstrap conversation and improve the researcher profile. "
                    "Preserve correct parts unless the feedback requires changing them. "
                    "Address this user feedback:\n"
                    f"{custom_feedback}"
                )
                append_log_entry(paths.logs, f"bootstrap attempt {attempt_no} custom_feedback", custom_feedback)
                continue_session = True
                attempt_no += 1
                continue

            if choice == "5":
                missing_artifacts = missing_bootstrap_profile_artifacts(paths)
                if missing_artifacts:
                    missing_block = "\n".join(f"- {path}" for path in missing_artifacts)
                    append_log_entry(
                        paths.logs,
                        "bootstrap_missing_artifacts",
                        missing_block,
                    )
                    self.ui.show_status(
                        "Bootstrap profile artifacts are incomplete. Continuing refinement.",
                        level="warn",
                    )
                    revision_feedback = (
                        "Continue the bootstrap conversation and complete the missing profile artifacts. "
                        "Do not discard correct completed artifacts. Write the missing files and refresh the stage summary.\n"
                        f"Missing artifacts:\n{missing_block}"
                    )
                    continue_session = True
                    attempt_no += 1
                    continue

                final_path = paths.stage_file(stage)
                shutil.copyfile(result.stage_file_path, final_path)
                append_log_entry(paths.logs, "bootstrap_approved", "Bootstrap profile approved.")
                append_log_entry(
                    paths.logs,
                    "bootstrap_promoted",
                    f"Promoted bootstrap summary.\ndraft: {result.stage_file_path}\nfinal: {final_path}",
                )
                self.ui.show_status("Approved bootstrap profile.", level="success")
                return True

            if choice == "6":
                return False

    def _adopt_project_bootstrap_baseline(
        self,
        paths: RunPaths,
        assessments,
        entry_stage_num: int,
    ) -> None:
        if entry_stage_num <= 1:
            return

        artifact_paths = self._project_bootstrap_artifact_paths(paths)
        assessments_by_number = {assessment.stage_number: assessment for assessment in assessments}

        for stage in STAGES:
            if stage.number >= entry_stage_num:
                break
            stage_markdown = self._bootstrap_stage_markdown(
                paths,
                stage,
                assessments_by_number.get(stage.number),
                artifact_paths,
            )
            write_text(paths.stage_file(stage), stage_markdown)
            append_approved_stage_summary(paths.memory, stage, stage_markdown)
            mark_stage_approved_manifest(paths, stage, 0, self._stage_file_paths(stage_markdown))
            write_stage_handoff(paths, stage, stage_markdown)

    def _project_bootstrap_artifact_paths(self, paths: RunPaths) -> list[str]:
        artifact_paths: list[str] = []
        for filename in ("bootstrap_summary.md", "stage_assessments.json", "scan_metadata.json"):
            path = paths.bootstrap_dir / filename
            if path.exists():
                artifact_paths.append(str(path.relative_to(paths.run_root)).replace("\\", "/"))
        return artifact_paths

    def _bootstrap_stage_markdown(
        self,
        paths: RunPaths,
        stage: StageSpec,
        assessment,
        artifact_paths: list[str],
    ) -> str:
        prior = approved_stage_summaries(read_text(paths.memory))
        stage_file_path = str(paths.stage_file(stage).relative_to(paths.run_root)).replace("\\", "/")
        files_produced = [f"- `{stage_file_path}`"] + [f"- `{path}`" for path in artifact_paths]
        evidence_lines = ["- No specific bootstrap evidence recorded."]
        status_line = "Bootstrap carry-forward status: unspecified."
        if assessment is not None:
            status_line = (
                f"Bootstrap carry-forward status: {assessment.status} "
                f"(confidence: {assessment.confidence})."
            )
            if assessment.evidence:
                evidence_lines = [f"- {item}" for item in assessment.evidence]
        suggestions = "\n".join(
            f"{index}. {text}"
            for index, text in enumerate(DEFAULT_REFINEMENT_SUGGESTIONS, start=1)
        )
        options = "\n".join(FIXED_STAGE_OPTIONS)
        evidence_block = "\n".join(evidence_lines)
        files_block = "\n".join(files_produced)

        return (
            f"# Stage {stage.number:02d}: {stage.display_name}\n\n"
            "## Objective\n"
            f"Carry forward the pre-existing project state for {stage.display_name} from the approved project bootstrap.\n\n"
            "## Previously Approved Stage Summaries\n"
            f"{prior}\n\n"
            "## What I Did\n"
            "- Reviewed the approved project bootstrap artifacts for this repository.\n"
            "- Recorded the prior state of this stage instead of rerunning it from scratch.\n\n"
            "## Key Results\n"
            f"- {status_line}\n"
            "- This stage is being accepted as prior project context before continuing downstream AutoR stages.\n"
            f"{evidence_block}\n\n"
            "## Files Produced\n"
            f"{files_block}\n\n"
            "## Suggestions for Refinement\n"
            f"{suggestions}\n\n"
            "## Your Options\n"
            f"{options}\n"
        )

    def _build_project_bootstrap_prompt(
        self,
        paths: RunPaths,
        stage: StageSpec,
        scan_text: str,
        project_root: Path,
        revision_feedback: str | None,
        continue_session: bool,
    ) -> str:
        template = load_prompt_template(self.prompt_dir, stage, output_format=selected_output_format(paths))
        stage_template = format_stage_template(template, stage, paths)

        if continue_session:
            return build_continuation_prompt(
                stage, stage_template, paths,
                handoff_context="",
                revision_feedback=revision_feedback,
            )

        user_request = read_text(paths.user_input)
        project_section = (
            f"# Existing Project Repository\n\n"
            f"**Project root:** `{project_root}`\n\n"
            f"{scan_text}"
        )

        sections = [
            "# Stage Instructions",
            stage_template.strip(),
            "# Required Stage Summary Format",
            (
                "You must create or overwrite the stage summary markdown file using exactly the "
                "top-level heading order below. Do not omit any section. Use exactly 3 numbered "
                "refinement suggestions and exactly the fixed 6 option lines."
            ),
            "```md\n" + required_stage_output_template(stage).strip() + "\n```",
            "# Original User Request",
            user_request.strip(),
            project_section,
            "# Revision Feedback",
            revision_feedback.strip() if revision_feedback else "None.",
        ]
        return "\n\n".join(sections).strip() + "\n"

    def _build_bootstrap_prompt(
        self,
        paths: RunPaths,
        stage: StageSpec,
        corpus_text: str,
        revision_feedback: str | None,
        continue_session: bool,
    ) -> str:
        """Build the prompt for the bootstrap stage."""
        template = load_prompt_template(self.prompt_dir, stage, output_format=selected_output_format(paths))
        stage_template = format_stage_template(template, stage, paths)

        if continue_session:
            return build_continuation_prompt(
                stage, stage_template, paths,
                handoff_context="",
                revision_feedback=revision_feedback,
            )

        user_request = read_text(paths.user_input)
        corpus_section = f"# User's Paper Corpus\n\n{corpus_text}"

        sections = [
            "# Stage Instructions",
            stage_template.strip(),
            "# Required Stage Summary Format",
            (
                "You must create or overwrite the stage summary markdown file using exactly the "
                "top-level heading order below. Do not omit any section. Use exactly 3 numbered "
                "refinement suggestions and exactly the fixed 6 option lines."
            ),
            "```md\n" + required_stage_output_template(stage).strip() + "\n```",
            "# Original User Request",
            user_request.strip(),
            corpus_section,
            "# Revision Feedback",
            revision_feedback.strip() if revision_feedback else "None.",
        ]
        return "\n\n".join(sections).strip() + "\n"

    # ------------------------------------------------------------------
    # Regular stages (01–08)
    # ------------------------------------------------------------------

    def _run_stage(self, paths: RunPaths, stage: StageSpec) -> bool:
        attempt_no = read_attempt_count(paths, stage) + 1
        loop_attempts = 0
        # Polish rounds are AutoR improving work that already passed validation, so
        # they are counted separately from `--max-attempts`, which bounds a stage
        # that is *failing*. Charging them to the same budget would make a stage
        # that is being made better look like one that is thrashing, and would
        # leave nothing for the repair path if a later round did break something.
        #
        # Read from disk rather than started at zero: the attempt number is run-wide
        # and a stage can be entered more than once, so a per-entry counter would
        # under-report retries on the second visit.
        polish_rounds = read_polish_count(paths, stage)
        entry_polish_rounds = polish_rounds
        is_polish_round = False
        if self.evolution is not None:
            self.evolution.begin_stage(paths, stage)
        revision_feedback: str | None = None
        continue_session = False
        last_validation_errors: list[str] = []
        mark_stage_execution_started(paths, stage)

        # Optional pre-loaded revision feedback. The Studio (or any other
        # caller) can drop a "<slug>.pending_feedback.txt" file under
        # operator_state/ to inject feedback into the FIRST attempt of this
        # stage's prompt instead of waiting for choose_action() on attempt 2.
        # Strictly opt-in: if the file is absent, behavior is unchanged from
        # the CLI flow.
        pending_fb_path = paths.operator_state_dir / f"{stage.slug}.pending_feedback.txt"
        if pending_fb_path.exists():
            try:
                custom_feedback = pending_fb_path.read_text(encoding="utf-8").strip()
            except Exception:
                custom_feedback = ""
            if custom_feedback:
                revision_feedback = (
                    "Continue the current stage conversation and improve the existing work. "
                    "Preserve correct completed parts unless the feedback requires changing them. "
                    "Address this user feedback:\n"
                    f"{custom_feedback}"
                )
                # If we have a prior session id, continue it so Claude has
                # the existing draft as context. Otherwise start fresh.
                continue_session = paths.stage_session_file(stage).exists()
                append_log_entry(
                    paths.logs,
                    f"{stage.slug} pending_feedback_loaded",
                    custom_feedback,
                )
            try:
                pending_fb_path.unlink()
            except Exception:
                pass

        while True:
            if loop_attempts - (polish_rounds - entry_polish_rounds) >= self.max_stage_attempts:
                error = (
                    f"Exceeded {self.max_stage_attempts} attempts in the current stage run. "
                    f"Last validation errors: {'; '.join(last_validation_errors) or 'None recorded.'}"
                )
                self.ui.show_status(
                    f"{stage.stage_title} failed after {self.max_stage_attempts} attempts in this run.",
                    level="error",
                )
                append_log_entry(
                    paths.logs,
                    f"{stage.slug} max_attempts_exceeded",
                    error,
                )
                mark_stage_failed_manifest(paths, stage, error)
                return self._handle_stage_exhaustion(
                    paths=paths,
                    stage=stage,
                    attempt_no=max(attempt_no - 1, 1),
                    last_validation_errors=last_validation_errors,
                )
            loop_attempts += 1
            # The manifest's `attempt_count` means "how many tries did this stage
            # need" — a diagnostic for a gate the operator could not clear, and what
            # `test_no_stage_needed_a_retry` reads to notice a new artifact gate that
            # fake mode was never taught to satisfy. A polish round is not a try that
            # failed, so it does not count here; the improvement ledger owns that
            # accounting. Feeding both numbers into one field would leave neither
            # question answerable.
            mark_stage_running_manifest(paths, stage, attempt_no - polish_rounds)
            write_attempt_count(paths, stage, attempt_no)
            self._print(f"\nRunning {stage.stage_title} (attempt {attempt_no})...")
            prompt = self._build_stage_prompt(paths, stage, revision_feedback, continue_session,
                                             attempt_no=attempt_no,
                                             previous_validation_errors=last_validation_errors or None)
            append_log_entry(
                paths.logs,
                f"{stage.slug} attempt {attempt_no} prompt",
                prompt,
            )

            result = self.operator.run_stage(
                stage,
                prompt,
                paths,
                attempt_no,
                continue_session=continue_session,
            )
            if result.session_id:
                sync_stage_session_id(paths, stage, result.session_id)
            append_log_entry(
                paths.logs,
                f"{stage.slug} attempt {attempt_no} result",
                (
                    f"success: {result.success}\n"
                    f"exit_code: {result.exit_code}\n"
                    f"session_id: {result.session_id or '(unknown)'}\n"
                    f"stage_file_path: {result.stage_file_path}\n"
                    f"final_stage_file_path: {paths.stage_file(stage)}\n\n"
                    "stdout:\n"
                    f"{result.stdout or '(empty)'}\n\n"
                    "stderr:\n"
                    f"{result.stderr or '(empty)'}"
                ),
            )

            if not result.stage_file_path.exists():
                self.ui.show_status(
                    f"Stage summary draft missing for {stage.stage_title}. Running repair attempt...",
                    level="warn",
                )
                append_log_entry(
                    paths.logs,
                    f"{stage.slug} attempt {attempt_no} repair_triggered",
                    "Primary attempt did not produce stage summary draft. Triggering repair pass.",
                )
                repair_result = self.operator.repair_stage_summary(
                    stage=stage,
                    original_prompt=prompt,
                    original_result=result,
                    paths=paths,
                    attempt_no=attempt_no,
                )
                append_log_entry(
                    paths.logs,
                    f"{stage.slug} attempt {attempt_no} repair_result",
                    (
                        f"success: {repair_result.success}\n"
                        f"exit_code: {repair_result.exit_code}\n"
                        f"stage_file_path: {repair_result.stage_file_path}\n\n"
                        "stdout:\n"
                        f"{repair_result.stdout or '(empty)'}\n\n"
                        "stderr:\n"
                        f"{repair_result.stderr or '(empty)'}"
                    ),
                )
                result = repair_result

            if not result.stage_file_path.exists():
                mark_stage_failed_manifest(paths, stage, "stage_summary_missing")
                fallback_text = "\n\n".join(
                    part for part in [result.stdout, result.stderr] if part
                )
                result = self._materialize_missing_stage_draft(
                    paths=paths,
                    stage=stage,
                    attempt_no=attempt_no,
                    source="primary attempt and repair",
                    fallback_text=fallback_text,
                )

            stage_markdown = read_text(result.stage_file_path)
            # Extract revision delta before validation (not a required section)
            revision_delta = extract_revision_delta(stage_markdown)
            stage_markdown = strip_revision_delta(stage_markdown)
            write_text(result.stage_file_path, stage_markdown)
            if stage.slug == "02_hypothesis_generation":
                write_hypothesis_manifest(paths, stage_markdown)
                self._amend_preregistration(
                    paths, "Stage 02 was re-run and rewrote the hypothesis manifest."
                )
            if stage.slug == "07_writing":
                self._generate_writing_review(paths)
            validation_errors = validate_stage_markdown(stage_markdown, stage=stage, paths=paths, artifact_roots=self.artifact_roots) + validate_stage_artifacts(stage, paths, self.artifact_dirs)
            if validation_errors:
                mark_stage_failed_manifest(paths, stage, "; ".join(validation_errors))
                self._print(
                    f"Stage summary for {stage.stage_title} was incomplete. Running repair attempt..."
                )
                append_log_entry(
                    paths.logs,
                    f"{stage.slug} attempt {attempt_no} validation_failed",
                    "\n".join(validation_errors),
                )
                repair_result = self.operator.repair_stage_summary(
                    stage=stage,
                    original_prompt=prompt,
                    original_result=result,
                    paths=paths,
                    attempt_no=attempt_no,
                )
                append_log_entry(
                    paths.logs,
                    f"{stage.slug} attempt {attempt_no} repair_result",
                    (
                        f"success: {repair_result.success}\n"
                        f"exit_code: {repair_result.exit_code}\n"
                        f"stage_file_path: {repair_result.stage_file_path}\n\n"
                        "stdout:\n"
                        f"{repair_result.stdout or '(empty)'}\n\n"
                        "stderr:\n"
                        f"{repair_result.stderr or '(empty)'}"
                    ),
                )

                if not repair_result.stage_file_path.exists():
                    fallback_text = "\n\n".join(
                        part
                        for part in [result.stdout, result.stderr, repair_result.stdout, repair_result.stderr]
                        if part
                    )
                    repair_result = self._materialize_missing_stage_draft(
                        paths=paths,
                        stage=stage,
                        attempt_no=attempt_no,
                        source="validation repair",
                        fallback_text=fallback_text,
                    )

                stage_markdown = read_text(repair_result.stage_file_path)
                revision_delta = extract_revision_delta(stage_markdown)
                stage_markdown = strip_revision_delta(stage_markdown)
                write_text(repair_result.stage_file_path, stage_markdown)
                if stage.slug == "02_hypothesis_generation":
                    write_hypothesis_manifest(paths, stage_markdown)
                    self._amend_preregistration(
                        paths, "Stage 02 was re-run and rewrote the hypothesis manifest."
                    )
                if stage.slug == "07_writing":
                    self._generate_writing_review(paths)
                validation_errors = validate_stage_markdown(stage_markdown, stage=stage, paths=paths, artifact_roots=self.artifact_roots) + validate_stage_artifacts(stage, paths, self.artifact_dirs)
                if validation_errors:
                    self.ui.show_status(
                        f"Repair output for {stage.stage_title} is still incomplete. Normalizing locally...",
                        level="warn",
                    )
                    normalized_markdown = canonicalize_stage_markdown(
                        stage=stage,
                        memory_text=read_text(paths.memory),
                        markdown=stage_markdown,
                        fallback_text="\n\n".join(
                            part for part in [result.stdout, result.stderr, repair_result.stdout, repair_result.stderr] if part
                        ),
                        stage_output_path=str(repair_result.stage_file_path.relative_to(paths.run_root)).replace("\\", "/"),
                    )
                    write_text(repair_result.stage_file_path, normalized_markdown)
                    append_log_entry(
                        paths.logs,
                        f"{stage.slug} attempt {attempt_no} local_normalization",
                        (
                            "Applied local stage markdown normalization after repair remained invalid.\n\n"
                            "Previous validation errors:\n"
                            + "\n".join(f"- {problem}" for problem in validation_errors)
                            + "\n\nNormalized markdown preview:\n"
                            + truncate_text(normalized_markdown, max_chars=6000)
                        ),
                    )

                    stage_markdown = read_text(repair_result.stage_file_path)
                    if stage.slug == "02_hypothesis_generation":
                        write_hypothesis_manifest(paths, stage_markdown)
                        self._amend_preregistration(
                            paths, "Stage 02 was re-run and rewrote the hypothesis manifest."
                        )
                    validation_errors = validate_stage_markdown(stage_markdown, stage=stage, paths=paths, artifact_roots=self.artifact_roots) + validate_stage_artifacts(stage, paths, self.artifact_dirs)
                    if validation_errors:
                        append_log_entry(
                            paths.logs,
                            f"{stage.slug} attempt {attempt_no} local_normalization_failed",
                            (
                                "Local normalization remained invalid. Re-running current stage from scratch.\n\n"
                                + "\n".join(f"- {problem}" for problem in validation_errors)
                            ),
                        )
                        self._print(
                            f"Local normalization for {stage.stage_title} is still incomplete. Re-running the stage..."
                        )
                        revision_feedback = (
                            "Continue the current stage conversation and fix the invalid stage summary. "
                            "Keep all correct work already completed, but produce a fully complete stage summary "
                            "with no placeholder markers and ensure every required section is substantively filled."
                        )
                        last_validation_errors = list(validation_errors)
                        continue_session = True
                        attempt_no += 1
                        continue

                result = repair_result

            stage_markdown = read_text(result.stage_file_path)

            # The draft is valid. Measure it, and decide whether it may stand.
            if self.evolution is not None and self.evolution.config.applies_to(stage):
                outcome = self.evolution.consider(
                    paths=paths,
                    stage=stage,
                    attempt_no=attempt_no,
                    draft_path=result.stage_file_path,
                    is_polish_round=is_polish_round,
                )
                if outcome.reverted:
                    # `consider` wrote the champion back over the draft; everything
                    # downstream — review, promotion, handoff — has to read the
                    # draft that is now on disk rather than the one that lost.
                    stage_markdown = read_text(result.stage_file_path)
                self.ui.show_status(
                    f"{stage.stage_title} attempt {attempt_no}: {outcome.note} "
                    f"[{outcome.score.total:.3f}]",
                    level="success" if outcome.improved else "info",
                )
                if self.evolution.should_continue(paths, stage):
                    directive = self.evolution.next_directive(paths, stage)
                    if directive:
                        self.evolution.begin_round(paths, stage)
                        polish_rounds += 1
                        write_polish_count(paths, stage, polish_rounds)
                        is_polish_round = True
                        revision_feedback = directive
                        continue_session = True
                        attempt_no += 1
                        continue

            # Anything from here is a human or reviewer decision, so the next
            # attempt it produces is directed rather than self-initiated.
            is_polish_round = False
            mark_stage_human_review_manifest(
                paths,
                stage,
                attempt_no - polish_rounds,
                self._stage_file_paths(stage_markdown),
            )
            append_log_entry(
                paths.logs,
                f"{stage.slug} attempt {attempt_no} awaiting_human_review",
                (
                    "Validated stage summary draft is ready for human review.\n"
                    f"draft: {result.stage_file_path}"
                ),
            )

            if revision_delta and attempt_no >= 2:
                self.ui.show_revision_delta(revision_delta, attempt_no)
            suggestions = parse_refinement_suggestions(stage_markdown)
            choice, auto_feedback = self._collect_review_decision(
                paths=paths,
                stage=stage,
                attempt_no=attempt_no,
                stage_markdown=stage_markdown,
                suggestions=suggestions,
            )

            if choice in {"1", "2", "3"}:
                selected = suggestions[int(choice) - 1]
                revision_feedback = (
                    "Continue the current stage conversation and improve the existing work. "
                    "Do not discard correct completed parts. Address this refinement request:\n"
                    f"{selected}"
                )
                continue_session = True
                attempt_no += 1
                continue

            if choice == "4":
                if auto_feedback is not None:
                    custom_feedback = auto_feedback
                else:
                    while True:
                        custom_feedback = self._read_multiline_feedback()
                        if not custom_feedback.strip().startswith("/"):
                            break
                        control_handled = self._handle_stage_control_command(
                            paths=paths,
                            stage=stage,
                            attempt_no=attempt_no,
                            command_text=custom_feedback,
                        )
                        if control_handled is not None:
                            return control_handled
                revision_feedback = (
                    "Continue the current stage conversation and improve the existing work. "
                    "Preserve correct completed parts unless the feedback requires changing them. "
                    "Address this user feedback:\n"
                    f"{custom_feedback}"
                )
                append_log_entry(
                    paths.logs,
                    f"{stage.slug} attempt {attempt_no} custom_feedback",
                    custom_feedback,
                )
                continue_session = True
                attempt_no += 1
                continue

            if choice == "5":
                final_stage_path = paths.stage_file(stage)
                shutil.copyfile(result.stage_file_path, final_stage_path)
                append_log_entry(
                    paths.logs,
                    f"{stage.slug} attempt {attempt_no} promoted",
                    (
                        "Promoted validated stage summary draft to final stage file after approval.\n"
                        f"draft: {result.stage_file_path}\n"
                        f"final: {final_stage_path}"
                    ),
                )
                append_approved_stage_summary(paths.memory, stage, stage_markdown)
                mark_stage_approved_manifest(
                    paths,
                    stage,
                    attempt_no - polish_rounds,
                    self._stage_file_paths(stage_markdown),
                )
                if stage.slug == "02_hypothesis_generation":
                    self._measure_pool_adoption(paths, stage, stage_markdown)
                if stage.slug == "04_implementation":
                    self._freeze_preregistration(paths)
                self._run_validity_review(paths, stage, stage_markdown)
                if stage.number == ROUND_CLOSING_STAGE_NUMBER:
                    self._close_round(paths, stage)
                if stage.slug == "07_writing":
                    output_format = selected_output_format(paths)
                    if self._research_diagram:
                        self.ui.show_status("Generating method illustration diagram...", level="info")
                        try:
                            diagram_path = post_writing_diagram_hook(
                                paths.run_root, output_format=output_format
                            )
                            if diagram_path:
                                append_log_entry(
                                    paths.logs,
                                    f"{stage.slug} research_diagram",
                                    f"Generated method illustration: {diagram_path}",
                                )
                                self.ui.show_status(f"Method diagram saved to {diagram_path}", level="success")
                            else:
                                append_log_entry(
                                    paths.logs,
                                    f"{stage.slug} research_diagram",
                                    "Diagram generation returned None (check logs for details).",
                                )
                                self.ui.show_status("Diagram generation did not produce output.", level="warn")
                        except Exception as exc:
                            append_log_entry(
                                paths.logs,
                                f"{stage.slug} research_diagram_error",
                                f"Diagram generation failed: {exc}",
                            )
                            self.ui.show_status(f"Diagram generation failed: {exc}", level="warn")
                    # The paper package is a LaTeX submission bundle. In markdown mode the
                    # deliverable is report/report.md, and emitting a stub manuscript.tex and a
                    # placeholder paper.pdf beside it would only invite a reader to grade the
                    # wrong artifact.
                    if output_format == "latex":
                        package = generate_paper_package(paths.run_root)
                        append_log_entry(
                            paths.logs,
                            f"{stage.slug} paper_package",
                            package.summary,
                        )
                    else:
                        review = self._generate_writing_review(paths)
                        append_log_entry(
                            paths.logs,
                            f"{stage.slug} report_review",
                            (
                                f"Markdown report finalized at {paths.report_file}\n"
                                f"status: {review.get('overall_status')}\n"
                                f"referenced figures: {review.get('referenced_image_count')}\n"
                                f"characters: {review.get('report_char_count')}"
                            ),
                        )
                elif stage.slug == "08_dissemination":
                    package = generate_release_package(paths.run_root)
                    append_log_entry(
                        paths.logs,
                        f"{stage.slug} release_package",
                        package.summary,
                    )
                write_stage_handoff(paths, stage, stage_markdown)
                write_artifact_index(paths)
                write_experiment_manifest(paths)
                append_log_entry(
                    paths.logs,
                    f"{stage.slug} approved",
                    (
                        "Stage approved and appended to memory.\n"
                        f"Updated artifact index: {paths.artifact_index}\n"
                        f"Updated experiment manifest: {paths.experiment_manifest}"
                    ),
                )
                self.ui.show_status(f"Approved {stage.stage_title}.", level="success")
                return True

            if choice == "6":
                update_manifest_run_status(
                    paths,
                    run_status="cancelled",
                    last_event="run.cancelled",
                    current_stage_slug=stage.slug,
                )
                return False

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _build_stage_prompt(
        self,
        paths: RunPaths,
        stage: StageSpec,
        revision_feedback: str | None,
        continue_session: bool,
        attempt_no: int = 1,
        previous_validation_errors: list[str] | None = None,
    ) -> str:
        output_format = selected_output_format(paths)
        template = load_prompt_template(self.prompt_dir, stage, output_format=output_format)
        # Shared rules are composed in before substitution, so a fragment can use
        # the same placeholder vocabulary as the templates without introducing a
        # token of its own.
        composed = compose_stage_template(template, stage, output_format)
        stage_template = format_stage_template(composed, stage, paths)
        handoff_context = build_handoff_context(paths, upto_stage=stage)

        # A run can arrive at Stage 05 without ever passing through Stage 04's
        # approval — resume, --redo-stage, or a --project-root bootstrap that
        # entered above Stage 02. Freeze here too, so the hypotheses are fixed
        # before results exist on every route in.
        if stage.number >= 5:
            self._freeze_preregistration(paths)

        # No hypotheses at all is a different problem from unfrozen ones, and
        # the stage that first needs them is the one that has to fix it.
        if stage.number >= 3 and not paths.hypothesis_manifest.exists():
            stage_template = (
                stage_template.rstrip()
                + "\n\n# Missing Hypotheses (resolve before anything else)\n\n"
                "This run has no hypotheses on record: Stage 02 did not run, most likely "
                "because the run was adopted from an existing project. Adopting a codebase "
                "does not adopt a research question.\n\n"
                "Before doing this stage's own work, write "
                f"`{paths.hypothesis_manifest.resolve()}` in the Stage 02 format: typed "
                "`theoretical_propositions`, `empirical_hypotheses` and `paper_claims` "
                "entries, each with `id` and `statement`, and every empirical hypothesis "
                "carrying a `decision_rule` stating in advance what would count as support "
                "and what would count as refutation. Derive them from the goal and the "
                "existing project; do not invent a hypothesis the work is not testing.\n"
            )
        stage_template = (
            stage_template.rstrip()
            + "\n\n## Run Configuration\n\n"
            + format_venue_for_prompt(paths)
            + "\n"
        )
        artifact_index = write_artifact_index(paths)
        stage_template = (
            stage_template.rstrip()
            + "\n\n## Structured Artifact Index\n\n"
            + f"Run-wide artifact index: `{paths.artifact_index.resolve()}`\n\n"
            + format_artifact_index_for_prompt(artifact_index)
            + "\n"
        )
        if stage.number >= 5:
            experiment_manifest = write_experiment_manifest(paths)
            stage_template = (
                stage_template.rstrip()
                + "\n\n## Experiment Bundle Manifest\n\n"
                + f"Standard experiment manifest: `{paths.experiment_manifest.resolve()}`\n\n"
                + format_experiment_manifest_for_prompt(experiment_manifest)
                + "\n"
            )
        if stage.slug == "00_intake":
            ctx = load_intake_context(paths)
            if ctx and ctx.resources:
                stage_template = (
                    stage_template.rstrip()
                    + "\n\n## Pre-Loaded Resources (already in workspace)\n\n"
                    + format_resources_for_intake_prompt(ctx.resources)
                    + "\n"
                )
        if stage.slug == "02_hypothesis_generation" and self.ideation_panel is not None:
            stage_template = (
                stage_template.rstrip()
                + "\n\n## Candidate Hypothesis Pool\n\n"
                + self._build_idea_pool(paths, stage, attempt_no)
                + "\n"
            )
        if stage.slug == "07_writing":
            manifest = build_writing_manifest(paths)
            stage_template = (
                stage_template.rstrip()
                + "\n\n## Writing Manifest\n\n"
                + format_manifest_for_prompt(manifest)
                + "\n"
            )

        # Inject bootstrap researcher profile if available (stage-specific)
        profile_text = format_profile_for_prompt(paths, stage_slug=stage.slug)
        if profile_text and stage.number >= 1:
            stage_template = (
                stage_template.rstrip()
                + "\n\n# Researcher Profile (from paper corpus bootstrap)\n\n"
                + profile_text
                + "\n"
            )

        # Inject accumulated decision ledger from prior stages
        ledger_context = build_decision_ledger_context(paths, upto_stage=stage)
        if ledger_context and stage.number >= 2:
            stage_template = (
                stage_template.rstrip()
                + "\n\n# Decision Ledger (from prior stages)\n\n"
                "The following decisions, assumptions, and open questions were recorded in earlier stages. "
                "Respect locked decisions and accepted assumptions. Address open questions when relevant.\n\n"
                + ledger_context
                + "\n"
            )

        hypothesis_context = build_hypothesis_context(paths)
        if hypothesis_context and stage.number >= 3:
            stage_template = (
                stage_template.rstrip()
                + "\n\n# Hypothesis Context (from Stage 02)\n\n"
                "The following typed claims were approved in Stage 02.\n"
                "- Treat **Theoretical Propositions** as accepted premises rather than direct experimental targets.\n"
                "- Treat **Empirical Hypotheses** as the claims that downstream implementation, experimentation, and analysis should test.\n"
                "- Treat **Paper Claims (Provisional)** as narrative framing only until evidence supports them.\n\n"
                + hypothesis_context
                + "\n"
            )

        # From Stage 05 on, the frozen preregistration supersedes the Stage 02
        # context above as the thing the run is accountable to. It is injected
        # separately and worded as a constraint rather than as background,
        # because the whole point is that it cannot be renegotiated.
        prereg = load_preregistration(paths)
        if prereg is not None and stage.number >= 5:
            stage_template = (
                stage_template.rstrip()
                + "\n\n# Preregistered Hypotheses (frozen — not editable)\n\n"
                + format_preregistration_for_prompt(prereg)
                + "\n"
            )
        rounds_context = format_rounds_for_prompt(paths)
        if rounds_context and stage.number >= 2:
            stage_template = (
                stage_template.rstrip()
                + "\n\n# Earlier Research Rounds\n\n"
                + rounds_context
                + "\n"
            )

        findings_context = format_findings_for_prompt(paths, stage)
        if findings_context:
            stage_template = (
                stage_template.rstrip()
                + "\n\n# Adversarial Validity Findings (each must be answered)\n\n"
                + findings_context
                + "\n"
            )

        outcomes_context = format_outcomes_for_prompt(paths) if stage.number >= 7 else ""
        if outcomes_context:
            stage_template = (
                stage_template.rstrip()
                + "\n\n# Hypothesis Verdicts\n\n"
                + outcomes_context
                + "\n"
            )

        approved_memory = read_text(paths.memory)
        if self._redo_start_stage is not None and stage.number >= self._redo_start_stage.number:
            approved_memory = filtered_approved_memory(approved_memory, max_stage_number=stage.number - 1)

        # Inject intake context for regular stages (01+)
        intake_context_text: str | None = None
        if stage.number > 0:
            ctx = load_intake_context(paths)
            if ctx:
                intake_context_text = format_intake_for_prompt(ctx)

        if continue_session:
            return build_continuation_prompt(
                stage, stage_template, paths, handoff_context, revision_feedback,
                intake_context_text=intake_context_text,
                attempt_no=attempt_no,
                previous_validation_errors=previous_validation_errors,
                web_search_context=self.web_search_context,
                obligations_context=format_for_stage_prompt(load_ledger(paths), stage),
            )

        user_request = read_text(paths.user_input)
        return build_prompt(
            stage, stage_template, user_request, approved_memory, handoff_context, revision_feedback,
            intake_context_text=intake_context_text,
            web_search_context=self.web_search_context,
            obligations_context=format_for_stage_prompt(load_ledger(paths), stage),
        )

    def _display_stage_output(self, stage: StageSpec, markdown: str) -> None:
        self.ui.show_stage_document(stage.stage_title, markdown)

    def _ask_choice(self, suggestions: list[str]) -> str:
        return self.ui.choose_action(suggestions)

    def _read_multiline_feedback(self) -> str:
        return self.ui.read_multiline_feedback()

    def _announce_approval_mode(self) -> None:
        if self.reviewer is None:
            self.ui.show_status("Approval mode: manual human gate.", level="info")
            return
        self.ui.show_status(
            (
                "Approval mode: automated reviewer gate "
                f"({self.review_operator}/{self.review_model})."
            ),
            level="warn",
        )

    def _collect_review_decision(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        stage_markdown: str,
        suggestions: list[str],
    ) -> tuple[str, str | None]:
        self._display_stage_output(stage, stage_markdown)
        if self.reviewer is None:
            choice = self._ask_choice(suggestions)
            append_log_entry(paths.logs, f"{stage.slug} attempt {attempt_no} user_choice", f"choice: {choice}")
            return choice, None

        self.ui.show_status(
            f"Automated reviewer is auditing {stage.stage_title}...",
            level="info",
        )
        decision = self.reviewer.review_stage(
            paths=paths,
            stage=stage,
            attempt_no=attempt_no,
            stage_markdown=stage_markdown,
            suggestions=suggestions,
        )
        self._render_review_decision(decision)
        log_body = [
            f"mode: automated",
            f"backend: {self.review_operator}",
            f"model: {self.review_model}",
            f"choice: {decision.choice}",
            f"decision_token: {decision.decision_token}",
        ]
        if decision.reason:
            log_body.append(f"reason: {decision.reason}")
        if decision.feedback:
            log_body.append(f"feedback:\n{decision.feedback}")
        if decision.raw_response:
            log_body.append("raw_response_excerpt:\n" + truncate_text(decision.raw_response, max_chars=2000))
        append_log_entry(paths.logs, f"{stage.slug} attempt {attempt_no} reviewer_choice", "\n".join(log_body))
        self._record_review_correction(
            paths=paths, stage=stage, attempt_no=attempt_no, decision=decision, suggestions=suggestions
        )
        self._settle_obligations(paths=paths, stage=stage, attempt_no=attempt_no, decision=decision)

        cross = self._apply_cross_review(
            paths=paths, stage=stage, attempt_no=attempt_no, decision=decision,
            stage_markdown=stage_markdown,
        )
        if cross is not None:
            return cross

        return decision.choice, decision.feedback or None

    def _settle_obligations(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        decision: ReviewDecision,
    ) -> None:
        """Close the obligations this stage met, and record the ones it created.

        Discharges are applied first: an approval that both settles an inherited debt and
        raises a new one should not have the new one immediately counted as deferred.
        Deferral is only recorded on approval, because a refused stage gets another attempt
        at the same obligations and has not deferred anything yet.
        """
        closed = discharge_obligations(
            paths, stage=stage, obligation_ids=decision.discharged, note=decision.reason
        )
        for obligation in closed:
            append_log_entry(
                paths.logs,
                f"{stage.slug} attempt {attempt_no} obligation_discharged",
                f"{obligation.obligation_id}: {obligation.text}",
            )

        approved = decision.choice == "5"
        if approved:
            deferred = note_deferrals(paths, stage=stage)
            if deferred:
                append_log_entry(
                    paths.logs,
                    f"{stage.slug} attempt {attempt_no} obligations_deferred",
                    f"{deferred} obligation(s) carried past this stage without being discharged.",
                )

        added = record_obligations(paths, stage=stage, entries=decision.carry_forward)
        for obligation in added:
            target = obligation.target_stage or "any later stage"
            append_log_entry(
                paths.logs,
                f"{stage.slug} attempt {attempt_no} obligation_recorded",
                f"{obligation.obligation_id} -> {target}: {obligation.text}",
            )

        if closed or added:
            self.ui.show_status(
                f"Obligations: +{len(added)} new, {len(closed)} discharged; "
                f"{ledger_summary(load_ledger(paths))}.",
                level="info",
            )

    def _apply_cross_review(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        decision: ReviewDecision,
        stage_markdown: str,
    ) -> tuple[str, str | None] | None:
        """Let an independent model family veto an approval.

        Returns a replacement decision when the audit refuses, or None to leave the
        primary's decision standing. Only approvals are audited: a refusal already sends
        the stage back, so a second opinion on it would change nothing.
        """
        if self.cross_reviewer is None or decision.choice != "5":
            return None

        self.ui.show_status("Cross-model reviewer is auditing the approval...", level="info")
        verdict = self.cross_reviewer.audit(
            paths=paths,
            stage=stage,
            stage_markdown=stage_markdown,
            primary_reason=decision.reason,
            primary_model=self.review_model,
        )

        append_log_entry(
            paths.logs,
            f"{stage.slug} attempt {attempt_no} cross_review",
            "\n".join(
                [
                    f"model: {verdict.model or 'unavailable'}",
                    f"agrees: {verdict.agrees}",
                    f"unavailable: {verdict.unavailable}",
                    f"reason: {verdict.reason}",
                ]
            ),
        )

        if verdict.unavailable:
            # Not agreement — the audit did not happen. Said plainly so a run whose
            # cross-review silently never ran cannot be mistaken for one that passed it.
            self.ui.show_status(
                f"Cross-model review did not run: {verdict.reason}", level="warn"
            )
            return None

        if not verdict.vetoes:
            self.ui.show_status(
                f"Cross-model reviewer ({verdict.model}) agrees with the approval.", level="success"
            )
            return None

        self.ui.show_status(
            f"Cross-model reviewer ({verdict.model}) vetoed the approval: {verdict.reason}",
            level="warn",
        )
        record_correction(
            paths,
            stage=stage,
            attempt_no=attempt_no,
            text=f"Cross-model review vetoed an approval of {stage.stage_title}: {verdict.reason}",
            source="rollback",
        )
        feedback = (
            "An independent reviewer from a different model family rejected the approval of "
            "this stage. Address this before it can be approved again:\n"
            f"{verdict.reason}"
        )
        return "4", feedback

    def _record_review_correction(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        decision: ReviewDecision,
        suggestions: list[str],
    ) -> None:
        """Promote a demanded correction into a standing rule for every later review.

        Only refusals teach anything: an approval says the stage met the bar, which the
        existing rules already encode. The text recorded is what the reviewer actually
        asked for, so the rule is traceable to the decision that produced it.
        """
        if decision.choice not in {"1", "2", "3", "4"}:
            return

        if decision.choice in {"1", "2", "3"}:
            index = int(decision.choice) - 1
            text = suggestions[index] if index < len(suggestions) else ""
        else:
            text = decision.feedback or decision.reason

        rule = record_correction(paths, stage=stage, attempt_no=attempt_no, text=text)
        if rule is None:
            return

        append_log_entry(
            paths.logs,
            f"{stage.slug} attempt {attempt_no} review_rule_learned",
            f"{rule.rule_id} ({rule.source}): {rule.text}",
        )
        self.ui.show_status(
            f"Review policy learned {rule.rule_id}; {policy_summary(load_policy(paths))}.",
            level="info",
        )

    def _render_review_decision(self, decision: ReviewDecision) -> None:
        label_map = {
            "1": "Use suggestion 1",
            "2": "Use suggestion 2",
            "3": "Use suggestion 3",
            "4": "Refine with custom feedback",
            "5": "Approve and continue",
            "6": "Abort",
        }
        body = [
            f"Backend  : {self.review_operator}",
            f"Model    : {self.review_model}",
            f"Decision : {label_map.get(decision.choice, decision.choice)}",
        ]
        if decision.reason:
            body.append(f"Reason   : {decision.reason}")
        if decision.feedback:
            body.extend(["", "Feedback:"] + decision.feedback.splitlines())
        self.ui.panel("Automated Reviewer", body, color=self.ui.FG_MAGENTA)

    def _materialize_missing_stage_draft(
        self,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        source: str,
        fallback_text: str,
    ):
        draft_path = paths.stage_tmp_file(stage)
        normalized_markdown = canonicalize_stage_markdown(
            stage=stage,
            memory_text=read_text(paths.memory),
            markdown="",
            fallback_text=(
                f"AutoR generated this local fallback stage draft because the {source} "
                "did not produce a stage summary file.\n\n"
                + (fallback_text.strip() if fallback_text.strip() else "No stdout or stderr was captured.")
            ),
            stage_output_path=str(draft_path.relative_to(paths.run_root)).replace("\\", "/"),
        )
        write_text(draft_path, normalized_markdown)
        append_log_entry(
            paths.logs,
            f"{stage.slug} attempt {attempt_no} local_fallback_draft",
            (
                f"Generated a local fallback stage draft after missing stage summary during {source}.\n"
                f"draft: {draft_path}\n\n"
                "Fallback markdown preview:\n"
                f"{truncate_text(normalized_markdown, max_chars=4000)}"
            ),
        )
        self.ui.show_status(
            f"{stage.stage_title} did not produce a stage summary file during {source}. "
            "Generated a local fallback draft and continuing recovery...",
            level="warn",
        )
        return type("FallbackResult", (), {"stage_file_path": draft_path, "stdout": fallback_text, "stderr": ""})()

    def _handle_stage_control_command(
        self,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        command_text: str,
    ) -> bool | None:
        command = command_text.strip()
        if not command.startswith("/"):
            return None

        normalized = command.lower()
        if normalized == "/skip":
            return self._skip_stage(
                paths=paths,
                stage=stage,
                attempt_no=attempt_no,
                reason="Human operator skipped this stage via /skip.",
                kind="human",
            )

        if normalized.startswith("/back"):
            target = self._parse_stage_jump_command(command, current_stage=stage)
            if target is None:
                self.ui.show_status(
                    f"Invalid /back command. Use '/back <stage>' with an earlier stage such as '/back 01' or '/back 03_study_design'.",
                    level="warn",
                )
                return None
            self._rollback_and_jump(
                paths=paths,
                current_stage=stage,
                target_stage=target,
                reason=f"Human operator requested /back from {stage.stage_title}.",
            )
            return True

        self.ui.show_status(
            "Unknown control command. Supported commands are '/skip' and '/back <stage>'.",
            level="warn",
        )
        return None

    def _handle_stage_exhaustion(
        self,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        last_validation_errors: list[str],
    ) -> bool:
        if self.unattended:
            return self._handle_unattended_stage_exhaustion(
                paths=paths,
                stage=stage,
                attempt_no=attempt_no,
                last_validation_errors=last_validation_errors,
            )

        input_is_tty = getattr(self.ui.input_stream, "isatty", lambda: False)()
        if not input_is_tty:
            return False

        options = [
            "1. Skip this stage and continue",
            "2. Roll back to an earlier stage",
            "3. Abort",
        ]
        if stage.number == STAGES[0].number:
            options[1] = "2. Roll back to an earlier stage (unavailable for Stage 01)"

        self.ui.panel(
            f"{stage.stage_title} | Recovery",
            [
                "AutoR exhausted the bounded retry window for this stage.",
                "Choose how to recover:",
                *options,
            ],
            color=self.ui.FG_RED,
        )

        if last_validation_errors:
            self.ui.panel(
                "Last Validation Errors",
                [f"- {problem}" for problem in last_validation_errors],
                color=self.ui.FG_YELLOW,
            )

        while True:
            choice = self.ui.read_single_line("Recovery choice [1/2/3]: ").strip()
            if choice == "1":
                return self._skip_stage(
                    paths=paths,
                    stage=stage,
                    attempt_no=attempt_no,
                    reason="Human operator skipped this stage after bounded retries were exhausted.",
                    kind="human",
                )
            if choice == "2":
                target = self._prompt_for_rollback_stage(current_stage=stage)
                if target is None:
                    continue
                self._rollback_and_jump(
                    paths=paths,
                    current_stage=stage,
                    target_stage=target,
                    reason=f"Human operator rolled back after {stage.stage_title} exhausted retries.",
                )
                return True
            if choice == "3":
                return False
            self.ui.show_status("Invalid choice. Enter 1, 2, or 3.", level="warn")

    def _handle_unattended_stage_exhaustion(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        last_validation_errors: list[str],
    ) -> bool:
        """Recover from an exhausted stage with no human available to choose.

        Aborting here would throw away every earlier stage, so a bounded number of stages are
        auto-skipped instead. The skip is promoted as an explicit skip summary, which keeps the
        downstream stages honest about what is missing.
        """
        errors_note = (
            "\n".join(f"- {problem}" for problem in last_validation_errors)
            if last_validation_errors
            else "- (no validation errors were recorded)"
        )

        if len(self.auto_skipped_stages) >= self.max_auto_skips:
            append_log_entry(
                paths.logs,
                f"{stage.slug} unattended_abort",
                (
                    "Unattended run aborted: the auto-skip budget is exhausted.\n"
                    f"auto_skip_budget: {self.max_auto_skips}\n"
                    f"already_skipped: {', '.join(self.auto_skipped_stages)}\n"
                    f"last validation errors:\n{errors_note}"
                ),
            )
            self.ui.show_status(
                (
                    f"{stage.stage_title} exhausted its retries and the unattended auto-skip budget "
                    f"({self.max_auto_skips}) is already spent. Aborting."
                ),
                level="error",
            )
            return False

        self.auto_skipped_stages.append(stage.slug)
        append_log_entry(
            paths.logs,
            f"{stage.slug} unattended_auto_skip",
            (
                "Unattended run auto-skipped this stage after bounded retries were exhausted.\n"
                f"auto_skip_used: {len(self.auto_skipped_stages)}/{self.max_auto_skips}\n"
                f"last validation errors:\n{errors_note}"
            ),
        )
        self.ui.show_status(
            (
                f"{stage.stage_title} exhausted its retries. Unattended mode auto-skipped it "
                f"({len(self.auto_skipped_stages)}/{self.max_auto_skips}) and will continue."
            ),
            level="warn",
        )
        return self._skip_stage(
            paths=paths,
            stage=stage,
            attempt_no=attempt_no,
            reason=(
                "Unattended mode auto-skipped this stage after the bounded retry window was "
                "exhausted. No human was available to choose a recovery action. "
                "Downstream stages must treat this stage's output as missing, not as approved work."
            ),
            kind="auto",
        )

    def _parse_stage_jump_command(self, command_text: str, current_stage: StageSpec) -> StageSpec | None:
        parts = command_text.strip().split(maxsplit=1)
        if len(parts) != 2:
            return None
        target = self._resolve_stage_identifier(parts[1])
        if target is None or target.number >= current_stage.number:
            return None
        return target

    def _prompt_for_rollback_stage(self, current_stage: StageSpec) -> StageSpec | None:
        if current_stage.number == STAGES[0].number:
            self.ui.show_status("There is no earlier formal stage to roll back to.", level="warn")
            return None

        while True:
            raw = self.ui.read_single_line(
                f"Enter an earlier stage to roll back to (for example 01 or 03_study_design), or press Enter to cancel: "
            ).strip()
            if not raw:
                return None
            target = self._resolve_stage_identifier(raw)
            if target is None:
                self.ui.show_status(f"Unknown stage identifier: {raw}", level="warn")
                continue
            if target.number >= current_stage.number:
                self.ui.show_status(
                    f"Rollback target must be earlier than {current_stage.stage_title}.",
                    level="warn",
                )
                continue
            return target

    def _resolve_stage_identifier(self, value: str) -> StageSpec | None:
        normalized = value.strip().lower()
        for candidate in STAGES:
            if normalized in {candidate.slug.lower(), str(candidate.number), f"{candidate.number:02d}"}:
                return candidate
        return None

    def _rollback_and_jump(
        self,
        paths: RunPaths,
        current_stage: StageSpec,
        target_stage: StageSpec,
        reason: str,
    ) -> None:
        rollback_to_stage(paths, target_stage, reason=reason)
        # Carried so the graph path records why the run moved. Both callers reach
        # here — a `/back` from the operator and a research round that decided to
        # refine its design — and recording either as the other would make the
        # route say a person intervened when the run redirected itself.
        self._jump_reason = reason
        # A rollback is the strongest evidence a review can produce: an approval that was
        # already given turned out to be wrong. Recorded at higher weight than a routine
        # refinement so later reviews treat it as such.
        record_correction(
            paths,
            stage=current_stage,
            attempt_no=0,
            text=(
                f"{current_stage.stage_title} was rolled back to {target_stage.stage_title}. "
                f"Reason: {reason}"
            ),
            source="rollback",
        )
        append_log_entry(
            paths.logs,
            f"{current_stage.slug} rollback_requested",
            f"Rolled back from {current_stage.stage_title} to {target_stage.stage_title}.\nReason: {reason}",
        )
        self.ui.show_status(
            f"Rolled back to {target_stage.stage_title}. AutoR will resume from there.",
            level="warn",
        )
        self._jump_target_stage = target_stage

    def _skip_stage(
        self,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        reason: str,
        kind: str,
    ) -> bool:
        stage_markdown = self._build_skipped_stage_markdown(paths, stage, reason, kind)
        final_stage_path = paths.stage_file(stage)
        write_text(final_stage_path, stage_markdown)
        append_approved_stage_summary(paths.memory, stage, stage_markdown)
        mark_stage_skipped_manifest(
            paths,
            stage,
            attempt_no,
            self._stage_file_paths(stage_markdown),
            reason=reason,
            kind=kind,
        )
        write_stage_handoff(paths, stage, stage_markdown)
        write_artifact_index(paths)
        write_experiment_manifest(paths)
        append_log_entry(
            paths.logs,
            f"{stage.slug} skipped",
            (
                f"Stage was skipped ({kind}) and promoted as a skip summary. "
                f"Its work was not done and it is not recorded as approved.\n"
                f"final: {final_stage_path}\n"
                f"reason: {reason}"
            ),
        )
        self.ui.show_status(
            f"Skipped {stage.stage_title}. AutoR will continue to the next stage.",
            level="warn",
        )
        return True

    def _build_skipped_stage_markdown(
        self, paths: RunPaths, stage: StageSpec, reason: str, kind: str
    ) -> str:
        previous = approved_stage_summaries(read_text(paths.memory))
        previous_block = "_None yet._" if previous == "None yet." else previous
        stage_rel_path = str(paths.stage_file(stage).relative_to(paths.run_root)).replace("\\", "/")
        if kind == "human":
            directive = "it was intentionally skipped at human direction so the run could continue"
            did = "- Recorded an explicit human-directed skip for this stage.\n"
        else:
            directive = (
                "it exhausted its retry budget in an unattended run and was auto-skipped "
                "with no human in the loop"
            )
            did = (
                "- Recorded an automatic skip after the bounded retry window was exhausted.\n"
                "- No human reviewed or directed this skip.\n"
            )
        return (
            f"# {stage.stage_title}\n\n"
            "## Objective\n\n"
            f"This stage would normally execute {stage.display_name}, but {directive}.\n\n"
            "## Previously Approved Stage Summaries\n\n"
            f"{previous_block}\n\n"
            "## What I Did\n\n"
            + did +
            "- Preserved the workflow timeline so downstream stages can continue with a clear audit trail.\n"
            "- Marked this stage as intentionally incomplete rather than silently fabricating missing work.\n\n"
            "## Key Results\n\n"
            f"- This stage was skipped ({kind}) and its work was never done.\n"
            "- Downstream stages should treat this stage as missing or provisional context, not as completed evidence.\n"
            f"- Skip reason: {reason}\n\n"
            "## Files Produced\n\n"
            f"- `{stage_rel_path}`\n\n"
            "## Decision Ledger\n\n"
            "- **Open Questions**: Which downstream claims now need extra scrutiny because this stage was skipped?\n"
            f"- **Locked Decisions**: {stage.stage_title} was skipped to keep the run moving.\n"
            "- **Assumptions**: Later stages will either work around the missing context or surface the missing dependencies explicitly.\n"
            "- **Rejected Alternatives**: Pretending the skipped work was completed or fabricating artifacts that do not exist.\n\n"
            "## Suggestions for Refinement\n"
            "1. Return to this stage later if downstream progress reveals that the skipped work is actually required.\n"
            "2. Tighten downstream claims so they do not overstate evidence that would have come from this stage.\n"
            "3. Add explicit notes in later stages when missing context from this skipped stage limits confidence.\n\n"
            "## Your Options\n"
            + "\n".join(FIXED_STAGE_OPTIONS)
            + "\n"
        )

    def _format_rollback_preview(self, paths: RunPaths, rollback_stage: StageSpec) -> str:
        manifest = ensure_run_manifest(paths)
        stale_candidates = [
            entry.slug
            for entry in manifest.stages
            if entry.number > rollback_stage.number and (entry.approved or entry.status != "pending")
        ]
        lines = [
            f"Rolling back to {rollback_stage.stage_title}.",
            f"Stage {rollback_stage.slug} will be marked pending/dirty.",
        ]
        if stale_candidates:
            lines.append("Downstream stages that will be marked stale:")
            lines.extend(f"- {slug}" for slug in stale_candidates)
        else:
            lines.append("No downstream stages currently need invalidation.")
        return "\n".join(lines)

    def describe_run_status(self, run_root: Path) -> str:
        paths = build_run_paths(run_root)
        ensure_run_layout(paths)
        manifest = load_run_manifest(paths.run_manifest)
        if manifest is None:
            raise RuntimeError(f"Could not load run manifest from {paths.run_manifest}")
        return format_manifest_status(manifest)

    def _close_round(self, paths: RunPaths, stage: StageSpec) -> None:
        """End the round and, if it asked for another and the budget allows, start one.

        The decision is recorded whatever the budget is. A run that wanted
        another round and could not have one should say so — the alternative is
        a record indistinguishable from a run that converged.
        """
        rounds_so_far = len(load_rounds(paths))
        pending = read_round_decision(paths)
        decision = str((pending or {}).get("decision") or "").strip()
        resume_slug = resume_stage_slug_for(decision)
        budget_left = rounds_so_far + 1 < self.max_rounds
        act = bool(resume_slug) and budget_left

        entry = record_round(
            paths,
            acted_on=act or not resume_slug,
            budget_note=(
                ""
                if act or not resume_slug
                else f"round budget spent ({rounds_so_far + 1}/{self.max_rounds})"
            ),
        )
        if entry is None:
            return

        append_log_entry(
            paths.logs,
            f"{stage.slug} round_closed",
            (
                f"Round {entry.number} decision: {entry.decision}"
                + (" (negative result)" if entry.negative_result else "")
                + f"\nVerdicts: {entry.hypothesis_verdicts or 'none recorded'}"
                f"\nRationale: {entry.rationale}"
                + (f"\nNot acted on: {entry.budget_note}" if entry.budget_note else "")
            ),
        )

        if not resume_slug:
            self.ui.show_status(
                f"Round {entry.number} closed: {entry.decision}"
                + (" (negative result)" if entry.negative_result else ""),
                level="info" if entry.decision == "converged" else "warn",
            )
            return

        if not budget_left:
            self.ui.show_status(
                f"Round {entry.number} wanted to {entry.decision}, but the round budget "
                f"({self.max_rounds}) is spent. Continuing to writing with that on the record. "
                "Raise --max-rounds to let the run iterate.",
                level="warn",
            )
            return

        target = next(item for item in STAGES if item.slug == resume_slug)
        self.ui.show_status(
            f"Round {entry.number} chose {entry.decision}. Starting round {entry.number + 1} "
            f"from {target.stage_title}.",
            level="warn",
        )
        self._rollback_and_jump(
            paths=paths,
            current_stage=stage,
            target_stage=target,
            reason=(
                f"Round {entry.number} concluded {entry.decision}: {entry.rationale}"
            ),
        )

    def _run_validity_review(self, paths: RunPaths, stage: StageSpec, stage_markdown: str) -> None:
        """Attack the result once the stage that produced it is approved.

        Separate from the approval gate on purpose: that one asks whether the
        stage did its work, and an agent asked to do both jobs at once reliably
        does the easier one. This has no authority to approve or reject — the
        next stage simply has to answer what it raises.
        """
        from .validity_review import REVIEWED_STAGE_NUMBERS

        if stage.number not in REVIEWED_STAGE_NUMBERS:
            return
        self.ui.show_status(
            f"Adversarial validity review of {stage.stage_title}...", level="info"
        )
        try:
            findings = ValidityReviewer(self.operator, ui=self.ui).review(
                paths=paths, stage=stage, stage_markdown=stage_markdown
            )
        except Exception as exc:  # noqa: BLE001 - a failed critique must not lose the stage
            append_log_entry(
                paths.logs,
                f"{stage.slug} validity_review_failed",
                f"The adversarial validity review did not run: {exc}",
            )
            self.ui.show_status(
                "Validity review did not run; the stage stands unchallenged.", level="warn"
            )
            return
        append_log_entry(
            paths.logs,
            f"{stage.slug} validity_review",
            (
                f"Adversarial review raised {len(findings)} findings.\n"
                + "\n".join(
                    f"- {item.identifier} ({item.severity} {item.category}): {item.finding}"
                    for item in findings
                )
            ),
        )
        if findings:
            critical = sum(1 for item in findings if item.severity == "critical")
            self.ui.show_status(
                f"Validity review raised {len(findings)} findings ({critical} critical). "
                "The next stage must answer each one.",
                level="warn",
            )

    def _freeze_preregistration(self, paths: RunPaths) -> None:
        """Fix the hypothesis set before any result exists.

        Stage 04 approval is the honest boundary: the design and the code are
        settled, nothing has been measured. Everything downstream is then
        adjudicated against this, and a later change to the hypotheses has to
        arrive as a recorded amendment rather than a quiet edit.
        """
        prereg = freeze_preregistration(paths)
        if prereg is None:
            append_log_entry(
                paths.logs,
                "preregistration not_frozen",
                (
                    "No hypothesis manifest was available to freeze. Stage 05 onward will "
                    "report this as a validation problem, because the run has nothing "
                    "falsifiable on record from before the experiments."
                ),
            )
            return
        append_log_entry(
            paths.logs,
            "preregistration frozen",
            (
                f"Froze {len(prereg.adjudicated_ids)} empirical hypotheses before "
                f"{prereg.frozen_before_stage}.\n"
                f"digest: {prereg.digest}\n"
                f"ids: {', '.join(prereg.adjudicated_ids) or 'none'}"
            ),
        )

    def _amend_preregistration(self, paths: RunPaths, reason: str) -> None:
        """Re-freeze after a legitimate revision, keeping the previous digest."""
        if load_preregistration(paths) is None:
            return
        amended = amend_preregistration(paths, reason)
        if amended is None or not amended.amendments:
            return
        append_log_entry(
            paths.logs,
            "preregistration amended",
            (
                f"The hypothesis set was revised after freezing.\n"
                f"reason: {reason}\n"
                f"amendments on record: {len(amended.amendments)}\n"
                f"digest: {amended.digest}"
            ),
        )

    def _install_skills(self, paths: RunPaths) -> list[str]:
        """Put the agent skill pack where the operator's CLI will find it.

        The operator runs with ``cwd=run_root``, so skills have to live in the
        run's own ``.claude/skills/``. Installing them is best-effort: a run
        must not fail because a skill file is unreadable, since skills are
        guidance and every stage has a complete prompt without them.
        """
        try:
            installed = install_run_skills(paths, self.skills_dir)
        except OSError as exc:
            append_log_entry(
                paths.logs,
                "skills install_failed",
                f"Could not install the agent skill pack from {self.skills_dir}: {exc}",
            )
            return []
        if installed:
            append_log_entry(
                paths.logs,
                "skills installed",
                (
                    f"Installed {len(installed)} agent skills into "
                    f"{paths.skills_dir.relative_to(paths.run_root).as_posix()}: "
                    + ", ".join(installed)
                ),
            )
        return installed

    def _stage_file_paths(self, stage_markdown: str) -> list[str]:
        from .utils import extract_path_references

        return extract_path_references(stage_markdown)

    def _print(self, text: str) -> None:
        self.ui.write(text.rstrip() + "\n")
