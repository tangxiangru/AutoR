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
import html
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit


DEFAULT_SEARCH_MODEL = "gemini-2.5-flash"

#: Vertex AI serves a different model catalogue than the Gemini Developer API.
DEFAULT_VERTEX_SEARCH_MODEL = "gemini-3.6-flash"
DEFAULT_VERTEX_LOCATION = "global"

DEFAULT_MAX_RESULTS = 10

#: Seconds allowed for turning one grounding redirect into its canonical URL.
URL_RESOLVE_TIMEOUT = 10

#: How much of a resolved page to read looking for its <title>. Capped so a large or
#: hostile page cannot turn one citation lookup into an unbounded download.
TITLE_SCAN_BYTES = 65536

_HTML_TITLE_RE = re.compile(rb"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

#: Environment variables consulted for the Gemini API key, in priority order.
API_KEY_ENV_VARS = ("GOOGLE_API_KEY", "GEMINI_API_KEY")

#: Environment variables consulted for the search model, in priority order.
MODEL_ENV_VARS = ("AUTOR_WEB_SEARCH_MODEL", "GEMINI_MODEL")

#: Vertex project, in priority order. ANTHROPIC_VERTEX_PROJECT_ID is last and is a
#: convenience: a box already running Claude Code on Vertex has it set, and that is exactly
#: the deployment where the built-in WebSearch tool is disabled and this module is needed.
VERTEX_PROJECT_ENV_VARS = (
    "AUTOR_VERTEX_PROJECT",
    "GOOGLE_CLOUD_PROJECT",
    "ANTHROPIC_VERTEX_PROJECT_ID",
)

VERTEX_LOCATION_ENV_VARS = ("AUTOR_VERTEX_LOCATION", "GOOGLE_CLOUD_LOCATION")

#: Forces a backend instead of auto-detecting: "vertex", "api_key", or "auto".
BACKEND_ENV_VAR = "AUTOR_WEB_SEARCH_BACKEND"

#: Vertex returns grounding citations as redirect stubs under this host rather than the
#: source URL, so they have to be followed before they are usable as references.
GROUNDING_REDIRECT_HOST = "vertexaisearch.cloud.google.com"

REPO_ROOT = Path(__file__).resolve().parent.parent
DIAGRAM_CONFIG_PATH = REPO_ROOT / "configs" / "diagram_config.yaml"
WEB_SEARCH_SCRIPT = REPO_ROOT / "tools" / "web_search.py"


class WebSearchError(RuntimeError):
    """Raised when a web search cannot be performed at all."""


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    #: Sentences from Gemini's *own* answer that this source was cited in support of.
    #: Grounding asserts that the source supports the claim, never that the page contains
    #: the sentence, so these must never be presented as quotations from the page.
    supported_claims: list[str] = field(default_factory=list)

    @property
    def citable(self) -> bool:
        """False when the URL is still a grounding stub with no usable target."""
        return not is_unresolved_redirect(self.url)

    def to_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "url": self.url,
            "citable": self.citable,
            "supported_claims": list(self.supported_claims),
        }


@dataclass(frozen=True)
class WebSearchResponse:
    query: str
    model: str
    answer: str
    backend: str = "api_key"
    results: list[SearchResult] = field(default_factory=list)

    @property
    def citable_source_count(self) -> int:
        return sum(1 for result in self.results if result.citable)

    @property
    def grounded(self) -> bool:
        """Whether anything here can actually be cited.

        An answer with no citable source is the failure this whole module exists to
        prevent, so it is a first-class field rather than a line of prose only the
        markdown renderer emits.
        """
        return self.citable_source_count > 0

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "model": self.model,
            "backend": self.backend,
            "answer": self.answer,
            "grounded": self.grounded,
            "citable_source_count": self.citable_source_count,
            "results": [result.to_dict() for result in self.results],
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


def resolve_vertex_project() -> str | None:
    for env_var in VERTEX_PROJECT_ENV_VARS:
        value = os.environ.get(env_var, "").strip()
        if value:
            return value
    return None


