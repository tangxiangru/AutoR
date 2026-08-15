from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from .utils import (
    RunPaths,
    StageSpec,
    TYPED_HYPOTHESIS_HEADINGS,
    extract_typed_hypothesis_sections,
)


@dataclass(frozen=True)
class HypothesisEntry:
    identifier: str
    statement: str
    claim_type: str
    derived_from: str = ""
    depends_on: str = ""
    verification_needed: str = ""
    #: What result would count as support, and what would count as refutation.
    #: Required for empirical hypotheses: a hypothesis with no decision rule
    #: cannot come out negative, which makes "falsifiable" a word rather than a
    #: property.
    decision_rule: str = ""
    status: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.identifier,
            "type": self.claim_type,
            "statement": self.statement,
            "derived_from": self.derived_from,
            "depends_on": self.depends_on,
            "verification_needed": self.verification_needed,
            "decision_rule": self.decision_rule,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "HypothesisEntry":
        return cls(
            identifier=str(payload.get("id") or "").strip(),
            claim_type=str(payload.get("type") or "").strip(),
            statement=str(payload.get("statement") or "").strip(),
            derived_from=str(payload.get("derived_from") or "").strip(),
            depends_on=str(payload.get("depends_on") or "").strip(),
            verification_needed=str(payload.get("verification_needed") or "").strip(),
            decision_rule=str(payload.get("decision_rule") or "").strip(),
            status=str(payload.get("status") or "").strip(),
        )


@dataclass(frozen=True)
class HypothesisManifest:
    generated_at: str
    theoretical_propositions: list[HypothesisEntry]
    empirical_hypotheses: list[HypothesisEntry]
    paper_claims: list[HypothesisEntry]

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "theoretical_propositions": [entry.to_dict() for entry in self.theoretical_propositions],
            "empirical_hypotheses": [entry.to_dict() for entry in self.empirical_hypotheses],
            "paper_claims": [entry.to_dict() for entry in self.paper_claims],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "HypothesisManifest":
        return cls(
            generated_at=str(payload.get("generated_at") or "").strip(),
            theoretical_propositions=[
                HypothesisEntry.from_dict(item)
                for item in payload.get("theoretical_propositions", [])
                if isinstance(item, dict)
            ],
            empirical_hypotheses=[
                HypothesisEntry.from_dict(item)
                for item in payload.get("empirical_hypotheses", [])
                if isinstance(item, dict)
            ],
            paper_claims=[
                HypothesisEntry.from_dict(item)
                for item in payload.get("paper_claims", [])
                if isinstance(item, dict)
            ],
        )


def build_hypothesis_manifest(stage_markdown: str) -> HypothesisManifest | None:
    sections = extract_typed_hypothesis_sections(stage_markdown)
    if len(sections) < len(TYPED_HYPOTHESIS_HEADINGS):
        return None

    return HypothesisManifest(
        generated_at=datetime.now().isoformat(timespec="seconds"),
        theoretical_propositions=_parse_section(
            sections["Theoretical Propositions"], "theoretical_proposition"
        ),
        empirical_hypotheses=_parse_section(
            sections["Empirical Hypotheses"], "empirical_hypothesis"
        ),
        paper_claims=_parse_section(
            sections["Paper Claims (Provisional)"], "paper_claim"
        ),
    )


def write_hypothesis_manifest(
    paths: RunPaths, stage_markdown: str, stage: StageSpec | None = None
) -> HypothesisManifest | None:
    """Derive the manifest from the stage's markdown and write it.

    ``stage`` is what makes the write revertible. AutoR owns this file — it is derived
    here rather than written by the agent — so the write can go through
    :func:`src.effects.set_artifact`, which stores the previous bytes and accumulates the
    inverse against the stage. A rollback past the stage that wrote it then rewinds this
    file exactly, rather than depending on the next :func:`src.provenance.observe` having
    happened to catch it at a boundary.

    Omitting ``stage`` writes directly, which is what the tests and any caller with no
    stage in hand do. The file is still attributed at the next stage boundary, so it is
    still withdrawable; it is the exactness that needs the stage, not the coverage.
    """

    manifest = build_hypothesis_manifest(stage_markdown)
    if manifest is None:
        return None
    body = json.dumps(manifest.to_dict(), indent=2, ensure_ascii=True) + "\n"
    if stage is not None:
        from .effects import set_artifact

        rel_path = paths.hypothesis_manifest.relative_to(paths.workspace_root).as_posix()
        set_artifact(paths, stage, rel_path, body, key="hypotheses")
        return manifest
    paths.hypothesis_manifest.parent.mkdir(parents=True, exist_ok=True)
    paths.hypothesis_manifest.write_text(body, encoding="utf-8")
    return manifest


def hypotheses_without_decision_rule(entries: Sequence[HypothesisEntry]) -> list[str]:
    """Which empirical hypotheses carry no decision rule, by identifier.

    One spelling of one rule, two readers: :func:`validate_hypothesis_decision_rules`,
    which refuses the stage, and ``src.rubric``, which grades the same condition on the
    draft. Written here rather than in either of them because a gate and its graded
    twin disagreeing about what "has a decision rule" means is the failure that makes a
    score and a gate tell a run two different things.

    ``derived_from`` is deliberately not required alongside it. The Stage 02 prompt
    lists that field under "Add supporting lines under each entry **when relevant**",
    and the repo's own Stage 02 fixtures omit it, so demanding it here would refuse a
    draft that did exactly what it was told.
    """
    return [
        entry.identifier or "(unnamed hypothesis)"
        for entry in entries
        if not entry.decision_rule.strip()
    ]


