"""Re-derive every number this repo publishes about `deliverable_coverage`.

Why this exists. The criterion was landed twice with numbers in the prose that did not
re-derive: a per-stage trend quoted from its two endpoints and described as monotone when
it is not, a denominator that counted the gainers rather than the population ("89 of 89"
for what is 88 of 118), and a whole replay run with ``artifact_roots`` omitted when the
live path in `src/evolution.py` always passes it. Each was found by someone else reading
the docs against the archive. A hand-typed measurement in prose is a claim with no owner,
so the claims now have a script.

Usage::

    python tools/rubric_replay.py --runs '/path/to/runs/*/.autor/2*'

Prints a block whose every line is quoted somewhere in `docs/framework.md` or
`src/rubric.py`. Nothing here is a benchmark result: it replays a criterion over archived
drafts, which says the criterion has a gradient, not that following it scores better.
"""

from __future__ import annotations

import argparse
import glob
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.deliverables import demanding_sentences, research_brief, task_demands  # noqa: E402
from src.rubric import _demand_terms, score_stage  # noqa: E402
from src.utils import STAGES, build_run_paths, read_text, task_statement  # noqa: E402

#: The stage drafts a replay counts. `.tmp.md` is an attempt mid-flight and
#: `.skip_stub.md` is the manager's placeholder; neither is a draft anyone scored.
_DRAFT_SUFFIX = ".md"
_EXCLUDED = (".tmp.md", ".skip_stub.md")
_MIN_DRAFT_CHARS = 200


def _run_dirs(pattern: str) -> list[Path]:
    return sorted(Path(p) for p in glob.glob(pattern) if Path(p).is_dir())


def _drafts(run_dir: Path):
    """Every accepted stage draft of one run, with the roots the live scorer passes.

    ``artifact_roots`` is not optional. `src/evolution.py` passes it on every real
    scoring call and the benchmark adapter points it at the task workspace, so a replay
    that omits it measures a configuration no run has ever been scored under.
    """
    paths = build_run_paths(run_dir)
    if not paths.user_input.exists():
        return
    workspace = run_dir.parent.parent
    for stage in STAGES:
        draft = run_dir / "stages" / f"{stage.slug}{_DRAFT_SUFFIX}"
        if not draft.exists() or any(draft.name.endswith(bad) for bad in _EXCLUDED):
            continue
        markdown = read_text(draft)
        if len(markdown) < _MIN_DRAFT_CHARS:
            continue
        yield paths, stage, markdown, [workspace]


def _mentioned(paths) -> str | None:
    """One sentence per demand that *mentions* it and grounds nothing: the free half."""
    demands = task_demands(task_statement(read_text(paths.user_input)))
    if not demands:
        return None
    return "\n".join(
        f"Our finding on this point is recorded fully; see detail on {' '.join(sorted(terms)[:4])}."
        for terms in _demand_terms(demands)
    )


def _cited(paths, path: str) -> str | None:
    """The same sentences, citing a path -- the round-2 and round-3 exploits."""
    body = _mentioned(paths)
    if body is None:
        return None
    return "\n".join(f"{line[:-1]} in `{path}`." for line in body.splitlines())


def _invented(paths) -> str | None:
    """The same sentences carrying a number nobody measured -- the round-3 exploit."""
    body = _mentioned(paths)
    if body is None:
        return None
    return "\n".join(f"{line[:-1]}, which gives 74.1% overall." for line in body.splitlines())