def resolve_vertex_location() -> str:
    for env_var in VERTEX_LOCATION_ENV_VARS:
        value = os.environ.get(env_var, "").strip()
        if value:
            return value
    return DEFAULT_VERTEX_LOCATION


def vertex_credentials_available() -> bool:
    """Report whether Application Default Credentials can be loaded.

    Never materializes or logs the token — only whether one could be obtained.
    """
    try:
        import google.auth

        google.auth.default()
    except Exception:  # noqa: BLE001 - any auth failure means "not available"
        return False
    return True


def resolve_search_model(explicit: str | None = None, *, backend_kind: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    for env_var in MODEL_ENV_VARS:
        value = os.environ.get(env_var, "").strip()
        if value:
            return value
    return DEFAULT_VERTEX_SEARCH_MODEL if backend_kind == "vertex" else DEFAULT_SEARCH_MODEL


@dataclass(frozen=True)
class SearchBackend:
    """How to reach Gemini: a Developer API key, or Vertex AI with ADC."""

    kind: str  # "api_key" | "vertex"
    model: str
    api_key: str | None = None
    project: str | None = None
    location: str | None = None

    def describe(self) -> str:
        if self.kind == "vertex":
            return f"Vertex AI ({self.model}, project {self.project}, location {self.location})"
        return f"Gemini API ({self.model})"


def resolve_backend(model: str | None = None) -> SearchBackend | None:
    """Pick a Gemini backend from the environment, or None if none is usable.

    An explicit API key wins over Vertex: setting one is a deliberate act, whereas the
    Vertex project may just be inherited from the host's Claude Code configuration.
    ``AUTOR_WEB_SEARCH_BACKEND`` overrides the choice entirely.
    """
    requested = os.environ.get(BACKEND_ENV_VAR, "").strip().lower() or "auto"
    api_key = resolve_gemini_api_key()
    project = resolve_vertex_project()

    def _vertex() -> SearchBackend | None:
        if not project or not vertex_credentials_available():
            return None
        return SearchBackend(
            kind="vertex",
            model=resolve_search_model(model, backend_kind="vertex"),
            project=project,
            location=resolve_vertex_location(),
        )

    def _api_key() -> SearchBackend | None:
        if not api_key:
            return None
        return SearchBackend(
            kind="api_key",
            model=resolve_search_model(model, backend_kind="api_key"),
            api_key=api_key,
        )

    if requested == "vertex":
        return _vertex()
    if requested in {"api_key", "api-key", "apikey"}:
        return _api_key()
    return _api_key() or _vertex()


def build_genai_client(backend: SearchBackend):
    """Construct a google-genai client for the chosen backend."""
    try:
        from google import genai
    except ImportError as exc:  # pragma: no cover - exercised only without the SDK
        raise WebSearchError(
            "The google-genai package is required for Gemini web search. "
            "Install it with: pip install google-genai"
        ) from exc

    if backend.kind != "vertex":
        return genai.Client(api_key=backend.api_key)

    # `enterprise` is the current spelling; `vertexai` is the older one. Accept either so a
    # pinned older SDK still works.
    try:
        return genai.Client(enterprise=True, project=backend.project, location=backend.location)
    except TypeError:
        return genai.Client(vertexai=True, project=backend.project, location=backend.location)


def resolve_source(url: str, *, timeout: int = URL_RESOLVE_TIMEOUT) -> tuple[str, str | None]:
    """Follow a grounding redirect to its canonical URL and page title, best-effort.

    Vertex hands back opaque redirect stubs instead of source URLs. An agent told to cite
    only what the tool returned would otherwise be citing
    `vertexaisearch.cloud.google.com/...`, which is useless in a bibliography. On any
    failure the original URL is returned unchanged rather than dropping the source.

    The page title comes free-ish: following the redirect is already a GET, and grounding
    labels every source with a bare domain, so reading the first `TITLE_SCAN_BYTES` of the
    body is what turns "arxiv.org" into something a reader can identify.
    """
    if GROUNDING_REDIRECT_HOST not in url:
        return url, None
    try:
        import urllib.request

        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            resolved = response.url or url
            return resolved, _extract_html_title(response.read(TITLE_SCAN_BYTES))
    except Exception:  # noqa: BLE001 - a citation we cannot canonicalize is still a citation
        return url, None


def resolve_source_url(url: str, *, timeout: int = URL_RESOLVE_TIMEOUT) -> str:
    """Follow a grounding redirect to its canonical URL, discarding the page title."""
    return resolve_source(url, timeout=timeout)[0]


def _extract_html_title(head: bytes) -> str | None:
    match = _HTML_TITLE_RE.search(head)
    if match is None:
        return None
    title = " ".join(html.unescape(match.group(1).decode("utf-8", "replace")).split())
    return title[:200] or None


def _looks_like_bare_domain(title: str, url: str) -> bool:
    """Whether a grounding title carries no more information than the URL already does."""
    candidate = title.strip().lower()
    if not candidate or candidate == url.strip().lower():
        return True
    host = urlsplit(url).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return bool(host) and candidate in {host, f"www.{host}"}


def best_title(grounding_title: str, page_title: str | None, url: str) -> str:
    """Prefer the page's own title when grounding only supplied a bare domain."""
    if page_title and _looks_like_bare_domain(grounding_title, url):
        return page_title
    return grounding_title


def dedupe_by_url(results: "Iterable[SearchResult]") -> list[SearchResult]:
    """Collapse results sharing a URL, unioning the claims each copy was cited for.

    Two distinct grounding redirects routinely resolve to the same page, so deduplication
    has to happen after resolution as well as before it. Claims are unioned rather than
    chosen between: keeping only one would silently narrow what the source was cited for,
    and picking by length would pair one chunk's title with another chunk's claim.
    """
    by_url: dict[str, SearchResult] = {}
    for result in results:
        existing = by_url.get(result.url)
        if existing is None:
            by_url[result.url] = result
            continue
        merged = list(existing.supported_claims)
        merged.extend(claim for claim in result.supported_claims if claim not in merged)
        by_url[result.url] = SearchResult(existing.title, existing.url, merged)
    return list(by_url.values())


def gemini_web_search(
    query: str,
    *,
    model: str | None = None,
    api_key: str | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
    resolve_urls: bool = True,
) -> WebSearchResponse:
    """Run one grounded web search through Gemini, on Vertex AI or the Developer API."""
    query = query.strip()
    if not query:
        raise WebSearchError("Search query cannot be empty.")

    if api_key:
        backend = SearchBackend(
            kind="api_key",
            model=resolve_search_model(model, backend_kind="api_key"),
            api_key=api_key,
        )
    else:
        backend = resolve_backend(model)

    if backend is None:
        raise WebSearchError(
            "No Gemini backend is configured. Either set GOOGLE_API_KEY / GEMINI_API_KEY "
            "for the Gemini Developer API, or configure Vertex AI by setting a project "
            "(GOOGLE_CLOUD_PROJECT) with working Application Default Credentials "
            "(gcloud auth application-default login)."
        )

    from google.genai import types

    client = build_genai_client(backend)
    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
    )

    try:
        response = client.models.generate_content(
            model=backend.model,
            contents=query,
            config=config,
        )
    except Exception as exc:  # noqa: BLE001 - surface any SDK/transport failure uniformly
        raise WebSearchError(f"Gemini web search failed on {backend.describe()}: {exc}") from exc

    results = extract_search_results(response, max_results=max_results)
    if resolve_urls:
        results = dedupe_by_url(_resolved(result) for result in results)

    return WebSearchResponse(
        query=query,
        model=backend.model,
        backend=backend.kind,
        answer=(getattr(response, "text", "") or "").strip(),
        results=results,
    )


