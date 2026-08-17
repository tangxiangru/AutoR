"""A skill only exists for a run if a prompt the run renders tells it to read one.

Measured on the 40-task ResearchClawBench arm pinned at `2ffaeb4`
(`/rmeng_data/robtang/rcb_runs/arm_2ffaeb4`, one run per task, 19.7 h median
each): 16 skills were installed per run, and over the whole arm there were **78
`Skill` tool calls** — 1.75 distinct skills per run. Attributing each call to the
stage session that made it, from the `_meta.stage` records in
`.autor/*/logs_raw.jsonl`:

    01_literature_survey   31 launches in 31 runs
    02_hypothesis_generation 14 in  8
    03_study_design        25 in  7
    04_implementation       3 in  2
    05_experimentation      0 in  0
    06_analysis             2 in  1
    07_writing              3 in  1

Stage 01 is the only stage that reliably reaches for a skill, and it is the only
stage whose prompt names one imperatively (`01_literature_survey.md`: "Use the
`citation-discipline` skill before you write `sources.json`"). It fires exactly
once in each of 31 runs. Stages 05, 06 and 07 — which produce the results and
write the graded artifact — account for **five launches across forty runs**.

The three skills named imperatively in `07_writing.md` — `paper-writing`,
`latex-repair`, `venue-checklist` — launched **zero** times, because
`load_prompt_template` selects `07_writing_markdown.md` when the output format is
markdown, and that file named no skill at all. The two named in
`08_dissemination.md` launched twice between them, because `rcb_agent.py` stops
at `07_writing` and stage 08 never runs.

So the failure is silent in the exact way the skill mechanism is: the guidance is
written, installed, valid, green under `test_run_skills.py`, and unreachable.
This file makes it loud. It asserts four things:

1. Every skill named imperatively in any prompt is a skill that exists.
2. Every such naming appears in at least one prompt that the *default*
   configuration renders — markdown output, `07_writing` as the final stage.
   A prompt for a format or a stage this configuration never reaches is allowed
   to name a skill, but it may not be the only place that skill is named.
3. Every *general* skill in the pack is named by a rendered prompt. Field skills
   are exempt: the discipline installer already narrows them to two per run, and
   14 of the 20 field skills did launch at least once in the arm, so pull-based
   routing demonstrably works once the field of candidates is small.
4. The unreachable-by-construction allowlist has not outlived its cause.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from src.run_skills import discipline_of, read_skill_pack
from src.utils import STAGES, resolve_output_format


REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT_DIR = REPO_ROOT / "src" / "prompts"
SKILL_PACK = REPO_ROOT / "src" / "skills"

#: What `rcb_agent.py` runs: markdown output, stopping after Stage 07. This is the
#: configuration every benchmark measurement of AutoR has been taken under, so it is
#: the one whose prompts have to carry the guidance.
DEFAULT_OUTPUT = "markdown"
DEFAULT_FINAL_STAGE_NUMBER = 7

#: An imperative naming: "read the `x` skill", "use the `x` skill", "the skills `a`,
#: `b` and `c` ... use them". A skill mentioned in passing inside a table cell or a
#: parenthetical is not one of these and does not count as routing.
_IMPERATIVE = re.compile(
    r"(?:read|use|open|consult)\s+(?:the\s+)?(?:skills?\s+)?"
    r"((?:`[a-z0-9-]+`(?:\s*(?:,|and|or)\s*)?)+)",
    re.IGNORECASE,
)
_NAME = re.compile(r"`([a-z0-9-]+)`")


def _rendered_prompt_files() -> set[Path]:
    """The prompt files the default configuration actually loads.

    Mirrors `load_prompt_template`: a `<slug>_<format>.md` variant wins over
    `<slug>.md`, and stages past the default final stage are never reached.
    """
    rendered: set[Path] = set()
    fmt = resolve_output_format(DEFAULT_OUTPUT)
    for stage in STAGES:
        if stage.number > DEFAULT_FINAL_STAGE_NUMBER:
            continue
        variant = PROMPT_DIR / f"{stage.slug}_{fmt}.md"
        rendered.add(variant if variant.exists() else PROMPT_DIR / stage.filename)
    return rendered


def _named_skills(text: str, known: set[str]) -> set[str]:
    found: set[str] = set()
    for match in _IMPERATIVE.finditer(text):
        found |= {name for name in _NAME.findall(match.group(1)) if name in known}
    return found


class SkillNamingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.known = {entry.name for entry in read_skill_pack(SKILL_PACK)}
        self.assertTrue(self.known, "the skill pack did not parse")

    def test_every_skill_a_prompt_names_exists(self) -> None:
        """A renamed skill leaves a prompt pointing at nothing, and nothing says so."""
        backticked = set()
        for path in PROMPT_DIR.glob("*.md"):
            for match in _IMPERATIVE.finditer(path.read_text(encoding="utf-8")):
                for name in _NAME.findall(match.group(1)):
                    # Only names shaped like a skill; a prompt also backticks paths
                    # and JSON keys, and those are not claims about the pack.
                    if "-" in name and not name.endswith((".md", ".json", ".py")):
                        backticked.add((path.name, name))
        for prompt_name, skill in sorted(backticked):
            with self.subTest(prompt=prompt_name, skill=skill):
                self.assertIn(
                    skill,
                    self.known,
                    f"{prompt_name} tells the operator to read `{skill}`, "
                    f"which is not in {SKILL_PACK}",
                )

    def test_a_skill_is_named_in_a_prompt_this_configuration_renders(self) -> None:
        """Guidance whose only pointer is in an unrendered prompt reaches nobody.

        The allowlist holds skills whose *trigger* cannot occur in this
        configuration, not skills nobody got round to wiring. Each entry says why.
        """
        unreachable_by_construction = {
            # No `main.tex` is ever compiled when the output format is markdown.
            "latex-repair": "fires on a LaTeX build failure; markdown runs have no build",
            # Both are Stage 08 skills and Stage 08 is past the default final stage.
            "reproducibility-check": "Stage 08 only; the default run stops at 07",
            "venue-checklist": "Stage 08 only; the default run stops at 07",
        }

        rendered = _rendered_prompt_files()
        named_anywhere: dict[str, set[str]] = {}
        named_rendered: set[str] = set()
        for path in PROMPT_DIR.glob("*.md"):
            named = _named_skills(path.read_text(encoding="utf-8"), self.known)
            for skill in named:
                named_anywhere.setdefault(skill, set()).add(path.name)
            if path in rendered:
                named_rendered |= named

        for skill, where in sorted(named_anywhere.items()):
            if skill in named_rendered or skill in unreachable_by_construction:
                continue
            self.fail(
                f"`{skill}` is named imperatively in {sorted(where)}, none of which "
                f"the default configuration renders (markdown output, final stage "
                f"{DEFAULT_FINAL_STAGE_NUMBER:02d}). Either name it in a rendered prompt "
                f"or add it to `unreachable_by_construction` with the reason."
            )

    def test_every_general_skill_is_named_by_a_prompt_that_runs(self) -> None:
        """The measured failure was 13 of 34 skills never launching in 40 runs.

        A field skill is different: the installer already narrows the pack to the
        run's own field, so two descriptions compete rather than twenty, and 14 of
        the 20 field skills did launch at least once in the arm. Those stay
        pull-only. A *general* skill is offered to every run in every field, and
        the measurement says that is not enough on its own — so a general skill
        earns its place in the pack by being named at the stage that needs it.
        """
        unreachable_by_construction = {
            "latex-repair",
            "reproducibility-check",
            "venue-checklist",
        }
        rendered = _rendered_prompt_files()
        named_rendered: set[str] = set()
        for path in rendered:
            named_rendered |= _named_skills(path.read_text(encoding="utf-8"), self.known)

        missing = sorted(
            name
            for name in self.known
            if not discipline_of(name)
            and name not in named_rendered
            and name not in unreachable_by_construction
        )
        self.assertEqual(
            missing,
            [],
            "general skills no prompt this configuration renders tells the operator to "
            f"read: {missing}. Name each one at the stage whose decision it covers, or "
            "give it a field prefix so the installer routes it, or delete it.",
        )

    def test_the_allowlist_has_not_outlived_its_cause(self) -> None:
        """An allowlist nobody prunes stops being readable.

        If a skill listed as unreachable is now named in a rendered prompt, the
        entry is stale and the reason it carries is wrong.
        """
        rendered = _rendered_prompt_files()
        named_rendered: set[str] = set()
        for path in rendered:
            named_rendered |= _named_skills(path.read_text(encoding="utf-8"), self.known)
        for skill in ("latex-repair", "reproducibility-check", "venue-checklist"):
            with self.subTest(skill=skill):
                self.assertNotIn(
                    skill,
                    named_rendered,
                    f"`{skill}` is allowlisted as unreachable but a rendered prompt "
                    f"now names it; remove the allowlist entry.",
                )


if __name__ == "__main__":
    unittest.main()
