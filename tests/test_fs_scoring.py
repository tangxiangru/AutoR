"""A judge failure scored as zero is the defect this module exists against.

ResearchClawBench's own scorer writes ``{"score": 0}`` when a judge call fails, which is
indistinguishable in the output from a criterion the report genuinely missed: one run's
honest total of 37.0 appeared on screen as 19.5 and nothing said which two items were
failures. FrontierScience makes that trap sharper rather than softer, because here a zero
is *common and correct* — a deliberately bad two-sentence answer was graded on three real
tasks and scored exactly 0.000 on all three, with the judge giving a separate reason for
every rubric item. So a real zero and a broken judge have to be different values, all the
way through, or the two become the same row in a table.

Four failure shapes were produced against the live endpoint and each one has a test here:

* a **truncated** response, which arrives as HTTP 200 with ``status == "incomplete"`` and
  ``incomplete_details.reason == "max_output_tokens"`` — 32,000 output tokens of which
  31,817 were reasoning, and 636 visible characters that stop mid-sentence;
* an **empty** response, which is what a 4,096 or 2,048 token budget produced: the whole
  budget went on reasoning and not one visible character came back;
* a response with **no verdict line** at all;
* a verdict **outside** the rubric's range.

The last group of tests holds the two properties that are not about failure at all: the
judge prompt is the paper's, byte for byte including its typo, and the rubric reaches the
judge exactly as the dataset wrote it. A prompt that has been silently improved is a
different instrument, and the only way to notice is to pin it.
"""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path

from src.frontierscience import FS_DATASET_POINTS_PER_ROW, FsRow, parse_rubric
from src.fs_scoring import (
    FS_JUDGE_NOISE_NOTE,
    FS_JUDGE_PROMPT,
    FS_JUDGE_PROMPT_SHA256,
    FS_JUDGE_SAMPLING_DRAWS,
    FS_JUDGE_SAMPLING_SD,
    FS_PASS_THRESHOLD,
    FS_RESULT_SCHEMA,
    FS_VERDICT_PATTERN,
    ScoringRefused,
    aggregate_draws,
    build_result,
    draw_record,
    format_spread,
    judge_draw_failures,
    parse_verdict,
    refusal_reasons,
    render_judge_prompt,
    response_text,
)

REPO = Path(__file__).resolve().parent.parent
PROMPT_FIXTURE = REPO / "tests" / "fixtures" / "fs_judge_prompt.txt"
SYNTHETIC = REPO / "tests" / "fixtures" / "fs_synthetic.jsonl"


def a_row() -> FsRow:
    """One synthetic task. Never a real one: the rubric text is not committed here."""
    payload = json.loads(SYNTHETIC.read_text(encoding="utf-8").splitlines()[0])
    return FsRow.from_payload(0, payload)


def completed(text: str, *, output_tokens: int = 1200, reasoning_tokens: int = 900) -> dict:
    """A Responses payload in the shape this endpoint actually returns.

    ``output_text`` is ``null`` here because it is null there, and the reasoning item is
    present because it is present there — the two together are what make
    :func:`response_text`'s filter testable rather than decorative.
    """
    return {
        "status": "completed",
        "output_text": None,
        "output": [
            {"type": "reasoning", "content": []},
            {"type": "message", "content": [{"type": "output_text", "text": text}]},
        ],
        "usage": {
            "input_tokens": 5000,
            "output_tokens": output_tokens,
            "output_tokens_details": {"reasoning_tokens": reasoning_tokens},
        },
    }


def truncated() -> dict:
    """The measured truncation: HTTP 200, ``incomplete``, a fragment, and no verdict."""
    payload = completed("The neutral molecular mass of the unknown is therefore approximately")
    payload["status"] = "incomplete"
    payload["incomplete_details"] = {"reason": "max_output_tokens"}
    payload["usage"]["output_tokens"] = 32000
    payload["usage"]["output_tokens_details"]["reasoning_tokens"] = 31817
    return payload


