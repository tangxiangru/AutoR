from __future__ import annotations

import builtins
import contextlib
import importlib.util
import io
import json
import os
import re
import tempfile
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import main as autor_main
from src import web_search as web_search_module
from src.utils import STAGES, build_prompt
from src.web_search import (
    DEFAULT_SEARCH_MODEL,
    DEFAULT_VERTEX_LOCATION,
    DEFAULT_VERTEX_SEARCH_MODEL,
    assess_search_readiness,
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


def _module_installed(name: str) -> bool:
    """Whether an optional dependency is importable, without raising if it is not.

    `find_spec` raises rather than returning None when a parent package is missing, so a
    bare call here would fail at class-definition time on exactly the machines this guard
    exists for.
    """
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


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
            return WebSearchResponse(query, "m", "a", "api_key", [])

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

    @staticmethod
    def _advertised_script(section: str) -> Path:
        """The path the section actually tells the operator to run."""
        match = re.search(r"^(\S+) \"([^\"]+)\" \"your search query", section, re.MULTILINE)
        assert match is not None, f"no runnable command found in section:\n{section}"
        return Path(match.group(2))

    def test_the_script_the_section_advertises_actually_exists(self) -> None:
        """Read the value the test is named for, rather than rebuilding it.

        Rebuilding tests/../tools/web_search.py from __file__ cannot see a change to
        WEB_SEARCH_SCRIPT, so the constant could point anywhere and the suite stayed green
        while every search died with 'No such file or directory'.
        """
        self.assertTrue(self._advertised_script(build_web_search_prompt_section()).exists())

    def test_that_guard_can_actually_fail(self) -> None:
        """A guard never shown to fire is not a guard."""
        section = build_web_search_prompt_section(script_path=Path("/nonexistent/web_search.py"))
        self.assertFalse(self._advertised_script(section).exists())

    def test_the_advertised_path_is_exact_not_merely_a_prefix(self) -> None:
        """`assertIn("tools/web_search.py", section)` is satisfied by
        tools/web_search.py.bak, so it cannot catch a rename."""
        advertised = self._advertised_script(build_web_search_prompt_section())
        self.assertEqual(advertised.name, "web_search.py")
        self.assertEqual(advertised, web_search_module.WEB_SEARCH_SCRIPT.resolve())

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
    @staticmethod
    def _sdk(available: bool = True):
        """State the SDK assumption explicitly.

        Credentials alone no longer mean `auto` injects: `google-genai` also has to be
        importable, and it is not installed in CI. Without this, these tests pass on a dev
        box and fail in CI for a reason that has nothing to do with what they check.
        """
        return patch("src.web_search.genai_sdk_available", return_value=available)

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
        with patch.dict(os.environ, {"GEMINI_API_KEY": "k"}, clear=True), self._sdk():
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
    @staticmethod
    def _sdk(available: bool = True):
        """State the SDK assumption explicitly.

        Credentials alone no longer mean `auto` injects: `google-genai` also has to be
        importable, and it is not installed in CI. Without this, these tests pass on a dev
        box and fail in CI for a reason that has nothing to do with what they check.
        """
        return patch("src.web_search.genai_sdk_available", return_value=available)

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
        with patch.dict(os.environ, {"GEMINI_API_KEY": "k"}, clear=True), self._sdk():
            self.assertIsNotNone(autor_main.resolve_web_search_context("auto"))

    def test_the_rcb_adapter_resolves_the_same_way(self) -> None:
        """One implementation, not two agreeing implementations.

        This used to compare the two entry points' results in a single
        auto-with-credentials cell -- the one cell where both returned non-None anyway.
        An RCB-local copy that always injected would have survived it. Identity covers
        every mode and credential combination at once, and is what actually holds now
        that the duplication is gone.
        """
        import rcb_agent
        from src import web_search

        for name in ("resolve_web_search_context", "web_search_notice", "assess_search_readiness"):
            with self.subTest(function=name):
                canonical = getattr(web_search, name)
                self.assertIs(getattr(rcb_agent, name), canonical)
                self.assertIs(getattr(autor_main, name), canonical)

    def test_the_two_entry_points_agree_on_every_mode(self) -> None:
        import rcb_agent

        for mode in ("auto", "gemini", "native"):
            for env in ({"GEMINI_API_KEY": "k"}, {}):
                with self.subTest(mode=mode, keyed=bool(env)):
                    with patch.dict(os.environ, env, clear=True), \
                         patch("src.web_search.DIAGRAM_CONFIG_PATH", Path("/nonexistent/d.yaml")), \
                         patch("src.web_search.vertex_credentials_available", return_value=False):
                        self.assertEqual(
                            rcb_agent.resolve_web_search_context(mode),
                            autor_main.resolve_web_search_context(mode),
            )


if __name__ == "__main__":
    unittest.main()


class VertexBackendTest(unittest.TestCase):
    @staticmethod
    def _sdk(available: bool = True):
        """State the SDK assumption explicitly.

        Credentials alone no longer mean `auto` injects: `google-genai` also has to be
        importable, and it is not installed in CI. Without this, these tests pass on a dev
        box and fail in CI for a reason that has nothing to do with what they check.
        """
        return patch("src.web_search.genai_sdk_available", return_value=available)

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
        with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "p1"}, clear=True), self._no_key(), self._adc(True), self._sdk():
            message, level = web_search_notice("auto")
        self.assertEqual(level, "info")
        self.assertIn("Vertex AI", message)
        self.assertIn("p1", message)

    def test_auto_injects_the_prompt_block_on_a_vertex_only_box(self) -> None:
        """The regression this whole path exists for: no API key, but search does work."""
        with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "p1"}, clear=True), self._no_key(), self._adc(True), self._sdk():
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


