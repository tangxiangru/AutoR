"""What the run cost is recorded, and nothing in the run decides on it.

The ask had three parts and the second is the one with teeth: report tokens and dollars at
the end of the run, let nothing at runtime decide on them, and keep them out of the paper.
"Nothing decides on them" is a promise until something checks it, and this repository
already has the shape for checking exactly that --
``tests/test_writable_decisive_fields.py`` classifies every gate by what its refusal turns
on, and ``tests/test_router_budget.py`` asserts over the syntax that ``StageRouter.choose``
never *branches* on a budget it is only handed. This is the same assertion for the cost
fields, and it covers every module under ``src/`` rather than one function.

What a decision is, here
------------------------
:data:`DECIDING_NODES` is the list, and it is the spec's list: a comparison, a boolean
operator, an ``if`` (statement or expression), a ``while``, an ``assert``, a comprehension
filter, a ``sorted`` key or a ``max``/``min`` over a cost field. The population of names is
``src.call_cost.INERT_NAMES``, which is derived from :data:`~src.call_cost.COST_FIELDS`
rather than written out here, so a field added there is covered without touching this file
and a field added anywhere else fails :class:`TheFieldsAreNamedInOnePlaceTests`.

The scan reads three kinds of node as "naming" a field: an identifier, an attribute, and a
**string constant**. The third is not paranoia -- ``if row["total_cost_usd"] > 10`` is a
decision that mentions no identifier at all, and it is the shape a reader of a ledger row
would reach for first.

Why the gate is satisfiable
----------------------------
Because nothing in ``src/`` branches on a *named* cost field. The arithmetic, the
serialisation and the formatting all iterate :data:`~src.call_cost.COST_FIELDS`, so the
value under test is an anonymous local and the field name never appears in the test.
:class:`TheGateIsNotVacuousTests` is the other half of that: it checks the fields really do
appear in a record, in a summary and in a formatter, so a future refactor cannot pass this
file by deleting the feature.

The supervisor, twice
---------------------
``src/supervisor.py`` is the component the constraint is aimed at: it is the only thing in
the tree that reads the cost ledger and acts on it, it wakes at every attempt boundary, and
it is the natural home for "this stage has spent too much money, stop". Its rulings must
stay a function of attempts, wall clock and failure digests.
:class:`TheSupervisorCannotSeeTheCostTests` asserts that twice over and by two different
methods: the syntax of the module carries no cost name at all -- not in a condition, not
anywhere -- and its rulings are replayed against two ledgers that differ only in what they
cost, with every field of every :class:`~src.supervisor.Intervention` required to match.
The second is what survives a refactor the first would not catch.

Absent is not zero
------------------
:class:`AbsentIsNotZeroTests` is the third constraint. The fake operator makes no backend
call and must not publish ``$0.00``; a backend that really charged nothing must publish
``$0.00``; the two have to be distinguishable in the record and in the formatter. That is a
test rather than a convention because zero is what every natural default gives you.

The mutation sweep is shipped rather than described
---------------------------------------------------
:data:`MUTATIONS` is the same claim as an instrument. Every entry is a one-anchor edit that
removes a rule this file is supposed to hold, and the first three are the ask's own
suggestion: put a cost into a decision path and confirm it dies. Run it against a **scratch
checkout**, because it edits the tree in place and restores it afterwards::

    git worktree add --detach /tmp/sweep HEAD
    cd /tmp/sweep && python3 -m tests.test_cost_is_recorded_and_unread --mutations

It prints one line per mutation naming the tests that died, and exits non-zero if any
survives, so "0 survivors" is re-derivable rather than asserted. Measured on this tree:
33 tried, 33 killed. That number is ``len(MUTATIONS)`` and
:meth:`TheSweepIsRunnableTests.test_the_docstring_says_how_many_mutations_there_are` fails
if this sentence and the tuple stop agreeing.
"""

from __future__ import annotations

import ast
import dataclasses
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Iterable, NamedTuple
from unittest.mock import MagicMock, patch

from src.approval_agent import AutomatedReviewer, ReviewDecision
from src.call_cost import (
    COST_FIELDS,
    COUNTER_FIELDS,
    DOLLAR_FIELD,
    INERT_NAMES,
    NOT_MEASURED,
    RECORD_FIELD,
    TOKEN_FIELDS,
    TOKEN_LABELS,
    TOKEN_SUM_LABEL,
    CallCost,
    CostTally,
    billed_tokens,
    call_cost_of,
    cost_from_stream_meta,
    describe_coverage,
    format_call_cost,
    is_result_event,
)
from src.manager import ResearchManager
from src.operator import ClaudeOperator
from src.stage_cost import (
    COST_SCOPE_NOTE,
    NO_COST_RECORDED,
    STAGE_COST_LEDGER_VERSION,
    StageCostMeter,
    append_stage_cost_row,
    bypassed_row,
    format_run_cost_report,
    format_stage_cost_summary,
    read_stage_cost_ledger,
    run_call_cost,
    summarize_stage_cost,
)
from src.router import StageRouter
from src.stage_graph import GraphState, StageGraph
from src.supervisor import Intervention, RunSupervisor
from src.terminal_ui import TerminalUI
from src.utils import (
    STAGES,
    OperatorResult,
    build_run_paths,
    create_run_root,
    ensure_run_layout,
    initialize_memory,
    write_text,
)
from src.validity_review import ValidityReviewOutcome
from tests.test_doc_counts import spelled
from tests.test_stage_cost_ledger import ManagerLoopFixture, _StubReviewer
from tools.log_cost_census import (
    MEASURED_RUNS,
    RECORDED,
    Census,
    census_of,
    population_matches,
    session_monotonicity,
)

REPO = Path(__file__).resolve().parent.parent
STAGE_01 = STAGES[0]


def src_modules() -> list[Path]:
    """Every module the gate covers: all of ``src/``, packages included."""
    return sorted(REPO.joinpath("src").rglob("*.py"))


def parsed_src() -> Iterable[tuple[Path, ast.Module]]:
    for path in src_modules():
        yield path, ast.parse(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The syntax gate
# ---------------------------------------------------------------------------

#: The node kinds that make a value decisive, spelled as the ask spelled them.
#:
#: ``BoolOp`` and ``Compare`` are collected wherever they appear rather than only inside an
#: ``if``: ``ok = cost.total_cost_usd > 10`` is the same decision one line earlier, and a
#: gate that only looked at ``If.test`` would miss the assignment and catch the branch.
DECIDING_NODES: tuple[str, ...] = (
    "If",
    "IfExp",
    "While",
    "Assert",
    "BoolOp",
    "Compare",
    "UnaryOp",
    "comprehension",
    "sorted-key",
    "max-or-min",
)

#: Builtins whose arguments choose between values and are therefore decisions.
ORDERING_BUILTINS = frozenset({"max", "min"})

#: The builtin whose ``key=`` argument orders a population.
SORTING_BUILTIN = "sorted"


def names_in(node: ast.AST) -> set[str]:
    """Every identifier, attribute and string constant reachable from *node*.

    All three, because a cost field can be reached by any of them: ``cost.total_cost_usd``
    is an attribute, ``total_cost_usd`` a bare name after an unpack, and
    ``row["total_cost_usd"]`` a string constant with no identifier anywhere in it.
    """
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Attribute):
            found.add(child.attr)
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            found.add(child.value)
    return found


class Decision(NamedTuple):
    module: str
    line: int
    kind: str
    names: tuple[str, ...]

    def __str__(self) -> str:
        return f"{self.module}:{self.line} reads {', '.join(self.names)} in a {self.kind}"


def _tests_of(node: ast.AST) -> list[tuple[str, ast.AST]]:
    """The sub-expressions of *node* that decide something, with the kind that made them so."""
    if isinstance(node, (ast.If, ast.While, ast.IfExp)):
        return [(type(node).__name__, node.test)]
    if isinstance(node, ast.Assert):
        return [("Assert", node.test)]
    if isinstance(node, (ast.BoolOp, ast.Compare, ast.UnaryOp)):
        return [(type(node).__name__, node)]
    if isinstance(node, ast.comprehension):
        return [("comprehension", test) for test in node.ifs]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in ORDERING_BUILTINS:
            return [("max-or-min", argument) for argument in node.args]
        if node.func.id == SORTING_BUILTIN:
            return [
                ("sorted-key", keyword.value)
                for keyword in node.keywords
                if keyword.arg == "key"
            ]
    return []


#: Modules whose job is to hold, serialise or render the number, and which therefore have
#: to branch on it.
#:
#: The rule this file enforces is not "no condition may read a cost" — that rule is the
#: wrong shape and it accuses the recorder for recording. It is "no condition that changes
#: **what the run does** may read a cost". A formatter asking "is this field absent, so do I
#: print a dash" is not a run decision, and with alias propagation on there are 88 of them
#: across these three: 43 in the renderer, 39 in the ledger, 6 in the recorder.
#:
#: The exemption is narrow and it is itself a gate. None of the three can start a stage,
#: choose a move, end a visit or move a budget; they are reached only to write down and to
#: display. Adding a fourth name here is adding a module that may see the money, and it
#: needs the same argument. Everything that *can* change a run — the supervisor, the router,
#: the manager, the evolution controller, the archive — is outside it and is scanned with
#: aliases resolved.
RECORDS_OR_RENDERS_THE_COST = (
    "src/call_cost.py",
    "src/stage_cost.py",
    "src/terminal_ui.py",
)


def aliases_within(scope: ast.AST, watched: set[str]) -> set[str]:
    """*watched*, plus every local that was assigned from something already in it.

    Iterated to a fixpoint, because an alias can be assigned from an alias. Without this
    the scan reads only the deciding expression, and

        spent = meter.call_cost.total_cost_usd
        if spent > 100.0:

    names nothing watched at the point of the comparison. A reviewer built a working
    escape on exactly that shape — a helper reading the bill into a local, a second helper
    filtering on the first, and three lines in ``StageRouter.choose`` dropping the
    expensive targets — and the whole suite stayed green while the router shopped on
    price. The syntax half of that hole is this function; the behavioural half is
    :meth:`TheSupervisorCannotSeeTheCostTests.test_the_router_rules_the_same_way_on_both_ledgers`,
    and neither is sufficient alone.
    """
    known = set(watched)
    for _ in range(8):  # a fixpoint in practice; bounded so a cycle cannot hang the suite
        grew = False
        for node in ast.walk(scope):
            targets: list[ast.AST] = []
            value: ast.AST | None = None
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and node.value is not None:
                targets, value = [node.target], node.value
            if value is None or not (known & names_in(value)):
                continue
            for target in targets:
                for name in names_in(target):
                    if name not in known:
                        known.add(name)
                        grew = True
        if not grew:
            break
    return known


