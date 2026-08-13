"""Freeze the hypotheses before the experiments, and hold the analysis to them.

The failure this exists to prevent is the dominant one in automated science:
the hypothesis quietly becomes whatever the results support. It leaves no
trace. The manuscript reads well, every artifact gate passes, and the claim was
chosen after seeing the data.

AutoR already produced ``hypothesis_manifest.json`` at Stage 02, but nothing
downstream ever wrote to it — the ``status`` field on every entry was whatever
Stage 02 declared before a single experiment had run, and no artifact connected
Stage 06's conclusions back to H1..Hn. This module closes that loop:

1. **Freeze.** When Stage 04 is approved — design done, implementation done, no
   results yet — the hypothesis set and its decision rules are written to
   ``workspace/notes/preregistration.json`` and hashed.
2. **Adjudicate.** Stage 06 must emit ``workspace/results/hypothesis_outcomes.json``
   giving every frozen empirical hypothesis a verdict and pointing at the
   result artifact that decides it.
3. **Trace.** Stage 07 must emit ``workspace/artifacts/claim_provenance.json``
   mapping each paper claim to a supported hypothesis, or marking it
   exploratory.

Changing the hypotheses after the freeze is allowed — a rollback to Stage 02 is
a legitimate reason — but only as a recorded amendment. An unrecorded change is
a validation error, because the difference between "we revised our hypothesis
and said so" and "we revised our hypothesis" is the whole of the thing.

That last sentence only holds if the frozen file can be checked against
something the stage under suspicion did not write. It cannot check itself:
``preregistration.json`` sits in ``workspace/notes/`` with every other artifact
the agent owns, and :func:`format_preregistration_for_prompt` renders its
``digest`` into the prompt, so the one field that would prove the bytes were
not rewritten is shown to the party that would rewrite them, in the format it
would have to produce. So AutoR keeps its own copy of the record at
:func:`preregistration_stamp_path`, outside ``workspace/``, and
:func:`preregistration_tamper_findings` runs three comparisons rather than one:
the hypotheses against the digest the file states for them, that digest against
the stamped one, and the length of the amendment ledger against the stamped
ledger. Each catches a rewrite the other two do not — an edited statement, an
edited statement with the header recomputed, and a deleted amendment row.

Deleting the frozen file is not a way around them. :func:`freeze_preregistration`
restores the stamped record when the workspace copy is missing or disagrees,
rather than deriving a fresh one from the current manifest, so a re-freeze
cannot manufacture a post-results ``frozen_at`` and an empty ledger.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .utils import RunPaths


#: A verdict has to be one of these. "It's complicated" is `inconclusive`, which
#: is a real scientific outcome; leaving the verdict off is not.
VERDICTS = ("supported", "refuted", "inconclusive", "not_tested")

#: Only empirical hypotheses (H*) are adjudicated. Theoretical propositions (T*)
#: are not experiments, and paper claims (C*) are adjudicated at Stage 07
#: through claim provenance instead.
ADJUDICATED_TYPE = "empirical"

CLAIM_STATUSES = ("confirmatory", "exploratory")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _digest(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


# ----------------------------------------------------------------------------
# Freezing
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class PreregHypothesis:
    identifier: str
    claim_type: str
    statement: str
    decision_rule: str
    verification: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.identifier,
            "type": self.claim_type,
            "statement": self.statement,
            "decision_rule": self.decision_rule,
            "verification": self.verification,
        }


@dataclass(frozen=True)
class Preregistration:
    frozen_at: str
    frozen_before_stage: str
    source_digest: str
    digest: str
    hypotheses: list[PreregHypothesis]
    amendments: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "frozen_at": self.frozen_at,
            "frozen_before_stage": self.frozen_before_stage,
            "source_digest": self.source_digest,
            "digest": self.digest,
            "hypotheses": [item.to_dict() for item in self.hypotheses],
            "amendments": [dict(item) for item in self.amendments],
        }

    @property
    def adjudicated_ids(self) -> list[str]:
        return [
            item.identifier
            for item in self.hypotheses
            if item.claim_type == ADJUDICATED_TYPE
        ]


def hypothesis_manifest_digest(paths: RunPaths) -> str:
    """Hash the parts of the hypothesis manifest a preregistration commits to.

    Deliberately excludes ``generated_at`` and the self-declared ``status``:
    rewriting Stage 02 with no change to any statement is not tampering, and a
    timestamp is not a hypothesis.
    """
    payload = _load_json(paths.hypothesis_manifest)
    if not isinstance(payload, dict):
        return ""
    committed = []
    for section in ("theoretical_propositions", "empirical_hypotheses", "paper_claims"):
        for entry in payload.get(section, []):
            if not isinstance(entry, dict):
                continue
            committed.append(
                {
                    "id": str(entry.get("id") or "").strip(),
                    "type": str(entry.get("type") or "").strip(),
                    "statement": str(entry.get("statement") or "").strip(),
                    "decision_rule": str(entry.get("decision_rule") or "").strip(),
                }
            )
    return _digest(committed)


def _preregistration_from_payload(payload: object) -> Preregistration | None:
    """One reader for the two places a frozen record is stored.

    The workspace copy and the stamp hold the same shape, and a second parser
    for the second copy would be a second answer to "what did this run freeze".
    """
    if not isinstance(payload, dict):
        return None
    hypotheses = [
        PreregHypothesis(
            identifier=str(item.get("id") or "").strip(),
            claim_type=str(item.get("type") or "").strip(),
            statement=str(item.get("statement") or "").strip(),
            decision_rule=str(item.get("decision_rule") or "").strip(),
            verification=str(item.get("verification") or "").strip(),
        )
        for item in payload.get("hypotheses", [])
        if isinstance(item, dict)
    ]
    return Preregistration(
        frozen_at=str(payload.get("frozen_at") or ""),
        frozen_before_stage=str(payload.get("frozen_before_stage") or ""),
        source_digest=str(payload.get("source_digest") or ""),
        digest=str(payload.get("digest") or ""),
        hypotheses=hypotheses,
        amendments=[dict(item) for item in payload.get("amendments", []) if isinstance(item, dict)],
    )


def load_preregistration(paths: RunPaths) -> Preregistration | None:
    return _preregistration_from_payload(_load_json(paths.preregistration))


def _write_preregistration(paths: RunPaths, prereg: Preregistration) -> None:
    paths.preregistration.parent.mkdir(parents=True, exist_ok=True)
    paths.preregistration.write_text(
        json.dumps(prereg.to_dict(), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


# ----------------------------------------------------------------------------
# AutoR's own copy of the record
# ----------------------------------------------------------------------------


def preregistration_stamp_path(paths: RunPaths) -> Path:
    """The frozen record as AutoR wrote it, outside the tree the stage works in.

    ``report_plan_stamp.json`` is the precedent and the reason carries over: a
    stamp kept only in ``workspace/notes/`` is a receipt the payer prints. The
    preregistration is the worse case of the two, because
    :func:`format_preregistration_for_prompt` renders ``digest`` into the
    prompt — the field that is supposed to prove the file was not rewritten is
    handed to the party that would rewrite it, in the format it would have to
    produce.

    The claim is not that this store cannot be reached. It is that a rewrite of
    the frozen set now has to be a matching rewrite of two files in two trees:
    this one is outside the directory every stage prompt names, no template
    mentions it, and nothing renders it into a prompt.
    """
    return paths.run_root / "preregistration_stamp.json"


def recorded_preregistration_stamp(paths: RunPaths) -> Preregistration | None:
    """The stamped record, or None when AutoR has never stamped this run.

    None is neither a pass nor a failure. It is the state of a run resumed from
    an AutoR that predates the stamp, and refusing that would fail a run for a
    reason the run cannot fix. The self-consistency comparison in
    :func:`preregistration_tamper_findings` needs no stamp and still runs; the
    two that need one are skipped, and the next :func:`freeze_preregistration`
    adopts the file as it stands.
    """
    stamped = _preregistration_from_payload(_load_json(preregistration_stamp_path(paths)))
    if stamped is None or not stamped.digest or not stamped.hypotheses:
        return None
    return stamped


def recorded_preregistration_repairs(paths: RunPaths) -> list[dict[str, str]]:
    """Every time AutoR had to put its copy back, and what disagreed.

    Kept because the repair is what destroys the evidence: once the stamped
    record is written over the workspace copy the two agree again, and without
    this the run's own artifacts would say the frozen set was never touched.
    """
    payload = _load_json(preregistration_stamp_path(paths))
    if not isinstance(payload, dict):
        return []
    return [dict(item) for item in payload.get("repairs", []) if isinstance(item, dict)]


def _write_preregistration_stamp(
    paths: RunPaths,
    prereg: Preregistration,
    repairs: list[dict[str, str]] | None = None,
) -> None:
    path = preregistration_stamp_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = prereg.to_dict()
    payload["repairs"] = [
        dict(item)
        for item in (recorded_preregistration_repairs(paths) if repairs is None else repairs)
    ]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _self_digest(prereg: Preregistration) -> str:
    """The digest the hypotheses in hand actually have, however they got there."""
    return _digest([item.to_dict() for item in prereg.hypotheses])


def _tamper_findings(
    prereg: Preregistration | None, stamped: Preregistration | None
) -> list[str]:
    """The three comparisons, one sentence each, no recovery advice.

    Split from :func:`preregistration_tamper_problems` so the router's edge
    reason and the stage gate's refusal cannot drift into two accounts of one
    disagreement. ``stamped is None`` leaves only the first comparison, which is
    the one that needs nothing outside the file.
    """
    if prereg is None:
        return []

    findings: list[str] = []
    recomputed = _self_digest(prereg)
    if recomputed != prereg.digest:
        findings.append(
            f"preregistration.json states digest {prereg.digest[:12] or '(none)'}, but the "
            f"hypotheses in it hash to {recomputed[:12]}. The frozen set on disk is not the "
            "set the file says was frozen."
        )
    if stamped is None:
        return findings

    if prereg.digest != stamped.digest:
        findings.append(
            f"preregistration.json states digest {prereg.digest[:12] or '(none)'}; AutoR froze "
            f"{stamped.digest[:12]}. The hypothesis set was replaced after the freeze."
        )
    if len(prereg.amendments) != len(stamped.amendments):
        findings.append(
            f"preregistration.json records {len(prereg.amendments)} amendment(s); AutoR "
            f"recorded {len(stamped.amendments)}. The ledger of what changed has itself changed."
        )
    return findings


#: Named by every tamper refusal, and deliberately not ``amend_preregistration``.
#: That function re-freezes only when the *manifest* digest has moved; when the
#: manifest is untouched it returns the existing record unchanged, so pointing a
#: rewritten file at it would name a step that cannot clear the refusal. A
#: refusal nothing clears leaves deleting the file as the cheapest move left,
#: which is the escape these comparisons exist to close.
PREREGISTRATION_RECOVERY = (
    "Leave the file alone: AutoR writes its own copy back over it before the next attempt, "
    "and deleting it restores that same copy rather than freezing a new one. If the "
    "hypotheses genuinely have to change, that is a rollback to Stage 02 — rewriting the "
    "manifest there records an amendment carrying the superseded digest."
)


def preregistration_tamper_findings(paths: RunPaths) -> list[str]:
    """What disagrees between the frozen file, its own digest and AutoR's copy."""
    return _tamper_findings(
        load_preregistration(paths), recorded_preregistration_stamp(paths)
    )


