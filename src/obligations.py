"""Obligations a reviewer carries forward when it approves a stage.

The approval gate learns from its refusals (:mod:`src.review_policy`), but most stages are
approved, and an approval discarded everything the reviewer noticed. That is where most of
the review actually lives. A real reviewer approving a literature survey says "fine, but
you owe me a power analysis at design time" — and then checks. Here the observation was
written into a log line and forgotten.

An approving reviewer can now attach **obligations**: specific things a later stage must
discharge. Each one is injected into the prompts of the stages it targets, and into the
review of those stages, so the reviewer that inherits an obligation is asked whether it was
met. An obligation that is neither discharged nor explicitly deferred is grounds to refuse.

That closes the other half of the loop:

    approval ──obligation──▶ later stage prompt ──▶ that stage's review ──▶ discharged
                                                              │
                                                     not met ─┴──▶ refusal

The design constraints that keep it honest:

* **Only the reviewer can discharge an obligation.** The stage that owes it cannot mark its
  own homework; it can only do the work and say so. Otherwise an executor under pressure
  closes its own debts.
* **Deferral is recorded, not silent.** A stage may push an obligation later, but the
  obligation stays open and its deferral count is visible, so "carried forward" cannot
  quietly mean "dropped".
* **Bounded and deduplicated**, like the review policy, so a reviewer repeating itself
  cannot manufacture the appearance of rigour.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .utils import STAGES, RunPaths, StageSpec


LEDGER_VERSION = 1

#: An obligation set has to stay readable inside a stage prompt.
MAX_OBLIGATIONS = 30

#: Below this an obligation is not checkable ("do better", "be careful").
MIN_OBLIGATION_CHARS = 20

OPEN, DISCHARGED = "open", "discharged"


@dataclass
class Obligation:
    obligation_id: str
    text: str
    origin_stage: str
    target_stage: str | None = None
    status: str = OPEN
    deferrals: int = 0
    discharged_by: str | None = None
    discharge_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def applies_to(self, stage: StageSpec) -> bool:
        """Whether *stage* is on the hook for this obligation.

        An untargeted obligation applies to every stage after the one that raised it, so a
        reviewer that does not name a stage still gets its point carried rather than lost.
        """
        if self.status != OPEN:
            return False
        if self.target_stage:
            return self.target_stage == stage.slug
        origin = _stage_number(self.origin_stage)
        return origin is not None and stage.number > origin


@dataclass
class ObligationLedger:
    version: int = LEDGER_VERSION
    obligations: list[Obligation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "obligations": [o.to_dict() for o in self.obligations]}

    @classmethod
    def from_dict(cls, payload: Any) -> "ObligationLedger":
        if not isinstance(payload, dict):
            return cls()
        items: list[Obligation] = []
        for entry in payload.get("obligations") or []:
            if not isinstance(entry, dict):
                continue
            text = str(entry.get("text") or "").strip()
            if not text:
                continue
            items.append(
                Obligation(
                    obligation_id=str(entry.get("obligation_id") or f"O{len(items) + 1:03d}"),
                    text=text,
                    origin_stage=str(entry.get("origin_stage") or "unknown"),
                    target_stage=(str(entry["target_stage"]) if entry.get("target_stage") else None),
                    status=str(entry.get("status") or OPEN),
                    deferrals=int(entry.get("deferrals") or 0),
                    discharged_by=(str(entry["discharged_by"]) if entry.get("discharged_by") else None),
                    discharge_note=str(entry.get("discharge_note") or ""),
                )
            )
        return cls(version=int(payload.get("version") or LEDGER_VERSION), obligations=items)

    def open_for(self, stage: StageSpec) -> list[Obligation]:
        return [o for o in self.obligations if o.applies_to(stage)]

    def by_id(self, obligation_id: str) -> Obligation | None:
        wanted = (obligation_id or "").strip().upper()
        return next((o for o in self.obligations if o.obligation_id.upper() == wanted), None)


def _stage_number(slug: str) -> int | None:
    for stage in STAGES:
        if stage.slug == slug:
            return stage.number
    match = re.match(r"^(\d+)", slug or "")
    return int(match.group(1)) if match else None


def normalize_stage_slug(value: str | None) -> str | None:
    """Resolve however a reviewer chose to name a stage.

    Accepts ``05``, ``5``, ``05_experimentation`` and the display name (``Study Design``,
    ``Stage 03: Study Design``). Live testing showed models reach for the display name, and
    silently degrading that to "any later stage" loses the targeting the reviewer intended.
    """
    if not value:
        return None
    normalized = re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())
    if not normalized:
        return None
    # "stage03" / "stage3": a bare prefix carries no information, so drop it and match the
    # number. Unlike the CLI's stage identifiers, leniency here is free — the alternative
    # is silently losing the targeting the reviewer asked for.
    bare = re.sub(r"^stage(?=\d)", "", normalized)
    for stage in STAGES:
        candidates = {
            re.sub(r"[^a-z0-9]+", "", stage.slug.lower()),
            str(stage.number),
            f"{stage.number:02d}",
            re.sub(r"[^a-z0-9]+", "", stage.display_name.lower()),
            re.sub(r"[^a-z0-9]+", "", stage.stage_title.lower()),
        }
        if normalized in candidates or bare in candidates:
            return stage.slug
    return None


def ledger_path(paths: RunPaths) -> Path:
    return paths.run_root / "obligations.json"


def load_ledger(paths: RunPaths) -> ObligationLedger:
    path = ledger_path(paths)
    if not path.exists():
        return ObligationLedger()
    try:
        return ObligationLedger.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return ObligationLedger()


def save_ledger(paths: RunPaths, ledger: ObligationLedger) -> Path:
    path = ledger_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _key(text: str) -> str:
    lowered = re.sub(r"\s+", " ", (text or "").strip().lower())
    return re.sub(r"[^a-z0-9 ]+", "", lowered).strip()


def record_obligations(
    paths: RunPaths,
    *,
    stage: StageSpec,
    entries: list[Any],
) -> list[Obligation]:
    """Record what an approving reviewer said a later stage still owes."""
    ledger = load_ledger(paths)
    existing = {_key(o.text) for o in ledger.obligations}
    added: list[Obligation] = []

    for entry in entries or []:
        if isinstance(entry, dict):
            text = str(entry.get("obligation") or entry.get("text") or "").strip()
            target = normalize_stage_slug(entry.get("target_stage") or entry.get("stage"))
        else:
            text, target = str(entry or "").strip(), None

        text = " ".join(text.split())
        if len(text) < MIN_OBLIGATION_CHARS:
            continue
        key = _key(text)
        if not key or key in existing or len(ledger.obligations) >= MAX_OBLIGATIONS:
            continue

        obligation = Obligation(
            obligation_id=f"O{len(ledger.obligations) + 1:03d}",
            text=text,
            origin_stage=stage.slug,
            target_stage=target,
        )
        ledger.obligations.append(obligation)
        existing.add(key)
        added.append(obligation)

    if added:
        save_ledger(paths, ledger)
    return added


def discharge_obligations(
    paths: RunPaths,
    *,
    stage: StageSpec,
    obligation_ids: list[Any],
    note: str = "",
) -> list[Obligation]:
    """Close obligations a reviewer confirms were met. Only a reviewer may call this."""
    ledger = load_ledger(paths)
    closed: list[Obligation] = []
    for raw_id in obligation_ids or []:
        obligation = ledger.by_id(str(raw_id))
        if obligation is None or obligation.status != OPEN:
            continue
        obligation.status = DISCHARGED
        obligation.discharged_by = stage.slug
        obligation.discharge_note = " ".join(str(note or "").split())[:500]
        closed.append(obligation)
    if closed:
        save_ledger(paths, ledger)
    return closed


def note_deferrals(paths: RunPaths, *, stage: StageSpec) -> int:
    """Mark still-open obligations that applied to this stage as deferred once more.

    Deferral is allowed but never silent: the count is written down and shown to every
    later reviewer, so an obligation cannot be carried forward indefinitely unnoticed.
    """
    ledger = load_ledger(paths)
    deferred = 0
    for obligation in ledger.obligations:
        if obligation.applies_to(stage):
            obligation.deferrals += 1
            deferred += 1
    if deferred:
        save_ledger(paths, ledger)
    return deferred


def format_for_stage_prompt(ledger: ObligationLedger, stage: StageSpec) -> str:
    """Tell a stage what earlier reviews decided it owes."""
    items = ledger.open_for(stage)
    if not items:
        return ""
    lines = [
        "Earlier reviews approved previous stages on the condition that these be addressed. "
        "Discharge each one in this stage, or state explicitly why it belongs later and what "
        "you did instead. Silently ignoring one is grounds for this stage to be rejected.",
        "",
    ]
    for obligation in items:
        aged = f" (deferred {obligation.deferrals}x)" if obligation.deferrals else ""
        lines.append(f"- `{obligation.obligation_id}` (from {obligation.origin_stage}){aged}: {obligation.text}")
    return "\n".join(lines)


def format_for_review_prompt(ledger: ObligationLedger, stage: StageSpec) -> str:
    """Ask the reviewer of this stage whether the inherited obligations were met."""
    items = ledger.open_for(stage)
    if not items:
        return ""
    lines = [
        "An earlier review approved a previous stage on the condition that these be "
        "addressed here. For each, decide whether this stage actually discharged it. List "
        "the ids that were genuinely met in `discharged`. Do not discharge one on a promise "
        "or a restatement — only on work present in this stage. An obligation neither met "
        "nor explicitly and reasonably deferred is grounds to refuse.",
        "",
    ]
    for obligation in items:
        aged = f" (already deferred {obligation.deferrals}x)" if obligation.deferrals else ""
        lines.append(f"- `{obligation.obligation_id}` (from {obligation.origin_stage}){aged}: {obligation.text}")
    return "\n".join(lines)


def ledger_summary(ledger: ObligationLedger) -> str:
    if not ledger.obligations:
        return "no carried-forward obligations"
    open_count = sum(1 for o in ledger.obligations if o.status == OPEN)
    return f"{open_count} open / {len(ledger.obligations)} total carried-forward obligation(s)"
