"""A reviewer whose job is to attack the result, not to check that it exists.

AutoR's existing ``AutomatedReviewer`` is a completeness gate. Its policy is
"materially complete", "looks toy", "missing concrete files" — it asks whether
the stage did work, never whether the work supports what it says. Nothing in
the pipeline ever asked *why is this result wrong*.

This runs after Stage 05 and Stage 06, with the opposite instruction: assume the
result is an artifact and find the mechanism. It has no authority to approve or
reject — that stays with the approval gate — and it does not edit anything. What
it produces is a list of specific, checkable objections, and the next stage is
required to answer every one of them, either by addressing it or by rebutting it
in writing.

That asymmetry is deliberate. A reviewer that can block creates a deadlock
between two agents; a reviewer whose findings must be *answered* creates a
record of what was considered and dismissed, which is the thing a reader of the
run actually needs.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from .approval_agent import extract_json_payload
from .call_cost import CallCost, cost_from_stream_meta
from .review_panel import PANEL_DIRNAME
from .review_custody import DEFAULT_CUSTODY_MODE, CustodyWatch
from .terminal_ui import TerminalUI
from .utils import (
    RunPaths,
    StageSpec,
    append_jsonl,
    goal_excerpt,
    read_text,
    truncate_text,
    write_text,
)


#: The stages worth attacking. Before 05 there is no result to be wrong about;
#: after 07 the manuscript is written and an objection arrives too late to change
#: anything but the prose.
REVIEWED_STAGE_NUMBERS = (5, 6)

#: Failure modes that produce a clean-looking positive result. Naming them beats
#: asking for "any problems": an open-ended critique reliably returns prose
#: quality, which is not what is dangerous here.
VALIDITY_CATEGORIES = (
    "confound",
    "weak_baseline",
    "insufficient_replication",
    "leakage",
    "metric_cherry_picking",
    "effect_within_noise",
    "overclaim",
    "unsupported_generalization",
    "missing_ablation",
    "irreproducible_procedure",
)

SEVERITIES = ("critical", "major", "minor")

#: How the next stage may dispose of a finding. There is no third option, and in
#: particular there is no "noted".
RESPONSE_STATUSES = ("addressed", "rebutted", "accepted_limitation")

#: How the adversarial pass ended, in the approval gate's vocabulary rather than a
#: second one of this module's own.
#:
#: :mod:`src.approval_agent` already separates "the backend never ran"
#: (``CRASHED_REASON``) from "it answered and the answer could not be read"
#: (``UNREADABLE_REASON``), and exposes a single predicate,
#: ``AutomatedReviewer.is_degraded_verdict``, for everything downstream. Both events
#: happen to this pass too, so it reuses the split. The third member of that
#: vocabulary, ``UNSUPPORTED_REASON``, has no counterpart here: it names a decision
#: token outside the gate's vocabulary, and this reviewer casts no vote — an
#: unrecognised ``category`` is coerced to ``overclaim`` rather than voiding the
#: finding, because losing a real objection to a taxonomy mismatch is the worse error.
COMPLETED = "completed"
CRASHED = "crashed"
UNREADABLE = "unreadable"
#: The pass ran and changed the run root while running. Its findings are kept -- see
#: :meth:`ValidityReviewer.review` -- and its clean bill is not credited.
TAMPERED = "tampered"

#: The completions under which the stage did not get a review it can stand on.
#:
#: It was two, and both meant the reviewer never looked. ``TAMPERED`` is the third and
#: means something else: it looked, and it moved what it was looking at, so its silence
#: is not evidence of anything. ``reviewer_failed`` in the written artifact is derived
#: from this and therefore now answers the slightly wider question -- *is this stage's
#: attack usable* rather than *did the attack run* -- which is the question every reader
#: of the field was already using it to answer.
DEGRADED_COMPLETIONS = (CRASHED, UNREADABLE, TAMPERED)


def is_degraded_completion(completion: str) -> bool:
    """Whether the empty finding list is AutoR's, rather than the reviewer's.

    The counterpart of ``AutomatedReviewer.is_degraded_verdict``, asking the same
    question of a pass that produces no verdict: did a reviewer look and find nothing,
    or did no reviewer look. Those are the same value — ``[]`` — everywhere downstream,
    and only this tells them apart.
    """
    return completion in DEGRADED_COMPLETIONS


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def validity_review_path(paths: RunPaths, stage_slug: str):
    return paths.reviews_dir / f"validity_review_{stage_slug}.json"


def validity_response_path(paths: RunPaths, reviewed_stage_slug: str):
    return paths.reviews_dir / f"validity_response_{reviewed_stage_slug}.json"


def reviewed_stage_for(stage: StageSpec) -> str | None:
    """Which earlier stage's validity review this stage has to answer."""
    if stage.number == 6:
        return "05_experimentation"
    if stage.number == 7:
        return "06_analysis"
    return None


