#!/usr/bin/env python3
"""Score one AIRS-Bench workspace with the benchmark's own evaluator.

::

    python tools/score_airs_run.py --repo ~/airs-bench --raw-dir /data/airs-raw \\
        --task TextualSimilaritySickSpearmanCorrelation --workspace /runs/sick_autor \\
        --python /path/to/venv/bin/python --out score.json

Nothing here computes a metric. ``evaluate_prepare.py`` and ``evaluate.py`` are the task's
own files and they are run unmodified; this tool stages them somewhere the agent cannot
reach, parses the number they print, and applies the benchmark's published normalization.

That distinction is the whole point of the file. A harness that reimplements a benchmark's
scorer is measuring its own reimplementation, and the two only agree until one of them is
edited.

**Where the labels go.** ``evaluate_prepare.py`` writes the test split *with its labels*
into whatever directory it is given. That directory is created under ``--score-dir`` and
removed afterwards unless ``--keep-score-dir`` is passed — never inside the workspace,
which the agent can still read on a resumed run.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.airsbench import TaskScore, load_task, score_submission  # noqa: E402


#: Printed beside every mean. The published leaderboard aggregates twenty tasks at ten or
#: twenty seeds; a number from this tool is neither of those until it is run that way, and
#: a table that does not say so invites exactly the comparison it cannot support.
COMPARABILITY_NOTE = (
    "AIRS-Bench's published leaderboard is a mean normalized score over all 20 tasks at "
    "10-20 seeds per agent. A score over fewer tasks, or at one seed, is not a point on "
    "that leaderboard however similar the units look."
)


def format_score(score: TaskScore) -> str:
    lines = [f"task            {score.task}"]
    if score.valid_submission and score.value is not None:
        direction = "lower is better" if score.lower_is_better else "higher is better"
        lines += [
            f"metric          {score.metric} = {score.value:.6g}  ({direction})",
            f"SOTA            {score.sota_score:.6g}",
            f"est. worst      {score.worst_score:.6g}",
            f"optimum         {score.optimal_score:.6g}",
            f"normalized      {score.normalized:.4f}"
            + ("   (>1 means past human SOTA)" if (score.normalized or 0) > 1 else ""),
        ]
        if len(score.all_metrics) > 1:
            others = ", ".join(f"{k}={v:.6g}" for k, v in score.all_metrics.items() if k != score.metric)
            lines.append(f"also reported   {others}")
    else:
        lines += [
            "metric          -- no valid submission --",
            f"reason          {score.reason}",
            f"normalized      n/a (counts as an invalid submission, not as a low score)",
        ]
    submission = score.submission or {}
    lines.append(
        f"submission      rows={submission.get('rows')} expected={submission.get('expected_rows')} "
        f"path={submission.get('path')}"
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="score_airs_run", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default="airs-bench", metavar="PATH",
                        help="Path to an airs-bench checkout.")
    parser.add_argument("--raw-dir", required=True, metavar="PATH",
                        help="Shared raw-data directory holding the downloaded datasets.")
    parser.add_argument("--task", required=True, metavar="NAME")
    parser.add_argument("--workspace", required=True, metavar="PATH",
                        help="Workspace holding submission.csv.")
    parser.add_argument("--python", default=sys.executable, metavar="BIN",
                        help="Interpreter used to run the task's evaluator. It needs the task's "
                             "evaluate_container_python_requirements installed.")
    parser.add_argument("--score-dir", metavar="PATH",
                        help="Where the labelled test split is staged. Defaults to a temporary "
                             "directory that is removed afterwards. Never put this inside the "
                             "workspace: it contains the answers.")
    parser.add_argument("--keep-score-dir", action="store_true",
                        help="Leave the scoring directory in place for inspection.")
    parser.add_argument("--timeout", type=int, default=3600, metavar="SECONDS")
    parser.add_argument("--out", metavar="PATH", help="Write the score as JSON.")
    parser.add_argument("--quiet", action="store_true", help="Print JSON only.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    task = load_task(Path(args.repo), args.task)
    workspace = Path(args.workspace).expanduser().resolve()

    with tempfile.TemporaryDirectory(prefix="airs-score-") as scratch:
        score_dir = Path(args.score_dir).expanduser() if args.score_dir else Path(scratch) / "score"
        score = score_submission(
            task=task,
            raw_dir=Path(args.raw_dir),
            workspace=workspace,
            score_dir=score_dir,
            python=args.python,
            timeout=args.timeout,
            keep_score_dir=args.keep_score_dir,
        )

    payload = score.to_dict()
    payload["workspace"] = str(workspace)
    payload["comparability"] = COMPARABILITY_NOTE
    if args.out:
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.quiet:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(format_score(score))
        print(f"\n{COMPARABILITY_NOTE}")
    return 0 if score.valid_submission else 1


if __name__ == "__main__":
    raise SystemExit(main())