class ThePromptIsThePapersTest(unittest.TestCase):
    """The instrument, pinned. A quietly improved prompt is a different measurement."""

    def test_the_template_is_byte_equal_to_the_committed_fixture(self) -> None:
        self.assertEqual(PROMPT_FIXTURE.read_text(encoding="utf-8"), FS_JUDGE_PROMPT + "\n")

    def test_the_papers_misspelling_is_preserved(self) -> None:
        """`attemped` is in arXiv:2601.21165 Appendix B. Correcting it changes the judge."""
        self.assertIn("Evaluate the attemped answer against the provided rubric", FS_JUDGE_PROMPT)
        self.assertIn("The attempted answer:", FS_JUDGE_PROMPT)

    def test_the_template_digest_is_the_digest_of_the_template(self) -> None:
        import hashlib

        self.assertEqual(
            FS_JUDGE_PROMPT_SHA256, hashlib.sha256(FS_JUDGE_PROMPT.encode("utf-8")).hexdigest()
        )

    def test_the_prompt_asks_for_the_verdict_the_pattern_reads(self) -> None:
        """Two halves of one contract: the sentence that asks and the regex that reads."""
        self.assertIn("write VERDICT: <total_points> in the last line", FS_JUDGE_PROMPT)
        self.assertIsNotNone(FS_VERDICT_PATTERN.search("VERDICT: 2.5"))


class TheRubricReachesTheJudgeUnchangedTest(unittest.TestCase):
    """No unescaping, no normalisation, no reflow. The raw field or nothing."""

    def setUp(self) -> None:
        self.row = a_row()
        self.prompt = render_judge_prompt(self.row, "an answer with {braces} and \\LaTeX in it")

    def test_the_rubric_slice_of_the_prompt_is_byte_equal_to_the_raw_field(self) -> None:
        start = self.prompt.index("The rubric: ") + len("The rubric: ")
        self.assertEqual(self.prompt[start : start + len(self.row.rubric)], self.row.rubric)

    def test_the_problem_and_the_answer_go_in_verbatim_too(self) -> None:
        self.assertIn(self.row.problem, self.prompt)
        self.assertIn("an answer with {braces} and \\LaTeX in it", self.prompt)

    def test_an_html_entity_survives_into_the_prompt(self) -> None:
        """The one row whose author wrote `&gt;` is the reason this is a test and not a
        comment: unescaping it would be an improvement, and improvements are the defect."""
        self.assertIn("theta &gt; 0", self.row.rubric)
        self.assertIn("theta &gt; 0", self.prompt)
        self.assertNotIn("theta > 0", self.prompt)

    def test_braces_in_the_substituted_text_are_not_re_scanned(self) -> None:
        """`str.format` reads placeholders out of the template only, which is what lets a
        rubric full of LaTeX braces through; a `%`-style or a second format pass would not."""
        row = replace(a_row(), rubric="Points: 10.0, Item: \\frac{a}{b} and {answer}")
        prompt = render_judge_prompt(row, "ANSWERTEXT")
        self.assertIn("\\frac{a}{b} and {answer}", prompt)
        self.assertEqual(prompt.count("ANSWERTEXT"), 1)


class TheVisibleTextIsTheMessageItemTest(unittest.TestCase):
    """`output_text` is null on this endpoint and a reasoning item must not be joined in."""

    def test_the_text_comes_out_of_the_message_item(self) -> None:
        self.assertEqual(response_text(completed("hello")), "hello")

    def test_a_reasoning_item_is_not_joined_in(self) -> None:
        """The contract is 'VERDICT on the last line'. Anything appended after the message
        moves what is last, and a reasoning item that ever carries text would do exactly that."""
        payload = completed("VERDICT: 3.0")
        payload["output"].append(
            {"type": "reasoning", "content": [{"type": "text", "text": "wait, VERDICT: 9.0"}]}
        )
        self.assertEqual(response_text(payload), "VERDICT: 3.0")
        self.assertEqual(parse_verdict(response_text(payload)), 3.0)

    def test_a_payload_with_no_output_yields_an_empty_string_not_a_crash(self) -> None:
        self.assertEqual(response_text({}), "")
        self.assertEqual(response_text({"output": None}), "")
        self.assertEqual(response_text({"output": ["not a mapping"]}), "")