@dataclass(frozen=True)
class ValidityFinding:
    identifier: str
    category: str
    severity: str
    finding: str
    why_it_matters: str
    what_would_settle_it: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.identifier,
            "category": self.category,
            "severity": self.severity,
            "finding": self.finding,
            "why_it_matters": self.why_it_matters,
            "what_would_settle_it": self.what_would_settle_it,
        }


@dataclass(frozen=True)
class ValidityReviewOutcome:
    """What the pass produced, and whether it ran at all.

    :meth:`ValidityReviewer.review` used to return the findings alone. That makes "a
    reviewer attacked the stage and found nothing" and "no reviewer ever returned" the
    same value, and the value is ``[]`` — which every reader downstream, the next
    stage's gate included, takes as nothing owed. The completion is carried beside the
    findings so a caller cannot read one without being handed the other.
    """

    completion: str
    findings: list[ValidityFinding]
    #: What the adversarial pass cost, when it made a backend call at all. The unmeasured
    #: report on every path that returns without one -- the stage that is not reviewed, the
    #: findings carried over from a panel, fake-operator mode -- because those spent nothing
    #: and "spent nothing" is not the same claim as "cost zero dollars".
    call_cost: CallCost = field(default_factory=CallCost)

    @property
    def degraded(self) -> bool:
        return is_degraded_completion(self.completion)


# ----------------------------------------------------------------------------
# AutoR's own copy of what the pass raised
# ----------------------------------------------------------------------------


def validity_review_stamp_path(paths: RunPaths):
    """What each adversarial pass raised, outside the tree the answering stage works in.

    ``report_plan_stamp.json`` and ``preregistration_stamp.json`` are the precedent, and
    the reason is the one #202 wrote down one artifact short of acting on:
    ``workspace/reviews/`` is writable by the stage the next gate constrains, so the file
    naming the objections a stage owes an answer to was handed to the stage that owes
    them. #202 moved the *completion* into the harness for exactly that reason and left
    the findings behind.

    Measured on a run from ``build_run_paths`` plus one :meth:`ValidityReviewer._write_review`
    carrying a single critical finding, ``validate_validity_response`` at Stage 06 went
    from one problem to zero when the workspace copy was deleted, and to zero again when
    its ``findings`` list was emptied in place — the objection and the obligation to
    answer it disappearing together, with the run's own artifacts then saying no reviewer
    had raised anything.

    The claim is not that this store cannot be reached. Everything under ``run_root`` is
    writable by the party the gate constrains, which ``docs/framework.md`` already states
    for the other two stamps and which holds here unchanged. What it buys is that the
    population the gate counts is AutoR's, that erasing an objection is no longer one
    ``rm`` inside the directory every stage prompt names, and that the erasure is refused
    and repaired rather than absorbed.
    """
    return paths.run_root / "validity_review_stamp.json"


#: Heading of the run-log line the manager writes when it puts its copy back.
#:
#: The repair is what destroys the evidence it was needed — once the stamped findings are
#: written over the workspace copy the two agree again — so the disagreement goes to
#: ``logs.txt``, which is append-only and written by the manager, before the copy is
#: restored. Same third-witness argument as :data:`src.preregistration.FREEZE_WITNESS_HEADING`,
#: and with the same boundary: a tamper that also truncates the log still gets through.
RESTORE_WITNESS_HEADING = "validity_review_restored"

#: What clears the refusal. Deliberately does not say "rewrite the file": asking the stage
#: that erased the objections to reconstruct them is asking the examinee to reprint the
#: exam paper, and a refusal naming a step the run should not take is worse than none.
VALIDITY_REVIEW_RECOVERY = (
    "Leave the workspace copy alone and answer the findings as AutoR stamped them — the "
    "next attempt's prompt writes the record back and lists them again."
)


