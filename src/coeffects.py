"""What each stage read when it was approved, and whether it still reads the same thing.

A stage's approval is a claim about a state of the run: *given these inputs, this output
was accepted*. Nothing recorded the first half. Staleness was decided by arithmetic on the
stage number — :func:`src.manifest.rollback_to_stage` marked everything after the target —
and that is the approximation :mod:`src.information_flow` was written to remove one layer
up:

    every context block was gated by a threshold on the stage number, so "who needs this"
    was approximated by "everyone from here on"

The information layer replaced the threshold with a declared topology: each ``Channel``
names the stage that produces it and the stages that read it. The lifecycle layer never
got the same treatment, so the same approximation is still deciding whose approval
survives a change.

Two things it gets wrong, in opposite directions.

**It misses a consumer that sits earlier than its producer.** ``research_rounds`` is
produced at Stage 06 and read at Stages 02 through 07 — Stages 03 to 06 repeat as a round,
so information genuinely flows backwards. A change at Stage 06 leaves every earlier
consumer's approval standing, because 2 is not greater than 6.

**It fires on stages that read nothing that moved.** Rolling back to Stage 03 marks Stage
07 stale whether or not anything Stage 07 declares has changed. That is usually right, and
it is right for a reason nobody checked rather than by a rule anyone can state.

This module states the rule. A stage's *committed view* is a digest per declared channel,
taken when the stage is approved. Its *current view* is the same digest taken now. The
stage is stale when they differ, and the channels that differ are the reason — which the
declared topology turns into the name of the stage that caused it.

**The view is over what the stage reads, not over the files behind it.** A channel is a
rendered block, and rendering is what the stage actually saw; going through the files
instead would need a second declaration of which file backs which channel, and two
spellings of one mapping is how they drift apart. It also gives the comparison the right
grain: two states are the same exactly when no channel this stage reads can tell them
apart.

**Only channels with a producer are in the view.** ``run_configuration``,
``project_context``, ``artifact_index`` and the rest come from outside the stage graph;
they are the environment the run sits in rather than a dependency on another stage's work,
and a rollback does not withdraw them.

**And one producer channel is excluded, by name and with a reason.**
``experiment_manifest`` is AutoR's own inventory, rewritten at every stage boundary with a
fresh ``generated_at``, so its digest moves on byte-identical research. Measured: two
renders either side of one ``write_experiment_manifest`` differ while the other eight
producer channels are unchanged. Left in, it would mark Stages 05 to 08 stale at every
boundary — the same flicker ``src.artifact_index`` documents for the rubric. What it
inventories is the artifacts, and those are versioned by :mod:`src.provenance`, so a change
that matters is visible through the channels that read them.
:class:`ChannelViewStabilityTests` is what keeps that exclusion honest: every producer
channel must either render stably across a boundary rewrite or be named here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping, Sequence

from .information_flow import CHANNELS, Channel, ChannelContext, dependency_edges
from .utils import RunPaths, StageSpec

#: Producer channels whose rendering moves without the research moving. Named rather
#: than detected, because the alternative — normalising a volatile field out of the
#: rendered text — is a second parser for a format the channel already owns.
VOLATILE_CHANNELS = frozenset({"experiment_manifest"})


def declared_inputs(stage: StageSpec, channels: Sequence[Channel] = CHANNELS) -> list[Channel]:
    """The channels this stage reads that another stage produces.

    The stage's coeffect specification, read off the same declaration the prompt is
    assembled from, so a stage cannot depend on something it did not declare and cannot
    declare something it does not read.
    """

    return [
        channel
        for channel in channels
        if channel.produced_by is not None
        and channel.key not in VOLATILE_CHANNELS
        and stage.slug in channel.consumed_by
    ]


def _digest(block: str) -> str:
    return hashlib.sha256(block.encode("utf-8")).hexdigest()[:16]


def current_view(
    paths: RunPaths, stage: StageSpec, channels: Sequence[Channel] = CHANNELS
) -> dict[str, str]:
    """A digest per declared channel, as this stage would read it right now.

    A channel that raises is recorded under the exception's name rather than as absent.
    An unreadable input and a missing one are different states, and a stage approved
    against one should be stale when the run is in the other.
    """

    context = ChannelContext(paths=paths, stage=stage, attempt_no=0)
    view: dict[str, str] = {}
    for channel in declared_inputs(stage, channels):
        try:
            rendered = channel.build(context) or ""
        except Exception as error:  # noqa: BLE001 - the class is the observation
            rendered = f"<unreadable: {type(error).__name__}>"
        view[channel.key] = _digest(rendered)
    return view


def drifted_channels(
    paths: RunPaths,
    stage: StageSpec,
    committed: Mapping[str, str],
    channels: Sequence[Channel] = CHANNELS,
) -> list[str]:
    """Which of the stage's declared channels no longer read as they did at approval.

    An empty ``committed`` returns nothing. A stage approved before this module existed
    recorded no view, and reading "no record" as "everything changed" would mark every
    approved stage of every resumed run stale at once — the fail-open rule
    :mod:`src.provenance` uses, for the same reason.
    """

    if not committed:
        return []
    current = current_view(paths, stage, channels)
    drifted = [key for key, digest in current.items() if committed.get(key) != digest]
    # A channel the stage committed to and no longer declares is also a change: the
    # topology moved under an approval that was given against the old one.
    drifted.extend(key for key in committed if key not in current)
    return sorted(set(drifted))


def producer_of(key: str, channels: Sequence[Channel] = CHANNELS) -> str:
    """Which stage produces a channel, for saying *why* a consumer went stale.

    Read off :func:`src.information_flow.dependency_edges` rather than the channel list,
    so the explanation and the topology come from one place. The edge list is the
    inspectable form of the graph the module docstring promises, and this is the
    inspection: a drifted consumer is reported with the producer that moved.
    """

    for producer, _consumer, channel_key in dependency_edges(tuple(channels)):
        if channel_key == key:
            return producer
    return "run_config"


@dataclass(frozen=True)
class Drift:
    """One approved stage whose declared inputs have moved since it was approved."""

    stage_slug: str
    channels: tuple[str, ...]

    def render(self, all_channels: Sequence[Channel] = CHANNELS) -> str:
        causes = ", ".join(
            f"{key} (from {producer_of(key, all_channels)})" for key in self.channels
        )
        return f"{self.stage_slug}: {causes}"


def drift_across_run(
    paths: RunPaths,
    entries: Sequence[object],
    channels: Sequence[Channel] = CHANNELS,
) -> list[Drift]:
    """Every approved stage whose committed view no longer matches, and what moved.

    ``entries`` is the manifest's stage list. Typed loosely on purpose: importing
    ``StageManifestEntry`` here would close a cycle, since :mod:`src.manifest` is what
    calls this.
    """

    from .utils import STAGES

    by_slug = {stage.slug: stage for stage in STAGES}
    drifts: list[Drift] = []
    for entry in entries:
        if not getattr(entry, "approved", False):
            continue
        stage = by_slug.get(getattr(entry, "slug", ""))
        if stage is None:
            continue
        committed = getattr(entry, "committed_view", None) or {}
        moved = drifted_channels(paths, stage, committed, channels)
        if moved:
            drifts.append(Drift(stage_slug=stage.slug, channels=tuple(moved)))
    return drifts


def format_drift(drifts: Sequence[Drift], channels: Sequence[Channel] = CHANNELS) -> str:
    if not drifts:
        return "No approved stage reads anything that has moved."
    lines = [f"{len(drifts)} approved stage(s) read something that has moved:"]
    lines.extend(f"- {drift.render(channels)}" for drift in drifts)
    return "\n".join(lines)