def preregistration_tamper_problems(paths: RunPaths) -> list[str]:
    """The findings a stage gate reports, each carrying the step that clears it."""
    return [
        f"{finding} {PREREGISTRATION_RECOVERY}"
        for finding in preregistration_tamper_findings(paths)
    ]


def _derive_preregistration(
    paths: RunPaths, before_stage: str
) -> Preregistration | None:
    """Build the record the current hypothesis manifest implies. Writes nothing.

    Separated from :func:`freeze_preregistration` because the two callers want
    different things from a manifest read: the freeze wants it only when AutoR
    has never stamped this run, while :func:`amend_preregistration` wants it
    precisely when the stamp exists and the manifest has legitimately moved.
    """
    manifest = _load_json(paths.hypothesis_manifest)
    if not isinstance(manifest, dict):
        return None

    hypotheses: list[PreregHypothesis] = []
    for section, claim_type in (
        ("theoretical_propositions", "theoretical"),
        ("empirical_hypotheses", "empirical"),
        ("paper_claims", "paper_claim"),
    ):
        for entry in manifest.get(section, []):
            if not isinstance(entry, dict):
                continue
            identifier = str(entry.get("id") or "").strip()
            statement = str(entry.get("statement") or "").strip()
            if not identifier or not statement:
                continue
            hypotheses.append(
                PreregHypothesis(
                    identifier=identifier,
                    claim_type=claim_type,
                    statement=statement,
                    decision_rule=str(entry.get("decision_rule") or "").strip(),
                    verification=str(entry.get("verification_needed") or "").strip(),
                )
            )

    if not hypotheses:
        return None

    return Preregistration(
        frozen_at=_now(),
        frozen_before_stage=before_stage,
        source_digest=hypothesis_manifest_digest(paths),
        digest=_digest([item.to_dict() for item in hypotheses]),
        hypotheses=hypotheses,
    )


