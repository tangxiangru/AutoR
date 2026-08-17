"""Which stage wrote each artifact, which version of it, and whether it still counts.

A rollback in AutoR was bookkeeping. :func:`src.manifest.rollback_to_stage` set
``stale``/``dirty``/``invalidated_by_stage`` on the manifest entries at and after the
target, and :meth:`src.manager.AutoRManager._rollback_and_jump` added a correction and a
log line. Nothing under ``workspace/`` moved. Every file the abandoned future wrote was
still on disk, and nothing on disk said which stage had written it.

Two consequences, and the second is the one that decided a run.

**A forward gate could be fed by the future it had just invalidated.** Six of the graph's
forward edges are guarded by counting files: ``_guard_design_artifacts`` counts
``workspace/data``, ``_guard_runnable_code`` counts ``workspace/code``,
``_guard_results_exist`` counts ``workspace/results``, ``_guard_validity_chain`` counts
``workspace/figures``, ``_guard_report_exists`` counts ``workspace/writing``. A run that
reached Stage 06, discovered the design was wrong and rolled back to Stage 03 then found
the edge out of Stage 03 already open — satisfied by the data files Stage 04 and Stage 05
had written under the design being abandoned. The gate meant to prove *this* visit did the
work was answering for the previous one.

``_guard_round_abandoned`` states the invariant the others were relying on: "Every other
guard here reads stage artifacts, which a rollback invalidates." That sentence was the
reason given for scoping one guard to the visit and leaving the rest global. It was not
true. A rollback invalidated manifest rows; the artifacts those guards read were untouched.

**The same defect had already been patched once, by hand.** ``_skip_stage`` carries the
note that a skipped Stage 06's round declaration is "never consumed and never unlinked.
Left on disk, the *next* Stage 06 closes its round from the previous visit's file —
inheriting a conclusion drawn from results it did not produce." One instance, one patch,
at one path. The general shape — a stage's output outliving the stage's approval — had no
mechanism behind it.

This module is that mechanism's first half: it makes *attribution* exist. Without a record
of which stage produced a file, "withdraw Stage 04's contribution" has no referent, and a
guard cannot tell an artifact it should count from one it should not. :mod:`src.effects`
is the second half, and turns attribution into recovery.

**Attribution is observed, not declared.** The stage's work is done by an agent CLI writing
files directly, so AutoR cannot intercept the writes. It can only compare: each row keeps a
content hash per version, and :func:`observe` re-scans the workspace at a stage boundary and
attributes whatever is new or changed to the stage that just ran. That is weaker than
instrumentation in one specific way, recorded per version as ``restorable``: a version whose
bytes AutoR never held can be withdrawn from the guards and deleted, but not rewound to. The
limit is the system boundary of a revertible-effect model drawn where it actually falls —
per file, by whether the previous state can be restored, rather than per medium.

**A row is a version chain, not a single state.** A file created at Stage 02 and rewritten
at Stage 05 has two versions, and rolling back to Stage 04 does not withdraw it: it rewinds
it to what Stage 02 left. Withdrawal is for files whose *creator* is being withdrawn. Keeping
only the latest version would collapse the two cases into "delete", which would take Stage
02's honest work with Stage 05's — which is precisely the loss a graph topology exists to
avoid.

**Version identity is a fresh name, never a value.** ``version_uid`` is drawn from a counter
that only ever increases, and a uid retired by a rewind is not reissued. A consumer that
recorded ``a000007`` and finds ``a000019`` knows its input changed, without comparing values
— two stages can write byte-identical content and still be distinguishable, which is what a
re-run after a rollback produces and what a value comparison would silently miss.

The ledger lives under ``evolution/`` beside the other records of how a run reached its
answer, not under ``workspace/``, so a benchmark export of the workspace does not ship it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .utils import INTAKE_STAGE, RunPaths, StageSpec, STAGES

#: Directory names never walked when attributing artifacts. Caches and version-control
#: metadata are not research output, and a ``.git`` under the workspace would make the
#: scan quadratic in the run's own history.
SKIP_DIR_NAMES = frozenset(
    {"__pycache__", ".git", ".ipynb_checkpoints", "node_modules", ".venv", ".pytest_cache"}
)

#: Workspace files a rollback must not touch, by path relative to ``workspace/``.
#:
#: The distinction is the one ``_guard_round_abandoned`` already draws: "Every other guard
#: here reads stage artifacts, which a rollback invalidates. This one reads a *ledger*." An
#: artifact is a stage's claim about the research and is withdrawn with the stage. A ledger
#: is the run's record of how it got here, and survives the stages it describes — otherwise
#: a rollback launders it. ``research_rounds.json`` is the case with a test on it already:
#: a round that concluded the question cannot be answered must not become answerable again
#: by rolling back to Stage 03 and resuming, and it would if the rollback rewound the file
#: recording the abandonment.
#:
#: ``preregistration.json`` is here for a different reason. It has its own invalidation
#: path in :mod:`src.preregistration`, stamped outside the workspace and checked for
#: tampering, and two mechanisms deciding whether one frozen document still counts is how
#: they drift apart.
#:
#: Excluded at :func:`observe` rather than at withdrawal, so these files carry no
#: attribution at all and the fail-open rule in :func:`is_live` keeps them countable.
LEDGER_PATHS = frozenset(
    {
        "notes/research_rounds.json",
        "notes/round_decision.json",
        "notes/preregistration.json",
    }
)

#: Where the boundary falls. Under it, ``observe`` keeps a copy of the bytes so a later
#: rollback can restore that version; over it, the version records ``restorable=False``
#: and a rollback can only withdraw and delete. A cap rather than a medium: the same
#: directory holds a 2 KB results table AutoR can rewind and a 4 GB checkpoint it cannot,
#: and the honest record says so per version.
RESTORABLE_BYTE_LIMIT = 8 * 1024 * 1024

#: Intake is in here at number 0 on purpose. Whatever bootstrap puts in the workspace
#: before Stage 01 runs is attributed to intake, and no rollback targets a stage below
#: 01, so those files are never withdrawn. Leaving intake out would reach the same
#: behaviour through an unattributed row, which is the same answer for the wrong reason
#: and would change the day someone rolls back to Stage 00.
_STAGE_NUMBER_BY_SLUG: dict[str, int] = {
    stage.slug: stage.number for stage in (INTAKE_STAGE, *STAGES)
}


def stage_number_for_slug(slug: str) -> int | None:
    """The stage number a slug names, or ``None`` when it names no stage.

    Rows written by an earlier AutoR, or by a caller passing a label that is not a
    stage, resolve to ``None`` and are treated as unattributed everywhere below.
    """

    return _STAGE_NUMBER_BY_SLUG.get(str(slug).strip())


@dataclass(frozen=True)
class ArtifactVersion:
    """One set of bytes a file held, and which stage's window left it that way."""

    stage: str
    version_uid: str
    content_hash: str
    size_bytes: int
    at: str
    #: Whether ``blob_hash`` holds the bytes, so a rollback can rewind to this version
    #: rather than only delete past it. False above :data:`RESTORABLE_BYTE_LIMIT`.
    restorable: bool = True
    blob_hash: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "version_uid": self.version_uid,
            "content_hash": self.content_hash,
            "size_bytes": self.size_bytes,
            "at": self.at,
            "restorable": self.restorable,
            "blob_hash": self.blob_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ArtifactVersion":
        return cls(
            stage=str(payload.get("stage", "")).strip(),
            version_uid=str(payload.get("version_uid", "")).strip(),
            content_hash=str(payload.get("content_hash", "")).strip(),
            size_bytes=int(payload.get("size_bytes", 0) or 0),
            at=str(payload.get("at", "")).strip(),
            restorable=bool(payload.get("restorable", True)),
            blob_hash=str(payload.get("blob_hash", "")).strip(),
        )


