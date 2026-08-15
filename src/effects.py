"""Every write a stage makes carries the inverse that withdraws it.

:mod:`src.provenance` makes attribution exist — which stage wrote which file. This module
is what attribution is for: a stage's writes go through a primitive that returns, with the
write, the operation that undoes it, and the run keeps those inverses per stage. Rolling
back to Stage 03 stops being a manifest edit and becomes the application of Stage 04's,
Stage 05's and Stage 06's accumulated inverses, in reverse.

**Why an inverse per write rather than a snapshot of the run.** A snapshot is all or
nothing. It can restore the state before Stage 04 and it cannot withdraw Stage 04 while
Stage 06 stands, because it has no representation of one stage's contribution separately
from the run's. That distinction is the whole reason AutoR's topology is a graph: a late
finding invalidates *a* decision, not every decision that followed it in wall-clock order,
and a rollback that discards Stage 05's honest measurement along with Stage 04's wrong
design has thrown away the evidence that justified the move. Inverses composed per stage
support both: the reverse-order withdrawal, which needs no hypothesis at all and is what
:func:`recover_to_stage` performs, and the selective one, whose precondition
:func:`independence_obstruction` decides and which the rollback preview reports on.

**Inverses are data, not closures.** A run resumes in a new process — ``--resume-run`` is
routine, and a stage timeout is 14400 seconds — so an inverse held as a Python closure is
an inverse that does not survive the thing most likely to need it. Each is an
:class:`Inverse`: a kind naming one of the handlers in :data:`INVERSE_HANDLERS`, and a JSON
payload. The accumulator is a JSONL file under ``evolution/effects/``, appended to as the
stage runs, so a crash mid-stage leaves a partial accumulator that still withdraws
everything the stage had done up to the crash.

**Undo is unconditional.** No inverse here has a precondition it can fail: deleting a path
that is already gone succeeds, and restoring bytes creates the parent directories it needs.
An undo that can refuse is not an undo — it turns a rollback into a state the run has no
rule for, and the recovery it was supposed to perform into a partial one nobody records.

**What the primitives cover, and what they do not.** A stage's real work is done by an
agent CLI writing files directly, and those writes do not come through here; they are
picked up by :func:`src.provenance.observe` at the stage boundary, which stores the bytes
it can and marks the rest ``restorable=False``. So the recovery this module offers is
layered: writes made through a primitive are withdrawn exactly, observed writes are
withdrawn to the previous bytes when the ledger holds them and deleted when it does not,
and a file too large for the ledger is deleted with the fact recorded rather than silently
half-restored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import provenance
from .provenance import Withdrawal, load_blob, store_blob
from .utils import RunPaths, StageSpec, STAGES


# ----------------------------------------------------------------------------
# Keys and commutativity
# ----------------------------------------------------------------------------


#: A key names the shared location an effect writes, at the granularity at which two
#: effects can be asked whether they interfere. Not the file and not the row: the *table*.
#: Two appends to ``literature.sources`` are two entries in one table, and the question
#: "can one be withdrawn while the other stands" is answered once for the table.
#:
#: A key is commutative when its value is a collection whose entries are added and removed
#: independently — a set of sources, a set of hypotheses, a directory of result files. Two
#: writes to it in either order leave a collection that answers every read alike, and
#: either can be withdrawn while the other stands.
#:
#: A key is ordered when its value is a sequence whose entries see each other — a
#: narrative, an append-only log. A paragraph written after another reads differently
#: without it, and neither order can be withdrawn without disturbing the rest. Ordered keys
#: are not a defect to be fixed; they are where the order-sensitive part of the run lives,
#: and naming them is what lets everything else be reordered safely.
COMMUTATIVE_KEYS = frozenset(
    {
        "literature.sources",
        "literature.claims",
        "hypotheses",
        "data",
        "code",
        "results",
        "figures",
        "notes",
    }
)

ORDERED_KEYS = frozenset(
    {
        "report.draft",
        "run.log",
        "research.rounds",
    }
)


def is_commutative(key: str) -> bool:
    """Whether two effects on this key are independent.

    Unknown keys are ordered. A key nobody has classified is a key nobody has checked
    the two registrations of, and reading it as commutative would license exactly the
    reordering the classification exists to authorise.
    """

    return str(key).strip() in COMMUTATIVE_KEYS


def key_for_workspace_path(paths: RunPaths, rel_path: str) -> str:
    """The key a workspace path belongs to, from the directory it sits in."""

    head = str(rel_path).strip().replace("\\", "/").split("/", 1)[0]
    mapping = {
        "data": "data",
        "code": "code",
        "results": "results",
        "figures": "figures",
        "notes": "notes",
        "literature": "literature.sources",
        "writing": "report.draft",
        "report": "report.draft",
    }
    return mapping.get(head, "notes")


# ----------------------------------------------------------------------------
# Inverses
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Inverse:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "payload": dict(self.payload)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "Inverse":
        raw = payload.get("payload", {})
        return cls(
            kind=str(payload.get("kind", "noop")).strip() or "noop",
            payload=dict(raw) if isinstance(raw, dict) else {},
        )


@dataclass(frozen=True)
class EffectRecord:
    """One write, the key it landed on, and how to take it back."""

    stage: str
    key: str
    action: str
    rel_path: str
    inverse: Inverse
    at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "key": self.key,
            "action": self.action,
            "rel_path": self.rel_path,
            "inverse": self.inverse.to_dict(),
            "at": self.at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "EffectRecord":
        raw_inverse = payload.get("inverse", {})
        return cls(
            stage=str(payload.get("stage", "")).strip(),
            key=str(payload.get("key", "")).strip(),
            action=str(payload.get("action", "")).strip(),
            rel_path=str(payload.get("rel_path", "")).strip(),
            inverse=Inverse.from_dict(raw_inverse if isinstance(raw_inverse, dict) else {}),
            at=str(payload.get("at", "")).strip(),
        )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _resolve(paths: RunPaths, rel_path: str) -> Path:
    return paths.workspace_root / rel_path


def _invert_delete_path(paths: RunPaths, payload: Mapping[str, Any]) -> str:
    rel_path = str(payload.get("rel_path", "")).strip()
    if not rel_path:
        return "no path to delete"
    target = _resolve(paths, rel_path)
    if not target.exists():
        return f"{rel_path} was already gone"
    target.unlink()
    provenance.drop_entries(paths, [rel_path])
    return f"deleted {rel_path}"


def _invert_restore_blob(paths: RunPaths, payload: Mapping[str, Any]) -> str:
    rel_path = str(payload.get("rel_path", "")).strip()
    blob_hash = str(payload.get("blob_hash", "")).strip()
    if not rel_path:
        return "no path to restore"
    blob = load_blob(paths, blob_hash)
    if blob is None:
        # The bytes were never held — the file was over the restorable limit, or the
        # blob store was pruned. Deleting is the honest fallback: leaving the current
        # bytes in place would present a withdrawn stage's output as the restored state.
        return _invert_delete_path(paths, {"rel_path": rel_path}) + " (no stored bytes to restore)"
    target = _resolve(paths, rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(blob)
    return f"restored {rel_path}"


def _invert_noop(paths: RunPaths, payload: Mapping[str, Any]) -> str:
    return str(payload.get("note", "")).strip() or "nothing to undo"


#: Every inverse the accumulator can hold. A record naming a kind that is not here is
#: reported and skipped rather than raised on: one unreadable row must not stop the
#: rest of a rollback, because the rows after it are the ones nearest the current state.
INVERSE_HANDLERS: dict[str, Callable[[RunPaths, Mapping[str, Any]], str]] = {
    "delete_path": _invert_delete_path,
    "restore_blob": _invert_restore_blob,
    "noop": _invert_noop,
}


# ----------------------------------------------------------------------------
# The accumulator
# ----------------------------------------------------------------------------


def effects_dir(paths: RunPaths) -> Path:
    return paths.evolution_dir / "effects"


def accumulator_path(paths: RunPaths, stage: StageSpec | str) -> Path:
    slug = stage.slug if isinstance(stage, StageSpec) else str(stage).strip()
    return effects_dir(paths) / f"{slug}.jsonl"


def reverted_path(paths: RunPaths, stage: StageSpec | str) -> Path:
    slug = stage.slug if isinstance(stage, StageSpec) else str(stage).strip()
    return effects_dir(paths) / f"{slug}.reverted.jsonl"


def record_effect(paths: RunPaths, record: EffectRecord) -> EffectRecord:
    """Append one inverse to its stage's accumulator.

    Appended as the effect happens rather than gathered at the end, so the accumulator
    of a stage killed by its 14400-second timeout still withdraws what it managed to do.
    """

    path = accumulator_path(paths, record.stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.to_dict(), ensure_ascii=True) + "\n")
    return record


def load_accumulator(paths: RunPaths, stage: StageSpec | str) -> list[EffectRecord]:
    path = accumulator_path(paths, stage)
    if not path.exists():
        return []
    records: list[EffectRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(EffectRecord.from_dict(payload))
    return records


def keys_touched(records: Sequence[EffectRecord]) -> set[str]:
    return {record.key for record in records if record.key}


def independence_obstruction(
    target: Sequence[EffectRecord],
    later: Sequence[EffectRecord],
) -> str | None:
    """Why ``target`` cannot be withdrawn while ``later`` stands, or ``None`` if it can.

    Two effects at distinct keys never interfere: each reads and writes its own
    collection, so either order leaves the same state and either can be withdrawn while
    the other stands. Two effects at one key interfere unless the key is commutative.
    So the obstruction is exactly the ordered keys both sides touch.

    Withdrawing in reverse order — the target stage and everything after it — needs none
    of this and never consults it: each inverse then meets the state its own application
    produced. This function is asked only when a caller wants to withdraw a stage out of
    order and keep the work that followed.
    """

    shared = keys_touched(target) & keys_touched(later)
    blocking = sorted(key for key in shared if not is_commutative(key))
    if not blocking:
        return None

    # Two ways to be blocking, and they call for different repairs. A key in
    # `ORDERED_KEYS` is a genuine finding about the research: a narrative or a log was
    # written by both sides, and no reordering of those is sound. A key in neither set is
    # a finding about this file: somebody added a shared location and did not classify
    # it, and it is being treated as ordered because that is the safe default, not
    # because anyone checked. Reporting them alike would hide the second behind the
    # first, and the second is the one with a fix.
    declared = [key for key in blocking if key in ORDERED_KEYS]
    unclassified = [key for key in blocking if key not in ORDERED_KEYS]
    parts: list[str] = []
    if declared:
        parts.append(
            "these keys are ordered and both sides wrote them: " + ", ".join(declared)
        )
    if unclassified:
        parts.append(
            "these keys are in neither COMMUTATIVE_KEYS nor ORDERED_KEYS, so they are "
            "treated as ordered until someone classifies them: " + ", ".join(unclassified)
        )
    return "; ".join(parts)


@dataclass(frozen=True)
class RevertReport:
    stages: list[str] = field(default_factory=list)
    applied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.applied)

    def render(self) -> str:
        if not self.stages:
            return "No accumulated effect needed withdrawing."
        lines = [f"Withdrew {len(self.applied)} effect(s) from {', '.join(self.stages)}."]
        lines.extend(f"- {note}" for note in self.applied)
        if self.skipped:
            lines.append("Could not withdraw:")
            lines.extend(f"- {note}" for note in self.skipped)
        return "\n".join(lines)


def _apply_records(paths: RunPaths, records: Sequence[EffectRecord]) -> tuple[list[str], list[str]]:
    applied: list[str] = []
    skipped: list[str] = []
    for record in reversed(records):
        handler = INVERSE_HANDLERS.get(record.inverse.kind)
        if handler is None:
            skipped.append(f"{record.rel_path}: no handler for inverse {record.inverse.kind!r}")
            continue
        try:
            applied.append(handler(paths, record.inverse.payload))
        except OSError as error:
            skipped.append(f"{record.rel_path}: {error}")
    return applied, skipped


def _retire_accumulator(paths: RunPaths, stage: StageSpec | str, records: Sequence[EffectRecord]) -> None:
    """Move a spent accumulator aside rather than deleting it.

    The run's record of how it reached its answer includes what it took back. A
    rollback that leaves no trace of what it withdrew is a claim about a rollback.
    """

    source = accumulator_path(paths, stage)
    if not source.exists():
        return
    archive = reverted_path(paths, stage)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with archive.open("a", encoding="utf-8") as handle:
        for record in records:
            payload = record.to_dict()
            payload["reverted_at"] = _now()
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
    source.unlink()


def revert_from(paths: RunPaths, stage: StageSpec, stages: Iterable[StageSpec]) -> RevertReport:
    """Withdraw every stage at or after ``stage``, latest first, each in reverse.

    The order needs no justification: reverting in the reverse of the order applied hands
    each inverse the state its own application produced, whatever the effects were. This
    is the rollback a backward edge takes.
    """

    ordered = sorted(
        (item for item in stages if item.number >= stage.number),
        key=lambda item: item.number,
        reverse=True,
    )
    touched: list[str] = []
    applied: list[str] = []
    skipped: list[str] = []
    for item in ordered:
        records = load_accumulator(paths, item)
        if not records:
            continue
        touched.append(item.slug)
        stage_applied, stage_skipped = _apply_records(paths, records)
        applied.extend(stage_applied)
        skipped.extend(stage_skipped)
        _retire_accumulator(paths, item, records)
    return RevertReport(stages=touched, applied=applied, skipped=skipped)


def apply_withdrawal(paths: RunPaths, plan: Sequence[Withdrawal]) -> RevertReport:
    """Move the files a withdrawal plan names, for writes the primitives never saw.

    The stage's own agent writes most of what a run produces, and those writes never pass
    through :func:`record_effect`. :mod:`src.provenance` observes them instead, keeping a
    version chain per file, so a withdrawal is still exact wherever the bytes were held:
    a file created inside the withdrawn range is deleted, and one that existed before it
    is rewound to what the last stage outside the range left.

    A version whose bytes were never held — over
    :data:`src.provenance.RESTORABLE_BYTE_LIMIT` — cannot be rewound to. Deleting is the
    fallback and it is said out loud, because leaving the current bytes would present a
    withdrawn stage's output as the restored state, which is the failure this whole path
    exists to prevent.
    """

    applied: list[str] = []
    skipped: list[str] = []
    dropped: list[str] = []

    for item in plan:
        target = paths.workspace_root / item.rel_path
        if item.deletes:
            if not target.exists():
                dropped.append(item.rel_path)
                continue
            try:
                target.unlink()
                applied.append(f"deleted {item.rel_path}")
                dropped.append(item.rel_path)
            except OSError as error:
                skipped.append(f"{item.rel_path}: {error}")
            continue

        version = item.restore_to
        assert version is not None
        blob = load_blob(paths, version.blob_hash) if version.restorable else None
        if blob is None:
            if not target.exists():
                continue
            try:
                target.unlink()
                applied.append(
                    f"deleted {item.rel_path} (no stored bytes for {version.version_uid})"
                )
                dropped.append(item.rel_path)
            except OSError as error:
                skipped.append(f"{item.rel_path}: {error}")
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
            applied.append(f"rewound {item.rel_path} to {version.version_uid}")
        except OSError as error:
            skipped.append(f"{item.rel_path}: {error}")

    if dropped:
        provenance.drop_entries(paths, dropped)

    return RevertReport(
        stages=["observed"] if applied or skipped else [],
        applied=applied,
        skipped=skipped,
    )


@dataclass(frozen=True)
class RecoveryReport:
    """What a rollback did to the workspace, as opposed to what it did to the manifest."""

    stage: str
    accumulated: RevertReport = field(default_factory=RevertReport)
    observed: RevertReport = field(default_factory=RevertReport)
    emissions_discarded: int = 0

    @property
    def touched(self) -> bool:
        return bool(
            self.accumulated.applied
            or self.accumulated.skipped
            or self.observed.applied
            or self.observed.skipped
            or self.emissions_discarded
        )

    def render(self) -> str:
        if not self.touched:
            return f"Rollback to {self.stage} withdrew nothing: the workspace held no attributed change."
        lines = [f"Rollback to {self.stage} withdrew the workspace, not only the manifest."]
        if self.accumulated.applied or self.accumulated.skipped:
            lines.append(self.accumulated.render())
        if self.observed.applied or self.observed.skipped:
            lines.append(self.observed.render())
        if self.emissions_discarded:
            lines.append(
                f"Discarded {self.emissions_discarded} withheld emission intent(s); "
                "none had been performed."
            )
        return "\n".join(lines)


def recover_to_stage(paths: RunPaths, stage: StageSpec, reason: str = "") -> RecoveryReport:
    """Put the workspace back to what it was before ``stage`` ran, and say what moved.

    The seam a backward edge goes through. Four things happen and the order is load
    bearing.

    The plan is read off the ledger first, while nothing has moved, because it is the
    only reading of "what the workspace looked like before this range" that is still
    available once the range starts being taken back.

    Accumulated inverses run next, latest stage first and each stage in reverse. These are
    the writes that came through a primitive, so their withdrawal is exact and needs no
    stored bytes.

    The plan is applied to whatever is left — the writes the agent made directly, which no
    inverse describes.

    The ledger is committed last, so a crash between the file moves and the ledger write
    leaves rows claiming versions that are gone, which the next :func:`observe` corrects,
    rather than a ledger claiming a clean state over a workspace that still holds the
    withdrawn one.

    Withheld emissions of the withdrawn range are dropped. They were never performed, so
    there is nothing to compensate; the record of having declined to perform them stays.
    """

    from . import emissions

    note = reason.strip() or f"Rolled back to {stage.stage_title}"
    plan = provenance.plan_withdrawal(paths, stage)
    accumulated = revert_from(paths, stage, STAGES)
    observed = apply_withdrawal(paths, plan)
    provenance.invalidate_from(paths, stage, note)
    discarded = emissions.discard_from(paths, stage, note)

    return RecoveryReport(
        stage=stage.stage_title,
        accumulated=accumulated,
        observed=observed,
        emissions_discarded=len(discarded),
    )


# ----------------------------------------------------------------------------
# Primitives
# ----------------------------------------------------------------------------


def set_artifact(
    paths: RunPaths,
    stage: StageSpec,
    rel_path: str,
    content: str | bytes,
    key: str | None = None,
) -> EffectRecord:
    """Write a workspace file and accumulate the inverse that takes it back.

    Creating a file inverts to deleting it. Overwriting one inverts to restoring the
    bytes that were there, which are put in the blob store before the write — after it,
    they are gone and the inverse would be a guess.
    """

    target = _resolve(paths, rel_path)
    payload = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    existed = target.exists()
    inverse: Inverse
    if existed:
        inverse = Inverse(
            "restore_blob",
            {"rel_path": rel_path, "blob_hash": store_blob(paths, target.read_bytes())},
        )
    else:
        inverse = Inverse("delete_path", {"rel_path": rel_path})

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)

    return record_effect(
        paths,
        EffectRecord(
            stage=stage.slug,
            key=key or key_for_workspace_path(paths, rel_path),
            action="overwrite" if existed else "create",
            rel_path=rel_path,
            inverse=inverse,
            at=_now(),
        ),
    )
