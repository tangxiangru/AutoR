#!/usr/bin/env python3
"""Answer every FIRE-Bench question from parametric memory alone, and score it.

The benchmark's premise is *rediscovery*: an agent designs and runs experiments and
arrives at a finding a paper's authors also arrived at. That premise assumes the finding
is not already in the model. These are published papers, most of them from 2023-2024, and
the model under test is later than all of them.

This is the control that says how much of any score is rediscovery. One API call per task:
the research question, no tools, no data, no experiment, no browsing, and an instruction to
answer in the register the grader reads. Whatever it scores is the floor that a run doing
real work has to clear before any of its score can be attributed to the work.

Writes FIRE-Bench-format logs so the benchmark's own scorer reads them unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.firebench import LOG_HEADER_RULE, available_tasks, bench_root_from, load_task, read_api_key

#: Every tool the CLI ships, denied by name. The floor has to be measured on the *same
#: instrument* as the arms it is a floor for -- same binary, same model, same wall clock
#: budget -- with only the thing under test removed, which is the ability to do anything.
#: Denying tools rather than trusting the prompt: "do not run an experiment" is a request,
#: and a model that quietly runs one turns the control into another arm.
ALL_TOOLS = (
    "Bash,Read,Write,Edit,MultiEdit,NotebookEdit,Glob,Grep,WebSearch,WebFetch,"
    "Task,TodoWrite,BashOutput,KillShell,SlashCommand,ToolSearch"
)

#: Deliberately close to what the pipeline's own synthesis call is told, minus everything
#: about experiments -- so a difference between this and a real run is the work, not the
#: register the answer is written in.
PROMPT = """You are asked one research question. Answer it from what you already know.

Do not describe an experiment, do not propose one, and do not say that one is needed.
State the finding.

Write two to four sentences of plain prose: the answer to the question, and the condition
under which it holds or breaks. No headings, no bullets, no preamble, no numbers, no
citations. The register of a paper's concluding sentence.

## The question

