"""An unusable backend must not be turned into research-shaped output.

Every case here traces to one live run. Vertex quota was exhausted, every call returned
``429 RESOURCE_EXHAUSTED``, and AutoR manufactured a structurally valid Stage 01 summary that
passed validation and carried the run forward. The captured output from that run is used
verbatim below, because a fixture invented after the fact would only test what I already
believed.
"""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from src.backend_health import (
    AUTH,
    QUOTA,
    UPSTREAM,
    BackendUnavailable,
    classify,
    describe,
)
from src.manager import ResearchManager
from src.terminal_ui import TerminalUI
from src.utils import (
    STAGES,
    build_run_paths,
    ensure_run_config,
    ensure_run_layout,
    read_text,
    write_text,
)


STAGE_01 = STAGES[0]

#: Verbatim from the run that motivated this module.
REAL_429 = (
    "AutoR generated this local fallback stage draft because the primary attempt and repair "
    "did not produce a stage summary file.\n\n"
    'API Error: Request rejected (429) · [{"error":{"code":429,"message":"Quota exceeded for '
    "aiplatform.googleapis.com/us_multi_region_online_prediction_requests_per_base_model with "
    'base model: anthropic-claude-sonnet-4-5. Please submit a quota increase request.",'
    '"status":"RESOURCE_EXHAUSTED"}}]'
)


class ClassifyTests(unittest.TestCase):
    def test_the_real_captured_quota_failure_is_recognised(self) -> None:
        self.assertEqual(classify(REAL_429), QUOTA)

    def test_rejected_credentials_are_recognised(self) -> None:
        self.assertEqual(
            classify('API Error: Request rejected (403) · {"status":"PERMISSION_DENIED"}'), AUTH
        )
        self.assertEqual(classify("Error: authentication_error, invalid api key"), AUTH)

    def test_a_backend_that_is_down_is_recognised(self) -> None:
        self.assertEqual(classify("API Error: 503 UNAVAILABLE"), UPSTREAM)
        self.assertEqual(classify("Error: overloaded_error"), UPSTREAM)

    def test_nothing_is_classified_from_empty_or_ordinary_output(self) -> None:
        self.assertIsNone(classify(""))
        self.assertIsNone(classify("Wrote sources.json and claims.json. Stage complete."))

    def test_a_summary_discussing_rate_limits_is_not_a_dead_backend(self) -> None:
        # The false positive that would matter most: a Stage 01 survey about API economics
        # mentioning 429s must not abort the run.
        prose = (
            "## Key Results\n\n"
            "Prior work reports that 429 rate-limit responses dominate the quota literature, "
            "and that quota exceeded events cluster at peak hours.\n"
        )
        self.assertIsNone(classify(prose))

    def test_a_status_code_alone_is_not_enough(self) -> None:
        # Needs to look like a reported error, not merely contain a number.
        self.assertIsNone(classify("We sampled 429 households from the panel."))

    def test_quota_wins_over_the_broader_upstream_pattern(self) -> None:
        # A 429 body also contains "error"; the specific cause is the useful one to report.
        self.assertEqual(classify(REAL_429), QUOTA)


class DescribeTests(unittest.TestCase):
    def test_the_message_says_this_is_not_the_research_failing(self) -> None:
        text = describe(QUOTA, REAL_429)
        self.assertIn("quota is exhausted", text)
        self.assertIn("has not produced weak findings", text)

    def test_the_backend_excerpt_is_included_and_bounded(self) -> None:
        text = describe(QUOTA, "x" * 5000)
        self.assertIn("Backend said:", text)
        self.assertLess(len(text), 1500)

    def test_an_unknown_cause_still_produces_a_usable_message(self) -> None:
        self.assertIn("unusable", describe("something_else"))