def _resolved(result: SearchResult) -> SearchResult:
    """Turn one grounding stub into a citable source, keeping its claims."""
    url, page_title = resolve_source(result.url)
    return SearchResult(
        title=best_title(result.title, page_title, url),
        url=url,
        supported_claims=result.supported_claims,
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

        claims = _claims_by_chunk_index(metadata)
        for index, chunk in enumerate(getattr(metadata, "grounding_chunks", None) or []):
            if len(results) >= max_results:
                return results
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
                    supported_claims=claims.get(index, []),
                )
            )

    return results


def _claims_by_chunk_index(metadata: object) -> dict[int, list[str]]:
    """Map each grounding chunk index to the answer sentences it was cited in support of.

    These are Gemini's own words, not text from the source page. Every distinct claim is
    kept rather than only the first: a source cited for three statements should not appear
    to stand behind whichever one happened to come back first.
    """
    claims: dict[int, list[str]] = {}
    for support in getattr(metadata, "grounding_supports", None) or []:
        segment = getattr(support, "segment", None)
        text = (getattr(segment, "text", "") or "").strip()
        if not text:
            continue
        for chunk_index in getattr(support, "grounding_chunk_indices", None) or []:
            bucket = claims.setdefault(chunk_index, [])
            if text not in bucket:
                bucket.append(text)
    return claims


