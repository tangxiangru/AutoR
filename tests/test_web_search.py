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