def _findings_from_payload(payload: object) -> list[ValidityFinding]:
    if not isinstance(payload, dict):
        return []
    findings: list[ValidityFinding] = []
    for entry in payload.get("findings", []):
        if not isinstance(entry, dict):
            continue
        findings.append(
            ValidityFinding(
                identifier=str(entry.get("id") or "").strip(),
                category=str(entry.get("category") or "").strip(),
                severity=str(entry.get("severity") or "").strip(),
                finding=str(entry.get("finding") or "").strip(),
                why_it_matters=str(entry.get("why_it_matters") or "").strip(),
                what_would_settle_it=str(entry.get("what_would_settle_it") or "").strip(),
            )
        )
    return findings


def _stamped_reviews(paths: RunPaths) -> dict:
    payload = _load_json(validity_review_stamp_path(paths))
    reviews = payload.get("reviews") if isinstance(payload, dict) else None
    return reviews if isinstance(reviews, dict) else {}


def stamped_review(paths: RunPaths, stage_slug: str) -> dict | None:
    """AutoR's record of the pass over ``stage_slug``, or None if it never stamped one.

    None is the pre-stamp state and the only one in which the workspace copy is worth
    anything: a run resumed from an AutoR that predates this, or a stage no reviewer has
    reached yet. It is not a pass — :func:`validity_review_tamper` is silent there
    because it has nothing to compare against, not because the file was checked.
    """
    entry = _stamped_reviews(paths).get(stage_slug)
    return entry if isinstance(entry, dict) else None


