"""Measure a capability against ResearchClawBench's score, not against AutoR's own rubric.

:mod:`src.trials` already does the statistics honestly — within-pair differences, a
refusal to compare across a composition difference, the exact sign-flip p printed
beside the floor it cannot go below. Its one limitation is the outcome measure: it
reads ``stage_fitness`` and ``criterion_fitness``, which are AutoR grading its own
drafts. A capability that makes AutoR like its own work more is not the claim anyone
wants; the claim is that the external benchmark score moves.

This module is a **producer**, not a second statistics module. :class:`src.trials.Pair`
is the only reader of those two dicts anywhere in the tree, and nothing above it names
a stage slug or a rubric key. So swapping the outcome measure is swapping what fills
them, and every one of the refusals in :mod:`src.trials` keeps working on the new
numbers without being touched.

**The mapping, and why each half is shaped the way it is.**

``stage_fitness`` gets exactly one key, ``"<task_id>|<env_digest>"``. One key because
``Pair._mean_over`` is an *unweighted* mean and ResearchClawBench's total is a
*weighted* one: a mean over a single element is that element, so ``Pair.difference``
comes out as the benchmark total difference exactly, with the weighting already done
where it belongs. The environment digest is in the key because a pair whose two arms
used different judges, different ``--model``, a different checklist or a different
web-search level is a *composition difference*, which is the thing
``collect_pairs`` already refuses to compare across. Folding the environment into the
key makes that refusal fire on a confounded pair with no new gate to write — and,
more to the point, no new gate to get wrong.

``criterion_fitness`` gets one key per checklist item, holding ``weight * score`` —
the item's contribution to the total. Every one of the forty shipped checklists has
weights summing to exactly 1.0, so **within one run** the decomposition sums to the
scalar, which AutoR's own decomposition does not do, and ``concentration`` becomes
literally "share of the movement sitting in one checklist item". The identity is a
per-run one and does not survive aggregation: ``TrialResult`` reports the *mean*
difference per key over *n* pairs against a total that is also a mean, so the column
sums to the scalar there too, but a reader who adds the raw per-pair contributions
across pairs gets ``n`` times it. Stated once here rather than implied twice. Not per-item keys' obvious
alternative, a two-key image/text split: two keys put ``concentration`` in [0.5, 1.0]
unconditionally and reduce the 0.6 Goodhart threshold to "the bigger half is 1.5× the
smaller", which fires on nearly everything. The image/text axis is real and causal —
image criteria see only ``report_text[:10000]`` and the Discussion is at the end of
the report, so a settled-reasoning channel can only reach text criteria — so it is
printed as its own table below, where it does not have to double as the decomposition.

**No record written here is ever persisted.** ``RunRecord.usable`` is
``rubric_version == RUBRIC_VERSION and provenance == "live"``, and a benchmark row
carrying AutoR's rubric version is a claim it cannot support. The containment is not a
comment: these records exist in memory for the length of one report and there is no
code path in this module or its tool that opens an :class:`src.archive.Archive`. If
one of these rows ever reached ``Archive.variant_fitness``, 0–100 benchmark totals
would pool with [0, 1] rubric means and drive topology promotion off a unit error.

**What a run has to be before it is a measurement.** Ten clauses, every one of them
written from something that actually happened on this box: a workspace with
``status == "running"`` and a 12 KB working draft in ``report/report.md`` scores
perfectly well; a run killed by quota still exports a fallback report and records
``status: "completed"``; thirteen PNGs under ``outputs/`` took all five judge image
slots and dropped one image criterion from 48 to 0, moving the total from 46.0 to 9.6.
None of those is a bad run. Each is a *non-run* that produces a plausible number, and
averaging one into a paired difference is how a four-day measurement becomes fiction.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Mapping, Sequence

from .archive import RunRecord
from .information_flow import CHANNELS
from .rubric import RUBRIC_VERSION
from .trials import (
    TrialResult,
    collect_pairs,
    format_trial_report,
    min_attainable_concentration,
)


#: Judge calls per workspace in the final scoring pass. The reference judge's
#: ``responses.create`` passes no ``temperature``, so it has real sampling noise, and
#: replicates are the only thing that turns "a text item moved 30 points, call it
#: noise" from folklore into a measured band. Three is cheap — scoring is minutes
#: against a run's hours — and it is a poor variance estimator, so what it produces is
#: reported as a range the judge could not resolve, never as a significance test.
SCORE_REPLICATES = 3

#: No heartbeat on ``logs_raw.jsonl`` for this long and the run is hung. The only
#: second-granularity signal a run emits: ``run_manifest.json`` updates on stage
#: transitions only, and ``_meta.json`` is written once at the end.
STALL_SECONDS = 2700

#: Deliberately absent: a per-run wall clock. A measured run on this box took 57011
#: seconds (15.8 h) and finished with ``report_source == "agent"``. Any cap short
#: enough to be useful against a hang is short enough to kill that run, so the trial
#: gets a deadline after which no *new* run starts and a running one is left alone.
BACKOFF_SCHEDULE_SECONDS = (1800, 3600, 7200)

#: Attempts per (task, arm) before the pair is refused, counting abandoned drivers and
#: transient backend deaths. Applied identically to both arms — an asymmetric retry
#: budget is a thumb on the scale.
MAX_ATTEMPTS = 2

#: Quota backoffs per (task, arm), on top of :data:`MAX_ATTEMPTS`. Vertex quota is
#: per-base-model and recovers; refusing the pair on the first 429 most likely ends a
#: four-day trial with zero pairs.
MAX_BACKOFFS = 2

#: The channel's own heading, read off the channel rather than written out again.
#:
#: Its absence from the treatment arm's Stage 07 prompt means the channel under test
#: delivered nothing — ``information_flow._render`` emits the heading whenever the block
#: is non-empty and emits nothing at all when it is — so that pair is not a test of it.
#:
#: The obvious marker, ``build_block``'s ``## Methodological questions this run settled``,
#: sees only half the channel: that sub-heading is emitted inside ``if cruxes:``, and a
#: block built from rejected idea-pool candidates alone — one of the two things PR #175
#: routes here — contains only ``## Hypotheses generated and not pursued``. Reading it
#: would publish "this pair did not administer the channel" over a dose that was
#: delivered. Derived from ``CHANNELS`` rather than copied so that renaming the heading
#: cannot leave the detector looking for a string nothing emits.
SETTLED_REASONING_HEADING = {
    channel.key: channel.heading for channel in CHANNELS
}["settled_reasoning"]


def _digest(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# The environment a run was measured in
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunEnvironment:
    """Everything that changes the number without changing the code under test.

    Each field is here because it was observed to move, not because it could. The
    web-search level is the sharpest: the same command line produced ``level: info``
    on two days and ``level: warn`` on a third, because ``google.genai`` was not
    importable by the interpreter that day — meaning Stage 01 had no way to search at
    all. That is a larger effect than anything a prompt change can buy, and nothing in
    the run's own artifacts flags it as an anomaly.
    """

    #: sha256 of the checklist bytes. Item identity is a property of the benchmark
    #: checkout and the scorer's output records only ``task_id``.
    checklist_digest: str = ""
    #: Worth about sixteen points on identical artifacts (Gemini 2.5 Flash 37.0,
    #: Claude Opus 20.8). Same judge both arms or there is no comparison.
    judge_model: str = ""
    #: The operator model.
    agent_model: str = ""
    #: Independent of the operator model, and the one that silently dies on an
    #: exhausted pool when only ``--model opus`` is passed.
    review_model: str = ""
    #: Resolved, not requested. ``run_config.json`` records ``"auto"``.
    web_search_level: str = ""
    #: The judge reads ``INSTRUCTIONS.md`` as background. Both arms byte-identical.
    instructions_digest: str = ""
    #: ``git rev-parse HEAD`` in the benchmark checkout.
    bench_revision: str = ""
    #: How many judge draws this arm's published total is the mean of. Not a property of
    #: the run but of the measurement of it, and it belongs in the digest for the same
    #: reason the judge model does: one draw against the mean of three is not a
    #: comparison. ``final_pass`` gives a replicate two tries and then moves on writing
    #: nothing, so an arm silently scored once against an arm scored three times is the
    #: ordinary failure, not the exotic one — and it is the direction that inflates,
    #: because a single draw carries the judge's full sampling range into the delta while
    #: the other arm has averaged its own away.
    judge_replicates: int = 0

    @property
    def digest(self) -> str:
        return _digest(dataclasses.asdict(self))

    def describe_difference(self, other: "RunEnvironment") -> list[str]:
        """Name every field that differs, in the report's voice.

        The digest is the gate; this is the diagnostics. Their separation is
        deliberate — a bug here cannot let a confounded pair through, because the pair
        dies on the key mismatch whatever this returns. What a bug here *can* do is
        leave a reader with "the two arms measured no stage in common", which is true
        and useless, so :func:`collect_rcb_pairs` asserts the two stay in step.
        """
        reasons: list[str] = []
        for spec in dataclasses.fields(self):
            mine = getattr(self, spec.name)
            theirs = getattr(other, spec.name)
            if mine != theirs:
                reasons.append(
                    f"the arms differ in `{spec.name}` "
                    f"(control {mine or '<unset>'}, treatment {theirs or '<unset>'})"
                )
        return reasons


# ---------------------------------------------------------------------------
# What one scored arm of a pair is
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoredItem:
    """One checklist item, scored ``SCORE_REPLICATES`` times by one judge."""

    index: int
    kind: str
    weight: float
    content_key: str
    scores: tuple[int, ...]

    @property
    def score(self) -> float:
        return sum(self.scores) / len(self.scores) if self.scores else 0.0

    @property
    def spread(self) -> float:
        """Max minus min across replicates: what this judge could not resolve.

        A range over three draws underestimates the distribution, so this is a floor
        on the judge's noise and is reported as one.
        """
        return (max(self.scores) - min(self.scores)) if self.scores else 0.0

    @property
    def contribution(self) -> float:
        return self.weight * self.score

    @property
    def key(self) -> str:
        return f"#{self.index:02d} {self.kind} w={self.weight:g}"


@dataclass(frozen=True)
class ArmEvidence:
    """One arm of one pair: what was scored, and everything the gate needs to see."""

    task_id: str
    arm: str
    run_id: str
    workspace: str
    env: RunEnvironment
    items: tuple[ScoredItem, ...]
    #: ``score.py``'s own ``total_score``: ``round(sum(w*s)/sum(w), 2)`` from a single
    #: pass. Carried so the recomputed number can be reconciled against it rather than
    #: quietly replacing it.
    published_total: float
    #: What the plan asked for. Carried so "scored three times" and "scored once because
    #: the judge failed twice on two of the three draws" are different sentences in the
    #: report rather than the same one.
    replicates_requested: int = 0
    #: How many images the scorer actually put in front of every image criterion, and how
    #: many it had to choose from. Image criteria are 60.6% of the benchmark's weight and
    #: all of them see the *same* first five of one ``rglob`` list, so an arm that emitted
    #: twelve figures was judged on an arbitrary five of them. It is not in the digest:
    #: how many figures a run produced is an effect of the code under test, not a
    #: confound to exclude. It is printed, because attributing an image-stratum delta to
    #: figure quality when the two arms were shown different figures is the error.
    images_shown: int = 0
    images_available: int = 0
    judge_failures: tuple[str, ...] = ()
    checklist_items_expected: int = 0
    #: Admission facts, read off the workspace by the tool. A mapping rather than
    #: fields so the gate and the reader agree about what was looked at.
    facts: Mapping[str, Any] = field(default_factory=dict)
    #: Stage slugs AutoR's own evolution loop scored. Not the outcome measure; a
    #: composition difference the benchmark seam is structurally blind to.
    autor_stages_scored: tuple[str, ...] = ()
    #: Whether Stage 07's prompt actually carried the settled-reasoning block.
    settled_reasoning_dose: bool = False

    @property
    def replicates(self) -> int:
        """How many judge draws the published total averages.

        Read off the environment rather than stored beside it. Two encodings of one
        count is how an arm scored once came to be printed as "3 replicate scorings per
        arm": the report read one copy and the composition gate read neither.
        """
        return self.env.judge_replicates

    @property
    def replicates_lost(self) -> int:
        return max(0, self.replicates_requested - self.replicates)

    @property
    def total_weight(self) -> float:
        return sum(item.weight for item in self.items)

    @property
    def total_weighted(self) -> float:
        """The published scalar: ``sum(weight * mean score)`` over every item.

        Not ``score.py``'s ``total_score``, which is one pass rounded to two places.
        With ``total_weight`` asserted to be 1.0 the two are the same number up to that
        rounding, and :func:`to_run_record` refuses when they are not.
        """
        return sum(item.contribution for item in self.items)


# ---------------------------------------------------------------------------
# Admission: is this run a measurement at all?
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdmissionClause:
    name: str
    why: str
    test: Callable[[ArmEvidence], bool]


def _fact(evidence: ArmEvidence, name: str, default: Any = None) -> Any:
    return evidence.facts.get(name, default)


#: Every clause refuses a *pair*, not an arm, because refusing one arm turns the pair
#: into "no treatment arm" and hides the cause. Each is a fixture in the tests, and the
#: report prints how many runs each one refused — a clause that has silently stopped
#: firing because an internal artifact was renamed shows up as a zero rather than as
#: nothing at all.
ADMISSION_CLAUSES: tuple[AdmissionClause, ...] = (
    AdmissionClause(
        "status_completed",
        "`_meta.status` must be `completed`. The scorer never looks at it, and a "
        "workspace mid-run scores its working draft as if it were the deliverable.",
        lambda ev: _fact(ev, "meta_status") == "completed",
    ),
    AdmissionClause(
        "pipeline_completed",
        "`_meta.pipeline_completed` must be true. A second, independent witness to the "
        "clause above: one measured workspace here has status `completed` and "
        "pipeline_completed false.",
        lambda ev: _fact(ev, "meta_pipeline_completed") is True,
    ),
    AdmissionClause(
        "report_from_agent",
        "`_meta.report_source` must be `agent`. A run killed by quota still exports a "
        "fallback report and is scored as an attempt — worth about 7.5 points of "
        "nothing.",
        lambda ev: _fact(ev, "meta_report_source") == "agent",
    ),
    AdmissionClause(
        "single_run_root",
        "Exactly one `.autor/<run_id>`. Nothing stops a second invocation writing into "
        "the same workspace, and the exporter picks the lexicographically last run "
        "root, which is the failed retry.",
        lambda ev: _fact(ev, "autor_run_count") == 1,
    ),
    AdmissionClause(
        "no_images_under_outputs",
        "Zero images under `outputs/`. The judge is shown the first five of one list "
        "that sweeps `outputs/` before `report/`, against every image criterion: "
        "thirteen PNGs there took an image item from 48 to 0 and the total from 46.0 "
        "to 9.6.",
        lambda ev: _fact(ev, "images_under_outputs") == 0,
    ),
    AdmissionClause(
        "single_report_md",
        "`report/report.md` exists and is the only `report/*.md`. Counting is not "
        "naming: with `report.md` missing the scorer returns the first `.md` an "
        "unsorted glob yields, so a lone leftover `draft.md` satisfies a count of one "
        "and is then scored as the deliverable, with nothing recording which file was "
        "read.",
        lambda ev: _fact(ev, "report_md_count") == 1
        and _fact(ev, "report_md_present") is True,
    ),
    AdmissionClause(
        "backend_reached",
        "`run_manifest.last_event` must not be `run.backend_unavailable`. The only "
        "machine-readable trace a quota death leaves: `last_error` stays null and "
        "`current_stage_slug` is nulled out.",
        lambda ev: _fact(ev, "last_event") != "run.backend_unavailable",
    ),
    AdmissionClause(
        "no_quota_in_logs",
        "No `RESOURCE_EXHAUSTED` in the run's own `logs.txt`. `classify_backend` only "
        "runs when neither the primary nor the repair attempt wrote a stage file, so a "
        "429 that lands mid-stage is baked into the summary as prose and the run reports "
        "itself complete.",
        lambda ev: _fact(ev, "resource_exhausted_hits", 0) == 0,
    ),
    AdmissionClause(
        "revision_matches_arm",
        "The worktree's HEAD at launch and at finish must be the same commit, must be "
        "clean, and must be the commit the arm label names. `RunRecord` has no revision "
        "field and `run_config.json` records no SHA; the arm label is the only carrier "
        "and nothing else checks it.",
        lambda ev: _revision_matches_arm(ev),
    ),
    AdmissionClause(
        "every_item_judged",
        "Every checklist item judged, none of them by a failed call. A judge failure is "
        "recorded as score 0 and is indistinguishable from a criterion the report "
        "missed: one run's honest total was 37.0 and the number on screen was 19.5.",
        lambda ev: (
            not ev.judge_failures
            and len(ev.items) > 0
            and len(ev.items) == ev.checklist_items_expected
        ),
    ),
)


def _revision_matches_arm(evidence: ArmEvidence) -> bool:
    launch = str(_fact(evidence, "revision_at_launch", ""))
    finish = str(_fact(evidence, "revision_at_finish", ""))
    if not launch or launch != finish:
        return False
    if _fact(evidence, "worktree_dirty", True):
        return False
    label = evidence.arm.strip()
    # Prefix either way: an arm labelled with a short SHA against a full HEAD, or the
    # reverse. Not a substring test — `47f3fbf` appearing anywhere in a SHA is chance.
    return bool(label) and (launch.startswith(label) or label.startswith(launch))


def admit_arm(evidence: ArmEvidence) -> tuple[bool, list[str]]:
    """``(admitted, failed clause names)``. Order is the clause order, for the ledger."""
    failed = [clause.name for clause in ADMISSION_CLAUSES if not clause.test(evidence)]
    return (not failed), failed


def clause_by_name(name: str) -> AdmissionClause:
    for clause in ADMISSION_CLAUSES:
        if clause.name == name:
            return clause
    raise KeyError(name)


# ---------------------------------------------------------------------------
# The seam
# ---------------------------------------------------------------------------


def to_run_record(evidence: ArmEvidence, *, capability: str) -> RunRecord:
    """One admitted arm as a :class:`RunRecord`, so :mod:`src.trials` can do the rest.

    **This record is never written to disk, and there is no code here that could write
    it.** ``rubric_version`` has to be ``RUBRIC_VERSION`` for ``RunRecord.usable`` to be
    true, and on a benchmark row that is a claim the row cannot support: the number in
    ``stage_fitness`` is a judge's 0–100 reading of a report, not AutoR's rubric. The
    containment is structural rather than documentary — no ``Archive`` is constructed
    anywhere in this module or in ``tools/rcb_trial.py``, and a test asserts it stays
    that way — because if one of these rows reached ``Archive.variant_fitness`` it
    would pool a 0–100 total with [0, 1] rubric means and steer topology promotion.

    Three refusals, because each invariant is silent when it breaks:

    * the checklist's weights must sum to 1.0, or the decomposition does not sum to the
      scalar and ``concentration`` stops meaning what the report says it means;
    * the arm must have been admitted, so a fallback report cannot arrive here by
      another route;
    * with a single replicate the recomputed weighted sum must reconcile with
      ``score.py``'s own ``total_score``, because that is one number written twice and
      the two encodings will otherwise drift without anybody noticing.
    """
    admitted, failed = admit_arm(evidence)
    if not admitted:
        raise ValueError(
            f"{evidence.task_id}/{evidence.arm} is not a measurement: "
            + ", ".join(failed)
            + ". A refused run belongs in the ledger, not in an average."
        )
    if abs(evidence.total_weight - 1.0) > 1e-9:
        raise ValueError(
            f"{evidence.task_id} checklist weights sum to {evidence.total_weight!r}, not 1.0. "
            "The per-item decomposition is only the total's decomposition when they do."
        )
    contributions = {item.key: item.contribution for item in evidence.items}
    if len(contributions) != len(evidence.items):
        raise ValueError(
            f"{evidence.task_id} produced duplicate item keys; the decomposition would "
            "silently drop an item and still sum to something plausible."
        )
    total = sum(contributions.values())
    if abs(total - evidence.total_weighted) > 1e-9:
        raise ValueError("the contributions do not sum to the published weighted total")
    if evidence.replicates <= 1:
        # score.py rounds to two places; anything past that is two encodings drifting.
        # ``<= 1`` and not ``== 1``: an evidence whose replicate count was never recorded
        # is a single pass until something says otherwise, and skipping the only place
        # the two encodings meet is not the safe direction to guess in.
        if abs(total - evidence.published_total) > 0.005 + 1e-9:
            raise ValueError(
                f"{evidence.task_id}/{evidence.arm}: recomputed total {total:.4f} does not "
                f"reconcile with score.py's {evidence.published_total:.4f}. One number, two "
                "encodings, and this is the only place they meet."
            )

    stage_key = f"{evidence.task_id}|{evidence.env.digest[:12]}"
    return RunRecord(
        run_id=evidence.run_id,
        variant_id=f"rcb/{evidence.env.judge_model}",
        rubric_version=RUBRIC_VERSION,
        edges={},
        stage_fitness={stage_key: total},
        topology="rcb",
        provenance="live",
        route=evidence.workspace,
        steps=len(evidence.items),
        revisits=0,
        agent_directed=0,
        bypassed=0,
        recorded_at="",
        criterion_fitness={f"{evidence.task_id}{key}": value for key, value in contributions.items()},
        trial_id=evidence.task_id,
        capability=capability,
        arm=evidence.arm,
    )


def compare_arms(control: ArmEvidence, treatment: ArmEvidence) -> list[str]:
    """Named reasons two admitted arms are not comparable.

    The environment digest inside the stage key already excludes them; this says which
    field did it. "The two arms measured no stage in common" is a true sentence about a
    one-byte difference in ``INSTRUCTIONS.md`` and it helps nobody.
    """
    reasons: list[str] = []
    if control.task_id != treatment.task_id:
        reasons.append(
            f"the arms scored different tasks (`{control.task_id}` and `{treatment.task_id}`)"
        )
    reasons += control.env.describe_difference(treatment.env)
    control_keys = [item.content_key for item in control.items]
    treatment_keys = [item.content_key for item in treatment.items]
    if control_keys != treatment_keys:
        reasons.append(
            "the arms were scored against different checklist items, so the per-item "
            "decomposition would pair by position across two different lists"
        )
    return reasons


# ---------------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------------


#: Clause names for the refusals the driver makes before the gate can see the run at all.
#: They share the ledger with the ten admission clauses because they lose the reader the
#: same thing — a pair — and because the ledger's whole job is the per-arm death count.
DRIVER_CLAUSE_PREFIX = "driver:"


def driver_clause(classification: str) -> str:
    return DRIVER_CLAUSE_PREFIX + (classification or "unknown")


@dataclass(frozen=True)
class Refusal:
    task_id: str
    arm: str
    clauses: tuple[str, ...]

    @property
    def summary(self) -> str:
        return f"`{self.task_id}` / `{self.arm}`: " + ", ".join(self.clauses)


@dataclass(frozen=True)
class RcbTrial:
    """A finished (or interrupted) paired trial and everything a reader needs to argue."""

    result: TrialResult
    #: Admitted evidence, keyed ``(task_id, arm)``.
    evidence: Mapping[tuple[str, str], ArmEvidence]
    refusals: tuple[Refusal, ...]
    planned_pairs: int

    @property
    def interim(self) -> bool:
        return self.result.n != self.planned_pairs

    def refusals_by_clause(self) -> dict[str, int]:
        """Every admission clause at its count, then every driver refusal that happened.

        The admission clauses are listed even at zero, because a clause that stopped
        firing looks exactly like a clause never violated. The driver rows are listed
        only when they fired, because they are not a fixed set — and because a zero
        against ``driver:quota`` would be the wrong claim: four of the ten clauses below
        can only be reached by a run the driver already let through, so a quota death
        arrives in this table under its driver name and never under the clause's.
        """
        counts = {clause.name: 0 for clause in ADMISSION_CLAUSES}
        driver: dict[str, int] = {}
        for refusal in self.refusals:
            for name in refusal.clauses:
                if name in counts:
                    counts[name] += 1
                else:
                    driver[name] = driver.get(name, 0) + 1
        counts.update(sorted(driver.items()))
        return counts

    def refusals_by_arm(self) -> dict[str, int]:
        counts: dict[str, int] = {
            self.result.control_arm: 0,
            self.result.treatment_arm: 0,
        }
        for refusal in self.refusals:
            counts[refusal.arm] = counts.get(refusal.arm, 0) + 1
        return counts


def collect_rcb_pairs(
    evidences: Iterable[ArmEvidence],
    *,
    capability: str,
    control_arm: str,
    treatment_arm: str,
    planned_pairs: int,
    driver_refusals: Sequence[Refusal] = (),
) -> RcbTrial:
    """Admit, pair, and replace every generic exclusion reason with a named one.

    The gate and the explanation are separate on purpose. ``collect_pairs`` does the
    excluding, off the environment digest baked into the stage key; this only renames
    what it excluded. The assertion at the end is what keeps the two honest: if a field
    is dropped from :class:`RunEnvironment` while its diff line survives, a confounded
    pair reaches ``pairs`` with a named reason for excluding it, and that raises here
    rather than being published.

    ``driver_refusals`` is the other half of the ledger, and the half that used to be
    missing: a run killed by quota, by the stall watchdog, by a backend outage, by a
    fallback report or by the scorer never becomes an :class:`ArmEvidence` at all, so the
    gate cannot refuse it and it was printed as "no treatment arm" — indistinguishable
    from an arm that was never launched. Three treatment deaths against zero control
    deaths is this trial's result whenever it happens, and it cannot be the one thing the
    ledger structurally cannot see.
    """
    admitted: dict[tuple[str, str], ArmEvidence] = {}
    refusals: list[Refusal] = []
    for evidence in evidences:
        ok, failed = admit_arm(evidence)
        if ok:
            admitted[(evidence.task_id, evidence.arm)] = evidence
        else:
            refusals.append(Refusal(evidence.task_id, evidence.arm, tuple(failed)))

    # One (task, arm) is one lost pair and is counted once. A driver refusal for an arm
    # that a later attempt got admitted for cost an attempt, not a pair; a driver refusal
    # for an arm the gate already refused would double the per-arm count that the reader
    # is told to judge the whole trial on.
    seen = set(admitted) | {(item.task_id, item.arm) for item in refusals}
    for refusal in driver_refusals:
        if (refusal.task_id, refusal.arm) in seen:
            continue
        seen.add((refusal.task_id, refusal.arm))
        refusals.append(refusal)

    records = [to_run_record(item, capability=capability) for item in admitted.values()]
    result = collect_pairs(
        records,
        capability=capability,
        control_arm=control_arm,
        treatment_arm=treatment_arm,
    )

    named: dict[str, list[str]] = {}
    for refusal in refusals:
        side = "control" if refusal.arm == control_arm else "treatment"
        named.setdefault(refusal.task_id, []).append(
            f"the {side} arm `{refusal.arm}` was refused ({', '.join(refusal.clauses)})"
        )
    tasks = {task for task, _ in admitted} | {refusal.task_id for refusal in refusals}
    for task in tasks:
        control = admitted.get((task, control_arm))
        treatment = admitted.get((task, treatment_arm))
        if control is not None and treatment is not None:
            named.setdefault(task, []).extend(compare_arms(control, treatment))

    kept = {pair.trial_id for pair in result.pairs}
    leaked = sorted(task for task, reasons in named.items() if reasons and task in kept)
    if leaked:
        raise AssertionError(
            "a pair with a named reason to be excluded survived pairing: "
            + ", ".join(leaked)
            + ". The environment digest and the cross-arm diff have gone out of step, "
            "which means a confound can now reach the published difference."
        )

    excluded = dict(result.excluded)
    for task, reasons in named.items():
        if reasons:
            excluded[task] = "; ".join(reasons)
    for task in tasks:
        if task not in kept and task not in excluded:
            excluded[task] = "no run of either arm was admitted"

    return RcbTrial(
        result=replace(result, excluded=tuple(sorted(excluded.items()))),
        evidence=admitted,
        refusals=tuple(refusals),
        planned_pairs=planned_pairs,
    )


# ---------------------------------------------------------------------------
# Reading the two arms side by side
# ---------------------------------------------------------------------------


def pair_resolution(control: ArmEvidence, treatment: ArmEvidence) -> float:
    """How much of a pair's difference this judge could not resolve, in total points.

    ``sum_i w_i * max(spread_i^control, spread_i^treatment)``. Replaces the folklore
    rule that a text item moving under thirty raw points is noise — that rule is in the
    wrong units (an item at ``w = 0.2`` converts thirty raw points into six total
    points) and it was never measured. This is measured, on these two workspaces, by
    this judge. It is a floor: a range over three draws underestimates a distribution,
    and it says nothing at all about run-to-run variance, of which there are zero
    observations.
    """
    total = 0.0
    for left, right in zip(control.items, treatment.items):
        total += left.weight * max(left.spread, right.spread)
    return total


def resolution_is_measured(control: ArmEvidence, treatment: ArmEvidence) -> bool:
    """Whether :func:`pair_resolution` is a measurement rather than an artefact of one draw.

    A spread needs two draws to exist. With one, every ``ScoredItem.spread`` is 0 and
    :func:`pair_resolution` returns 0.00 — *fewer* draws producing a *smaller* stated
    uncertainty, which is exactly backwards, and which reads off the page as "this judge
    resolved every item exactly" on the one arm where nothing about the judge's noise was
    observed at all. Losing replicates is the ordinary case: ``final_pass`` gives each
    draw two tries and then moves on.
    """
    return min(control.replicates, treatment.replicates) >= 2


def stratum_rollup(control: ArmEvidence, treatment: ArmEvidence) -> dict[str, Any]:
    """The image/text split, with the identity that makes it checkable.

    Causal, not cosmetic: image criteria are shown only ``report_text[:10000]`` and the
    Discussion sits at the end of the report by construction, so a channel that routes
    settled reasoning into Discussion can reach the text stratum and structurally
    cannot reach the image one. Within a pair
    ``delta_total == share_image * delta_image + share_text * delta_text`` holds
    exactly, and the residual is asserted rather than assumed — it is a free check that
    the two arms' item lists really did line up.
    """
    strata: dict[str, dict[str, float]] = {}
    for kind in ("image", "text"):
        weight = sum(item.weight for item in control.items if item.kind == kind)
        control_mean = (
            sum(item.contribution for item in control.items if item.kind == kind) / weight
            if weight
            else 0.0
        )
        treatment_mean = (
            sum(item.contribution for item in treatment.items if item.kind == kind) / weight
            if weight
            else 0.0
        )
        strata[kind] = {
            "share": weight,
            "control": control_mean,
            "treatment": treatment_mean,
            "delta": treatment_mean - control_mean,
        }
    delta_total = treatment.total_weighted - control.total_weighted
    rebuilt = sum(value["share"] * value["delta"] for value in strata.values())
    return {
        "strata": strata,
        "delta_total": delta_total,
        "residual": delta_total - rebuilt,
    }


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


#: The single largest hole, and it goes directly under the total rather than in a
#: caveats section nobody reaches. Every (task, arm) ran once, so the apparatus has no
#: observation at all of AutoR's own run-to-run variance, which is almost certainly
#: larger than the judge's.
_ONE_OBSERVATION = (
    "Each (task, arm) ran **once**. The resolution above is the judge's sampling range "
    "over replicate scorings of the same two workspaces; there are zero observations of "
    "AutoR's own run-to-run variance, which is very likely larger. Read a difference "
    "that exceeds the resolution as *the judge cannot explain it*, never as *the "
    "treatment explains it*."
)

#: Printed wherever an n below the planned n carries a p. Every refusal removes a pair,
#: and refusals are not random with respect to arm.
_REFUSAL_BIAS = (
    "Every refusal above removes a **pair**, and quota and wall-clock deaths are not "
    "random with respect to arm: the channel under test adds prompt content to Stage "
    "07, which can make treatment runs longer and likelier to be cut off. A surviving "
    "sample weighted toward the treatment runs that finished fastest is a sample of the "
    "treatment runs that did less, and it manufactures a null. If the per-arm refusal "
    "counts above are lopsided, the difference below is not this trial's result."
)


def format_rcb_trial_report(
    trial: RcbTrial,
    *,
    contrast_log: str = "",
    plan_digest: str = "",
    judge_model: str = "",
    planned_judge_model: str = "",
    unit: str = "RCB points (0-100 total scale)",
) -> str:
    """The whole rendering: provenance, ledger, statistics, decomposition, dose.

    Order is an argument. The refusal ledger sits *above* the total because a trial
    that refused three treatment runs and zero control runs has produced a result, and
    it is not the number underneath. The p-value sits at the bottom under the floor it
    cannot beat, because at three pairs the floor is 0.25 and the conclusion has to be
    carried by the decomposition and by which channel each task can see.
    """
    result = trial.result
    lines: list[str] = [
        "# ResearchClawBench paired trial",
        "",
        f"- capability: `{result.capability}`",
        f"- control revision: `{result.control_arm}`   treatment revision: `{result.treatment_arm}`",
        f"- judge: `{judge_model or '<unrecorded>'}`   (judge choice is worth about "
        "sixteen points on identical artifacts, so it is part of the number)",
    ]
    if planned_judge_model and judge_model and planned_judge_model != judge_model:
        # The judge above is read off the score files; this one is what the plan asked
        # for. `score_rcb_run.py` builds its judge with `args.model or its own default`,
        # so a dropped `--model` scores the whole trial with a model nobody chose while
        # the header states the declaration and reads correct.
        lines.append(
            f"- **the judge that ran is not the judge the plan declared** "
            f"(`{planned_judge_model}`). Sixteen points on identical artifacts is larger "
            "than anything this trial is looking for."
        )
    if plan_digest:
        lines.append(f"- plan digest: `{plan_digest[:16]}` (frozen before the first launch)")
    if contrast_log:
        lines += [
            "",
            "The contrast, verbatim from `git log --oneline <control>..<treatment>`:",
            "",
            "```",
            contrast_log.strip(),
            "```",
        ]

    if trial.interim:
        lines += [
            "",
            f"> **INTERIM — {result.n} of {trial.planned_pairs} planned pairs.** The p-value "
            "below is not this trial's result. A resumable apparatus whose report runs at "
            "any moment is a machine for stopping when the sign looks good; the planned n "
            "was frozen before the first launch so that stopping early is visible here "
            "rather than invisible everywhere.",
        ]

    lines += ["", "## Runs refused, before any number", ""]
    by_arm = trial.refusals_by_arm()
    # Printed even when both counts are zero. The paragraph below tells the reader to
    # judge the difference on this line, and a line that appears only once something has
    # already gone wrong is not there on the reading where they need it.
    lines.append(
        "- per arm: "
        + f"control `{result.control_arm}` {by_arm.get(result.control_arm, 0)}, "
        + f"treatment `{result.treatment_arm}` {by_arm.get(result.treatment_arm, 0)}"
    )
    if trial.refusals:
        for refusal in trial.refusals:
            lines.append(f"  - {refusal.summary}")
    else:
        lines.append("- no run was refused.")
    lines += ["", "| Clause | Runs refused |", "| --- | --- |"]
    for name, count in trial.refusals_by_clause().items():
        lines.append(f"| `{name}` | {count} |")
    lines += [
        "",
        "A clause showing zero has never been violated, or has stopped firing because the "
        "artifact it reads was renamed, or cannot fire at all on this path — a run killed "
        f"by quota or by the watchdog is refused by the driver and arrives above as a "
        f"`{DRIVER_CLAUSE_PREFIX}` row, never as `no_quota_in_logs`. All three look the "
        "same from here, which is why the count is printed rather than the failures alone.",
    ]
    if trial.refusals or trial.interim:
        lines += ["", _REFUSAL_BIAS]

    lines += ["", "## The difference", "", format_trial_report(result, unit=unit)]

    for pair in result.pairs:
        control = trial.evidence.get((pair.trial_id, result.control_arm))
        treatment = trial.evidence.get((pair.trial_id, result.treatment_arm))
        if control is None or treatment is None:  # pragma: no cover - pairing guarantees both
            continue
        lines += _format_pair(pair.trial_id, control, treatment)

    lines += [
        "",
        "## What this is a measurement of",
        "",
        "The number above is one judge's reading of one report against a checklist the "
        "run never saw, on tasks chosen because the two channels under test could show "
        "there at all. It is an upper bound on the benchmark-wide effect, not an "
        "estimate of it: nineteen of the forty tasks carry zero Mode-B text weight and "
        "nine have no text criteria whatsoever, so on those the Discussion cannot be "
        "read by any criterion.",
    ]
    return "\n".join(lines)


def _images_shown_lines(control: ArmEvidence, treatment: ArmEvidence) -> list[str]:
    """What the judge was actually shown, which the score file records and nothing read.

    Image criteria carry 60.6% of the benchmark's weight and every one of them is shown
    the same first five entries of one list that sweeps ``outputs/`` and then ``report/``.
    So "the treatment arm's figures scored better" and "the treatment arm emitted twelve
    figures and an arbitrary five of them were shown" produce the same number, and one
    real workspace on this box is already over the cap at six. This is not in the
    environment digest — how many figures a run produced is an effect of the change under
    test, not a confound to hold fixed — so the pair is admitted and the reader is told.
    """
    lines = [
        f"- images shown to the judge: control **{control.images_shown}** of "
        f"{control.images_available}, treatment **{treatment.images_shown}** of "
        f"{treatment.images_available}"
    ]
    capped = [
        name
        for name, arm in (("control", control), ("treatment", treatment))
        if arm.images_available > arm.images_shown
    ]
    if capped or control.images_shown != treatment.images_shown:
        lines.append(
            "- **The two arms were not shown the same evidence.** "
            + (
                f"The {' and '.join(capped)} arm's figures were over the scorer's cap, so "
                "an arbitrary five of them stood for all of them. "
                if capped
                else ""
            )
            + "Any movement in the image stratum below is figure count and figure "
            "selection as much as figure quality, and the image stratum is 60.6% of the "
            "benchmark's weight."
        )
    return lines


def _format_pair(task_id: str, control: ArmEvidence, treatment: ArmEvidence) -> list[str]:
    resolution = pair_resolution(control, treatment)
    delta = treatment.total_weighted - control.total_weighted
    lines = [
        "",
        f"### `{task_id}`",
        "",
        f"- total: control **{control.total_weighted:.2f}**, treatment "
        f"**{treatment.total_weighted:.2f}**, delta **{delta:+.2f}**",
        # Both counts, always, and never one of them labelled "per arm": an arm whose
        # replicates were lost to judge failures was printed as the other arm's count,
        # which is the one reading under which the number needs no caveat.
        f"- judge draws: control **{control.replicates}**, treatment "
        f"**{treatment.replicates}**, of "
        f"{control.replicates_requested or treatment.replicates_requested or '?'} planned",
    ]
    if resolution_is_measured(control, treatment):
        lines.append(
            f"- judge resolution on this pair: **±{resolution:.2f}** total points"
        )
    else:
        lines.append(
            "- judge resolution on this pair: **unmeasured**. A spread needs two draws, "
            "and one arm here has one, so nothing was observed about what this judge "
            "could not resolve on these two workspaces. Read the delta below against "
            "the folklore band it replaces — a text item has moved 30 raw points "
            "between judges on identical text — and not against zero."
        )
    if control.replicates_lost or treatment.replicates_lost:
        lines.append(
            f"- **Under-replicated.** {control.replicates_lost} control and "
            f"{treatment.replicates_lost} treatment replicate scorings were planned and "
            "never produced: `final_pass` gives each draw two tries and then moves on. "
            "The totals above are means over fewer draws than the plan asked for."
        )
    lines += _images_shown_lines(control, treatment)
    lines += ["", _ONE_OBSERVATION]

    if set(control.autor_stages_scored) != set(treatment.autor_stages_scored):
        lines += [
            "",
            f"- **the arms' own runs did not score the same stages** "
            f"(control {len(control.autor_stages_scored)}, treatment "
            f"{len(treatment.autor_stages_scored)}). The benchmark seam cannot see this: "
            "both arms are scored against the same checklist whatever their internal "
            "composition, so `shape_changes` is structurally zero here. That a revision "
            "changes how far a run gets is a separate result and is not in the delta.",
        ]

    lines += [
        "",
        "| # | type | w | control | treatment | delta | resolution |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for left, right in zip(control.items, treatment.items):
        lines.append(
            f"| {left.index} | {left.kind} | {left.weight:g} | {left.score:.1f} | "
            f"{right.score:.1f} | {right.score - left.score:+.1f} | "
            f"±{max(left.spread, right.spread):.1f} |"
        )

    rollup = stratum_rollup(control, treatment)
    lines += [
        "",
        "| stratum | share of weight | control | treatment | delta |",
        "| --- | --- | --- | --- | --- |",
    ]
    for kind, value in rollup["strata"].items():
        lines.append(
            f"| {kind} | {value['share']:.2f} | {value['control']:.1f} | "
            f"{value['treatment']:.1f} | {value['delta']:+.1f} |"
        )
    lines.append("")
    lines.append(
        f"Within this pair `delta_total = share_image*delta_image + share_text*delta_text` "
        f"to a residual of {rollup['residual']:+.4f}. Across pairs it does not hold — the "
        "three tasks have different image shares — so no cross-pair stratum total is "
        "printed. Only the text stratum is reachable by anything routed into Discussion: "
        "image criteria are shown the first 10,000 characters of the report and the "
        "Discussion is at the end."
    )

    deltas = [
        abs(right.weight * right.score - left.weight * left.score)
        for left, right in zip(control.items, treatment.items)
    ]
    movement = sum(deltas)
    if movement > 0:
        share = max(deltas) / movement
        floor = min_attainable_concentration(len(deltas))
        lines.append("")
        lines.append(
            f"Concentration on this pair: **{share:.0%}** of the movement is in one "
            f"checklist item (floor at {len(deltas)} items: {floor:.0%}). The pooled "
            "figure in the table above mixes items from different tasks into one "
            "denominator, which is why the per-pair number is printed too."
        )

    if not treatment.settled_reasoning_dose:
        lines += [
            "",
            "- **Zero settled-reasoning dose.** Stage 07's prompt in the treatment arm did "
            f"not carry `{SETTLED_REASONING_HEADING}`, which the channel emits whenever it "
            "has anything at all to send — a settled crux, a rejected hypothesis, or both. "
            "This pair did not administer the channel, so it is **not a test of it**, "
            "whichever way the delta went.",
        ]
    return lines


# ---------------------------------------------------------------------------
# The plan, and the planner
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArmSpec:
    label: str
    worktree: str
    sha: str


@dataclass(frozen=True)
class TrialPlan:
    """Frozen before the first launch, and hashed into every state file.

    One ``--plan PATH`` in place of ten arm/task/model/judge flags, because the repo
    owner has objected to flag proliferation and because a trial that runs for days
    needs its parameters in a file somebody can read afterwards, not in a shell history.
    """

    capability: str
    bench: str
    tasks: tuple[str, ...]
    control: ArmSpec
    treatment: ArmSpec
    judge_kind: str = "reference"
    judge_model: str = "gpt-5.1"
    agent_model: str = "opus"
    review_model: str = "opus"
    state_dir: str = "/rmeng_data/robtang/rcb-trial"
    #: ``control_first`` or ``counterbalanced``. See :func:`arm_order`.
    arm_order_mode: str = "control_first"
    #: Unix time after which no *new* run starts. A running one is left alone.
    deadline: float = 0.0
    stall_seconds: int = STALL_SECONDS
    replicates: int = SCORE_REPLICATES
    operator: str = "autor"
    #: Dry-run only: how much better the fake operator makes the treatment arm's
    #: report. Zero would give two identical columns, which a broken seam would pass.
    fake_quality: float = 0.0

    @property
    def planned_pairs(self) -> int:
        return len(self.tasks)

    def to_dict(self) -> dict[str, Any]:
        payload = dataclasses.asdict(self)
        payload["tasks"] = list(self.tasks)
        return payload

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TrialPlan":
        known = {spec.name for spec in dataclasses.fields(cls)}
        unknown = sorted(set(payload) - known - {"digest"})
        if unknown:
            raise ValueError(
                f"unknown plan fields: {', '.join(unknown)}. A misspelled field that is "
                "silently ignored is a parameter set wrong for four days."
            )
        values = {key: payload[key] for key in known if key in payload}
        values["tasks"] = tuple(values.get("tasks", ()))
        for side in ("control", "treatment"):
            if side in values:
                values[side] = ArmSpec(**values[side])
        plan = cls(**values)
        if plan.control.label == plan.treatment.label:
            raise ValueError("the two arms carry the same label; the difference would be zero")
        if not plan.tasks:
            raise ValueError("a plan with no tasks cannot become a measurement")
        return plan


def arm_order(plan: TrialPlan) -> tuple[tuple[str, str], ...]:
    """The launch order: pair-major, both arms of a task adjacent.

    Adjacency is the point — the two arms of one pair should straddle as little drift
    in Vertex load and judge behaviour as possible.

    ``control_first`` is the default and is what the shipped plan uses. The obvious
    alternative, alternating the within-pair order, de-confounds a first-versus-second
    position effect across pairs — but only if the pairs finish. This trial will very
    likely complete one or two of them, and with one pair completed an alternating
    order turns a position effect into something that cannot even be named afterwards.
    A fixed order leaves it confounded and *legible*: every treatment run ran second,
    and a reader can say so. ``counterbalanced`` is kept because with six pairs
    completed it is the better choice.
    """
    order: list[tuple[str, str]] = []
    for index, task in enumerate(plan.tasks):
        first, second = plan.control.label, plan.treatment.label
        if plan.arm_order_mode == "counterbalanced" and index % 2 == 1:
            first, second = second, first
        order.append((task, first))
        order.append((task, second))
    return tuple(order)


#: Quota, unlike a bad idea, recovers. Everything else about a dead run is terminal.
#:
#: Strings only a model backend emits. A bare ``429`` was in this tuple and it classified
#: every healthy run on this box as a quota death: all four real ``logs.txt`` here carry
#: ``429`` incidentally — a chi2 value, ``sources.json:429`` from a grep, a table cell,
#: and arXiv answering ``HTTP Error 429`` to a literature fetch that then succeeded —
#: while none of them contains ``RESOURCE_EXHAUSTED`` at all. Classifying a healthy run
#: as quota is not a conservative error: :func:`next_action` spends two backoffs and two
#: relaunches on it and then refuses the pair, so the whole trial ends with zero pairs
#: after nine hours of sleeping.
#:
#: :mod:`src.backend_health` reaches the same conclusion about the same substring and
#: defends against it by requiring an error-shaped line. That defence is not enough here:
#: arXiv's rate limit *is* an error-shaped line, and it is not the model backend refusing
#: to serve the run. :func:`count_quota_hits` reads this same tuple, because a classifier
#: and an admission clause that disagree about what a quota death is are two encodings of
#: one rule, and they had already drifted.
_QUOTA_MARKERS = ("RESOURCE_EXHAUSTED", "Quota exceeded", "rate_limit_error")


def classify_run(state: Mapping[str, Any]) -> str:
    """``ok`` / ``quota`` / ``backend`` / ``fallback`` / ``incomplete`` / ``stalled``.

    Quota is checked against the run's own ``logs.txt`` and not only against
    ``last_event``, because ``classify_backend`` runs only when neither the primary nor
    the repair attempt wrote a stage file. A 429 that lands mid-stage leaves
    ``last_event == "run.completed"`` and the error text baked into a stage summary, and
    a driver that reads only the manifest retries nothing and refuses nothing.

    It is never checked against the driver's stdout. The operator catches the API error
    and writes it to the run's log; a retry loop that greps the driver's stdout has
    never once fired.
    """
    if state.get("stalled"):
        return "stalled"
    log_text = str(state.get("run_log_text", ""))
    if any(marker in log_text for marker in _QUOTA_MARKERS):
        return "quota"
    if state.get("last_event") == "run.backend_unavailable":
        return "quota" if state.get("backend_cause") == "quota" else "backend"
    if state.get("meta_status") != "completed":
        return "incomplete"
    if state.get("meta_report_source") != "agent":
        return "fallback"
    return "ok"


@dataclass(frozen=True)
class Action:
    """What the shell should do next. A value, so the planner can be tested at all."""

    kind: str
    task_id: str = ""
    arm: str = ""
    attempt: int = 0
    seconds: int = 0
    reason: str = ""


def next_action(
    plan: TrialPlan,
    states: Sequence[Mapping[str, Any]],
    *,
    now: float,
    live_pids: frozenset[int] = frozenset(),
    final_pass_done: bool = False,
) -> Action:
    """The whole recovery policy, as a pure function of the state directory.

    Written as a value-returning function rather than as control flow inside the driver
    because the alternative is testing multi-day kill-and-restart behaviour by spending
    multi-day kill-and-restart wall clock.
    """
    for state in states:
        if state.get("phase") == "launched" and int(state.get("child_pid") or 0) in live_pids:
            return Action(
                "abort",
                task_id=str(state.get("task_id", "")),
                arm=str(state.get("arm", "")),
                reason=(
                    f"a child from a previous driver is still running (pid "
                    f"{state.get('child_pid')}). Adopting it cannot recover its exit code "
                    "honestly, and starting alongside it is the concurrency that exhausts "
                    "the quota."
                ),
            )

    by_key: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for state in states:
        key = (str(state.get("task_id", "")), str(state.get("arm", "")))
        by_key.setdefault(key, []).append(state)

    for key in arm_order(plan):
        entries = by_key.get(key, [])
        task_id, arm = key
        if any(item.get("phase") == "refused" for item in entries):
            # Terminal. Re-emitting the refusal would loop, and re-launching after one
            # would spend the budget the refusal exists to stop spending.
            continue
        attempts = sorted(entries, key=lambda item: int(item.get("attempt") or 0))
        if not attempts:
            if now >= plan.deadline > 0:
                continue
            return Action("launch", task_id=task_id, arm=arm, attempt=1)

        latest = attempts[-1]
        attempt = int(latest.get("attempt") or 1)
        phase = str(latest.get("phase", ""))
        launches = len(attempts)
        backoffs = sum(1 for item in attempts if item.get("classification") == "quota")

        if phase == "launched":
            return Action(
                "abandon",
                task_id=task_id,
                arm=arm,
                attempt=attempt,
                reason=(
                    "the driver died with this run in flight and the child is gone. "
                    "`rcb_agent.py` has no resume — only `--export-only` — so the attempt "
                    "is abandoned and re-planned into a fresh workspace, and the old one "
                    "is left on disk because `.autor/` lives inside it."
                ),
            )

        classification = str(latest.get("classification") or classify_run(latest))
        if phase == "abandoned" or classification in ("backend", "stalled"):
            if launches - backoffs >= MAX_ATTEMPTS or now >= plan.deadline > 0:
                return Action("refuse", task_id=task_id, arm=arm, reason=classification or "abandoned")
            return Action("launch", task_id=task_id, arm=arm, attempt=attempt + 1)

        if classification == "quota":
            if backoffs > MAX_BACKOFFS or now >= plan.deadline > 0:
                return Action("refuse", task_id=task_id, arm=arm, reason="quota")
            wait = BACKOFF_SCHEDULE_SECONDS[min(backoffs - 1, len(BACKOFF_SCHEDULE_SECONDS) - 1)]
            return Action(
                "backoff", task_id=task_id, arm=arm, attempt=attempt + 1, seconds=wait,
                reason="quota is per-base-model and recovers; a first 429 is not a verdict",
            )

        if classification in ("fallback", "incomplete"):
            # The run ran and produced a non-run. Retrying is a fresh draw on the same
            # dice, and it is not the failure retrying is for.
            return Action("refuse", task_id=task_id, arm=arm, reason=classification)

        if not latest.get("scored"):
            return Action("score", task_id=task_id, arm=arm, attempt=attempt)

    if not final_pass_done:
        return Action("final_pass")
    return Action("done")


# ---------------------------------------------------------------------------
# Reading a workspace (parsing only; the tool does the I/O)
# ---------------------------------------------------------------------------


def count_quota_hits(log_text: str) -> int:
    """How many quota refusals the run's own log records.

    The same markers :func:`classify_run` reads, deliberately: the clause
    ``no_quota_in_logs`` and the classifier are one rule about what a quota death looks
    like, and when they were two tuples they disagreed.
    """
    return sum(len(re.findall(re.escape(marker), log_text)) for marker in _QUOTA_MARKERS)


def items_from_score_payloads(payloads: Sequence[Mapping[str, Any]]) -> tuple[ScoredItem, ...]:
    """Zip N replicate scorings of one workspace into one item vector.

    Positional pairing is sound and checked: ``score.py`` enumerates the checklist in
    file order, the serial executor preserves order by construction, and ``content[:200]``
    is unique inside every one of the forty shipped checklists — so the content key is
    asserted equal across replicates rather than trusted.
    """
    if not payloads:
        return ()
    base = list(payloads[0].get("items") or [])
    for other in payloads[1:]:
        rows = list(other.get("items") or [])
        if len(rows) != len(base):
            raise ValueError("replicate scorings returned different item counts")
        for left, right in zip(base, rows):
            if str(left.get("content", "")) != str(right.get("content", "")):
                raise ValueError(
                    "replicate scorings disagree about item identity; the checklist "
                    "changed underneath the trial"
                )
    items: list[ScoredItem] = []
    for position, row in enumerate(base):
        scores = tuple(
            int((list(payload.get("items") or [])[position]).get("score", 0))
            for payload in payloads
        )
        items.append(
            ScoredItem(
                index=int(row.get("index", position)),
                kind=str(row.get("type", "text")),
                weight=float(row.get("weight", 0.0)),
                content_key=str(row.get("content", "")),
                scores=scores,
            )
        )
    return tuple(items)
