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
from unittest.mock import patch
from pathlib import Path

from src.run_skills import read_skill_pack
from src.information_flow import (
    ALL_STAGES,
    CHANNELS,
    UNBOUNDED_BY_CONSTRUCTION,
    Channel,
    ChannelContext,
    _render,
    dependency_edges,
    inbound_channels,
    render_inbound,
)
from src.utils import (
    MAX_REPORT_FIGURES,
    STAGES,
    build_run_paths,
    ensure_run_config,
    ensure_run_layout,
    write_text,
)


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


class EveryChannelDeclaresWhatItMaySpendTest(unittest.TestCase):
    """A budget was a per-builder convention, and a convention has no floor.

    Three channels capped themselves and argued for it in their own module docstrings --
    `withdrawal_ledger`'s five records, `settled_reasoning`'s four cruxes and six hundred
    characters a field, `artifact_index`'s five entries a category. Each argument lived
    inside the builder that made it, so a channel added without one was unbounded and
    nothing anywhere said so. `Channel.max_chars` is the rule; this is what stops the
    exemption from being the easy answer.
    """

    def test_a_channel_declares_a_budget_or_says_why_it_cannot_grow(self) -> None:
        undeclared = [
            channel.key
            for channel in CHANNELS
            if channel.max_chars is None and channel.key not in UNBOUNDED_BY_CONSTRUCTION
        ]
        self.assertEqual(
            undeclared, [],
            "give it a max_chars, or name it in UNBOUNDED_BY_CONSTRUCTION with the "
            "structure that bounds it",
        )

    def test_the_exemption_list_names_no_channel_that_is_gone(self) -> None:
        """The other direction: a reason for a channel that no longer exists is a reason
        nobody will notice has stopped applying."""
        live = {channel.key for channel in CHANNELS}
        self.assertEqual([key for key in UNBOUNDED_BY_CONSTRUCTION if key not in live], [])

    def test_every_exemption_carries_a_reason_long_enough_to_be_one(self) -> None:
        short = [
            key for key, reason in UNBOUNDED_BY_CONSTRUCTION.items() if len(reason.strip()) < 40
        ]
        self.assertEqual(short, [], "a reason too short to check is not a reason")

    def test_the_rule_is_the_programs_and_not_only_this_files(self) -> None:
        """It raises at import, like `Edge.__post_init__` on an unregistered guard.

        A rule that lives only in a test is a rule that passes for anyone who does not
        run it. The population here is source rather than run data, so raising can only
        happen while someone is editing the channel table.
        """
        from src.information_flow import _every_channel_declares_what_it_may_spend

        with patch("src.information_flow.CHANNELS", (
            Channel(key="nameless", heading="## X", produced_by=None,
                    consumed_by=frozenset(), build=lambda _ctx: "x"),
        )):
            with self.assertRaises(ValueError) as caught:
                _every_channel_declares_what_it_may_spend()
        self.assertIn("nameless", str(caught.exception))

    def test_a_reason_for_a_channel_that_is_gone_also_raises(self) -> None:
        from src.information_flow import _every_channel_declares_what_it_may_spend

        stale = dict(UNBOUNDED_BY_CONSTRUCTION)
        stale["retired"] = "a reason long enough to look like a real one, and stale"
        with patch("src.information_flow.UNBOUNDED_BY_CONSTRUCTION", stale):
            with self.assertRaises(ValueError) as caught:
                _every_channel_declares_what_it_may_spend()
        self.assertIn("retired", str(caught.exception))

    def test_a_declared_budget_is_a_positive_number(self) -> None:
        self.assertEqual(
            [c.key for c in CHANNELS if c.max_chars is not None and c.max_chars <= 0], []
        )