def is_unresolved_redirect(url: str) -> bool:
    """True when a grounding stub could not be turned into a citable source URL."""
    return GROUNDING_REDIRECT_HOST in url


def format_response_markdown(response: WebSearchResponse) -> str:
    provider = "Vertex AI" if response.backend == "vertex" else "Gemini API"
    lines = [f"# Web Search: {response.query}", "", f"_Provider: {provider} ({response.model})_", ""]
    lines.extend(["## Answer", "", response.answer or "_The search returned no answer text._", ""])
    lines.append("## Sources")
    lines.append("")
    if not response.results:
        lines.append("_No grounded sources were returned. Treat the answer as unverified._")
        return "\n".join(lines).rstrip() + "\n"

    if not response.grounded:
        lines.append(
            "_No source resolved to a citable URL. Treat the answer as unverified._"
        )
        lines.append("")

    for index, result in enumerate(response.results, start=1):
        suffix = "" if result.citable else " — **unresolved redirect, not citable**"
        lines.append(f"{index}. [{result.title}]({result.url}){suffix}")
        if result.supported_claims:
            # Deliberately a bullet list and not a blockquote: these sentences are the
            # model's, and a blockquote under a hyperlink reads as a quotation from the
            # page, which is how a real source acquires a claim it never made.
            lines.append(
                "   Cited in support of these statements from the answer above "
                "(Gemini's wording, not text from the page):"
            )
            lines.extend(f"   - {claim}" for claim in result.supported_claims)
    return "\n".join(lines).rstrip() + "\n"


def resolve_web_search_context(mode: str) -> str | None:
    """Return the prompt block for the Gemini search tool, or None to keep native search.

    'auto' degrades to native search when no Gemini key is configured, so the default path
    never advertises a tool that would fail on first use.
    """
    if mode == "native":
        return None
    if mode == "auto" and resolve_backend() is None:
        return None
    return build_web_search_prompt_section()


def web_search_notice(mode: str) -> tuple[str, str]:
    """Describe the resolved search path as a ``(message, level)`` pair.

    `auto` silently falling back to native search is the dangerous case: on a deployment
    where the built-in `WebSearch` tool is disabled, the fallback is to a tool that does not
    work, and Stage 01 goes looking for literature with nothing to search with. Saying so at
    startup is the difference between a diagnosable run and one that quietly invents
    citations.
    """
    if mode == "native":
        return ("Web search: the backend's native tool.", "info")

    backend = resolve_backend()

    if mode == "gemini":
        if backend is None:
            return (
                "Web search: --web-search gemini was requested but no Gemini backend is "
                "configured. Operators will be told to use tools/web_search.py and it will "
                "fail on first use. Set GOOGLE_API_KEY / GEMINI_API_KEY, or configure Vertex "
                "AI (GOOGLE_CLOUD_PROJECT plus `gcloud auth application-default login`).",
                "error",
            )
        return (f"Web search: {backend.describe()}.", "info")

    if backend is not None:
        return (f"Web search: {backend.describe()}, selected automatically.", "info")

    return (
        "Web search: no Gemini backend found, falling back to the backend's native search. "
        "If this deployment has WebSearch disabled (for example Claude Code on Vertex AI), "
        "Stage 01 has no way to search at all. Set GOOGLE_API_KEY / GEMINI_API_KEY, or "
        "configure Vertex AI (GOOGLE_CLOUD_PROJECT plus `gcloud auth application-default "
        "login`), or pass --web-search native to silence this.",
        "warn",
    )