class SearchReadinessTest(unittest.TestCase):
    """Credentials alone are not a promise that the tool can run.

    The prompt block tells the operator "the built-in WebSearch tool is disabled, use this
    script instead". Three further things have to be true for that to be honest.
    """

    KEY = {"GEMINI_API_KEY": "k"}

    def _readiness(self, *, env=None, sdk=True, **kwargs):
        with patch.dict(os.environ, env if env is not None else self.KEY, clear=True), \
             patch("src.web_search.DIAGRAM_CONFIG_PATH", Path("/nonexistent/diagram.yaml")), \
             patch("src.web_search.genai_sdk_available", return_value=sdk):
            return assess_search_readiness(**kwargs)

    def test_a_key_and_the_sdk_and_no_sandbox_is_usable(self) -> None:
        readiness = self._readiness()
        self.assertTrue(readiness.usable)
        self.assertIsNone(readiness.blocker)
        self.assertIsNone(readiness.hard_blocker)

    def test_a_missing_sdk_blocks_even_with_a_key(self) -> None:
        """google-genai is not a default dependency, and the Vertex probe uses google.auth
        — a different distribution that can be installed without it."""
        readiness = self._readiness(sdk=False)
        self.assertFalse(readiness.usable)
        self.assertIn("google-genai", readiness.blocker)
        self.assertIn("pip install google-genai", readiness.hard_blocker)

    def test_no_credentials_blocks(self) -> None:
        with patch("src.web_search.vertex_credentials_available", return_value=False):
            readiness = self._readiness(env={})
        self.assertFalse(readiness.usable)
        self.assertIn("no Gemini backend", readiness.blocker)

    def test_the_missing_backend_is_reported_before_the_missing_sdk(self) -> None:
        with patch("src.web_search.vertex_credentials_available", return_value=False):
            readiness = self._readiness(env={}, sdk=False)
        self.assertIn("no Gemini backend", readiness.blocker)

    def test_a_network_restricted_codex_sandbox_blocks(self) -> None:
        for sandbox in ("read-only", "workspace-write"):
            with self.subTest(sandbox=sandbox):
                readiness = self._readiness(operator="codex", codex_sandbox=sandbox)
                self.assertFalse(readiness.usable)
                self.assertIn("Codex sandbox", readiness.blocker)
                self.assertIn(sandbox, readiness.blocker)

    def test_the_codex_default_sandbox_is_the_restricted_one(self) -> None:
        """Passing no --codex-sandbox is the common case, and its default blocks egress."""
        self.assertIn("workspace-write", self._readiness(operator="codex").blocker)

    def test_full_access_codex_is_not_blocked(self) -> None:
        readiness = self._readiness(operator="codex", codex_sandbox="danger-full-access")
        self.assertTrue(readiness.usable)

    def test_claude_is_never_sandbox_blocked(self) -> None:
        readiness = self._readiness(operator="claude", codex_sandbox="workspace-write")
        self.assertTrue(readiness.usable)

    def test_the_sandbox_blocker_is_not_hard_enough_to_abort_a_run(self) -> None:
        """It is inferred from the requested mode, not observed, so it warns rather than
        failing a run that might actually have worked."""
        readiness = self._readiness(operator="codex", codex_sandbox="workspace-write")
        self.assertIsNotNone(readiness.blocker)
        self.assertIsNone(readiness.hard_blocker)

    def test_every_blocker_names_a_remedy(self) -> None:
        cases = [
            self._readiness(sdk=False),
            self._readiness(operator="codex", codex_sandbox="workspace-write"),
        ]
        with patch("src.web_search.vertex_credentials_available", return_value=False):
            cases.append(self._readiness(env={}))
        for readiness in cases:
            with self.subTest(blocker=readiness.blocker):
                self.assertRegex(readiness.blocker, r"Set |Install |Use |pip install|--")


class ReadinessDrivesTheDecisionTest(unittest.TestCase):
    USABLE = web_search_module.SearchReadiness(
        backend=web_search_module.SearchBackend(kind="api_key", model="m", api_key="k"),
        sdk_available=True,
    )
    NO_SDK = web_search_module.SearchReadiness(
        backend=web_search_module.SearchBackend(kind="api_key", model="m", api_key="k"),
        sdk_available=False,
    )
    SANDBOXED = web_search_module.SearchReadiness(
        backend=web_search_module.SearchBackend(kind="api_key", model="m", api_key="k"),
        sdk_available=True,
        sandbox_blocker="the Codex sandbox `workspace-write` restricts outbound network access.",
    )

    def test_auto_falls_back_when_the_sdk_is_missing(self) -> None:
        self.assertIsNone(resolve_web_search_context("auto", readiness=self.NO_SDK))

    def test_auto_falls_back_when_the_sandbox_blocks_egress(self) -> None:
        self.assertIsNone(resolve_web_search_context("auto", readiness=self.SANDBOXED))

    def test_auto_injects_when_everything_checks_out(self) -> None:
        self.assertIsNotNone(resolve_web_search_context("auto", readiness=self.USABLE))

    def test_native_never_injects(self) -> None:
        for readiness in (self.USABLE, self.NO_SDK, self.SANDBOXED):
            self.assertIsNone(resolve_web_search_context("native", readiness=readiness))

    def test_the_notice_names_the_specific_blocker_not_just_the_key(self) -> None:
        message, level = web_search_notice("auto", readiness=self.NO_SDK)
        self.assertEqual(level, "warn")
        self.assertIn("google-genai", message)

    def test_an_explicit_gemini_request_reports_the_blocker_at_error_level(self) -> None:
        message, level = web_search_notice("gemini", readiness=self.NO_SDK)
        self.assertEqual(level, "error")
        self.assertIn("google-genai", message)

    def test_a_usable_backend_is_reported_at_info_level(self) -> None:
        for mode in ("auto", "gemini"):
            message, level = web_search_notice(mode, readiness=self.USABLE)
            self.assertEqual(level, "info")
            self.assertIn("Gemini API", message)


