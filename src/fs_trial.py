"""Measure a capability against FrontierScience-Research, where the arms are producers.

The sibling of :mod:`src.rcb_trial`, and the same seam: :mod:`src.trials` already does
the statistics honestly, :class:`src.trials.Pair` is the only reader of ``stage_fitness``
and ``criterion_fitness`` anywhere in the tree, and swapping the outcome measure is
swapping what fills them. What is different here is what an *arm* is, and almost every
decision below follows from that one difference.

**An arm is an answer producer, not a git revision.** ResearchClawBench's trial compares
two checkouts of AutoR running the same entry point, so an arm is a commit and
``revision_matches_arm`` is the whole of arm identity. The question this benchmark is
asked is different: does a no-browsing AutoR run entered at Stage 02 write a better exam
answer than one long call to the same underlying model? One arm is a pipeline in a
worktree at a commit; the other is a single call to a model, with no worktree and no
commit at all. So :class:`FsArmSpec` carries ``kind``, ``model`` and ``answer_guidance``
for both, and ``worktree``/``sha``/``review_model``/``profile`` only for the ``autor``
side, and :func:`_refuse_a_label_that_is_not_the_producer` runs at *freeze* time. That
timing is the lesson and not a nicety: the sibling trial accepted a plan labelled
``{"label": "off", "sha": "621566b"}`` -- the obvious way to write an on/off trial --
launched it, and had every arm refused by the clause that reads the label. Twelve runs,
twelve refusals, zero pairs, and a report whose exclusion lines named the clause but not
the cause.

**Where ResearchClawBench declares a composition, this trial declares none, and that is
an argument rather than an omission.** ``collect_pairs(composition=...)`` exists because
a benchmark total is one key per arm by construction, so ``Pair.same_shape`` could not
see that one arm abandoned at Stage 06 and the other ran to Stage 08. Handing it "how
far the run got" here would set aside *every* pair: a pipeline arm approves one stage and
a single-call arm approves none, by design, for ever. The report would then say "there is
no same-shape pair yet" over a trial that ran perfectly, which is the shape of failure
this module exists to avoid rather than an instance of the refusal working. What plays
composition's part here is two admission clauses: ``stages_approved_exactly`` pins each
arm's shape to the one value its kind is allowed to have, and ``no_auto_skips`` refuses a
run that got a different distance. A run whose composition moved is refused into the
ledger with its own name, which is what the reader needed from the set-aside line.

**The mapping.** ``stage_fitness`` gets exactly one key, ``"<task_key>|<env_digest>"``.
One key because ``Pair._mean_over`` is an unweighted mean and a mean over one element is
that element, so ``Pair.difference`` is the rubric-point difference exactly. The
environment digest is in the key because a pair whose two arms used different judges,
different models, a different instruction or a different guidance is a composition
difference, and ``collect_pairs`` already refuses to compare across one. Folding the
environment into the key makes that refusal fire on a confounded pair with no new gate to
write -- and, more to the point, no new gate to get wrong.

``criterion_fitness`` is ``{}``, and the report says so out loud rather than leaving a
blank table. ResearchClawBench's judge returns a score per checklist item, so its
decomposition is the total's decomposition and ``concentration`` means "share of the
movement in one item". This judge returns *one number*. The per-item scores exist only as
prose inside its reasoning, in a format measured to be unstable -- one response numbered
its sections ``Item N`` and another wrote ``Rubric section:`` and drilled into
sub-items -- so scraping them would be a second instrument, unvalidated, published beside
a validated one. An empty decomposition is safe all the way through the renderer:
``TrialResult.concentration`` returns 0.0 when the movement is zero, and
``format_trial_report`` guards the whole criterion block behind ``if deltas:``.

**Why there is no adaptive re-judge, written here because the feature is invisible.** An
earlier draft of this design promoted a task to more judge draws when its first score
landed near the pass threshold, which is the obvious way to spend a judge budget well.
It cannot be built on this seam. ``judge_replicates`` is in the environment digest -- it
has to be, because an arm averaged over three draws and an arm averaged over one are not
comparable, and one draw carries the judge's full sampling range into the delta while the
other has averaged its own away. So promoting one arm of a pair changes that arm's
digest, empties the pair's shared-stage intersection, and drops the pair. Silently, and
worse than silently: the pairs it would drop are exactly the ones nearest the threshold,
the ones a reader most wants, and the exclusion line they arrive under reads "the two
arms measured no stage in common", which is true and tells nobody what happened. If the
feature is ever wanted, the promotion has to be applied to **both arms of a pair at
once**, and ``judge_replicates`` has to stay in the digest so that a half-applied
promotion is loud.

**No record written here is ever persisted.** ``RunRecord.usable`` requires
``rubric_version == RUBRIC_VERSION``, and a benchmark row carrying AutoR's rubric version
is a claim it cannot support. The containment is structural: no :class:`src.archive.Archive`
is constructible from this module or from ``tools/fs_trial.py``, and a test asserts it
stays that way. If one of these rows reached ``Archive.variant_fitness``, 0-10 rubric
points would pool with [0, 1] rubric means *and* with ResearchClawBench's 0-100 totals --
three units in one bucket -- and drive topology promotion off a unit error.

**Ten clauses, each refusing a pair.** Refusing one arm turns the pair into "there was no
treatment arm" and hides the cause, so a clause refuses the pair and the ledger prints
every clause at its count even when the count is zero. Each is written from something
that happened: measured over the forty real ResearchClawBench runs on this box,
thirty-nine of forty wrote ``status: "completed"`` and the fortieth wrote no result line
at all; 77.5% auto-skipped at least one stage and 20% auto-skipped the stage being
scored; and ``AnswerSynthesizer`` will happily assemble a deliverable out of nothing when
no stage was ever approved. None of those is a bad run. Each is a *non-run* that produces
a plausible number, and averaging one into a paired difference is how a measurement
becomes fiction.

**Names are prefixed ``Fs``/``fs_`` where a sibling already owns the bare name**, and the
reason is a gate rather than taste. ``tests/test_declared_symbols_are_wired.py`` matches
bare identifiers across ``src/``, so a symbol here called ``admit_arm`` would read as
referenced because :mod:`src.rcb_trial` defines and calls one -- exactly how
``git_contrast_log`` stayed invisible to that scan while it was called ``contrast_log``.
Two benchmarks sharing a vocabulary would launder each other's dead code in both
directions.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Mapping, Sequence

from .archive import RunRecord
from .frontierscience import (
    FS_ANSWER_GUIDANCE_CHOICES,
    FS_DATASET_POINTS_PER_ROW,
    FS_IDEATE_STAGE,
    FS_MAX_ANSWER_CHARS,
    FS_MIN_ANSWER_CHARS,
    FS_PROFILE_CHOICES,
    FS_REFUSAL_ANSWER_IS_A_PLAN,
    FS_SOURCE_FALLBACK,
    FS_TASK_INSTRUCTION_SHA256,
    FS_TASK_KEY_PREFIX,
    has_refusal,
    task_key,
)
from .fs_scoring import FS_JUDGE_NOISE_NOTE, FS_PASS_THRESHOLD
from .rubric import RUBRIC_VERSION
from .trials import (
    FS_TOTAL,
    SAMPLED_SIGN_ASSIGNMENTS,
    SIGN_FLIP_SEED,
    TrialResult,
    collect_pairs,
    format_trial_report,
)


#: Attempts per ``(task, arm)`` before the pair is refused, counting abandoned drivers.
#: Applied identically to both arms -- an asymmetric retry budget is a thumb on the
#: scale, and the arms are already asymmetric in cost, which is the direction that would
#: tempt somebody to give the expensive one more tries.
FS_MAX_ATTEMPTS = 2

#: No heartbeat on ``logs_raw.jsonl`` for this long and the run is hung. The only
#: second-granularity signal an AutoR run emits: ``run_manifest.json`` updates on stage
#: transitions only, and ``_meta.json`` is written once at the end. Deliberately absent
#: beside it: a per-run wall clock. The single measured per-stage duration for a
#: comparable configuration on this box was 2100 s, and AutoR's own wall clock on the
#: sibling benchmark has a median of 15.2 hours over 39 runs, so any cap short enough to
#: catch a hang is short enough to kill a run that was going to finish.
FS_STALL_SECONDS = 2700

#: How long a ``launched`` run is given to become visible before it may be called dead.
#:
#: The liveness test is ``child_pid in autor_pids(...)``, and that set is built by walking
#: ``/proc`` and substring-matching each command line. Neither end of it is instantaneous.
#: Measured on this box, over twelve samples on a quiet and a loaded machine, a child took
#: **33-42 ms** to appear in that set -- and most of it is the ``/proc`` walk itself, not
#: the child, so the floor rises with the number of processes on the box. Before that, a
#: perfectly healthy run reads as dead.
#:
#: What it cost with no grace at all: ``tools/fs_trial.py`` writes the run's state file
#: *before* ``Popen``, so there is also a window in which the state says ``launched`` and
#: carries no ``child_pid`` -- ``int(None or 0)`` is 0, 0 is in no pid set, and the run is
#: abandoned microseconds after it was started. The replacement gets a fresh workspace and
#: a fresh attempt while the original child is still executing, so the trial pays twice
#: and the abandoned attempt's state file stays in its launch shape for ever. In
#: ``tests/test_fs_trial_driver.py`` the poll interval is overridden to 20 ms -- shorter
#: than one ``/proc`` scan -- which turned this into an intermittent extra attempt that
#: failed a different test on about one module run in three.
#:
#: Sixty seconds is three orders of magnitude above the measured latency and forty-five
#: times *below* :data:`FS_STALL_SECONDS`, which is this module's existing statement about
#: how long a run may be silent before anyone worries. Waiting a minute before declaring a
#: run that has just started dead is strictly more conservative than the policy already in
#: force for one that has gone quiet.
FS_LAUNCH_GRACE_SECONDS = 60

#: Above this share of refused runs in *either* arm, the paired difference is not
#: published at all -- only the refusal rates are. Refusals are not random with respect
#: to arm: the pipeline arm can be refused for a stage timeout, an auto-skip or a
#: synthesized answer, and the single-call arm structurally cannot be refused for any of
#: the three. The survivors are then the subset where the pipeline happened to run
#: cleanly, which is a sample of its easier tasks, and the difference is biased upward.
FS_MAX_REFUSAL_RATE = 0.20

#: The smallest difference worth detecting, in rubric points out of ten, declared before
#: the trial rather than read off it. Half a point is a fifth of the across-task standard
#: deviation measured for a direct ``claude-opus-4-5`` arm (2.345 over 21 tasks) and
#: about 1.5 times the judge's own sampling sd at the scores where that sd was measured
#: (0.326 over 23 draws on two tasks scoring 2.5-3.3; the sd at 7 points is UNMEASURED).
#: A trial powered below this is reporting that it could not have seen the effect.
FS_MINIMUM_EFFECT = 0.5

#: ``z_{0.975} + z_{0.80}``. The multiplier in the minimum-detectable-effect arithmetic,
#: written out because the two halves answer different questions -- 1.96 is the false
#: positive rate and 0.8416 is the power -- and a single 2.8 in the code invites the
#: reading that it is a fudge factor. This is a normal approximation to a test that is
#: not normal: :func:`src.trials.sign_flip_p` permutes signs and makes no distributional
#: assumption, and the approximation is stated in the report as the approximation it is.
FS_MDE_MULTIPLIER = 1.959964 + 0.841621

#: The two-sided 95% coefficient for a Wilson interval on ``pass@>=7``. Wilson and not
#: Wald, because Wald's interval is degenerate at exactly the counts this trial expects:
#: a measured direct-opus arm passed 3 of 21, and at 0 of 21 -- which a subject slice can
#: easily produce -- Wald reports the interval [0, 0] and claims certainty from an
#: absence.
FS_WILSON_Z = 1.959964

#: What ``_meta.stages_approved`` must hold, per arm kind. Exactly, not at least: the
#: ideate arm walks one stage and the direct arm walks none, so an arm carrying a
#: different list did not run the procedure its label names.
#:
#: The direct arm's ``()`` is the half that is easy to leave out, and leaving it out is
#: the freeze-time defect in another costume. The design table wrote this clause as
#: ``stages_approved == ["02_hypothesis_generation"]`` full stop; applied to a direct arm
#: -- which has no manager, no reviewer and therefore no approved stage -- it refuses
#: every control run of every pair, and the trial ends with zero pairs after spending
#: both arms.
FS_STAGES_APPROVED_BY_KIND: Mapping[str, tuple[str, ...]] = {
    "autor": (FS_IDEATE_STAGE,),
    "direct": (),
}

#: The two producer kinds an arm may be. ``autor`` runs the pipeline in a worktree at a
#: commit; ``direct`` makes one call to a model and keeps the reply.
FS_ARM_KINDS = tuple(sorted(FS_STAGES_APPROVED_BY_KIND))

#: ``fs:043``. Checked at freeze time so that a mistyped task list costs a string
#: comparison rather than a launch: the driver never opens the dataset -- the two
#: subprocesses it starts do, each against the pinned digest -- so a key nothing can
#: resolve would otherwise be discovered by ``fs_agent.py`` after the workspace exists.
FS_TASK_KEY_PATTERN = re.compile(rf"^{re.escape(FS_TASK_KEY_PREFIX)}[0-9]{{3}}$")

#: The faults :attr:`FsTrialPlan.fake_faults` may ask the dry run's fake operator for,
#: each naming the admission clause it exists to make fire from end to end.
#:
#: ``no-transcript`` is the sharpest of the three and the reason this knob exists at all:
#: it produces a run with a perfectly ordinary ``_meta.json`` and no witness behind it,
#: which is the state a ``browsing_tool_calls == 0`` clause would admit if the metadata
#: recorded zero instead of null. Reachable only by fabricating the absence, and a unit
#: test that fabricates it in a dictionary is testing the clause against its own
#: statement.
FS_FAKE_FAULTS: Mapping[str, str] = {
    "browse": "no_browsing",
    "no-transcript": "no_browsing",
    "truncate": "answer_not_truncated",
}

#: Clause names for the refusals the driver makes before the gate can see the run at all.
#: They share the ledger with the ten admission clauses because they lose the reader the
#: same thing -- a pair -- and because the ledger's whole job is the per-arm death count.
FS_DRIVER_CLAUSE_PREFIX = "driver:"


def _digest(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# The environment a run was measured in
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FsRunEnvironment:
    """Everything that changes the number without changing the thing under test.

    Eight fields that two arms must agree on to be comparable, and a ninth that is a
    plan-level constant today and is recorded anyway. Every one is *observed* off the
    artifacts rather than copied from the plan: a field filled from the plan agrees by
    construction and is therefore not the field the contract names, and the confounds
    worth catching are exactly the ones where the plan said one thing and the run did
    another.
    """

    #: The bytes the question came from, as the scorer measured them. Not the plan's
    #: declaration: ``load_dataset`` refuses anything but the pinned digest today, and
    #: the moment that pin is relaxed this is the field that still says which file was
    #: answered.
    dataset_sha256: str = ""
    #: Worth about sixteen points on identical artifacts on the sibling benchmark. Same
    #: judge both arms or there is no comparison, and the paper's GPT-5 is a 404 on this
    #: endpoint, so this is never the paper's judge.
    judge_model: str = ""
    #: ``low`` / ``medium`` / ``high``. A different effort is a different instrument, and
    #: the published numbers this harness is read against were produced at ``high``.
    judge_reasoning_effort: str = ""
    #: The model that wrote the answer. The whole point of the paired baseline is that
    #: both arms sit on the same one, so that what is measured is the scaffolding.
    answer_model: str = ""
    #: ``paper`` / ``minimal`` / ``coverage``. A declared prompt intervention: ``coverage``
    #: tells the agent the rubric's shape, so it must be applied to both arms or to
    #: neither, and the digest is what makes a half-applied one impossible to average.
    answer_guidance: str = ""
    #: sha256 of the verbatim task instruction both arms were given. Frozen in the plan
    #: and re-read here off the run, so an instruction edited between the two arms of a
    #: pair separates them instead of averaging them.
    task_instruction_sha256: str = ""
    #: The tools every model seat in the run was actually carrying, as a sorted tuple.
    #: What the flags *asked for* is not this: a backend with no denied-tool knob records
    #: that it denied nothing, and a run-level sentence that cannot be falsified by one
    #: seat is the intersection.
    disallowed_tools: tuple[str, ...] = ()
    #: How many answer runs this arm's total is the mean over. One today, for every arm,
    #: because the driver produces one evidence per run and pools nothing -- and it is in
    #: the digest so that an arm pooled over three attempts can never be averaged against
    #: an arm that ran once.
    answer_attempts: int = 1
    #: How many judge draws this arm's published total is the mean of. A plan-level
    #: constant, so today it is equal across the two arms by construction and this field
    #: catches nothing -- which is exactly why it is recorded rather than assumed. It is
    #: the field an adaptive re-judge would move, and the module docstring says what that
    #: would do to the pairs nearest the threshold.
    judge_replicates: int = 0

    @property
    def digest(self) -> str:
        return _digest(dataclasses.asdict(self))

    def describe_difference(self, other: "FsRunEnvironment") -> list[str]:
        """Name every field that differs, in the report's voice.

        The digest is the gate; this is the diagnostics. Their separation is deliberate:
        a bug here cannot let a confounded pair through, because the pair dies on the key
        mismatch whatever this returns. What a bug here *can* do is leave a reader with
        "the two arms measured no stage in common", which is true and useless, so
        :func:`collect_fs_pairs` asserts the two stay in step.
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
class FsArmSpec:
    """One answer producer, described completely enough to be checked against a run.

    ``kind`` decides which of the remaining fields mean anything, and both kinds are
    checked at freeze time by :func:`_refuse_a_label_that_is_not_the_producer`.
    """

    label: str
    kind: str
    model: str
    answer_guidance: str
    #: ``autor`` only: the checkout the pipeline runs from.
    worktree: str = ""
    #: ``autor`` only: the commit that checkout is at. The label must prefix-match it
    #: both ways, because the label is the only carrier of the revision that reaches the
    #: admission gate.
    sha: str = ""
    #: ``autor`` only. Passed with ``--model`` always: the reviewer's model is resolved
    #: independently, so an arm that names one and not the other leaves the panels on
    #: whatever the backend defaults to.
    review_model: str = ""
    #: ``autor`` only: ``ideate``. Recorded rather than assumed so that a second pipeline
    #: profile is a plan edit and not a code edit.
    profile: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FsArmSpec":
        """Refuse an unknown field rather than ignore it.

        The same rule as :meth:`FsTrialPlan.from_dict` and for the same reason: a
        misspelled ``review_model`` that is silently dropped is a reviewer running on the
        backend default for the length of the trial, and nothing says so.
        """
        known = {spec.name for spec in dataclasses.fields(cls)}
        unknown = sorted(set(payload) - known)
        if unknown:
            raise ValueError(
                f"unknown arm fields: {', '.join(unknown)}. An arm is the description of a "
                "producer, and a field nobody reads is a producer nobody described."
            )
        values = {key: str(payload.get(key, "")) for key in known}
        return cls(**values)

    @property
    def expected_stages_approved(self) -> tuple[str, ...]:
        return FS_STAGES_APPROVED_BY_KIND.get(self.kind, ())

    def describe(self) -> str:
        """One line a reader can check the arm against, with nothing left implicit."""
        if self.kind == "autor":
            return (
                f"`{self.label}` -- AutoR `{self.profile or '<no profile>'}` at "
                f"`{self.sha or '<no sha>'}` in `{self.worktree or '<no worktree>'}`, "
                f"answering with `{self.model}`, reviewing with "
                f"`{self.review_model or self.model}`, guidance `{self.answer_guidance}`"
            )
        return (
            f"`{self.label}` -- one direct call to `{self.model}`, guidance "
            f"`{self.answer_guidance}`"
        )


