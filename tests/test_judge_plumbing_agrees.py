"""Two scorers, one key file, one atomic write — and no shared reader to keep them equal.

``tools/score_rcb_run.py`` and ``tools/score_fs_run.py`` each read an API key from a file
outside the tree, each redact key-shaped text out of an error before printing it, and each
write their result with ``mkdir`` plus ``os.replace``. Those three are the same decisions
solving the same problems, and every one of them was paid for: the missing ``mkdir``
scored a whole trial's runs and died on ``FileNotFoundError``, which the driver read as
"scoring failed" and retried for four days; the ``os.replace`` is what stops a kill mid
write leaving a truncated JSON file that a final pass skips forever.

They are copies, deliberately, and this module is the price of that decision. Collapsing
them into a shared module was considered and rejected on a mechanical ground rather than a
stylistic one: ``tests/test_score_rcb_run.py`` loads that tool with
``spec_from_file_location`` and ``exec_module``, and the file has no ``sys.path``
bootstrap, so a ``from src...`` import there would raise ``ImportError`` under the loader
that four of this repository's tightest gates use. The alternative to a shared reader is a
test that makes the copies agree, which is this one.

It compares **normalised abstract syntax trees**, not text. Byte equality is impossible and
would have to be abandoned the moment either file was formatted differently, and a text
diff cannot tell a renamed function from a rewritten one. Two differences are declared
rather than discovered: ResearchClawBench's redactor is called ``_redact`` and this one is
called ``redact``, and its ``read_api_key`` tells the reader to "pass --judge vertex",
which is advice about a fallback judge that FrontierScience does not have and must not
inherit. Each exemption has a control that fails when the exemption stops being needed,
because an exemption list nobody prunes stops being readable.

The functions that are *supposed* to differ are listed too, in
:data:`DECLARED_DIVERGENCES`, with the reason each one diverges. A divergence table is not
decoration here: the point of the whole file is that a reader can tell which differences
were decided and which just happened.
"""

from __future__ import annotations

import ast
import copy
import unittest
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parent.parent
RCB_TOOL = REPO / "tools" / "score_rcb_run.py"
FS_TOOL = REPO / "tools" / "score_fs_run.py"

#: The plumbing the two scorers must implement identically, as ``fs name -> rcb name``.
#: Three functions, each of which exists because something went wrong once, and none of
#: which has anything to do with which benchmark is being scored.
SHARED_FUNCTIONS: dict[str, str] = {
    "read_api_key": "read_api_key",
    "redact": "_redact",
    "write_result": "write_result",
}


class Exemption(NamedTuple):
    """One declared difference inside a shared function, and what makes it necessary."""

    function: str
    kind: str
    why: str


#: The two differences this comparison is allowed to ignore. Anything else is a defect in
#: one of the two files, and the comparison says which one by failing.
EXEMPTIONS: tuple[Exemption, ...] = (
    Exemption(
        function="redact",
        kind="name",
        why=(
            "ResearchClawBench's redactor is private (`_redact`) and this one is public "
            "(`redact`), because this tool's own module docstring promises that every "
            "exception goes through it and a private name cannot be pointed at. The bodies "
            "must still be identical: they are the same regex over the same shapes."
        ),
    ),
    Exemption(
        function="read_api_key",
        kind="message",
        why=(
            "The `SystemExit` message differs, and has to. ResearchClawBench's says to "
            "'pass --judge vertex to score with Claude instead', which is advice about a "
            "fallback judge that FrontierScience does not have; copying it would send a "
            "reader after a flag that does not exist. Only the message is exempt -- the "
            "parsing below it, which is what actually reads the key, is compared."
        ),
    ),
)


class Divergence(NamedTuple):
    """A function the two scorers implement differently on purpose."""

    fs_symbol: str
    rcb_symbol: str
    why: str


