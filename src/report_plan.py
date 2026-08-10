"""Choose the figures before the results exist, and hold the report to that choice.

Preregistration fixes what the run predicted. The experimental protocol fixes
what would count as having shown it. This fixes *what the reader is shown* —
the last place the same defect had left to hide.

A report's figures were being chosen at the end, out of whatever the run
happened to produce, and then pruned to fit the ceiling by the order a
directory walk returned. That is choosing the evidence after seeing it, one
level up: the figure that survives is the one that exists, not the one that
settles a question. The plan moves the choice to Stage 03, where the design is
still being decided and a missing figure is a thing to go and compute rather
than a thing to delete.

The artifact is ``workspace/notes/report_plan.json``. Each slot commits to a
filename, the claim it settles, what a reader should see, what the figure looks
like if that claim holds and if it does not, and the result file it will be
computed from. Alongside them, ``headline_numbers`` names the quantities the
report has to state — the numbers that make the figures legible in prose.

Three gates hang off it, deliberately at three different stages:

1. **Shape, from Stage 03.** Held at the stage that writes it. The
   ``experimental_protocol.json`` precedent is the counter-example: the Stage 03
   prompt asks for it and the gate first fires at Stage 05, so a Stage 03 that
   skipped it is approved and the failure surfaces two stages later, where the
   only repair is a rollback.
2. **The sources resolve, from Stage 06.** "Never draw a figure from numbers
   you did not compute", checked while there is still a stage that could
   compute them.
3. **Coverage, at Stage 07, markdown only.** Every planned slot was either
   published and referenced, or dropped with a recorded reason. Narrowed to
   markdown on purpose: the latex branch has no single well-defined published
   figure location (figures are placed by the document), and that branch runs
   its own layout review instead.

**On the anti-gaming shape of the rules.**

- The length floors (40 characters on ``shows``, 20 on each branch sentence and
  on ``dropped_because``) are floors under *a sentence was written*, nothing
  more. They are not quality thresholds and must not grow into them: whether a
  figure is a good figure is the review panel's judgement, and a gate that
  tried to measure it would only be measuring length. The cap of eight headline
  numbers exists for the mirror-image reason — so the field cannot become a
  dumping ground that satisfies a count.
- ``if_supported`` must differ from ``if_refuted``. This is trivially defeated
  by inserting "not", and that is acceptable. Like ``why_competent`` on a
  baseline, the guard's job is to make the empty move cost a written sentence
  and put that sentence in the record where a reviewer reads it — not to be
  unforgeable.
- Every figure must carry at least one ``supports`` id no other figure carries.
  This is the one rule here that pushes the figure count *down*: a run that
  cannot name a distinct claim for slot 5 has no slot 5. Nothing in this module
  ever asks for more figures. The only count refusals are "none at all" and
  "more than the ceiling", because ``MAX_REPORT_FIGURES`` is a ceiling and a
  gate that restated it as a goal would have converted it into a quota.

**The digest is AutoR's, not the agent's.** ``declared_at``, ``digest`` and
``amendments`` are written by :func:`stamp_report_plan` on Stage 03 approval.
Asking a language model for a sha256 is a wish, not a gate, so the validators
ignore all three: the agent writes ``figures`` and ``headline_numbers`` and
nothing else. A later round *amends* the plan rather than rewriting it — an
unchanged plan is stamped once and never again, so a round that legitimately
left the choice alone does not manufacture a spurious amendment, and a round
that moved it leaves a ledger entry saying so.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Sequence

from .utils import (
    DEFAULT_OUTPUT_FORMAT,
    FIGURE_SUFFIXES,
    MAX_REPORT_FIGURES,
    PREFERRED_REPORT_IMAGE_SUFFIX,
    RunPaths,
    extract_markdown_image_targets,
)


#: Where a figure's numbers may come from. ``notes/`` is deliberately absent: a
#: figure computed from a note is a figure computed from prose. ``outputs/`` is
#: here because a benchmark workspace points its result writes there.
SOURCE_ARTIFACT_ROOTS = ("results", "data", "outputs")

#: A figure may serve a question nobody preregistered — that is often the most
#: interesting figure in a run. It has to say so, and the slug still has to be
#: distinct from every other slot's, so "exploratory" cannot be a wildcard used
#: five times.
EXPLORATORY_PREFIX = "exploratory:"
MIN_EXPLORATORY_SLUG_CHARS = 3

#: Floors under "a sentence was written". See the module docstring: these are
#: not quality thresholds.
MIN_SHOWS_CHARS = 40
MIN_BRANCH_CHARS = 20
MIN_DROP_REASON_CHARS = 20

#: A ceiling, so the field cannot become a list that satisfies a count.
MAX_HEADLINE_NUMBERS = 8

#: Above this, a file has content and is not read back to prove it. Only the
#: empty-file case matters here, and a result artifact can be a large binary.
_WHITESPACE_PROBE_BYTES = 4096


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _digest(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _text(value: object) -> str:
    return str(value or "").strip()


def _normalised(value: str) -> str:
    """Whitespace- and case-insensitive form, for comparing two sentences."""
    return " ".join(value.split()).casefold()


# ----------------------------------------------------------------------------
# The artifact
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class PlannedFigure:
    slot: int
    filename: str
    supports: list[str]
    shows: str
    if_supported: str
    if_refuted: str
    source_artifact: str
    dropped_because: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "slot": self.slot,
            "filename": self.filename,
            "supports": list(self.supports),
            "shows": self.shows,
            "if_supported": self.if_supported,
            "if_refuted": self.if_refuted,
            "source_artifact": self.source_artifact,
            "dropped_because": self.dropped_because,
        }

    @property
    def is_dropped(self) -> bool:
        return len(self.dropped_because.strip()) >= MIN_DROP_REASON_CHARS


@dataclass(frozen=True)
class HeadlineNumber:
    quantity: str
    unit: str
    source_artifact: str

    def to_dict(self) -> dict[str, str]:
        return {
            "quantity": self.quantity,
            "unit": self.unit,
            "source_artifact": self.source_artifact,
        }


@dataclass(frozen=True)
class ReportPlan:
    figures: list[PlannedFigure]
    headline_numbers: list[HeadlineNumber]
    declared_at: str = ""
    digest: str = ""
    #: Why this study's report carries no figure. Required only when ``figures``
    #: is empty, which three of the forty benchmark tasks genuinely are.
    no_figures_because: str = ""
    amendments: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "declared_at": self.declared_at,
            "digest": self.digest,
            "no_figures_because": self.no_figures_because,
            "amendments": [dict(item) for item in self.amendments],
            "figures": [item.to_dict() for item in self.figures],
            "headline_numbers": [item.to_dict() for item in self.headline_numbers],
        }


def _entries(payload: dict, key: str) -> list:
    """The list at ``key``, or an empty one.

    ``.get(key, [])`` is not enough: ``"figures": null`` and ``"figures": 5``
    are both things a model writes, and both are iterated straight into a
    ``TypeError`` that escapes ``validate_stage_artifacts`` and ends the run.
    A malformed plan has to come back as a refusal the stage can act on, the
    same as a missing one — the gate is not a place to crash.
    """
    value = payload.get(key)
    return value if isinstance(value, list) else []


def load_report_plan(paths: RunPaths) -> ReportPlan | None:
    payload = _load_json(paths.report_plan)
    if not isinstance(payload, dict):
        return None

    figures: list[PlannedFigure] = []
    for entry in _entries(payload, "figures"):
        if not isinstance(entry, dict):
            continue
        raw_slot = entry.get("slot")
        try:
            slot = int(raw_slot)
        except (TypeError, ValueError):
            slot = 0
        if isinstance(raw_slot, bool):
            slot = 0
        supports_value = entry.get("supports")
        if isinstance(supports_value, str):
            supports = [supports_value.strip()] if supports_value.strip() else []
        elif isinstance(supports_value, list):
            # Deduplicated, order preserved. One slot listing `["H1", "H1"]` claims one
            # question, not two, and the distinctness rule below counts *slots per claim*:
            # left as written, a slot's own repeat would make `claimed["H1"]` 2 and refuse
            # the only slot carrying it, with a message blaming a second slot that does not
            # exist.
            supports = list(dict.fromkeys(_text(item) for item in supports_value if _text(item)))
        else:
            supports = []
        figures.append(
            PlannedFigure(
                slot=slot,
                filename=_text(entry.get("filename")),
                supports=supports,
                shows=_text(entry.get("shows")),
                if_supported=_text(entry.get("if_supported")),
                if_refuted=_text(entry.get("if_refuted")),
                source_artifact=_text(entry.get("source_artifact")),
                dropped_because=_text(entry.get("dropped_because")),
            )
        )

    headline_numbers = [
        HeadlineNumber(
            quantity=_text(entry.get("quantity")),
            unit=_text(entry.get("unit")),
            source_artifact=_text(entry.get("source_artifact")),
        )
        for entry in _entries(payload, "headline_numbers")
        if isinstance(entry, dict)
    ]

    return ReportPlan(
        figures=figures,
        headline_numbers=headline_numbers,
        declared_at=_text(payload.get("declared_at")),
        digest=_text(payload.get("digest")),
        no_figures_because=_text(payload.get("no_figures_because")),
        amendments=[dict(item) for item in _entries(payload, "amendments") if isinstance(item, dict)],
    )


def report_plan_digest(plan: ReportPlan) -> str:
    """Hash the fields the plan commits to, and only those.

    ``declared_at`` and ``amendments`` are excluded: a re-stamp with no change
    to a single slot is not a change of plan, and a timestamp is not a choice.
    ``dropped_because`` *is* included, because abandoning a slot is exactly the
    kind of move the amendment ledger exists to record.
    """
    return _digest(
        {
            "figures": [item.to_dict() for item in plan.figures],
            "headline_numbers": [item.to_dict() for item in plan.headline_numbers],
        }
    )


def _write_report_plan(paths: RunPaths, plan: ReportPlan) -> None:
    paths.report_plan.parent.mkdir(parents=True, exist_ok=True)
    paths.report_plan.write_text(
        json.dumps(plan.to_dict(), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def report_plan_stamp_path(paths: RunPaths) -> Path:
    """AutoR's own copy of the three fields the agent must not write.

    Outside ``workspace/``, for the reason ``evolution_dir`` is: it is a record
    of how the run reached its answer rather than part of the answer. The plan
    itself has to stay in ``workspace/notes/`` — the agent writes it, amends it
    and is shown it. But that means the agent also has write access to the
    fields that are supposed to prove *when* it was written, and a stamp kept
    only there is a receipt the payer prints.
    """
    return paths.run_root / "report_plan_stamp.json"


def recorded_report_plan_stamp(paths: RunPaths) -> tuple[str, str, list[dict[str, str]]] | None:
    """``(declared_at, digest, amendments)`` as AutoR last wrote them, or None.

    None means "AutoR has never stamped this plan", which is the only state in
    which the file's own ``declared_at`` is worth anything.
    """
    payload = _load_json(report_plan_stamp_path(paths))
    if not isinstance(payload, dict):
        return None
    declared_at = _text(payload.get("declared_at"))
    digest = _text(payload.get("digest"))
    if not declared_at or not digest:
        return None
    amendments = [dict(item) for item in _entries(payload, "amendments") if isinstance(item, dict)]
    return (declared_at, digest, amendments)


def _write_report_plan_stamp(paths: RunPaths, plan: ReportPlan) -> None:
    path = report_plan_stamp_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "declared_at": plan.declared_at,
                "digest": plan.digest,
                "amendments": [dict(item) for item in plan.amendments],
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )


def stamp_report_plan(paths: RunPaths, reason: str = "initial declaration") -> ReportPlan | None:
    """Record when the plan was declared, and every time it moved afterwards.

    Called by the manager when Stage 03 is approved, and again as a safety net
    from Stage 06 on for runs that reach there without passing through a Stage
    03 approval (``--resume-run``, ``--redo-stage``, a ``--project-root``
    bootstrap). A plan whose content digest is unchanged is not rewritten, so
    carrying a correct plan through a second round does not manufacture an
    amendment — copied from ``amend_preregistration``, for the same reason.

    **The previous digest is read from AutoR's sidecar, never from the plan
    file.** The agent owns ``report_plan.json``: Stage 03 writes it and Stage 06
    is told to edit ``dropped_because`` into it. Trusting the ``digest`` and
    ``declared_at`` inside it to say whether it moved makes the record
    self-certifying, and it fails on the ordinary accident rather than only on
    a hostile one — a stage that regenerates the whole file from its own
    template, obeying "do not write declared_at, digest or amendments", leaves
    a plan with no stamp at all. Read from the file, that is indistinguishable
    from a first declaration: ``declared_at`` silently becomes a post-results
    timestamp and the amendment ledger stays empty, which is precisely the
    claim the artifact exists to make and the one it would then be making
    falsely. Read from the sidecar, it is an amendment, and the file is
    repaired on the spot.
    """
    plan = load_report_plan(paths)
    if plan is None:
        return None

    recorded = recorded_report_plan_stamp(paths)
    if recorded is not None:
        declared_at, previous_digest, amendments = recorded
    else:
        declared_at, previous_digest, amendments = (
            plan.declared_at,
            plan.digest,
            plan.amendments,
        )

    current = report_plan_digest(plan)
    if previous_digest == current and declared_at:
        stamped = ReportPlan(
            figures=plan.figures,
            headline_numbers=plan.headline_numbers,
            declared_at=declared_at,
            digest=current,
            amendments=amendments,
        )
    elif not previous_digest:
        stamped = ReportPlan(
            figures=plan.figures,
            headline_numbers=plan.headline_numbers,
            declared_at=declared_at or _now(),
            digest=current,
            amendments=amendments,
        )
    else:
        stamped = ReportPlan(
            figures=plan.figures,
            headline_numbers=plan.headline_numbers,
            declared_at=declared_at or _now(),
            digest=current,
            amendments=[
                *amendments,
                {
                    "recorded_at": _now(),
                    "reason": reason,
                    "previous_digest": previous_digest,
                    "new_digest": current,
                },
            ],
        )
    _write_report_plan_stamp(paths, stamped)
    # Only when the header on disk disagrees, so an unchanged plan keeps its
    # bytes and a stamped-but-wiped one is put back.
    if plan.to_dict() != stamped.to_dict():
        _write_report_plan(paths, stamped)
    return stamped


# ----------------------------------------------------------------------------
# Shape: the gate that runs from Stage 03, where the plan is written
# ----------------------------------------------------------------------------


def _hypothesis_ids(paths: RunPaths) -> set[str] | None:
    """The ids a figure may cite, or ``None`` when there is no manifest to check against.

    A ``--project-root`` run can reach Stage 03 with no Stage 02 manifest. The
    membership check degrades to "name something" rather than refusing every
    id, because the alternative is a gate that fails for a reason the run
    cannot fix. An empty manifest is treated the same way as a missing one.
    """
    from .hypothesis_manifest import load_hypothesis_manifest

    manifest = load_hypothesis_manifest(paths.hypothesis_manifest)
    if manifest is None:
        return None
    identifiers = {
        entry.identifier
        for section in (
            manifest.theoretical_propositions,
            manifest.empirical_hypotheses,
            manifest.paper_claims,
        )
        for entry in section
        if entry.identifier
    }
    return identifiers or None


def _relative_source(reference: str) -> PurePosixPath | None:
    """The reference as a workspace-relative file path, or None when it is not one."""
    cleaned = reference.strip().replace("\\", "/")
    if not cleaned:
        return None
    candidate = PurePosixPath(cleaned)
    if candidate.is_absolute():
        return None
    parts = [part for part in candidate.parts if part != "."]
    if ".." in parts or len(parts) < 2:
        return None
    if parts[0] not in SOURCE_ARTIFACT_ROOTS:
        return None
    return PurePosixPath(*parts)


def _source_artifact_problem(reference: str, label: str) -> str | None:
    if not reference:
        return (
            f"{label} names no source_artifact. A figure has to say which file its numbers "
            "come from, so producing that file is a stage's job rather than an afterthought."
        )
    if _relative_source(reference) is None:
        roots = ", ".join(f"{root}/" for root in SOURCE_ARTIFACT_ROOTS)
        return (
            f"{label} draws from `{reference}`, which is not a workspace-relative file under "
            f"{roots}. A figure is computed from a result the run produced, never from a note."
        )
    return None


def _allowed_figure_suffixes(output_format: str) -> set[str]:
    """The suffixes a published figure may carry, derived from the format's constants."""
    if output_format == "markdown":
        return {PREFERRED_REPORT_IMAGE_SUFFIX}
    return set(FIGURE_SUFFIXES)