def decisions_reading(tree: ast.AST, module: str, watched: Iterable[str]) -> list[Decision]:
    """Every place in *tree* where a decision reads one of *watched*, or an alias of one.

    Aliases are resolved per function rather than per module: a local called ``value`` is
    a cost in one function and an unrelated number in the next, and treating the whole
    file as one scope would accuse the second.
    """
    wanted = set(watched)
    found: list[Decision] = []
    scopes: list[ast.AST] = [tree] + [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    seen: set[tuple[int, str]] = set()
    resolve_aliases = module not in RECORDS_OR_RENDERS_THE_COST
    for scope in scopes:
        local = aliases_within(scope, wanted) if resolve_aliases else wanted
        for node in ast.walk(scope):
            for kind, test in _tests_of(node):
                hit = sorted(local & names_in(test))
                if not hit:
                    continue
                line = getattr(test, "lineno", getattr(node, "lineno", 0))
                if (line, kind) in seen:
                    continue
                seen.add((line, kind))
                found.append(Decision(module, line, kind, tuple(hit)))
    return found


class NothingUnderSrcDecidesOnTheCostTests(unittest.TestCase):
    def test_no_module_reads_a_cost_field_in_a_condition(self) -> None:
        """The gate. Recorded, summarised, formatted -- and never in a branch.

        The failure message names the module, the line and the field, because the useful
        thing to hand whoever trips this is where the decision is, not that there is one.
        """
        offences: list[Decision] = []
        for path, tree in parsed_src():
            offences.extend(
                decisions_reading(tree, path.relative_to(REPO).as_posix(), INERT_NAMES)
            )
        self.assertEqual(
            [],
            offences,
            "a cost field reaches a decision:\n" + "\n".join(str(item) for item in offences),
        )

    def test_the_scan_catches_each_shape_the_ask_named(self) -> None:
        """The gate's own coverage, one synthetic module per shape.

        Without this the gate could be watching the right names through a walker that
        only understands ``if``, and every other shape in :data:`DECIDING_NODES` would be
        an open door with a test in front of it.
        """
        samples = {
            "If": "if row.total_cost_usd:\n    pass\n",
            "IfExp": "x = 1 if row.total_cost_usd else 2\n",
            "While": "while row.total_cost_usd:\n    pass\n",
            "Assert": "assert row.total_cost_usd\n",
            "BoolOp": "x = row.total_cost_usd and other\n",
            "Compare": 'x = row["total_cost_usd"] > 10\n',
            "UnaryOp": "x = not row.total_cost_usd\n",
            "comprehension": "x = [r for r in rows if r.total_cost_usd]\n",
            "sorted-key": "x = sorted(rows, key=lambda r: r.total_cost_usd)\n",
            "max-or-min": "x = max(a.total_cost_usd, b)\n",
        }
        self.assertEqual(sorted(samples), sorted(DECIDING_NODES))
        for kind, source in samples.items():
            with self.subTest(kind=kind):
                found = decisions_reading(ast.parse(source), "sample.py", INERT_NAMES)
                self.assertTrue(found, f"the scan does not see a {kind}")
                self.assertIn(kind, {item.kind for item in found})

    def test_a_field_reached_only_by_a_string_key_is_still_caught(self) -> None:
        """The shape a ledger reader reaches for first, and it names no identifier."""
        source = 'if payload["cost"]["total_cost_usd"] > 10:\n    pass\n'
        self.assertTrue(decisions_reading(ast.parse(source), "sample.py", INERT_NAMES))

    def test_recording_summarising_and_formatting_are_not_decisions(self) -> None:
        """The three the ask permits, so the gate is not simply "never mention it"."""
        for source in (
            'record = {"total_cost_usd": cost.total_cost_usd}\n',
            "total = a.total_cost_usd + b.total_cost_usd\n",
            'line = f"{cost.total_cost_usd}"\n',
        ):
            with self.subTest(source=source.strip()):
                self.assertEqual([], decisions_reading(ast.parse(source), "sample.py", INERT_NAMES))


# ---------------------------------------------------------------------------
# One place to name a field
# ---------------------------------------------------------------------------

#: Modules allowed to spell a cost field's name as a string literal, and why.
#:
#: The rule exists so a new field is added to :data:`~src.call_cost.COST_FIELDS` -- where it
#: inherits the arithmetic, the record, the formatter and the gate -- rather than typed into
#: whichever reader needs it. An exemption is a decision somebody wrote down, and there is
#: exactly one.
LITERAL_EXEMPTIONS: dict[str, str] = {
    "src/terminal_ui.py": (
        "Renders the Codex backend's `turn_completed` panel, which is a different event "
        "with a different vocabulary: it carries `cached_input_tokens`, a key no measured "
        "Claude result event has, and it is not a `{\"type\": \"result\"}` event at all, so "
        "`is_result_event` does not match it and no CallCost is ever built from it. Making "
        "it read `TOKEN_FIELDS` would couple two backends' usage shapes together on the "
        "strength of two names happening to agree."
    ),
}


#: Modules allowed to import the cost *vocabulary* -- the collections, not the values.
#:
#: The field-name scan below catches every direct way to decide on cost, including a string
#: subscript and a `getattr` with a literal. It does not catch laundering the collection
#: through a parameter:
#:
#:     def _greedy(row, fields):
#:         return any(getattr(row, f, 0) > 10.0 for f in fields)
#:
#: which names no field and no collection, and decides on cost the moment a caller passes
#: `COST_FIELDS`. Measured: that shape passes the scan. It is closed from the other end
#: instead -- the collection cannot reach a module that would launder it, because importing
#: it is what this list gates. Satisfiable because nothing outside `src/call_cost.py`
#: imports the collections today; the modules below import the *types* and the helpers, and
#: `CallCost` carries values whose field names the scan already covers.
MAY_IMPORT_THE_COST_VOCABULARY = ("src/call_cost.py",)

COST_COLLECTIONS = ("COST_FIELDS", "TOKEN_FIELDS", "INERT_NAMES", "COUNTER_FIELDS")


#: How a module says "I dispatched a backend call". Any of these and no `call_cost` means
#: the call is spent and uncounted, so the module owes the scope note a mention.
DISPATCH_MARKERS = ("run_prompt", "ReviewDecision(", "OperatorResult(")

#: Modules that dispatch through another module rather than themselves, so the marker
#: appears in them without a call of their own to price.
DISPATCHES_THROUGH_SOMEONE_ELSE = ("src/utils.py", "src/manager.py")


class TheScopeNoteNamesEveryUncountedCallerTests(unittest.TestCase):
    """The total is allowed to be partial. It is not allowed to say it is not.

    A reviewer found `COST_SCOPE_NOTE` claiming to cover "review calls" while
    `ReviewPanel.review_stage` builds its `ReviewDecision` at six sites and sets `call_cost`
    at none, and `src/deliberation.py` and `src/ideation_panel.py` dispatch their own
    prompts the same way. Under `--review-panel` every seat's and the chair's backend call
    was missing from a total that read as complete — an undercount that looks like a
    measurement, which is worse than no number.

    Derived rather than promised: the list comes off the tree, so threading a panel's cost
    through is what takes its name out of the note, and a new unpriced caller fails here.
    """

    def test_every_module_that_dispatches_without_pricing_is_named(self) -> None:
        unpriced: list[str] = []
        for path, _tree in parsed_src():
            relative = path.relative_to(REPO).as_posix()
            if relative in DISPATCHES_THROUGH_SOMEONE_ELSE:
                continue
            text = path.read_text(encoding="utf-8")
            if not any(marker in text for marker in DISPATCH_MARKERS):
                continue
            if "call_cost" in text:
                continue
            unpriced.append(relative)
        missing = [
            name
            for name in unpriced
            if name.rsplit("/", 1)[-1].removesuffix(".py").replace("_", " ") not in COST_SCOPE_NOTE
            and name.rsplit("/", 1)[-1].removesuffix(".py").split("_")[0] not in COST_SCOPE_NOTE
        ]
        self.assertEqual(
            missing,
            [],
            "these dispatch a backend call, report no cost, and are not named in "
            f"COST_SCOPE_NOTE, so the total silently omits them: {missing}",
        )

    def test_the_note_does_not_claim_the_panels(self) -> None:
        """The specific sentence that was false, kept false-able."""
        self.assertIn("review panel", COST_SCOPE_NOTE)
        self.assertIn("spent more than this says", COST_SCOPE_NOTE)


class TheVocabularyCannotBeLaunderedTests(unittest.TestCase):
    """The other end of the field-name scan, and why it is needed.

    Attacked by hand before it existed. A comparison on `row.total_cost_usd`, on
    `row["total_cost_usd"]`, on `getattr(row, "total_cost_usd")`, and on a local copied out
    of any of them all die on the scan. Iterating a collection handed in as an argument does
    not, because the deciding function then names nothing this file knows about. So the
    collection is kept where it cannot be handed anywhere.
    """

    def test_only_call_cost_imports_the_collections(self) -> None:
        offenders: list[str] = []
        for path, tree in parsed_src():
            relative = path.relative_to(REPO).as_posix()
            if relative in MAY_IMPORT_THE_COST_VOCABULARY:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name in COST_COLLECTIONS:
                            offenders.append(f"{relative} imports {alias.name}")
        self.assertEqual(
            offenders,
            [],
            "a module outside the recorder imports the cost vocabulary, which is how a "
            "decision reads cost without naming a field: " + "; ".join(offenders),
        )


class TheFieldsAreNamedInOnePlaceTests(unittest.TestCase):
    def test_the_literals_live_in_src_call_cost_and_one_declared_exception(self) -> None:
        elsewhere: dict[str, set[str]] = {}
        for path, tree in parsed_src():
            relative = path.relative_to(REPO).as_posix()
            if relative == "src/call_cost.py":
                continue
            hit = {
                node.value
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and node.value in set(COST_FIELDS)
            }
            if hit:
                elsewhere[relative] = hit
        self.assertEqual(
            sorted(elsewhere),
            sorted(LITERAL_EXEMPTIONS),
            f"a cost field is spelled outside src/call_cost.py: {elsewhere}",
        )

    def test_every_exemption_carries_a_reason(self) -> None:
        for module, reason in LITERAL_EXEMPTIONS.items():
            with self.subTest(module=module):
                self.assertTrue(REPO.joinpath(module).is_file(), f"{module} does not exist")
                self.assertGreater(len(reason), 120, f"{module}'s exemption is not a reason")

    def test_the_watched_list_covers_every_declared_field(self) -> None:
        for name in COST_FIELDS + COUNTER_FIELDS + (RECORD_FIELD,):
            self.assertIn(name, INERT_NAMES, f"{name} is declared and not watched")

    def test_every_token_field_has_a_label_and_the_sum_names_them_all(self) -> None:
        """A field added to the tuple with no label would print its own identifier."""
        self.assertEqual(sorted(TOKEN_LABELS), sorted(TOKEN_FIELDS))
        for label in TOKEN_LABELS.values():
            self.assertIn(label, TOKEN_SUM_LABEL)

    def test_the_record_carries_exactly_the_declared_fields(self) -> None:
        self.assertEqual(
            [item.name for item in dataclass_fields(CallCost)],
            list(COUNTER_FIELDS) + list(COST_FIELDS),
        )


# ---------------------------------------------------------------------------
# The gate is not vacuous
# ---------------------------------------------------------------------------


class TheGateIsNotVacuousTests(unittest.TestCase):
    """The fields are actually there, in the three places the ask allows.

    Without this the cheapest way to pass every test above is to delete the feature. Each
    check names a live symbol rather than grepping, so a rename moves both halves together.
    """

    def test_they_are_in_the_record(self) -> None:
        row = StageCostMeter(STAGE_01).close().to_dict()
        self.assertIn(RECORD_FIELD, row)
        self.assertEqual(sorted(row[RECORD_FIELD]), sorted(COUNTER_FIELDS + COST_FIELDS))

    def test_they_are_in_the_summary(self) -> None:
        summary = summarize_stage_cost([StageCostMeter(STAGE_01).close().to_dict()])
        self.assertIn(RECORD_FIELD, summary)
        self.assertIn(DOLLAR_FIELD, summary[RECORD_FIELD])

    def test_they_are_in_the_formatter(self) -> None:
        text = format_call_cost(CallCost(1, 1, 1, 2, 3, 4, 5.0))
        self.assertIn("$5.00", text)
        for label in TOKEN_LABELS.values():
            self.assertIn(label, text)

    def test_the_carrier_types_all_have_the_field(self) -> None:
        """The wire the ledger's own note asked for, end to end.

        `src/stage_cost.py` used to say: "Do not derive one from `logs_raw.jsonl` inside
        the supervisor; wire it through `OperatorResult` and `ReviewDecision` first."
        These are those two, plus the third reviewer that runs inside the same visit.
        """
        for carrier in (OperatorResult, ReviewDecision, ValidityReviewOutcome):
            with self.subTest(carrier=carrier.__name__):
                self.assertIn(RECORD_FIELD, {item.name for item in dataclass_fields(carrier)})


# ---------------------------------------------------------------------------
# The supervisor
# ---------------------------------------------------------------------------


def _row(stage: str, *, attempts: int, outcome: str, cost: dict | None = None) -> dict:
    row = {
        "stage": stage,
        "stage_number": int(stage[:2]),
        "visit": 1,
        "started_at": "2026-08-17T00:00:00",
        "wall_seconds": 10.0,
        "attempts": attempts,
        "polish_rounds": 0,
        "operator_invocations": attempts,
        "review_invocations": attempts,
        "auto_skipped": False,
        "outcome": outcome,
        "exhausted": False,
        "attempts_with_a_recorded_cause": attempts,
        "failure_census": {},
        "distinct_failures": 0,
        "max_repeat": 0,
        "max_consecutive_repeat": 0,
        "repeated_failure": False,
        "dominant_failure": None,
        "failures": [],
        "attempt_digests": [],
        "note": "",
    }
    row[RECORD_FIELD] = cost if cost is not None else CallCost().to_dict()
    return row


class TheSupervisorCannotSeeTheCostTests(unittest.TestCase):
    """The component the constraint is aimed at, checked two independent ways."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        runs = Path(self.tmp) / "runs"
        runs.mkdir()
        self.paths = build_run_paths(create_run_root(runs))
        ensure_run_layout(self.paths)

    def _ledger(self, rows: list[dict]) -> None:
        self.paths.stage_cost_ledger.write_text(
            json.dumps({"version": STAGE_COST_LEDGER_VERSION, "rows": rows}), encoding="utf-8"
        )

    def test_the_module_carries_no_cost_name_at_all(self) -> None:
        """Stricter than the syntax gate, and deliberately so.

        Everywhere else a cost field may be recorded, summarised and formatted. Here it
        may not appear, because the supervisor has no reason to touch a number it may not
        act on and every reason not to hold one: it is the one component that reads the
        cost ledger, wakes inside a stage, and can end a visit.
        """
        source = REPO.joinpath("src", "supervisor.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        watched = set(INERT_NAMES)
        # The module docstring is prose about what it must not do and is not code.
        body = [node for node in tree.body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]
        seen: set[str] = set()
        for node in body:
            seen |= watched & names_in(node)
        self.assertEqual(set(), seen, f"src/supervisor.py names {sorted(seen)}")

    def test_it_does_not_import_the_cost_module(self) -> None:
        tree = ast.parse(REPO.joinpath("src", "supervisor.py").read_text(encoding="utf-8"))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        } | {
            alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertNotIn("call_cost", imported)
        self.assertNotIn(".call_cost", imported)

    def test_two_ledgers_that_differ_only_in_cost_get_identical_rulings(self) -> None:
        """The half the syntax cannot reach: a rule that read the cost indirectly.

        The expensive ledger is the one a cost-aware supervisor would act on -- one stage
        holding a five-hundred-dollar bill against two that spent nothing. Every field of
        every ruling has to match the free ledger's, at the attempt boundary and at the
        stage exit.
        """
        stages = [stage.slug for stage in STAGES]
        cheap = [
            _row("01_literature_survey", attempts=2, outcome="approved"),
            _row("02_hypothesis_generation", attempts=2, outcome="approved"),
            _row("03_study_design", attempts=2, outcome="approved"),
        ]
        dear = [
            _row(
                "01_literature_survey",
                attempts=2,
                outcome="approved",
                cost=CallCost(40, 40, 5_117, 27_191_137, 644_146_902, 3_292_425, 574.67).to_dict(),
            ),
            _row("02_hypothesis_generation", attempts=2, outcome="approved"),
            _row("03_study_design", attempts=2, outcome="approved"),
        ]
        # The rows differ in exactly one key, and that key is the cost.
        self.assertEqual(
            [{k: v for k, v in row.items() if k != RECORD_FIELD} for row in cheap],
            [{k: v for k, v in row.items() if k != RECORD_FIELD} for row in dear],
        )
        self.assertNotEqual(cheap[0][RECORD_FIELD], dear[0][RECORD_FIELD])

        def rulings() -> list[Intervention]:
            supervisor = RunSupervisor(stage_slugs=stages, max_auto_skips=3)
            meter = StageCostMeter(STAGES[3])
            meter.note_attempt()
            meter.note_call_cost(CallCost(1, 1, 1, 1, 1, 1, 99.0))
            return [
                supervisor.review_attempt(
                    paths=self.paths,
                    stage_slug="04_implementation",
                    stage_number=4,
                    meter=meter,
                    attempt_no=2,
                    auto_skips_spent=0,
                    deliverable_number=7,
                    per_stage_ceiling=8,
                ),
                supervisor.review_stage_exit(
                    paths=self.paths,
                    stage_slug="04_implementation",
                    admissible_forward=["05_experimentation"],
                ),
            ]

        self._ledger(cheap)
        free = [item.to_dict() for item in rulings()]
        self._ledger(dear)
        billed = [item.to_dict() for item in rulings()]
        for one, two in zip(free, billed):
            one.pop("at"), two.pop("at")
        self.assertEqual(free, billed)

    def test_the_router_rules_the_same_way_on_both_ledgers(self) -> None:
        """The syntax gate has a floor, and this is what sits under it.

        A reviewer built a working escape against the scan: a helper in
        ``src/stage_cost.py`` reading the bill into a local, a second helper filtering a
        comprehension on the first, and three lines in ``StageRouter.choose`` dropping the
        expensive targets out of ``live``. The router shopped on price and every one of
        the eighty syntax tests passed, because the deciding expression named no watched
        field and no watched collection -- the names were spent one call earlier.

        A syntactic gate always has another laundering path; there is no version of
        ``names_in`` that closes the class. What closes it is asking the component for its
        answer twice, over ledgers that differ in nothing but the money. This is the same
        assertion the supervisor already gets, aimed at the other component that could
        want it.
        """
        # Every stage that is a *target* of a move out of the nodes chosen from below,
        # and the whole set is billed. A ledger whose expensive stage no edge points at
        # cannot see a router that drops expensive targets — the first version of this
        # test billed `01_literature_survey` and chose from 04 and 06, which reach it
        # from neither, and the planted escape passed.
        billed_stages = (
            "02_hypothesis_generation",
            "03_study_design",
            "04_implementation",
            "05_experimentation",
            "06_analysis",
            "01_literature_survey",
        )
        expensive = CallCost(40, 40, 5_117, 27_191_137, 644_146_902, 3_292_425, 574.67).to_dict()
        cheap = [_row(slug, attempts=2, outcome="approved") for slug in billed_stages]
        dear = [
            _row(slug, attempts=2, outcome="approved", cost=expensive)
            for slug in billed_stages
        ]
        self.assertNotEqual(cheap[0][RECORD_FIELD], dear[0][RECORD_FIELD])

        def decisions() -> list[dict[str, object]]:
            graph = StageGraph.adaptive()
            out = []
            for slug, number in (("06_analysis", 6), ("07_writing", 7)):
                decision = StageRouter(None, mode="auto").choose(
                    paths=self.paths,
                    stage=next(item for item in STAGES if item.slug == slug),
                    graph=graph,
                    state=GraphState(),
                )
                out.append(
                    {
                        "target": decision.target,
                        "kind": decision.kind,
                        "reason": decision.reason,
                        "default": decision.default_target,
                        "agent_directed": decision.agent_directed,
                        "offered": decision.offered,
                        "blocked": decision.blocked,
                        "refusal": decision.refusal,
                        "at": number,
                    }
                )
            return out

        self._ledger(cheap)
        free = decisions()
        self._ledger(dear)
        billed = decisions()
        self.assertEqual(free, billed)

    def test_the_open_meter_the_supervisor_holds_does_carry_a_cost(self) -> None:
        """So the test above is a real blindness rather than an empty input.

        `review_attempt` is handed the live `StageCostMeter`, and that meter has the
        visit's running bill on it. The supervisor could read it in one attribute access
        and does not.
        """
        meter = StageCostMeter(STAGES[3])
        meter.note_call_cost(CallCost(1, 1, 1, 1, 1, 1, 99.0))
        self.assertEqual(meter.call_cost.total_cost_usd, 99.0)


# ---------------------------------------------------------------------------
# Absent, not zero
# ---------------------------------------------------------------------------


class AbsentIsNotZeroTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        runs = Path(self.tmp) / "runs"
        runs.mkdir()
        self.paths = build_run_paths(create_run_root(runs))
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        initialize_memory(self.paths, "goal")

    def test_the_fake_operator_reports_no_cost_rather_than_a_zero_one(self) -> None:
        """The case the ask names by hand, driven through the real operator.

        `--fake-operator` makes no backend call, so there is nothing to price. Every
        measured field comes back absent and no result event was seen.
        """
        operator = ClaudeOperator(fake_mode=True, output_stream=io.StringIO())
        result = operator.run_stage(STAGE_01, "prompt", self.paths, 1)
        for name in COST_FIELDS:
            with self.subTest(field=name):
                self.assertIsNone(getattr(result.call_cost, name))
        self.assertEqual(result.call_cost.result_events, 0)
        self.assertEqual(result.call_cost.priced_events, 0)

    def test_a_result_event_that_named_no_price_leaves_every_field_absent(self) -> None:
        """The event arrived, the money did not. Both counters say which of those happened.

        Distinct from "no event at all": a backend whose stream carries a result with no
        ``usage`` block and no charge has answered, and the record has to be able to say
        that without inventing a zero for either.
        """
        cost = CallCost.from_result_event({"type": "result"})
        for name in COST_FIELDS:
            with self.subTest(field=name):
                self.assertIsNone(getattr(cost, name))
        self.assertEqual((cost.result_events, cost.priced_events), (1, 0))

    def test_the_token_half_of_the_line_says_not_measured_too(self) -> None:
        """Not just the dollars. A `0` in a token column is a measurement nobody took."""
        line = format_call_cost(CallCost())
        self.assertEqual(line.count(NOT_MEASURED), len(TOKEN_FIELDS) + 2)
        self.assertNotIn(" 0", line)

    def test_a_measured_zero_and_an_unmeasured_one_are_different_records(self) -> None:
        unmeasured = CallCost()
        measured = CallCost.from_result_event({"type": "result", DOLLAR_FIELD: 0.0})
        self.assertNotEqual(unmeasured.to_dict(), measured.to_dict())
        self.assertIsNone(unmeasured.total_cost_usd)
        self.assertEqual(measured.total_cost_usd, 0.0)
        self.assertEqual(measured.priced_events, 1)

    def test_and_they_render_differently(self) -> None:
        """The distinction has to survive the formatter or it is not a distinction."""
        unmeasured = format_call_cost(CallCost())
        measured = format_call_cost(CallCost.from_result_event({"type": "result", DOLLAR_FIELD: 0.0}))
        self.assertIn(NOT_MEASURED, unmeasured)
        self.assertNotIn("$0.00", unmeasured)
        self.assertIn("$0.00", measured)

    def test_an_operator_that_never_heard_of_the_field_is_unmeasured(self) -> None:
        """A stub, a third-party backend, a `MagicMock` -- all absent, none zero."""
        for stand_in in (MagicMock().call_cost, None, 0, 0.0, "free", {}):
            with self.subTest(stand_in=type(stand_in).__name__):
                self.assertEqual(call_cost_of(stand_in), CallCost())

    def test_a_bypassed_stage_is_unmeasured_rather_than_free(self) -> None:
        """Nothing was dispatched, so nothing answered. `$0.00` would be a derived claim."""
        row = bypassed_row(STAGE_01, note="stepped over").to_dict()
        self.assertEqual(row["operator_invocations"], 0)
        self.assertIsNone(row[RECORD_FIELD][DOLLAR_FIELD])
        self.assertIn(NOT_MEASURED, format_run_cost_report([row]))

    def test_an_unmeasured_report_adds_nothing_and_does_not_become_a_zero(self) -> None:
        priced = CallCost.from_result_event(
            {"type": "result", DOLLAR_FIELD: 3.5, "usage": {"output_tokens": 7}}
        )
        total = CallCost() + priced + CallCost()
        self.assertEqual(total.total_cost_usd, 3.5)
        self.assertEqual(total.output_tokens, 7)
        # The fields nobody reported stay absent even after three additions.
        self.assertIsNone(total.input_tokens)

    def test_a_ledger_written_before_this_field_existed_reads_as_unmeasured(self) -> None:
        """A version-1 row has no such key, and a missing key is not a free stage."""
        self.assertEqual(CallCost.from_mapping(None), CallCost())
        self.assertEqual(run_call_cost([{"stage": "01_literature_survey"}]), CallCost())
        self.assertGreater(STAGE_COST_LEDGER_VERSION, 1)

    def test_a_run_with_no_rows_says_so_rather_than_printing_a_bill_of_zero(self) -> None:
        self.assertEqual(format_run_cost_report([]), NO_COST_RECORDED)
        self.assertNotIn("$0.00", NO_COST_RECORDED)


# ---------------------------------------------------------------------------
# The two traps in the data
# ---------------------------------------------------------------------------


class TheTrapsInTheDataTests(unittest.TestCase):
    """Both traps, as arithmetic on this module rather than as prose above it."""

    def test_the_dollar_figure_sums_and_is_never_maximised(self) -> None:
        """Trap one. `total_cost_usd` is per call; three calls of $1 cost $3.

        A reader that took the last value, or the largest, would report $1. Both readings
        are what a *cumulative* field would deserve and both are wrong here; the census
        prints the wrong one beside the right one on the measured runs.
        """
        events = [{"type": "result", DOLLAR_FIELD: value} for value in (1.0, 0.25, 1.0)]
        total = CallCost()
        for event in events:
            total = total + CallCost.from_result_event(event)
        self.assertEqual(total.total_cost_usd, 2.25)
        self.assertEqual(total.result_events, 3)

    def test_a_charge_that_falls_between_calls_is_still_added(self) -> None:
        """The observation that settles trap one, in miniature.

        The second call of a session charging less than the first is what rules out
        reading the field as a running total, and it must not confuse the addition.
        """
        first = CallCost.from_result_event({"type": "result", DOLLAR_FIELD: 21.9295})
        second = CallCost.from_result_event({"type": "result", DOLLAR_FIELD: 0.0431})
        self.assertLess(second.total_cost_usd, first.total_cost_usd)
        self.assertAlmostEqual((first + second).total_cost_usd, 21.9726, places=4)

    def test_no_single_token_figure_is_published_without_naming_its_addends(self) -> None:
        """Trap two. `input_tokens` alone is the uncached remainder.

        The shape of the measured runs, at scale: a few thousand uncached input tokens
        against hundreds of millions of cache reads. Any "tokens used" figure that reads
        the first is wrong by five orders of magnitude, so the only total this module
        produces is named for the sum and printed beside its parts.
        """
        cost = CallCost.from_result_event(
            {
                "type": "result",
                "usage": {
                    "input_tokens": 5_117,
                    "cache_creation_input_tokens": 27_191_137,
                    "cache_read_input_tokens": 644_146_902,
                    "output_tokens": 3_292_425,
                },
            }
        )
        self.assertEqual(billed_tokens(cost), 674_635_581)
        self.assertGreater(billed_tokens(cost) / cost.input_tokens, 100_000)
        line = format_call_cost(cost)
        self.assertIn(TOKEN_SUM_LABEL, line)
        for label in TOKEN_LABELS.values():
            self.assertIn(label, line)

    def test_the_four_fields_are_carried_separately_and_none_is_dropped(self) -> None:
        cost = CallCost.from_result_event(
            {"type": "result", "usage": {name: 1 for name in TOKEN_FIELDS}}
        )
        for name in TOKEN_FIELDS:
            self.assertEqual(getattr(cost, name), 1, name)
        self.assertEqual(billed_tokens(cost), len(TOKEN_FIELDS))

    def test_a_non_result_event_is_not_a_call(self) -> None:
        for payload in ({"type": "assistant"}, {"type": "system"}, {}, "text", None):
            self.assertFalse(is_result_event(payload), payload)

    def test_a_codex_turn_is_not_read_as_a_priced_claude_result(self) -> None:
        """The other backend, whose usage block is a different vocabulary.

        `src/terminal_ui.py` renders `cached_input_tokens` from a `turn_completed` event.
        It is not a result event, so nothing is built from it, and this is the exemption
        in `LITERAL_EXEMPTIONS` checked as behaviour rather than taken on trust.
        """
        turn = {
            "type": "turn_completed",
            "usage": {"input_tokens": 10, "cached_input_tokens": 90, "output_tokens": 5},
        }
        self.assertFalse(is_result_event(turn))

    def test_a_boolean_is_not_a_token_count(self) -> None:
        """`True` is an `int` in Python, and a usage block carrying one would add 1."""
        cost = CallCost.from_result_event(
            {"type": "result", DOLLAR_FIELD: True, "usage": {"output_tokens": True}}
        )
        self.assertIsNone(cost.output_tokens)
        self.assertIsNone(cost.total_cost_usd)
        self.assertEqual(cost.priced_events, 0)

    def test_the_coverage_line_never_divides_events_by_dispatches(self) -> None:
        """Measured: the two counts differ, so a ratio of them would look like a bug."""
        line = describe_coverage(CallCost(99, 99))
        self.assertIn("99 of 99", line)
        self.assertNotIn("dispatch", line)


# ---------------------------------------------------------------------------
# Every dispatch site is classified
# ---------------------------------------------------------------------------


class Dispatch(NamedTuple):
    #: ``module::function`` -- never a line number, which rots on the next edit above it.
    where: str
    charged: bool
    why: str


#: Every place under ``src/`` that launches a backend through the streaming operator, and
#: whether its cost reaches a stage-visit row.
#:
#: Derived on one side and declared on the other:
#: :meth:`EveryBackendDispatchIsClassifiedTests.test_the_declared_sites_are_the_ones_in_the_tree`
#: parses the tree for the call sites, so a new one fails this file rather than quietly
#: escaping the total. The uncharged ones are uncharged for a structural reason, not an
#: oversight, and :data:`~src.stage_cost.COST_SCOPE_NOTE` says so beside every total the
#: run prints.
DISPATCH_SITES: tuple[Dispatch, ...] = (
    Dispatch(
        "src/operator.py::_run_real",
        True,
        "The stage run itself. Its cost rides out on `OperatorResult.call_cost` and the "
        "manager charges it beside `_note_operator_call`.",
    ),
    Dispatch(
        "src/operator.py::repair_stage_summary",
        True,
        "The summary-repair pass, on the same return type and charged at both of the "
        "manager's two call sites for it.",
    ),
    Dispatch(
        "src/approval_agent.py::run_prompt",
        True,
        "The approval gate, through `ReviewDecision.call_cost`. The same method serves the "
        "review, deliberation and ideation panels, whose fan-out is below the boundary "
        "`review_invocations` counts; they pass no `CostTally` and charge nothing.",
    ),
    Dispatch(
        "src/validity_review.py::review",
        True,
        "The adversarial pass, through `ValidityReviewOutcome.call_cost`. It runs inside "
        "the visit, right after the stage is approved, so a meter is open to charge.",
    ),
    Dispatch(
        "src/router.py::_ask",
        False,
        "The routing agent picks the next edge at a stage *exit*, after "
        "`ResearchManager._run_stage` has closed the meter in its `finally`. There is no "
        "open visit to charge it to, and inventing one would put a call made between two "
        "stages inside one of them.",
    ),
    Dispatch(
        "src/router.py::_reask",
        False,
        "The routing agent's one re-ask when its first answer could not be read. Same "
        "boundary, same reason, and it is listed separately because a call site nobody "
        "classified and a call site somebody excused look identical from outside.",
    ),
    Dispatch(
        "src/rcb.py::_attempt",
        False,
        "The benchmark front end's own operator loop, which does not run the stage graph "
        "and opens no stage-cost meter at all.",
    ),
)


class EveryBackendDispatchIsClassifiedTests(unittest.TestCase):
    def _sites_in_the_tree(self) -> set[str]:
        found: set[str] = set()
        for path, tree in parsed_src():
            relative = path.relative_to(REPO).as_posix()
            stack: list[str] = []

            class Walk(ast.NodeVisitor):
                def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                    stack.append(node.name)
                    self.generic_visit(node)
                    stack.pop()

                visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

                def visit_Call(self, node: ast.Call) -> None:
                    if (
                        isinstance(node.func, ast.Attribute)
                        and node.func.attr == "_run_streaming_command"
                    ):
                        found.add(f"{relative}::{'.'.join(stack)}")
                    self.generic_visit(node)

            Walk().visit(tree)
        return found

    def test_the_declared_sites_are_the_ones_in_the_tree(self) -> None:
        self.assertEqual(
            sorted(item.where for item in DISPATCH_SITES), sorted(self._sites_in_the_tree())
        )

    def test_every_site_carries_a_reason(self) -> None:
        for site in DISPATCH_SITES:
            with self.subTest(site=site.where):
                self.assertGreater(len(site.why), 80, f"{site.where} has no reason")

    def test_the_scope_note_warns_about_the_uncharged_ones(self) -> None:
        """The total says what it covers, because a bill that does not is read as complete."""
        self.assertTrue(any(not site.charged for site in DISPATCH_SITES))
        self.assertIn("routing", COST_SCOPE_NOTE.lower())
        self.assertIn(COST_SCOPE_NOTE, format_run_cost_report([bypassed_row(STAGE_01, note="x").to_dict()]))

    def test_the_split_the_ledger_module_states_in_prose_is_the_split_in_the_table(self) -> None:
        """A count written in a docstring, pinned to the thing it counts.

        `src/stage_cost.py` tells a reader how many backend dispatches are outside the
        total. That sentence is prose and prose has no compiler, so it is checked here
        against :data:`DISPATCH_SITES`, which is itself checked against the tree.
        """
        uncharged = [site for site in DISPATCH_SITES if not site.charged]
        self.assertEqual(len(uncharged), 3)
        self.assertEqual(len(DISPATCH_SITES) - len(uncharged), 4)
        source = REPO.joinpath("src", "stage_cost.py").read_text(encoding="utf-8")
        self.assertIn(
            f"{spelled(len(uncharged)).capitalize()} other\nplaces in ``src/`` reach the backend",
            source,
        )


# ---------------------------------------------------------------------------
# The wire, end to end
# ---------------------------------------------------------------------------


class TheCostReachesTheLedgerTests(ManagerLoopFixture, unittest.TestCase):
    """The stream event goes in one end and comes out on a ledger row.

    On the shared apparatus rather than a second copy of it: ``ManagerLoopFixture`` is
    already reused by ``tests/test_run_supervisor.py`` for exactly this -- a real
    ``ResearchManager`` over a real run root with the operator stubbed -- and a second
    hundred lines of draft fixture is a second thing to keep in step.
    """

    def test_the_row_carries_what_the_operator_and_the_reviewer_reported(self) -> None:
        """Both halves of a visit's bill, added, on the row the ledger writes.

        $2.50 from the stage run and $0.75 from the approval gate is $3.25 for the visit.
        The two token figures add the same way, and ``result_events`` says the total came
        from two priced calls rather than from one call twice.
        """
        draft = self._valid_draft(STAGE_01)
        self.operator.run_stage = MagicMock(
            return_value=OperatorResult(
                success=True,
                exit_code=0,
                stdout="",
                stderr="",
                stage_file_path=draft,
                session_id="session-1",
                call_cost=CallCost(1, 1, 10, 20, 30, 40, 2.50),
            )
        )
        self.manager.reviewer = _StubReviewer(
            [
                ReviewDecision(
                    choice="5",
                    decision_token="approve",
                    reason="fine",
                    call_cost=CallCost(1, 1, 1, 2, 3, 4, 0.75),
                )
            ]
        )
        self.manager._run_stage(self.paths, STAGE_01)

        row = read_stage_cost_ledger(self.paths)[0]
        self.assertAlmostEqual(row[RECORD_FIELD][DOLLAR_FIELD], 3.25)
        self.assertEqual(row[RECORD_FIELD]["input_tokens"], 11)
        self.assertEqual(row[RECORD_FIELD]["output_tokens"], 44)
        self.assertEqual(row[RECORD_FIELD]["result_events"], 2)
        self.assertEqual(row[RECORD_FIELD]["priced_events"], 2)

    def test_an_operator_that_reports_nothing_leaves_the_row_unmeasured(self) -> None:
        """The stub every other test in this repository uses, and it must not read $0.00.

        Two operator calls and a review are dispatched and counted; not one of them says
        what it cost, so the row's dollar figure is absent and the run report says so
        rather than printing a bill of zero.
        """
        self._stub_operator(self._valid_draft(STAGE_01))
        self.manager.reviewer = _StubReviewer(
            [ReviewDecision(choice="5", decision_token="approve", reason="fine")]
        )
        self.manager._run_stage(self.paths, STAGE_01)

        rows = read_stage_cost_ledger(self.paths)
        self.assertIsNone(rows[0][RECORD_FIELD][DOLLAR_FIELD])
        self.assertGreater(rows[0]["operator_invocations"], 0)
        self.assertIn(NOT_MEASURED, format_run_cost_report(rows))

    def test_a_second_visit_is_charged_separately(self) -> None:
        """A backward edge re-runs a stage and the second run is a separate purchase.

        The row is per *visit*, so two visits are two bills rather than one running total,
        and the run's own figure is their sum.
        """
        draft = self._valid_draft(STAGE_01)
        for price in (1.25, 4.00):
            self.operator.run_stage = MagicMock(
                return_value=OperatorResult(
                    success=True, exit_code=0, stdout="", stderr="",
                    stage_file_path=draft, session_id="session-1",
                    call_cost=CallCost(1, 1, None, None, None, None, price),
                )
            )
            self.manager.reviewer = _StubReviewer(
                [ReviewDecision(choice="5", decision_token="approve", reason="fine")]
            )
            self.manager._run_stage(self.paths, STAGE_01)

        rows = read_stage_cost_ledger(self.paths)
        self.assertEqual([row["visit"] for row in rows], [1, 2])
        self.assertAlmostEqual(rows[0][RECORD_FIELD][DOLLAR_FIELD], 1.25)
        self.assertAlmostEqual(rows[1][RECORD_FIELD][DOLLAR_FIELD], 4.00)
        self.assertAlmostEqual(run_call_cost(rows).total_cost_usd, 5.25)

    def test_the_stream_parser_prices_a_result_event(self) -> None:
        """``stream_meta`` is the channel, and this is the one hop that has to hold."""
        meta = {"raw_line_count": 3, RECORD_FIELD: CallCost(1, 1, 1, 1, 1, 1, 4.5).to_dict()}
        self.assertEqual(cost_from_stream_meta(meta).total_cost_usd, 4.5)
        self.assertEqual(cost_from_stream_meta({}), CallCost())
        self.assertEqual(cost_from_stream_meta(None), CallCost())

    def test_the_reviewers_sink_sums_its_calls(self) -> None:
        """A review and its verdict-only re-ask are two calls and one charge."""
        tally = CostTally()
        tally.add(CallCost(1, 1, None, None, None, None, 1.0))
        tally.add(CallCost(1, 1, None, None, None, None, 2.0))
        self.assertEqual(tally.total.total_cost_usd, 3.0)
        self.assertEqual(tally.total.result_events, 2)

    def test_the_adversarial_pass_is_charged_to_the_visit_it_ran_inside(self) -> None:
        """The third reviewer, which runs after the stage is approved and before it closes.

        It is a backend launch the manager dispatched inside the visit, so its spend is the
        visit's. ``_attempt_validity_review`` is where both of the two attempts go through,
        so charging there covers the re-ask as well as the first pass.
        """
        from src.validity_review import COMPLETED

        meter = StageCostMeter(STAGE_01)
        self.manager._stage_cost = meter
        self.addCleanup(setattr, self.manager, "_stage_cost", None)

        class _Pass:
            def review(self, **_kwargs) -> ValidityReviewOutcome:
                return ValidityReviewOutcome(
                    COMPLETED, [], CallCost(1, 1, None, None, None, None, 6.5)
                )

        outcome = self.manager._attempt_validity_review(
            self.paths, STAGE_01, "# Stage 01", _Pass(), attempt_no=1
        )
        self.assertEqual(outcome.completion, COMPLETED)
        self.assertEqual(meter.call_cost.total_cost_usd, 6.5)

    def test_a_pass_that_raised_does_not_lose_the_visit_or_invent_a_price(self) -> None:
        """The `except` path returns an outcome rather than nothing, and it is unmeasured."""
        meter = StageCostMeter(STAGE_01)
        self.manager._stage_cost = meter
        self.addCleanup(setattr, self.manager, "_stage_cost", None)

        class _Broken:
            def review(self, **_kwargs) -> ValidityReviewOutcome:
                raise RuntimeError("the critic died")

        outcome = self.manager._attempt_validity_review(
            self.paths, STAGE_01, "# Stage 01", _Broken(), attempt_no=1
        )
        self.assertTrue(outcome.degraded)
        self.assertIsNone(meter.call_cost.total_cost_usd)

    def test_both_ways_a_run_ends_report_what_it_cost(self) -> None:
        """Derived from the syntax, because the two exits are far apart in one long file.

        The clean exit and the abort branch. A cancelled run spent everything it spent and
        produced less for it, so leaving the report on the happy path only would drop it
        from exactly the run whose bill is worth reading.
        """
        tree = ast.parse(REPO.joinpath("src", "manager.py").read_text(encoding="utf-8"))
        stack: list[str] = []
        callers: set[str] = set()

        class Walk(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            def visit_Call(self, node: ast.Call) -> None:
                if isinstance(node.func, ast.Attribute) and node.func.attr == "_report_run_cost":
                    callers.add(stack[-1])
                self.generic_visit(node)

        Walk().visit(tree)
        self.assertEqual(callers, {"_walk_stages", "_complete_run"})
        # And it goes wherever the log summary already goes, so neither exit can keep one
        # and lose the other.
        logged: set[str] = set()
        stack.clear()

        class LogWalk(Walk):
            def visit_Call(self, node: ast.Call) -> None:
                if isinstance(node.func, ast.Attribute) and node.func.attr == "_log_stage_cost_summary":
                    logged.add(stack[-1])
                self.generic_visit(node)

        LogWalk().visit(tree)
        self.assertEqual(callers, logged)


# ---------------------------------------------------------------------------
# The instrument the numbers came from
# ---------------------------------------------------------------------------


class TheCensusIsRunnableTests(unittest.TestCase):
    """``tools/log_cost_census.py``, exercised on a log this file writes.

    The measured runs live on a filesystem CI has never seen, so what a test can hold is
    the instrument's arithmetic rather than its output on them. The fixture below is a
    miniature of the shape that produced the two traps: one session id charged three times,
    the second charge lower than the first, and a usage block whose cache reads dwarf its
    uncached input.
    """

    def _log(self, events: list[dict]) -> Path:
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        path = Path(tmp) / "logs_raw.jsonl"
        path.write_text(
            "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
        )
        return path

    def test_it_sums_per_call_and_prints_the_wrong_reading_beside_it(self) -> None:
        log = self._log(
            [
                {"_meta": {"mode": "real_start"}},
                {"type": "result", "session_id": "s1", DOLLAR_FIELD: 10.0},
                {"type": "result", "session_id": "s1", DOLLAR_FIELD: 1.0},
                {"type": "result", "session_id": "s1", DOLLAR_FIELD: 4.0},
            ]
        )
        census = census_of("fixture", log)
        self.assertEqual(census.total.total_cost_usd, 15.0)
        # The cumulative reading takes the last value of each session, and is wrong.
        self.assertEqual(census.last_per_session_usd, 4.0)
        self.assertEqual(census.sessions, 1)
        self.assertEqual(census.dispatch_records, 1)

    def test_one_descending_charge_is_what_rules_the_cumulative_reading_out(self) -> None:
        self.assertEqual(session_monotonicity([("s1", 10.0), ("s1", 1.0), ("s1", 4.0)]), 1)
        # Two sessions interleaved: each is judged against its own previous charge.
        self.assertEqual(
            session_monotonicity([("s1", 1.0), ("s2", 9.0), ("s1", 2.0), ("s2", 3.0)]), 1
        )
        # A genuinely cumulative field would produce none.
        self.assertEqual(session_monotonicity([("s1", 1.0), ("s1", 2.0), ("s1", 3.0)]), 0)

    def test_an_unreadable_line_costs_one_line_and_not_the_rest_of_the_file(self) -> None:
        """The bound on the damage, which is what the binary read buys.

        A raw NUL inside a JSON string is not valid JSON, and `json.loads` refuses it. The
        census skips that line and keeps counting, so one corrupt event costs one event
        rather than every event after it. Measured: the 08-14 run's `logs_raw.jsonl` has
        8,455 lines and none of them needs this -- the defence is a bound, not a repair,
        and the tool's header says so rather than implying a fault it has never met.
        """
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        path = Path(tmp) / "logs_raw.jsonl"
        path.write_bytes(
            b'{"type": "result", "total_cost_usd": 1.0}\n'
            b'{"type": "result", "note": "' + b"\x00" + b'", "total_cost_usd": 2.0}\n'
            b'{"type": "result", "total_cost_usd": 3.0}\n'
        )
        census = census_of("fixture", path)
        self.assertEqual(census.total.result_events, 2)
        self.assertEqual(census.total.total_cost_usd, 4.0)

    def test_the_population_line_refuses_to_compare_an_unrecorded_population(self) -> None:
        line = population_matches([census_of("somebody_elses_run", self._log([]))])
        self.assertIn("not the recorded one", line)
        for name in MEASURED_RUNS:
            self.assertIn(name, line)

    def test_it_says_DRIFTED_rather_than_printing_a_different_number(self) -> None:
        """The only mechanism by which a docstring figure can stop being true out loud."""
        wrong = [
            Census(
                run=name,
                total=CallCost(1, 1, 1, 1, 1, 1, 1.0),
                dispatch_records=1,
                sessions=1,
                descending_steps=0,
                last_per_session_usd=1.0,
            )
            for name in MEASURED_RUNS
        ]
        self.assertIn("DRIFTED", population_matches(wrong))

    def test_the_recorded_table_covers_the_recorded_population(self) -> None:
        self.assertEqual(sorted(RECORDED), sorted(MEASURED_RUNS))

    def test_the_census_reads_the_shipped_parser_rather_than_a_copy(self) -> None:
        """An instrument that reimplements what it measures measures something else."""
        source = REPO.joinpath("tools", "log_cost_census.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "src.call_cost"
            for alias in node.names
        }
        self.assertIn("CallCost", imported)
        self.assertIn("is_result_event", imported)
        # And it does not re-spell the field names it is reporting on.
        constants = {
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertEqual(set(), constants & set(TOKEN_FIELDS))

    def test_the_recorded_dispatch_records_differ_from_the_result_events(self) -> None:
        """Why the coverage line never divides one by the other.

        Two of the three measured runs saw more result events than dispatch records, which
        is a fact about the stream rather than an accounting error, and it is recorded here
        so a future reader who "fixes" the ratio meets it.
        """
        differing = [
            name for name, row in RECORDED.items() if row.result_events != row.dispatch_records
        ]
        self.assertEqual(len(differing), 2, differing)


# ---------------------------------------------------------------------------
# The operator layer prices its own calls
# ---------------------------------------------------------------------------


class _FakeStdout:
    """A stream of lines, with a hook that fires once the last one has been delivered.

    The hook is what lets a test put the stage timeout *after* the backend answered, which
    is the branch a stage killed at four hours actually takes.
    """

    def __init__(self, lines: list[str]) -> None:
        self._lines = iter(lines)
        self.on_exhausted = lambda: None

    def __iter__(self) -> "_FakeStdout":
        return self

    def __next__(self) -> str:
        try:
            return next(self._lines)
        except StopIteration:
            self.on_exhausted()
            raise

    def close(self) -> None:
        return None


class _FakeProcess:
    """Enough of ``subprocess.Popen`` for ``_run_streaming_command`` to read a stream."""

    def __init__(self, lines: list[str]) -> None:
        self.stdout = _FakeStdout(lines)
        self.stdin = None

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def terminate(self) -> None:
        return None

    def kill(self) -> None:
        return None


RESUME_FAILURE = "No conversation found with session id abc"


class TheOperatorLayerPricesItsOwnCallsTests(unittest.TestCase):
    """The first hop: a ``result`` event on the wire becomes a number on the return type.

    Everything above this file tests the arithmetic on a ``CallCost`` somebody handed it.
    These drive the parser over a stream and the return types over the parser, because a
    correct ``CallCost`` that nothing fills is the defect one level up.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.paths = build_run_paths(Path(self.tmp) / "run")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        initialize_memory(self.paths, "goal")
        self.operator = ClaudeOperator(fake_mode=False, output_stream=io.StringIO())

    @staticmethod
    def _result_line(price: float, **usage: int) -> str:
        return json.dumps({"type": "result", DOLLAR_FIELD: price, "usage": usage}) + "\n"

    def _stream(self, lines: list[str]) -> dict:
        with patch("src.operator.subprocess.Popen", return_value=_FakeProcess(lines)):
            *_rest, meta = self.operator._run_streaming_command(
                command=["claude"],
                cwd=self.paths.run_root,
                stage=STAGE_01,
                attempt_no=1,
                paths=self.paths,
                mode="real_start",
            )
        return meta

    def test_the_parser_prices_the_result_events_in_a_stream(self) -> None:
        meta = self._stream(
            [
                json.dumps({"type": "assistant", "message": {}}) + "\n",
                self._result_line(1.5, input_tokens=3, output_tokens=9),
                self._result_line(2.5, input_tokens=4, output_tokens=1),
            ]
        )
        cost = cost_from_stream_meta(meta)
        self.assertEqual(cost.total_cost_usd, 4.0)
        self.assertEqual(cost.input_tokens, 7)
        self.assertEqual(cost.output_tokens, 10)
        # Two result events out of three lines: the assistant event is not a call.
        self.assertEqual(cost.result_events, 2)

    def test_a_stream_that_reported_nothing_leaves_the_meta_unmeasured(self) -> None:
        meta = self._stream([json.dumps({"type": "assistant", "message": {}}) + "\n"])
        self.assertEqual(cost_from_stream_meta(meta), CallCost())

    def test_a_stage_that_timed_out_is_still_charged_for_what_it_burned(self) -> None:
        """Four hours of tokens and a kill is the invocation whose bill matters most.

        The timer fires *after* the stream has delivered its result, which is the shape of
        the case worth covering: a stage that was answered and then killed, rather than one
        killed before it said anything. `_run_streaming_command` returns down a different
        branch there, and an earlier draft of the timeout return carried no cost at all.
        """
        fired: list = []

        class LateTimer:
            def __init__(self, timeout, fn) -> None:
                fired.append(fn)
                self.daemon = False

            def start(self) -> None:
                return None

            def cancel(self) -> None:
                return None

        lines = [self._result_line(7.25, output_tokens=11)]
        process = _FakeProcess(lines)
        process.stdout.on_exhausted = lambda: fired[0]()
        with patch("src.operator.subprocess.Popen", return_value=process), patch(
            "src.operator.threading.Timer", LateTimer
        ):
            exit_code, _out, _err, _session, meta = self.operator._run_streaming_command(
                command=["claude"],
                cwd=self.paths.run_root,
                stage=STAGE_01,
                attempt_no=1,
                paths=self.paths,
                mode="real_start",
            )
        self.assertEqual(exit_code, -1)
        self.assertTrue(meta["timed_out"])
        self.assertEqual(cost_from_stream_meta(meta).total_cost_usd, 7.25)

    def _stub_stream(self, prices: list[float], *, resume_failure_first: bool = False):
        """Return a ``_run_streaming_command`` stand-in that charges *prices* in turn."""
        seen = {"calls": 0}

        def fake_stream(**kwargs):
            index = seen["calls"]
            seen["calls"] += 1
            meta = {
                "raw_line_count": 1,
                "non_json_line_count": 0,
                "malformed_json_count": 0,
                RECORD_FIELD: CallCost(
                    1, 1, None, None, None, None, prices[index]
                ).to_dict(),
            }
            if resume_failure_first and index == 0:
                return (1, RESUME_FAILURE, "", None, meta)
            write_text(self.paths.stage_tmp_file(STAGE_01), "# Stage 01: Literature Survey\n")
            return (0, "done", "", "session-observed", meta)

        return fake_stream, seen

    def test_the_stage_run_carries_its_price_out_on_the_result(self) -> None:
        fake_stream, _seen = self._stub_stream([3.5])
        with patch("src.operator.shutil.which", return_value="/usr/bin/claude"), patch.object(
            self.operator, "_run_streaming_command", side_effect=fake_stream
        ):
            result = self.operator._run_real(
                stage=STAGE_01, prompt="p", paths=self.paths, attempt_no=1
            )
        self.assertTrue(result.success)
        self.assertEqual(result.call_cost.total_cost_usd, 3.5)

    def test_a_resume_that_failed_and_was_retried_is_charged_for_both_calls(self) -> None:
        """The run paid twice, so the row says twice.

        `_run_real` rebinds ``stream_meta`` when it takes the fallback, so a reader of the
        last one would charge $4.00 for a visit that cost $5.00 and lose whatever the
        broken resume had already burned before it failed.
        """
        fake_stream, seen = self._stub_stream([1.0, 4.0], resume_failure_first=True)
        with patch("src.operator.shutil.which", return_value="/usr/bin/claude"), patch.object(
            self.operator, "_run_streaming_command", side_effect=fake_stream
        ):
            result = self.operator._run_real(
                stage=STAGE_01, prompt="p", paths=self.paths, attempt_no=1, continue_session=True
            )
        self.assertEqual(seen["calls"], 2, "the fallback did not run")
        self.assertEqual(result.call_cost.total_cost_usd, 5.0)
        self.assertEqual(result.call_cost.result_events, 2)

    def test_the_price_is_on_the_per_attempt_record_too(self) -> None:
        """``operator_state/`` keeps it per call, which is what an audit reads."""
        fake_stream, _seen = self._stub_stream([2.0])
        with patch("src.operator.shutil.which", return_value="/usr/bin/claude"), patch.object(
            self.operator, "_run_streaming_command", side_effect=fake_stream
        ):
            self.operator._run_real(stage=STAGE_01, prompt="p", paths=self.paths, attempt_no=1)
        state = json.loads(
            self.paths.stage_attempt_state_file(STAGE_01, 1).read_text(encoding="utf-8")
        )
        self.assertEqual(state[RECORD_FIELD][DOLLAR_FIELD], 2.0)


class TheReviewerCarriesItsOwnPriceTests(unittest.TestCase):
    """The second hop: what the approval gate spent reaches ``ReviewDecision``."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.paths = build_run_paths(Path(self.tmp) / "run")
        ensure_run_layout(self.paths)
        with patch("src.approval_agent.ClaudeOperator"):
            self.reviewer = AutomatedReviewer("claude", model="opus", unattended=True)

    def _stub_backend(self, replies: list[tuple[int, str]], prices: list[float]) -> None:
        seen = {"calls": 0}

        def fake_stream(**kwargs):
            index = seen["calls"]
            seen["calls"] += 1
            exit_code, text = replies[index]
            return (
                exit_code,
                text,
                "",
                "session",
                {RECORD_FIELD: CallCost(1, 1, None, None, None, None, prices[index]).to_dict()},
            )

        self.reviewer._operator._prepare_invocation = MagicMock(
            return_value=(["claude"], self.paths.run_root, None)
        )
        self.reviewer._operator._run_streaming_command = MagicMock(side_effect=fake_stream)
        self.seen = seen

    def test_run_prompt_fills_the_sink_it_is_handed(self) -> None:
        self._stub_backend([(0, '{"decision":"approve","reason":"fine"}')], [1.25])
        spend = CostTally()
        self.reviewer.run_prompt(
            paths=self.paths, stage=STAGE_01, attempt_no=1, prompt="p", label="review", spend=spend
        )
        self.assertEqual(spend.total.total_cost_usd, 1.25)

    def test_a_caller_that_passes_no_sink_is_unaffected(self) -> None:
        """The three panels call this and charge nothing; they must still get a verdict."""
        self._stub_backend([(0, "text")], [9.0])
        exit_code, stdout_text, _stderr = self.reviewer.run_prompt(
            paths=self.paths, stage=STAGE_01, attempt_no=1, prompt="p", label="panel_x"
        )
        self.assertEqual((exit_code, stdout_text), (0, "text"))

    def test_the_verdict_carries_what_the_review_cost(self) -> None:
        self._stub_backend([(0, '{"decision":"approve","reason":"good enough"}')], [2.75])
        with patch.object(self.reviewer, "_build_review_prompt", return_value="p"):
            decision = self.reviewer.review_stage(
                paths=self.paths, stage=STAGE_01, attempt_no=1,
                stage_markdown="# Stage 01: Literature Survey", suggestions=["a", "b", "c"],
            )
        self.assertEqual(decision.decision_token, "approve")
        self.assertEqual(decision.call_cost.total_cost_usd, 2.75)

    def test_an_unreadable_verdict_charges_the_re_ask_as_well(self) -> None:
        """Two calls, one verdict, one bill. The re-ask is money the run spent."""
        self._stub_backend(
            [(0, "I looked at it and I have thoughts."), (0, '{"decision":"approve","reason":"ok"}')],
            [1.0, 0.5],
        )
        with patch.object(self.reviewer, "_build_review_prompt", return_value="p"):
            decision = self.reviewer.review_stage(
                paths=self.paths, stage=STAGE_01, attempt_no=1,
                stage_markdown="# Stage 01: Literature Survey", suggestions=["a", "b", "c"],
            )
        self.assertEqual(self.seen["calls"], 2)
        self.assertEqual(decision.call_cost.total_cost_usd, 1.5)

    def test_a_crashed_reviewer_is_still_charged_for_the_call_it_made(self) -> None:
        """A backend that answered nothing spent what it spent getting there."""
        self._stub_backend([(1, "")], [0.4])
        with patch.object(self.reviewer, "_build_review_prompt", return_value="p"):
            decision = self.reviewer.review_stage(
                paths=self.paths, stage=STAGE_01, attempt_no=1,
                stage_markdown="# Stage 01: Literature Survey", suggestions=["a", "b", "c"],
            )
        self.assertEqual(decision.choice, "4")
        self.assertEqual(decision.call_cost.total_cost_usd, 0.4)

    def test_a_fake_reviewer_is_unmeasured_rather_than_free(self) -> None:
        with patch("src.approval_agent.ClaudeOperator"):
            fake = AutomatedReviewer("claude", model="opus", fake_mode=True)
        decision = fake.review_stage(
            paths=self.paths, stage=STAGE_01, attempt_no=1,
            stage_markdown="# Stage 01", suggestions=["a", "b", "c"],
        )
        self.assertEqual(decision.decision_token, "approve")
        self.assertIsNone(decision.call_cost.total_cost_usd)


# ---------------------------------------------------------------------------
# Not in the paper
# ---------------------------------------------------------------------------

#: Names that write something to disk. Used to check the run's cost report writes nothing.
WRITERS = frozenset({"write_text", "append_log_entry", "append_jsonl", "write_bytes", "open", "dump"})

#: Every function that can turn a cost into characters. The population
#: :func:`rendering_sites` is derived from, so a fifth way to render one shows up as a new
#: call site rather than as a new place the number could leak to.
RENDERERS = frozenset(
    {"format_call_cost", "format_run_cost_report", "billed_tokens", "describe_coverage", "run_call_cost"}
)

#: ``module::function`` for every production call of one of :data:`RENDERERS`.
RENDERING_SITES: tuple[str, ...] = (
    "src/call_cost.py::format_call_cost",
    "src/stage_cost.py::format_run_cost_report",
    "src/stage_cost.py::summarize_stage_cost",
    "src/manager.py::_report_run_cost",
)

#: Every module under ``src/`` that names a cost field, and what it does with it.
#:
#: Three roles and no fourth: carry it from the backend, record it, print it once at the
#: end. Nothing here judges anything, and :class:`NothingUnderSrcDecidesOnTheCostTests` is
#: what holds that over the syntax of all eight.
COST_AWARE_MODULES: dict[str, str] = {
    "src/call_cost.py": "declares the fields, the absent-aware arithmetic and the formatter",
    "src/operator.py": "prices the backend's result events and puts the report on OperatorResult",
    "src/approval_agent.py": "carries the review's own spend out on ReviewDecision",
    "src/validity_review.py": "carries the adversarial pass's spend out on ValidityReviewOutcome",
    "src/utils.py": "declares the field on OperatorResult, which is the wire itself",
    "src/stage_cost.py": "records it on the visit row, sums it over the run, formats it",
    "src/manager.py": "charges each call to the open meter and prints the total to the terminal",
    "src/terminal_ui.py": (
        "names two of the field strings in the Codex `turn_completed` panel, which is a "
        "different backend's usage vocabulary and never becomes a CallCost; see "
        "LITERAL_EXEMPTIONS"
    ),
}


def cost_naming_modules() -> set[str]:
    """Modules whose code -- not whose prose -- names a watched cost name."""
    found: set[str] = set()
    for path, tree in parsed_src():
        body = [
            node for node in tree.body
            if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
        ]
        names: set[str] = set()
        for node in body:
            names |= names_in(node)
        if names & set(INERT_NAMES):
            found.add(path.relative_to(REPO).as_posix())
    return found


def rendering_sites() -> set[str]:
    """``module::function`` for every call of a :data:`RENDERERS` name under ``src/``."""
    found: set[str] = set()
    for path, tree in parsed_src():
        relative = path.relative_to(REPO).as_posix()
        stack: list[str] = []

        class Walk(ast.NodeVisitor):
            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

            def visit_Call(self, node: ast.Call) -> None:
                func = node.func
                name = (
                    func.id if isinstance(func, ast.Name)
                    else func.attr if isinstance(func, ast.Attribute)
                    else None
                )
                if name in RENDERERS:
                    found.add(f"{relative}::{'.'.join(stack) or '<module>'}")
                self.generic_visit(node)

        Walk().visit(tree)
    return found


class TheReportDoesNotChangeTests(unittest.TestCase):
    """Constraint three: the deliverable does not change, and a test says so."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        runs = Path(self.tmp) / "runs"
        runs.mkdir()
        self.paths = build_run_paths(create_run_root(runs))
        ensure_run_layout(self.paths)

    def _deliverable_modules(self) -> set[str]:
        """Modules that touch the report directory or the report file, derived."""
        found: set[str] = set()
        for path, tree in parsed_src():
            names = {
                node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
            }
            if names & {"report_file", "report_dir"}:
                found.add(path.relative_to(REPO).as_posix())
        return found

    def test_every_module_that_touches_a_cost_field_is_declared_with_its_role(self) -> None:
        """The whole surface, derived, against a table that says what each one does.

        A module joining this list is a module that has learned about money, and the
        question worth asking about each is which of the three permitted things it does --
        carry it, record it, or print it. A new one fails here rather than appearing in
        the tree unclassified, which is the same rule
        ``tests/test_writable_decisive_fields.py`` applies to gates.
        """
        self.assertEqual(sorted(COST_AWARE_MODULES), sorted(cost_naming_modules()))
        for module, role in COST_AWARE_MODULES.items():
            with self.subTest(module=module):
                self.assertGreater(len(role), 40, f"{module} has no stated role")

    def test_the_only_production_reader_of_a_rendered_cost_is_the_terminal_report(self) -> None:
        """Where a cost figure can become text, derived from the syntax.

        A number that is never rendered outside these four places cannot reach
        ``workspace/report/``: three of them are the formatter and its own two callers
        inside :mod:`src.stage_cost`, and the fourth is the manager method that prints to
        the terminal and writes nothing. Nothing else in ``src/`` turns a cost into
        characters.
        """
        self.assertEqual(sorted(RENDERING_SITES), sorted(rendering_sites()))
        outside = {site for site in RENDERING_SITES if not site.startswith(("src/call_cost.py", "src/stage_cost.py"))}
        self.assertEqual({"src/manager.py::_report_run_cost"}, outside)

    def test_the_derived_populations_are_not_empty(self) -> None:
        """Otherwise the checks above pass by finding nothing to check."""
        self.assertGreater(len(self._deliverable_modules()), 3)
        self.assertGreater(len(cost_naming_modules()), 3)
        self.assertGreater(len(rendering_sites()), 3)

    def test_no_stage_prompt_or_template_mentions_a_cost_field(self) -> None:
        """The agent is never told to put the bill in the paper."""
        roots = [REPO / "src" / "prompts", REPO / "templates"]
        for root in roots:
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                for name in COST_FIELDS:
                    self.assertNotIn(name, text, f"{path.relative_to(REPO)} names {name}")

    def test_the_run_cost_report_writes_nothing(self) -> None:
        """Terminal output only, asserted over the method's own syntax.

        `logs.txt` included: the ledger is the machine-readable copy and the terminal is
        the human one, and a third copy is a third thing that has to stay true.
        """
        tree = ast.parse(REPO.joinpath("src", "manager.py").read_text(encoding="utf-8"))
        method = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_report_run_cost"
        )
        called = {
            node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            for node in ast.walk(method)
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))
        }
        self.assertEqual(set(), called & WRITERS, f"{sorted(called & WRITERS)} writes a file")
        self.assertIn("panel", called)

    def test_printing_the_report_leaves_the_report_directory_untouched(self) -> None:
        """The behavioural half: run it against a workspace that has a report in it."""
        report = self.paths.report_file
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("# Findings\n\nThe deliverable.\n", encoding="utf-8")
        before = {
            item: item.read_bytes() for item in sorted(self.paths.report_dir.rglob("*")) if item.is_file()
        }
        append_stage_cost_row(
            self.paths,
            dataclasses.replace(
                StageCostMeter(STAGE_01).close(), call_cost=CallCost(1, 1, 1, 2, 3, 4, 12.5)
            ),
        )
        stream = io.StringIO()
        manager = ResearchManager(
            project_root=REPO,
            runs_dir=Path(self.tmp) / "runs",
            operator=MagicMock(model="m", backend_name="claude", fake_mode=True),
            ui=TerminalUI(output_stream=stream, input_stream=io.StringIO(), interactive=False),
            unattended=True,
        )
        manager._report_run_cost(self.paths)

        after = {
            item: item.read_bytes() for item in sorted(self.paths.report_dir.rglob("*")) if item.is_file()
        }
        self.assertEqual(before, after)
        self.assertIn("$12.50", stream.getvalue())

    def test_the_cost_does_not_reach_the_log_summary(self) -> None:
        """`logs.txt` keeps the attempt census; the money goes to the terminal only."""
        row = StageCostMeter(STAGE_01).close().to_dict()
        row[RECORD_FIELD] = CallCost(1, 1, 1, 2, 3, 4, 12.5).to_dict()
        text = format_stage_cost_summary([row])
        self.assertNotIn("$", text)
        self.assertNotIn(TOKEN_SUM_LABEL, text)


