"""Measure a stage draft, so a refinement round can be told whether it helped.

AutoR already refines: a reviewer asks for changes, the stage runs again, the new
draft replaces the old one. Nothing anywhere compares the two. A refinement that
made the stage *worse* — dropped a resolving file reference, replaced a measured
number with a hedge, collapsed the decision ledger into one repeated sentence —
is promoted exactly like one that helped, because "later" was the only ordering
the loop had.

This module supplies the missing ordering. It scores a draft against criteria
that are read off disk rather than off the prose, so the score moves when the
work moves and not when the wording does.

**The score is deliberately blind to what the run concluded.**

That constraint is the whole design, not a caveat. A fitness function plus a loop
is an optimiser, and an optimiser pointed at "how good does this result look"
is an automated p-hacker: it will find that the cheapest way to raise the number
is to change the answer. :mod:`src.preregistration` exists to stop a human-driven
version of that. A scored improvement loop would reintroduce it with a budget.

So no criterion here reads a verdict *value*. Stage 06 is scored on whether every
preregistered hypothesis carries a verdict backed by an artifact that exists — a
run whose hypothesis was refuted, cleanly, with the evidence on disk, scores
higher than one whose hypothesis was supported on an assertion. The verdicts are
routed through :func:`_verdict_blind_outcomes`, which strips the value before any
scoring code can see it, and :func:`verdict_digest` hashes the verdict set so
:mod:`src.evolution` can reject a polish round that moved one.

The rubric is mechanical on purpose. An LLM judge scoring drafts written by the
same model family is a fitness function the optimiser can talk to, and the point
of a ratchet is that it cannot be argued with. Qualitative judgement stays where
it already is: the human, or the reviewer agent at the stage boundary, which now
sees the best candidate instead of the last one.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Mapping, NamedTuple, Sequence

from .artifact_index import is_autor_own_record
from .utils import (
    FIGURE_SUFFIXES,
    MACHINE_DATA_SUFFIXES,
    RESULT_SUFFIXES,
    STAGES,
    RunPaths,
    StageSpec,
    _existing_files,
    _extract_path_references,
    _listed_file_exists,
    extract_markdown_section,
    read_text,
    stage_execution_started_at,
    validate_stage_markdown,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle at runtime, type-only here
    from .hypothesis_manifest import HypothesisEntry


#: Bump when a criterion is added, removed, reweighted, or has its measurement
#: changed. Scores carrying different versions are not comparable, and every
#: consumer that ranks two scores has to refuse to rank across a version change:
#: a reweight would otherwise read as a run that got better or worse overnight.
#: ``2`` excludes AutoR's own record files from ``artifact_breadth``. A v1 score and
#: a v2 score are not two measurements of one thing, and every consumer refuses to
#: rank across the change rather than quietly treating the correction as a run
#: having got worse.
#: ``3`` caps ``quantification`` at ``numeric_fidelity`` where both apply, so a draft
#: cannot be paid for numbers no artifact supports — see
#: :func:`_cap_quantification_by_fidelity`. Every stage draft scored before the cap
#: over-credits any Key Results section carrying unverifiable numbers, which is why
#: this is a version bump and not a patch.
#: ``5`` moves two things at once. ``artifact_breadth`` now reads the four workspace
#: directories Stages 01, 02, 07 and 08 are told to write — ``literature/``,
#: ``notes/``, ``artifacts/`` and ``reviews/`` — and scores against
#: :data:`STAGE_ARTIFACT_KINDS`, the kinds *this* stage's prompt asks for, instead of
#: a bare count of any two or three; and ``reproducibility`` gains a Stage 02-03 link
#: for the decision rule on every empirical hypothesis. Both change what an existing
#: score means: replayed against v4, a Stage 08 that produced its whole release bundle
#: measures 0.333 on breadth, and 0.0 if none of that bundle went under ``writing/``.
#: So a v4 total and a v5 total are not two measurements of one thing.
#: ``6`` adds ``deliverable_coverage``, the first criterion that reads a document the run
#: did not write -- the task statement -- and asks whether the draft speaks to what was
#: asked, with a number an artifact holds. Every criterion before it measured the run
#: against its own record. Replayed over the 263 stage drafts of a 40-task benchmark
#: pass -- `python tools/rubric_replay.py`, which re-derives every number in this note --
#: the existing eight read mean 0.989 / sd 0.036; the new one reads mean 0.644 / sd 0.322
#: and generally falls with stage number -- 0.70 / 0.94 / 0.62 / 0.54 / 0.61 / 0.54 /
#: 0.51 for Stages 01 to 07 -- because a late stage owes more of the task than an early
#: one. It is *not* monotone: Stage 02 is the high point, and an earlier version of this
#: note claimed monotonicity from the two endpoints alone. Those figures are with
#: ``artifact_roots`` passed, which is what :class:`EvolutionController` does on every
#: real call; an earlier version quoted a replay that omitted it and so described a
#: configuration no run is ever scored under. On the run that pass
#: scored 0.0 externally the eight read 0.97 at Stage 06 and the new criterion reads 0.00
#: from Stage 05 on, which is the stage the run stopped producing the object the task
#: named. ``6`` also stops ``numeric_fidelity`` treating an arXiv id or a "Fig. 3" as a
#: reported measurement, which had made deleting the subject paper's name from a draft
#: worth 9.5x ``DEFAULT_MIN_GAIN``. Both change what an existing score means, so a v5
#: total and a v6 total are not two measurements of one thing.
#:
#: ``7`` is a correction, not a feature, and it is a version bump because it moves every
#: ``deliverable_coverage`` score. Three ways to raise the criterion without doing any
#: work were open in v6 and are closed here -- restating a demand in its own words,
#: quoting the task statement, and pasting back the shortfall the ratchet had just
#: printed (the last raised the total on 89 of 89 drafts). The on-disk half now applies
#: at every stage rather than from Stage 05, so a v6 early-stage score and a v7 one are
#: not comparable either. ``_IDENTIFIER_PREFIX`` also gains the left word boundary it
#: shipped without: ``v`` was matching the tail of CV, HIV, dev and MeV, so writing
#: "CV 0.821" hid an invented number from ``numeric_fidelity`` for a gain of +0.0476 --
#: the same size as the gradient v6 added the filter to remove.
RUBRIC_VERSION = "7"

#: The keys the rubric refuses to read out of an adjudication artifact.
#:
#: Enforced by construction in :func:`_verdict_blind_outcomes` rather than by
#: review, and checked end-to-end by a test that flips every verdict on disk and
#: asserts the total is unchanged.
OUTCOME_BLIND_FIELDS = ("verdict", "status", "conclusion", "result")

#: A file smaller than this is not evidence that a stage produced anything. Zero
#: byte placeholders are the cheapest way to satisfy a criterion that counts.
MIN_ARTIFACT_BYTES = 32

#: Written in the future or the conditional. A stage summary is a report on work
#: that happened; a draft that mostly describes intentions is the characteristic
#: failure of an automated pipeline, and it is invisible to every other gate
#: because the prose is fluent and every required section is present.
_HEDGE_PATTERNS = (
    r"\bwe (?:will|plan to|intend to|aim to|would|expect to)\b",
    r"\b(?:is|are) (?:designed|intended|expected|planned) to\b",
    r"\bshould (?:improve|increase|reduce|show|demonstrate|help)\b",
    r"\b(?:could|might|may) (?:improve|increase|reduce|show|demonstrate|help)\b",
    r"\bto be (?:run|executed|measured|evaluated|determined|added)\b",
    r"\bnext (?:step|steps) (?:is|are|will)\b",
    r"\bnot yet (?:run|measured|evaluated|implemented)\b",
    r"\bin a future (?:stage|iteration|round)\b",
)

#: A number carrying a unit or a comparison. "improved accuracy" is a sentence;
#: "62.4% vs 58.1% (+4.3 points, n=5)" is a result.
_QUANTITY_PATTERN = re.compile(
    r"(?<![\w.])"
    r"[-+]?\d+(?:[.,]\d+)?"
    r"\s*"
    r"(?:%|pp|points?|×|x\b|ms\b|s\b|GB\b|MB\b|k\b|M\b|B\b|σ|±|/\d)",
    flags=re.IGNORECASE,
)
#: A bare number attached to a named quantity: `accuracy 0.741`, `n = 5`, `p<0.01`.
_NAMED_QUANTITY_PATTERN = re.compile(
    r"\b[A-Za-z][\w@.-]{2,}\s*[:=]?\s*[<>≤≥]?\s*[-+]?\d+(?:\.\d+)?\b"
)

_DECISION_LEDGER_BUCKETS = (
    "Open Questions",
    "Locked Decisions",
    "Assumptions",
    "Rejected Alternatives",
)

@dataclass(frozen=True)
class Criterion:
    """One measurable dimension of a stage draft.

    ``min_stage`` exists because a criterion that cannot apply must not be scored
    zero: Stage 01 has no experiment manifest to produce, and grading it as if it
    failed to produce one would make every early stage look worse than every late
    one, which would make the champion ratchet prefer late stages' drafts for no
    reason connected to their quality.
    """

    key: str
    title: str
    weight: float
    min_stage: int = 1
    max_stage: int = 8

    def applies_to(self, stage: StageSpec) -> bool:
        return self.min_stage <= stage.number <= self.max_stage


CRITERIA: tuple[Criterion, ...] = (
    Criterion("contract", "Contract compliance", weight=2.0),
    Criterion("grounding", "References that resolve", weight=3.0),
    Criterion("artifact_breadth", "Artifacts produced this stage", weight=2.0, min_stage=1),
    Criterion("quantification", "Findings carrying numbers", weight=2.0, min_stage=4),
    Criterion("numeric_fidelity", "Reported numbers trace to results", weight=3.0, min_stage=5),
    Criterion("traceability", "Decision ledger", weight=1.5),
    Criterion("commitment", "Reports work, not intentions", weight=1.5),
    Criterion("reproducibility", "Machine-readable validity chain", weight=3.0),
    # min_stage=1 deliberately: a survey that never mentions what the task asked for is
    # where the substitution starts, and `min_stage=3` would make an early draft's total
    # a different measurement from a late one's. Both halves apply at every stage --
    # the exemption that scored only the "spoken to" half below Stage 05 is what let a
    # draft of restated demands reach 1.000 there, and Stage 01 does write `literature/`.
    Criterion("deliverable_coverage", "Answers the task's demands", weight=3.0),
)

CRITERIA_BY_KEY: dict[str, Criterion] = {item.key: item for item in CRITERIA}


@dataclass(frozen=True)
class CriterionScore:
    key: str
    title: str
    weight: float
    #: 0.0 to 1.0.
    score: float
    #: What was measured, in one line, so the ledger says why and not just how much.
    observed: str
    #: What would raise it. Empty at full marks — an improvement directive built
    #: from a saturated criterion asks for churn, not improvement.
    shortfall: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "weight": self.weight,
            "score": round(self.score, 4),
            "observed": self.observed,
            "shortfall": self.shortfall,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CriterionScore":
        return cls(
            key=str(payload.get("key") or ""),
            title=str(payload.get("title") or ""),
            weight=float(payload.get("weight") or 0.0),
            score=float(payload.get("score") or 0.0),
            observed=str(payload.get("observed") or ""),
            shortfall=str(payload.get("shortfall") or ""),
        )


@dataclass(frozen=True)
class StageScore:
    """A draft's measured standing, and the fingerprint of what it concluded.

    ``verdict_digest`` is not scored. It is carried so that a caller comparing two
    scores can tell the difference between a draft that got better and a draft
    that changed its mind — which is the one comparison a fitness-driven loop must
    never get wrong.
    """

    stage_slug: str
    attempt_no: int
    rubric_version: str
    criteria: tuple[CriterionScore, ...]
    total: float
    verdict_digest: str = ""

    @property
    def by_key(self) -> dict[str, CriterionScore]:
        return {item.key: item for item in self.criteria}

    def weakest(self, limit: int = 3) -> list[CriterionScore]:
        """Unsaturated criteria, worst first, weighted by how much they are worth.

        Sorting on the raw score would send a polish round after a 0.4 criterion
        worth 1.5 ahead of a 0.6 criterion worth 3.0, when the second is where the
        points are.
        """
        candidates = [item for item in self.criteria if item.score < 1.0 and item.shortfall]
        candidates.sort(key=lambda item: ((1.0 - item.score) * item.weight, item.weight), reverse=True)
        return candidates[:limit]

    def comparable_to(self, other: "StageScore") -> bool:
        return (
            self.rubric_version == other.rubric_version
            and self.stage_slug == other.stage_slug
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage_slug,
            "attempt": self.attempt_no,
            "rubric_version": self.rubric_version,
            "total": round(self.total, 4),
            "verdict_digest": self.verdict_digest,
            "criteria": [item.to_dict() for item in self.criteria],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StageScore":
        return cls(
            stage_slug=str(payload.get("stage") or ""),
            attempt_no=int(payload.get("attempt") or 0),
            rubric_version=str(payload.get("rubric_version") or ""),
            criteria=tuple(
                CriterionScore.from_dict(item)
                for item in payload.get("criteria", [])
                if isinstance(item, Mapping)
            ),
            total=float(payload.get("total") or 0.0),
            verdict_digest=str(payload.get("verdict_digest") or ""),
        )


# ----------------------------------------------------------------------------
# Outcome blindness
# ----------------------------------------------------------------------------


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def _verdict_blind_outcomes(paths: RunPaths) -> list[dict[str, Any]]:
    """Adjudication records with every outcome-bearing field removed.

    The scoring code below reads only this. It cannot prefer `supported` over
    `refuted` because by the time it runs, the distinction is gone: what survives
    is whether a verdict was recorded at all, and what it points at.
    """
    payload = _load_json(paths.hypothesis_outcomes)
    if not isinstance(payload, dict):
        return []
    blinded: list[dict[str, Any]] = []
    for entry in payload.get("outcomes", []):
        if not isinstance(entry, dict):
            continue
        # Every outcome-bearing field collapses to a boolean here. Building the
        # blinded record by listing what survives, rather than by deleting what
        # does not, is what makes a criterion added later unable to reach a verdict
        # by accident: there is nothing in the returned dict to reach.
        recorded = any(str(entry.get(field) or "").strip() for field in OUTCOME_BLIND_FIELDS)
        blinded.append(
            {
                "id": str(entry.get("id") or "").strip(),
                "has_verdict": recorded,
                "rationale_chars": len(str(entry.get("rationale") or "").strip()),
                "evidence": [
                    str(item).strip()
                    for item in entry.get("evidence", [])
                    if str(item).strip()
                ],
            }
        )
    return blinded


def verdict_digest(paths: RunPaths) -> str:
    """Fingerprint what the run currently concludes, for drift detection only.

    Deliberately *not* an input to any score. :mod:`src.evolution` compares this
    across a polish round and rejects the round if it moved, which is how a loop
    that is allowed to improve the evidence is stopped from improving the answer.
    """
    payload = _load_json(paths.hypothesis_outcomes)
    if not isinstance(payload, dict):
        return ""
    verdicts = sorted(
        (str(entry.get("id") or "").strip(), str(entry.get("verdict") or "").strip())
        for entry in payload.get("outcomes", [])
        if isinstance(entry, dict)
    )
    if not verdicts:
        return ""
    canonical = json.dumps(verdicts, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------
# Individual criteria
# ----------------------------------------------------------------------------


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _score_contract(
    markdown: str,
    stage: StageSpec,
    paths: RunPaths,
    artifact_roots: Sequence[Path] | None,
) -> CriterionScore:
    """The stage's markdown contract, expressed as a number instead of a pass/fail.

    Inside the stage loop this is normally saturated, because a draft only reaches
    the ratchet after validation cleared. It is not dead weight: the archive
    replays cold drafts through the same rubric, and a repair pass that fixed four
    of five errors should read as progress rather than as another failure.

    **Deliberately not** :func:`validate_stage_artifacts`. That gate is right and
    it is not outcome-blind: :func:`validate_hypothesis_outcomes` demands an
    evidence pointer for a hypothesis recorded as supported or refuted and not for
    one recorded as inconclusive, which is correct for a gate and would be a
    gradient here — the cheapest way to a clean contract score would be to call
    every outcome inconclusive. The artifact side is covered instead by
    ``artifact_breadth`` and ``reproducibility``, which apply the same requirement
    to every verdict. Splitting them this way also stops one condition being
    weighted twice.
    """
    problems = validate_stage_markdown(
        markdown, stage=stage, paths=paths, artifact_roots=artifact_roots
    )
    count = len(problems)
    score = _clamp(1.0 - 0.2 * count)
    if count == 0:
        return CriterionScore(
            "contract", CRITERIA_BY_KEY["contract"].title, 2.0, 1.0, "no stage-contract errors"
        )
    return CriterionScore(
        "contract",
        CRITERIA_BY_KEY["contract"].title,
        2.0,
        score,
        f"{count} stage-contract error(s)",
        "Clear the outstanding validation errors: " + "; ".join(problems[:3]),
    )


def _score_grounding(
    markdown: str,
    paths: RunPaths,
    artifact_roots: Sequence[Path] | None,
) -> CriterionScore:
    """Every path the draft names, across the whole draft, has to resolve.

    The shipped gate checks `Files Produced` only. A stage that cites
    `workspace/results/ablation.json` in Key Results and never wrote it passes
    that gate and reads as if the artifact exists, which is the failure mode this
    criterion is for.
    """
    weight = CRITERIA_BY_KEY["grounding"].weight
    referenced = _extract_path_references(markdown)
    if not referenced:
        return CriterionScore(
            "grounding",
            CRITERIA_BY_KEY["grounding"].title,
            weight,
            0.0,
            "no file references",
            "Cite the concrete files this stage produced, as backticked paths, in "
            "What I Did and Key Results as well as Files Produced.",
        )

    resolving = [ref for ref in referenced if _listed_file_exists(paths.run_root, ref, artifact_roots)]
    missing = [ref for ref in referenced if ref not in resolving]
    resolution = len(resolving) / len(referenced)

    # Resolution alone saturates at one reference. Breadth is what separates a
    # summary anchored in the run from one that names its single output file.
    breadth = _clamp(len(resolving) / 6.0)
    score = _clamp(0.7 * resolution + 0.3 * breadth)

    observed = f"{len(resolving)}/{len(referenced)} referenced paths resolve"
    if missing:
        shortfall = (
            "These referenced paths do not exist: "
            + ", ".join(f"`{item}`" for item in missing[:4])
            + ". Produce the file or stop citing it."
        )
    elif breadth < 1.0:
        shortfall = (
            "Anchor more of the narrative in artifacts: cite the specific file "
            "behind each claim in Key Results, not only the headline output."
        )
    else:
        shortfall = ""
    return CriterionScore("grounding", CRITERIA_BY_KEY["grounding"].title, weight, score, observed, shortfall)


def _artifact_kind_dirs(
    paths: RunPaths, artifact_dirs: Mapping[str, Sequence[Path]] | None
) -> dict[str, tuple[Path, ...]]:
    """Which workspace directory each artifact kind is read from.

    A kind is named after the directory it comes from, so "this stage wrote
    ``literature``" is a claim a reader can check with ``ls``. ``writing`` is the one
    exception: a run's manuscript lives under ``writing/`` in LaTeX mode and under
    ``report/`` in markdown mode, and the two are one kind of work.

    ``artifact_dirs`` is the operator's declaration of where a benchmark harness puts
    its outputs, and only the three categories a benchmark contract can redirect —
    ``data``, ``results``, ``figures`` — accept one.
    """
    extra = artifact_dirs or {}
    return {
        "data": (paths.data_dir, *extra.get("data", ())),
        "results": (paths.results_dir, *extra.get("results", ())),
        "figures": (paths.figures_dir, *extra.get("figures", ())),
        "code": (paths.code_dir,),
        "writing": (paths.writing_dir, paths.report_dir),
        "literature": (paths.literature_dir,),
        "notes": (paths.notes_dir,),
        "artifacts": (paths.artifacts_dir,),
        "reviews": (paths.reviews_dir,),
    }


#: What counts as a file of each kind. The four kinds added here accept ``.md``,
#: because a reading note, an assumption map, a readiness checklist and a release note
#: are markdown and the prompts ask for them in those words. That is not a way in for
#: prose: ``MIN_ARTIFACT_BYTES`` still applies, the file has to be under the directory
#: its stage was pointed at, and the criterion is a set of *kinds* — a second paragraph
#: in a second file moves nothing.
_ARTIFACT_KIND_SUFFIXES: dict[str, set[str]] = {
    "data": MACHINE_DATA_SUFFIXES,
    "results": RESULT_SUFFIXES,
    "figures": FIGURE_SUFFIXES,
    "code": {".py", ".sh", ".r", ".jl", ".ipynb", ".cpp", ".rs", ".go", ".ts", ".js"},
    "writing": {".md", ".tex", ".bib"},
    "literature": {".md", ".json", ".jsonl", ".bib", ".csv", ".tsv", ".yaml", ".yml"},
    "notes": {".md", ".json", ".jsonl", ".csv", ".tsv", ".yaml", ".yml"},
    "artifacts": {".md", ".json", ".jsonl", ".pdf", ".tex", ".zip", ".tar", ".gz"},
    "reviews": {".md", ".json", ".jsonl", ".yaml", ".yml"},
}


#: What each stage is expected to leave behind, by stage number.
#:
#: Every kind named here is a directory that stage's own prompt tells the agent to
#: write to — ``tests/test_rubric_artifact_kinds.py`` reads the ``{{WORKSPACE_*_DIR}}``
#: placeholders out of ``src/prompts/`` and refuses any expectation the prompt never
#: asked for. That is why Stage 03 expects ``data`` and ``notes`` and not ``code``:
#: implementation is Stage 04's job and ``03_study_design.md`` never names the code
#: directory. Scored as a set rather than as a count so that a stage cannot climb by
#: emitting more of the one kind it already had, and so that the shortfall can name
#: the directory that is missing instead of listing every directory in the run.
STAGE_ARTIFACT_KINDS: dict[int, frozenset[str]] = {
    1: frozenset({"literature"}),
    2: frozenset({"literature", "notes"}),
    3: frozenset({"data", "notes"}),
    4: frozenset({"code", "data", "notes"}),
    5: frozenset({"code", "results"}),
    6: frozenset({"figures", "results"}),
    7: frozenset({"artifacts", "writing"}),
    8: frozenset({"artifacts", "reviews", "writing"}),
}


def expected_artifact_kinds(stage: StageSpec) -> frozenset[str]:
    """The kinds this stage is graded on producing. Empty for a stage nobody declared."""
    return STAGE_ARTIFACT_KINDS.get(stage.number, frozenset())


class HarnessWrites(NamedTuple):
    """The files and whole subtrees AutoR itself puts inside a graded directory.

    Two members rather than one set because ``reviews/panel/`` is a *directory* AutoR
    owns — the panel writes one transcript pair per stage per attempt, so the names are
    not enumerable in advance and matching them one by one would leak every second file.
    """

    files: frozenset[Path]
    trees: frozenset[Path]

    def covers(self, path: Path) -> bool:
        return path in self.files or any(tree in path.parents for tree in self.trees)


def _harness_written_records(paths: RunPaths) -> HarnessWrites:
    """Everything AutoR writes for the stage, into directories this criterion now reads.

    :func:`is_autor_own_record` covers the scientific bookkeeping — the six files under
    ``notes/`` and two under ``results/`` that ``RECORD_ARTIFACTS`` lists — and that list
    is about the *experiment bundle*, so these do not belong in it. They are the same
    hazard by a different route: each is written by AutoR's own machinery into a
    directory the stage is graded on, so a stage that produced nothing would collect the
    kind anyway. ``tests/test_rubric_artifact_kinds.py`` drives each writer and censuses
    ``src/`` for a path under a graded directory that this list has not classified.

    Written **before the draft is scored, inside the stage's own window**, so each one
    is a live free kind rather than a hazard in principle:

    - ``notes/idea_pool.{json,md}``: :func:`record_idea_pool` runs while the Stage 02
      prompt is being built, and Stage 02 is graded on ``notes``.
    - ``artifacts/report_review.json`` and ``artifacts/layout_review.json``: the manager
      generates one — which one depends on the output format — after every Stage 07
      attempt, and Stage 07 is graded on ``artifacts``. ``07_writing.md`` says so to the
      agent in as many words: "generated for you by the workflow manager after each
      attempt — read it, do not write it".
    - ``reviews/comment_ledger.json``: ``_close_comment_round`` writes it when an
      anchored-revision round closes, one call above ``consider``.
    - ``reviews/deliberations.json``: ``_settle_cruxes`` writes it in the statement after
      that, still above ``consider``.
    - ``reviews/panel/``: ``ReviewPanel._record`` writes a transcript pair and the effect
      ledger from ``_collect_review_decision``, which runs *after* attempt N is scored
      and therefore before attempt N+1 is.
    - ``reviews/effort.json``: ``_note_effort_failure`` writes it in the same window, on
      the branch where the panel refused.

    And two AutoR records in ``reviews/`` whose current call sites happen to sit after
    the last score of the run. They are excluded on ownership, not on ordering, because
    the ordering is not theirs to keep: ``_report_optional_machinery`` is called from
    ``_complete_run``, and a resumed or revisited walk re-opens a stage window after it.

    - ``reviews/scorecard.{json,md}``: :func:`write_scorecard`.
    - ``reviews/validity_review_<stage>.json``: the adversarial reviewer's own findings,
      about the stage rather than by it.

    Every name is imported from the module that writes it, so a rename cannot leave this
    list pointing at nothing — that is why ``idea_pool.md``, ``report_review.json``,
    ``layout_review.json`` and ``panel/`` gained constants at their writers.
    """
    from .deliberation import LEDGER_FILENAME as DELIBERATION_LEDGER_FILENAME
    from .effort import LEDGER_FILENAME as EFFORT_LEDGER_FILENAME
    from .ideation_panel import IDEA_POOL_FILENAME, IDEA_POOL_MARKDOWN_FILENAME
    from .review_panel import PANEL_DIRNAME
    from .scorecard import SCORECARD_JSON, SCORECARD_MD
    from .stage_comments import COMMENT_LEDGER_FILENAME
    from .validity_review import validity_review_path
    from .writing_manifest import LAYOUT_REVIEW_FILENAME, REPORT_REVIEW_FILENAME

    return HarnessWrites(
        files=frozenset(
            {
                paths.notes_dir / IDEA_POOL_FILENAME,
                paths.notes_dir / IDEA_POOL_MARKDOWN_FILENAME,
                paths.artifacts_dir / REPORT_REVIEW_FILENAME,
                paths.artifacts_dir / LAYOUT_REVIEW_FILENAME,
                paths.reviews_dir / COMMENT_LEDGER_FILENAME,
                paths.reviews_dir / DELIBERATION_LEDGER_FILENAME,
                paths.reviews_dir / EFFORT_LEDGER_FILENAME,
                paths.reviews_dir / SCORECARD_JSON,
                paths.reviews_dir / SCORECARD_MD,
                # One per stage: the reviewer names the file after the stage it read, so
                # the set is derived from `STAGES` rather than from a glob, which would
                # also swallow the *response* the stage itself writes beside it.
                *(validity_review_path(paths, stage.slug) for stage in STAGES),
            }
        ),
        trees=frozenset({paths.reviews_dir / PANEL_DIRNAME}),
    )


def _fresh_artifact_kinds(
    paths: RunPaths,
    stage: StageSpec,
    artifact_dirs: Mapping[str, Sequence[Path]] | None,
) -> tuple[set[str], set[str]]:
    """Which artifact kinds exist, and which were written during this stage.

    Freshness matters because the run tree accumulates. Without a cutoff, Stage 07
    would score full marks on figures Stage 06 produced, and a stage that did
    nothing at all would be indistinguishable from one that did.
    """
    cutoff = stage_execution_started_at(paths, stage)
    kinds = _artifact_kind_dirs(paths, artifact_dirs)
    harness_written = _harness_written_records(paths)

    present: set[str] = set()
    fresh: set[str] = set()
    for kind, directories in kinds.items():
        allowed = _ARTIFACT_KIND_SUFFIXES[kind]
        for directory in directories:
            for path in _existing_files(directory):
                if path.suffix.lower() not in allowed:
                    continue
                # AutoR's own bookkeeping is not the stage's output. Per-file rather
                # than by pruning the directory, because `artifact_dirs` are
                # operator-declared and may point anywhere.
                if is_autor_own_record(paths, path) or harness_written.covers(path):
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                # A zero-byte file is the cheapest possible way to satisfy a gate
                # that counts, so it does not count.
                if stat.st_size < MIN_ARTIFACT_BYTES:
                    continue
                present.add(kind)
                if cutoff is None or stat.st_mtime >= cutoff:
                    fresh.add(kind)
    return present, fresh


def _score_artifact_breadth(
    paths: RunPaths,
    stage: StageSpec,
    artifact_dirs: Mapping[str, Sequence[Path]] | None,
) -> CriterionScore:
    """The kinds this stage's own prompt asked for, written inside its own window.

    Scored against :data:`STAGE_ARTIFACT_KINDS` rather than against a count of any
    two or three kinds. The count was wrong in both directions at the ends of the
    graph. It could not see ``literature/``, ``notes/``, ``artifacts/`` or
    ``reviews/`` at all, so a Stage 08 was graded on whichever part of its release
    bundle happened to land in ``writing/`` — one kind of the three it owes, or none
    at all, in which case it was told "every artifact in the run predates this
    stage's execution" while the bundle sat on disk seconds old. And it credited a
    Stage 06 that wrote ``code/`` and ``notes/`` and no figures with one of its
    three, because any three kinds were worth the same as the three the analysis
    stage owes. Both numbers are replays against ``origin/main@fdded57``;
    ``tests/test_rubric_artifact_kinds.py`` carries the trees they were taken on.
    """
    weight = CRITERIA_BY_KEY["artifact_breadth"].weight
    present, fresh = _fresh_artifact_kinds(paths, stage, artifact_dirs)
    expected = expected_artifact_kinds(stage)
    if not expected:
        return CriterionScore(
            "artifact_breadth",
            CRITERIA_BY_KEY["artifact_breadth"].title,
            weight,
            1.0,
            "no artifact kinds are declared for this stage",
        )

    earned = fresh & expected
    missing = expected - fresh
    score = _clamp(len(earned) / len(expected))
    observed = (
        f"{len(earned)}/{len(expected)} expected artifact kind(s) written during this stage "
        f"({', '.join(sorted(earned)) or 'none'}); {len(present)} kind(s) present overall"
    )
    if score >= 1.0:
        shortfall = ""
    elif not fresh and present:
        shortfall = (
            "Every artifact in the run predates this stage's execution. Produce or "
            "update the files this stage is responsible for: "
            + ", ".join(f"`workspace/{kind}/`" for kind in sorted(missing))
            + "."
        )
    else:
        shortfall = (
            f"{len(earned)} of the {len(expected)} artifact kinds this stage is responsible "
            "for were written here. Write the missing ones — "
            + ", ".join(f"`workspace/{kind}/`" for kind in sorted(missing))
            + " — as files, rather than describing them in prose."
        )
    return CriterionScore(
        "artifact_breadth", CRITERIA_BY_KEY["artifact_breadth"].title, weight, score, observed, shortfall
    )


def _score_quantification(markdown: str) -> CriterionScore:
    """Key Results has to contain results, in the sense of numbers.

    Scored on Key Results alone. Counting quantities across the whole document
    would let a Study Design section full of budget figures stand in for having
    measured anything.
    """
    weight = CRITERIA_BY_KEY["quantification"].weight
    section = extract_markdown_section(markdown, "Key Results") or ""
    united = len(_QUANTITY_PATTERN.findall(section))
    named = len(_NAMED_QUANTITY_PATTERN.findall(section))
    quantities = united + named
    score = _clamp(quantities / 6.0)
    observed = f"{quantities} quantified statement(s) in Key Results"
    if score >= 1.0:
        shortfall = ""
    elif quantities == 0:
        shortfall = (
            "Key Results states no measured quantity. Report the numbers: the metric, "
            "the value, the comparison, and how many runs it is over."
        )
    else:
        shortfall = (
            "Key Results is mostly narrative. Give each finding its number, its baseline "
            "comparison, and its spread across repeats."
        )
    return CriterionScore(
        "quantification", CRITERIA_BY_KEY["quantification"].title, weight, score, observed, shortfall
    )


def _artifact_numbers(paths: RunPaths) -> set[float]:
    """Every number recorded in a machine-readable result artifact.

    Read from the files themselves rather than from anything the stage wrote in
    prose, because the point is to have a source of truth the draft did not author.
    """
    values: set[float] = set()

    def absorb(node: Any) -> None:
        if isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            values.add(float(node))
        elif isinstance(node, Mapping):
            for item in node.values():
                absorb(item)
        elif isinstance(node, (list, tuple)):
            for item in node:
                absorb(item)
        elif isinstance(node, str):
            for token in re.findall(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", node):
                try:
                    values.add(float(token))
                except ValueError:
                    continue

    for directory in (paths.results_dir, paths.data_dir):
        for path in _existing_files(directory):
            suffix = path.suffix.lower()
            if suffix not in {".json", ".jsonl", ".csv", ".tsv", ".yaml", ".yml", ".txt"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if suffix == ".json":
                parsed = _load_json(path)
                if parsed is not None:
                    absorb(parsed)
                    continue
            absorb(text)
    return values


#: Identifiers that carry a "." but measure nothing: arXiv ids, DOIs, version strings,
#: equation and section references. Admitting them makes ``numeric_fidelity`` demand that
#: the paper a task is *about* appear in a results file, so the cheapest way to raise the
#: criterion is to delete the research subject's name from the prose. Measured on a
#: controlled pair at Stage 06, everything else held fixed: a draft ending "on the
#: 2111.01152 system" totals 0.7587, with ``numeric_fidelity`` 0.67 and the shortfall
#: "These reported values appear in no results artifact: 2111.01152"; the same draft
#: ending "on the target system" totals 0.8063. That +0.0476 is 9.5x
#: ``DEFAULT_MIN_GAIN``, so the ratchet records the deletion of the paper's identity as a
#: new champion.
#: The left boundary is load-bearing and was missing when this landed. Without it the
#: alternative ``v`` matched the *tail* of CV, PV, HIV, dev, MeV and .csv, ``table``
#: matched stable and suitable, ``section`` matched cross-section. Measured over the 263
#: archived stage drafts, 29 numeric tokens across 11 of the 40 runs were silently
#: dropped that way -- and it cut both ways: an invented number written "CV 0.821"
#: escaped ``numeric_fidelity`` entirely, worth +0.0476 of total for one word, which is
#: the same size as the gradient this filter was added to remove; and an honest on-disk
#: "CV 0.0230" stopped counting as an answer for ``deliverable_coverage``.
_IDENTIFIER_PREFIX = re.compile(
    # The hyphen is in the boundary class too, or `section` matches `cross-section`.
    r"(?<![A-Za-z0-9_-])"
    r"(?:arxiv|doi|fig|figure|eq|eqn|equation|table|section|sec|ref|v|#)\s*[.:]?\s*$",
    re.IGNORECASE,
)

#: An arXiv identifier written bare, as a task naming its subject paper writes it:
#: `the 2111.01152 system`. Four digits, a dot, four or five digits. A real measurement
#: of that exact shape is excluded from the check rather than failed by it, which costs a
#: check and not a score.
_ARXIV_ID = re.compile(r"^\d{4}\.\d{4,5}$")


#: Reported values that are almost never measurements: seed counts, epoch counts,
#: years, section numbers. Penalising a draft for saying "5 seeds" when no artifact
#: happens to contain a bare 5 would make the criterion noise.
def _is_measurement_like(raw: str, value: float, *, prefix: str = "") -> bool:
    if _ARXIV_ID.match(raw):
        return False
    if prefix and _IDENTIFIER_PREFIX.search(prefix):
        return False
    if "." in raw:
        return True
    return abs(value) >= 1000


def _matches_artifact_number(value: float, raw: str, percent: bool, known: set[float]) -> bool:
    """Whether a reported value is one an artifact on disk actually holds.

    Tolerance is one half of the last reported decimal place, and a percentage is
    matched against its fraction too, so `74.1%` is satisfied by `0.741` in a results
    file. Anything looser would accept a number that merely resembles one that was
    measured. Module-level because two criteria ask this question --
    :func:`_score_numeric_fidelity` about every number in the draft, and
    :func:`_score_deliverable_coverage` about the one number a demand's answer carries --
    and two encodings of one rule drift.
    """
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    tolerance = max(0.5 * (10 ** -decimals), abs(value) * 1e-9)
    for candidate in (value, value / 100.0) if percent else (value,):
        scale = max(0.5 * (10 ** -decimals) / 100.0, tolerance) if candidate != value else tolerance
        if any(abs(candidate - known_value) <= scale for known_value in known):
            return True
    return False


def _score_numeric_fidelity(markdown: str, paths: RunPaths) -> CriterionScore:
    """Every number the draft reports has to appear in an artifact it did not write.

    This is the check that catches the failure mode independent evaluations keep
    finding in automated science: a fluent write-up quoting metrics that exist
    nowhere in the run. Every other gate here passes such a draft — the sections
    are present, the files it names exist, the prose is quantified. The number
    itself is simply invented, and only a comparison against the raw outputs sees
    it.

    The tolerance rule lives in :func:`_matches_artifact_number`.
    """
    weight = CRITERIA_BY_KEY["numeric_fidelity"].weight
    section = "\n".join(
        extract_markdown_section(markdown, heading) or ""
        for heading in ("Key Results", "What I Did")
    )
    # Strip backticked spans: a path like `results/run_05.json` and a command line
    # are not claims about a measured value.
    section = re.sub(r"`[^`\n]*`", " ", section)

    reported: list[tuple[str, float, bool]] = []
    for match in re.finditer(r"(?<![\w.])([-+]?\d+(?:\.\d+)?)\s*(%?)", section):
        raw, percent = match.group(1), bool(match.group(2))
        try:
            value = float(raw)
        except ValueError:
            continue
        if not _is_measurement_like(raw, value, prefix=section[max(0, match.start() - 24):match.start()]):
            continue
        reported.append((raw, value, percent))

    if not reported:
        return CriterionScore(
            "numeric_fidelity",
            CRITERIA_BY_KEY["numeric_fidelity"].title,
            weight,
            0.0,
            "no measured value reported",
            "Report the measured values in Key Results, and make sure each one also appears "
            "in a file under workspace/results so a reader can check it.",
        )

    known = _artifact_numbers(paths)
    if not known:
        return CriterionScore(
            "numeric_fidelity",
            CRITERIA_BY_KEY["numeric_fidelity"].title,
            weight,
            0.0,
            f"{len(reported)} reported value(s), no machine-readable results to check them against",
            "Write the raw measurements to workspace/results as JSON or CSV. A number that "
            "appears only in the summary cannot be verified by anyone, including the next stage.",
        )

    unmatched = [
        raw for raw, value, percent in reported if not _matches_artifact_number(value, raw, percent, known)
    ]
    score = _clamp((len(reported) - len(unmatched)) / len(reported))
    observed = f"{len(reported) - len(unmatched)}/{len(reported)} reported values found in results artifacts"
    shortfall = (
        ""
        if not unmatched
        else (
            "These reported values appear in no results artifact: "
            + ", ".join(unmatched[:6])
            + ". Either write the raw measurement to workspace/results, or correct the number. "
            "Do not restate it more confidently."
        )
    )
    return CriterionScore(
        "numeric_fidelity", CRITERIA_BY_KEY["numeric_fidelity"].title, weight, score, observed, shortfall
    )


#: Words a demand shares with every research report ever written. A demand's terms are
#: what makes it *that* demand; "produce a report with figures" is not a subject.
_PROCESS_WORDS = frozenset({
    "report", "reports", "figure", "figures", "analysis", "analyses", "result", "results",
    "study", "studies", "task", "tasks", "paper", "papers", "method", "methods",
    "section", "sections", "output", "outputs", "input", "inputs", "file", "files",
    "plot", "plots", "image", "images", "work", "run", "runs", "stage", "stages",
    "model", "models", "code", "notebook", "workspace", "deliverable", "deliverables",
    "data", "dataset", "datasets", "goal", "goals", "scientific", "research",
})


def _demand_terms(demands: Sequence[str]) -> list[set[str]]:
    """The words that distinguish each demand from the others in the same task.

    A term shared by more than half the demands is the task's own vocabulary -- every
    demand in a protein task says "protein" -- and matching on it would score a report
    that mentions the subject once as having answered everything.
    """
    from .deliverables import _content_words

    per_demand = [_content_words(demand) - _PROCESS_WORDS for demand in demands]
    frequency: dict[str, int] = {}
    for words in per_demand:
        for word in words:
            frequency[word] = frequency.get(word, 0) + 1
    ceiling = max(1, len(demands) // 2)
    narrowed: list[set[str]] = []
    for words in per_demand:
        distinctive = {word for word in words if frequency[word] <= ceiling}
        narrowed.append(distinctive or words)
    return narrowed


def _score_deliverable_coverage(
    markdown: str,
    paths: RunPaths,
    artifact_roots: Sequence[Path] | None = None,
) -> CriterionScore:
    """Does the draft speak to what the task asked for, and with a number?

    The gap this fills. Every other criterion here measures the run against its own
    record: whether the references it wrote resolve, whether the ledger it wrote is
    populated, whether the numbers it reported trace to the files it produced. A run
    that studied the wrong question rigorously scores 1.000 on all eight -- measured, on
    a draft whose `What I Did` says in its own words that it did not do the task. The
    external judge scored that run 0.0.

    So this criterion, alone among them, reads a document the run did not write: the
    task statement. For each demand in it, the draft must have a sentence *about* that
    demand, and that sentence must also land on disk -- a number an artifact holds, or a
    file the run wrote. Both halves matter, and each is worth half: without the second,
    the criterion is moved by keyword-stuffing; without the first, it is
    `numeric_fidelity` again.

    **How far prose can move it, measured rather than asserted.** Every figure below comes
    from ``python tools/rubric_replay.py`` over the 40 archived runs, and the tool exists
    because this docstring has twice carried a number that did not re-derive.

    A draft of one restated demand per line -- no numbers, no files, no work -- averages
    **0.51**. That is the designed half: a report that names what the task asked for does
    beat one silent about it, and the other half cannot be bought with words. Four
    cheaper routes were open at one time or another and are closed:

    * a sentence made of nothing but the demand's own vocabulary is not engagement (it
      scored **1.000** at every stage below 05, on 40 of 40 tasks, in v6);
    * a sentence that is an eight-word span of the task statement does not count (pasting
      the whole task statement moves the total by a median of **-0.0025**);
    * a sentence carrying this criterion's own shortfall does not count. That one was the
      worst: the ratchet prints the shortfall into the next polish prompt, so pasting it
      back raised the *total* on 88 of the 118 v6 drafts that had one, median **+0.036**,
      all past ``DEFAULT_MIN_GAIN``. It now moves **0 of 173** past that threshold. The
      shortfall names demands by number for this reason -- an index has nothing in it to
      match;
    * citing a path that merely *resolves* -- ``/etc/hostname``, or the stage's own
      summary under ``stages/`` -- took the criterion to 1.000 on 263 of 263 drafts for a
      median total gain of +0.0476, against a median +0.0221 for a real polish round in
      the same archive. :func:`_result_file_cited` asks who wrote the file, and the same
      injection now scores exactly what the same sentences score with no citation at all.

    **What remains, stated rather than closed.** Adding one sentence per demand that
    merely *mentions* it still gains up to **+0.094** of the stage total, on 88 of 263
    drafts. That is the free half doing what it is for, and it is the largest gradient
    left; a criterion where mentioning earned nothing would also refuse the honest report
    that says a requirement could not be met and why, which the rest of this design
    requires to stay valid. A fitness function whose own feedback is a recipe for beating
    it is the failure this module exists to prevent, reached twice from directions the
    design did not consider -- after :func:`_cap_quantification_by_fidelity` and again
    here -- so the number is published rather than the claim that there is none.

    Verdict-blind, and structurally so: nothing here opens
    ``paths.hypothesis_outcomes`` or reads an :data:`OUTCOME_BLIND_FIELDS` key. A
    refuted answer with a traceable number scores exactly what a supported one does,
    which is the property the module docstring exists to protect. The demand verbs on
    the task side include `verify`, `validate` and `demonstrate`; they are read off the
    *task*, never off the draft, so no phrasing of a result can reach them.

    Not a gate, deliberately. #208 measured four mechanical task-completion gates against
    twelve scored runs and every one of them would have blocked the best run in the set;
    partial credit into the champion ratchet is the form that survives that finding.
    """
    from .deliverables import task_demands
    from .utils import task_statement

    weight = CRITERIA_BY_KEY["deliverable_coverage"].weight
    key = "deliverable_coverage"
    title = CRITERIA_BY_KEY[key].title

    demands = task_demands(task_statement(read_text(paths.user_input)))
    if not demands:
        return CriterionScore(
            key, title, weight, 1.0, "no demand sentence in the task statement", ""
        )

    body = "\n".join(
        extract_markdown_section(markdown, heading) or ""
        for heading in ("Objective", "What I Did", "Key Results")
    )
    # Backticked spans are kept, unlike in `numeric_fidelity`: a demand whose answer is
    # an *object* rather than a statistic is answered by the file holding the object, and
    # that reference is written in backticks.
    normalized_task = " ".join(read_text(paths.user_input).split()).casefold()
    sentences = [
        sentence
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", body)
        if sentence.strip() and not _is_quoted_from(sentence, normalized_task)
    ]
    known = _artifact_numbers(paths)

    from .deliverables import _content_words

    engaged: list[str] = []
    answered: list[str] = []
    for demand, terms in zip(demands, _demand_terms(demands)):
        if not terms:
            engaged.append(demand)
            answered.append(demand)
            continue
        need = min(2, len(terms))
        hit = False
        landed = False
        for sentence in sentences:
            words = _content_words(sentence)
            if len(words & terms) < need:
                continue
            if _sentence_lands_on_disk(sentence, known, paths, artifact_roots):
                # Evidence needs no vocabulary test. "The quasiparticle gap is 41.7 meV"
                # is made of nothing but the demand's own nouns and a number, and it is
                # the answer.
                hit = landed = True
                break
            # An *unsupported* sentence made of nothing but the demand's own vocabulary
            # says the demand back. The free half is for having something of the run's
            # own to say, so at least one content word has to come from somewhere other
            # than the ask. Without this, a draft of one restated demand per line scored
            # 1.000 at every stage below 05, on 40 of 40 archived tasks, with no work.
            if words - terms - _PROCESS_WORDS:
                hit = True
        if hit:
            engaged.append(demand)
        if landed:
            answered.append(demand)

    total = len(demands)
    score = _clamp((len(engaged) + len(answered)) / (2 * total))

    missing = [
        index for index, demand in enumerate(demands, start=1) if demand not in engaged
    ]
    unanswered = [
        index
        for index, demand in enumerate(demands, start=1)
        if demand in engaged and demand not in answered
    ]
    observed = (
        f"{len(engaged)}/{total} of the task's demands are spoken to, "
        f"{len(answered)}/{total} by something on disk"
    )
    # The shortfall names demands by their *number* in the `# What the Task Asks For`
    # block every stage prompt already carries. It carried the demand's text once, and
    # once its subject words; the ratchet prints the shortfall into the next polish
    # prompt, so both times the feedback was a phrase that could be pasted back for
    # engagement credit. An index cannot be pasted into a sentence about the demand --
    # there is nothing in it to match -- and it is no less actionable, because the
    # numbered list it refers to is in the same prompt.
    if score >= 1.0:
        shortfall = ""
    elif missing:
        shortfall = (
            f"Key Results says nothing about demand {_numbers(missing)} of "
            f"`# What the Task Asks For`. Report the result for it, with the number or the "
            "result file that carries it, or say that it could not be produced and why."
        )
    else:
        shortfall = (
            f"Demand {_numbers(unanswered)} of `# What the Task Asks For` is discussed with "
            "nothing checkable behind it. Give the number the run measured for it, or name "
            "the result file this run wrote that holds the answer."
        )
    return CriterionScore(key, title, weight, score, observed, shortfall)


def _numbers(indices: Sequence[int]) -> str:
    """`2`, or `2 and 4`, or `2, 4 and 5`."""
    listed = [str(index) for index in indices[:4]]
    if len(listed) == 1:
        return listed[0]
    return ", ".join(listed[:-1]) + " and " + listed[-1]


#: How much of a sentence has to be a contiguous span of the task statement before it
#: stops counting as the run's own words.
_QUOTE_RUN_WORDS = 8

#: Fixed spans of this criterion's own shortfall templates. The ratchet prints the
#: shortfall into the polish prompt, so anything the shortfall says is text the next
#: draft has in front of it -- and pasting it back used to raise the *total* on every
#: draft it was tried on, median +0.069, all of them past ``DEFAULT_MIN_GAIN``. A fitness
#: function whose own feedback is a recipe for beating it is the failure this module's
#: docstring exists to prevent, arrived at from a direction the design did not consider.
_SHORTFALL_MARKERS = (
    "of `# what the task asks for`",
    "of # what the task asks for",
)


def _is_quoted_from(sentence: str, normalized_task: str) -> bool:
    """Whether a sentence is the task statement, or this criterion's own complaint, handed back.

    Quoting the ask is not answering it, and quoting the grader is not answering it
    either.
    """
    normalized = " ".join(sentence.split()).casefold()
    if any(marker in normalized for marker in _SHORTFALL_MARKERS):
        return True
    words = normalized.split()
    if len(words) < _QUOTE_RUN_WORDS:
        return False
    for start in range(len(words) - _QUOTE_RUN_WORDS + 1):
        if " ".join(words[start : start + _QUOTE_RUN_WORDS]) in normalized_task:
            return True
    return False


def _sentence_lands_on_disk(
    sentence: str,
    known: set[float],
    paths: RunPaths,
    artifact_roots: Sequence[Path] | None = None,
) -> bool:
    """Whether a sentence's answer exists outside the sentence.

    Either a measurement an artifact on disk also holds, or a reference to a file **this
    run produced as a result**. The second disjunct is not slack: a task that names an
    *object* as its output -- a derivation, an equation set, a table, a sequence -- has no
    statistic to report, and a criterion that only accepted numbers would cap exactly the
    deliverable it exists to protect at half marks.

    "Produced as a result" is the whole of it, and the first version asked the wrong
    question. It called :func:`_listed_file_exists` against the run root, which answers
    *does this path resolve* -- so one sentence per demand citing ``/etc/hostname``, or
    the stage's own summary under ``stages/``, took the criterion to 1.000 on 263 of 263
    archived drafts for a median total gain of +0.0476. A real polish round in the same
    archive gained a median +0.0221, so writing four sentences was worth twice doing the
    work. :func:`_result_file_cited` asks who wrote the file instead.
    """
    stripped = re.sub(r"`[^`\n]*`", " ", sentence)
    for match in re.finditer(r"(?<![\w.])([-+]?\d+(?:\.\d+)?)\s*(%?)", stripped):
        raw, percent = match.group(1), bool(match.group(2))
        try:
            value = float(raw)
        except ValueError:
            continue
        prefix = stripped[max(0, match.start() - 24):match.start()]
        if not _is_measurement_like(raw, value, prefix=prefix):
            continue
        if _matches_artifact_number(value, raw, percent, known):
            return True
    return _result_file_cited(sentence, paths, artifact_roots)


def _result_file_cited(
    sentence: str, paths: RunPaths, artifact_roots: Sequence[Path] | None = None
) -> bool:
    """Whether a sentence names a file this run wrote *as a result*.

    Three narrowings against "the path resolves", each closing a measured route to a free
    score. An absolute path is refused outright -- ``/etc/hostname`` is on every machine.
    The path must land under one of the run's own output directories, so a benchmark's
    read-only input under ``data/`` is not an answer the run produced. And AutoR's own
    record files are excluded: ``stages/``, ``artifacts/``, ``notes/`` and ``reviews/``
    exist on every run by construction, so citing them would price bookkeeping as
    evidence -- the substitution this whole criterion exists to catch, arrived at through
    the criterion itself.
    """
    roots = [paths.results_dir, paths.figures_dir, paths.report_dir, paths.literature_dir]
    for extra in artifact_roots or ():
        roots.extend(
            extra / name for name in ("results", "figures", "report", "outputs", "literature")
        )
    resolved_roots = [root.resolve() for root in roots]

    for reference in _extract_path_references(sentence):
        candidate = PurePosixPath(reference.strip())
        if candidate.is_absolute():
            continue
        for base in (paths.run_root, paths.workspace_root, *(artifact_roots or ())):
            target = (base / reference).resolve()
            if not target.is_file():
                continue
            if any(
                target == root or root in target.parents
                for root in resolved_roots
            ):
                return True
    return False


def _score_traceability(markdown: str) -> CriterionScore:
    """The four decision-ledger buckets, filled and saying different things.

    The shipped gate checks the four headings are present. The failure it cannot
    see is a ledger whose four buckets contain the same sentence, or three of
    which say "None" — which is what an agent writes when it is satisfying a
    heading rather than recording a decision.
    """
    weight = CRITERIA_BY_KEY["traceability"].weight
    section = extract_markdown_section(markdown, "Decision Ledger") or ""
    filled: list[str] = []
    empty: list[str] = []
    for bucket in _DECISION_LEDGER_BUCKETS:
        pattern = re.compile(
            rf"{re.escape(bucket)}\s*:?\s*\**\s*\n?(.*?)(?=(?:{'|'.join(re.escape(other) for other in _DECISION_LEDGER_BUCKETS)})|\Z)",
            flags=re.DOTALL | re.IGNORECASE,
        )
        match = pattern.search(section)
        body = (match.group(1) if match else "").strip(" \n\t-*:")
        normalized = re.sub(r"\s+", " ", body.lower()).strip(" .-")
        if len(normalized) < 12 or normalized in {"none", "n/a", "na", "nothing", "none yet", "tbd"}:
            empty.append(bucket)
        else:
            filled.append(normalized)

    distinct = len({item[:120] for item in filled})
    score = _clamp(distinct / len(_DECISION_LEDGER_BUCKETS))
    observed = f"{distinct}/{len(_DECISION_LEDGER_BUCKETS)} decision-ledger buckets carry distinct content"
    if score >= 1.0:
        shortfall = ""
    elif empty:
        shortfall = (
            "These decision-ledger buckets are empty or say nothing: "
            + ", ".join(empty)
            + ". Record the decision that was actually taken, or state that none was and why."
        )
    else:
        shortfall = (
            "The decision-ledger buckets repeat each other. An assumption, a locked "
            "decision, and a rejected alternative are three different things."
        )
    return CriterionScore(
        "traceability", CRITERIA_BY_KEY["traceability"].title, weight, score, observed, shortfall
    )


#: A sentence that describes work rather than surrounding it: it carries a quantity, or
#: it names a path. Used as the denominator of :func:`_score_commitment` in place of a
#: word count — see that function for why the word count had to go.
_WORK_BEARING_PATH = re.compile(r"`[^`]*[/.][^`]*`")

#: Work-bearing sentences per unit of hedge allowance. Calibrated, not chosen: on the
#: four stage summaries of the first real backend run, ``work / 4`` reproduces the old
#: ``words / 200`` to within a factor of one (8.05 against 9.50, 16.75 against 15.50,
#: 15.74 against 14.75), so a genuinely dense report keeps the allowance it had. Stage
#: 04 comes out twice as generous, which is the right direction: it earned it in short
#: lines naming files.
_SENTENCES_PER_ALLOWANCE = 4.0


def _work_bearing_sentences(body: str) -> int:
    """Sentences that say what was done, as opposed to sentences that are present."""
    return sum(
        1
        for sentence in re.split(r"(?<=[.!?])\s+|\n", body)
        if sentence.strip()
        and (
            _QUANTITY_PATTERN.search(sentence)
            or _NAMED_QUANTITY_PATTERN.search(sentence)
            or _WORK_BEARING_PATH.search(sentence)
        )
    )


def _score_commitment(markdown: str) -> CriterionScore:
    """Density of intention over report, in the sections describing work done.

    Density over *work*, not over words, and the difference is the whole point.

    The allowance used to be ``words / 200``, which put a length gradient inside a
    criterion the improvement prompt promises has none — ``src/evolution.py`` tells the
    agent, every polish round, that "every criterion here is a ratio or a count over
    artifacts on disk; prose cannot move any of them". Measured before this change, on
    one hedge held fixed while clean prose was added around it: 149 words scored 0.8000,
    677 scored 0.9409, 2,789 scored 0.9857. That is +0.0253 on a Stage 01 total against
    a ``DEFAULT_MIN_GAIN`` of 0.02, so `EvolutionController.consider` recorded a round
    that added nothing but words as ``promoted``, "New champion". The prohibition was
    written down and the gradient rewarded breaking it.

    Counting work-bearing sentences instead closes it for prose specifically: padding
    adds sentences that carry no quantity and name no path, so it moves the numerator
    and the denominator not at all. Buying allowance now requires writing quantities
    that were not measured, which is a different move, is what ``quantification`` and
    ``numeric_fidelity`` are for, and leaves a trace in the report rather than in its
    length.
    """
    weight = CRITERIA_BY_KEY["commitment"].weight
    body = "\n".join(
        extract_markdown_section(markdown, heading) or ""
        for heading in ("What I Did", "Key Results")
    )
    words = len(body.split())
    working = _work_bearing_sentences(body)
    hedges = sum(len(re.findall(pattern, body, flags=re.IGNORECASE)) for pattern in _HEDGE_PATTERNS)
    # One hedge per four sentences of described work is ordinary scientific caution.
    # Six is a plan.
    allowance = max(working / _SENTENCES_PER_ALLOWANCE, 1.0)
    score = _clamp(1.0 - (hedges / (allowance * 5.0)))
    observed = (
        f"{hedges} forward-looking phrase(s) against {working} sentence(s) carrying a "
        f"quantity or a path, in {words} words of What I Did / Key Results"
    )
    shortfall = (
        ""
        if score >= 1.0
        else (
            "What I Did and Key Results describe intentions rather than completed work. "
            "State what was run and what came out; move anything not yet done into "
            "Suggestions for Refinement."
        )
    )
    return CriterionScore(
        "commitment", CRITERIA_BY_KEY["commitment"].title, weight, score, observed, shortfall
    )


def _empirical_hypotheses(
    paths: RunPaths, stage: StageSpec, markdown: str
) -> list["HypothesisEntry"]:
    """The empirical hypotheses this draft is answerable for.

    At Stage 02 they are read out of **the draft being scored**, not out of
    ``notes/hypothesis_manifest.json``. ``score_stage`` runs once per candidate, and
    a polish round that gets reverted leaves the loser's manifest on disk — scoring
    the new draft against the old file would grade a document nobody wrote. From
    Stage 03 the draft carries no hypothesis sections at all, so the manifest Stage 02
    left behind is the only copy, and it is the one Stage 04 will freeze.

    Every read is defensive by construction. ``score_stage`` has no ``try`` around it
    and a hand-edited manifest is a file the agent can write, so a corrupt one has to
    cost the criterion rather than end the run.
    """
    from .hypothesis_manifest import HypothesisEntry, build_hypothesis_manifest

    if stage.number == 2:
        manifest = build_hypothesis_manifest(markdown)
        return list(manifest.empirical_hypotheses) if manifest is not None else []

    payload = _load_json(paths.hypothesis_manifest)
    section = payload.get("empirical_hypotheses") if isinstance(payload, dict) else None
    if not isinstance(section, list):
        return []
    return [HypothesisEntry.from_dict(item) for item in section if isinstance(item, dict)]


def _score_reproducibility(paths: RunPaths, stage: StageSpec, markdown: str) -> CriterionScore:
    """The machine-readable validity chain that applies at this stage.

    Each check is a boolean over an artifact that either exists and parses or does
    not. Nothing here reads a verdict value; Stage 06's check is that every
    adjudication points at a file, not that it points at a favourable one.
    """
    weight = CRITERIA_BY_KEY["reproducibility"].weight
    checks: list[tuple[str, bool, str]] = []

    if stage.number >= 1:
        # Delegated rather than reimplemented. An earlier version of this check
        # looked for `workspace/literature/evidence_ledger.json`, a file no part of
        # AutoR writes, so it failed on every run and docked the criterion for work
        # that had in fact been done. `validate_literature_evidence` is the shipped
        # definition of what a literature evidence base has to be; there should not
        # be a second one here to drift from it.
        from .evidence_ledger import validate_literature_evidence

        checks.append(
            (
                "literature evidence base",
                not validate_literature_evidence(paths),
                "Write workspace/literature/sources.json and claims.json so each claim names the "
                "source_ids behind it.",
            )
        )
    if 2 <= stage.number <= 3:
        # The graded twin of the Stage 02+ gate in `validate_stage_artifacts`. Stages
        # 2-3 only, and not `>= 2`: from Stage 04 the same hypothesis set is measured
        # by the frozen-preregistration link below, and scoring both would spend two
        # of this criterion's links on one artifact — the run would look more
        # reproducible for having declared its hypotheses twice.
        from .hypothesis_manifest import hypotheses_without_decision_rule

        entries = _empirical_hypotheses(paths, stage, markdown)
        undecided = hypotheses_without_decision_rule(entries)
        named = f" ({', '.join(undecided)})" if undecided else ""
        checks.append(
            (
                "falsifiable hypothesis set",
                bool(entries) and not undecided,
                f"Give every empirical hypothesis{named} a `- Decision rule: ...` line saying "
                "what result would count as support and what would count as refutation. A "
                "hypothesis with no decision rule cannot come out negative, and Stage 04 "
                "freezes the set as it stands.",
            )
        )
    if stage.number >= 3:
        protocol = _load_json(paths.experimental_protocol)
        checks.append(
            (
                "experimental protocol",
                isinstance(protocol, dict) and bool(protocol.get("baselines")),
                "Declare workspace/notes/experimental_protocol.json with a competent baseline and "
                "a tuning budget for each comparison.",
            )
        )
    if stage.number >= 4:
        prereg = _load_json(paths.preregistration)
        checks.append(
            (
                "frozen preregistration",
                isinstance(prereg, dict) and bool(prereg.get("hypotheses")),
                "Fix the hypothesis set before results exist; it is written when Stage 04 is approved.",
            )
        )
    if stage.number >= 5:
        manifest = _load_json(paths.experiment_manifest)
        indexed = manifest.get("result_artifacts") if isinstance(manifest, dict) else None
        checks.append(
            (
                "experiment manifest",
                bool(indexed),
                "Produce result files under workspace/results so experiment_manifest.json indexes "
                "them; a result nothing indexes cannot be found by the analysis stage.",
            )
        )
    if stage.number >= 6:
        outcomes = _verdict_blind_outcomes(paths)
        adjudicated = [item for item in outcomes if item["has_verdict"]]
        evidenced = [
            item
            for item in adjudicated
            if item["evidence"] and all(_evidence_resolves(paths, ref) for ref in item["evidence"])
        ]
        checks.append(
            (
                "adjudicated hypotheses",
                bool(adjudicated) and len(evidenced) == len(adjudicated),
                "Give every preregistered hypothesis a verdict in "
                "workspace/results/hypothesis_outcomes.json, each pointing at a result file that "
                "exists. A refuted hypothesis with clean evidence is a complete outcome; an "
                "unevidenced one is not.",
            )
        )
    if stage.number >= 7:
        provenance = _load_json(paths.claim_provenance)
        claims = provenance.get("claims") if isinstance(provenance, dict) else None
        checks.append(
            (
                "claim provenance",
                isinstance(claims, list) and bool(claims),
                "Map every claim the write-up makes to a preregistered hypothesis or label it "
                "exploratory, in workspace/artifacts/claim_provenance.json.",
            )
        )

    if not checks:
        return CriterionScore(
            "reproducibility", CRITERIA_BY_KEY["reproducibility"].title, weight, 1.0, "no chain links apply yet"
        )

    passing = [name for name, ok, _ in checks if ok]
    failing = [(name, hint) for name, ok, hint in checks if not ok]
    score = len(passing) / len(checks)
    observed = f"{len(passing)}/{len(checks)} validity-chain artifacts in place"
    shortfall = (
        ""
        if not failing
        else "Missing: " + " ".join(f"[{name}] {hint}" for name, hint in failing[:3])
    )
    return CriterionScore(
        "reproducibility", CRITERIA_BY_KEY["reproducibility"].title, weight, score, observed, shortfall
    )


def _evidence_resolves(paths: RunPaths, reference: str) -> bool:
    candidate = reference.lstrip("./")
    return any((base / candidate).is_file() for base in (paths.workspace_root, paths.run_root))


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------


def _cap_quantification_by_fidelity(scores: list[CriterionScore]) -> list[CriterionScore]:
    """A finding is not quantified by a number that checks out against nothing.

    The two criteria measure different things and both are worth keeping visible:
    ``quantification`` asks whether Key Results carries numbers at all,
    ``numeric_fidelity`` asks whether those numbers appear in an artifact the draft
    did not write. Scored independently and then summed, the pair **pays for
    fabrication**, which is the exact opposite of what this module is for:

    ======================================  =============  ================  ==============
    Key Results says                        quantification  numeric_fidelity  weighted, of 5
    ======================================  =============  ================  ==============
    "the method works better"                        0.00              0.00             0.0
    six numbers, no results file to check             1.00              0.00             2.0
    six numbers, all traceable                        1.00              1.00             5.0
    ======================================  =============  ================  ==============

    So inventing six numbers was worth **two weighted points more than honestly
    reporting none**, and the champion ratchet in :mod:`src.evolution` promotes on
    this total. ``numeric_fidelity``'s docstring already anticipated the draft --
    "every other gate here passes such a draft ... the prose is quantified" -- and
    declining to reward it is not the same as declining to pay for it.

    Capping restores the ordering. Where both criteria apply, the share of findings
    that are *quantified* cannot exceed the share of reported numbers that are
    *real*, so the middle row becomes 0.0 and fabrication earns nothing. Both scores
    are still reported separately, with the cap recorded in ``observed``, because a
    stage told only the capped number cannot tell which half to fix.

    Below Stage 05 ``numeric_fidelity`` does not apply and nothing is capped: Stage
    04 legitimately reports parameter counts and budgets before any result exists.
    """
    fidelity = next((item for item in scores if item.key == "numeric_fidelity"), None)
    if fidelity is None:
        return scores
    return [
        replace(
            item,
            score=fidelity.score,
            observed=f"{item.observed}; capped at numeric fidelity ({fidelity.score:.2f})",
        )
        if item.key == "quantification" and item.score > fidelity.score
        else item
        for item in scores
    ]


def score_stage(
    *,
    paths: RunPaths,
    stage: StageSpec,
    markdown: str,
    attempt_no: int = 1,
    artifact_dirs: Mapping[str, Sequence[Path]] | None = None,
    artifact_roots: Sequence[Path] | None = None,
) -> StageScore:
    """Measure one stage draft. Pure read: nothing on disk is modified."""
    scores: list[CriterionScore] = []
    for criterion in CRITERIA:
        if not criterion.applies_to(stage):
            continue
        if criterion.key == "contract":
            scores.append(_score_contract(markdown, stage, paths, artifact_roots))
        elif criterion.key == "grounding":
            scores.append(_score_grounding(markdown, paths, artifact_roots))
        elif criterion.key == "artifact_breadth":
            scores.append(_score_artifact_breadth(paths, stage, artifact_dirs))
        elif criterion.key == "quantification":
            scores.append(_score_quantification(markdown))
        elif criterion.key == "numeric_fidelity":
            scores.append(_score_numeric_fidelity(markdown, paths))
        elif criterion.key == "traceability":
            scores.append(_score_traceability(markdown))
        elif criterion.key == "commitment":
            scores.append(_score_commitment(markdown))
        elif criterion.key == "reproducibility":
            scores.append(_score_reproducibility(paths, stage, markdown))
        elif criterion.key == "deliverable_coverage":
            scores.append(_score_deliverable_coverage(markdown, paths, artifact_roots))

    scores = _cap_quantification_by_fidelity(scores)

    total_weight = sum(item.weight for item in scores) or 1.0
    total = sum(item.score * item.weight for item in scores) / total_weight

    return StageScore(
        stage_slug=stage.slug,
        attempt_no=attempt_no,
        rubric_version=RUBRIC_VERSION,
        criteria=tuple(scores),
        total=total,
        verdict_digest=verdict_digest(paths),
    )


def format_score_for_prompt(score: StageScore, *, limit: int = 4) -> str:
    """Render a score as the operator sees it: worst criteria first, with the ask."""
    lines = [
        f"Measured standing of the current draft: **{score.total:.3f}** "
        f"(rubric v{score.rubric_version}, 0.0-1.0).",
        "",
        "| Criterion | Score | Observed |",
        "| --- | --- | --- |",
    ]
    for item in sorted(score.criteria, key=lambda entry: entry.score):
        lines.append(f"| {item.title} | {item.score:.2f} | {item.observed} |")

    weakest = score.weakest(limit=limit)
    if weakest:
        lines.append("")
        lines.append("Where the points are:")
        for item in weakest:
            lines.append(f"- **{item.title}** ({item.score:.2f}): {item.shortfall}")
    return "\n".join(lines)


def format_score_line(score: StageScore) -> str:
    """One line, for a terminal status or a log heading."""
    parts = ", ".join(f"{item.key}={item.score:.2f}" for item in score.criteria)
    return f"{score.total:.3f} [{parts}]"
