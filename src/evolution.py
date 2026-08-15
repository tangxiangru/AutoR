"""Make a refinement round prove it helped before it is allowed to stand.

AutoR's stage loop already iterates. What it never had was an ordering: attempt
three replaced attempt two because it happened later, and a round that dropped a
resolving reference or replaced a measured number with a hedge was promoted on
exactly the same terms as one that fixed something. "Refine" was a hope.

This module turns the loop into a ratchet.

* Every candidate is measured by :mod:`src.rubric`, which reads the run off disk.
* The champion is the draft that gets promoted at approval — not the last one.
* A round that scores worse is **reverted**: the champion's markdown is written
  back over the draft, so the reviewer and the human see the best candidate the
  run produced rather than the most recent.
* Candidates that lose on the total but win on some criterion stay on a Pareto
  frontier (:mod:`src.pareto`), and a later round is spent merging them.
* The improvement directive names the criteria that lost points and the evidence,
  and says nothing about the ones already at full marks — a round told "make it
  better" produces churn, a round told "these four referenced paths do not exist"
  produces a fix.

**The round that must not be allowed to win.**

A scored loop is an optimiser, and in a research pipeline the cheapest way to
raise a score is to change the finding. :mod:`src.rubric` is built so no criterion
can see a verdict, which removes the gradient. This module closes the remaining
route: a polish round that rewrites `hypothesis_outcomes.json` — even to a set
that scores identically — is rejected outright and the champion is restored, with
a ``verdict_drift`` row in the ledger. Improving the evidence is the point;
improving the answer is the failure the whole scientific-validity chain exists to
prevent, and a self-improvement loop is the most efficient way to reintroduce it.

Everything is on disk under ``runs/<id>/evolution/``: every candidate, every
score, every directive, every reverted round. A ratchet that cannot be inspected
is a claim about a ratchet.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .pareto import Complement, complementary_pair, format_frontier_for_prompt, insert
from .rubric import (
    RUBRIC_VERSION,
    StageScore,
    format_score_for_prompt,
    format_score_line,
    score_stage,
)
from .utils import RunPaths, StageSpec, append_jsonl, append_log_entry, read_text, write_text


#: Below this, a round did not improve anything — it moved the number. The rubric
#: is built from counts and ratios, so a real fix moves the total by far more than
#: this; anything smaller is a reworded sentence crossing a length threshold.
DEFAULT_MIN_GAIN = 0.005

#: Consecutive rounds without a gain before the stage is declared polished. One is
#: too eager: a merge round often costs a point somewhere before paying for itself,
#: and stopping on the first flat round would never reach the merge.
DEFAULT_PATIENCE = 2

#: Polish rounds per stage when nothing is specified.
#:
#: Two rather than three because the third is almost never the one that pays: a
#: stage responds to its first targeted fix or it does not, and :attr:`patience`
#: stops a flat stage before the budget does anyway. Two leaves room for the merge
#: round that a Pareto frontier occasionally earns.
DEFAULT_ROUNDS = 2


@dataclass(frozen=True)
class EvolutionConfig:
    """What the improvement loop is allowed to spend.

    Split into two settings because they cost completely different things, and
    conflating them was making the cheap half opt-in for no reason.

    ``measure`` scores every valid draft, runs the champion ratchet, rejects a
    round that moved a verdict, and writes the ledger. All of that is disk reads —
    :mod:`src.rubric` never calls a backend — so it is on by default. A run that
    measures and never polishes still gets the property that matters most: the
    draft that gets promoted is the best one the run produced, not the last one.

    ``rounds`` buys further attempts at a stage that already passed validation.
    Each one is a full stage execution, so this is where the money goes, and it is
    the number to turn down.
    """

    #: Score every draft and run the ratchet. Free; off only for a caller who wants
    #: the old behaviour exactly.
    measure: bool = True
    #: Polish rounds allowed per stage, beyond the first draft. These do not consume
    #: the stage's repair budget: a stage that is being improved is not a stage that
    #: is failing, and charging improvement rounds against `--max-attempts` would
    #: make a well-behaved stage look like it was thrashing.
    rounds: int = DEFAULT_ROUNDS
    min_gain: float = DEFAULT_MIN_GAIN
    patience: int = DEFAULT_PATIENCE
    #: Stages to evolve. Empty means all of them.
    stages: tuple[str, ...] = ()

    @property
    def enabled(self) -> bool:
        """Whether this config does anything at all.

        Kept so a caller can ask the question without knowing which of the two
        settings turned it off.
        """
        return self.measure

    def applies_to(self, stage: StageSpec) -> bool:
        if not self.measure:
            return False
        return not self.stages or stage.slug in self.stages

    def to_dict(self) -> dict[str, Any]:
        return {
            "measure": self.measure,
            "rounds": self.rounds,
            "min_gain": self.min_gain,
            "patience": self.patience,
            "stages": list(self.stages),
            "rubric_version": RUBRIC_VERSION,
        }


@dataclass
class StageEvolutionState:
    stage_slug: str
    champion: StageScore | None = None
    frontier: list[StageScore] = field(default_factory=list)
    rounds_spent: int = 0
    flat_rounds: int = 0
    #: Verdict fingerprint of the champion, carried so drift is measured against
    #: the draft that is standing rather than against the previous attempt — two
    #: rejected rounds in a row must not be able to walk the verdicts anywhere.
    verdict_digest: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class RoundOutcome:
    #: ``first`` | ``promoted`` | ``frontier`` | ``regressed`` | ``verdict_drift``
    #: | ``directed`` (a human or the reviewer asked for this one; it stands).
    verdict: str
    score: StageScore
    champion: StageScore | None
    delta: float
    #: True when the draft on disk was replaced by the champion's markdown.
    reverted: bool
    note: str

    @property
    def improved(self) -> bool:
        return self.verdict in {"first", "promoted"}


class EvolutionController:
    """Per-run owner of the champion ratchet, the frontier, and the ledger."""

    def __init__(
        self,
        config: EvolutionConfig,
        *,
        artifact_dirs: Mapping[str, Sequence[Path]] | None = None,
        artifact_roots: Sequence[Path] | None = None,
    ) -> None:
        self.config = config
        self.artifact_dirs = artifact_dirs
        self.artifact_roots = artifact_roots
        self._states: dict[str, StageEvolutionState] = {}

    # -- paths ---------------------------------------------------------------

    def stage_dir(self, paths: RunPaths, stage: StageSpec) -> Path:
        return paths.evolution_dir / stage.slug

    def champion_file(self, paths: RunPaths, stage: StageSpec) -> Path:
        return self.stage_dir(paths, stage) / "champion.md"

    def _champion_score_file(self, paths: RunPaths, stage: StageSpec) -> Path:
        return self.stage_dir(paths, stage) / "champion.json"

    def _frontier_file(self, paths: RunPaths, stage: StageSpec) -> Path:
        return self.stage_dir(paths, stage) / "frontier.json"

    def _candidate_file(self, paths: RunPaths, stage: StageSpec, attempt_no: int) -> Path:
        return self.stage_dir(paths, stage) / "candidates" / f"attempt_{attempt_no:02d}.md"

    def ledger_file(self, paths: RunPaths) -> Path:
        return paths.evolution_dir / "improvement_ledger.jsonl"

    def summary_file(self, paths: RunPaths) -> Path:
        return paths.evolution_dir / "summary.json"

    # -- state ---------------------------------------------------------------

    def state(self, paths: RunPaths, stage: StageSpec) -> StageEvolutionState:
        """Load or rehydrate this stage's state.

        Rehydrated from disk on first touch so a resumed run keeps its champion.
        Without that, `--resume-run` would restart the ratchet from nothing and
        the next draft would win by default, silently discarding the best work the
        earlier session produced.
        """
        cached = self._states.get(stage.slug)
        if cached is not None:
            return cached

        state = StageEvolutionState(stage_slug=stage.slug)
        stored = _read_json(self._champion_score_file(paths, stage))
        if isinstance(stored, Mapping):
            champion = StageScore.from_dict(stored)
            if champion.rubric_version == RUBRIC_VERSION:
                state.champion = champion
                state.verdict_digest = champion.verdict_digest
            else:
                # Scores from another rubric version are not comparable, so the
                # champion is dropped rather than defended. Recorded, because a
                # champion vanishing between sessions with no explanation is the
                # kind of thing that gets debugged for an hour.
                append_log_entry(
                    paths.logs,
                    f"{stage.slug} evolution_champion_discarded",
                    f"Stored champion was measured under rubric v{champion.rubric_version}; "
                    f"this build is v{RUBRIC_VERSION}. Starting the ratchet over.",
                )
        stored_frontier = _read_json(self._frontier_file(paths, stage))
        if isinstance(stored_frontier, list):
            state.frontier = [
                score
                for score in (
                    StageScore.from_dict(item) for item in stored_frontier if isinstance(item, Mapping)
                )
                if score.rubric_version == RUBRIC_VERSION
            ]
        self._states[stage.slug] = state
        return state

    # -- the ratchet ---------------------------------------------------------

    def consider(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        draft_path: Path,
        is_polish_round: bool = False,
    ) -> RoundOutcome:
        """Measure the draft at ``draft_path`` and decide whether it may stand.

        Reverts the draft file to the champion when it may not. The manager keeps
        working with the same path either way, which is what makes the ratchet
        invisible to every other part of the loop.
        """
        state = self.state(paths, stage)
        markdown = read_text(draft_path)
        score = score_stage(
            paths=paths,
            stage=stage,
            markdown=markdown,
            attempt_no=attempt_no,
            artifact_dirs=self.artifact_dirs,
            artifact_roots=self.artifact_roots,
        )
        self._archive_candidate(paths, stage, attempt_no, markdown, score)

        champion = state.champion
        delta = score.total - champion.total if champion is not None else score.total

        # 0. Was this round asked for by a person?
        #
        # The ratchet governs AutoR's own polish rounds. It does not govern a
        # reviewer or a human who asked for a change: that is direction, and a
        # measurement is not entitled to overrule it. AutoR would otherwise
        # silently revert a requested edit because a rubric preferred the previous
        # wording, which is the opposite of the arrangement this project is built
        # on. The delta is still measured and recorded, so the ledger shows whether
        # the requested change helped — the human keeps the decision and gets the
        # number.
        if not is_polish_round and champion is not None:
            update = insert(state.frontier, score)
            state.frontier = list(update.members) if update.verdict != "incomparable" else [score]
            state.champion = score
            state.verdict_digest = score.verdict_digest
            state.flat_rounds = 0
            self._persist(paths, stage, state, markdown)
            outcome = RoundOutcome(
                "directed",
                score,
                score,
                delta,
                False,
                f"Directed revision; it stands regardless of measurement ({delta:+.3f}).",
            )
            self._record(paths, stage, attempt_no, outcome, state, is_polish_round)
            return outcome

        # 1. Did this round move what the run concludes?
        drifted = (
            is_polish_round
            and bool(state.verdict_digest)
            and bool(score.verdict_digest)
            and score.verdict_digest != state.verdict_digest
        )
        if drifted:
            outcome = RoundOutcome(
                verdict="verdict_drift",
                score=score,
                champion=champion,
                delta=delta,
                reverted=self._revert(paths, stage, draft_path),
                note=(
                    "This round changed a hypothesis verdict. An improvement round may "
                    "strengthen the evidence for a finding; it may not change the finding. "
                    "The previous draft was restored."
                ),
            )
            state.flat_rounds += 1
            self._record(paths, stage, attempt_no, outcome, state, is_polish_round)
            return outcome

        # 2. Is it the first thing we have measured?
        if champion is None:
            state.champion = score
            state.verdict_digest = score.verdict_digest
            state.frontier = [score]
            self._persist(paths, stage, state, markdown)
            outcome = RoundOutcome("first", score, score, delta, False, "First measured draft.")
            self._record(paths, stage, attempt_no, outcome, state, is_polish_round)
            return outcome

        # 3. Did it beat the champion by enough to be a fix rather than noise?
        if delta >= self.config.min_gain:
            update = insert(state.frontier, score)
            state.frontier = list(update.members) if update.verdict != "incomparable" else [score]
            state.champion = score
            state.verdict_digest = score.verdict_digest
            state.flat_rounds = 0
            self._persist(paths, stage, state, markdown)
            outcome = RoundOutcome(
                "promoted", score, score, delta, False, f"New champion (+{delta:.3f})."
            )
            self._record(paths, stage, attempt_no, outcome, state, is_polish_round)
            return outcome

        # 4. It lost on the total. Is it the only draft good at something?
        update = insert(state.frontier, score)
        state.flat_rounds += 1
        if update.accepted:
            state.frontier = list(update.members)
            self._persist(paths, stage, state, None)
            outcome = RoundOutcome(
                "frontier",
                score,
                champion,
                delta,
                self._revert(paths, stage, draft_path),
                "Lost on the total but is the only draft holding some criterion; kept on the "
                "frontier for a merge round.",
            )
            self._record(paths, stage, attempt_no, outcome, state, is_polish_round)
            return outcome

        outcome = RoundOutcome(
            "regressed",
            score,
            champion,
            delta,
            self._revert(paths, stage, draft_path),
            f"No better than the standing draft ({delta:+.3f}); the champion was restored.",
        )
        self._record(paths, stage, attempt_no, outcome, state, is_polish_round)
        return outcome

    def _revert(self, paths: RunPaths, stage: StageSpec, draft_path: Path) -> bool:
        champion_markdown = self.champion_file(paths, stage)
        if not champion_markdown.exists():
            return False
        shutil.copyfile(champion_markdown, draft_path)
        return True

    # -- round scheduling ----------------------------------------------------

    def should_continue(self, paths: RunPaths, stage: StageSpec) -> bool:
        """Whether another polish round is worth paying for.

        Four stops, and the last one is what makes this affordable to leave on. The
        budget bounds the spend and the patience counter stops a stage that has
        stopped responding — but both of those only fire *after* a round has been
        paid for. :meth:`recoverable_headroom` fires before: if no criterion has a
        named shortfall worth ``min_gain``, there is nothing for a round to do, and
        AutoR would be buying a stage execution to reword a draft that is already at
        the ceiling of what the rubric can see. A clean stage costs nothing.
        """
        if not self.config.applies_to(stage):
            return False
        if self.config.rounds <= 0:
            return False
        state = self.state(paths, stage)
        if state.rounds_spent >= self.config.rounds:
            return False
        if state.flat_rounds >= self.config.patience:
            return False
        if state.champion is None:
            return False
        if state.champion.total >= 1.0 - 1e-9:
            return False
        return self.recoverable_headroom(state.champion) >= self.config.min_gain

    def recoverable_headroom(self, champion: StageScore) -> float:
        """How much of the total a round could plausibly recover.

        Weighted over criteria that are both below full marks *and* carry a named
        shortfall. A criterion scoring 0.6 with nothing to say about what would
        raise it is not headroom — it is a measurement the rubric cannot turn into
        an instruction, and a round aimed at it produces churn.
        """
        total_weight = sum(item.weight for item in champion.criteria) or 1.0
        return (
            sum(
                (1.0 - item.score) * item.weight
                for item in champion.criteria
                if item.score < 1.0 and item.shortfall
            )
            / total_weight
        )

    def begin_round(self, paths: RunPaths, stage: StageSpec) -> None:
        self.state(paths, stage).rounds_spent += 1

    def begin_stage(self, paths: RunPaths, stage: StageSpec) -> None:
        """Give a stage a fresh round budget each time the run enters it.

        The champion deliberately survives — that is the ratchet, and a revisit's
        first draft replaces it only by being `directed`, which it is. The *budget*
        does not survive: a stage re-entered because a later stage found a problem
        is doing new work, and charging it for the rounds its previous visit spent
        would leave the visit that actually needs improvement with nothing.
        """
        state = self.state(paths, stage)
        state.rounds_spent = 0
        state.flat_rounds = 0

    def next_directive(self, paths: RunPaths, stage: StageSpec) -> str:
        """The instruction for the next polish round.

        Two shapes. A merge, when the frontier holds drafts with complementary
        strengths and combining them has more headroom than fixing the champion's
        weakest criterion. Otherwise a targeted repair naming the criteria that
        lost points, with what was measured and what would raise it.

        Both end with the same prohibitions, because the ways a scored loop cheats
        are predictable: pad the prose, restate a number more confidently, or quietly
        move the finding.
        """
        state = self.state(paths, stage)
        champion = state.champion
        if champion is None:
            return ""

        complement = complementary_pair(state.frontier)
        weakest = champion.weakest(limit=3)
        merge_headroom = complement.headroom if complement is not None else 0.0
        repair_headroom = sum((1.0 - item.score) * item.weight for item in weakest) / (
            sum(item.weight for item in champion.criteria) or 1.0
        )

        if complement is not None and merge_headroom > repair_headroom and merge_headroom > self.config.min_gain:
            body = self._merge_directive(paths, stage, complement)
        else:
            body = self._repair_directive(champion, weakest)

        return body + "\n\n" + self._prohibitions(stage, champion)

    def _repair_directive(self, champion: StageScore, weakest: Sequence[Any]) -> str:
        lines = [
            "## Targeted improvement round",
            "",
            "The current draft has been measured against AutoR's rigour rubric. This round "
            "exists to raise the criteria below and nothing else.",
            "",
            format_score_for_prompt(champion),
            "",
            "Work through them in order. For each one, change the *run* — write the missing "
            "artifact, record the missing measurement, resolve the broken reference — and then "
            "update the stage summary to match. A criterion already at 1.00 is finished: do not "
            "touch that part of the draft.",
        ]
        if not weakest:
            lines.append("")
            lines.append(
                "No criterion has a named shortfall. If nothing here can be raised by real work, "
                "say so in Suggestions for Refinement and leave the draft as it is."
            )
        return "\n".join(lines)

    def _merge_directive(self, paths: RunPaths, stage: StageSpec, complement: Complement) -> str:
        left, right = complement.left, complement.right
        return "\n".join(
            [
                "## Merge round",
                "",
                "Two earlier drafts of this stage are each the only one that got something right. "
                "Neither dominates the other, so the best available draft is one that has not been "
                "written yet: the one that keeps both sets of strengths.",
                "",
                format_frontier_for_prompt([left, right]),
                "",
                f"- Attempt {left.attempt_no} is the only one holding: "
                + ", ".join(f"`{key}`" for key in complement.left_wins),
                f"- Attempt {right.attempt_no} is the only one holding: "
                + ", ".join(f"`{key}`" for key in complement.right_wins),
                "",
                f"Both are on disk under `{self.stage_dir(paths, stage).name}/candidates/`. Read them, "
                "then produce a draft that keeps what each one got right. Combining the measured "
                f"best of both would reach {complement.merged_ceiling:.3f}, against "
                f"{max(left.total, right.total):.3f} for the better of the two.",
                "",
                "This is a merge, not a rewrite. Anything neither draft got wrong stays as it is.",
            ]
        )

    def _prohibitions(self, stage: StageSpec, champion: StageScore) -> str:
        lines = [
            "### What does not count as improvement",
            "",
            "- Do not lengthen a section to raise a score. Eight of these criteria are ratios or "
            "counts over artifacts on disk and prose cannot move any of them. "
            "`deliverable_coverage` is the exception, and it is honest about how far prose can "
            "move it: **half**. Mentioning a thing the task asked for earns half its share, "
            "because a report that names it beats one that is silent about it. The other half is "
            "only paid when the sentence that mentions it also carries a number that appears in "
            "a file under `workspace/results`, or names a file the run actually wrote. Restating "
            "the task, or pasting back the shortfall printed above, earns nothing at all -- both "
            "are filtered. So the way to raise this is to do the work the task named and report "
            "the result, or to state in that demand's own section that it could not be produced "
            "and why.",
            "- Do not restate an unverified number more confidently. If a value is not in a file "
            "under `workspace/results`, either measure it and write it there or remove the claim.",
            "- Do not delete a weak part of the draft to raise an average. A dropped file "
            "reference lowers `grounding`, and the previous draft is kept and compared.",
        ]
        if champion.verdict_digest:
            lines.append(
                "- **Do not change any hypothesis verdict.** The hypotheses were frozen before "
                "results existed and every verdict is already recorded. Strengthen the evidence "
                "behind a finding as much as you can; do not touch the finding. A round that "
                "moves a verdict is rejected automatically and this draft is restored."
            )
        if stage.number >= 5:
            lines.append(
                "- Do not re-run an experiment in order to obtain a different outcome. Re-running "
                "for more repeats is welcome; record every run, including the ones that disagree."
            )
        return "\n".join(lines)

    # -- promotion -----------------------------------------------------------

    def champion_markdown(self, paths: RunPaths, stage: StageSpec) -> str | None:
        path = self.champion_file(paths, stage)
        return read_text(path) if path.exists() else None

    def finalize_stage(self, paths: RunPaths, stage: StageSpec) -> StageScore | None:
        """Record this stage's settled champion into the run-level summary.

        The summary is what :mod:`src.archive` reads when the run is over, so a
        stage that was never evolved has to be absent from it rather than present
        with a zero — an unmeasured stage averaged in as a failure would drag a
        scaffold variant's fitness down for work it never did.
        """
        state = self.state(paths, stage)
        if state.champion is None:
            return None
        summary = _read_json(self.summary_file(paths))
        payload: dict[str, Any] = dict(summary) if isinstance(summary, Mapping) else {}
        payload.setdefault("rubric_version", RUBRIC_VERSION)
        payload.setdefault("stages", {})
        payload["stages"][stage.slug] = {
            **state.champion.to_dict(),
            "rounds_spent": state.rounds_spent,
            "candidates_measured": len(state.history),
            "frontier_size": len(state.frontier),
        }
        payload["updated_at"] = _now()
        write_text(self.summary_file(paths), json.dumps(payload, indent=2, ensure_ascii=False))
        return state.champion

    # -- persistence ---------------------------------------------------------

    def _archive_candidate(
        self,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        markdown: str,
        score: StageScore,
    ) -> None:
        """Keep every candidate, including the ones that lost.

        A discarded candidate is the only evidence that the ratchet discarded
        anything. Without it the run says "the champion scored 0.84" and there is
        no way to tell that from a run that only ever produced one draft.
        """
        candidate_path = self._candidate_file(paths, stage, attempt_no)
        write_text(candidate_path, markdown)
        write_text(
            candidate_path.with_suffix(".json"),
            json.dumps(score.to_dict(), indent=2, ensure_ascii=False),
        )

    def _persist(
        self,
        paths: RunPaths,
        stage: StageSpec,
        state: StageEvolutionState,
        champion_markdown: str | None,
    ) -> None:
        if state.champion is not None:
            write_text(
                self._champion_score_file(paths, stage),
                json.dumps(state.champion.to_dict(), indent=2, ensure_ascii=False),
            )
        if champion_markdown is not None:
            write_text(self.champion_file(paths, stage), champion_markdown)
        write_text(
            self._frontier_file(paths, stage),
            json.dumps([item.to_dict() for item in state.frontier], indent=2, ensure_ascii=False),
        )

    def _record(
        self,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        outcome: RoundOutcome,
        state: StageEvolutionState,
        is_polish_round: bool,
    ) -> None:
        row = {
            "recorded_at": _now(),
            "stage": stage.slug,
            "attempt": attempt_no,
            "round_kind": "polish" if is_polish_round else "stage_attempt",
            "rounds_spent": state.rounds_spent,
            "verdict": outcome.verdict,
            "total": round(outcome.score.total, 4),
            "delta": round(outcome.delta, 4),
            "reverted": outcome.reverted,
            "champion_total": round(outcome.champion.total, 4) if outcome.champion else None,
            "frontier_size": len(state.frontier),
            "criteria": {item.key: round(item.score, 4) for item in outcome.score.criteria},
            "verdict_digest": outcome.score.verdict_digest,
            "note": outcome.note,
        }
        state.history.append(row)
        append_jsonl(self.ledger_file(paths), row)
        append_log_entry(
            paths.logs,
            f"{stage.slug} attempt {attempt_no} evolution_{outcome.verdict}",
            f"{format_score_line(outcome.score)}\ndelta: {outcome.delta:+.4f}\n{outcome.note}",
        )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def load_run_criteria(paths: RunPaths) -> dict[str, float]:
    """Mean score per rubric criterion across the stages that measured it.

    The per-stage total is what the archive ranks on; this is what makes a
    difference *interpretable*. A capability that raises the total by writing more
    files and a capability that raises it by grounding more claims are the same
    number and completely different results, and only the decomposition tells them
    apart. See :mod:`src.trials`.

    Averaged over the stages where a criterion applied, not over all eight:
    ``numeric_fidelity`` starts at Stage 05, and counting the earlier stages as
    zeroes would make it look like every run fails it.
    """
    payload = _read_json(paths.evolution_dir / "summary.json")
    if not isinstance(payload, Mapping):
        return {}
    if str(payload.get("rubric_version") or "") != RUBRIC_VERSION:
        return {}
    stages = payload.get("stages")
    if not isinstance(stages, Mapping):
        return {}
    collected: dict[str, list[float]] = {}
    for entry in stages.values():
        if not isinstance(entry, Mapping):
            continue
        for item in entry.get("criteria", []):
            if not isinstance(item, Mapping):
                continue
            key = str(item.get("key") or "").strip()
            score = item.get("score")
            if key and isinstance(score, (int, float)):
                collected.setdefault(key, []).append(float(score))
    return {key: sum(values) / len(values) for key, values in collected.items()}


def load_run_fitness(paths: RunPaths) -> dict[str, float]:
    """Per-stage champion totals for a finished run, for the cross-run archive.

    Absent stages stay absent. :mod:`src.archive` averages over what a variant was
    actually measured on, and a stage that never ran must not read as one it failed.
    """
    payload = _read_json(paths.evolution_dir / "summary.json")
    if not isinstance(payload, Mapping):
        return {}
    if str(payload.get("rubric_version") or "") != RUBRIC_VERSION:
        return {}
    stages = payload.get("stages")
    if not isinstance(stages, Mapping):
        return {}
    fitness: dict[str, float] = {}
    for slug, entry in stages.items():
        if isinstance(entry, Mapping) and isinstance(entry.get("total"), (int, float)):
            fitness[str(slug)] = float(entry["total"])
    return fitness