@dataclass(frozen=True)
class FsArmEvidence:
    """One arm of one pair: what was scored, and everything the gate needs to see."""

    task_key: str
    spec: FsArmSpec
    run_id: str
    workspace: str
    env: FsRunEnvironment
    #: The driver's own reading: the mean of the per-draw points it found in the score
    #: files. Reconciled against :attr:`published_total` in :func:`to_fs_run_record`,
    #: because they are one number written by two readers.
    total_points: float
    #: ``aggregate_draws``' own ``total_score``, averaged over the score files. The other
    #: encoding.
    published_total: float
    #: Every judge draw's points, in file order. What a spread would be measured over,
    #: and what makes "one draw" and "three draws that agreed" different sentences.
    draw_points: tuple[float, ...] = ()
    #: What the plan asked for, so "scored once" and "scored once because two of three
    #: draws were refused" are different sentences rather than the same one.
    draws_requested: int = 0
    judge_failures: tuple[str, ...] = ()
    #: Read off the score file's ``task`` block rather than out of the dataset. The
    #: driver never opens the dataset -- the agent and the scorer each do, against the
    #: pinned digest -- so what the report groups by is what was actually scored.
    subject: str = ""
    row_index: int = -1
    duplicate_of: int | None = None
    rubric_points_total: float = FS_DATASET_POINTS_PER_ROW
    #: Admission facts, read off ``_meta.json`` and the answer file by the tool. A
    #: mapping rather than fields so that the gate and the reader agree about what was
    #: looked at.
    facts: Mapping[str, Any] = field(default_factory=dict)
    #: The task keys this evidence's total is a mean over. One in the ordinary case; two
    #: for the pair that the byte-identical rows 6 and 11 collapse into.
    merged_from: tuple[str, ...] = ()

    @property
    def arm(self) -> str:
        return self.spec.label

    @property
    def kind(self) -> str:
        return self.spec.kind

    @property
    def draws(self) -> int:
        return len(self.draw_points)

    @property
    def spread(self) -> float | None:
        """Max minus min across judge draws, or ``None`` with fewer than two.

        ``None`` and never 0.0. A single draw that reported a spread of zero would state
        a smaller uncertainty than three draws that disagreed, which is exactly backwards
        and reads off the page as "this judge resolved the answer exactly" on the one
        arm where nothing about the judge's noise was observed at all.
        """
        if len(self.draw_points) < 2:
            return None
        return max(self.draw_points) - min(self.draw_points)


# ---------------------------------------------------------------------------
# Admission: is this run a measurement at all?
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FsAdmissionClause:
    name: str
    why: str
    test: Callable[[FsArmEvidence], bool]


def _fact(evidence: FsArmEvidence, name: str, default: Any = None) -> Any:
    return evidence.facts.get(name, default)


