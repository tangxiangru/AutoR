"""Score one FrontierScience answer with the paper's judge prompt, over plain stdlib HTTP.

The effects half of the FrontierScience scorer. Everything that decides anything lives in
:mod:`src.fs_scoring` and :mod:`src.frontierscience`; what is left here is a socket, a
clock, a key file and a printer.

**No third-party client, and that is a property rather than an accident.**
``tools/score_rcb_run.py`` needs the ``openai`` package because ResearchClawBench's own
scorer is built around it, so that tool cannot run on a machine with a bare interpreter —
and ``tests/test_score_rcb_run.py`` loads it through ``spec_from_file_location`` for
precisely that reason, keeping the import inside the constructor so the test module does
not go red on CI, which installs nothing. This tool asks for one endpoint, one JSON body
and one JSON response, all of which ``urllib.request`` already does. So the end-to-end
test here can stand up a real ``http.server`` and drive the real request path, on bare
CI, with no key and no network — which is the difference between testing the plumbing and
testing a mock of it.

**What was measured against the live endpoint**, and where each number went:

* ``gpt-5`` and ``gpt-5.2`` return 404 on this deployment; ``gpt-5.1`` answers. The
  paper's judge is therefore unavailable and **no total this tool prints is comparable to
  the paper's table** — the banner is printed on every run, not left to the reader.
* 34 of 34 serial calls succeeded with zero retries. Concurrent judge calls were the
  measured cause of most failures on ResearchClawBench and there is no local evidence
  against that lesson, so this tool has no concurrency and no flag to add any.
* Mean judge call 72.9 s over the probe's 29 judge calls -- 81.7 s across all 34 calls it
  made, answer generation included -- and longest 322.3 s. Hence a 600 s wall limit.
* Largest total judge output observed 20,004 tokens, 15,202 of them reasoning — 4,802
  visible — and at 4,096 and 2,048 the judge returned *nothing*, the whole budget having
  gone on reasoning. The budget has to cover the thinking, not the answer. Hence 32,000.
* A truncated response is HTTP 200 with ``status == "incomplete"``. It is refused, never
  recorded as a score. A deliberately bad answer scores exactly 0.000 here, so a real
  zero exists and must stay distinguishable from a failure.

**The key never appears on a command line.** ``--api-key`` does not exist and must not be
added: an argument lands in the shell history and in the process table, where anything on
the box can read it. The key is read from a file outside any repository, and every
exception is passed through :func:`redact` before it is printed, because an HTTP client's
error text can carry the request that produced it and this output gets pasted into issues.

**Nothing this tool writes belongs in the repository.** ``--raw-dir`` saves the judge's
full response, and the judge quotes rubric items back verbatim while it reasons; the
dataset card asks that this text stay out of crawlable corpora. Point it somewhere outside
the tree.

Usage::

    python3 tools/score_fs_run.py --task fs:043 --answer answer.md --out score.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.frontierscience import (  # noqa: E402
    DatasetRefused,
    FS_DATASET_ROWS,
    FS_DATASET_SHA256,
    FS_TASK_SELECTION_HELP,
    load_dataset,
    resolve_dataset_path,
    resolve_task_keys,
    rows_by_key,
)
from src.fs_scoring import (  # noqa: E402
    FS_JUDGE_NOISE_NOTE,
    ScoringRefused,
    build_result,
    draw_record,
    render_judge_prompt,
)
from src.utils import code_version  # noqa: E402


#: The judge that answers on this deployment. The paper grades with GPT-5 at high
#: reasoning effort, and both ``gpt-5`` and ``gpt-5.2`` return 404 here, so this is a
#: substitution rather than a configuration: judge choice moved a ResearchClawBench total
#: by about sixteen points, which is larger than any effect this benchmark is being used
#: to look for.
FS_JUDGE_MODEL = "gpt-5.1"

#: The OpenAI-compatible endpoint the judge is served from here, without the
#: ``/responses`` suffix. An endpoint is not a secret; the key that opens it is, and it
#: never appears in this file — see :func:`read_api_key`.
FS_JUDGE_ENDPOINT = "https://shi-lab-2-resource.services.ai.azure.com/openai/v1"

#: The paper grades at high effort and so does this. Lowering it is a change of
#: instrument, not a saving: the reasoning is where this judge does the per-item work
#: that produces a decimal total rather than a round one.
FS_JUDGE_REASONING_EFFORT = "high"

#: Output token budget. At 4,096 and again at 2,048 the judge spent the entire budget on
#: reasoning and returned zero visible characters and no verdict — a complete failure that
#: arrives as HTTP 200. The largest total output observed was 20,004 tokens, of which
#: 15,202 were reasoning and only 4,802 were visible: this budget is charged for the
#: thinking, so sizing it from the answer would under-buy it by a factor of four. 32,000 is
#: the measured maximum with room over it.
FS_JUDGE_MAX_OUTPUT_TOKENS = 32000

#: Wall limit for one call. Mean 72.9 s over the 29 judge calls of the endpoint probe,
#: longest 322.3 s. Nearly twice the longest, because the cost of a timeout here is a
#: refused pair and the cost of waiting is five minutes.
FS_JUDGE_TIMEOUT_SECONDS = 600

#: Attempts per call, transport failures only. Never used in 34 live calls; kept because
#: the one time it is needed is in the middle of a sixty-task pass.
FS_JUDGE_MAX_TRY = 4

#: Backoff between those attempts. Three waits for four attempts.
FS_JUDGE_BACKOFF_SECONDS = (5, 20, 60)

#: HTTP codes worth trying again, the set the endpoint probe retried on. A 4xx that is not
#: one of these is a request this tool got wrong, and sending it four times is four
#: identical mistakes and a longer log.
FS_JUDGE_RETRY_CODES = frozenset({408, 429, 500, 502, 503, 504})

#: Serial, with no flag to change it. Concurrent judge calls were the measured cause of
#: most scoring failures on ResearchClawBench; 34 of 34 serial calls here succeeded with
#: zero retries. Sixty tasks by two arms is 2.6 hours of judging, which does not buy
#: enough to be worth challenging that.
FS_JUDGE_WORKERS = 1

#: Where the key is read from. Outside any repository on purpose: a default inside the
#: tree is one ``git add -A`` away from a leak.
DEFAULT_KEY_FILE = Path.home() / "api.txt"


def read_api_key(path: Path) -> str:
    """The key, from a file that is never committed.

    Tolerant about shape because the caller should never have to print the file to find
    out what shape it is: a bare token, `KEY=token`, and a quoted value all read the
    same. Nothing here echoes the value, and the only confirmation that parsing worked is
    that a call succeeds.
    """
    if not path.is_file():
        raise SystemExit(
            f"No judge key at {path}. Put the key for the reference judge there and pass "
            "--key-file if it lives somewhere else. Do not pass a key on the command "
            "line: it lands in the shell history and in the process table."
        )
    raw = path.read_text(encoding="utf-8").strip()
    if "=" in raw and not raw.startswith("sk-"):
        raw = raw.split("=", 1)[1]
    return raw.strip().strip("\"'")


def redact(text: str) -> str:
    """Strip anything key-shaped before it reaches an error message.

    Error text from an HTTP client can carry the request that produced it, and this
    output gets pasted into issues.
    """
    import re

    return re.sub(r"(sk-|Bearer\s+)[A-Za-z0-9_\-\.]{12,}", r"\1<redacted>", text)


class ResponsesJudge:
    """One judge, one call at a time, through ``urllib.request``.

    Returns the parsed payload and the wall clock it took, and never decides anything
    about it: whether a payload is a score is :func:`src.fs_scoring.draw_record`'s
    question, and keeping the two apart is what lets every refusal rule be tested against
    recorded responses instead of against a live endpoint at 78 seconds a go.

    A transport failure that survives every attempt is returned as a payload rather than
    raised, carrying ``transport_error``. The alternative — an exception here — would make
    the caller invent a draw record for it, and an invented draw is exactly the shape this
    whole file exists to refuse.
    """

    def __init__(
        self,
        *,
        model: str,
        endpoint: str,
        api_key: str,
        reasoning_effort: str = FS_JUDGE_REASONING_EFFORT,
        max_output_tokens: int = FS_JUDGE_MAX_OUTPUT_TOKENS,
        timeout_seconds: float = FS_JUDGE_TIMEOUT_SECONDS,
    ) -> None:
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.reasoning_effort = reasoning_effort
        self.max_output_tokens = max_output_tokens
        self.timeout_seconds = timeout_seconds
        self._api_key = api_key
        self.calls = 0
        self.failures: list[str] = []

    def __call__(self, prompt: str, *, max_try: int = FS_JUDGE_MAX_TRY) -> tuple[dict, float]:
        body = json.dumps(
            {
                "model": self.model,
                "input": prompt,
                "reasoning": {"effort": self.reasoning_effort},
                "max_output_tokens": self.max_output_tokens,
            }
        ).encode("utf-8")

        started = time.time()
        last = ""
        for attempt in range(max_try):
            self.calls += 1
            request = urllib.request.Request(
                f"{self.endpoint}/responses",
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                    "api-key": self._api_key,
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if isinstance(payload, dict):
                    return payload, time.time() - started
                last = f"judge returned a {type(payload).__name__}, not an object"
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8")[:500]
                except Exception:  # noqa: BLE001 - the status is what matters
                    detail = ""
                last = redact(f"HTTP {exc.code}: {detail}")
                if exc.code not in FS_JUDGE_RETRY_CODES:
                    break
            except Exception as exc:  # noqa: BLE001 - the reason is what matters
                last = redact(f"{type(exc).__name__}: {exc}")
            if attempt < max_try - 1:
                time.sleep(FS_JUDGE_BACKOFF_SECONDS[min(attempt, len(FS_JUDGE_BACKOFF_SECONDS) - 1)])

        self.failures.append(last)
        return (
            {"status": "transport_failed", "output": [], "usage": {}, "transport_error": last},
            time.time() - started,
        )


def write_result(out: Path, result: dict) -> None:
    """Create the directory, then replace rather than truncate.

    Both halves are paid for, in ``tools/score_rcb_run.py``'s history rather than in this
    file's: nothing else creates ``<state_dir>/scores/``, so a bare ``write_text`` scored
    every item, printed the total and died on ``FileNotFoundError``, which a driver reads
    as "scoring failed" and retries for four days. The ``os.replace`` is the other half —
    a kill during a plain write leaves a truncated JSON file that a final pass skips
    forever because it exists.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(result, indent=2), encoding="utf-8")
    os.replace(tmp, out)