def validate_report_plan(
    paths: RunPaths,
    output_format: str = DEFAULT_OUTPUT_FORMAT,
) -> list[str]:
    """Shape checks, from Stage 03 on: the plan is a commitment or it is nothing.

    Held at the stage that writes the plan rather than at the stage that reads
    it, so a plan-less Stage 03 is refused while the design can still be
    changed.
    """
    plan = load_report_plan(paths)
    if plan is None:
        return [
            "requires a report plan at workspace/notes/report_plan.json, written before any "
            "result exists. Each figure the report will carry gets a slot: the filename it "
            "will be published under, the claim it settles, what a reader should see in it, "
            "what it looks like if that claim holds and if it does not, and the result file "
            "it is computed from. `headline_numbers` names the quantities the report must "
            "state, with their units."
        ]

    problems: list[str] = []
    figures = plan.figures
    #: Whether AutoR has ever stamped this plan. Read from AutoR's own copy
    #: rather than the file's ``declared_at``, for the reason
    #: :func:`recorded_report_plan_stamp` exists: the agent can write that
    #: field. False means the plan is still being declared — the first Stage 03
    #: that writes it, or a re-attempt of that stage.
    declared = recorded_report_plan_stamp(paths) is not None

    if not figures:
        # A plan with no figures is unusual, not wrong. Measured over the 40
        # ResearchClawBench tasks, three of them have no image criterion at all,
        # and the median task has two — so a floor of one would make those three
        # runs draw a figure that carries nothing, which is exactly the
        # dilution the slot ranking exists to prevent. Following this codebase's
        # habit, the move is not forbidden; it has to be on the record.
        if len(str(plan.no_figures_because or "").strip()) < MIN_SHOWS_CHARS:
            problems.append(
                "report_plan.json declares no figures and does not say why. A report with no "
                "figure is a real answer for some studies — set `no_figures_because` to the "
                f"reason, in at least {MIN_SHOWS_CHARS} characters, naming what the prose "
                "carries instead. Otherwise name the figure the report is built around, the "
                "claim it settles and the file it comes from."
            )
    elif output_format == "markdown" and len(figures) > MAX_REPORT_FIGURES:
        problems.append(
            f"report_plan.json declares {len(figures)} figures, but at most "
            f"{MAX_REPORT_FIGURES} reach the reader of a markdown report — the rest are work "
            f"nobody sees. Drop the weakest slots. {MAX_REPORT_FIGURES} is a ceiling, not a "
            "target: a plan with fewer slots, each settling a different claim, is a better "
            "plan."
        )

    if figures and sorted(item.slot for item in figures) != list(range(1, len(figures) + 1)):
        declared = ", ".join(str(item.slot) for item in figures)
        problems.append(
            f"report_plan.json declares slots [{declared}]; they must be unique and "
            f"contiguous from 1 to {len(figures)}. The slot order is the ranking, and the "
            "ranking is what makes the weakest figure identifiable now rather than at export."
        )

    seen_filenames: dict[str, int] = {}
    for item in figures:
        key = item.filename.casefold()
        if key:
            seen_filenames[key] = seen_filenames.get(key, 0) + 1

    allowed_suffixes = _allowed_figure_suffixes(output_format)
    claimed = Counter(identifier for item in figures for identifier in item.supports)
    known_ids = _hypothesis_ids(paths)

    for item in figures:
        label = f"report_plan.json slot {item.slot}" if item.slot else "report_plan.json figure"

        if not item.filename:
            problems.append(
                f"{label} declares no filename. The filename is the join key between this "
                "plan and the published report: without it, `planned` and `published` cannot "
                "be compared."
            )
        elif Path(item.filename).name != item.filename or "/" in item.filename or "\\" in item.filename:
            problems.append(
                f"{label} declares filename `{item.filename}`, which is not a bare filename. "
                "Figures are published directly under the report's images directory, so a "
                "path here names a figure the export cannot find."
            )
        elif Path(item.filename).suffix.lower() not in allowed_suffixes:
            expected = ", ".join(sorted(allowed_suffixes))
            problems.append(
                f"{label} declares filename `{item.filename}`, whose format is not published "
                f"by this run's deliverable. Use one of: {expected}."
            )
        elif seen_filenames.get(item.filename.casefold(), 0) > 1:
            problems.append(
                f"{label} declares filename `{item.filename}`, which another slot also "
                "declares. Two slots writing one file is one figure with two plans."
            )

        if not item.supports:
            problems.append(
                f"{label} names no claim it supports. Cite a hypothesis id from "
                f"hypothesis_manifest.json, or `{EXPLORATORY_PREFIX}<slug>` for a question "
                "the run did not preregister."
            )
        else:
            for identifier in item.supports:
                if identifier.startswith(EXPLORATORY_PREFIX):
                    slug = identifier[len(EXPLORATORY_PREFIX) :].strip()
                    if len(slug) < MIN_EXPLORATORY_SLUG_CHARS:
                        problems.append(
                            f"{label} supports `{identifier}`, whose slug is shorter than "
                            f"{MIN_EXPLORATORY_SLUG_CHARS} characters. Name the exploratory "
                            "question, so a second slot cannot quietly claim the same one."
                        )
                elif known_ids is not None and identifier not in known_ids:
                    problems.append(
                        f"{label} supports `{identifier}`, which is not an id in "
                        f"hypothesis_manifest.json. Cite a declared hypothesis, or label the "
                        f"question `{EXPLORATORY_PREFIX}<slug>`."
                    )
            if all(claimed[identifier] > 1 for identifier in item.supports):
                overlap = ", ".join(item.supports)
                problems.append(
                    f"{label} supports {overlap}, every one of which another slot already "
                    "carries. A slot that answers no question the other slots leave open is "
                    "a slot spent twice: give it a claim of its own, or drop it."
                )

        if len(item.shows) < MIN_SHOWS_CHARS:
            problems.append(
                f"{label} says nothing usable in `shows` ({len(item.shows)} characters). "
                f"Describe what a reader should see, naming both axes and their units, in at "
                f"least {MIN_SHOWS_CHARS} characters."
            )

        for branch_name, branch in (("if_supported", item.if_supported), ("if_refuted", item.if_refuted)):
            if len(branch) < MIN_BRANCH_CHARS:
                problems.append(
                    f"{label} does not say what the figure looks like in `{branch_name}` "
                    f"({len(branch)} characters, at least {MIN_BRANCH_CHARS} needed)."
                )
        if (
            item.if_supported
            and item.if_refuted
            and _normalised(item.if_supported) == _normalised(item.if_refuted)
        ):
            problems.append(
                f"{label} says the same thing whether the claim holds or not. A figure whose "
                "two branches are one sentence is decoration: it cannot come out either way, "
                "so it carries no claim."
            )

        problem = _source_artifact_problem(item.source_artifact, label)
        if problem:
            problems.append(problem)

        if item.dropped_because and len(item.dropped_because) < MIN_DROP_REASON_CHARS:
            problems.append(
                f"{label} is dropped with a {len(item.dropped_because)}-character reason. "
                f"Say what happened to the claim it carried, in at least "
                f"{MIN_DROP_REASON_CHARS} characters."
            )
        elif item.dropped_because and not declared:
            # Abandoning a slot is a move that only exists *after* the plan was
            # declared. Before then, a dropped slot is the cheapest thing in
            # this file: it satisfies every field check, is skipped by the
            # Stage 06 source gate and by the Stage 07 coverage gate, and owes
            # no figure. Five slots with four born dropped reads as a five-slot
            # plan and commits to one.
            problems.append(
                f"{label} is dropped in the same plan that declares it. `dropped_because` "
                "records a slot abandoned once the results were in; a slot the run never "
                "intended to produce is not a plan, it is padding. Remove the slot, or "
                "remove its `dropped_because` and commit to the figure."
            )

    if not plan.headline_numbers:
        problems.append(
            "report_plan.json declares no headline_numbers. Name the quantities the report "
            "has to state, with units — a result the prose never puts a number on is a "
            "result the reader has to take on trust."
        )
    elif len(plan.headline_numbers) > MAX_HEADLINE_NUMBERS:
        problems.append(
            f"report_plan.json declares {len(plan.headline_numbers)} headline numbers; at "
            f"most {MAX_HEADLINE_NUMBERS}. These are the numbers the report leads with, not "
            "an inventory of everything measured."
        )

    for index, number in enumerate(plan.headline_numbers, start=1):
        label = f"report_plan.json headline number {index}"
        if not number.quantity:
            problems.append(f"{label} names no quantity.")
        if not number.unit:
            problems.append(
                f"{label} has no unit. `dimensionless` and `count` are units; an empty "
                "string is not."
            )
        problem = _source_artifact_problem(number.source_artifact, label)
        if problem:
            problems.append(problem)

    return problems


