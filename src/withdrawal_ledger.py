"""The state goes back. The evidence does not.

Every mechanism around this one is built to make a withdrawal complete: the accumulated
inverses put the workspace back, the version chains rewind what they can, the committed
views retire the approvals that no longer hold. Taken to its limit that is a system whose
dynamic history leaves no trace — whatever sequence of moves a run has been through, it
quiesces where a run that had gone straight there would have.

For a plugin host that is the whole goal. For a research run it is half of one, and the
wrong half to stop at. A run that withdraws Stage 04's design and then re-enters Stage 04
with no record of what was withdrawn has bought itself the right to make the same mistake
again, cheaply and repeatedly. The state should leave no trace. The *evidence* should
survive exactly because the state did not.

So the run's context divides in two, and the division is deliberate rather than incidental:

- **The workspace** is revertible. Withdrawing a stage returns it to what the last
  surviving stage left, and nothing of the abandoned attempt remains in it.
- **This ledger** is monotone. It only ever grows, no withdrawal touches it, and it is what
  the abandoned attempt leaves behind.

The second half is what makes the first safe to use. Recovery that also erased the reason
for the recovery would make a rollback indistinguishable from never having tried, and a run
that cannot distinguish those is a run that will try again.

**It has to reach the stage that could repeat the mistake, or it is an archive.** The record
is delivered as a typed information channel to the seven stages a backward edge can land on
— read off ``REVISIT_EDGES`` rather than hand-picked, so a new backward edge brings its
target into the readership without anyone remembering to add it. A stage re-entered after a
withdrawal is told what was withdrawn from it and why, in the same prompt that asks it to
try again.

The file lives under ``evolution/`` rather than ``workspace/``: it is a record of how the
run reached its answer, not part of the answer, and a benchmark export of the workspace does
not ship it. That placement is also what puts it outside every withdrawal path by
construction rather than by an exclusion somebody has to maintain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .utils import RunPaths, StageSpec

#: How many past withdrawals a prompt carries. The whole history is kept on disk; what a
#: stage needs is the recent shape of what has been tried, and an unbounded block would
#: grow until it crowded out the work the stage is being asked to do.
PROMPT_WITHDRAWAL_LIMIT = 5


@dataclass(frozen=True)
class WithdrawalRecord:
    """One withdrawal: what it took back, from where, and why."""

    at: str
    target_stage: str
    reason: str
    #: Files whose creator was inside the withdrawn range, so they were removed.
    deleted: int = 0
    #: Files that existed before the range and were returned to the version the last
    #: surviving stage left.
    rewound: int = 0
    #: Stages whose approval the withdrawal retired, by slug.
    invalidated: tuple[str, ...] = ()
    #: Approvals retired because an input moved rather than because of the numbering,
    #: rendered as ``stage: channel (from producer)``. The interesting half: these are
    #: the ones a stage-number rule would have missed.
    drifted: tuple[str, ...] = ()
    #: Intents to act outside the run that were dropped unperformed.
    emissions_discarded: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "at": self.at,
            "target_stage": self.target_stage,
            "reason": self.reason,
            "deleted": self.deleted,
            "rewound": self.rewound,
            "invalidated": list(self.invalidated),
            "drifted": list(self.drifted),
            "emissions_discarded": self.emissions_discarded,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "WithdrawalRecord":
        def _tuple(key: str) -> tuple[str, ...]:
            raw = payload.get(key)
            return tuple(str(item) for item in raw) if isinstance(raw, list) else ()

        return cls(
            at=str(payload.get("at", "")).strip(),
            target_stage=str(payload.get("target_stage", "")).strip(),
            reason=str(payload.get("reason", "")).strip(),
            deleted=int(payload.get("deleted", 0) or 0),
            rewound=int(payload.get("rewound", 0) or 0),
            invalidated=_tuple("invalidated"),
            drifted=_tuple("drifted"),
            emissions_discarded=int(payload.get("emissions_discarded", 0) or 0),
        )

    def render(self) -> str:
        moved = []
        if self.deleted:
            moved.append(f"{self.deleted} artifact(s) deleted")
        if self.rewound:
            moved.append(f"{self.rewound} rewound")
        if self.emissions_discarded:
            moved.append(f"{self.emissions_discarded} unsent action(s) dropped")
        body = f"- **{self.target_stage}** ({self.at}): {self.reason}"
        if moved:
            body += f"\n  - {', '.join(moved)}"
        if self.invalidated:
            body += f"\n  - approvals retired: {', '.join(self.invalidated)}"
        if self.drifted:
            body += f"\n  - retired because an input moved: {'; '.join(self.drifted)}"
        return body


def ledger_path(paths: RunPaths) -> Path:
    return paths.evolution_dir / "withdrawal_ledger.jsonl"


def append_withdrawal(paths: RunPaths, record: WithdrawalRecord) -> WithdrawalRecord:
    """Add one row. Append-only: nothing in the system rewrites or removes a row.

    A withdrawal that could edit this file would be able to withdraw the record of itself,
    which is the one thing the split between workspace and ledger exists to prevent.
    """

    path = ledger_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.to_dict(), ensure_ascii=True) + "\n")
    return record


def load_withdrawals(paths: RunPaths) -> list[WithdrawalRecord]:
    path = ledger_path(paths)
    if not path.exists():
        return []
    records: list[WithdrawalRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(WithdrawalRecord.from_dict(payload))
    return records


def withdrawals_for_stage(paths: RunPaths, stage: StageSpec) -> list[WithdrawalRecord]:
    return [record for record in load_withdrawals(paths) if record.target_stage == stage.slug]


def format_withdrawal_history_for_prompt(paths: RunPaths, stage: StageSpec) -> str | None:
    """What this run has already withdrawn, for the stage that could repeat it.

    Ordered with the stage's own withdrawals first. A stage re-entered after its own work
    was taken back is the case this block exists for; the rest of the history is context
    for why the run is where it is.
    """

    records = load_withdrawals(paths)
    if not records:
        return None

    own = withdrawals_for_stage(paths, stage)
    others = [record for record in records if record.target_stage != stage.slug]
    lines: list[str] = []

    if own:
        lines.append(
            f"This stage has been withdrawn {len(own)} time(s) in this run. What was taken "
            "back, and why:"
        )
        lines.extend(record.render() for record in own[-PROMPT_WITHDRAWAL_LIMIT:])

    if others:
        if lines:
            lines.append("")
        lines.append("Other withdrawals in this run:")
        lines.extend(record.render() for record in others[-PROMPT_WITHDRAWAL_LIMIT:])

    return "\n".join(lines)


def summarise(records: Sequence[WithdrawalRecord]) -> str:
    if not records:
        return "No withdrawal has been recorded."
    by_stage: dict[str, int] = {}
    for record in records:
        by_stage[record.target_stage] = by_stage.get(record.target_stage, 0) + 1
    parts = ", ".join(f"{stage} x{count}" for stage, count in sorted(by_stage.items()))
    return f"{len(records)} withdrawal(s): {parts}"