def _is_count(value: Any) -> bool:
    """A real integer count, and not ``None`` and not a bool.

    ``None`` is "not observed" everywhere in ``_meta.json``'s transcript fields, and the
    whole point of that convention is that a run which produced no evidence must not
    satisfy a ``== 0`` clause by having none. ``bool`` is excluded because ``True == 1``
    and ``False == 0`` in Python, so a field that turned into a flag would silently pass
    a count check.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def _answer_not_fallback(evidence: FsArmEvidence) -> bool:
    """Two independent witnesses, because the metadata is written by the party gated.

    ``_meta.answer_source`` is what the exporter recorded; the marker is the first line
    of the answer file itself, which the fallback path writes before anything can decide
    what to call it. One field is a claim about the file; the other is the file. On the
    sibling benchmark a run killed by quota exported a fallback report and was scored as
    an attempt, worth about 7.5 points of nothing.
    """
    if _fact(evidence, "meta_answer_source") == FS_SOURCE_FALLBACK:
        return False
    marked = _fact(evidence, "answer_first_line_is_fallback")
    return marked is False


def _stages_approved_exactly(evidence: FsArmEvidence) -> bool:
    approved = _fact(evidence, "meta_stages_approved")
    if not isinstance(approved, list):
        return False
    return tuple(str(item) for item in approved) == evidence.spec.expected_stages_approved


def _answer_within_bounds(evidence: FsArmEvidence) -> bool:
    chars = _fact(evidence, "answer_chars")
    if not _is_count(chars) or not (FS_MIN_ANSWER_CHARS <= chars <= FS_MAX_ANSWER_CHARS):
        return False
    refusals = _fact(evidence, "answer_refusals")
    reasons = [str(item) for item in refusals] if isinstance(refusals, list) else []
    return not has_refusal(reasons, FS_REFUSAL_ANSWER_IS_A_PLAN)


def _answer_not_truncated(evidence: FsArmEvidence) -> bool:
    """Dispatched by operator, because the two backends say it in different places.

    The Claude CLI streams JSON and the only witness is ``stop_reason`` on the result
    lines; ``max_tokens`` on *any* call in the run counts, because a stage that was cut
    off and retried leaves a complete final answer standing on an incomplete one. The
    Responses path says it in ``status`` and ``incomplete_details`` instead, which is
    where the sibling scorer found an HTTP 200 carrying an incomplete answer that stopped
    mid-sentence at 636 characters.

    A backend that recorded neither is refused rather than admitted. That is the safe
    direction and it is not free: no codex arm can be admitted until somebody records
    those two fields, and the honest way to notice that is a refusal ledger row rather
    than a silent pass.
    """
    if str(_fact(evidence, "operator", "")) == "claude":
        return _fact(evidence, "truncated") is False
    status = _fact(evidence, "responses_status")
    return status == "completed" and not _fact(evidence, "responses_incomplete_reason")


def _no_browsing(evidence: FsArmEvidence) -> bool:
    """Run for both arms, and a null witness refuses.

    The published protocol for this benchmark is "without browsing", so the count is a
    condition on the *result* rather than on comparability, which is why it is a clause
    and not a digest field. Both arms: the earlier draft of this design said the direct
    arm structurally could not browse, and reading ``src/operator.py`` says otherwise --
    the non-repair path passes no tool restriction at all unless one is asked for.

    ``None`` refuses. A run with no transcript -- a crash before the first call -- has
    produced no evidence about what it reached for, and admitting it would let the
    absence of a witness stand in for the testimony of one.
    """
    return _is_count(_fact(evidence, "browsing_tool_calls")) and (
        _fact(evidence, "browsing_tool_calls") == 0
    )


def _producer_matches_arm(evidence: FsArmEvidence) -> bool:
    """The run was produced by the thing the arm's label names.

    Both halves run on both kinds. The model check is symmetric because both kinds
    declare a model and an asymmetric gate is a thumb on the scale; the revision check
    is additional for ``autor``, where there is a worktree whose HEAD can move between
    launch and finish and whose working tree can be dirty. The label must prefix-match
    the sha both ways, and not merely contain it: a seven-character sha appearing
    somewhere inside a forty-character one is chance.
    """
    if str(_fact(evidence, "meta_model", "")) != evidence.spec.model:
        return False
    if evidence.kind != "autor":
        return True
    launch = str(_fact(evidence, "revision_at_launch", ""))
    finish = str(_fact(evidence, "revision_at_finish", ""))
    if not launch or launch != finish:
        return False
    if _fact(evidence, "worktree_dirty", True):
        return False
    sha = evidence.spec.sha.strip()
    return bool(sha) and (launch.startswith(sha) or sha.startswith(launch))


def _every_draw_judged(evidence: FsArmEvidence) -> bool:
    return (
        not evidence.judge_failures
        and evidence.draws > 0
        and evidence.draws == evidence.draws_requested
    )


#: Every clause refuses a *pair*, not an arm, because refusing one arm turns the pair
#: into "there was no treatment arm" and hides the cause. Each is a fixture in the tests,
#: with a positive and a negative case, and the report prints how many runs each one
#: refused -- a clause that has silently stopped firing because a metadata field was
#: renamed shows up as a zero rather than as nothing at all.
FS_ADMISSION_CLAUSES: tuple[FsAdmissionClause, ...] = (
    FsAdmissionClause(
        "meta_status_completed",
        "`_meta.status` must be `completed`. It is computed from the six exit clauses "
        "rather than handed in, so a run that says otherwise is one that failed its own "
        "check -- and on the sibling benchmark thirty-nine of forty runs wrote "
        "`completed` while a fifth of them had auto-skipped the stage being scored.",
        lambda ev: _fact(ev, "meta_status") == "completed",
    ),
    FsAdmissionClause(
        "pipeline_completed",
        "`_meta.pipeline_completed` must be true. A second, independent witness to the "
        "clause above, and not a duplicate of it: `_route_to_deliverable` returns False "
        "when the final stage is the one already reached, which aborts the run with "
        "`auto_skipped_stages` still empty -- so this is the only field that separates a "
        "pipeline that walked its stage from one that never entered it.",
        lambda ev: _fact(ev, "meta_pipeline_completed") is True,
    ),
    FsAdmissionClause(
        "stages_approved_exactly",
        "`_meta.stages_approved` must be exactly what this arm's kind walks: "
        f"`{list(FS_STAGES_APPROVED_BY_KIND['autor'])}` for an AutoR arm and `[]` for a "
        "direct one. This is what separates a synthesized answer from an answer "
        "synthesized out of nothing, and it is what stands in for the composition "
        "declaration the sibling trial makes.",
        _stages_approved_exactly,
    ),
    FsAdmissionClause(
        "answer_not_fallback",
        "`_meta.answer_source` must not be `fallback`, and the answer's first line must "
        "not carry the fallback marker. Two witnesses because one of them is written by "
        "the party the gate constrains.",
        _answer_not_fallback,
    ),
    FsAdmissionClause(
        "no_auto_skips",
        "`_meta.auto_skipped_stages` must be empty. Measured on the sibling benchmark: "
        "77.5% of forty real runs auto-skipped at least one stage and 20% auto-skipped "
        "the stage being scored, and the field appears in none of their metadata files "
        "-- it existed only in the stdout event stream, so every downstream recorded "
        "them as successes.",
        lambda ev: isinstance(_fact(ev, "meta_auto_skipped_stages"), list)
        and not _fact(ev, "meta_auto_skipped_stages"),
    ),
    FsAdmissionClause(
        "answer_within_bounds",
        f"The answer is between {FS_MIN_ANSWER_CHARS} and {FS_MAX_ANSWER_CHARS} "
        "characters and did not hit the content refusal. The floor is low because an "
        "800-character correct derivation is a legitimate answer; the content refusal is "
        "what keeps a 250-character 'I will do this in three steps' out, since that "
        "clears any length check and is then scored as a wrong answer rather than as no "
        "answer.",
        _answer_within_bounds,
    ),
    FsAdmissionClause(
        "answer_not_truncated",
        "No call in the run stopped at its token ceiling. Read from the stream-json "
        "`stop_reason` on the Claude path and from `status`/`incomplete_details` on the "
        "Responses path, because the two backends say it in different places and a "
        "reader that knows only one of them reports a truncated answer as a whole one.",
        _answer_not_truncated,
    ),
    FsAdmissionClause(
        "no_browsing",
        "`browsing_tool_calls` must be observed and zero, for **both** arms. The "
        "benchmark's published protocol is no browsing; denying the tools says what the "
        "agent was allowed to do and the transcript says what it did. A null is a "
        "refusal, not a pass.",
        _no_browsing,
    ),
    FsAdmissionClause(
        "producer_matches_arm",
        "The run's recorded model is the arm's model, and for an AutoR arm the "
        "worktree's HEAD at launch and at finish is the same clean commit that the arm's "
        "label names. Nothing else carries the revision: the metadata records no SHA and "
        "the label is the only place the plan's claim about the producer survives to.",
        _producer_matches_arm,
    ),
    FsAdmissionClause(
        "every_draw_judged",
        "Every judge draw the plan asked for was produced, and none of them failed. A "
        "failed draw recorded as a zero is indistinguishable from a genuinely worthless "
        "answer here -- `VERDICT: 0` is a real observed verdict -- and on the sibling "
        "benchmark that confusion published a run's honest 37.0 as 19.5.",
        _every_draw_judged,
    ),
)


def admit_fs_arm(evidence: FsArmEvidence) -> tuple[bool, list[str]]:
    """``(admitted, failed clause names)``. Order is the clause order, for the ledger."""
    failed = [clause.name for clause in FS_ADMISSION_CLAUSES if not clause.test(evidence)]
    return (not failed), failed


def fs_driver_clause(classification: str) -> str:
    return FS_DRIVER_CLAUSE_PREFIX + (classification or "unknown")


# ---------------------------------------------------------------------------
# The seam
# ---------------------------------------------------------------------------


def to_fs_run_record(evidence: FsArmEvidence, *, capability: str) -> RunRecord:
    """One admitted arm as a :class:`RunRecord`, so :mod:`src.trials` can do the rest.

    **This record is never written to disk, and there is no code here that could write
    it.** ``rubric_version`` has to be ``RUBRIC_VERSION`` for ``RunRecord.usable`` to be
    true, and on a benchmark row that is a claim the row cannot support. The containment
    is structural rather than documentary -- no ``Archive`` is constructed anywhere in
    this module or in ``tools/fs_trial.py``, and a test asserts it stays that way.

    Three refusals, and the first two are where this differs from the sibling. There the
    check is that the checklist's weights sum to 1.0, because the total is a weighted
    mean and the per-item decomposition is only the total's decomposition when they do.
    A FrontierScience rubric sums to 10.0 and the judge returns a scalar, so there is no
    weighting to check and no decomposition to make sum. What is checkable instead is
    that the scalar is inside the scale it claims to be on, and that the two readers of
    that one number -- the driver's mean over the per-draw points, and the scorer's own
    ``total_score`` -- agree.
    """
    admitted, failed = admit_fs_arm(evidence)
    if not admitted:
        raise ValueError(
            f"{evidence.task_key}/{evidence.arm} is not a measurement: "
            + ", ".join(failed)
            + ". A refused run belongs in the ledger, not in an average."
        )
    total = float(evidence.total_points)
    if not (0.0 <= total <= evidence.rubric_points_total + 1e-9):
        raise ValueError(
            f"{evidence.task_key}/{evidence.arm}: total {total} is outside "
            f"[0, {evidence.rubric_points_total}]. A verdict off the rubric's own scale is "
            "a parse of the judge's prose, not a score."
        )
    if abs(total - float(evidence.published_total)) > 1e-6:
        raise ValueError(
            f"{evidence.task_key}/{evidence.arm}: the mean over the recorded draws "
            f"({total:.6f}) does not reconcile with the scorer's published total "
            f"({evidence.published_total:.6f}). One number, two encodings, and this is the "
            "only place they meet."
        )

    stage_key = f"{evidence.task_key}|{evidence.env.digest[:12]}"
    return RunRecord(
        run_id=evidence.run_id,
        variant_id=f"fs/{evidence.env.judge_model}",
        rubric_version=RUBRIC_VERSION,
        edges={},
        stage_fitness={stage_key: total},
        topology="fs",
        provenance="live",
        route=evidence.workspace,
        steps=evidence.draws,
        revisits=0,
        agent_directed=0,
        bypassed=0,
        recorded_at="",
        # Empty on purpose, and safe all the way through `format_trial_report`: the judge
        # returns one number and scraping per-item scores out of its prose would be a
        # second, unvalidated instrument published beside a validated one. The report
        # says so where the criterion table would have been.
        criterion_fitness={},
        trial_id=evidence.task_key,
        capability=capability,
        arm=evidence.arm,
    )


def compare_fs_arms(control: FsArmEvidence, treatment: FsArmEvidence) -> list[str]:
    """Named reasons two admitted arms are not comparable.

    The environment digest inside the stage key already excludes them; this says which
    field did it. "The two arms measured no stage in common" is a true sentence about a
    one-character difference in ``--answer-guidance`` and it helps nobody.
    """
    reasons: list[str] = []
    if control.task_key != treatment.task_key:
        reasons.append(
            f"the arms answered different tasks (`{control.task_key}` and "
            f"`{treatment.task_key}`)"
        )
    if control.merged_from != treatment.merged_from:
        reasons.append(
            "the arms' duplicate-row folds do not cover the same tasks "
            f"(control {list(control.merged_from)}, treatment {list(treatment.merged_from)})"
        )
    reasons += control.env.describe_difference(treatment.env)
    return reasons


# ---------------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FsRefusal:
    task_key: str
    arm: str
    clauses: tuple[str, ...]

    @property
    def summary(self) -> str:
        return f"`{self.task_key}` / `{self.arm}`: " + ", ".join(self.clauses)


@dataclass(frozen=True)
class FsTrial:
    """A finished (or interrupted) paired trial and everything a reader needs to argue."""

    result: TrialResult
    control: FsArmSpec
    treatment: FsArmSpec
    #: Admitted evidence, keyed ``(task_key, arm)``, after the duplicate fold. The
    #: population *under* the number: every arm here is in a pair or in
    #: ``result.excluded``, and nothing else is.
    evidence: Mapping[tuple[str, str], FsArmEvidence]
    #: Every arm a judge produced a total for, keyed the same way and *before* the fold --
    #: admitted and refused alike. A separate field and not a filter over ``evidence``,
    #: because refusing an arm is the operation that removes it from ``evidence``, and a
    #: disclosure computed over the survivors of the thing it is disclosing states the
    #: opposite of the truth exactly when the truth is worst.
    scored: Mapping[tuple[str, str], FsArmEvidence]
    refusals: tuple[FsRefusal, ...]
    planned_pairs: int
    #: ``(folded key, the task keys folded into it)`` for the byte-identical rows.
    folded: tuple[tuple[str, tuple[str, ...]], ...] = ()
    #: Whether the fold was asked for at all, so the report can say which population it
    #: is over rather than leaving a reader to infer it from a count.
    dedupe_pairs: bool = True

    @property
    def folded_away(self) -> int:
        """Pairs the duplicate fold removed on purpose, so attrition is not confused with it.

        Without this the interim banner reads "5 of 6 planned pairs" on a trial where
        every run succeeded and one pair of byte-identical rows collapsed as designed --
        an attrition warning over a trial with no attrition, which is the sort of warning
        a reader learns to skip.
        """
        return sum(max(0, len(members) - 1) for _group, members in self.folded)

    @property
    def expected_pairs(self) -> int:
        """How many pairs a complete run of this plan would produce."""
        return max(0, self.planned_pairs - self.folded_away)

    @property
    def interim(self) -> bool:
        return self.result.n != self.expected_pairs

    def refused_clauses_by_arm(self) -> dict[tuple[str, str], tuple[str, ...]]:
        """``(task, arm) -> the clauses that refused it``, for the arms that were refused.

        Both refusal populations at once, because the caller asking is asking whether a
        given arm is in the difference, and an arm refused by the driver and an arm
        refused by a clause are equally out of it.
        """
        return {(item.task_key, item.arm): item.clauses for item in self.refusals}

    def refusals_by_clause(self) -> dict[str, int]:
        """Every admission clause at its count, then every driver refusal that happened.

        The admission clauses are listed even at zero, because a clause that stopped
        firing looks exactly like a clause never violated. The driver rows are listed
        only when they fired, because they are not a fixed set -- and because a zero
        against ``driver:stalled`` would be the wrong claim: several of the clauses below
        can only be reached by a run the driver already let through, so a watchdog kill
        arrives in this table under its driver name and never under a clause's.
        """
        counts = {clause.name: 0 for clause in FS_ADMISSION_CLAUSES}
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
        counts = {self.control.label: 0, self.treatment.label: 0}
        for refusal in self.refusals:
            counts[refusal.arm] = counts.get(refusal.arm, 0) + 1
        return counts

    def admitted_by_arm(self) -> dict[str, int]:
        """How many ``(task, arm)`` cells of each arm reached the difference.

        Counted over :attr:`scored` minus the refused, and therefore *before* the
        duplicate fold: the fold turns two admitted cells into one, and a refusal rate
        whose numerator counts cells and whose denominator counts pairs is not a rate.
        """
        refused = self.refused_clauses_by_arm()
        counts = {self.control.label: 0, self.treatment.label: 0}
        for key in self.scored:
            if key in refused:
                continue
            counts[key[1]] = counts.get(key[1], 0) + 1
        return counts

    def refusal_rate(self, arm: str) -> float | None:
        """Refused cells over cells that reached a terminal state, or ``None`` for none.

        ``None`` and not 0.0 when nothing has finished. A rate of zero over an empty
        denominator reads as "this arm refused nothing", which is the sentence a reader
        would use to decide the difference is trustworthy, published over a trial that
        has not run.
        """
        refused = self.refusals_by_arm().get(arm, 0)
        admitted = self.admitted_by_arm().get(arm, 0)
        total = refused + admitted
        return None if total == 0 else refused / total

    def refusal_rate_exceeds(self, ceiling: float) -> list[str]:
        """The arms whose refusal rate is above *ceiling*, in plan order."""
        return [
            spec.label
            for spec in (self.control, self.treatment)
            if (self.refusal_rate(spec.label) or 0.0) > ceiling
        ]


def fold_duplicate_rows(
    evidences: Sequence[FsArmEvidence], *, control_arm: str, treatment_arm: str
) -> tuple[list[FsArmEvidence], list[tuple[str, tuple[str, ...]]], list[str]]:
    """Collapse byte-identical dataset rows into one pair each.

    Rows 6 and 11 of this split are byte-identical -- same problem, same rubric -- so a
    sixty-row population holds fifty-nine distinct questions. Answering one question
    twice and entering both differences into a sign-flip test violates the independence
    the null assumes; keeping both would slightly understate the p-value, in the
    direction that publishes.

    The fold is a *mean of the two differences*, and it is taken as a mean per arm, which
    is the same number: ``mean(T_i - C_i) = mean(T) - mean(C)``. That identity only holds
    when both arms contributed the same members, so a member admitted for one arm and
    refused for the other is dropped from both and named. Averaging two control runs
    against one treatment run would be a different estimator wearing this one's label.

    Returns ``(evidences, folds, notes)``. Runs after admission, never before: a refused
    member cannot be laundered into a mean it was excluded from, because it never reaches
    here.
    """
    grouped: dict[str, dict[str, dict[str, FsArmEvidence]]] = {}
    for item in evidences:
        group = task_key(item.duplicate_of) if item.duplicate_of is not None else item.task_key
        grouped.setdefault(group, {}).setdefault(item.arm, {})[item.task_key] = item

    folded: list[FsArmEvidence] = []
    folds: list[tuple[str, tuple[str, ...]]] = []
    notes: list[str] = []
    for group, by_arm in sorted(grouped.items()):
        members = {key for arms in by_arm.values() for key in arms}
        if len(members) == 1:
            for arms in by_arm.values():
                folded.extend(arms.values())
            continue
        shared = sorted(
            set(by_arm.get(control_arm, {})) & set(by_arm.get(treatment_arm, {}))
        )
        dropped = sorted(members - set(shared))
        if dropped:
            notes.append(
                f"`{group}`: {', '.join(f'`{key}`' for key in dropped)} was admitted for "
                "only one arm, so it is out of the fold for both -- averaging a two-run "
                "arm against a one-run arm is a different estimator"
            )
        if not shared:
            continue
        for arm, arms in sorted(by_arm.items()):
            chosen = [arms[key] for key in shared if key in arms]
            if len(chosen) != len(shared):
                continue
            merged = _merge_members(chosen, group=group)
            if merged is None:
                notes.append(
                    f"`{group}` / `{arm}`: the runs of the duplicate rows were measured in "
                    "different environments, so their mean is not a mean of one thing"
                )
                continue
            folded.append(merged)
        folds.append((group, tuple(shared)))
    return folded, folds, notes


def _merge_members(members: Sequence[FsArmEvidence], *, group: str) -> FsArmEvidence | None:
    """One evidence standing for several byte-identical rows, or ``None`` if they differ.

    ``None`` when the members were not measured in the same environment: the merged
    object carries one :class:`FsRunEnvironment`, and picking one of two would publish a
    mean over two instruments under the name of one.
    """
    if len({item.env.digest for item in members}) != 1:
        return None
    count = len(members)
    return replace(
        members[0],
        task_key=group,
        total_points=sum(item.total_points for item in members) / count,
        published_total=sum(item.published_total for item in members) / count,
        draw_points=tuple(point for item in members for point in item.draw_points),
        draws_requested=sum(item.draws_requested for item in members),
        judge_failures=tuple(
            failure for item in members for failure in item.judge_failures
        ),
        merged_from=tuple(item.task_key for item in members),
    )


def collect_fs_pairs(
    evidences: Iterable[FsArmEvidence],
    *,
    capability: str,
    control: FsArmSpec,
    treatment: FsArmSpec,
    planned_pairs: int,
    dedupe_pairs: bool = True,
    driver_refusals: Sequence[FsRefusal] = (),
) -> FsTrial:
    """Admit, fold, pair, and replace every generic exclusion reason with a named one.

    The gate and the explanation are separate on purpose. ``collect_pairs`` does the
    excluding, off the environment digest baked into the stage key; this only renames
    what it excluded. The assertion at the end is what keeps the two honest: if a field
    is dropped from :class:`FsRunEnvironment` while its diff line survives, a confounded
    pair reaches ``pairs`` with a named reason for excluding it, and that raises here
    rather than being published.

    ``driver_refusals`` is the other half of the ledger. A run killed by the watchdog, by
    a crash, by a fallback answer or by the scorer's own refusal never becomes an
    :class:`FsArmEvidence` at all, so the gate cannot refuse it -- and it used to render
    as "no `<arm>` arm", the same sentence as an arm that was never launched. Three
    treatment deaths against zero control deaths is a trial's result whenever it happens,
    and it cannot be the one thing the ledger structurally cannot see.

    ``outcome=FS_TOTAL`` is fixed here and is not a parameter. A trial that could name
    its own measure could name one nothing selects on and exempt itself from the
    circularity refusal, so the declaration lives in the producer that knows what filled
    the dicts.
    """
    admitted: dict[tuple[str, str], FsArmEvidence] = {}
    scored: dict[tuple[str, str], FsArmEvidence] = {}
    refusals: list[FsRefusal] = []
    for evidence in evidences:
        scored[(evidence.task_key, evidence.arm)] = evidence
        ok, failed = admit_fs_arm(evidence)
        if ok:
            admitted[(evidence.task_key, evidence.arm)] = evidence
        else:
            refusals.append(FsRefusal(evidence.task_key, evidence.arm, tuple(failed)))

    folds: list[tuple[str, tuple[str, ...]]] = []
    fold_notes: list[str] = []
    if dedupe_pairs:
        merged, folds, fold_notes = fold_duplicate_rows(
            sorted(admitted.values(), key=lambda item: (item.task_key, item.arm)),
            control_arm=control.label,
            treatment_arm=treatment.label,
        )
        admitted = {(item.task_key, item.arm): item for item in merged}

    # One (task, arm) is one lost pair and is counted once. A driver refusal for an arm a
    # later attempt got admitted for cost an attempt, not a pair; a driver refusal for an
    # arm the gate already refused would double the per-arm count the reader is told to
    # judge the whole trial on.
    seen = set(scored) | {(item.task_key, item.arm) for item in refusals}
    for refusal in driver_refusals:
        if (refusal.task_key, refusal.arm) in seen:
            continue
        seen.add((refusal.task_key, refusal.arm))
        refusals.append(refusal)

    records = [to_fs_run_record(item, capability=capability) for item in admitted.values()]
    result = collect_pairs(
        records,
        capability=capability,
        control_arm=control.label,
        treatment_arm=treatment.label,
        outcome=FS_TOTAL,
    )

    # Two dictionaries, not one, because only one of them is a confound and the leak
    # check below is about confounds alone.
    #
    # ``confounds`` holds what :func:`compare_fs_arms` found between two arms that *both*
    # reached the pair. One of those surviving into ``result.pairs`` means the digest
    # baked into the stage key and the cross-arm diff disagree, and something the diff can
    # name is inside the published difference. That is the assertion's whole subject.
    #
    # ``refusal_reasons`` is prose about arms that never reached a pair at all, keyed on
    # the raw task key the refusal carries. Merging the two used to raise on the ordinary
    # trial: the duplicate fold renames the surviving evidence to the *group* key, and the
    # group key is one of the members' own task keys, so refusing one arm of row 6 while
    # rows 6 and 11 fold into `fs:006` put a refusal reason and a live pair on one key.
    # The trial then ended with an AssertionError and no report -- and the message blamed
    # the environment digest, which had not moved.
    confounds: dict[str, list[str]] = {}
    refusal_reasons: dict[str, list[str]] = {}
    for refusal in refusals:
        side = "control" if refusal.arm == control.label else "treatment"
        refusal_reasons.setdefault(refusal.task_key, []).append(
            f"the {side} arm `{refusal.arm}` was refused ({', '.join(refusal.clauses)})"
        )
    tasks = {task for task, _ in admitted} | {item.task_key for item in refusals}
    for task in tasks:
        left = admitted.get((task, control.label))
        right = admitted.get((task, treatment.label))
        if left is not None and right is not None:
            reasons = compare_fs_arms(left, right)
            if reasons:
                confounds[task] = reasons

    kept = {pair.trial_id for pair in result.pairs}
    leaked = sorted(task for task, reasons in confounds.items() if reasons and task in kept)
    if leaked:
        raise AssertionError(
            "a confounded pair survived pairing: "
            + "; ".join(f"`{task}` ({'; '.join(confounds[task])})" for task in leaked)
            + ". The environment digest in the stage key and the cross-arm diff have gone "
            "out of step -- the diff can name a difference the digest did not exclude -- "
            "so a confound can now reach the published difference."
        )

    excluded = dict(result.excluded)
    for task in sorted(set(confounds) | set(refusal_reasons)):
        if task in kept:
            # A refused arm whose task key is also the name of a surviving fold group.
            # The refusal is real and is printed in the ledger under its own key; writing
            # it here as well would tell a reader that one task both produced a pair and
            # was excluded from the mean. (`confounds` never reaches this branch: a task
            # in both `confounds` and `kept` raised above.)
            continue
        excluded[task] = "; ".join(refusal_reasons.get(task, []) + confounds.get(task, []))
    for task in tasks:
        if task not in kept and task not in excluded:
            excluded[task] = "no run of either arm was admitted"
    for note in fold_notes:
        excluded[note.split("`")[1]] = note

    return FsTrial(
        result=replace(result, excluded=tuple(sorted(excluded.items()))),
        control=control,
        treatment=treatment,
        evidence=admitted,
        scored=scored,
        refusals=tuple(refusals),
        planned_pairs=planned_pairs,
        folded=tuple(folds),
        dedupe_pairs=dedupe_pairs,
    )


# ---------------------------------------------------------------------------
# Reading the two arms side by side
# ---------------------------------------------------------------------------


def wilson_interval(
    successes: int, trials: int, *, z: float = FS_WILSON_Z
) -> tuple[float, float]:
    """Two-sided Wilson score interval for a proportion, clamped to [0, 1].

    Wilson rather than Wald because the counts this trial expects are the ones Wald gets
    wrong: a measured direct-opus arm passed 3 of 21, and a subject slice at 0 of 20 gets
    the interval [0, 0] out of Wald -- certainty manufactured from an absence. Returns
    ``(0.0, 1.0)`` at zero trials, which is the only honest interval over no data.
    """
    if trials <= 0:
        return (0.0, 1.0)
    proportion = successes / trials
    denominator = 1.0 + z * z / trials
    centre = (proportion + z * z / (2 * trials)) / denominator
    spread = (
        z
        * math.sqrt(proportion * (1 - proportion) / trials + z * z / (4 * trials * trials))
        / denominator
    )
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def paired_difference_sd(differences: Sequence[float]) -> float | None:
    """Sample standard deviation of the within-pair differences, or ``None`` below two.

    ``None`` and never 0.0. One pair has no dispersion to measure, and a zero would be
    read as "the arms differ by the same amount every time", which is the strongest
    claim the data could make and here it would be made by having no data.
    """
    values = [float(value) for value in differences]
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def minimum_detectable_effect(sd: float | None, pairs: int) -> float | None:
    """The smallest true difference this many pairs could have found, at 80% power.

    ``(z_{0.975} + z_{0.80}) * sd / sqrt(n)``. A normal approximation to a permutation
    test, and the report says so: :func:`src.trials.sign_flip_p` assumes nothing about
    the distribution, so this is a guide to what the sample can resolve rather than the
    test's own operating characteristic. ``None`` when the sd is unmeasured, because an
    MDE computed from an assumed sd is a claim about the apparatus dressed as a claim
    about the data.
    """
    if sd is None or pairs <= 0:
        return None
    return FS_MDE_MULTIPLIER * sd / math.sqrt(pairs)


def subject_rollup(trial: FsTrial) -> dict[str, dict[str, float]]:
    """Per-subject mean difference and pair count, and deliberately nothing else.

    No pass rate. Twenty tasks at the observed pass proportion carry a binomial standard
    deviation of about nine percentage points, so a per-subject pass rate is a number
    whose noise is larger than any effect this trial is looking for -- and printed in a
    table beside a mean it would be read as the same kind of measurement.
    """
    buckets: dict[str, list[float]] = {}
    for pair in trial.result.comparable_pairs:
        evidence = trial.evidence.get((pair.trial_id, trial.control.label))
        subject = evidence.subject if evidence is not None else ""
        buckets.setdefault(subject or "<unrecorded>", []).append(pair.difference)
    return {
        subject: {"n": len(values), "mean": sum(values) / len(values)}
        for subject, values in sorted(buckets.items())
    }


def arm_cost(trial: FsTrial, arm: str) -> dict[str, float]:
    """Backend calls, output tokens and median wall clock for one arm's admitted runs.

    Printed beside the score and never folded into it. The pipeline arm spends several
    times the tokens of one direct call by construction, and a win that came with an
    eight-fold token bill has to be named as one rather than reported as a free
    improvement. Median wall clock rather than mean: the sibling benchmark's real
    distribution runs from 11.9 to 26.5 hours and one stalled run moves a mean.
    """
    calls: list[float] = []
    tokens: list[float] = []
    seconds: list[float] = []
    for (_task, label), evidence in sorted(trial.evidence.items()):
        if label != arm:
            continue
        for name, sink in (
            ("backend_calls", calls),
            ("output_tokens_total", tokens),
            ("duration_seconds", seconds),
        ):
            value = _fact(evidence, name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                sink.append(float(value))
    ordered = sorted(seconds)
    median = 0.0
    if ordered:
        middle = len(ordered) // 2
        median = (
            ordered[middle]
            if len(ordered) % 2
            else (ordered[middle - 1] + ordered[middle]) / 2
        )
    return {
        "runs": float(len([1 for key in trial.evidence if key[1] == arm])),
        "backend_calls": sum(calls),
        "output_tokens": sum(tokens),
        "median_seconds": median,
    }


def arm_totals(trial: FsTrial, arm: str) -> list[float]:
    """Every admitted total for one arm, over the pairs that reached the difference.

    Over the paired population and not over everything admitted, so that the two arms'
    headline means are means over the same tasks. An arm whose extra admitted runs had
    no partner would otherwise be compared on a different set of questions, which is the
    goal-difficulty confound the whole paired design exists to remove.
    """
    keys = [pair.trial_id for pair in trial.result.comparable_pairs]
    return [
        trial.evidence[(task, arm)].total_points
        for task in keys
        if (task, arm) in trial.evidence
    ]


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


#: Printed on every report, above every number, and never behind a condition. The
#: paper's judge is GPT-5 at high reasoning effort and that deployment returns 404 on
#: this endpoint, so nothing here was produced with the instrument the published table
#: was produced with. Judge choice moved a ResearchClawBench total by about sixteen
#: points on identical artifacts, which is larger than anything either benchmark's
#: capability trials are looking for.
FS_NON_COMPARABILITY_BANNER = (
    "> **These numbers are not comparable to the paper's table.** The paper grades with "
    "GPT-5 at high reasoning effort; that deployment returns 404 on this endpoint. Every "
    "number below was produced by **gpt-5.1** at high effort against the paper's verbatim "
    "Appendix B prompt. Judge choice has been measured to move a total on identical "
    "artifacts by about sixteen points on the sibling benchmark, so a figure from here "
    "must never be placed beside the paper's 25.2 / 19.4 / 17.5 without this sentence."
)

#: The hole the apparatus cannot close, printed under the total rather than in a caveats
#: section nobody reaches.
FS_ONE_OBSERVATION = (
    "Each (task, arm) ran **once**. The dispersion above is the judge's, over replicate "
    "gradings of the same two answers; there are zero observations of the answer "
    "producer's own run-to-run variance, which is very likely larger. Read a difference "
    "that exceeds the judge's band as *the judge cannot explain it*, never as *the "
    "treatment explains it*."
)

#: Printed wherever an n below the planned n carries a p.
FS_REFUSAL_BIAS = (
    "Every refusal above removes a **pair**, and refusals are not random with respect to "
    "arm. A pipeline arm can be refused for a stage timeout, an auto-skipped stage or a "
    "synthesized answer; a single-call arm structurally cannot be refused for any of the "
    "three. A surviving sample weighted toward the pipeline runs that finished cleanly is "
    "a sample of the tasks it found easy, and it biases the difference upward. If the "
    "per-arm refusal counts above are lopsided, the difference below is not this trial's "
    "result."
)


def format_fs_trial_report(
    trial: FsTrial,
    *,
    plan: "FsTrialPlan",
    judge_model: str = "",
) -> str:
    """The whole rendering: provenance, banner, ledger, difference, published numbers.

    Order is an argument. The non-comparability banner is second because a reader who
    stops after the headline has to have met it; the refusal ledger sits above the total
    because a trial that refused a fifth of one arm and none of the other has produced a
    result and it is not the number underneath; and the publication gate sits *between*
    them, so a difference that must not be published is not printed and then withdrawn.

    ``judge_model`` is observed off the score files by the caller and is printed against
    the plan's declaration, in that order. A dropped ``--model`` scores the whole trial
    with a judge nobody chose while the header states the declaration and reads correct.
    """
    result = trial.result
    lines: list[str] = [
        "# FrontierScience-Research paired trial",
        "",
        f"- capability: `{result.capability}`",
        f"- control arm: {trial.control.describe()}",
        f"- treatment arm: {trial.treatment.describe()}",
        f"- dataset: `{plan.dataset}` sha256 `{plan.dataset_sha256[:16]}`",
        f"- task instruction sha256: `{plan.task_instruction_sha256[:16]}` (both arms, "
        "verbatim, frozen in the plan digest)",
        f"- judge: `{judge_model or '<unrecorded>'}` at "
        f"`{plan.judge_reasoning_effort}` effort, "
        f"{plan.judge_replicates} draw(s) per answer",
        f"- plan digest: `{plan.digest[:16]}` (frozen before the first launch)",
        f"- sign-flip test: exact enumeration at or below 18 pairs, otherwise "
        f"{SAMPLED_SIGN_ASSIGNMENTS:,} sampled sign assignments with seed "
        f"`{SIGN_FLIP_SEED}`",
    ]
    if judge_model and judge_model != plan.judge_model:
        lines.append(
            f"- **the judge that ran is not the judge the plan declared** "
            f"(`{plan.judge_model}`). Judge choice is worth more than anything this trial "
            "is looking for, so nothing below is this trial's result."
        )
    # Observed, then declared, for the dataset too. The plan's digest is what a reader
    # checks their own copy against; the runs record what they actually opened, and the
    # scorer pins only its own constant. Two files answering to one name is the one
    # confound the environment digest cannot describe, because both arms would carry it.
    seen = sorted({item.env.dataset_sha256 for item in trial.scored.values() if item.env.dataset_sha256})
    if seen and seen != [plan.dataset_sha256]:
        lines.append(
            "- **the runs did not all answer the dataset the plan names.** Declared "
            f"`{plan.dataset_sha256[:16]}`, observed "
            + ", ".join(f"`{digest[:16]}`" for digest in seen)
            + ". Nothing below is a measurement of the split the plan describes."
        )
    lines += ["", FS_NON_COMPARABILITY_BANNER]

    if trial.interim:
        lines += [
            "",
            f"> **INTERIM -- {result.n} of {trial.expected_pairs} pairs "
            f"({trial.planned_pairs} planned task(s), {trial.folded_away} folded away as "
            "duplicate rows).** The "
            "p-value below is not this trial's result. A resumable apparatus whose report "
            "runs at any moment is a machine for stopping when the sign looks good; the "
            "planned n was frozen before the first launch so that stopping early is "
            "visible here rather than invisible everywhere.",
        ]

    lines += _refusal_ledger(trial, plan)

    blocked = trial.refusal_rate_exceeds(plan.max_refusal_rate_for_publication)
    if blocked:
        lines += [
            "",
            "## The difference is not published",
            "",
            f"- **{' and '.join(f'`{label}`' for label in blocked)} refused more than "
            f"{plan.max_refusal_rate_for_publication:.0%} of the runs that finished.** "
            "The paired difference, the per-arm means and the pass rates are withheld, "
            "and the refusal rates above are the only result of this trial.",
            "",
            FS_REFUSAL_BIAS,
            "",
            "Withheld rather than printed with a warning on purpose. A reader who sees a "
            "signed number takes it, and a caveat underneath does not undo that -- the "
            "surviving sample here is the subset of tasks on which one arm happened to "
            "run cleanly, and the difference over it is biased in a known direction by an "
            "unknown amount.",
        ]
        lines += _what_this_measures(trial, plan)
        return "\n".join(lines)

    lines += [
        "",
        "## The difference",
        "",
        format_trial_report(result),
    ]
    lines += _population_lines(trial)
    lines += _published_numbers(trial, plan, judge_model=judge_model)
    lines += _refused_to_print(trial, plan)
    lines += _what_this_measures(trial, plan)
    return "\n".join(lines)


def _refusal_ledger(trial: FsTrial, plan: "FsTrialPlan") -> list[str]:
    """Every refusal, both arms' rates side by side, and every clause at its count."""
    lines = ["", "## Runs refused, before any number", ""]
    by_arm = trial.refusals_by_arm()
    admitted = trial.admitted_by_arm()
    # Printed even when both counts are zero. The paragraph below tells the reader to
    # judge the difference on this line, and a line that appears only once something has
    # already gone wrong is not there on the reading where they need it.
    for role, spec in (("control", trial.control), ("treatment", trial.treatment)):
        rate = trial.refusal_rate(spec.label)
        shown = (
            "unmeasured (no run of this arm has reached a verdict)"
            if rate is None
            else f"{rate:.0%}"
        )
        lines.append(
            f"- {role} `{spec.label}`: **{by_arm.get(spec.label, 0)} refused**, "
            f"{admitted.get(spec.label, 0)} admitted, refusal rate {shown}"
        )
    lines.append(
        f"- publication ceiling: {plan.max_refusal_rate_for_publication:.0%} in either "
        "arm. Above it the paired difference is not published at all, because refusals "
        "are not random with respect to arm."
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
        "metadata field it reads was renamed, or cannot fire at all on this path -- a run "
        "killed by the watchdog is refused by the driver and arrives above as a "
        f"`{FS_DRIVER_CLAUSE_PREFIX}` row, never as `meta_status_completed`. All three "
        "look the same from here, which is why the count is printed rather than the "
        "failures alone.",
    ]
    if trial.refusals or trial.interim:
        lines += ["", FS_REFUSAL_BIAS]
    return lines


