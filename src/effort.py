"""Spend effort where the research needs it, not evenly.

:mod:`src.deliberation` gave a stage a way to stop and think hard. This is the other half, and
without it the first half is only a sentence in a prompt: **nothing in AutoR ever ran cheaper
on routine work.** Every stage carries the full prompt assembly, the full gate, and every panel
that happens to be switched on — whether it is choosing an identification strategy or writing a
CSV loader.

That uniformity is the same mistake the multi-agent feedback literature made and measured.
Applying the expensive configuration everywhere is how the expensive configuration loses on
average: the cost lands on every step and the benefit lands on a few.

So a stage runs in one of two tiers:

``routine``
    The decisions are already made and this is execution. Lean prompt, single reviewer at the
    gate, no crux escalation offered, no ideation panel.
``deliberative``
    Something genuinely undecided is at stake. Everything configured is available.

**Who chooses.** The stage that just finished declares what the next one needs, because it is
the thing that just learned whether the hard part is over. A default per stage applies when
nothing says otherwise.

**What stops a wrong guess being costly.** A routine stage that fails its gate twice is
*promoted* to deliberative and re-run with the full apparatus. Cheap is a bet, and this is what
happens when the bet loses — the run recovers by itself rather than thrashing at low power.

Both directions of waste are recorded. A routine stage that had to be promoted was
under-resourced; a deliberative stage that passed on its first attempt with nothing contested
was over-resourced. A tiering scheme that cannot report either is not measuring anything.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .utils import RunPaths, StageSpec, append_log_entry, read_text, write_text


ROUTINE = "routine"
DELIBERATIVE = "deliberative"
TIERS = (ROUTINE, DELIBERATIVE)

#: Failures at which a routine stage is promoted. Two rather than one: a single failed gate is
#: ordinary and often a formatting problem, while twice means the work itself is harder than
#: the previous stage thought.
PROMOTE_AFTER_FAILURES = 2

LEDGER_FILENAME = "effort.json"


@dataclass
class Concentration:
    """What each tier is actually given, once the tiers are known.

    Tiering by itself only *labels* the steps that matter. This is the part that acts on the
    label. The polish loop is the run's most expensive knob — :mod:`src.evolution` says so
    itself, "each one is a full stage execution, so this is where the money goes" — and it was
    being spread across all eight stages regardless. Cost on every step, benefit on a few.

    Concentration is a reallocation rather than an increase: the same rounds, aimed only at the
    stages that still have something to decide, and the cheaper model handed to the ones that
    do not.
    """

    #: Polish rounds are withheld from routine stages entirely.
    polish_routine: bool = False
    #: Rounds actually spent, per tier, so the reallocation can be checked rather than assumed.
    rounds_spent: dict[str, int] = field(default_factory=lambda: {ROUTINE: 0, DELIBERATIVE: 0})
    #: Stages that ran on the cheaper model.
    cheap_model_stages: list[str] = field(default_factory=list)
    routine_model: str = ""

    def note_round(self, tier: str) -> None:
        self.rounds_spent[tier] = self.rounds_spent.get(tier, 0) + 1

    def note_cheap_model(self, stage_slug: str) -> None:
        if stage_slug not in self.cheap_model_stages:
            self.cheap_model_stages.append(stage_slug)

    def to_dict(self) -> dict[str, Any]:
        spent = dict(self.rounds_spent)
        total = sum(spent.values())
        return {
            "polish_withheld_from_routine": not self.polish_routine,
            "polish_rounds_spent": spent,
            "share_on_deliberative": (
                round(spent.get(DELIBERATIVE, 0) / total, 2) if total else None
            ),
            "routine_model": self.routine_model,
            "stages_on_the_cheaper_model": list(self.cheap_model_stages),
            "verdict": self._verdict(spent, total),
        }

    @staticmethod
    def _verdict(spent: dict[str, int], total: int) -> str:
        if total == 0:
            return "No polish rounds were spent, so nothing was concentrated."
        leaked = spent.get(ROUTINE, 0)
        if leaked:
            return (
                f"{total} polish round(s) spent, but {leaked} of them went to routine stages. "
                "The expensive knob is still landing where the benefit does not."
            )
        return (
            f"All {total} polish round(s) went to deliberative stages; routine stages spent "
            "none."
        )

#: Where each stage starts when nothing has said otherwise.
#:
#: These are starting guesses about the *shape* of the work, not claims about any particular
#: research question — which is exactly why a stage can override the next one's tier. Framing,
#: hypotheses, design, and interpretation are where a wrong call is expensive and hard to
#: reverse. Implementation and execution are where the decisions have already been made and
#: the work is to carry them out correctly.
DEFAULT_TIERS: dict[str, str] = {
    "01_literature_survey": DELIBERATIVE,
    "02_hypothesis_generation": DELIBERATIVE,
    "03_study_design": DELIBERATIVE,
    "04_implementation": ROUTINE,
    "05_experimentation": ROUTINE,
    "06_analysis": DELIBERATIVE,
    "07_writing": DELIBERATIVE,
    "08_dissemination": ROUTINE,
}

_DECLARATION = re.compile(
    r"next\s+stage\s+effort\s*:\s*(routine|deliberative)\b(?:\s*[-—:]\s*(.*))?",
    flags=re.IGNORECASE,
)


@dataclass
class TierDecision:
    stage_slug: str
    tier: str
    chosen_by: str = "default"
    reason: str = ""
    promoted_from: str = ""
    failures: int = 0
    attempts: int = 0
    contested: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_tier(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    lowered = value.strip().lower()
    return lowered if lowered in TIERS else None


def parse_declaration(stage_markdown: str) -> tuple[str, str] | None:
    """Read a ``Next stage effort: routine — the design is settled`` line from a summary.

    A line rather than a JSON block: this is written into a stage summary a human reads, and
    the required output format is already crowded. Anything the stage says after the tier is
    kept as the reason, because a tier with no reason is a guess nobody can audit later.
    """
    match = _DECLARATION.search(stage_markdown or "")
    if match is None:
        return None
    tier = normalize_tier(match.group(1))
    if tier is None:
        return None
    return tier, (match.group(2) or "").strip()


@dataclass
class EffortPlan:
    """Which tier each stage runs in, and why."""

    decisions: dict[str, TierDecision] = field(default_factory=dict)
    enabled: bool = True

    def tier_for(self, stage: StageSpec) -> str:
        if not self.enabled:
            return DELIBERATIVE
        decision = self.decisions.get(stage.slug)
        return decision.tier if decision else DEFAULT_TIERS.get(stage.slug, DELIBERATIVE)

    def decision_for(self, stage: StageSpec) -> TierDecision:
        if stage.slug not in self.decisions:
            self.decisions[stage.slug] = TierDecision(
                stage_slug=stage.slug,
                tier=DEFAULT_TIERS.get(stage.slug, DELIBERATIVE),
                chosen_by="default",
                reason="No prior stage declared an effort tier for this one.",
            )
        return self.decisions[stage.slug]

    def is_routine(self, stage: StageSpec) -> bool:
        # No `enabled` check here on purpose: `tier_for` already answers deliberative when the
        # plan is off, and guarding the same thing twice means neither guard is the one being
        # tested.
        return self.tier_for(stage) == ROUTINE

    def declare(self, stage_slug: str, tier: str, reason: str, *, chosen_by: str = "prior stage") -> None:
        """Record what a stage said the next one needs."""
        existing = self.decisions.get(stage_slug)
        if existing is not None and existing.chosen_by == "promotion":
            # A promotion is evidence; a declaration is a guess. Evidence wins.
            return
        self.decisions[stage_slug] = TierDecision(
            stage_slug=stage_slug, tier=tier, chosen_by=chosen_by, reason=reason
        )

    def note_failure(self, stage: StageSpec) -> bool:
        """Count a failed gate. Returns True when this promotes the stage."""
        decision = self.decision_for(stage)
        decision.failures += 1
        if (
            self.enabled
            and decision.tier == ROUTINE
            and decision.failures >= PROMOTE_AFTER_FAILURES
        ):
            decision.promoted_from = ROUTINE
            decision.tier = DELIBERATIVE
            decision.chosen_by = "promotion"
            decision.reason = (
                f"Ran as routine and failed its gate {decision.failures} times; the work is "
                "harder than the previous stage expected."
            )
            return True
        return False

    def note_outcome(self, stage: StageSpec, *, attempts: int, contested: bool | None) -> None:
        decision = self.decision_for(stage)
        decision.attempts = attempts
        decision.contested = contested


# ---------------------------------------------------------------------------
# Prompt block
# ---------------------------------------------------------------------------


def tier_notice(stage: StageSpec, tier: str, next_stage: StageSpec | None) -> str:
    """Tell a stage how much ceremony it is running with, and ask it to set the next one."""
    if tier == ROUTINE:
        head = (
            "# Effort Tier: routine\n\n"
            "The decisions this stage depends on are already made. This is execution: carry "
            "them out correctly and completely, and do not re-open settled questions. You are "
            "running with a lighter review than a deliberative stage, so the bar is that the "
            "work is *right*, not that it is *argued for*.\n\n"
            "If you discover that something genuinely is not settled, say so plainly in "
            "`Decision Ledger` under Open Questions rather than quietly deciding it yourself."
        )
    else:
        head = (
            "# Effort Tier: deliberative\n\n"
            "Something genuinely undecided is at stake here. Take the time. Consider more than "
            "one way the question could be answered, say why you chose the one you chose, and "
            "record what would have changed your mind. Work that is complete and unargued is "
            "not what this stage is for. What the task names as its outputs is not one of the "
            "things this stage decides: if two readings of the task are live, carry both and "
            "let the stage that costs the design choose between them."
        )

    if next_stage is None:
        return head
    return (
        head
        + "\n\n## Set the next stage's effort\n\n"
        + f"End your `Decision Ledger` with one line saying what **{next_stage.stage_title}** "
        "needs:\n\n"
        + "```\nNext stage effort: routine — the design is settled; this is engineering.\n```\n\n"
        + "or\n\n"
        + "```\nNext stage effort: deliberative — the identification strategy is still open.\n```\n\n"
        + "Choose `routine` when the decisions that stage depends on are already made, and "
        "`deliberative` when it still has to decide something that would be expensive to get "
        "wrong. Guessing routine is not punished — a routine stage that fails twice is promoted "
        "automatically — but guessing it every time defeats the point."
    )


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


def record_plan(
    paths: RunPaths, plan: EffortPlan, concentration: "Concentration | None" = None
) -> dict[str, Any]:
    decisions = [decision.to_dict() for decision in plan.decisions.values()]
    payload: dict[str, Any] = {
        "enabled": plan.enabled,
        "stages": decisions,
        "summary": summarize(plan),
    }
    if concentration is not None:
        payload["concentration"] = concentration.to_dict()
    paths.reviews_dir.mkdir(parents=True, exist_ok=True)
    write_text(paths.reviews_dir / LEDGER_FILENAME, json.dumps(payload, indent=2, ensure_ascii=False))
    return payload


def summarize(plan: EffortPlan) -> dict[str, Any]:
    decisions = list(plan.decisions.values())
    routine = [d for d in decisions if d.tier == ROUTINE]
    deliberative = [d for d in decisions if d.tier == DELIBERATIVE]
    promoted = [d for d in decisions if d.promoted_from]
    # A deliberative stage that passed first time with nothing contested paid for an argument
    # nobody had.
    overspent = [
        d for d in deliberative
        if not d.promoted_from and d.attempts == 1 and d.contested is False
    ]
    declared = [d for d in decisions if d.chosen_by == "prior stage"]
    return {
        "stages_planned": len(decisions),
        "run_as_routine": len(routine),
        "run_as_deliberative": len(deliberative),
        "declared_by_a_prior_stage": len(declared),
        "promoted_after_failing": len(promoted),
        "deliberative_but_uncontested": len(overspent),
        "verdict": _verdict(len(decisions), len(routine), len(promoted), len(overspent)),
    }


def _verdict(planned: int, routine: int, promoted: int, overspent: int) -> str:
    """Both directions of waste, said plainly."""
    if planned == 0:
        return "No stages were tiered."
    if routine == 0:
        return (
            f"Every one of {planned} stage(s) ran deliberative. Nothing was treated as routine, "
            "so this run spent the expensive configuration everywhere — which is the thing "
            "tiering exists to avoid."
        )
    parts = [f"{routine} of {planned} stage(s) ran routine"]
    if promoted:
        parts.append(
            f"{promoted} had to be promoted after failing, so that call was wrong"
        )
    if overspent:
        parts.append(
            f"{overspent} ran deliberative but passed first time uncontested, so that effort "
            "bought nothing"
        )
    if not promoted and not overspent:
        parts.append("no stage was mis-tiered in either direction")
    return "; ".join(parts) + "."