# ---------------------------------------------------------------------------
# The mutation sweep, as an instrument
# ---------------------------------------------------------------------------

CALL_COST = "src/call_cost.py"
STAGE_COST = "src/stage_cost.py"
OPERATOR = "src/operator.py"
APPROVAL = "src/approval_agent.py"
MANAGER = "src/manager.py"
SUPERVISOR = "src/supervisor.py"
ROUTER = "src/router.py"

#: ``(what it breaks, file, the text to replace, what to replace it with)``.
#:
#: Same shape as ``tests/test_stage_cost_ledger.MUTATIONS`` and run the same way, because a
#: commit message saying "N mutations, all killed" is a number a reader has to believe::
#:
#:     git worktree add --detach /tmp/sweep HEAD
#:     cd /tmp/sweep && python3 -m tests.test_cost_is_recorded_and_unread --mutations
#:
#: Each anchor must match exactly once and the runner refuses the sweep rather than
#: reporting a kill it did not make: an anchor that stops matching after a refactor is a
#: mutation silently not applied, which reads in the output exactly like one that was
#: killed.
MUTATIONS: tuple[tuple[str, str, str, str], ...] = (
    # -- the gate itself ---------------------------------------------------
    #
    # The two the ask names by hand: put a cost into a decision path and confirm it dies.
    # Two rather than one because they are killed by different mechanisms, and only the
    # second survives a syntax check.
    ("the supervisor stops a stage for being expensive", SUPERVISOR,
     "        if unchanging_failure(digests) and (at_stake is None or at_stake >= MIN_ATTEMPTS_AT_STAKE):",
     "        expensive = sum(\n"
     '            float((row.get("call_cost") or {}).get("total_cost_usd") or 0)\n'
     "            for row in read_stage_cost_ledger(paths)\n"
     "        ) > 10\n"
     "        if expensive or (unchanging_failure(digests) and (at_stake is None or at_stake >= MIN_ATTEMPTS_AT_STAKE)):"),
    ("the supervisor records the bill in its evidence without branching on it", SUPERVISOR,
     '                "closed_stages": len(others),\n'
     '                "longest_unchanged_run": longest_unchanged_run(digests),\n'
     "            },\n"
     "        )\n"
     "\n"
     "    def _why_nothing(",
     '                "closed_stages": len(others),\n'
     '                "longest_unchanged_run": longest_unchanged_run(digests),\n'
     '                "spent_usd": sum(\n'
     '                    float((row.get("call_cost") or {}).get("total_cost_usd") or 0)\n'
     "                    for row in read_stage_cost_ledger(paths)\n"
     "                ),\n"
     "            },\n"
     "        )\n"
     "\n"
     "    def _why_nothing("),
    ("the router shops on price", ROUTER,
     "class StageRouter:",
     "def _too_dear(rows):\n"
     '    return any((row.get("call_cost") or {}).get("total_cost_usd", 0) > 10 for row in rows)\n'
     "\n"
     "\n"
     "class StageRouter:"),

    # -- absent is not zero -------------------------------------------------
    ("an unreported token count is recorded as zero", CALL_COST,
     "    if isinstance(value, int):\n        return value\n    return None\n",
     "    if isinstance(value, int):\n        return value\n    return 0\n"),
    ("an unreported dollar figure is recorded as zero", CALL_COST,
     "    if isinstance(value, (int, float)):\n        return float(value)\n    return None\n",
     "    if isinstance(value, (int, float)):\n        return float(value)\n    return 0.0\n"),
    ("a report that priced nothing still counts as priced", CALL_COST,
     "        return cls(result_events=1, priced_events=1 if present else 0, **measured)",
     "        return cls(result_events=1, priced_events=1, **measured)"),
    ("the formatter prints $0.00 where nothing was measured", CALL_COST,
     '    return NOT_MEASURED if value is None else f"${value:,.2f}"',
     '    return f"${value or 0:,.2f}"'),
    ("the formatter prints 0 tokens where nothing was measured", CALL_COST,
     '    return NOT_MEASURED if value is None else f"{value:,}"',
     '    return f"{value or 0:,}"'),
    ("an operator that reports nothing is charged zero", CALL_COST,
     "    return value if isinstance(value, CallCost) else CallCost()",
     "    return value if isinstance(value, CallCost) else CallCost(0, 0, 0, 0, 0, 0, 0.0)"),
    ("a boolean in the usage block is counted as a token", CALL_COST,
     "    if isinstance(value, bool):\n        return None\n    if isinstance(value, int):",
     "    if isinstance(value, int):"),
    ("a stage the run stepped over is billed at zero", STAGE_COST,
     "        attempt_digests=[],\n        note=note,\n    )",
     "        attempt_digests=[],\n        note=note,\n"
     "        call_cost=CallCost(1, 1, 0, 0, 0, 0, 0.0),\n    )"),
    ("a run with no rows prints a bill instead of saying nothing was measured", STAGE_COST,
     "    if not rows:\n        return NO_COST_RECORDED",
     "    if not rows:\n        return format_call_cost(CallCost())"),

    # -- trap one: the dollar figure sums ----------------------------------
    ("the visit keeps the last call's charge instead of adding them", CALL_COST,
     "        merged.update(\n"
     "            {name: _sum(getattr(self, name), getattr(other, name)) for name in COST_FIELDS}\n"
     "        )",
     "        merged.update({name: getattr(other, name) for name in COST_FIELDS})"),
    ("the run's total takes one row rather than summing them", STAGE_COST,
     "    total = CallCost()\n    for row in rows:\n        total = total + CallCost.from_mapping(row.get(RECORD_FIELD))\n    return total",
     "    for row in rows:\n        return CallCost.from_mapping(row.get(RECORD_FIELD))\n    return CallCost()"),
    ("the meter replaces the visit's bill with the latest call", STAGE_COST,
     "        self.call_cost = self.call_cost + call_cost_of(cost)",
     "        self.call_cost = call_cost_of(cost)"),

    # -- trap two: which fields a token figure sums ------------------------
    ("only the uncached input is treated as a token field", CALL_COST,
     'TOKEN_FIELDS: tuple[str, ...] = (\n    "input_tokens",\n    "cache_creation_input_tokens",\n'
     '    "cache_read_input_tokens",\n    "output_tokens",\n)',
     'TOKEN_FIELDS: tuple[str, ...] = ("input_tokens",)'),
    ("a token total is printed without naming what it sums", CALL_COST,
     'TOKEN_SUM_LABEL = " + ".join(TOKEN_LABELS[name] for name in TOKEN_FIELDS)',
     'TOKEN_SUM_LABEL = "tokens"'),
    ("the sum stops at the first field", CALL_COST,
     "    total: int | None = None\n    for name in TOKEN_FIELDS:\n        total = _sum(total, getattr(cost, name))\n    return total",
     "    return cost.input_tokens"),

    # -- the wire ----------------------------------------------------------
    ("the stream is never priced", OPERATOR,
     "                if is_result_event(payload):\n                    spend = spend + CallCost.from_result_event(payload)\n",
     ""),
    ("every stream line is treated as a result event", CALL_COST,
     "    return isinstance(event, Mapping) and event.get(EVENT_TYPE_KEY) == RESULT_EVENT_TYPE",
     "    return isinstance(event, Mapping)"),
    ("the stage run drops its own cost report", OPERATOR,
     "            session_id=effective_session_id,\n            call_cost=call_cost,\n        )\n\n    def repair_stage_summary(",
     "            session_id=effective_session_id,\n        )\n\n    def repair_stage_summary("),
    ("a resume that failed and was retried is charged once", OPERATOR,
     "            call_cost = call_cost + cost_from_stream_meta(stream_meta)\n            session_id = fallback_session_id\n            active_command = fallback_command",
     "            session_id = fallback_session_id\n            active_command = fallback_command"),
    ("a stage that timed out is charged nothing", OPERATOR,
     '                "timed_out": True,\n                RECORD_FIELD: spend.to_dict(),\n',
     '                "timed_out": True,\n'),
    ("the reviewer's verdict carries no price", APPROVAL,
     "        decision = replace(decision, call_cost=spend.total)",
     "        pass  # the cost is dropped"),
    ("the reviewer's sink is never filled", APPROVAL,
     "        if spend is not None:\n            spend.add(cost_from_stream_meta(stream_meta))\n",
     ""),
    ("the manager does not charge the stage run", MANAGER,
     "            self._note_call_cost(stage, result.call_cost)\n", ""),
    ("the manager does not charge the approval gate", MANAGER,
     "        self._note_call_cost(stage, decision.call_cost)\n", ""),
    ("the manager does not charge the adversarial pass", MANAGER,
     "        self._note_call_cost(stage, outcome.call_cost)\n        return outcome\n",
     "        return outcome\n"),
    ("the row does not publish what the visit cost", STAGE_COST,
     "            RECORD_FIELD: self.call_cost.to_dict(),\n", ""),
    ("the ledger version does not move with the row", STAGE_COST,
     "STAGE_COST_LEDGER_VERSION = 2", "STAGE_COST_LEDGER_VERSION = 1"),

    # -- terminal only ------------------------------------------------------
    ("the run never reports what it cost", MANAGER,
     "        # a walk ends here -- completed, halted and abandoned -- and not only the one that\n"
     "        # reaches the end. Same reason `_record_block_census` sits where it does.\n"
     "        self._report_run_cost(paths)\n",
     ""),
    ("the run's bill is written into logs.txt as well", MANAGER,
     "            rows = read_stage_cost_ledger(paths)\n            self.ui.panel(",
     "            rows = read_stage_cost_ledger(paths)\n"
     '            append_log_entry(paths.logs, "run_cost", format_run_cost_report(rows))\n'
     "            self.ui.panel("),
    ("the total does not say what it covers", STAGE_COST,
     "    lines.append(COST_SCOPE_NOTE)\n", ""),
)

