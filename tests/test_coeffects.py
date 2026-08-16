"""Staleness asked of the declared topology instead of the stage number.

:class:`ChannelViewStabilityTests` is the one that keeps :data:`VOLATILE_CHANNELS`
honest: every producer channel either renders the same twice across a boundary rewrite,
or is named there with a reason. Without it, the exclusion list is an assertion about the
channels rather than a measurement of them.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from src.coeffects import (
    VOLATILE_CHANNELS,
    Drift,
    current_view,
    declared_inputs,
    drift_across_run,
    drifted_channels,
    format_drift,
    producer_of,
)
from src.experiment_manifest import write_experiment_manifest
from src.information_flow import CHANNELS, ChannelContext
from src.manifest import (
    ensure_run_manifest,
    mark_stage_approved_manifest,
    rollback_to_stage,
)
from src.provenance import observe
from src.utils import STAGES, build_run_paths, ensure_run_layout, write_text

STAGE_02, STAGE_03, STAGE_04, STAGE_05, STAGE_06, STAGE_07 = (
    STAGES[1],
    STAGES[2],
    STAGES[3],
    STAGES[4],
    STAGES[5],
    STAGES[6],
)


class CoeffectTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(self.paths)
        ensure_run_manifest(self.paths)

    def write_rounds(self, decision: str) -> None:
        write_text(
            self.paths.research_rounds,
            json.dumps(
                {
                    "rounds": [
                        {"round": 1, "decision": decision, "rationale": "because", "acted_on": True}
                    ]
                }
            )
            + "\n",
        )


class DeclaredInputsTests(CoeffectTestCase):
    def test_only_channels_another_stage_produces_are_declared_inputs(self) -> None:
        keys = {channel.key for channel in declared_inputs(STAGE_07)}

        self.assertIn("preregistration", keys)
        self.assertNotIn(
            "run_configuration",
            keys,
            "ambient context is the environment the run sits in, not a dependency on a stage",
        )

    def test_a_volatile_channel_is_not_a_declared_input(self) -> None:
        keys = {channel.key for channel in declared_inputs(STAGE_07)}
        self.assertNotIn("experiment_manifest", keys)

    def test_the_topology_is_respected_rather_than_the_numbering(self) -> None:
        """``research_rounds`` is produced at 06 and read at 02. Information flows back."""

        keys = {channel.key for channel in declared_inputs(STAGE_02)}
        self.assertIn("research_rounds", keys)
        self.assertEqual(producer_of("research_rounds"), STAGE_06.slug)


class ChannelViewStabilityTests(CoeffectTestCase):
    def test_every_producer_channel_is_stable_across_a_boundary_or_named_volatile(self) -> None:
        """The measurement behind :data:`VOLATILE_CHANNELS`.

        A channel whose digest moves without the research moving would mark its consumers
        stale at every stage boundary. If this fails, either the channel got a volatile
        field and should lose it, or it belongs in ``VOLATILE_CHANNELS`` with a reason.
        """

        write_text(self.paths.results_dir / "metrics.json", '{"accuracy": 0.9}\n')
        write_text(self.paths.experimental_protocol, '{"baselines": [{"name": "control"}]}\n')
        write_text(self.paths.report_plan, '{"figures": []}\n')
        write_text(self.paths.preregistration, '{"hypotheses": [{"id": "H1", "type": "empirical"}]}\n')
        write_text(self.paths.hypothesis_outcomes, '{"outcomes": []}\n')
        self.write_rounds("converged")
        write_experiment_manifest(self.paths)

        def render(stage, channel):
            context = ChannelContext(paths=self.paths, stage=stage, attempt_no=0)
            return channel.build(context) or ""

        unstable: list[str] = []
        for channel in CHANNELS:
            if channel.produced_by is None:
                continue
            consumer = next(
                (stage for stage in STAGES if stage.slug in channel.consumed_by), None
            )
            if consumer is None:
                continue
            before = render(consumer, channel)
            write_experiment_manifest(self.paths)  # the boundary rewrite
            after = render(consumer, channel)
            if before != after and channel.key not in VOLATILE_CHANNELS:
                unstable.append(channel.key)

        self.assertEqual(
            unstable,
            [],
            "these producer channels render differently on unchanged research; fix the "
            f"channel or name it in VOLATILE_CHANNELS with a reason: {unstable}",
        )

    def test_the_named_volatile_channel_really_is_volatile(self) -> None:
        """An exclusion nobody can contradict is an assertion, not a measurement.

        Two claims, and together they are the volatility. The rendered block carries
        ``generated_at``; and rendering the channel *rewrites the file it renders*, so that
        field is refreshed from the clock on every render. Whenever two stage boundaries
        fall in different seconds — which ``src.artifact_index`` records as often — the
        digest moves on research that did not.

        Asserted this way rather than by rendering twice and comparing, because two renders
        inside one test land in the same second and the comparison passes for the wrong
        reason. That is the same clock-tick hazard, met while trying to measure it.
        """

        channel = next(item for item in CHANNELS if item.key == "experiment_manifest")
        context = ChannelContext(paths=self.paths, stage=STAGE_07, attempt_no=0)

        first = channel.build(context) or ""
        stamp = json.loads(self.paths.experiment_manifest.read_text(encoding="utf-8"))["generated_at"]
        self.assertIn(stamp, first, "the block carries the manifest's wall-clock stamp")

        # The clock is moved rather than waited for. Two renders inside one test land in
        # the same second, and the file's mtime granularity is coarser than the gap
        # between them, so neither a re-render nor a stat can tell the two apart here --
        # the clock-tick hazard `src.artifact_index` documents, met while measuring it.
        with mock.patch("src.experiment_manifest.datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2031, 1, 1, 0, 0, 0)
            later = channel.build(context) or ""

        self.assertNotEqual(
            first,
            later,
            "experiment_manifest is excluded from the view because rendering it rewrites "
            "the file it renders, refreshing a wall-clock stamp the block carries; if that "
            "stops being true, drop it from VOLATILE_CHANNELS rather than leaving an "
            "exclusion nothing measures",
        )


class DriftTests(CoeffectTestCase):
    def test_no_committed_view_means_no_drift(self) -> None:
        """Fail-open. A run approved before this field existed must not go stale at once."""

        self.assertEqual(drifted_channels(self.paths, STAGE_07, {}), [])

    def test_an_unchanged_input_does_not_drift(self) -> None:
        write_text(self.paths.preregistration, '{"hypotheses": [{"id": "H1"}]}\n')
        committed = current_view(self.paths, STAGE_07)

        self.assertEqual(drifted_channels(self.paths, STAGE_07, committed), [])

    def test_a_changed_input_drifts_and_names_itself(self) -> None:
        self.write_rounds("refine_design")
        committed = current_view(self.paths, STAGE_02)

        self.write_rounds("abandon")

        self.assertEqual(drifted_channels(self.paths, STAGE_02, committed), ["research_rounds"])

    def test_a_change_the_stage_does_not_declare_is_not_drift(self) -> None:
        write_text(self.paths.preregistration, '{"hypotheses": [{"id": "H1"}]}\n')
        committed = current_view(self.paths, STAGE_02)

        write_text(self.paths.preregistration, '{"hypotheses": [{"id": "H2"}]}\n')

        self.assertNotIn("preregistration", {c.key for c in declared_inputs(STAGE_02)})
        self.assertEqual(drifted_channels(self.paths, STAGE_02, committed), [])

    def test_drift_is_reported_with_the_stage_that_caused_it(self) -> None:
        rendered = Drift(stage_slug=STAGE_02.slug, channels=("research_rounds",)).render()
        self.assertIn("research_rounds", rendered)
        self.assertIn(STAGE_06.slug, rendered)

    def test_only_approved_stages_are_examined(self) -> None:
        self.write_rounds("refine_design")
        mark_stage_approved_manifest(self.paths, STAGE_02, 1, [])
        self.write_rounds("abandon")

        manifest = ensure_run_manifest(self.paths)
        drifts = drift_across_run(self.paths, manifest.stages)

        self.assertEqual([drift.stage_slug for drift in drifts], [STAGE_02.slug])
        self.assertIn(STAGE_02.slug, format_drift(drifts))


class ApprovalRecordsWhatItReadTests(CoeffectTestCase):
    def test_an_approval_records_the_view_it_was_given_against(self) -> None:
        self.write_rounds("converged")
        mark_stage_approved_manifest(self.paths, STAGE_02, 1, [])

        entry = next(
            item for item in ensure_run_manifest(self.paths).stages if item.slug == STAGE_02.slug
        )
        self.assertIn("research_rounds", entry.committed_view)

    def test_the_view_survives_a_manifest_round_trip(self) -> None:
        self.write_rounds("converged")
        mark_stage_approved_manifest(self.paths, STAGE_02, 1, [])
        first = next(
            item for item in ensure_run_manifest(self.paths).stages if item.slug == STAGE_02.slug
        ).committed_view

        reloaded = next(
            item for item in ensure_run_manifest(self.paths).stages if item.slug == STAGE_02.slug
        ).committed_view

        self.assertEqual(first, reloaded)
        self.assertTrue(first)


class RollbackReadsTheTopologyTests(CoeffectTestCase):
    def test_a_rollback_invalidates_an_earlier_stage_that_reads_what_moved(self) -> None:
        """The hole a stage-number rule cannot see.

        Stage 02 declares ``research_rounds``, which Stage 06 produces — Stages 03 to 06
        repeat as a round, so information flows backwards. Rolling back to Stage 03 used to
        leave Stage 02 approved against a round record that had moved under it, because 2
        is not greater than 3.
        """

        self.write_rounds("refine_design")
        mark_stage_approved_manifest(self.paths, STAGE_02, 1, [])
        self.write_rounds("abandon")

        rollback_to_stage(self.paths, STAGE_03, "the design was wrong")

        entry = next(
            item for item in ensure_run_manifest(self.paths).stages if item.slug == STAGE_02.slug
        )
        self.assertTrue(entry.stale)
        self.assertFalse(entry.approved)
        self.assertIn("reads a channel the rollback moved", entry.invalidated_reason or "")

    def test_an_earlier_stage_that_reads_nothing_that_moved_keeps_its_approval(self) -> None:
        """The narrowing has to be real, or the rule is the old one with more machinery."""

        self.write_rounds("converged")
        mark_stage_approved_manifest(self.paths, STAGE_02, 1, [])

        rollback_to_stage(self.paths, STAGE_03, "the design was wrong")

        entry = next(
            item for item in ensure_run_manifest(self.paths).stages if item.slug == STAGE_02.slug
        )
        self.assertTrue(entry.approved)
        self.assertFalse(entry.stale)

    def test_the_stage_number_rule_still_holds_above_the_target(self) -> None:
        """The topology is added to the numbering, not substituted for it.

        Above the target the recovery has withdrawn the stage's own output, so its approval
        is void whatever it reads. Replacing the numbering here would leave a stage approved
        with its artifacts deleted.
        """

        write_text(self.paths.data_dir / "late.csv", "id\n1\n")
        observe(self.paths, STAGE_05)
        mark_stage_approved_manifest(self.paths, STAGE_05, 1, [])

        rollback_to_stage(self.paths, STAGE_03, "the design was wrong")

        entry = next(
            item for item in ensure_run_manifest(self.paths).stages if item.slug == STAGE_05.slug
        )
        self.assertTrue(entry.stale)
        self.assertFalse((self.paths.data_dir / "late.csv").exists())


if __name__ == "__main__":
    unittest.main()