class AdvertisedInterpreterTest(unittest.TestCase):
    def test_the_section_names_this_interpreter_not_a_bare_python3(self) -> None:
        """`python3` is whatever the agent's PATH resolves it to, which need not be the
        interpreter whose site-packages we checked for google-genai."""
        section = build_web_search_prompt_section()
        self.assertIn(sys.executable, section)

    def test_an_interpreter_path_with_spaces_is_quoted(self) -> None:
        with patch.object(web_search_module.sys, "executable", "/opt/my env/bin/python"):
            section = build_web_search_prompt_section()
        self.assertIn("'/opt/my env/bin/python'", section)

    def test_it_falls_back_to_python3_when_the_interpreter_is_unknown(self) -> None:
        with patch.object(web_search_module.sys, "executable", ""):
            self.assertEqual(web_search_module.search_command_prefix(), "python3")


class ExplicitGeminiRefusalTest(unittest.TestCase):
    """`--web-search gemini` plus a certain blocker is a configuration error.

    Continuing means every stage prompt asserts a working search tool that fails on first
    use, and Stage 01 spends its retry budget before falling back to memory.
    """

    def _run_main(self, argv):
        # TerminalUI binds sys.stdout as a default argument at import time, so
        # redirect_stdout cannot reach it; silence the banner at the source.
        with patch.object(sys, "argv", ["main.py", *argv]), \
             patch("src.terminal_ui.TerminalUI.show_banner"), \
             patch("src.terminal_ui.TerminalUI.show_status"):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                return autor_main.main()

    def test_a_keyless_explicit_gemini_run_is_refused(self) -> None:
        with patch.dict(os.environ, {}, clear=True), \
             patch("src.web_search.DIAGRAM_CONFIG_PATH", Path("/nonexistent/diagram.yaml")), \
             patch("src.web_search.vertex_credentials_available", return_value=False):
            with self.assertRaises(ValueError) as caught:
                self._run_main(["--web-search", "gemini", "--goal", "x", "--fake-operator"])
        self.assertIn("--web-search gemini cannot work here", str(caught.exception))
        self.assertIn("no Gemini backend", str(caught.exception))

    def test_the_refusal_names_a_way_out(self) -> None:
        with patch.dict(os.environ, {}, clear=True), \
             patch("src.web_search.DIAGRAM_CONFIG_PATH", Path("/nonexistent/diagram.yaml")), \
             patch("src.web_search.vertex_credentials_available", return_value=False):
            with self.assertRaises(ValueError) as caught:
                self._run_main(["--web-search", "gemini", "--goal", "x", "--fake-operator"])
        self.assertIn("--web-search auto", str(caught.exception))

    def test_auto_is_not_refused_without_credentials(self) -> None:
        """auto degrading to native is the designed path and must never abort."""
        with patch.dict(os.environ, {}, clear=True), \
             patch("src.web_search.DIAGRAM_CONFIG_PATH", Path("/nonexistent/diagram.yaml")), \
             patch("src.web_search.vertex_credentials_available", return_value=False):
            readiness = assess_search_readiness()
            self.assertIsNone(resolve_web_search_context("auto", readiness=readiness))
            self.assertIsNotNone(readiness.hard_blocker)

    def test_a_sandbox_blocker_alone_does_not_refuse_the_run(self) -> None:
        with patch.dict(os.environ, {"GEMINI_API_KEY": "k"}, clear=True), \
             patch("src.web_search.genai_sdk_available", return_value=True):
            readiness = assess_search_readiness(operator="codex", codex_sandbox="workspace-write")
        self.assertIsNone(readiness.hard_blocker)


class GenaiSdkProbeTest(unittest.TestCase):
    """The probe itself, not a patched stand-in for it.

    Every other readiness test patches `genai_sdk_available`, which would leave the real
    function free to always answer True.
    """

    def test_it_reports_the_sdk_missing_when_it_cannot_be_found(self) -> None:
        with patch("importlib.util.find_spec", return_value=None) as find_spec:
            self.assertFalse(web_search_module.genai_sdk_available())
        find_spec.assert_called_once_with("google.genai")

    def test_it_reports_the_sdk_present_when_it_can(self) -> None:
        with patch("importlib.util.find_spec", return_value=object()):
            self.assertTrue(web_search_module.genai_sdk_available())

    def test_a_missing_parent_package_reports_absent_rather_than_raising(self) -> None:
        """`find_spec("google.genai")` imports `google` to search it, so on a machine with
        no `google` namespace at all it raises ModuleNotFoundError -- precisely the case
        this probe exists to detect. Letting that escape takes down every entry point,
        which is how CI caught it."""
        with patch("importlib.util.find_spec", side_effect=ModuleNotFoundError("No module named 'google'")):
            self.assertFalse(web_search_module.genai_sdk_available())

    def test_other_import_failures_also_report_absent(self) -> None:
        for error in (ImportError("broken"), ValueError("__spec__ is None"), AttributeError("x")):
            with self.subTest(error=type(error).__name__):
                with patch("importlib.util.find_spec", side_effect=error):
                    self.assertFalse(web_search_module.genai_sdk_available())

    def test_it_probes_google_genai_and_not_google_auth(self) -> None:
        """`google-auth` is a separate distribution and can be installed without
        `google-genai`, so probing it would answer the wrong question."""
        seen: list[str] = []

        def record(name):
            seen.append(name)
            return None

        with patch("importlib.util.find_spec", side_effect=record):
            web_search_module.genai_sdk_available()
        self.assertEqual(seen, ["google.genai"])


