"""Turn the one-way march into a loop that can come back with a better question.

AutoR's stages run 01 through 08 and stop. Rollback exists, but it is a *repair*
mechanism: something went wrong, invalidate the downstream work, do it again.
There was no way to express the ordinary shape of research — we predicted X, we
measured, X was wrong, here is what that tells us and here is round two.

The consequence was structural, not cosmetic. A refuted hypothesis had nowhere
to go. Stage 06 adjudicates it (see :mod:`src.preregistration`), Stage 07 then
has to write a manuscript, and the only paths available were to write up a
result the run does not have or to roll back and pretend the first attempt never
happened. Neither is what a researcher does.

A **round** covers Stages 03-06: design, implement, experiment, analyse. It ends
with a decision recorded in ``workspace/notes/research_rounds.json``:

- ``converged`` — go and write it up.
- ``refine_design`` — same hypotheses, the design could not test them properly.
  Back to Stage 03.
- ``new_hypothesis`` — the hypotheses were wrong in an informative way. Back to
  Stage 02, where the preregistration amendment machinery records the change.
- ``abandon`` — the question cannot be answered with the resources available.
  The run stops and says so.

**What stops every round declaring victory.** An agent asked "are we done?" says
yes. So ``converged`` is refused when no hypothesis came out supported, unless
the round explicitly declares a negative result — a run whose contribution *is*
the refutation. Both are legitimate; quietly proceeding to write a paper about
nothing is not, and it is the default failure without this rule.

Iteration is bounded by ``--max-rounds`` and off by default, because rounds
multiply the cost of an unattended run. The decision is recorded either way, so
a single-round run still says whether it converged or merely stopped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from .utils import RunPaths, StageSpec


#: What a round may conclude. There is no "continue" — a round that wants
#: another one has to say what it would change.
DECISIONS = ("converged", "refine_design", "new_hypothesis", "abandon")

#: Which stage each decision resumes from. ``converged`` and ``abandon`` do not
#: resume.
DECISION_ENTRY_STAGE = {
    "refine_design": "03_study_design",
    "new_hypothesis": "02_hypothesis_generation",
}

#: The round ends when this stage is approved.
ROUND_CLOSING_STAGE_NUMBER = 6

#: The first stage inside a round. Stages before it are per-run, not per-round.
ROUND_FIRST_STAGE_NUMBER = 3


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


@dataclass(frozen=True)
class Round:
    number: int
    decision: str
    rationale: str
    what_we_learned: str
    what_changes_next: str
    negative_result: bool
    hypothesis_verdicts: dict[str, str]
    recorded_at: str
    acted_on: bool = True
    budget_note: str = ""
    #: The abandoned round this one overrules, if any. Zero otherwise.
    reopens_round: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "round": self.number,
            "decision": self.decision,
            "rationale": self.rationale,
            "what_we_learned": self.what_we_learned,
            "what_changes_next": self.what_changes_next,
            "negative_result": self.negative_result,
            "hypothesis_verdicts": dict(self.hypothesis_verdicts),
            "recorded_at": self.recorded_at,
            "acted_on": self.acted_on,
            "budget_note": self.budget_note,
            "reopens_round": self.reopens_round,
        }


@dataclass(frozen=True)
class RoundIntent:
    """What a closed round asked the run to do next.

    A request, not an instruction. It goes to the router like any other proposed
    move: admissible or refused, and recorded either way with its choice set.
    """

    target: str
    reason: str
    number: int


def load_rounds(paths: RunPaths) -> list[Round]:
    payload = _load_json(paths.research_rounds)
    if not isinstance(payload, dict):
        return []
    rounds: list[Round] = []
    for entry in payload.get("rounds", []):
        if not isinstance(entry, dict):
            continue
        verdicts = entry.get("hypothesis_verdicts")
        rounds.append(
            Round(
                number=int(entry.get("round") or 0),
                decision=str(entry.get("decision") or "").strip(),
                rationale=str(entry.get("rationale") or "").strip(),
                what_we_learned=str(entry.get("what_we_learned") or "").strip(),
                what_changes_next=str(entry.get("what_changes_next") or "").strip(),
                negative_result=bool(entry.get("negative_result", False)),
                hypothesis_verdicts={
                    str(key): str(value) for key, value in verdicts.items()
                }
                if isinstance(verdicts, dict)
                else {},
                recorded_at=str(entry.get("recorded_at") or ""),
                acted_on=bool(entry.get("acted_on", True)),
                budget_note=str(entry.get("budget_note") or ""),
                reopens_round=int(entry.get("reopens_round") or 0),
            )
        )
    return rounds


def current_round_number(paths: RunPaths) -> int:
    """1-based. The round in progress is one past the last one recorded."""
    return len(load_rounds(paths)) + 1


def latest_round(paths: RunPaths) -> Round | None:
    rounds = load_rounds(paths)
    return rounds[-1] if rounds else None


def _write_rounds(paths: RunPaths, rounds: list[Round]) -> None:
    paths.research_rounds.parent.mkdir(parents=True, exist_ok=True)
    paths.research_rounds.write_text(
        json.dumps(
            {"updated_at": _now(), "rounds": [item.to_dict() for item in rounds]},
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )


def read_round_decision(paths: RunPaths) -> dict | None:
    """Stage 06's declaration, before the round budget is applied to it."""
    payload = _load_json(paths.round_decision)
    return payload if isinstance(payload, dict) else None


