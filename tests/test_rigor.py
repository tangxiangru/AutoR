"""One dial in place of four switches.

The tests that matter are the ones about the seam between the level and the individual flags,
because that seam is what makes the dial an interface rather than a fifth switch: an explicit
flag has to win in *both* directions, or `--rigor thorough --no-ideation-panel` is a lie.
"""

from __future__ import annotations

import unittest

from src.rigor import (
    DEFAULT_LEVEL,
    FAST,
    FEATURE_NOTES,
    LEVELS,
    MAX,
    STANDARD,
    THOROUGH,
    describe,
    feature_flags,
    features_for,
    help_text,
    normalize_level,
    resolve,
)


def _resolve(level: str, **overrides) -> dict[str, bool]:
    return resolve(level, {flag: overrides.get(flag) for flag in feature_flags()})


class LevelTests(unittest.TestCase):
    def test_the_default_is_standard(self) -> None:
        self.assertEqual(DEFAULT_LEVEL, STANDARD)

    def test_fast_is_exactly_the_old_behaviour(self) -> None:
        self.assertEqual(features_for(FAST), frozenset())
        self.assertFalse(any(_resolve(FAST).values()))

    def test_the_default_turns_on_only_the_switch_that_lowers_cost(self) -> None:
        # Effort tiers withholds polish rounds from settled stages, so defaulting it on costs
        # nothing and saves something. Nothing else is cheap enough to impose.
        self.assertEqual(features_for(STANDARD), frozenset({"effort_tiers"}))

    def test_the_levels_are_nested(self) -> None:
        # A higher level must never turn something off that a lower one turned on, or the dial
        # stops being a dial.
        for lower, higher in zip(LEVELS, LEVELS[1:]):
            self.assertTrue(
                features_for(lower) <= features_for(higher),
                f"{higher} does not contain {lower}",
            )

    def test_the_costliest_feature_is_last(self) -> None:
        # The review panel bills per gate rather than per run, and is the one the multi-agent
        # feedback literature has direct evidence against.
        self.assertNotIn("review_panel", features_for(THOROUGH))
        self.assertIn("review_panel", features_for(MAX))

    def test_max_turns_everything_on(self) -> None:
        self.assertEqual(features_for(MAX), frozenset(feature_flags()))
        self.assertTrue(all(_resolve(MAX).values()))

    def test_an_unknown_level_falls_back_rather_than_raising(self) -> None:
        self.assertEqual(normalize_level("paranoid"), DEFAULT_LEVEL)
        self.assertEqual(normalize_level(None), DEFAULT_LEVEL)
        self.assertEqual(normalize_level(" Thorough "), THOROUGH)


class OverrideTests(unittest.TestCase):
    """An explicit flag has to beat the level in both directions."""

    def test_a_flag_can_add_something_the_level_omits(self) -> None:
        self.assertTrue(_resolve(STANDARD, review_panel=True)["review_panel"])

    def test_a_flag_can_remove_something_the_level_includes(self) -> None:
        # This is the case a plain store_true could never express.
        self.assertFalse(_resolve(THOROUGH, ideation_panel=False)["ideation_panel"])

    def test_unspecified_means_the_level_decides(self) -> None:
        resolved = _resolve(THOROUGH)
        self.assertTrue(resolved["deliberation"])
        self.assertFalse(resolved["review_panel"])

    def test_an_override_does_not_disturb_the_other_switches(self) -> None:
        resolved = _resolve(THOROUGH, ideation_panel=False)
        self.assertTrue(resolved["effort_tiers"])
        self.assertTrue(resolved["deliberation"])


class ConsistencyTests(unittest.TestCase):
    def test_every_level_only_names_real_switches(self) -> None:
        # A feature listed in a level but missing from feature_flags() would be silently
        # dropped by resolve(), which is the quietest possible way for a dial to do nothing.
        known = set(feature_flags())
        for level in LEVELS:
            self.assertTrue(features_for(level) <= known, level)

    def test_every_switch_is_reachable_from_some_level(self) -> None:
        reachable = set().union(*(features_for(level) for level in LEVELS))
        self.assertEqual(reachable, set(feature_flags()))

    def test_every_switch_has_a_note_explaining_its_placement(self) -> None:
        self.assertEqual(set(FEATURE_NOTES), set(feature_flags()))

    def test_resolve_always_answers_for_every_switch(self) -> None:
        for level in LEVELS:
            self.assertEqual(set(_resolve(level)), set(feature_flags()))


class DescriptionTests(unittest.TestCase):
    def test_a_bare_level_is_described_by_what_it_turned_on(self) -> None:
        self.assertIn("effort tiers", describe(STANDARD, _resolve(STANDARD)))

    def test_a_level_with_nothing_on_says_so(self) -> None:
        self.assertIn("no optional machinery", describe(FAST, _resolve(FAST)))

    def test_the_description_follows_the_overrides_not_the_level(self) -> None:
        resolved = _resolve(STANDARD, review_panel=True)
        self.assertIn("review panel", describe(STANDARD, resolved))

    def test_the_help_lists_every_level_and_the_default(self) -> None:
        text = help_text()
        for level in LEVELS:
            self.assertIn(level, text)
        self.assertIn(f"Defaults to {DEFAULT_LEVEL}", text)
        self.assertIn("--no-ideation-panel", text)


class CommandLineTests(unittest.TestCase):
    def _args(self, *argv):
        import sys
        import main

        original = sys.argv
        sys.argv = ["main.py", "--goal", "x", *argv]
        try:
            args = main.parse_args()
        finally:
            sys.argv = original
        return args

    def test_the_switches_default_to_unset_not_to_false(self) -> None:
        args = self._args()
        # None is what lets an override be distinguished from silence.
        for flag in feature_flags():
            self.assertIsNone(getattr(args, flag), flag)

    def test_the_negative_form_exists_for_every_switch(self) -> None:
        for flag in feature_flags():
            args = self._args(f"--no-{flag.replace('_', '-')}")
            self.assertIs(getattr(args, flag), False, flag)

    def test_the_positive_form_still_works(self) -> None:
        self.assertIs(self._args("--review-panel").review_panel, True)

    def test_the_dial_defaults_to_standard_on_the_command_line(self) -> None:
        self.assertEqual(self._args().rigor, DEFAULT_LEVEL)

    def test_the_benchmark_entry_point_carries_the_same_dial(self) -> None:
        import rcb_agent

        args = rcb_agent.parse_args(["--workspace", "."])
        self.assertEqual(args.rigor, DEFAULT_LEVEL)
        for flag in feature_flags():
            self.assertIsNone(getattr(args, flag), flag)


if __name__ == "__main__":
    unittest.main()