@dataclass(frozen=True)
class ArtifactProvenance:
    """One workspace file: every version it has held, and whether it still counts."""

    rel_path: str
    versions: tuple[ArtifactVersion, ...] = ()
    #: Set when a rollback withdrew the stage that *created* this file. The row is kept
    #: rather than dropped: a reader has to be able to tell a withdrawn artifact from
    #: one that was never seen, and the fail-open rule in :func:`is_live` reads an unseen
    #: file as countable — so dropping the row would hand the withdrawn artifact straight
    #: back to the gate it was withdrawn from.
    invalidated_by_stage: str | None = None
    invalidated_reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "rel_path": self.rel_path,
            "produced_by_stage": self.produced_by_stage,
            "last_written_by_stage": self.last_written_by_stage,
            "version_uid": self.version_uid,
            "content_hash": self.content_hash,
            "size_bytes": self.size_bytes,
            "first_seen_at": self.first_seen_at,
            "updated_at": self.updated_at,
            "invalidated_by_stage": self.invalidated_by_stage,
            "invalidated_reason": self.invalidated_reason,
            "restorable": self.restorable,
            "blob_hash": self.blob_hash,
            "versions": [version.to_dict() for version in self.versions],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ArtifactProvenance":
        raw_versions = payload.get("versions")
        versions: list[ArtifactVersion] = []
        if isinstance(raw_versions, list):
            versions = [
                ArtifactVersion.from_dict(item) for item in raw_versions if isinstance(item, dict)
            ]
        if not versions:
            # A row written before version chains existed carries one flat state. Read
            # as a single version so the chain-aware readers below need no second shape.
            stage = str(payload.get("produced_by_stage", "")).strip()
            if stage or payload.get("content_hash"):
                versions = [
                    ArtifactVersion(
                        stage=stage,
                        version_uid=str(payload.get("version_uid", "")).strip(),
                        content_hash=str(payload.get("content_hash", "")).strip(),
                        size_bytes=int(payload.get("size_bytes", 0) or 0),
                        at=str(payload.get("updated_at", "")).strip(),
                        restorable=bool(payload.get("restorable", True)),
                        blob_hash=str(payload.get("blob_hash", "")).strip(),
                    )
                ]
        invalidated = payload.get("invalidated_by_stage")
        return cls(
            rel_path=str(payload.get("rel_path", "")).strip(),
            versions=tuple(versions),
            invalidated_by_stage=(
                str(invalidated).strip()
                if isinstance(invalidated, str) and invalidated.strip()
                else None
            ),
            invalidated_reason=str(payload.get("invalidated_reason", "")).strip(),
        )

    @property
    def live(self) -> bool:
        return self.invalidated_by_stage is None

    @property
    def produced_by_stage(self) -> str:
        return self.versions[0].stage if self.versions else ""

    @property
    def last_written_by_stage(self) -> str:
        return self.versions[-1].stage if self.versions else ""

    @property
    def version_uid(self) -> str:
        return self.versions[-1].version_uid if self.versions else ""

    @property
    def content_hash(self) -> str:
        return self.versions[-1].content_hash if self.versions else ""

    @property
    def size_bytes(self) -> int:
        return self.versions[-1].size_bytes if self.versions else 0

    @property
    def restorable(self) -> bool:
        return self.versions[-1].restorable if self.versions else False

    @property
    def blob_hash(self) -> str:
        return self.versions[-1].blob_hash if self.versions else ""

    @property
    def first_seen_at(self) -> str:
        return self.versions[0].at if self.versions else ""

    @property
    def updated_at(self) -> str:
        return self.versions[-1].at if self.versions else ""

    def restore_point(self, before_stage_number: int) -> ArtifactVersion | None:
        """The latest version written by a stage strictly before ``before_stage_number``.

        What the file should say once every stage at or after that number is withdrawn.
        ``None`` when the file has no such version, which means it did not exist before
        the withdrawn range and withdrawing the range deletes it.
        """

        candidate: ArtifactVersion | None = None
        for version in self.versions:
            number = stage_number_for_slug(version.stage)
            if number is None or number >= before_stage_number:
                continue
            candidate = version
        return candidate

    def trimmed_to(self, before_stage_number: int) -> "ArtifactProvenance":
        """This row with every version written at or after ``before_stage_number`` dropped."""

        kept = tuple(
            version
            for version in self.versions
            if (stage_number_for_slug(version.stage) or -1) < before_stage_number
        )
        return replace(self, versions=kept)


