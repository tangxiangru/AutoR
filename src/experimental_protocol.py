"""What makes a verdict trustworthy: a real baseline and enough runs to see noise.

Preregistration fixes *what* the run predicted. This fixes *what would count as
having shown it*. Both failures it guards against produce a clean-looking
`supported` verdict:

- **A baseline nobody tried to make strong.** Beating an untuned comparison is
  not evidence about the method, it is evidence about the effort split. The
  protocol makes each baseline declare a tuning budget in advance, and Stage 05
  records what each one actually got — so an asymmetry is on the record instead
  of buried in a number.
- **One run.** A single seed cannot distinguish an effect from variance. The
  gate refuses `supported` or `refuted` from one run unless the outcome says
  why one run is enough — some things genuinely are deterministic, and that is
  a claim worth making explicitly rather than by omission.

Before this, ``significan``, ``variance``, ``p-value`` and ``n_seeds`` appeared
zero times across AutoR's prompt corpus; ``baseline`` was a word in a list of
things Stage 03 might mention.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from .utils import RunPaths


#: How a spread was computed. Reporting `0.74 ± 0.03` without saying which of
#: these it is makes the interval unreadable, and every venue asks.
DISPERSION_TYPES = ("std", "stderr", "ci95", "iqr", "range", "none")

#: Below this, an effect and its noise are not separable by inspection. Not a
#: statistical threshold — a floor under "we ran it more than once".
MIN_SEEDS_FOR_A_VERDICT = 2


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


@dataclass(frozen=True)
class Baseline:
    name: str
    why_competent: str
    tuning_budget: str


@dataclass(frozen=True)
class ExperimentalProtocol:
    declared_at: str
    primary_metric: str
    planned_seeds: int
    baselines: list[Baseline]

    def to_dict(self) -> dict[str, object]:
        return {
            "declared_at": self.declared_at,
            "primary_metric": self.primary_metric,
            "planned_seeds": self.planned_seeds,
            "baselines": [
                {
                    "name": item.name,
                    "why_competent": item.why_competent,
                    "tuning_budget": item.tuning_budget,
                }
                for item in self.baselines
            ],
        }


def load_experimental_protocol(paths: RunPaths) -> ExperimentalProtocol | None:
    payload = _load_json(paths.experimental_protocol)
    if not isinstance(payload, dict):
        return None
    baselines = [
        Baseline(
            name=str(item.get("name") or "").strip(),
            why_competent=str(item.get("why_competent") or "").strip(),
            tuning_budget=str(item.get("tuning_budget") or "").strip(),
        )
        for item in payload.get("baselines", [])
        if isinstance(item, dict)
    ]
    try:
        planned_seeds = int(payload.get("planned_seeds") or 0)
    except (TypeError, ValueError):
        planned_seeds = 0
    return ExperimentalProtocol(
        declared_at=str(payload.get("declared_at") or ""),
        primary_metric=str(payload.get("primary_metric") or "").strip(),
        planned_seeds=planned_seeds,
        baselines=baselines,
    )


def validate_experimental_protocol(paths: RunPaths) -> list[str]:
    """Runs from Stage 05 on, alongside the preregistration check."""
    protocol = load_experimental_protocol(paths)
    if protocol is None:
        return [
            "requires an experimental protocol at workspace/notes/experimental_protocol.json "
            "declaring, before the experiments run, the primary metric, how many seeds are "
            "planned, and which baselines the method will be compared against with what "
            "tuning budget each."
        ]

    problems: list[str] = []
    if not protocol.primary_metric:
        problems.append(
            "experimental_protocol.json declares no primary_metric. Choosing the metric after "
            "seeing the results is the same defect as choosing the hypothesis after seeing them."
        )
    if protocol.planned_seeds < 1:
        problems.append("experimental_protocol.json must declare planned_seeds as a positive integer.")
    if not protocol.baselines:
        problems.append(
            "experimental_protocol.json declares no baselines. A result with nothing to compare "
            "against cannot be evidence that the method did anything."
        )
    for baseline in protocol.baselines:
        if not baseline.name:
            problems.append("experimental_protocol.json contains a baseline with no name.")
            continue
        if not baseline.why_competent:
            problems.append(
                f"experimental_protocol.json baseline `{baseline.name}` does not say why it is a "
                "competent comparison. Beating a baseline nobody argued for is not a result."
            )
        if not baseline.tuning_budget:
            problems.append(
                f"experimental_protocol.json baseline `{baseline.name}` declares no tuning budget. "
                "State it in advance, so an effort asymmetry between the method and its baseline "
                "is on the record rather than inside the number."
            )
    return problems


# ----------------------------------------------------------------------------
# Statistical backing for a verdict
# ----------------------------------------------------------------------------


def validate_outcome_statistics(paths: RunPaths) -> list[str]:
    """Runs from Stage 06 on, on top of the hypothesis-outcome checks.

    Only ``supported`` and ``refuted`` are held to this. ``inconclusive`` and
    ``not_tested`` are the honest verdicts when the evidence is thin, and
    forcing statistics onto them would push a run toward claiming more than it
    measured — the opposite of the point.
    """
    payload = _load_json(paths.hypothesis_outcomes)
    if not isinstance(payload, dict):
        return []

    problems: list[str] = []
    for entry in payload.get("outcomes", []):
        if not isinstance(entry, dict):
            continue
        identifier = str(entry.get("id") or "").strip() or "an outcome"
        verdict = str(entry.get("verdict") or "").strip()
        if verdict not in ("supported", "refuted"):
            continue

        statistics = entry.get("statistics")
        if not isinstance(statistics, dict):
            problems.append(
                f"hypothesis_outcomes.json outcome {identifier} is {verdict} with no `statistics` "
                "block. A verdict has to say how many runs it rests on and how the spread was "
                "measured."
            )
            continue

        raw_seeds = statistics.get("n_seeds")
        seeds = raw_seeds if isinstance(raw_seeds, int) and not isinstance(raw_seeds, bool) else None
        if seeds is None or seeds < 1:
            problems.append(
                f"hypothesis_outcomes.json outcome {identifier} must record `statistics.n_seeds` "
                "as a positive integer."
            )
        elif seeds < MIN_SEEDS_FOR_A_VERDICT and not str(
            statistics.get("single_run_justification") or ""
        ).strip():
            problems.append(
                f"hypothesis_outcomes.json outcome {identifier} is {verdict} on a single run. "
                "Either run it again, or record `statistics.single_run_justification` saying why "
                "one run settles it — a deterministic procedure is a legitimate reason, and it is "
                "a claim worth making out loud."
            )

        dispersion_type = str(statistics.get("dispersion_type") or "").strip()
        if dispersion_type not in DISPERSION_TYPES:
            problems.append(
                f"hypothesis_outcomes.json outcome {identifier} has dispersion_type "
                f"{dispersion_type!r}; expected one of {', '.join(DISPERSION_TYPES)}. "
                "An interval whose meaning is unstated cannot be read."
            )
        elif dispersion_type == "none" and (seeds or 0) >= MIN_SEEDS_FOR_A_VERDICT:
            problems.append(
                f"hypothesis_outcomes.json outcome {identifier} reports {seeds} runs but no "
                "dispersion. If it was run more than once, say how much it varied."
            )
    return problems


def format_protocol_for_prompt(protocol: ExperimentalProtocol) -> str:
    lines = [
        f"Declared at: {protocol.declared_at}",
        f"Primary metric: {protocol.primary_metric}",
        f"Planned seeds: {protocol.planned_seeds}",
        "",
        "This protocol was declared before the experiments ran. Report the primary metric",
        "whatever it shows; do not switch to a metric that came out better.",
        "",
        "Baselines:",
    ]
    for baseline in protocol.baselines:
        lines.append(f"- **{baseline.name}** — {baseline.why_competent}")
        lines.append(f"  - Tuning budget: {baseline.tuning_budget}")
    lines.append("")
    lines.append(
        "Give each baseline the tuning budget declared above. If you cannot, record the "
        "shortfall rather than reporting the comparison as though the budgets matched."
    )
    return "\n".join(lines)