def _population_lines(trial: FsTrial) -> list[str]:
    """Which questions the difference is over, and how that differs from the paper's."""
    if not trial.dedupe_pairs:
        return [
            "",
            "- **Duplicate rows were not folded.** This plan set `dedupe_pairs: false`, so "
            "any byte-identical rows in the split contribute two pairs whose differences "
            "are two draws on one question. The sign-flip null assumes the pair "
            "differences are independent, and two answers to the same question are not.",
        ]
    if not trial.folded:
        return [
            "",
            "- Duplicate folding was on and folded nothing: no two admitted tasks in this "
            "population share a problem and a rubric.",
        ]
    described = "; ".join(
        f"`{group}` <- {', '.join(f'`{key}`' for key in members)}"
        for group, members in trial.folded
    )
    return [
        "",
        f"- **{len(trial.folded)} duplicate row group(s) folded**: {described}. The "
        "difference for a folded group is the mean of its members' differences, which is "
        "the same number as the difference of the two arms' means over them.",
        "- The published split holds sixty rows and fifty-nine distinct questions: rows 6 "
        "and 11 are byte-identical. **This analysis is over the distinct questions, not "
        "over the paper's sixty-row population**, because two answers to one question are "
        "not two independent observations under the sign-flip null.",
    ]


def _published_numbers(
    trial: FsTrial, plan: "FsTrialPlan", *, judge_model: str
) -> list[str]:
    """The headline, and every number that qualifies it, each carrying its judge."""
    result = trial.result
    judge = judge_model or plan.judge_model
    control_totals = arm_totals(trial, trial.control.label)
    treatment_totals = arm_totals(trial, trial.treatment.label)
    lines = ["", "## The published numbers", ""]
    if not result.comparable_pairs:
        lines.append(
            "- **No pair reached the difference**, so there is no mean to publish. The "
            "refusal ledger above is this trial's whole result so far."
        )
        return lines

    lines += [
        f"- mean rubric points, control `{trial.control.label}`: "
        f"**{sum(control_totals) / len(control_totals):.3f}** / "
        f"{FS_DATASET_POINTS_PER_ROW:g} (judge `{judge}`)",
        f"- mean rubric points, treatment `{trial.treatment.label}`: "
        f"**{sum(treatment_totals) / len(treatment_totals):.3f}** / "
        f"{FS_DATASET_POINTS_PER_ROW:g} (judge `{judge}`)",
        f"- paired mean difference: **{result.mean_difference:+.3f}** "
        f"{result.outcome.unit} over {result.n} pair(s) (judge `{judge}`)",
    ]

    sd = paired_difference_sd(result.differences)
    mde = minimum_detectable_effect(sd, result.n)
    if sd is None:
        lines.append(
            "- observed sd of the paired differences: **unmeasured (fewer than two "
            "pairs)**. Not zero: one pair has no dispersion, and a zero here would be the "
            "strongest claim the data could make, made by having no data."
        )
    else:
        lines.append(
            f"- observed sd of the paired differences: **{sd:.3f}** rubric points; the "
            f"minimum effect {result.n} pairs could detect at 80% power is "
            f"**{mde:+.3f}**, against a declared minimum effect of interest of "
            f"**{plan.minimum_effect_of_interest:+.3f}**. That is a normal approximation "
            "to a permutation test, so read it as what this sample can resolve rather "
            "than as the sign-flip test's own operating characteristic."
        )
        if mde is not None and mde > plan.minimum_effect_of_interest:
            lines.append(
                "- **This trial could not have detected the effect it was designed "
                f"around.** The smallest difference it can resolve ({mde:.3f}) is larger "
                f"than the one declared worth detecting "
                f"({plan.minimum_effect_of_interest:.3f}), so a null here is a fact about "
                "the sample size."
            )

    for role, spec, totals in (
        ("control", trial.control, control_totals),
        ("treatment", trial.treatment, treatment_totals),
    ):
        passes = sum(1 for value in totals if value >= plan.pass_threshold)
        low, high = wilson_interval(passes, len(totals))
        lines.append(
            f"- pass@>={plan.pass_threshold:g}, {role} `{spec.label}`: **{passes}/"
            f"{len(totals)}** = {passes / len(totals):.1%}, Wilson 95% CI "
            f"[{low:.1%}, {high:.1%}] (judge `{judge}`)"
        )
    lines.append(
        "- pass@>=7 is the paper's own metric and is printed here as a second reading "
        "rather than as the headline. It is not structurally zero -- a direct "
        "`claude-opus-4-5` arm cleared it on 3 of 21 tasks under this judge -- but it "
        "discards the distance between a 2.0 and a 6.9, which is where this benchmark's "
        "signal is. The mean rubric points above is the metric the paper names as a "
        "legitimate alternative, and it is the one to read."
    )

    lines += ["", "| Subject | Pairs | Mean difference |", "| --- | --- | --- |"]
    for subject, values in subject_rollup(trial).items():
        lines.append(f"| {subject} | {int(values['n'])} | {values['mean']:+.3f} |")
    lines.append("")
    lines.append(
        "No per-subject pass rate. At twenty tasks a subject's pass proportion carries a "
        "binomial standard deviation of about nine percentage points, which is larger "
        "than any difference this trial is powered for, and a rate printed in that table "
        "would be read as the same kind of measurement as the mean beside it."
    )

    lines += ["", "| Cost | Control | Treatment |", "| --- | --- | --- |"]
    left = arm_cost(trial, trial.control.label)
    right = arm_cost(trial, trial.treatment.label)
    for label, key, form in (
        ("admitted runs", "runs", "{:.0f}"),
        ("backend calls", "backend_calls", "{:.0f}"),
        ("output tokens", "output_tokens", "{:.0f}"),
        ("median wall clock (s)", "median_seconds", "{:.0f}"),
    ):
        lines.append(f"| {label} | {form.format(left[key])} | {form.format(right[key])} |")
    lines.append("")
    lines.append(
        "The cost columns are beside the score and never inside it. A pipeline arm spends "
        "several times a single call's tokens by construction, and a win that arrived "
        "with an eight-fold bill has to be named as one. **AutoR's wall clock and score "
        "on this benchmark are otherwise UNMEASURED** -- no real (non-fake-operator) "
        "AutoR run of FrontierScience exists -- so any number in the treatment column of "
        "a dry run is a property of the fake operator."
    )
    lines.append("")

    spreads = [
        item.spread
        for item in trial.evidence.values()
        if item.spread is not None
    ]
    if plan.judge_replicates <= 1 or not spreads:
        lines.append(
            f"- judge sampling noise: **unmeasured ({plan.judge_replicates} draw"
            f"{'' if plan.judge_replicates == 1 else 's'})**, never 0.00. "
            f"{FS_JUDGE_NOISE_NOTE}."
        )
    else:
        lines.append(
            f"- judge sampling noise on these answers: largest observed spread "
            f"**{max(spreads):.3f}** points over {plan.judge_replicates} draws. "
            f"{FS_JUDGE_NOISE_NOTE}."
        )
    observed_attempts = sorted({item.env.answer_attempts for item in trial.evidence.values()})
    if observed_attempts == [1] or not observed_attempts:
        lines.append(
            "- between-attempt variance: **unmeasured (1 attempt per (task, arm))**, "
            "never 0.00. Every published total is one answer graded, so the answer "
            "producer's own run-to-run spread is not in any interval on this page."
        )
    else:
        lines.append(
            f"- between-attempt variance: pooled over {observed_attempts} attempts per "
            "(task, arm)."
        )
    if plan.answer_attempts not in observed_attempts and observed_attempts:
        lines.append(
            f"- **the plan declared {plan.answer_attempts} answer attempt(s) and the runs "
            f"recorded {observed_attempts}.** The declaration and the observation are two "
            "encodings of one count and they disagree."
        )
    lines += ["", FS_ONE_OBSERVATION]
    return lines


