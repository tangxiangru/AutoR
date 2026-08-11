"""Learn which moves through the graph actually pay, across runs.

A run that navigates its own topology produces something a linear pipeline never
could: evidence about the topology. Run 12 went back from Stage 06 to Stage 05
because one seed was not enough, and finished at 0.81. Run 13 wrote up the single
seed and finished at 0.62. Neither number means much alone. Forty of them mean the
backward edge out of Stage 06 is worth taking, and that is a fact about the
harness rather than about either run.

This is the Darwin Gödel Machine's arrangement (Zhang et al., arXiv 2505.22954) —
an archive of self-modified variants, empirical validation in place of proof,
parents sampled from the archive rather than only from the incumbent — with the
unit of variation changed. DGM's variants are agent source code. Here they are
**topologies**: an edge set and the order the edges are preferred in. That
substitution is deliberate on three counts.

* A research harness people run on their own machines should not rewrite its own
  Python between runs. A topology is data, it diffs, and it reverts.
* The topology is where the leverage is. Whether the run goes back to Stage 05
  when the analysis is thin matters more than any wording in the prompt.
* A topology can be validated before it is used. An edge priority is a number; a
  rewritten agent is only validated by running it.

**What a learned prior is not allowed to do.** It reorders preferences. It never
opens a guarded edge, never adds an edge that was not declared, and never removes
one. The guards are the correctness argument for letting an agent route at all
(:mod:`src.stage_graph`), and a component that learns from outcomes is exactly the
component that must not be able to weaken them — the cheapest way to raise mean
fitness across an archive would be to stop checking whether hypotheses were
adjudicated before writing up.

**Exploit and explore are separate proposers.** :meth:`Archive.propose_variant`
reads believable payoffs, and a payoff is only believable once runs have both
taken an edge and skipped it. That makes it structurally unable to reach an edge
nothing has taken: no takers, so no evidence either way, so never preferred, so
never taken. The backward edges the graph exists for are the ones that start
unpreferred, so they are the ones the loop strands.
:meth:`Archive.propose_exploration` is the entry into that blind spot — it buys a
trial for one never-taken edge, and nothing more. An explored edge that does not
pay is deprioritised again by the ordinary proposer as soon as its payoff becomes
believable, so exploration cannot ratchet anything in on its own.

**Promotion needs the improvement to replay.** DGM promotes on a benchmark delta.
A rigour score on a research run is noisier than a SWE-bench pass rate, so a
variant here stays unpromoted until it has been observed ``min_observations``
times and still beats the incumbent. Scores from different rubric versions are
never compared at all: a reweighting would otherwise read as every archived run
having improved overnight.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .evolution import load_run_criteria, load_run_fitness
from .router import routing_summary
from .rubric import RUBRIC_VERSION
from .inference import ALPHA, minimum_arms_for
from .stage_graph import REVISIT_EDGES, Edge, StageGraph
from .utils import STAGES, RunPaths, append_jsonl, load_run_config, read_text, write_text


ARCHIVE_VERSION = "1"

#: Observations each side of a comparison needs before it is believed.
#:
#: Derived, not chosen. An exact two-sided permutation test over arms of size *a*
#: and *b* has ``C(a+b, a)`` labellings, so no result can go below ``2/C(a+b,a)``:
#: three a side bottoms out at 0.10, and against a family the size of the adaptive
#: graph's edge set the corrected threshold needs six. The family is computed rather
#: than written down: the graph has grown from eighteen edges to twenty-two since
#: this line was first written, and a hard-coded divisor would have under-corrected
#: silently from the moment an edge was added.
#:
#: The previous value was three, with a docstring saying "three is not enough to be
#: sure and is enough to stop acting on a single lucky run" — a sentence about
#: intent. The archive was licensing topology changes at a sample size where the
#: arithmetic forbids the claim.
DEFAULT_MIN_OBSERVATIONS = minimum_arms_for(ALPHA, family=len(REVISIT_EDGES) + len(STAGES))

#: Mean fitness a challenger must beat the incumbent by. Roughly the size of one
#: criterion moving a quarter of its range on the eight-criterion rubric: the lightest
#: criterion carries 1.5 of 18, so a quarter of its range is 0.25 * 1.5/18 = 0.021.
#: Below that the archive would promote noise.
DEFAULT_MIN_GAIN = 0.02

#: Weight on an unproven variant when sampling a parent. Pure fitness-proportional
#: sampling converges on whatever won first and never revisits the decision, which
#: is the local minimum DGM's archive exists to escape.
NOVELTY_WEIGHT = 0.35


# ----------------------------------------------------------------------------
# Records
# ----------------------------------------------------------------------------


def comparability_basis(
    topology: str, rubric_version: str, stage_fitness: "Mapping[str, float]"
) -> str:
    """The key two runs must share before their fitness may be compared at all.

    A stage's score is a weighted mean over the criteria that apply to it, and the
    late stages face more of them: Stage 02 is scored on five criteria worth 11,
    Stage 06 on eight worth 18, including `numeric_fidelity`, which is the hardest.
    So the *set of stages a run reached* is a free parameter of the objective. On a
    scripted `--fake-operator` run the difference is not subtle — mean fitness over
    stages 01-02 is 0.973 against 0.817 over all eight, a gap nearly eight times the
    margin a promotion needs.

    Left alone, that makes "stop early" the cheapest available improvement, and the
    archive would find it: a topology variant whose runs halt at Stage 03 would be
    measured as a large gain and promoted for it. Encoding the composition in the
    comparison key is the fix, and it is the same rule the archive already applies
    to rubric versions — two numbers that do not measure the same thing are not two
    measurements of one thing.
    """
    return f"{topology or 'unknown'}|v{rubric_version}|" + "-".join(sorted(stage_fitness))


@dataclass(frozen=True)
class TrialTag:
    """Identifies one arm of a paired trial.

    All three are required together. A ``trial_id`` with no ``capability`` cannot be
    grouped with anything, and an ``arm`` with no ``trial_id`` is a label on a run
    nobody can pair — both would look like data and be none.
    """

    trial_id: str
    capability: str
    arm: str

    @classmethod
    def build(cls, trial_id: str, capability: str, arm: str) -> "TrialTag":
        values = {"--trial": trial_id, "--capability": capability, "--arm": arm}
        missing = [flag for flag, value in values.items() if not str(value or "").strip()]
        if missing:
            raise ValueError(
                "A paired trial needs all of --trial, --capability and --arm; missing "
                + ", ".join(missing)
                + ". A run tagged with only some of them cannot be paired with anything."
            )
        return cls(trial_id.strip(), capability.strip(), arm.strip())


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    variant_id: str
    rubric_version: str
    #: ``source->target`` counted once per traversal. A run that took an edge twice
    #: is two observations of it, which is what the payoff arithmetic wants.
    edges: dict[str, int]
    stage_fitness: dict[str, float]
    #: The topology this run walked. Part of the basis: a linear run never had the
    #: revisit edges, so counting it as a run that "reached the node and declined"
    #: puts a run that was never offered the choice into the control arm. Measured,
    #: that flips the sign — three adaptive runs taking `06->05` at 0.60 against
    #: three declining at 0.70 reads as +0.100 once six linear runs at 0.40 are
    #: pooled in, when the answer is -0.100.
    topology: str
    #: ``live`` or ``fake``. A fake operator emits scripted drafts, so its scores
    #: measure the script. Recorded rather than dropped — a fake run is the only
    #: end-to-end exercise of the ``RunPaths -> RunRecord`` seam — but never pooled
    #: into an estimate.
    provenance: str
    route: str
    steps: int
    revisits: int
    agent_directed: int
    #: Moves that never went through the router. Not in :attr:`edges` — they are not
    #: edge observations — but carried so a reader can see the route was longer than
    #: the traversals the estimator counted.
    bypassed: int
    recorded_at: str
    #: Every routing decision, with the set it was chosen from. The unit the
    #: `offered and declined` estimator works on — `edges` alone cannot say whether
    #: a move was declined or was never on offer, and those are different
    #: observations. See :mod:`src.decisions`.
    decisions: "list[dict[str, object]]" = field(default_factory=list)
    #: Mean score per rubric criterion. Not used for ranking — the total is — but a
    #: difference between two configurations is uninterpretable without it: writing
    #: more files and grounding more claims move the same total and are not the same
    #: result. See :mod:`src.trials`.
    #:
    #: Defaulted, unlike `provenance`. An empty decomposition is the honest reading
    #: of a record written before it existed; an empty provenance is not "live".
    criterion_fitness: dict[str, float] = field(default_factory=dict)
    #: Set when this run is one arm of a paired trial. Empty otherwise. The pairing
    #: is what removes goal difficulty — the confound that makes the observational
    #: estimator need more runs than anyone will do.
    trial_id: str = ""
    #: What the trial is testing, e.g. `effort_tiers`. Runs pair only within one.
    capability: str = ""
    #: Which side of the pair, e.g. `off` / `on`.
    arm: str = ""

    @property
    def mean_fitness(self) -> float:
        """Mean champion score across the stages this run actually measured.

        Averaged over measured stages rather than over all eight: a run stopped at
        Stage 07 by ``--final-stage`` did not fail Stage 08, and counting an absent
        stage as a zero would make every partial run look like a bad topology.

        The consequence is that this number is only meaningful *within* a
        :func:`comparability_basis`. Nothing here may be compared against a run that
        measured a different set of stages, and every consumer below goes through
        :attr:`basis` to make sure it is not.
        """
        if not self.stage_fitness:
            return 0.0
        return sum(self.stage_fitness.values()) / len(self.stage_fitness)

    @property
    def basis(self) -> str:
        return comparability_basis(self.topology, self.rubric_version, self.stage_fitness)

    @property
    def usable(self) -> bool:
        """Whether this row may enter an estimate."""
        return self.rubric_version == RUBRIC_VERSION and self.provenance == "live"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "variant_id": self.variant_id,
            "rubric_version": self.rubric_version,
            "edges": dict(self.edges),
            "stage_fitness": dict(self.stage_fitness),
            "criterion_fitness": dict(self.criterion_fitness),
            "trial_id": self.trial_id,
            "capability": self.capability,
            "arm": self.arm,
            "topology": self.topology,
            "provenance": self.provenance,
            "mean_fitness": round(self.mean_fitness, 4),
            "route": self.route,
            "steps": self.steps,
            "revisits": self.revisits,
            "agent_directed": self.agent_directed,
            "bypassed": self.bypassed,
            "decisions": [dict(item) for item in self.decisions],
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RunRecord":
        return cls(
            run_id=str(payload.get("run_id") or ""),
            variant_id=str(payload.get("variant_id") or ""),
            rubric_version=str(payload.get("rubric_version") or ""),
            edges={str(k): int(v) for k, v in (payload.get("edges") or {}).items()},
            stage_fitness={
                str(k): float(v)
                for k, v in (payload.get("stage_fitness") or {}).items()
                if isinstance(v, (int, float))
            },
            # A row written before these existed knows neither, and must not be
            # assumed into either: an unknown topology forms its own basis, and an
            # unknown provenance is not `live`.
            criterion_fitness={
                str(k): float(v)
                for k, v in (payload.get("criterion_fitness") or {}).items()
                if isinstance(v, (int, float))
            },
            trial_id=str(payload.get("trial_id") or ""),
            capability=str(payload.get("capability") or ""),
            arm=str(payload.get("arm") or ""),
            topology=str(payload.get("topology") or ""),
            provenance=str(payload.get("provenance") or "unknown"),
            route=str(payload.get("route") or ""),
            steps=int(payload.get("steps") or 0),
            revisits=int(payload.get("revisits") or 0),
            agent_directed=int(payload.get("agent_directed") or 0),
            bypassed=int(payload.get("bypassed") or 0),
            decisions=[dict(item) for item in payload.get("decisions", []) if isinstance(item, dict)],
            recorded_at=str(payload.get("recorded_at") or ""),
        )


@dataclass(frozen=True)
class Variant:
    """A topology in the archive: which edges, and in what order they are preferred."""

    variant_id: str
    #: The built-in topology this variant is a modification of.
    topology: str
    #: ``source->target`` to priority. Absent edges keep the built-in priority.
    edge_priority: dict[str, int] = field(default_factory=dict)
    parent_id: str = ""
    generation: int = 0
    #: Why this variant was proposed, in one sentence, from the payoff that
    #: suggested it. An archive of unexplained numbers is not something anyone will
    #: act on, and a promotion nobody can justify is one nobody can withdraw.
    note: str = ""
    promoted: bool = False
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "topology": self.topology,
            "edge_priority": dict(self.edge_priority),
            "parent_id": self.parent_id,
            "generation": self.generation,
            "note": self.note,
            "promoted": self.promoted,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Variant":
        return cls(
            variant_id=str(payload.get("variant_id") or ""),
            topology=str(payload.get("topology") or "adaptive"),
            edge_priority={
                str(k): int(v) for k, v in (payload.get("edge_priority") or {}).items()
            },
            parent_id=str(payload.get("parent_id") or ""),
            generation=int(payload.get("generation") or 0),
            note=str(payload.get("note") or ""),
            promoted=bool(payload.get("promoted")),
            created_at=str(payload.get("created_at") or ""),
        )

    def apply_to(self, graph: StageGraph) -> StageGraph:
        """A copy of ``graph`` with this variant's priorities substituted in.

        Only the priority changes. Edges the variant does not mention keep theirs,
        edges it mentions that the graph does not have are ignored, and no guard is
        touched — a variant cannot open a door, only prefer one that is already open.
        """
        rebuilt: list[Edge] = []
        for edge in graph.edges:
            key = f"{edge.source}->{edge.target}"
            priority = self.edge_priority.get(key, edge.priority)
            rebuilt.append(
                Edge(
                    source=edge.source,
                    target=edge.target,
                    kind=edge.kind,
                    rationale=edge.rationale,
                    guard=edge.guard,
                    priority=priority,
                )
            )
        return StageGraph(rebuilt, name=graph.name)


BASELINE_VARIANT = Variant(
    variant_id="baseline",
    topology="adaptive",
    note="The declared topology with its hand-set priorities.",
    promoted=True,
)


# ----------------------------------------------------------------------------
# Payoff
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class EdgePayoff:
    edge: str
    taken_runs: int
    skipped_runs: int
    taken_mean: float
    skipped_mean: float

    @property
    def delta(self) -> float:
        return self.taken_mean - self.skipped_mean

    def believable(self, min_observations: int) -> bool:
        return self.taken_runs >= min_observations and self.skipped_runs >= min_observations

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge": self.edge,
            "taken_runs": self.taken_runs,
            "skipped_runs": self.skipped_runs,
            "taken_mean": round(self.taken_mean, 4),
            "skipped_mean": round(self.skipped_mean, 4),
            "delta": round(self.delta, 4),
        }


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def edge_payoffs(
    records: Iterable[RunRecord],
    known_edges: Iterable[str] | None = None,
) -> dict[str, EdgePayoff]:
    """For each edge, runs that took it against runs that were at the same node and did not.

    The comparison is against *runs that reached the source*, not against every run
    in the archive. Comparing "took 06→05" against the whole archive would credit
    the edge with the difference between runs that got as far as Stage 06 and runs
    that did not, which has nothing to do with the edge.

    ``known_edges`` is the topology's declared edge set. Without it the candidate
    edges are only those some run already took, so an edge nothing has ever taken
    is not merely unbelievable — it is invisible, and cannot be reasoned about at
    all. Passing the declared set makes it appear with ``taken_runs == 0``, which
    is what :meth:`Archive.unexplored_edges` needs in order to notice it.
    """
    usable = [record for record in records if record.usable]
    payoffs: dict[str, EdgePayoff] = {}

    edges = {edge for record in usable for edge in record.edges} | set(known_edges or ())
    for edge in sorted(edges):
        source = edge.split("->", 1)[0]
        reached = [
            record
            for record in usable
            if any(key.split("->", 1)[0] == source for key in record.edges)
        ]
        # Compare within a basis, then pool the per-basis contrasts. Pooling the raw
        # means instead would let the *composition* of each arm supply the delta: an
        # arm of runs that stopped at Stage 03 is scored on the easy criteria only,
        # and would beat an arm of runs that finished for a reason that has nothing
        # to do with the edge.
        bases = {record.basis for record in reached}
        taken_means: list[float] = []
        skipped_means: list[float] = []
        taken_runs = skipped_runs = 0
        for basis in sorted(bases):
            arm = [record for record in reached if record.basis == basis]
            taken = [record.mean_fitness for record in arm if edge in record.edges]
            skipped = [record.mean_fitness for record in arm if edge not in record.edges]
            if not taken or not skipped:
                # A basis with only one arm carries no contrast. Counting its runs
                # would inflate the observation count that decides believability
                # without contributing anything to the delta.
                continue
            taken_runs += len(taken)
            skipped_runs += len(skipped)
            taken_means.append(_mean(taken))
            skipped_means.append(_mean(skipped))
        payoffs[edge] = EdgePayoff(
            edge, taken_runs, skipped_runs, _mean(taken_means), _mean(skipped_means)
        )
    return payoffs


# ----------------------------------------------------------------------------
# The archive
# ----------------------------------------------------------------------------


class Archive:
    """Runs, variants, and the arithmetic that turns the first into the second."""

    def __init__(
        self,
        root: Path,
        *,
        min_observations: int = DEFAULT_MIN_OBSERVATIONS,
        min_gain: float = DEFAULT_MIN_GAIN,
    ) -> None:
        self.root = Path(root)
        self.min_observations = min_observations
        self.min_gain = min_gain

    # -- storage -------------------------------------------------------------

    @property
    def runs_file(self) -> Path:
        return self.root / "runs.jsonl"

    @property
    def variants_file(self) -> Path:
        return self.root / "variants.json"

    def runs(self) -> list[RunRecord]:
        if not self.runs_file.exists():
            return []
        records: list[RunRecord] = []
        for line in read_text(self.runs_file).splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                # One malformed line is not a reason to lose the archive. It is a
                # reason not to pretend the archive is complete, which is why the
                # count is what every believability test is against.
                continue
            if isinstance(payload, dict):
                records.append(RunRecord.from_dict(payload))

        # One row per run, keeping the last.
        #
        # `record_into_archive` fires on both the fresh and the resume path, and the
        # run id is the run directory's name, so a resumed run is recorded twice and
        # a twice-resumed run three times. Duplicates are free observations: they
        # push `taken_runs` and `skipped_runs` past `min_observations` without any
        # new evidence, which is the one number standing between a coincidence and a
        # topology change. No archive is vendored here, so the ratio is not a fixed
        # figure to quote — measure your own with
        # ``wc -l runs.jsonl`` against the count of distinct ``run_id`` values.
        deduped: dict[str, RunRecord] = {}
        for record in records:
            deduped[record.run_id] = record
        return list(deduped.values())

    def variants(self) -> list[Variant]:
        if not self.variants_file.exists():
            return [BASELINE_VARIANT]
        try:
            payload = json.loads(read_text(self.variants_file))
        except json.JSONDecodeError:
            return [BASELINE_VARIANT]
        stored = [
            Variant.from_dict(item)
            for item in (payload if isinstance(payload, list) else [])
            if isinstance(item, Mapping)
        ]
        if not any(item.variant_id == BASELINE_VARIANT.variant_id for item in stored):
            stored.insert(0, BASELINE_VARIANT)
        return stored

    def variant(self, variant_id: str) -> Variant | None:
        return next((item for item in self.variants() if item.variant_id == variant_id), None)

    def _save_variants(self, variants: Sequence[Variant]) -> None:
        write_text(
            self.variants_file,
            json.dumps([item.to_dict() for item in variants], indent=2, ensure_ascii=False),
        )

    # -- recording -----------------------------------------------------------

    def record_run(
        self,
        paths: RunPaths,
        *,
        variant_id: str = "baseline",
        provenance: str = "live",
        trial: "TrialTag | None" = None,
    ) -> RunRecord | None:
        """Append a finished run's route and fitness. Returns ``None`` if unmeasured.

        A run with no evolution summary contributes nothing: without per-stage
        scores there is no fitness, and a record carrying a route but no outcome
        would be counted in the denominator of every payoff it appears in while
        adding no information to the numerator.
        """
        fitness = load_run_fitness(paths)
        if not fitness:
            return None
        summary = routing_summary(paths)
        record = RunRecord(
            run_id=paths.run_root.name,
            variant_id=variant_id,
            rubric_version=RUBRIC_VERSION,
            edges={str(k): int(v) for k, v in (summary.get("edges") or {}).items()},
            stage_fitness=fitness,
            criterion_fitness=load_run_criteria(paths),
            trial_id=trial.trial_id if trial else "",
            capability=trial.capability if trial else "",
            arm=trial.arm if trial else "",
            topology=str(load_run_config(paths).get("stage_graph") or ""),
            provenance=provenance,
            route=str(summary.get("route") or ""),
            steps=int(summary.get("steps") or 0),
            revisits=int(summary.get("revisits") or 0),
            agent_directed=int(summary.get("agent_directed") or 0),
            bypassed=int(summary.get("bypassed") or 0),
            decisions=list(summary.get("decisions") or []),
            recorded_at=_now(),
        )
        append_jsonl(self.runs_file, record.to_dict())
        return record

    # -- selection -----------------------------------------------------------

    def variant_fitness(self) -> dict[str, tuple[int, float]]:
        """Observation count and mean fitness per variant, current rubric only."""
        buckets: dict[str, list[float]] = {}
        for record in self.runs():
            if not record.usable:
                continue
            buckets.setdefault(record.variant_id, []).append(record.mean_fitness)
        return {key: (len(values), _mean(values)) for key, values in buckets.items()}

    def variant_fitness_by_basis(self) -> dict[str, dict[str, tuple[int, float]]]:
        """Per-variant fitness, kept separate by comparability basis."""
        buckets: dict[str, dict[str, list[float]]] = {}
        for record in self.runs():
            if not record.usable:
                continue
            buckets.setdefault(record.basis, {}).setdefault(record.variant_id, []).append(
                record.mean_fitness
            )
        return {
            basis: {key: (len(values), _mean(values)) for key, values in per_variant.items()}
            for basis, per_variant in buckets.items()
        }

    def incumbent(self) -> Variant:
        """The promoted variant that beats the baseline by the most, within a basis.

        Ranking promoted variants by a pooled mean would reintroduce, one function
        along, the confounding :func:`comparability_basis` exists to remove — and it
        matters more here than it looks, because the incumbent is both the parent
        :meth:`propose_variant` mutates and the comparison target inside
        :meth:`promote`. A basis-matched head-to-head against an incumbent chosen by
        a composition-confounded mean is a matched test with an unmatched control.
        """
        promoted = [item for item in self.variants() if item.promoted]
        if not promoted:
            return BASELINE_VARIANT
        by_basis = self.variant_fitness_by_basis()

        def margin(variant: Variant) -> float:
            margins = [
                per[variant.variant_id][1] - per[BASELINE_VARIANT.variant_id][1]
                for per in by_basis.values()
                if variant.variant_id in per and BASELINE_VARIANT.variant_id in per
            ]
            return _mean(margins) if margins else 0.0

        return max(promoted, key=lambda item: (margin(item), item.generation))

    def sample_parent(self, *, seed: int | None = None) -> Variant:
        """Pick a variant to run next: mostly the good ones, sometimes an unproven one.

        Fitness-proportional alone would lock the archive onto whichever variant
        won early, and stop generating the observations that would show a different
        one is better. The novelty term is what keeps under-sampled variants in the
        draw. Seeded from the archive size so the choice is reproducible from the
        archive itself rather than from the wall clock.
        """
        variants = self.variants()
        if len(variants) == 1:
            return variants[0]
        fitness = self.variant_fitness()
        weights: list[float] = []
        for item in variants:
            observations, mean = fitness.get(item.variant_id, (0, 0.0))
            novelty = NOVELTY_WEIGHT / (1.0 + observations)
            weights.append(max(mean, 0.0) + novelty)
        rng = random.Random(len(self.runs()) if seed is None else seed)
        return rng.choices(variants, weights=weights, k=1)[0]

    # -- variation -----------------------------------------------------------

    def propose_variant(self, *, graph: StageGraph | None = None) -> Variant | None:
        """Derive a child of the incumbent from an edge payoff that is believable.

        Returns ``None`` when nothing in the archive supports a change, which is the
        common answer and the right one. A proposer that always proposes converts an
        archive into a random walk.
        """
        # The `offered and declined` contrast, not the run-level one. The old
        # control arm pooled "the guard was shut", "--final-stage pruned it", "the
        # visit budget was spent" and "this topology has no such edge" into one
        # group, and only the absence of a *choice* is evidence about a choice.
        # `edge_payoffs` is still computed and still printed by `report`, under a
        # heading saying it is unadjusted — an operator should be able to see the
        # two estimators disagree rather than have the conclusion change silently.
        from .decisions import decisions_from, offered_payoffs

        contrasts = offered_payoffs(decisions_from(self.runs()))
        family = max(len(contrasts), 1)
        payoffs = [
            payoff
            for payoff in contrasts.values()
            if payoff.test.believable(family=family) and abs(payoff.delta) >= self.min_gain
        ]
        if not payoffs:
            return None

        parent = self.incumbent()
        best = max(payoffs, key=lambda item: abs(item.delta))
        base_graph = graph or StageGraph.named(parent.topology)
        source, target = best.edge.split("->", 1)
        current = next(
            (
                edge.priority
                for edge in base_graph.edges
                if edge.source == source and edge.target == target
            ),
            None,
        )
        if current is None:
            return None

        # Preferred one step more, or one step less. A single step keeps the change
        # attributable: a variant that reshuffles five edges at once cannot be told
        # apart from a variant that got lucky on one of them.
        adjusted = max(0, current - 1) if best.delta > 0 else current + 1
        if adjusted == current:
            return None

        priorities = dict(parent.edge_priority)
        priorities[best.edge] = adjusted
        if priorities == parent.edge_priority:
            return None

        direction = "preferred" if best.delta > 0 else "deprioritised"
        variant = Variant(
            variant_id=_variant_id(parent, best.edge, adjusted),
            topology=parent.topology,
            edge_priority=priorities,
            parent_id=parent.variant_id,
            generation=parent.generation + 1,
            note=(
                f"`{best.edge}` {direction}: decisions that took it averaged "
                f"{best.taken_mean:.3f} over {best.taken_n} against "
                f"{best.declined_mean:.3f} over {best.declined_n} that were offered it and "
                f"declined ({best.delta:+.3f}; {best.test.describe(family=family)})."
            ),
            promoted=False,
            created_at=_now(),
        )
        existing = self.variants()
        if any(item.variant_id == variant.variant_id for item in existing):
            return None
        self._save_variants([*existing, variant])
        return variant

    def unexplored_edges(self, graph: StageGraph) -> list[str]:
        """Declared edges no archived run has ever taken, in priority order.

        These are the archive's blind spot. :func:`edge_payoffs` compares runs that
        took an edge against runs that did not, so an edge with no takers yields no
        evidence in either direction, and :meth:`propose_variant` — which only reads
        believable payoffs — can never reach it. Left alone the arrangement is a
        closed loop: never taken, so never evidenced, so never preferred, so never
        taken. The backward edges the graph exists for are exactly the ones that
        start unpreferred, so exactly the ones the loop strands.
        """
        declared = [f"{edge.source}->{edge.target}" for edge in graph.edges]
        taken = {edge for record in self.runs() for edge in record.edges}
        by_priority = {f"{edge.source}->{edge.target}": edge.priority for edge in graph.edges}
        return sorted(
            (edge for edge in declared if edge not in taken),
            key=lambda edge: (by_priority.get(edge, 0), edge),
        )

    def propose_exploration(self, *, graph: StageGraph | None = None) -> Variant | None:
        """Derive a child that makes one never-taken edge preferable enough to try.

        The counterpart to :meth:`propose_variant`. That one exploits evidence; this
        one is how the evidence comes to exist. Both produce the same kind of
        ``Variant``, promoted on the same replay conditions, so exploration buys a
        trial and never a conclusion — an explored edge that does not pay is
        deprioritised again by the ordinary proposer once its payoff is believable.

        Deliberately conservative:

        * **One edge, one step.** Same attributability rule the exploit proposer
          follows. A variant that opens three unexplored edges at once cannot be told
          apart from one that got lucky on a single edge.
        * **Only when the archive is worth trusting.** With fewer than
          ``min_observations`` runs the incumbent is barely evidenced either, and
          deviating from it is noise rather than exploration.
        * **Never a guard.** It moves a priority. An edge whose guard fails stays
          inadmissible and is never taken however preferred it is, which is what
          keeps the correctness argument in :mod:`src.stage_graph` intact.
        """
        parent = self.incumbent()
        base_graph = graph or StageGraph.named(parent.topology)
        if len(self.runs()) < self.min_observations:
            return None

        # Priority 0 is already the default move out of its node. An edge that
        # preferred and still untaken is not waiting on the prior — its guard is
        # closed, or the node is never reached — and nudging it changes nothing.
        # So exploration only has something to offer edges that lost the ordering.
        by_priority = {f"{e.source}->{e.target}": e.priority for e in base_graph.edges}

        # An edge with no rival is not explorable. Preferring it changes nothing: a
        # run reaching that node was going to take it anyway. `linear` is the case
        # that makes this concrete — every node has exactly one way onward, so no
        # reordering there can send a run anywhere it was not already going, and a
        # proposal saying otherwise would buy a variant for a trial that cannot run.
        #
        # Terminals do not count as rivals. `06_analysis->finish` is live only when
        # the round concluded the question cannot be answered, and in that case it is
        # the only live forward move, so its priority relative to the writing edge
        # decides nothing either.
        rivals: dict[str, int] = {}
        for edge in base_graph.edges:
            if edge.kind in {"advance", "revisit"}:
                rivals[edge.source] = rivals.get(edge.source, 0) + 1
        candidates = [
            edge
            for edge in self.unexplored_edges(base_graph)
            if by_priority.get(edge, 0) > 0 and rivals.get(edge.split("->", 1)[0], 0) > 1
        ]
        if not candidates:
            return None

        edge_key = candidates[0]
        source, target = edge_key.split("->", 1)
        current = by_priority[edge_key]

        priorities = dict(parent.edge_priority)
        priorities[edge_key] = max(0, current - 1)
        if priorities == parent.edge_priority:
            return None

        variant = Variant(
            variant_id=_variant_id(parent, edge_key, priorities[edge_key]),
            topology=parent.topology,
            edge_priority=priorities,
            parent_id=parent.variant_id,
            generation=parent.generation + 1,
            note=(
                f"`{edge_key}` preferred one step to explore it: no archived run has "
                f"taken it, so it has no payoff in either direction and the ordinary "
                f"proposer cannot reach it. Exploratory — it buys a trial, not a verdict."
            ),
            promoted=False,
            created_at=_now(),
        )
        existing = self.variants()
        if any(item.variant_id == variant.variant_id for item in existing):
            return None
        self._save_variants([*existing, variant])
        return variant

    def promote(self, variant_id: str) -> bool:
        """Mark a variant promoted, if the evidence for it has replayed.

        Two independent conditions, and the observation count is the one that does
        the work: a challenger that beat the incumbent once beat it once.
        """
        challenger = self.variant(variant_id)
        if challenger is None or challenger.promoted:
            return False
        incumbent = self.incumbent()
        if incumbent.variant_id == variant_id:
            return False

        # Head-to-head within each basis, then require the challenger to have won
        # enough of them. Comparing pooled means would let the challenger win by
        # having been run on easier compositions — and "runs that stopped early" is
        # the easiest composition there is, which makes it the cheapest thing for a
        # topology to learn.
        by_basis = self.variant_fitness_by_basis()
        observations = 0
        margins: list[float] = []
        for per_variant in by_basis.values():
            mine = per_variant.get(variant_id)
            theirs = per_variant.get(incumbent.variant_id)
            if mine is None or theirs is None:
                continue
            observations += mine[0]
            margins.append(mine[1] - theirs[1])
        if observations < self.min_observations or not margins:
            return False
        if min(margins) < self.min_gain:
            # Winning on average while losing on some composition is the signature
            # of a variant that traded one kind of run for another.
            return False

        updated = [
            Variant(
                variant_id=item.variant_id,
                topology=item.topology,
                edge_priority=item.edge_priority,
                parent_id=item.parent_id,
                generation=item.generation,
                note=item.note,
                promoted=True if item.variant_id == variant_id else item.promoted,
                created_at=item.created_at,
            )
            for item in self.variants()
        ]
        self._save_variants(updated)
        return True

    # -- reporting -----------------------------------------------------------

    def report(self) -> str:
        records = self.runs()
        usable = [item for item in records if item.rubric_version == RUBRIC_VERSION]
        lines = [
            f"# AutoR topology archive ({self.root})",
            "",
            f"- archive format: v{ARCHIVE_VERSION}",
            f"- rubric: v{RUBRIC_VERSION}",
            f"- runs recorded: {len(records)} ({len(usable)} on the current rubric)",
            f"- variants: {len(self.variants())}",
            "",
        ]
        fitness = self.variant_fitness()
        if fitness:
            lines += ["## Variants", "", "| Variant | Runs | Mean fitness | Promoted |", "| --- | --- | --- | --- |"]
            for item in self.variants():
                observations, mean = fitness.get(item.variant_id, (0, 0.0))
                lines.append(
                    f"| `{item.variant_id}` | {observations} | "
                    f"{mean:.3f} | {'yes' if item.promoted else 'no'} |"
                )
            lines.append("")

        from .decisions import decisions_from, format_offered_payoffs, offered_payoffs

        contrasts = offered_payoffs(decisions_from(usable))
        lines += [
            "## Edge payoff — offered and declined",
            "",
            "The estimator the proposer acts on. Treatment is decisions that took the move; "
            "control is decisions that were *offered* it and did not.",
            "",
            format_offered_payoffs(contrasts),
            "",
        ]

        payoffs = edge_payoffs(usable)
        if payoffs:
            lines += [
                "## Edge payoff — unadjusted (not acted on)",
                "",
                "The older run-level contrast, kept and printed so the two can be seen to "
                "disagree. Its control arm pools four states — the guard was shut, "
                "`--final-stage` pruned the edge, the visit budget was spent, or the topology "
                "never had it — and only one of those was a choice.",
                "",
                "| Edge | Took | Mean | Skipped | Mean | Delta | Believable |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
            for payoff in sorted(payoffs.values(), key=lambda item: abs(item.delta), reverse=True):
                lines.append(
                    f"| `{payoff.edge}` | {payoff.taken_runs} | {payoff.taken_mean:.3f} | "
                    f"{payoff.skipped_runs} | {payoff.skipped_mean:.3f} | {payoff.delta:+.3f} | "
                    f"{'yes' if payoff.believable(self.min_observations) else 'no'} |"
                )
            lines.append("")
            lines.append(
                f"An edge is believable at {self.min_observations} runs on each side. Below that "
                "the delta is printed and not acted on."
            )
        return "\n".join(lines)


def _variant_id(parent: Variant, edge: str, priority: int) -> str:
    slug = edge.replace("->", "_to_").replace("0", "")
    return f"g{parent.generation + 1}-{slug}-p{priority}"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def resolve_graph(archive: Archive | None, topology: str) -> tuple[StageGraph, str]:
    """The graph to run, and the id of the variant it came from.

    With no archive, or an archive with nothing promoted, this is the declared
    topology unchanged — so an operator who has never enabled the archive gets the
    same graph they always did.
    """
    base = StageGraph.named(topology)
    if archive is None:
        return base, "baseline"
    variant = archive.sample_parent()
    if variant.variant_id == BASELINE_VARIANT.variant_id or variant.topology != topology:
        return base, BASELINE_VARIANT.variant_id
    return variant.apply_to(base), variant.variant_id