#: Same job, different answer, in each case because the two benchmarks return different
#: things from their judges. Listed so that "these differ" is a decision on the record
#: rather than something a reader has to reconstruct from two files.
DECLARED_DIVERGENCES: tuple[Divergence, ...] = (
    Divergence(
        "src/fs_scoring.py::response_text",
        "_response_text",
        "ResearchClawBench's reader takes `output_text` when it is non-empty and then joins "
        "every content block of every output item. This one ignores `output_text` (null on "
        "the endpoint used here) and joins only `type == 'message'` items, because the "
        "FrontierScience contract is a verdict on the last line and anything appended after "
        "the message moves what is last. The other tool extracts a JSON object and does not "
        "care about order.",
    ),
    Divergence(
        "src/fs_scoring.py::aggregate_draws",
        "aggregate_draws",
        "ResearchClawBench's judge returns a per-item table, so its aggregation does a "
        "positional join across draws. This judge returns one scalar per draw, so there is "
        "nothing to join -- and a failed draw here removes the total instead of contributing "
        "a zero to a mean.",
    ),
    Divergence(
        "src/fs_scoring.py::format_spread",
        "format_spread",
        "One decimal place is right for a 0-100 benchmark whose judge spans 8.5 points and "
        "wrong for a 0-10 one whose measured sampling sd is 0.326: it would print a real 0.05 "
        "spread as 0.0, which is the exact claim this repository refuses to make. The "
        "single-draw branch also carries the measured noise band, which the other one has "
        "nowhere to put.",
    ),
    Divergence(
        "src/fs_scoring.py::refusal_reasons",
        "refusal_reasons",
        "Different clauses over different evidence. ResearchClawBench refuses on judge "
        "failures and on a checklist that came back short; FrontierScience has no checklist "
        "in the result and refuses on failed draws and on a draw count that does not match "
        "what was asked for.",
    ),
    Divergence(
        "src/fs_scoring.py::ScoringRefused",
        "ScoringRefused",
        "Same shape and same purpose, but this one copies the result and the reasons into "
        "the exception rather than holding the caller's objects, because the caller here "
        "keeps mutating its draw list after the refusal is raised.",
    ),
)


def _strip_docstring(node: ast.AST) -> None:
    body = getattr(node, "body", None)
    if not body:
        return
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        if isinstance(first.value.value, str):
            del body[0]


class _BlankMessages(ast.NodeTransformer):
    """Replace every f-string with a placeholder, for the one exempt function.

    Scoped deliberately: this runs on ``read_api_key`` and nothing else. Applied
    everywhere it would erase the ``.tmp.{os.getpid()}`` suffix in ``write_result``, which
    is one of the things that must agree.
    """

    def visit_JoinedStr(self, node: ast.JoinedStr) -> ast.AST:  # noqa: N802 - ast's name
        return ast.copy_location(ast.Constant(value="<message>"), node)


def function_named(path: Path, name: str) -> ast.AST:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                return node
    raise AssertionError(f"{path.name} does not define {name}")


def normalised(node: ast.AST, *, blank_messages: bool) -> str:
    """The function's source with its name, its docstring and, if exempt, its messages gone."""
    clone = copy.deepcopy(node)
    clone.name = "_canonical"  # type: ignore[attr-defined]
    _strip_docstring(clone)
    if blank_messages:
        clone = _BlankMessages().visit(clone)
        ast.fix_missing_locations(clone)
    return ast.unparse(clone)


def _blanked(function: str) -> bool:
    return any(item.function == function and item.kind == "message" for item in EXEMPTIONS)


class TheSharedPlumbingIsTheSameCodeTest(unittest.TestCase):
    """Three functions, compared as trees rather than as text."""

    def test_the_population_this_compares_is_not_empty(self) -> None:
        """The control every scanning assertion needs. An empty mapping passes the rest."""
        self.assertEqual(len(SHARED_FUNCTIONS), 3)
        self.assertTrue(RCB_TOOL.is_file() and FS_TOOL.is_file())

    def test_each_shared_function_normalises_to_the_same_tree(self) -> None:
        for fs_name, rcb_name in SHARED_FUNCTIONS.items():
            with self.subTest(function=fs_name):
                blank = _blanked(fs_name)
                self.assertEqual(
                    normalised(function_named(FS_TOOL, fs_name), blank_messages=blank),
                    normalised(function_named(RCB_TOOL, rcb_name), blank_messages=blank),
                    f"{fs_name} has drifted from {rcb_name}; make them the same or declare "
                    "the difference in EXEMPTIONS with a reason",
                )

    def test_the_comparison_would_notice_a_dropped_statement(self) -> None:
        """Without this the test above passes on a comparison that always returns equal.

        ``write_result``'s ``mkdir`` is the statement deleted here because it is the one
        whose absence actually cost a trial: the scorer judged every item, printed the
        total, and died writing the file.
        """
        original = function_named(RCB_TOOL, "write_result")
        damaged = copy.deepcopy(original)
        del damaged.body[1]  # the mkdir, once the docstring is counted
        self.assertNotEqual(
            normalised(original, blank_messages=False),
            normalised(damaged, blank_messages=False),
        )

    def test_the_comparison_ignores_the_docstrings_and_only_the_docstrings(self) -> None:
        """A docstring is prose about the code and the two files argue in different terms."""
        fs_source = function_named(FS_TOOL, "write_result")
        self.assertIn("os.replace", ast.unparse(fs_source))
        self.assertNotIn("FileNotFoundError", normalised(fs_source, blank_messages=False))