#: Tests that fail under *every* mutation for a reason that is not the mutation.
#:
#: Applying a mutation is precisely what stops its own anchor from matching, so the anchor
#: check dies ``len(MUTATIONS)`` times out of ``len(MUTATIONS)`` and would report a kill for
#: a rule nobody holds. ``tests/test_stage_cost_ledger.py`` has a method of the same name and
#: is excluded with it, which is the conservative direction: a false kill is a green number
#: covering a hole, and a survivor is visible.
SWEEP_SELF_TESTS = frozenset({"test_every_anchor_matches_its_file_exactly_once"})

#: The modules the sweep runs. The gate is here, the ledger row is next door, and the
#: supervisor's own suite is the one that would notice a ruling changing shape.
SWEEP_MODULES = (
    "tests.test_cost_is_recorded_and_unread",
    "tests.test_stage_cost_ledger",
    "tests.test_run_supervisor",
)


def _dead_tests(root: Path) -> set[str]:
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", *SWEEP_MODULES, "-v"],
        cwd=root, capture_output=True, text=True,
    )
    out = proc.stdout + proc.stderr
    dead = set(re.findall(r"^(\w+) \(tests\.[\w.]+\) \.\.\. (?:FAIL|ERROR)", out, re.M))
    dead |= set(re.findall(r"^(?:FAIL|ERROR): (\w+) ", out, re.M))
    # An import-time break takes the whole module down and reports no test name at all.
    if not dead and proc.returncode != 0:
        dead.add("<the suite did not run>")
    return dead - SWEEP_SELF_TESTS


