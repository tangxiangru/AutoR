"""The seam a benchmark front end makes one operator call through, and what it reads back.

Five things that were written for one benchmark, are used by two, and belong to neither.
They lived in ``src.frontierscience`` until that adapter was removed; FIRE-Bench imported
them from there, so the move is what keeps FIRE-Bench working rather than a tidy-up.

:class:`_OperatorCall` is the load-bearing one. ``OperatorProtocol.run_stage`` renders
AutoR's stage contract and a stage summary is not an answer, so a front end that wants one
plain call goes through ``_prepare_invocation`` / ``_run_streaming_command`` instead -- the
same private pair :class:`src.rcb.ReportSynthesizer` uses. A third copy of that invocation
is a third place for the MCP config and the denied-tool list to drift apart, which is why
this is imported rather than reimplemented.

The constants are defaults for the fake path and for the stage this call is attributed to.
A front end with its own stage overrides them; FIRE-Bench does.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .utils import (
    RunPaths,
    StageSpec,
    build_run_paths,
    read_text,
    write_text,
)

#: Synthetic stage used only to label this adapter's own operator calls in the run
#: log. Numbered 9 like the ResearchClawBench report synthesizer's, and for the
#: same reason: it is not one of the eight, and a real stage number would put it
#: in the manifest.
ANSWER_STAGE = StageSpec(9, "09_bench_answer", "Benchmark Answer")


#: First line of an answer produced by ``--fake-operator``. A smoke run writes a
#: file long enough to clear every length check, which is exactly what makes it
#: dangerous: nothing else in the artifact says the model was never called.
#: ``_meta.json`` carries ``fake_operator`` as well, for the same
#: two-witness reason as :data:`FS_FALLBACK_MARKER`.
FAKE_ANSWER_MARKER = "<!-- autor:fake-operator -->"




#: The fields :func:`read_transcript_witness` publishes, and what ``None`` means in each.
#:
#: Every key is always present in ``_meta.json``. ``None`` is "not observed", never zero
#: and never false: a run with no transcript -- ``--fake-operator``, or a crash before the
#: first call -- must not be able to satisfy a ``browsing_tool_calls == 0`` admission
#: clause by having no evidence. A clause reading a null refuses the pair, which is the
#: safe direction; a clause reading a zero admits it.
TRANSCRIPT_FIELDS = (
    "stop_reason",
    "truncated",
    "browsing_tool_calls",
    "browsing_tool_names",
    "backend_calls",
    "output_tokens_total",
)


def has_refusal(reasons: Iterable[str], prefix: str) -> bool:
    """Whether any recorded reason belongs to *prefix*'s clause.

    Reasons are namespaced strings, ``driver:answer_is_a_plan:Objective``, so that
    the ledger can print what was actually wrong without the clause name having to
    be re-derived from prose. Everything that decides on a clause goes through
    here, so the namespace is one rule rather than a startswith written in six
    places, five of which would eventually be an equality test that misses the
    detail suffix.
    """
    return any(reason == prefix or reason.startswith(prefix + ":") for reason in reasons)


def stage_answer_bodies(paths: RunPaths) -> list[str]:
    """Approved stage summaries with AutoR's control-loop scaffolding removed.

    The stripper is :func:`src.rcb._research_body`, imported rather than rewritten.
    Two copies of "what part of a stage summary reads as research" would be two
    encodings of one rule, and the copy nobody edits is the one that keeps
    ``## Your Options / 1. Use suggestion 1 ... 6. Abort`` in a scored artifact.
    """
    return [
        body
        for body in (_research_body(read_text(path)) for path in stage_summary_files(paths))
        if body.strip()
    ]


def stages_approved_in(paths: RunPaths) -> list[str]:
    """Stage slugs a reviewer actually approved, from the run manifest.

    The manifest rather than ``memory.md``, and the distinction is load-bearing:
    :func:`src.utils.append_approved_stage_summary` is called for a *skipped*
    stage too, so approved memory contains an entry for a stage nobody reviewed.
    :attr:`src.manifest.StageManifestEntry.approved` is the narrower claim, and
    ``settled`` -- the one the resume cursor uses -- is the wider one that a
    skipped stage also satisfies. This function wants the narrow one.
    """
    manifest = load_run_manifest(paths.run_manifest)
    if manifest is None:
        return []
    return [entry.slug for entry in manifest.stages if entry.approved and not entry.skipped]


def read_transcript_witness(paths: RunPaths | None) -> dict[str, Any]:
    """What the raw stream-json log says the backend actually did.

    Six fields, all of them ``None`` when there is no transcript to read. The run tree is
    created for this: ``_fresh_run_tree`` in the front end exists so that even the direct
    arm's single call streams into ``logs_raw.jsonl``, because on a benchmark whose
    published protocol is "without browsing" the transcript is the only witness for
    whether the agent reached for a browsing tool. Denying the tools says what the agent
    was *allowed* to do; this says what it did.

    One file covers every seat. The reviewer and each ideation proposer stream through the
    same :class:`src.utils.RunPaths`, so a count taken here is a count over all seven
    models the pipeline arm seats, not over the executor alone.

    The shapes below were read off a real corpus rather than a schema: a 7,141-line
    transcript from the sibling benchmark carries 73 ``type: "result"`` lines, each with
    ``stop_reason``, ``usage.output_tokens`` and ``usage.server_tool_use`` counters, and
    4,235 ``type: "assistant"`` lines whose ``message.content`` holds the ``tool_use``
    blocks. ``stop_reason`` is *absent* from almost every assistant line, which is why it
    is taken from the result lines.

    ``truncated`` is true when **any** call in the run stopped at its token ceiling, not
    only the last one: a stage that was cut off and then retried leaves a complete final
    answer standing on an incomplete one.
    """
    absent: dict[str, Any] = {field: None for field in TRANSCRIPT_FIELDS}
    if paths is None or not paths.logs_raw.exists():
        return absent

    backend_calls = 0
    output_tokens = 0
    browsing_calls = 0
    browsing_names: set[str] = set()
    stop_reason: str | None = None
    truncated = False
    with paths.logs_raw.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                # A non-JSON line is logged by the operator itself, wrapped in `_meta`.
                # Skipping it is not a silent drop: the count it would contribute to is
                # `backend_calls`, and a line that is not JSON is not a completed call.
                continue
            if not isinstance(payload, dict):
                continue
            message = payload.get("message")
            if isinstance(message, dict):
                for block in message.get("content") or []:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    name = str(block.get("name") or "")
                    if _is_browsing_tool(name):
                        browsing_calls += 1
                        browsing_names.add(name)
            if payload.get("type") != "result":
                continue
            backend_calls += 1
            reason = payload.get("stop_reason")
            if isinstance(reason, str) and reason:
                stop_reason = reason
                if reason == "max_tokens":
                    truncated = True
            usage = payload.get("usage")
            if isinstance(usage, dict):
                output_tokens += _whole_number_under(usage, "output_tokens")
                server = usage.get("server_tool_use")
                if isinstance(server, dict):
                    # Server-side search never appears as a `tool_use` block, so a count
                    # taken only from the blocks would read zero on a run that searched.
                    for key, count in server.items():
                        if isinstance(count, int) and count and _is_browsing_tool(str(key)):
                            browsing_calls += count
                            browsing_names.add(str(key))
    if backend_calls == 0 and browsing_calls == 0 and not browsing_names:
        # A transcript that holds no completed call is not a witness to anything. Reading
        # it as "zero browsing calls" would let a run that never started satisfy the
        # protocol clause by producing no evidence.
        return absent
    return {
        "stop_reason": stop_reason,
        "truncated": truncated,
        "browsing_tool_calls": browsing_calls,
        "browsing_tool_names": sorted(browsing_names),
        "backend_calls": backend_calls,
        "output_tokens_total": output_tokens,
    }


class _OperatorCall:
    """The one seam both answer producers use to make a single operator call.

    ``OperatorProtocol.run_stage`` is not usable here: it renders AutoR's stage
    contract, and a stage summary is precisely the shape :func:`answer_content_refusals`
    refuses. So both producers go through ``_prepare_invocation`` /
    ``_run_streaming_command``, the same private pair
    :class:`src.rcb.ReportSynthesizer` uses, which keeps the invocation, the MCP
    config, the denied tools and the raw log identical to a stage's without
    widening the protocol.

    **A fake operator does not fake this call.** ``_prepare_invocation`` builds the
    real CLI command whatever ``fake_mode`` says -- only ``run_stage`` branches --
    so a producer that reached this seam under ``--fake-operator`` would spawn the
    real backend. Two guards keep that from happening, and they are not
    interchangeable: each producer's ``__call__`` returns :meth:`fake_answer` from
    an explicit ``fake`` branch placed *before* anything else, and
    :meth:`supported` answers ``False`` under a fake operator as a backstop for a
    third producer written later. Because the explicit branch comes first, the
    backstop is never reached today and a ``--fake-operator`` smoke run publishes
    ``answer_source: "synthesized"`` on the pipeline arm -- not ``"stage"``, which
    is what an earlier draft of this class produced and what this paragraph used
    to claim.
    """

    def __init__(self, operator: Any) -> None:
        self.operator = operator

    @property
    def fake(self) -> bool:
        return bool(getattr(self.operator, "fake_mode", False))

    def supported(self) -> bool:
        if self.fake:
            return False
        return all(
            hasattr(self.operator, name)
            for name in ("_prepare_invocation", "_run_streaming_command")
        )

    @staticmethod
    def fake_answer(*, title: str, question: str, note: str) -> str:
        """A scripted reply for ``--fake-operator``, marked as one in its first line.

        Long enough that a caller's own length floor cannot refuse it, because a smoke run has to
        exercise the same export, metadata and exit-code path a real run takes. Marked in
        the file *and* in ``_meta.json`` because an artifact that clears every length and
        format check while no model was ever called is the exact shape of a fake result
        being counted as an attempt.

        It deliberately does not echo any of the run's own artifacts. A fake answer
        assembled out of stage summaries would carry their headings, be refused by
        :func:`answer_content_refusals`, and turn the smoke test into an assertion about
        the fake rather than about the adapter.
        """
        return "\n".join(
            [
                FAKE_ANSWER_MARKER,
                "",
                f"# {title}",
                "",
                note,
                "",
                "## The question this run was given",
                "",
                truncate_text(question, max_chars=2000),
            ]
        )

    def invoke(self, *, paths: RunPaths, prompt: str, label: str, attempt: int) -> tuple[int, str]:
        """Run one operator call and return its exit code and captured reply."""
        import uuid

        prompt_path = paths.prompt_cache_dir / f"{ANSWER_STAGE.slug}_{label}.prompt.md"
        write_text(prompt_path, prompt)
        command, cwd, stdin_text = self.operator._prepare_invocation(  # noqa: SLF001
            prompt_path,
            str(uuid.uuid4()),
            paths=paths,
            resume=False,
        )
        exit_code, stdout, _stderr, _session, meta = self.operator._run_streaming_command(  # noqa: SLF001
            command=command,
            cwd=cwd,
            stage=ANSWER_STAGE,
            attempt_no=attempt,
            paths=paths,
            mode=label,
            stdin_text=stdin_text,
        )
        # The assistant's own words when the reader offers them, the whole stream otherwise.
        #
        # This class is the one seam in the tree that keeps a *reply* rather than parsing a
        # section out of it, and the whole stream is not the reply: a `tool_result` block is
        # text under `content`, so a directory listing the model ran for itself arrives in
        # `stdout` ahead of the answer. Six of twenty-eight `direct` answers in the sixty-task
        # trial began that way, the answer intact underneath, and a content-refusal clause
        # reading the top of the file refused all six.
        #
        # Falling back rather than requiring the field keeps a backend that does not label
        # its events working: `CodexOperator` goes through the same seam, and an operator
        # that reports no assistant blocks should produce a whole-stream answer rather than
        # an empty one.
        assistant = str((meta or {}).get("assistant_text") or "").strip()
        return exit_code, assistant or (stdout or "")


