"""An MCP server that hands the stage's agent writes which already carry their inverse.

:mod:`src.provenance` attributes what a stage wrote by *comparing* the workspace across a
stage boundary, because the agent writes files directly and AutoR cannot intercept it. That
works, and it is weaker than instrumentation in two ways the ledger has to record. A change
is attributed to whichever stage's boundary next observes it, so a write and its attribution
are separated by everything that happens in between; and a version whose bytes were never
held can be deleted on the way back but not rewound to.

This closes both, for the writes that come through it. A tool call is attributed to the
stage the manifest says is running, at the moment it happens, and the previous bytes go into
the content-addressed store before the new ones land -- so the inverse is exact rather than
reconstructed. It is the difference between a runtime that observes effects and one that
tracks them.

**A paragraph is not a tool.** The same argument :mod:`src.mcp_web_search` makes: an
instruction to "record sources through the helper" competes with everything else in a long
prompt, whereas a tool in the model's actual tool list gets reached for. It also puts each
write in the trace as a named call with structured arguments rather than as an opaque shell
invocation, which is what makes "what did Stage 01 actually record" answerable without
parsing shell strings.

**Nothing depends on the agent using it.** A stage that writes files directly is still
attributed at the next boundary and still withdrawable -- just to observation granularity.
That is what makes the server safe to run on every stage: it adds exactness where it is
used and takes nothing away where it is not, so a server that fails to start degrades to the
behaviour that was there before rather than breaking the run.

**The stage is read from the manifest, not passed in.** The config is written once per run
and the server outlives any one stage, so the current stage has to be resolved per call.
``run_manifest.json`` already carries ``current_stage_slug``, set where the stage starts
running, and reading it there means the attribution follows the authority rather than a copy
of it that can go stale.

The transport is newline-delimited JSON-RPC 2.0 on stdin/stdout, standard library only.

Run directly for a protocol smoke test::

    AUTOR_RUN_ROOT=runs/<id> echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
        | python3 -m src.mcp_write
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, TextIO

if __package__ in (None, ""):  # pragma: no cover - direct `python3 src/mcp_write.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.effects import (  # noqa: E402
    append_claim,
    append_source,
    record_result,
    register_hypothesis,
    set_artifact,
)
from src.utils import STAGES, RunPaths, StageSpec, build_run_paths  # noqa: E402

SERVER_NAME = "autor-write"
SERVER_VERSION = "1.0.0"

#: Names the run this server writes into. Set in the ``--mcp-config`` env block rather than
#: passed as an argument, so the same module entry point serves every run.
RUN_ROOT_ENV = "AUTOR_RUN_ROOT"

FALLBACK_PROTOCOL_VERSION = "2025-06-18"

METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603

_WHY = (
    " Writing through this tool rather than directly is what lets a later rollback take "
    "this exact change back; a direct write is still recovered, but only to the state the "
    "previous stage boundary observed."
)

TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "autor_record_result",
        "description": (
            "Write a machine-readable result artifact under workspace/results/." + _WHY
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File name under workspace/results, e.g. 'metrics.json'.",
                },
                "content": {"type": "string", "description": "The file's full contents."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "autor_set_artifact",
        "description": (
            "Write any workspace file -- data, code, notes, figures metadata." + _WHY
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path relative to workspace/, e.g. 'data/counts.csv'.",
                },
                "content": {"type": "string", "description": "The file's full contents."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "autor_append_source",
        "description": (
            "Add one literature source to workspace/literature/sources.json. Needs an 'id'; "
            "re-using an existing id replaces that entry." + _WHY
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "object",
                    "description": "The source record. Must carry a non-empty 'id'.",
                }
            },
            "required": ["source"],
        },
    },
    {
        "name": "autor_append_claim",
        "description": (
            "Add one literature claim to workspace/literature/claims.json. Needs an 'id'."
            + _WHY
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "claim": {
                    "type": "object",
                    "description": "The claim record. Must carry a non-empty 'id'.",
                }
            },
            "required": ["claim"],
        },
    },
    {
        "name": "autor_register_hypothesis",
        "description": (
            "Add one empirical hypothesis to workspace/notes/hypothesis_manifest.json. "
            "Needs an 'id'." + _WHY
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "hypothesis": {
                    "type": "object",
                    "description": "The hypothesis record. Must carry a non-empty 'id'.",
                }
            },
            "required": ["hypothesis"],
        },
    },
)

TOOLS_BY_NAME = {tool["name"]: tool for tool in TOOLS}


def _text_result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def resolve_run_root(environ: dict[str, str] | None = None) -> Path | None:
    value = (environ if environ is not None else dict(os.environ)).get(RUN_ROOT_ENV, "")
    return Path(value) if value.strip() else None


def current_stage(paths: RunPaths) -> StageSpec | None:
    """Which stage the manifest says is running, or ``None``.

    Read per call rather than captured at start-up. The config is written once per run and
    this process outlives any one stage, so a captured value would attribute Stage 05's
    writes to Stage 01 for the rest of the run.
    """

    from .manifest import load_run_manifest

    manifest = load_run_manifest(paths.run_manifest)
    if manifest is None or not manifest.current_stage_slug:
        return None
    return next((stage for stage in STAGES if stage.slug == manifest.current_stage_slug), None)


def call_tool(name: str, arguments: dict[str, Any], *, run_root: Path | None) -> dict[str, Any]:
    """Perform one write, or say why it could not happen.

    Every failure comes back as ``isError`` on a normal result rather than as a protocol
    error: the model can act on "that needs an id" and retry, whereas a protocol error ends
    the call with nothing it can use. A refusal here also has to leave the agent a way
    forward, and the way forward is the ordinary file write -- still attributed, still
    withdrawable, just less exactly.
    """

    if run_root is None:
        return _text_result(
            f"{RUN_ROOT_ENV} is not set, so this server does not know which run to write "
            "into. Write the file directly instead.",
            is_error=True,
        )

    paths = build_run_paths(run_root)
    stage = current_stage(paths)
    if stage is None:
        return _text_result(
            "The run manifest names no stage as running, so this write could not be "
            "attributed. Write the file directly instead.",
            is_error=True,
        )

    # Refused here rather than left to the writer. An empty path reaches `set_artifact`
    # as the workspace root and comes back as `IsADirectoryError`, which is true and
    # useless: the model can act on "that needs a path" and cannot act on an errno.
    if name in {"autor_record_result", "autor_set_artifact"} and not str(
        arguments.get("path") or ""
    ).strip():
        return _text_result(f"{name} requires a non-empty 'path'.", is_error=True)

    try:
        if name == "autor_record_result":
            record = record_result(
                paths, stage, str(arguments.get("path") or ""), str(arguments.get("content") or "")
            )
        elif name == "autor_set_artifact":
            record = set_artifact(
                paths, stage, str(arguments.get("path") or ""), str(arguments.get("content") or "")
            )
        elif name == "autor_append_source":
            record = append_source(paths, stage, dict(arguments.get("source") or {}))
        elif name == "autor_append_claim":
            record = append_claim(paths, stage, dict(arguments.get("claim") or {}))
        elif name == "autor_register_hypothesis":
            record = register_hypothesis(paths, stage, dict(arguments.get("hypothesis") or {}))
        else:  # pragma: no cover - guarded by the caller
            return _text_result(f"Unknown tool: {name}", is_error=True)
    except ValueError as error:
        return _text_result(str(error), is_error=True)
    except OSError as error:
        return _text_result(f"The write failed: {error}", is_error=True)
    except Exception as error:  # noqa: BLE001 - never take the agent's session down
        return _text_result(f"The write failed unexpectedly: {error}", is_error=True)

    return _text_result(
        f"Wrote {record.rel_path} ({record.action}) as {stage.slug}. "
        "Its inverse is accumulated, so a rollback past this stage takes it back exactly."
    )


def handle_message(
    message: dict[str, Any], *, run_root: Path | None = None
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
        result = {"tools": list(TOOLS)}
    elif method == "tools/call":
        params = message.get("params") or {}
        name = str(params.get("name") or "")
        if name not in TOOLS_BY_NAME:
            return _error(message_id, METHOD_NOT_FOUND, f"Unknown tool: {name}")
        result = call_tool(name, params.get("arguments") or {}, run_root=run_root)
    elif is_notification:
        return None
    elif method == "ping":
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
    run_root: Path | None = None,
) -> int:
    """Read newline-delimited JSON-RPC from stdin until EOF."""

    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    if run_root is None:
        run_root = resolve_run_root()

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        try:
            response = handle_message(message, run_root=run_root)
        except Exception as exc:  # noqa: BLE001 - a crash here kills the agent's whole stage
            response = _error(message.get("id"), INTERNAL_ERROR, str(exc))
        if response is None:
            continue
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()
    return 0


def build_mcp_server_entry(paths: RunPaths, *, repo_root: Path | None = None) -> dict[str, Any]:
    """This server's block for the agent's ``--mcp-config``.

    Launched with AutoR's own interpreter and PYTHONPATH, like the search server, so the
    child resolves ``src.effects`` the way the parent already verified rather than through
    whatever ``python3`` the agent's PATH finds.
    """

    root = (repo_root or Path(__file__).resolve().parent.parent).resolve()
    return {
        SERVER_NAME: {
            "command": sys.executable or "python3",
            "args": ["-m", "src.mcp_write"],
            "env": {"PYTHONPATH": str(root), RUN_ROOT_ENV: str(paths.run_root.resolve())},
            "cwd": str(root),
        }
    }


def main() -> int:  # pragma: no cover - process entry point
    return serve()


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
