#!/usr/bin/env python3
"""What a finished run's ``logs_raw.jsonl`` says it cost, and both ways to read it wrong.

Every cost figure quoted in ``src/call_cost.py``, ``src/stage_cost.py`` and the pull request
that added them comes from one invocation of this file. The population is
:data:`MEASURED_RUNS`, named rather than globbed, for the reason
``tools/supervisor_threshold_replay.py`` names its own: a fourth run under the same trial
directory is still being written, and a denominator that moves under the reader is not
evidence. ::

    python3 tools/log_cost_census.py \\
        /rmeng_data/robtang/rcb-trial-graph/workspaces/Astronomy_000_20260814_175426/.autor/*/ \\
        /rmeng_data/robtang/rcb-trial-graph/workspaces/Astronomy_000_20260815_074118/.autor/*/ \\
        /rmeng_data/robtang/rcb-trial-graph/workspaces/Chemistry_000_20260816_011751/.autor/*/

The last line of the report says whether this invocation is the recorded one and whether
any of the recorded numbers has drifted. :data:`RECORDED` is the table those numbers live
in, and the report prints ``DRIFTED`` with both sides rather than quietly printing a
different one.

**It calls the shipped reader.** :func:`src.call_cost.CallCost.from_result_event` and
:func:`src.call_cost.is_result_event` are imported rather than reimplemented, so the census
measures the arithmetic the run will actually use. An instrument that reimplements the code
it measures is how a measurement comes out right about a program that does something else.

The two readings, printed side by side
---------------------------------------
``total_cost_usd`` is a per-call charge. The census prints the sum, which is right, and
beside it the sum of the *last* value seen per ``session_id``, which is what the field would
deserve if it were cumulative. It also prints how many times a session's next result charges
*less* than the one before, which is the observation that rules the cumulative reading out:
one such step is enough, and the measured runs have dozens.

``input_tokens`` is the uncached remainder of a four-way split. The census prints all four
and the ratio of cache reads to uncached input, because that ratio is the size of the
mistake a single "tokens used" figure makes.

Why the log is read as bytes, and what that is *not* a fix for
---------------------------------------------------------------
``src/stage_cost.py``'s docstring records that a NUL byte makes GNU grep treat a whole file
as binary, so ``grep -c`` prints nothing on the run that contributes the most exhaustions.
That is true of ``logs.txt``. It is **not** true of ``logs_raw.jsonl``, which is the file
this reader opens: measured on the 08-14 run, its 8,455 lines hold no NUL byte and every one
of them parses. The binary read and the replacing decoder are a bound on the damage rather
than a fix for an observed fault -- a line that will not decode costs one line, and the
count of the other 8,454 stands. Said plainly because the alternative is a comment implying
a problem this file has never met.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Any, Iterable, NamedTuple, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.call_cost import (  # noqa: E402
    DOLLAR_FIELD,
    TOKEN_FIELDS,
    TOKEN_LABELS,
    CallCost,
    billed_tokens,
    is_result_event,
)

#: The three runs of the first live paired trial whose ``run_manifest.json`` says they
#: finished. The fourth directory under the same trial, ``Chemistry_000_20260816_173127``,
#: was still ``running`` and is excluded everywhere for the same reason: its
#: ``logs_raw.jsonl`` grows while it is being counted.
MEASURED_RUNS: tuple[str, ...] = (
    "Astronomy_000_20260814_175426",
    "Astronomy_000_20260815_074118",
    "Chemistry_000_20260816_011751",
)


class Recorded(NamedTuple):
    """What one run of :data:`MEASURED_RUNS` measured, when the numbers were written down."""

    result_events: int
    dispatch_records: int
    summed_usd: float
    last_per_session_usd: float
    sessions: int
    descending_steps: int
    input_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    output_tokens: int


#: The figures quoted in ``src/call_cost.py``'s header and in the pull request, keyed by run.
#:
#: Held here rather than only in prose so :func:`population_matches` can say ``DRIFTED``
#: out loud. A number in a docstring that no instrument contradicts is a number nobody can
#: check, and this repository has shipped five of those.
RECORDED: dict[str, Recorded] = {
    "Astronomy_000_20260814_175426": Recorded(
        result_events=82,
        dispatch_records=82,
        summed_usd=574.67,
        last_per_session_usd=212.68,
        sessions=38,
        descending_steps=22,
        input_tokens=5_117,
        cache_creation_input_tokens=27_191_137,
        cache_read_input_tokens=644_146_902,
        output_tokens=3_292_425,
    ),
    "Astronomy_000_20260815_074118": Recorded(
        result_events=99,
        dispatch_records=95,
        summed_usd=744.99,
        last_per_session_usd=254.87,
        sessions=55,
        descending_steps=23,
        input_tokens=7_845,
        cache_creation_input_tokens=32_474_254,
        cache_read_input_tokens=908_452_140,
        output_tokens=3_496_566,
    ),
    "Chemistry_000_20260816_011751": Recorded(
        result_events=100,
        dispatch_records=95,
        summed_usd=643.42,
        last_per_session_usd=191.09,
        sessions=53,
        descending_steps=27,
        input_tokens=5_712,
        cache_creation_input_tokens=32_774_595,
        cache_read_input_tokens=719_039_242,
        output_tokens=3_153_967,
    ),
}

#: The key a dispatch record sits under in ``logs_raw.jsonl``. AutoR writes one before every
#: backend launch, so counting them gives invocations rather than result events -- the two
#: numbers a reader is most likely to assume are the same.
DISPATCH_KEY = "_meta"

#: The key the backend puts its session identifier under on a result event.
SESSION_KEY = "session_id"


def stream_events(path: Path) -> Iterable[dict[str, Any]]:
    """Every JSON object in a raw log, in order, skipping what will not parse.

    Binary reads with a replacing decoder, so a line that will not decode costs one line
    rather than the rest of the file. On the measured runs nothing is lost this way -- the
    08-14 log's 8,455 lines all parse -- and the header says why the defence is here anyway.
    """
    with path.open("rb") as handle:
        for raw in handle:
            try:
                payload = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if isinstance(payload, dict):
                yield payload


def session_monotonicity(charges: Sequence[tuple[str, float]]) -> int:
    """How many times a session's next charge is *lower* than its previous one.

    The observation that settles whether ``total_cost_usd`` is cumulative. A cumulative
    field cannot go down within a session, so one descending step refutes the reading and
    the census reports the count rather than a verdict.
    """
    previous: dict[str, float] = {}
    descending = 0
    for session, charge in charges:
        seen = previous.get(session)
        if seen is not None and charge < seen:
            descending += 1
        previous[session] = charge
    return descending


class Census(NamedTuple):
    run: str
    total: CallCost
    dispatch_records: int
    sessions: int
    descending_steps: int
    last_per_session_usd: float

    def as_recorded(self) -> Recorded:
        return Recorded(
            result_events=self.total.result_events,
            dispatch_records=self.dispatch_records,
            summed_usd=round(self.total.total_cost_usd or 0.0, 2),
            last_per_session_usd=round(self.last_per_session_usd, 2),
            sessions=self.sessions,
            descending_steps=self.descending_steps,
            input_tokens=self.total.input_tokens or 0,
            cache_creation_input_tokens=self.total.cache_creation_input_tokens or 0,
            cache_read_input_tokens=self.total.cache_read_input_tokens or 0,
            output_tokens=self.total.output_tokens or 0,
        )


def census_of(run: str, log: Path) -> Census:
    """One run's cost, both readings of it, and the counts that tell them apart."""
    total = CallCost()
    dispatch_records = 0
    charges: list[tuple[str, float]] = []
    last_seen: dict[str, float] = {}
    for event in stream_events(log):
        if DISPATCH_KEY in event:
            dispatch_records += 1
            continue
        if not is_result_event(event):
            continue
        total = total + CallCost.from_result_event(event)
        charge = event.get(DOLLAR_FIELD)
        if isinstance(charge, (int, float)) and not isinstance(charge, bool):
            session = str(event.get(SESSION_KEY) or "")
            charges.append((session, float(charge)))
            last_seen[session] = float(charge)
    return Census(
        run=run,
        total=total,
        dispatch_records=dispatch_records,
        sessions=len(last_seen),
        descending_steps=session_monotonicity(charges),
        last_per_session_usd=sum(last_seen.values()),
    )