def build_web_search_prompt_section(
    *,
    script_path: Path | None = None,
    model: str | None = None,
) -> str:
    """Build the prompt block that redirects operators away from the native search tool."""
    resolved_script = (script_path or WEB_SEARCH_SCRIPT).resolve()
    backend = resolve_backend(model)
    provider = backend.describe() if backend else f"Gemini ({resolve_search_model(model)})"
    return (
        "The built-in `WebSearch` tool is **disabled** in this deployment. Calling it will "
        "fail or silently return nothing, so do not rely on it.\n\n"
        "Use this Gemini-backed replacement instead, through a shell command:\n\n"
        "```bash\n"
        f'python3 "{resolved_script}" "your search query here"\n'
        f'python3 "{resolved_script}" "your search query here" --json --max-results 8\n'
        "```\n\n"
        f"- It performs a real, grounded Google search through {provider} "
        "and prints a synthesised answer plus the source URLs it is grounded in.\n"
        "- Default output is markdown; `--json` gives "
        "`{query, model, backend, answer, grounded, citable_source_count, results[]}`, "
        "each result being `{title, url, citable, supported_claims[]}`.\n"
        "- Exit codes: `0` the search returned at least one citable source, `2` it "
        "completed but nothing citable came back, `1` it failed outright. On `1` or `2`, "
        "retry with a different query rather than fabricating citations. Check `grounded` "
        "in the JSON for the same signal.\n"
        "- **`supported_claims` is not text from the source page.** It is the model's own "
        "wording from the answer above, listing what each source was cited in support of. "
        "Grounding asserts that a source supports a claim, never that the page contains "
        "that sentence. Never transcribe it as a quotation, and never attribute its "
        "wording to the source's authors.\n"
        "- Fetching a **known** URL still works normally with `WebFetch` or `curl`. Only the "
        "search step needs this tool. To quote a source, fetch it and quote what it says.\n"
        "- Every citation you record must come from a URL this tool actually returned. Never "
        "invent a reference, DOI, or arXiv identifier.\n"
        "- A source marked **unresolved redirect**, or `\"citable\": false` in JSON, has no "
        "usable URL. Treat its content as a lead to verify, not as a citable reference."
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
    parser.add_argument(
        "--model",
        help=f"Gemini model to use. Defaults to {DEFAULT_SEARCH_MODEL} on the Gemini API "
             f"and {DEFAULT_VERTEX_SEARCH_MODEL} on Vertex AI.",
    )
    parser.add_argument(
        "--no-resolve-urls",
        action="store_true",
        help="Leave Vertex grounding redirects unresolved. Faster, but the source URLs are "
             "opaque redirect stubs that cannot be cited.",
    )
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
            resolve_urls=not args.no_resolve_urls,
        )
    except WebSearchError as exc:
        print(f"web_search error: {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(response.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(format_response_markdown(response), end="")

    if not response.grounded:
        # Distinct from 1 (the search failed) so the caller can tell "nothing citable came
        # back, try another query" from "the tool is broken". Exiting 0 here would let an
        # ungrounded answer look like a successful search to anything reading only $?.
        print(
            "web_search: the search returned no citable source; treat the answer as "
            "unverified and retry with a different query.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