@dataclass(frozen=True)
class ProvenanceLedger:
    #: Monotone. The next uid to hand out, never decreased and never rewound by a
    #: withdrawal, so a uid names one version of one file for the life of the run.
    next_uid: int
    entries: dict[str, ArtifactProvenance] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "next_uid": self.next_uid,
            "entries": [
                entry.to_dict() for entry in sorted(self.entries.values(), key=lambda e: e.rel_path)
            ],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ProvenanceLedger":
        entries: dict[str, ArtifactProvenance] = {}
        raw_entries = payload.get("entries", [])
        if isinstance(raw_entries, list):
            for item in raw_entries:
                if not isinstance(item, dict):
                    continue
                record = ArtifactProvenance.from_dict(item)
                if record.rel_path:
                    entries[record.rel_path] = record
        return cls(next_uid=int(payload.get("next_uid", 1) or 1), entries=entries)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ledger_path(paths: RunPaths) -> Path:
    return paths.evolution_dir / "artifact_provenance.json"


def blob_dir(paths: RunPaths) -> Path:
    return paths.evolution_dir / "effects" / "blobs"


def load_ledger(paths: RunPaths) -> ProvenanceLedger:
    path = ledger_path(paths)
    if not path.exists():
        return ProvenanceLedger(next_uid=1)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        # A ledger that cannot be read is not a reason to refuse every gate. The
        # fail-open rule in `is_live` covers an empty ledger, so a corrupt one degrades
        # to the pre-provenance behaviour rather than to a stuck run.
        return ProvenanceLedger(next_uid=1)
    if not isinstance(payload, dict):
        return ProvenanceLedger(next_uid=1)
    return ProvenanceLedger.from_dict(payload)


