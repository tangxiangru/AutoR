"""A review policy that improves itself from the reviewer's own corrections.

The approval gate in :mod:`src.approval_agent` judges each stage against a fixed prompt.
That makes it stateless: if the reviewer demands a power analysis at Stage 03, nothing stops
Stage 05 from shipping without one, and nothing stops the same omission recurring on the
next run. A human reviewer does not work that way — having once been burned, they keep
checking.

This module closes that loop. Every correction the reviewer demands is recorded as a
**standing rule**, and every later review is judged against the accumulated set. The
review capability is therefore produced by review and governs subsequent review, so the
gate gets strictly harder as a run proceeds:

    stage N review  ──demands a correction──▶  rule
                                                │
    stage N+1 review  ◀──rule is now checked────┘

Two properties make this more than a slogan:

* **It is auditable.** The policy is a plain JSON artifact at the run root, and every rule
  names the stage and attempt that produced it, so any claim about "self-improvement" can
  be checked against the record rather than believed.
* **It cannot silently inflate.** Rules are deduplicated on normalized text and the set is
  bounded, so a reviewer that repeats itself does not manufacture the appearance of
  learning.

Rules are stored verbatim rather than being generalized by an extra model call. A recorded
rule keeps the stage it came from, and the reviewing model generalizes at read time, which
avoids spending a call per correction to paraphrase text a model is about to read anyway.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .utils import RunPaths, StageSpec


POLICY_VERSION = 1

#: Upper bound on standing rules. A review prompt has to stay readable, and past this many
#: corrections the marginal rule is noise rather than signal.
MAX_RULES = 40

#: Corrections shorter than this carry no checkable content ("improve it", "more detail").
MIN_RULE_CHARS = 25

#: How rules are grouped in the prompt, strongest evidence first.
SOURCE_LABELS = {
    "rollback": "A stage was rolled back after this was missed",
    "refinement": "The reviewer demanded this correction",
}


@dataclass(frozen=True)
class ReviewRule:
    rule_id: str
    text: str
    origin_stage: str
    origin_attempt: int
    source: str = "refinement"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReviewPolicy:
    version: int = POLICY_VERSION
    rules: list[ReviewRule] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "rules": [rule.to_dict() for rule in self.rules]}

    @classmethod
    def from_dict(cls, payload: Any) -> "ReviewPolicy":
        if not isinstance(payload, dict):
            return cls()
        rules: list[ReviewRule] = []
        for entry in payload.get("rules") or []:
            if not isinstance(entry, dict):
                continue
            text = str(entry.get("text") or "").strip()
            if not text:
                continue
            rules.append(
                ReviewRule(
                    rule_id=str(entry.get("rule_id") or f"R{len(rules) + 1:03d}"),
                    text=text,
                    origin_stage=str(entry.get("origin_stage") or "unknown"),
                    origin_attempt=int(entry.get("origin_attempt") or 0),
                    source=str(entry.get("source") or "refinement"),
                )
            )
        return cls(version=int(payload.get("version") or POLICY_VERSION), rules=rules)


def policy_path(paths: RunPaths) -> Path:
    return paths.run_root / "review_policy.json"


def load_policy(paths: RunPaths) -> ReviewPolicy:
    path = policy_path(paths)
    if not path.exists():
        return ReviewPolicy()
    try:
        return ReviewPolicy.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        # A corrupt policy must not take the run down with it: the gate still works
        # without its learned rules, it is just back to its baseline strictness.
        return ReviewPolicy()


def save_policy(paths: RunPaths, policy: ReviewPolicy) -> Path:
    path = policy_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(policy.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def normalize_rule_text(text: str) -> str:
    """Collapse a correction to a comparison key.

    Reviewers restate the same demand with different punctuation, casing and stage numbers
    across attempts. Without this, one recurring complaint would fill the policy and look
    like accumulated learning.
    """
    lowered = re.sub(r"\s+", " ", (text or "").strip().lower())
    lowered = re.sub(r"\bstage\s*\d+\b", "stage", lowered)
    return re.sub(r"[^a-z0-9 ]+", "", lowered).strip()


def record_correction(
    paths: RunPaths,
    *,
    stage: StageSpec,
    attempt_no: int,
    text: str,
    source: str = "refinement",
) -> ReviewRule | None:
    """Turn one demanded correction into a standing rule.

    Returns the new rule, or None when the correction was empty, too thin to check, or a
    restatement of a rule already held.
    """
    cleaned = " ".join((text or "").split())
    if len(cleaned) < MIN_RULE_CHARS:
        return None

    policy = load_policy(paths)
    key = normalize_rule_text(cleaned)
    if not key:
        return None
    if any(normalize_rule_text(rule.text) == key for rule in policy.rules):
        return None
    if len(policy.rules) >= MAX_RULES:
        return None

    rule = ReviewRule(
        rule_id=f"R{len(policy.rules) + 1:03d}",
        text=cleaned,
        origin_stage=stage.slug,
        origin_attempt=attempt_no,
        source=source if source in SOURCE_LABELS else "refinement",
    )
    policy.rules.append(rule)
    save_policy(paths, policy)
    return rule


def format_policy_for_prompt(policy: ReviewPolicy, *, stage: StageSpec | None = None) -> str:
    """Render the standing rules for injection into a review prompt.

    ``stage`` excludes the rules this stage's own retries produced, which is what the
    mechanism was always documented to do -- "a correction demanded once is checked on
    every stage *after* it". Without it a rule the reviewer invents at attempt 3 is
    enforced against attempt 4 of the same draft, under a prompt that says a stage
    repeating a corrected mistake "must not be approved". Since a review that demands
    anything records a rule, the bar then rises by one requirement per attempt and the
    loop cannot converge: the stage is refused for a requirement that did not exist when
    it was written.

    Measured on the ResearchClawBench batch before this argument existed --
    `Information_001` learned 8 rules across Stage 02's 9 attempts and 7 across Stage
    03's 9, and both stages exhausted the retry budget with **no validation errors
    recorded**; `Astronomy_003` accumulated 33 rules, ran 46 stage executions for 7
    stages, and took 18.4 hours. `Chemistry_003`, with 6 rules, took 6.0.

    Cross-stage carry is untouched: a rule from Stage 02 still binds Stage 03 onward,
    which is the accumulation the design is for.
    """
    rules = policy.rules
    if stage is not None:
        rules = [rule for rule in rules if rule.origin_stage != stage.slug]
    if not rules:
        return ""

    lines = [
        "These corrections were demanded earlier in this run, at *other* stages. They are "
        "now standing requirements: check this stage against every one of them, not only "
        "against the stage's own objectives. A stage that repeats a mistake already "
        "corrected once must not be approved.",
        "",
    ]
    for source in ("rollback", "refinement"):
        group = [rule for rule in rules if rule.source == source]
        if not group:
            continue
        lines.append(f"**{SOURCE_LABELS[source]}:**")
        for rule in group:
            lines.append(f"- `{rule.rule_id}` (from {rule.origin_stage}, attempt {rule.origin_attempt}): {rule.text}")
        lines.append("")
    return "\n".join(lines).rstrip()


def policy_summary(policy: ReviewPolicy) -> str:
    """One line describing the policy, for the run log and the terminal."""
    if not policy.rules:
        return "no standing review rules yet"
    by_source = {
        source: sum(1 for rule in policy.rules if rule.source == source)
        for source in SOURCE_LABELS
    }
    parts = [f"{count} from {source}" for source, count in by_source.items() if count]
    return f"{len(policy.rules)} standing review rule(s) ({', '.join(parts)})"


def rules_from(policy: ReviewPolicy, sources: Iterable[str]) -> list[ReviewRule]:
    wanted = set(sources)
    return [rule for rule in policy.rules if rule.source in wanted]
