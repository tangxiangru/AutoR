from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import main as autor_main
from src.utils import STAGES, build_prompt
from src.web_search import (
    DEFAULT_SEARCH_MODEL,
    DEFAULT_VERTEX_LOCATION,
    DEFAULT_VERTEX_SEARCH_MODEL,
    dedupe_by_url,
    is_unresolved_redirect,
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
        self.assertEqual(results[0], SearchResult("Paper A", "https://example.org/a", "Key finding."))
        self.assertEqual(results[1].title, "https://example.org/b")
        self.assertEqual(results[1].snippet, "")

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
            results=[SearchResult("Paper A", "https://example.org/a", "Snippet.")],
        )
        text = format_response_markdown(response)
        self.assertIn("# Web Search: q", text)
        self.assertIn("The answer.", text)
        self.assertIn("[Paper A](https://example.org/a)", text)
        self.assertIn("> Snippet.", text)

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
            with redirect_stdout(io.StringIO()):
                web_search_main(["black", "hole", "superradiance"])

        self.assertEqual(captured["query"], "black hole superradiance")

    def test_a_failed_search_exits_nonzero(self) -> None:
        with patch("src.web_search.gemini_web_search", side_effect=WebSearchError("no key")):
            with redirect_stdout(io.StringIO()):
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
            SearchResult("github.com", "https://github.com/a", ""),
            SearchResult("github.com", "https://github.com/a", "a longer snippet"),
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].snippet, "a longer snippet")

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
