"""Grade a FrontierScience answer, and refuse to call a judge failure a zero.

The pure half of the FrontierScience scorer: the judge prompt, the reader that gets text
back out of a Responses API payload, the rules that decide whether a draw is a
measurement, and the result document. :mod:`tools.score_fs_run` is the half that touches
the network; everything here is a function of already-parsed data, so the rules can be
tested without a key, without a socket, and without spending eighty seconds per
assertion.

**A failed draw is ``None``, and that is load-bearing.** A deliberately bad
two-sentence answer was scored on three of these tasks and came back **exactly 0.000**
on all three, with the judge giving a separate reason for every rubric item. So a real
zero exists on this benchmark, it is common, and it is the honest score for a bad
answer. Which means the one thing a failed judge call must never produce is a zero:
:mod:`tools.score_rcb_run` exists because ResearchClawBench's scorer writes
``{"score": 0}`` for a failed call, and one run's honest total of 37.0 appeared on
screen as 19.5 with nothing in the output to say which items were failures. Here the
points of a failed draw are ``None``, :func:`refusal_reasons` names it, and no total is
written.

**The judge is not the paper's judge, and no number from this file is comparable to the
paper's table.** The paper grades with GPT-5 at high reasoning effort. That deployment
returns 404 on the endpoint available here, as does ``gpt-5.2``; ``gpt-5.1`` is what
answers. Judge choice moved a ResearchClawBench total by about sixteen points on
identical artifacts, so this is a difference in the instrument and not a detail of the
plumbing.

**Four things measured against the live endpoint, each of which changes the code.**

1. ``output_text`` is ``null`` on this deployment. The text lives in ``output[]``, and
   :func:`response_text` filters on ``type == "message"`` rather than joining everything.
   That filter is the contract, not tidiness: the verdict is defined as being *on the
   last line*, and a reasoning item that ever carried a ``content[].text`` would put
   something after it. ResearchClawBench's reader joins every part because it extracts a
   JSON object and does not care about order; this one does.
2. A truncated response arrives as **HTTP 200** with ``status == "incomplete"`` and
   ``incomplete_details.reason == "max_output_tokens"``. Observed: 32,000 output tokens
   of which 31,817 were reasoning, 636 visible characters, cut mid-sentence, and a
   perfectly ordinary success code. :func:`judge_draw_failures` reads the status, so this
   is refused rather than scored on the fragment.
3. At a 4,096 and at a 2,048 token budget the judge spent the *entire* budget on
   reasoning and returned zero visible characters and no verdict. The largest *total*
   output observed was 20,004 tokens, 15,202 of them reasoning, so the visible part of
   that same call was 4,802. A budget chosen from the size of the answer is therefore the
   wrong quantity by a factor of four; the reasoning is what has to fit.
4. Judge sampling noise is a pooled sd of **0.326 points out of 10** over 23 draws on two
   tasks whose means were 2.5 and 3.3. That is an order of magnitude tighter
   than ResearchClawBench's judge — and it is measured *at three points*. The sd at seven
   points, which is where the paper's pass threshold sits, is unmeasured, and
   :data:`FS_JUDGE_NOISE_NOTE` says so in the same breath as the number so the two cannot
   be quoted apart.

**One draw's spread is unmeasured, never 0.0.** A zero there is the most expensive kind
of wrong: it reads as "this judge is deterministic", asserted from exactly the evidence
that cannot show it.

**The whole path was run once against a published figure, and it landed inside the noise.**
A direct ``claude-opus-4-5`` arm answered a balanced 21-task draw — seven physics, seven
chemistry, seven biology — and every answer was graded through this file's rules: the
prompt above byte for byte (same sha256), the ``output[]`` reader, the refusal clauses,
``gpt-5.1`` at high effort. 21 of 21 were judged and no judge call failed. Mean 4.125 out
of 10, median 4.0, min 0.0, max 8.3, across-task sd 2.345; by subject biology 4.874,
chemistry 4.282, physics 3.220; 3 of the 21 answers reached the paper's seven-point
threshold, a pass rate of **14.3%**. arXiv:2601.21165 reports Claude Opus 4.5 at **17.5%**
over all sixty tasks at thirty trials each under a GPT-5 judge. Twenty-one Bernoulli draws
at the observed rate carry a standard deviation of about 7.6 percentage points, so 14.3
and 17.5 are one number as far as this evidence can distinguish them.

That is corroboration of the path, not comparability of the instruments, and "the judge is
not the paper's judge" above still stands exactly as written: the judge is ``gpt-5.1`` and
not the paper's GPT-5, the population is 21 tasks and not 60, each is one draw and not
thirty, so **no total this file produces may be quoted beside the paper's table**. What
the agreement buys is narrower and worth having anyway. Every other check on this file is
internal — the prompt matches a fixture this repository wrote, the verdicts match
responses this repository recorded — and a prompt, a reader or a refusal rule that was
quietly wrong would fail all of them together and none of them visibly. An externally
published number is the one oracle here that was not produced by the same machine, and a
broken path does not land within one sd of it by accident.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping, Sequence

from .frontierscience import FS_DATASET_POINTS_PER_ROW, FsRow


#: Verbatim from arXiv:2601.21165 Appendix B. The misspelling "attemped" is in the paper
#: and is preserved on purpose: this is the string the published numbers were produced
#: with, and a judge prompt that has been silently improved is a different instrument
#: wearing the same citation. ``tests/test_fs_scoring.py`` pins it byte-for-byte against
#: a fixture, so correcting the typo fails the suite rather than the review.
FS_JUDGE_PROMPT = """You are grading a science exam.

