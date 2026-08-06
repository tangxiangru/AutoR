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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .utils import (
    FIGURE_SUFFIXES,
    MACHINE_DATA_SUFFIXES,
    RESULT_SUFFIXES,
    RunPaths,
    StageSpec,
    _existing_files,
    _extract_path_references,
    _listed_file_exists,
    extract_markdown_section,
    stage_execution_started_at,
    validate_stage_markdown,
)


#: Bump when a criterion is added, removed, reweighted, or has its measurement
#: changed. Scores carrying different versions are not comparable, and every
#: consumer that ranks two scores has to refuse to rank across a version change:
#: a reweight would otherwise read as a run that got better or worse overnight.
RUBRIC_VERSION = "1"

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
    Criterion("artifact_breadth", "Artifacts produced this stage", weight=2.0, min_stage=3),
    Criterion("quantification", "Findings carrying numbers", weight=2.0, min_stage=4),
    Criterion("numeric_fidelity", "Reported numbers trace to results", weight=3.0, min_stage=5),
    Criterion("traceability", "Decision ledger", weight=1.5),
    Criterion("commitment", "Reports work, not intentions", weight=1.5),
    Criterion("reproducibility", "Machine-readable validity chain", weight=3.0),
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
    kinds: dict[str, tuple[Path, ...]] = {
        "data": (paths.data_dir, *(artifact_dirs or {}).get("data", ())),
        "results": (paths.results_dir, *(artifact_dirs or {}).get("results", ())),
        "figures": (paths.figures_dir, *(artifact_dirs or {}).get("figures", ())),
        "code": (paths.code_dir,),
        "writing": (paths.writing_dir, paths.report_dir),
    }
    suffixes = {
        "data": MACHINE_DATA_SUFFIXES,
        "results": RESULT_SUFFIXES,
        "figures": FIGURE_SUFFIXES,
        "code": {".py", ".sh", ".r", ".jl", ".ipynb", ".cpp", ".rs", ".go", ".ts", ".js"},
        "writing": {".md", ".tex", ".bib"},
    }

    present: set[str] = set()
    fresh: set[str] = set()
    for kind, directories in kinds.items():
        allowed = suffixes[kind]
        for directory in directories:
            for path in _existing_files(directory):
                if path.suffix.lower() not in allowed:
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
    weight = CRITERIA_BY_KEY["artifact_breadth"].weight
    present, fresh = _fresh_artifact_kinds(paths, stage, artifact_dirs)
    # What a stage is reasonably expected to touch. Scored against an expectation
    # rather than a raw count so a stage cannot climb by emitting more of the one
    # kind it already had.
    expected = 2 if stage.number < 5 else 3
    score = _clamp(len(fresh) / expected)
    observed = (
        f"{len(fresh)} artifact kind(s) written during this stage "
        f"({', '.join(sorted(fresh)) or 'none'}); {len(present)} present overall"
    )
    if score >= 1.0:
        shortfall = ""
    elif not fresh and present:
        shortfall = (
            "Every artifact in the run predates this stage's execution. Produce or "
            "update the files this stage is responsible for."
        )
    else:
        shortfall = (
            f"Only {len(fresh)} of an expected {expected} artifact kinds were written here. "
            "Add the missing machine-readable outputs (data, results, figures, code) rather "
            "than describing them in prose."
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


#: Reported values that are almost never measurements: seed counts, epoch counts,
#: years, section numbers. Penalising a draft for saying "5 seeds" when no artifact
#: happens to contain a bare 5 would make the criterion noise.
def _is_measurement_like(raw: str, value: float) -> bool:
    if "." in raw:
        return True
    return abs(value) >= 1000


def _score_numeric_fidelity(markdown: str, paths: RunPaths) -> CriterionScore:
    """Every number the draft reports has to appear in an artifact it did not write.

    This is the check that catches the failure mode independent evaluations keep
    finding in automated science: a fluent write-up quoting metrics that exist
    nowhere in the run. Every other gate here passes such a draft — the sections
    are present, the files it names exist, the prose is quantified. The number
    itself is simply invented, and only a comparison against the raw outputs sees
    it.

    Tolerance is one half of the last reported decimal place, and a percentage is
    matched against its fraction too, so `74.1%` is satisfied by `0.741` in a
    results file. Anything looser would accept a number that merely resembles one
    that was measured.
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
        if not _is_measurement_like(raw, value):
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

    def matches(value: float, raw: str, percent: bool) -> bool:
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        tolerance = max(0.5 * (10 ** -decimals), abs(value) * 1e-9)
        for candidate in (value, value / 100.0) if percent else (value,):
            scale = max(0.5 * (10 ** -decimals) / 100.0, tolerance) if candidate != value else tolerance
            if any(abs(candidate - known_value) <= scale for known_value in known):
                return True
        return False

    unmatched = [raw for raw, value, percent in reported if not matches(value, raw, percent)]
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


def _score_commitment(markdown: str) -> CriterionScore:
    """Density of intention over report, in the sections describing work done."""
    weight = CRITERIA_BY_KEY["commitment"].weight
    body = "\n".join(
        extract_markdown_section(markdown, heading) or ""
        for heading in ("What I Did", "Key Results")
    )
    words = max(len(body.split()), 1)
    hedges = sum(len(re.findall(pattern, body, flags=re.IGNORECASE)) for pattern in _HEDGE_PATTERNS)
    # One hedge per 200 words is ordinary scientific caution. Six is a plan.
    allowance = max(words / 200.0, 1.0)
    score = _clamp(1.0 - (hedges / (allowance * 5.0)))
    observed = f"{hedges} forward-looking phrase(s) across {words} words of What I Did / Key Results"
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


def _score_reproducibility(paths: RunPaths, stage: StageSpec) -> CriterionScore:
    """The machine-readable validity chain that applies at this stage.

    Each check is a boolean over an artifact that either exists and parses or does
    not. Nothing here reads a verdict value; Stage 06's check is that every
    adjudication points at a file, not that it points at a favourable one.
    """
    weight = CRITERIA_BY_KEY["reproducibility"].weight
    checks: list[tuple[str, bool, str]] = []

    if stage.number >= 1:
        ledger = paths.literature_dir / "evidence_ledger.json"
        checks.append(
            (
                "literature evidence ledger",
                isinstance(_load_json(ledger), (dict, list)),
                "Write workspace/literature/evidence_ledger.json so each cited claim points at a source.",
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
        checks.append(
            (
                "experiment manifest",
                isinstance(manifest, dict) and bool(manifest.get("experiments")),
                "Record every experiment in workspace/results/experiment_manifest.json with its "
                "command, config and seeds.",
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
            scores.append(_score_reproducibility(paths, stage))

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
