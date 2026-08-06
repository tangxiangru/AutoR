from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime

from .utils import RunPaths, TYPED_HYPOTHESIS_HEADINGS, extract_typed_hypothesis_sections


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


def write_hypothesis_manifest(paths: RunPaths, stage_markdown: str) -> HypothesisManifest | None:
    manifest = build_hypothesis_manifest(stage_markdown)
    if manifest is None:
        return None
    paths.hypothesis_manifest.parent.mkdir(parents=True, exist_ok=True)
    paths.hypothesis_manifest.write_text(
        json.dumps(manifest.to_dict(), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return manifest


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
