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

**Scope.** The corpus is every set of task statements this box has in bulk:
ResearchClawBench's forty, and FIRE-Bench's thirty-five when that checkout is present. It
was ResearchClawBench alone until a skill written for the claim-counted family failed here
— correctly unreachable over forty checklist briefs, and reachable over thirty-four of
thirty-five of the other kind. Exempting it would have recorded a routing success as a
routing hole, and the next such skill would have been exempted by precedent. A skill can
still be legitimately unreachable over both corpora and useful on a real research goal, so
the exemption list stays and an entry needs a reason.
"""

from __future__ import annotations

import collections
import json
import os
import unittest
from pathlib import Path

from src.run_skills import read_skill_pack, select_run_skills

REPO = Path(__file__).resolve().parent.parent
BENCH = Path("/home/robtang_google_com/RCB/tasks")

#: The second corpus, used when it is on disk. Its briefs are a different research shape --
#: rediscover a published finding under a clock, deliverable a two-sentence conclusion --
#: so a predicate that selects nothing here and everything there is doing its job.
FIRE = Path(os.environ.get("FIREBENCH_ROOT", Path.home() / "FIRE-Bench")).expanduser()

#: Skills that no benchmark brief selects, and the reason that is correct. A skill written
#: for a research shape the forty tasks do not contain belongs here rather than in a regex
#: loosened until something matches.
UNREACHABLE_ON_PURPOSE: dict[str, str] = {}


def briefs() -> dict[str, str]:
    out: dict[str, str] = {}
    if BENCH.is_dir():
        for directory in sorted(BENCH.iterdir()):
            info = directory / "task_info.json"
            if info.is_file():
                out[directory.name] = json.loads(info.read_text(encoding="utf-8"))["task"]
    papers = FIRE / "benchmark" / "papers"
    if papers.is_dir():
        for statement in sorted(papers.glob("*/instruction/instruction.txt")):
            # Prefixed so `task.split("_")[0]` -- which the selector reads as a discipline --
            # cannot collide with a ResearchClawBench field name.
            out["fire_" + statement.parent.parent.name] = statement.read_text(encoding="utf-8")
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