def freeze_preregistration(
    paths: RunPaths,
    *,
    before_stage: str = "05_experimentation",
) -> Preregistration | None:
    """Fix the hypothesis set once, and hold that one record for the whole run.

    Called on Stage 04 approval and again before every attempt from Stage 05 on,
    so this is also the hook that repairs the frozen file. Three states:

    * **AutoR has stamped this run.** The stamp is the record. A workspace copy
      that disagrees with it — edited, truncated, or deleted outright — is
      written over with the stamped one, and the disagreement is appended to
      :func:`recorded_preregistration_repairs`. Deriving a fresh freeze here
      instead is what made deletion the cheapest escape from a tamper refusal:
      the re-freeze took the current manifest, dated itself after the results
      existed, and started an empty amendment ledger, and every downstream
      validator passed.
    * **No stamp, but a frozen file.** A run that froze before this stamp
      existed. Adopt the file as it stands: refusing it would fail a run for a
      reason the run cannot fix.
    * **Neither.** The first freeze. Derive from the manifest and write both.

    The set is never re-derived once stamped. A legitimate later change goes
    through :func:`amend_preregistration`, which keeps the superseded digest.
    """
    stamped = recorded_preregistration_stamp(paths)
    existing = load_preregistration(paths)

    if stamped is not None:
        disagreements = (
            ["preregistration.json is gone; AutoR still holds the record it froze."]
            if existing is None
            else _tamper_findings(existing, stamped)
        )
        if not disagreements:
            return existing
        _write_preregistration(paths, stamped)
        _write_preregistration_stamp(
            paths,
            stamped,
            repairs=[
                *recorded_preregistration_repairs(paths),
                {"repaired_at": _now(), "found": " ".join(disagreements)},
            ],
        )
        return stamped

    if existing is not None:
        _write_preregistration_stamp(paths, existing)
        return existing

    derived = _derive_preregistration(paths, before_stage)
    if derived is None:
        return None
    _write_preregistration(paths, derived)
    _write_preregistration_stamp(paths, derived)
    return derived


