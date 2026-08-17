"""What a reviewer custody census would have fired on, replayed over finished runs.

``src/review_custody.py`` is a gate, and this repository's rule is to measure a gate's
blast radius before landing it. The population is named rather than globbed, for the
reason ``tools/supervisor_threshold_replay.py`` gives: a fifth run being written into the
same directory would move every number here between one reading and the next, and a
number that moves is not one a design decision can rest on.

WHAT THIS CAN AND CANNOT SEE. An archive retains one modification time per file, so this
replays an **mtime** census. The live census compares content identities, and a file the
reviewer rewrote to the same bytes is not a breach there. Every fire this tool reports is
therefore an upper bound, and the gap between the two is the thing the ledger exists to
measure on a live arm -- it cannot be closed from disk.

RUN IT:

    python3 tools/review_custody_replay.py            # the pinned population
    python3 tools/review_custody_replay.py --root DIR # one run root, ad hoc

WHAT IT PRINTED when the mechanism landed, over MEASURED_RUNS:

    episodes                     138
    fire without the exclusions  138  (100%) -- the list is load-bearing, not decorative
    fire with them                 4  (2.9%), all in Astronomy_000_20260814_175426
    of those, approvals             2  of 27 approvals across the four runs (7.4%)

All four are one behaviour: the reviewer re-running the doer's producer scripts in place
to check they reproduce. Both demoted approvals say so in their own recorded reason. None
of the seven files carries a timestamp field, so a deterministic re-run leaves the bytes
identical and the live content census is silent on all four -- an argument, not a
measurement, and the reason ``--review-custody`` defaults to ``record``.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.provenance import SKIP_DIR_NAMES  # noqa: E402


#: The four finished runs of the first live paired trial, named rather than globbed.
MEASURED_RUNS = (
    "Astronomy_000_20260814_175426",
    "Astronomy_000_20260815_074118",
    "Chemistry_000_20260816_011751",
    "Chemistry_000_20260816_173127",
)
MEASURED_TRIAL_ROOT = Path("/rmeng_data/robtang/rcb-trial-graph/workspaces")

#: What the replay printed when the mechanism landed. Printed beside the live figure so a
#: population that has drifted says so instead of quietly reporting a different number.
MEASURED_EPISODES = 138
MEASURED_FIRES = 4

#: `src/review_custody.churn_files` spelled for an archive, where there is no `RunPaths`
#: to read the names off.
CHURN_FILES = frozenset({"logs.txt", "logs_raw.jsonl"})

_EPISODE = re.compile(r"(?P<slug>\d\d_[a-z_]+)_(?P<label>.+)_attempt_(?P<n>\d+)\.prompt\.md$")


def episodes(root: Path) -> list[tuple[str, int, int]]:
    """(label, window start, window end) per reviewer episode.

    The window is bracketed by two writes the harness already makes: the prompt file,
    written by ``AutomatedReviewer.run_prompt`` immediately before the invocation, and the
    per-call record under ``operator_state/``, written immediately after it returns. No
    instrumentation had to exist for this to be measurable.
    """

    found = []
    for prompt in sorted((root / "prompt_cache").glob("*.prompt.md")):
        match = _EPISODE.match(prompt.name)
        if match is None:
            continue
        label = match.group("label")
        if "review" not in label and "panel" not in label:
            continue
        record = root / "operator_state" / f"{match['slug']}.{label}_attempt_{match['n']}.json"
        if not record.exists():
            continue
        found.append(
            (f"{match['slug']}:{label}:{match['n']}", prompt.stat().st_mtime_ns, record.stat().st_mtime_ns)
        )
    return found


def snapshot(root: Path) -> list[tuple[str, int]]:
    entries = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_DIR_NAMES for part in relative.parts[:-1]):
            continue
        try:
            entries.append((relative.as_posix(), path.stat().st_mtime_ns))
        except OSError:
            continue
    return entries


def replay(root: Path) -> tuple[int, int, int, list[tuple[str, list[str]]]]:
    entries = snapshot(root)
    raw = kept = 0
    hits: list[tuple[str, list[str]]] = []
    found = episodes(root)
    for label, start, end in found:
        moved = [name for name, when in entries if start < when <= end]
        if moved:
            raw += 1
        survivors = [
            name
            for name in moved
            if name not in CHURN_FILES and not name.startswith(("prompt_cache/", "operator_state/"))
        ]
        if survivors:
            kept += 1
            hits.append((label, sorted(survivors)))
    return len(found), raw, kept, hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, action="append", help="A run root to replay instead of the pinned population.")
    args = parser.parse_args()

    if args.root:
        roots = list(args.root)
        pinned = False
    else:
        roots = []
        for name in MEASURED_RUNS:
            matches = sorted((MEASURED_TRIAL_ROOT / name).glob(".autor/*/"))
            if not matches:
                print(f"missing from the pinned population: {name}", file=sys.stderr)
                continue
            roots.append(matches[-1])
        pinned = True

    if not roots:
        print("no run roots to replay", file=sys.stderr)
        return 1

    totals = [0, 0, 0]
    for root in roots:
        count, raw, kept, hits = replay(root)
        totals = [totals[0] + count, totals[1] + raw, totals[2] + kept]
        print(f"{root.parts[-3]:40s} episodes={count:4d} raw={raw:4d} after_exclusions={kept}")
        for label, paths in hits:
            print(f"    {label}: {', '.join(paths)}")

    count, raw, kept = totals
    print(f"\nepisodes {count} | fire without the exclusions {raw} | with them {kept}")
    if pinned:
        if (count, kept) == (MEASURED_EPISODES, MEASURED_FIRES):
            print("population: as recorded")
        else:
            print(
                f"population: DRIFTED -- recorded {MEASURED_EPISODES} episodes and "
                f"{MEASURED_FIRES} fires, read {count} and {kept}. The numbers in "
                "src/review_custody.py and this docstring describe the recorded one."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
