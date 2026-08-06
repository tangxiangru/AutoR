from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import main as autor_main
from src import web_search as web_search_module
from src.utils import STAGES, build_prompt
from src.web_search import (
    DEFAULT_SEARCH_MODEL,
    DEFAULT_VERTEX_LOCATION,
    DEFAULT_VERTEX_SEARCH_MODEL,
    best_title,
    dedupe_by_url,
    is_unresolved_redirect,
    resolve_source,
    resolve_backend,
    resolve_source_url,
    vertex_credentials_available,
    resolve_web_search_context,
    web_search_notice,
    SearchResult,
    WebSearchError,
    WebSearchResponse,
    build_web_search_prompt_section,
    extract_search_results,
    format_response_markdown,
    gemini_web_search,
    main as web_search_main,
    resolve_gemini_api_key,
    resolve_search_model,
)


class _Web:
    def __init__(self, uri: str, title: str = "") -> None:
        self.uri = uri
        self.title = title


class _Chunk:
    def __init__(self, web) -> None:
        self.web = web


class _Segment:
    def __init__(self, text: str) -> None:
        self.text = text


class _Support:
    def __init__(self, text: str, indices: list[int]) -> None:
        self.segment = _Segment(text)
        self.grounding_chunk_indices = indices


class _Metadata:
    def __init__(self, chunks, supports=None) -> None:
        self.grounding_chunks = chunks
        self.grounding_supports = supports or []


class _Candidate:
    def __init__(self, metadata) -> None:
        self.grounding_metadata = metadata


class _Response:
    def __init__(self, candidates, text: str = "") -> None:
        self.candidates = candidates
        self.text = text


class ResolveModelTest(unittest.TestCase):
    def test_explicit_model_wins(self) -> None:
        with patch.dict(os.environ, {"AUTOR_WEB_SEARCH_MODEL": "from-env"}, clear=False):
            self.assertEqual(resolve_search_model("explicit"), "explicit")

    def test_env_override(self) -> None:
        with patch.dict(os.environ, {"AUTOR_WEB_SEARCH_MODEL": "gemini-x"}, clear=False):
            self.assertEqual(resolve_search_model(None), "gemini-x")

    def test_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_search_model(None), DEFAULT_SEARCH_MODEL)


class ResolveApiKeyTest(unittest.TestCase):
    def test_google_api_key_takes_priority(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "a", "GEMINI_API_KEY": "b"}, clear=True):
            self.assertEqual(resolve_gemini_api_key(), "a")

    def test_gemini_api_key_is_a_fallback(self) -> None:
        with patch.dict(os.environ, {"GEMINI_API_KEY": "b"}, clear=True):
            self.assertEqual(resolve_gemini_api_key(), "b")

    def test_blank_env_var_is_not_a_key(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "   "}, clear=True):
            with patch("src.web_search.DIAGRAM_CONFIG_PATH", Path("/nonexistent/diagram.yaml")):
                self.assertIsNone(resolve_gemini_api_key())

    def test_diagram_gen_uses_the_same_resolver(self) -> None:
        from src import diagram_gen

        with patch.dict(os.environ, {"GEMINI_API_KEY": "shared-key"}, clear=True):
            self.assertEqual(diagram_gen._resolve_api_key(), resolve_gemini_api_key())


