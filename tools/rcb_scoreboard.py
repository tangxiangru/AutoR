#!/usr/bin/env python3
"""Print the ResearchClawBench arm scoreboard as markdown, from the score files.

The README used to carry this table by hand, and it went stale the way a hand-copied table
always does: it read n=35 for arms that had reached 40, and it omitted nine arms that had
been run since. A table nobody can regenerate is a claim nobody can check.

Two rules this encodes, because both have been got wrong in this repository before:

* **One score per task: the newest workspace that has one.** Several arms hold two or three
  workspaces per task from relaunches, and letting glob order choose between them makes the
  arm mean depend on the order the filesystem happens to return.
* **Only `_score_gpt51.json`.** That is `--judge reference --draws 3`. A one-draw number or
  another judge is not a smaller number, it is an incomparable one, and mixing them has
  produced two published errors.

`n` is the number of tasks an arm has scored. An arm below 40 is missing tasks, and they
are not missing at random -- the ones still outstanding are usually the slow and hard ones,
which the control scores *above* its own average on, so a partial arm's paired lead reads
high. Sort order is the paired difference, but do not read the top of the table as a
ranking until the `n` column says 40.

Usage:
    python3 tools/rcb_scoreboard.py [--runs DIR] [--min-n 10] [--contrasts]
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import statistics as st
from pathlib import Path

DEFAULT_RUNS = "/rmeng_data/robtang/rcb_runs"
CONTROL = "control_bare_cc"

#: Two-sided 95% t for small samples; 2.02 is close enough past ~40.
_T = {9: 2.262, 12: 2.179, 13: 2.160, 15: 2.131, 17: 2.110, 19: 2.093, 20: 2.086,
      21: 2.080, 24: 2.064, 25: 2.060, 29: 2.045, 31: 2.040, 33: 2.035, 35: 2.030,
      36: 2.028, 37: 2.026, 39: 2.023}


def tcrit(n: int) -> float:
    return _T.get(n - 1, 2.02 if n > 21 else 2.4)


def load(runs: str, arm: str) -> dict[str, float]:
    """One score per task, from the newest scored workspace."""
    out: dict[str, list[tuple[str, float]]] = {}
    for path in glob.glob(f"{runs}/{arm}/*/_score_gpt51.json"):
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        total, weight = payload.get("total_score"), payload.get("total_weight")
        if not (isinstance(total, (int, float)) and weight):
            continue
        name = Path(path).parent.name
        out.setdefault("_".join(name.split("_")[:2]), []).append((name, total / weight))
    return {task: max(v)[1] for task, v in out.items()}


def paired(a: dict[str, float], b: dict[str, float]):
    keys = sorted(set(a) & set(b))
    if len(keys) < 3:
        return None
    d = [a[k] - b[k] for k in keys]
    se = st.stdev(d) / math.sqrt(len(d))
    return len(d), st.mean(d), se, tcrit(len(d)) * se, sum(x > 0 for x in d), sum(x < 0 for x in d)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", default=DEFAULT_RUNS)
    ap.add_argument("--min-n", type=int, default=10, help="skip arms with fewer scored tasks")
    ap.add_argument("--contrasts", action="store_true",
                    help="also print the one-variable arm pairs")
    args = ap.parse_args(argv)

    arms = sorted({Path(p).parts[-3] for p in glob.glob(f"{args.runs}/*/*/_score_gpt51.json")})
    data = {a: load(args.runs, a) for a in arms}
    control = data.get(CONTROL, {})
    if not control:
        print(f"no {CONTROL} scores under {args.runs}")
        return 1

    rows = []
    for arm, scores in data.items():
        if arm == CONTROL or len(scores) < args.min_n:
            continue
        res = paired(scores, control)
        if res is None:
            continue
        n, mean, se, half, won, lost = res
        rows.append((mean, arm, len(scores), st.mean(scores.values()), se, half, won, lost))

    print("| arm | n | mean | vs bare Claude Code | 95% CI | W–L |")
    print("|:---|---:|---:|---:|:---|---:|")
    for mean, arm, n, arm_mean, se, half, won, lost in sorted(rows, reverse=True):
        flag = " ✳" if (mean - half > 0 or mean + half < 0) else ""
        full = "**" if n >= 40 else ""
        print(f"| `{arm}` | {full}{n}{full} | {arm_mean:.2f} | {mean:+.2f} ± {se:.2f}{flag} "
              f"| {mean - half:+.2f} … {mean + half:+.2f} | {won}–{lost} |")
    print(f"| `{CONTROL}` | **{len(control)}** | {st.mean(control.values()):.2f} | — | | |")
    print("\n✳ = 95% interval excludes zero. **bold n** = all forty tasks scored.")

    if args.contrasts:
        pairs = [
            ("xrev_on", "xrev_off", "cross-review on − off"),
            ("opcalls_on", "opcalls_off", "operator calls on − off"),
            ("pins_on", "pins_off", "task-id pins on − off"),
            ("full40_abl40", "full40_main40", "120-skill pack − 161"),
            ("full40_abl40", "full40_skills161", "120-skill pack − 161 (2nd)"),
            ("topo_adaptive", "topo_linear", "adaptive graph − linear"),
            ("figfloor", "base_a", "figure floor 15 − 3"),
            ("noskills", "base_a", "45 low-read skills withheld"),
            ("full40_skills161", "full40_main40", "PLACEBO: same pack, different code"),
            ("full40_abl40", "full40_a9c2b48", "PLACEBO: same pack, different code"),
            ("base_a", "base_b", "PLACEBO: byte-identical command"),
        ]
        print("\n| one-variable contrast | n | difference | sd |")
        print("|:---|---:|---:|---:|")
        for x, y, label in pairs:
            if x not in data or y not in data:
                continue
            res = paired(data[x], data[y])
            if res is None:
                continue
            n, mean, se, _half, _w, _l = res
            keys = sorted(set(data[x]) & set(data[y]))
            sd = st.stdev([data[x][k] - data[y][k] for k in keys])
            flag = " ✳" if abs(mean) > 2 * se else ""
            print(f"| {label} | {n} | {mean:+.2f} ± {se:.2f}{flag} | {sd:.2f} |")
        print("\n✳ = clears two standard errors. A placebo row is two arms that differ in "
              "nothing that should matter; read the treatments against those, not against zero.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