def validate_round_decision(paths: RunPaths, stage: StageSpec) -> list[str]:
    """Stage 06 must say what the round concluded, and may not claim more than it has.

    The rule that carries the weight: ``converged`` with no supported hypothesis
    and no declared negative result is refused. Without it, a run that refuted
    everything it predicted proceeds to write a paper, and nothing in the
    pipeline objects.
    """
    if stage.number < ROUND_CLOSING_STAGE_NUMBER:
        return []

    if stage.number > ROUND_CLOSING_STAGE_NUMBER:
        # The declaration is consumed when the round closes, so from Stage 07 on
        # the question is what the closed round concluded, not what is pending.
        final = latest_round(paths)
        if final is None:
            return [
                "requires at least one closed research round. Stage 06 records the round's "
                "conclusion in workspace/notes/research_rounds.json when it is approved."
            ]
        standing = unreopened_abandonment(paths)
        if standing is not None:
            return [
                f"cannot run: round {standing.number} concluded `abandon` — {standing.rationale}. "
                "Writing up a run that decided the question could not be answered would "
                "contradict its own record. A later round may overrule it, but has to say so: "
                f"set `reopens_round: {standing.number}` in round_decision.json."
            ]
        return []

    payload = read_round_decision(paths)
    if payload is None:
        return [
            "requires workspace/notes/round_decision.json saying what this round concluded: "
            f"one of {', '.join(DECISIONS)}, with the reasoning and what would change next."
        ]

    problems: list[str] = []
    decision = str(payload.get("decision") or "").strip()
    if decision not in DECISIONS:
        problems.append(
            f"round_decision.json decision is {decision!r}; expected one of {', '.join(DECISIONS)}."
        )
        return problems

    if len(str(payload.get("rationale") or "").strip()) < 40:
        problems.append("round_decision.json needs a substantive rationale for the decision.")
    if len(str(payload.get("what_we_learned") or "").strip()) < 40:
        problems.append(
            "round_decision.json must say what this round established, including when the "
            "answer is that a prediction was wrong."
        )
    if decision in DECISION_ENTRY_STAGE and len(str(payload.get("what_changes_next") or "").strip()) < 40:
        problems.append(
            f"round_decision.json chooses {decision} but does not say what would change. "
            "Repeating a round without changing anything produces the same result."
        )

    from .preregistration import load_hypothesis_outcomes, load_preregistration

    prereg = load_preregistration(paths)
    if prereg is not None and decision == "converged":
        outcomes = load_hypothesis_outcomes(paths)
        supported = [item.identifier for item in outcomes if item.verdict == "supported"]
        if not supported and not bool(payload.get("negative_result", False)):
            refuted = [item.identifier for item in outcomes if item.verdict == "refuted"]
            problems.append(
                "round_decision.json declares the run converged, but no preregistered "
                f"hypothesis came out supported ({len(refuted)} refuted). Either run another "
                "round, or set `negative_result: true` and make the refutation the "
                "contribution — a paper reporting what does not work is a real paper, and a "
                "paper that quietly drops its own refuted prediction is not."
            )
    return problems


def record_round(
    paths: RunPaths,
    *,
    acted_on: bool,
    budget_note: str = "",
) -> Round | None:
    """Close the round from Stage 06's declaration and the adjudicated verdicts."""
    payload = read_round_decision(paths)
    if payload is None:
        return None

    from .preregistration import load_hypothesis_outcomes

    verdicts = {item.identifier: item.verdict for item in load_hypothesis_outcomes(paths)}
    rounds = load_rounds(paths)
    entry = Round(
        number=len(rounds) + 1,
        decision=str(payload.get("decision") or "").strip(),
        rationale=str(payload.get("rationale") or "").strip(),
        what_we_learned=str(payload.get("what_we_learned") or "").strip(),
        what_changes_next=str(payload.get("what_changes_next") or "").strip(),
        negative_result=bool(payload.get("negative_result", False)),
        hypothesis_verdicts=verdicts,
        recorded_at=_now(),
        acted_on=acted_on,
        budget_note=budget_note,
        reopens_round=int(payload.get("reopens_round") or 0),
    )
    rounds.append(entry)
    _write_rounds(paths, rounds)
    # The declaration belongs to one round. Leaving it in place would let the
    # next round inherit the previous round's conclusion.
    paths.round_decision.unlink(missing_ok=True)
    return entry