def _restated(paths) -> str:
    """A draft that says every demand back and does nothing: the free-half probe."""
    demands = task_demands(task_statement(read_text(paths.user_input)))
    body = "\n".join(
        "We address " + " ".join(sorted(terms)) + " in detail here."
        for terms in _demand_terms(demands)
    )
    return (
        "# S\n\n## Objective\n\nx\n\n## What I Did\n\ny\n\n"
        f"## Key Results\n\n{body}\n\n## Files Produced\n\n- none\n\n"
        "## Decision Ledger\n\n- Open Questions: a\n- Locked Decisions: b\n"
        "- Assumptions: c\n- Rejected Alternatives: d\n\n"
        "## Suggestions for Refinement\n\n1. x\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs",
        default="/rmeng_data/robtang/rcb_runs/full40/*/.autor/2*",
        help="glob matching archived run directories (the ones holding stages/)",
    )
    args = parser.parse_args()

    runs = _run_dirs(args.runs)
    if not runs:
        print(f"no runs matched {args.runs!r}", file=sys.stderr)
        return 1

    demand_counts: list[int] = []
    wide = brief = narrow = 0
    per_stage: dict[str, list[float]] = {}
    new_scores: list[float] = []
    old_totals: list[float] = []
    new_totals: list[float] = []
    restated_scores: list[float] = []
    probe_deltas: dict[str, list[float]] = {}
    probe_full: dict[str, int] = {}
    paste_task_delta: list[float] = []
    paste_shortfall_delta: list[float] = []
    shortfall_population = 0
    headroom_before = headroom_after = 0

    for run_dir in runs:
        paths = build_run_paths(run_dir)
        if paths.user_input.exists():
            statement = task_statement(read_text(paths.user_input))
            wide += len(demanding_sentences(statement))
            brief += len(demanding_sentences(research_brief(statement)))
            demands = task_demands(statement)
            narrow += len(demands)
            demand_counts.append(len(demands))

        for paths, stage, markdown, roots in _drafts(run_dir):
            score = score_stage(
                paths=paths, stage=stage, markdown=markdown, artifact_roots=roots
            )
            coverage = score.by_key.get("deliverable_coverage")
            if coverage is None:
                continue
            others = [c for c in score.criteria if c.key != "deliverable_coverage"]
            old = sum(c.score * c.weight for c in others) / sum(c.weight for c in others)
            per_stage.setdefault(stage.slug, []).append(coverage.score)
            new_scores.append(coverage.score)
            old_totals.append(old)
            new_totals.append(score.total)
            if old >= 1.0 - 1e-9:
                headroom_before += 1
                if score.total < 1.0 - 1e-9:
                    headroom_after += 1

            restated_scores.append(
                score_stage(
                    paths=paths, stage=stage, markdown=_restated(paths), artifact_roots=roots
                ).by_key["deliverable_coverage"].score
            )

            # Every route anyone has found to buy score with prose, priced on the same
            # draft. A route missing from this list is a claim in the docs with no owner.
            probes = {
                "mention only (the documented free half)": _mentioned(paths),
                "  + cite the benchmark's own reference paper": _cited(
                    paths, "workspace/literature/paper_000.pdf"
                ),
                "  + cite AutoR's own experiment manifest": _cited(
                    paths, "workspace/results/experiment_manifest.json"
                ),
                "  + cite a path that merely resolves": _cited(paths, "/etc/hostname"),
                "  + an invented percentage": _invented(paths),
            }
            for label, injection in probes.items():
                if injection is None:
                    continue
                probed = score_stage(
                    paths=paths,
                    stage=stage,
                    markdown=markdown.replace(
                        "## Files Produced", injection + "\n\n## Files Produced", 1
                    ),
                    artifact_roots=roots,
                )
                probe_deltas.setdefault(label, []).append(probed.total - score.total)
                if probed.by_key["deliverable_coverage"].score >= 1.0 - 1e-9:
                    probe_full[label] = probe_full.get(label, 0) + 1

            statement = task_statement(read_text(paths.user_input))
            pasted = markdown.replace("## Files Produced", statement + "\n\n## Files Produced", 1)
            paste_task_delta.append(
                score_stage(paths=paths, stage=stage, markdown=pasted, artifact_roots=roots).total
                - score.total
            )

            if coverage.shortfall:
                shortfall_population += 1
                pasted = markdown.replace(
                    "## Files Produced", coverage.shortfall + "\n\n## Files Produced", 1
                )
                paste_shortfall_delta.append(
                    score_stage(
                        paths=paths, stage=stage, markdown=pasted, artifact_roots=roots
                    ).total
                    - score.total
                )

    def line(label: str, value: str) -> None:
        print(f"{label:<52} {value}")

    print(f"\n{len(runs)} runs, {len(new_scores)} accepted stage drafts, artifact_roots passed\n")
    line("demands: whole statement / brief / clauses", f"{wide} / {brief} / {narrow}")
    line("demands per task: mean / min / max",
         f"{statistics.mean(demand_counts):.2f} / {min(demand_counts)} / {max(demand_counts)}")
    print()
    line("deliverable_coverage mean / sd",
         f"{statistics.mean(new_scores):.4f} / {statistics.pstdev(new_scores):.4f}")
    means = [statistics.mean(per_stage[slug]) for slug in sorted(per_stage)]
    line("  by stage", " ".join(f"{m:.2f}" for m in means))
    line("  monotone non-increasing",
         str(all(means[i] >= means[i + 1] for i in range(len(means) - 1))))
    line("the other criteria: mean / sd / at 1.000",
         f"{statistics.mean(old_totals):.4f} / {statistics.pstdev(old_totals):.4f} / "
         f"{sum(t >= 1.0 - 1e-9 for t in old_totals)}")
    line("drafts at 1.000 before / gaining headroom",
         f"{headroom_before} / {headroom_after}")
    print()
    print("prose probes (a gain here is score bought without doing the work):")
    line("  restated demands, no evidence: mean / max",
         f"{statistics.mean(restated_scores):.4f} / {max(restated_scores):.4f}")
    for label, deltas in probe_deltas.items():
        line(f"  {label}",
             f"median {statistics.median(deltas):+.4f}  max {max(deltas):+.4f}  "
             f"past 0.005: {sum(d > 0.005 for d in deltas)}/{len(deltas)}  "
             f"coverage at 1.000: {probe_full.get(label, 0)}")
    line("  paste the task statement: median total delta",
         f"{statistics.median(paste_task_delta):+.4f}")
    line("  paste the shortfall: median / n moved / n",
         f"{statistics.median(paste_shortfall_delta):+.4f} / "
         f"{sum(abs(d) > 1e-9 for d in paste_shortfall_delta)} / {shortfall_population}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