def _refused_to_print(trial: FsTrial, plan: "FsTrialPlan") -> list[str]:
    """What this report will not print, and why each absence is a decision."""
    return [
        "",
        "## What this report refuses to print",
        "",
        "- **No per-rubric-item table and no concentration figure.** This judge returns "
        "one number. Its per-item reasoning exists only as prose, in a format measured to "
        "be unstable across responses -- one numbered its sections `Item N`, another wrote "
        "`Rubric section:` and drilled into sub-items -- so a decomposition scraped out of "
        "it would be a second, unvalidated instrument published beside a validated one. "
        "`criterion_fitness` is therefore empty by construction, which is why the "
        "criterion table and the Goodhart concentration are absent above rather than "
        "blank.",
        "- **No per-subject pass rate**, for the binomial reason given beside the subject "
        "table.",
        "- **No spread of 0.00 from a single draw.** A dispersion that shrinks as the "
        "evidence shrinks is not a dispersion.",
        "- **No score taken while the trial was in flight.** Every total above comes from "
        "one continuous final pass with one judge, so a judge that drifted across the "
        "trial cannot ride into the difference unmeasured.",
        f"- **No pair whose two arms `compare_fs_arms` can tell apart.** `collect_fs_pairs` "
        f"raises rather than publishing one, so the {len(trial.result.excluded)} excluded "
        "task(s) above are excluded from the mean and not merely annotated under it. The "
        "raise is over cross-arm confounds only, and deliberately so: after the duplicate "
        "fold a surviving pair carries the *group's* key, which is also one member's own "
        "key, so a refusal of that member is not a confound reaching the difference and "
        "must not be read as one. Those refusals are in the ledger above under their own "
        "keys.",
    ]


