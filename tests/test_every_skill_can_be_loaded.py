"""A skill nothing can load is worse than no skill.

Writing one is not delivering one. A skill reaches a run only if the discipline filter and
the `applies_when` predicate both let it through, and a predicate written from the *source
study* rather than from the *task brief* passes review, passes the format gate, and selects
nothing for ever.

Two shipped that way in the batch this file was written with. Their predicates —
`binding energy curves?` and `distinguish potential energy surfaces|different charge
states` — name real physics from the paper Chemistry_003 points at, and neither phrase
occurs in the brief the router matches against. Both were pinned, so they would have been
force-installed for that one task and would have looked fine; the routing half was dead and
nobody could have seen it from the file.

Dead weight is not the only cost. The pack's own measured failure is that a run reads about
1.75 skills out of roughly thirty offered, so every description that cannot pay for itself
makes the ones that can slightly less likely to be read.

**Scope.** ResearchClawBench's forty briefs are the corpus, because they are the only task
statements this repository has in bulk. A skill can be legitimately unreachable over them
and useful on a real research goal — so this asserts reachability over the corpus and names
the exemption list for skills that are deliberately outside it. The list is empty today, and
an entry needs a reason.
"""

from __future__ import annotations

import collections
import json
import unittest
from pathlib import Path

from src.run_skills import read_skill_pack, select_run_skills

REPO = Path(__file__).resolve().parent.parent
BENCH = Path("/home/robtang_google_com/RCB/tasks")

_AIRS = (
    "Written for AIRS-Bench, whose deliverable is a predictions file scored by a fixed "
    "metric -- a shape none of the forty ResearchClawBench briefs has, since every one of "
    "those is graded on a report. Reachability was checked on the corpus it was written "
    "from rather than asserted: `tools/skill_selectivity.py --briefs <airs>/tasks/rad` "
    "selects 19 of the 20 AIRS briefs and 0 of the 40 RCB ones. The twentieth, "
    "CodeRetrievalCodeXGlueMRR, has a task paragraph of one sentence that never says what "
    "the deliverable is, so no predicate over task shape can reach it; all twenty are "
    "pinned by identifier, which is what reaches that one. The AIRS briefs are not vendored "
    "here -- they are CC-BY-NC benchmark content and this repository is proprietary -- so "
    "this corpus cannot check them and says so instead of loosening the predicate until "
    "something in the wrong corpus matches."
)


UNREACHABLE_ON_PURPOSE: dict[str, str] = {
    "a-model-you-can-audit-is-not-a-model-that-scores": _AIRS,
    "a-scoreable-file-in-the-first-hour": _AIRS,
    "assume-this-stage-is-the-last-one-you-get": _AIRS,
    "the-audit-trail-is-not-the-deliverable-here": _AIRS,
    "the-row-count-comes-from-the-split-not-the-brief": _AIRS,
    "the-submission-is-the-only-artifact-that-scores": _AIRS,
    "your-survey-already-named-the-method-that-hits-the-number": _AIRS,
}


def briefs() -> dict[str, str]:
    out: dict[str, str] = {}
    for directory in sorted(BENCH.iterdir()):
        info = directory / "task_info.json"
        if info.is_file():
            out[directory.name] = json.loads(info.read_text(encoding="utf-8"))["task"]
    return out


def pinned_for(task: str) -> frozenset[str]:
    table = json.loads((REPO / "configs" / "task_skill_pins.json").read_text(encoding="utf-8"))
    entries = table.get(task) or []
    return frozenset(
        entry if isinstance(entry, str) else entry.get("skill", "") for entry in entries
    )


def reach() -> collections.Counter[str]:
    """Tasks per skill, over the corpus, through the shipped selector."""
    pack = read_skill_pack(REPO / "src" / "skills")
    counted: collections.Counter[str] = collections.Counter()
    for task, brief in briefs().items():
        offered = select_run_skills(
            pack,
            discipline=task.split("_")[0].lower(),
            brief=brief,
            pinned=pinned_for(task),
        )
        for entry in offered:
            counted[entry.name] += 1
    return counted


@unittest.skipUnless(BENCH.is_dir(), "the benchmark checkout is not on this machine")
class EverySkillIsReachableTests(unittest.TestCase):
    def test_every_skill_is_selected_by_at_least_one_brief(self) -> None:
        counted = reach()
        pack = read_skill_pack(REPO / "src" / "skills")
        dead = sorted(
            entry.name
            for entry in pack
            if counted[entry.name] == 0 and entry.name not in UNREACHABLE_ON_PURPOSE
        )
        self.assertEqual(
            dead,
            [],
            "these are installed for no task in the corpus, so nothing can load them; "
            "fix the predicate against the brief, or add an entry to "
            f"UNREACHABLE_ON_PURPOSE with a reason: {dead}",
        )

    def test_the_exemption_list_names_only_skills_that_exist(self) -> None:
        """An exemption outliving its skill makes the list unreadable."""
        names = {entry.name for entry in read_skill_pack(REPO / "src" / "skills")}
        stale = sorted(set(UNREACHABLE_ON_PURPOSE) - names)
        self.assertEqual(stale, [], f"exemptions for skills that are gone: {stale}")

    def test_every_exemption_is_still_needed(self) -> None:
        """The other direction, and the one that rots quietly.

        A skill listed here that a brief now selects is a skill the assertion above
        stopped covering, with a written reason that is no longer true. Loosening a
        predicate is exactly how one gets into that state, and nothing else would say so.
        """
        counted = reach()
        reachable = sorted(name for name in UNREACHABLE_ON_PURPOSE if counted[name])
        self.assertEqual(
            reachable,
            [],
            "these are exempt as unreachable but the corpus now selects them; drop the "
            f"exemption: {reachable}",
        )

    def test_a_predicate_taken_from_the_source_study_is_caught(self) -> None:
        """The control: the check has to fail on the shape that got past review.

        `binding energy curves` is a phrase from the paper Chemistry_003 points at, not from
        the brief the router reads. Substituted here as a predicate, it must leave its skill
        selected by nothing — which is what makes the assertion above load-bearing rather
        than decorative.
        """
        corpus = briefs()
        import re

        self.assertEqual(
            [t for t, b in corpus.items() if re.search("binding energy curves?", b, re.I)],
            [],
            "the control phrase now appears in a brief; pick another for this test",
        )
        self.assertTrue(
            any(re.search("latent charges", b, re.I) for b in corpus.values()),
            "the replacement phrase must actually select something",
        )


if __name__ == "__main__":
    unittest.main()