def amend_preregistration(paths: RunPaths, reason: str) -> Preregistration | None:
    """Re-freeze against the current hypothesis manifest, keeping the history.

    Called when the run legitimately revisits Stage 02 — a rollback, or a
    reviewer sending the hypotheses back. The amendment is what makes the
    change honest: the record says the hypotheses moved, when, and why.

    The record being amended is read from the stamp when there is one, not from
    the workspace copy. Otherwise a rewritten ``preregistration.json`` would
    supply its own ``source_digest`` to the comparison below, and a Stage 02
    re-run would launder the rewrite into the amendment as though AutoR had
    frozen it.
    """
    existing = recorded_preregistration_stamp(paths) or load_preregistration(paths)
    if existing is None:
        return freeze_preregistration(paths)

    current_source = hypothesis_manifest_digest(paths)
    if current_source == existing.source_digest:
        return existing

    refrozen = _derive_preregistration(paths, existing.frozen_before_stage)
    if refrozen is None:
        _write_preregistration(paths, existing)
        _write_preregistration_stamp(paths, existing)
        return existing

    amended = Preregistration(
        frozen_at=refrozen.frozen_at,
        frozen_before_stage=refrozen.frozen_before_stage,
        source_digest=refrozen.source_digest,
        digest=refrozen.digest,
        hypotheses=refrozen.hypotheses,
        amendments=[
            *existing.amendments,
            {
                "recorded_at": _now(),
                "reason": reason,
                "previous_digest": existing.digest,
                "previous_source_digest": existing.source_digest,
                "new_digest": refrozen.digest,
            },
        ],
    )
    _write_preregistration(paths, amended)
    _write_preregistration_stamp(paths, amended)
    return amended