def _write_stamp(paths: RunPaths, stage_slug: str, entry: dict) -> None:
    path = validity_review_stamp_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    reviews = dict(_stamped_reviews(paths))
    reviews[stage_slug] = entry
    path.write_text(
        json.dumps({"stamped_at": _now(), "reviews": reviews}, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )


def load_findings(paths: RunPaths, stage_slug: str) -> list[ValidityFinding]:
    """The findings the run owes an answer to, from AutoR's copy where there is one.

    Every reader goes through here — the gate, the prompt that lists the objections, and
    fake mode's answerer — so the stamp being authoritative here is what makes deleting
    the workspace copy buy nothing anywhere rather than nothing in one place.
    """
    stamped = stamped_review(paths, stage_slug)
    if stamped is not None:
        return _findings_from_payload(stamped)
    return _findings_from_payload(_load_json(validity_review_path(paths, stage_slug)))


def validity_review_tamper(paths: RunPaths, stage_slug: str) -> str:
    """How the workspace copy disagrees with the stamp, in one sentence. "" when it does not.

    Compares the finding records rather than the bytes. A byte comparison would never
    converge — the restored file carries a fresh ``generated_at`` — and #206 found the
    shape that failure takes: a repair applied on every attempt, appending an identical
    row to the record without bound while nothing gets better.
    """
    stamped = stamped_review(paths, stage_slug)
    if stamped is None:
        return ""

    expected = [item.to_dict() for item in _findings_from_payload(stamped)]
    path = validity_review_path(paths, stage_slug)
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return (
            f"workspace/reviews/{path.name} is gone or unreadable, and AutoR's stamped copy "
            f"records {len(expected)} finding(s) raised against {stage_slug}"
        )

    present = [item.to_dict() for item in _findings_from_payload(payload)]
    if present == expected:
        return ""

    # Dropped and rewritten are named apart because they are different edits and this
    # sentence is where a reader of `logs.txt` finds out which one happened. An id that
    # is still on the page with softer words under it has not been dropped, and calling
    # it dropped sends the reader looking for a row that is sitting right there — the
    # equal-cardinality rewrite is the cheapest tamper of the two, so it is the one the
    # wording must not misreport.
    present_ids = {item["id"] for item in present}
    dropped = [item["id"] for item in expected if item["id"] not in present_ids]
    rewritten = [
        item["id"] for item in expected if item["id"] in present_ids and item not in present
    ]
    detail = ", ".join(
        part
        for part in (
            f"dropping {', '.join(dropped)}" if dropped else "",
            f"rewriting {', '.join(rewritten)}" if rewritten else "",
        )
        if part
    )
    return (
        f"workspace/reviews/{path.name} holds {len(present)} finding(s) where AutoR stamped "
        f"{len(expected)}" + (f", {detail}" if detail else ", rewritten in place")
    )


def restore_validity_review(paths: RunPaths, stage_slug: str) -> str:
    """Write AutoR's record back over a workspace copy that disagrees. "" when clean.

    Returns the disagreement so the caller can put it in the run log *before* the copy is
    restored, because after the restore there is nothing left on disk to show it happened.
    """
    disagreement = validity_review_tamper(paths, stage_slug)
    if not disagreement:
        return ""
    stamped = stamped_review(paths, stage_slug) or {}
    _write_review_file(
        paths,
        stage_slug,
        _findings_from_payload(stamped),
        note=str(stamped.get("note") or ""),
        completion=str(stamped.get("completion") or COMPLETED),
    )
    return disagreement


def _write_review_file(
    paths: RunPaths,
    stage_slug: str,
    findings: list[ValidityFinding],
    *,
    note: str,
    completion: str,
) -> None:
    """The workspace artifact, from whichever party is writing it.

    Shared by the reviewer and the repair so a restored file is the same shape as an
    original one; if they diverged, :func:`validity_review_tamper` would report a tamper
    against AutoR's own repair forever.
    """
    payload = {
        "generated_at": _now(),
        "reviewed_stage": stage_slug,
        # Derived rather than stored beside the completion, and deliberately the
        # only shape of it that reaches disk. Nothing decides on this copy: the
        # completion is the manager's record (#202) and the findings are the stamp's,
        # both for the same reason — `workspace/reviews/` is writable by the very stage
        # the next gate constrains. What is written here is the artifact field
        # docs/run-artifacts.md already documents, unchanged.
        "reviewer_failed": is_degraded_completion(completion),
        "note": note,
        "findings": [item.to_dict() for item in findings],
    }
    write_text(
        validity_review_path(paths, stage_slug),
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


def validate_validity_response(paths: RunPaths, stage: StageSpec) -> list[str]:
    """Every finding from the previous stage's review must be answered.

    Answering is cheap and dismissing is allowed — ``rebutted`` with an argument
    is a complete response, and so is ``accepted_limitation``. What is not
    allowed is silence, because a finding nobody responded to is
    indistinguishable in the record from one nobody raised.
    """
    reviewed = reviewed_stage_for(stage)
    if reviewed is None:
        return []

    problems: list[str] = []
    # Refused here rather than only in the manager, which is where #202 put the
    # *completion* and for a reason that does not carry: a Stage 06 agent cannot re-run
    # Stage 05's reviewer, so a backend failure refused here would spend the whole
    # attempt budget on a repair the stage cannot make. This is the opposite case. The
    # disagreement is the answering stage's own edit, and the repair is AutoR's — the
    # next attempt's prompt build writes the record back — so the refusal costs one
    # attempt and clears itself, instead of clearing silently.
    disagreement = validity_review_tamper(paths, reviewed)
    if disagreement:
        problems.append(
            f"cannot be judged against the adversarial review of {reviewed}: "
            f"{disagreement}. {VALIDITY_REVIEW_RECOVERY}"
        )

    findings = load_findings(paths, reviewed)
    if not findings:
        # No review ran, or it found nothing. Either way there is nothing owed —
        # except an explanation for a record that disagrees with AutoR's own.
        return problems

    response_path = validity_response_path(paths, reviewed)
    payload = _load_json(response_path)
    if payload is None:
        return problems + [
            f"requires {response_path.name} under workspace/reviews answering each of the "
            f"{len(findings)} validity findings raised against {reviewed}. A finding nobody "
            "responded to is indistinguishable from one nobody raised."
        ]
    if not isinstance(payload, dict):
        return problems + [f"{response_path.name} must contain a JSON object."]

    responses = payload.get("responses")
    if not isinstance(responses, list):
        return problems + [f"{response_path.name} must contain a responses list."]

    by_id: dict[str, dict] = {}
    for entry in responses:
        if isinstance(entry, dict):
            identifier = str(entry.get("id") or "").strip()
            if identifier:
                by_id[identifier] = entry

    for finding in findings:
        entry = by_id.get(finding.identifier)
        if entry is None:
            problems.append(
                f"{response_path.name} does not answer validity finding {finding.identifier} "
                f"({finding.severity} {finding.category}): {finding.finding[:90]}"
            )
            continue
        status = str(entry.get("status") or "").strip()
        if status not in RESPONSE_STATUSES:
            problems.append(
                f"{response_path.name} answers {finding.identifier} with status {status!r}; "
                f"expected one of {', '.join(RESPONSE_STATUSES)}."
            )
        explanation = str(entry.get("explanation") or "").strip()
        if len(explanation) < 40:
            problems.append(
                f"{response_path.name} answers {finding.identifier} with no substantive "
                "explanation. Say what changed, or why the objection does not hold."
            )
        if status == "addressed" and not str(entry.get("evidence") or "").strip():
            problems.append(
                f"{response_path.name} marks {finding.identifier} addressed but points at "
                "nothing. Name the artifact or the change that addresses it."
            )

    unknown = set(by_id) - {finding.identifier for finding in findings}
    for identifier in sorted(unknown):
        problems.append(
            f"{response_path.name} answers {identifier}, which is not a finding in "
            f"{validity_review_path(paths, reviewed).name}."
        )
    return problems


def format_findings_for_prompt(paths: RunPaths, stage: StageSpec) -> str:
    reviewed = reviewed_stage_for(stage)
    if reviewed is None:
        return ""
    findings = load_findings(paths, reviewed)
    if not findings:
        return ""

    response_path = validity_response_path(paths, reviewed)
    lines = [
        f"An adversarial reviewer attacked {reviewed} and raised {len(findings)} findings.",
        "Its job was to explain why the result is wrong, so treat these as the objections a",
        "hostile reviewer will make. You must answer every one.",
        "",
    ]
    for finding in findings:
        lines.append(f"- **{finding.identifier}** ({finding.severity} · {finding.category}) {finding.finding}")
        if finding.why_it_matters:
            lines.append(f"  - Why it matters: {finding.why_it_matters}")
        if finding.what_would_settle_it:
            lines.append(f"  - What would settle it: {finding.what_would_settle_it}")
    lines.extend(
        [
            "",
            f"Write `{response_path.resolve()}`:",
            "",
            "```json",
            '{"responses": [{"id": "V1", "status": "addressed | rebutted | accepted_limitation",',
            '  "explanation": "what changed, or why the objection does not hold",',
            '  "evidence": "the artifact or change (required when addressed)"}]}',
            "```",
            "",
            "`rebutted` is a complete answer when you have an argument. So is",
            "`accepted_limitation` when the objection stands and the run cannot fix it — say so",
            "in the manuscript too. What is not acceptable is leaving a finding unanswered.",
        ]
    )
    return "\n".join(lines)


def findings_from_panel(paths: RunPaths, stage: StageSpec) -> list[ValidityFinding]:
    """Convert a review panel's surviving concerns into answerable findings.

    The panel (:mod:`src.review_panel`) already fields a Methodologist and a
    Reviewer 2 whose mandates overlap this module's categories, so running a
    separate critic on top of it would ask the same questions twice and pay for
    both. When a panel deliberated over this stage, its concerns *are* the
    findings — what this module adds is the part the panel does not have: an
    obligation on the **next** stage to answer them.

    Only the final round counts. A concern that a member withdrew during
    deliberation was answered inside the panel, and re-raising it would punish
    the deliberation for working.
    """
    panel_dir = paths.reviews_dir / PANEL_DIRNAME
    if not panel_dir.is_dir():
        return []

    latest = None
    for candidate in sorted(panel_dir.glob(f"{stage.slug}*.json")):
        payload = _load_json(candidate)
        if isinstance(payload, dict) and payload.get("stage") == stage.slug:
            latest = payload
    if latest is None:
        return []

    rounds = latest.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        return []
    final_round = rounds[-1]
    if not isinstance(final_round, list):
        return []

    findings: list[ValidityFinding] = []
    for verdict in final_round:
        if not isinstance(verdict, dict) or verdict.get("failed"):
            continue
        role = str(verdict.get("title") or verdict.get("role") or "panel member").strip()
        blocking = bool(verdict.get("blocking"))
        for concern in verdict.get("concerns", []):
            text = str(concern).strip()
            if not text:
                continue
            findings.append(
                ValidityFinding(
                    identifier=f"V{len(findings) + 1}",
                    category="overclaim",
                    severity="critical" if blocking else "major",
                    finding=text,
                    why_it_matters=f"Raised by the {role} and still standing after deliberation.",
                    what_would_settle_it=str(verdict.get("feedback") or "").strip(),
                )
            )
    return findings


class ValidityReviewer:
    """Runs the red-team pass. Shares the operator machinery with the approval gate."""

    def __init__(
        self,
        operator,
        *,
        ui: TerminalUI | None = None,
        custody_mode: str = DEFAULT_CUSTODY_MODE,
    ) -> None:
        self._operator = operator
        self.ui = ui or TerminalUI()
        self.custody_mode = custody_mode

    @property
    def fake_mode(self) -> bool:
        return bool(getattr(self._operator, "fake_mode", False))

    def review(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        stage_markdown: str,
        attempt_no: int = 1,
    ) -> ValidityReviewOutcome:
        """Attack the stage once, and say how the attempt ended.

        ``attempt_no`` only reaches the operator's own logging, so a re-ask is
        distinguishable in ``logs/raw`` from the call that provoked it. Deciding
        *whether* to re-ask is the manager's: it owns the operator and the budget, and
        this returns the fact it needs rather than acting on it.
        """
        if stage.number not in REVIEWED_STAGE_NUMBERS:
            # Nothing to complete: before 05 there is no result to be wrong about. The
            # empty list here is an absence of subject matter, not an absent judgement,
            # so it must not read as degraded.
            return ValidityReviewOutcome(COMPLETED, [])

        # If a panel already deliberated over this stage, its surviving concerns
        # are the findings. Running a second critic would ask the Methodologist's
        # questions twice and pay for both.
        from_panel = findings_from_panel(paths, stage)
        if from_panel:
            self._write_review(
                paths, stage, from_panel, note="carried from the review panel's final round"
            )
            return ValidityReviewOutcome(COMPLETED, from_panel)

        if self.fake_mode:
            findings = [
                ValidityFinding(
                    identifier="V1",
                    category="insufficient_replication",
                    severity="critical",
                    finding="The reported comparison rests on a single run of a two-row synthetic split.",
                    why_it_matters=(
                        "A single run cannot separate the effect from variance, so the gap is "
                        "not evidence about the method."
                    ),
                    what_would_settle_it="Repeat the comparison across at least five seeds and report the spread.",
                )
            ]
            self._write_review(paths, stage, findings, note="fake-operator mode")
            return ValidityReviewOutcome(COMPLETED, findings)

        prompt_path = paths.prompt_cache_dir / f"{stage.slug}_validity_review.prompt.md"
        write_text(prompt_path, self._build_prompt(paths=paths, stage=stage, stage_markdown=stage_markdown))

        session_id = str(uuid.uuid4())
        command, invocation_cwd, stdin_text = self._operator._prepare_invocation(  # noqa: SLF001
            prompt_path, session_id, paths=paths, resume=False
        )
        append_jsonl(
            paths.logs_raw,
            {
                "_meta": {
                    "stage": stage.slug,
                    "mode": "validity_review_start",
                    "command": command,
                    "prompt_path": str(prompt_path),
                    "session_id": session_id,
                    "attempt_no": attempt_no,
                }
            },
        )
        watch = CustodyWatch(paths, mode=self.custody_mode)
        watch.open()
        exit_code, stdout_text, stderr_text, _observed, _meta = self._operator._run_streaming_command(  # noqa: SLF001
            command=command,
            cwd=invocation_cwd,
            stage=stage,
            attempt_no=attempt_no,
            paths=paths,
            mode="validity_review",
            stdin_text=stdin_text,
        )
        breach = watch.close(stage_slug=stage.slug, label="validity_review")
        # Carried out on all three paths below, including the two that produced no
        # findings. A red-team pass that crashed still bought the tokens it burned, and a
        # cost recorded only when the call succeeded would under-report exactly the visits
        # whose spend is worth reading.
        call_cost = cost_from_stream_meta(_meta)
        if exit_code != 0:
            # A red-team pass that did not run is recorded as not having run.
            # Writing an empty finding list would read as "nothing wrong".
            self._write_review(
                paths,
                stage,
                [],
                note=f"the validity reviewer failed with exit code {exit_code} and raised nothing",
                completion=CRASHED,
            )
            return ValidityReviewOutcome(CRASHED, [], call_cost)

        payload = self._extract_json(stdout_text)
        if payload is None:
            # Not "it returned nothing": there is no findings object at all. Emptiness
            # cannot be the test, because `{"findings": []}` is a clean review and the
            # prompt above says in as many words that raising nothing is legitimate.
            # The absence of the object the prompt asked for can be, and it is the same
            # event the approval gate calls unreadable.
            self._write_review(
                paths,
                stage,
                [],
                note=(
                    f"the validity reviewer returned {len(stdout_text)} characters carrying no "
                    "findings object, so this stage has no judgement rather than a clean one"
                ),
                completion=UNREADABLE,
            )
            return ValidityReviewOutcome(UNREADABLE, [], call_cost)

        findings = self._findings_from(payload)
        # The one place the borrowed demotion inverts, and it must not be copied straight.
        # `validate_validity_response` returns early on an empty finding list -- "no review
        # ran, or it found nothing; either way there is nothing owed" -- so discarding a
        # tampering reviewer's findings would delete the next stage's obligation and make
        # a gate *pass*. The findings go through untouched and the completion carries the
        # doubt: the stage still owes exactly what it owed, and the run stops calling this
        # pass completed.
        if watch.arms_a_demotion and breach.mutated:
            self._write_review(
                paths,
                stage,
                findings,
                note=(
                    "the validity reviewer changed the run root while attacking it -- "
                    + breach.summary()
                ),
                completion=TAMPERED,
            )
            return ValidityReviewOutcome(TAMPERED, findings, call_cost)
        self._write_review(paths, stage, findings)
        return ValidityReviewOutcome(COMPLETED, findings, call_cost)

    def _write_review(
        self,
        paths: RunPaths,
        stage: StageSpec,
        findings: list[ValidityFinding],
        *,
        note: str = "",
        completion: str = COMPLETED,
    ) -> None:
        # Both copies, always, in that order: the stamp is the population the next
        # stage's gate counts against, so a pass that reached the workspace and not the
        # run root would be a review nothing can hold anybody to.
        _write_stamp(
            paths,
            stage.slug,
            {
                "stamped_at": _now(),
                "reviewed_stage": stage.slug,
                "completion": completion,
                "note": note,
                "findings": [item.to_dict() for item in findings],
            },
        )
        _write_review_file(
            paths, stage.slug, findings, note=note, completion=completion
        )

    def _parse(self, raw: str) -> list[ValidityFinding]:
        payload = self._extract_json(raw)
        if not isinstance(payload, dict):
            return []
        return self._findings_from(payload)

    def _findings_from(self, payload: dict) -> list[ValidityFinding]:
        """The findings in an object that has already been recovered from a transcript.

        Split from :meth:`_parse` because :meth:`review` has to know *which* of the two
        empty results it got — no object, or an object with an empty list — and a
        function that swallows the distinction cannot tell it.
        """
        findings: list[ValidityFinding] = []
        for index, entry in enumerate(payload.get("findings", []), start=1):
            if not isinstance(entry, dict):
                continue
            finding = str(entry.get("finding") or "").strip()
            if not finding:
                continue
            category = str(entry.get("category") or "").strip()
            severity = str(entry.get("severity") or "").strip()
            findings.append(
                ValidityFinding(
                    identifier=str(entry.get("id") or "").strip() or f"V{index}",
                    category=category if category in VALIDITY_CATEGORIES else "overclaim",
                    severity=severity if severity in SEVERITIES else "major",
                    finding=finding,
                    why_it_matters=str(entry.get("why_it_matters") or "").strip(),
                    what_would_settle_it=str(entry.get("what_would_settle_it") or "").strip(),
                )
            )
        return findings

    @staticmethod
    def _extract_json(raw: str):
        """The findings object, from a transcript that also contains other JSON.

        This used to be a fourth private copy of the same idea, and the narrowest: it tried
        the whole string and then ``text[first '{' : last '}']``. On an adversarial review
        that read a JSON artifact before answering, that slice spans both objects and parses
        as neither. Its failure used to be silent, because :meth:`_parse` returned an empty
        list either way and the run then recorded that the reviewer had attacked the stage and
        raised nothing. It is no longer silent: :meth:`review` treats a ``None`` payload as
        ``UNREADABLE``, re-asks once, and discloses a pass that never completed. Returning
        ``None`` rather than ``{}`` is what keeps that distinguishable from ``{"findings": []}``,
        which is a clean review the prompt explicitly blesses.
        """
        return extract_json_payload(raw, verdict_key="findings")

    def _build_prompt(self, *, paths: RunPaths, stage: StageSpec, stage_markdown: str) -> str:
        def excerpt(path, limit: int = 6000) -> str:
            return truncate_text(read_text(path), max_chars=limit) if path.exists() else "(absent)"

        def goal(limit: int = 3000) -> str:
            # Not `excerpt`: that takes a prefix, and a goal can carry the question
            # behind however much preamble the caller prepended to it.
            path = paths.user_input
            return goal_excerpt(read_text(path), max_chars=limit) if path.exists() else "(absent)"

        return (
            "# Adversarial Validity Review\n\n"
            f"You are reviewing {stage.stage_title} of an automated research run.\n\n"
            "**Your job is to explain why this result is wrong.** Assume it is an artifact and "
            "find the mechanism. You are not assessing completeness, effort, writing quality or "
            "presentation — another reviewer does that, and duplicating it wastes this pass.\n\n"
            "You cannot approve, reject, or edit anything. You produce objections; the next "
            "stage has to answer them.\n\n"
            "## What to look for\n\n"
            "- `confound` — something other than the intervention explains the difference.\n"
            "- `weak_baseline` — the comparison was not given a fair chance. Check the tuning "
            "budgets declared in the experimental protocol against what the run actually did.\n"
            "- `insufficient_replication` — the effect cannot be separated from run-to-run "
            "variance at the reported seed count.\n"
            "- `leakage` — test information reached training, tuning, or model selection.\n"
            "- `metric_cherry_picking` — the reported metric is not the preregistered primary "
            "one, or a metric appeared after the results did.\n"
            "- `effect_within_noise` — the gap is smaller than the spread.\n"
            "- `overclaim` — the conclusion is stronger than the measurement supports.\n"
            "- `unsupported_generalization` — a claim about a population that was not sampled.\n"
            "- `missing_ablation` — the mechanism is asserted but not isolated.\n"
            "- `irreproducible_procedure` — a step exists only in prose, not in code.\n\n"
            "## Discipline\n\n"
            "- Every finding must be **specific and checkable**. \"The evaluation could be more "
            "rigorous\" is not a finding. \"Both conditions were tuned on the same split that "
            "reports the headline number\" is.\n"
            "- Cite the artifact you read. If you cannot point at something in the run, you are "
            "speculating, and speculation crowds out the real objections.\n"
            "- Raising nothing is a legitimate outcome. Do not pad the list; a fabricated "
            "objection costs the next stage a real answer.\n"
            "- Rank by how much the conclusion moves if you are right, not by how easy the fix is.\n\n"
            "## Output\n\n"
            "Return JSON only, no prose outside the object:\n\n"
            "```json\n"
            '{"findings": [{"id": "V1", "category": "<one of the categories above>", '
            '"severity": "critical|major|minor", "finding": "...", "why_it_matters": "...", '
            '"what_would_settle_it": "..."}]}\n'
            "```\n\n"
            "# Original Goal\n\n"
            f"{goal(3000)}\n\n"
            "# Preregistered Hypotheses\n\n"
            f"{excerpt(paths.preregistration)}\n\n"
            "# Experimental Protocol\n\n"
            f"{excerpt(paths.experimental_protocol)}\n\n"
            "# Hypothesis Outcomes\n\n"
            f"{excerpt(paths.hypothesis_outcomes)}\n\n"
            "# Experiment Manifest\n\n"
            f"{excerpt(paths.experiment_manifest)}\n\n"
            "# Artifact Index\n\n"
            f"{excerpt(paths.artifact_index, 4000)}\n\n"
            "# Stage Summary Under Review\n\n"
            f"{truncate_text(stage_markdown, max_chars=16000)}\n\n"
            f"The run directory is `{paths.run_root.resolve()}`. Read whatever you need from it.\n"
        )