# ----------------------------------------------------------------------------
# The sources resolve: the gate that runs from Stage 06, while it can be acted on
# ----------------------------------------------------------------------------


def _resolve_source_artifact(
    paths: RunPaths,
    relative: PurePosixPath,
    extra_dirs: Sequence[Path],
) -> Path | None:
    """Find the file a slot names, in the run tree or in a configured artifact root.

    ``extra_dirs`` are the directories the manager maps the ``results`` and
    ``data`` categories onto for runs whose output contract points outside the
    run tree (a benchmark workspace's ``outputs/``). Both the directory itself
    and its parent are tried, because a workspace-relative reference such as
    ``outputs/metrics.json`` is relative to the parent.

    A non-empty match wins over an empty one wherever both exist, so a stray
    zero-byte file in one root cannot mask the real artifact in another.
    """
    bases: list[Path] = [paths.workspace_root]
    for directory in extra_dirs:
        bases.append(directory)
        bases.append(directory.parent)
    found: list[Path] = []
    for base in bases:
        candidate = base / Path(str(relative))
        if candidate.is_file():
            found.append(candidate)
    for directory in extra_dirs:
        candidate = directory / relative.name
        if candidate.is_file():
            found.append(candidate)
    for candidate in found:
        if not _is_empty(candidate):
            return candidate
    return found[0] if found else None