class TheBudgetIsEnforcedAndSaysWhatItDroppedTest(unittest.TestCase):
    """A silent truncation is the worst of the three available behaviours.

    The model cannot tell a channel that had little to say from one whose tail was taken,
    and neither can a reader of `prompt_cache/`.
    """

    def _channel(self, budget: int | None, body: str) -> Channel:
        return Channel(
            key="probe", heading="## Probe", produced_by=None,
            consumed_by=frozenset({STAGES[0].slug}), build=lambda _ctx: body,
            max_chars=budget,
        )

    def _render_probe(self, budget: int | None, body: str) -> str:
        return _render(body, self._channel(budget, body))

    def test_a_block_inside_its_budget_is_untouched(self) -> None:
        rendered = self._render_probe(100, "short")
        self.assertIn("short", rendered)
        self.assertNotIn("dropped", rendered)

    def test_a_block_over_budget_is_clipped_and_says_by_how_much(self) -> None:
        rendered = self._render_probe(50, "x" * 200)
        self.assertIn("150 character(s) dropped", rendered)
        self.assertIn("budget is 50", rendered)

    def test_the_head_is_what_survives(self) -> None:
        """These blocks lead with what is open. Two callers elsewhere keep the tail
        instead, reading a verdict at the end of a transcript, and implement their own
        head-drop for that reason -- the direction is the reader's decision."""
        rendered = self._render_probe(10, "HEADHEADHEADtailtail")
        self.assertIn("HEADHEADHE", rendered)
        self.assertNotIn("tailtail", rendered)

    def test_no_budget_means_no_clip(self) -> None:
        """The control on the exemption: a channel on the list is genuinely not clipped."""
        rendered = self._render_probe(None, "y" * 5000)
        self.assertNotIn("dropped", rendered)
        self.assertIn("y" * 5000, rendered)

    def test_the_heading_and_preface_are_outside_the_budget(self) -> None:
        channel = Channel(
            key="probe", heading="## Probe", produced_by=None,
            consumed_by=frozenset({STAGES[0].slug}), build=lambda _ctx: "z" * 100,
            preface="Read this first.", max_chars=10,
        )
        rendered = _render("z" * 100, channel)
        self.assertIn("## Probe", rendered)
        self.assertIn("Read this first.", rendered)


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


