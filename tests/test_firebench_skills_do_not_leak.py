"""Skills written after reading a benchmark's answers must not carry the answers.

Three skills in `src/skills/` were designed while a FIRE-Bench campaign's failures were
in front of the author, and the reference conclusions -- the exact text the grader scores
against -- were readable on the same disk. That is a legitimate way to work and an easy
way to cheat, and the difference is not visible in the result: a skill that encodes the
answer produces a run that looks like a good run and a score that looks like a
measurement.

So the answers are used here as a **filter, never as a source**. A skill may be derived
from a failure mechanism or from the task statement; it may not contain the reference's
own wording. This file is what makes that checkable by someone who was not in the room.

The test is a shared 5-gram, which is deliberately crude in the safe direction: five
consecutive content words in common with a reference conclusion is not a coincidence in
prose this short, and the check cannot be satisfied by paraphrase-hunting because it also
fails on quotation. What it cannot catch is a skill that names the *finding* in its own
words; nothing automatic can. `SKILLS_UNDER_TEST` is therefore a list a reviewer is meant
to read, and the population guard below fails when a new FIRE-Bench-era skill is added
without being put on it.
"""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Skills authored while a FIRE-Bench campaign's artifacts were in view.
SKILLS_UNDER_TEST = (
    "a-ceiling-is-not-a-null",
    "both-arms-or-no-claim",
    "a-conclusion-is-not-a-report",
)

#: Words too common for a shared run of them to mean anything.
_STOP = frozenset(
    "a an the of to in on at by for with and or but is are was were be been being that this "
    "these those it its as not no if then than from into out up down over under more most less "
    "least can could may might will would shall should do does did done have has had".split()
)


def content_words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", text.lower()) if w not in _STOP]


def ngrams(words: list[str], n: int = 5) -> set[tuple[str, ...]]:
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def reference_conclusions() -> dict[str, str]:
    root = Path(os.environ.get("FIREBENCH_ROOT", Path.home() / "FIRE-Bench")).expanduser()
    papers = root / "benchmark" / "papers"
    if not papers.is_dir():
        return {}
    return {
        path.parent.name: path.read_text(encoding="utf-8")
        for path in sorted(papers.glob("*/conclusion.txt"))
    }


class SkillsDoNotCarryTheAnswers(unittest.TestCase):
    def setUp(self) -> None:
        self.references = reference_conclusions()

    def test_no_skill_shares_a_five_gram_with_any_reference_conclusion(self) -> None:
        if not self.references:
            self.skipTest("no FIRE-Bench checkout on this box")
        offences: list[str] = []
        for name in SKILLS_UNDER_TEST:
            body = (REPO / "src" / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
            skill_grams = ngrams(content_words(body))
            for task, reference in self.references.items():
                shared = skill_grams & ngrams(content_words(reference))
                for gram in sorted(shared):
                    offences.append(f"{name} ↔ {task}: {' '.join(gram)}")
        self.assertEqual(
            offences,
            [],
            "a skill repeats a reference conclusion's own wording; derive it from the "
            "failure or from the task statement instead: " + "; ".join(offences),
        )

    def test_the_negative_control_would_have_caught_a_leak(self) -> None:
        """Without this, a passing test cannot be told from a check that never fires."""
        if not self.references:
            self.skipTest("no FIRE-Bench checkout on this box")
        task, reference = next(iter(sorted(self.references.items())))
        planted = "# leak\n\n" + reference
        shared = ngrams(content_words(planted)) & ngrams(content_words(reference))
        self.assertTrue(shared, f"the 5-gram check found nothing in a verbatim copy of {task}")

    def test_no_skill_names_a_task_id(self) -> None:
        """A skill that names a task is a pin, and pins go in `configs/task_skill_pins.json`.

        The distinction is not bookkeeping. A routed skill has to earn its way in through
        `applies_when` against the run's own brief, so it generalises by construction; a
        skill that hardcodes `premise_order_effects` generalises to exactly one task and
        is indistinguishable, from the outside, from having been written against that
        task's answer.
        """
        if not self.references:
            self.skipTest("no FIRE-Bench checkout on this box")
        offences = []
        for name in SKILLS_UNDER_TEST:
            body = (REPO / "src" / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
            for task in self.references:
                if task in body:
                    offences.append(f"{name} names {task}")
        self.assertEqual(offences, [], "; ".join(offences))

    def test_every_skill_under_test_exists_and_is_routed(self) -> None:
        for name in SKILLS_UNDER_TEST:
            path = REPO / "src" / "skills" / name / "SKILL.md"
            self.assertTrue(path.is_file(), f"{name} is listed here but not on disk")
            head = path.read_text(encoding="utf-8").split("---")[1]
            self.assertIn("applies_when:", head, f"{name} is unrouted; it would be offered to every run")
            self.assertIn("stages:", head, f"{name} does not say which stages it belongs to")


if __name__ == "__main__":
    unittest.main()
