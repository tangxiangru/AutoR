#!/usr/bin/env python3
"""Report AIRS-Bench arms in the three units the benchmark's own Figure 4 reports.

::

    python tools/airs_report.py --repo ~/airs-bench \\
        --arm autor=/runs/airs/autor/arm_manifest.json \\
        --arm bare=/runs/airs/bare/arm_manifest.json \\
        --side-scores /runs/airs/apps_score.json \\
        --figure /runs/airs/airs_figure.png --json /runs/airs/report.json

Everything here is reproduced from ``notebooks/create_summary_plots.ipynb`` — the code that
drew the published figure — and not from the paper's prose, because the three rules that
change the numbers most are only in the code:

1. **``valid_submission`` is ``status == "SUCCESS"``**, and the headline is its mean. It is a
   metric in its own right, not a footnote, and it is the one that charges an arm for a
   submission the evaluator refused.
2. **``normalize_score_log(...).fillna(0).clip(lower=0)``.** A run with no scoreable
   submission enters the mean as **0** and every task the arm was given stays in the
   denominator. Dropping such a task instead removes an arm's worst outcome from its own
   average — which is what this repository's first AIRS write-up did, and it flattered the
   arm that failed by 0.046.
3. **The notebook's ``aggregate_func`` returns median, IQM *and* mean.** Figure 4 plots the
   mean. On this benchmark they disagree by a factor of more than two, so all three are
   printed and which one is quoted is a decision, not formatting.

**One deliberate deviation, and it is forced.** The notebook derives each task's
``worst_score`` from the runs in the analysis (``scores.min()`` across every agent), so the
anchor moves with the pool. Two arms are not a pool: on a task where both beat SOTA the
observed worst is *better* than SOTA, ``phi(sota) - phi(worst)`` goes negative, and both
arms score 0 on a task they both won. This tool uses the published
``estimated_worst_score`` from ``metadata.yaml`` — the fixed anchor from the 14-agent run
the leaderboard was built on, and the only choice under which a two-arm number means
anything beside it. ``--observed-worst`` runs it the notebook's way, for comparison.

**Elo is computed, and then hedged.** The construction is theirs — inject SOTA as an agent,
one battle per (task, pair, seed × seed), a win to the better score, an invalid submission
loses to a valid one, both-invalid is a tie, then Bradley-Terry with ``SCALE=400`` and
``INIT_RATING=1000``. But Elo is only meaningful *within* a pool, and a pool of two agents
plus SOTA is a re-expression of the head-to-head win count. It is printed with that said,
and it is not comparable to a rating from their fifteen-entity pool.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.airsbench import AirsTask, load_task  # noqa: E402


#: The benchmark's Elo constants, from ``compute_mle_elo``.
ELO_SCALE = 400.0
ELO_INIT_RATING = 1000.0

#: Seeds the notebook gives the injected SOTA "agent" (``[(sota, "SUCCESS")]*10``). It only
#: changes how heavily SOTA's battles weigh, not the ordering.
SOTA_SEEDS = 10

SOTA_LABEL = "SOTA"

#: Strength floor for an agent that won no battle at all, as a fraction of the strongest
#: agent's. Bradley-Terry has no finite maximum for such an agent; see :func:`elo_ratings`.
WINLESS_STRENGTH_FLOOR = 1e-6


# ---------------------------------------------------------------------------
# The three metrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArmMetrics:
    """One arm in the three units of Figure 4, plus the two aggregates it does not plot."""

    arm: str
    tasks: tuple[str, ...]
    #: Per task, in ``tasks`` order, after ``fillna(0).clip(lower=0)``.
    scores: tuple[float, ...]
    #: Per task, whether the run produced a submission the evaluator scored.
    valid: tuple[bool, ...]
    #: Per task, the raw metric value, ``None`` where there was no valid submission.
    values: tuple[float | None, ...]

    @property
    def valid_submission_rate(self) -> float:
        return 100.0 * sum(self.valid) / len(self.valid) if self.valid else 0.0

    @property
    def mean(self) -> float:
        return sum(self.scores) / len(self.scores) if self.scores else 0.0

    @property
    def median(self) -> float:
        ordered = sorted(self.scores)
        if not ordered:
            return 0.0
        middle = len(ordered) // 2
        return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2

    @property
    def iqm(self) -> float:
        """Interquartile mean — the middle half, which one task cannot carry.

        Computed by the notebook beside the mean and not plotted by the figure. On this
        benchmark it is the aggregate that survives `CodeGenerationAPPSPassAt5`, whose
        normalized score has a denominator eleven times smaller than a typical task's.
        """
        ordered = sorted(self.scores)
        if not ordered:
            return 0.0
        cut = len(ordered) // 4
        middle = ordered[cut: len(ordered) - cut] or ordered
        return sum(middle) / len(middle)

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "n_tasks": len(self.tasks),
            "valid_submission_rate": self.valid_submission_rate,
            "mean_normalized_score": self.mean,
            "median_normalized_score": self.median,
            "iqm_normalized_score": self.iqm,
            "per_task": {
                name: {"normalized": score, "value": value, "valid": valid}
                for name, score, value, valid in zip(self.tasks, self.scores, self.values, self.valid)
            },
        }


def arm_metrics(
    arm: str,
    scored: dict[str, tuple[AirsTask, float | None]],
    *,
    worst_override: dict[str, float] | None = None,
) -> ArmMetrics:
    """Aggregate one arm over its tasks. ``None`` is a zero in the mean, not an omission."""
    names = tuple(sorted(scored))
    scores: list[float] = []
    for name in names:
        task, value = scored[name]
        if worst_override is not None and name in worst_override:
            task = _with_worst(task, worst_override[name])
        scores.append(_reported(task, value))
    return ArmMetrics(
        arm=arm,
        tasks=names,
        scores=tuple(scores),
        valid=tuple(scored[name][1] is not None for name in names),
        values=tuple(scored[name][1] for name in names),
    )


def _with_worst(task: AirsTask, worst: float) -> AirsTask:
    from dataclasses import replace

    return replace(task, worst_score=worst)


def _reported(task: AirsTask, value: float | None) -> float:
    """``AirsTask.reported``, but tolerating the degenerate anchor ``--observed-worst`` makes.

    With an observed-worst anchor the denominator can be zero or negative on a task every
    arm won. The notebook would divide by it; this returns 0.0 and the caller is told how
    many tasks it happened on, because a silent 0 there is indistinguishable from an arm
    that scored nothing.
    """
    try:
        return task.reported(value)
    except Exception:  # noqa: BLE001 - a degenerate anchor is a reporting choice, not a crash
        return 0.0


def degenerate_anchor_tasks(tasks: dict[str, AirsTask]) -> list[str]:
    """Tasks whose ``phi(sota) - phi(worst)`` is not positive — the anchor is unusable."""
    broken = []
    for name, task in tasks.items():
        try:
            if task.phi(task.sota_score) - task.phi(task.worst_score) <= 0:
                broken.append(name)
        except (ValueError, OverflowError):
            broken.append(name)
    return sorted(broken)


# ---------------------------------------------------------------------------
# Elo
# ---------------------------------------------------------------------------


def build_battles(
    per_arm: dict[str, dict[str, float | None]],
    tasks: dict[str, AirsTask],
    *,
    sota_seeds: int = SOTA_SEEDS,
) -> dict[tuple[str, str], float]:
    """``(a, b) -> wins of a over b``, ties counted as a half to each side.

    The construction is the notebook's: SOTA is injected as an agent with ``sota_seeds``
    runs at the SOTA score, every unordered pair of agents meets on every task once per
    seed pair, an invalid submission loses to a valid one, and two invalid submissions tie.
    """
    agents = sorted(per_arm) + [SOTA_LABEL]
    wins: dict[tuple[str, str], float] = {}

    def record(a: str, b: str, outcome: float) -> None:
        wins[(a, b)] = wins.get((a, b), 0.0) + outcome
        wins[(b, a)] = wins.get((b, a), 0.0) + (1.0 - outcome)

    for name, task in tasks.items():
        runs: dict[str, list[float | None]] = {
            arm: [per_arm[arm].get(name)] for arm in per_arm if name in per_arm[arm]
        }
        runs[SOTA_LABEL] = [task.sota_score] * sota_seeds
        present = [agent for agent in agents if agent in runs]
        for index, first in enumerate(present):
            for second in present[index + 1:]:
                for left in runs[first]:
                    for right in runs[second]:
                        record(first, second, _outcome(left, right, task.lower_is_better))
    return wins


def _outcome(left: float | None, right: float | None, lower_is_better: bool) -> float:
    """1.0 if *left* wins, 0.0 if it loses, 0.5 for a tie. ``None`` is an invalid run."""
    if left is None and right is None:
        return 0.5
    if left is None:
        return 0.0
    if right is None:
        return 1.0
    if math.isclose(left, right, abs_tol=1e-6):
        return 0.5
    better = left < right if lower_is_better else left > right
    return 1.0 if better else 0.0


def elo_ratings(wins: dict[tuple[str, str], float], *, iterations: int = 10_000) -> dict[str, float]:
    """Bradley-Terry MLE, expressed on the benchmark's Elo scale.

    The notebook fits this with an unpenalised ``LogisticRegression`` on ``+/-log(10)``
    design rows, which is Bradley-Terry with strength ``10 ** (elo / 400)``; solved here by
    minorization-maximization instead, so the tool needs no ``sklearn``. Both are the same
    maximum and both are identified only up to a constant, which is fixed the same way: the
    log-strengths are centred, so the mean rating is ``INIT_RATING``.
    """
    agents = sorted({name for pair in wins for name in pair})
    if len(agents) < 2:
        return {agent: ELO_INIT_RATING for agent in agents}
    strength = {agent: 1.0 for agent in agents}
    totals = {
        (a, b): wins.get((a, b), 0.0) + wins.get((b, a), 0.0)
        for a in agents for b in agents if a != b
    }
    for _ in range(iterations):
        updated = {}
        for a in agents:
            won = sum(wins.get((a, b), 0.0) for b in agents if b != a)
            denominator = sum(
                totals[(a, b)] / (strength[a] + strength[b])
                for b in agents if b != a and totals[(a, b)]
            )
            updated[a] = (won / denominator) if denominator and won else 0.0
        # An agent that won nothing has **no finite maximum**: its strength goes to zero and
        # its rating to minus infinity, which is the correct answer to "how much worse" and
        # a useless one to print. The notebook does not hit this because an unpenalised
        # `LogisticRegression` stops at `tol=1e-6` with a large finite coefficient, so the
        # number it reports for such an agent is its solver's stopping point rather than an
        # estimate. Floored here instead, relative to the strongest agent, so the value is
        # bounded and the ordering is right -- and so that a rating this far down is read as
        # "won nothing" rather than as a measurement.
        ceiling = max(updated.values(), default=1.0) or 1.0
        floor = ceiling * WINLESS_STRENGTH_FLOOR
        updated = {a: max(v, floor) for a, v in updated.items()}
        centre = math.exp(sum(math.log(v) for v in updated.values()) / len(updated))
        moved = max(abs(math.log(updated[a] / centre) - math.log(strength[a])) for a in agents)
        strength = {a: v / centre for a, v in updated.items()}
        if moved < 1e-12:
            break
    return {a: ELO_SCALE * math.log10(strength[a]) + ELO_INIT_RATING for a in agents}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_arm(path: Path) -> tuple[str, dict[str, float | None]]:
    """``(arm name, task -> metric value or None)`` from an arm manifest."""
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    values: dict[str, float | None] = {}
    for run in manifest.get("runs", []):
        values[run["task"]] = run.get("value") if run.get("submission_valid") else None
    return manifest.get("arm", Path(path).parent.name), values


def apply_side_scores(per_arm: dict[str, dict[str, float | None]], path: Path) -> list[str]:
    """Fold in tasks scored outside the arm runner, e.g. APPS under its own interpreter.

    Shape: ``{"<arm>": {"value": ..., ...}}`` for one task named by the file's ``task`` key,
    or ``{"<task>": {"<arm>": {"value": ...}}}``. Returns the task names it touched, so the
    report can say which numbers did not come from the arm's own scoring pass.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    touched: list[str] = []
    task_name = payload.get("task") or "CodeGenerationAPPSPassAt5"
    if all(isinstance(v, dict) and "value" in v for k, v in payload.items() if k != "task"):
        for arm, record in payload.items():
            if arm == "task" or arm not in per_arm:
                continue
            per_arm[arm][task_name] = record.get("value") if record.get("valid") else None
            touched.append(task_name)
    return sorted(set(touched))


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


