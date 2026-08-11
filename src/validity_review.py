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
from dataclasses import dataclass
from datetime import datetime

from .approval_agent import extract_json_payload
from .terminal_ui import TerminalUI
from .utils import (
    RunPaths,
    StageSpec,
    append_jsonl,
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


def load_findings(paths: RunPaths, stage_slug: str) -> list[ValidityFinding]:
    payload = _load_json(validity_review_path(paths, stage_slug))
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

    findings = load_findings(paths, reviewed)
    if not findings:
        # No review ran, or it found nothing. Either way there is nothing owed.
        return []

    response_path = validity_response_path(paths, reviewed)
    payload = _load_json(response_path)
    if payload is None:
        return [
            f"requires {response_path.name} under workspace/reviews answering each of the "
            f"{len(findings)} validity findings raised against {reviewed}. A finding nobody "
            "responded to is indistinguishable from one nobody raised."
        ]
    if not isinstance(payload, dict):
        return [f"{response_path.name} must contain a JSON object."]

    responses = payload.get("responses")
    if not isinstance(responses, list):
        return [f"{response_path.name} must contain a responses list."]

    by_id: dict[str, dict] = {}
    for entry in responses:
        if isinstance(entry, dict):
            identifier = str(entry.get("id") or "").strip()
            if identifier:
                by_id[identifier] = entry

    problems: list[str] = []
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
    panel_dir = paths.reviews_dir / "panel"
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

    def __init__(self, operator, *, ui: TerminalUI | None = None) -> None:
        self._operator = operator
        self.ui = ui or TerminalUI()

    @property
    def fake_mode(self) -> bool:
        return bool(getattr(self._operator, "fake_mode", False))

    def review(self, *, paths: RunPaths, stage: StageSpec, stage_markdown: str) -> list[ValidityFinding]:
        if stage.number not in REVIEWED_STAGE_NUMBERS:
            return []

        # If a panel already deliberated over this stage, its surviving concerns
        # are the findings. Running a second critic would ask the Methodologist's
        # questions twice and pay for both.
        from_panel = findings_from_panel(paths, stage)
        if from_panel:
            self._write_review(
                paths, stage, from_panel, note="carried from the review panel's final round"
            )
            return from_panel

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
            return findings

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
                }
            },
        )
        exit_code, stdout_text, stderr_text, _observed, _meta = self._operator._run_streaming_command(  # noqa: SLF001
            command=command,
            cwd=invocation_cwd,
            stage=stage,
            attempt_no=1,
            paths=paths,
            mode="validity_review",
            stdin_text=stdin_text,
        )
        if exit_code != 0:
            # A red-team pass that did not run is recorded as not having run.
            # Writing an empty finding list would read as "nothing wrong".
            self._write_review(
                paths,
                stage,
                [],
                note=f"the validity reviewer failed with exit code {exit_code} and raised nothing",
                failed=True,
            )
            return []

        findings = self._parse(stdout_text)
        self._write_review(paths, stage, findings)
        return findings

    def _write_review(
        self,
        paths: RunPaths,
        stage: StageSpec,
        findings: list[ValidityFinding],
        *,
        note: str = "",
        failed: bool = False,
    ) -> None:
        payload = {
            "generated_at": _now(),
            "reviewed_stage": stage.slug,
            "reviewer_failed": failed,
            "note": note,
            "findings": [item.to_dict() for item in findings],
        }
        write_text(
            validity_review_path(paths, stage.slug),
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        )

    def _parse(self, raw: str) -> list[ValidityFinding]:
        payload = self._extract_json(raw)
        if not isinstance(payload, dict):
            return []
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
        as neither -- and this parser's failure is silent, because :meth:`_parse` returns an
        empty list either way. The run then records that the validity reviewer attacked the
        stage and raised nothing, which is the opposite of what happened.
        """
        return extract_json_payload(raw, verdict_key="findings")

    def _build_prompt(self, *, paths: RunPaths, stage: StageSpec, stage_markdown: str) -> str:
        def excerpt(path, limit: int = 6000) -> str:
            return truncate_text(read_text(path), max_chars=limit) if path.exists() else "(absent)"

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
            f"{excerpt(paths.user_input, 3000)}\n\n"
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