def save_ledger(paths: RunPaths, ledger: ProvenanceLedger) -> None:
    path = ledger_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(ledger.to_dict(), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_identity(path: Path, size_bytes: int) -> str:
    """A value that changes when the file's contents change.

    A digest below :data:`RESTORABLE_BYTE_LIMIT`, and size-and-mtime above it.

    :func:`observe` runs at every stage boundary and walks the whole workspace, so the
    cost of this call is paid eight times a run over everything the run has produced. A
    training checkpoint is the case that matters: hashing four gigabytes eight times to
    learn something the run cannot act on is the wrong trade, because a version over the
    limit is recorded ``restorable=False`` and a rollback can only delete it. What is
    needed above the limit is *change detection*, not content addressing, and size with
    mtime is the standard cheap detector for that.

    What it costs is the case where a large file is rewritten within the same second at
    exactly its previous length. Such a rewrite is read as no change, so the version chain
    misses it and a rollback deletes the file rather than rewinding — which is what it
    would have done anyway, the bytes never having been held.
    """

    if size_bytes > RESTORABLE_BYTE_LIMIT:
        return f"size-mtime:{size_bytes}:{path.stat().st_mtime_ns}"
    return hash_file(path)


def store_blob(paths: RunPaths, payload: bytes) -> str:
    """Put bytes in the content-addressed store and return their hash.

    Write-once: two versions with the same bytes share one blob, and re-storing an
    existing one is a no-op rather than a rewrite, so a restore cannot race a store.
    """

    digest = hash_bytes(payload)
    target = blob_dir(paths) / digest
    if target.exists():
        return digest
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(payload)
    tmp.replace(target)
    return digest


def load_blob(paths: RunPaths, digest: str) -> bytes | None:
    if not digest:
        return None
    target = blob_dir(paths) / digest
    if not target.exists():
        return None
    return target.read_bytes()


def _walk_workspace(paths: RunPaths) -> list[Path]:
    root = paths.workspace_root
    if not root.exists():
        return []
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_DIR_NAMES for part in relative.parts[:-1]):
            continue
        if relative.as_posix() in LEDGER_PATHS:
            continue
        found.append(path)
    return found


