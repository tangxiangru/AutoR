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

#: A brief that enumerates its deliverables under an `Output:` label is asking for them
#: as *nouns*, and the verb gate above cannot see a noun phrase. Measured over the 40
#: archived ResearchClawBench briefs: 53 sentences of 25 characters or more survive
#: `research_brief` and are then dropped by the verb test, and 23 of those are enumerated
#: `Input:` / `Output:` lines -- the lines that literally list what the run owes.
#: Physics_000 is the clearest case. Its brief says "Output 2: Optimal size mismatch
#: values between adjacent shells." and "Output 3: Shell sequences and paths formed via
#: self-assembly in growth simulations."; neither contains a demand verb, so neither
#: reached `# What the Task Asks For`, and the two graded criteria they name carry 0.70 of
#: that task's weight (they scored 28 and 5 against the bare agent's 60 and 50).
#:
#: `Input:` stays out, for the reason the `_BRIEF_HEADINGS` note gives: a description of
#: what the run *has* is not a description of what it *owes*, and admitting data blurbs is
#: the dilution this module exists to avoid. Only the output side is admitted.
#: The label is usually on its own, with the deliverables enumerated after it --
#: ``Output:  1. Predicted stable multi-shell icosahedral structures.  2. Optimal size
#: mismatch values between adjacent shells.  3. Shell sequences and paths formed via
#: self-assembly in growth simulations.`` The sentence splitter breaks that on the
#: enumerators, so by the time a sentence is tested the label is three sentences behind
#: it and each item is a bare noun phrase. So the block is found first, and every
#: sentence inside it is a demand.
_OUTPUT_BLOCK = re.compile(
    r"(?is)\b(?:outputs?|deliverables?)\s*:\s*(.*?)"
    r"(?=\b(?:inputs?|deliverables?|scientific\s+(?:objective|goal)|research\s+(?:objective|goal)"
    r"|task\s+description|evaluation|constraints?|notes?)\s*:|\Z)"
)

