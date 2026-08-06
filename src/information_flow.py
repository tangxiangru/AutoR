"""What each stage receives, declared per edge instead of broadcast to everyone.

``src.stage_graph`` types the edges for *control* — when a move may be taken.
This types them for *information* — what a move carries. They are different
questions and the second one had no answer: every context block was gated by a
threshold on the stage number, so "who needs this" was approximated by "everyone
from here on".

Three things follow from writing the dependency down instead of approximating it.

**The prompt stops carrying what a stage does not read.** Measured on a real run
before this change, the Stage 02 hypothesis context and the frozen
preregistration were both injected from Stage 05 onward — the same H1, twice,
one of them labelled editable. That is not only 148 wasted words; it puts a
mutable copy of the hypotheses next to the frozen one at exactly the stages
where the freeze is the point.

**Attribution becomes possible.** ``src.archive`` learns which *moves* pay.
A move carries a payload; until the payload has a name, "this edge helped"
cannot become "this information helped".

**The graph is inspectable.** ``dependency_edges()`` returns the producer →
consumer pairs, so the information topology can be printed, tested, and diffed
rather than reconstructed by reading thirteen ``if`` statements.

A channel is deliberately allowed to have no producer (``produced_by=None``):
run configuration and the researcher profile come from outside the stage graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .utils import RunPaths, StageSpec


#: Stage slugs, so a typo in a consumer set fails a test rather than silently
#: withholding context from a stage that needed it.
ALL_STAGES = (
    "00_intake",
    "01_literature_survey",
    "02_hypothesis_generation",
    "03_study_design",
    "04_implementation",
    "05_experimentation",
    "06_analysis",
    "07_writing",
    "08_dissemination",
)


def _from(slug: str) -> frozenset[str]:
    """Every stage from ``slug`` onward — the old threshold, written explicitly.

    Used only where a channel genuinely binds every later stage. Most channels
    do not, and saying so is the point of this module.
    """
    index = ALL_STAGES.index(slug)
    return frozenset(ALL_STAGES[index:])


@dataclass(frozen=True)
class Channel:
    """One typed information edge into a set of stages."""

    key: str
    heading: str
    #: The stage that creates this information. ``None`` for context that comes
    #: from the run configuration or a bootstrap rather than from a stage.
    produced_by: str | None
    #: The stages that actually read it. This is the edge.
    consumed_by: frozenset[str]
    #: Returns the rendered block, or None/"" when there is nothing to send.
    build: Callable[["ChannelContext"], str | None]
    #: How to read the block. Kept next to the data so the instruction cannot
    #: drift away from the thing it describes.
    preface: str = ""
    #: Why these consumers and not others. Read by the test that guards the
    #: topology, so a narrowing has to be argued for rather than just made.
    rationale: str = ""

    def serves(self, stage: StageSpec) -> bool:
        return stage.slug in self.consumed_by


@dataclass
class ChannelContext:
    """Everything a channel builder may need, so builders stay pure functions."""

    paths: RunPaths
    stage: StageSpec
    attempt_no: int
    manager: object = None
    extras: dict[str, object] = field(default_factory=dict)


def _render(block: str | None, channel: Channel) -> str:
    body = (block or "").strip()
    if not body:
        return ""
    parts = [channel.heading, ""]
    if channel.preface:
        parts.extend([channel.preface.strip(), ""])
    parts.append(body)
    return "\n".join(parts)


def inbound_channels(stage: StageSpec, channels: tuple[Channel, ...]) -> list[Channel]:
    return [channel for channel in channels if channel.serves(stage)]


def render_inbound(
    context: ChannelContext, channels: tuple[Channel, ...]
) -> tuple[str, list[str]]:
    """Compose this stage's inbound context. Returns the text and the keys used.

    The key list is the point of the return tuple: it is what lets a run record
    which information actually reached a stage, which is the input attribution
    needs.
    """
    blocks: list[str] = []
    delivered: list[str] = []
    for channel in inbound_channels(context.stage, channels):
        rendered = _render(channel.build(context), channel)
        if rendered:
            blocks.append(rendered)
            delivered.append(channel.key)
    return ("\n\n".join(blocks), delivered)


def dependency_edges(channels: tuple[Channel, ...]) -> list[tuple[str, str, str]]:
    """(producer, consumer, channel key) for every typed information edge."""
    return sorted(
        (channel.produced_by or "run_config", consumer, channel.key)
        for channel in channels
        for consumer in channel.consumed_by
    )


# ---------------------------------------------------------------------------
# The channels
# ---------------------------------------------------------------------------


def _venue(context: ChannelContext) -> str:
    from .utils import format_venue_for_prompt

    return format_venue_for_prompt(context.paths)


def _artifact_index(context: ChannelContext) -> str:
    from .artifact_index import format_artifact_index_for_prompt, write_artifact_index

    index = write_artifact_index(context.paths)
    return (
        f"Run-wide artifact index: `{context.paths.artifact_index.resolve()}`\n\n"
        + format_artifact_index_for_prompt(index)
    )


def _experiment_manifest(context: ChannelContext) -> str:
    from .experiment_manifest import (
        format_experiment_manifest_for_prompt,
        write_experiment_manifest,
    )

    manifest = write_experiment_manifest(context.paths)
    return (
        f"Standard experiment manifest: `{context.paths.experiment_manifest.resolve()}`\n\n"
        + format_experiment_manifest_for_prompt(manifest)
    )


def _intake_resources(context: ChannelContext) -> str | None:
    from .intake import format_resources_for_intake_prompt, load_intake_context

    ctx = load_intake_context(context.paths)
    if not ctx or not ctx.resources:
        return None
    return format_resources_for_intake_prompt(ctx.resources)


def _idea_pool(context: ChannelContext) -> str | None:
    manager = context.manager
    if manager is None or getattr(manager, "ideation_panel", None) is None:
        return None
    return manager._build_idea_pool(context.paths, context.stage, context.attempt_no)  # noqa: SLF001


def _writing_manifest(context: ChannelContext) -> str:
    from .writing_manifest import build_writing_manifest, format_manifest_for_prompt

    return format_manifest_for_prompt(build_writing_manifest(context.paths))


def _researcher_profile(context: ChannelContext) -> str | None:
    from .bootstrap import format_profile_for_prompt

    return format_profile_for_prompt(context.paths, stage_slug=context.stage.slug)


def _decision_ledger(context: ChannelContext) -> str | None:
    from .utils import build_decision_ledger_context

    return build_decision_ledger_context(context.paths, upto_stage=context.stage)


def _hypotheses(context: ChannelContext) -> str | None:
    from .utils import build_hypothesis_context

    return build_hypothesis_context(context.paths)


def _preregistration(context: ChannelContext) -> str | None:
    from .preregistration import format_preregistration_for_prompt, load_preregistration

    prereg = load_preregistration(context.paths)
    return format_preregistration_for_prompt(prereg) if prereg is not None else None


def _rounds(context: ChannelContext) -> str | None:
    from .research_rounds import format_rounds_for_prompt

    return format_rounds_for_prompt(context.paths)


def _validity_findings(context: ChannelContext) -> str | None:
    from .validity_review import format_findings_for_prompt

    return format_findings_for_prompt(context.paths, context.stage)


def _verdicts(context: ChannelContext) -> str | None:
    from .preregistration import format_outcomes_for_prompt

    return format_outcomes_for_prompt(context.paths)


CHANNELS: tuple[Channel, ...] = (
    Channel(
        key="run_configuration",
        heading="## Run Configuration",
        produced_by=None,
        consumed_by=_from("00_intake"),
        build=_venue,
        rationale="Venue and output format bind every stage's deliverable shape.",
    ),
    Channel(
        key="artifact_index",
        heading="## Structured Artifact Index",
        produced_by=None,
        consumed_by=frozenset(
            {
                "03_study_design",
                "04_implementation",
                "05_experimentation",
                "06_analysis",
                "07_writing",
                "08_dissemination",
            }
        ),
        build=_artifact_index,
        rationale=(
            "An index of data, results and figures. Stages 00-02 produce no such "
            "artifacts and read none, so the index is empty noise there."
        ),
    ),
    Channel(
        key="experiment_manifest",
        heading="## Experiment Bundle Manifest",
        produced_by="05_experimentation",
        consumed_by=frozenset(
            {"05_experimentation", "06_analysis", "07_writing", "08_dissemination"}
        ),
        build=_experiment_manifest,
        rationale="Stage 05 writes it and re-reads it across attempts; 06-08 analyse and package it.",
    ),
    Channel(
        key="intake_resources",
        heading="## Pre-Loaded Resources (already in workspace)",
        produced_by=None,
        consumed_by=frozenset({"00_intake", "01_literature_survey"}),
        build=_intake_resources,
        rationale=(
            "Materials the user supplied. Stage 01 is the first stage that reads them "
            "as evidence; before this they reached only Stage 00, which merely records them."
        ),
    ),
    Channel(
        key="idea_pool",
        heading="## Candidate Hypothesis Pool",
        produced_by=None,
        consumed_by=frozenset({"02_hypothesis_generation"}),
        build=_idea_pool,
        rationale="The ideation panel's candidates exist to be chosen from, once.",
    ),
    Channel(
        key="writing_manifest",
        heading="## Writing Manifest",
        produced_by=None,
        consumed_by=frozenset({"07_writing"}),
        build=_writing_manifest,
        rationale="A manifest of what the manuscript must assemble.",
    ),
    Channel(
        key="researcher_profile",
        heading="# Researcher Profile (from paper corpus bootstrap)",
        produced_by=None,
        consumed_by=frozenset(
            {"01_literature_survey", "02_hypothesis_generation", "07_writing"}
        ),
        build=_researcher_profile,
        rationale=(
            "Themes, citation neighbourhood and writing style. It shapes what to survey, "
            "what to hypothesise and how to write — not how to run an experiment."
        ),
    ),
    Channel(
        key="decision_ledger",
        heading="# Decision Ledger (from prior stages)",
        produced_by="01_literature_survey",
        consumed_by=_from("02_hypothesis_generation"),
        preface=(
            "The following decisions, assumptions, and open questions were recorded in "
            "earlier stages. Respect locked decisions and accepted assumptions. Address "
            "open questions when relevant."
        ),
        build=_decision_ledger,
        rationale="A locked decision binds every stage after it. This one genuinely is broadcast.",
    ),
    Channel(
        key="hypotheses",
        heading="# Hypothesis Context (from Stage 02)",
        produced_by="02_hypothesis_generation",
        consumed_by=frozenset({"03_study_design", "04_implementation"}),
        preface=(
            "The following typed claims were approved in Stage 02.\n"
            "- Treat **Theoretical Propositions** as accepted premises rather than direct experimental targets.\n"
            "- Treat **Empirical Hypotheses** as the claims that downstream implementation, experimentation, and analysis should test.\n"
            "- Treat **Paper Claims (Provisional)** as narrative framing only until evidence supports them."
        ),
        build=_hypotheses,
        rationale=(
            "Stops at Stage 04 because the preregistration is frozen at Stage 04's "
            "approval and supersedes it. Sending both put the same H1 into every later "
            "prompt twice, one copy labelled editable — next to the frozen copy, at "
            "exactly the stages where the freeze is the point."
        ),
    ),
    Channel(
        key="preregistration",
        heading="# Preregistered Hypotheses (frozen — not editable)",
        produced_by="04_implementation",
        consumed_by=_from("05_experimentation"),
        build=_preregistration,
        rationale="From the freeze onward this is the authoritative statement of what the run predicted.",
    ),
    Channel(
        key="research_rounds",
        heading="# Earlier Research Rounds",
        produced_by="06_analysis",
        consumed_by=frozenset(
            {
                "02_hypothesis_generation",
                "03_study_design",
                "04_implementation",
                "05_experimentation",
                "06_analysis",
                "07_writing",
            }
        ),
        build=_rounds,
        rationale=(
            "A later round must not repeat an earlier one's design, and Stage 07 must know "
            "whether the run converged. Stage 08 reads the round ledger from disk instead."
        ),
    ),
    Channel(
        key="validity_findings",
        heading="# Adversarial Validity Findings (each must be answered)",
        produced_by="05_experimentation",
        consumed_by=frozenset({"06_analysis", "07_writing"}),
        build=_validity_findings,
        rationale="Only the stage that owes an answer needs the objections.",
    ),
    Channel(
        key="hypothesis_verdicts",
        heading="# Hypothesis Verdicts",
        produced_by="06_analysis",
        consumed_by=frozenset({"07_writing", "08_dissemination"}),
        build=_verdicts,
        rationale="Writing may only claim what came out supported; dissemination reports the same.",
    ),
)
