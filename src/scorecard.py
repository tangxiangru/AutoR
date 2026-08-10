"""One page saying which of the run's optional machinery earned its cost.

AutoR now has five optional features that each measure themselves honestly and write their
own ledger: the review panel, the ideation panel, anchored comments, crux deliberation, and
effort tiering. Each can say it did not help. **None of them are read together.**

That is a real gap rather than a cosmetic one. A user deciding which flags to run next time
would have to open five JSON files and do the arithmetic, so in practice nobody does, and
five honest self-assessments add up to no answer at all. The multi-agent feedback literature
made exactly this the point of its design: what settled the question was one comparison
*across* the arms, not each tool reporting on itself.

So this reads every ledger a run produced and answers the only question that matters when the
run is over — **which of these should I have turned on?**

Three verdicts, and the distinction between the last two is the whole point:

``keep``
    Enabled, measured, and the measurement says it changed an outcome.
``drop``
    Enabled, measured, and it changed nothing. Say so plainly.
``unproven``
    Enabled, but the measurement could not run — no baseline to compare against, or the run
    ended before the comparison was possible. **Not the same as "it worked."**

A feature that was never switched on is reported as unused rather than as a failure, and a
ledger that cannot be read is reported as unreadable rather than as an absence of effect.
Confusing "I could not measure this" with "this did nothing" would make the scorecard exactly
the kind of instrument the rest of this work exists to avoid.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from .utils import RunPaths, read_text, write_text


SCORECARD_JSON = "scorecard.json"
SCORECARD_MD = "scorecard.md"

KEEP = "keep"
DROP = "drop"
UNPROVEN = "unproven"
UNUSED = "unused"
UNREADABLE = "unreadable"


@dataclass
class FeatureReport:
    key: str
    name: str
    flag: str
    verdict: str
    detail: str = ""
    calls: int | None = None
    ledger: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Scorecard:
    features: list[FeatureReport] = field(default_factory=list)
    #: The dial the run was started with, so the card can be read against what was asked for.
    level: str = ""

    @property
    def optional_calls(self) -> int:
        return sum(report.calls or 0 for report in self.features)

    def by_verdict(self, verdict: str) -> list[FeatureReport]:
        return [report for report in self.features if report.verdict == verdict]

    def headline(self) -> str:
        used = [r for r in self.features if r.verdict in {KEEP, DROP, UNPROVEN}]
        if not used:
            return "No optional machinery was enabled on this run; nothing to weigh."
        keep, drop, unproven = (len(self.by_verdict(v)) for v in (KEEP, DROP, UNPROVEN))
        calls = self.optional_calls
        parts = [
            f"{len(used)} optional feature(s) ran, costing about {calls} extra model call(s)"
            if calls
            else f"{len(used)} optional feature(s) ran"
        ]
        if keep:
            parts.append(f"{keep} changed an outcome")
        if drop:
            parts.append(f"{drop} changed nothing and can be turned off")
        if unproven:
            parts.append(f"{unproven} could not be measured on this run")
        return "; ".join(parts) + "."

    def to_dict(self) -> dict[str, Any]:
        return {
            "rigor": self.level,
            "headline": self.headline(),
            "optional_model_calls": self.optional_calls,
            "keep": [r.key for r in self.by_verdict(KEEP)],
            "drop": [r.key for r in self.by_verdict(DROP)],
            "unproven": [r.key for r in self.by_verdict(UNPROVEN)],
            "features": [report.to_dict() for report in self.features],
        }


# ---------------------------------------------------------------------------
# Reading the ledgers
# ---------------------------------------------------------------------------


def _load(paths: RunPaths, filename: str) -> tuple[dict[str, Any] | None, bool]:
    """Return (payload, readable). A missing file is not the same as a broken one."""
    path = paths.reviews_dir / filename
    if not path.exists():
        path = paths.notes_dir / filename
    if not path.exists():
        return None, True
    try:
        payload = json.loads(read_text(path))
    except (OSError, json.JSONDecodeError):
        return None, False
    return (payload if isinstance(payload, dict) else None), isinstance(payload, dict)


def _report(
    *,
    key: str,
    name: str,
    flag: str,
    filename: str,
    paths: RunPaths,
    assess: Callable[[dict[str, Any]], tuple[str, str, int | None]],
) -> FeatureReport:
    payload, readable = _load(paths, filename)
    if not readable:
        return FeatureReport(
            key=key, name=name, flag=flag, verdict=UNREADABLE, ledger=filename,
            detail=f"{filename} exists but could not be parsed, so this feature was not weighed.",
        )
    if payload is None:
        return FeatureReport(
            key=key, name=name, flag=flag, verdict=UNUSED, ledger=filename,
            detail="Not enabled on this run.",
        )
    try:
        verdict, detail, calls = assess(payload)
    except Exception as exc:  # noqa: BLE001 - a bad ledger must not sink the scorecard
        return FeatureReport(
            key=key, name=name, flag=flag, verdict=UNREADABLE, ledger=filename,
            detail=f"{filename} could not be interpreted ({exc}).",
        )
    return FeatureReport(
        key=key, name=name, flag=flag, verdict=verdict, detail=detail, calls=calls, ledger=filename
    )


def _summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary")
    return summary if isinstance(summary, dict) else {}


def _assess_review_panel(payload: dict[str, Any]) -> tuple[str, str, int | None]:
    summary = _summary(payload)
    gates = int(summary.get("gates_reviewed") or 0)
    changed = int(summary.get("gates_where_the_panel_changed_the_decision") or 0)
    calls = int(summary.get("panel_calls") or 0)
    if gates == 0:
        return UNPROVEN, "The panel never reached a gate, so nothing was compared.", calls
    if changed:
        return KEEP, str(summary.get("verdict") or ""), calls
    return DROP, str(summary.get("verdict") or ""), calls


def _assess_ideation(payload: dict[str, Any]) -> tuple[str, str, int | None]:
    effect = payload.get("effect") if isinstance(payload.get("effect"), dict) else {}
    calls = int(effect.get("proposer_calls") or 0)
    verdict_text = str(effect.get("verdict") or "")
    if not effect.get("adoption_measured"):
        # Widening is not usefulness, and the pool says so itself until Stage 02 is approved.
        return UNPROVEN, verdict_text or "Stage 02 was never approved, so uptake is unknown.", calls
    if int(effect.get("adopted_from_other_proposers") or 0) > 0:
        return KEEP, verdict_text, calls
    return DROP, verdict_text, calls


def _assess_comments(payload: dict[str, Any]) -> tuple[str, str, int | None]:
    summary = _summary(payload)
    rounds = int(summary.get("rounds") or 0)
    addressed = int(summary.get("comments_addressed") or 0)
    if rounds == 0:
        return UNPROVEN, "No anchored review rounds ran.", None
    if addressed:
        return KEEP, str(summary.get("verdict") or ""), None
    return DROP, str(summary.get("verdict") or ""), None


def _assess_deliberation(payload: dict[str, Any]) -> tuple[str, str, int | None]:
    summary = _summary(payload)
    raised = int(summary.get("cruxes_raised") or 0)
    changed = int(summary.get("changed_the_agents_answer") or 0)
    confirmed = int(summary.get("confirmed_the_agents_answer") or 0)
    calls = int(summary.get("voice_calls") or 0)
    if raised == 0:
        return UNPROVEN, "No stage raised a crux, so the panel never ran.", calls
    if changed:
        return KEEP, str(summary.get("verdict") or ""), calls
    if confirmed:
        return DROP, str(summary.get("verdict") or ""), calls
    # Escalated, but no working answer was offered to compare against.
    return UNPROVEN, str(summary.get("verdict") or ""), calls


def _assess_effort(payload: dict[str, Any]) -> tuple[str, str, int | None]:
    if payload.get("enabled") is False:
        return UNUSED, "Not enabled on this run.", None
    summary = _summary(payload)
    planned = int(summary.get("stages_planned") or 0)
    routine = int(summary.get("run_as_routine") or 0)
    if planned == 0:
        return UNPROVEN, "No stages were tiered.", None
    detail = str(summary.get("verdict") or "")
    concentration = payload.get("concentration")
    if isinstance(concentration, dict) and concentration.get("verdict"):
        detail = f"{detail} {concentration['verdict']}".strip()
    if routine == 0:
        # Everything ran deliberative, which is the state tiering exists to move away from.
        return DROP, detail, None
    return KEEP, detail, None


#: Every optional feature that measures itself, and how to read its verdict.
FEATURES: tuple[dict[str, Any], ...] = (
    {"key": "review_panel", "name": "Review panel", "flag": "--review-panel",
     "filename": "panel_effect.json", "assess": _assess_review_panel},
    {"key": "ideation_panel", "name": "Ideation panel", "flag": "--ideation-panel",
     "filename": "idea_pool.json", "assess": _assess_ideation},
    {"key": "anchored_comments", "name": "Anchored review comments", "flag": "(automatic)",
     "filename": "comment_ledger.json", "assess": _assess_comments},
    {"key": "deliberation", "name": "Crux deliberation", "flag": "--deliberation",
     "filename": "deliberations.json", "assess": _assess_deliberation},
    {"key": "effort_tiers", "name": "Effort tiers", "flag": "--effort-tiers",
     "filename": "effort.json", "assess": _assess_effort},
)


def build_scorecard(paths: RunPaths, level: str = "") -> Scorecard:
    return Scorecard(
        features=[_report(paths=paths, **feature) for feature in FEATURES], level=level
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


_VERDICT_LABEL = {
    KEEP: "keep — changed an outcome",
    DROP: "drop — changed nothing",
    UNPROVEN: "unproven — could not be measured",
    UNUSED: "not enabled",
    UNREADABLE: "ledger unreadable",
}


def render_markdown(scorecard: Scorecard) -> str:
    lines = [
        "# What the optional machinery bought",
        "",
        (
            f"Run at `--rigor {scorecard.level}`."
            if scorecard.level
            else ""
        ),
        scorecard.headline(),
        "",
        "| Feature | Flag | Verdict | Extra calls |",
        "| --- | --- | --- | --- |",
    ]
    for report in scorecard.features:
        calls = str(report.calls) if report.calls else "—"
        lines.append(
            f"| {report.name} | `{report.flag}` | {_VERDICT_LABEL.get(report.verdict, report.verdict)} | {calls} |"
        )
    lines.append("")

    for verdict, heading in (
        (DROP, "Turn these off"),
        (KEEP, "These earned their cost"),
        (UNPROVEN, "These could not be judged"),
        (UNREADABLE, "These could not be read"),
    ):
        reports = scorecard.by_verdict(verdict)
        if not reports:
            continue
        lines.extend([f"## {heading}", ""])
        for report in reports:
            lines.append(f"- **{report.name}** (`{report.flag}`) — {report.detail or 'no detail recorded.'}")
        lines.append("")

    if scorecard.by_verdict(UNPROVEN):
        lines.extend([
            "> *Unproven is not a pass.* These features ran without a baseline to compare "
            "against, so the run cannot say whether they helped — only that it does not know.",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def write_scorecard(paths: RunPaths, level: str = "") -> Scorecard:
    """Build the scorecard and leave it where the run's other review artifacts live."""
    scorecard = build_scorecard(paths, level)
    paths.reviews_dir.mkdir(parents=True, exist_ok=True)
    write_text(paths.reviews_dir / SCORECARD_JSON, json.dumps(scorecard.to_dict(), indent=2, ensure_ascii=False))
    write_text(paths.reviews_dir / SCORECARD_MD, render_markdown(scorecard))
    return scorecard