def _what_this_measures(trial: FsTrial, plan: "FsTrialPlan") -> list[str]:
    return [
        "",
        "## What this is a measurement of",
        "",
        f"The upper bound on the claim: this measures, under a `{plan.judge_model}` judge, "
        f"the difference between the treatment arm `{trial.treatment.label}` and the "
        f"control arm `{trial.control.label}` -- both described in full at the top of this "
        f"page -- over {trial.expected_pairs} distinct question(s) drawn from one split of "
        f"one benchmark, with browsing denied to both arms and with the answer graded "
        f"afterwards against a rubric no stage was shown. "
        f"{trial.result.n} of those question(s) produced a pair.",
        "",
        "It is not a measurement of AutoR's capability, which is a pipeline of eight "
        "stages of which this configuration runs one. It is not a state of the art figure "
        "for FrontierScience-Research. And it is not comparable to the paper's table, for "
        "the reason printed at the top of this page.",
    ]


# ---------------------------------------------------------------------------
# The plan, and the planner
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FsTrialPlan:
    """Frozen before the first launch, and hashed into every state file.

    One ``--plan PATH`` in place of thirty flags, because a trial that runs for days
    needs its parameters in a file somebody can read afterwards rather than in a shell
    history -- and because a plan is the only artifact that can be digested, and a digest
    is what makes "the apparatus did not change while it ran" checkable.
    """

    capability: str
    dataset: str
    dataset_sha256: str
    tasks: tuple[str, ...]
    control: FsArmSpec
    treatment: FsArmSpec
    #: Why this trial costs what it costs, in the operator's own words, and what of that
    #: has actually been measured. Required and non-empty: see
    #: :func:`_refuse_a_budget_nobody_measured`.
    cost_note: str
    task_instruction_sha256: str = FS_TASK_INSTRUCTION_SHA256
    disallowed_tools: tuple[str, ...] = ("WebSearch", "WebFetch")
    judge_kind: str = "responses"
    judge_model: str = "gpt-5.1"
    judge_endpoint: str = ""
    judge_reasoning_effort: str = "high"
    judge_max_output_tokens: int = 32000
    judge_timeout_seconds: float = 600.0
    #: Where the raw judge responses go, or ``""`` for nowhere. It has to be outside this
    #: repository when it is set at all: the judge quotes rubric items verbatim while it
    #: reasons, and the dataset card asks that this text not enter a crawlable corpus.
    judge_raw_dir: str = ""
    #: One, and :func:`_refuse_a_plan_that_cannot_produce_a_pair` refuses anything else.
    #: The field is kept rather than deleted because it is what a pooled-attempt design
    #: would set, it is in the environment digest so that a half-applied pooling separates
    #: the arms, and the report prints the declaration against the observation as a second
    #: witness. A knob that can only be set wrong is worse than no knob, so the freeze is
    #: what turns this one from a lie into a placeholder.
    answer_attempts: int = 1
    judge_replicates: int = 1
    pass_threshold: float = FS_PASS_THRESHOLD
    minimum_effect_of_interest: float = FS_MINIMUM_EFFECT
    max_refusal_rate_for_publication: float = FS_MAX_REFUSAL_RATE
    dedupe_pairs: bool = True
    stage_timeout_seconds: int = 3600
    max_attempts: int = FS_MAX_ATTEMPTS
    state_dir: str = ""
    #: ``counterbalanced`` here, where ``src.rcb_trial`` defaults to ``control_first``.
    #: That trial completes one or two pairs, and with one pair an alternating order
    #: turns a position effect into something that cannot be named afterwards. At sixty
    #: pairs a position effect is estimable and alternating is the correct default.
    arm_order_mode: str = "counterbalanced"
    #: How many answer runs may be in flight at once. The judge is separate and serial.
    concurrency: int = 6
    #: Judge calls in flight. One, and the reason is measured: 34 of 34 serial calls
    #: succeeded here with zero retries, and the sibling benchmark's concurrent judge
    #: calls caused most of its failures. There is no local evidence on the other side.
    judge_concurrency: int = 1
    #: Unix time after which no *new* run starts. A running one is left alone.
    deadline: float = 0.0
    stall_seconds: int = FS_STALL_SECONDS
    operator: str = "claude"
    #: Dry-run only: how much better the fake operator makes the treatment arm's answer.
    #: Zero would give two identical columns, which a broken seam would pass.
    fake_quality: float = 0.0
    #: Dry-run only: faults the fake operator injects into the *treatment* arm, so that
    #: the clauses which refuse a run are reachable end to end and not only from a unit
    #: test holding a hand-written fact dictionary. A clause exercised only against a
    #: dictionary somebody wrote to make it fire is a clause tested against its own
    #: statement rather than against a workspace.
    fake_faults: tuple[str, ...] = ()

    @property
    def planned_pairs(self) -> int:
        return len(self.tasks)

    def to_dict(self) -> dict[str, Any]:
        payload = dataclasses.asdict(self)
        payload["tasks"] = list(self.tasks)
        payload["disallowed_tools"] = list(self.disallowed_tools)
        return payload

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())

    def arm_for(self, label: str) -> FsArmSpec:
        if label == self.control.label:
            return self.control
        if label == self.treatment.label:
            return self.treatment
        raise KeyError(f"no arm labelled {label!r} in this plan")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FsTrialPlan":
        known = {spec.name for spec in dataclasses.fields(cls)}
        unknown = sorted(set(payload) - known - {"digest"})
        if unknown:
            raise ValueError(
                f"unknown plan fields: {', '.join(unknown)}. A misspelled field that is "
                "silently ignored is a parameter set wrong for the length of the trial."
            )
        values = {key: payload[key] for key in known if key in payload}
        values["tasks"] = tuple(str(item) for item in values.get("tasks", ()))
        values["disallowed_tools"] = tuple(
            str(item) for item in values.get("disallowed_tools", ("WebSearch", "WebFetch"))
        )
        values["fake_faults"] = tuple(str(item) for item in values.get("fake_faults", ()))
        for side in ("control", "treatment"):
            if side in values and not isinstance(values[side], FsArmSpec):
                values[side] = FsArmSpec.from_dict(values[side])
        plan = cls(**values)
        _refuse_a_plan_that_cannot_produce_a_pair(plan)
        for side in ("control", "treatment"):
            _refuse_a_label_that_is_not_the_producer(side, getattr(plan, side))
        _refuse_a_budget_nobody_measured(plan)
        return plan