class EachExemptionIsStillNeededTest(unittest.TestCase):
    """An exemption that has outlived its cause is a lie the next reader inherits."""

    def test_every_exemption_names_a_function_that_is_compared(self) -> None:
        for item in EXEMPTIONS:
            with self.subTest(exemption=item.function):
                self.assertIn(item.function, SHARED_FUNCTIONS)
                self.assertGreaterEqual(len(item.why), 120, "a reason has to say what it buys")
                self.assertTrue(item.why.endswith("."))

    def test_the_name_exemption_is_still_needed(self) -> None:
        """It goes the moment ResearchClawBench renames its redactor."""
        source = RCB_TOOL.read_text(encoding="utf-8")
        self.assertIn("def _redact(", source)
        self.assertNotIn("def redact(", source)
        self.assertIn("def redact(", FS_TOOL.read_text(encoding="utf-8"))

    def test_the_message_exemption_is_still_needed(self) -> None:
        """Two halves: the messages really do differ, and the reason really is the vertex
        advice this tool must not inherit."""
        without = {
            path.name: normalised(function_named(path, "read_api_key"), blank_messages=False)
            for path in (FS_TOOL, RCB_TOOL)
        }
        self.assertNotEqual(without[FS_TOOL.name], without[RCB_TOOL.name])
        self.assertIn("--judge vertex", RCB_TOOL.read_text(encoding="utf-8"))
        self.assertNotIn("--judge vertex", FS_TOOL.read_text(encoding="utf-8"))

    def test_the_message_exemption_does_not_hide_the_parsing(self) -> None:
        """Blanking the messages must leave the part that actually reads the key visible,
        or the exemption would be a licence to rewrite the whole function."""
        blanked = normalised(function_named(FS_TOOL, "read_api_key"), blank_messages=True)
        self.assertIn("'sk-'", blanked)
        self.assertIn("split('=', 1)", blanked)
        self.assertIn("<message>", blanked)


class TheDeclaredDivergencesAreRealTest(unittest.TestCase):
    """Where the two scorers differ on purpose, and proof that they still both exist."""

    def test_every_declared_divergence_names_a_symbol_the_other_tool_still_has(self) -> None:
        source = RCB_TOOL.read_text(encoding="utf-8")
        for item in DECLARED_DIVERGENCES:
            with self.subTest(divergence=item.fs_symbol):
                self.assertTrue(
                    f"def {item.rcb_symbol}(" in source or f"class {item.rcb_symbol}" in source,
                    f"{item.rcb_symbol} is gone from score_rcb_run.py; the divergence is stale",
                )

    def test_every_declared_divergence_names_a_symbol_this_side_still_has(self) -> None:
        for item in DECLARED_DIVERGENCES:
            module, _, name = item.fs_symbol.partition("::")
            with self.subTest(divergence=item.fs_symbol):
                source = (REPO / module).read_text(encoding="utf-8")
                self.assertTrue(
                    f"def {name}(" in source or f"class {name}" in source,
                    f"{item.fs_symbol} is gone; the divergence is stale",
                )

    def test_every_declared_divergence_says_why(self) -> None:
        for item in DECLARED_DIVERGENCES:
            with self.subTest(divergence=item.fs_symbol):
                self.assertGreaterEqual(len(item.why), 120)
                self.assertTrue(item.why.endswith("."))
                self.assertNotIn("?", item.why, "a reason that asks a question decided nothing")

    def test_a_divergence_and_a_shared_function_are_never_the_same_function(self) -> None:
        """The two lists are the whole taxonomy: agree, or differ for a written reason.
        A function in both would mean the file claims both at once."""
        diverged = {item.fs_symbol.partition("::")[2] for item in DECLARED_DIVERGENCES}
        self.assertEqual(diverged & set(SHARED_FUNCTIONS), set())


if __name__ == "__main__":
    unittest.main()
