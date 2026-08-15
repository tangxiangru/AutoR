"""Actions that leave the run are held until the stage that asked for them is approved.

:mod:`src.effects` can withdraw a write because the run owns the file: it can change the
bytes exclusively and it can put the previous bytes back. Not everything a stage does is
like that. Opening a pull request, spending a model-API quota, writing a row into a shared
leaderboard, sending mail — each of those puts data somewhere other parties can already
read, and no inverse the run holds takes it back.

So the run's actions divide, and the division is per action rather than per medium. An
*acquisition* installs a record the run owns — a file it created, a handle it holds, a
directory it made — and is withdrawable. An *emission* pushes data across the boundary and
is not. Writing a draft into ``workspace/`` is an acquisition; pushing that draft to a
remote is an emission, and the second is not the first done harder.

There are two ways to be able to recover from an emission and this module implements the
first: **withhold it** until the state that produced it is settled. A stage that wants to
emit registers the intent here; the intent is released when the stage is approved and
discarded when the stage is rolled back. The alternative — emit now, compensate later — is
available to a caller that needs it and is not free: a compensating action restores the
world only up to an equivalence the application supplies, coarser than the one the rest of
this system reasons in, and nothing here can check it.

The kinds a run is known to cross by are ``pull_request``, ``quota``, ``leaderboard``,
``network``, ``message`` and ``outside_run_write``. The kind is a label rather than a
filter: an intent whose kind is not one of those is still held, because refusing an
unclassified intent would push its caller back to emitting directly, which is the
behaviour this module exists to replace.

**This module does not perform emissions.** It holds intents and says which are released.
The caller performs the released ones, which keeps the decision about what crosses the
boundary in one place and the knowledge of how to cross it with whoever owns the channel.
A withheld intent that is never released is not a failure to emit; it is the run declining
to act on a stage whose work it took back.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .utils import RunPaths, StageSpec

STATUS_WITHHELD = "withheld"
STATUS_RELEASED = "released"
STATUS_DISCARDED = "discarded"


@dataclass(frozen=True)
class Emission:
    emission_id: str
    stage: str
    kind: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = STATUS_WITHHELD
    created_at: str = ""
    settled_at: str = ""
    settled_reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "emission_id": self.emission_id,
            "stage": self.stage,
            "kind": self.kind,
            "summary": self.summary,
            "payload": dict(self.payload),
            "status": self.status,
            "created_at": self.created_at,
            "settled_at": self.settled_at,
            "settled_reason": self.settled_reason,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "Emission":
        raw = payload.get("payload", {})
        return cls(
            emission_id=str(payload.get("emission_id", "")).strip(),
            stage=str(payload.get("stage", "")).strip(),
            kind=str(payload.get("kind", "")).strip(),
            summary=str(payload.get("summary", "")).strip(),
            payload=dict(raw) if isinstance(raw, dict) else {},
            status=str(payload.get("status", STATUS_WITHHELD)).strip() or STATUS_WITHHELD,
            created_at=str(payload.get("created_at", "")).strip(),
            settled_at=str(payload.get("settled_at", "")).strip(),
            settled_reason=str(payload.get("settled_reason", "")).strip(),
        )

    @property
    def withheld(self) -> bool:
        return self.status == STATUS_WITHHELD


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def emissions_path(paths: RunPaths) -> Path:
    return paths.evolution_dir / "emissions.json"


def load_emissions(paths: RunPaths) -> list[Emission]:
    path = emissions_path(paths)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return []
    entries = payload.get("emissions") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return []
    return [Emission.from_dict(item) for item in entries if isinstance(item, dict)]


def save_emissions(paths: RunPaths, emissions: Sequence[Emission]) -> None:
    path = emissions_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"emissions": [item.to_dict() for item in emissions]}, indent=2, ensure_ascii=True
        )
        + "\n",
        encoding="utf-8",
    )


def withhold(
    paths: RunPaths,
    stage: StageSpec | str,
    kind: str,
    summary: str,
    payload: Mapping[str, Any] | None = None,
) -> Emission:
    """Register an intent to cross the boundary. Nothing crosses until it is released."""

    slug = stage.slug if isinstance(stage, StageSpec) else str(stage).strip()
    existing = load_emissions(paths)
    emission = Emission(
        emission_id=f"e{len(existing) + 1:04d}",
        stage=slug,
        kind=str(kind).strip(),
        summary=str(summary).strip(),
        payload=dict(payload or {}),
        status=STATUS_WITHHELD,
        created_at=_now(),
    )
    save_emissions(paths, [*existing, emission])
    return emission


def pending(paths: RunPaths, stage: StageSpec | str | None = None) -> list[Emission]:
    slug = None
    if stage is not None:
        slug = stage.slug if isinstance(stage, StageSpec) else str(stage).strip()
    return [
        emission
        for emission in load_emissions(paths)
        if emission.withheld and (slug is None or emission.stage == slug)
    ]


def _settle(
    paths: RunPaths,
    stage: StageSpec | str | None,
    status: str,
    reason: str,
    stage_numbers_at_or_after: int | None = None,
) -> list[Emission]:
    from .provenance import stage_number_for_slug

    slug = None
    if stage is not None:
        slug = stage.slug if isinstance(stage, StageSpec) else str(stage).strip()

    settled: list[Emission] = []
    updated: list[Emission] = []
    now = _now()
    for emission in load_emissions(paths):
        if not emission.withheld:
            updated.append(emission)
            continue
        matches = True
        if slug is not None:
            matches = emission.stage == slug
        if stage_numbers_at_or_after is not None:
            number = stage_number_for_slug(emission.stage)
            matches = number is not None and number >= stage_numbers_at_or_after
        if not matches:
            updated.append(emission)
            continue
        moved = replace(emission, status=status, settled_at=now, settled_reason=reason.strip())
        updated.append(moved)
        settled.append(moved)

    if settled:
        save_emissions(paths, updated)
    return settled


def release(paths: RunPaths, stage: StageSpec | str, reason: str = "stage approved") -> list[Emission]:
    """Mark a stage's withheld intents releasable and hand them back to the caller.

    The caller performs them. Marking happens first: an intent recorded as released and
    then not performed is a visible discrepancy, and one performed and then not recorded
    is an emission the run cannot account for.
    """

    return _settle(paths, stage, STATUS_RELEASED, reason)


def discard_from(
    paths: RunPaths, stage: StageSpec, reason: str = ""
) -> list[Emission]:
    """Drop every withheld intent registered by ``stage`` or any stage after it.

    What a rollback does with the emissions of the future it withdrew. They were never
    performed, so there is nothing to compensate; the record of having declined to
    perform them stays.
    """

    note = reason.strip() or f"withdrawn by rollback to {stage.stage_title}"
    return _settle(paths, None, STATUS_DISCARDED, note, stage_numbers_at_or_after=stage.number)
