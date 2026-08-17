"""A flag that is declared and never read is worse than a missing flag.

A missing flag fails loudly: argparse rejects it and the user tries something else. A flag
that parses and is then dropped on the floor is silent — it appears in `--help`, it appears
in the documentation, the run accepts it, and nothing happens. `--routine-model` was in that
state on the `rcb_agent.py` path: declared, documented, and read by no line in the file, so
the one knob whose whole job is to keep the strong model for the stages that need it did
nothing on the only front-end where effort tiering is unconditionally on.

It was found by an audit of the documentation, not by a test, which is the wrong way round.
The scan below is a few lines and would have caught it the day it landed.

The front ends are checked together on purpose. `main.py`, `rcb_agent.py` and `fs_agent.py`
declare overlapping flag sets and have diverged before; a gate that covered only one of them
would be the same defect written fresh.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Flags this repository knowingly parses and does not act on, each with the reason.
#: Deliberately exact rather than a prefix match: adding an entry has to be a decision
#: somebody wrote down, not a line that quietly grew. Both sets are empty today —
#: `--cross-review` and `--cross-review-model` were the last two, exempted on `main.py`
#: because wiring them would have added a Gemini call to every approval on any machine
#: with a project in the environment. `create_cross_reviewer` makes that a decision
#: instead of a side effect: it refuses the auditor behind `--fake-operator`, so the
#: flags are now read on both front ends and neither needs an exemption.
KNOWN_UNWIRED: dict[str, set[str]] = {
    "main.py": set(),
    "rcb_agent.py": set(),
    "fs_agent.py": set(),
}


def _declared_flags(source: str) -> list[str]:
    return re.findall(r'add_argument\(\s*"(--[a-z0-9-]+)"', source)


def _is_read(source: str, flag: str) -> bool:
    attr = flag[2:].replace("-", "_")
    return bool(
        re.search(rf"\bargs\.{attr}\b", source)
        or re.search(rf'getattr\(\s*args\s*,\s*"{attr}"', source)
    )


class EveryDeclaredFlagIsReadTests(unittest.TestCase):
    def test_no_front_end_parses_a_flag_it_never_reads(self) -> None:
        for name, exempt in KNOWN_UNWIRED.items():
            with self.subTest(front_end=name):
                source = (REPO / name).read_text(encoding="utf-8")
                flags = _declared_flags(source)
                self.assertGreater(len(flags), 20, f"{name}: the scan found no flags to check")

                unwired = {flag for flag in flags if not _is_read(source, flag)}
                self.assertEqual(
                    unwired - exempt,
                    set(),
                    f"{name} declares these flags and reads none of them: "
                    f"{sorted(unwired - exempt)}",
                )

    def test_the_exemptions_are_still_needed(self) -> None:
        """An exemption for a flag that is now wired is a lie the next reader inherits."""
        for name, exempt in KNOWN_UNWIRED.items():
            source = (REPO / name).read_text(encoding="utf-8")
            for flag in exempt:
                with self.subTest(front_end=name, flag=flag):
                    self.assertIn(flag, _declared_flags(source), f"{name} no longer declares {flag}")
                    self.assertFalse(
                        _is_read(source, flag),
                        f"{name} now reads {flag}; drop it from KNOWN_UNWIRED",
                    )

    def test_the_scan_would_notice_a_dropped_flag(self) -> None:
        """Guards the regex, not the tree.

        `_is_read` matching too loosely is the way this test rots into a green no-op, and it
        would rot silently: the assertion above passes either way. So a flag that is declared
        and demonstrably absent from the body has to come back as unread.
        """
        fabricated = 'parser.add_argument(\n        "--a-flag-nobody-reads",\n        type=str,\n    )'
        self.assertFalse(_is_read(fabricated, "--a-flag-nobody-reads"))
        self.assertTrue(_is_read(fabricated + "\nprint(args.a_flag_nobody_reads)", "--a-flag-nobody-reads"))


if __name__ == "__main__":
    unittest.main()
