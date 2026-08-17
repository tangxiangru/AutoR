"""The scorer must not write a total it cannot stand behind, and must not leak the key.

Three failures this file is written against. Two of them have already happened once in
this repository, against ResearchClawBench's scorer; the third happened here, in the first
version of this file:

1. **A judge failure recorded as a score.** The stock scorer there writes ``{"score": 0}``
   for a failed call; an honest 37.0 was reported as 19.5 and nothing in the output said
   which items had failed. On FrontierScience a zero is a *legitimate* score — a bad
   two-sentence answer earned exactly 0.000 on three real tasks — so the two must never
   collapse. Here a refused total exits 1 and writes **nothing** to ``--out``, because the
   trial driver inherits the refusal from the file's absence.
2. **A budget that was declared and not passed.** ``JUDGE_TIME_LIMIT`` was read by no code
   at all in the other tool, and ``JUDGE_MAX_TOKENS`` only by the fallback judge, so on the
   default path the call went out with the client's defaults while two tests asserting the
   constants' *values* stayed green. Asserting a constant does not test that anything
   reads it. :class:`TheDeclaredBudgetsAreTheOnesSentTest` captures the request body, and
   :meth:`TheDeclaredBudgetsAreTheOnesSentTest.test_the_wall_limit_reaches_the_socket_and_is_not_only_a_constant`
   captures the one budget that never appears in a body: the socket timeout.
3. **A regression fixture drawn from a subset of the evidence.** The class at the bottom
   of this file used to replay the six ``judge_*`` responses only, and its manifest encoded
   that six-file population — so the *other* twenty-three recorded judge calls were outside
   every test in the repository. One of them, ``noise_19_draw1``, is a complete
   15,183-character judgement whose last line is ``**VERDICT: 2.725**``, and the shipped
   verdict pattern refused it: a fully graded response reported as "no verdict line", which
   is the same output a broken judge produces. The fixture is now **all 29** recorded judge
   responses plus the truncated generation, and
   :meth:`AgainstEveryRecordedJudgementTest.test_the_manifest_is_the_whole_recorded_population`
   is the control that stops it shrinking back to a convenient subset.

Everything here runs against a real ``http.server`` on loopback rather than a stubbed
client object. That is affordable only because the tool speaks plain ``urllib.request``:
there is no third-party client to fake, so the socket, the headers, the JSON body, the
retry loop and the timeout are all the real ones, on a bare interpreter, with no key and
no network.

The last class replays all twenty-nine recorded ``gpt-5.1`` judge responses against the
probe's own reading of each one, including the six that produced 2.675 / 0.000 / 2.000 /
0.000 / 3.000 / 0.000, plus a thirtieth that was truncated and must be refused rather than
scored 0. The responses are not committed — a judge quotes rubric items back verbatim while
it reasons — so only their digests are, and the tests skip when the bodies are not on the
machine.

**The skip count is a property of the machine, not of the commit.** Five tests here and
eight in ``tests/test_fs_dataset.py`` are gated on two things that live outside the
repository and are not fetched: the pinned split and the recorded responses. A runner that
installs neither — which is the CI this repository describes — reports thirteen skips more
than a machine that has both. Read a jump from ``skipped=1`` to ``skipped=14`` as the
absence of the artifacts and not as a regression.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "tools" / "score_fs_run.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures"
REGRESSION_MANIFEST = FIXTURES / "fs_judge_regression.json"

#: Module-level constants that carry no ``#:`` reason, and why each is allowed to.
#: ``REPO_ROOT`` is the ``sys.path`` bootstrap every ``tools/`` script opens with — it is
#: not a choice with a measurement behind it, it is how the file finds ``src/`` at all,
#: and giving it a prose reason would make the convention read as decoration.
CONSTANTS_WITHOUT_A_REASON = frozenset({"REPO_ROOT"})


def has_a_reason(text: str, name: str) -> bool:
    """Whether the line above ``name``'s assignment is a ``#:`` comment.

    Factored out so the control below can run the same rule over a snippet it wrote
    itself. A scan asserted only against the file it was written for cannot show that it
    would fail on anything.
    """
    head = text.split(f"\n{name} = ")[0].rstrip().splitlines()
    return bool(head) and head[-1].lstrip().startswith("#:")


def _load():
    spec = importlib.util.spec_from_file_location("score_fs_run", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def recorded_responses_dir() -> Path:
    """Where the recorded probe responses live, outside any repository."""
    import os

    override = (os.environ.get("FRONTIERSCIENCE_JUDGE_RAW") or "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cache" / "frontierscience" / "regression"


def recorded_responses_present() -> bool:
    manifest = json.loads(REGRESSION_MANIFEST.read_text(encoding="utf-8"))
    directory = recorded_responses_dir()
    return all((directory / entry["file"]).is_file() for entry in manifest["responses"])


def completed(text: str) -> dict:
    return {
        "status": "completed",
        "output_text": None,
        "output": [
            {"type": "reasoning", "content": []},
            {"type": "message", "content": [{"type": "output_text", "text": text}]},
        ],
        "usage": {
            "input_tokens": 4000,
            "output_tokens": 900,
            "output_tokens_details": {"reasoning_tokens": 700},
        },
    }


class _Stub:
    """A real HTTP server that hands back canned Responses payloads, in order.

    Zero third-party dependencies and no network: it binds loopback on an ephemeral port.
    Every request it saw is kept, which is what lets the tests below assert on the body
    and the headers the tool actually sent rather than on the arguments it meant to send.
    """

    def __init__(self, script: list[tuple[int, object]]) -> None:
        self.script = list(script)
        self.requests: list[dict] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's name
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                stub.requests.append(
                    {
                        "path": self.path,
                        "headers": dict(self.headers),
                        "body": json.loads(raw.decode("utf-8")) if raw else {},
                    }
                )
                status, payload = (
                    stub.script.pop(0) if stub.script else (200, completed("VERDICT: 1"))
                )
                body = (payload if isinstance(payload, str) else json.dumps(payload)).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args) -> None:  # noqa: D102 - silence the test output
                return

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def endpoint(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/openai/v1"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


class _Harness(unittest.TestCase):
    """Shared setup: a loaded tool, a temp workspace, a key file and a synthetic dataset."""

    def setUp(self) -> None:
        from tests.test_fs_dataset import synthetic_rows

        self.tool = _load()
        # No sleeping in a unit test. The schedule itself is asserted separately.
        self.tool.FS_JUDGE_BACKOFF_SECONDS = (0, 0, 0)
        self.tool.load_dataset = lambda path=None: synthetic_rows()

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.answer = self.tmp / "answer.md"
        self.answer.write_text("A short but real answer.\n", encoding="utf-8")
        self.key_file = self.tmp / "key.txt"
        self.key_file.write_text("not-a-real-key-value\n", encoding="utf-8")
        self.out = self.tmp / "scores" / "fs000.json"

    def run_tool(self, stub: _Stub, *extra: str, judge_timeout: str | None = "10") -> tuple[int, str]:
        """Drive ``main`` over the stub. ``judge_timeout=None`` leaves the flag off entirely,
        which is the only way to observe what the *default* wall limit does."""
        argv = [
            "--task", "fs:000",
            "--answer", str(self.answer),
            "--dataset", str(self.tmp / "research_test.jsonl"),
            "--endpoint", stub.endpoint,
            "--key-file", str(self.key_file),
            "--out", str(self.out),
        ]
        if judge_timeout is not None:
            argv += ["--judge-timeout", judge_timeout]
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = self.tool.main([*argv, *extra])
        return code, buffer.getvalue()

    def watch_socket_timeouts(self) -> list:
        """Every ``timeout`` ``urlopen`` is called with, in order, restored on teardown.

        A wall limit is a client-side socket setting: it is not in the request body, not in
        the headers, and not in the response, so the class that captures the wire cannot see
        it at all. The only place it is observable is the call itself.
        """
        import unittest.mock

        seen: list = []
        real = self.tool.urllib.request.urlopen

        def spy(request, *args, **kwargs):
            seen.append(kwargs.get("timeout", args[0] if args else None))
            return real(request, *args, **kwargs)

        patcher = unittest.mock.patch.object(self.tool.urllib.request, "urlopen", spy)
        patcher.start()
        self.addCleanup(patcher.stop)
        return seen


class AScoredRunWritesAResultTest(_Harness):
    """The happy path, end to end, over a real socket."""

    def test_a_completed_judgement_is_written_and_exits_zero(self) -> None:
        stub = _Stub([(200, completed("per-item reasoning\n\nVERDICT: 7.5"))])
        self.addCleanup(stub.close)

        code, output = self.run_tool(stub)

        self.assertEqual(code, 0, output)
        self.assertTrue(self.out.is_file(), "a scored run wrote no result file")
        result = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(result["schema"], "fs_score/1")
        self.assertEqual(result["total_score"], 7.5)
        self.assertTrue(result["passed"])
        self.assertFalse(result["refused"])
        self.assertEqual(result["draws"][0]["points"], 7.5)

    def test_the_result_directory_is_created_rather_than_assumed(self) -> None:
        """`<state_dir>/scores/` has no other creator. A bare write_text scored every item,
        printed the total, died on FileNotFoundError, and a driver read that as a failure."""
        self.assertFalse(self.out.parent.exists())
        stub = _Stub([(200, completed("VERDICT: 3"))])
        self.addCleanup(stub.close)
        self.assertEqual(self.run_tool(stub)[0], 0)
        self.assertTrue(self.out.is_file())

    def test_the_output_names_the_judge_and_says_it_is_not_the_papers(self) -> None:
        """The number is a property of the judge. Sixteen points of a ResearchClawBench
        total were, and this judge is not even the one the paper used."""
        stub = _Stub([(200, completed("VERDICT: 3"))])
        self.addCleanup(stub.close)
        _, output = self.run_tool(stub)
        self.assertIn("gpt-5.1", output)
        self.assertIn("NOT comparable to the paper's table", output)

    def test_a_second_draw_produces_a_spread_and_a_mean(self) -> None:
        stub = _Stub([(200, completed("VERDICT: 2.5")), (200, completed("VERDICT: 3.5"))])
        self.addCleanup(stub.close)

        code, _ = self.run_tool(stub, "--draws", "2")

        self.assertEqual(code, 0)
        result = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(result["total_scores"], [2.5, 3.5])
        self.assertAlmostEqual(result["total_score"], 3.0)
        self.assertAlmostEqual(result["total_spread"], 1.0)
        self.assertEqual(len(stub.requests), 2)

    def test_one_draw_reports_its_dispersion_as_unmeasured_not_as_zero(self) -> None:
        stub = _Stub([(200, completed("VERDICT: 3"))])
        self.addCleanup(stub.close)
        self.run_tool(stub)
        result = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertIsNone(result["total_spread"])
        self.assertIn("unmeasured (1 draw)", result["spread_text"])
        self.assertIn("UNMEASURED", result["spread_text"])

    def test_the_raw_response_is_saved_where_it_was_asked_for(self) -> None:
        stub = _Stub([(200, completed("VERDICT: 3"))])
        self.addCleanup(stub.close)
        raw_dir = self.tmp / "raw"
        self.assertEqual(self.run_tool(stub, "--raw-dir", str(raw_dir))[0], 0)
        saved = sorted(raw_dir.glob("*.json"))
        self.assertEqual([path.name for path in saved], ["fs000.d0.json"])
        self.assertEqual(json.loads(saved[0].read_text(encoding="utf-8"))["status"], "completed")

    def test_the_producers_own_metadata_is_merged_into_the_answer_block(self) -> None:
        meta = self.tmp / "_meta.json"
        meta.write_text(json.dumps({"producer": "autor", "auto_skipped_stages": []}), encoding="utf-8")
        stub = _Stub([(200, completed("VERDICT: 3"))])
        self.addCleanup(stub.close)
        self.run_tool(stub)
        result = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(result["answer"]["producer"], "autor")
        self.assertEqual(result["answer"]["chars"], len("A short but real answer.\n"))

    def test_an_explicit_answer_meta_beats_the_file_sitting_beside_the_answer(self) -> None:
        """``--answer-meta`` exists to say *which* producer's record applies, and the case
        it exists for is the one where a stale ``_meta.json`` is also in the directory. If
        the override is dropped the tool reads the sibling, writes a result that looks
        complete, and attributes the score to the wrong arm — with nothing in the output
        saying which file it read.
        """
        (self.tmp / "_meta.json").write_text(
            json.dumps({"producer": "the-sibling", "pipeline_completed": False}), encoding="utf-8"
        )
        explicit = self.tmp / "chosen_meta.json"
        explicit.write_text(
            json.dumps({"producer": "the-explicit-one", "pipeline_completed": True,
                        "auto_skipped_stages": ["draft"]}),
            encoding="utf-8",
        )
        stub = _Stub([(200, completed("VERDICT: 3"))])
        self.addCleanup(stub.close)

        self.assertEqual(self.run_tool(stub, "--answer-meta", str(explicit))[0], 0)

        answer = json.loads(self.out.read_text(encoding="utf-8"))["answer"]
        self.assertEqual(answer["producer"], "the-explicit-one")
        self.assertTrue(answer["pipeline_completed"])
        self.assertEqual(answer["auto_skipped_stages"], ["draft"])

    def test_the_sibling_is_what_is_read_when_no_explicit_one_is_given(self) -> None:
        """The control for the test above: without it, a tool that ignored ``--answer-meta``
        and a tool that ignored the sibling would both pass."""
        (self.tmp / "_meta.json").write_text(
            json.dumps({"producer": "the-sibling"}), encoding="utf-8"
        )
        (self.tmp / "chosen_meta.json").write_text(
            json.dumps({"producer": "the-explicit-one"}), encoding="utf-8"
        )
        stub = _Stub([(200, completed("VERDICT: 3"))])
        self.addCleanup(stub.close)

        self.assertEqual(self.run_tool(stub)[0], 0)

        answer = json.loads(self.out.read_text(encoding="utf-8"))["answer"]
        self.assertEqual(answer["producer"], "the-sibling")

    def test_an_unreadable_answer_meta_invents_nothing_and_still_scores(self) -> None:
        """Never fatal, never invented. A malformed producer record must not stop the run
        and must not leave a field behind that the scorer made up — the fields it carries
        are the ones an admissibility rule decides on."""
        broken = self.tmp / "broken_meta.json"
        broken.write_text("{not json at all", encoding="utf-8")
        stub = _Stub([(200, completed("VERDICT: 3"))])
        self.addCleanup(stub.close)

        self.assertEqual(self.run_tool(stub, "--answer-meta", str(broken))[0], 0)

        answer = json.loads(self.out.read_text(encoding="utf-8"))["answer"]
        self.assertEqual(set(answer), {"path", "sha256", "chars"})

    def test_a_missing_answer_meta_path_is_not_an_error(self) -> None:
        stub = _Stub([(200, completed("VERDICT: 3"))])
        self.addCleanup(stub.close)
        self.assertEqual(self.run_tool(stub, "--answer-meta", str(self.tmp / "absent.json"))[0], 0)
        self.assertEqual(
            set(json.loads(self.out.read_text(encoding="utf-8"))["answer"]),
            {"path", "sha256", "chars"},
        )

    def test_the_result_digests_the_answer_that_was_read_and_the_prompt_that_was_sent(self) -> None:
        """The two fields a reader six months out uses to say *which* prompt and *which*
        answer produced a total. Both were writable as a literal with the suite green, and
        both are checked here against the bytes rather than against the intent: the answer
        digest against the file on disk, the prompt digest against the string that went out
        on the wire.
        """
        import hashlib

        stub = _Stub([(200, completed("VERDICT: 3"))])
        self.addCleanup(stub.close)
        self.assertEqual(self.run_tool(stub)[0], 0)

        result = json.loads(self.out.read_text(encoding="utf-8"))
        sent = stub.requests[0]["body"]["input"]
        self.assertEqual(
            result["judge"]["prompt_sha256"],
            hashlib.sha256(sent.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(result["judge"]["prompt_chars"], len(sent))
        self.assertEqual(
            result["answer"]["sha256"],
            hashlib.sha256(self.answer.read_bytes()).hexdigest(),
        )
        self.assertNotEqual(result["judge"]["prompt_sha256"], result["answer"]["sha256"])

    def test_the_prompt_digest_moves_when_the_answer_does(self) -> None:
        """The control. A digest of any fixed string would satisfy the test above on a
        single run; these two runs differ only in the answer that goes into the prompt."""
        import hashlib

        first = _Stub([(200, completed("VERDICT: 3"))])
        self.addCleanup(first.close)
        self.run_tool(first)
        before = json.loads(self.out.read_text(encoding="utf-8"))

        self.answer.write_text("A different but equally real answer.\n", encoding="utf-8")
        second = _Stub([(200, completed("VERDICT: 3"))])
        self.addCleanup(second.close)
        self.run_tool(second)
        after = json.loads(self.out.read_text(encoding="utf-8"))

        self.assertNotEqual(before["judge"]["prompt_sha256"], after["judge"]["prompt_sha256"])
        self.assertNotEqual(before["answer"]["sha256"], after["answer"]["sha256"])
        self.assertEqual(
            after["answer"]["sha256"],
            hashlib.sha256(b"A different but equally real answer.\n").hexdigest(),
        )


class ARefusalWritesNothingTest(_Harness):
    """Four failure shapes, all of which arrive looking like success."""

    def _refuses(self, payload, *, status: int = 200) -> str:
        stub = _Stub([(status, payload)] * 4)
        self.addCleanup(stub.close)
        code, output = self.run_tool(stub)
        self.assertEqual(code, 1, output)
        self.assertFalse(self.out.exists(), "a refused total was written to --out anyway")
        self.assertIn("REFUSING TO QUOTE A TOTAL", output)
        return output

    def test_a_truncated_response_is_refused_although_it_is_http_200(self) -> None:
        payload = completed("the tally so far is")
        payload["status"] = "incomplete"
        payload["incomplete_details"] = {"reason": "max_output_tokens"}
        self.assertIn("max_output_tokens", self._refuses(payload))

    def test_a_response_with_no_verdict_is_refused(self) -> None:
        self.assertIn("no `VERDICT: <n>` line", self._refuses(completed("I graded every item.")))

    def test_an_empty_message_is_refused_rather_than_scored_zero(self) -> None:
        """The 4,096-token budget: the judge spent everything on reasoning and returned
        nothing. Scored as 0 it is indistinguishable from a genuinely worthless answer."""
        self.assertIn("no visible text", self._refuses(completed("")))

    def test_a_transport_failure_is_refused_and_named(self) -> None:
        output = self._refuses({"error": "boom"}, status=500)
        self.assertIn("judge call failed", output)
        self.assertIn("HTTP 500", output)

    def test_a_real_zero_is_a_score_and_not_a_refusal(self) -> None:
        """The control for every test above. Without it they would all pass on a tool that
        refuses everything, and the whole point is that 0.000 is a legitimate total here."""
        stub = _Stub([(200, completed("every item fails\n\nVERDICT: 0"))])
        self.addCleanup(stub.close)
        code, _ = self.run_tool(stub)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(self.out.read_text(encoding="utf-8"))["total_score"], 0.0)


class TheDeclaredBudgetsAreTheOnesSentTest(_Harness):
    """A constant nothing reads is a constant two tests can assert and neither can check."""

    def test_the_model_effort_and_token_budget_reach_the_wire(self) -> None:
        stub = _Stub([(200, completed("VERDICT: 3"))])
        self.addCleanup(stub.close)
        self.run_tool(stub)

        body = stub.requests[0]["body"]
        self.assertEqual(body["model"], self.tool.FS_JUDGE_MODEL)
        self.assertEqual(body["reasoning"], {"effort": self.tool.FS_JUDGE_REASONING_EFFORT})
        self.assertEqual(body["max_output_tokens"], self.tool.FS_JUDGE_MAX_OUTPUT_TOKENS)
        self.assertEqual(stub.requests[0]["path"], "/openai/v1/responses")

    def test_the_prompt_on_the_wire_is_the_papers_prompt_with_this_rubric_in_it(self) -> None:
        from src.fs_scoring import FS_JUDGE_PROMPT
        from tests.test_fs_dataset import synthetic_rows

        stub = _Stub([(200, completed("VERDICT: 3"))])
        self.addCleanup(stub.close)
        self.run_tool(stub)

        sent = stub.requests[0]["body"]["input"]
        self.assertTrue(sent.startswith(FS_JUDGE_PROMPT.split("{problem}")[0]))
        self.assertIn(synthetic_rows()[0].rubric, sent)
        self.assertIn("A short but real answer.", sent)

    def test_the_wall_limit_reaches_the_socket_and_is_not_only_a_constant(self) -> None:
        """``--judge-timeout`` is the one budget this class cannot check on the wire.

        This is defect 2 of the module docstring in its exact original form:
        ``JUDGE_TIME_LIMIT`` in the other tool was declared, defaulted, documented and read
        by nothing, while a test asserting its *value* stayed green. Dropping
        ``timeout=self.timeout_seconds`` from the ``urlopen`` call leaves every other test
        in this file passing, so the kwarg has to be observed where it is passed.
        """
        seen = self.watch_socket_timeouts()
        stub = _Stub([(200, completed("VERDICT: 3"))])
        self.addCleanup(stub.close)

        self.assertEqual(self.run_tool(stub, "--judge-timeout", "12.5")[0], 0)

        self.assertEqual(seen, [12.5], "the flag never reached urlopen")

    def test_the_default_wall_limit_is_the_declared_constant_and_also_reaches_it(self) -> None:
        """With the flag off, what the socket gets must be FS_JUDGE_TIMEOUT_SECONDS itself —
        not the client's own default, which is what a dropped kwarg silently falls back to."""
        seen = self.watch_socket_timeouts()
        stub = _Stub([(200, completed("VERDICT: 3"))])
        self.addCleanup(stub.close)

        self.assertEqual(self.run_tool(stub, judge_timeout=None)[0], 0)

        self.assertEqual(seen, [float(self.tool.FS_JUDGE_TIMEOUT_SECONDS)])
        self.assertEqual(
            json.loads(self.out.read_text(encoding="utf-8"))["judge"]["timeout_seconds"],
            self.tool.FS_JUDGE_TIMEOUT_SECONDS,
        )

    def test_the_wall_limit_is_carried_into_every_retry_and_not_just_the_first_call(self) -> None:
        """A retry builds a fresh Request; a budget applied only to the first attempt would
        leave the attempt most likely to hang — the one after a 500 — unbounded."""
        seen = self.watch_socket_timeouts()
        stub = _Stub([(500, {"error": "upstream"}), (200, completed("VERDICT: 4"))])
        self.addCleanup(stub.close)

        self.assertEqual(self.run_tool(stub, "--judge-timeout", "7")[0], 0)

        self.assertEqual(seen, [7.0, 7.0])

    def test_the_spy_would_notice_a_call_that_passed_no_timeout(self) -> None:
        """The control. The watcher reads a kwarg, and a watcher that recorded nothing at
        all would let all three assertions above pass over an empty list."""
        seen = self.watch_socket_timeouts()
        try:
            self.tool.urllib.request.urlopen("http://127.0.0.1:1/nothing")
        except Exception:  # noqa: BLE001 - nothing is listening, and the call is the point
            pass
        self.assertEqual(seen, [None])

    def test_the_budgets_are_the_measured_ones(self) -> None:
        self.assertEqual(self.tool.FS_JUDGE_MAX_OUTPUT_TOKENS, 32000)
        self.assertEqual(self.tool.FS_JUDGE_TIMEOUT_SECONDS, 600)
        self.assertEqual(self.tool.FS_JUDGE_WORKERS, 1)

    def test_every_constant_says_why_its_value_is_that_value(self) -> None:
        """A `#:` line above each one, naming the measurement rather than the units."""
        text = TOOL.read_text(encoding="utf-8")
        declared = [
            name
            for name in re.findall(r"^([A-Z][A-Z0-9_]*) = ", text, re.MULTILINE)
            if name not in CONSTANTS_WITHOUT_A_REASON
        ]
        self.assertGreaterEqual(len(declared), 8, "the scan found almost no constants")
        for name in declared:
            with self.subTest(constant=name):
                self.assertTrue(has_a_reason(text, name), f"{name} has no `#:` reason")

    def test_the_exemption_from_that_scan_is_still_needed(self) -> None:
        """An exemption for a constant that has since grown a reason is a lie."""
        text = TOOL.read_text(encoding="utf-8")
        for name in CONSTANTS_WITHOUT_A_REASON:
            with self.subTest(constant=name):
                self.assertIn(f"\n{name} = ", text, f"{name} is gone; drop the exemption")
                self.assertFalse(
                    has_a_reason(text, name),
                    f"{name} now carries a reason; drop it from CONSTANTS_WITHOUT_A_REASON",
                )

    def test_the_scan_would_notice_a_constant_that_lost_its_reason(self) -> None:
        """The control. The scan is a text rule, and a text rule that matched nothing would
        pass every assertion above."""
        self.assertTrue(has_a_reason("#: because it was measured at 600.\nX = 600\n", "X"))
        self.assertFalse(has_a_reason("# an ordinary comment\nX = 600\n", "X"))
        self.assertFalse(has_a_reason("Y = 1\nX = 600\n", "X"))

    def test_the_wall_limit_and_the_output_budget_are_named_in_the_docstring(self) -> None:
        """Each default is a measurement. The numbers behind them live beside them.

        ``15,202`` and ``4,802`` are pinned alongside ``20,004`` because the number on its
        own was described wrongly three times over: 20,004 is the *total* output of
        ``noise_19_draw6``, 15,202 of it reasoning, so the visible part was 4,802. Calling
        that "the largest visible output" made the sentence contradict the argument it was
        supporting — that the budget is bought by the thinking and not by the answer.
        """
        text = TOOL.read_text(encoding="utf-8")
        for marker in ("322.3", "20,004", "15,202", "4,802", "72.9", "34 of 34"):
            self.assertIn(marker, text, f"the measurement {marker} is not recorded")
        self.assertNotIn(
            "largest visible", text, "20,004 is a total output, not a visible one"
        )


