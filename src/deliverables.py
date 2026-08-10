"""Hold a run to the deliverables its own task statement asked for.

AutoR's rubric measures how *well* a stage worked: whether references resolve, whether
the decision ledger is populated, whether claims trace to artifacts. None of that asks
the prior question -- did the run answer what it was asked?

Observed on ResearchClawBench Astronomy_000. The task statement said:

    "derive statistically rigorous upper limits on ULB masses **and self-interaction
     coupling strengths**"

The run produced a rigorous mass exclusion band and never reported a coupling limit. Its
own rubric scored 1.000. The scored criterion asking for the coupling constant in GeV^-1
scored 25/100, and it carried half the task's weight. Nothing in the pipeline noticed,
because nothing was comparing the report against the ask.

This module adds that comparison, structurally rather than semantically. Stage 07 writes
`artifacts/deliverables_coverage.json` enumerating what the task demanded and where each
demand is answered. The gate then checks things a machine can actually settle:

* every `task_quote` is a **verbatim** span of the task statement, so the stage cannot
  soften an inconvenient requirement into one it happens to have met;
* every demanding sentence in the task statement is covered by some quote, so it cannot
  enumerate a convenient subset;
* an answered deliverable names where it is answered, and that location appears in the
  report; an unanswered one states why.

What the gate deliberately does not do is judge whether the answer is *correct*. That is
the same line every other AutoR validator holds.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .utils import RunPaths, read_text

COVERAGE_FILENAME = "deliverables_coverage.json"

#: Verbs that turn a sentence of a task statement into something owed. Drawn from the 40
#: ResearchClawBench task descriptions plus the ordinary vocabulary of a research brief.
DEMAND_VERBS = (
    "derive", "compute", "calculate", "estimate", "quantify", "measure",
    "compare", "benchmark", "evaluate", "assess", "validate", "verify",
    "identify", "determine", "characterize", "characterise", "analyze", "analyse",
    "predict", "classify", "reconstruct", "reproduce", "replicate",
    "produce", "generate", "construct", "build", "develop", "implement",
    "demonstrate", "show", "establish", "constrain", "test",
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"[a-z0-9]+")


def _normalize(text: str) -> str:
    """Collapse whitespace so a quote survives re-wrapping."""
    return " ".join(text.split())


def _content_words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 3}


def demanding_sentences(task_statement: str) -> list[str]:
    """Sentences of the task statement that ask for something.

    A research brief is mostly context; the demands are the handful of sentences with a
    verb like "derive" or "compare" in them. Those are what a report owes an answer to.
    """
    found: list[str] = []
    for raw in _SENTENCE_SPLIT.split(task_statement or ""):
        sentence = _normalize(raw).strip("-*# \t")
        if len(sentence) < 25:
            continue
        lowered = sentence.lower()
        if any(re.search(rf"\b{verb}\w*\b", lowered) for verb in DEMAND_VERBS):
            found.append(sentence)
    return found


def load_coverage(paths: RunPaths) -> Any:
    path = paths.artifacts_dir / COVERAGE_FILENAME
    if not path.exists():
        return None
    try:
        return json.loads(read_text(path))
    except json.JSONDecodeError:
        return "invalid"


def validate_deliverables_coverage(paths: RunPaths, task_statement: str) -> list[str]:
    """Check that the report answers what the task statement asked for."""
    problems: list[str] = []
    payload = load_coverage(paths)
    if payload is None:
        return [f"requires {COVERAGE_FILENAME} under workspace/artifacts."]
    if payload == "invalid":
        return [f"{COVERAGE_FILENAME} is not valid JSON."]

    entries = payload.get("deliverables") if isinstance(payload, dict) else payload
    if not isinstance(entries, list) or not entries:
        return [f"{COVERAGE_FILENAME} must contain a non-empty 'deliverables' list."]

    normalized_task = _normalize(task_statement).lower()
    report_text = _normalize(read_text(paths.report_file)).lower() if paths.report_file.exists() else ""

    quotes: list[str] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            problems.append(f"{COVERAGE_FILENAME} entry {index} must be an object.")
            continue

        quote = _normalize(str(entry.get("task_quote") or ""))
        if not quote:
            problems.append(f"{COVERAGE_FILENAME} entry {index} is missing a non-empty task_quote.")
        elif quote.lower() not in normalized_task:
            # The teeth: without this a stage can restate the requirement as something it
            # already did and mark it answered.
            problems.append(
                f"{COVERAGE_FILENAME} entry {index} quotes text that is not in the task "
                f"statement: {quote[:80]!r}. Quote the task verbatim."
            )
        else:
            quotes.append(quote)

        addressed = entry.get("addressed")
        if not isinstance(addressed, bool):
            problems.append(f"{COVERAGE_FILENAME} entry {index} needs a boolean 'addressed'.")
            continue

        if addressed:
            where = _normalize(str(entry.get("where") or ""))
            if not where:
                problems.append(
                    f"{COVERAGE_FILENAME} entry {index} is marked addressed but does not say where."
                )
            elif report_text and not _locator_appears(where, report_text):
                problems.append(
                    f"{COVERAGE_FILENAME} entry {index} points at {where[:60]!r}, which does not "
                    "appear in report.md."
                )
        elif not _normalize(str(entry.get("reason") or "")):
            problems.append(
                f"{COVERAGE_FILENAME} entry {index} is not addressed and gives no reason. "
                "An unmet requirement must be stated, not omitted."
            )

    problems.extend(_uncovered_demands(task_statement, quotes))
    return problems


def _locator_appears(where: str, report_text: str) -> bool:
    """Whether a stated location is findable in the report.

    Deliberately loose -- a section title, a figure filename, or a heading all count. The
    point is that the pointer is not fabricated, not that it follows a format.
    """
    candidate = where.lower()
    if candidate in report_text:
        return True
    for fragment in re.split(r"[/,;|]| and ", candidate):
        fragment = fragment.strip()
        if len(fragment) >= 6 and fragment in report_text:
            return True
    return False


def _uncovered_demands(task_statement: str, quotes: list[str]) -> list[str]:
    """Demanding sentences no quote speaks to.

    Overlap is measured on content words rather than exact containment: a stage may
    legitimately quote the clause rather than the whole sentence, and requiring the whole
    sentence would push it toward quoting everything and answering nothing.
    """
    if not quotes:
        return []
    quoted_words: set[str] = set()
    for quote in quotes:
        quoted_words |= _content_words(quote)

    missed: list[str] = []
    for sentence in demanding_sentences(task_statement):
        words = _content_words(sentence)
        if not words:
            continue
        if len(words & quoted_words) / len(words) < 0.34:
            missed.append(sentence)
    return [
        f"{COVERAGE_FILENAME} does not account for what the task asked: {sentence[:110]!r}"
        for sentence in missed[:5]
    ]


def format_deliverables_for_prompt(task_statement: str) -> str:
    """The prompt block that tells a stage what it owes, and how it will be checked."""
    demands = demanding_sentences(task_statement)
    if not demands:
        return ""
    listed = "\n".join(f"{index}. {sentence}" for index, sentence in enumerate(demands, start=1))
    return (
        "The task statement asks for the following. A report that is rigorous about "
        "something else still fails the task.\n\n"
        f"{listed}\n\n"
        f"Before this stage can be approved, write `workspace/artifacts/{COVERAGE_FILENAME}`:\n\n"
        "```json\n"
        '{"deliverables": [\n'
        '  {"task_quote": "<verbatim span of the task statement>",\n'
        '   "addressed": true,\n'
        '   "where": "<section heading or images/figure.png in report.md>"},\n'
        '  {"task_quote": "<verbatim span>", "addressed": false,\n'
        '   "reason": "<why it could not be answered>"}\n'
        "]}\n"
        "```\n\n"
        "- `task_quote` must appear **verbatim** in the task statement. Restating a "
        "requirement as something you happened to do is the failure this check exists for.\n"
        "- Every numbered demand above must be spoken to by some quote.\n"
        "- `where` must actually appear in `report.md`.\n"
        "- Reporting a requirement as unmet is a valid outcome. Omitting it is not."
    )