def observe(paths: RunPaths, stage: StageSpec | str) -> ProvenanceLedger:
    """Attribute everything new or changed under ``workspace/`` to the stage that ran.

    Called at a stage boundary. A path whose bytes match the newest version on record is
    untouched work and gets no new version. Anything else — a path the ledger has never
    seen, or one whose bytes moved — gets a version appended, naming this stage and a
    fresh uid.

    A row carrying a withdrawal is revived only if its bytes changed. A rollback that
    could not delete a file leaves it on disk withdrawn, and a re-run that genuinely
    rewrote it clears the withdrawal. A re-run that did not touch it leaves it withdrawn,
    which is the point: the file is still the abandoned future's, and the gate that counts
    it should still not count it.
    """

    slug = stage.slug if isinstance(stage, StageSpec) else str(stage).strip()
    ledger = load_ledger(paths)
    entries = dict(ledger.entries)
    next_uid = ledger.next_uid
    now = _now()

    for path in _walk_workspace(paths):
        rel_path = path.relative_to(paths.workspace_root).as_posix()
        try:
            stat = path.stat()
            digest = content_identity(path, stat.st_size)
        except OSError:
            continue

        existing = entries.get(rel_path)
        if existing is not None and existing.content_hash == digest:
            continue

        restorable = stat.st_size <= RESTORABLE_BYTE_LIMIT
        blob_hash = ""
        if restorable:
            try:
                blob_hash = store_blob(paths, path.read_bytes())
            except OSError:
                restorable = False
                blob_hash = ""

        version = ArtifactVersion(
            stage=slug,
            version_uid=f"a{next_uid:06d}",
            content_hash=digest,
            size_bytes=stat.st_size,
            at=now,
            restorable=restorable,
            blob_hash=blob_hash,
        )
        next_uid += 1

        if existing is None:
            entries[rel_path] = ArtifactProvenance(rel_path=rel_path, versions=(version,))
            continue

        entries[rel_path] = replace(
            existing,
            versions=(*existing.versions, version),
            # The bytes moved, so whatever withdrew this path no longer describes it.
            invalidated_by_stage=None,
            invalidated_reason="",
        )

    updated = ProvenanceLedger(next_uid=next_uid, entries=entries)
    save_ledger(paths, updated)
    return updated


@dataclass(frozen=True)
class Withdrawal:
    """What a rollback determined about one file, before anything on disk moved."""

    entry: ArtifactProvenance
    #: The version to put back, or ``None`` when the file did not exist before the
    #: withdrawn range and should be deleted.
    restore_to: ArtifactVersion | None

    @property
    def rel_path(self) -> str:
        return self.entry.rel_path

    @property
    def deletes(self) -> bool:
        return self.restore_to is None


def plan_withdrawal(paths: RunPaths, stage: StageSpec) -> list[Withdrawal]:
    """What withdrawing every stage at or after ``stage`` implies for each file.

    Read-only. Two cases per file, and separating them is the point of keeping version
    chains: a file created inside the withdrawn range has no earlier version and goes
    away, while a file created before it and amended inside it rewinds to what the last
    stage outside the range left. Collapsing both into "delete" would discard the work of
    stages the rollback never touched.
    """

    ledger = load_ledger(paths)
    plan: list[Withdrawal] = []
    for entry in sorted(ledger.entries.values(), key=lambda item: item.rel_path):
        if not entry.versions:
            continue
        touched = any(
            (stage_number_for_slug(version.stage) or -1) >= stage.number
            for version in entry.versions
        )
        if not touched:
            continue
        plan.append(Withdrawal(entry=entry, restore_to=entry.restore_point(stage.number)))
    return plan


def snapshot(paths: RunPaths) -> dict[str, str]:
    """Where every tracked file stands right now, as a version identifier per path.

    Not a copy of the workspace. The blobs behind those versions are already in the
    content-addressed store, so a snapshot is a set of pointers into it — cheap enough to
    take whenever the walk leaves a stage, which is what makes it usable as the boundary of
    an excursion.

    A path absent from a snapshot is a path that did not exist at that moment, which is
    what :func:`plan_restore` reads as "delete this on the way back".
    """

    ledger = load_ledger(paths)
    return {
        rel_path: entry.version_uid
        for rel_path, entry in ledger.entries.items()
        if entry.live and entry.version_uid
    }