# ----------------------------------------------------------------------------
# Adjudication
# ----------------------------------------------------------------------------


def validate_preregistration(paths: RunPaths) -> list[str]:
    """Checks that run from Stage 05 on, once the hypotheses should be frozen."""
    prereg = load_preregistration(paths)
    if prereg is None:
        stamped = recorded_preregistration_stamp(paths)
        if stamped is not None:
            # Not "never frozen" — AutoR froze this run and still holds the
            # record, so the message that fits a run which never preregistered
            # would be a false description of the state on disk and would point
            # at a Stage 04 approval that already happened.
            return [
                "is missing workspace/notes/preregistration.json. AutoR froze "
                f"{len(stamped.adjudicated_ids)} empirical hypothesis(es) at {stamped.frozen_at} "
                f"with digest {stamped.digest[:12]} and still holds that record. "
                f"{PREREGISTRATION_RECOVERY}"
            ]
        if not paths.hypothesis_manifest.exists():
            # The usual cause is a `--project-root` run that carried Stage 02
            # forward from an existing codebase without deriving hypotheses
            # from it. Adopting someone else's code does not adopt a research
            # question, and a run that reaches experimentation with nothing
            # falsifiable on record cannot produce a negative result.
            return [
                "has no hypotheses on record. Write workspace/notes/hypothesis_manifest.json "
                "in the Stage 02 format — typed T/H/C entries, each empirical hypothesis "
                "carrying a decision rule — before running experiments. A run with no "
                "falsifiable hypothesis cannot come out negative, so it cannot come out right."
            ]
        return [
            "requires a frozen preregistration at workspace/notes/preregistration.json. "
            "It is written automatically when Stage 04 is approved; its absence means the "
            "hypothesis set was never fixed before results existed."
        ]

    problems: list[str] = []
    if not prereg.adjudicated_ids:
        problems.append(
            "preregistration.json contains no empirical hypotheses. An experiment stage "
            "with nothing falsifiable to test has no way to come out negative."
        )
    for item in prereg.hypotheses:
        if item.claim_type != ADJUDICATED_TYPE:
            continue
        if not item.decision_rule:
            problems.append(
                f"preregistration.json hypothesis {item.identifier} has no decision rule. "
                "State in Stage 02, as `- Decision rule: ...`, what result would count as "
                "support and what would count as refutation."
            )

    # Against itself and against AutoR's copy, before against its source. A
    # record that does not describe its own bytes is not evidence about the
    # manifest it was taken from.
    problems.extend(preregistration_tamper_problems(paths))

    current_source = hypothesis_manifest_digest(paths)
    if not current_source:
        # `_derive_preregistration` returns None without a parseable manifest,
        # so a frozen record proves one existed. Its absence now is the source
        # being removed after the fact — and the falsy digest used to skip the
        # comparison below rather than fail it, which made deleting the manifest
        # the way to make a manifest rewrite unprovable.
        problems.append(
            "workspace/notes/hypothesis_manifest.json is gone, and the preregistration was "
            "frozen from it. Restore the Stage 02 manifest: with no source on record there is "
            "nothing the frozen set can be compared against, and a comparison that is skipped "
            "when its input is missing is not a check."
        )
    elif current_source != prereg.source_digest:
        problems.append(
            "the hypothesis manifest changed after preregistration and no amendment was "
            "recorded. Hypotheses may be revised, but the revision has to be on the record — "
            "otherwise there is no way to tell a revised hypothesis from one written to fit "
            "the results."
        )
    return problems


@dataclass(frozen=True)
class HypothesisOutcome:
    identifier: str
    verdict: str
    rationale: str
    evidence: list[str]


def load_hypothesis_outcomes(paths: RunPaths) -> list[HypothesisOutcome]:
    payload = _load_json(paths.hypothesis_outcomes)
    if not isinstance(payload, dict):
        return []
    outcomes: list[HypothesisOutcome] = []
    for entry in payload.get("outcomes", []):
        if not isinstance(entry, dict):
            continue
        outcomes.append(
            HypothesisOutcome(
                identifier=str(entry.get("id") or "").strip(),
                verdict=str(entry.get("verdict") or "").strip(),
                rationale=str(entry.get("rationale") or "").strip(),
                evidence=[str(item).strip() for item in entry.get("evidence", []) if str(item).strip()],
            )
        )
    return outcomes


