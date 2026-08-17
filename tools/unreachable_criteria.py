"""How much of the benchmark asks about a paper the workspace does not contain.

The claim this exists to keep honest. A task-by-task study of the 2026-08-16 arm
reported that "10.0% of total weight sits on 16 criteria where all three arms score at
or below 10" and called it the remaining headroom. It is not headroom. Every one of
those criteria names something specific -- an analysis (SHAP), a dataset (TextVQA), a
model (Qwen2.5-3B), a tool (HADDOCK3), an event (CAPRI round 57) -- and those names are
in the *target paper*, which ResearchClawBench does not ship. `related_work/` holds
other papers: 3.4 million characters of them for Neuroscience_000, containing the string
"SHAP" zero times.

Measured here rather than asserted, because the first two attempts at this measurement
were both wrong in ways that flattered the conclusion. The first read only the top level
of two directories and undercounted. The second recursed and got 30 of 30 identifiers
"present" -- because it was reading `_score.json`, the judge's own output, which contains
the criteria verbatim, and `outputs/`, which the agent wrote. **A search for a criterion's
words that includes the criterion, or anything downstream of it, answers yes by
construction.** Only `related_work/` and `data/` are read here.

Usage::

    python tools/unreachable_criteria.py --arm /path/to/scores --runs /path/to/runs
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

#: A token that identifies a specific thing rather than describing one: an acronym, a
#: model or version string, a CamelCase name. "comparison", "features" and "importance"
#: are in every paper ever written and matching on them is how the second attempt at this
#: got 30 of 30.
_IDENTIFIER = re.compile(
    r"\b(?:[A-Z]{3,}[0-9]*|[A-Za-z]+[0-9][A-Za-z0-9.\-]*|[A-Z][a-z]+[A-Z][A-Za-z]*)\b"
)

#: Acronyms too common to identify anything, plus the judge's own vocabulary.
_GENERIC = frozenset({"AI", "The", "This", "Mode", "ROC", "AUC"})

#: Only what the benchmark hands the agent. Never `outputs/`, `code/` or `report/`, which
#: the run writes; never `_score.json` or `INSTRUCTIONS.md`, which carry the criteria.
_SUPPLIED_DIRS = ("related_work", "data")

_TEXT_SUFFIXES = {".txt", ".md", ".json", ".csv", ".tsv", ".yaml", ".yml", ".html", ".xml"}
_MAX_TEXT_BYTES = 20_000_000

#: Below this, every arm has effectively failed the criterion.
_FLOOR = 10


def supplied_text(workspace: Path) -> str:
    parts: list[str] = []
    for sub in _SUPPLIED_DIRS:
        for path in sorted((workspace / sub).rglob("*")):
            if not path.is_file():
                continue
            try:
                if path.suffix.lower() == ".pdf":
                    parts.append(
                        subprocess.run(  # noqa: S603
                            ["pdftotext", str(path), "-"],
                            capture_output=True, text=True, timeout=120, check=False,
                        ).stdout
                    )
                elif path.suffix.lower() in _TEXT_SUFFIXES and path.stat().st_size < _MAX_TEXT_BYTES:
                    parts.append(path.read_text(encoding="utf-8", errors="replace"))
            except (OSError, subprocess.SubprocessError):
                continue
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arms", nargs="+", required=True, help="score directories, one per arm")
    parser.add_argument("--runs", required=True, help="workspace root of any one arm")
    args = parser.parse_args()

    per_arm = []
    for arm in args.arms:
        per_arm.append({
            os.path.basename(p)[:-5]: json.load(open(p, encoding="utf-8"))
            for p in glob.glob(f"{arm}/*.json")
        })
    tasks = sorted(set.intersection(*(set(a) for a in per_arm)))

    total_weight = sum(i["weight"] for t in tasks for i in per_arm[0][t]["items"])
    hard: list[tuple[float, str, int]] = []
    for task in tasks:
        for index in range(len(per_arm[0][task]["items"])):
            scores = [a[task]["items"][index].get("score") or 0 for a in per_arm]
            if max(scores) <= _FLOOR:
                hard.append((per_arm[0][task]["items"][index]["weight"], task, index))
    hard.sort(reverse=True)

    hard_weight = sum(w for w, _, _ in hard)
    print(f"{len(hard)} criteria no arm scores above {_FLOOR}: "
          f"{hard_weight:.2f} of {total_weight:.1f} weight ({hard_weight / total_weight:.1%})\n")

    present = absent = 0
    for weight, task, index in hard:
        matches = glob.glob(f"{args.runs}/{task}_*/")
        if not matches:
            continue
        text = supplied_text(Path(matches[0])).lower()
        content = per_arm[0][task]["items"][index]["content"]
        terms = [w for w in dict.fromkeys(_IDENTIFIER.findall(content)) if w not in _GENERIC][:8]
        if not terms:
            print(f"  w={weight:.2f} {task}#{index}: names nothing specific enough to look for")
            continue
        missing = [w for w in terms if w.lower() not in text]
        present += len(terms) - len(missing)
        absent += len(missing)
        print(f"  w={weight:.2f} {task}#{index}: supplied text {len(text):,} chars, "
              f"{len(terms) - len(missing)}/{len(terms)} present"
              + (f", absent: {', '.join(missing[:5])}" if missing else ""))

    print(f"\n{present}/{present + absent} of these criteria's distinctive identifiers appear "
          f"anywhere in what the benchmark supplies.")
    print("The rest name things that exist only in the target paper, which is not shipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