def plan_restore(paths: RunPaths, marks: Mapping[str, str]) -> list[Withdrawal]:
    """What it takes to put the workspace back to a snapshot. Read-only.

    Expressed as the same :class:`Withdrawal` list a stage-range withdrawal produces, so
    one applier serves both. The difference is only in how the target version is chosen:
    by stage number there, by recorded identifier here.

    A file whose version has not moved is not in the plan. A file created since the
    snapshot is deleted. A file that has moved is rewound to the version the snapshot
    names, if that version is still in the chain — a chain trimmed by an intervening
    withdrawal may no longer carry it, and the honest answer then is to delete rather than
    to leave a later version in place and call it restored.
    """

    ledger = load_ledger(paths)
    plan: list[Withdrawal] = []
    for rel_path, entry in sorted(ledger.entries.items()):
        wanted = marks.get(rel_path)
        if wanted is not None and entry.version_uid == wanted:
            continue
        target = (
            next((version for version in entry.versions if version.version_uid == wanted), None)
            if wanted is not None
            else None
        )
        plan.append(Withdrawal(entry=entry, restore_to=target))
    return plan


def trim_to_snapshot(paths: RunPaths, marks: Mapping[str, str]) -> None:
    """Cut every version chain back to the version the snapshot names.

    Called after the files have moved, so the ledger describes the workspace the restore
    leaves rather than the one it found. Rows whose path is not in the snapshot are dropped
    outright: :func:`plan_restore` deleted the file, and a row for a path that is not on
    disk would make the next :func:`observe` read the next creation as a rewrite of
    something that was never there.
    """

    ledger = load_ledger(paths)
    entries: dict[str, ArtifactProvenance] = {}
    for rel_path, entry in ledger.entries.items():
        wanted = marks.get(rel_path)
        if wanted is None:
            continue
        kept: list[ArtifactVersion] = []
        for version in entry.versions:
            kept.append(version)
            if version.version_uid == wanted:
                break
        if kept:
            entries[rel_path] = replace(
                entry,
                versions=tuple(kept),
                invalidated_by_stage=None,
                invalidated_reason="",
            )
    save_ledger(paths, ProvenanceLedger(next_uid=ledger.next_uid, entries=entries))


def plan_single_stage_withdrawal(
    paths: RunPaths, stage: StageSpec
) -> tuple[list[Withdrawal], list[str]]:
    """What withdrawing *only* this stage implies, and what stops it.

    Returns the plan and the list of contested paths -- files this stage wrote that a later
    stage has written since. A contested file cannot be handled selectively: rewinding it to
    what preceded this stage would discard the later stage's work, and leaving it alone
    would leave this stage's work standing. The caller either drops back to a reverse-order
    withdrawal or refuses, and the contested list is what it says when it does.

    Uncontested files rewind to the last version written by a stage other than this one, or
    are deleted where there is none. Same two cases as :func:`plan_withdrawal`; the
    difference is only which versions count as inside the range.
    """

    ledger = load_ledger(paths)
    plan: list[Withdrawal] = []
    contested: list[str] = []
    for rel_path, entry in sorted(ledger.entries.items()):
        indices = [i for i, v in enumerate(entry.versions) if v.stage == stage.slug]
        if not indices:
            continue
        if any(v.stage != stage.slug for v in entry.versions[indices[0] + 1 :]):
            contested.append(rel_path)
            continue
        restore_to = entry.versions[indices[0] - 1] if indices[0] > 0 else None
        plan.append(Withdrawal(entry=entry, restore_to=restore_to))
    return plan, contested


def trim_stage_versions(paths: RunPaths, stage: StageSpec, rel_paths: Sequence[str]) -> None:
    """Drop this stage's versions from the named chains, after the files have moved.

    Called with the uncontested paths only, so every version being dropped is one this
    stage wrote and nothing later depends on. A row left with no versions is dropped
    entirely: the file was deleted, and a row for a path that is not on disk would make the
    next :func:`observe` read the next creation as a rewrite of something never there.
    """

    targets = {str(item) for item in rel_paths}
    if not targets:
        return
    ledger = load_ledger(paths)
    entries: dict[str, ArtifactProvenance] = {}
    for rel_path, entry in ledger.entries.items():
        if rel_path not in targets:
            entries[rel_path] = entry
            continue
        kept = tuple(v for v in entry.versions if v.stage != stage.slug)
        if kept:
            entries[rel_path] = replace(
                entry, versions=kept, invalidated_by_stage=None, invalidated_reason=""
            )
    save_ledger(paths, ProvenanceLedger(next_uid=ledger.next_uid, entries=entries))


