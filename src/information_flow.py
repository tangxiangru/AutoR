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
        key="project_context",
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
        key="experimental_protocol",
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
)