def unreopened_abandonment(paths: RunPaths) -> Round | None:
    """The abandonment that still stands, if there is one.

    Not ``latest_round``. An abandonment is a conclusion about the whole run, and
    reading only the last entry let it be laundered: close round 1 as ``abandon``,
    go back through any route that does not consult it — `/back`,
    `--rollback-stage`, or the graph's own revisit edges — re-approve Stage 06 and
    declare ``converged``, and the ledger reads ``[abandon, converged]`` while every
    downstream check sees only the second. The run then writes up the question it
    had recorded that it could not answer.

    Overruling one is legitimate and often right — a person who disagrees is exactly
    who should be able to. It has to be on the record, which is what
    ``reopens_round`` is: a later round naming the abandoned round it supersedes.
    The difference between "we reconsidered and said so" and "we reconsidered" is
    the whole of the thing, which is the same rule
    :func:`src.preregistration.amend_preregistration` already applies to hypotheses.
    """
    rounds = load_rounds(paths)
    reopened = {item.reopens_round for item in rounds if item.reopens_round}
    standing = [
        item for item in rounds if item.decision == "abandon" and item.number not in reopened
    ]
    return standing[-1] if standing else None


def resume_stage_slug_for(decision: str) -> str | None:
    return DECISION_ENTRY_STAGE.get(decision)


def format_rounds_for_prompt(paths: RunPaths) -> str:
    """What earlier rounds established. Injected into every stage inside a round.

    Without this a second round repeats the first: same design, same blind spot,
    same result, at full cost.
    """
    rounds = load_rounds(paths)
    if not rounds:
        return ""
    lines = [
        f"This is round {len(rounds) + 1}. Earlier rounds of this run:",
        "",
    ]
    for entry in rounds:
        lines.append(f"### Round {entry.number} — {entry.decision}")
        if entry.hypothesis_verdicts:
            verdicts = ", ".join(
                f"{key}: {value}" for key, value in sorted(entry.hypothesis_verdicts.items())
            )
            lines.append(f"- Verdicts: {verdicts}")
        if entry.what_we_learned:
            lines.append(f"- What it established: {entry.what_we_learned}")
        if entry.what_changes_next:
            lines.append(f"- What this round should change: {entry.what_changes_next}")
        if entry.rationale:
            lines.append(f"- Why: {entry.rationale}")
        lines.append("")
    lines.append(
        "Do not repeat an earlier round's design without changing what it got wrong. A "
        "refuted hypothesis from an earlier round is a finding this run owns; carry it "
        "forward rather than quietly dropping it."
    )
    return "\n".join(lines)


def format_round_status(paths: RunPaths, max_rounds: int) -> str:
    rounds = load_rounds(paths)
    if not rounds:
        return ""
    final = rounds[-1]
    if final.decision == "converged":
        shape = "converged" + (" on a negative result" if final.negative_result else "")
    elif not final.acted_on:
        shape = f"stopped with the round budget spent ({len(rounds)}/{max_rounds}), wanting {final.decision}"
    else:
        shape = final.decision
    return f"{len(rounds)} round(s); {shape}"

def amend_last_round(paths: RunPaths, *, acted_on: bool, budget_note: str = "") -> Round | None:
    """Correct the last round's record once the router has ruled on its intent.

    `record_round` runs at Stage 06 approval; whether the intent was honoured is not
    known until the router has evaluated it, which happens afterwards. Writing
    `acted_on` at approval time and leaving it meant the ledger could claim a round
    was acted on when the move it asked for was refused — a claim nothing later would
    contradict, in the one artifact a reader consults to find out what the run
    decided.
    """
    rounds = load_rounds(paths)
    if not rounds:
        return None
    last = rounds[-1]
    amended = Round(
        number=last.number,
        decision=last.decision,
        rationale=last.rationale,
        what_we_learned=last.what_we_learned,
        what_changes_next=last.what_changes_next,
        negative_result=last.negative_result,
        hypothesis_verdicts=last.hypothesis_verdicts,
        recorded_at=last.recorded_at,
        acted_on=acted_on,
        budget_note=budget_note,
        reopens_round=last.reopens_round,
    )
    _write_rounds(paths, [*rounds[:-1], amended])
    return amended


def discard_pending_decision(paths: RunPaths) -> bool:
    """Drop a round declaration that no round will close.

    `_skip_stage` returns before the approval branch, so a Stage 06 that exhausted
    its retries never reaches `record_round` and never unlinks the file. Left there,
    the *next* Stage 06 closes its round from the previous visit's declaration —
    inheriting a conclusion drawn from results it did not produce.
    """
    if not paths.round_decision.exists():
        return False
    paths.round_decision.unlink(missing_ok=True)
    return True