class ExtractResultsTest(unittest.TestCase):
    def test_grounded_sources_become_results(self) -> None:
        response = _Response(
            [
                _Candidate(
                    _Metadata(
                        [_Chunk(_Web("https://example.org/a", "Paper A")), _Chunk(_Web("https://example.org/b"))],
                        [_Support("Key finding.", [0])],
                    )
                )
            ]
        )

        results = extract_search_results(response)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], SearchResult("Paper A", "https://example.org/a", ["Key finding."]))
        self.assertEqual(results[1].title, "https://example.org/b")
        self.assertEqual(results[1].supported_claims, [])

    def test_duplicate_urls_are_collapsed(self) -> None:
        chunk = _Chunk(_Web("https://example.org/a", "A"))
        response = _Response([_Candidate(_Metadata([chunk, chunk]))])
        self.assertEqual(len(extract_search_results(response)), 1)

    def test_max_results_is_honoured(self) -> None:
        chunks = [_Chunk(_Web(f"https://example.org/{i}")) for i in range(10)]
        response = _Response([_Candidate(_Metadata(chunks))])
        self.assertEqual(len(extract_search_results(response, max_results=3)), 3)

    def test_a_response_with_no_grounding_yields_no_results(self) -> None:
        self.assertEqual(extract_search_results(_Response([_Candidate(None)])), [])
        self.assertEqual(extract_search_results(_Response([])), [])
        self.assertEqual(extract_search_results(object()), [])

    def test_a_chunk_without_a_web_field_is_skipped(self) -> None:
        response = _Response([_Candidate(_Metadata([_Chunk(None), _Chunk(_Web("https://ok"))]))])
        self.assertEqual(len(extract_search_results(response)), 1)


class FormatTest(unittest.TestCase):
    def test_markdown_lists_answer_and_sources(self) -> None:
        response = WebSearchResponse(
            query="q",
            model="gemini-x",
            answer="The answer.",
            results=[SearchResult("Paper A", "https://example.org/a", ["A claim."])],
        )
        text = format_response_markdown(response)
        self.assertIn("# Web Search: q", text)
        self.assertIn("The answer.", text)
        self.assertIn("[Paper A](https://example.org/a)", text)
        self.assertIn("- A claim.", text)

    def test_a_supported_claim_is_never_rendered_as_a_quotation(self) -> None:
        """A blockquote under a source link reads as "this page says this". It does not.

        `supported_claims` is Gemini's own wording; grounding only asserts that the source
        supports the claim. Rendering it as a quotation is how a real paper acquires a
        sentence it never contained.
        """
        text = format_response_markdown(
            WebSearchResponse(
                query="q",
                model="m",
                answer="The answer.",
                results=[SearchResult("Paper A", "https://example.org/a", ["A claim."])],
            )
        )
        self.assertNotIn("> A claim.", text)
        self.assertIn("not text from the page", text)

    def test_every_claim_a_source_was_cited_for_is_shown(self) -> None:
        text = format_response_markdown(
            WebSearchResponse(
                query="q",
                model="m",
                answer="a",
                results=[SearchResult("A", "https://a", ["First claim.", "Second claim."])],
            )
        )
        self.assertIn("- First claim.", text)
        self.assertIn("- Second claim.", text)

    def test_results_that_are_all_unresolved_are_flagged_as_unverified(self) -> None:
        stub = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC"
        text = format_response_markdown(
            WebSearchResponse("q", "m", "a", "vertex", [SearchResult("x", stub)])
        )
        self.assertIn("unverified", text)

    def test_no_sources_is_flagged_as_unverified(self) -> None:
        text = format_response_markdown(WebSearchResponse("q", "m", "answer", []))
        self.assertIn("unverified", text)


class SearchErrorTest(unittest.TestCase):
    def test_empty_query_is_rejected(self) -> None:
        with self.assertRaises(WebSearchError):
            gemini_web_search("   ")

    def test_a_missing_key_is_a_clear_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("src.web_search.DIAGRAM_CONFIG_PATH", Path("/nonexistent/diagram.yaml")):
                with self.assertRaises(WebSearchError) as caught:
                    gemini_web_search("anything")
        self.assertIn("GOOGLE_API_KEY", str(caught.exception))


