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

#: Skills that no benchmark brief selects, and the reason that is correct. A skill written
#: for a research shape the forty tasks do not contain belongs here rather than in a regex
#: loosened until something matches.
#:
#: The five below are one decision, not five, and it is a deliberate trade rather than a
#: predicate that missed. They carry ``applies_when: intermediate derivations``, which is
#: a phrase in FrontierScience-Research's own closing instruction to the model rather than
#: a description of a research shape — the thing `src.run_skills`'s module docstring
#: argues against. Measured both ways before it landed: the phrase occurs in **60 of the
#: 60** FrontierScience task statements, through `routing_text`, and in **0 of the 40**
#: ResearchClawBench briefs that are this file's corpus. So they are unreachable here by
#: construction and by design, and a regex loosened until one of the forty matched would
#: be selecting a task nobody wrote them for.
#:
#: The cost is written down rather than argued away: a predicate over a harness's tail
#: sentence generalises to nothing outside that harness. It was taken because the largest
#: measured effect these five are aimed at is a refusal rate, and a predicate covering
#: only some of the sixty tasks would leave the primary endpoint uninterpretable. They are
#: also force-installed by `fs_agent.FS_FORCED_SKILLS`, which is what actually puts them
#: in front of a run; the predicate is the second route, not the first.
_FRONTIERSCIENCE_PREDICATE = (
    "predicate is FrontierScience-Research's own closing instruction ('intermediate "
    "derivations'), measured at 60/60 of its task statements and 0/40 of this corpus's "
    "briefs; force-installed by fs_agent.FS_FORCED_SKILLS rather than routed here"
)

UNREACHABLE_ON_PURPOSE: dict[str, str] = {
    "answer-in-the-symbols-the-problem-printed": _FRONTIERSCIENCE_PREDICATE,
    "bind-every-deliverable-to-the-file-that-is-graded": _FRONTIERSCIENCE_PREDICATE,
    "every-printed-part-gets-its-own-answered-section": _FRONTIERSCIENCE_PREDICATE,
    "grant-the-expected-reading-before-you-depart-from-it": _FRONTIERSCIENCE_PREDICATE,
    "one-visible-line-per-quantity-the-answer-owes": _FRONTIERSCIENCE_PREDICATE,
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

    def test_the_reason_the_five_carry_is_the_measurement_it_states(self) -> None:
        """The exemption's reason is a number, so it is checked rather than believed.

        It claims the predicate occurs in none of the forty briefs. If a brief ever
        contains the phrase the exemption is wrong in the direction that matters — the
        skills would be installed for a ResearchClawBench run they were not written for,
        and the sentence in this file would still say they cannot be.
        """
        import re

        matched = sorted(
            task
            for task, brief in briefs().items()
            if re.search("intermediate derivations", brief, re.I)
        )
        self.assertEqual(
            matched,
            [],
            "the FrontierScience predicate now selects tasks in this corpus, so the "
            f"exemption's stated 0/40 is stale: {matched}",
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
