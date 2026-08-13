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

import re
import unittest
from pathlib import Path

from src.information_flow import CHANNELS
from src.rubric import CRITERIA
from src.stage_graph import _ADVANCE_GUARDS, REVISIT_EDGES, StageGraph
from src.utils import STAGES

REPO = Path(__file__).resolve().parent.parent

NUMBER_WORDS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
    8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen",
    14: "fourteen", 15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen",
    19: "nineteen", 20: "twenty", 21: "twenty-one", 22: "twenty-two",
    23: "twenty-three", 24: "twenty-four", 25: "twenty-five",
}


def spelled(value: int) -> str:
    return NUMBER_WORDS[value]


def _adaptive_edges() -> int:
    return len(StageGraph.adaptive().edges)


def _forward_edges() -> int:
    return sum(1 for edge in StageGraph.adaptive().edges if edge.kind != "revisit")


#: ``(noun, live value)``. Every spelled-out numeral immediately before *noun* in a
#: tracked document must equal *value*. The noun is matched case-insensitively and
#: must be the whole phrase, so "typed channels" does not also catch "channels".
COUNTED_NOUNS: tuple[tuple[str, int], ...] = (
    ("typed channels", len(CHANNELS)),
    ("typed information channels", len(CHANNELS)),
    ("backward edges", len(REVISIT_EDGES)),
    ("backward moves", len(REVISIT_EDGES)),
    ("dotted edges", len(REVISIT_EDGES)),
    ("edges in the adaptive graph", _adaptive_edges()),
    ("forward edges", _forward_edges() - 1),  # the abandonment terminal aside
    ("guarded forward edges", len(_ADVANCE_GUARDS)),
)

TRACKED_DOCS = ("README.md", "docs/architecture.md", "docs/self-improvement.md")

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
