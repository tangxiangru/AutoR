#!/usr/bin/env python3
"""Render a campaign's report as the markdown section that goes in the trial log.

Written rather than typed. Every number in `docs/firebench-trial-log.md` before this
existed was copied by hand out of a terminal, which is the one step between a measurement
and a document that nothing checks -- and this repository has already published a table
whose three columns came from three different judge draws because of exactly that.

Reads the `report.json` that `fire_trial.py report` writes and prints a section. It states
the campaign's limits from the plan rather than from prose, because the limits are what
the campaign measured: the first 35-task run's pipeline arm was stopped by
`--max-attempts 2`, not by its wall clock, and a table that does not carry that number
cannot be read correctly a week later.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

METRICS = ("precision", "recall", "f1")


def cell(entry: dict, metric: str, zero: bool = False) -> str:
    block = entry.get(metric) or {}
    key = "mean_unscoreable_as_zero" if zero else "mean"
    sd_key = "sd_unscoreable_as_zero" if zero else "sd"
    if block.get(key) is None:
        return "—"
    sd = block.get(sd_key)
    return f"{block[key]:.1f} ± {sd:.1f}" if sd is not None else f"{block[key]:.1f}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    arms = plan["arms"]
    tasks = plan["tasks"]

    out: list[str] = [f"## {args.title}", ""]
    limits = " · ".join(
        [f"deadline **{plan['deadline_seconds']} s**"]
        + ([" ".join(plan["agent_args"])] if plan.get("agent_args") else ["adapter defaults"])
    )
    out += [f"{len(tasks)} tasks × {len(arms)} arms = {len(plan['cells'])} cells · {limits}", ""]
    if args.note:
        out += [args.note, ""]

    out += ["| arm | scoreable | Prec. | Recall | F1 |", "|:---|---:|---:|---:|---:|"]
    for arm in arms:
        e = report["per_arm"][arm]
        out.append(
            f"| `{arm}` | {e['scored_tasks']}/{e['tasks']} | "
            + " | ".join(cell(e, m) for m in METRICS) + " |"
        )
    out += ["", "Counting an unscoreable run as 0, which is what upstream's scorer does:", "",
            "| arm | Prec. | Recall | F1 |", "|:---|---:|---:|---:|"]
    for arm in arms:
        e = report["per_arm"][arm]
        out.append(f"| `{arm}` | " + " | ".join(cell(e, m, zero=True) for m in METRICS) + " |")

    pairs = []
    if "autor-direct" in arms and "autor-pipeline" in arms:
        for task in tasks:
            a = report["per_task"][task]["autor-direct"].get("f1")
            b = report["per_task"][task]["autor-pipeline"].get("f1")
            if a is not None and b is not None:
                pairs.append(a - b)
    if pairs:
        out += ["", f"`autor-direct − autor-pipeline`: {len(pairs)} complete pairs, median "
                    f"**{statistics.median(pairs):+.1f} F1**, "
                    f"{sum(1 for x in pairs if x > 0)} wins / {sum(1 for x in pairs if x < 0)} "
                    f"losses / {sum(1 for x in pairs if x == 0)} ties."]
    unscored = {arm: report["per_arm"][arm]["unscored_tasks"] for arm in arms}
    for arm, names in unscored.items():
        if names:
            out += ["", f"`{arm}` produced no scoreable conclusion on {len(names)} task(s): "
                        + ", ".join(f"`{n}`" for n in sorted(names)) + "."]
    out.append("")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