You will be given the problem, attempted answer, and a rubric to grade the answer. The rubric will total up to 10 points.

Evaluate the attemped answer against the provided rubric. Pay close attention to detail and grade it strictly, but fairly. Only evaluate against the rubric, as you yourself should not make any judgements (e.g., even if you think the answer is correct but rubric is wrong, you should treat the rubric as the gold standard). Return the absolute total number of points earned (it can be a decimal based on the rubric). ***

The problem: {problem}

***

The rubric: {rubric}

***

The attempted answer: {answer}

***

First, think step-by-step about each rubric item. Explain your reasoning for each rubric item. Then, tally the points up and write VERDICT: <total_points> in the last line of your response, no other text. For example, VERDICT: 2.5 or VERDICT: 8."""

#: Digest of the template above, recorded in every result. The prompt is the instrument;
#: two totals produced by two different prompts are two different measurements, and the
#: only way a reader six months out can tell is if each result says which one it used.
FS_JUDGE_PROMPT_SHA256 = hashlib.sha256(FS_JUDGE_PROMPT.encode("utf-8")).hexdigest()

#: Anchored at both ends of a line, ``MULTILINE``, and the **last** match is the answer.
#: The prompt says "in the last line of your response", and judges restate a running
#: subtotal while they work; a first-match read of a response that says ``VERDICT: 3``
#: mid-reasoning and settles on 7.5 publishes 3. Both ``VERDICT: 0`` and
#: ``VERDICT: 2.675`` were observed on the live endpoint, so the decimal branch is not
#: hypothetical and neither is the bare integer — and **so is the emphasised branch**:
#: 1 of the 29 recorded judge calls, ``noise_19_draw1``, closes a complete 15,183-character
#: judgement with ``**VERDICT: 2.725**``. A pattern that admits only the bare form refuses
#: that response, and the refusal is indistinguishable from a judge that never tallied.
#: So ``*`` is tolerated around the token and around the number, and so is a leading ``$``
#: — that one is not observed here, it is carried over from the reader the endpoint probe
#: ran, which tolerated ``\$?\**`` and is therefore the reader the "29 of 29 parsed" claim
#: was originally measured with. What is *not* relaxed is the line anchor: it is the only
#: thing separating a verdict from a sentence that mentions one, and
#: ``tests/test_fs_scoring.py`` holds a case on each side of it.
FS_VERDICT_PATTERN = re.compile(
    r"^[\s*]*VERDICT:[\s*]*\$?[\s*]*([0-9]+(?:\.[0-9]+)?)[\s*$]*$", re.MULTILINE
)

#: Pooled standard deviation of the judge over repeated draws on one unchanged answer:
#: 23 draws across two tasks, dof 21. Small enough that one draw per task is defensible,
#: which is the only reason a sixty-task paired trial fits in an afternoon of judging.
FS_JUDGE_SAMPLING_SD = 0.326

#: How many draws that estimate rests on. Printed with the number because a standard
#: deviation without its sample size is a claim about precision with no precision.
FS_JUDGE_SAMPLING_DRAWS = 23

#: The sentence that travels with the number, everywhere the number is printed. The two
#: tasks it was measured on averaged 2.528 and 3.270; the paper's pass threshold is 7,
#: and the dispersion there is not something this estimate can be stretched to cover.
#: Saying "UNMEASURED" out loud is cheaper than a reader assuming the band is flat.
FS_JUDGE_NOISE_NOTE = (
    f"one draw carries about +/-{FS_JUDGE_SAMPLING_SD:.2f} points of gpt-5.1 judge sampling "
    f"noise (pooled sd over {FS_JUDGE_SAMPLING_DRAWS} draws on two tasks whose means were "
    "2.5 and 3.3; the sd at 7 points is UNMEASURED)"
)

#: The paper calls an answer correct at seven rubric points or better. Recorded beside
#: every total rather than applied to it: on the endpoint probe's hand-written answers the
#: levels were 0.0 to 3.3, where a pass count is all zeros and carries no comparison. On a
#: real arm it is not degenerate — the 21-task ``claude-opus-4-5`` draw in this module's
#: docstring scored 0.0 to 8.3 and passed 3 of 21 — but the threshold is still applied by
#: the reader, at whatever population they can name, and never folded into a total here.
FS_PASS_THRESHOLD = 7.0

#: Schema tag on every result file. Versioned because the fields below are read by a
#: driver that will outlive this shape, and an unversioned document that gains a field is
#: indistinguishable from one that lost it.
FS_RESULT_SCHEMA = "fs_score/1"


class ScoringRefused(ValueError):
    """A total that is not a measurement, raised rather than returned.

    Same shape as :class:`tools.score_rcb_run.ScoringRefused` and for the same reason:
    the refusal used to live only in ``main`` there, so anything that imported the
    scoring function got back a dict whose total already had the failed calls folded in
    as zeros, with no exception and no flag. The result rides on the exception so a
    caller can still show the per-draw table, which is what says whether one call was
    flaky or the whole judge is down.
    """

    def __init__(self, message: str, result: Mapping[str, Any], reasons: Sequence[str]) -> None:
        super().__init__(message)
        self.result = dict(result)
        self.reasons = list(reasons)


def render_judge_prompt(row: FsRow, answer: str) -> str:
    """The paper's prompt with this task's problem, this task's rubric, and the answer.

    Substitution only. ``str.format`` reads placeholders out of the *template* and never
    rescans what it substitutes, so a rubric full of LaTeX braces goes in unharmed — and
    a test asserts that the rubric slice of the result is byte-equal to
    :attr:`FsRow.rubric`, because the one change that would be invisible here is a
    well-meant unescape of the ``&gt;`` that one row's author left behind.
    """
    return FS_JUDGE_PROMPT.format(problem=row.problem, rubric=row.rubric, answer=answer)


def response_text(payload: Mapping[str, Any]) -> str:
    """The visible text of a Responses API payload, and nothing else.

    ``output_text`` is ``null`` on this endpoint, so the text has to be assembled from
    ``output[]``. The filter on ``type == "message"`` is the contract rather than
    housekeeping: the verdict is defined as the last line, and joining a reasoning item's
    text in would move whatever is last.
    """
    parts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        for chunk in item.get("content") or []:
            if not isinstance(chunk, Mapping):
                continue
            text = chunk.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def parse_verdict(text: str) -> float | None:
    """The last ``VERDICT: <n>`` line, or ``None``. Never a default, never a zero.

    ``None`` rather than ``0.0`` because a real ``VERDICT: 0`` is a routine outcome here
    — a bad answer scored exactly that on three tasks — so the two have to be different
    values or a broken judge and a bad answer become the same row in the table.
    """
    matches = FS_VERDICT_PATTERN.findall(text or "")
    if not matches:
        return None
    return float(matches[-1])


def judge_draw_failures(
    payload: Mapping[str, Any],
    text: str,
    *,
    rubric_points_total: float = FS_DATASET_POINTS_PER_ROW,
) -> list[str]:
    """Every reason this draw is not a score. Empty means the number can be used.

    Five clauses, each of which was observed rather than imagined. The status clause and
    the ``incomplete_details`` clause are two witnesses for the same event because the
    event arrives as **HTTP 200**: nothing in the transport says anything is wrong, and a
    scorer that reads only the body gets 636 characters of a sentence that stops in the
    middle. The empty-text clause is the 4,096-token budget, where the judge spent
    everything on reasoning and returned no characters at all. The missing-verdict clause
    is the ordinary parse failure. The range clause catches the one arithmetic error a
    judge can make that still looks like an answer.
    """
    reasons: list[str] = []
    status = payload.get("status")
    if status != "completed":
        reasons.append(f"judge response status is {status!r}, not 'completed'")
    details = payload.get("incomplete_details")
    reason = details.get("reason") if isinstance(details, Mapping) else None
    if reason:
        reasons.append(f"judge response was incomplete: {reason}")
    if not (text or "").strip():
        reasons.append("judge returned no visible text (the whole budget went on reasoning)")
    value = parse_verdict(text)
    if value is None:
        reasons.append("no `VERDICT: <n>` line in the judge response")
        return reasons
    if not (0.0 <= value <= rubric_points_total + 1e-9):
        reasons.append(f"verdict {value} is outside [0, {rubric_points_total}]")
    return reasons


def draw_record(
    payload: Mapping[str, Any],
    *,
    index: int,
    latency_seconds: float,
    raw_path: str = "",
    rubric_points_total: float = FS_DATASET_POINTS_PER_ROW,
) -> dict[str, Any]:
    """One judge call, as the row it becomes in the result file.

    Pure on purpose, and it is the only place a payload is turned into points. The
    network half hands the payload straight here, so the rule that decides whether a call
    counted is unit-tested against recorded responses rather than exercised only by
    spending money.

    ``points`` is ``None`` whenever :func:`judge_draw_failures` says anything at all,
    including when a verdict *was* parsed but the response was truncated — a tally at the
    end of a response that was cut off is a tally over the items the judge got to.
    """
    text = response_text(payload)
    failures = judge_draw_failures(payload, text, rubric_points_total=rubric_points_total)
    usage = payload.get("usage") if isinstance(payload.get("usage"), Mapping) else {}
    details = usage.get("output_tokens_details")
    reasoning = details.get("reasoning_tokens") if isinstance(details, Mapping) else None
    incomplete = payload.get("incomplete_details")
    verdict = parse_verdict(text)
    return {
        "index": index,
        "points": None if failures else verdict,
        "status": payload.get("status"),
        "incomplete_reason": incomplete.get("reason") if isinstance(incomplete, Mapping) else None,
        "output_tokens": usage.get("output_tokens"),
        "reasoning_tokens": reasoning,
        "visible_chars": len(text),
        "verdict_matches": len(FS_VERDICT_PATTERN.findall(text)),
        "latency_seconds": round(float(latency_seconds), 2),
        "raw_path": raw_path,
        "failures": failures,
    }


def format_spread(spread: float | None, draws: int) -> str:
    """One phrasing for every place a dispersion is printed, including its absence.

    The single-draw branch carries :data:`FS_JUDGE_NOISE_NOTE` rather than leaving the
    caller to remember it. A dispersion field reading ``unmeasured`` invites the reader to
    supply their own guess, and the guess that costs the most is "so it is small".
    """
    if spread is None:
        if draws == 1:
            return f"unmeasured (1 draw); {FS_JUDGE_NOISE_NOTE}"
        if draws == 0:
            return "unmeasured (no draws)"
        return f"unmeasured ({draws} draws, at least one of which was refused)"
    return f"spread {spread:.3f} over {draws} draws"


def aggregate_draws(draws: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Fold N judge passes over one answer into a total, or into no total at all.

    Averaging is the easy half. The half that matters is that a single failed draw takes
    the total away rather than being averaged around: with ``points`` of ``None`` the
    mean would either crash or, far worse, quietly count the failure as a zero and pull
    a 3.0 down to 1.5.
    """
    points = [draw.get("points") for draw in draws]
    usable = [float(value) for value in points if isinstance(value, (int, float))]
    failures = [reason for draw in draws for reason in draw.get("failures") or []]
    complete = bool(draws) and len(usable) == len(draws)
    spread = (max(usable) - min(usable)) if complete and len(usable) > 1 else None
    return {
        "total_score": (sum(usable) / len(usable)) if complete else None,
        "total_scores": list(points),
        "total_spread": spread,
        "spread_text": format_spread(spread, len(draws)),
        "judge_calls": len(draws),
        "judge_failures": failures,
    }


