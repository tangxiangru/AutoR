"""How many runs before ``--archive-steer`` is deciding on signal rather than noise?

An instrument, not a test. It walks the *real* :class:`~src.stage_graph.StageGraph`
under synthetic routing policies, feeds the resulting records to the *real*
:func:`~src.archive.edge_payoffs`, and counts how many edges satisfy the real
:meth:`~src.archive.EdgePayoff.believable` after N runs.

Nothing here reimplements the payoff arithmetic. The point is to measure the
shipped code, so every number it prints is a property of ``src/archive.py`` and
``src/stage_graph.py`` as they stand, not of a model of them.

    python3 tools/archive_sample_complexity.py
"""

from __future__ import annotations

import math
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.archive import DEFAULT_MIN_OBSERVATIONS, RunRecord, edge_payoffs  # noqa: E402
from src.rubric import RUBRIC_VERSION  # noqa: E402
from src.stage_graph import (  # noqa: E402
    DEFAULT_MAX_STEPS,
    DEFAULT_MAX_VISITS,
    FINISH,
    StageGraph,
)
from src.utils import STAGES  # noqa: E402


GRAPH = StageGraph.adaptive()
ORDER = {stage.slug: index for index, stage in enumerate(STAGES)}
DECLARED = [f"{edge.source}->{edge.target}" for edge in GRAPH.edges]
KIND = {f"{edge.source}->{edge.target}": edge.kind for edge in GRAPH.edges}
REVISITS = [key for key, kind in KIND.items() if kind == "revisit"]


def replay_cost(key: str) -> int:
    """Steps to get back to the source after taking a backward edge. Derived."""
    source, target = key.split("->", 1)
    if target == FINISH:
        return 0
    return ORDER[source] - ORDER[target] + 1


#: Backward edges that genuinely pay, so the simulation can also be asked whether
#: the archive recovers the right *sign*, not merely enough observations.
TRUE_EFFECT = {"06_analysis->05_experimentation": 0.05, "07_writing->06_analysis": 0.03}


# ---------------------------------------------------------------------------
# The walk
# ---------------------------------------------------------------------------


def walk(rng: random.Random, *, revisit_p: float, weighting: str, abandon_p: float = 0.0):
    """One run over the real topology. Returns (edges taken, stages visited).

    Mirrors the budget rules the shipped ``moves()`` applies -- ``max_visits`` per
    node, ``max_steps`` over the walk -- and assumes every guard passes. That
    assumption is deliberately generous to the archive: a guard that fails removes
    a move from the menu, which can only reduce the number of distinct edges a run
    contributes evidence about.
    """
    current = STAGES[0].slug
    visited = [current]
    edges: dict[str, int] = {}

    while True:
        steps = len(visited)
        out = GRAPH.out_edges(current)

        def live(edge) -> bool:
            if edge.target == FINISH:
                return True
            return visited.count(edge.target) < DEFAULT_MAX_VISITS and steps < DEFAULT_MAX_STEPS

        forward = [e for e in out if e.kind == "advance" and live(e)]
        backward = [e for e in out if e.kind == "revisit" and live(e)]

        if current == "06_analysis" and abandon_p and rng.random() < abandon_p:
            # The conditional terminal preempts every other move at its node.
            edges["06_analysis->finish"] = edges.get("06_analysis->finish", 0) + 1
            return edges, visited

        chosen = None
        if backward and rng.random() < revisit_p:
            if weighting == "uniform":
                chosen = rng.choice(backward)
            else:  # "local": an agent reaches for the nearest correction
                weights = [1.0 / replay_cost(f"{e.source}->{e.target}") for e in backward]
                chosen = rng.choices(backward, weights=weights, k=1)[0]
        elif forward:
            chosen = forward[0]
        elif [e for e in out if e.kind == "finish" and live(e)]:
            chosen = next(e for e in out if e.kind == "finish")

        if chosen is None:
            return edges, visited  # a budget halted the walk

        key = f"{chosen.source}->{chosen.target}"
        edges[key] = edges.get(key, 0) + 1
        if chosen.target == FINISH:
            return edges, visited
        current = chosen.target
        visited.append(current)


def make_record(rng: random.Random, index: int, edges, visited, *, sigma: float = 0.06) -> RunRecord:
    """One archived row. ``sigma`` is the run-to-run spread of a stage score.

    Measured on the only real archive available (568 runs, all fake-operator, so
    all on scripted content): the spread of ``mean_fitness`` across runs is 0.0027
    and the spread of stage scores *within* a run is 0.11. The first is far too
    small to stand in for live runs on different goals and the second is far too
    large, so :func:`precision_sweep` sweeps the range rather than picking one.
    """
    lift = sum(TRUE_EFFECT.get(key, 0.0) for key in edges)
    base = 0.75 + lift
    fitness = {
        slug: max(0.0, min(1.0, rng.gauss(base, sigma))) for slug in dict.fromkeys(visited)
    }
    return RunRecord(
        run_id=f"sim{index}",
        variant_id="baseline",
        rubric_version=RUBRIC_VERSION,
        edges=edges,
        stage_fitness=fitness,
        topology="adaptive",
        provenance="live",
        route="",
        steps=len(visited),
        revisits=sum(v for k, v in edges.items() if KIND.get(k) == "revisit"),
        agent_directed=0,
        recorded_at="t",
    )


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------

