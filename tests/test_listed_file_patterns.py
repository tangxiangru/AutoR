from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.utils import (
    STAGES,
    build_run_paths,
    ensure_run_layout,
    expand_braces,
    validate_stage_markdown,
    write_text,
)


class ExpandBracesTest(unittest.TestCase):
    def test_a_simple_set_expands(self) -> None:
        self.assertEqual(
            expand_braces("text/paper_00{0,1,2,3}.txt"),
            [f"text/paper_00{i}.txt" for i in range(4)],
        )

    def test_two_sets_produce_the_cross_product(self) -> None:
        self.assertEqual(sorted(expand_braces("a{b,c}{1,2}.txt")),
                         ["ab1.txt", "ab2.txt", "ac1.txt", "ac2.txt"])

    def test_nested_sets_expand(self) -> None:
        self.assertEqual(sorted(expand_braces("x{a,{b,c}}")), ["xa", "xb", "xc"])

    def test_a_plain_path_is_returned_unchanged(self) -> None:
        self.assertEqual(expand_braces("no-braces.txt"), ["no-braces.txt"])

    def test_unbalanced_braces_are_treated_literally_not_guessed(self) -> None:
        self.assertEqual(expand_braces("unbalanced{a,b.txt"), ["unbalanced{a,b.txt"])

    def test_expansion_terminates_on_an_empty_option(self) -> None:
        self.assertEqual(sorted(expand_braces("f{,x}.txt")), ["f.txt", "fx.txt"])


class ListedPatternTest(unittest.TestCase):
    """Real files reported through a pattern must satisfy the gate; nothing else may."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        text_dir = self.paths.literature_dir / "text"
        text_dir.mkdir(parents=True, exist_ok=True)
        for index in range(4):
            write_text(text_dir / f"paper_00{index}.txt", "body\n")

    def _missing(self, listed: str) -> list[str]:
        markdown = (
            "# Stage 01: Literature Survey\n\n"
            "## Objective\no\n\n## Previously Approved Stage Summaries\nn\n\n"
            "## What I Did\nw\n\n## Key Results\nk\n\n"
            f"## Files Produced\n- `{listed}`\n\n"
            "## Decision Ledger\nOpen Questions: -\nLocked Decisions: -\n"
            "Assumptions: -\nRejected Alternatives: -\n\n"
            "## Suggestions for Refinement\n1. a\n2. b\n3. c\n\n"
            "## Your Options\n1. a\n2. b\n3. c\n4. d\n5. e\n6. f\n"
        )
        return [
            p for p in validate_stage_markdown(markdown, stage=STAGES[0], paths=self.paths)
            if "references missing file" in p
        ]

    def test_the_brace_form_from_the_real_run_now_validates(self) -> None:
        self.assertEqual(self._missing("workspace/literature/text/paper_00{0,1,2,3}.txt"), [])

    def test_the_glob_form_from_the_real_run_now_validates(self) -> None:
        self.assertEqual(self._missing("workspace/literature/text/paper_00*.txt"), [])

    def test_a_literal_path_still_validates(self) -> None:
        self.assertEqual(self._missing("workspace/literature/text/paper_000.txt"), [])

    def test_a_pattern_matching_nothing_still_fails(self) -> None:
        """The gate must keep its teeth: patterns are not a way to claim anything."""
        self.assertEqual(len(self._missing("workspace/literature/text/absent_*.txt")), 1)

    def test_a_brace_set_where_one_member_is_absent_still_passes(self) -> None:
        # At-least-one semantics, matching how a shell glob reads.
        self.assertEqual(self._missing("workspace/literature/text/paper_00{0,9}.txt"), [])

    def test_a_missing_literal_path_still_fails(self) -> None:
        self.assertEqual(len(self._missing("workspace/literature/text/never.txt")), 1)

    def test_a_recursive_glob_is_supported(self) -> None:
        self.assertEqual(self._missing("workspace/**/paper_001.txt"), [])


if __name__ == "__main__":
    unittest.main()