COMPARABILITY = (
    "AIRS-Bench's published table is a mean over all 20 tasks at 10-20 seeds per agent, "
    "scored in a container with no network. A number from fewer tasks, at one seed, on a "
    "machine where the agent can download a model, is not a point on it."
)


def format_report(
    metrics: list[ArmMetrics],
    elo: dict[str, float],
    *,
    notes: Sequence[str] = (),
) -> str:
    width = max(len(m.arm) for m in metrics) + 2
    lines = [
        f"{'arm'.ljust(width)}{'valid sub %':>12}{'mean':>9}{'median':>9}{'IQM':>9}{'Elo':>9}",
        "-" * (width + 48),
    ]
    for metric in sorted(metrics, key=lambda m: m.mean):
        lines.append(
            f"{metric.arm.ljust(width)}{metric.valid_submission_rate:>11.1f}%"
            f"{metric.mean:>9.3f}{metric.median:>9.3f}{metric.iqm:>9.3f}"
            f"{elo.get(metric.arm, float('nan')):>9.0f}"
        )
    if SOTA_LABEL in elo:
        lines.append(f"{SOTA_LABEL.ljust(width)}{'—':>12}{1.0:>9.3f}{1.0:>9.3f}{1.0:>9.3f}"
                     f"{elo[SOTA_LABEL]:>9.0f}")
    if len(metrics) == 2:
        left, right = metrics
        paired = [b - a for a, b in zip(left.scores, right.scores)]
        won = sum(1 for d in paired if d > 0)
        lines += [
            "",
            f"paired over {len(paired)} task(s): {right.arm} - {left.arm} = "
            f"{sum(paired)/len(paired):+.3f} mean, "
            f"{sorted(paired)[len(paired)//2]:+.3f} median; "
            f"{right.arm} wins {won}, {left.arm} wins {len(paired)-won-paired.count(0)}, "
            f"{paired.count(0)} tie",
        ]
    for note in notes:
        lines += ["", note]
    lines += ["", COMPARABILITY]
    return "\n".join(lines)


