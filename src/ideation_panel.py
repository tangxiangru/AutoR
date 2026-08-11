"""Many agents for divergence, not convergence.

:mod:`src.review_panel` seats a room to *converge* on one gate decision. This module does the
opposite job with the same machinery, because the evidence for multi-agent systems points that
way rather than at deliberation.

AgentPanel (`arXiv:2608.03283 <https://arxiv.org/abs/2608.03283>`_) beat centralized multi-agent
debate on two ideation benchmarks, and its own reading of why is not that the agents argued
better. It is that a heterogeneous population *widened the candidate pool* and left the
selecting to a human: "the value of multi-agent scientific systems lies not only in improving
individual responses, but also in expanding and organizing a diverse candidate pool for human
comparison, selection, and refinement." Its measured gains concentrate in **feasibility**
(5.08 vs 4.08 on LiveIdeaBench, 0.28 vs 0.11 on IdeaBench), not originality — more agents did
not produce wilder ideas, they produced more usable ones.

So Stage 02 gets a pool, not a verdict. Proposers work from distinct lenses, blind to each
other, may abstain, and their candidates are deduplicated, scored, and handed to the stage as
material to choose from. Nothing here decides anything.

**The failure mode this is built against.** Havranek and Irsova
(`arXiv:2607.14713 <https://arxiv.org/abs/2607.14713>`_) found a plain single pass beating two
multi-agent tools, and the mechanism they report is that the reports "tended to raise much the
same points". A pool of five restatements of one idea is that null in another costume, so the
first proposer is treated as a single-pass baseline and the pool records how much of itself
the other proposers actually added. When that number is zero, the artifact says so.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .approval_agent import AutomatedReviewer
from .terminal_ui import TerminalUI
from .utils import RunPaths, StageSpec, append_log_entry, read_text, truncate_text, write_text


#: Words too common to carry meaning when deciding whether two hypotheses are the same one.
_STOPWORDS = frozenset(
    """a an and are as at be been but by can for from had has have how if in into is it its
    may not of on or that the their them then there these this to was were what when which
    will with would we our us""".split()
)

#: Jaccard overlap of content words above which two statements are treated as one idea.
#:
#: Calibrated on realistic hypothesis sentences rather than guessed: rewordings of one claim
#: score 0.60-0.78, a related-but-distinct claim about the same variables scores 0.28, and
#: unrelated claims score 0.00. 0.5 sits in that gap, so a restatement collapses and a genuine
#: variant survives. Deliberately blunt — the point is to notice a pool that has collapsed,
#: not to adjudicate whether two phrasings are subtly different.
DUPLICATE_THRESHOLD = 0.5

#: Where the pool lands. Stage 02's own artifacts live under workspace/notes.
IDEA_POOL_FILENAME = "idea_pool.json"


@dataclass(frozen=True)
class ProposerLens:
    """One way of looking for a hypothesis.

    Lenses are the generation-side answer to correlated seats. Five agents asked for "a good
    hypothesis" return five versions of the obvious one; five agents asked for the mechanism,
    the contradiction, the import from another field, the boring explanation, and the regime
    change return five different objects.
    """

    key: str
    title: str
    charter: str
    backend: str | None = None
    model: str | None = None


DEFAULT_LENSES: tuple[ProposerLens, ...] = (
    ProposerLens(
        key="mechanism",
        title="Mechanism",
        charter=(
            "Propose hypotheses about the underlying mechanism — what process would have to be "
            "true for the observed pattern to arise. Prefer a claim that names the moving parts "
            "over one that names the outcome."
        ),
    ),
    ProposerLens(
        key="contrarian",
        title="Contrarian",
        charter=(
            "Propose hypotheses that contradict the expected answer. If the obvious reading of "
            "the goal is X, ask what the world looks like if not-X holds, and what evidence "
            "would already exist if it did. Do not be contrarian for its own sake; be "
            "contrarian where the obvious reading is under-defended."
        ),
    ),
    ProposerLens(
        key="adjacent",
        title="Adjacent Field",
        charter=(
            "Propose hypotheses by importing a mechanism, model, or method that is standard in "
            "a neighbouring field and unusual in this one. Name the field you are borrowing "
            "from and why the analogy holds."
        ),
    ),
    ProposerLens(
        key="null",
        title="Null and Artifact",
        charter=(
            "Propose the boring explanations that must be ruled out before anything interesting "
            "can be claimed: confounds, selection effects, measurement artifacts, and the "
            "possibility that the effect is absent. These are hypotheses, and a study that "
            "cannot exclude them has not found anything."
        ),
    ),
    ProposerLens(
        key="regime",
        title="Regime and Scale",
        charter=(
            "Propose hypotheses about how the effect changes with scale, regime, or population — "
            "where it should strengthen, invert, or vanish. A claim that specifies where it "
            "fails is more testable than one that claims it holds everywhere."
        ),
    ),
)

LENSES_BY_KEY = {lens.key: lens for lens in DEFAULT_LENSES}


@dataclass(frozen=True)
class Candidate:
    idea_id: str
    proposer: str
    proposer_title: str
    backend: str
    model: str
    title: str
    statement: str
    rationale: str = ""
    prediction: str = ""
    novelty: float | None = None
    feasibility: float | None = None
    relevance: float | None = None
    duplicate_of: str | None = None
    #: Filled after Stage 02 is approved: did the stage actually build on this candidate?
    adopted: bool | None = None

    @property
    def mean_score(self) -> float | None:
        scores = [s for s in (self.novelty, self.feasibility, self.relevance) if s is not None]
        return round(sum(scores) / len(scores), 2) if scores else None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["mean_score"] = self.mean_score
        return payload


@dataclass
class IdeaPool:
    candidates: list[Candidate] = field(default_factory=list)
    abstentions: list[str] = field(default_factory=list)
    unreachable: list[str] = field(default_factory=list)
    proposer_calls: int = 0
    baseline_proposer: str = ""

    @property
    def distinct(self) -> list[Candidate]:
        return [candidate for candidate in self.candidates if candidate.duplicate_of is None]

    def ranked(self) -> list[Candidate]:
        """Distinct candidates, best first. Unscored candidates keep their proposal order."""
        return sorted(
            self.distinct,
            key=lambda c: (c.mean_score is None, -(c.mean_score or 0.0)),
        )

    @property
    def adoption_measured(self) -> bool:
        return any(candidate.adopted is not None for candidate in self.distinct)

    def effect(self) -> dict[str, Any]:
        """What the extra proposers added over the first one.

        The first proposer is the single-pass baseline: one lens, one call, no sight of anyone
        else. If every distinct hypothesis in the pool traces back to it, the other proposers
        restated it, and the pool should say so rather than presenting five entries as five
        ideas.
        """
        distinct = self.distinct
        from_baseline = [c for c in distinct if c.proposer == self.baseline_proposer]
        added = [c for c in distinct if c.proposer != self.baseline_proposer]
        proposed = len(self.candidates)
        return {
            "proposed": proposed,
            "distinct": len(distinct),
            "collapsed_as_duplicates": proposed - len(distinct),
            "baseline_proposer": self.baseline_proposer,
            "from_baseline_proposer": len(from_baseline),
            "added_by_other_proposers": len(added),
            "abstentions": len(self.abstentions),
            "unreachable": len(self.unreachable),
            "proposer_calls": self.proposer_calls,
            "adoption_measured": self.adoption_measured,
            "adopted": sum(1 for c in distinct if c.adopted),
            "adopted_from_baseline_proposer": sum(1 for c in from_baseline if c.adopted),
            "adopted_from_other_proposers": sum(1 for c in added if c.adopted),
            "verdict": _pool_verdict(
                distinct=len(distinct),
                added=len(added),
                calls=self.proposer_calls,
                unreachable=len(self.unreachable),
                seated=len(self.unreachable) + len(self.abstentions) + len(
                    {c.proposer for c in self.candidates}
                ),
                adoption_measured=self.adoption_measured,
                adopted=sum(1 for c in distinct if c.adopted),
                adopted_from_others=sum(1 for c in added if c.adopted),
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "ranked": [candidate.idea_id for candidate in self.ranked()],
            "abstained": self.abstentions,
            "unreachable": self.unreachable,
            "effect": self.effect(),
        }


def _pool_verdict(
    *,
    distinct: int,
    added: int,
    calls: int,
    unreachable: int = 0,
    seated: int = 0,
    adoption_measured: bool = False,
    adopted: int = 0,
    adopted_from_others: int = 0,
) -> str:
    """One sentence about what the panel produced, and — once known — what was used.

    Widening and being useful are different claims, and the multi-agent feedback literature
    turns on the distinction: authors ranking reports measured *perceived* usefulness "rather
    than realized improvement", and AgentPanel's own conclusion is that its ideas "remain
    speculative candidates that require expert validation". Until Stage 02 has actually been
    approved this can only report the first claim, and it says which one it is making.
    """
    # ``unreachable`` being truthy already carries the "at least one seat" case, so a
    # missing ``seated`` (older records predate the count) still reads as a total outage
    # rather than being silently downgraded.
    if unreachable and unreachable >= seated:
        return (
            f"No proposer could be reached ({unreachable} of {seated} failed); the panel "
            "never sat. The stage proceeds without a pool, and this run says nothing about "
            "whether widening the candidate pool helps — it was never tried."
        )

    if distinct == 0:
        reached = (
            f" {unreachable} of {seated} proposer(s) could not be reached." if unreachable else ""
        )
        return (
            "No candidate hypotheses survived; the stage proceeds without a pool." + reached
        )

    if added == 0:
        widened = (
            f"All {distinct} distinct hypotheses came from the baseline proposer; the other "
            f"proposers restated it, at {calls} proposer calls. On this run the panel widened "
            "nothing — consider --ideation-lenses with fewer seats, or dropping it."
        )
    else:
        widened = (
            f"{added} of {distinct} distinct hypotheses came from proposers beyond the "
            f"baseline, at {calls} proposer calls."
        )

    if not adoption_measured:
        return widened + " Whether any of them were used is not yet measured."
    if adopted == 0:
        return (
            widened
            + " Stage 02 adopted none of them and generated its own hypotheses instead, so the "
            "pool cost its calls and changed nothing."
        )
    if adopted_from_others == 0:
        return (
            widened
            + f" Stage 02 adopted {adopted}, all from the baseline proposer — a single pass "
            "would have supplied everything the stage used."
        )
    return (
        widened
        + f" Stage 02 adopted {adopted}, {adopted_from_others} of them from proposers beyond "
        "the baseline."
    )


# ---------------------------------------------------------------------------
# Near-duplicate detection
# ---------------------------------------------------------------------------


def _content_words(text: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return frozenset(word for word in words if len(word) > 2 and word not in _STOPWORDS)


def similarity(left: str, right: str) -> float:
    """Jaccard overlap of content words. 1.0 means the same words in any order."""
    a, b = _content_words(left), _content_words(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def mark_duplicates(candidates: list[Candidate], threshold: float = DUPLICATE_THRESHOLD) -> list[Candidate]:
    """Fold near-identical hypotheses into their first occurrence.

    Done in plain Python rather than with a model call: the measurement exists to catch a pool
    that has collapsed into restatements, and asking a model whether five of its own ideas are
    really the same idea is the wrong instrument for that.
    """
    resolved: list[Candidate] = []
    for candidate in candidates:
        # Compare the claim only. Titles are noise here: two proposers giving one idea two
        # different names is precisely the collapse this is meant to catch, and folding the
        # titles into the comparison dilutes the overlap enough to miss it.
        match = next(
            (
                kept
                for kept in resolved
                if kept.duplicate_of is None
                and similarity(candidate.statement, kept.statement) >= threshold
            ),
            None,
        )
        resolved.append(
            candidate if match is None else Candidate(**{**candidate.__dict__, "duplicate_of": match.idea_id})
        )
    return resolved


def resolve_lenses(keys: list[str] | None) -> tuple[ProposerLens, ...]:
    if not keys:
        return DEFAULT_LENSES
    lenses: list[ProposerLens] = []
    for key in keys:
        normalized = key.strip().lower()
        if normalized not in LENSES_BY_KEY:
            known = ", ".join(sorted(LENSES_BY_KEY))
            raise ValueError(f"Unknown ideation lens: {key}. Known lenses: {known}.")
        lens = LENSES_BY_KEY[normalized]
        if lens not in lenses:
            lenses.append(lens)
    return tuple(lenses)


def apply_lens_models(lenses: tuple[ProposerLens, ...], assignments: list[str] | None) -> tuple[ProposerLens, ...]:
    """Assign a backend and model per lens from ``lens=[backend:]model`` strings."""
    if not assignments:
        return lenses
    by_key = {lens.key: lens for lens in lenses}
    updated = dict(by_key)
    for raw in assignments:
        if "=" not in raw:
            raise ValueError(
                f"Bad ideation model assignment: {raw!r}. Expected lens=model or lens=backend:model."
            )
        key, _, spec = raw.partition("=")
        key, spec = key.strip().lower(), spec.strip()
        if key not in by_key:
            known = ", ".join(sorted(by_key))
            raise ValueError(f"Unknown ideation lens in model assignment: {key}. Seated lenses: {known}.")
        if not spec:
            raise ValueError(f"Bad ideation model assignment: {raw!r}. No model given.")
        backend, _, model = spec.partition(":") if ":" in spec else (None, "", spec)
        model = model.strip()
        if not model:
            raise ValueError(f"Bad ideation model assignment: {raw!r}. No model given.")
        current = updated[key]
        updated[key] = ProposerLens(
            **{**current.__dict__, "backend": (backend or current.backend), "model": model}
        )
    return tuple(updated[lens.key] for lens in lenses)


# ---------------------------------------------------------------------------
# The panel
# ---------------------------------------------------------------------------


class IdeationPanel:
    """Widen Stage 02's candidate pool. Decides nothing."""

    def __init__(
        self,
        lenses: tuple[ProposerLens, ...] = DEFAULT_LENSES,
        *,
        backend_name: str,
        model: str,
        fake_mode: bool = False,
        ui: TerminalUI | None = None,
        stage_timeout: int = 14400,
        ideas_per_proposer: int = 2,
        score_pool: bool = True,
    ) -> None:
        if not lenses:
            raise ValueError("An ideation panel needs at least one lens.")
        self.lenses = lenses
        self.backend_name = backend_name
        self.model = model
        self.fake_mode = fake_mode
        self.ui = ui or TerminalUI()
        self.ideas_per_proposer = max(1, ideas_per_proposer)
        self.score_pool = score_pool
        self._members = {
            lens.key: AutomatedReviewer(
                lens.backend or backend_name,
                model=lens.model or model,
                fake_mode=fake_mode,
                ui=self.ui,
                stage_timeout=stage_timeout,
            )
            for lens in lenses
        }

    def build_pool(self, *, paths: RunPaths, stage: StageSpec, attempt_no: int) -> IdeaPool:
        pool = IdeaPool(baseline_proposer=self.lenses[0].key)
        if self.fake_mode:
            return pool

        for index, lens in enumerate(self.lenses):
            member = self._members[lens.key]
            self.ui.show_status(f"Ideation panel: {lens.title} is proposing hypotheses...", level="info")
            exit_code, stdout_text, _stderr = member.run_prompt(
                paths=paths,
                stage=stage,
                attempt_no=attempt_no,
                prompt=self._proposal_prompt(paths=paths, lens=lens),
                label=f"ideate_{lens.key}",
            )
            pool.proposer_calls += 1
            if exit_code != 0:
                pool.unreachable.append(lens.key)
                continue
            payload = member._extract_json_payload(stdout_text)  # noqa: SLF001
            if not isinstance(payload, dict):
                pool.unreachable.append(lens.key)
                continue
            raw_ideas = payload.get("hypotheses")
            if not isinstance(raw_ideas, list) or not raw_ideas:
                # A proposer with nothing to add is silent rather than padding the pool.
                pool.abstentions.append(lens.key)
                continue
            for position, raw in enumerate(raw_ideas[: self.ideas_per_proposer], start=1):
                candidate = self._candidate_from(raw, lens=lens, member=member, position=position, index=index)
                if candidate is not None:
                    pool.candidates.append(candidate)

        pool.candidates = mark_duplicates(pool.candidates)
        if self.score_pool and pool.distinct:
            self._score(pool, paths=paths, stage=stage, attempt_no=attempt_no)
        return pool

    def _candidate_from(
        self, raw: Any, *, lens: ProposerLens, member: AutomatedReviewer, position: int, index: int
    ) -> Candidate | None:
        if not isinstance(raw, dict):
            return None
        statement = str(raw.get("statement") or raw.get("hypothesis") or "").strip()
        if not statement:
            return None
        return Candidate(
            idea_id=f"{lens.key}-{position}",
            proposer=lens.key,
            proposer_title=lens.title,
            backend=member.backend_name,
            model=member.model,
            title=str(raw.get("title") or "").strip() or f"{lens.title} hypothesis {position}",
            statement=statement,
            rationale=str(raw.get("rationale") or "").strip(),
            prediction=str(raw.get("prediction") or raw.get("testable_prediction") or "").strip(),
        )

    def _score(self, pool: IdeaPool, *, paths: RunPaths, stage: StageSpec, attempt_no: int) -> None:
        """Score the distinct pool on the dimensions the ideation benchmarks use.

        One call over the whole pool rather than one per candidate: the scores are for ordering
        material a later reader will judge anyway, and paying per candidate would spend more on
        ranking the pool than on generating it.
        """
        scorer = self._members[self.lenses[0].key]
        self.ui.show_status("Ideation panel: scoring the candidate pool...", level="info")
        exit_code, stdout_text, _stderr = scorer.run_prompt(
            paths=paths,
            stage=stage,
            attempt_no=attempt_no,
            prompt=self._scoring_prompt(pool, paths=paths),
            label="ideate_score",
        )
        if exit_code != 0:
            return
        payload = scorer._extract_json_payload(stdout_text)  # noqa: SLF001
        if not isinstance(payload, dict) or not isinstance(payload.get("scores"), list):
            return

        by_id = {str(entry.get("idea_id")): entry for entry in payload["scores"] if isinstance(entry, dict)}
        scored: list[Candidate] = []
        for candidate in pool.candidates:
            entry = by_id.get(candidate.idea_id)
            if entry is None or candidate.duplicate_of is not None:
                scored.append(candidate)
                continue
            scored.append(
                Candidate(
                    **{
                        **candidate.__dict__,
                        "novelty": _score_value(entry.get("novelty")),
                        "feasibility": _score_value(entry.get("feasibility")),
                        "relevance": _score_value(entry.get("relevance")),
                    }
                )
            )
        pool.candidates = scored

    # -- prompts --------------------------------------------------------------

    def _proposal_prompt(self, *, paths: RunPaths, lens: ProposerLens) -> str:
        return (
            f"# AutoR Ideation Panel: {lens.title}\n\n"
            f"You are the **{lens.title}** proposer on a hypothesis-generation panel. Other "
            "proposers are working from different lenses on the same goal. You cannot see them "
            "and should not guess at them — the panel's value is that your candidates are not "
            "downstream of anyone else's.\n\n"
            f"## Your Lens\n\n{lens.charter}\n\n"
            "## What To Produce\n\n"
            f"At most {self.ideas_per_proposer} candidate hypotheses, each one specific enough "
            "to be wrong. A hypothesis that no observation could contradict is not a candidate.\n\n"
            "- State it as a claim, not a topic. \"X increases Y through Z\" is a claim; "
            "\"the relationship between X and Y\" is a topic.\n"
            "- Give the prediction that would distinguish it from the obvious alternative.\n"
            "- Ground it in the run's actual goal and literature, not in generic domain knowledge.\n"
            "- If your lens has nothing real to offer on this goal, return an empty list. An "
            "empty list costs the panel nothing; a restatement of the obvious hypothesis costs "
            "it the diversity it exists for.\n\n"
            "## Return Format\n\n"
            "Return JSON only, no prose outside the object:\n"
            '{"hypotheses":[{"title":"","statement":"","rationale":"","prediction":""}]}\n\n'
            "# Research Goal\n\n"
            f"{truncate_text(_excerpt(paths.user_input), max_chars=4000)}\n\n"
            "# Approved Memory\n\n"
            f"{truncate_text(_excerpt(paths.memory), max_chars=10000)}\n\n"
            "# Literature Directory\n\n"
            f"`{paths.literature_dir.resolve()}` — read it before proposing.\n"
        )

    def _scoring_prompt(self, pool: IdeaPool, *, paths: RunPaths) -> str:
        listing = "\n\n".join(
            f"### {candidate.idea_id}\n"
            f"**{candidate.title}**\n\n{candidate.statement}"
            + (f"\n\nPrediction: {candidate.prediction}" if candidate.prediction else "")
            for candidate in pool.distinct
        )
        ids = ", ".join(candidate.idea_id for candidate in pool.distinct)
        return (
            "# AutoR Ideation Panel: Pool Scoring\n\n"
            "Score each candidate hypothesis below. You are ordering material for a researcher "
            "to choose from, not picking a winner.\n\n"
            "Score each on 0-10:\n\n"
            "- **novelty** — is this something the field has not already settled?\n"
            "- **feasibility** — could it actually be tested with the data and effort this run "
            "has? This is the dimension that separates a useful pool from a creative one.\n"
            "- **relevance** — does it answer the research goal as stated, rather than an "
            "adjacent question that is easier?\n\n"
            "Be willing to score low. A pool where everything scores 8 has not been read.\n\n"
            "## Return Format\n\n"
            "Return JSON only:\n"
            '{"scores":[{"idea_id":"","novelty":0,"feasibility":0,"relevance":0}]}\n\n'
            f"Score exactly these ids: {ids}\n\n"
            "# Research Goal\n\n"
            f"{truncate_text(_excerpt(paths.user_input), max_chars=3000)}\n\n"
            "# Candidates\n\n"
            f"{listing}\n"
        )