def _is_empty(path: Path) -> bool:
    """No bytes, or nothing but whitespace.

    The existence check is otherwise satisfied by ``touch``: the cheapest way
    to clear "the file your figure comes from does not exist" is to create it
    with nothing in it, and a figure drawn from an empty file is the thing this
    gate exists to refuse. Anything with a byte of content in it passes — this
    is a floor under *a file was written*, not a judgement about the data, and
    a one-line CSV is a legitimate result. Only small files are read back:
    anything above :data:`_WHITESPACE_PROBE_BYTES` has content by definition,
    and a ``.parquet`` is not worth decoding to find that out.
    """
    try:
        size = path.stat().st_size
        if size == 0:
            return True
        if size > _WHITESPACE_PROBE_BYTES:
            return False
        return not path.read_bytes().strip()
    except OSError:
        return False


def validate_report_plan_sources(
    paths: RunPaths,
    extra_dirs: Sequence[Path] = (),
) -> list[str]:
    """From Stage 06 on: the file each live commitment draws from has to exist.

    "Never draw a figure from numbers you did not compute", enforced at the
    stage that draws the figures rather than at the stage that publishes them,
    where the only remaining move would be to delete the figure. A dropped slot
    is skipped: abandoning a figure is allowed, and its reason is checked
    elsewhere.

    ``headline_numbers`` are held to the same rule, and this is the only gate
    that ever reads their ``source_artifact``. Without it the field is the
    cheapest thing in the plan: shape-checked once at Stage 03 and then never
    resolved, so a quantity the report leads with could be sourced from a file
    nothing ever wrote. A headline number has no ``dropped_because`` escape
    because it has no slot to abandon — amend the plan instead, which is a move
    the ledger records.

    An empty file is refused alongside a missing one, and says so differently.
    Existence alone is satisfied by ``touch``: the cheapest way past "produce
    it" would otherwise be to create the path with nothing in it, and a figure
    drawn from an empty file is exactly the figure this gate is here to stop.
    """
    plan = load_report_plan(paths)
    if plan is None:
        return []

    problems: list[str] = []
    for item in plan.figures:
        if item.is_dropped:
            continue
        relative = _relative_source(item.source_artifact)
        if relative is None:
            # Shape is the Stage 03 gate's business; reporting it twice would
            # make one defect look like two.
            continue
        resolved = _resolve_source_artifact(paths, relative, extra_dirs)
        if resolved is None:
            problems.append(
                f"report_plan.json slot {item.slot} plans `{item.filename}` from "
                f"`{item.source_artifact}`, which does not exist. Produce it, or record "
                "`dropped_because` on that slot and say what happened to the claim it "
                "carried."
            )
        elif _is_empty(resolved):
            problems.append(
                f"report_plan.json slot {item.slot} plans `{item.filename}` from "
                f"`{item.source_artifact}`, which is empty. A figure computed from an "
                "empty file is a figure computed from nothing: write the result, or "
                "record `dropped_because` on that slot and say what happened to the "
                "claim it carried."
            )

    for index, number in enumerate(plan.headline_numbers, start=1):
        relative = _relative_source(number.source_artifact)
        if relative is None:
            continue
        resolved = _resolve_source_artifact(paths, relative, extra_dirs)
        if resolved is None:
            problems.append(
                f"report_plan.json headline number {index} ({number.quantity or 'unnamed'}) "
                f"is computed from `{number.source_artifact}`, which does not exist. A "
                "number the report leads with has to come from a file the run wrote: "
                "produce it, or amend the plan to the quantity you can actually state."
            )
        elif _is_empty(resolved):
            problems.append(
                f"report_plan.json headline number {index} ({number.quantity or 'unnamed'}) "
                f"is computed from `{number.source_artifact}`, which is empty. The number "
                "the report leads with cannot come from a file with nothing in it: write "
                "the result, or amend the plan to the quantity you can actually state."
            )
    return problems


