"""Gemini-backed web search for AutoR operators.

Some Claude Code deployments (notably Vertex AI) ship with the built-in ``WebSearch``
tool disabled, which silently guts Stage 01 literature survey. This module provides a
replacement that any operator backend can reach through a plain shell call, so the
capability does not depend on which vendor tool happens to be enabled.

The search itself is delegated to the Gemini API's Google Search grounding tool, which
returns both a synthesised answer and the grounded source URLs.

Command line usage::

    python3 tools/web_search.py "superradiance black hole constraints" --max-results 8
    python3 tools/web_search.py "diffusion model scaling laws" --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


DEFAULT_SEARCH_MODEL = "gemini-2.5-flash"
DEFAULT_MAX_RESULTS = 10

#: Environment variables consulted for the Gemini API key, in priority order.
API_KEY_ENV_VARS = ("GOOGLE_API_KEY", "GEMINI_API_KEY")

#: Environment variables consulted for the search model, in priority order.
MODEL_ENV_VARS = ("AUTOR_WEB_SEARCH_MODEL", "GEMINI_MODEL")

REPO_ROOT = Path(__file__).resolve().parent.parent
DIAGRAM_CONFIG_PATH = REPO_ROOT / "configs" / "diagram_config.yaml"
WEB_SEARCH_SCRIPT = REPO_ROOT / "tools" / "web_search.py"


class WebSearchError(RuntimeError):
    """Raised when a web search cannot be performed at all."""


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""


@dataclass(frozen=True)
class WebSearchResponse:
    query: str
    model: str
    answer: str
    results: list[SearchResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "model": self.model,
            "answer": self.answer,
            "results": [asdict(result) for result in self.results],
        }


def resolve_gemini_api_key() -> str | None:
    """Resolve a Gemini API key from env vars or the local config file.

    Never falls back to a hardcoded key. This is the single resolver for the repository;
    :mod:`src.diagram_gen` delegates to it so the two features cannot drift apart.
    """
    for env_var in API_KEY_ENV_VARS:
        value = os.environ.get(env_var, "").strip()
        if value:
            return value

    if DIAGRAM_CONFIG_PATH.exists():
        import yaml

        with open(DIAGRAM_CONFIG_PATH, "r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}
        api_keys = config.get("api_keys", {}) or {}
        for key_name in ("google_api_key", "gemini_api_key"):
            value = (api_keys.get(key_name) or "").strip()
            if value:
                return value
    return None


def resolve_search_model(explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    for env_var in MODEL_ENV_VARS:
        value = os.environ.get(env_var, "").strip()
        if value:
            return value
    return DEFAULT_SEARCH_MODEL


def gemini_web_search(
    query: str,
    *,
    model: str | None = None,
    api_key: str | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> WebSearchResponse:
    """Run one grounded web search through the Gemini API."""
    query = query.strip()
    if not query:
        raise WebSearchError("Search query cannot be empty.")

    resolved_key = api_key or resolve_gemini_api_key()
    if not resolved_key:
        raise WebSearchError(
            "Gemini API key not found. Set GOOGLE_API_KEY or GEMINI_API_KEY in the "
            "environment, or add api_keys.google_api_key to configs/diagram_config.yaml."
        )

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:  # pragma: no cover - exercised only without the SDK
        raise WebSearchError(
            "The google-genai package is required for Gemini web search. "
            "Install it with: pip install google-genai"
        ) from exc

    resolved_model = resolve_search_model(model)
    client = genai.Client(api_key=resolved_key)
    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
    )

    try:
        response = client.models.generate_content(
            model=resolved_model,
            contents=query,
            config=config,
        )
    except Exception as exc:  # noqa: BLE001 - surface any SDK/transport failure uniformly
        raise WebSearchError(f"Gemini web search failed: {exc}") from exc

    return WebSearchResponse(
        query=query,
        model=resolved_model,
        answer=(getattr(response, "text", "") or "").strip(),
        results=extract_search_results(response, max_results=max_results),
    )


def extract_search_results(response: object, *, max_results: int = DEFAULT_MAX_RESULTS) -> list[SearchResult]:
    """Pull grounded sources out of a Gemini response.

    The SDK's grounding metadata is optional at every level, so each hop is guarded
    rather than assumed: a response with an answer but no citations is still useful.
    """
    candidates = getattr(response, "candidates", None) or []
    results: list[SearchResult] = []
    seen_urls: set[str] = set()

    for candidate in candidates:
        metadata = getattr(candidate, "grounding_metadata", None)
        if metadata is None:
            continue

        snippets = _snippets_by_chunk_index(metadata)
        for index, chunk in enumerate(getattr(metadata, "grounding_chunks", None) or []):
            web = getattr(chunk, "web", None)
            if web is None:
                continue
            url = (getattr(web, "uri", "") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            results.append(
                SearchResult(
                    title=(getattr(web, "title", "") or url).strip(),
                    url=url,
                    snippet=snippets.get(index, ""),
                )
            )
            if len(results) >= max_results:
                return results

    return results


def _snippets_by_chunk_index(metadata: object) -> dict[int, str]:
    """Map each grounding chunk index to the answer text it supports."""
    snippets: dict[int, str] = {}
    for support in getattr(metadata, "grounding_supports", None) or []:
        segment = getattr(support, "segment", None)
        text = (getattr(segment, "text", "") or "").strip()
        if not text:
            continue
        for chunk_index in getattr(support, "grounding_chunk_indices", None) or []:
            snippets.setdefault(chunk_index, text)
    return snippets


def format_response_markdown(response: WebSearchResponse) -> str:
    lines = [f"# Web Search: {response.query}", "", f"_Provider: Gemini ({response.model})_", ""]
    lines.extend(["## Answer", "", response.answer or "_The search returned no answer text._", ""])
    lines.append("## Sources")
    lines.append("")
    if not response.results:
        lines.append("_No grounded sources were returned. Treat the answer as unverified._")
    else:
        for index, result in enumerate(response.results, start=1):
            lines.append(f"{index}. [{result.title}]({result.url})")
            if result.snippet:
                lines.append(f"   > {result.snippet}")
    return "\n".join(lines).rstrip() + "\n"


def build_web_search_prompt_section(
    *,
    script_path: Path | None = None,
    model: str | None = None,
) -> str:
    """Build the prompt block that redirects operators away from the native search tool."""
    resolved_script = (script_path or WEB_SEARCH_SCRIPT).resolve()
    resolved_model = resolve_search_model(model)
    return (
        "The built-in `WebSearch` tool is **disabled** in this deployment. Calling it will "
        "fail or silently return nothing, so do not rely on it.\n\n"
        "Use this Gemini-backed replacement instead, through a shell command:\n\n"
        "```bash\n"
        f'python3 "{resolved_script}" "your search query here"\n'
        f'python3 "{resolved_script}" "your search query here" --json --max-results 8\n'
        "```\n\n"
        f"- It performs a real, grounded Google search through the Gemini API (`{resolved_model}`) "
        "and prints a synthesised answer plus the source URLs it is grounded in.\n"
        "- Default output is markdown; `--json` gives `{query, model, answer, results[]}` for parsing.\n"
        "- It exits non-zero and prints the reason on failure. If a search fails, retry with a "
        "different query rather than fabricating citations.\n"
        "- Fetching a **known** URL still works normally with `WebFetch` or `curl`. Only the "
        "search step needs this tool.\n"
        "- Every citation you record must come from a URL this tool actually returned. Never "
        "invent a reference, DOI, or arXiv identifier."
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="web_search",
        description="Grounded web search backed by the Gemini API.",
    )
    parser.add_argument("query", nargs="+", help="The search query.")
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit machine-readable JSON instead of markdown.",
    )
    parser.add_argument("--model", help=f"Gemini model to use. Defaults to {DEFAULT_SEARCH_MODEL}.")
    parser.add_argument(
        "--max-results",
        type=int,
        default=DEFAULT_MAX_RESULTS,
        help=f"Maximum number of grounded sources to report. Defaults to {DEFAULT_MAX_RESULTS}.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    query = " ".join(args.query).strip()

    try:
        response = gemini_web_search(
            query,
            model=args.model,
            max_results=args.max_results,
        )
    except WebSearchError as exc:
        print(f"web_search error: {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(response.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(format_response_markdown(response), end="")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
