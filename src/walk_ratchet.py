"""A backward move that made the run worse is itself taken back.

The graph exists so a late finding can send the run back. Nothing checked whether going
back helped. A run could leave Stage 06 for Stage 03, rebuild the design, walk forward
again and arrive at a Stage 06 that scored *lower* than the one it abandoned — and that
outcome was recorded, promoted and built on exactly like an improvement, because "later"
was the only ordering the walk had.

:mod:`src.evolution` already solved this one level down. Within a stage, a polish round
that scores worse is reverted and the champion is restored. The walk had no equivalent: the
ratchet stopped at the stage boundary, and the moves the graph was added for were the ones
outside it.

**What an excursion is.** The interval between leaving a stage by a backward edge and
getting back to it. It opens when the walk leaves stage *S* for something earlier, and
closes the next time the walk leaves a stage numbered *S* or above — the point at which it
has recovered the ground it gave up and the two states are comparable.

**What it is compared on.** The score of *the same stage*, before and after. The excursion
was taken to improve S's situation, so S's own rubric total is the measure, and both numbers
are already recorded per visit in ``stage_graph.json``. No new scoring runs.

**Why there is no noise band.** :mod:`src.rubric` reads the run off disk and never calls a
backend, so the same workspace scores the same number twice. A judged score would need a
margin wider than its sampling noise before a comparison of two draws meant anything; a
mechanical one does not, and :data:`RATCHET_MARGIN` is 0.0 for that reason rather than by
omission. It exists as a named constant so that swapping in a judged score is a change to a
value with an argument attached rather than a silent reintroduction of the problem.

**Where the run goes back to.** A snapshot of the provenance ledger's version pointers,
taken when the excursion opened. Restoring it is the same applier a stage-range withdrawal
uses, with the target version chosen by recorded identifier instead of by stage number. The
blobs are already in the content-addressed store, so the snapshot costs a dictionary rather
than a copy of the workspace.

**One rewind per stage.** A rewind puts the run back exactly where it was before the
backward move, which is also the state that made the backward move look attractive. The
per-stage cap is what stops the ratchet from becoming the loop it exists to detect. A second
excursion from the same stage that also comes back worse is recorded and allowed to stand:
the run has been told once, in the withdrawal ledger and in the prompt, and a mechanism that
keeps overruling the same decision has stopped being a ratchet and become a wall.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .utils import RunPaths, StageSpec

#: How much worse an excursion has to end before it is taken back. Zero because the rubric
#: is mechanical: it reads the run off disk, never calls a backend, and scores the same
#: workspace identically twice, so any drop is a real drop. A judged score would need a
#: margin wider than its own sampling dispersion before two draws could be compared at all.
RATCHET_MARGIN = 0.0

#: How many times the ratchet may overrule excursions from one stage. See the module note:
#: a rewind restores the state that made the backward move look attractive in the first
#: place, so an uncapped ratchet is a loop.
MAX_REWINDS_PER_STAGE = 1


@dataclass(frozen=True)
class Excursion:
    """A backward move in flight: where it left from, and what the run looked like then."""

    from_stage: str
    to_stage: str
    opened_at: str
    reason: str
    #: The departing stage's rubric total at the moment it was left. ``None`` when the
    #: stage had never been scored, which makes the excursion unjudgeable rather than
    #: judged favourably.
    baseline: float | None
    #: Version pointer per workspace path, from :func:`src.provenance.snapshot`.
    marks: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_stage": self.from_stage,
            "to_stage": self.to_stage,
            "opened_at": self.opened_at,
            "reason": self.reason,
            "baseline": self.baseline,
            "marks": dict(self.marks),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Excursion":
        baseline = payload.get("baseline")
        return cls(
            from_stage=str(payload.get("from_stage") or ""),
            to_stage=str(payload.get("to_stage") or ""),
            opened_at=str(payload.get("opened_at") or ""),
            reason=str(payload.get("reason") or ""),
            baseline=float(baseline) if isinstance(baseline, (int, float)) else None,
            marks={str(k): str(v) for k, v in dict(payload.get("marks") or {}).items()},
        )


@dataclass(frozen=True)
class Outcome:
    """What the ratchet decided when an excursion closed."""

    from_stage: str
    to_stage: str
    baseline: float | None
    closed_at_score: float | None
    #: ``improved`` | ``held`` | ``rewound`` | ``worse_but_capped`` | ``unjudgeable``
    verdict: str
    detail: str = ""

    def render(self) -> str:
        span = f"{self.from_stage} -> {self.to_stage} -> {self.from_stage}"
        scores = f"{_fmt(self.baseline)} -> {_fmt(self.closed_at_score)}"
        body = f"excursion {span}: {scores} ({self.verdict})"
        return f"{body}\n{self.detail}" if self.detail else body


def _fmt(value: float | None) -> str:
    return "unscored" if value is None else f"{value:.1f}"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def state_path(paths: RunPaths) -> Path:
    return paths.evolution_dir / "excursions.json"


def _load(paths: RunPaths) -> dict[str, Any]:
    path = state_path(paths)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save(paths: RunPaths, payload: Mapping[str, Any]) -> None:
    path = state_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def open_excursion(paths: RunPaths) -> Excursion | None:
    raw = _load(paths).get("open")
    return Excursion.from_dict(raw) if isinstance(raw, dict) else None


def rewinds_so_far(paths: RunPaths, stage_slug: str) -> int:
    counts = _load(paths).get("rewinds")
    if not isinstance(counts, dict):
        return 0
    return int(counts.get(stage_slug, 0) or 0)


def outcomes(paths: RunPaths) -> list[Outcome]:
    raw = _load(paths).get("outcomes")
    if not isinstance(raw, list):
        return []
    return [
        Outcome(
            from_stage=str(item.get("from_stage") or ""),
            to_stage=str(item.get("to_stage") or ""),
            baseline=item.get("baseline") if isinstance(item.get("baseline"), (int, float)) else None,
            closed_at_score=(
                item.get("closed_at_score")
                if isinstance(item.get("closed_at_score"), (int, float))
                else None
            ),
            verdict=str(item.get("verdict") or ""),
            detail=str(item.get("detail") or ""),
        )
        for item in raw
        if isinstance(item, dict)
    ]


def last_score_for(state: Any, stage_slug: str) -> float | None:
    """The most recent rubric total recorded for a stage, from the walk's own record.

    Read backwards off ``state.path`` rather than recomputed. The rollback paths call
    ``graph_leave`` with ``score_total=None`` — the move was already made by the time the
    walk saw it — so the departing score is not on the visit that opens an excursion, and
    the last one that *was* measured is the honest baseline.
    """

    for visit in reversed(getattr(state, "path", []) or []):
        if visit.stage == stage_slug and visit.score_total is not None:
            return float(visit.score_total)
    return None


def begin(
    paths: RunPaths,
    state: Any,
    from_stage: StageSpec,
    to_stage: StageSpec,
    reason: str = "",
) -> Excursion | None:
    """Open an excursion, unless one is already open.

    A backward move taken while an excursion is in flight extends the outer one rather than
    nesting inside it. The outer baseline is the state before the run started going
    backwards at all, which is the comparison worth keeping: judging an inner excursion
    against a state that is itself under review would let two bad moves ratify each other.
    """

    from .provenance import snapshot

    payload = _load(paths)
    if isinstance(payload.get("open"), dict):
        return None

    excursion = Excursion(
        from_stage=from_stage.slug,
        to_stage=to_stage.slug,
        opened_at=_now(),
        reason=reason.strip(),
        baseline=last_score_for(state, from_stage.slug),
        marks=snapshot(paths),
    )
    payload["open"] = excursion.to_dict()
    _save(paths, payload)
    return excursion


def settle(
    paths: RunPaths,
    state: Any,
    stage: StageSpec,
    score: float | None = None,
) -> Outcome | None:
    """Close the open excursion if the walk has recovered its ground, and judge it.

    Called where the walk leaves a stage. Returns ``None`` while no excursion is open or the
    run has not yet climbed back to the stage it left, so the caller can invoke it at every
    departure without deciding when an excursion ends.

    ``score`` may be omitted, and is on the paths where the move was already made by the
    time the walk saw it — a rollback, a ``/back``, a round decision — which call
    ``graph_leave`` with no score at all. The closing figure then comes from the same place
    the baseline does, the last total the walk recorded for this stage, so both ends of the
    comparison are read the same way.
    """

    from .effects import apply_withdrawal
    from .provenance import plan_restore, trim_to_snapshot
    from .utils import STAGES

    excursion = open_excursion(paths)
    if excursion is None:
        return None

    by_slug = {item.slug: item for item in STAGES}
    origin = by_slug.get(excursion.from_stage)
    if origin is None or stage.number < origin.number:
        return None

    payload = _load(paths)
    payload.pop("open", None)
    if score is None:
        score = last_score_for(state, stage.slug)

    if excursion.baseline is None or score is None:
        outcome = Outcome(
            excursion.from_stage,
            excursion.to_stage,
            excursion.baseline,
            score,
            "unjudgeable",
            "one end of the comparison was never scored, so the excursion is recorded "
            "rather than judged",
        )
    elif score >= excursion.baseline - RATCHET_MARGIN:
        verdict = "improved" if score > excursion.baseline else "held"
        outcome = Outcome(
            excursion.from_stage, excursion.to_stage, excursion.baseline, score, verdict
        )
    elif rewinds_so_far(paths, excursion.from_stage) >= MAX_REWINDS_PER_STAGE:
        outcome = Outcome(
            excursion.from_stage,
            excursion.to_stage,
            excursion.baseline,
            score,
            "worse_but_capped",
            f"{excursion.from_stage} has already been rewound "
            f"{MAX_REWINDS_PER_STAGE} time(s); a ratchet that keeps overruling the same "
            "decision is a wall, so this one is recorded and left standing",
        )
    else:
        plan = plan_restore(paths, excursion.marks)
        report = apply_withdrawal(paths, plan)
        trim_to_snapshot(paths, excursion.marks)
        counts = dict(payload.get("rewinds") or {})
        counts[excursion.from_stage] = counts.get(excursion.from_stage, 0) + 1
        payload["rewinds"] = counts
        outcome = Outcome(
            excursion.from_stage,
            excursion.to_stage,
            excursion.baseline,
            score,
            "rewound",
            report.render(),
        )

    recorded = list(payload.get("outcomes") or [])
    recorded.append(
        {
            "from_stage": outcome.from_stage,
            "to_stage": outcome.to_stage,
            "baseline": outcome.baseline,
            "closed_at_score": outcome.closed_at_score,
            "verdict": outcome.verdict,
            "detail": outcome.detail,
            "at": _now(),
        }
    )
    payload["outcomes"] = recorded
    _save(paths, payload)
    return outcome


def summarise(paths: RunPaths) -> str:
    """What every backward move in this run bought, in one block.

    The number a graph-versus-pipeline comparison actually needs: not how many backward
    edges were taken, but how many of them ended better than they started.
    """

    settled = outcomes(paths)
    if not settled:
        return "No backward move has closed yet."
    counts: dict[str, int] = {}
    for outcome in settled:
        counts[outcome.verdict] = counts.get(outcome.verdict, 0) + 1
    parts = ", ".join(f"{verdict} x{count}" for verdict, count in sorted(counts.items()))
    lines = [f"{len(settled)} backward move(s) closed: {parts}"]
    lines.extend(f"- {outcome.render()}" for outcome in settled)
    return "\n".join(lines)