def supported_hypothesis_ids(paths: RunPaths) -> set[str]:
    return {
        outcome.identifier
        for outcome in load_hypothesis_outcomes(paths)
        if outcome.verdict == "supported"
    }


def _evidence_exists(paths: RunPaths, reference: str) -> bool:
    """Accept a workspace-relative or run-relative path that resolves to a file."""
    candidate = reference.lstrip("./")
    for base in (paths.workspace_root, paths.run_root):
        resolved = base / candidate
        if resolved.is_file():
            return True
    return False


def validate_hypothesis_outcomes(paths: RunPaths) -> list[str]:
    """Checks that run from Stage 06 on: every frozen hypothesis gets a verdict."""
    prereg = load_preregistration(paths)
    if prereg is None:
        return []

    payload = _load_json(paths.hypothesis_outcomes)
    if payload is None:
        return [
            "requires workspace/results/hypothesis_outcomes.json recording, for every "
            "preregistered hypothesis, whether the evidence supported it, refuted it, or "
            "was inconclusive."
        ]
    if not isinstance(payload, dict):
        return ["hypothesis_outcomes.json must contain a JSON object."]

    problems: list[str] = []

    recorded_digest = str(payload.get("preregistration_digest") or "").strip()
    if not recorded_digest:
        problems.append(
            "hypothesis_outcomes.json must record the preregistration_digest it adjudicates."
        )
    elif recorded_digest != prereg.digest:
        problems.append(
            "hypothesis_outcomes.json adjudicates a different hypothesis set than the frozen "
            f"preregistration ({recorded_digest[:12]} vs {prereg.digest[:12]})."
        )

    outcomes = load_hypothesis_outcomes(paths)
    seen: dict[str, int] = {}
    for outcome in outcomes:
        seen[outcome.identifier] = seen.get(outcome.identifier, 0) + 1

    expected = prereg.adjudicated_ids
    for identifier in expected:
        count = seen.get(identifier, 0)
        if count == 0:
            problems.append(
                f"hypothesis_outcomes.json has no verdict for preregistered hypothesis {identifier}. "
                "A hypothesis that was not tested is recorded as not_tested, not omitted."
            )
        elif count > 1:
            problems.append(f"hypothesis_outcomes.json has {count} verdicts for {identifier}.")

    known = set(expected)
    for outcome in outcomes:
        if outcome.identifier and outcome.identifier not in known:
            problems.append(
                f"hypothesis_outcomes.json adjudicates {outcome.identifier}, which is not a "
                "preregistered empirical hypothesis."
            )
            continue
        if outcome.verdict not in VERDICTS:
            problems.append(
                f"hypothesis_outcomes.json verdict for {outcome.identifier} is "
                f"{outcome.verdict!r}; expected one of {', '.join(VERDICTS)}."
            )
        if not outcome.rationale:
            problems.append(f"hypothesis_outcomes.json outcome {outcome.identifier} has no rationale.")
        if outcome.verdict in ("supported", "refuted"):
            if not outcome.evidence:
                problems.append(
                    f"hypothesis_outcomes.json records {outcome.identifier} as {outcome.verdict} "
                    "with no evidence. A verdict has to point at the artifact that decides it."
                )
            for reference in outcome.evidence:
                if not _evidence_exists(paths, reference):
                    problems.append(
                        f"hypothesis_outcomes.json cites `{reference}` for {outcome.identifier}, "
                        "but no such file exists in the run."
                    )
    return problems


# ----------------------------------------------------------------------------
# Claim provenance
# ----------------------------------------------------------------------------