class CliTest(unittest.TestCase):
    def test_json_output_is_machine_readable(self) -> None:
        response = WebSearchResponse(
            query="q", model="m", answer="a", results=[SearchResult("T", "https://u")]
        )
        buffer = io.StringIO()
        with patch("src.web_search.gemini_web_search", return_value=response):
            with redirect_stdout(buffer):
                exit_code = web_search_main(["q", "--json"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["results"][0]["url"], "https://u")

    def test_multi_word_query_is_joined(self) -> None:
        captured: dict[str, str] = {}

        def fake_search(query, **kwargs):
            captured["query"] = query
            return WebSearchResponse(query, "m", "a", [])

        with patch("src.web_search.gemini_web_search", side_effect=fake_search):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                web_search_main(["black", "hole", "superradiance"])

        self.assertEqual(captured["query"], "black hole superradiance")

    def test_a_failed_search_exits_nonzero(self) -> None:
        with patch("src.web_search.gemini_web_search", side_effect=WebSearchError("no key")):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(web_search_main(["q"]), 1)


class PromptSectionTest(unittest.TestCase):
    def test_section_disables_native_search_and_names_the_script(self) -> None:
        section = build_web_search_prompt_section()
        self.assertIn("`WebSearch` tool is **disabled**", section)
        self.assertIn("tools/web_search.py", section)
        self.assertIn("--json", section)
        self.assertIn("Never invent a reference", section)

    def test_the_script_the_section_advertises_actually_exists(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        self.assertTrue((repo_root / "tools" / "web_search.py").exists())

    def test_section_reaches_the_stage_prompt(self) -> None:
        prompt = build_prompt(
            STAGES[0],
            "template",
            "user request",
            "memory",
            web_search_context=build_web_search_prompt_section(),
        )
        self.assertIn("# Web Search Capability", prompt)
        self.assertIn("tools/web_search.py", prompt)

    def test_no_section_means_no_heading(self) -> None:
        prompt = build_prompt(STAGES[0], "template", "user request", "memory")
        self.assertNotIn("# Web Search Capability", prompt)


class WebSearchNoticeTest(unittest.TestCase):
    """The notice exists so a silent fallback cannot hide a dead Stage 01."""

    def _no_key(self):
        return patch("src.web_search.DIAGRAM_CONFIG_PATH", Path("/nonexistent/diagram.yaml"))

    def test_auto_without_a_key_warns_and_names_the_deployment(self) -> None:
        with patch.dict(os.environ, {}, clear=True), self._no_key():
            message, level = web_search_notice("auto")
        self.assertEqual(level, "warn")
        self.assertIn("Vertex", message)
        self.assertIn("GEMINI_API_KEY", message)

    def test_auto_with_a_key_is_informational(self) -> None:
        with patch.dict(os.environ, {"GEMINI_API_KEY": "k"}, clear=True):
            message, level = web_search_notice("auto")
        self.assertEqual(level, "info")
        self.assertIn("Gemini", message)

    def test_gemini_without_a_key_is_an_error_not_a_warning(self) -> None:
        with patch.dict(os.environ, {}, clear=True), self._no_key():
            message, level = web_search_notice("gemini")
        self.assertEqual(level, "error")
        self.assertIn("fail on first use", message)

    def test_native_is_informational_even_with_a_key(self) -> None:
        with patch.dict(os.environ, {"GEMINI_API_KEY": "k"}, clear=True):
            message, level = web_search_notice("native")
        self.assertEqual(level, "info")

    def test_every_mode_yields_a_notice(self) -> None:
        for mode in ("auto", "gemini", "native"):
            for env in ({}, {"GEMINI_API_KEY": "k"}):
                with patch.dict(os.environ, env, clear=True), self._no_key():
                    message, level = web_search_notice(mode)
                self.assertTrue(message.strip(), mode)
                self.assertIn(level, {"info", "warn", "error"}, mode)

    def test_the_notice_agrees_with_what_is_injected(self) -> None:
        """A warn/error notice must mean no Gemini block reached the prompt, and vice versa."""
        for mode in ("auto", "gemini", "native"):
            for env in ({}, {"GEMINI_API_KEY": "k"}):
                with patch.dict(os.environ, env, clear=True), self._no_key():
                    _message, level = web_search_notice(mode)
                    injected = resolve_web_search_context(mode) is not None
                if mode == "gemini":
                    self.assertTrue(injected, mode)   # gemini always injects, even keyless
                elif mode == "native":
                    self.assertFalse(injected, mode)
                else:
                    self.assertEqual(injected, level == "info", (mode, env))


class WebSearchModeTest(unittest.TestCase):
    def test_native_never_injects(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}, clear=True):
            self.assertIsNone(autor_main.resolve_web_search_context("native"))

    def test_gemini_always_injects(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("src.web_search.DIAGRAM_CONFIG_PATH", Path("/nonexistent/diagram.yaml")):
                self.assertIsNotNone(autor_main.resolve_web_search_context("gemini"))

    def test_auto_degrades_to_native_without_a_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("src.web_search.DIAGRAM_CONFIG_PATH", Path("/nonexistent/diagram.yaml")):
                self.assertIsNone(autor_main.resolve_web_search_context("auto"))

    def test_auto_uses_gemini_when_a_key_exists(self) -> None:
        with patch.dict(os.environ, {"GEMINI_API_KEY": "k"}, clear=True):
            self.assertIsNotNone(autor_main.resolve_web_search_context("auto"))

    def test_the_rcb_adapter_resolves_the_same_way(self) -> None:
        import rcb_agent

        with patch.dict(os.environ, {"GEMINI_API_KEY": "k"}, clear=True):
            self.assertEqual(
                rcb_agent.resolve_web_search_context("auto"),
                autor_main.resolve_web_search_context("auto"),
            )


if __name__ == "__main__":
    unittest.main()


class VertexBackendTest(unittest.TestCase):
    """Vertex AI is the path that matters on deployments where WebSearch is disabled."""

    def _no_key(self):
        return patch("src.web_search.DIAGRAM_CONFIG_PATH", Path("/nonexistent/diagram.yaml"))

    def _adc(self, available: bool):
        return patch("src.web_search.vertex_credentials_available", return_value=available)

    def test_vertex_is_used_when_a_project_and_adc_exist_but_no_key(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "p1"}, clear=True), self._no_key(), self._adc(True):
            backend = resolve_backend()
        self.assertIsNotNone(backend)
        self.assertEqual(backend.kind, "vertex")
        self.assertEqual(backend.project, "p1")
        self.assertEqual(backend.location, DEFAULT_VERTEX_LOCATION)
        self.assertEqual(backend.model, DEFAULT_VERTEX_SEARCH_MODEL)

    def test_an_explicit_api_key_wins_over_an_inherited_vertex_project(self) -> None:
        env = {"GEMINI_API_KEY": "k", "GOOGLE_CLOUD_PROJECT": "p1"}
        with patch.dict(os.environ, env, clear=True), self._adc(True):
            backend = resolve_backend()
        self.assertEqual(backend.kind, "api_key")
        self.assertEqual(backend.model, DEFAULT_SEARCH_MODEL)

    def test_backend_env_var_forces_vertex_over_a_key(self) -> None:
        env = {"GEMINI_API_KEY": "k", "GOOGLE_CLOUD_PROJECT": "p1", "AUTOR_WEB_SEARCH_BACKEND": "vertex"}
        with patch.dict(os.environ, env, clear=True), self._adc(True):
            self.assertEqual(resolve_backend().kind, "vertex")

    def test_backend_env_var_forces_the_api_key_over_vertex(self) -> None:
        env = {"GEMINI_API_KEY": "k", "GOOGLE_CLOUD_PROJECT": "p1", "AUTOR_WEB_SEARCH_BACKEND": "api_key"}
        with patch.dict(os.environ, env, clear=True), self._adc(True):
            self.assertEqual(resolve_backend().kind, "api_key")

    def test_a_project_without_credentials_is_not_a_backend(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "p1"}, clear=True), self._no_key(), self._adc(False):
            self.assertIsNone(resolve_backend())

    def test_the_claude_vertex_project_is_inherited_as_a_last_resort(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_VERTEX_PROJECT_ID": "sercan"}, clear=True), self._no_key(), self._adc(True):
            self.assertEqual(resolve_backend().project, "sercan")

    def test_an_explicit_project_var_beats_the_inherited_one(self) -> None:
        env = {"AUTOR_VERTEX_PROJECT": "mine", "ANTHROPIC_VERTEX_PROJECT_ID": "inherited"}
        with patch.dict(os.environ, env, clear=True), self._no_key(), self._adc(True):
            self.assertEqual(resolve_backend().project, "mine")

    def test_an_explicit_model_overrides_the_vertex_default(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "p"}, clear=True), self._no_key(), self._adc(True):
            self.assertEqual(resolve_backend("gemini-x").model, "gemini-x")

    def test_the_notice_reports_vertex_rather_than_warning(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "p1"}, clear=True), self._no_key(), self._adc(True):
            message, level = web_search_notice("auto")
        self.assertEqual(level, "info")
        self.assertIn("Vertex AI", message)
        self.assertIn("p1", message)

    def test_auto_injects_the_prompt_block_on_a_vertex_only_box(self) -> None:
        """The regression this whole path exists for: no API key, but search does work."""
        with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "p1"}, clear=True), self._no_key(), self._adc(True):
            self.assertIsNotNone(resolve_web_search_context("auto"))

    def test_credentials_probe_never_returns_a_token(self) -> None:
        self.assertIsInstance(vertex_credentials_available(), bool)