class MainPassesTheOperatorToReadinessTest(unittest.TestCase):
    """The sandbox is only knowable from the operator, so the gate has to be told which one.

    `main.py` resolves the search context before the resume branch reads `run_config`, so
    the flag is the only source, and passing None here would silently drop the whole
    sandbox check on every Codex run.
    """

    def test_the_operator_and_sandbox_flags_reach_the_assessment(self) -> None:
        captured: dict[str, object] = {}

        class _Stop(BaseException):
            """Abort main() at the assessment; running the pipeline is not the point."""

        def record(**kwargs):
            captured.update(kwargs)
            raise _Stop

        with patch("main.assess_search_readiness", side_effect=record), \
             patch("src.terminal_ui.TerminalUI.show_banner"), \
             patch.object(sys, "argv", ["main.py", "--operator", "codex",
                                        "--codex-sandbox", "workspace-write",
                                        "--web-search", "native", "--goal", "x",
                                        "--fake-operator", "--skip-intake"]):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                try:
                    autor_main.main()
                except _Stop:
                    pass

        self.assertEqual(captured.get("operator"), "codex")
        self.assertEqual(captured.get("codex_sandbox"), "workspace-write")

    def test_it_defaults_to_claude_rather_than_none(self) -> None:
        captured: dict[str, object] = {}

        class _Stop(BaseException):
            """Abort main() at the assessment; running the pipeline is not the point."""

        def record(**kwargs):
            captured.update(kwargs)
            raise _Stop

        with patch("main.assess_search_readiness", side_effect=record), \
             patch("src.terminal_ui.TerminalUI.show_banner"), \
             patch.object(sys, "argv", ["main.py", "--web-search", "native", "--goal", "x",
                                        "--fake-operator", "--skip-intake"]):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                try:
                    autor_main.main()
                except _Stop:
                    pass

        self.assertEqual(captured.get("operator"), "claude")


