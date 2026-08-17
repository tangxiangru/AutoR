"""Counts written into prose, checked against the symbols they claim to count.

Three sweeps of the docs in one week found the same class of defect each time: a
sentence says "thirteen typed channels", someone adds a channel, and the sentence
stays green because prose has no compiler. The counts that rotted were not obscure —
they were the ones the README leads with, and one of them contradicted a second copy
of itself four hundred lines further down.

Two rules, both cheap:

**A spelled-out count next to a countable noun must equal the symbol.** The scan is
deliberately narrow — a fixed list of (phrase, live value) pairs — because a general
"find every number in the docs" check would be all false positives. Adding a row here
is how a new claim gets protected.

**A count written in digits is checked against the same symbol.** The word scan
alone let two README sites keep saying `16` through the commit that took
``CHANNELS`` to 18, and the sweep meant to catch that was ``grep -rni sixteen``,
which cannot match a digit. One of the two was the architecture diagram.

**A row of the README's "counts you can re-derive" table is re-derived, or exempt
by name.** Its values are digits in the cell *after* the noun, so neither numeral
scan can see them at all. Every row is in ``RE_DERIVABLE_TABLE_ROWS`` or in
``UNDERIVABLE_TABLE_ROWS`` with a reason, so deleting a row from the checked list
fails rather than quietly retiring the claim.

``COUNTED_NOUNS`` has no such coverage rule and deleting a row from it is a
surviving mutation. That is deliberate rather than missed: its population is
prose. Scanning the four tracked docs for every spelled-out numeral before a
phrase containing "channel" or "edge" returned forty-eight phrases when this note
was written, and thirty-one of them were ordinary sentences no symbol counts —
"one edge out of each node", "eighteen edges to twenty-two", "Six of the eight
forward edges". A coverage rule there would be an exemption list longer than the
check, which is the same reason the scan is a fixed list of phrases and not a
search for numbers.

**A doc may not cite a line number in this repo's own source.** Of the forty-four
`file.py:NNN` references the docs carried before this test existed, twelve of twelve
spot-checked pointed at the wrong line, and two of the survivors were right by
coincidence — one landed on a blank line, another on a closing bracket. A line number
rots on the next edit to the file above it, which is a guarantee of decay, not a risk
of it. Symbol names do not rot: `grep` finds them wherever they moved. External repos
are exempt, because the doc cannot re-derive those and the reader is being pointed at
a pinned artifact rather than at moving code.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from src.information_flow import ALL_STAGES, CHANNELS
from src.rubric import CRITERIA
from src.run_skills import discipline_of, read_skill_pack
from src.stage_graph import (
    _ADVANCE_GUARDS,
    BLOCK_KINDS,
    REVISIT_EDGES,
    TERMINAL_EDGES,
    StageGraph,
)
from src.utils import REQUIRED_STAGE_HEADINGS, STAGES

REPO = Path(__file__).resolve().parent.parent

NUMBER_WORDS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
    8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen",
    14: "fourteen", 15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen",
    19: "nineteen", 20: "twenty", 21: "twenty-one", 22: "twenty-two",
    23: "twenty-three", 24: "twenty-four", 25: "twenty-five",
    26: "twenty-six", 27: "twenty-seven", 28: "twenty-eight", 29: "twenty-nine",
    30: "thirty", 31: "thirty-one", 32: "thirty-two", 33: "thirty-three",
    34: "thirty-four", 35: "thirty-five", 36: "thirty-six", 37: "thirty-seven",
    38: "thirty-eight", 39: "thirty-nine", 40: "forty",
    41: "forty-one", 42: "forty-two", 43: "forty-three", 44: "forty-four",
    45: "forty-five", 46: "forty-six", 47: "forty-seven", 48: "forty-eight",
    49: "forty-nine", 50: "fifty",
}


def spelled(value: int) -> str:
    return NUMBER_WORDS[value]


def _adaptive_edges() -> int:
    return len(StageGraph.adaptive().edges)


def _forward_edges() -> int:
    return sum(1 for edge in StageGraph.adaptive().edges if edge.kind != "revisit")


def _channels_with_a_producer() -> int:
    """Channels whose information is made by a stage rather than by the run config."""
    return sum(1 for channel in CHANNELS if channel.produced_by is not None)


def _channels_that_narrow() -> int:
    """Channels that withhold themselves from at least one stage.

    The README lists four narrowings by name and this is why that list is not a
    count: almost every channel narrows, and the four are the ones whose reason is
    not readable off the key.
    """
    return sum(1 for channel in CHANNELS if set(channel.consumed_by) != set(ALL_STAGES))

def _criteria_reaching(stage_number: int) -> int:
    return sum(1 for criterion in CRITERIA if criterion.min_stage <= stage_number)


def _weight_reaching(stage_number: int) -> str:
    """The weight a stage is graded out of, spelled the way prose spells it.

    ``13.0`` reads as "13" in a sentence and the docs write it that way, so the trailing
    zero comes off rather than the documents being made to carry it.
    """
    total = sum(c.weight for c in CRITERIA if c.min_stage <= stage_number)
    return f"{total:g}"


def _reachable_validators() -> int:
    """How many distinct ``validate_*`` functions ``validate_stage_artifacts`` calls.

    Three documents quote this number and they had already drifted apart: adding one
    validator moved `README.md` and `docs/framework.md` to eighteen and left
    `docs/architecture.md` saying seventeen, so a reader comparing two pages of the same
    repo got two answers. Counted off the syntax rather than off a hand-list, because
    the failure being prevented is a validator someone added and did not count.
    """
    tree = ast.parse((REPO / "src" / "utils.py").read_text(encoding="utf-8"))
    gate = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "validate_stage_artifacts"
    )
    return len(
        {
            node.func.id
            for node in ast.walk(gate)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id.startswith("validate_")
        }
    )


#: ``(noun, live value)``. Every spelled-out numeral immediately before *noun* in a
#: tracked document must equal *value*. The noun is matched case-insensitively and
#: must be the whole phrase, so "typed channels" does not also catch "channels".
def _skill_pack_size() -> int:
    return len(read_skill_pack(REPO / "src" / "skills"))


def _skills_without_a_field() -> int:
    return sum(
        1 for entry in read_skill_pack(REPO / "src" / "skills") if not discipline_of(entry.name)
    )


COUNTED_NOUNS: tuple[tuple[str, int], ...] = (
    ("typed channels", len(CHANNELS)),
    ("typed information channels", len(CHANNELS)),
    ("typed context channels", len(CHANNELS)),
    ("blocks are typed", len(CHANNELS)),
    ("channels produced inside the walk", _channels_with_a_producer()),
    ("channels narrow", _channels_that_narrow()),
    ("backward edges", len(REVISIT_EDGES)),
    ("backward moves", len(REVISIT_EDGES)),
    ("dotted edges", len(REVISIT_EDGES)),
    ("edges in the adaptive graph", _adaptive_edges()),
    ("forward edges", _forward_edges() - 1),  # the abandonment terminal aside
    ("guarded forward edges", len(_ADVANCE_GUARDS)),
    ("`validate_*` functions", _reachable_validators()),
    # The README said "Six skills ship today" through the twenty-eight merges that took
    # the pack past thirty, because no symbol was counting. These three rows are that
    # symbol. `general` and `field` are the two halves `install_run_skills` routes
    # differently, so a skill added without a field prefix moves a different number from
    # one added with one.
    ("skills ship today", _skill_pack_size()),
    ("general ones", _skills_without_a_field()),
    ("field-specific ones", _skill_pack_size() - _skills_without_a_field()),
)

#: Three documents state the channel count and ``docs/framework.md`` states it
#: three times, but the framework was outside this scan: two of the three could
#: not go stale and the third could, and nothing said which was which. It is
#: tracked now, and the phrase it uses that the others do not — "typed context
#: channels" — is a row above.
#: The paper notes were outside the scan and one of them rotted exactly the way the
#: comment above predicts: ``docs/iclr/composable-stage-graphs.md`` said "eighteen typed
#: information channels" — a phrase already in ``COUNTED_NOUNS`` — through the two
#: additions that took ``CHANNELS`` past it. Being a design note is not a reason to be
#: exempt: it is the document that argues *from* the topology, so a wrong count there is
#: an argument with a wrong premise rather than a stale sentence.
TRACKED_DOCS = (
    "README.md",
    "docs/architecture.md",
    "docs/self-improvement.md",
    "docs/framework.md",
    "docs/iclr/composable-stage-graphs.md",
    "docs/iclr/round-loop-and-stage-graph.md",
)

#: ``(row label, live value)`` for the README table headed "Every number below comes
#: from a named symbol in the source. Re-derive them". These values are digits in a
#: table cell, so neither numeral scan above can see them: the channel row sat at 16
#: through the commit that took ``CHANNELS`` to 18 and nothing went red.
RE_DERIVABLE_TABLE_ROWS: tuple[tuple[str, int], ...] = (
    ("Stages (nodes in the walk)", len(STAGES)),
    ("Guarded forward edges", len(_ADVANCE_GUARDS)),
    ("Backward edges", len(REVISIT_EDGES)),
    ("Conditional terminal edges", len(TERMINAL_EDGES)),
    ("Edges in the default (`adaptive`) graph", _adaptive_edges()),
    ("Edges in `--stage-graph linear`", len(StageGraph.linear().edges)),
    ("Typed information channels", len(CHANNELS)),
    ("Required stage-summary headings", len(REQUIRED_STAGE_HEADINGS)),
    ("Rubric criteria (weighted, backend-free)", len(CRITERIA)),
)


#: Rows of the same table whose value no symbol in this module can produce, each
#: with the reason it is exempt. A row in neither this mapping nor
#: ``RE_DERIVABLE_TABLE_ROWS`` fails ``test_every_row_of_that_table_is_accounted_for``,
#: because otherwise the cheapest way to pass the check above is to delete a row
#: from it and leave the claim standing in the README.
UNDERIVABLE_TABLE_ROWS: dict[str, str] = {
    "`validate_*` functions the stage gate calls": (
        "the count is of call sites inside validate_stage_artifacts, not of a "
        "collection; counting them here would be a second implementation of the "
        "gate rather than a re-derivation of it"
    ),
    "Flags on `main.py` / `rcb_agent.py`": (
        "two numbers in one cell, and parse_args builds them imperatively"
    ),
    "Python modules / lines / tests": (
        "the stated symbol is 'the tree'; the test count in particular moves with "
        "every branch in flight, so pinning it here would red the suite on merges "
        "that changed nothing about it"
    ),
}

#: The sentence the table promises under. Split on it rather than counting tables,
#: so that a new table added above cannot silently take this one's place.
RE_DERIVABLE_TABLE_PROMISE = (
    "Every number below comes from a named symbol in the source. Re-derive them"
)


def _re_derivable_table(path: Path) -> dict[str, str]:
    """``{first cell: last cell}`` for the first markdown table after the promise."""
    text = path.read_text(encoding="utf-8")
    if RE_DERIVABLE_TABLE_PROMISE not in text:
        return {}
    rows: dict[str, str] = {}
    started = False
    for line in text.split(RE_DERIVABLE_TABLE_PROMISE, 1)[1].splitlines():
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            if started:
                break
            continue
        started = True
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2 or set(cells[0]) <= {"-", ":", " "} or cells[0] == "Count":
            continue
        rows[cells[0]] = cells[-1]
    return rows


#: Line references outside this repo's own tree. The reader is being sent to a pinned
#: artifact somewhere else, which this repo cannot re-derive and does not churn.
EXTERNAL_REFERENCE_PREFIXES = ("evaluation/",)


class CountsInProseMatchTheSymbolTests(unittest.TestCase):
    def test_every_spelled_out_count_matches_its_symbol(self) -> None:
        wrong: list[str] = []
        for name in TRACKED_DOCS:
            text = (REPO / name).read_text(encoding="utf-8")
            for noun, value in COUNTED_NOUNS:
                # The noun may be broken across a line in the source markdown, so
                # every space in it matches any run of whitespace. Without this the
                # scan silently skips exactly the wrapped sentences, which is where
                # the first three stale counts were found.
                spaced = r"\s+".join(re.escape(word) for word in noun.split())
                pattern = re.compile(
                    r"\b([A-Za-z]+(?:-[a-z]+)?)\s+" + spaced + r"\b", re.IGNORECASE
                )
                for match in pattern.finditer(text):
                    word = match.group(1).lower()
                    if word not in NUMBER_WORDS.values():
                        continue
                    if word != spelled(value):
                        line = text[: match.start()].count("\n") + 1
                        wrong.append(
                            f"{name}:{line} says '{match.group(0)}' but the symbol "
                            f"counts {value} ({spelled(value)})"
                        )
        self.assertEqual(wrong, [], "\n".join(wrong))

    def test_a_count_written_in_digits_matches_its_symbol_too(self) -> None:
        """The same nouns, counted in digits instead of words.

        A channel was added and the two README sites that state the count as `16`
        rather than "sixteen" stayed behind, because the scan above requires a
        spelled-out numeral and the sweep that was supposed to catch the rot was
        `grep -rni sixteen` — which cannot match a digit by construction. One of
        the two was the architecture diagram, the only picture of the layer.
        """
        wrong: list[str] = []
        for name in TRACKED_DOCS:
            text = (REPO / name).read_text(encoding="utf-8")
            for noun, value in COUNTED_NOUNS:
                spaced = r"\s+".join(re.escape(word) for word in noun.split())
                pattern = re.compile(r"\b(\d+)\s+" + spaced + r"\b", re.IGNORECASE)
                for match in pattern.finditer(text):
                    if int(match.group(1)) != value:
                        line = text[: match.start()].count("\n") + 1
                        wrong.append(
                            f"{name}:{line} says '{match.group(0)}' but the symbol "
                            f"counts {value}"
                        )
        self.assertEqual(wrong, [], "\n".join(wrong))

    def test_the_re_derivable_table_rows_are_re_derivable(self) -> None:
        """The README's own promise, enforced on the rows that can keep it.

        The table is introduced with "Every number below comes from a named symbol
        in the source. Re-derive them", and nothing did: its channel row said 16
        against a `CHANNELS` of 18. Neither scan above can reach it — the value is
        a digit in the cell *after* the noun, not a numeral before it.

        Rows whose value no symbol here can produce are exempt by name in
        `UNDERIVABLE_TABLE_ROWS`, with the reason. Listing one of those as
        re-derivable would put a hand-typed number in a test and call it a
        measurement.
        """
        rows = _re_derivable_table(REPO / "README.md")
        wrong: list[str] = []
        for label, value in RE_DERIVABLE_TABLE_ROWS:
            found = rows.get(label)
            self.assertIsNotNone(
                found,
                f"README.md no longer has a re-derivable table row labelled "
                f"{label!r}; if it was renamed, rename it here too — a row that "
                f"stops matching stops being checked, silently",
            )
            assert found is not None  # for type checkers; assertIsNotNone above
            if found != str(value):
                wrong.append(f"README.md row {label!r} says {found}, {value} is live")
        self.assertEqual(wrong, [], "\n".join(wrong))

    def test_every_row_of_that_table_is_accounted_for(self) -> None:
        """Deleting a row from the checked list has to cost something.

        The check above iterates the rows *it* declares, so the cheapest way to
        pass it is to stop declaring one while the number stays in the README —
        the same shape as the defect it was written for. Every row of the table is
        therefore either re-derived or exempt by name with a reason, and a new row
        is neither until someone says which.
        """
        rows = set(_re_derivable_table(REPO / "README.md"))
        declared = {label for label, _ in RE_DERIVABLE_TABLE_ROWS}
        self.assertEqual(
            rows - declared - set(UNDERIVABLE_TABLE_ROWS),
            set(),
            "README table rows that are neither re-derived nor exempt",
        )
        self.assertEqual(
            (declared | set(UNDERIVABLE_TABLE_ROWS)) - rows,
            set(),
            "labels claimed here that the README table no longer has",
        )

    def test_the_table_scan_reads_a_table_that_has_the_stale_shape(self) -> None:
        """Control for both tests above: a parser that finds nothing passes anything.

        The failure this guards against is not a wrong number but an empty
        population — a changed table format, a moved heading, a `_re_derivable_table`
        that returns `{}`. It also pins the promise the rows are checked against, so
        deleting the sentence and keeping the table cannot quietly retire them.
        """
        text = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn(RE_DERIVABLE_TABLE_PROMISE, text)
        rows = _re_derivable_table(REPO / "README.md")
        self.assertGreaterEqual(len(rows), len(RE_DERIVABLE_TABLE_ROWS))
        for label, _ in RE_DERIVABLE_TABLE_ROWS:
            with self.subTest(row=label):
                self.assertRegex(rows[label], r"^\d+$")

    def test_the_rubric_version_in_the_docs_is_the_live_one(self) -> None:
        """A bump splits the archive in two; a doc still naming the old one is a lie.

        Both places were already wrong when this was added — `README.md` said `"2"`
        and `docs/framework.md` said `3` while the code said `3` and `4` respectively.
        The version is quoted precisely because a reader needs to know which scores
        are comparable, which is the one thing a stale copy destroys.
        """
        from src.rubric import RUBRIC_VERSION

        for name in ("README.md", "docs/framework.md"):
            text = (REPO / name).read_text(encoding="utf-8")
            # Only the two canonical forms in which a doc states the *live* version.
            # A sentence recounting which bump was which ("it went to 3 when...") is
            # history and must stay readable, so it is deliberately not matched.
            pattern = r'`RUBRIC_VERSION(?:` is `| = ")(\d+)'
            quoted = set(re.findall(pattern, text))
            self.assertTrue(quoted, f"{name} stopped naming RUBRIC_VERSION")
            self.assertEqual(
                quoted,
                {RUBRIC_VERSION},
                f"{name} quotes RUBRIC_VERSION {sorted(quoted)}, the code says {RUBRIC_VERSION}",
            )

    def test_the_criteria_count_is_stated_correctly(self) -> None:
        text = (REPO / "docs/self-improvement.md").read_text(encoding="utf-8")
        self.assertIn(f"{spelled(len(CRITERIA)).capitalize()} criteria", text)

    def test_the_early_and_late_criterion_counts_are_stated_correctly(self) -> None:
        """One sentence, written twice, about the number the objective turns on.

        `docs/self-improvement.md` and `comparability_basis`'s own docstring both argue
        that the *set of stages a run reached* is a free parameter of the objective, and
        both make the argument by contrasting how many criteria Stage 02 faces with how
        many Stage 06 faces. A `min_stage` change moves those counts and neither copy is
        near the code that moved: raising `artifact_breadth` to Stage 01 made both read
        "five criteria worth 11" against a live 6 and 13.0.

        Pinned as a pair, in prose and in a docstring, because the divergence being
        prevented is the two copies disagreeing as much as either one being stale.
        """
        # Every space matches a run of whitespace: the sentence wraps in both copies,
        # and it wraps at a different word in each.
        pattern = re.compile(
            r"\s+".join(
                r"Stage 02 is scored on (\w+) criteria worth ([\d.]+), "
                r"Stage 06 on (\w+) worth ([\d.]+)".split(" ")
            )
        )
        for name in ("docs/self-improvement.md", "src/archive.py"):
            with self.subTest(document=name):
                match = pattern.search((REPO / name).read_text(encoding="utf-8"))
                self.assertIsNotNone(match, f"{name} stopped making the comparison")
                assert match is not None  # for the type checker
                self.assertEqual(
                    [match.group(1), match.group(2), match.group(3), match.group(4)],
                    [
                        spelled(_criteria_reaching(2)),
                        _weight_reaching(2),
                        spelled(_criteria_reaching(6)),
                        _weight_reaching(6),
                    ],
                    f"{name} states criterion counts the rubric no longer has",
                )

    def test_the_stage_count_is_stated_correctly(self) -> None:
        text = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"{spelled(len(STAGES))} stages", text.lower())

    def test_the_mermaid_diagram_draws_every_backward_edge(self) -> None:
        """A count elsewhere in the file does not fix a picture that is missing edges.

        The README's graph diagram drew ten dotted edges while `REVISIT_EDGES` had
        thirteen, so the three that were missing — 02→01, 03→02, 06→04 — were absent
        from the only place a reader looks for the shape.
        """
        text = (REPO / "README.md").read_text(encoding="utf-8")
        blocks = re.findall(r"```mermaid\n(.*?)```", text, re.DOTALL)
        dotted = sum(block.count("-.->") for block in blocks)
        self.assertEqual(
            dotted,
            len(REVISIT_EDGES),
            f"the diagram draws {dotted} backward edges, REVISIT_EDGES has "
            f"{len(REVISIT_EDGES)}",
        )


#: Where the per-visit ``blocked`` field's value set is written out for a reader.
#: One document does it, and adding a sixth kind to ``BLOCK_KINDS`` left it listing
#: five — the reader was told an exhaustive set that had stopped being exhaustive.
BLOCK_KIND_ENUMERATION = ("docs/run-artifacts.md", r"`blocked`, target → ((?:`\w+`/)*`\w+`)")

#: Every copy of the argument for the ``offered and declined`` control arm. All four
#: make the case by enumerating what the naive arm pools, and the enumeration is one
#: entry per :data:`BLOCK_KINDS` kind plus "the topology never had the edge" — so a
#: new block kind falsifies all four at once, in two documents and two modules that
#: nothing else connects. Adding ``budget`` moved the true count from five to six
#: kinds and every copy still said "four".
POOLED_CONTROL_ARM = (
    "docs/self-improvement.md",
    "src/decisions.py",
    "src/stage_graph.py",
    "src/archive.py",
)

#: There was a fifth. ``tests/test_decisions.py`` carried the same argument in different
#: words -- "the four states it stops pooling" -- so the regex below could not see it, and
#: this group certified four copies as agreeing while a fifth disagreed. It was retired
#: rather than added: its docstring now states no count and points here. A pin over a
#: hand-listed population is only as exhaustive as the phrasing it greps for, and the
#: cheapest way to keep that true is to have fewer copies rather than a better regex.


class TheBlockedValueSetIsWrittenDownOnceTests(unittest.TestCase):
    """Prose that enumerates ``BLOCK_KINDS``, checked against ``BLOCK_KINDS``.

    Both checks here are about an *exhaustive* claim rather than a count: a reader
    parsing `stage_graph.json` is told which values `blocked` can take, and an
    operator reading the archive's argument is told what the naive control arm
    pools. Neither is a rounding error when it goes stale — the first makes a
    schema wrong, and the second makes the estimator's justification wrong.
    """

    def test_the_documented_blocked_value_set_is_the_live_one(self) -> None:
        name, pattern = BLOCK_KIND_ENUMERATION
        text = (REPO / name).read_text(encoding="utf-8")
        found = re.findall(pattern, text)
        self.assertEqual(
            len(found),
            1,
            f"{name} no longer writes the `blocked` value set in the form this test "
            f"reads; a scan that matches nothing passes anything",
        )
        listed = [item.strip("`") for item in found[0].split("/")]
        self.assertEqual(
            sorted(listed),
            sorted(BLOCK_KINDS),
            f"{name} documents `blocked` as {listed}, BLOCK_KINDS is {list(BLOCK_KINDS)}",
        )

    def test_every_copy_of_the_pooled_control_arm_counts_the_same_states(self) -> None:
        """One state per block kind, plus the topology that never had the edge.

        The four copies are the shape this repository keeps shipping: one argument
        written out four times, in files no test connects, so a change that
        falsifies it falsifies all four silently. Pinned as a group rather than one
        at a time, because two of them disagreeing is as bad as both being stale.
        """
        expected = spelled(len(BLOCK_KINDS) + 1)
        for name in POOLED_CONTROL_ARM:
            with self.subTest(document=name):
                text = (REPO / name).read_text(encoding="utf-8")
                found = re.findall(r"(\w+)\s+unrelated\s+states", text)
                self.assertEqual(
                    len(found),
                    1,
                    f"{name} states the pooled-control-arm count {len(found)} times; "
                    f"this test reads exactly one",
                )
                self.assertEqual(
                    found[0],
                    expected,
                    f"{name} says the naive control arm pools '{found[0]}' unrelated "
                    f"states; it pools one per BLOCK_KINDS kind ({len(BLOCK_KINDS)}) "
                    f"plus the topology that never had the edge, so {expected}",
                )

    def test_every_copy_names_every_block_kind_it_claims_to_pool(self) -> None:
        """The count agreeing is not the list agreeing.

        Bumping "four" to "seven" and leaving the list at four entries passes the
        check above and tells the reader less than the wrong number did. Each kind
        has to appear, in backticks, in the sentence that does the counting.
        """
        for name in POOLED_CONTROL_ARM:
            text = (REPO / name).read_text(encoding="utf-8")
            start = re.search(r"(\w+)\s+unrelated\s+states", text)
            self.assertIsNotNone(start, name)
            assert start is not None  # for the type checker
            window = text[start.start() : start.start() + 900]
            for kind in BLOCK_KINDS:
                with self.subTest(document=name, kind=kind):
                    self.assertIn(
                        f"`{kind}`",
                        window,
                        f"{name} enumerates what the naive control arm pools without "
                        f"naming `{kind}`",
                    )


class DocsDoNotCiteLineNumbersTests(unittest.TestCase):
    def test_no_doc_cites_a_line_number_in_this_repo(self) -> None:
        offenders: list[str] = []
        for path in sorted(REPO.glob("*.md")) + sorted((REPO / "docs").glob("*.md")):
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"([A-Za-z_][\w/]*\.py):(\d+)(?:-\d+)?", text):
                target = match.group(1)
                if target.startswith(EXTERNAL_REFERENCE_PREFIXES):
                    continue
                if not _is_in_this_repo(target):
                    continue
                line = text[: match.start()].count("\n") + 1
                offenders.append(
                    f"{path.relative_to(REPO)}:{line} cites {match.group(0)} — "
                    "name the symbol instead; line numbers rot on the next edit"
                )
        self.assertEqual(offenders, [], "\n".join(offenders))


def _is_in_this_repo(reference: str) -> bool:
    if (REPO / reference).exists():
        return True
    name = Path(reference).name
    return any((REPO / "src").rglob(name)) or (REPO / name).exists()


if __name__ == "__main__":
    unittest.main()
