"""Typed information edges: who reads what, declared instead of approximated.

Before this, every context block was gated on a stage-number threshold, so
"which stages need this" was approximated by "everyone from here on". The
approximation was wrong in a way that mattered: the Stage 02 hypothesis context
and the frozen preregistration were both delivered from Stage 05 onward — the
same hypotheses twice, one copy labelled editable, at exactly the stages where
the freeze is the point.

These tests hold the topology, not the wording.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.information_flow import (
    ALL_STAGES,
    CHANNELS,
    Channel,
    ChannelContext,
    dependency_edges,
    inbound_channels,
    render_inbound,
)
from src.utils import STAGES, build_run_paths, ensure_run_layout, write_text


BY_KEY = {channel.key: channel for channel in CHANNELS}
STAGE = {stage.slug: stage for stage in STAGES}


class TopologyTest(unittest.TestCase):
    def test_every_consumer_is_a_real_stage(self) -> None:
        """A typo in a consumer set withholds context silently."""
        for channel in CHANNELS:
            for consumer in channel.consumed_by:
                with self.subTest(channel=channel.key, consumer=consumer):
                    self.assertIn(consumer, ALL_STAGES)

    def test_every_producer_is_a_real_stage_or_declared_external(self) -> None:
        for channel in CHANNELS:
            with self.subTest(channel=channel.key):
                self.assertTrue(channel.produced_by is None or channel.produced_by in ALL_STAGES)

    def test_no_channel_is_consumed_by_nobody(self) -> None:
        orphans = [channel.key for channel in CHANNELS if not channel.consumed_by]
        self.assertEqual(orphans, [])

    def test_nothing_is_delivered_before_it_is_produced(self) -> None:
        """An edge pointing backwards means a stage is shown an empty block."""
        order = {slug: index for index, slug in enumerate(ALL_STAGES)}
        backwards = [
            (channel.key, channel.produced_by, consumer)
            for channel in CHANNELS
            if channel.produced_by
            for consumer in channel.consumed_by
            if order[consumer] < order[channel.produced_by]
        ]
        # research_rounds is the exception and must stay one: a later round
        # re-enters an earlier stage, so its producer is downstream by design.
        unexpected = [item for item in backwards if item[0] != "research_rounds"]
        self.assertEqual(unexpected, [], f"backwards edges: {unexpected}")

    def test_every_narrowing_is_argued_for(self) -> None:
        """A channel that does not reach every stage must say why not."""
        for channel in CHANNELS:
            if len(channel.consumed_by) < len(ALL_STAGES):
                with self.subTest(channel=channel.key):
                    self.assertTrue(
                        channel.rationale.strip(),
                        f"{channel.key} withholds itself from some stage with no stated reason",
                    )

    def test_the_dependency_graph_is_inspectable(self) -> None:
        edges = dependency_edges(CHANNELS)
        self.assertGreater(len(edges), 20)
        self.assertIn(("04_implementation", "06_analysis", "preregistration"), edges)


class HypothesisDuplicationTest(unittest.TestCase):
    """The specific bug the typing exists to fix."""

    def test_the_mutable_hypotheses_stop_where_the_frozen_ones_start(self) -> None:
        mutable = BY_KEY["hypotheses"].consumed_by
        frozen = BY_KEY["preregistration"].consumed_by
        self.assertEqual(mutable & frozen, set(), "the same hypotheses are delivered twice")

    def test_the_frozen_set_covers_every_stage_after_the_freeze(self) -> None:
        frozen = BY_KEY["preregistration"].consumed_by
        for slug in ("05_experimentation", "06_analysis", "07_writing", "08_dissemination"):
            self.assertIn(slug, frozen)

    def test_the_mutable_set_covers_the_stages_before_it(self) -> None:
        mutable = BY_KEY["hypotheses"].consumed_by
        self.assertIn("03_study_design", mutable)
        self.assertIn("04_implementation", mutable)


class DeliveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")

    def _context(self, slug: str) -> ChannelContext:
        return ChannelContext(paths=self.paths, stage=STAGE[slug], attempt_no=1)

    def test_a_stage_receives_only_the_channels_that_name_it(self) -> None:
        served = {c.key for c in inbound_channels(STAGE["01_literature_survey"], CHANNELS)}
        self.assertNotIn("preregistration", served)
        self.assertNotIn("experiment_manifest", served)
        self.assertNotIn("writing_manifest", served)
        self.assertIn("run_configuration", served)

    def test_stage_08_is_not_sent_the_writing_manifest(self) -> None:
        served = {c.key for c in inbound_channels(STAGE["08_dissemination"], CHANNELS)}
        self.assertNotIn("writing_manifest", served)
        self.assertNotIn("idea_pool", served)

    def test_render_reports_which_channels_actually_carried_something(self) -> None:
        """Empty channels must not be reported as delivered — attribution reads this."""
        text, delivered = render_inbound(self._context("06_analysis"), CHANNELS)
        for key in delivered:
            self.assertIn(BY_KEY[key].heading, text)
        self.assertNotIn("preregistration", delivered, "nothing was frozen in this fixture")

    def test_a_channel_with_no_content_contributes_no_heading(self) -> None:
        empty = Channel(
            key="nothing",
            heading="## Nothing",
            produced_by=None,
            consumed_by=frozenset({"01_literature_survey"}),
            build=lambda _context: "",
            rationale="test",
        )
        text, delivered = render_inbound(self._context("01_literature_survey"), (empty,))
        self.assertEqual(text, "")
        self.assertEqual(delivered, [])

    def test_the_preface_travels_with_the_data(self) -> None:
        served = Channel(
            key="thing",
            heading="## Thing",
            produced_by=None,
            consumed_by=frozenset({"01_literature_survey"}),
            build=lambda _context: "body",
            preface="how to read it",
            rationale="test",
        )
        text, _ = render_inbound(self._context("01_literature_survey"), (served,))
        self.assertLess(text.index("how to read it"), text.index("body"))


class NoRelayTest(unittest.TestCase):
    """A node emits what it added, not what it inherited."""

    def test_the_stage_contract_no_longer_mandates_a_relay(self) -> None:
        from src.utils import REQUIRED_STAGE_HEADINGS

        self.assertNotIn("Previously Approved Stage Summaries", REQUIRED_STAGE_HEADINGS)

    def test_the_output_template_does_not_ask_for_one(self) -> None:
        from src.utils import required_stage_output_template

        self.assertNotIn(
            "Previously Approved Stage Summaries", required_stage_output_template(STAGES[0])
        )

    def test_prior_context_still_reaches_the_stage_by_another_route(self) -> None:
        """Removing the relay must not remove the information.

        The node stops restating its inbound edge; `# Approved Memory` still
        carries it. Dropping the section without that would be information loss,
        not compression.
        """
        from src.utils import build_prompt

        prompt = build_prompt(
            STAGES[3],
            "## Body",
            "the goal",
            approved_memory="### Stage 01\n\nwhat stage 01 established",
        )
        self.assertIn("what stage 01 established", prompt)


if __name__ == "__main__":
    unittest.main()