{question}
"""


def ask(question: str, *, model: str, endpoint: str, key: str, timeout: int = 300) -> str:
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": PROMPT.format(question=question)}],
            "max_completion_tokens": 2000,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}/chat/completions",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}", "api-key": key},
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return (payload["choices"][0]["message"]["content"] or "").strip()
        except Exception:  # noqa: BLE001 - a lost call is a retry, not a result
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))
    return ""


def ask_cli(question: str, *, model: str, timeout: int = 600) -> str:
    """One call to the same CLI the arms use, with every tool denied.

    `--strict-mcp-config` with a config naming no servers is what makes "no tools" true
    rather than asked for: without it the CLI still loads whatever the operator's user has
    configured, and on the box this was written for that is a web search server.
    """
    import subprocess, tempfile

    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / "mcp.json"
        empty.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
        completed = subprocess.run(
            [
                "claude", "-p", PROMPT.format(question=question),
                "--model", model,
                "--output-format", "json",
                "--mcp-config", str(empty), "--strict-mcp-config",
                "--disallowed-tools", ALL_TOOLS,
            ],
            capture_output=True, text=True, timeout=timeout, cwd=tmp,
            env={**os.environ, "CLAUDE_STREAM_IDLE_TIMEOUT_MS": "1800000",
                 "CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS": "1800000"},
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return ""
    return (payload.get("result") or "").strip() if not payload.get("is_error") else ""


def main() -> int:
    parser = argparse.ArgumentParser(prog="fire_parametric_probe")
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--out-root", required=True, help="Where the log tree goes.")
    parser.add_argument("--model", default="gpt-5.1")
    parser.add_argument("--endpoint", default="https://shi-lab-2-resource.services.ai.azure.com/openai/v1")
    parser.add_argument("--agent-id", default="parametric")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--score", action="store_true",
                        help="Score what was written, with the benchmark's own scorer, three "
                             "draws per log, and print the arm-level means.")
    parser.add_argument("--backend", choices=["openai", "claude-cli"], default="openai",
                        help="claude-cli measures the floor on the same binary and model "
                             "the arms use, which is the only version of it that they can "
                             "be compared against.")
    args = parser.parse_args()

    bench_root = bench_root_from(args.bench_root)
    key = read_api_key()
    if not key:
        raise SystemExit("no key; expected ~/api.txt")
    out_root = Path(args.out_root).expanduser().resolve()
    stamp = time.strftime("%Y%m%d%H%M%S")
    tasks = available_tasks(bench_root, "verified")

    def one(task_id: str) -> tuple[str, int]:
        task = load_task(bench_root, task_id, "verified")
        # The question only. Not the resource list, not the budget, not the datasets --
        # none of that is answerable without running anything, and including it would
        # invite the model to describe a study instead of stating a finding.
        question = task.instruction.split("You have access to")[0].strip()
        answer = (
            ask_cli(question, model=args.model) if args.backend == "claude-cli"
            else ask(question, model=args.model, endpoint=args.endpoint, key=key)
        )
        log = out_root / "log" / args.agent_id / args.model / task_id / stamp / "log.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            f"agent_id: {args.agent_id}\ntask_id: {task_id}\nllm_model: {args.model}\n"
            f"{LOG_HEADER_RULE}\n"
            "This run made no observation. One model call, no tools, no data, no experiment.\n\n"
            + json.dumps({"result": answer}, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        return task_id, len(answer)

    done = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(one, t): t for t in tasks}
        for future in as_completed(futures):
            try:
                task_id, n = future.result()
                done += 1
                print(f"[{done}/{len(tasks)}] {task_id}: {n} chars", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[fail] {futures[future]}: {type(exc).__name__}: {exc}", flush=True)
    print(f"[written] {out_root}/log/{args.agent_id}/{args.model}/")
    if args.score:
        score(out_root / "log" / args.agent_id / args.model, bench_root, args.concurrency)
    return 0


def score(root: Path, bench_root: Path, concurrency: int) -> None:
    """Run the shipped scorer over every log this probe wrote, and report the floor.

    In the same file as the generator on purpose: the floor is only meaningful beside the
    exact prompt and model that produced it, and a number carried to another script is a
    number whose provenance is a filename.
    """
    import statistics
    import subprocess

    scorer = REPO_ROOT / "tools" / "score_fire_run.py"
    logs = sorted(root.glob("*/*/log.log"))

    def one(path: Path):
        task = path.parent.parent.name
        out = path.parent / "_score"
        subprocess.run(
            [sys.executable, str(scorer), "--bench-root", str(bench_root), "--log-file",
             str(path), "--task", task, "--draws", "3", "--out-dir", str(out)],
            capture_output=True, text=True, env={**os.environ, "TMPDIR": "/tmp"},
        )
        summary = out / "summary.json"
        return task, (json.loads(summary.read_text(encoding="utf-8")) if summary.is_file() else {})

    rows: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(one, p): p for p in logs}
        for index, future in enumerate(as_completed(futures), 1):
            task, summary = future.result()
            rows[task] = summary
            print(f"[score {index}/{len(logs)}] {task}: "
                  f"F1={(summary.get('median_draw') or {}).get('f1')}", flush=True)
    (root.parent.parent.parent / "summaries.json").write_text(
        json.dumps(rows, indent=1), encoding="utf-8")
    print()
    for metric in ("precision", "recall", "f1"):
        values = [(r.get("median_draw") or {}).get(metric) for r in rows.values()]
        values = [v for v in values if v is not None]
        if values:
            sd = statistics.stdev(values) if len(values) > 1 else 0.0
            print(f"{metric:10s} {statistics.mean(values):5.1f} ± {sd:4.1f}   (n={len(values)})")


if __name__ == "__main__":
    raise SystemExit(main())