class TheRetryLoopTest(_Harness):
    """Transient failures are retried; a request this tool got wrong is not."""

    def test_a_five_hundred_is_retried_and_the_run_recovers(self) -> None:
        stub = _Stub([(500, {"error": "upstream"}), (200, completed("VERDICT: 4"))])
        self.addCleanup(stub.close)
        code, _ = self.run_tool(stub)
        self.assertEqual(code, 0)
        self.assertEqual(len(stub.requests), 2)
        self.assertEqual(json.loads(self.out.read_text(encoding="utf-8"))["total_score"], 4.0)

    def test_a_four_hundred_is_not_retried(self) -> None:
        """A malformed request retried four times is four identical mistakes and a longer
        log; the retry codes are an allowlist for that reason."""
        stub = _Stub([(400, {"error": "bad request"})] * 4)
        self.addCleanup(stub.close)
        code, _ = self.run_tool(stub)
        self.assertEqual(code, 1)
        self.assertEqual(len(stub.requests), 1)

    def test_every_code_in_the_allowlist_is_actually_retried(self) -> None:
        """The set as a population, not as a literal.

        Only 500 was ever driven through the loop, so 408 and 429 could be dropped from
        ``FS_JUDGE_RETRY_CODES`` with the suite green — and 429 is the code most likely to
        fire in a sixty-task pass, where losing it turns a rate limit into a refused pair.

        The membership assertion is not the constant-assertion this module's docstring
        disavows; it is the population the sweep runs over. A sweep that iterates the set
        under test and nothing else re-admits the same defect one level up: delete 429 and
        both the set and the loop shrink together.
        """
        self.assertEqual(
            sorted(self.tool.FS_JUDGE_RETRY_CODES),
            [408, 429, 500, 502, 503, 504],
            "the allowlist moved; 408 and 429 are the two a long serial pass actually meets",
        )
        for code in sorted(self.tool.FS_JUDGE_RETRY_CODES):
            with self.subTest(status=code):
                stub = _Stub([(code, {"error": "transient"}), (200, completed("VERDICT: 4"))])
                self.addCleanup(stub.close)
                self.assertEqual(self.run_tool(stub)[0], 0)
                self.assertEqual(len(stub.requests), 2, f"{code} was not retried")

    def test_a_code_outside_the_allowlist_is_the_control_for_that_sweep(self) -> None:
        """Without it the sweep above would pass on a tool that retried everything, which is
        the failure the allowlist exists to prevent: four identical malformed requests."""
        self.assertNotIn(400, self.tool.FS_JUDGE_RETRY_CODES)
        stub = _Stub([(400, {"error": "bad request"})] * 4)
        self.addCleanup(stub.close)
        self.assertEqual(self.run_tool(stub)[0], 1)
        self.assertEqual(len(stub.requests), 1)

    def test_the_backoff_schedule_is_shorter_than_the_attempt_count(self) -> None:
        """Three waits between four attempts, and the indexing clamps rather than raising."""
        tool = _load()
        self.assertEqual(len(tool.FS_JUDGE_BACKOFF_SECONDS), tool.FS_JUDGE_MAX_TRY - 1)
        self.assertEqual(tool.FS_JUDGE_BACKOFF_SECONDS, (5, 20, 60))


