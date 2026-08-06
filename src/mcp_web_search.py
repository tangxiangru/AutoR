"""An MCP server exposing Gemini-backed web search to the coding agent.

Claude Code on Vertex AI ships with the built-in ``WebSearch`` tool disabled, which
guts Stage 01. :mod:`src.web_search` already replaces the capability, but only as a
shell script the prompt asks the agent to remember to run. That has two costs:

* **A paragraph is not a tool.** An instruction competes with everything else in a long
  prompt, and the model is markedly more reliable at reaching for something that appears
  in its actual tool list.
* **A Bash call is not auditable as a search.** Every search currently arrives in
  ``logs_raw.jsonl`` as an opaque shell invocation, indistinguishable from the hundreds
  of other commands a stage runs. AutoR's whole claim is that a run is inspectable; "which
  searches did Stage 01 actually perform, and what came back" should be answerable from
  the log without parsing shell strings.

Serving the same function over MCP puts search back where the disabled tool used to be:
in the tool list, and in the trace as a named tool call with structured arguments.

The transport is newline-delimited JSON-RPC 2.0 on stdin/stdout, per the MCP stdio
binding. It is written against the standard library only, like the rest of AutoR --
nothing here needs an SDK.

Run directly for a protocol smoke test::

    echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 -m src.mcp_web_search
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, TextIO

if __package__ in (None, ""):  # pragma: no cover - direct `python3 src/mcp_web_search.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.web_search import (  # noqa: E402
    DEFAULT_MAX_RESULTS,
    WebSearchError,
    format_response_markdown,
    gemini_web_search,
)

SERVER_NAME = "autor-search"
SERVER_VERSION = "1.0.0"

#: Echoed back when the client does not name one. The client's own version wins, because
#: MCP negotiates down and a server that insists on its favourite is a server that stops
#: working the next time the CLI updates.
FALLBACK_PROTOCOL_VERSION = "2025-06-18"

#: JSON-RPC reserved codes. Tool *failures* are not protocol errors: they come back as a
#: normal result with isError set, so the model can read the reason and retry.
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603

WEB_SEARCH_TOOL = {
    "name": "web_search",
    "description": (
        "Search the web and return a synthesised answer plus the source URLs it is "
        "grounded in. Use this instead of the built-in WebSearch tool, which is disabled "
        "in this deployment. Every citation you record must come from a URL this tool "
        "actually returned; never invent a reference, DOI, or arXiv identifier. The "
        "'supported_claims' under each source are this model's own wording, not text "
        "from the page -- to quote a source, fetch it and quote what it says."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "max_results": {
                "type": "integer",
                "description": f"Maximum grounded sources to report. Defaults to {DEFAULT_MAX_RESULTS}.",
                "minimum": 1,
            },
        },
        "required": ["query"],
    },
}


def _text_result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def call_web_search(
    arguments: dict[str, Any],
    *,
    search: Callable[..., Any] = gemini_web_search,
) -> dict[str, Any]:
    """Run one search and shape it as an MCP tool result.

    A failed or ungrounded search is reported as ``isError`` rather than raised: the model
    can act on "that returned nothing citable, try another query", whereas a protocol
    error just terminates the call with nothing it can use.
    """
    query = str(arguments.get("query") or "").strip()
    if not query:
        return _text_result("web_search requires a non-empty 'query'.", is_error=True)

    max_results = arguments.get("max_results")
    kwargs: dict[str, Any] = {}
    if isinstance(max_results, int) and not isinstance(max_results, bool) and max_results > 0:
        kwargs["max_results"] = max_results

    try:
        response = search(query, **kwargs)
    except WebSearchError as exc:
        return _text_result(f"Search failed: {exc}", is_error=True)
    except Exception as exc:  # noqa: BLE001 - never take the agent's session down
        return _text_result(f"Search failed unexpectedly: {exc}", is_error=True)

    body = format_response_markdown(response)
    if not response.grounded:
        return _text_result(
            body
            + "\nNo citable source came back. Treat the answer as unverified and retry "
            "with a different query rather than citing it.",
            is_error=True,
        )
    return _text_result(body)


def handle_message(
    message: dict[str, Any],
    *,
    search: Callable[..., Any] = gemini_web_search,
) -> dict[str, Any] | None:
    """Answer one JSON-RPC message, or None when it is a notification."""
    method = message.get("method")
    message_id = message.get("id")
    is_notification = "id" not in message

    if method == "initialize":
        params = message.get("params") or {}
        result: dict[str, Any] = {
            "protocolVersion": params.get("protocolVersion") or FALLBACK_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
    elif method == "tools/list":
        result = {"tools": [WEB_SEARCH_TOOL]}
    elif method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        if name != WEB_SEARCH_TOOL["name"]:
            return _error(message_id, METHOD_NOT_FOUND, f"Unknown tool: {name}")
        result = call_web_search(params.get("arguments") or {}, search=search)
    elif is_notification:
        # `notifications/initialized` and friends: acknowledged by saying nothing, which
        # is what the spec requires. Answering a notification is itself a protocol error.
        return None
    elif method in {"ping"}:
        result = {}
    else:
        return _error(message_id, METHOD_NOT_FOUND, f"Unknown method: {method}")

    if is_notification:
        return None
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _error(message_id: Any, code: int, text: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": text}}


def serve(
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    *,
    search: Callable[..., Any] = gemini_web_search,
) -> int:
    """Read newline-delimited JSON-RPC from stdin until EOF."""
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            # No id to answer against, and the spec's parse-error reply needs one. Drop it
            # rather than guessing; the client will time the request out.
            continue
        if not isinstance(message, dict):
            continue
        try:
            response = handle_message(message, search=search)
        except Exception as exc:  # noqa: BLE001 - a crash here kills the agent's whole stage
            response = _error(message.get("id"), INTERNAL_ERROR, str(exc))
        if response is None:
            continue
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()
    return 0


def main() -> int:  # pragma: no cover - process entry point
    return serve()


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