class RedirectResolutionTest(unittest.TestCase):
    STUB = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC"

    def test_a_non_redirect_url_is_returned_untouched_without_a_request(self) -> None:
        with patch("urllib.request.urlopen", side_effect=AssertionError("should not be called")):
            self.assertEqual(resolve_source_url("https://arxiv.org/abs/1"), "https://arxiv.org/abs/1")

    def test_a_failed_resolution_keeps_the_source_rather_than_dropping_it(self) -> None:
        with patch("urllib.request.urlopen", side_effect=OSError("boom")):
            self.assertEqual(resolve_source_url(self.STUB), self.STUB)

    def test_an_unresolved_stub_is_flagged_as_not_citable(self) -> None:
        self.assertTrue(is_unresolved_redirect(self.STUB))
        self.assertFalse(is_unresolved_redirect("https://arxiv.org/abs/1"))
        body = format_response_markdown(
            WebSearchResponse("q", "m", "a", "vertex", [SearchResult("x", self.STUB)])
        )
        self.assertIn("not citable", body)

    def test_the_prompt_tells_operators_not_to_cite_an_unresolved_stub(self) -> None:
        self.assertIn("unresolved redirect", build_web_search_prompt_section())


class DedupeByUrlTest(unittest.TestCase):
    def test_two_redirects_resolving_to_one_page_collapse(self) -> None:
        """Dedup has to happen after resolution: distinct stubs reach the same source."""
        merged = dedupe_by_url([
            SearchResult("github.com", "https://github.com/a", []),
            SearchResult("github.com", "https://github.com/a", ["a claim"]),
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].supported_claims, ["a claim"])

    def test_merging_unions_the_claims_rather_than_choosing_between_them(self) -> None:
        """Keeping only one copy's claims would narrow what the source was cited for."""
        merged = dedupe_by_url([
            SearchResult("A", "https://a", ["first", "shared"]),
            SearchResult("A", "https://a", ["shared", "second"]),
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].supported_claims, ["first", "shared", "second"])

    def test_distinct_urls_are_preserved_in_order(self) -> None:
        merged = dedupe_by_url([
            SearchResult("a", "https://a"),
            SearchResult("b", "https://b"),
        ])
        self.assertEqual([r.url for r in merged], ["https://a", "https://b"])