def validate_hypothesis_decision_rules(paths: RunPaths) -> list[str]:
    """Refuse a hypothesis set that cannot come out negative, at the stage that wrote it.

    The Stage 02 prompt requires a ``- Decision rule: ...`` line on every empirical
    hypothesis. Until this existed, the first gate that read one was
    :func:`src.preregistration.validate_preregistration` at Stage 05 — three stages
    downstream of the mistake, after the set was frozen at Stage 04, where the only
    repair is a rollback. That is the same shape as the experimental-protocol
    counter-example already written at the ``validate_report_plan`` call site in
    :func:`src.utils.validate_stage_artifacts`, and the fix is the same one: hold the
    check at the stage that can still make the change cheaply.

    A missing manifest is deliberately **not** refused here. At Stage 02
    :func:`src.utils.validate_stage_markdown` already requires the typed hypothesis
    subsections and ``write_hypothesis_manifest`` derives the file from them moments
    before this runs; from Stage 03 on, absence is ``validate_preregistration``'s to
    report, and it says something more useful about it than this could.
    """
    if not paths.hypothesis_manifest.exists():
        return []
    try:
        payload = json.loads(paths.hypothesis_manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [
            "cannot read workspace/notes/hypothesis_manifest.json as JSON "
            f"({exc}). Rewrite it in the Stage 02 format; a hypothesis set nothing can "
            "parse cannot be frozen, adjudicated, or reported."
        ]

    section = payload.get("empirical_hypotheses") if isinstance(payload, dict) else None
    if not isinstance(section, list):
        return []
    entries = [HypothesisEntry.from_dict(item) for item in section if isinstance(item, dict)]
    missing = hypotheses_without_decision_rule(entries)
    if not missing:
        return []
    return [
        "has empirical hypotheses with no decision rule in "
        f"workspace/notes/hypothesis_manifest.json: {', '.join(missing)}. State, as "
        "`- Decision rule: ...` under each one in Stage 02, what result would count as "
        "support and what would count as refutation. A hypothesis with no decision rule "
        "cannot come out negative, and Stage 04 freezes this set as it stands."
    ]


def load_hypothesis_manifest(path) -> HypothesisManifest | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return HypothesisManifest.from_dict(payload)


def format_hypothesis_manifest_for_prompt(manifest: HypothesisManifest) -> str:
    lines: list[str] = []
    groups = [
        ("Theoretical Propositions", manifest.theoretical_propositions),
        ("Empirical Hypotheses", manifest.empirical_hypotheses),
        ("Paper Claims (Provisional)", manifest.paper_claims),
    ]
    for heading, items in groups:
        if not items:
            continue
        lines.append(f"### {heading}")
        for item in items:
            lines.append(f"- **{item.identifier}**: {item.statement}")
            if item.derived_from:
                lines.append(f"  - Derived from: {item.derived_from}")
            if item.depends_on:
                lines.append(f"  - Depends on: {item.depends_on}")
            if item.decision_rule:
                lines.append(f"  - Decision rule: {item.decision_rule}")
            if item.verification_needed:
                lines.append(f"  - Verification: {item.verification_needed}")
            if item.status:
                lines.append(f"  - Status: {item.status}")
        lines.append("")
    return "\n".join(lines).strip()


def _parse_section(section_text: str, claim_type: str) -> list[HypothesisEntry]:
    entries: list[HypothesisEntry] = []
    current: dict[str, str] | None = None

    for raw_line in section_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue

        entry_match = re.match(r"^-\s+\*\*([A-Z]\d+)\*\*:\s*(.+)$", stripped)
        if entry_match:
            if current is not None:
                entries.append(_entry_from_state(current, claim_type))
            current = {
                "id": entry_match.group(1).strip(),
                "statement": entry_match.group(2).strip(),
            }
            continue

        if current is None:
            continue

        detail_match = re.match(r"^-\s+([^:]+):\s*(.+)$", stripped)
        if detail_match:
            label = detail_match.group(1).strip().lower()
            value = detail_match.group(2).strip()
            if label == "derived from":
                current["derived_from"] = value
            elif label == "depends on":
                current["depends_on"] = value
            elif label == "verification":
                current["verification_needed"] = value
            elif label in ("decision rule", "decision-rule"):
                current["decision_rule"] = value
            elif label == "status":
                current["status"] = value

    if current is not None:
        entries.append(_entry_from_state(current, claim_type))

    return entries


def _entry_from_state(state: dict[str, str], claim_type: str) -> HypothesisEntry:
    return HypothesisEntry(
        identifier=state.get("id", ""),
        statement=state.get("statement", ""),
        claim_type=claim_type,
        derived_from=state.get("derived_from", ""),
        depends_on=state.get("depends_on", ""),
        verification_needed=state.get("verification_needed", ""),
        decision_rule=state.get("decision_rule", ""),
        status=state.get("status", ""),
    )
