#!/usr/bin/env python3
"""Score a FIRE-Bench log more than once, and report the spread as well as the score.

::

    python3 tools/score_fire_run.py --bench-root ~/FIRE-Bench \\
        --log-file ~/FIRE-Bench/log/autor/opus/cot_in_planning/20260818.../log.log \\
        --task cot_in_planning --draws 5

**Why draws, and why the spread is reported first.** The evaluator is an LLM pipeline:
the answer is summarised, both texts are decomposed into atomic claims, and each claim is
judged. Measured on this box, the *same log* scored three times with the same
configuration returned F1 of 57.1, 92.3 and 100.0 -- a 43-point range with nothing
changing but the sampling. The decomposition is the unstable part: the same paragraph
comes back as three claims one time and six the next, and the denominator moves with it.

A single draw on a single task is therefore not a measurement of an agent, and a table of
one-draw numbers is a table of judge noise. This tool exists to make that impossible to
report by accident: it prints the median and the range together, and refuses to print a
mean of one.

Stdlib only, like the rest of ``tools/``. The scoring itself needs the benchmark's
``ragchecker``/``refchecker``/``litellm``/``torch`` tree, which lives in a separate
virtualenv; this file finds that interpreter and runs ``tools/fire_eval_driver.py``
under it, one draw per subprocess. One draw per process rather than a loop inside one is
deliberate: ``refchecker`` retries a 4xx forever with a ten-second sleep and no
traceback, so a hung draw has to be killable without losing the draws already finished.

**The reportable row is ``median_draw``, not the three per-metric medians.** FIRE-Bench
reports precision, recall and F1 together, and those three numbers have to come from one
draw or the row describes no run that happened -- ``F1 = 2PR/(P+R)`` fails on it, and the
reader cannot tell that from an arithmetic error. The per-metric medians and ranges are
kept beside it because each metric's spread is worth reporting; laying three of them out
as a row is what is forbidden.

**A draw that did not produce a number is not a zero.** ``no_conclusion``,
``judge_failed`` and ``error`` draws are counted and named in the summary, and excluded
from the statistics -- the failure mode this guards against is the one that scored a
ResearchClawBench run at 19.5 when two of its three items were judge failures rather than
zeros.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.firebench import load_credentials  # noqa: E402

#: Where the benchmark's scoring dependencies live. A virtualenv rather than the system
#: interpreter because ``refchecker`` pins ``torch>=2,<3`` and pulls in spacy and
#: transformers; installing that into whatever python happens to be first on PATH is how
#: an unrelated tool stops working a week later.
DEFAULT_VENV = Path.home() / ".venvs" / "firebench"

#: Per draw. Generous because the pipeline makes one call per claim and a slow
#: deployment has been seen at 65 s for a single log; short enough that refchecker's
#: infinite retry loop is caught rather than inherited.
DEFAULT_TIMEOUT = 900


def find_interpreter(explicit: str | None) -> str:
    if explicit:
        return explicit
    candidate = DEFAULT_VENV / "bin" / "python"
    if candidate.is_file():
        return str(candidate)
    raise SystemExit(
        f"No scoring interpreter. Expected {candidate}. Create it with:\n"
        f"  uv venv --python 3.11 {DEFAULT_VENV}\n"
        f"  {DEFAULT_VENV}/bin/python -m pip install ragchecker refchecker openai python-dotenv\n"
        "or pass --python."
    )


def one_draw(
    *,
    python: str,
    driver: Path,
    bench_root: Path,
    log_file: Path,
    task: str,
    out: Path,
    timeout: int,
) -> dict:
    command = [
        python,
        str(driver),
        "--bench-root", str(bench_root),
        "--log-file", str(log_file),
        "--task", task,
        "--out", str(out),
    ]
    env = os.environ.copy()
    env.setdefault("TMPDIR", "/tmp")
    started = time.time()
    try:
        subprocess.run(command, env=env, cwd=str(bench_root), timeout=timeout,
                       capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "seconds": round(time.time() - started, 1),
            "note": f"draw exceeded {timeout}s; refchecker retries a bad model name forever",
        }
    if out.is_file():
        try:
            return json.loads(out.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"status": "error", "note": "driver wrote no readable result"}


def median_draw(draws: list[dict]) -> dict | None:
    """The one draw whose F1 is the median, as a coherent (precision, recall, F1) triple.

    **A row has to come from one draw.** Taking the median of each metric independently
    is what this function replaced, and it produces rows that cannot be true together:
    measured on two real cells, ``P = 53.8, R = 50.0, F1 = 41.2`` -- whose harmonic mean
    is 51.8, not 41.2 -- because the three medians came from three different draws.
    Nothing in the arithmetic is wrong; the row simply describes no run that happened,
    and a reader who checks it against F1 = 2PR/(P+R) finds an error that is not there.

    The per-metric medians stay in the summary beside this, because the spread of each
    metric is a real thing to report. What may not be done is to lay three of them out
    as a row.
    """
    scored = [
        d for d in draws
        if d.get("status") == "scored" and (d.get("overall_metrics") or {}).get("f1") is not None
    ]
    if not scored:
        return None
    scored.sort(key=lambda d: float(d["overall_metrics"]["f1"]))
    chosen = scored[len(scored) // 2]["overall_metrics"]
    return {
        "precision": round(float(chosen.get("precision", 0.0)), 2),
        "recall": round(float(chosen.get("recall", 0.0)), 2),
        "f1": round(float(chosen.get("f1", 0.0)), 2),
    }


def summarise(draws: list[dict]) -> dict:
    scored = [d for d in draws if d.get("status") == "scored" and d.get("overall_metrics")]
    summary: dict = {
        "draws": len(draws),
        "scored": len(scored),
        "not_scored": {},
        # The row. Everything below it is per-metric spread, which is not a row.
        "median_draw": median_draw(draws),
    }
    for draw in draws:
        if draw.get("status") != "scored":
            summary["not_scored"][draw.get("status", "?")] = (
                summary["not_scored"].get(draw.get("status", "?"), 0) + 1
            )
    for metric in ("precision", "recall", "f1"):
        values = [float(d["overall_metrics"][metric]) for d in scored if metric in d["overall_metrics"]]
        if not values:
            continue
        summary[metric] = {
            "median": round(statistics.median(values), 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "values": [round(v, 2) for v in values],
        }
        if len(values) > 1:
            summary[metric]["stdev"] = round(statistics.stdev(values), 2)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="score_fire_run")
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--log-file", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--draws", type=int, default=3,
                        help="How many times to score the same log. Default 3; the judge's "
                             "measured range on one identical log was 43 F1 points.")
    parser.add_argument("--out-dir", default="",
                        help="Where per-draw JSON goes. Defaults to <log-file dir>/_score/.")
    parser.add_argument("--python", default="", help=f"Scoring interpreter. Defaults to {DEFAULT_VENV}/bin/python.")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--max-transport-retries", type=int, default=4,
                        help="Extra attempts to replace draws lost to transport, not to the "
                             "judge. Measured on this deployment, roughly one draw in four "
                             "came back APITimeoutError; without this the median is taken "
                             "over whatever survived, which is a smaller and differently "
                             "biased sample than the one that was asked for.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    bench_root = Path(args.bench_root).expanduser().resolve()
    log_file = Path(args.log_file).expanduser().resolve()
    if not log_file.is_file():
        raise SystemExit(f"No log at {log_file}")
    driver = Path(__file__).resolve().parent / "fire_eval_driver.py"
    if not driver.is_file():
        raise SystemExit(f"No driver at {driver}")
    python = find_interpreter(args.python or None)
    # From the key file, into this process's environment, and inherited by every draw's
    # subprocess. Not copied into the checkout: the judge needs the key, the repository
    # does not, and FIRE-Bench's `.env` is a tracked file.
    load_credentials()
    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else log_file.parent / "_score"
    out_dir.mkdir(parents=True, exist_ok=True)

    draws: list[dict] = []
    wanted = max(1, args.draws)
    attempts = 0
    # Attempts, not draws. A transport failure is not a draw of the judge -- it is a draw
    # that never reached the judge -- so replacing it keeps the sample the size that was
    # asked for. A *judge* failure is not replaced: that is the judge answering.
    while len([d for d in draws if d.get("status") == "scored"]) < wanted and attempts < wanted + max(0, args.max_transport_retries):
        attempts += 1
        out = out_dir / f"draw_{attempts:02d}.json"
        record = one_draw(
            python=python, driver=driver, bench_root=bench_root, log_file=log_file,
            task=args.task, out=out, timeout=args.timeout,
        )
        draws.append(record)
        metrics = record.get("overall_metrics") or {}
        print(
            f"attempt {attempts}: {record.get('status')} "
            + (f"P={metrics.get('precision')} R={metrics.get('recall')} F1={metrics.get('f1')} "
               if metrics else "")
            + f"({record.get('seconds', '?')}s)",
            flush=True,
        )
        # A draw that could not produce a number will not produce one on the next attempt
        # either -- there is no conclusion in the log, or the task id is not in the
        # evaluator's dictionary. Spending four more draws on it buys nothing.
        if record.get("status") in {"no_conclusion", "unknown_task"}:
            break

    summary = summarise(draws)
    summary.update({
        "task": args.task,
        "log_file": str(log_file),
        "judge": next((d.get("judge") for d in draws if d.get("judge")), None),
        "conclusion": next((d.get("conclusion") for d in draws if d.get("conclusion")), None),
        "core_idea": next((d.get("core_idea") for d in draws if d.get("core_idea")), None),
        "reference": next((d.get("reference") for d in draws if d.get("reference")), None),
    })
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items()
                      if k in {"task", "draws", "scored", "not_scored", "median_draw",
                               "precision", "recall", "f1"}},
                     indent=2))
    print(f"[written] {summary_path}")
    return 0 if summary["scored"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