class TheVerdictIsTheLastOneTest(unittest.TestCase):
    """Nine readings, including the three the live endpoint produced."""

    def test_a_decimal_verdict_parses(self) -> None:
        self.assertEqual(parse_verdict("reasoning\n\nVERDICT: 2.675"), 2.675)

    def test_an_integer_verdict_parses(self) -> None:
        self.assertEqual(parse_verdict("VERDICT: 0"), 0.0)

    def test_the_last_verdict_wins(self) -> None:
        """A judge that restates a running subtotal and settles at the end is the ordinary
        case; a first-match read publishes the subtotal."""
        self.assertEqual(parse_verdict("VERDICT: 3\nmore thinking\nVERDICT: 7.5"), 7.5)

    def test_a_verdict_wrapped_in_markdown_emphasis_is_read(self) -> None:
        """The first line here is measured, not defensive. ``noise_19_draw1`` of the
        endpoint probe is a complete 15,183-character judgement whose last line is
        ``**VERDICT: 2.725**``, and a pattern that admits only the bare form reports it as
        "no verdict line" — the same output a judge that never tallied produces. The other
        two are the neighbouring shapes the same tolerance admits, pinned so that narrowing
        the pattern back to the one observed spelling is a decision and not a slip."""
        self.assertEqual(parse_verdict("per-item reasoning\n\n**VERDICT: 2.725**"), 2.725)
        self.assertEqual(parse_verdict("**VERDICT:** 8"), 8.0)
        self.assertEqual(parse_verdict("*VERDICT: 0*"), 0.0)

    def test_a_verdict_that_is_not_alone_on_its_line_is_not_read(self) -> None:
        self.assertIsNone(parse_verdict("the tally says VERDICT: 8 which I doubt"))

    def test_emphasis_does_not_buy_a_verdict_the_line_anchor_would_refuse(self) -> None:
        """The control for the test above it. Widening the pattern to admit ``**`` must not
        turn a sentence that mentions a verdict into one: the anchor is the whole rule, and
        a judge that writes "the tally says **VERDICT: 8**, which I doubt" mid-prose is
        restating a subtotal, not settling on it."""
        self.assertIsNone(parse_verdict("the tally says **VERDICT: 8**, which I doubt"))
        self.assertIsNone(parse_verdict("I nearly wrote **VERDICT: 9.5** here"))
        self.assertIsNone(parse_verdict("**VERDICT: 3** is what a worse answer would earn"))

    def test_the_last_verdict_still_wins_when_one_of_them_is_emphasised(self) -> None:
        """The widened pattern must not change which match is taken."""
        self.assertEqual(parse_verdict("VERDICT: 3\nmore thinking\n**VERDICT: 7.5**"), 7.5)
        self.assertEqual(parse_verdict("**VERDICT: 3**\nmore thinking\nVERDICT: 7.5"), 7.5)

    def test_no_verdict_yields_none_rather_than_zero(self) -> None:
        """The whole point. `None` is distinguishable from the 0.000 a bad answer earns."""
        self.assertIsNone(parse_verdict("I graded every item but forgot the last line."))
        self.assertIsNone(parse_verdict(""))

    def test_surrounding_whitespace_on_the_verdict_line_is_tolerated(self) -> None:
        self.assertEqual(parse_verdict("  VERDICT: 4.25  "), 4.25)