def invalidate_from(
    paths: RunPaths,
    stage: StageSpec,
    reason: str = "",
) -> list[Withdrawal]:
    """Withdraw every version written at or after ``stage``. Returns what was withdrawn.

    Only the ledger moves here; :func:`src.effects.apply_withdrawal` is what moves the
    files. Rows whose creator is inside the withdrawn range are marked invalidated and
    kept; rows that merely have versions inside it are trimmed back to their restore
    point and stay live.
    """

    ledger = load_ledger(paths)
    plan = plan_withdrawal(paths, stage)
    if not plan:
        return []

    note = reason.strip() or f"Rolled back to {stage.stage_title}"
    entries = dict(ledger.entries)
    for item in plan:
        if item.deletes:
            # Marked, not trimmed. Trimming a row whose every version is inside the
            # withdrawn range empties its chain, and an empty chain reports no content
            # hash — so the next `observe` compares the file on disk against nothing,
            # reads it as changed, and revives the withdrawal. A file the rollback could
            # not delete would count again at the next boundary, which is the whole
            # defect this module exists to close. The history stays: it is the record of
            # what the abandoned future did, and the row is dropped outright by
            # `drop_entries` once the file is actually gone.
            entries[item.rel_path] = replace(
                item.entry, invalidated_by_stage=stage.slug, invalidated_reason=note
            )
        else:
            # Trimmed, because the chain now has to describe the file as the rewind
            # leaves it: the restore point is the newest version, and its hash is what
            # the next `observe` will find on disk.
            entries[item.rel_path] = replace(
                item.entry.trimmed_to(stage.number),
                invalidated_by_stage=None,
                invalidated_reason="",
            )

    save_ledger(paths, ProvenanceLedger(next_uid=ledger.next_uid, entries=entries))
    return plan


def drop_entries(paths: RunPaths, rel_paths: Iterable[str]) -> None:
    """Forget the named rows entirely, for paths whose files no longer exist.

    Only :mod:`src.effects` calls this, and only after it has deleted the file. A row for
    a path that is not on disk would make :func:`observe` treat the next creation as a
    rewrite of something that was never there.
    """

    targets = {str(item).strip() for item in rel_paths if str(item).strip()}
    if not targets:
        return
    ledger = load_ledger(paths)
    entries = {key: value for key, value in ledger.entries.items() if key not in targets}
    if len(entries) != len(ledger.entries):
        save_ledger(paths, ProvenanceLedger(next_uid=ledger.next_uid, entries=entries))


def is_live(ledger: ProvenanceLedger, rel_path: str) -> bool:
    """Whether a path counts. Unknown paths count.

    Fail-open, deliberately. A run started before this ledger existed, a resumed run whose
    ledger did not survive, and a file written outside any stage's window all reach here
    with no row. Reading those as withdrawn would close every counting gate in the graph
    at once, and a precondition no real run can meet is not a strict gate, it is a broken
    one — which this repo has already shipped once, in ``_guard_results_exist``. Only an
    explicit withdrawal takes a file out of a count.
    """

    entry = ledger.entries.get(rel_path)
    if entry is None:
        return True
    return entry.live


def unreviewed_stage_slugs(paths: RunPaths) -> set[str]:
    """Stages the manifest records as skipped and not approved.

    Derived rather than stored, and that is the whole design of this state. A stored flag
    would have to be set where a skip happens, cleared where the stage is later approved,
    and kept in step with a manifest that already knows the answer -- three places to drift
    where the manifest is the authority. Reading it means the flag clears by itself the
    moment the stage is genuinely re-run and accepted.

    Both kinds of skip count, and so does the rescued-draft case. ``_skip_stage`` records
    every one of them as ``skipped`` with ``approved`` false, and says of the rescue that
    "it is promoted but was never reviewed" -- which is exactly the claim this set makes.
    """

    from .manifest import load_run_manifest

    manifest = load_run_manifest(paths.run_manifest)
    if manifest is None:
        return set()
    return {
        entry.slug
        for entry in manifest.stages
        if entry.skipped and not entry.approved and entry.slug
    }


