from __future__ import annotations

import json
import re
from dataclasses import asdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from ..artifact_index import ArtifactIndex, load_artifact_index
from ..manifest import ensure_run_manifest, load_run_manifest
from ..utils import (
    DEFAULT_OUTPUT_FORMAT,
    STAGES,
    RunPaths,
    build_run_paths,
    read_text,
    selected_output_format,
)
from .sessions import parse_real_session, read_events, summarize_sessions
from .studio_runner import StudioRunner


IterationMode = Literal["continue", "redo", "branch"]
IterationScopeType = Literal["stage", "file", "subtree", "manuscript"]
ParticipationModel = Literal["human_in_loop"]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    normalized = normalized.strip("-")
    return normalized or "project"


@dataclass(frozen=True)
class ProjectRecord:
    project_id: str
    title: str
    thesis: str
    participation_model: ParticipationModel = "human_in_loop"
    tags: list[str] = field(default_factory=list)
    run_ids: list[str] = field(default_factory=list)
    active_run_id: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "title": self.title,
            "thesis": self.thesis,
            "participation_model": self.participation_model,
            "tags": list(self.tags),
            "run_ids": list(self.run_ids),
            "active_run_id": self.active_run_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ProjectRecord":
        return cls(
            project_id=str(payload.get("project_id") or "").strip(),
            title=str(payload.get("title") or "").strip(),
            thesis=str(payload.get("thesis") or "").strip(),
            participation_model="human_in_loop",
            tags=[str(item).strip() for item in payload.get("tags", []) if str(item).strip()],
            run_ids=[str(item).strip() for item in payload.get("run_ids", []) if str(item).strip()],
            active_run_id=str(payload["active_run_id"]) if payload.get("active_run_id") is not None else None,
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
        )


@dataclass(frozen=True)
class StudioStageSummary:
    number: int
    slug: str
    title: str
    status: str
    approved: bool
    dirty: bool
    stale: bool
    attempt_count: int
    artifact_paths: list[str]
    updated_at: str
    approved_at: str | None = None


@dataclass(frozen=True)
class StudioRunSummary:
    run_id: str
    run_root: str
    goal: str
    model: str
    venue: str
    run_status: str
    current_stage_slug: str | None
    updated_at: str
    completed_at: str | None
    artifact_count: int
    counts_by_category: dict[str, int]
    stages: list[StudioStageSummary]


@dataclass(frozen=True)
class StudioProjectSummary:
    project_id: str
    title: str
    thesis: str
    participation_model: ParticipationModel
    tags: list[str]
    run_ids: list[str]
    active_run_id: str | None
    latest_run_status: str | None
    latest_completed_stage_slug: str | None
    updated_at: str


@dataclass(frozen=True)
class FileTreeNode:
    name: str
    rel_path: str
    node_type: Literal["directory", "file"]
    size_bytes: int = 0
    children: list["FileTreeNode"] = field(default_factory=list)


@dataclass(frozen=True)
class IterationRequest:
    run_id: str
    base_stage_slug: str
    scope_type: IterationScopeType
    scope_value: str
    mode: IterationMode
    freeze_upstream: bool = True
    invalidate_downstream: bool = True
    user_feedback: str = ""


@dataclass(frozen=True)
class IterationPlan:
    run_id: str
    base_stage_slug: str
    scope_type: IterationScopeType
    scope_value: str
    mode: IterationMode
    preserved_stages: list[str]
    affected_stages: list[str]
    stale_stages: list[str]
    branch_run_id: str | None
    reuses_current_run: bool
    summary: str
    user_feedback: str
    operator_brief: str
    reviewer_actions: list[str]


@dataclass(frozen=True)
class StudioPaperPreview:
    run_id: str
    tex_relative_path: str | None
    tex_content: str
    section_paths: list[str]
    pdf_relative_path: str | None
    pdf_available: bool
    build_log_relative_path: str | None
    build_log_content: str
    output_format: str = DEFAULT_OUTPUT_FORMAT
    report_relative_path: str | None = None
    report_content: str = ""
    report_available: bool = False


@dataclass(frozen=True)
class StudioVersionRecord:
    version_id: str
    label: str
    kind: str
    created_at: str
    stage_slug: str | None
    stage_title: str | None
    stage_number: int | None
    run_status: str
    artifact_paths: list[str]
    notes: str
    session_id: str | None = None