def run_mutations(root: Path | None = None) -> int:
    """Apply each of :data:`MUTATIONS` in turn and report what died. Returns the survivors.

    Restores every file in a ``finally``, so an interrupted sweep leaves the tree as it
    found it -- but it does edit the tree, so run it in a scratch checkout.
    """
    root = root or REPO
    baseline = _dead_tests(root)
    if baseline:
        print(f"REFUSED: the tree is not green before mutating: {sorted(baseline)}")
        return len(baseline)
    print(f"baseline green; {len(MUTATIONS)} mutations to try\n")
    survivors: list[str] = []
    for name, relative, old, new in MUTATIONS:
        path = root / relative
        text = path.read_text(encoding="utf-8")
        if text.count(old) != 1:
            print(f"NOT APPLIED ({text.count(old)} anchor matches): {name}")
            survivors.append(name)
            continue
        path.write_text(text.replace(old, new), encoding="utf-8")
        try:
            dead = _dead_tests(root)
        finally:
            path.write_text(text, encoding="utf-8")
        if dead:
            print(f"killed  {name}\n            by: {', '.join(sorted(dead))}")
        else:
            print(f"SURVIVED  {name}")
            survivors.append(name)
    print(f"\ntried {len(MUTATIONS)}, killed {len(MUTATIONS) - len(survivors)}, "
          f"survivors {len(survivors)}")
    for name in survivors:
        print("   SURVIVOR:", name)
    return len(survivors)


