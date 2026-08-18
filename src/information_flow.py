"""What each stage receives, declared per edge instead of broadcast to everyone.

``src.stage_graph`` types the edges for *control* — when a move may be taken.
This types them for *information* — what a move carries. They are different
questions and the second one had no answer: every context block was gated by a
threshold on the stage number, so "who needs this" was approximated by "everyone
from here on".

Three things follow from writing the dependency down instead of approximating it.

**The prompt stops carrying what a stage does not read.** Before this change the
Stage 02 hypothesis context and the frozen preregistration were both injected
from Stage 05 onward — the same H1, twice, one of them labelled editable. The
wasted words were the smaller half of it: it put a mutable copy of the
hypotheses next to the frozen one at exactly the stages where the freeze is the
point. What survives as a checkable statement is the topology, not the word
count — ``hypotheses.consumed_by`` now stops at ``04_implementation`` and no
longer intersects ``preregistration.consumed_by``, asserted in
``tests/test_information_flow.py``.

**Attribution becomes possible.** ``src.archive`` learns which *moves* pay.
A move carries a payload; until the payload has a name, "this edge helped"
cannot become "this information helped".

**The graph is inspectable.** ``dependency_edges()`` returns the producer →
consumer pairs, so the information topology can be printed, tested, and diffed
rather than reconstructed by reading a pile of ``if`` statements.

A channel is deliberately allowed to have no producer (``produced_by=None``):
run configuration, the researcher profile, the deliverable contract and the
scan of an existing project repository come from outside the stage graph.

**A renderer with no caller is not a channel.** Two of them shipped that way.
``format_protocol_for_prompt`` was imported by nothing outside its own tests,
so the primary metric, planned seed count and per-baseline tuning budgets that
Stage 03 declares reached no prompt as data — Stage 05's template names the file
path, and the templates for 04, 06 and 07 do not mention the protocol at all.
``format_project_context_for_prompt`` was worse than uncalled: ``src.manager``
imported the name and never called it, so a grep for the symbol answered "wired"
and a run started with ``--project-root`` walked the stage graph over a
repository no prompt described. ``experimental_protocol`` and ``project_context`` are the
two edges; ``test_no_prompt_renderer_is_imported_without_being_called`` is the
guard for the trap that hid the second one.

**A constraint has to arrive while it can still be obeyed.** The figure ceiling
was the worst case of the opposite: ``MAX_REPORT_FIGURES`` reached Stage 07 and
nowhere earlier, so the run learned how many figures a reader would see four
stages after it decided which figures to make, when the only remaining move was
to delete the weakest. ``report_contract`` delivers the shape of the deliverable
to the stage that plans the work (03) as well as the stages that draw (06) and
publish (07) it, and ``report_plan`` carries the resulting choice forward. An
edge here is cheaper than a repair there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .stage_graph import REVISIT_EDGES
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
    #: The most characters this channel's body may spend in a stage prompt.
    #:
    #: A budget was a per-builder convention before this field existed:
    #: ``withdrawal_ledger`` caps itself at five records, ``settled_reasoning`` at four
    #: cruxes and six hundred characters a field, ``artifact_index`` at five entries a
    #: category -- and each of those arguments lives inside the builder that makes it,
    #: so a channel added without one is unbounded and nothing says so. ``_render``
    #: enforces this, which is what turns the convention into a rule.
    #:
    #: ``None`` means the channel is structurally bounded by what it renders and needs
    #: no ceiling. That is a claim, and ``test_information_flow`` makes it a checked one:
    #: every channel either declares a budget or is named in ``UNBOUNDED_BY_CONSTRUCTION``
    #: with the reason it cannot grow, so the exemption list cannot grow by assertion.
    #:
    #: What the numbers are measured against: over 197 archived stage prompts the whole
    #: rendered channel set -- everything under ``# Stage Instructions`` after the static
    #: template -- has a median of 25.6 KB and a p90 of 78.6 KB, and the prompt it sits
    #: in runs to a median of 277 KB by Stage 07 with a maximum of 1.79 MB.
    max_chars: int | None = None

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
    """The channel's block, clipped to what it declared it may spend.

    The clip keeps the head and says how much it dropped, in the prompt itself. A silent
    truncation is the worst of the three available behaviours: the model cannot tell a
    channel that had little to say from one whose tail was taken, and neither can a
    reader of ``prompt_cache/``. Keeping the head rather than the tail because these
    blocks are written most-important-first -- a rendered ledger leads with what is open,
    a findings list with what was raised -- and two callers elsewhere that need the tail
    (``approval_agent`` and ``review_panel``, reading a verdict at the end of a
    transcript) implement their own head-drop for that reason. The direction is a
    per-reader decision and this is the readers' side of it.

    The heading and preface are outside the budget. They are the harness's own words
    about how to read the block, they are a fixed cost per channel, and clipping them
    would remove the instruction before the thing it describes.
    """

    body = (block or "").strip()
    if not body:
        return ""
    if channel.max_chars is not None and len(body) > channel.max_chars:
        dropped = len(body) - channel.max_chars
        body = (
            body[: channel.max_chars].rstrip()
            + f"\n\n_[{dropped} character(s) dropped: this channel's budget is "
            f"{channel.max_chars}.]_"
        )
    parts = [channel.heading, ""]
    if channel.preface:
        parts.extend([channel.preface.strip(), ""])
    parts.append(body)
    return "\n".join(parts)


def inbound_channels(stage: StageSpec, channels: tuple[Channel, ...]) -> list[Channel]:
    return [channel for channel in channels if channel.serves(stage)]


def render_inbound(
    context: ChannelContext,
    channels: tuple[Channel, ...],
    sizes: "list[tuple[str, int, int | None]] | None" = None,
) -> tuple[str, list[str]]:
    """Compose this stage's inbound context. Returns the text and the keys used.

    The key list is the point of the return tuple: it is what lets a run record
    which information actually reached a stage, which is the input attribution
    needs.

    *sizes* is a sink -- ``(key, characters, budget)`` appended per delivered channel --
    and not a third element of the tuple, in the shape ``CostTally`` and ``CustodyWatch``
    already have. It is a sink for a harder reason than theirs, though: **a builder may
    write.** ``_artifact_index`` calls ``write_artifact_index`` and ``_experiment_manifest``
    rewrites the manifest with a fresh timestamp -- which is the very drift
    ``docs/iclr/composable-stage-graphs.md`` excludes from the committed view by name. A
    second pass to measure what the first pass rendered would run those writes twice per
    prompt. The measurement has to come off the same render as the text.
    """

    blocks: list[str] = []
    delivered: list[str] = []
    for channel in inbound_channels(context.stage, channels):
        rendered = _render(channel.build(context), channel)
        if rendered:
            blocks.append(rendered)
            delivered.append(channel.key)
            if sizes is not None:
                sizes.append((channel.key, len(rendered), channel.max_chars))
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


def _report_contract(context: ChannelContext) -> str:
    """The shape of the scored deliverable, sent to the stages that can still act on it.

    Everything here is true of *any* AutoR run in the given output format, and
    the figure ceiling is read from ``MAX_REPORT_FIGURES`` rather than written
    out, so the prompt cannot drift away from the gate that enforces it
    (``validate_markdown_report``). Nothing benchmark-specific belongs in this
    block: no grader, no weighting, no scoring model. A benchmark that scores a
    report its own way says so in its own goal text, which reaches every stage
    verbatim through ``user_input``.

    Conditioned on the output format because the ceiling is not universal: a
    latex run targets a venue that routinely carries eight or ten figures, and
    shipping "at most five" there would damage the paper rather than focus it.

    The deliverable's *path* is not repeated here — ``## Run Configuration``
    already names it in the same prompt, and this block is about the shape of
    the thing, not its location.
    """
    from .utils import MAX_REPORT_FIGURES, selected_output_format

    if selected_output_format(context.paths) != "markdown":
        return "\n".join(
            [
                "- The scored deliverable is one compiled paper, and the venue named in "
                "`## Run Configuration` sets how many figures it may carry. Plan one "
                "figure per claim.",
                "- Choose the figures now, against the claims they carry. A figure chosen "
                "at the end is chosen by whatever happened to exist by then.",
            ]
        )
    return "\n".join(
        [
            "- The scored deliverable is one markdown report, named in "
            "`## Run Configuration`. Everything else the run produces is evidence for it, "
            "not a substitute for it.",
            f"- At most {MAX_REPORT_FIGURES} figures reach the reader, and Stage 07's gate "
            "refuses a report that publishes more. A sixth figure is not extra coverage; "
            "it is work nobody sees.",
            "- Choose the figures now, against the claims they carry. A figure chosen at "
            "the end is chosen by whatever happened to exist by then.",
            "- A slot that answers no question the other slots leave open is a slot spent "
            "twice. Fewer figures, each settling a different claim, beats a full set of "
            "views of one result.",
            "- The ceiling is not a target and there is no floor. Count the questions a "
            "figure has to settle and plan that many: some reports rest on one, and a "
            "report whose result is a single number may honestly carry none. Padding "
            "toward the ceiling costs the figures that were carrying a claim.",
        ]
    )


def _report_plan(context: ChannelContext) -> str | None:
    from .report_plan import format_report_plan_for_prompt, load_report_plan

    plan = load_report_plan(context.paths)
    return format_report_plan_for_prompt(plan) if plan is not None else None


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
    # Widening the candidate pool is for a stage that still has to choose. A stage running
    # routine has already been told its decisions are made, so paying a proposer panel to
    # re-open them is the expensive configuration landing where its benefit does not.
    plan = getattr(manager, "effort_plan", None)
    if plan is not None and plan.is_routine(context.stage):
        return None
    return manager._build_idea_pool(context.paths, context.stage, context.attempt_no)  # noqa: SLF001


def _withdrawal_history(context: ChannelContext) -> str | None:
    from .withdrawal_ledger import format_withdrawal_history_for_prompt

    return format_withdrawal_history_for_prompt(context.paths, context.stage)


def _settled_reasoning(context: ChannelContext) -> str | None:
    from .settled_reasoning import build_block

    return build_block(context.paths)


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


def _experimental_protocol(context: ChannelContext) -> str | None:
    from .experimental_protocol import (
        format_protocol_for_prompt,
        load_experimental_protocol,
    )

    protocol = load_experimental_protocol(context.paths)
    return format_protocol_for_prompt(protocol) if protocol is not None else None


def _project_context(context: ChannelContext) -> str | None:
    from .project_bootstrap import format_project_context_for_prompt

    return format_project_context_for_prompt(context.paths)


def _rounds(context: ChannelContext) -> str | None:
    from .research_rounds import format_rounds_for_prompt

    return format_rounds_for_prompt(context.paths)


def _validity_findings(context: ChannelContext) -> str | None:
    from .validity_review import format_findings_for_prompt

    return format_findings_for_prompt(context.paths, context.stage)


def _verdicts(context: ChannelContext) -> str | None:
    from .preregistration import format_outcomes_for_prompt

    return format_outcomes_for_prompt(context.paths)


#: Every stage a backward edge can land on. Derived rather than listed: the withdrawal
#: history has to reach whoever can repeat the withdrawn decision, and that set is already
#: written down as the targets of ``REVISIT_EDGES``. A new backward edge brings its target
#: into the readership with it.
_REVISIT_TARGETS: frozenset[str] = frozenset(edge.target for edge in REVISIT_EDGES)



def _task_shaped_skills(context: ChannelContext) -> str:
    """The skills a predicate selected for *this* run's brief, named for this stage.

    Most of the pack is offered to every run, and the model chooses from a listing
    of thirty entries -- sixteen from AutoR plus the fourteen Claude Code ships.
    Measured over a 40-task arm it chose 1.75 of them per run, in 789 hours of
    agent time. A skill written for one shape of task cannot win that competition
    by description alone, and it should not have to: the router already decided it
    was relevant before the run started.

    So this channel is the router telling the stage what it decided, and nothing
    more. It carries only skills whose `applies_when` matched this brief and whose
    `stages` names this stage, so a run whose brief matches nothing gets no block
    and pays nothing. The unconditional pack stays pull-based, which is the trade
    the skill mechanism was built to make.

    Three inputs rather than one, because three different things can put a skill in
    front of a stage and the renderer announces each under its own banner: a
    predicate over the brief, a pin on this task's identifier, and a front end that
    forces a set on every run of its benchmark. Each is read with `getattr` and a
    default, because a channel builder that raises takes the whole prompt down with
    it and the test doubles in this suite carry only the attributes they need.
    """
    from .run_skills import format_skills_for_prompt

    entries = getattr(context.manager, "_installed_skills", None) or []
    pinned = getattr(context.manager, "_pinned_skills", None) or frozenset()
    forced = getattr(context.manager, "_forced_skills", None) or frozenset()
    return format_skills_for_prompt(
        list(entries), context.stage.slug, frozenset(pinned), frozenset(forced)
    )


#: Channels that declare no budget, and the reason each cannot grow.
#:
#: The list is the point. `Channel.max_chars` defaulting to ``None`` would otherwise make
#: "unbounded" the thing that happens when nobody thought about it, which is how a
#: convention decays -- so a channel is either given a ceiling or named here with the
#: structure that bounds it, and ``test_information_flow`` fails on a channel that is
#: neither. An exemption list that cannot grow by assertion is the same device
#: ``docs/iclr/composable-stage-graphs.md`` uses for the channel excluded from the
#: committed view.
UNBOUNDED_BY_CONSTRUCTION: dict[str, str] = {
    "run_configuration": (
        "a fixed block from the venue registry and the run config; measured at 508-522 "
        "characters over 320 renders, and it has no input that grows"
    ),
    "report_contract": (
        "static prose conditioned on the output format, with the figure ceiling read from "
        "MAX_REPORT_FIGURES; 934 characters on every one of 120 renders"
    ),
    "settled_reasoning": (
        "the builder is the ceiling: MAX_CRUXES=4, MAX_REJECTED=5 and MAX_FIELD_CHARS=600, "
        "argued in its own module docstring"
    ),
    "withdrawal_history": (
        "PROMPT_WITHDRAWAL_LIMIT=5 records, with the same argument this field generalises "
        "-- 'an unbounded block would grow until it crowded out the work the stage is "
        "being asked to do'"
    ),
}


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
        key="report_contract",
        heading="## Deliverable Contract",
        produced_by=None,
        consumed_by=frozenset({"03_study_design", "06_analysis", "07_writing"}),
        build=_report_contract,
        rationale=(
            "The shape of the scored deliverable binds the stage that plans the figures "
            "(03), the stage that draws them (06) and the stage that publishes them (07). "
            "Stages 04 and 05 write and run code: a ceiling on how many figures reach the "
            "reader changes nothing about what to implement or execute, and sending it "
            "there would invite plotting instead of running. Stages 00-02 have no "
            "deliverable to shape yet, and Stage 08 packages a report it cannot change."
        ),
    ),
    Channel(
        key="artifact_index",
        max_chars=6_000,
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
        max_chars=6_000,
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
        max_chars=4_000,
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
        key="project_context",
        max_chars=24_000,
        heading="# Existing Project Repository (from the project bootstrap)",
        produced_by=None,
        consumed_by=_from("01_literature_survey"),
        build=_project_context,
        preface=(
            "This run was started against a repository that already existed. What follows "
            "is what the scan found in it, not what this run produced.\n"
            "- An assessment is a reading of the files, not a result. Confirm it against "
            "the repository before building on it, and say so in your stage summary when it "
            "turns out to be wrong.\n"
            "- Every stage the scan assessed is listed, each marked either carried forward "
            "— this run accepted that stage as already done — or still owed. The carried-"
            "forward ones were also written into `# Approved Memory` as stage summaries, so "
            "you may meet them twice; that is deliberate, because a revisit to a stage below "
            "the re-entry point rewrites that section and drops them, and this block is then "
            "the only copy left."
        ),
        rationale=(
            "`recommend_entry_stage` returns any stage from 01 to 08, so no fixed early set "
            "of readers is right: the run that re-enters at Stage 07 to write up results "
            "that already exist is the run that most needs to be told what the repository "
            "holds, and a `{03,04,05,07}` would withhold it from exactly that run. Stage 00 "
            "is the one stage that provably cannot read it — `run()` calls "
            "`_run_project_bootstrap` after `_run_intake`, so no scan exists while intake is "
            "running and the block would be empty every time. On a run without "
            "`--project-root` the channel is silent at every stage, which is what an "
            "unconditional edge to a conditional artifact should look like. This block does "
            "overlap `# Approved Memory` — `_adopt_project_bootstrap_baseline` copies each "
            "below-entry assessment into a stage summary — and the overlap is kept rather "
            "than trimmed: `append_approved_stage_summary` retains only the entries numbered "
            "below the stage it writes, so approving the `07_writing → 01_literature_survey` "
            "revisit on a run that re-entered at 07 erases Stages 02-06 from memory, and the "
            "scan's reading of them survives only here."
        ),
    ),
    Channel(
        key="idea_pool",
        max_chars=24_000,
        heading="## Candidate Hypothesis Pool",
        produced_by=None,
        consumed_by=frozenset({"02_hypothesis_generation"}),
        build=_idea_pool,
        rationale="The ideation panel's candidates exist to be chosen from, once.",
    ),
    Channel(
        key="writing_manifest",
        max_chars=8_000,
        heading="## Writing Manifest",
        produced_by=None,
        consumed_by=frozenset({"07_writing"}),
        build=_writing_manifest,
        rationale="A manifest of what the manuscript must assemble.",
    ),
    Channel(
        key="researcher_profile",
        max_chars=12_000,
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
        max_chars=24_000,
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
        max_chars=40_000,
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
        max_chars=40_000,
        heading="# Preregistered Hypotheses (frozen — not editable)",
        produced_by="04_implementation",
        consumed_by=_from("05_experimentation"),
        build=_preregistration,
        rationale="From the freeze onward this is the authoritative statement of what the run predicted.",
    ),
    Channel(
        key="experimental_protocol",
        max_chars=12_000,
        heading="# Experimental Protocol (declared at Stage 03)",
        produced_by="03_study_design",
        consumed_by=frozenset(
            {"04_implementation", "05_experimentation", "06_analysis", "07_writing"}
        ),
        build=_experimental_protocol,
        preface=(
            "Stage 04 builds for this protocol and Stage 05 spends it. A harness fixed to "
            "one seed, or with no way to give a baseline the budget declared below, cannot "
            "be made to obey the protocol at Stage 05 without going back through the "
            "`05_experimentation → 04_implementation` revisit edge and rebuilding it — an "
            "edge here is cheaper than that repair. Stage 04's smoke run is not the "
            "experiment: build for the planned seeds and the declared budgets, do not spend "
            "them there."
        ),
        rationale=(
            "Stage 03 writes it and four later stages are bound by it, none of which is "
            "shown its contents anywhere else. Stage 05's template names the file path and "
            "states the obligations it creates; the templates for 04, 06 and 07 do not "
            "mention it. 04 builds the harness that has to run `planned_seeds` runs and "
            "each declared baseline. 05 owes each baseline the budget it declared. 06 may "
            "not replace the primary metric with one that came out better, and "
            "`validate_outcome_statistics` refuses a `supported` or `refuted` verdict "
            "without `statistics.n_seeds` — the count the design planned reaches its prompt "
            "here or not at all. 07 reports that metric and states a budget shortfall as a "
            "limitation. Stage 03 is the author and its own template carries the schema and "
            "the rules, so re-sending the file to its writer would restate the instruction "
            "rather than deliver anything; Stages 00-02 precede the design; Stage 08 "
            "packages a comparison it cannot re-run."
        ),
    ),
    Channel(
        key="settled_reasoning",
        heading="# Reasoning This Run Already Settled",
        produced_by=None,
        consumed_by=frozenset({"07_writing"}),
        preface=(
            "The panels below argued these points during the run and the arguments were "
            "recorded rather than published. They belong in **Discussion**, after the "
            "results — the opening of the report belongs to the numbers.\n"
            "- A settled question, the alternatives rejected, and what would overturn the "
            "answer is the substance of a real discussion section. Written as *\"we chose X "
            "over Y because Z, and W would overturn it\"*, it is an argument; pasted as a "
            "list of everything anyone said, it is padding, and padding is scored down.\n"
            "- Use only what bears on a claim the report actually makes. Silence on a "
            "settled point is better than a paragraph that discusses nothing."
        ),
        build=_settled_reasoning,
        rationale=(
            "Stage 07 only. Every earlier stage either produced this material or was told "
            "the part of it that bound its own decision, so re-sending it upstream would "
            "re-open questions the run closed. Writing is the first stage whose job is to "
            "state why the run believes what it believes, and the first that had no access "
            "to the record of the run deciding it."
        ),
    ),
    Channel(
        key="report_plan",
        max_chars=30_000,
        heading="# Report Plan (declared at Stage 03)",
        produced_by="03_study_design",
        consumed_by=frozenset(
            {
                "03_study_design",
                "04_implementation",
                "05_experimentation",
                "06_analysis",
                "07_writing",
            }
        ),
        build=_report_plan,
        preface=(
            "The figures below were chosen before any result existed, and they are a "
            "commitment rather than a suggestion. Each slot names the file its numbers "
            "come from: the stages that write and run code owe those files at those "
            "paths. Stage 06 draws the figures, under exactly the filenames declared "
            "here, and Stage 07 publishes them. **Do not draw a figure before Stage 06** "
            "— a figure drawn before the results exist is a figure fitted to nothing. A "
            "slot that has to be abandoned carries `dropped_because` saying what happened "
            "to the claim it was going to settle."
        ),
        rationale=(
            "03 re-reads its own plan so a second round amends it rather than rewriting "
            "it from scratch, the way 05 re-reads the experiment manifest. 04 and 05 need "
            "it because each slot names a `source_artifact`: 04 writes the code that emits "
            "those files and 05 is the stage that actually emits them, and the Stage 06 "
            "gate that refuses a slot whose source does not exist is unfixable by then if "
            "neither stage was told the paths. 06 draws the figures and 07 publishes them. "
            "Stages 00-02 precede the plan; Stage 08 cannot change a published report. The "
            "preface withholds the drawing instruction from everyone before 06 on purpose "
            "— the plan reaches 04 and 05 as a list of files to produce, not as an "
            "invitation to plot instead of run."
        ),
    ),
    Channel(
        key="research_rounds",
        max_chars=24_000,
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
        max_chars=24_000,
        heading="# Adversarial Validity Findings (each must be answered)",
        produced_by="05_experimentation",
        consumed_by=frozenset({"06_analysis", "07_writing"}),
        build=_validity_findings,
        rationale="Only the stage that owes an answer needs the objections.",
    ),
    Channel(
        key="hypothesis_verdicts",
        max_chars=24_000,
        heading="# Hypothesis Verdicts",
        produced_by="06_analysis",
        consumed_by=frozenset({"07_writing", "08_dissemination"}),
        build=_verdicts,
        rationale="Writing may only claim what came out supported; dissemination reports the same.",
    ),
    Channel(
        key="withdrawal_history",
        heading="## What This Run Has Already Withdrawn",
        produced_by=None,
        consumed_by=_REVISIT_TARGETS,
        build=_withdrawal_history,
        preface=(
            "These are decisions this run made, acted on, and then took back. The work "
            "they produced is no longer on disk. Do not redo what was withdrawn without "
            "addressing the reason it was."
        ),
        rationale=(
            "A withdrawal returns the workspace to what preceded it, which is what makes a "
            "backward edge safe to take and also what makes the same mistake cheap to "
            "repeat: a stage re-entered after its work was taken back arrives at a "
            "workspace that looks exactly as it did the first time. The state is supposed "
            "to leave no trace; the reason is not. Delivered to the seven stages a backward "
            "edge can land on, because those are the ones that can repeat a withdrawn "
            "decision. Stage 00 and Stage 08 are no edge's target -- intake runs once "
            "before any withdrawal can have happened, and dissemination packages a result "
            "it cannot revisit."
        ),
    ),
    Channel(
        key="task_shaped_skills",
        max_chars=12_000,
        heading="## Skills Selected For This Task",
        produced_by=None,
        consumed_by=frozenset(ALL_STAGES),
        build=_task_shaped_skills,
        rationale=(
            "Every stage, because which skills a task's shape calls for is a property "
            "of the task and not of the stage: a brief that names an attribution "
            "deliverable needs that skill at design time and again at writing. The "
            "block is empty unless a skill's own `stages` field names the stage, so a "
            "channel open to all eight costs nothing at the seven a given skill did "
            "not ask for. Narrowing the channel instead of the skill would move the "
            "routing decision away from the skill that knows it."
        ),
    ),
)


def _every_channel_declares_what_it_may_spend() -> None:
    """Refuse a channel that neither declares a budget nor says why it cannot grow.

    At import, and raising, for the reason :meth:`Edge.__post_init__` refuses an
    unregistered guard: the alternative fails open. ``max_chars`` defaults to ``None``,
    so an author who does not think about it gets "unbounded" -- which is how the
    per-builder convention this field replaces decayed in the first place.

    Safe to raise here because the population is source, not run data. This can only
    fail while someone is editing this file, never on a user's run, so it is not the
    kind of precondition ``docs/iclr/composable-stage-graphs.md`` warns about.
    """

    undeclared = sorted(
        channel.key
        for channel in CHANNELS
        if channel.max_chars is None and channel.key not in UNBOUNDED_BY_CONSTRUCTION
    )
    if undeclared:
        raise ValueError(
            "These channels declare no `max_chars` and give no reason they cannot grow: "
            + ", ".join(undeclared)
            + ". Give each one a budget, or name it in UNBOUNDED_BY_CONSTRUCTION with "
            "the structure that bounds it."
        )
    stale = sorted(set(UNBOUNDED_BY_CONSTRUCTION) - {channel.key for channel in CHANNELS})
    if stale:
        raise ValueError(
            "UNBOUNDED_BY_CONSTRUCTION names channels that no longer exist: "
            + ", ".join(stale)
            + ". A reason nobody can reach is a reason nobody will notice has stopped "
            "applying."
        )


_every_channel_declares_what_it_may_spend()