def unreviewed_paths(paths: RunPaths) -> set[str]:
    """Files whose most recent writer is a stage nobody accepted.

    Keyed on the *last* writer rather than the creator. A file Stage 03 created and a
    skipped Stage 05 rewrote holds Stage 05's content, and whether that content was
    accepted is the question this answers; the creator only decides who owns the file for
    a withdrawal.

    This is deliberately not a withdrawal. These files still count toward the forward
    gates, because an auto-skip is a decision to *continue* past a failure rather than to
    repudiate the work -- measured across the run archive, skipping is how a majority of
    runs get past a stage that ran out of attempts, and closing their forward edge would
    turn "this stage did not finish" into "the run stops". What the flag buys is that a
    reader can tell accepted work from residue, which is the thing that was missing.
    """

    ledger = load_ledger(paths)
    unreviewed = unreviewed_stage_slugs(paths)
    if not unreviewed:
        return set()
    return {
        rel_path
        for rel_path, entry in ledger.entries.items()
        if entry.live and entry.last_written_by_stage in unreviewed
    }


def paths_written_by(paths: RunPaths, stage: StageSpec) -> list[str]:
    """Every live workspace file this stage wrote most recently, in path order.

    What a stage's own record should be able to name. ``_build_skipped_stage_markdown``
    heads a section "Files Produced" and lists only the stage's summary, so a skipped
    stage that left three result files on disk published a record saying it produced one
    file and did no work.
    """

    ledger = load_ledger(paths)
    return sorted(
        rel_path
        for rel_path, entry in ledger.entries.items()
        if entry.live and entry.last_written_by_stage == stage.slug
    )


def path_is_live(paths: RunPaths, path: Path) -> bool:
    """Whether one named file counts, for a guard that checks existence rather than count.

    Same fail-open rule as :func:`is_live`, and the same reason: a gate that reads a single
    well-known path must not close because no stage boundary has attributed it.
    """

    if not path.exists():
        return False
    try:
        rel_path = path.relative_to(paths.workspace_root).as_posix()
    except ValueError:
        return True
    return is_live(load_ledger(paths), rel_path)


def live_files(paths: RunPaths, directory: Path, suffixes: set[str]) -> list[Path]:
    """Files under ``directory`` with one of ``suffixes`` that a withdrawal has not taken.

    The guard-facing query. Walks the directory as the pre-provenance counter did and then
    subtracts what the ledger has withdrawn, so a gate reads the work of the visit it is
    gating rather than of the visit that was abandoned.
    """

    if not directory.exists():
        return []
    ledger = load_ledger(paths)
    root = paths.workspace_root
    found: list[Path] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        try:
            rel_path = path.relative_to(root).as_posix()
        except ValueError:
            # Outside the workspace, so no ledger row can describe it and no rollback
            # reaches it. Counted, as it was before.
            found.append(path)
            continue
        if is_live(ledger, rel_path):
            found.append(path)
    return found


def count_live_files(paths: RunPaths, directory: Path, suffixes: set[str]) -> int:
    return len(live_files(paths, directory, suffixes))


def format_withdrawal_plan(plan: Sequence[Withdrawal]) -> str:
    """What a rollback is about to do to the workspace, before it does it."""

    if not plan:
        return "No artifact needs withdrawing."
    deletes = [item for item in plan if item.deletes]
    rewinds = [item for item in plan if not item.deletes]
    lines = [f"{len(plan)} artifact(s) affected: {len(deletes)} deleted, {len(rewinds)} rewound."]
    for item in deletes:
        lines.append(f"- delete {item.rel_path} (created by {item.entry.produced_by_stage})")
    for item in rewinds:
        assert item.restore_to is not None
        lines.append(
            f"- rewind {item.rel_path} to {item.restore_to.version_uid} "
            f"({item.restore_to.stage})"
        )
    return "\n".join(lines)