class DeliverableContractTest(unittest.TestCase):
    """The constraint that decides most of the work has to arrive before the work.

    ``MAX_REPORT_FIGURES`` used to reach Stage 07 and nowhere else: the run was
    told how many figures a reader would see four stages after it chose which
    figures to make, when the only move left was deleting the weakest. These
    tests hold the arrival time and the derivation, not the sentences.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")

    def _context(self, slug: str) -> ChannelContext:
        return ChannelContext(paths=self.paths, stage=STAGE[slug], attempt_no=1)

    def _render(self, slug: str) -> str:
        return BY_KEY["report_contract"].build(self._context(slug))

    def test_the_planning_stage_is_told_the_deliverable_shape(self) -> None:
        served = {c.key for c in inbound_channels(STAGE["03_study_design"], CHANNELS)}
        self.assertIn("report_contract", served)

    def test_the_stages_that_write_and_run_code_are_not(self) -> None:
        """A figure ceiling at 04/05 invites plotting instead of implementing."""
        for slug in ("04_implementation", "05_experimentation"):
            served = {c.key for c in inbound_channels(STAGE[slug], CHANNELS)}
            with self.subTest(stage=slug):
                self.assertNotIn("report_contract", served)

    def test_the_ceiling_is_derived_from_the_constant_and_not_typed_out(self) -> None:
        """One encoding of the rule. Move the constant, the prompt moves with it."""
        from unittest.mock import patch

        import src.utils as utils

        with patch.object(utils, "MAX_REPORT_FIGURES", 7):
            moved = self._render("03_study_design")
        self.assertIn("7", moved)
        self.assertNotIn("5 figures", moved)

    def test_a_latex_run_is_never_shipped_a_five_figure_ceiling(self) -> None:
        """The ceiling is markdown's, not every run's: a venue paper carries more."""
        ensure_run_config(self.paths, output_format="latex")
        latex = self._render("03_study_design")
        self.assertNotIn(str(MAX_REPORT_FIGURES), latex)
        self.assertIn("venue", latex.lower())

    def test_the_shared_channels_carry_nothing_benchmark_specific(self) -> None:
        """The scoring numbers are one benchmark's and travel in its own goal text.

        Every AutoR run receives these two blocks, so a weighting, a grader or a
        benchmark name in either one would ship one benchmark's scoring model to
        runs that have no grader at all. Scanned on the delivered surface — what
        the agent reads — not on the module source, because a docstring
        explaining the rule is not a prompt.

        The scan covers only the text *AutoR* wrote. ``report_plan``'s body is
        the run's own plan read back, so the tokens do not apply to it: a
        perfectly good ``shows`` says "Accuracy (%) against context length", and
        a scan that included it would either fail on the suite's own plan
        fixture or, worse, pass because this test happens to run without one.
        The empty-population trap is the reason the split is explicit rather
        than incidental: ``report_plan``'s heading and preface are AutoR's and
        are scanned; its body is the agent's and is not.
        """
        for key in ("report_contract", "report_plan"):
            channel = BY_KEY[key]
            autor_authored = key != "report_plan"
            for slug in sorted(channel.consumed_by):
                body = (channel.build(self._context(slug)) or "") if autor_authored else ""
                delivered = " ".join([channel.heading, channel.preface, body]).lower()
                for token in ("researchclawbench", "judge", "rubric", "checklist", "%"):
                    with self.subTest(channel=key, stage=slug, token=token):
                        self.assertNotIn(token, delivered)

    def test_the_contract_scan_runs_over_a_non_empty_body(self) -> None:
        """The control for the scan above: an empty body passes every token check."""
        for slug in sorted(BY_KEY["report_contract"].consumed_by):
            with self.subTest(stage=slug):
                self.assertTrue((BY_KEY["report_contract"].build(self._context(slug)) or "").strip())


class ReportPlanChannelTest(unittest.TestCase):
    """Stage 03's first outbound edge: a plan nobody reads is documentation."""

    def test_the_plan_is_produced_by_the_stage_that_plans(self) -> None:
        self.assertEqual(BY_KEY["report_plan"].produced_by, "03_study_design")

    def test_the_plan_reaches_the_stages_that_act_on_it(self) -> None:
        consumers = BY_KEY["report_plan"].consumed_by
        for slug in ("04_implementation", "06_analysis", "07_writing"):
            with self.subTest(stage=slug):
                self.assertIn(slug, consumers)

    def test_the_planning_stage_reads_its_own_plan_back(self) -> None:
        """A second round amends the plan; it cannot amend what it is not shown."""
        self.assertIn("03_study_design", BY_KEY["report_plan"].consumed_by)

    def test_the_stage_that_has_to_emit_the_source_files_is_sent_it(self) -> None:
        """Every slot names a ``source_artifact``, and Stage 05 is the stage that
        writes those files. The Stage 06 gate refuses a slot whose source does
        not exist, and by Stage 06 the stage that could have produced it has
        run: withholding the paths from 05 makes that refusal unfixable. The
        Stage 05 prompt already instructs the run to "write them at the paths
        the plan names", which it cannot do from a plan it is not shown."""
        self.assertIn("05_experimentation", BY_KEY["report_plan"].consumed_by)

    def test_no_stage_before_the_drawing_stage_is_told_to_draw(self) -> None:
        """The plan reaches 04 and 05 as files to emit, not as figures to plot.

        The preface is the only instruction that travels with the plan, and it
        is the same text for every consumer. A blanket "produce them" would
        reach the two stages whose job is to write and run code, contradicting
        Stage 03's own "produce no figure files at this stage" and inviting
        exactly the plotting-instead-of-running that keeps the figure ceiling
        out of 04 and 05.
        """
        preface = BY_KEY["report_plan"].preface.lower()
        self.assertIn("do not draw a figure before stage 06", preface)
        self.assertIn("stage 06 draws the figures", preface)

    def test_every_channel_produced_by_a_stage_reaches_a_later_one(self) -> None:
        """Producing for nobody downstream is a record, not a channel."""
        order = {slug: index for index, slug in enumerate(ALL_STAGES)}
        for channel in CHANNELS:
            if channel.produced_by is None:
                continue
            later = [
                consumer
                for consumer in channel.consumed_by
                if order[consumer] > order[channel.produced_by]
            ]
            with self.subTest(channel=channel.key):
                self.assertTrue(later, f"{channel.key} is consumed only by its own producer")


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


