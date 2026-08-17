"""How much of the benchmark asks about a paper the workspace does not contain.

The claim this exists to keep honest, and the reason it is on its third correction.

A task-by-task study reported that "10.0% of total weight sits on 16 criteria where all
three arms score at or below 10" and called it the remaining headroom. A first correction
said it was not headroom at all -- that those criteria name things (`SHAP`, `CAPRI`,
`Qwen2.5-3B`) which live only in the target paper, and that ResearchClawBench does not
ship it. **That correction was wrong, and wrong for a reason worth more than either
claim.** It shelled out to `pdftotext`, which is not installed on the machine it ran on,
and caught the resulting `FileNotFoundError` under `except (OSError, ...)`. Every PDF
silently contributed the empty string, so every term in every paper was "absent", and the
measurement reported 2 of 30 identifiers present.

Read with an extractor that works: **14 of 30**. `SHAP` occurs 17 times in
Neuroscience_000's supplied papers, `CAPRI` 37 times and `HADDOCK3` 25 in
Chemistry_002's. About half of what those criteria name is on disk and was not mined --
that half is headroom. The other half (`FlyWire`, `FAFB`, `NeoAgDT`, `EmbedNet`, `DIDS`)
is not on disk and is the floor.

So the rule this file now enforces, which is the actual finding: **an input this tool
cannot read is not an input that lacks the term.** A missing extractor, an encrypted PDF,
a scanned page -- each of them produces silence, and silence counted as absence is how a
tool tells you what you were already inclined to believe. It refuses to print a verdict
for any task whose PDFs it could not open.

Two other ways this measurement has been wrong, both preserved as guards below: reading
only the top level of two directories undercounted, and recursing the whole workspace
reported 30 of 30 "present" because it was reading `_score.json`, the judge's own output,
which contains the criteria verbatim. A search for a criterion's words in a corpus that
includes the criterion answers yes by construction.

Usage::

    python tools/unreachable_criteria.py --arms <score dirs> --runs <workspace root>
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


def _pdf_text(path: Path) -> str | None:
    """The text of one PDF, or None if this machine cannot read it.

    None and "" are different answers and the difference is the whole point: an empty
    string means the paper contains nothing, and None means we do not know what the paper
    contains. The version of this tool that conflated them reported that a 631,001-word
    corpus containing "SHAP" seventeen times contained it zero times.
    """
    try:
        import pymupdf  # noqa: PLC0415 - optional, and its absence is a reportable state
    except ImportError:
        pymupdf = None
    if pymupdf is not None:
        try:
            with pymupdf.open(path) as document:
                return "\n".join(page.get_text() for page in document)
        except Exception:  # noqa: BLE001 - an unreadable PDF is a state, not a crash
            return None
    try:
        completed = subprocess.run(  # noqa: S603
            ["pdftotext", str(path), "-"],
            capture_output=True, text=True, timeout=120, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout if completed.returncode == 0 else None


def supplied_text(workspace: Path) -> tuple[str, list[str]]:
    """What the benchmark hands the agent, and the files that could not be read.

    Returns the unreadable list rather than swallowing it, so a caller cannot mistake
    "we could not open the papers" for "the papers do not mention it".
    """
    parts: list[str] = []
    unreadable: list[str] = []
    for sub in _SUPPLIED_DIRS:
        for path in sorted((workspace / sub).rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() == ".pdf":
                text = _pdf_text(path)
                if text is None:
                    unreadable.append(path.name)
                else:
                    parts.append(text)
                continue
            if path.suffix.lower() in _TEXT_SUFFIXES:
                try:
                    if path.stat().st_size < _MAX_TEXT_BYTES:
                        parts.append(path.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    unreadable.append(path.name)
    return "\n".join(parts), unreadable


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

    present = absent = refused = 0
    for weight, task, index in hard:
        matches = glob.glob(f"{args.runs}/{task}_*/")
        if not matches:
            continue
        raw, unreadable = supplied_text(Path(matches[0]))
        if unreadable:
            print(f"  w={weight:.2f} {task}#{index}: REFUSING — could not read "
                  f"{len(unreadable)} supplied file(s): {', '.join(unreadable[:3])}. "
                  "An input this tool cannot open is not an input that lacks the term.")
            refused += 1
            continue
        text = raw.lower()
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
    if refused:
        print(f"{refused} criteria not judged: their supplied files could not be read.")
    print("What is present and unscored is headroom nobody mined. What is absent names "
          "something the workspace does not contain, and is the floor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