#: The leading label on a one-line ``Output: <noun phrase>``. Stripped only for the
#: comparison against the block capture, never from the quote a run has to carry.
_OUTPUT_LABEL = re.compile(
    r"^\s*(?:\d+[.)]\s*)?(?:outputs?|deliverables?)\s*\d*\s*:\s*", re.IGNORECASE
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

    A sentence inside an ``Output:`` block is owed whether or not it contains a verb: see
    `_OUTPUT_BLOCK`. "Shell sequences and paths formed via self-assembly in growth
    simulations." is a deliverable written as a noun phrase, and the verb test alone
    drops it.

    Order is preserved and duplicates are dropped, so a sentence that is both labelled
    and verb-bearing appears once.
    """
    statement = task_statement or ""
    declared: set[str] = set()
    for block in _OUTPUT_BLOCK.findall(statement):
        for raw in _SENTENCE_SPLIT.split(block):
            sentence = _normalize(raw).strip("-*# \t")
            if len(sentence) >= 25:
                declared.add(_OUTPUT_LABEL.sub("", sentence))

    found: list[str] = []
    for raw in _SENTENCE_SPLIT.split(statement):
        sentence = _normalize(raw).strip("-*# \t")
        if len(sentence) < 25 or sentence in found:
            continue
        lowered = sentence.lower()
        # A one-line `Output: <noun phrase>` keeps its label in the quote and loses it
        # for the comparison, because the block capture starts after the label.
        if _OUTPUT_LABEL.sub("", sentence) in declared or any(
            re.search(rf"\b{verb}\w*\b", lowered) for verb in DEMAND_VERBS
        ):
            found.append(sentence)
    return found


#: Headings a research brief puts the actual question under. Everything else inside a
#: fenced task statement is the *delivery contract* -- how to lay out a workspace, that
#: figures are mandatory, that `report.md` is the deliverable. Measured over the 40
#: archived ResearchClawBench tasks: reading the whole fenced statement returns 337
#: demanding sentences of which 200 (59.3%) are the same five contract lines present in
#: all 40 tasks. Scoping to these headings returns 59, and 75 once they are split into
#: clauses. (An earlier version of this note said 137: that is the count with
#: `Available Data Files` admitted, which the next comment says is deliberately out.)
#: :func:`task_statement` already
#: strips AutoR's own wrapper; this strips the benchmark's inner one.
#: `Available Data Files` is deliberately not here. A file description says what the run
#: has, not what it owes, and admitting the block took the 40 archived tasks from 75
#: demands to 147, the 72 added being dataset blurbs -- the same dilution in miniature.
_BRIEF_HEADINGS = re.compile(
    r"^#{1,6}\s*(?:Task Description|Scientific Objective|Research Objective)\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_ANY_HEADING = re.compile(r"^#{1,6}\s+\S.*$", re.MULTILINE)


def research_brief(task_statement: str) -> str:
    """The part of a task statement that states the question, not how to deliver it.

    Returns the whole statement unchanged when it carries none of the brief headings --
    a free-form goal has no delivery contract to strip.
    """
    spans: list[str] = []
    for match in _BRIEF_HEADINGS.finditer(task_statement or ""):
        start = match.end()
        nxt = _ANY_HEADING.search(task_statement, start)
        spans.append(task_statement[start : nxt.start() if nxt else len(task_statement)])
    return "\n".join(spans).strip() or (task_statement or "")


def task_demands(task_statement: str) -> list[str]:
    """What the task asks the *research* to produce, one clause at a time.

    Two narrowings over :func:`demanding_sentences`. The population is
    :func:`research_brief`, so the delivery contract stops being counted as the research
    question -- a stage told that five sixths of what it owes is "save PNGs to
    report/images/" will optimise for that, and one did. And each sentence is split on
    ``;``: a brief whose three semicolon-separated outputs are the three things it is
    graded on reads, unsplit, as a single demand with no resolution.

    Widens rather than returning nothing, because an empty list makes
    :func:`format_deliverables_for_prompt` emit no block at all and the stage would then
    be told nothing about what it owes. Some briefs are machine-concatenated
    ("features.Output:"), so ``_SENTENCE_SPLIT`` never splits them and no demand verb is
    found; those fall back to every sentence of the brief.
    """
    def _clauses(sentences: list[str]) -> list[str]:
        out: list[str] = []
        for sentence in sentences:
            for part in sentence.split(";"):
                clause = _normalize(part).strip("-*# \t")
                if len(clause) >= 25:
                    out.append(clause)
        return out

    brief = research_brief(task_statement)
    scoped = brief != (task_statement or "")
    demands = _clauses(demanding_sentences(brief))
    if not demands and scoped:
        # A brief that states its outputs without a demand verb is still a brief. Only
        # reachable when the headings matched, so a free-form goal keeps the old
        # behaviour of yielding nothing rather than every sentence it contains.
        demands = _clauses(_SENTENCE_SPLIT.split(brief))
    if not demands:
        demands = demanding_sentences(task_statement)
    return list(dict.fromkeys(demands))


def load_coverage(paths: RunPaths) -> Any:
    path = paths.artifacts_dir / COVERAGE_FILENAME
    if not path.exists():
        return None
    try:
        return json.loads(read_text(path))
    except json.JSONDecodeError:
        return "invalid"


def _deliverable_text(paths: RunPaths) -> tuple[str, str]:
    """The document a `where` has to point into, whichever format the run targets.

    This used to read ``paths.report_file`` alone, which is `workspace/report/report.md`
    and nothing else. A latex run has no such file, so the locator check fell through the
    ``elif report_text and ...`` guard and asserted nothing -- a skip with no counter,
    inside the one gate that asks whether the run answered the question it was given.

    The other three halves of this validator -- the quote is verbatim, every demanding
    sentence is accounted for, an unmet demand states why -- never depended on the
    format. Only this one did, and only because the deliverable was named rather than
    resolved.

    Returns the document's name as well as its text, so a refusal says which document it
    looked in rather than always saying `report.md`.

    Still fail-open when neither exists: a stage that has written no deliverable yet is
    caught by the gates that check for one, and making this the second refusal for one
    condition would be two gates over one fact.
    """

    if paths.report_file.exists():
        return paths.report_file.name, _normalize(read_text(paths.report_file)).lower()
    sources = sorted(
        path for path in paths.writing_dir.rglob("*.tex") if path.is_file()
    ) if paths.writing_dir.exists() else []
    if sources:
        joined = "\n".join(read_text(path) for path in sources)
        name = "main.tex" if len(sources) == 1 else f"the {len(sources)} .tex sources under workspace/writing"
        return name, _normalize(joined).lower()
    return "", ""


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
    deliverable_name, deliverable_text = _deliverable_text(paths)

    quotes: list[str] = []
    declined: list[str] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            problems.append(f"{COVERAGE_FILENAME} entry {index} must be an object.")
            continue

        quote = _normalize(str(entry.get("task_quote") or ""))
        verbatim = bool(quote) and quote.lower() in normalized_task
        if not quote:
            problems.append(f"{COVERAGE_FILENAME} entry {index} is missing a non-empty task_quote.")
        elif not verbatim:
            # The teeth: without this a stage can restate the requirement as something it
            # already did and mark it answered.
            problems.append(
                f"{COVERAGE_FILENAME} entry {index} quotes text that is not in the task "
                f"statement: {quote[:80]!r}. Quote the task verbatim."
            )

        addressed = entry.get("addressed")
        if not isinstance(addressed, bool):
            problems.append(f"{COVERAGE_FILENAME} entry {index} needs a boolean 'addressed'.")
            continue

        # Only an entry that says it *answered* something counts as coverage of it.
        # Pooled before this distinction, an eloquent refusal's content words covered the
        # demand it declined -- so the cheapest way to account for a requirement was to
        # quote it and explain why the run did not meet it.
        if verbatim:
            (quotes if addressed else declined).append(quote)

        if addressed:
            where = _normalize(str(entry.get("where") or ""))
            if not where:
                problems.append(
                    f"{COVERAGE_FILENAME} entry {index} is marked addressed but does not say where."
                )
            elif deliverable_text and not _locator_appears(where, deliverable_text):
                problems.append(
                    f"{COVERAGE_FILENAME} entry {index} points at {where[:60]!r}, which does not "
                    f"appear in {deliverable_name}."
                )
        elif not _normalize(str(entry.get("reason") or "")):
            problems.append(
                f"{COVERAGE_FILENAME} entry {index} is not addressed and gives no reason. "
                "An unmet requirement must be stated, not omitted."
            )

    problems.extend(_uncovered_demands(task_statement, quotes, declined))
    return problems


#: Fragments that locate nothing. A `where` of "images/foo.png" splits to "images", which
#: is in every report that has a figure, so the pointer resolves without pointing
#: anywhere. Honest about its reach: replayed over the 603 coverage entries of the 40
#: archived runs this changes **no** verdict, and it does not save the case that
#: motivated it -- Information_002's entry 4 also names `derived_hamiltonians.png`, 24
#: characters and genuinely in the report, and the fragment loop is a disjunction. It
#: closes the class for the next corpus, not this one. The measured refusal that *would*
#: have caught entry 4 -- rejecting an entry discharged by figure filenames alone -- was
#: rejected instead: it fails 148 of 575 addressed entries across 38 of the 40 runs.
_GENERIC_LOCATORS = frozenset({
    "images", "figure", "figures", "section", "results", "report", "appendix",
    "table", "tables", "method", "methods", "data", "abstract", "discussion",
})

def _locator_appears(where: str, report_text: str) -> bool:
    """Whether a stated location is findable in the report.

    Deliberately loose -- a section title, a figure filename, or a heading all count. The
    point is that the pointer is not fabricated, not that it follows a format. Loose is
    not the same as free, though: a fragment has to be long enough and specific enough to
    name something, or every `where` mentioning a picture resolves.
    """
    candidate = where.lower()
    if candidate in report_text:
        return True
    for fragment in re.split(r"[/,;|]| and ", candidate):
        fragment = fragment.strip()
        if len(fragment) >= 12 and fragment not in _GENERIC_LOCATORS and fragment in report_text:
            return True
    return False




def _uncovered_demands(
    task_statement: str, quotes: list[str], declined: list[str] | None = None
) -> list[str]:
    """Demanding sentences no answered quote speaks to.

    Overlap is measured on content words rather than exact containment: a stage may
    legitimately quote the clause rather than the whole sentence, and requiring the whole
    sentence would push it toward quoting everything and answering nothing.

    A declined quote accounts for the demand *it* declines and for nothing else. Pooled
    together, the content words of an eloquent refusal covered neighbouring demands the
    entry says nothing about, so the cheapest way to account for a requirement was to
    decline a different one at length. Declining a demand with a reason still passes:
    reporting a requirement as unmet is a valid outcome, and a gate that refused it would
    teach the run to stop declaring what it did not do -- the failure the reviewer-side
    substitution check names in so many words.
    """
    if not quotes and not declined:
        return []
    quoted_words: set[str] = set()
    for quote in quotes:
        quoted_words |= _content_words(quote)

    missed: list[str] = []
    for sentence in task_demands(task_statement):
        words = _content_words(sentence)
        if not words:
            continue
        if len(words & quoted_words) / len(words) >= 0.34:
            continue
        # Accounted for by the entry that declines it, and only by that entry.
        if any(len(words & _content_words(quote)) / len(words) >= 0.34 for quote in declined or ()):
            continue
        missed.append(sentence)
    return [
        f"{COVERAGE_FILENAME} does not account for what the task asked: {sentence[:110]!r}"
        for sentence in missed[:5]
    ]


def format_deliverables_for_prompt(task_statement: str) -> str:
    """The prompt block that tells a stage what it owes, and how it will be checked."""
    demands = task_demands(task_statement)
    if not demands:
        return ""
    listed = "\n".join(f"{index}. {sentence}" for index, sentence in enumerate(demands, start=1))
    # The contract lines are the demanding sentences the brief did *not* claim. A sentence
    # a demand was split out of is not a contract line -- it is the same demand, unsplit.
    contract = [
        sentence
        for sentence in demanding_sentences(task_statement)
        if not any(demand in sentence for demand in demands)
    ]
    contract_block = (
        "\n\nHow to deliver, which is not what to find:\n\n"
        + "\n".join(f"- {sentence}" for sentence in contract[:8])
        if contract
        else ""
    )
    return (
        "The task statement asks for the following. A report that is rigorous about "
        "something else still fails the task.\n\n"
        f"{listed}{contract_block}\n\n"
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
        "- `addressed: false` is for a requirement this run could not meet, and it must "
        "name the artifact, dataset, model or instrument that was missing. It is not a "
        "way to narrow the task: before writing it, check whether the work is runnable "
        "from what is in this workspace -- if it is, do it. An attempt reported with its "
        "caveat and its uncertainty is worth far more than an omission, and a number you "
        "did not compute is worth less than either. Omitting a requirement is never an "
        "option."
    )