def refusal_reasons(
    draws: Sequence[Mapping[str, Any]], *, draws_requested: int
) -> list[str]:
    """Every way this total is a number rather than a measurement.

    Pure and separate from anything that calls a judge, so the rule is testable without a
    key. The count clauses are the same failure as the first one, one step earlier: zero
    draws aggregate to a total of ``None`` and a result file that still validates, and a
    run that asked for three draws and recorded two has thrown away the only evidence
    about how stable the remaining two are.
    """
    reasons: list[str] = []
    for draw in draws:
        for reason in draw.get("failures") or []:
            reasons.append(f"draw {draw.get('index')}: {reason}")
    if not draws:
        reasons.append("no judge draws were recorded, so the total is a total over nothing")
    elif len(draws) != draws_requested:
        reasons.append(
            f"{len(draws)} draw(s) recorded against {draws_requested} requested; the "
            "missing ones are absent from the total rather than visible in it"
        )
    return reasons


def build_result(
    *,
    row: FsRow,
    dataset: Mapping[str, Any],
    answer: Mapping[str, Any],
    judge: Mapping[str, Any],
    draws: Sequence[Mapping[str, Any]],
    draws_requested: int,
    scored_at: str,
    code_version: str,
    pass_threshold: float = FS_PASS_THRESHOLD,
) -> dict[str, Any]:
    """The whole ``fs_score/1`` document, assembled from parts nobody had to invent.

    *scored_at* and *code_version* are arguments rather than calls. Reading a clock or
    shelling out to git in here would make the document depend on when and where it was
    built, and the one property this function needs is that the same inputs produce the
    same bytes — which is what lets a regression test assert a whole result file instead
    of picking three fields out of it.

    ``passed`` is ``None`` when there is no total. ``False`` would be a claim: it says
    the answer did not reach seven points, which is exactly what a refused draw cannot
    tell anyone.
    """
    aggregate = aggregate_draws(draws)
    reasons = refusal_reasons(draws, draws_requested=draws_requested)
    total = aggregate["total_score"]
    judge_block = dict(judge)
    judge_block.setdefault("prompt_template_sha256", FS_JUDGE_PROMPT_SHA256)
    return {
        "schema": FS_RESULT_SCHEMA,
        "task": row.task_block(),
        "dataset": dict(dataset),
        "answer": dict(answer),
        "judge": judge_block,
        "draws_requested": draws_requested,
        "draws": [dict(draw) for draw in draws],
        "total_score": total,
        "total_scores": aggregate["total_scores"],
        "total_spread": aggregate["total_spread"],
        "spread_text": aggregate["spread_text"],
        "pass_threshold": pass_threshold,
        "passed": None if total is None else bool(total >= pass_threshold),
        "judge_calls": aggregate["judge_calls"],
        "judge_failures": aggregate["judge_failures"],
        "refused": bool(reasons),
        "refusal_reasons": reasons,
        "scored_at": scored_at,
        "scorer_version": FS_RESULT_SCHEMA,
        "code_version": code_version,
    }