class ADrawIsAMeasurementOrItIsNothingTest(unittest.TestCase):
    """One positive and one negative case for each of the five failure clauses."""

    def test_a_completed_response_with_a_verdict_has_no_failures(self) -> None:
        self.assertEqual(judge_draw_failures(completed("VERDICT: 2.5"), "VERDICT: 2.5"), [])

    def test_a_status_that_is_not_completed_is_a_failure(self) -> None:
        payload = completed("VERDICT: 2.5")
        payload["status"] = "in_progress"
        self.assertIn(
            "judge response status is 'in_progress', not 'completed'",
            judge_draw_failures(payload, "VERDICT: 2.5"),
        )

    def test_a_truncated_response_is_refused_even_though_it_is_http_200(self) -> None:
        payload = truncated()
        reasons = judge_draw_failures(payload, response_text(payload))
        self.assertTrue(any("incomplete: max_output_tokens" in reason for reason in reasons))

    def test_an_empty_body_is_a_failure_rather_than_a_zero(self) -> None:
        payload = completed("", output_tokens=4096, reasoning_tokens=4096)
        reasons = judge_draw_failures(payload, "")
        self.assertTrue(any("no visible text" in reason for reason in reasons))

    def test_a_missing_verdict_is_a_failure(self) -> None:
        reasons = judge_draw_failures(completed("I graded it."), "I graded it.")
        self.assertIn("no `VERDICT: <n>` line in the judge response", reasons)

    def test_a_verdict_above_the_rubric_total_is_a_failure(self) -> None:
        reasons = judge_draw_failures(
            completed("VERDICT: 11"), "VERDICT: 11", rubric_points_total=10.0
        )
        self.assertTrue(any("outside [0, 10.0]" in reason for reason in reasons))

    def test_a_verdict_of_exactly_the_rubric_total_is_accepted(self) -> None:
        """The other side of the bound. Ten out of ten is a legal score, not an overflow."""
        self.assertEqual(
            judge_draw_failures(completed("VERDICT: 10"), "VERDICT: 10", rubric_points_total=10.0),
            [],
        )

    def test_a_verdict_of_zero_is_a_score_and_not_a_failure(self) -> None:
        """Measured: a bad two-sentence answer scored exactly 0.000 on three real tasks."""
        record = draw_record(completed("VERDICT: 0"), index=0, latency_seconds=11.2)
        self.assertEqual(record["points"], 0.0)
        self.assertEqual(record["failures"], [])


class ADrawRecordIsTheRowItBecomesTest(unittest.TestCase):
    """What the result file says about one judge call, and what it refuses to say."""

    def test_a_good_draw_carries_its_points_and_its_accounting(self) -> None:
        record = draw_record(
            completed("reasoning\nVERDICT: 2.675", output_tokens=12793, reasoning_tokens=9217),
            index=0,
            latency_seconds=81.89,
            raw_path="/outside/raw/fs000.d0.json",
        )
        self.assertEqual(record["points"], 2.675)
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["output_tokens"], 12793)
        self.assertEqual(record["reasoning_tokens"], 9217)
        self.assertEqual(record["verdict_matches"], 1)
        self.assertEqual(record["latency_seconds"], 81.89)
        self.assertEqual(record["raw_path"], "/outside/raw/fs000.d0.json")

    def test_a_truncated_draw_has_no_points_even_if_a_verdict_was_parsed(self) -> None:
        """A tally at the end of a response that was cut off is a tally over the items the
        judge reached, and there is no way to tell which ones those were."""
        payload = truncated()
        payload["output"][1]["content"][0]["text"] += "\n\nVERDICT: 1.5"
        record = draw_record(payload, index=0, latency_seconds=216.88)
        self.assertIsNone(record["points"])
        self.assertEqual(record["incomplete_reason"], "max_output_tokens")
        self.assertTrue(record["failures"])

    def test_a_draw_with_no_usage_block_records_none_rather_than_zero(self) -> None:
        record = draw_record({"status": "completed", "output": []}, index=1, latency_seconds=0.4)
        self.assertIsNone(record["output_tokens"])
        self.assertIsNone(record["reasoning_tokens"])
        self.assertEqual(record["visible_chars"], 0)