def resolve_row(rows, task: str):
    """Find the row for ``--task``, accepting ``fs:043`` or ``43``, refusing anything else.

    Through :func:`src.frontierscience.resolve_task_keys` rather than a lookup of its own,
    so this tool and the trial driver read one grammar and raise one refusal. A private
    ``fs:043``-or-integer parser here would be a second encoding of the same rule, and the
    copy that nobody exercises is the copy that drifts.
    """
    keys = resolve_task_keys(rows, tasks=task)
    if len(keys) != 1:
        raise DatasetRefused(
            f"--task {task!r} selects {len(keys)} tasks; this tool scores one answer against "
            f"one task. {FS_TASK_SELECTION_HELP}"
        )
    return rows_by_key(rows)[keys[0]]


def read_answer_meta(path: Path | None, answer: Path) -> dict:
    """Extra ``answer`` fields for the result, from the producer's own ``_meta.json``.

    Optional, and never fatal. The producer of an answer knows things the scorer cannot
    see — which arm wrote it, whether the pipeline completed, whether any stage was
    auto-skipped — and those decide whether the score is admissible. A scorer that
    invented them would be worse than one that omits them, so an unreadable file yields
    nothing and says so.
    """
    candidate = path if path is not None else answer.parent / "_meta.json"
    if not candidate.is_file():
        return {}
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def score(
    row,
    answer_text: str,
    *,
    judge: ResponsesJudge,
    draws: int,
    raw_dir: Path | None,
    dataset_path: Path,
    dataset_sha256: str,
    answer_path: Path,
    answer_meta: Mapping[str, Any],
) -> dict:
    """Draw the judge *draws* times, build the result, and refuse if it is not a measurement.

    Every draw runs even after one has already failed, the same decision
    ``tools/score_rcb_run.py`` made and for the same reason: a refusal says "this total is
    not a measurement", and the remaining draws are what tell you whether it was one flaky
    call or the whole judge. Refusing early throws that away to save a minute.

    The refusal is raised here rather than printed in ``main`` so that a programmatic
    caller cannot obtain the number without it.
    """
    prompt = render_judge_prompt(row, answer_text)
    records: list[dict] = []
    for index in range(draws):
        payload, latency = judge(prompt)
        raw_path = ""
        if raw_dir is not None:
            raw_dir.mkdir(parents=True, exist_ok=True)
            target = raw_dir / f"{row.key.replace(':', '')}.d{index}.json"
            target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            raw_path = str(target)
        record = draw_record(
            payload,
            index=index,
            latency_seconds=latency,
            raw_path=raw_path,
            rubric_points_total=row.rubric_points_total,
        )
        transport = payload.get("transport_error")
        if transport:
            record["failures"] = [f"judge call failed: {transport}", *record["failures"]]
        records.append(record)

    answer_block = {
        "path": str(answer_path),
        "sha256": hashlib.sha256(answer_text.encode("utf-8")).hexdigest(),
        "chars": len(answer_text),
    }
    answer_block.update(dict(answer_meta))
    result = build_result(
        row=row,
        dataset={
            "path": str(dataset_path),
            "sha256": dataset_sha256,
            "rows": FS_DATASET_ROWS,
        },
        answer=answer_block,
        judge={
            "model": judge.model,
            "endpoint": judge.endpoint,
            "reasoning_effort": judge.reasoning_effort,
            "max_output_tokens": judge.max_output_tokens,
            "timeout_seconds": judge.timeout_seconds,
            "concurrency": FS_JUDGE_WORKERS,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "prompt_chars": len(prompt),
        },
        draws=records,
        draws_requested=draws,
        scored_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        code_version=code_version(),
    )
    if result["refused"]:
        raise ScoringRefused("this total is not a measurement", result, result["refusal_reasons"])
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="score_fs_run",
        description="Score one FrontierScience-Research answer against the task's rubric.",
    )
    parser.add_argument(
        "--task",
        required=True,
        help="Task to score, as a key (`fs:043`) or a row index (`43`). Row index, never "
             "task_group_id: rows 6 and 11 of the split are byte-identical, so the group "
             "id addresses fifty-nine of the sixty rows.",
    )
    parser.add_argument(
        "--answer",
        required=True,
        type=Path,
        metavar="PATH",
        help="File holding the answer to grade. Read as UTF-8 and sent verbatim.",
    )
    parser.add_argument(
        "--answer-meta",
        type=Path,
        default=None,
        metavar="PATH",
        help="JSON file whose keys are merged into the result's `answer` block, for the "
             "facts only the producer knows. Defaults to `_meta.json` beside the answer "
             "when that file exists, and to nothing when it does not.",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to research_test.jsonl. Defaults to $FRONTIERSCIENCE_DATASET, then to "
             "~/.cache/frontierscience/research_test.jsonl. The digest is pinned and a "
             "mismatch is refused rather than scored.",
    )
    parser.add_argument(
        "--model",
        default=FS_JUDGE_MODEL,
        help=f"Judge model id. Defaults to {FS_JUDGE_MODEL}, which is what answers on this "
             "endpoint; the paper's GPT-5 returns 404 here, so no total is comparable to "
             "the paper's table.",
    )
    parser.add_argument(
        "--endpoint",
        default=FS_JUDGE_ENDPOINT,
        help=f"OpenAI-compatible base URL, without /responses. Defaults to {FS_JUDGE_ENDPOINT}.",
    )
    parser.add_argument(
        "--key-file",
        type=Path,
        default=DEFAULT_KEY_FILE,
        metavar="PATH",
        help=f"File holding the judge's key. Defaults to {DEFAULT_KEY_FILE}. Never pass the "
             "key itself: there is no flag for it, because an argument lands in the shell "
             "history and in the process table.",
    )
    parser.add_argument(
        "--reasoning-effort",
        default=FS_JUDGE_REASONING_EFFORT,
        choices=("low", "medium", "high"),
        help=f"Judge reasoning effort. Defaults to {FS_JUDGE_REASONING_EFFORT}, which is what "
             "the paper grades at; anything else is a different instrument.",
    )
    parser.add_argument(
        "--judge-max-tokens",
        type=int,
        default=FS_JUDGE_MAX_OUTPUT_TOKENS,
        metavar="N",
        help=f"Judge output token budget. Defaults to {FS_JUDGE_MAX_OUTPUT_TOKENS}. At 4096 "
             "and at 2048 the judge spent the whole budget on reasoning and returned no "
             "verdict at all; the largest total output observed was 20,004 tokens, 15,202 "
             "of them reasoning, so this budget buys thinking rather than answer.",
    )
    parser.add_argument(
        "--judge-timeout",
        type=float,
        default=FS_JUDGE_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help=f"Wall limit for one judge call. Defaults to {FS_JUDGE_TIMEOUT_SECONDS}. The mean "
             "of the 29 judge calls observed here was 72.9 s and the longest took 322.3 s.",
    )
    parser.add_argument(
        "--draws",
        type=int,
        default=1,
        metavar="N",
        help="Grade the same answer N times and report the mean. Defaults to 1, which "
             "reports its dispersion as unmeasured rather than as zero. " + FS_JUDGE_NOISE_NOTE + ".",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=None,
        metavar="PATH",
        help="Directory to save each judge response in, for regression and audit. Point it "
             "outside this repository: the judge quotes rubric items verbatim while it "
             "reasons. Defaults to not saving them.",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        metavar="PATH",
        help="Where to write the fs_score/1 result. Nothing is written when the total is "
             "refused, so a driver can inherit the refusal from the file's absence.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.draws < 1:
        print("--draws must be at least 1.", file=sys.stderr)
        return 2
    if not args.answer.is_file():
        print(f"No answer file at {args.answer}.", file=sys.stderr)
        return 2

    dataset_path = resolve_dataset_path(args.dataset)
    try:
        rows = load_dataset(args.dataset)
        row = resolve_row(rows, args.task)
    except DatasetRefused as exc:
        print(f"refusing to score: {exc}", file=sys.stderr)
        return 1

    answer_text = args.answer.read_text(encoding="utf-8")
    judge = ResponsesJudge(
        model=args.model,
        endpoint=args.endpoint,
        api_key=read_api_key(args.key_file),
        reasoning_effort=args.reasoning_effort,
        max_output_tokens=args.judge_max_tokens,
        timeout_seconds=args.judge_timeout,
    )

    refused: ScoringRefused | None = None
    try:
        result = score(
            row,
            answer_text,
            judge=judge,
            draws=args.draws,
            raw_dir=args.raw_dir,
            dataset_path=dataset_path,
            dataset_sha256=FS_DATASET_SHA256,
            answer_path=args.answer,
            answer_meta=read_answer_meta(args.answer_meta, args.answer),
        )
    except ScoringRefused as exc:
        refused, result = exc, exc.result

    print(f"judge:   {result['judge']['model']} (the paper's GPT-5 is 404 on this endpoint,")
    print("         so this total is NOT comparable to the paper's table)")
    print(f"task:    {row.key}  {row.subject}  {row.rubric_items} rubric items, "
          f"{row.rubric_points_total} points")
    print(f"answer:  {args.answer}  ({result['answer']['chars']} chars)")
    print()
    for draw in result["draws"]:
        points = draw["points"]
        shown = "REFUSED" if points is None else f"{points:.3f}"
        print(
            f"  draw {draw['index']}: {shown:>7}  status={draw['status']}  "
            f"{draw['visible_chars']} visible chars  {draw['latency_seconds']:.1f}s"
        )
        for reason in draw["failures"]:
            print(f"      - {reason}")

    print()
    if refused is not None:
        print(f"REFUSING TO QUOTE A TOTAL: {len(refused.reasons)} reason(s).")
        for reason in refused.reasons:
            print(f"  - {reason}")
        print("A failed draw is not a zero: a bad answer scores exactly 0.000 here, so")
        print("recording a failure as 0 would make the two indistinguishable. Nothing")
        print(f"was written to {args.out}.")
        return 1

    print(f"TOTAL (judge {result['judge']['model']}, {result['draws_requested']} draw"
          f"{'s' if result['draws_requested'] != 1 else ''}): {result['total_score']:.3f}"
          f" / {row.rubric_points_total}")
    print(f"  dispersion: {result['spread_text']}")
    print(f"  pass at {result['pass_threshold']}: {result['passed']}")
    write_result(args.out, result)
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
