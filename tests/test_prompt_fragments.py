"""Shared prompt fragments: held once, and derived from the constants they describe.

The extension lists were hand-copied into three prompts and two copies were
already incomplete subsets of the constants. A sentence generated from the
constant cannot drift; a sentence describing it can, and had. These tests hold
that property rather than the wording.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from src.prompt_fragments import (
    RUN_SAFETY,
    STAGE_HEADER,
    artifact_formats,
    compose_stage_template,
)
from src.utils import (
    FIGURE_SUFFIXES,
    MACHINE_DATA_SUFFIXES,
    RENDERABLE_IMAGE_SUFFIXES,
    RESULT_SUFFIXES,
    STAGES,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT_DIR = REPO_ROOT / "src" / "prompts"
STAGE = {stage.number: stage for stage in STAGES}


class DerivedFromConstantsTest(unittest.TestCase):
    def test_the_data_formats_sentence_lists_every_accepted_suffix(self) -> None:
        text = artifact_formats(STAGE[3], "markdown")
        for suffix in MACHINE_DATA_SUFFIXES:
            self.assertIn(f"`{suffix}`", text)

    def test_the_result_formats_sentence_lists_every_accepted_suffix(self) -> None:
        text = artifact_formats(STAGE[5], "markdown")
        for suffix in RESULT_SUFFIXES:
            self.assertIn(f"`{suffix}`", text)

    def test_adding_a_suffix_to_the_constant_reaches_the_prompt(self) -> None:
        """The whole point: the prose cannot fall behind the constant."""
        import src.prompt_fragments as fragments

        original = set(MACHINE_DATA_SUFFIXES)
        try:
            fragments.MACHINE_DATA_SUFFIXES = original | {".arrow"}
            self.assertIn("`.arrow`", fragments.artifact_formats(STAGE[3], "markdown"))
        finally:
            fragments.MACHINE_DATA_SUFFIXES = original

    def test_markdown_mode_warns_that_a_stage_06_figure_can_be_invisible_at_07(self) -> None:
        """A real contradiction between two constants, stated where the figure is made."""
        text = artifact_formats(STAGE[6], "markdown")
        self.assertIn("PNG", text)
        invisible = FIGURE_SUFFIXES - RENDERABLE_IMAGE_SUFFIXES
        self.assertTrue(invisible, "the contradiction this warning exists for is gone")
        self.assertIn("counts as no figure at all one stage later", text)

    def test_latex_mode_does_not_carry_the_markdown_warning(self) -> None:
        self.assertNotIn("markdown mode", artifact_formats(STAGE[6], "latex"))

    def test_stages_without_a_format_gate_get_no_block(self) -> None:
        for number in (1, 2, 4, 7, 8):
            with self.subTest(stage=number):
                self.assertEqual(artifact_formats(STAGE[number], "markdown"), "")


class CompositionTest(unittest.TestCase):
    def test_the_shared_rules_reach_every_stage(self) -> None:
        for stage in STAGES:
            with self.subTest(stage=stage.slug):
                composed = compose_stage_template("## Body", stage, "markdown")
                self.assertIn("## Run Safety", composed)
                self.assertIn(STAGE_HEADER, composed)
                self.assertIn("## Body", composed)

    def test_the_safety_rules_come_after_the_stage_instructions(self) -> None:
        composed = compose_stage_template("## Body", STAGE[3], "markdown")
        self.assertLess(composed.index("## Body"), composed.index("## Run Safety"))

    def test_no_fragment_invents_a_placeholder(self) -> None:
        known = set(
            re.findall(r'"(\{\{[A-Z_]+\}\})"', (REPO_ROOT / "src" / "utils.py").read_text(encoding="utf-8"))
        )
        composed = "\n".join(
            compose_stage_template("", stage, fmt)
            for stage in STAGES
            for fmt in ("markdown", "latex")
        )
        unknown = {token for token in re.findall(r"\{\{[A-Z_]+\}\}", composed) if token not in known}
        self.assertEqual(unknown, set())


class NoLongerDuplicatedTest(unittest.TestCase):
    """The templates must not re-state what the fragment now supplies."""

    SHARED = (
        "# Stage {{STAGE_NUMBER}}: {{STAGE_NAME}}",
        "- All generated working files must remain under `{{WORKSPACE_ROOT}}`.",
        "- The stage summary draft for the current attempt must be written to `{{STAGE_OUTPUT_PATH}}`.",
        "- Do not control workflow progression.",
        "- Do not write outside the current run directory.",
    )

    def test_no_stage_template_restates_a_shared_rule(self) -> None:
        offenders = [
            f"{path.name}: {line}"
            for path in sorted(PROMPT_DIR.glob("0*.md"))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() in self.SHARED
        ]
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_no_stage_template_hand_copies_an_extension_list(self) -> None:
        """Two of the three original copies were already incomplete subsets."""
        offenders = []
        for path in sorted(PROMPT_DIR.glob("0*.md")):
            text = path.read_text(encoding="utf-8")
            for suffix_set, label in (
                (MACHINE_DATA_SUFFIXES, "MACHINE_DATA_SUFFIXES"),
                (RESULT_SUFFIXES, "RESULT_SUFFIXES"),
            ):
                listed = sum(1 for suffix in suffix_set if f"`{suffix}`" in text)
                if listed >= 3:
                    offenders.append(f"{path.name} hand-copies {listed} of {label}")
        self.assertEqual(offenders, [], "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