class RefusalTests(unittest.TestCase):
    """The behaviour the live run exposed, pinned."""

    def _manager_and_paths(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        runs_dir = Path(tmp_dir.name) / "runs"
        runs_dir.mkdir()
        paths = build_run_paths(runs_dir / "20260101_000000")
        ensure_run_layout(paths)
        write_text(paths.user_input, "Goal")
        write_text(paths.memory, "# Approved Run Memory\n")
        ensure_run_config(paths, model="sonnet", venue="neurips_2025")
        operator = MagicMock()
        operator.model = "sonnet"
        operator.backend_name = "claude"
        manager = ResearchManager(
            project_root=Path(__file__).resolve().parent.parent,
            runs_dir=runs_dir,
            operator=operator,
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
        )
        return manager, paths

    def test_a_dead_backend_stops_the_run_instead_of_fabricating_a_draft(self) -> None:
        manager, paths = self._manager_and_paths()
        with self.assertRaises(BackendUnavailable) as ctx:
            manager._materialize_missing_stage_draft(
                paths=paths, stage=STAGE_01, attempt_no=1,
                source="primary attempt and repair", fallback_text=REAL_429,
            )
        self.assertEqual(ctx.exception.cause, QUOTA)
        # The thing that must not exist: a locally written summary that would pass validation.
        self.assertFalse(paths.stage_tmp_file(STAGE_01).exists())

    def test_the_cause_is_recorded_before_the_run_stops(self) -> None:
        manager, paths = self._manager_and_paths()
        with self.assertRaises(BackendUnavailable):
            manager._materialize_missing_stage_draft(
                paths=paths, stage=STAGE_01, attempt_no=1,
                source="primary attempt and repair", fallback_text=REAL_429,
            )
        log = read_text(paths.logs)
        self.assertIn("backend_unavailable", log)
        self.assertIn("RESOURCE_EXHAUSTED", log)

    def test_a_model_that_ran_and_wrote_badly_still_gets_its_fallback(self) -> None:
        # The fallback path is right when the model ran; only a dead backend loses it.
        manager, paths = self._manager_and_paths()
        result = manager._materialize_missing_stage_draft(
            paths=paths, stage=STAGE_01, attempt_no=1,
            source="primary attempt and repair",
            fallback_text="I explored the literature but ran out of turns before writing the file.",
        )
        self.assertTrue(paths.stage_tmp_file(STAGE_01).exists())
        self.assertTrue(result.stage_file_path.exists())

    def test_an_empty_capture_still_gets_its_fallback(self) -> None:
        manager, paths = self._manager_and_paths()
        manager._materialize_missing_stage_draft(
            paths=paths, stage=STAGE_01, attempt_no=1,
            source="primary attempt and repair", fallback_text="",
        )
        self.assertTrue(paths.stage_tmp_file(STAGE_01).exists())

    def test_the_run_reports_the_backend_rather_than_crashing(self) -> None:
        manager, paths = self._manager_and_paths()

        def explode(*_args, **_kwargs):
            raise BackendUnavailable(QUOTA, REAL_429)

        manager._walk_stages = explode
        self.assertFalse(manager._run_from_paths(paths))
        log = read_text(paths.logs)
        self.assertIn("run_aborted", log)
        self.assertIn("quota is exhausted", log)


class ResearchProseIsNotAnOutageTests(unittest.TestCase):
    """The two gates are supposed to be independent evidence. For four tokens they were not.

    `classify` requires a line to look like a reported error *and* to carry a recognised
    signature. But `RESOURCE_EXHAUSTED`, `PERMISSION_DENIED`, `UNAUTHENTICATED` and
    `UNAVAILABLE` were in *both* lists and both were matched with `re.IGNORECASE`, so for
    those four the requirement collapsed to "the text contains this English word once".
    ``\\bstatus\\b`` in the error-line gate and a bare ``\\b5\\d{2}\\b`` in the upstream
    signature composed the same way: `520\t  - Status: carried` is a line of AutoR's own
    stage prose and it satisfied both.

    Measured over 1,110 real stage outputs from the topology ablation's four run trees --
    model-written research prose, not backend output -- the old classifier reads **263 of
    them (23.7%) as a dead backend**, 257 `upstream` and 6 `auth`. The new one reads none.
    Trigger lines look like this one, from a stage summary:

        stress-tests delayed and unavailable Scotland-England boundary expansion

    That 23.7% is an *exposure*, not a fire rate: `classify` only runs from
    `_materialize_missing_stage_draft`, when the primary attempt and its repair both
    produced nothing. It was reached once in the first 3.7 hours of an 80-run ablation --
    and it fired, aborting `topo_linear/Chemistry_001` at 1 of 8 approved stages. That run
    then exited "completed" with exit code 0 and was scored 0.3 as if it were an attempt.
    The text that fired is not recoverable: the log preserves `truncate_text(..., 2000)`
    and the match was past the cut.
    """

    def test_an_english_sentence_using_the_word_unavailable_is_not_an_outage(self) -> None:
        self.assertIsNone(classify(
            "stress-tests delayed and unavailable Scotland-England boundary expansion "
            "among its scenarios, and Error: bars are omitted from Figure 4."))

    def test_a_prompt_echo_with_a_line_number_is_not_an_outage(self) -> None:
        """`520` is the line number and `Status:` is AutoR's own stage formatting."""
        self.assertIsNone(classify("520\t  - Status: carried | Tested by: H2; H3"))

    def test_the_word_internal_in_prose_is_not_an_outage(self) -> None:
        self.assertIsNone(classify(
            "Error: the internal representation is unavailable in this build."))

    def test_a_five_hundred_in_prose_is_not_an_outage(self) -> None:
        """No HTTP framing on the line, so the number is a number."""
        self.assertIsNone(classify("Error: 512 residues exceeded the context window."))

    def test_a_number_and_an_error_word_on_different_lines_do_not_compose(self) -> None:
        """Classification is per line. Joining them let two unrelated fragments add up."""
        self.assertIsNone(classify("Error: the fit did not converge\nn = 503 samples"))

    def test_the_grpc_constants_still_fire_in_upper_case(self) -> None:
        for text, expected in (
            ('API Error: 403 [{"error":{"code":403,"status":"PERMISSION_DENIED"}}]', AUTH),
            ("API Error: Request rejected (429) RESOURCE_EXHAUSTED", QUOTA),
            ('{"error":{"code":503,"status":"UNAVAILABLE"}}', UPSTREAM),
        ):
            with self.subTest(text=text):
                self.assertEqual(classify(text), expected)

    def test_a_real_403_from_this_box_still_fires(self) -> None:
        """The exact shape the eval-w nodes emit; 18 of 18 archived captures classify auth."""
        self.assertEqual(classify(
            "Failed to authenticate. API Error: 403 [{\"error\":{\"code\":403,"
            "\"message\":\"Request had insufficient authentication scopes.\","
            "\"status\":\"PERMISSION_DENIED\",\"details\":[{\"reason\":"
            "\"ACCESS_TOKEN_SCOPE_INSUFFICIENT\"}]}}]"), AUTH)

    def test_an_http_code_still_fires_where_the_line_frames_it_as_one(self) -> None:
        self.assertEqual(classify("API Error: 500 internal server error"), UPSTREAM)
        self.assertEqual(classify('{"type":"error","error":{"type":"overloaded_error"}}'), UPSTREAM)


if __name__ == "__main__":
    unittest.main()
