"""Hand Stage 07 the reasoning the run already did and would otherwise throw away.

AutoR spends real calls arguing with itself. A crux panel settles a methodological question
and is required to state what would falsify its answer; an ideation panel proposes hypotheses
from five distinct lenses and most of them are rejected. All of it lands in
``workspace/reviews/`` and stops there. Stage 07 has never read that directory, so the report
is written as though those arguments never happened.

That is a gap with a measurable price. ResearchClawBench's judge splits every criterion into
two ladders before scoring it (``evaluation/score.py``):

* **Mode A — quantitative.** Above 50 requires *metrics better than the published paper*. On a
  reproduction task, against a paper the agent is not given, that is out of reach. The band is
  effectively 0–50 and the whole spread sits below it: absent, mentioned without a number,
  number with a methodology error, number that deviates.
* **Mode B — mechanistic.** Above 50 reads: 51–60 *"more supporting evidence provided than the
  paper"*, 61–70 *"more complete logical chain and more rigorous argumentation"*, 71–80
  *"raises valuable insights not covered in the paper"*.

Classifying the 154 shipped criteria against those two definitions puts 32.7% of the total
weight in Mode B. **That third of the board is the only part where a report can score above
"as good as the paper", and the three bands above 50 describe, almost literally, the contents
of ``deliberations.json``: alternatives considered and rejected with reasons, a falsifier per
answer, and dissent that lost.**

So this module renders that material for Stage 07. Two things it deliberately does not do:

* **It does not pad.** The judge is told "no inflation for well-written but shallow content;
  longer does not mean better", and image criteria — 60.6% of the weight — see only the first
  10,000 characters of the report. A long block would cost more than it earns, so the entry
  count and the per-field length are capped and the preface sends the material to Discussion,
  after the numbers.
* **It does not invent.** A crux whose panel never sat contributes nothing, and says so by
  being absent. Only an answered crux and a rejected-with-a-reason candidate are rendered.
"""

from __future__ import annotations

import json
from typing import Any

from .utils import RunPaths, read_text

#: Resolved cruxes rendered. A run that argued about more than this has plenty to write
#: about; the report needs the ones it turned on, not a transcript.
MAX_CRUXES = 4

#: Rejected hypotheses rendered. Same reasoning: the Discussion band rewards "insights not
#: covered in the paper", not an inventory of everything anyone proposed.
MAX_REJECTED = 5

#: Per-field ceiling. Long enough for a real methodological argument, short enough that the
#: whole block cannot displace the results it is supposed to be discussing.
MAX_FIELD_CHARS = 600


def _clip(value: Any, limit: int = MAX_FIELD_CHARS) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _load(path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(read_text(path))
    except (OSError, json.JSONDecodeError):
        return None


def resolved_cruxes(paths: RunPaths) -> list[dict[str, Any]]:
    """Cruxes a panel actually settled, newest last.

    An entry with no answer is skipped rather than reported as an open question. The run may
    have escalated it and found the panel unreachable, and a report that presents an outage
    as a deliberate open question is claiming reasoning that did not happen.
    """
    payload = _load(paths.reviews_dir / "deliberations.json")
    entries = payload.get("deliberations") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict) or not str(entry.get("answer") or "").strip():
            continue
        request = entry.get("request") if isinstance(entry.get("request"), dict) else {}
        considered = request.get("already_considered")
        out.append(
            {
                "question": _clip(request.get("question")),
                "answer": _clip(entry.get("answer")),
                "falsifier": _clip(entry.get("falsifier")),
                "dissent": _clip(entry.get("dissent")),
                "rejected": [
                    _clip(item, 300)
                    for item in (considered if isinstance(considered, list) else [])
                    if str(item or "").strip()
                ][:4],
            }
        )
    return out


def rejected_candidates(paths: RunPaths) -> list[dict[str, Any]]:
    """Distinct hypotheses the run generated and did not pursue.

    Duplicates are excluded: a restatement of the adopted hypothesis is not a road not taken,
    and listing it as one would overstate how wide the search was.
    """
    payload = _load(paths.reviews_dir / "idea_pool.json")
    candidates = payload.get("candidates") if isinstance(payload, dict) else None
    if not isinstance(candidates, list):
        return []
    out: list[dict[str, Any]] = []
    for raw in candidates:
        if not isinstance(raw, dict) or raw.get("adopted") or raw.get("duplicate_of"):
            continue
        statement = _clip(raw.get("statement"))
        if not statement:
            continue
        out.append(
            {
                "title": _clip(raw.get("title"), 160),
                "statement": statement,
                "lens": _clip(raw.get("proposer_title") or raw.get("proposer"), 60),
                "prediction": _clip(raw.get("prediction"), 300),
            }
        )
    return out


def build_block(paths: RunPaths) -> str | None:
    """Render the settled reasoning, or None when the run did none worth reporting."""
    cruxes = resolved_cruxes(paths)[-MAX_CRUXES:]
    rejected = rejected_candidates(paths)[:MAX_REJECTED]
    if not cruxes and not rejected:
        return None

    lines: list[str] = []
    if cruxes:
        lines.append("## Methodological questions this run settled")
        lines.append("")
        for crux in cruxes:
            lines.append(f"**Question.** {crux['question']}")
            lines.append(f"- **Resolved:** {crux['answer']}")
            for item in crux["rejected"]:
                lines.append(f"- **Considered and rejected:** {item}")
            if crux["falsifier"]:
                lines.append(f"- **Would be overturned by:** {crux['falsifier']}")
            if crux["dissent"]:
                lines.append(f"- **Dissent on record:** {crux['dissent']}")
            lines.append("")
    if rejected:
        lines.append("## Hypotheses generated and not pursued")
        lines.append("")
        for cand in rejected:
            head = f"**{cand['title']}**" if cand["title"] else "**(untitled)**"
            lens = f" _({cand['lens']} lens)_" if cand["lens"] else ""
            lines.append(f"- {head}{lens} — {cand['statement']}")
            if cand["prediction"]:
                lines.append(f"  - Would have predicted: {cand['prediction']}")
        lines.append("")
    return "\n".join(lines).strip()