class DispersionIsNeverInventedTest(unittest.TestCase):
    """One draw has no spread, and saying 0.0 there would be a claim about the judge."""

    def test_one_draw_reports_its_dispersion_as_unmeasured_not_as_zero(self) -> None:
        merged = aggregate_draws([draw_record(completed("VERDICT: 3"), index=0, latency_seconds=1)])
        self.assertIsNone(merged["total_spread"])
        self.assertIn("unmeasured (1 draw)", merged["spread_text"])
        self.assertNotIn("0.0", merged["spread_text"].split(";")[0])

    def test_the_single_draw_text_carries_the_measured_noise_band(self) -> None:
        self.assertIn(FS_JUDGE_NOISE_NOTE, format_spread(None, 1))

    def test_the_noise_band_says_the_seven_point_case_is_unmeasured(self) -> None:
        """The sd was measured on two tasks averaging 2.528 and 3.270 points, and the pass
        threshold is 7. Quoting the number without that is quoting it out of its range."""
        self.assertIn("0.33", FS_JUDGE_NOISE_NOTE)
        self.assertIn(str(FS_JUDGE_SAMPLING_DRAWS), FS_JUDGE_NOISE_NOTE)
        self.assertIn("UNMEASURED", FS_JUDGE_NOISE_NOTE)
        self.assertAlmostEqual(FS_JUDGE_SAMPLING_SD, 0.326)

    def test_the_two_means_the_band_quotes_are_the_ones_that_were_measured(self) -> None:
        """They were written as 2.5 and 3.2. Recomputed from the recorded draws the means
        are 2.528 over the first task's eight and 3.270 over the second task's fifteen, so
        the second rounds to 3.3 — an arithmetic slip, and the kind that survives because a
        rounded mean inside a sentence reads as prose rather than as a number."""
        self.assertIn("2.5 and 3.3", FS_JUDGE_NOISE_NOTE)
        self.assertNotIn("3.2;", FS_JUDGE_NOISE_NOTE)

    def test_the_spread_is_reported_once_there_is_one(self) -> None:
        draws = [
            draw_record(completed("VERDICT: 2.5"), index=0, latency_seconds=1),
            draw_record(completed("VERDICT: 3.0"), index=1, latency_seconds=1),
        ]
        merged = aggregate_draws(draws)
        self.assertAlmostEqual(merged["total_spread"], 0.5)
        self.assertEqual(merged["spread_text"], "spread 0.500 over 2 draws")
        self.assertAlmostEqual(merged["total_score"], 2.75)

    def test_a_failed_draw_removes_the_total_rather_than_averaging_around_it(self) -> None:
        draws = [
            draw_record(completed("VERDICT: 3.0"), index=0, latency_seconds=1),
            draw_record(truncated(), index=1, latency_seconds=1),
        ]
        merged = aggregate_draws(draws)
        self.assertIsNone(merged["total_score"])
        self.assertIsNone(merged["total_spread"])
        self.assertEqual(merged["total_scores"], [3.0, None])
        self.assertTrue(merged["judge_failures"])

    def test_aggregating_nothing_is_a_total_over_nothing_and_says_so(self) -> None:
        merged = aggregate_draws([])
        self.assertIsNone(merged["total_score"])
        self.assertEqual(merged["judge_calls"], 0)


class TheRefusalRuleTest(unittest.TestCase):
    """Three clauses, each with the case that passes it."""

    def _good(self, index: int = 0) -> dict:
        return draw_record(completed("VERDICT: 3"), index=index, latency_seconds=1)

    def test_a_fully_judged_run_is_not_refused(self) -> None:
        self.assertEqual(refusal_reasons([self._good()], draws_requested=1), [])

    def test_a_failed_draw_is_refused_and_named(self) -> None:
        reasons = refusal_reasons(
            [draw_record(truncated(), index=0, latency_seconds=1)], draws_requested=1
        )
        self.assertTrue(reasons)
        self.assertTrue(all(reason.startswith("draw 0:") for reason in reasons))

    def test_zero_draws_is_a_total_over_nothing(self) -> None:
        self.assertIn(
            "no judge draws were recorded, so the total is a total over nothing",
            refusal_reasons([], draws_requested=1),
        )

    def test_fewer_draws_than_requested_is_refused(self) -> None:
        reasons = refusal_reasons([self._good()], draws_requested=3)
        self.assertTrue(any("1 draw(s) recorded against 3 requested" in r for r in reasons))

    def test_the_refusal_carries_the_result_so_the_table_survives(self) -> None:
        refused = ScoringRefused("nope", {"total_score": None}, ["a reason"])
        self.assertEqual(refused.result, {"total_score": None})
        self.assertEqual(refused.reasons, ["a reason"])