def _refuse_a_plan_that_cannot_produce_a_pair(plan: FsTrialPlan) -> None:
    """Every freeze-time refusal that is not about one arm on its own.

    All of these are the same defect in different costumes, and the costume is what makes
    it expensive: each one is accepted at freeze, launched, spent, and then discovered by
    a gate at report time. Two arms whose answer models differ produce two different
    environment digests, so ``collect_pairs`` excludes every pair with the reason "the two
    arms measured no stage in common" -- true, useless, and arrived at after the trial has
    been paid for. The same is true of the guidance. Refusing here costs a string
    comparison.
    """
    if plan.control.label == plan.treatment.label:
        raise ValueError("the two arms carry the same label; the difference would be zero")
    if not plan.tasks:
        raise ValueError("a plan with no tasks cannot become a measurement")
    if len(set(plan.tasks)) != len(plan.tasks):
        raise ValueError(
            "the task list repeats a key. Two runs of one question are two draws on one "
            "question, and the sign-flip null assumes the pair differences are independent."
        )
    bad = [task for task in plan.tasks if not FS_TASK_KEY_PATTERN.match(task)]
    if bad:
        raise ValueError(
            f"these are not task keys: {', '.join(bad)}. The driver never opens the "
            f"dataset -- the agent and the scorer each do -- so a key nothing can resolve "
            f"would be discovered after the workspace exists. Use {FS_TASK_KEY_PREFIX}NNN."
        )
    if plan.task_instruction_sha256 != FS_TASK_INSTRUCTION_SHA256:
        raise ValueError(
            f"the plan pins the task instruction at {plan.task_instruction_sha256!r} and "
            f"this tree renders {FS_TASK_INSTRUCTION_SHA256!r}. The prompt is the "
            "instrument: a plan frozen against one wording and run against another is two "
            "arms answering two questions."
        )
    if plan.control.model != plan.treatment.model:
        raise ValueError(
            f"the arms name different answer models (`{plan.control.model}` and "
            f"`{plan.treatment.model}`). `answer_model` is in the environment digest, so "
            "every pair would be excluded with 'the two arms measured no stage in common'. "
            "A cross-model comparison is a different trial and needs that field taken out "
            "of the digest deliberately."
        )
    if plan.control.answer_guidance != plan.treatment.answer_guidance:
        raise ValueError(
            f"the arms were given different guidance (`{plan.control.answer_guidance}` and "
            f"`{plan.treatment.answer_guidance}`). Guidance is a declared prompt "
            "intervention and it is in the digest: applied to one arm it is the thing "
            "being measured, not the thing being held fixed."
        )
    if plan.arm_order_mode not in ("control_first", "counterbalanced"):
        raise ValueError(f"unknown arm_order_mode {plan.arm_order_mode!r}")
    if plan.answer_attempts < 1 or plan.judge_replicates < 1:
        raise ValueError("answer_attempts and judge_replicates are counts of things that happen")
    if plan.answer_attempts != 1:
        raise ValueError(
            f"this plan asks for {plan.answer_attempts} answer attempts per (task, arm) and "
            "this driver can only produce one. `next_actions` launches a second attempt "
            "after an abandon, a stall or a crash and never after a run that finished, and "
            "`evidence_for` records one evidence per run and pools nothing -- so a plan "
            "declaring more is accepted, launched, spent, and then disagrees with its own "
            "runs in a report line. That is the twelve-runs shape this freeze exists to "
            "stop, and refusing here costs a string comparison. Pooling attempts means "
            "averaging them into one total *and* leaving `answer_attempts` in the "
            "environment digest, so that a half-applied pooling separates the two arms "
            "rather than averaging them; until that is built, one is the only honest value."
        )
    if plan.concurrency < 1 or plan.judge_concurrency < 1:
        raise ValueError("a concurrency below one is a trial that never starts a run")
    if not 0.0 < plan.max_refusal_rate_for_publication <= 1.0:
        raise ValueError(
            "max_refusal_rate_for_publication is a share in (0, 1]. Zero would withhold "
            "every difference and one would publish any of them."
        )
    if plan.minimum_effect_of_interest <= 0:
        raise ValueError(
            "minimum_effect_of_interest is what the trial was powered for; declaring zero "
            "is declaring that no sample size could be too small."
        )
    if not 0.0 < plan.pass_threshold <= FS_DATASET_POINTS_PER_ROW:
        raise ValueError(
            f"pass_threshold must be inside (0, {FS_DATASET_POINTS_PER_ROW:g}], the "
            "rubric's own scale."
        )
    unknown_faults = sorted(set(plan.fake_faults) - set(FS_FAKE_FAULTS))
    if unknown_faults:
        raise ValueError(
            f"unknown fake_faults: {', '.join(unknown_faults)}. Choose from "
            f"{', '.join(sorted(FS_FAKE_FAULTS))}; a fault nothing injects is a dry run "
            "that quietly exercises nothing."
        )
    if plan.fake_faults and plan.operator != "fake":
        raise ValueError(
            "fake_faults is a dry-run knob and this plan's operator is "
            f"{plan.operator!r}. Injecting a fault into a real arm would spend a real run "
            "on producing a refusal."
        )


def _refuse_a_label_that_is_not_the_producer(side: str, spec: FsArmSpec) -> None:
    """Fail at freeze time on the mismatch ``producer_matches_arm`` would fail on later.

    An arm carries the producer twice. For an ``autor`` arm, ``sha`` is what the worktree
    is checked out to and ``label`` is what the admission clause compares the recorded
    revision against, because the metadata records no SHA and the label is the only
    carrier. For a ``direct`` arm the pair is ``model`` and ``label``. Two fields, one
    fact, and only one of them is read by the gate.

    So a plan reading ``{"label": "off", "sha": "621566b"}`` -- the obvious way to write
    an on/off trial, and the way a flag-shaped CLI trains you to think -- is accepted,
    launched, and then has **every single arm refused** after the runs are already spent.
    Measured on the sibling benchmark's dry-run path: twelve runs, twelve refusals, zero
    pairs, and a report whose exclusion lines named the clause but not the cause.

    The relation checked here is exactly the one the clause will apply, so a plan that
    passes freeze cannot fail admission on this ground.
    """
    label = spec.label.strip()
    if not label:
        raise ValueError(f"the {side} arm has no label; every run of it would be refused")
    if spec.kind not in FS_ARM_KINDS:
        raise ValueError(
            f"the {side} arm's kind is {spec.kind!r}; it must be one of "
            f"{', '.join(FS_ARM_KINDS)}. The kind decides which admission clauses apply, "
            "so an unknown one is an arm no gate knows how to read."
        )
    if not spec.model.strip():
        raise ValueError(f"the {side} arm names no model; `producer_matches_arm` reads it")
    if spec.answer_guidance not in FS_ANSWER_GUIDANCE_CHOICES:
        raise ValueError(
            f"the {side} arm's guidance is {spec.answer_guidance!r}; it must be one of "
            f"{', '.join(FS_ANSWER_GUIDANCE_CHOICES)}"
        )
    if spec.kind == "direct":
        if spec.model not in label:
            raise ValueError(
                f"the {side} arm is labelled `{label}` and answers with `{spec.model}`. A "
                "direct arm's label is the only place its producer is named in the report, "
                "and a label that does not name the model is a column heading nobody can "
                "check the number against."
            )
        for name in ("worktree", "sha", "review_model", "profile"):
            if getattr(spec, name).strip():
                raise ValueError(
                    f"the {side} arm is `direct` and sets `{name}`. A direct arm makes one "
                    "call to a model: it has no worktree, no commit, no reviewer and no "
                    "profile, and a field that is recorded and never used is a description "
                    "of a producer that does not exist."
                )
        return
    sha = spec.sha.strip()
    if not sha:
        raise ValueError(f"the {side} arm has no sha; there is nothing to check the worktree out to")
    if not spec.worktree.strip():
        raise ValueError(f"the {side} arm has no worktree; there is nowhere to launch it from")
    if not spec.review_model.strip():
        raise ValueError(
            f"the {side} arm names no review model. The reviewer's model resolves "
            "independently of the operator's, so an arm that passes `--model` alone leaves "
            "the panels on whatever the backend defaults to -- which on this box is an "
            "exhausted pool the run dies in without ever being classified as a quota "
            "failure."
        )
    if spec.profile not in FS_PROFILE_CHOICES:
        raise ValueError(
            f"the {side} arm's profile is {spec.profile!r}; it must be one of "
            f"{', '.join(FS_PROFILE_CHOICES)}"
        )
    if not (label.startswith(sha) or sha.startswith(label)):
        raise ValueError(
            f"the {side} arm is labelled `{label}` but runs at `{sha}`. The arm label is "
            "what `producer_matches_arm` compares the run's recorded revision against, so "
            "every run of this arm would be launched, scored, and then discarded. Label "
            "the arm with its commit."
        )


