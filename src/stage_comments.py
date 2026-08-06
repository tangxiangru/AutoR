"""Review comments anchored to the text they object to, and revisions checked against them.

Every refusal path in AutoR re-runs the whole stage. The continuation prompt asks the operator
to "preserve correct completed parts unless the feedback requires changing them" — and nothing
checks that it did. A reviewer who objects to one paragraph currently rerolls the ninety
percent nobody objected to, and the run has no way to notice.

This module makes a refusal *local*:

1. **A comment quotes the text it objects to.** Not a line number, which rots the moment
   anything above it moves, and not a section name, which is too coarse to act on. The
   multi-agent audit tools in the feedback literature do exactly this — every criticism is
   tied to a quotation, "so a disagreement has to point at text rather than at a hunch".
2. **The revision is told to change those spans and leave the rest byte-identical.**
3. **The next draft is diffed against the comments.** For each comment: did the quoted span
   actually change? And across the document: how much changed that no comment asked about?

Point 3 is the one that matters. "Only change what I asked about" is a prompt wish until
something measures it, and this is the same discipline the panels already carry: a feature
that cannot report its own failure is not measured.

A quote that cannot be found in the draft is recorded as ``unanchored`` rather than silently
dropped. A reviewer objecting to text the document does not contain is objecting to something
it imagined, and that is worth surfacing rather than passing on to the operator as an
instruction it cannot satisfy.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .utils import RunPaths, StageSpec, read_text, write_text


#: Severities a comment may carry, most serious first.
SEVERITIES = ("blocking", "major", "minor")

#: Below this many characters a quote is too generic to anchor anything — "the results" will
#: match half the document, and a comment that matches everywhere points at nothing.
MIN_QUOTE_CHARS = 12

COMMENT_LEDGER_FILENAME = "comment_ledger.json"


def normalize(text: str) -> str:
    """Collapse whitespace so a quote survives re-wrapping but not rewording."""
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class StageComment:
    comment_id: str
    quote: str
    comment: str
    required_change: str = ""
    severity: str = "major"
    author: str = "reviewer"
    section: str = ""
    status: str = "open"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def locate(markdown: str, quote: str) -> int | None:
    """Character offset of *quote* in *markdown*, tolerating whitespace differences."""
    if not quote.strip():
        return None
    direct = markdown.find(quote)
    if direct >= 0:
        return direct

    # Re-wrapped text: match on normalized whitespace, then map back to a real offset by
    # searching for the first token run.
    haystack, needle = normalize(markdown), normalize(quote)
    if not needle or needle not in haystack:
        return None
    head = needle.split(" ")[0]
    return markdown.find(head) if head else None


def section_for(markdown: str, offset: int | None) -> str:
    """The nearest markdown heading above *offset*, as human context for the comment."""
    if offset is None:
        return ""
    headings = [
        (match.start(), match.group(1).strip())
        for match in re.finditer(r"^#{1,6}\s+(.*?)\s*$", markdown[:offset], flags=re.MULTILINE)
    ]
    return headings[-1][1] if headings else ""


def parse_comments(payload: Any, *, author: str, markdown: str) -> list[StageComment]:
    """Read anchored comments out of a reviewer's JSON response.

    Tolerant by design: a reviewer that returns no ``comments`` key at all is the old
    unanchored behaviour and must keep working, so this returns an empty list rather than
    raising.
    """
    if not isinstance(payload, dict):
        return []
    raw_comments = payload.get("comments")
    if not isinstance(raw_comments, list):
        return []

    comments: list[StageComment] = []
    for index, raw in enumerate(raw_comments, start=1):
        if not isinstance(raw, dict):
            continue
        quote = str(raw.get("quote") or "").strip()
        body = str(raw.get("comment") or raw.get("issue") or "").strip()
        if not body or len(quote) < MIN_QUOTE_CHARS:
            continue
        severity = str(raw.get("severity") or "major").strip().lower()
        offset = locate(markdown, quote)
        comments.append(
            StageComment(
                comment_id=f"{author}-{index}",
                quote=quote,
                comment=body,
                required_change=str(raw.get("required_change") or raw.get("fix") or "").strip(),
                severity=severity if severity in SEVERITIES else "major",
                author=author,
                section=section_for(markdown, offset),
                status="open" if offset is not None else "unanchored",
            )
        )
    return comments


def anchored(comments: list[StageComment]) -> list[StageComment]:
    return [comment for comment in comments if comment.status != "unanchored"]


def build_comment_feedback(comments: list[StageComment]) -> str:
    """The revision instruction: change these spans, leave everything else alone."""
    live = anchored(comments)
    if not live:
        return ""

    order = {severity: index for index, severity in enumerate(SEVERITIES)}
    live = sorted(live, key=lambda c: order.get(c.severity, len(SEVERITIES)))

    lines = [
        "The reviewer did not reject this stage as a whole. They objected to specific passages, "
        "quoted below.",
        "",
        "**Revise only these passages.** Every other part of the stage summary must come back "
        "byte-identical — do not re-word, re-order, re-title, or 'improve' anything a comment "
        "did not ask about. The revision is diffed against these quotes afterwards, and changes "
        "outside them are recorded as collateral.",
        "",
    ]
    for comment in live:
        lines.append(f"### {comment.comment_id} ({comment.severity}){f' — {comment.section}' if comment.section else ''}")
        lines.append("")
        lines.append("Quoted from your draft:")
        lines.append("")
        lines.extend(f"> {line}" for line in comment.quote.splitlines())
        lines.append("")
        lines.append(f"Objection: {comment.comment}")
        if comment.required_change:
            lines.append(f"Required change: {comment.required_change}")
        lines.append("")

    lines.append(
        "If you believe a comment is wrong, say so in `Revision Delta` and leave the passage "
        "unchanged. Arguing is allowed; silently ignoring is not."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Verifying that the revision was actually targeted
# ---------------------------------------------------------------------------


@dataclass
class RevisionOutcome:
    addressed: list[str] = field(default_factory=list)
    untouched: list[str] = field(default_factory=list)
    unanchored: list[str] = field(default_factory=list)
    anchored_lines_changed: int = 0
    collateral_lines_changed: int = 0
    lines_added: int = 0

    @property
    def collateral_ratio(self) -> float:
        total = self.anchored_lines_changed + self.collateral_lines_changed
        return round(self.collateral_lines_changed / total, 2) if total else 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["collateral_ratio"] = self.collateral_ratio
        payload["verdict"] = self.verdict()
        return payload

    def verdict(self) -> str:
        """One sentence, unflattering when that is the truth."""
        parts: list[str] = []
        if self.untouched:
            parts.append(
                f"{len(self.untouched)} comment(s) left the quoted passage unchanged "
                f"({', '.join(self.untouched)})"
            )
        if self.addressed:
            parts.append(f"{len(self.addressed)} comment(s) were acted on")
        if self.collateral_lines_changed:
            parts.append(
                f"{self.collateral_lines_changed} line(s) changed that no comment asked about"
            )
        if self.unanchored:
            parts.append(
                f"{len(self.unanchored)} comment(s) quoted text the draft did not contain "
                f"({', '.join(self.unanchored)})"
            )
        if not parts:
            return "The revision made no measurable change."
        return "; ".join(parts) + "."


def _anchored_line_indices(before: str, comments: list[StageComment]) -> set[int]:
    """Line numbers in *before* that a comment's quote covers."""
    lines = before.splitlines()
    starts: list[int] = []
    offset = 0
    for line in lines:
        starts.append(offset)
        offset += len(line) + 1

    covered: set[int] = set()
    for comment in anchored(comments):
        position = locate(before, comment.quote)
        if position is None:
            continue
        end = position + len(comment.quote)
        for index, start in enumerate(starts):
            line_end = start + len(lines[index])
            if start <= end and line_end >= position:
                covered.add(index)
    return covered