class BackendJsonTest(unittest.TestCase):
    def test_json_output_records_which_backend_answered(self) -> None:
        payload = WebSearchResponse("q", "gemini-3.6-flash", "a", "vertex", []).to_dict()
        self.assertEqual(payload["backend"], "vertex")
        self.assertEqual(payload["model"], "gemini-3.6-flash")

    def test_markdown_names_vertex_as_the_provider(self) -> None:
        body = format_response_markdown(WebSearchResponse("q", "m", "a", "vertex", []))
        self.assertIn("Vertex AI", body)

    def test_markdown_names_the_gemini_api_for_key_backed_runs(self) -> None:
        body = format_response_markdown(WebSearchResponse("q", "m", "a", "api_key", []))
        self.assertIn("Gemini API", body)


class NoBackendTest(unittest.TestCase):
    def test_the_error_names_both_ways_to_configure_search(self) -> None:
        with patch.dict(os.environ, {}, clear=True), \
             patch("src.web_search.DIAGRAM_CONFIG_PATH", Path("/nonexistent/diagram.yaml")), \
             patch("src.web_search.vertex_credentials_available", return_value=False):
            with self.assertRaises(WebSearchError) as caught:
                gemini_web_search("anything")
        message = str(caught.exception)
        self.assertIn("GEMINI_API_KEY", message)
        self.assertIn("application-default", message)