def _refuse_a_budget_nobody_measured(plan: FsTrialPlan) -> None:
    """The plan has to say what it will cost, and which part of that was measured.

    A word gate, and a narrow one: the note must exist and must contain the word
    ``UNMEASURED`` while any arm of the plan is an ``autor`` arm. No real
    (non-fake-operator) AutoR run of FrontierScience-Research exists, so every statement
    about that arm's wall clock or score is a projection, and the cheapest thing to write
    in a config comment is a schedule that reads like an observation. This is the defect
    the whole integration was designed around, and the plan file is where it would land.

    Deliberately not a check that the note is *true*, which nothing can check. It is a
    check that the note contains the one word whose absence would let a projection be
    read as a measurement, and it goes away by itself the day somebody measures the arm
    and rewrites the note -- at which point the plan has no ``autor`` arm-shaped hole and
    this refusal has to be revisited rather than deleted quietly.
    """
    note = plan.cost_note.strip()
    if not note:
        raise ValueError(
            "the plan has no `cost_note`. A trial that runs for days is a spend, and a "
            "spend with no written estimate is one nobody can be held to."
        )
    if any(spec.kind == "autor" for spec in (plan.control, plan.treatment)):
        if "UNMEASURED" not in note:
            raise ValueError(
                "this plan has an `autor` arm and its `cost_note` does not contain the word "
                "UNMEASURED. No real AutoR run of this benchmark exists, so the arm's "
                "per-task wall clock and score are projections; a note that reads like a "
                "schedule somebody measured is the one thing this apparatus was built to "
                "refuse."
            )


def fs_arm_order(plan: FsTrialPlan) -> tuple[tuple[str, str], ...]:
    """The launch order: pair-major, both arms of a task adjacent.

    Adjacency is the point -- the two arms of one pair should straddle as little drift in
    backend load and judge behaviour as possible.

    ``counterbalanced`` is the default here and ``control_first`` is kept. The sibling
    trial defaults the other way round and is right to: it completes one or two pairs, and
    with one pair an alternating order turns a first-versus-second position effect into
    something that cannot be named afterwards, where a fixed order leaves it confounded
    and *legible*. At sixty pairs the position effect is estimable and alternating is what
    keeps it from loading entirely onto one arm.
    """
    order: list[tuple[str, str]] = []
    for index, task in enumerate(plan.tasks):
        first, second = plan.control.label, plan.treatment.label
        if plan.arm_order_mode == "counterbalanced" and index % 2 == 1:
            first, second = second, first
        order.append((task, first))
        order.append((task, second))
    return tuple(order)


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------


def classify_fs_run(state: Mapping[str, Any]) -> str:
    """``ok`` / ``stalled`` / ``crashed`` / ``fallback`` / ``incomplete``.

    Read off the state file the driver wrote from ``_meta.json``, and never off the
    driver's own stdout: the front end catches its exceptions and writes them into the
    run's event stream, so a classifier that greps the driver's output sees a clean exit
    for a run that failed inside.

    ``crashed`` and not ``incomplete`` when there is no metadata at all. They are
    different events with different policies: a run that wrote metadata saying it did not
    complete has *answered*, and answering badly is not something a second draw fixes; a
    run that wrote nothing was killed, and that is what an attempt budget is for.
    """
    if state.get("stalled"):
        return "stalled"
    if not state.get("meta_present"):
        return "crashed"
    if state.get("meta_answer_source") == FS_SOURCE_FALLBACK or state.get(
        "answer_first_line_is_fallback"
    ):
        return "fallback"
    if state.get("meta_status") != "completed":
        return "incomplete"
    return "ok"


#: Classifications a second attempt can plausibly fix, because the run was interrupted
#: rather than finished. Everything else is a run that produced a non-run: retrying it is
#: a fresh draw on the same dice, and it is not the failure retrying is for.
FS_RETRYABLE = ("stalled", "crashed")


@dataclass(frozen=True)
class FsAction:
    """What the shell should do next. A value, so the planner can be tested at all.

    ``kind`` is one of ``launch`` / ``abandon`` / ``refuse`` / ``wait`` / ``final_pass``
    / ``done``. ``wait`` is the one the sibling driver has no use for: it runs one child
    at a time and blocks in the watchdog, so "there is nothing to start and something is
    still running" is not a state it can be in. Here it is the ordinary state for most of
    a trial, and naming it is what lets the planner stay pure -- the alternative is a
    shell that decides for itself whether an empty action list means "sleep" or "stop".

    Not imported from :mod:`src.rcb_trial`. An action vocabulary is not
    benchmark-agnostic: that one has ``backoff`` and ``score`` and this one has neither,
    and the shared kernel holds only what genuinely does not name a benchmark.
    """

    kind: str
    task_key: str = ""
    arm: str = ""
    attempt: int = 0
    reason: str = ""


def next_actions(
    plan: FsTrialPlan,
    states: Sequence[Mapping[str, Any]],
    *,
    now: float,
    live_pids: frozenset[int] = frozenset(),
    final_pass_done: bool = False,
) -> tuple[FsAction, ...]:
    """The whole recovery policy, as a pure function of the state directory.

    Written as a value-returning function rather than as control flow inside the driver
    because the alternative is validating multi-day kill-and-restart behaviour by
    spending multi-day kill-and-restart wall clock.

    Four decisions worth reading, each of them a difference from the sibling driver:

    * **A live ``launched`` run consumes budget rather than aborting the trial.** The
      sibling runs one child at a time, so a child from a previous driver is proof that
      two drivers are racing and it aborts. Here the plan asks for several at once, and
      the same state is the ordinary one after a restart: the lock has already refused a
      second live driver, so a live child is *this* trial's child and the right response
      is to count it and start fewer.
    * **A ``launched`` run whose pid is gone is abandoned and never resumed** -- but not
      before :data:`FS_LAUNCH_GRACE_SECONDS`. There is no resume: ``fs_agent.py`` has
      ``--export-only`` and nothing else, and adopting a half-finished workspace would
      mean scoring an answer nobody can say was finished. The replacement attempt gets a
      *fresh* workspace. The grace is there because "its pid is gone" is not observable
      the instant a run starts: the state file is written before ``Popen`` and carries no
      pid at all, and the pid set is a ``/proc`` walk that takes longer than the child
      takes to exist. Without it the driver abandoned runs it had just launched.
    * **``fallback`` and ``incomplete`` are refused, not retried.** The run ran and
      produced a non-run. A second draw on the same dice is not what an attempt budget is
      for, and spending it hides the failure behind an eventual success.
    * **No score action.** The sibling scores in the loop for early warning and pays a
      judge for it. Nine of the ten clauses here read ``_meta.json`` and cost nothing, so
      the early warning is free and the judge is spent exactly once, in a single
      continuous final pass -- which is also what keeps judge drift out of the published
      difference.
    """
    by_key: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for state in states:
        key = (str(state.get("task_key", "")), str(state.get("arm", "")))
        by_key.setdefault(key, []).append(state)

    live: set[tuple[str, str]] = set()
    actions: list[FsAction] = []
    for state in states:
        key = (str(state.get("task_key", "")), str(state.get("arm", "")))
        if state.get("phase") != "launched":
            continue
        launched_at = state.get("launched_at")
        dated = isinstance(launched_at, (int, float))
        if int(state.get("child_pid") or 0) in live_pids:
            live.add(key)
        elif dated and now - float(launched_at) < FS_LAUNCH_GRACE_SECONDS:
            # Too young to be called dead: see FS_LAUNCH_GRACE_SECONDS. Counted as live
            # rather than merely skipped, because the child almost certainly is running
            # and the concurrency budget below has to see it -- treating it as neither
            # live nor abandoned would let the loop start one more run than the plan asks
            # for, every time a launch is polled inside its own first second.
            #
            # A state with no `launched_at` gets no grace and behaves exactly as before.
            # The field has been written by `launch_run` since the driver existed, so the
            # only states without one are hand-made; failing back to the old behaviour is
            # the right answer for a record this cannot date.
            #
            # `isinstance` and not `or 0.0`: the first draft of this coerced a missing
            # field to 0.0, which gives an undated record a *sixty-second* grace whenever
            # `now` is itself near zero -- and `test_a_launched_run_whose_pid_is_gone_is_
            # abandoned_and_never_resumed` calls this with `now=0.0`. The comment above
            # was true of the intent and false of the code until that test said so.
            live.add(key)
        else:
            actions.append(
                FsAction(
                    "abandon",
                    task_key=key[0],
                    arm=key[1],
                    attempt=int(state.get("attempt") or 1),
                    reason=(
                        "the driver died with this run in flight and the child is gone. "
                        "There is no resume, so the attempt is abandoned and re-planned "
                        "into a fresh workspace; the old one is left on disk because the "
                        "run tree lives inside it."
                    ),
                )
            )

    budget = max(0, plan.concurrency - len(live))
    pending = False
    for key in fs_arm_order(plan):
        entries = by_key.get(key, [])
        task, arm = key
        if any(item.get("phase") == "refused" for item in entries):
            # Terminal. Re-emitting the refusal would loop, and re-launching after one
            # would spend the budget the refusal exists to stop spending.
            continue
        if key in live:
            pending = True
            continue
        attempts = sorted(entries, key=lambda item: int(item.get("attempt") or 0))
        if not attempts:
            if now >= plan.deadline > 0:
                continue
            pending = True
            if budget > 0:
                budget -= 1
                actions.append(FsAction("launch", task_key=task, arm=arm, attempt=1))
            continue

        latest = attempts[-1]
        attempt = int(latest.get("attempt") or 1)
        phase = str(latest.get("phase", ""))
        if phase == "launched":
            # Already turned into an `abandon` above; the replacement is planned on the
            # next pass, once the abandonment is on disk. Emitting both at once would
            # have the shell launch against a state file that still says `launched`.
            pending = True
            continue
        classification = str(latest.get("classification") or classify_fs_run(latest))
        if phase == "abandoned" or classification in FS_RETRYABLE:
            if len(attempts) >= plan.max_attempts or now >= plan.deadline > 0:
                actions.append(
                    FsAction(
                        "refuse",
                        task_key=task,
                        arm=arm,
                        reason=classification or "abandoned",
                    )
                )
                continue
            pending = True
            if budget > 0:
                budget -= 1
                actions.append(
                    FsAction("launch", task_key=task, arm=arm, attempt=attempt + 1)
                )
            continue
        if classification != "ok":
            actions.append(FsAction("refuse", task_key=task, arm=arm, reason=classification))

    if actions:
        return tuple(actions)
    if pending:
        return (
            FsAction(
                "wait",
                reason=(
                    f"{len(live)} run(s) in flight against a concurrency of "
                    f"{plan.concurrency}; nothing else can start until one finishes."
                ),
            ),
        )
    if not final_pass_done:
        return (FsAction("final_pass"),)
    return (FsAction("done"),)
