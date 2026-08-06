"""Prompt text that belongs to every stage, held once instead of copied ten times.

Ten stage templates each restated the same rules about where a stage may write,
who promotes the draft, and who decides progression. Five identical lines across
ten files is not a style problem: it is five places to forget when the rule
changes, and the copies had already drifted — Stage 01 alone carried an extra
"Do not approve the stage yourself" line, and the ordering differed between
files for no reason.

Two of these fragments are *derived from the constants the validators use*
rather than written as prose. The accepted-extension lists were hand-copied into
three prompts and two of the copies were already incomplete subsets of
``MACHINE_DATA_SUFFIXES`` and ``RESULT_SUFFIXES``. A sentence generated from the
constant cannot drift from it; a sentence describing the constant can, and had.

Composition happens in ``_build_stage_prompt`` *before* placeholder
substitution, so fragments may use the same ``{{TOKEN}}`` vocabulary as the
templates and get expanded for free. No new token is introduced.
"""

from __future__ import annotations

from .utils import (
    FIGURE_SUFFIXES,
    MACHINE_DATA_SUFFIXES,
    RENDERABLE_IMAGE_SUFFIXES,
    RESULT_SUFFIXES,
    StageSpec,
)


STAGE_HEADER = "# Stage {{STAGE_NUMBER}}: {{STAGE_NAME}}"


#: Where a stage may write, and who decides what happens next. One semantic
#: cluster, none of it stage-specific. Appended after the stage's own
#: instructions rather than merged into each template's Filesystem section,
#: because the bullets that remain there are genuine per-stage directory
#: routing.
RUN_SAFETY = """## Run Safety

- Write only under `{{WORKSPACE_ROOT}}`.
- Put this attempt's stage summary at `{{STAGE_OUTPUT_PATH}}`. The manager validates and
  promotes it to `{{STAGE_FINAL_OUTPUT_PATH}}`; never write that path yourself.
- You do not approve this stage or decide what runs next."""


def _extensions(suffixes: set[str]) -> str:
    return ", ".join(f"`{item}`" for item in sorted(suffixes))


def artifact_formats(stage: StageSpec, output_format: str) -> str:
    """The extensions a stage's gate can actually see, straight from the constants.

    The Stage 06 markdown branch resolves a real contradiction rather than
    restating a rule: ``FIGURE_SUFFIXES`` accepts SVG and PDF, so an SVG figure
    passes Stage 06's gate — and ``RENDERABLE_IMAGE_SUFFIXES`` does not, so the
    same figure is invisible to the reviewer one stage later. Saying so at the
    point the figure is created is cheaper than a Stage 07 failure that reads as
    "no figures".
    """
    if stage.number == 3:
        return (
            "## Accepted Machine-Readable Formats\n\n"
            "Dataset artifacts under `{{WORKSPACE_DATA_DIR}}` must use one of these extensions, "
            f"or the stage gate does not see them: {_extensions(MACHINE_DATA_SUFFIXES)}."
        )
    if stage.number == 5:
        return (
            "## Accepted Machine-Readable Formats\n\n"
            "Result artifacts under `{{WORKSPACE_RESULTS_DIR}}` must use one of these extensions, "
            f"or the stage gate does not see them: {_extensions(RESULT_SUFFIXES)}."
        )
    if stage.number == 6:
        if output_format == "markdown":
            return (
                "## Accepted Figure Formats\n\n"
                "This run is in markdown mode. Save figures under `{{WORKSPACE_FIGURES_DIR}}` as "
                "**PNG**. Stage 06 would accept "
                f"{_extensions(FIGURE_SUFFIXES)}, but Stage 07 only attaches "
                f"{_extensions(RENDERABLE_IMAGE_SUFFIXES)} to the report, so an SVG or PDF figure "
                "passes here and counts as no figure at all one stage later."
            )
        return (
            "## Accepted Figure Formats\n\n"
            "Figures under `{{WORKSPACE_FIGURES_DIR}}` must use one of these extensions: "
            f"{_extensions(FIGURE_SUFFIXES)}."
        )
    return ""


def stage_fragments(stage: StageSpec, output_format: str) -> list[str]:
    """Shared blocks for this stage, in the order they should appear."""
    return [block for block in (artifact_formats(stage, output_format),) if block]


def compose_stage_template(template: str, stage: StageSpec, output_format: str) -> str:
    """Assemble the full pre-substitution stage instruction text.

    Order matters: the stage's own instructions first, then the format rules
    that constrain them, then the safety rules that constrain everything.
    """
    parts = [STAGE_HEADER, template.strip(), *stage_fragments(stage, output_format), RUN_SAFETY]
    return "\n\n".join(part for part in parts if part)