class TheSweepIsRunnableTests(unittest.TestCase):
    """The instrument, checked without running it.

    ``len(MUTATIONS)`` subprocess suites is not a unit test. What can go stale unnoticed is
    an *anchor*, and an anchor that no longer matches is a mutation silently not applied --
    which reads in the output exactly like a kill.
    """

    def test_every_anchor_matches_its_file_exactly_once(self) -> None:
        for name, relative, old, _new in MUTATIONS:
            with self.subTest(mutation=name):
                text = (REPO / relative).read_text(encoding="utf-8")
                self.assertEqual(
                    text.count(old), 1,
                    f"{name}: anchor matches {text.count(old)} times in {relative}",
                )

    def test_no_mutation_leaves_the_file_unchanged(self) -> None:
        for name, _relative, old, new in MUTATIONS:
            with self.subTest(mutation=name):
                self.assertNotEqual(old, new, f"{name} is not a mutation")

    def test_no_two_mutations_share_a_name(self) -> None:
        """The runner reports by name, so a duplicate hides a survivor behind a kill."""
        names = [name for name, _r, _o, _w in MUTATIONS]
        self.assertEqual(len(names), len(set(names)), "duplicate mutation name")

    def test_the_sweep_covers_every_file_this_branch_touched_in_src(self) -> None:
        self.assertEqual(
            {relative for _n, relative, _o, _w in MUTATIONS},
            {CALL_COST, STAGE_COST, OPERATOR, APPROVAL, MANAGER, SUPERVISOR, ROUTER},
        )

    def test_the_self_test_exclusion_names_a_test_that_exists(self) -> None:
        for name in SWEEP_SELF_TESTS:
            self.assertTrue(hasattr(TheSweepIsRunnableTests, name), name)

    def test_the_docstring_says_how_many_mutations_there_are(self) -> None:
        """The count next to the thing it counts, which is the cheapest one to keep honest."""
        docstring = sys.modules[__name__].__doc__ or ""
        self.assertIn(f"{len(MUTATIONS)} tried, {len(MUTATIONS)} killed", docstring)


if __name__ == "__main__":
    if "--mutations" in sys.argv:
        raise SystemExit(1 if run_mutations() else 0)
    unittest.main()