def assess_revision(before: str, after: str, comments: list[StageComment]) -> RevisionOutcome:
    """Diff a revision against the comments that asked for it.

    Two questions, both mechanical. Did each quoted passage actually change? And how much of
    the document changed that no comment pointed at? A revision that rewrites everything is
    not a targeted revision, however targeted the instruction was.
    """
    outcome = RevisionOutcome()
    for comment in comments:
        if comment.status == "unanchored":
            outcome.unanchored.append(comment.comment_id)
        elif locate(after, comment.quote) is None:
            # The text the reviewer objected to is gone, so it was acted on.
            outcome.addressed.append(comment.comment_id)
        else:
            outcome.untouched.append(comment.comment_id)

    before_lines, after_lines = before.splitlines(), after.splitlines()
    covered = _anchored_line_indices(before, comments)
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "insert":
            outcome.lines_added += j2 - j1
            continue
        touched = set(range(i1, i2))
        outcome.anchored_lines_changed += len(touched & covered)
        outcome.collateral_lines_changed += len(touched - covered)
        if tag == "replace":
            outcome.lines_added += max(0, (j2 - j1) - (i2 - i1))
    return outcome


def carry_forward(comments: list[StageComment], outcome: RevisionOutcome) -> list[StageComment]:
    """The comments a further round still owes: the ones whose passage never moved.

    An unaddressed comment that quietly disappears is how a review becomes advisory. Keeping
    it means the next round is asked for the same change again, with the same quote.
    """
    untouched = set(outcome.untouched)
    return [comment for comment in comments if comment.comment_id in untouched]


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