class NoKeyReachesTheRepositoryOrTheProcessTableTest(unittest.TestCase):
    """The key file lives outside the tree, and there is no flag that would put it in argv."""

    def setUp(self) -> None:
        self.tool = _load()

    def test_the_tool_contains_no_key_shaped_literal(self) -> None:
        suspicious = re.findall(r"(?:sk-[A-Za-z0-9_\-]{16,})", TOOL.read_text(encoding="utf-8"))
        self.assertEqual(suspicious, [], "a key-shaped literal is in the tool")

    def test_the_key_file_default_is_outside_any_repository(self) -> None:
        default = self.tool.DEFAULT_KEY_FILE.resolve()
        self.assertFalse(str(default).startswith(str(REPO_ROOT.resolve()) + "/"))

    def test_the_cli_refuses_to_take_a_key_as_an_argument(self) -> None:
        text = TOOL.read_text(encoding="utf-8")
        self.assertNotIn('"--api-key"', text)
        self.assertNotIn("'--api-key'", text)
        self.assertIn("--key-file", text)

    def test_a_missing_key_file_says_what_to_do_rather_than_crashing(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            self.tool.read_api_key(Path("/nonexistent/api.txt"))
        message = str(caught.exception)
        self.assertIn("/nonexistent/api.txt", message)
        self.assertIn("shell history", message)

    def test_the_key_reader_tolerates_the_shapes_a_file_arrives_in(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "api.txt"
            for written, expected in (
                ("token-value\n", "token-value"),
                ("AZURE_KEY=token-value\n", "token-value"),
                ('AZURE_KEY="token-value"\n', "token-value"),
            ):
                path.write_text(written, encoding="utf-8")
                self.assertEqual(self.tool.read_api_key(path), expected)

    def test_errors_are_redacted_before_they_are_printed(self) -> None:
        # Assembled rather than written out: a literal here would be found by the
        # repository-wide key scan, which is the point of that scan.
        fake = "sk-" + ("abcdefghijkl" + "mnopqrstuvwxyz" + "012345")
        leaked = f"AuthError: request failed with Bearer {fake}"
        self.assertNotIn("mnopqrstuvwxyz", self.tool.redact(leaked))
        self.assertIn("<redacted>", self.tool.redact(leaked))


class TheKeyGoesInTheHeaderAndNowhereElseTest(_Harness):
    """The one place the key is allowed to appear, checked on the wire."""

    def test_the_key_is_sent_as_a_header_and_never_in_the_body(self) -> None:
        self.key_file.write_text("a-distinctive-token-value", encoding="utf-8")
        stub = _Stub([(200, completed("VERDICT: 3"))])
        self.addCleanup(stub.close)
        code, output = self.run_tool(stub)

        self.assertEqual(code, 0)
        request = stub.requests[0]
        self.assertEqual(request["headers"]["Authorization"], "Bearer a-distinctive-token-value")
        self.assertNotIn("a-distinctive-token-value", json.dumps(request["body"]))
        self.assertNotIn("a-distinctive-token-value", output)
        self.assertNotIn("a-distinctive-token-value", self.out.read_text(encoding="utf-8"))


class TheTaskGrammarIsTheSharedOneTest(_Harness):
    """One grammar for `--task`, so this tool and the trial driver refuse the same things."""

    def test_a_bare_row_index_and_a_task_key_reach_the_same_row(self) -> None:
        from tests.test_fs_dataset import synthetic_rows

        rows = synthetic_rows()
        self.assertEqual(self.tool.resolve_row(rows, "1"), self.tool.resolve_row(rows, "fs:001"))

    def test_a_spec_that_selects_more_than_one_task_is_refused(self) -> None:
        from src.frontierscience import DatasetRefused
        from tests.test_fs_dataset import synthetic_rows

        with self.assertRaises(DatasetRefused) as caught:
            self.tool.resolve_row(synthetic_rows(), "all")
        self.assertIn("scores one answer against one task", str(caught.exception))

    def test_an_unknown_task_is_refused_with_the_grammar_attached(self) -> None:
        from src.frontierscience import DatasetRefused
        from tests.test_fs_dataset import synthetic_rows

        with self.assertRaises(DatasetRefused) as caught:
            self.tool.resolve_row(synthetic_rows(), "fs:999")
        self.assertIn("random.Random(S).sample", str(caught.exception))


class NoBenchmarkScoreReachesTheArchiveTest(unittest.TestCase):
    """A rubric point out of ten must never pool with an AutoR rubric mean in [0, 1].

    The same fence ``tests/test_rcb_trial.py`` puts around the ResearchClawBench driver,
    for the same reason: ``RunRecord.usable`` is ``rubric_version == RUBRIC_VERSION and
    provenance == 'live'``, and a benchmark row carrying AutoR's rubric version is a claim
    it cannot support. Pooled into ``Archive.variant_fitness`` these totals would sit
    beside [0, 1] rubric means and steer topology promotion off a unit error. Prose in a
    docstring is not a guard; the guard is that no archive is constructible from any of
    these files.
    """

    FILES = ("src/frontierscience.py", "src/fs_scoring.py", "tools/score_fs_run.py")

    def test_the_files_this_scan_reads_are_the_real_ones(self) -> None:
        """The control. A typo in a path would make every assertion below vacuous."""
        for name in self.FILES:
            with self.subTest(module=name):
                self.assertGreater(len((REPO_ROOT / name).read_text(encoding="utf-8")), 1000)

    def test_no_scoring_module_can_reach_the_archive(self) -> None:
        for name in self.FILES:
            body = (REPO_ROOT / name).read_text(encoding="utf-8")
            for forbidden in ("Archive(", "record_run", "runs.jsonl"):
                with self.subTest(module=name, symbol=forbidden):
                    self.assertNotIn(forbidden, body, f"{name} can reach the archive via {forbidden}")


class EveryDeclaredFlagIsReadTest(unittest.TestCase):
    """A flag that parses and is then dropped is silent: it appears in --help and does nothing.

    ``tests/test_cli_flags_are_read.py`` holds this for the two front ends and found
    ``--routine-model`` declared, documented and read by no line. The scorer has thirteen
    flags and the same failure is available to it.
    """

    def test_the_tool_reads_every_flag_it_declares(self) -> None:
        source = TOOL.read_text(encoding="utf-8")
        flags = re.findall(r'add_argument\(\s*"(--[a-z0-9-]+)"', source)
        self.assertGreaterEqual(len(flags), 12, "the scan found almost no flags")
        unwired = {
            flag
            for flag in flags
            if not re.search(rf"\bargs\.{flag[2:].replace('-', '_')}\b", source)
        }
        self.assertEqual(unwired, set(), f"declared and never read: {sorted(unwired)}")

    def test_the_scan_would_notice_a_flag_that_is_never_read(self) -> None:
        """The control: the rule is a regex, and a regex that matches nothing passes."""
        source = TOOL.read_text(encoding="utf-8").replace("args.raw_dir", "None")
        self.assertFalse(re.search(r"\bargs\.raw_dir\b", source))


@unittest.skipUnless(
    recorded_responses_present(),
    "the recorded probe responses are not on this machine",
)
class AgainstEveryRecordedJudgementTest(unittest.TestCase):
    """The verdicts the live endpoint actually produced, replayed through the real reader.

    All twenty-nine of them. The previous fixture held six, and the reason that mattered is
    :meth:`test_a_verdict_wrapped_in_markdown_emphasis_is_still_a_verdict` below: the one
    emphasised verdict line in the recording sits in the twenty-three the fixture left out,
    and the pattern that refused it was green on every test in this repository.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(REGRESSION_MANIFEST.read_text(encoding="utf-8"))
        cls.directory = recorded_responses_dir()

    def _payload(self, entry: dict) -> dict:
        import hashlib

        raw = (self.directory / entry["file"]).read_bytes()
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(),
            entry["sha256"],
            f"{entry['file']} is not the response the manifest was written against",
        )
        record = json.loads(raw)
        # The probe stored the API payload under `body` alongside its own timing.
        return record.get("body", record)

    def _entry(self, name: str) -> dict:
        return next(entry for entry in self.manifest["responses"] if entry["file"] == name)

    def test_the_manifest_is_the_whole_recorded_population(self) -> None:
        """The population control, and the one that would have caught the defect.

        Not just "the list is non-empty" — the count, against the number of judge calls the
        probe made. A fixture assembled from whichever responses were convenient is exactly
        how a pattern that refuses one real response stays green.
        """
        entries = self.manifest["responses"]
        scored = [entry for entry in entries if not entry["expected_refused"]]
        self.assertEqual(len(scored), 29, "the fixture is not the whole recording")
        self.assertEqual(len(scored), self.manifest["judge_responses"])
        self.assertEqual(len(entries), 30)
        self.assertEqual(len({entry["file"] for entry in entries}), 30)
        self.assertEqual(sum(1 for entry in entries if entry["expected_refused"]), 1)

    def test_every_one_of_the_twenty_nine_recorded_verdicts_is_reproduced(self) -> None:
        """Each expectation is the probe's own reading, not a recording of this parser."""
        from src.fs_scoring import draw_record

        seen = 0
        for entry in self.manifest["responses"]:
            if entry["expected_refused"]:
                continue
            with self.subTest(response=entry["file"]):
                record = draw_record(self._payload(entry), index=0, latency_seconds=0.0)
                self.assertEqual(record["failures"], [])
                self.assertAlmostEqual(record["points"], entry["expected_points"])
                seen += 1
        self.assertEqual(seen, 29)

    def test_the_six_graded_answers_still_reproduce_the_verdicts_they_produced(self) -> None:
        """The six the endpoint probe scored by hand: 2.675 / 0 / 2 / 0 / 3 / 0."""
        from src.fs_scoring import draw_record

        names = [
            "judge_19_direct.json", "judge_19_bad.json", "judge_26_direct.json",
            "judge_26_bad.json", "judge_43_direct.json", "judge_43_bad.json",
        ]
        seen = [
            draw_record(self._payload(self._entry(name)), index=0, latency_seconds=0.0)["points"]
            for name in names
        ]
        self.assertEqual(seen, [2.675, 0.0, 2.0, 0.0, 3.0, 0.0])

    def test_a_verdict_wrapped_in_markdown_emphasis_is_still_a_verdict(self) -> None:
        """``noise_19_draw1`` is the response the six-file fixture hid.

        HTTP 200, ``status: completed``, 15,183 visible characters of per-item grading, and
        a last line of ``**VERDICT: 2.725**``. Read by a pattern that admits only the bare
        form it becomes "no verdict line", which is the report a judge that never tallied
        gets — so a complete judgement and a broken judge collapse into one row.
        """
        from src.fs_scoring import draw_record, response_text

        payload = self._payload(self._entry("noise_19_draw1.json"))
        text = response_text(payload)
        self.assertIn("**VERDICT: 2.725**", text, "the recording no longer holds the bold case")
        self.assertNotIn("\nVERDICT: 2.725", text, "the bold case is what makes this test bite")
        record = draw_record(payload, index=0, latency_seconds=0.0)
        self.assertEqual(record["failures"], [])
        self.assertAlmostEqual(record["points"], 2.725)

    def test_the_truncated_response_is_refused_rather_than_scored_zero(self) -> None:
        """HTTP 200, ``status: incomplete``, 636 characters cut mid-sentence. Recorded as a
        zero it would be indistinguishable from the three genuine 0.000s above it."""
        from src.fs_scoring import draw_record, refusal_reasons

        entry = next(e for e in self.manifest["responses"] if e["expected_refused"])
        record = draw_record(self._payload(entry), index=0, latency_seconds=0.0)
        self.assertIsNone(record["points"])
        self.assertNotEqual(record["points"], 0.0)
        self.assertEqual(record["incomplete_reason"], entry["expected_reason_contains"])
        self.assertTrue(refusal_reasons([record], draws_requested=1))


if __name__ == "__main__":
    unittest.main()