def _score_value(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(10.0, round(value, 2)))


def _excerpt(path) -> str:
    return read_text(path).strip() if path.exists() else "(missing)"


# ---------------------------------------------------------------------------
# Artifacts and prompt injection
# ---------------------------------------------------------------------------


#: A pooled hypothesis counts as adopted when some paragraph of the approved stage summary
#: overlaps it this much. Lower than :data:`DUPLICATE_THRESHOLD` on purpose: a stage that took
#: a candidate is expected to sharpen and re-word it, not paste it, so the bar for "this is the
#: same hypothesis, developed" sits below the bar for "these two proposers said one thing".
ADOPTION_THRESHOLD = 0.35


def _paragraphs(markdown: str) -> list[str]:
    """Split an approved stage summary into the units a hypothesis could live in."""
    blocks: list[str] = []
    for block in re.split(r"\n\s*\n", markdown):
        cleaned = re.sub(r"^[#>\-*\d.\s]+", "", block.strip())
        if len(cleaned) >= 40:
            blocks.append(cleaned)
    return blocks


def measure_adoption(pool: IdeaPool, stage_markdown: str, threshold: float = ADOPTION_THRESHOLD) -> IdeaPool:
    """Mark which pooled candidates the approved stage actually built on.

    This is the measurement both papers say is missing. Havranek and Irsova had authors rank
    *perceived* usefulness and note plainly that it is not realized improvement; AgentPanel
    ends on its ideas being "speculative candidates that require expert validation". A pool
    that widened the options and was then ignored has not helped, and until this runs the pool
    cannot tell those two outcomes apart.

    Deliberately textual and local rather than a model call. Asking a model whether a stage
    used an idea it was shown invites it to say yes, which is the failure this measurement
    exists to detect.
    """
    blocks = _paragraphs(stage_markdown)
    measured: list[Candidate] = []
    for candidate in pool.candidates:
        if candidate.duplicate_of is not None:
            measured.append(candidate)
            continue
        best = max((similarity(candidate.statement, block) for block in blocks), default=0.0)
        measured.append(Candidate(**{**candidate.__dict__, "adopted": best >= threshold}))
    pool.candidates = measured
    return pool