class SupportedClaimProvenanceTest(unittest.TestCase):
    """One GroundingSupport routinely cites several chunks for one generated sentence.

    That is the mechanism by which a model-authored claim gets attached to a source that
    never made it, so the shape is pinned here rather than assumed.
    """

    def test_one_support_citing_two_chunks_reaches_both_results(self) -> None:
        response = _Response([
            _Candidate(
                _Metadata(
                    [_Chunk(_Web("https://arxiv.org/abs/1", "arxiv.org")),
                     _Chunk(_Web("https://blog.example/x", "blog.example"))],
                    [_Support("Retrieval cuts hallucination by 40%.", [0, 1])],
                )
            )
        ])

        results = extract_search_results(response)

        self.assertEqual(len(results), 2)
        for result in results:
            self.assertEqual(result.supported_claims, ["Retrieval cuts hallucination by 40%."])

    def test_two_supports_on_one_chunk_are_both_kept(self) -> None:
        response = _Response([
            _Candidate(
                _Metadata(
                    [_Chunk(_Web("https://a", "a"))],
                    [_Support("First, generic.", [0]), _Support("Second, specific.", [0])],
                )
            )
        ])

        self.assertEqual(
            extract_search_results(response)[0].supported_claims,
            ["First, generic.", "Second, specific."],
        )

    def test_a_repeated_claim_is_not_duplicated(self) -> None:
        response = _Response([
            _Candidate(
                _Metadata(
                    [_Chunk(_Web("https://a", "a"))],
                    [_Support("Same.", [0]), _Support("Same.", [0])],
                )
            )
        ])
        self.assertEqual(extract_search_results(response)[0].supported_claims, ["Same."])


class CitabilityInJsonTest(unittest.TestCase):
    """The prompt tells the agent to parse --json, so every judgement has to survive there.

    A groundedness signal that exists only in the markdown renderer is invisible to the
    consumer the tool actually advertises.
    """

    STUB = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC"

    def test_a_citable_result_marks_the_response_grounded(self) -> None:
        payload = WebSearchResponse(
            "q", "m", "a", "vertex", [SearchResult("A", "https://arxiv.org/abs/1")]
        ).to_dict()
        self.assertTrue(payload["grounded"])
        self.assertEqual(payload["citable_source_count"], 1)
        self.assertTrue(payload["results"][0]["citable"])

    def test_an_unresolved_stub_is_not_citable_and_not_grounded(self) -> None:
        payload = WebSearchResponse(
            "q", "m", "a", "vertex", [SearchResult("A", self.STUB)]
        ).to_dict()
        self.assertFalse(payload["grounded"])
        self.assertEqual(payload["citable_source_count"], 0)
        self.assertFalse(payload["results"][0]["citable"])

    def test_an_answer_with_no_sources_is_not_grounded(self) -> None:
        self.assertFalse(WebSearchResponse("q", "m", "an answer").to_dict()["grounded"])

    def test_the_json_key_does_not_call_model_output_a_snippet(self) -> None:
        payload = WebSearchResponse(
            "q", "m", "a", "vertex", [SearchResult("A", "https://a", ["claim"])]
        ).to_dict()
        self.assertNotIn("snippet", payload["results"][0])
        self.assertEqual(payload["results"][0]["supported_claims"], ["claim"])

    def test_the_prompt_advertises_the_schema_it_actually_emits(self) -> None:
        section = build_web_search_prompt_section()
        payload = WebSearchResponse(
            "q", "m", "a", "vertex", [SearchResult("A", "https://a", ["c"])]
        ).to_dict()
        for key in payload:
            self.assertIn(key, section, f"--json emits {key!r} but the prompt never mentions it")
        for key in payload["results"][0]:
            self.assertIn(key, section, f"a result carries {key!r} but the prompt never mentions it")

    def test_the_prompt_warns_that_claims_are_not_page_text(self) -> None:
        section = build_web_search_prompt_section()
        self.assertIn("not text from the source page", section)
        self.assertIn("Never transcribe it as a quotation", section)


