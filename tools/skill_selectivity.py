#!/usr/bin/env python3
"""What each task-scoped skill's predicate actually selects, over a corpus of briefs.

A skill that carries `applies_when` is making a claim: *this is the shape of task I
am for*. The claim is checkable, and until it is checked it is a guess about the
model's own reading of a regex. Two ways it goes wrong, and both are silent:

* **Over-selection.** A predicate that matches 30 of 40 briefs is not routing, it
  is an unconditional skill with extra steps — and worse than one, because it also
  costs a description that promises specificity.
* **Under-selection.** A predicate that misses the tasks it was written from is a
  skill nobody will ever be offered. The pack already contains thirteen skills that
  launched zero times in forty runs; a silent predicate is a fourteenth.

So this prints the selection set, and refuses to be satisfied by a plausible-looking
regex. Run it against the corpus you wrote the skill from, before the skill lands:

    python3 tools/skill_selectivity.py --briefs /home/robtang_google_com/RCB/tasks
    python3 tools/skill_selectivity.py --briefs <dir> --expect close-the-gap:Physics_000,Chemistry_003

`--expect` turns the claim into an assertion and exits non-zero when it fails,
which is what makes this runnable from a review rather than read from one.

The corpus is a directory. Each brief is read from whichever it finds first:
`<task>/task_info.json` (the `task` key), `<task>.json` (same), or `<task>.md`/
`<task>.txt` read whole. Nothing about ResearchClawBench is wired in here beyond
the shape of that first file, and a corpus of plain text files works the same way.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.run_skills import discipline_of, read_skill_pack, routing_text  # noqa: E402

#: A predicate matching more of the corpus than this is reported as over-selecting.
#: Not a hard failure: a shape really can be common. It is a number that has to be
#: looked at, which is the point.
WIDE_FRACTION = 0.40


def load_briefs(root: Path) -> dict[str, str]:
    """Every brief under ``root``, keyed by task name, narrowed exactly as the router does.

    Through `routing_text`, which is the same function `task_brief` calls, because
    measuring against anything else reports a selection set the installer does not
    produce. That is not hypothetical: this tool's first version narrowed with
    `research_brief` alone and reported a predicate selecting eight tasks that the
    installer would have selected none of, because `research_brief` drops the
    `Available Data Files` block and the predicate keyed on it.

    Prefer `--from-runs`, which reads real `user_input.txt` files. A corpus of
    `task_info.json` is the *benchmark's* text; a run's `user_input.txt` is what the
    adapter actually built around it, and those are not always the same document.
    """
    briefs: dict[str, str] = {}
    for child in sorted(root.iterdir()):
        text = ""
        name = child.name
        if child.is_dir():
            info = child / "task_info.json"
            if info.is_file():
                try:
                    text = json.loads(info.read_text(encoding="utf-8")).get("task", "")
                except (OSError, ValueError):
                    text = ""
        elif child.suffix == ".json":
            name = child.stem
            try:
                text = json.loads(child.read_text(encoding="utf-8")).get("task", "")
            except (OSError, ValueError):
                text = ""
        elif child.suffix in {".md", ".txt"}:
            name = child.stem
            try:
                text = child.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
        if text:
            briefs[name] = routing_text(text)
    return briefs


def load_run_briefs(root: Path) -> dict[str, str]:
    """The routing text of every real run under ``root``, keyed by task name.

    A run directory is `<task>_<date>_<time>/.autor/<run_id>/user_input.txt`. This is
    the ground truth for what a predicate would have selected, because it is the file
    `task_brief` reads.
    """
    briefs: dict[str, str] = {}
    for user_input in sorted(root.glob("*/.autor/*/user_input.txt")):
        workspace = user_input.parents[2].name
        parts = workspace.rsplit("_", 2)
        task = parts[0] if len(parts) == 3 and parts[1].isdigit() else workspace
        try:
            briefs[task] = routing_text(user_input.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return briefs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--briefs", type=Path, help="directory of task statements")
    source.add_argument(
        "--from-runs",
        type=Path,
        help="directory of run workspaces; reads each run's own user_input.txt, which is "
        "what the installer reads",
    )
    parser.add_argument(
        "--skills", type=Path, default=REPO_ROOT / "src" / "skills", help="skill pack directory"
    )
    parser.add_argument(
        "--expect",
        action="append",
        default=[],
        metavar="SKILL:TASK,TASK",
        help="assert a skill selects exactly these tasks; repeatable; non-zero exit on mismatch",
    )
    parser.add_argument(
        "--all", action="store_true", help="also list the unconditional skills"
    )
    args = parser.parse_args()

    corpus = args.briefs or args.from_runs
    if not corpus.is_dir():
        print(f"no such directory: {corpus}", file=sys.stderr)
        return 2
    briefs = load_briefs(corpus) if args.briefs else load_run_briefs(corpus)
    if not briefs:
        print(f"no briefs found under {corpus}", file=sys.stderr)
        return 2

    entries = read_skill_pack(args.skills)
    scoped = [entry for entry in entries if entry.task_scoped]
    total = len(briefs)

    print(f"{len(entries)} skills, {len(scoped)} task-scoped, over {total} briefs in {corpus}\n")

    selections: dict[str, list[str]] = {}
    for entry in sorted(scoped, key=lambda e: e.name):
        hits = sorted(name for name, brief in briefs.items() if entry.applies_to(brief))
        selections[entry.name] = hits
        share = len(hits) / total
        flag = "  <-- WIDE" if share > WIDE_FRACTION else ("  <-- SELECTS NOTHING" if not hits else "")
        field = discipline_of(entry.name)
        print(f"{entry.name}{'  [' + field + ']' if field else ''}{flag}")
        print(f"  applies_when : {entry.applies_when or '(none)'}")
        if entry.applies_unless:
            print(f"  applies_unless: {entry.applies_unless}")
        print(f"  stages       : {', '.join(sorted(entry.stages)) or '(none)'}")
        print(f"  selects {len(hits)}/{total} ({share:.0%}): {', '.join(hits) or '-'}\n")

    if args.all:
        print("unconditional (offered to every run, subject to the field filter):")
        for entry in sorted(entries, key=lambda e: e.name):
            if not entry.task_scoped:
                print(f"  {entry.name}")
        print()

    # How many skills does each brief pull in? This is the number the routing
    # exists to hold down, and it is the one a reader should check first.
    print("task-scoped skills offered per brief:")
    per_brief = {
        name: sorted(s for s, hits in selections.items() if name in hits) for name in briefs
    }
    for name in sorted(per_brief, key=lambda n: (-len(per_brief[n]), n)):
        got = per_brief[name]
        print(f"  {name:<22} {len(got)}  {', '.join(got) or '-'}")
    counts = [len(v) for v in per_brief.values()]
    print(f"\n  min {min(counts)}  median {sorted(counts)[len(counts) // 2]}  max {max(counts)}")

    failures: list[str] = []
    for spec in args.expect:
        skill, _, wanted_raw = spec.partition(":")
        skill = skill.strip()
        wanted = sorted(t.strip() for t in wanted_raw.split(",") if t.strip())
        if skill not in selections:
            failures.append(f"{skill}: not a task-scoped skill in {args.skills}")
            continue
        got = selections[skill]
        if got != wanted:
            missing = [t for t in wanted if t not in got]
            extra = [t for t in got if t not in wanted]
            failures.append(
                f"{skill}: expected {wanted}, got {got}"
                + (f"; missing {missing}" if missing else "")
                + (f"; extra {extra}" if extra else "")
            )
    if failures:
        print("\nEXPECTATIONS FAILED")
        for line in failures:
            print(f"  {line}")
        return 1
    if args.expect:
        print(f"\n{len(args.expect)} expectation(s) hold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
