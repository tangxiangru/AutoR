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

DEFAULT_JUDGE_MODEL = "claude-opus-4-5@20251101"


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


def score(workspace: Path, bench: Path, *, model: str, project_id: str) -> dict:
    sys.path.insert(0, str(bench))
    import evaluation.config as config
    import evaluation.score as scorer

    # score_workspace refuses to build an agent unless these are present. They
    # are never used, because the agent is replaced below.
    for name in ("JUDGE_API_KEY", "JUDGE_API_BASE", "JUDGE_MODEL_NAME"):
        os.environ.setdefault(name, "unused-local-judge")
    config.JUDGE_MODEL_NAME = model

    judge = VertexJudge(model=model, project_id=project_id)
    scorer.LLMAgent = lambda **_: judge  # type: ignore[assignment]

    # Serialise. Concurrency is the trap that fires most often, and a benchmark
    # run that takes four hours can afford a scorer that takes three minutes.
    def serial(inputs, fn, max_workers=None, use_tqdm=False):  # noqa: ARG001
        return [fn(**item) for item in inputs]

    scorer.multi_thread = serial  # type: ignore[assignment]

    result = scorer.score_workspace(workspace)
    result["judge_model"] = model
    result["judge_calls"] = judge.calls
    result["judge_failures"] = judge.failures
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--bench", required=True, type=Path)
    parser.add_argument("--model", default=DEFAULT_JUDGE_MODEL)
    parser.add_argument(
        "--project-id", default=os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID", "")
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if not args.project_id:
        print("Set ANTHROPIC_VERTEX_PROJECT_ID or pass --project-id.", file=sys.stderr)
        return 2

    result = score(args.workspace, args.bench, model=args.model, project_id=args.project_id)
    if "error" in result:
        print(f"scoring failed: {result['error']}", file=sys.stderr)
        return 1

    items = result.get("results", [])
    failures = result.get("judge_failures", [])

    print(f"judge:     {result['judge_model']}")
    print(f"workspace: {args.workspace}")
    print()
    for item in items:
        print(
            f"  [{item.get('type','?'):>5}] w={item.get('weight',0):<5} "
            f"score={item.get('score',0):>3}  {str(item.get('content',''))[:70]}"
        )

    # The check that matters. A judge failure reads as a zero, so a total quoted
    # without this is not a measurement of the run.
    if failures:
        print()
        print(f"REFUSING TO QUOTE A TOTAL: {len(failures)} judge call(s) failed.")
        for reason in failures:
            print(f"  - {reason}")
        print("Every one of those is recorded as score 0 and is indistinguishable")
        print("from a criterion the report genuinely missed. Fix and re-run.")
        return 1

    print()
    print(f"TOTAL (judge {result['judge_model']}): {result.get('total_score', 0):.1f}")
    print(f"items judged: {len(items)}   judge calls: {result.get('judge_calls', 0)}")

    if args.out:
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
