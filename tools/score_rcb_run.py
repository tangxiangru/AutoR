"""Score a finished ResearchClawBench workspace, without the scorer's three traps.

An instrument, not a test. It drives ResearchClawBench's own ``score_workspace``
so every number it prints is that scorer's, not a reimplementation — but it
repairs three defaults that turn a judge failure into a score of zero, and it
refuses to print a total until it has checked that every item was actually
judged.

**Why this exists.** The stock scorer records a failed judge call as
``{"score": 0, "reasoning": "Failed to parse scoring response."}``, which is
indistinguishable in the output from a criterion the report genuinely missed.
Scoring one run here, two of three items were judge failures: the honest total
was 37.0 and the number on screen was 19.5. Nothing in the output said which.

**The three traps**, all at ``evaluation/score.py`` where ``LLMAgent`` is built:

1. ``max_tokens=500`` — a reasoning model spends the budget thinking and returns
   an empty body.
2. ``time_limit=120`` — too short for a multimodal call carrying six images.
3. ``multi_thread(max_workers=16)`` — concurrent multimodal calls were the actual
   cause of most failures. Serialising is slower and finishes.

**The judge is part of the result.** The reference judge is ``gpt-5.1``. On
identical artifacts, Gemini 2.5 Flash scored 37.0 where Claude Opus scored 20.8
— a 16-point spread that is a property of the judge, not the run. A benchmark
number quoted without its judge is not comparable to anything, so this prints
the judge on every line of output and refuses to write a result file without it.

Usage::

    python3 tools/score_rcb_run.py --workspace <ws> --bench /path/to/ResearchClawBench

Requires ``anthropic`` and the bench's ``structai``; set
``ANTHROPIC_VERTEX_PROJECT_ID``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


#: Room for a reasoning model to think and still answer. The stock 500 is what
#: makes a thinking judge return nothing.
JUDGE_MAX_TOKENS = 4096

#: A multimodal call carrying a target image plus five agent images does not
#: finish in the stock 120s.
JUDGE_TIME_LIMIT = 600

#: Serial. The stock 16 is the trap that actually fires.
JUDGE_WORKERS = 1

#: The judge ResearchClawBench itself scores with (`evaluation/.env.example`).
#: Use it unless you cannot: judge choice moves the number by about sixteen
#: points, so a run scored with anything else is not comparable to a published
#: figure.
REFERENCE_JUDGE_MODEL = "gpt-5.1"

#: The OpenAI-compatible endpoint the reference judge is served from here. An
#: endpoint is not a secret; the key that opens it is, and never appears in this
#: file — see `read_api_key`.
REFERENCE_JUDGE_ENDPOINT = "https://shi-lab-2-resource.services.ai.azure.com/openai/v1"

#: Fallback when no reference key is available.
FALLBACK_JUDGE_MODEL = "claude-opus-4-5@20251101"

#: Where the key is read from. Outside any repository on purpose: a default
#: inside the tree is one `git add -A` away from a leak.
DEFAULT_KEY_FILE = Path.home() / "api.txt"


def read_api_key(path: Path) -> str:
    """The key, from a file that is never committed.

    Tolerant about shape because the caller should never have to print the file
    to find out what shape it is: a bare token, `KEY=token`, and a quoted value
    all read the same. Nothing here echoes the value, and the only confirmation
    that parsing worked is that a call succeeds.
    """
    if not path.is_file():
        raise SystemExit(
            f"No judge key at {path}. Put the reference judge's key there, or pass "
            "--judge vertex to score with Claude instead. Do not pass a key on the "
            "command line: it lands in the shell history and in the process table."
        )
    raw = path.read_text(encoding="utf-8").strip()
    if "=" in raw and not raw.startswith("sk-"):
        raw = raw.split("=", 1)[1]
    return raw.strip().strip("\"'")


def _redact(text: str) -> str:
    """Strip anything key-shaped before it reaches an error message.

    Error text from an HTTP client can carry the request that produced it, and
    this output gets pasted into issues.
    """
    import re

    return re.sub(r"(sk-|Bearer\s+)[A-Za-z0-9_\-\.]{12,}", r"\1<redacted>", text)


def _response_text(response: Any) -> str:
    """Pull the text out of a Responses API result, whatever shape it arrived in."""
    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text.strip():
        return text
    parts: list[str] = []
    for item in getattr(response, "output", []) or []:
        for block in getattr(item, "content", []) or []:
            value = getattr(block, "text", None)
            if isinstance(value, str):
                parts.append(value)
    return "\n".join(parts)


class ReferenceJudge:
    """The gpt-5.1 judge, through the OpenAI-compatible Responses API.

    Same contract as :class:`VertexJudge`: ``score.py`` only ever calls the
    agent as ``agent(prompt, image_paths=, return_example=, max_try=)`` and
    expects a dict back.
    """

    def __init__(self, *, model: str, endpoint: str, api_key: str) -> None:
        from openai import OpenAI

        self.model = model
        self._client = OpenAI(base_url=endpoint, api_key=api_key)
        self.calls = 0
        self.failures: list[str] = []

    def __call__(
        self,
        prompt: str,
        image_paths: list[str] | None = None,
        return_example: dict | None = None,
        max_try: int = 2,
        **_: Any,
    ) -> dict | None:
        import base64
        import mimetypes

        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        for path in image_paths or []:
            data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
            media_type = mimetypes.guess_type(path)[0] or "image/png"
            content.append(
                {"type": "input_image", "image_url": f"data:{media_type};base64,{data}"}
            )

        last = ""
        for _attempt in range(max_try):
            self.calls += 1
            try:
                # Both budgets are passed here, not just declared above. They were
                # module constants that only `VertexJudge` read, so the default judge
                # ran with the client's own defaults: no wall limit on a multimodal
                # call carrying six images, and no output budget on a reasoning model
                # that can spend the whole of one thinking and return an empty body.
                # An empty body is scored 0, which reads as a bad artifact rather than
                # as a judge that never answered.
                response = self._client.responses.create(
                    model=self.model,
                    input=[{"role": "user", "content": content}],
                    max_output_tokens=JUDGE_MAX_TOKENS,
                    timeout=JUDGE_TIME_LIMIT,
                )
                text = _response_text(response)
                parsed = _first_json_object(text)
                if isinstance(parsed, dict) and "score" in parsed:
                    return parsed
                last = f"unparseable body ({len(text)} chars)"
            except Exception as exc:  # noqa: BLE001 - the reason is what matters
                last = _redact(f"{type(exc).__name__}: {exc}")
        self.failures.append(last)
        return None


DEFAULT_JUDGE_MODEL = FALLBACK_JUDGE_MODEL


class VertexJudge:
    """A drop-in for ``structai.LLMAgent`` backed by Claude on Vertex.

    ``score.py`` only ever calls the agent as
    ``agent(prompt, image_paths=..., return_example=..., max_try=...)`` and
    expects a dict back, so the whole surface is ``__call__``.
    """

    def __init__(self, *, model: str, project_id: str, region: str = "global") -> None:
        from anthropic import AnthropicVertex

        self.model = model
        self._client = AnthropicVertex(project_id=project_id, region=region)
        self.calls = 0
        self.failures: list[str] = []

    def __call__(
        self,
        prompt: str,
        image_paths: list[str] | None = None,
        return_example: dict | None = None,
        max_try: int = 2,
        **_: Any,
    ) -> dict | None:
        import base64
        import mimetypes

        content: list[dict[str, Any]] = []
        for path in image_paths or []:
            data = Path(path).read_bytes()
            media_type = mimetypes.guess_type(path)[0] or "image/png"
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.b64encode(data).decode("ascii"),
                    },
                }
            )
        content.append({"type": "text", "text": prompt})

        last = ""
        for attempt in range(max_try):
            self.calls += 1
            try:
                response = self._client.messages.create(
                    model=self.model,
                    max_tokens=JUDGE_MAX_TOKENS,
                    temperature=0,
                    messages=[{"role": "user", "content": content}],
                )
                text = "".join(
                    block.text for block in response.content if getattr(block, "type", "") == "text"
                ).strip()
                parsed = _first_json_object(text)
                if isinstance(parsed, dict) and "score" in parsed:
                    return parsed
                last = f"unparseable body ({len(text)} chars)"
            except Exception as exc:  # noqa: BLE001 - the reason is what matters
                last = f"{type(exc).__name__}: {exc}"
        self.failures.append(last)
        # Returning None is what score.py already treats as a failure. The
        # difference is that this object counted it, so the caller can tell a
        # judge failure from a real zero.
        return None


def _first_json_object(text: str) -> Any:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    for candidate in (text, text[start : end + 1]):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


class ScoringRefused(ValueError):
    """A total that is not a measurement, raised rather than returned.

    The judge-failure refusal used to live only in ``main``. Anything that did
    ``from score_rcb_run import score`` got back a dict whose ``total_score``
    already had the failed calls folded in as zeros, with no exception and no
    flag — a guarantee that held only at the printing layer. The result is
    carried on the exception so the caller can still show the per-item table.
    """

    def __init__(self, message: str, result: dict, reasons: list[str]) -> None:
        super().__init__(message)
        self.result = result
        self.reasons = reasons


def refusal_reasons(result: dict) -> list[str]:
    """Every way this total is a number rather than a measurement.

    Pure, and separate from :func:`score`, so the rule is testable without a benchmark
    checkout — the wiring gets an integration test, but the rule gets one everywhere.

    The judge-failure clause is the original one. The two item-count clauses are the
    same failure one step earlier: an empty or short checklist yields ``total_score:
    0``, ``judge_failures: []``, exit 0 and a written ``--out`` file — a fully formed
    zero indistinguishable from a report that missed every criterion, which is exactly
    the shape of the 19.5-against-37.0 incident this file exists for.
    """
    reasons: list[str] = []
    failures = result.get("judge_failures") or []
    items = result.get("items") or []
    expected = result.get("checklist_items_expected", 0)
    if failures:
        reasons.append(
            f"{len(failures)} judge call(s) failed: " + "; ".join(str(item) for item in failures)
        )
    if not items:
        reasons.append("zero items were scored, so the total is a zero over nothing")
    elif expected and len(items) != expected:
        reasons.append(
            f"{len(items)} items scored against a checklist of {expected}; the missing "
            "ones are absent from the total rather than visible in it"
        )
    return reasons


def _self_description(bench: Path, workspace: Path, result: dict, scorer) -> None:
    """Three keys that make the output stand on its own.

    ``images_shown`` because 60.6% of the benchmark's weight is image criteria and
    every one of them is shown the *same* first five of one list that sweeps
    ``outputs/`` before ``report/`` — and ``IMAGE_EXTENSIONS`` is a ``set``, so which
    five those are changes between interpreters. Nothing anywhere recorded them.
    ``checklist_items_expected`` because an item count is only a fact next to what it
    was supposed to be. ``bench_revision`` because item identity is a property of the
    benchmark checkout and the output records only ``task_id``.
    """
    try:
        images = scorer._find_generated_images(workspace)
        result["images_shown"] = [str(path) for path in images[:5]]
        # Beside the five, how many there were to choose from. Five of five and five of
        # twelve are the same line in the score file otherwise, and they are not the same
        # evidence: the two arms of a pair that produced different numbers of figures were
        # judged on different figures across 60.6% of the benchmark's weight.
        result["images_available"] = len(images)
    except Exception:  # noqa: BLE001 - a missing helper must not lose a scored run
        result["images_shown"] = []
        result["images_available"] = 0

    expected = 0
    task_id = str(result.get("task_id") or "")
    if task_id:
        checklist = bench / "tasks" / task_id / "target_study" / "checklist.json"
        try:
            expected = len(json.loads(checklist.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            expected = 0
    result["checklist_items_expected"] = expected

    import subprocess

    revision = subprocess.run(
        ["git", "-C", str(bench), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    result["bench_revision"] = revision.stdout.strip() if revision.returncode == 0 else ""


def score(workspace: Path, bench: Path, *, judge) -> dict:
    sys.path.insert(0, str(bench))

    # Set before the import, not after. `evaluation/config.py` reads these at import
    # time, and `evaluation/score.py` does `from .config import JUDGE_MODEL_NAME` --
    # a module-level copy. Setting them afterwards reaches neither, and every run
    # died on "Judge API configuration is missing" with the configuration right there.
    # They are never used: the agent is replaced below.
    for name in ("JUDGE_API_KEY", "JUDGE_API_BASE"):
        os.environ.setdefault(name, "unused-local-judge")
    os.environ.setdefault("JUDGE_MODEL_NAME", judge.model)

    import evaluation.config as config
    import evaluation.score as scorer

    # Rebind both. `config` is what a future reader will reach for; `scorer` holds the
    # copy the gate actually tests, and a rebind of one without the other is the bug
    # this comment exists to stop coming back.
    config.JUDGE_MODEL_NAME = judge.model
    scorer.JUDGE_MODEL_NAME = judge.model

    scorer.LLMAgent = lambda **_: judge  # type: ignore[assignment]

    # Serialise. Concurrency is the trap that fires most often, and a benchmark
    # run that takes four hours can afford a scorer that takes three minutes.
    def serial(inputs, fn, max_workers=None, use_tqdm=False):  # noqa: ARG001
        return [fn(**item) for item in inputs]

    scorer.multi_thread = serial  # type: ignore[assignment]

    result = scorer.score_workspace(workspace)
    result["judge_model"] = judge.model
    result["judge_calls"] = judge.calls
    result["judge_failures"] = judge.failures
    if "error" in result:
        return result

    _self_description(bench, workspace, result, scorer)

    reasons = refusal_reasons(result)
    if reasons:
        raise ScoringRefused("this total is not a measurement", result, reasons)
    return result


def write_result(out: Path, result: dict) -> None:
    """Create the directory, then replace rather than truncate.

    Both halves are paid for. The ``mkdir``: nothing else creates ``<state_dir>/scores/``
    — the paired-trial driver builds the path and hands it over as ``--out`` — so with a
    bare ``write_text`` the real judge path could not write a single result. Every test
    was green because the dry run's fake judge writes through a helper that does create
    the directory, and the failure needed a whole trial of real runs to surface: the
    scorer judged every item, printed the total, and died on ``FileNotFoundError``, which
    the driver reads as "scoring failed" and silently retries for four days.

    The ``os.replace``: a kill during a plain ``write_text`` leaves a truncated JSON file
    that ``final_pass`` will skip forever because it exists, and that the report cannot
    parse. Re-running is then not a repair.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(result, indent=2), encoding="utf-8")
    os.replace(tmp, out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--bench", required=True, type=Path)
    parser.add_argument(
        "--judge",
        choices=("reference", "vertex"),
        default="reference",
        help=(
            "reference = gpt-5.1, what the benchmark itself scores with. "
            "vertex = Claude on Vertex, for when no reference key is available. "
            "The choice is worth about sixteen points, so it is reported with the total."
        ),
    )
    parser.add_argument("--model", default=None, help="Override the judge model id.")
    parser.add_argument(
        "--key-file",
        type=Path,
        default=DEFAULT_KEY_FILE,
        help=(
            f"File holding the reference judge's key (default {DEFAULT_KEY_FILE}). "
            "Never pass the key itself: it would land in the shell history."
        ),
    )
    parser.add_argument("--endpoint", default=REFERENCE_JUDGE_ENDPOINT)
    parser.add_argument(
        "--project-id", default=os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID", "")
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if args.judge == "reference":
        judge = ReferenceJudge(
            model=args.model or REFERENCE_JUDGE_MODEL,
            endpoint=args.endpoint,
            api_key=read_api_key(args.key_file),
        )
    else:
        if not args.project_id:
            print("Set ANTHROPIC_VERTEX_PROJECT_ID or pass --project-id.", file=sys.stderr)
            return 2
        judge = VertexJudge(
            model=args.model or FALLBACK_JUDGE_MODEL, project_id=args.project_id
        )

    refused: ScoringRefused | None = None
    try:
        result = score(args.workspace, args.bench, judge=judge)
    except ScoringRefused as exc:
        refused, result = exc, exc.result
    if "error" in result:
        print(f"scoring failed: {result['error']}", file=sys.stderr)
        return 1

    # `score_workspace` returns this under "items". Reading "results" left the
    # per-item table empty and printed "items judged: 0" beside a real total --
    # a scorer reporting that it scored nothing, right after scoring everything.
    items = result.get("items", [])

    print(f"judge:     {result['judge_model']}")
    print(f"workspace: {args.workspace}")
    print()
    for item in items:
        print(
            f"  [{item.get('type','?'):>5}] w={item.get('weight',0):<5} "
            f"score={item.get('score',0):>3}  {str(item.get('content',''))[:70]}"
        )

    # The check that matters. A judge failure reads as a zero, so a total quoted
    # without this is not a measurement of the run. It is decided in `score` now, so
    # a programmatic caller cannot get the number without it; this only prints it.
    if refused is not None:
        print()
        print(f"REFUSING TO QUOTE A TOTAL: {len(refused.reasons)} reason(s).")
        for reason in refused.reasons:
            print(f"  - {reason}")
        print("Every one of those is recorded as score 0 and is indistinguishable")
        print("from a criterion the report genuinely missed. Fix and re-run.")
        return 1

    print()
    print(f"TOTAL (judge {result['judge_model']}): {result.get('total_score', 0):.1f}")
    print(f"items judged: {len(items)}   judge calls: {result.get('judge_calls', 0)}")

    if args.out:
        write_result(args.out, result)
        print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