def population_matches(measured: Sequence[Census]) -> str:
    """One line saying whether this invocation is the documented one, and whether it moved.

    Three answers, and the middle one is why the function exists. A population that is not
    :data:`MEASURED_RUNS` gets no comparison at all -- a reader who globbed the trial
    directory has picked up a run still being written and no docstring figure describes it.
    A population that *is* the recorded one but produces different numbers prints
    ``DRIFTED`` and both sides, which is the only mechanism by which a figure in
    ``src/call_cost.py`` can stop being true out loud rather than quietly.
    """
    names = tuple(item.run for item in measured)
    if names != MEASURED_RUNS:
        return (
            f"population: not the recorded one ({len(names)} run(s)); the recorded "
            f"population is {', '.join(MEASURED_RUNS)}, and no docstring figure "
            "describes this one"
        )
    drifted = [
        f"{item.run}: recorded {RECORDED[item.run]}, measured {item.as_recorded()}"
        for item in measured
        if RECORDED[item.run] != item.as_recorded()
    ]
    if drifted:
        return "population: DRIFTED -- " + "; ".join(drifted)
    return (
        f"population: as recorded -- {len(MEASURED_RUNS)} finished run(s), every figure "
        "in src/call_cost.py's header re-derived"
    )


def _report(measured: Sequence[Census]) -> None:
    for item in measured:
        total = item.total
        print(f"\n== {item.run} ==")
        print(
            f"  {total.result_events} result event(s), {total.priced_events} priced, "
            f"from {item.dispatch_records} dispatch record(s)"
        )
        print(f"  {item.sessions} distinct session id(s)")
        print("  -- trap one: is total_cost_usd per call or cumulative? --")
        print(
            f"    summed per call            ${total.total_cost_usd or 0.0:,.2f}   <- what "
            "the run cost"
        )
        print(
            f"    last value per session id  ${item.last_per_session_usd:,.2f}   <- what a "
            "cumulative field would deserve"
        )
        ratio = (total.total_cost_usd or 0.0) / max(item.last_per_session_usd, 1e-9)
        print(
            f"    the wrong reading is {ratio:,.1f}x out, and {item.descending_steps} "
            "charge(s) fall below the previous one in the same session, which is what "
            "rules it out"
        )
        print("  -- trap two: which fields does a token figure sum? --")
        for name in TOKEN_FIELDS:
            print(f"    {TOKEN_LABELS[name]:<12} {getattr(total, name) or 0:>15,}")
        print(f"    {'sum':<12} {billed_tokens(total) or 0:>15,}")
        cache_read = total.cache_read_input_tokens or 0
        print(
            f"    cache_read is {cache_read / max(total.input_tokens or 1, 1):,.0f}x the "
            "uncached input, so input alone understates the run by five orders of magnitude"
        )
    print()
    print(population_matches(measured))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_dirs", nargs="+", help="run roots holding logs_raw.jsonl")
    args = parser.parse_args(argv)

    measured: list[Census] = []
    for pattern in args.run_dirs:
        for match in sorted(glob.glob(pattern)):
            root = Path(match)
            log = root / "logs_raw.jsonl"
            if not log.is_file():
                print(f"skipped {root}: no logs_raw.jsonl")
                continue
            # The run's own name is its workspace directory, two levels above `.autor/<ts>/`.
            name = root.parent.parent.name
            measured.append(census_of(name, log))
    if not measured:
        print("no runs read")
        return 1
    _report(measured)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