class ConfigFileReadTest(unittest.TestCase):
    """The key resolver sits on the startup path of every run, so it must not end one.

    `pyyaml` is optional and the config is hand-edited; a missing package or a stray tab
    used to raise out of main() before the banner printed.

    Driven through a stand-in `yaml` module, because pyyaml is not a dependency and is
    absent in CI -- where a skip would hide every one of these. The one test that needs
    the real parser says so.
    """

    @staticmethod
    def _yaml_stub(result=None, error=None):
        module = ModuleType("yaml")

        def safe_load(_handle):
            if error is not None:
                raise error
            return result

        module.safe_load = safe_load
        return module

    def _resolve(self, *, yaml_module=None, open_error=None, contents="api_keys:\n"):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "diagram_config.yaml"
            path.write_text(contents)
            stack = [
                patch.dict(os.environ, {}, clear=True),
                patch("src.web_search.DIAGRAM_CONFIG_PATH", path),
            ]
            if yaml_module is not None:
                stack.append(patch.dict(sys.modules, {"yaml": yaml_module}))
            if open_error is not None:
                stack.append(patch("builtins.open", side_effect=open_error))
            errors = io.StringIO()
            with contextlib.ExitStack() as exits:
                for ctx in stack:
                    exits.enter_context(ctx)
                exits.enter_context(redirect_stderr(errors))
                return resolve_gemini_api_key(), errors.getvalue()

    def test_a_key_in_the_config_file_is_read(self) -> None:
        key, errors = self._resolve(
            yaml_module=self._yaml_stub({"api_keys": {"google_api_key": "from-file"}})
        )
        self.assertEqual(key, "from-file")
        self.assertEqual(errors, "")

    def test_the_second_key_name_is_also_accepted(self) -> None:
        key, _ = self._resolve(
            yaml_module=self._yaml_stub({"api_keys": {"gemini_api_key": "second"}})
        )
        self.assertEqual(key, "second")

    def test_malformed_yaml_reports_no_key_instead_of_raising(self) -> None:
        key, errors = self._resolve(
            yaml_module=self._yaml_stub(error=ValueError("mapping values are not allowed here"))
        )
        self.assertIsNone(key)
        self.assertIn("could not read", errors)
        self.assertIn("mapping values", errors)

    def test_a_config_that_is_not_a_mapping_is_handled_cleanly(self) -> None:
        """Valid YAML of the wrong shape is not a parse failure, so it must not be
        reported as one. Without the isinstance guard this still returns None -- by
        raising AttributeError into the catch-all -- and the absence of a warning is the
        only thing that tells the two apart."""
        key, errors = self._resolve(yaml_module=self._yaml_stub(["just", "a", "list"]))
        self.assertIsNone(key)
        self.assertEqual(errors, "")

    def test_an_empty_config_reports_no_key_quietly(self) -> None:
        key, errors = self._resolve(yaml_module=self._yaml_stub(None))
        self.assertIsNone(key)
        self.assertEqual(errors, "")

    def test_a_config_without_an_api_keys_block_reports_no_key_quietly(self) -> None:
        key, errors = self._resolve(yaml_module=self._yaml_stub({"defaults": {"model_name": "x"}}))
        self.assertIsNone(key)
        self.assertEqual(errors, "")

    def test_a_missing_pyyaml_reports_no_key_and_names_the_remedy(self) -> None:
        real_import = builtins.__import__

        def no_yaml(name, *args, **kwargs):
            if name == "yaml":
                raise ImportError("No module named 'yaml'")
            return real_import(name, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "diagram_config.yaml"
            path.write_text("api_keys:\n")
            errors = io.StringIO()
            with patch.dict(os.environ, {}, clear=True), \
                 patch("src.web_search.DIAGRAM_CONFIG_PATH", path), \
                 patch.dict(sys.modules, {}, clear=False), \
                 patch("builtins.__import__", side_effect=no_yaml), \
                 redirect_stderr(errors):
                sys.modules.pop("yaml", None)
                key = resolve_gemini_api_key()
        self.assertIsNone(key)
        self.assertIn("pyyaml is not installed", errors.getvalue())
        self.assertIn("GEMINI_API_KEY", errors.getvalue())

    def test_an_unreadable_config_reports_no_key(self) -> None:
        key, errors = self._resolve(
            yaml_module=self._yaml_stub({}), open_error=PermissionError("nope")
        )
        self.assertIsNone(key)
        self.assertIn("could not read", errors)

    def test_a_missing_config_file_is_silent(self) -> None:
        with patch.dict(os.environ, {}, clear=True), \
             patch("src.web_search.DIAGRAM_CONFIG_PATH", Path("/nonexistent/diagram.yaml")), \
             redirect_stderr(io.StringIO()) as errors:
            self.assertIsNone(resolve_gemini_api_key())
        self.assertEqual(errors.getvalue(), "")

    def test_an_environment_key_short_circuits_the_file_entirely(self) -> None:
        """A broken config must not matter when the environment already answered."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "diagram_config.yaml"
            path.write_text("{[not yaml\n")
            with patch.dict(os.environ, {"GEMINI_API_KEY": "env-key"}, clear=True), \
                 patch("src.web_search.DIAGRAM_CONFIG_PATH", path), \
                 redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(resolve_gemini_api_key(), "env-key")
            self.assertEqual(errors.getvalue(), "")

    @unittest.skipUnless(
        _module_installed("yaml"),
        "pyyaml is not installed; the stand-in covers the rest of this class",
    )
    def test_the_real_parser_rejects_genuinely_malformed_yaml(self) -> None:
        """The stand-in cannot tell us what real pyyaml actually raises."""
        key, errors = self._resolve(contents="api_keys:\n\tgoogle_api_key: x\n  bad: [\n")
        self.assertIsNone(key)
        self.assertIn("could not read", errors)


class SearchRetryAndTimeoutTest(unittest.TestCase):
    """Stage 01 issues dozens of searches over hours; the SDK default is one attempt.

    Driven through a stand-in `types` module rather than the real SDK, which is not a
    dependency and is absent in CI -- the same reason a skip here would hide the whole
    class. `test_the_real_sdk_accepts_these_options` is the one that needs it, and says so.
    """

    class _FakeTypes:
        """Records what HttpOptions was asked for."""

        class HttpRetryOptions:
            def __init__(self, attempts, initial_delay, max_delay):
                self.attempts = attempts
                self.initial_delay = initial_delay
                self.max_delay = max_delay

        class HttpOptions:
            def __init__(self, timeout, retry_options):
                self.timeout = timeout
                self.retry_options = retry_options

    def _options(self):
        return web_search_module._http_options(self._FakeTypes)

    def test_a_timeout_and_retry_are_configured(self) -> None:
        options = self._options()
        self.assertIsNotNone(options)
        self.assertEqual(options.timeout, web_search_module.SEARCH_TIMEOUT_MS)
        self.assertEqual(options.retry_options.attempts, web_search_module.SEARCH_RETRY_ATTEMPTS)

    def test_retry_is_more_than_the_sdk_default_of_one_attempt(self) -> None:
        self.assertGreater(self._options().retry_options.attempts, 1)

    def test_a_timeout_is_set_at_all(self) -> None:
        """Without one, a hung connection burns the whole --stage-timeout."""
        self.assertGreater(self._options().timeout, 0)

    def test_the_backoff_grows(self) -> None:
        retry = self._options().retry_options
        self.assertGreater(retry.max_delay, retry.initial_delay)

    def test_an_sdk_without_retry_options_degrades_instead_of_crashing(self) -> None:
        class _OldTypes:
            HttpOptions = object  # present, but no HttpRetryOptions

        self.assertIsNone(web_search_module._http_options(_OldTypes))

    def test_an_sdk_without_http_options_at_all_degrades(self) -> None:
        self.assertIsNone(web_search_module._http_options(object()))

    @unittest.skipIf(
        not web_search_module.genai_sdk_available(),
        "google-genai is not installed; the stand-in covers the rest of this class",
    )
    def test_the_real_sdk_accepts_these_options(self) -> None:
        """The stand-in cannot catch a signature the real SDK would reject."""
        from google.genai import types

        options = web_search_module._http_options(types)
        self.assertIsNotNone(options)
        self.assertEqual(options.timeout, web_search_module.SEARCH_TIMEOUT_MS)
        self.assertEqual(options.retry_options.attempts, web_search_module.SEARCH_RETRY_ATTEMPTS)

    def _captured_client_kwargs(self, backend):
        captured: dict[str, object] = {}

        class _FakeClient:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        fake_genai = ModuleType("google.genai")
        fake_genai.Client = _FakeClient
        fake_google = ModuleType("google")
        fake_google.genai = fake_genai
        with patch.dict(
            sys.modules,
            {"google": fake_google, "google.genai": fake_genai, "google.genai.types": self._FakeTypes},
        ):
            web_search_module.build_genai_client(backend)
        return captured

    def test_the_client_is_built_with_those_options(self) -> None:
        captured = self._captured_client_kwargs(
            web_search_module.SearchBackend(kind="api_key", model="m", api_key="k")
        )
        self.assertEqual(captured.get("api_key"), "k")
        self.assertEqual(captured["http_options"].timeout, web_search_module.SEARCH_TIMEOUT_MS)

    def test_the_vertex_client_gets_them_too(self) -> None:
        captured = self._captured_client_kwargs(
            web_search_module.SearchBackend(
                kind="vertex", model="m", project="p", location="global"
            )
        )
        self.assertEqual(captured.get("project"), "p")
        self.assertEqual(captured["http_options"].timeout, web_search_module.SEARCH_TIMEOUT_MS)


class WebSearchModePersistenceTest(unittest.TestCase):
    """`--web-search` was the only backend selection not recorded in run_config.json.

    operator, model, venue, codex_sandbox, approval_mode, review_operator, review_model
    and output_format are all persisted and reconciled on resume. This one was re-derived
    from the ambient environment every time, so a resumed run could silently change what
    it told the operator about the deployment -- and with Vertex ADC in the mix, the input
    to that decision is an expiring credential.
    """

    def _paths(self, tmp):
        from src.utils import build_run_paths, ensure_run_layout

        paths = build_run_paths(Path(tmp) / "run")
        ensure_run_layout(paths)
        return paths

    def test_the_mode_round_trips_through_the_config(self) -> None:
        from src.utils import load_run_config, save_run_config

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            for mode in ("auto", "gemini", "native"):
                with self.subTest(mode=mode):
                    save_run_config(paths, {"web_search": mode})
                    self.assertEqual(load_run_config(paths)["web_search"], mode)

    def test_a_legacy_config_without_the_key_reads_as_auto(self) -> None:
        """Runs created before this existed must keep working."""
        from src.utils import load_run_config

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            paths.run_config.write_text(json.dumps({"model": "sonnet", "operator": "claude"}))
            self.assertEqual(load_run_config(paths)["web_search"], "auto")

    def test_a_bogus_persisted_mode_is_clamped(self) -> None:
        from src.utils import load_run_config

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            paths.run_config.write_text(json.dumps({"web_search": "sideways"}))
            self.assertEqual(load_run_config(paths)["web_search"], "auto")

    def test_the_default_config_carries_the_key(self) -> None:
        from src.utils import default_run_config

        self.assertEqual(default_run_config()["web_search"], "auto")

    def test_ensure_preserves_the_recorded_mode_when_no_flag_is_given(self) -> None:
        from src.utils import ensure_run_config

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            ensure_run_config(paths, model="sonnet", web_search="gemini")
            self.assertEqual(ensure_run_config(paths, model="sonnet")["web_search"], "gemini")

    def test_an_explicit_flag_overrides_the_recorded_mode(self) -> None:
        from src.utils import ensure_run_config

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            ensure_run_config(paths, model="sonnet", web_search="gemini")
            self.assertEqual(
                ensure_run_config(paths, model="sonnet", web_search="native")["web_search"],
                "native",
            )

    def test_it_is_persisted_beside_every_other_selection(self) -> None:
        """A field the writer drops is a field the resume cannot reconcile."""
        from src.utils import default_run_config, load_run_config, save_run_config

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            save_run_config(paths, default_run_config())
            written = json.loads(paths.run_config.read_text())
        for key in ("operator", "model", "venue", "codex_sandbox", "approval_mode", "web_search"):
            self.assertIn(key, written)
        self.assertEqual(set(load_run_config(paths)) - {"created_at"}, set(written) - {"created_at"})


class NormalizeWebSearchModeTest(unittest.TestCase):
    def test_known_modes_survive(self) -> None:
        from src.utils import normalize_web_search_mode

        for mode in ("auto", "gemini", "native"):
            self.assertEqual(normalize_web_search_mode(mode), mode)

    def test_case_and_padding_are_tolerated(self) -> None:
        from src.utils import normalize_web_search_mode

        self.assertEqual(normalize_web_search_mode("  GEMINI "), "gemini")

    def test_anything_else_falls_back_to_auto(self) -> None:
        from src.utils import normalize_web_search_mode

        for value in (None, "", "sideways", 7, [], {"a": 1}):
            with self.subTest(value=value):
                self.assertEqual(normalize_web_search_mode(value), "auto")

    def test_the_cli_accepts_exactly_the_modes_the_config_can_store(self) -> None:
        """A flag value the config cannot store would be silently downgraded on resume."""
        from src.utils import WEB_SEARCH_MODE_CHOICES, normalize_web_search_mode

        for mode in WEB_SEARCH_MODE_CHOICES:
            with self.subTest(mode=mode):
                with patch.object(sys, "argv", ["main.py", "--web-search", mode, "--goal", "g"]):
                    args = autor_main.parse_args()
                self.assertEqual(args.web_search, mode)
                self.assertEqual(normalize_web_search_mode(args.web_search), mode)

    def test_the_cli_rejects_a_mode_the_config_would_clamp(self) -> None:
        with patch.object(sys, "argv", ["main.py", "--web-search", "sideways", "--goal", "g"]):
            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    autor_main.parse_args()

    def test_omitting_the_flag_is_distinguishable_from_passing_auto(self) -> None:
        """Without this, a resume could not tell "keep what the run recorded" from
        "the user asked for auto", and the recorded mode would be overwritten every time."""
        with patch.object(sys, "argv", ["main.py", "--goal", "g"]):
            self.assertIsNone(autor_main.parse_args().web_search)
        with patch.object(sys, "argv", ["main.py", "--goal", "g", "--web-search", "auto"]):
            self.assertEqual(autor_main.parse_args().web_search, "auto")


class WebSearchModeReachesTheRunTest(unittest.TestCase):
    """End to end through the real CLI: the mode has to survive to run_config.json.

    The unit tests above prove `src/utils.py` can round-trip the field. These prove the
    manager actually hands it over and that the resume branch reconciles it -- the two
    seams where dropping it is invisible, because the run still works and just searches
    differently than it was told to.
    """

    REPO_ROOT = Path(__file__).resolve().parent.parent

    def _run_cli(self, runs_dir: Path, *extra: str, stdin: str = "6\n"):
        return subprocess.run(
            [sys.executable, "main.py", "--fake-operator", "--runs-dir", str(runs_dir), *extra],
            cwd=self.REPO_ROOT,
            input=stdin,
            text=True,
            capture_output=True,
        )

    @staticmethod
    def _recorded(runs_dir: Path) -> dict:
        run_root = sorted(p for p in runs_dir.iterdir() if p.is_dir())[-1]
        return json.loads((run_root / "run_config.json").read_text()), run_root

    def test_a_new_run_records_the_mode_it_was_started_with(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp) / "runs"
            result = self._run_cli(runs_dir, "--goal", "record the mode", "--web-search", "native")
            self.assertEqual(result.returncode, 1, msg=result.stderr)
            config, _ = self._recorded(runs_dir)
        self.assertEqual(config["web_search"], "native")

    def test_a_new_run_without_the_flag_records_the_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp) / "runs"
            result = self._run_cli(runs_dir, "--goal", "default mode")
            self.assertEqual(result.returncode, 1, msg=result.stderr)
            config, _ = self._recorded(runs_dir)
        self.assertEqual(config["web_search"], "auto")

    def test_a_resume_without_the_flag_keeps_the_recorded_mode(self) -> None:
        """This is the defect: the mode used to be re-derived from the environment on
        every resume, so a run started with --web-search native could quietly start
        telling operators that WebSearch is disabled halfway through."""
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp) / "runs"
            self._run_cli(runs_dir, "--goal", "resume keeps mode", "--web-search", "native")
            config, run_root = self._recorded(runs_dir)
            self.assertEqual(config["web_search"], "native")

            result = self._run_cli(runs_dir, "--resume-run", run_root.name)
            self.assertEqual(result.returncode, 1, msg=result.stderr)
            config, _ = self._recorded(runs_dir)
        self.assertEqual(config["web_search"], "native")

    def test_a_resume_with_the_flag_overrides_the_recorded_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp) / "runs"
            self._run_cli(runs_dir, "--goal", "resume overrides", "--web-search", "native")
            _, run_root = self._recorded(runs_dir)

            result = self._run_cli(runs_dir, "--resume-run", run_root.name, "--web-search", "auto")
            self.assertEqual(result.returncode, 1, msg=result.stderr)
            config, _ = self._recorded(runs_dir)
        self.assertEqual(config["web_search"], "auto")


class _FakeSdk:
    """A stand-in for `google.genai`, good enough to drive gemini_web_search.

    Nothing in the suite executed the SDK call path, so the mutation that turns a real
    API failure into an empty *successful* response passed the whole thing green -- the
    exact silent-lie mode this module exists to prevent. The real SDK is not a dependency
    and is absent in CI, so the harness is a fake rather than a skip.
    """

    class GoogleSearch:
        pass

    class Tool:
        def __init__(self, google_search=None):
            self.google_search = google_search

    class GenerateContentConfig:
        def __init__(self, tools=None):
            self.tools = tools or []

    class HttpRetryOptions:
        def __init__(self, attempts, initial_delay, max_delay):
            self.attempts, self.initial_delay, self.max_delay = attempts, initial_delay, max_delay

    class HttpOptions:
        def __init__(self, timeout, retry_options):
            self.timeout, self.retry_options = timeout, retry_options


class _RecordingClient:
    def __init__(self, response=None, error=None, calls=None):
        self._response, self._error, self.calls = response, error, calls if calls is not None else []
        self.models = self

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


@contextlib.contextmanager
def _fake_sdk_installed(client):
    genai = ModuleType("google.genai")
    genai.types = _FakeSdk
    google = ModuleType("google")
    google.genai = genai
    types_mod = ModuleType("google.genai.types")
    for name in dir(_FakeSdk):
        if not name.startswith("_"):
            setattr(types_mod, name, getattr(_FakeSdk, name))
    with patch.dict(sys.modules, {"google": google, "google.genai": genai, "google.genai.types": types_mod}), \
         patch("src.web_search.build_genai_client", return_value=client):
        yield


class SdkCallPathTest(unittest.TestCase):
    """The request AutoR sends, and what it does with what comes back."""

    BACKEND = None  # set per test

    def _search(self, *, response=None, error=None, **kwargs):
        client = _RecordingClient(response=response, error=error)
        backend = web_search_module.SearchBackend(kind="api_key", model="gemini-test", api_key="k")
        with _fake_sdk_installed(client), \
             patch("src.web_search.resolve_backend", return_value=backend):
            try:
                return gemini_web_search("a query", **kwargs), client
            except WebSearchError as exc:
                return exc, client

    def test_the_request_carries_the_query_and_the_backend_model(self) -> None:
        _, client = self._search(response=_Response([], text="answer"))
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["contents"], "a query")
        self.assertEqual(client.calls[0]["model"], "gemini-test")

    def test_the_request_enables_google_search_grounding(self) -> None:
        """Without this the model answers from memory and returns no sources at all --
        and every other assertion in the suite still passes."""
        _, client = self._search(response=_Response([], text="answer"))
        tools = client.calls[0]["config"].tools
        self.assertEqual(len(tools), 1)
        self.assertIsNotNone(tools[0].google_search)

    def test_the_answer_text_is_carried_through(self) -> None:
        result, _ = self._search(response=_Response([], text="  the answer  "))
        self.assertEqual(result.answer, "the answer")

    def test_a_response_with_no_text_yields_an_empty_answer(self) -> None:
        result, _ = self._search(response=_Response([]))
        self.assertEqual(result.answer, "")

    def test_the_backend_kind_is_recorded_on_the_response(self) -> None:
        result, _ = self._search(response=_Response([], text="x"))
        self.assertEqual(result.backend, "api_key")
        self.assertEqual(result.model, "gemini-test")

    def test_an_sdk_failure_becomes_a_websearcherror_naming_the_backend(self) -> None:
        """The mutation that turns this into an empty successful response is the one the
        whole suite used to miss."""
        result, _ = self._search(error=RuntimeError("429 quota exceeded"))
        self.assertIsInstance(result, WebSearchError)
        self.assertIn("429 quota exceeded", str(result))
        self.assertIn("Gemini API", str(result))

    def test_an_sdk_failure_is_never_reported_as_a_successful_empty_search(self) -> None:
        result, _ = self._search(error=RuntimeError("boom"))
        self.assertNotIsInstance(result, WebSearchResponse)

    def test_grounded_sources_reach_the_response(self) -> None:
        response = _Response([
            _Candidate(_Metadata(
                [_Chunk(_Web("https://arxiv.org/abs/1", "Paper"))],
                [_Support("A claim.", [0])],
            ))
        ], text="answer")
        result, _ = self._search(response=response, resolve_urls=False)
        self.assertEqual([r.url for r in result.results], ["https://arxiv.org/abs/1"])
        self.assertEqual(result.results[0].supported_claims, ["A claim."])

    def test_resolution_is_skipped_when_asked(self) -> None:
        stub = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AB"
        response = _Response([_Candidate(_Metadata([_Chunk(_Web(stub, "x"))]))], text="a")
        with patch("src.web_search.resolve_source", side_effect=AssertionError("must not resolve")):
            result, _ = self._search(response=response, resolve_urls=False)
        self.assertEqual(result.results[0].url, stub)
        self.assertFalse(result.grounded)

    def test_resolution_runs_and_dedupes_by_the_resolved_url(self) -> None:
        """Two distinct stubs reaching one page must collapse, which can only happen
        after resolution."""
        stubs = [f"https://vertexaisearch.cloud.google.com/grounding-api-redirect/{i}" for i in "AB"]
        response = _Response([
            _Candidate(_Metadata(
                [_Chunk(_Web(stubs[0], "arxiv.org")), _Chunk(_Web(stubs[1], "arxiv.org"))],
                [_Support("First.", [0]), _Support("Second.", [1])],
            ))
        ], text="a")
        with patch("src.web_search.resolve_source", return_value=("https://arxiv.org/abs/1", "Real Title")):
            result, _ = self._search(response=response, resolve_urls=True)
        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.results[0].url, "https://arxiv.org/abs/1")
        self.assertEqual(result.results[0].title, "Real Title")
        self.assertEqual(result.results[0].supported_claims, ["First.", "Second."])
        self.assertTrue(result.grounded)

    def test_the_max_results_cap_reaches_the_extractor(self) -> None:
        chunks = [_Chunk(_Web(f"https://example.org/{i}")) for i in range(6)]
        response = _Response([_Candidate(_Metadata(chunks))], text="a")
        result, _ = self._search(response=response, max_results=2, resolve_urls=False)
        self.assertEqual(len(result.results), 2)

    def test_an_empty_query_never_reaches_the_sdk(self) -> None:
        client = _RecordingClient(response=_Response([]))
        with _fake_sdk_installed(client):
            with self.assertRaises(WebSearchError):
                gemini_web_search("   ")
        self.assertEqual(client.calls, [])

    def test_an_explicit_api_key_bypasses_backend_resolution(self) -> None:
        client = _RecordingClient(response=_Response([], text="a"))
        with _fake_sdk_installed(client), \
             patch("src.web_search.resolve_backend", side_effect=AssertionError("must not resolve")):
            result = gemini_web_search("q", api_key="explicit", resolve_urls=False)
        self.assertEqual(result.backend, "api_key")


class CliForwardingTest(unittest.TestCase):
    """What the CLI hands to gemini_web_search, not merely that it called it.

    The previous fake swallowed every keyword argument into **kwargs and never inspected
    them, so --model, --max-results and --no-resolve-urls could all have been dropped in
    silence.
    """

    def _forwarded(self, argv):
        captured: dict[str, object] = {}

        def fake_search(query, **kwargs):
            captured["query"] = query
            captured.update(kwargs)
            return WebSearchResponse(query, "m", "a", "api_key", [SearchResult("t", "https://u")])

        with patch("src.web_search.gemini_web_search", side_effect=fake_search):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = web_search_main(argv)
        return captured, code

    def test_the_model_flag_is_forwarded(self) -> None:
        captured, _ = self._forwarded(["q", "--model", "gemini-9.9-pro"])
        self.assertEqual(captured["model"], "gemini-9.9-pro")

    def test_the_max_results_flag_is_forwarded(self) -> None:
        captured, _ = self._forwarded(["q", "--max-results", "3"])
        self.assertEqual(captured["max_results"], 3)

    def test_the_default_max_results_is_forwarded_too(self) -> None:
        captured, _ = self._forwarded(["q"])
        self.assertEqual(captured["max_results"], web_search_module.DEFAULT_MAX_RESULTS)

    def test_no_resolve_urls_inverts_correctly(self) -> None:
        """An inverted flag is the classic place for a silent polarity bug."""
        self.assertTrue(self._forwarded(["q"])[0]["resolve_urls"])
        self.assertFalse(self._forwarded(["q", "--no-resolve-urls"])[0]["resolve_urls"])

    def test_a_failure_prints_the_reason_not_just_a_nonzero_code(self) -> None:
        """The prompt promises 'it prints the reason on failure'. Asserting only the exit
        code leaves that promise unheld."""
        errors = io.StringIO()
        with patch("src.web_search.gemini_web_search", side_effect=WebSearchError("no backend configured")):
            with redirect_stdout(io.StringIO()), redirect_stderr(errors):
                code = web_search_main(["q"])
        self.assertEqual(code, 1)
        self.assertIn("no backend configured", errors.getvalue())
        self.assertIn("web_search error", errors.getvalue())


class ContinuationPromptCarriesTheSectionTest(unittest.TestCase):
    """Refinement attempts go through build_continuation_prompt, not build_prompt.

    Only build_prompt was covered, so the block could be dropped from every refinement
    turn -- every 1/2/3/4 the reviewer takes -- with the suite green.
    """

    def _continuation(self, **kwargs):
        from src.utils import build_continuation_prompt, build_run_paths, ensure_run_layout

        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "run")
            ensure_run_layout(paths)
            return build_continuation_prompt(
                STAGES[0], "template", paths, "handoff", "feedback", **kwargs
            )

    def test_the_section_reaches_a_refinement_turn(self) -> None:
        prompt = self._continuation(web_search_context=build_web_search_prompt_section())
        self.assertIn("# Web Search Capability", prompt)
        self.assertIn("tools/web_search.py", prompt)

    def test_no_section_means_no_heading(self) -> None:
        self.assertNotIn("# Web Search Capability", self._continuation(web_search_context=None))

    def test_both_prompt_builders_agree(self) -> None:
        """A block present on the first attempt and absent on every retry is worse than
        one that is absent throughout: the agent is told the tool exists, then not."""
        section = build_web_search_prompt_section()
        first = build_prompt(STAGES[0], "template", "user request", "memory", web_search_context=section)
        again = self._continuation(web_search_context=section)
        for prompt in (first, again):
            self.assertIn("# Web Search Capability", prompt)