class UngroundedExitCodeTest(unittest.TestCase):
    """Exiting 0 on an ungrounded answer lets it look like a successful search to `$?`."""

    def _run(self, response, argv):
        buffer, errors = io.StringIO(), io.StringIO()
        with patch("src.web_search.gemini_web_search", return_value=response):
            with redirect_stdout(buffer), redirect_stderr(errors):
                code = web_search_main(argv)
        return code, buffer.getvalue(), errors.getvalue()

    def test_a_grounded_answer_exits_zero(self) -> None:
        code, _, _ = self._run(
            WebSearchResponse("q", "m", "a", "vertex", [SearchResult("A", "https://arxiv.org/1")]),
            ["q"],
        )
        self.assertEqual(code, 0)

    def test_an_ungrounded_answer_exits_two_and_says_why(self) -> None:
        code, _, errors = self._run(WebSearchResponse("q", "m", "an answer"), ["q"])
        self.assertEqual(code, 2)
        self.assertIn("no citable source", errors)

    def test_the_ungrounded_exit_code_is_distinct_from_outright_failure(self) -> None:
        with patch("src.web_search.gemini_web_search", side_effect=WebSearchError("boom")):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(web_search_main(["q"]), 1)

    def test_the_prompt_documents_every_exit_code_main_can_return(self) -> None:
        section = build_web_search_prompt_section()
        for code in ("`0`", "`1`", "`2`"):
            self.assertIn(code, section)


class MaxResultsFloorTest(unittest.TestCase):
    def test_a_non_positive_cap_returns_nothing_rather_than_one(self) -> None:
        chunks = [_Chunk(_Web(f"https://example.org/{i}")) for i in range(3)]
        response = _Response([_Candidate(_Metadata(chunks))])
        for cap in (-5, -1, 0):
            with self.subTest(max_results=cap):
                self.assertEqual(extract_search_results(response, max_results=cap), [])

    def test_a_positive_cap_is_still_honoured_exactly(self) -> None:
        chunks = [_Chunk(_Web(f"https://example.org/{i}")) for i in range(10)]
        response = _Response([_Candidate(_Metadata(chunks))])
        for cap in (1, 3, 9):
            with self.subTest(max_results=cap):
                self.assertEqual(len(extract_search_results(response, max_results=cap)), cap)

    def test_the_cap_holds_across_several_candidates(self) -> None:
        response = _Response([
            _Candidate(_Metadata([_Chunk(_Web("https://a")), _Chunk(_Web("https://b"))])),
            _Candidate(_Metadata([_Chunk(_Web("https://c")), _Chunk(_Web("https://d"))])),
        ])
        self.assertEqual(len(extract_search_results(response, max_results=3)), 3)