def load_idea_pool(paths: RunPaths) -> IdeaPool | None:
    """Rebuild the pool written earlier in this stage, or None when there is not one."""
    path = paths.notes_dir / IDEA_POOL_FILENAME
    if not path.exists():
        return None
    try:
        payload = json.loads(read_text(path))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("candidates"), list):
        return None

    fields = set(Candidate.__dataclass_fields__)
    candidates = [
        Candidate(**{key: value for key, value in raw.items() if key in fields})
        for raw in payload["candidates"]
        if isinstance(raw, dict) and raw.get("statement")
    ]
    effect = payload.get("effect") if isinstance(payload.get("effect"), dict) else {}
    return IdeaPool(
        candidates=candidates,
        abstentions=list(payload.get("abstained") or []),
        unreachable=list(payload.get("unreachable") or []),
        proposer_calls=int(effect.get("proposer_calls") or 0),
        baseline_proposer=str(effect.get("baseline_proposer") or ""),
    )


def record_idea_pool(paths: RunPaths, pool: IdeaPool, stage: StageSpec, attempt_no: int) -> dict[str, Any]:
    payload = {"stage": stage.slug, "attempt": attempt_no, **pool.to_dict()}
    paths.notes_dir.mkdir(parents=True, exist_ok=True)
    write_text(paths.notes_dir / IDEA_POOL_FILENAME, json.dumps(payload, indent=2, ensure_ascii=False))
    write_text(paths.notes_dir / "idea_pool.md", format_pool_for_prompt(pool))
    append_log_entry(
        paths.logs,
        f"{stage.slug} attempt {attempt_no} idea_pool",
        (
            f"proposed: {payload['effect']['proposed']}\n"
            f"distinct: {payload['effect']['distinct']}\n"
            f"added beyond baseline: {payload['effect']['added_by_other_proposers']}\n"
            f"{payload['effect']['verdict']}"
        ),
    )
    return payload