POLICIES = {
    "always forward (matches all 513 real runs)": dict(revisit_p=0.00, weighting="uniform"),
    "occasional revisit p=0.05, uniform": dict(revisit_p=0.05, weighting="uniform"),
    "occasional revisit p=0.15, uniform": dict(revisit_p=0.15, weighting="uniform"),
    "agent-chosen p=0.15, prefers cheap": dict(revisit_p=0.15, weighting="local"),
    "heavy explore p=0.30, uniform": dict(revisit_p=0.30, weighting="uniform"),
    "p=0.15 + 5% abandon at 06": dict(revisit_p=0.15, weighting="uniform", abandon_p=0.05),
}

SAMPLE_SIZES = [5, 10, 25, 50, 100, 200, 500, 1000]
REPLICATES = 200
MIN_OBS = DEFAULT_MIN_OBSERVATIONS


def believable_counts(records, min_obs: int = MIN_OBS):
    payoffs = edge_payoffs(records, known_edges=DECLARED)
    ok = {k for k, p in payoffs.items() if p.believable(min_obs)}
    return ok, payoffs


def main() -> None:
    print(f"topology: adaptive, {len(DECLARED)} declared edges "
          f"({len(REVISITS)} revisit, {len(DECLARED) - len(REVISITS)} forward/terminal)")
    print(f"min_observations = {MIN_OBS} (>= {2 * MIN_OBS} runs of contrast per edge)")
    print(f"{REPLICATES} replicates per cell\n")

    for label, kwargs in POLICIES.items():
        print(f"--- {label}")
        print(f"{'N':>6} {'believable (median)':>20} {'of which revisit':>17} "
              f"{'P(>=1)':>8} {'P(all 10 revisit)':>18}")
        for n in SAMPLE_SIZES:
            totals, revisit_totals, any_hit, all_hit = [], [], 0, 0
            for rep in range(REPLICATES):
                rng = random.Random(hash((label, n, rep)) & 0xFFFFFFFF)
                records = [make_record(rng, i, *walk(rng, **kwargs)) for i in range(n)]
                ok, _ = believable_counts(records)
                totals.append(len(ok))
                rv = len(ok & set(REVISITS))
                revisit_totals.append(rv)
                any_hit += bool(ok)
                all_hit += rv == len(REVISITS)
            print(f"{n:>6} {statistics.median(totals):>20.1f} "
                  f"{statistics.median(revisit_totals):>17.1f} "
                  f"{any_hit / REPLICATES:>8.2f} {all_hit / REPLICATES:>18.2f}")
        print()

    # Per-edge detail at the most generous plausible policy.
    print("--- per-edge, heavy explore p=0.30 uniform, N=1000, single replicate")
    rng = random.Random(7)
    records = [make_record(rng, i, *walk(rng, revisit_p=0.30, weighting="uniform"))
               for i in range(1000)]
    ok, payoffs = believable_counts(records)
    print(f"{'edge':47s} {'cost':>4} {'taken':>6} {'skipped':>8} {'delta':>7} {'believable':>11}")
    for key in DECLARED:
        p = payoffs[key]
        print(f"{key:47s} {replay_cost(key):>4} {p.taken_runs:>6} {p.skipped_runs:>8} "
              f"{p.delta:>+7.3f} {'yes' if key in ok else 'no':>11}")

    precision_sweep()


def precision_sweep() -> None:
    """Believable is a count, not a precision. How often is the count wrong?

    ``propose_variant`` acts on ``max(payoffs, key=abs(delta))`` among the
    believable ones -- the order statistic most likely to be the noisiest edge. So
    the number that decides whether steering is signal is not "how many edges are
    believable" but "how often is the one it picks an edge with no true effect".
    """
    from src.archive import DEFAULT_MIN_GAIN

    print(f"\n--- precision: does the edge propose_variant would pick actually pay?")
    print(f"policy p=0.30 uniform; true effect only on "
          f"{', '.join(sorted(TRUE_EFFECT))}; min_gain={DEFAULT_MIN_GAIN}")
    print("sd_run is the run-to-run spread of `mean_fitness`, the quantity min_gain is")
    print("compared against. 0.0027 is the measured value on the real 568-run archive.")
    print(f"{'sd_run':>7} {'N':>6} {'P(propose)':>11} {'P(picks a null edge)':>21} "
          f"{'P(wrong sign|real)':>19}")
    for sd_run in (0.0027, 0.010, 0.020, 0.040, 0.080):
        # mean_fitness averages the eight stage scores, so a per-stage draw of
        # sd_run * sqrt(8) produces a run-level spread of sd_run.
        sigma = sd_run * math.sqrt(len(STAGES))
        for n in (10, 25, 50, 100, 500):
            proposed = null_pick = wrong_sign = 0
            for rep in range(REPLICATES):
                rng = random.Random(hash(("prec", sd_run, n, rep)) & 0xFFFFFFFF)
                records = [
                    make_record(rng, i, *walk(rng, revisit_p=0.30, weighting="uniform"),
                                sigma=sigma)
                    for i in range(n)
                ]
                payoffs = [
                    p for p in edge_payoffs(records, known_edges=DECLARED).values()
                    if p.believable(MIN_OBS) and abs(p.delta) >= DEFAULT_MIN_GAIN
                ]
                if not payoffs:
                    continue
                proposed += 1
                best = max(payoffs, key=lambda item: abs(item.delta))
                truth = TRUE_EFFECT.get(best.edge, 0.0)
                if truth == 0.0:
                    null_pick += 1
                elif (best.delta > 0) != (truth > 0):
                    wrong_sign += 1
            denom = proposed or 1
            print(f"{sd_run:>7.4f} {n:>6} {proposed / REPLICATES:>11.2f} "
                  f"{null_pick / denom:>21.2f} {wrong_sign / denom:>19.2f}")
        print()


if __name__ == "__main__":
    main()
