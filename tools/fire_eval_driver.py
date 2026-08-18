#!/usr/bin/env python3
"""Score one FIRE-Bench log with FIRE-Bench's own evaluator. One draw, one JSON out.

**This file does not run under AutoR's interpreter.** It imports the benchmark's
`eval/RAGChecker/eval.py`, which needs ``ragchecker``, ``refchecker``, ``litellm``,
``torch`` and their dependency tree. ``tools/score_fire_run.py`` is the stdlib-only
orchestrator that invokes this one with the right interpreter and aggregates the draws;
this file exists as a file rather than as a ``-c`` string so that what was run is
readable and diffable afterwards.

It re-implements nothing. The claim decomposition, the judge prompts and the
precision/recall arithmetic are the benchmark's, called through
``eval.eval_single_log``. What it adds is the three things that call does not do:

1. **It refuses instead of scoring nothing.** ``extract_single_final_thought`` returns
   ``None`` for a log with no result line, and ``eval_single_log`` then interpolates it
   into an f-string, so the judge is handed the four characters ``None`` and scores them
   -- a precision of 0.0 that is indistinguishable from a wrong answer. A missing
   conclusion is a missing run, and it exits with ``status: "no_conclusion"``.
2. **It records what was scored, not only the score.** The extracted conclusion and the
   summariser's "core idea" both go in the output, because the pipeline's first step
   deletes every number in the text and a score that is surprising is usually surprising
   there rather than in the judge.
3. **It reports only the metrics that mean anything.** ``eval.py`` requests
   ``all_metrics`` while hardcoding ``retrieved_context: []``, so the eight retriever and
   generator metrics are the empty-input fallbacks in
   ``ragchecker/computation.py`` -- structural zeros that read like measurements.
   ``overall_metrics`` is separated out from them in the output.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(prog="fire_eval_driver")
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--log-file", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    bench_root = Path(args.bench_root).expanduser().resolve()
    log_file = Path(args.log_file).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    record: dict = {
        "task": args.task,
        "log_file": str(log_file),
        "bench_root": str(bench_root),
        "status": "failed",
    }
    started = time.time()

    # cwd and sys.path both matter: eval.py reads `base_dir = "log"` relative to cwd, and
    # `from utils import *` has to resolve to eval/RAGChecker/utils.py rather than to the
    # checkout's own utils/ package.
    eval_dir = bench_root / "eval" / "RAGChecker"
    os.chdir(bench_root)
    sys.path.insert(0, str(eval_dir))
    try:
        from dotenv import load_dotenv

        load_dotenv(bench_root / ".env")
        import eval as fire_eval  # noqa: A001 - the benchmark named it this

        record["judge"] = {
            "core_idea_model": fire_eval.eval_model,
            "claim_model": fire_eval.claim_model,
            "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        }
        from utils import extract_core_idea, extract_single_final_thought, gt, query

        raw = extract_single_final_thought(str(log_file))
        if not raw or not str(raw).strip():
            record["status"] = "no_conclusion"
            record["note"] = (
                "extract_single_final_thought found nothing. The log has no result line, "
                "so there is no answer to score -- this is not a score of zero."
            )
            out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(json.dumps({"status": record["status"], "out": str(out_path)}))
            return 3
        record["conclusion"] = raw
        record["conclusion_chars"] = len(raw)
        if args.task not in gt:
            record["status"] = "unknown_task"
            record["note"] = f"{args.task!r} is not in the evaluator's gt dictionary."
            out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(json.dumps({"status": record["status"], "out": str(out_path)}))
            return 4
        record["reference"] = gt[args.task]
        record["question"] = query[args.task]
        record["core_idea"] = extract_core_idea(raw, fire_eval.client, fire_eval.eval_model)

        results = fire_eval.eval_single_log(
            str(log_file), "", "", args.task, "", fire_eval.client, fire_eval.eval_model
        )
        payload = json.loads(results.to_json())
        metrics = payload.get("metrics", {})
        record["overall_metrics"] = metrics.get("overall_metrics", {})
        record["other_metrics_structurally_zero"] = {
            name: value for name, value in metrics.items() if name != "overall_metrics"
        }
        record["claims"] = {
            "response": payload.get("results", [{}])[0].get("response_claims"),
            "gt_answer": payload.get("results", [{}])[0].get("gt_answer_claims"),
        }
        record["status"] = "scored" if record["overall_metrics"] else "judge_failed"
    except Exception as exc:  # noqa: BLE001 - the traceback is the result here
        record["status"] = "error"
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["traceback"] = traceback.format_exc()

    record["seconds"] = round(time.time() - started, 1)
    out_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": record["status"], "out": str(out_path),
                      **record.get("overall_metrics", {})}))
    return 0 if record["status"] == "scored" else 1


if __name__ == "__main__":
    raise SystemExit(main())