class TaskShapedSkillsChannelTest(unittest.TestCase):
    """The router's decision reaches the stage, or the routing bought nothing.

    Installing a skill only for the runs it suits is half a mechanism. The other
    half is telling the run: the operator sees an undifferentiated listing of about
    thirty skills — sixteen from AutoR plus Claude Code's own — and cannot tell that
    two of them were chosen against this brief. Measured over a 40-task arm, the
    pack drew 78 `Skill` calls in 789 hours; the one skill a prompt named in the
    imperative accounted for 31 of them, and the three a prompt said were "installed
    for this stage" accounted for none.

    So this channel is the router speaking, and these tests hold that it speaks only
    where it should: at the stages a selected skill asked for, and nowhere else.
    """

    class _FakeManager:
        def __init__(self, entries, forced=frozenset()):
            self._installed_skills = entries
            self._forced_skills = frozenset(forced)

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.paths = build_run_paths(root / "run_0001")
        ensure_run_layout(self.paths)
        pack = root / "pack"
        for name, extra in (
            ("scoped-design", "applies_when: widget\nstages: 03_study_design"),
            ("forced-design", "applies_when: nothing here\nstages: 03_study_design"),
            ("always-on", ""),
        ):
            (pack / name).mkdir(parents=True)
            (pack / name / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Use when a widget appears, at design time.\n"
                f"{extra}\n---\n\nbody\n",
                encoding="utf-8",
            )
        self.entries = read_skill_pack(pack)

    def _channel(self) -> Channel:
        (channel,) = [c for c in CHANNELS if c.key == "task_shaped_skills"]
        return channel

    def _render(self, slug: str, entries, forced=frozenset()) -> str:
        text, _ = render_inbound(
            ChannelContext(
                paths=self.paths,
                stage=STAGE[slug],
                attempt_no=1,
                manager=self._FakeManager(entries, forced),
            ),
            (self._channel(),),
        )
        return text

    def test_the_channel_is_in_the_shipped_topology(self) -> None:
        self.assertIn("task_shaped_skills", {channel.key for channel in CHANNELS})

    def test_a_selected_skill_reaches_the_stage_it_asked_for(self) -> None:
        text = self._render("03_study_design", self.entries)
        self.assertIn("scoped-design", text)
        self.assertIn("Skills Selected For This Task", text)

    def test_it_reaches_no_other_stage(self) -> None:
        for slug in ("01_literature_survey", "05_experimentation", "07_writing"):
            with self.subTest(stage=slug):
                self.assertEqual(self._render(slug, self.entries), "")

    def test_an_unconditional_skill_is_never_announced(self) -> None:
        """The pull mechanism's whole trade is not paying for the pack in every prompt."""
        for slug in STAGE:
            with self.subTest(stage=slug):
                self.assertNotIn("always-on", self._render(slug, self.entries))

    def test_a_run_that_matched_nothing_gets_no_block(self) -> None:
        for slug in STAGE:
            with self.subTest(stage=slug):
                self.assertEqual(self._render(slug, []), "")

    def test_a_manager_without_the_attribute_does_not_raise(self) -> None:
        """A channel builder that throws takes the whole prompt down with it."""
        text, _ = render_inbound(
            ChannelContext(paths=self.paths, stage=STAGE["03_study_design"], attempt_no=1),
            (self._channel(),),
        )
        self.assertEqual(text, "")

    def test_a_skill_the_front_end_forced_reaches_the_stage_it_named(self) -> None:
        """The third input to the same channel, and the one whose predicate matched
        nothing: `forced-design` says `applies_when: nothing here`, so the router would
        never have selected it and only the front end's decision puts it in the prompt.
        """
        text = self._render("03_study_design", self.entries, frozenset({"forced-design"}))
        self.assertIn("forced-design", text)
        self.assertIn("installed on every run of this benchmark", text)

    def test_a_forced_skill_is_told_apart_from_a_shape_match_in_the_same_block(self) -> None:
        """One block, two banners. A reader of the prompt has to be able to say which
        of the two decisions put a given name there, because they are different
        evidence and the run config distinguishes them too."""
        text = self._render("03_study_design", self.entries, frozenset({"forced-design"}))
        self.assertIn("scoped-design", text)
        self.assertLess(
            text.index("scoped-design"),
            text.index("installed on every run of this benchmark"),
        )

    def test_a_run_that_forced_nothing_carries_no_forced_banner(self) -> None:
        """The control for the two above.

        Rendered from the entries the router alone would have installed — the same
        stage, the same channel, one input removed — so the banner's presence in those
        two tests is the seam and not the template.
        """
        routed = [entry for entry in self.entries if entry.name != "forced-design"]
        text = self._render("03_study_design", routed)
        self.assertIn("scoped-design", text)
        self.assertNotIn("forced-design", text)
        self.assertNotIn("installed on every run of this benchmark", text)