def record_round(
    paths: RunPaths,
    stage: StageSpec,
    attempt_no: int,
    comments: list[StageComment],
    outcome: RevisionOutcome | None = None,
) -> dict[str, Any]:
    """Append one review round to the stage's comment ledger."""
    path = paths.reviews_dir / COMMENT_LEDGER_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)

    ledger: dict[str, Any] = {"rounds": []}
    if path.exists():
        try:
            existing = json.loads(read_text(path))
            if isinstance(existing, dict) and isinstance(existing.get("rounds"), list):
                ledger = existing
        except (OSError, json.JSONDecodeError):
            ledger = {"rounds": []}

    entry: dict[str, Any] = {
        "stage": stage.slug,
        "attempt": attempt_no,
        "comments": [comment.to_dict() for comment in comments],
    }
    if outcome is not None:
        entry["outcome"] = outcome.to_dict()

    rounds = [
        round_entry
        for round_entry in ledger["rounds"]
        if not (round_entry.get("stage") == stage.slug and round_entry.get("attempt") == attempt_no)
    ]
    rounds.append(entry)
    ledger["rounds"] = rounds
    ledger["summary"] = _ledger_summary(rounds)
    write_text(path, json.dumps(ledger, indent=2, ensure_ascii=False))
    return ledger


def _ledger_summary(rounds: list[dict[str, Any]]) -> dict[str, Any]:
    raised = sum(len(entry.get("comments") or []) for entry in rounds)
    outcomes = [entry["outcome"] for entry in rounds if isinstance(entry.get("outcome"), dict)]
    addressed = sum(len(outcome.get("addressed") or []) for outcome in outcomes)
    untouched = sum(len(outcome.get("untouched") or []) for outcome in outcomes)
    unanchored = sum(len(outcome.get("unanchored") or []) for outcome in outcomes)
    collateral = sum(int(outcome.get("collateral_lines_changed") or 0) for outcome in outcomes)
    on_target = sum(int(outcome.get("anchored_lines_changed") or 0) for outcome in outcomes)
    total = on_target + collateral
    return {
        "rounds": len(rounds),
        "comments_raised": raised,
        "comments_addressed": addressed,
        "comments_left_untouched": untouched,
        "comments_quoting_absent_text": unanchored,
        "lines_changed_on_target": on_target,
        "lines_changed_as_collateral": collateral,
        "collateral_ratio": round(collateral / total, 2) if total else 0.0,
        "verdict": _summary_verdict(len(rounds), addressed, untouched, on_target, collateral),
    }


def _summary_verdict(rounds: int, addressed: int, untouched: int, on_target: int, collateral: int) -> str:
    if rounds == 0:
        return "No anchored review rounds yet."
    total = on_target + collateral
    if total == 0:
        return f"{rounds} anchored round(s); no lines changed."
    share = collateral / total
    if share >= 0.5:
        return (
            f"{addressed} comment(s) acted on across {rounds} round(s), but {collateral} of "
            f"{total} changed lines were outside anything a comment asked about. Targeted "
            "revision is not being honoured here — the stage is being rewritten, not patched."
        )
    return (
        f"{addressed} comment(s) acted on and {untouched} left untouched across {rounds} "
        f"round(s); {collateral} of {total} changed lines were collateral."
    )
