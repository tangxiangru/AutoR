from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from .utils import RunPaths, StageSpec, STAGES


@dataclass(frozen=True)
class StageManifestEntry:
    number: int
    slug: str
    title: str
    status: str = "pending"
    approved: bool = False
    skipped: bool = False
    skip_kind: str | None = None
    skip_reason: str | None = None
    dirty: bool = False
    stale: bool = False
    attempt_count: int = 0
    session_id: str | None = None
    final_stage_path: str = ""
    draft_stage_path: str = ""
    artifact_paths: list[str] = field(default_factory=list)
    last_error: str | None = None
    invalidated_reason: str | None = None
    invalidated_by_stage: str | None = None
    updated_at: str = ""
    approved_at: str | None = None

    @property
    def settled(self) -> bool:
        """The stage has a promoted summary, so the run should move past it.

        This is the resume cursor. ``approved`` is a narrower claim — that the
        stage's work was actually reviewed and accepted — and a skipped stage
        satisfies the first without satisfying the second.
        """
        return self.approved or self.skipped

    def to_dict(self) -> dict[str, object]:
        return {
            "number": self.number,
            "slug": self.slug,
            "title": self.title,
            "status": self.status,
            "approved": self.approved,
            "skipped": self.skipped,
            "skip_kind": self.skip_kind,
            "skip_reason": self.skip_reason,
            "settled": self.settled,
            "dirty": self.dirty,
            "stale": self.stale,
            "attempt_count": self.attempt_count,
            "session_id": self.session_id,
            "final_stage_path": self.final_stage_path,
            "draft_stage_path": self.draft_stage_path,
            "artifact_paths": list(self.artifact_paths),
            "last_error": self.last_error,
            "invalidated_reason": self.invalidated_reason,
            "invalidated_by_stage": self.invalidated_by_stage,
            "updated_at": self.updated_at,
            "approved_at": self.approved_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "StageManifestEntry":
        return cls(
            number=int(payload.get("number") or 0),
            slug=str(payload.get("slug") or ""),
            title=str(payload.get("title") or ""),
            status=str(payload.get("status") or "pending"),
            approved=bool(payload.get("approved", False)),
            skipped=bool(payload.get("skipped", False)),
            skip_kind=str(payload["skip_kind"]) if payload.get("skip_kind") is not None else None,
            skip_reason=str(payload["skip_reason"]) if payload.get("skip_reason") is not None else None,
            dirty=bool(payload.get("dirty", False)),
            stale=bool(payload.get("stale", False)),
            attempt_count=int(payload.get("attempt_count") or 0),
            session_id=str(payload["session_id"]) if payload.get("session_id") is not None else None,
            final_stage_path=str(payload.get("final_stage_path") or ""),
            draft_stage_path=str(payload.get("draft_stage_path") or ""),
            artifact_paths=[str(item) for item in payload.get("artifact_paths", []) if str(item).strip()],
            last_error=str(payload["last_error"]) if payload.get("last_error") is not None else None,
            invalidated_reason=str(payload["invalidated_reason"]) if payload.get("invalidated_reason") is not None else None,
            invalidated_by_stage=str(payload["invalidated_by_stage"]) if payload.get("invalidated_by_stage") is not None else None,
            updated_at=str(payload.get("updated_at") or ""),
            approved_at=str(payload["approved_at"]) if payload.get("approved_at") is not None else None,
        )


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    created_at: str
    updated_at: str
    run_status: str
    last_event: str
    current_stage_slug: str | None
    last_error: str | None
    completed_at: str | None
    stages: list[StageManifestEntry]

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "run_status": self.run_status,
            "last_event": self.last_event,
            "current_stage_slug": self.current_stage_slug,
            "last_error": self.last_error,
            "completed_at": self.completed_at,
            "stages": [stage.to_dict() for stage in self.stages],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "RunManifest":
        stages = payload.get("stages", [])
        return cls(
            run_id=str(payload.get("run_id") or ""),
            created_at=str(payload.get("created_at") or _now()),
            updated_at=str(payload.get("updated_at") or _now()),
            run_status=str(payload.get("run_status") or "pending"),
            last_event=str(payload.get("last_event") or "run.created"),
            current_stage_slug=str(payload["current_stage_slug"]) if payload.get("current_stage_slug") is not None else None,
            last_error=str(payload["last_error"]) if payload.get("last_error") is not None else None,
            completed_at=str(payload["completed_at"]) if payload.get("completed_at") is not None else None,
            stages=[StageManifestEntry.from_dict(item) for item in stages if isinstance(item, dict)],
        )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def initialize_run_manifest(paths: RunPaths) -> RunManifest:
    timestamp = _now()
    manifest = RunManifest(
        run_id=paths.run_root.name,
        created_at=timestamp,
        updated_at=timestamp,
        run_status="pending",
        last_event="run.created",
        current_stage_slug=None,
        last_error=None,
        completed_at=None,
        stages=[
            StageManifestEntry(
                number=stage.number,
                slug=stage.slug,
                title=stage.stage_title,
                final_stage_path=str(paths.stage_file(stage).relative_to(paths.run_root)),
                draft_stage_path=str(paths.stage_tmp_file(stage).relative_to(paths.run_root)),
                updated_at=timestamp,
            )
            for stage in STAGES
        ],
    )
    save_run_manifest(paths.run_manifest, manifest)
    return manifest


def ensure_run_manifest(paths: RunPaths) -> RunManifest:
    manifest = load_run_manifest(paths.run_manifest)
    if manifest is not None:
        return manifest
    return initialize_run_manifest(paths)


def load_run_manifest(path) -> RunManifest | None:
    if not path.exists():
        return None
    # The file may be mid-write from a background runner thread. Retry a few
    # times on empty / partial reads instead of silently returning None (which
    # would trigger re-initialization and clobber in-flight progress).
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            last_error = exc
            text = ""
        if text:
            try:
                return RunManifest.from_dict(json.loads(text))
            except json.JSONDecodeError as exc:
                last_error = exc
        if attempt < 4:
            import time as _time

            _time.sleep(0.02 * (attempt + 1))
    if last_error is not None:
        # File exists but is unreadable after retries — propagate so the
        # caller can decide instead of re-initializing and losing state.
        raise RuntimeError(
            f"Failed to read run manifest at {path} after retries: {last_error}"
        ) from last_error
    return None


def save_run_manifest(path, manifest: RunManifest) -> None:
    """Atomically persist the manifest via tmp-file + os.replace.

    Non-atomic write_text('w') caused mid-write reads in concurrent callers
    (the Studio HTTP poller racing the background runner) to see an empty or
    partial file and re-initialize it, corrupting state. Atomic rename
    eliminates the window entirely.
    """
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest.to_dict(), indent=2, ensure_ascii=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(payload)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def format_manifest_status(manifest: RunManifest) -> str:
    lines = [
        f"Run: {manifest.run_id}",
        f"Updated At: {manifest.updated_at}",
        f"Run Status: {manifest.run_status}",
        f"Last Event: {manifest.last_event}",
        f"Current Stage: {manifest.current_stage_slug or 'None'}",
        "Stages:",
    ]
    for entry in manifest.stages:
        flags = []
        if entry.approved:
            flags.append("approved")
        if entry.skipped:
            flags.append(f"skipped:{entry.skip_kind or 'unknown'}")
        if entry.dirty:
            flags.append("dirty")
        if entry.stale:
            flags.append("stale")
        suffix = f" [{' '.join(flags)}]" if flags else ""
        lines.append(
            f"- {entry.slug}: status={entry.status}, approved={entry.approved}, attempts={entry.attempt_count}, "
            f"session_id={entry.session_id or 'none'}{suffix}"
        )
    return "\n".join(lines)


def update_manifest_run_status(
    paths: RunPaths,
    *,
    run_status: str,
    last_event: str,
    current_stage_slug: str | None = None,
    last_error: str | None = None,
    completed_at: str | None = None,
) -> RunManifest:
    manifest = ensure_run_manifest(paths)
    updated = RunManifest(
        run_id=manifest.run_id,
        created_at=manifest.created_at,
        updated_at=_now(),
        run_status=run_status,
        last_event=last_event,
        current_stage_slug=current_stage_slug,
        last_error=last_error,
        completed_at=completed_at,
        stages=manifest.stages,
    )
    save_run_manifest(paths.run_manifest, updated)
    return updated


def update_stage_entry(paths: RunPaths, stage: StageSpec, **changes: object) -> RunManifest:
    manifest = ensure_run_manifest(paths)
    updated_stages: list[StageManifestEntry] = []
    for entry in manifest.stages:
        if entry.slug != stage.slug:
            updated_stages.append(entry)
            continue
        payload = entry.to_dict()
        payload.update(changes)
        payload["updated_at"] = _now()
        updated_stages.append(StageManifestEntry.from_dict(payload))

    updated = RunManifest(
        run_id=manifest.run_id,
        created_at=manifest.created_at,
        updated_at=_now(),
        run_status=manifest.run_status,
        last_event=manifest.last_event,
        current_stage_slug=manifest.current_stage_slug,
        last_error=manifest.last_error,
        completed_at=manifest.completed_at,
        stages=updated_stages,
    )
    save_run_manifest(paths.run_manifest, updated)
    return updated


def mark_stage_running_manifest(paths: RunPaths, stage: StageSpec, attempt_no: int) -> RunManifest:
    update_manifest_run_status(
        paths,
        run_status="running",
        last_event="stage.started",
        current_stage_slug=stage.slug,
    )
    return update_stage_entry(
        paths,
        stage,
        status="running",
        approved=False,
        dirty=False,
        stale=False,
        attempt_count=attempt_no,
        last_error=None,
    )


def mark_stage_human_review_manifest(
    paths: RunPaths,
    stage: StageSpec,
    attempt_no: int,
    artifact_paths: list[str],
) -> RunManifest:
    update_manifest_run_status(
        paths,
        run_status="human_review",
        last_event="stage.awaiting_human_review",
        current_stage_slug=stage.slug,
    )
    return update_stage_entry(
        paths,
        stage,
        status="human_review",
        approved=False,
        dirty=False,
        stale=False,
        attempt_count=attempt_no,
        artifact_paths=artifact_paths,
    )


def mark_stage_approved_manifest(
    paths: RunPaths,
    stage: StageSpec,
    attempt_no: int,
    artifact_paths: list[str],
) -> RunManifest:
    update_manifest_run_status(
        paths,
        run_status="pending",
        last_event="stage.approved",
        current_stage_slug=None,
    )
    return update_stage_entry(
        paths,
        stage,
        status="approved",
        approved=True,
        skipped=False,
        skip_kind=None,
        skip_reason=None,
        dirty=False,
        stale=False,
        attempt_count=attempt_no,
        artifact_paths=artifact_paths,
        approved_at=_now(),
    )


def mark_stage_skipped_manifest(
    paths: RunPaths,
    stage: StageSpec,
    attempt_no: int,
    artifact_paths: list[str],
    *,
    reason: str,
    kind: str,
) -> RunManifest:
    """Record a stage that was promoted without its work being done.

    A skip settles the stage — the run moves on and downstream stages read the
    skip summary — but it is not an approval. Recording it as ``approved``
    would leave the manifest unable to distinguish reviewed work from an
    exhausted retry budget, which is exactly the distinction a downstream
    reader of the manifest needs.
    """
    if kind not in {"human", "auto"}:
        raise ValueError(f"skip kind must be 'human' or 'auto', got {kind!r}")
    update_manifest_run_status(
        paths,
        run_status="pending",
        last_event="stage.skipped",
        current_stage_slug=None,
    )
    return update_stage_entry(
        paths,
        stage,
        status="skipped",
        approved=False,
        skipped=True,
        skip_kind=kind,
        skip_reason=reason,
        dirty=False,
        stale=False,
        attempt_count=attempt_no,
        artifact_paths=artifact_paths,
        approved_at=None,
    )


def mark_stage_failed_manifest(paths: RunPaths, stage: StageSpec, error: str) -> RunManifest:
    update_manifest_run_status(
        paths,
        run_status="failed",
        last_event="stage.failed",
        current_stage_slug=stage.slug,
        last_error=error,
    )
    return update_stage_entry(
        paths,
        stage,
        status="failed",
        approved=False,
        dirty=True,
        stale=False,
        last_error=error,
    )


def sync_stage_session_id(paths: RunPaths, stage: StageSpec, session_id: str | None) -> RunManifest:
    return update_stage_entry(paths, stage, session_id=session_id)


def rollback_to_stage(paths: RunPaths, rollback_stage: StageSpec, reason: str | None = None) -> RunManifest:
    """Mark the manifest back to ``rollback_stage`` **and** take the workspace back with it.

    This function used to do only the first half. It set ``status``, ``approved``,
    ``dirty``, ``stale`` and ``invalidated_by_stage`` on the entries at and after the
    target and left ``workspace/`` untouched, so the artifacts of the future being
    abandoned stayed on disk and stayed countable. Six of the graph's forward guards count
    files; a run that rolled back from Stage 06 to Stage 03 found the edge out of Stage 03
    already open, satisfied by the data Stage 04 and Stage 05 had written under the design
    being abandoned.

    The recovery is wired here rather than at the three call sites so that no caller can
    reach a rollback without it. ``/back`` from the operator, a research round that
    redirected itself, and a review that withdrew an approval all go through this seam,
    and a rollback that recovered the workspace on two of the three paths would be worse
    than one that recovered on none: the difference between the paths is invisible in the
    run record.
    """

    from .effects import recover_to_stage
    from .utils import append_log_entry

    manifest = ensure_run_manifest(paths)
    invalidated_reason = reason or f"Rolled back to {rollback_stage.stage_title}"

    recovery = recover_to_stage(paths, rollback_stage, invalidated_reason)
    if recovery.touched:
        append_log_entry(paths.logs, "rollback recovery", recovery.render())
    updated_stages: list[StageManifestEntry] = []

    for entry in manifest.stages:
        payload = entry.to_dict()
        if entry.number < rollback_stage.number:
            updated_stages.append(entry)
            continue
        if entry.number == rollback_stage.number:
            payload.update(
                {
                    "status": "pending",
                    "approved": False,
                    "skipped": False,
                    "skip_kind": None,
                    "skip_reason": None,
                    "dirty": True,
                    "stale": False,
                    "approved_at": None,
                    "invalidated_reason": invalidated_reason,
                    "invalidated_by_stage": rollback_stage.slug,
                }
            )
        else:
            payload.update(
                {
                    "status": "stale",
                    "approved": False,
                    "skipped": False,
                    "skip_kind": None,
                    "skip_reason": None,
                    "dirty": True,
                    "stale": True,
                    "approved_at": None,
                    "invalidated_reason": invalidated_reason,
                    "invalidated_by_stage": rollback_stage.slug,
                }
            )
        payload["updated_at"] = _now()
        updated_stages.append(StageManifestEntry.from_dict(payload))

    updated = RunManifest(
        run_id=manifest.run_id,
        created_at=manifest.created_at,
        updated_at=_now(),
        run_status="pending",
        last_event="run.rolled_back",
        current_stage_slug=rollback_stage.slug,
        last_error=None,
        completed_at=None,
        stages=updated_stages,
    )
    save_run_manifest(paths.run_manifest, updated)
    rebuild_memory_from_manifest(paths, updated)
    return updated


def rebuild_memory_from_manifest(paths: RunPaths, manifest: RunManifest | None = None) -> None:
    manifest = manifest or ensure_run_manifest(paths)
    goal_text = paths.user_input.read_text(encoding="utf-8").strip()
    entries: list[str] = []
    from .utils import read_text, render_approved_stage_entry, write_text

    for stage in STAGES:
        entry = next(item for item in manifest.stages if item.slug == stage.slug)
        if not entry.settled:
            continue
        stage_path = paths.stage_file(stage)
        if not stage_path.exists():
            continue
        entries.append(render_approved_stage_entry(stage, read_text(stage_path)))

    body = (
        "# Approved Run Memory\n\n"
        "## Original User Goal\n"
        f"{goal_text}\n\n"
        "## Approved Stage Summaries\n\n"
    )
    body += "\n\n".join(entries) + "\n" if entries else "_None yet._\n"
    write_text(paths.memory, body)