class SourceTitleTest(unittest.TestCase):
    """Grounding labels every source with a bare domain, which identifies nothing."""

    def test_a_page_title_replaces_a_bare_domain(self) -> None:
        self.assertEqual(
            best_title("arxiv.org", "Attention Is All You Need", "https://arxiv.org/abs/1706.03762"),
            "Attention Is All You Need",
        )

    def test_a_www_prefixed_domain_is_still_a_bare_domain(self) -> None:
        self.assertEqual(best_title("nature.com", "A paper", "https://www.nature.com/x"), "A paper")

    def test_a_real_grounding_title_is_kept_over_the_page_title(self) -> None:
        self.assertEqual(
            best_title("Attention Is All You Need", "arXiv.org e-Print archive", "https://arxiv.org/abs/1"),
            "Attention Is All You Need",
        )

    def test_no_page_title_leaves_the_domain_in_place(self) -> None:
        self.assertEqual(best_title("arxiv.org", None, "https://arxiv.org/abs/1"), "arxiv.org")

    def test_a_title_equal_to_the_url_counts_as_bare(self) -> None:
        self.assertEqual(best_title("https://a/b", "Real Title", "https://a/b"), "Real Title")


class ResolveSourceTest(unittest.TestCase):
    STUB = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC"

    class _FakeResponse:
        def __init__(self, url: str, body: bytes) -> None:
            self.url = url
            self._body = body

        def read(self, size: int = -1) -> bytes:
            return self._body[:size] if size and size > 0 else self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> bool:
            return False

    def test_a_redirect_yields_both_the_target_and_its_title(self) -> None:
        page = b"<html><head><title>  Attention Is\nAll You Need </title></head>"
        with patch(
            "urllib.request.urlopen",
            return_value=self._FakeResponse("https://arxiv.org/abs/1706.03762", page),
        ):
            url, title = resolve_source(self.STUB)
        self.assertEqual(url, "https://arxiv.org/abs/1706.03762")
        self.assertEqual(title, "Attention Is All You Need")

    def test_html_entities_in_a_title_are_unescaped(self) -> None:
        with patch(
            "urllib.request.urlopen",
            return_value=self._FakeResponse("https://a/b", b"<title>A &amp; B</title>"),
        ):
            self.assertEqual(resolve_source(self.STUB)[1], "A & B")

    def test_a_runaway_title_is_truncated(self) -> None:
        """The title goes into a prompt, so an unbounded one is an unbounded token cost."""
        page = b"<title>" + b"x" * 5000 + b"</title>"
        with patch("urllib.request.urlopen", return_value=self._FakeResponse("https://a", page)):
            title = resolve_source(self.STUB)[1]
        self.assertEqual(len(title), 200)

    def test_a_page_with_no_title_resolves_the_url_anyway(self) -> None:
        with patch(
            "urllib.request.urlopen",
            return_value=self._FakeResponse("https://a/b", b"<html><body>x</body></html>"),
        ):
            self.assertEqual(resolve_source(self.STUB), ("https://a/b", None))

    def test_a_failed_resolution_reports_no_title_and_keeps_the_stub(self) -> None:
        with patch("urllib.request.urlopen", side_effect=OSError("boom")):
            self.assertEqual(resolve_source(self.STUB), (self.STUB, None))

    def test_a_non_redirect_is_not_fetched(self) -> None:
        with patch("urllib.request.urlopen", side_effect=AssertionError("should not be called")):
            self.assertEqual(resolve_source("https://arxiv.org/abs/1"), ("https://arxiv.org/abs/1", None))

    def test_the_body_read_is_capped(self) -> None:
        """An unbounded read turns one citation lookup into an arbitrary download."""
        seen: dict[str, int] = {}
        response = self._FakeResponse("https://a", b"<title>t</title>")
        original_read = response.read

        def recording_read(size: int = -1) -> bytes:
            seen["size"] = size
            return original_read(size)

        response.read = recording_read  # type: ignore[method-assign]
        with patch("urllib.request.urlopen", return_value=response):
            resolve_source(self.STUB)
        self.assertEqual(seen["size"], web_search_module.TITLE_SCAN_BYTES)
