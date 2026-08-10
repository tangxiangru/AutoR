"""The unit of observation is a decision, not a run.

:func:`src.archive.edge_payoffs` compares runs that took an edge against runs that
"reached the same node and did not". That control arm pools four unrelated states:

* the guard was shut, so the edge was never on offer;
* ``--final-stage`` pruned it;
* the visit budget was spent;
* the run was on a topology where the edge does not exist at all.

Only the last of those was ever a *choice*, and only a choice is evidence about a
choice. The distinction is not academic here, because five of the seven guards test
the same disk predicates the rubric scores — ``_guard_results_exist`` and the
reproducibility check read the same expression. So a guard being shut is correlated
with the run being weak, and pooling "guard shut" into the control arm makes the
guard a selection mechanism on the outcome. The contrast then measures how much
worse a run is when its artifacts are missing, and reports it as the payoff of an
edge nobody could have taken.

The fix is the counterfactual the run already recorded and nothing read. Since
:class:`src.stage_graph.Visit` carries ``offered``, "was declined" is a fact on
disk:

    treatment — decisions at this node where this edge was chosen
    control   — decisions at this node where this edge was **offered and not** chosen
    excluded  — decisions where it was not on offer

Two further exclusions, both because the alternative counts something that was not
a decision. A ``bypassed`` visit is an operator's `/back` or a research round's own
jump: no guard was evaluated, nothing was on offer, nothing chose. And a visit from
before ``offered`` was recorded has an empty choice set, which is indistinguishable
from "nothing else was available" and must not be read as it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .archive import RunRecord
from .inference import TestResult, unpaired_permutation


@dataclass(frozen=True)
class Decision:
    """One routing choice, with the set it was chosen from."""

    run_id: str
    source: str
    chose: str
    offered: tuple[str, ...]
    #: The run's mean fitness. The outcome attributed to the decision.
    #:
    #: Attributing a whole run to one decision is crude and it is what a paired
    #: trial does better; this is the observational estimator, and its job is to be
    #: honest about a weak signal rather than to invent a strong one.
    fitness: float
    basis: str

    def offered_edge(self, edge: str) -> bool:
        source, target = edge.split("->", 1)
        return source == self.source and target in self.offered

    def took_edge(self, edge: str) -> bool:
        source, target = edge.split("->", 1)
        return source == self.source and self.chose == target


def decisions_from(records: Iterable[RunRecord]) -> list[Decision]:
    """Every real routing decision in these runs.

    A record with no recorded decisions contributes nothing rather than
    contributing an empty choice set, which the estimator would read as "no
    alternative existed".
    """
    collected: list[Decision] = []
    for record in records:
        if not record.usable:
            continue
        for entry in record.decisions:
            source = str(entry.get("source") or "")
            chose = str(entry.get("chose") or "")
            offered = tuple(str(item) for item in entry.get("offered", []) if str(item))
            if not source or not chose or not offered:
                continue
            if entry.get("bypassed"):
                continue
            collected.append(
                Decision(
                    run_id=record.run_id,
                    source=source,
                    chose=chose,
                    offered=offered,
                    fitness=record.mean_fitness,
                    basis=record.basis,
                )
            )
    return collected


@dataclass(frozen=True)
class OfferedPayoff:
    edge: str
    taken: tuple[float, ...]
    declined: tuple[float, ...]
    test: TestResult

    @property
    def taken_n(self) -> int:
        return len(self.taken)

    @property
    def declined_n(self) -> int:
        return len(self.declined)

    @property
    def taken_mean(self) -> float:
        return sum(self.taken) / len(self.taken) if self.taken else 0.0

    @property
    def declined_mean(self) -> float:
        return sum(self.declined) / len(self.declined) if self.declined else 0.0

    @property
    def delta(self) -> float:
        return self.taken_mean - self.declined_mean

    def to_dict(self) -> dict[str, object]:
        return {
            "edge": self.edge,
            "taken_runs": self.taken_n,
            "declined_runs": self.declined_n,
            "taken_mean": round(self.taken_mean, 4),
            "declined_mean": round(self.declined_mean, 4),
            "delta": round(self.delta, 4),
            "p_value": round(self.test.p_value, 4),
            "attainable_floor": round(self.test.floor, 4),
        }


def offered_payoffs(
    decisions: Sequence[Decision], *, within_basis: bool = True
) -> dict[str, OfferedPayoff]:
    """Per-edge contrast between taking a move and declining one that was offered.

    ``within_basis`` keeps the comparability rule the archive already applies
    between runs: two decisions are only contrasted when their runs measured the
    same stages on the same topology under the same rubric. Without it the
    composition of each arm can supply the delta, which is the bias that let the
    archive reward a run for stopping early.
    """
    edges: set[str] = set()
    for decision in decisions:
        for target in decision.offered:
            edges.add(f"{decision.source}->{target}")

    payoffs: dict[str, OfferedPayoff] = {}
    for edge in sorted(edges):
        offered_here = [item for item in decisions if item.offered_edge(edge)]
        bases = {item.basis for item in offered_here} if within_basis else {""}

        taken: list[float] = []
        declined: list[float] = []
        for basis in sorted(bases):
            arm = [
                item
                for item in offered_here
                if not within_basis or item.basis == basis
            ]
            took = [item.fitness for item in arm if item.took_edge(edge)]
            passed = [item.fitness for item in arm if not item.took_edge(edge)]
            if not took or not passed:
                # A basis with only one arm carries no contrast; counting its
                # decisions would inflate the sample size that decides
                # believability without contributing to the difference.
                continue
            taken.extend(took)
            declined.extend(passed)

        payoffs[edge] = OfferedPayoff(
            edge=edge,
            taken=tuple(taken),
            declined=tuple(declined),
            test=unpaired_permutation(taken, declined),
        )
    return payoffs


def format_offered_payoffs(
    payoffs: dict[str, OfferedPayoff], *, family: int | None = None
) -> str:
    if not payoffs:
        return (
            "No routing decision has been recorded with a choice set yet. Every edge "
            "observation so far predates `offered`, or came from a move that bypassed "
            "the router."
        )
    correction = family if family is not None else max(len(payoffs), 1)
    lines = [
        "| Edge | Took | Mean | Declined | Mean | Delta | Test |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for payoff in sorted(payoffs.values(), key=lambda item: abs(item.delta), reverse=True):
        lines.append(
            f"| `{payoff.edge}` | {payoff.taken_n} | {payoff.taken_mean:.3f} | "
            f"{payoff.declined_n} | {payoff.declined_mean:.3f} | {payoff.delta:+.3f} | "
            f"{payoff.test.describe(family=correction)} |"
        )
    lines.append("")
    lines.append(
        f"Corrected for a family of {correction} edge(s). A row that says it cannot reach the "
        "threshold is reporting its sample size, not its effect."
    )
    return "\n".join(lines)

def believable_evidence(
    payoffs: dict[str, OfferedPayoff], targets: Sequence[str], source: str
) -> list[OfferedPayoff]:
    """The contrasts for these moves that the arithmetic actually licenses.

    The filter is the whole design. An archive with three runs in it has an opinion
    about every edge and is entitled to none of them, and a routing prompt that
    printed those opinions would be an unrandomised, guard-selected statistic at
    n=3 arguing for a move at the moment a guard has just failed. Only rows that
    clear the family-corrected threshold *and* could have cleared it at this sample
    size are shown; everything else is not shown at all, rather than shown with a
    caveat nobody reads.
    """
    family = max(len(payoffs), 1)
    live = []
    for target in targets:
        payoff = payoffs.get(f"{source}->{target}")
        if payoff is not None and payoff.test.believable(family=family):
            live.append(payoff)
    return sorted(live, key=lambda item: abs(item.delta), reverse=True)


def format_evidence_for_prompt(payoffs: Sequence[OfferedPayoff], family: int) -> str:
    """Numbers, not a recommendation.

    The archive does not get to author a sentence inside the prompt that decides the
    route. It gets to show what earlier runs measured, with the sample sizes and the
    test beside it, and the agent — which can see the actual research and the archive
    cannot — decides what that is worth.
    """
    if not payoffs:
        return ""
    lines = [
        "## What earlier runs measured about these moves",
        "",
        "Observational and from other research questions, so it is weaker than what you can "
        "see in front of you. Only contrasts that clear a family-corrected threshold are "
        "shown; the rest are omitted rather than shown weakly.",
        "",
        "| Move | Took it | Declined it | Difference | Test |",
        "| --- | --- | --- | --- | --- |",
    ]
    for payoff in payoffs:
        lines.append(
            f"| `{payoff.edge}` | {payoff.taken_mean:.3f} (n={payoff.taken_n}) | "
            f"{payoff.declined_mean:.3f} (n={payoff.declined_n}) | {payoff.delta:+.3f} | "
            f"{payoff.test.describe(family=family)} |"
        )
    lines.append("")
    lines.append(
        "This is evidence, not an instruction. A move that paid on average across other runs "
        "can still be wrong here, and the reason you give should be about this run's results."
    )
    return "\n".join(lines)