class TheResultDocumentTest(unittest.TestCase):
    """`fs_score/1`: every field a reader needs to say what was measured."""

    def setUp(self) -> None:
        self.row = a_row()

    def _build(self, draws, requested=1):
        return build_result(
            row=self.row,
            dataset={"path": "/outside/research_test.jsonl", "sha256": "96c0434a", "rows": 60},
            answer={"path": "/outside/answer.md", "sha256": "abc", "chars": 1234},
            judge={"model": "gpt-5.1", "endpoint": "https://example.invalid/openai/v1"},
            draws=draws,
            draws_requested=requested,
            scored_at="2026-08-17T03:41:09Z",
            code_version="0b64ab8dda4d",
        )

    def test_the_document_has_the_schema_the_driver_reads(self) -> None:
        result = self._build([draw_record(completed("VERDICT: 7.5"), index=0, latency_seconds=8)])
        self.assertEqual(result["schema"], FS_RESULT_SCHEMA)
        for key in (
            "task", "dataset", "answer", "judge", "draws_requested", "draws", "total_score",
            "total_scores", "total_spread", "spread_text", "pass_threshold", "passed",
            "judge_calls", "judge_failures", "refused", "refusal_reasons", "scored_at",
            "scorer_version", "code_version",
        ):
            self.assertIn(key, result)

    def test_the_task_block_names_the_question_without_quoting_it(self) -> None:
        result = self._build([draw_record(completed("VERDICT: 7.5"), index=0, latency_seconds=8)])
        self.assertEqual(result["task"]["key"], self.row.key)
        self.assertEqual(result["task"]["rubric_sha256"], self.row.rubric_sha256)
        self.assertNotIn(self.row.rubric[:40], json.dumps(result))

    def test_the_prompt_template_digest_travels_with_every_result(self) -> None:
        result = self._build([draw_record(completed("VERDICT: 7.5"), index=0, latency_seconds=8)])
        self.assertEqual(result["judge"]["prompt_template_sha256"], FS_JUDGE_PROMPT_SHA256)

    def test_a_total_at_or_above_the_threshold_passes(self) -> None:
        result = self._build([draw_record(completed("VERDICT: 7"), index=0, latency_seconds=8)])
        self.assertEqual(result["pass_threshold"], FS_PASS_THRESHOLD)
        self.assertTrue(result["passed"])
        self.assertFalse(result["refused"])

    def test_a_refused_result_says_passed_is_unknown_rather_than_false(self) -> None:
        """`False` is a claim: it says the answer did not reach seven points, which is
        exactly what a refused draw cannot tell anyone."""
        result = self._build([draw_record(truncated(), index=0, latency_seconds=8)])
        self.assertIsNone(result["passed"])
        self.assertIsNone(result["total_score"])
        self.assertTrue(result["refused"])
        self.assertTrue(result["refusal_reasons"])

    def test_the_same_inputs_produce_the_same_bytes(self) -> None:
        """No clock and no subprocess in here, which is what lets a regression test assert
        a whole document instead of picking three fields out of it."""
        draws = [draw_record(completed("VERDICT: 4.5"), index=0, latency_seconds=8)]
        self.assertEqual(json.dumps(self._build(draws)), json.dumps(self._build(draws)))

    def test_the_rubric_total_the_draws_are_bounded_by_is_the_tasks_own(self) -> None:
        self.assertAlmostEqual(self.row.rubric_points_total, FS_DATASET_POINTS_PER_ROW)
        self.assertEqual(len(parse_rubric(self.row.rubric)), self.row.rubric_items)


if __name__ == "__main__":
    unittest.main()
