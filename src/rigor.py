"""One dial instead of four switches.

The optional machinery arrived one feature at a time, and each arrival made the same locally
correct argument: this is unproven, so do not impose it — default it off behind its own flag.
Four features later the aggregate is indefensible. A user had to know four switches to get any
of it, and AutoR then wrote them a scorecard whose entire purpose is to say *which of those
four you should have picked*. An instrument that says "you cannot know this up front" sitting
behind an interface that demands you know it up front is a contradiction, not a design.

So the switches collapse into `--rigor`, and the levels are ordered by the two things that
actually decide whether a feature belongs in a default: what it costs per run, and what
evidence there is that it helps.

============  =============================================================
Level         What it turns on
============  =============================================================
``fast``      Nothing optional. What AutoR did before any of this existed.
``standard``  Effort tiers. **This is the default.**
``thorough``  ...plus crux deliberation and the ideation panel.
``max``       ...plus the review panel.
============  =============================================================

The ordering is not a taste. Effort tiers is the only one of the four that makes a run
*cheaper* — it withholds polish rounds from stages whose decisions are already made — so
defaulting it on costs nothing and saves something. Crux deliberation is budgeted and only
fires when the agent says it is stuck. The ideation panel is one-off. The review panel is last
because it is both the most expensive (calls per *gate*, not per run) and the one the
multi-agent feedback literature has direct evidence against.

That last point is worth stating plainly: the feature built first here, and most elaborately,
is the one that belongs furthest from the default.

Individual flags still work and still win. They are escape hatches now rather than the
interface: `--rigor thorough --no-ideation-panel` is a sentence someone might actually write,
where four independent booleans were not.
"""

from __future__ import annotations

from typing import Any


FAST = "fast"
STANDARD = "standard"
THOROUGH = "thorough"
MAX = "max"

LEVELS = (FAST, STANDARD, THOROUGH, MAX)
DEFAULT_LEVEL = STANDARD

#: The switches a level owns. Anything absent from a level's set is off at that level.
#:
#: Keys are the argparse destinations, so a feature added here without a matching flag would
#: silently do nothing — :func:`feature_flags` is what keeps the two in step.
_LEVEL_FEATURES: dict[str, frozenset[str]] = {
    FAST: frozenset(),
    STANDARD: frozenset({"effort_tiers"}),
    THOROUGH: frozenset({"effort_tiers", "deliberation", "ideation_panel"}),
    MAX: frozenset({"effort_tiers", "deliberation", "ideation_panel", "review_panel"}),
}

#: Why each feature sits where it does, so `--rigor --help` can say more than a list.
FEATURE_NOTES: dict[str, str] = {
    "effort_tiers": "runs settled stages cheaply; the only switch that lowers a run's cost",
    "deliberation": "budgeted, and only fires when a stage says it is stuck",
    "ideation_panel": "one extra round of proposers at Stage 02",
    "review_panel": "calls per gate rather than per run, and the costliest of the four",
}


def feature_flags() -> tuple[str, ...]:
    """Every switch a level can control, in the order they were introduced."""
    return ("effort_tiers", "deliberation", "ideation_panel", "review_panel")


def normalize_level(value: Any) -> str:
    if not isinstance(value, str):
        return DEFAULT_LEVEL
    lowered = value.strip().lower()
    return lowered if lowered in LEVELS else DEFAULT_LEVEL


def features_for(level: str) -> frozenset[str]:
    return _LEVEL_FEATURES[normalize_level(level)]


def resolve(level: str, overrides: dict[str, bool | None]) -> dict[str, bool]:
    """Decide each switch: an explicit flag wins, otherwise the level decides.

    ``None`` means the user did not say, which is why the switches are declared with
    ``BooleanOptionalAction`` and no default — a plain ``store_true`` cannot tell "off because
    they asked" from "off because nobody mentioned it", and that difference is the whole
    reason an override can beat a level.
    """
    enabled = features_for(level)
    return {
        flag: (enabled and flag in enabled) if overrides.get(flag) is None else bool(overrides[flag])
        for flag in feature_flags()
    }


def describe(level: str, resolved: dict[str, bool]) -> str:
    """One line for the run log and the banner."""
    on = [flag for flag in feature_flags() if resolved.get(flag)]
    if not on:
        return f"rigor {normalize_level(level)}: no optional machinery."
    return f"rigor {normalize_level(level)}: " + ", ".join(flag.replace("_", " ") for flag in on) + "."


def help_text() -> str:
    """The `--rigor` help, built from the table so the two cannot drift."""
    parts = []
    for level in LEVELS:
        enabled = features_for(level)
        names = ", ".join(flag.replace("_", " ") for flag in feature_flags() if flag in enabled)
        parts.append(f"{level}: {names or 'nothing optional'}")
    return (
        "How much optional machinery to run. "
        + " | ".join(parts)
        + f". Defaults to {DEFAULT_LEVEL}. Individual switches override the level, so "
        "`--rigor thorough --no-ideation-panel` does what it says."
    )
