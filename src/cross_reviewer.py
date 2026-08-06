"""An independent second opinion on an approval, from a different model family.

The approval gate in :mod:`src.approval_agent` is strong — it runs a coding agent with
tools, so it can re-read a paper and re-execute an analysis before judging. But it is the
same model family as the executor, usually the same model. Opus judging opus shares the
blind spots that produced the work, and a shared blind spot is exactly what a review is
supposed to catch.

This adds a **cross-family veto**. When the primary reviewer approves, a Gemini reviewer
reads the same evidence and answers one question: is this approval defensible? A refusal
sends the stage back for refinement; an agreement lets it through.

The asymmetry is deliberate, in both directions:

* **It only audits approvals.** A refusal from the primary already sends the stage back,
  so a second opinion on it would change nothing and cost a call.
* **It cannot approve anything the primary refused.** It is a veto, never an override, so
  adding it can only make the gate stricter. That is what makes it safe to enable by
  default when a Gemini backend is configured.

The Gemini reviewer has no filesystem and cannot re-run an analysis, so it is a
*documentary* check: it judges the record — the stage summary, the manifests, and the
primary's stated reasoning — for internal inconsistency, claims the artifacts do not
support, and approvals whose reasoning does not actually address what was asked. It is
weaker than the primary at verification and independent of it at judgement, which is the
combination worth having.

A cross-model refusal is recorded as a standing rule by :mod:`src.review_policy`, so a
blind spot caught once is checked on every stage afterwards.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .utils import RunPaths, StageSpec, read_text, truncate_text
from .web_search import SearchBackend, build_genai_client, resolve_backend


#: Deliberately not the default search model: a reviewer should be at least as capable as
#: the thing it audits, and this one is auditing frontier-model output.
DEFAULT_CROSS_REVIEW_MODEL = "gemini-3.1-pro-preview"

#: A verdict must justify itself. Below this the refusal is not actionable and is ignored
#: rather than bouncing a stage on a shrug.
MIN_REASON_CHARS = 40


@dataclass(frozen=True)
class CrossVerdict:
    agrees: bool
    reason: str = ""
    raw_response: str = ""
    model: str = ""
    #: True when the check could not be performed at all, as opposed to performed and
    #: passed. The two must never be conflated: an unavailable auditor is not agreement.
    unavailable: bool = False

    @property
    def vetoes(self) -> bool:
        return not self.agrees and not self.unavailable


class GeminiCrossReviewer:
    """Second-opinion reviewer backed by Gemini, on Vertex AI or the Developer API."""

    def __init__(self, model: str | None = None, backend: SearchBackend | None = None) -> None:
        self.requested_model = model or DEFAULT_CROSS_REVIEW_MODEL
        self._backend = backend

    def backend(self) -> SearchBackend | None:
        if self._backend is None:
            self._backend = resolve_backend(self.requested_model)
        return self._backend

    def available(self) -> bool:
        return self.backend() is not None

    def audit(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        stage_markdown: str,
        primary_reason: str,
        primary_model: str,
    ) -> CrossVerdict:
        backend = self.backend()
        if backend is None:
            return CrossVerdict(
                agrees=True,
                unavailable=True,
                reason="No Gemini backend configured; cross-model review was skipped.",
            )

        prompt = self.build_prompt(
            paths=paths,
            stage=stage,
            stage_markdown=stage_markdown,
            primary_reason=primary_reason,
            primary_model=primary_model,
        )

        try:
            client = build_genai_client(backend)
            response = client.models.generate_content(model=backend.model, contents=prompt)
            raw = (getattr(response, "text", "") or "").strip()
        except Exception as exc:  # noqa: BLE001 - an auditor that errored has not agreed
            return CrossVerdict(
                agrees=True,
                unavailable=True,
                reason=f"Cross-model review could not run: {exc}",
                model=backend.model,
            )

        return self.parse(raw, model=backend.model)

    @staticmethod
    def parse(raw_response: str, *, model: str = "") -> CrossVerdict:
        payload = _extract_json_object(raw_response)
        if payload is None:
            # An unparseable auditor is an auditor that did not run. Treating it as a veto
            # would let a formatting failure bounce good work; treating it as agreement
            # would launder silence into approval, so it is marked unavailable.
            return CrossVerdict(
                agrees=True,
                unavailable=True,
                reason="Cross-model reviewer did not return valid JSON.",
                raw_response=raw_response,
                model=model,
            )

        verdict = str(payload.get("verdict") or "").strip().lower()
        reason = " ".join(str(payload.get("reason") or "").split())
        agrees = verdict not in {"refuse", "reject", "disagree", "block", "veto"}

        if not agrees and len(reason) < MIN_REASON_CHARS:
            return CrossVerdict(
                agrees=True,
                reason=f"Cross-model refusal ignored: no substantive reason given ({reason!r}).",
                raw_response=raw_response,
                model=model,
            )

        return CrossVerdict(agrees=agrees, reason=reason, raw_response=raw_response, model=model)

    def build_prompt(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        stage_markdown: str,
        primary_reason: str,
        primary_model: str,
    ) -> str:
        return (
            "# Cross-Model Review Audit\n\n"
            f"A reviewer running {primary_model or 'another model'} has just APPROVED "
            f"{stage.stage_title} of an automated research run. You are a reviewer from a "
            "different model family. Your job is not to redo the review — it is to decide "
            "whether this approval is defensible on the evidence given.\n\n"
            "You are the independent check on a system where the author, the executor and "
            "the first reviewer are all the same model family. Look for what that "
            "arrangement would miss.\n\n"
            "## What to look for\n"
            "- Claims in the stage summary that its own reported artifacts do not support.\n"
            "- Numbers, citations or results that appear without a stated source or method.\n"
            "- Internal contradictions between sections.\n"
            "- An approval whose stated reasoning does not actually address the stage's "
            "objective, or which praises effort rather than evidence.\n"
            "- Work that reads as complete but has not established anything checkable.\n\n"
            "## What not to do\n"
            "- Do not refuse over style, length, formatting, or wishing for more work.\n"
            "- Do not refuse because you cannot personally verify a file. You have no "
            "filesystem; absence of your own verification is not evidence of a problem.\n"
            "- The sections below are an excerpt, not the run. A section marked as not "
            "included is a limit of this packet, and says nothing about whether the "
            "underlying artifact exists. Never treat it as evidence of a missing file, and "
            "never infer from it that the approving reviewer fabricated anything.\n"
            "- Do not demand final-paper quality from an early stage.\n"
            "- Refuse only if approving would let a real defect through.\n\n"
            "Return JSON only, no prose outside it:\n"
            '{"verdict":"agree|refuse","reason":"..."}\n\n'
            "`reason` is required when refusing and must name the specific defect, "
            "concretely enough that the next attempt can fix it.\n\n"
            f"## The Approving Reviewer's Stated Reasoning\n\n{truncate_text(primary_reason or '(none given)', max_chars=6000)}\n\n"
            f"## Stage Summary Under Review\n\n{truncate_text(stage_markdown, max_chars=24000)}\n\n"
            f"## Original Research Goal\n\n{truncate_text(read_text(paths.user_input), max_chars=4000)}\n\n"
            f"## Artifact Index\n\n{_excerpt(paths.artifact_index, 6000)}\n\n"
            f"## Experiment Manifest\n\n{_excerpt(paths.experiment_manifest, 4000)}\n"
        )


#: Shown when a section could not be included. Worded so it cannot be read as evidence
#: that the underlying artifact is absent — a distinction the auditor got wrong in testing,
#: vetoing sound work because a section of its own prompt was empty.
NOT_INCLUDED = "(not included in this audit packet — draw no conclusion from its absence)"


def _excerpt(path, max_chars: int) -> str:
    try:
        if not path.exists():
            return NOT_INCLUDED
    except OSError:
        return NOT_INCLUDED
    text = read_text(path).strip()
    return truncate_text(text, max_chars=max_chars) if text else NOT_INCLUDED


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    candidate = (raw or "").strip()
    if not candidate:
        return None

    for text in (
        candidate,
        *(m.group(1) for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL)),
        *(m.group(1) for m in re.finditer(r"(\{.*\})", candidate, re.DOTALL)),
    ):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def resolve_cross_reviewer(mode: str, model: str | None = None) -> "GeminiCrossReviewer | None":
    """Build the cross reviewer for a CLI mode, or None to leave the gate single-opinion."""
    if mode == "off":
        return None
    reviewer = GeminiCrossReviewer(model=model)
    if mode == "auto" and not reviewer.available():
        return None
    return reviewer