def render_figure(
    metrics: list[ArmMetrics],
    path: Path,
    *,
    title: str = "",
    outlier_above: float = 2.0,
) -> Path:
    """Per-task normalized score for each arm, against SOTA at 1.0.

    Deliberately **not** a three-panel reproduction of the published Figure 4. That figure
    carries fifteen agents per panel; here there are two, and three panels of two bars each
    is a table drawn slowly — the summary numbers are printed as a table instead. What has
    enough data to need a picture is the per-task comparison, which is also the only view
    that shows *where* a difference between two arms comes from.

    Any task scoring above *outlier_above* gets its own panel with its own axis. On this
    benchmark that is `CodeGenerationAPPSPassAt5` at 7.4 and 14.2, and drawing it on the
    shared axis compresses the other eighteen into the leftmost twelfth of the plot — the
    first render of this figure did exactly that and was unreadable. Two panels, not two
    x-scales on one panel: a broken or dual scale would misstate the ratio it is hiding.
    """
    import matplotlib  # noqa: PLC0415 - a tool-only dependency

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415

    # Categorical slots 1 and 2 of the documented palette, in fixed order. The first three
    # slots are validated all-pairs in both modes, so a two-series chart is inside the
    # documented case.
    series = ["#2a78d6", "#eb6834"]
    surface, ink, muted, grid, alert = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1", "#e34948"

    names = list(metrics[0].tasks)
    pair_mean = {n: sum(m.scores[i] for m in metrics) / len(metrics)
                 for i, n in enumerate(names)}
    outliers = [n for n in names if pair_mean[n] > outlier_above]
    ordinary = sorted((n for n in names if n not in outliers), key=lambda n: pair_mean[n])
    outliers.sort(key=lambda n: pair_mean[n])

    rows = len(ordinary)
    height = max(4.2, 0.34 * rows + (1.0 if outliers else 0.0) + 2.0)
    ratios = [max(1, len(outliers)), rows] if outliers else [rows]
    label_width = max((len(n) for n in names), default=20)
    figure, axes_list = plt.subplots(
        len(ratios), 1,
        figsize=(6.6 + 0.075 * label_width, height), facecolor=surface,
        gridspec_kw={"height_ratios": ratios}, squeeze=False, layout="constrained",
    )
    figure.get_layout_engine().set(hspace=0.06, h_pad=0.10)
    panels = [ax[0] for ax in axes_list]
    span = 0.38

    def draw(axis, group: list[str], *, headroom: float) -> None:
        axis.set_facecolor(surface)
        for offset, (metric, colour) in enumerate(zip(metrics, series)):
            index = {n: i for i, n in enumerate(metric.tasks)}
            positions = [i + (offset - 0.5) * span for i in range(len(group))]
            values = [metric.scores[index[n]] for n in group]
            axis.barh(positions, values, height=span * 0.9, color=colour,
                      label=metric.arm, zorder=3, linewidth=0)
            # Selective labels only: the runs with no valid submission, which are the rows
            # a reader would otherwise read as "scored badly" rather than "scored nothing".
            for y, n in zip(positions, group):
                if not metric.valid[index[n]]:
                    axis.text(0.012, y, "no valid submission", va="center", ha="left",
                              fontsize=7.5, color=alert, zorder=4, style="italic")
        axis.axvline(1.0, color=ink, linewidth=1.3, linestyle=(0, (4, 3)), zorder=2)
        axis.set_yticks(range(len(group)))
        axis.set_yticklabels(group, fontsize=8, color=ink)
        axis.set_ylim(-0.7, len(group) - 0.3)
        top = max(
            (m.scores[{n: i for i, n in enumerate(m.tasks)}[n]] for m in metrics for n in group),
            default=1.0,
        )
        axis.set_xlim(0, max(headroom, top * 1.08))
        axis.grid(axis="x", color=grid, linewidth=0.8, zorder=0)
        axis.set_axisbelow(True)
        for side in ("top", "right", "left"):
            axis.spines[side].set_visible(False)
        axis.spines["bottom"].set_color(grid)
        axis.tick_params(colors=muted, length=0, labelsize=8)

    if outliers:
        draw(panels[0], outliers, headroom=1.2)
        panels[0].set_title(
            "own axis: this task's normalized-score denominator is ~11x smaller than a "
            "typical task's",
            fontsize=8.5, color=muted, loc="left", pad=5,
        )

    main = panels[-1]
    draw(main, ordinary, headroom=1.25)
    main.text(1.0, len(ordinary) - 0.35, " human SOTA = 1.0", fontsize=8.5, color=ink,
              va="bottom", ha="left")
    main.set_xlabel("normalized score   (AIRS-Bench convention: fillna(0), clip(lower=0))",
                    fontsize=9, color=ink)
    main.legend(frameon=False, loc="lower right", fontsize=9, labelcolor=ink)
    if title:
        figure.suptitle(title, fontsize=11, color=ink, x=0.01, ha="left")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=170, facecolor=surface)
    plt.close(figure)
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="airs_report", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default="airs-bench", metavar="PATH")
    parser.add_argument("--arm", action="append", default=[], metavar="NAME=MANIFEST",
                        help="An arm and its manifest. Repeatable.")
    parser.add_argument("--side-scores", action="append", default=[], metavar="PATH",
                        help="Scores produced outside the arm runner, e.g. APPS under its "
                             "own interpreter. Repeatable.")
    parser.add_argument("--drop-task", action="append", default=[], metavar="NAME",
                        help="Exclude a task from every arm. Reported in the output, "
                             "because a mean over a quietly reduced task set is not the "
                             "benchmark's mean.")
    parser.add_argument("--observed-worst", action="store_true",
                        help="Anchor each task on the worst score observed in THIS analysis, "
                             "the way the notebook does, instead of metadata's published "
                             "estimated_worst_score. Degenerate for a small pool; see the "
                             "module docstring.")
    parser.add_argument("--figure", metavar="PATH", help="Write the per-task figure here.")
    parser.add_argument("--title", default="", help="Figure title.")
    parser.add_argument("--json", metavar="PATH", help="Write the full report as JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if len(args.arm) < 1:
        print("Pass at least one --arm NAME=MANIFEST", file=sys.stderr)
        return 2

    per_arm: dict[str, dict[str, float | None]] = {}
    for spec in args.arm:
        name, _, manifest = spec.partition("=")
        loaded_name, values = load_arm(Path(manifest))
        per_arm[name or loaded_name] = values

    side_tasks: list[str] = []
    for path in args.side_scores:
        side_tasks += apply_side_scores(per_arm, Path(path))

    names = sorted({task for values in per_arm.values() for task in values} - set(args.drop_task))
    tasks = {name: load_task(Path(args.repo), name) for name in names}

    worst_override = None
    if args.observed_worst:
        worst_override = {}
        for name, task in tasks.items():
            observed = [v for values in per_arm.values() if (v := values.get(name)) is not None]
            if observed:
                worst_override[name] = max(observed) if task.lower_is_better else min(observed)

    metrics = [
        arm_metrics(arm, {n: (tasks[n], per_arm[arm].get(n)) for n in names},
                    worst_override=worst_override)
        for arm in sorted(per_arm)
    ]
    elo = elo_ratings(build_battles({a: {n: per_arm[a].get(n) for n in names} for a in per_arm},
                                    tasks))

    notes: list[str] = []
    if args.drop_task:
        notes.append("Excluded from every arm and from the denominator: "
                     + ", ".join(sorted(args.drop_task)))
    if side_tasks:
        notes.append("Scored outside the arm runner: " + ", ".join(side_tasks))
    if args.observed_worst:
        degenerate = degenerate_anchor_tasks(
            {n: _with_worst(tasks[n], worst_override[n]) for n in worst_override}
        )
        notes.append(
            "--observed-worst: the anchor is this analysis's own worst run, so these numbers "
            "are not comparable with the published table."
            + (f" Degenerate on {len(degenerate)} task(s) where every arm beat SOTA: "
               + ", ".join(degenerate) if degenerate else "")
        )
    notes.append(
        "Elo is over a pool of "
        f"{len(per_arm) + 1} entities including SOTA. Elo is only meaningful within a pool; "
        "with two agents it re-expresses the head-to-head win count and is not comparable "
        "to a rating from the published fifteen-entity pool."
    )
    notes.append(
        "No error bars: the published ones are a stratified bootstrap over 10-20 seeds per "
        "task, and these arms have one seed each. A bootstrap over tasks would be a "
        "different quantity and is not drawn as if it were the same one."
    )

    print(format_report(metrics, elo, notes=notes))

    if args.figure:
        written = render_figure(metrics, Path(args.figure), title=args.title)
        print(f"\nfigure -> {written}")
    if args.json:
        payload = {
            "arms": [m.to_dict() for m in metrics],
            "elo": elo,
            "tasks": names,
            "dropped": sorted(args.drop_task),
            "anchor": "observed-worst" if args.observed_worst else "metadata estimated_worst_score",
            "notes": notes,
            "comparability": COMPARABILITY,
        }
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"json   -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