# ----------------------------------------------------------------------------
# Coverage: the gate that runs at Stage 07, markdown only
# ----------------------------------------------------------------------------


def validate_report_plan_coverage(
    paths: RunPaths,
    figures_dirs: Sequence[Path] = (),
) -> list[str]:
    """At Stage 07: every planned slot was published, or dropped on the record.

    Markdown only. The latex branch has no single well-defined location for a
    published figure — the document places them — and it runs a layout review
    that covers the same ground, so a coverage check there would refuse work it
    cannot see.

    Dropping stays cheap: one sentence on the slot. What it stops being is
    silent, and because ``dropped_because`` is a committed field, writing it
    moves the digest and the amendment ledger records that the plan changed
    after the results were in.
    """
    plan = load_report_plan(paths)
    if plan is None or not plan.figures:
        # Absence and emptiness are the Stage 03 gate's refusals, and it runs
        # here too.
        return []

    referenced = set()
    if paths.report_file.is_file():
        try:
            report_text = paths.report_file.read_text(encoding="utf-8")
        except OSError:
            report_text = ""
        referenced = {
            PurePosixPath(target.split("#", 1)[0].split("?", 1)[0].strip()).name.casefold()
            for target in extract_markdown_image_targets(report_text)
        }

    search_dirs = [paths.report_images_dir, *figures_dirs]
    problems: list[str] = []
    for item in plan.figures:
        if item.is_dropped:
            continue
        published = bool(item.filename) and any(
            (directory / item.filename).is_file() for directory in search_dirs
        )
        if published and item.filename.casefold() in referenced:
            continue
        supports = ", ".join(item.supports) or "no claim"
        problems.append(
            f"planned figure slot {item.slot} ({item.filename or 'unnamed'}, supports "
            f"{supports}) was neither published nor dropped. Publish it under report/images/ "
            "and reference it from report.md, or record `dropped_because` on that slot in "
            f"report_plan.json ({MIN_DROP_REASON_CHARS} characters or more) saying what "
            "happened to the claim it carried."
        )

    if all(item.is_dropped for item in plan.figures):
        problems.append(
            "report_plan.json drops every planned figure, so the report argues for nothing "
            "the reader can see. Publish at least one of the planned slots, or re-plan the "
            "figures against the results that exist."
        )
    return problems