def format_pool_for_prompt(pool: IdeaPool) -> str:
    """Render the pool as material for Stage 02 to select from and sharpen."""
    ranked = pool.ranked()
    if not ranked:
        return (
            "No candidate hypotheses were produced by the ideation panel. Generate hypotheses "
            "from the goal and literature as usual.\n"
        )

    lines = [
        "These candidate hypotheses were proposed independently by agents working from "
        "different lenses, then deduplicated and scored. They are **material, not a decision**: "
        "adopt, merge, sharpen, or reject them on their evidence, and say in your stage summary "
        "which you took and why you left the rest.",
        "",
    ]
    for candidate in ranked:
        score = candidate.mean_score
        header = f"### {candidate.idea_id} — {candidate.title}"
        if score is not None:
            header += (
                f"  _(novelty {candidate.novelty}, feasibility {candidate.feasibility}, "
                f"relevance {candidate.relevance})_"
            )
        lines.extend([header, f"_Lens: {candidate.proposer_title}_", "", candidate.statement, ""])
        if candidate.rationale:
            lines.extend([f"Rationale: {candidate.rationale}", ""])
        if candidate.prediction:
            lines.extend([f"Distinguishing prediction: {candidate.prediction}", ""])

    collapsed = pool.effect()["collapsed_as_duplicates"]
    if collapsed:
        lines.append(
            f"_{collapsed} further proposal(s) were folded in as restatements of the above._"
        )
    if pool.abstentions:
        lines.append(f"_Lenses with nothing to add on this goal: {', '.join(pool.abstentions)}._")
    return "\n".join(lines).rstrip() + "\n"