@dataclass(frozen=True)
class StudioTraceEvent:
    event_id: str
    timestamp: str
    title: str
    detail: str
    actor: str
    status: str
    stage_slug: str | None = None
    attempt_count: int | None = None


@dataclass(frozen=True)
class StudioRunHistory:
    run_id: str
    current_version_id: str | None
    versions: list[StudioVersionRecord]
    trace_events: list[StudioTraceEvent]


class ProjectIndexStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._registry_path = self.root / "projects.json"

    def list_projects(self) -> list[ProjectRecord]:
        if not self._registry_path.exists():
            return []
        payload = json.loads(self._registry_path.read_text(encoding="utf-8"))
        return [
            ProjectRecord.from_dict(item)
            for item in payload.get("projects", [])
            if isinstance(item, dict)
        ]

    def create_project(
        self,
        title: str,
        thesis: str,
        participation_model: ParticipationModel = "human_in_loop",
        default_mode: str | None = None,
        tags: list[str] | None = None,
    ) -> ProjectRecord:
        projects = self.list_projects()
        project_id = self._allocate_project_id(title, projects)
        record = ProjectRecord(
            project_id=project_id,
            title=title.strip(),
            thesis=thesis.strip(),
            participation_model=participation_model,
            tags=list(tags or []),
            run_ids=[],
            active_run_id=None,
            created_at=_now(),
            updated_at=_now(),
        )
        self._save_projects(projects + [record])
        return record

    def attach_run(self, project_id: str, run_id: str, make_active: bool = True) -> ProjectRecord:
        projects = self.list_projects()
        updated: list[ProjectRecord] = []
        selected: ProjectRecord | None = None
        for project in projects:
            if project.project_id != project_id:
                updated.append(project)
                continue
            run_ids = list(project.run_ids)
            if run_id not in run_ids:
                run_ids.append(run_id)
            selected = ProjectRecord(
                project_id=project.project_id,
                title=project.title,
                thesis=project.thesis,
                participation_model=project.participation_model,
                tags=project.tags,
                run_ids=run_ids,
                active_run_id=run_id if make_active else project.active_run_id,
                created_at=project.created_at,
                updated_at=_now(),
            )
            updated.append(selected)
        if selected is None:
            raise KeyError(f"Unknown project id: {project_id}")
        self._save_projects(updated)
        return selected

    def _allocate_project_id(self, title: str, existing: list[ProjectRecord]) -> str:
        base = _slugify(title)
        taken = {project.project_id for project in existing}
        candidate = base
        counter = 2
        while candidate in taken:
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate

    def _save_projects(self, projects: list[ProjectRecord]) -> None:
        payload = {"projects": [project.to_dict() for project in projects]}
        self._registry_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )


class StudioService:
    def __init__(
        self,
        repo_root: Path,
        runs_dir: Path | None = None,
        metadata_root: Path | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.runs_dir = runs_dir or (repo_root / "runs")
        self.metadata_root = metadata_root or (repo_root / ".autor")
        self.project_store = ProjectIndexStore(self.metadata_root)
        # Always use the real runner. The availability check (claude CLI on
        # PATH) is deferred to start_run() so the service can be constructed
        # in test environments that don't have the CLI installed — existing
        # tests for stage docs, iteration planning, etc. don't need the runner.
        self.runner = StudioRunner(
            runs_dir=self.runs_dir,
            project_root=self.repo_root,
        )

    def create_project(
        self,
        title: str,
        thesis: str,
        participation_model: ParticipationModel = "human_in_loop",
        default_mode: str | None = None,
        tags: list[str] | None = None,
    ) -> ProjectRecord:
        return self.project_store.create_project(
            title=title,
            thesis=thesis,
            participation_model=participation_model,
            default_mode=default_mode,
            tags=tags,
        )

    def list_projects(self) -> list[ProjectRecord]:
        return self.project_store.list_projects()

    def list_project_summaries(self) -> list[StudioProjectSummary]:
        return [self.get_project_summary(project.project_id) for project in self.project_store.list_projects()]

    def get_project_summary(self, project_id: str) -> StudioProjectSummary:
        project = next((item for item in self.project_store.list_projects() if item.project_id == project_id), None)
        if project is None:
            raise KeyError(f"Unknown project id: {project_id}")

        # Walk the project's run list newest-first, skipping any that have been
        # deleted from disk. This keeps the projects overview endpoint alive
        # even if the user removed a runs/ subdirectory manually.
        candidate_run_ids: list[str] = []
        if project.active_run_id:
            candidate_run_ids.append(project.active_run_id)
        for rid in reversed(project.run_ids):
            if rid not in candidate_run_ids:
                candidate_run_ids.append(rid)

        latest_run_status: str | None = None
        latest_completed_stage_slug: str | None = None
        for rid in candidate_run_ids:
            try:
                run_summary = self.get_run_summary(rid)
            except (FileNotFoundError, KeyError):
                continue
            except Exception:
                continue
            latest_run_status = run_summary.run_status
            approved = [stage.slug for stage in run_summary.stages if stage.approved]
            latest_completed_stage_slug = approved[-1] if approved else None
            break

        return StudioProjectSummary(
            project_id=project.project_id,
            title=project.title,
            thesis=project.thesis,
            participation_model=project.participation_model,
            tags=list(project.tags),
            run_ids=list(project.run_ids),
            active_run_id=project.active_run_id,
            latest_run_status=latest_run_status,
            latest_completed_stage_slug=latest_completed_stage_slug,
            updated_at=project.updated_at,
        )

    def attach_run_to_project(self, project_id: str, run_id: str, make_active: bool = True) -> ProjectRecord:
        self._require_run(run_id)
        return self.project_store.attach_run(project_id, run_id, make_active=make_active)

    def start_project_run(self, project_id: str, goal: str | None = None) -> str:
        """Kick off a new simulated run for a project and attach it immediately."""
        project = next(
            (item for item in self.project_store.list_projects() if item.project_id == project_id),
            None,
        )
        if project is None:
            raise KeyError(f"Unknown project id: {project_id}")
        effective_goal = (goal or project.thesis or project.title).strip()
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        run_id = self.runner.start_run(
            project_id=project.project_id,
            goal=effective_goal,
        )
        self.project_store.attach_run(project.project_id, run_id, make_active=True)
        return run_id

    def approve_stage(self, run_id: str, stage_slug: str) -> None:
        self.runner.approve_stage(run_id, stage_slug)

    def submit_stage_feedback(self, run_id: str, stage_slug: str, feedback: str) -> None:
        if not feedback.strip():
            raise ValueError("Feedback must not be empty.")
        self.runner.submit_feedback(run_id, stage_slug, feedback)

    def get_stage_session(self, run_id: str, stage_slug: str) -> dict[str, object]:
        """Return per-stage interaction trace.

        Tries our own session JSONL first, then falls back to parsing the real
        runner's ``logs_raw.jsonl`` (Claude stream-json) so the Progress
        Monitor on the Review page works for both runners.
        """
        paths = self._require_run(run_id)
        events = read_events(paths.run_root, stage_slug)
        if not events:
            events = parse_real_session(paths.run_root, stage_slug)
        return {
            "run_id": run_id,
            "stage_slug": stage_slug,
            "event_count": len(events),
            "events": events,
        }

    def list_run_sessions(self, run_id: str) -> dict[str, object]:
        paths = self._require_run(run_id)
        return {"run_id": run_id, "sessions": summarize_sessions(paths.run_root)}

    def list_run_ids(self) -> list[str]:
        if not self.runs_dir.exists():
            return []
        run_ids = [
            path.name
            for path in self.runs_dir.iterdir()
            if path.is_dir() and (path / "run_manifest.json").exists()
        ]
        return sorted(run_ids)

    def get_run_summary(self, run_id: str) -> StudioRunSummary:
        paths = self._require_run(run_id)
        manifest = ensure_run_manifest(paths)
        config = self._load_json(paths.run_config)
        artifact_index = load_artifact_index(paths.artifact_index)
        goal = read_text(paths.user_input).strip() if paths.user_input.exists() else ""
        stages = [
            StudioStageSummary(
                number=entry.number,
                slug=entry.slug,
                title=entry.title,
                status=entry.status,
                approved=entry.approved,
                dirty=entry.dirty,
                stale=entry.stale,
                attempt_count=entry.attempt_count,
                artifact_paths=list(entry.artifact_paths),
                updated_at=entry.updated_at,
                approved_at=entry.approved_at,
            )
            for entry in manifest.stages
        ]
        counts_by_category = artifact_index.counts_by_category if artifact_index is not None else {}
        return StudioRunSummary(
            run_id=run_id,
            run_root=str(paths.run_root),
            goal=goal,
            model=str(config.get("model") or "unknown"),
            venue=str(config.get("venue") or "default"),
            run_status=manifest.run_status,
            current_stage_slug=manifest.current_stage_slug,
            updated_at=manifest.updated_at,
            completed_at=manifest.completed_at,
            artifact_count=artifact_index.artifact_count if artifact_index is not None else 0,
            counts_by_category=counts_by_category,
            stages=stages,
        )

    def get_stage_document(self, run_id: str, stage_slug: str) -> str:
        """Return the markdown for a stage.

        Falls back to the in-progress ``.tmp.md`` draft when the final stage
        file doesn't exist yet (e.g. while the runner is mid-stage). This
        lets the Studio show real Claude output as it's being written, and
        keeps the Review page from breaking when the user lands on a stage
        that's still running.
        """
        paths = self._require_run(run_id)
        stage = _resolve_stage(stage_slug)
        final = paths.stage_file(stage)
        if final.exists():
            return read_text(final)
        draft = paths.stage_tmp_file(stage)
        if draft.exists():
            return read_text(draft)
        # Neither file exists yet — return an empty string instead of raising
        # so the frontend can render a "stage hasn't produced output yet" state.
        return ""

    def get_artifact_index(self, run_id: str) -> ArtifactIndex | None:
        paths = self._require_run(run_id)
        return load_artifact_index(paths.artifact_index)

    def get_file_content(self, run_id: str, relative_path: str) -> dict[str, object]:
        paths = self._require_run(run_id)
        path = self._resolve_run_relative_path(paths, relative_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Unknown run file: {relative_path}")
        run_root = paths.run_root.resolve()
        try:
            content = path.read_text(encoding="utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            content = ""
            encoding = "binary"
        return {
            "run_id": run_id,
            "relative_path": str(path.resolve().relative_to(run_root)).replace("\\", "/"),
            "size_bytes": path.stat().st_size,
            "encoding": encoding,
            "content": content,
        }

    def build_file_tree(
        self,
        run_id: str,
        root_relative: str = "workspace",
        max_depth: int | None = None,
        include_hidden: bool = False,
    ) -> FileTreeNode:
        paths = self._require_run(run_id)
        root_path = paths.run_root / root_relative
        if not root_path.exists():
            raise FileNotFoundError(f"Unknown run path: {root_relative}")
        return self._build_tree_node(
            base_root=paths.run_root,
            path=root_path,
            max_depth=max_depth,
            include_hidden=include_hidden,
        )

    def get_paper_preview(self, run_id: str) -> StudioPaperPreview:
        paths = self._require_run(run_id)
        output_format = selected_output_format(paths)
        report_available = paths.report_file.exists()
        tex_path = paths.writing_dir / "main.tex"
        tex_content = read_text(tex_path) if tex_path.exists() else ""
        section_paths = [
            str(path.relative_to(paths.run_root)).replace("\\", "/")
            for path in sorted((paths.writing_dir / "sections").rglob("*.tex"))
        ]
        pdf_path = self._find_paper_pdf(paths)
        build_log_path = self._find_existing_path(
            [
                paths.writing_dir / "build.log",
                paths.artifacts_dir / "build.log",
                paths.artifacts_dir / "paper_package" / "build.log",
            ]
        )
        return StudioPaperPreview(
            run_id=run_id,
            tex_relative_path=self._relative_to_run(paths, tex_path) if tex_path.exists() else None,
            tex_content=tex_content,
            section_paths=section_paths,
            pdf_relative_path=self._relative_to_run(paths, pdf_path) if pdf_path is not None else None,
            pdf_available=pdf_path is not None,
            build_log_relative_path=self._relative_to_run(paths, build_log_path) if build_log_path is not None else None,
            build_log_content=read_text(build_log_path) if build_log_path is not None else "",
            output_format=output_format,
            report_relative_path=self._relative_to_run(paths, paths.report_file) if report_available else None,
            report_content=read_text(paths.report_file) if report_available else "",
            report_available=report_available,
        )

    def get_paper_pdf_bytes(self, run_id: str) -> bytes:
        paths = self._require_run(run_id)
        pdf_path = self._find_paper_pdf(paths)
        if pdf_path is None:
            raise FileNotFoundError(f"No manuscript PDF found for run: {run_id}")
        return pdf_path.read_bytes()

    def get_run_history(self, run_id: str) -> StudioRunHistory:
        paths = self._require_run(run_id)
        manifest = ensure_run_manifest(paths)
        versions = self._build_versions(paths, manifest)
        trace_events = self._build_trace_events(paths, manifest)
        current_version_id = versions[-1].version_id if versions else None
        return StudioRunHistory(
            run_id=run_id,
            current_version_id=current_version_id,
            versions=versions,
            trace_events=trace_events,
        )

    def plan_iteration(self, request: IterationRequest) -> IterationPlan:
        run = self.get_run_summary(request.run_id)
        stage = _resolve_stage(request.base_stage_slug)
        preserved_stages = [
            item.slug
            for item in run.stages
            if request.freeze_upstream and item.number < stage.number
        ]
        affected_stages = _affected_stage_slugs(stage.slug, request.scope_type)
        stale_stages: list[str] = []
        branch_run_id: str | None = None
        reuses_current_run = request.mode != "branch"

        if request.mode == "continue":
            affected_stages = [stage.slug]
            stale_stages = []
            summary = (
                f"Continue {stage.slug} in the current run. "
                f"Only the selected scope `{request.scope_value}` is expected to change."
            )
        elif request.mode == "redo":
            if request.invalidate_downstream:
                stale_stages = [
                    item.slug
                    for item in run.stages
                    if item.number > stage.number and (item.approved or item.status != "pending")
                ]
            summary = (
                f"Redo the current run from {stage.slug}. "
                f"Downstream stages marked stale: {', '.join(stale_stages) if stale_stages else 'none'}."
            )
        else:
            branch_run_id = f"{run.run_id}-branch-{stage.slug}"
            stale_stages = []
            summary = (
                f"Create a new branch run from {stage.slug} for scope `{request.scope_value}`. "
                f"The current run stays unchanged."
            )

        feedback_text = request.user_feedback.strip()
        operator_brief_lines = [
            f"Target run: {request.run_id}",
            f"Iteration mode: {request.mode}",
            f"Base stage: {stage.slug}",
            f"Scope: {request.scope_type} -> {request.scope_value}",
        ]
        if preserved_stages:
            operator_brief_lines.append(f"Preserve upstream approvals: {', '.join(preserved_stages)}")
        if stale_stages:
            operator_brief_lines.append(f"Treat downstream stages as stale: {', '.join(stale_stages)}")
        if branch_run_id is not None:
            operator_brief_lines.append(f"Create branch run id: {branch_run_id}")
        operator_brief_lines.append(
            "Human feedback: " + (feedback_text if feedback_text else "No additional human feedback yet.")
        )
        reviewer_actions = [
            "Inspect the selected stage summary before resuming the run.",
            f"Use `{request.mode}` for the scope `{request.scope_value}`.",
            "Hand the operator brief to AutoR when execution actions are wired into the UI.",
        ]

        return IterationPlan(
            run_id=request.run_id,
            base_stage_slug=stage.slug,
            scope_type=request.scope_type,
            scope_value=request.scope_value,
            mode=request.mode,
            preserved_stages=preserved_stages,
            affected_stages=affected_stages,
            stale_stages=stale_stages,
            branch_run_id=branch_run_id,
            reuses_current_run=reuses_current_run,
            summary=summary,
            user_feedback=feedback_text,
            operator_brief="\n".join(operator_brief_lines),
            reviewer_actions=reviewer_actions,
        )

    def _require_run(self, run_id: str) -> RunPaths:
        run_root = self.runs_dir / run_id
        manifest = load_run_manifest(run_root / "run_manifest.json")
        if manifest is None:
            raise FileNotFoundError(f"Run not found: {run_id}")
        return build_run_paths(run_root)

    def _build_tree_node(
        self,
        base_root: Path,
        path: Path,
        max_depth: int | None,
        include_hidden: bool,
        depth: int = 0,
    ) -> FileTreeNode:
        rel_path = str(path.relative_to(base_root)).replace("\\", "/")
        if path.is_file():
            return FileTreeNode(
                name=path.name,
                rel_path=rel_path,
                node_type="file",
                size_bytes=path.stat().st_size,
            )

        if max_depth is not None and depth >= max_depth:
            return FileTreeNode(name=path.name, rel_path=rel_path, node_type="directory", children=[])

        children: list[FileTreeNode] = []
        for child in sorted(path.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
            if not include_hidden and child.name.startswith("."):
                continue
            children.append(
                self._build_tree_node(
                    base_root=base_root,
                    path=child,
                    max_depth=max_depth,
                    include_hidden=include_hidden,
                    depth=depth + 1,
                )
            )
        return FileTreeNode(name=path.name, rel_path=rel_path, node_type="directory", children=children)

    def _load_json(self, path: Path) -> dict[str, object]:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _build_versions(self, paths: RunPaths, manifest) -> list[StudioVersionRecord]:
        versions = [
            StudioVersionRecord(
                version_id="run-start",
                label="Run Started",
                kind="run_start",
                created_at=manifest.created_at,
                stage_slug=None,
                stage_title=None,
                stage_number=None,
                run_status="pending",
                artifact_paths=[],
                notes="Initial run checkpoint before any approved stage output existed.",
            )
        ]
        for entry in manifest.stages:
            if not entry.approved:
                if entry.status == "human_review":
                    versions.append(
                        StudioVersionRecord(
                            version_id=f"awaiting-review-{entry.slug}",
                            label=f"Awaiting Review: {entry.title}",
                            kind="awaiting_review",
                            created_at=entry.updated_at or manifest.updated_at,
                            stage_slug=entry.slug,
                            stage_title=entry.title,
                            stage_number=entry.number,
                            run_status=entry.status,
                            artifact_paths=list(entry.artifact_paths),
                            notes="Draft stage summary is ready for human review but not yet approved.",
                            session_id=entry.session_id,
                        )
                    )
                continue
            versions.append(
                StudioVersionRecord(
                    version_id=f"checkpoint-{entry.slug}",
                    label=entry.title,
                    kind="auto_checkpoint",
                    created_at=entry.approved_at or entry.updated_at or manifest.updated_at,
                    stage_slug=entry.slug,
                    stage_title=entry.title,
                    stage_number=entry.number,
                    run_status=entry.status,
                    artifact_paths=list(entry.artifact_paths),
                    notes=f"Auto checkpoint captured after human approval of {entry.title}.",
                    session_id=entry.session_id,
                )
            )

        if manifest.completed_at is not None:
            final_stage = next((entry for entry in reversed(manifest.stages) if entry.approved), None)
            versions.append(
                StudioVersionRecord(
                    version_id="run-complete",
                    label="Run Completed",
                    kind="derived_milestone",
                    created_at=manifest.completed_at,
                    stage_slug=final_stage.slug if final_stage is not None else None,
                    stage_title=final_stage.title if final_stage is not None else None,
                    stage_number=final_stage.number if final_stage is not None else None,
                    run_status=manifest.run_status,
                    artifact_paths=list(final_stage.artifact_paths) if final_stage is not None else [],
                    notes="Derived completion milestone from the final approved run manifest state.",
                    session_id=final_stage.session_id if final_stage is not None else None,
                )
            )
        return versions

    def _build_trace_events(self, paths: RunPaths, manifest) -> list[StudioTraceEvent]:
        events: list[StudioTraceEvent] = []
        heading_pattern = re.compile(r"^===\s+([^|]+?)\s+\|\s+(.+?)\s+===$")
        if paths.logs.exists():
            for raw_line in paths.logs.read_text(encoding="utf-8").splitlines():
                match = heading_pattern.match(raw_line.strip())
                if not match:
                    continue
                timestamp = match.group(1).strip()
                heading = match.group(2).strip()
                events.append(self._trace_event_from_heading(timestamp, heading))

        if not any(event.title == "Run Started" for event in events):
            events.insert(
                0,
                StudioTraceEvent(
                    event_id="manifest-run-start",
                    timestamp=manifest.created_at,
                    title="Run Started",
                    detail="Derived from run manifest creation time.",
                    actor="system",
                    status="info",
                ),
            )
        if manifest.completed_at is not None and not any(event.title == "Run Completed" for event in events):
            events.append(
                StudioTraceEvent(
                    event_id="manifest-run-complete",
                    timestamp=manifest.completed_at,
                    title="Run Completed",
                    detail="Derived from the final run manifest state.",
                    actor="system",
                    status="success",
                )
            )
        return events

    def _trace_event_from_heading(self, timestamp: str, heading: str) -> StudioTraceEvent:
        stage_slug: str | None = None
        attempt_count: int | None = None
        actor = "autor"
        status = "info"
        title = heading
        detail = heading

        stage_attempt = re.match(r"^([0-9]{2}_[a-z0-9_]+)\s+attempt\s+([0-9]+)\s+(.+)$", heading)
        if stage_attempt:
            stage_slug = stage_attempt.group(1)
            attempt_count = int(stage_attempt.group(2))
            tail = stage_attempt.group(3)
            title = _humanize_trace_heading(tail)
            detail = f"{_display_name_for_stage(stage_slug)} · attempt {attempt_count}"
            if "prompt" in tail:
                status = "info"
            elif "result" in tail or "promoted" in tail:
                status = "neutral"
            elif "user_choice" in tail:
                actor = "human"
                status = "neutral"
            return StudioTraceEvent(
                event_id=f"{timestamp}|{heading}",
                timestamp=timestamp,
                title=title,
                detail=detail,
                actor=actor,
                status=status,
                stage_slug=stage_slug,
                attempt_count=attempt_count,
            )

        stage_heading = re.match(r"^([0-9]{2}_[a-z0-9_]+)\s+(.+)$", heading)
        if stage_heading:
            stage_slug = stage_heading.group(1)
            tail = stage_heading.group(2)
            title = _humanize_trace_heading(tail)
            detail = _display_name_for_stage(stage_slug)
            if "approved" in tail or "package" in tail:
                actor = "human" if "approved" in tail else "autor"
                status = "success"
            elif "error" in tail:
                status = "warning"
            elif "user_choice" in tail:
                actor = "human"
                status = "neutral"
            return StudioTraceEvent(
                event_id=f"{timestamp}|{heading}",
                timestamp=timestamp,
                title=title,
                detail=detail,
                actor=actor,
                status=status,
                stage_slug=stage_slug,
                attempt_count=attempt_count,
            )

        title = _humanize_trace_heading(heading)
        detail = heading
        if "complete" in heading:
            status = "success"
        elif "start" in heading:
            status = "info"
        return StudioTraceEvent(
            event_id=f"{timestamp}|{heading}",
            timestamp=timestamp,
            title=title,
            detail=detail,
            actor="system",
            status=status,
        )

    def _find_paper_pdf(self, paths: RunPaths) -> Path | None:
        preferred_candidates = [
            paths.writing_dir / "main.pdf",
            paths.artifacts_dir / "paper.pdf",
            paths.artifacts_dir / "paper_package" / "paper.pdf",
        ]
        existing = self._find_existing_path(preferred_candidates)
        if existing is not None:
            return existing

        for root in (paths.writing_dir, paths.artifacts_dir):
            for candidate in sorted(root.rglob("*.pdf")):
                if candidate.is_file():
                    return candidate
        return None

    def _find_existing_path(self, candidates: list[Path]) -> Path | None:
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate
        return None

    def _relative_to_run(self, paths: RunPaths, path: Path) -> str:
        return str(path.relative_to(paths.run_root)).replace("\\", "/")

    def _resolve_run_relative_path(self, paths: RunPaths, relative_path: str) -> Path:
        candidate = (paths.run_root / relative_path).resolve()
        run_root = paths.run_root.resolve()
        try:
            candidate.relative_to(run_root)
        except ValueError as exc:
            raise ValueError(f"Path escapes run root: {relative_path}") from exc
        return candidate


def _resolve_stage(stage_slug: str):
    for stage in STAGES:
        if stage.slug == stage_slug:
            return stage
    raise KeyError(f"Unknown stage slug: {stage_slug}")


def _affected_stage_slugs(base_stage_slug: str, scope_type: IterationScopeType) -> list[str]:
    base_stage = _resolve_stage(base_stage_slug)
    if scope_type == "stage":
        return [stage.slug for stage in STAGES if stage.number >= base_stage.number]
    if scope_type in {"file", "subtree", "manuscript"}:
        return [stage.slug for stage in STAGES if stage.number >= base_stage.number]
    return [base_stage.slug]


def _display_name_for_stage(stage_slug: str) -> str:
    for stage in STAGES:
        if stage.slug == stage_slug:
            return stage.stage_title
    return stage_slug.replace("_", " ")


def _humanize_trace_heading(value: str) -> str:
    normalized = value.replace("_", " ").strip()
    return " ".join(part.capitalize() for part in normalized.split())


def studio_to_dict(value):
    if isinstance(value, ArtifactIndex):
        return value.to_dict()
    return asdict(value)