# ----------------------------------------------------------------------------
# Prompt rendering
# ----------------------------------------------------------------------------


def format_report_plan_for_prompt(plan: ReportPlan) -> str:
    lines: list[str] = []
    if plan.declared_at:
        lines.append(f"Declared at: {plan.declared_at} (Stage 03, before any result existed)")
    if plan.amendments:
        lines.append(f"Amendments on record: {len(plan.amendments)}")
        for amendment in plan.amendments:
            lines.append(
                f"  - {amendment.get('recorded_at', '')}: {amendment.get('reason', '')}"
            )
    if lines:
        lines.append("")

    lines.append("Planned figures:")
    for item in plan.figures:
        status = " — DROPPED" if item.is_dropped else ""
        lines.append(f"- **Slot {item.slot}: `{item.filename}`**{status}")
        lines.append(f"  - Supports: {', '.join(item.supports) or 'nothing declared'}")
        lines.append(f"  - Shows: {item.shows}")
        lines.append(f"  - If the claim holds: {item.if_supported}")
        lines.append(f"  - If it does not: {item.if_refuted}")
        lines.append(f"  - Computed from: `{item.source_artifact}`")
        if item.is_dropped:
            lines.append(f"  - Dropped because: {item.dropped_because}")

    if plan.headline_numbers:
        lines.append("")
        lines.append("Headline numbers the report must state:")
        for number in plan.headline_numbers:
            lines.append(
                f"- {number.quantity} ({number.unit}), from `{number.source_artifact}`"
            )
    return "\n".join(lines)