def validate_claim_provenance(paths: RunPaths) -> list[str]:
    """Checks that run from Stage 07 on: the paper may only claim what it showed.

    A confirmatory claim has to name a preregistered hypothesis that came out
    supported. Anything else is exploratory — which is permitted and often the
    most interesting part of a run, but it has to be labelled, because a
    post-hoc finding presented as a confirmed prediction is the specific thing
    preregistration exists to prevent.
    """
    prereg = load_preregistration(paths)
    if prereg is None:
        return []

    payload = _load_json(paths.claim_provenance)
    if payload is None:
        return [
            "requires workspace/artifacts/claim_provenance.json mapping each claim the "
            "manuscript makes either to a supported preregistered hypothesis or to an "
            "explicitly exploratory finding."
        ]
    if not isinstance(payload, dict):
        return ["claim_provenance.json must contain a JSON object."]

    claims = payload.get("claims")
    if not isinstance(claims, list) or not claims:
        return ["claim_provenance.json must contain a non-empty claims list."]

    supported = supported_hypothesis_ids(paths)
    known = set(prereg.adjudicated_ids)
    problems: list[str] = []

    for index, entry in enumerate(claims, start=1):
        if not isinstance(entry, dict):
            problems.append(f"claim_provenance.json claim {index} must be an object.")
            continue
        text = str(entry.get("claim") or "").strip()
        status = str(entry.get("status") or "").strip()
        hypothesis_id = str(entry.get("hypothesis_id") or "").strip()
        evidence = [str(item).strip() for item in entry.get("evidence", []) if str(item).strip()]

        label = text[:60] or f"claim {index}"
        if not text:
            problems.append(f"claim_provenance.json claim {index} has no claim text.")
        if status not in CLAIM_STATUSES:
            problems.append(
                f"claim_provenance.json claim {label!r} has status {status!r}; "
                f"expected one of {', '.join(CLAIM_STATUSES)}."
            )
            continue

        if status == "confirmatory":
            if not hypothesis_id:
                problems.append(
                    f"claim_provenance.json claim {label!r} is confirmatory but names no "
                    "hypothesis. A confirmatory claim is one the run predicted in advance."
                )
            elif hypothesis_id not in known:
                problems.append(
                    f"claim_provenance.json claim {label!r} cites {hypothesis_id}, which was "
                    "not preregistered."
                )
            elif hypothesis_id not in supported:
                problems.append(
                    f"claim_provenance.json claim {label!r} is confirmatory on {hypothesis_id}, "
                    "whose verdict is not `supported`. Mark it exploratory, or change the claim."
                )
        if not evidence:
            problems.append(f"claim_provenance.json claim {label!r} cites no evidence.")
        else:
            for reference in evidence:
                if not _evidence_exists(paths, reference):
                    problems.append(
                        f"claim_provenance.json claim {label!r} cites `{reference}`, "
                        "but no such file exists in the run."
                    )
    return problems


# ----------------------------------------------------------------------------
# Prompt rendering
# ----------------------------------------------------------------------------


def format_preregistration_for_prompt(prereg: Preregistration) -> str:
    lines = [
        f"Frozen at: {prereg.frozen_at} (before {prereg.frozen_before_stage})",
        f"Digest: {prereg.digest}",
        "",
        "These hypotheses were fixed before any result existed. You may not edit, reword,",
        "narrow or drop them to fit what the experiments produced. If the evidence refutes",
        "one, record it as refuted — that is a result, not a failure. New ideas that came",
        "out of the data are exploratory findings and must be labelled as such.",
        "",
    ]
    for item in prereg.hypotheses:
        if item.claim_type != ADJUDICATED_TYPE:
            continue
        lines.append(f"- **{item.identifier}**: {item.statement}")
        if item.decision_rule:
            lines.append(f"  - Decision rule: {item.decision_rule}")
        if item.verification:
            lines.append(f"  - Verification: {item.verification}")
    if prereg.amendments:
        lines.append("")
        lines.append(f"Amendments on record: {len(prereg.amendments)}")
        for amendment in prereg.amendments:
            lines.append(f"  - {amendment.get('recorded_at', '')}: {amendment.get('reason', '')}")
    return "\n".join(lines)


def format_outcomes_for_prompt(paths: RunPaths) -> str:
    outcomes = load_hypothesis_outcomes(paths)
    if not outcomes:
        return ""
    lines = ["Adjudicated hypotheses (from Stage 06):"]
    for outcome in outcomes:
        lines.append(f"- {outcome.identifier}: **{outcome.verdict}** — {outcome.rationale}")
        for reference in outcome.evidence:
            lines.append(f"  - evidence: `{reference}`")
    lines.append("")
    lines.append(
        "Only a hypothesis with verdict `supported` may back a confirmatory claim in the "
        "manuscript. Everything else is exploratory and must say so."
    )
    return "\n".join(lines)
