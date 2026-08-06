"""ResearchClawBench adapter: run AutoR as a fully unattended benchmark agent.

`ResearchClawBench <https://github.com/InternScience/ResearchClawBench>`_ launches an agent
as a single shell command with the benchmark workspace as its working directory, captures
stdout, and then judges whatever ended up at ``<workspace>/report/report.md``. There is no
human on the other end and no second chance to ask a question.

Two things have to be bridged for AutoR to run in that harness:

1. **No human.** AutoR's approval gate is replaced by the reviewer agent (``--full-auto``)
   and every remaining terminal prompt is turned into a hard error rather than a hang.
   See :mod:`src.terminal_ui`'s unattended mode.
2. **No shared output contract.** AutoR writes a run tree under ``runs/<run_id>/``; the
   benchmark reads ``report/report.md``, ``report/images/*.png``, ``code/`` and ``outputs/``
   inside the workspace. :func:`export_run` performs that translation after the pipeline
   finishes, whether it succeeded or not — a partial report scores better than no report.

   With the default ``markdown`` output format Stage 07 already produces the report, so the
   translation is a copy. With ``latex`` it produces a paper package instead, and the report
   has to be synthesized from the approved artifacts.

The report itself is produced by the first of four paths that yields real content:

``agent``
    Something wrote ``report/report.md`` at the benchmark path directly, because the goal
    contract asked for it. A report AutoR exported on an earlier pass does not count: the
    digest in ``.autor_export.json`` distinguishes the two.
``stage``
    Stage 07 ran in ``markdown`` output mode, so its gate-checked deliverable already exists in
    the run tree and is promoted verbatim.
``synthesized``
    A single extra operator call converts the approved run artifacts into the benchmark's
    markdown format.
``fallback``
    Pure-Python assembly from the approved stage summaries. Always available, so the
    harness never sees an empty workspace.
"""

from __future__ import annotations

import filecmp
import hashlib
import json
import shutil
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, TextIO

from .utils import (
    DEFAULT_OUTPUT_FORMAT,
    MIN_REPORT_CHARS,
    RunPaths,
    StageSpec,
    approved_stage_summaries,
    build_run_paths,
    read_text,
    resolve_output_format,
    truncate_text,
    write_text,
)


#: Directories the benchmark harness expects to exist inside the workspace.
RCB_WORKSPACE_DIRS = ("code", "outputs", "report", "report/images")

#: Directory holding the AutoR run tree, kept inside the workspace so a run is self-contained.
AUTOR_RUNS_DIRNAME = ".autor"

#: Records which report AutoR last exported, so a re-export can tell its own output apart
#: from one the agent wrote. A dotfile at the workspace root: the benchmark reads only
#: report/, outputs/ and the metadata files it writes itself, so this stays invisible to it.
EXPORT_MARKER_NAME = ".autor_export.json"

#: Synthetic stage used only to label the report-synthesis operator call in the logs.
REPORT_STAGE = StageSpec(9, "09_benchmark_report", "Benchmark Report")

FIGURE_SUFFIXES = (".png",)

#: Run-tree directories never mirrored into the benchmark workspace.
EXPORT_SKIP_DIRS = frozenset({"__pycache__", ".git", ".ipynb_checkpoints", "node_modules"})


@dataclass(frozen=True)
class ExportResult:
    report_path: Path
    report_source: str
    figures: list[str] = field(default_factory=list)
    code_files: int = 0
    output_files: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["report_path"] = str(self.report_path)
        return payload


@dataclass(frozen=True)
class BenchmarkResult:
    workspace: Path
    run_root: Path
    pipeline_completed: bool
    export: ExportResult
    auto_skipped_stages: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        """0 when a real report reached the harness.

        The pipeline completing is not the bar: ResearchClawBench scores the report, so a
        run that auto-skipped a stage but still produced a substantive report is a success,
        and a "completed" run with an empty report is not.
        """
        return 0 if self.export.report_path.exists() else 1


# ---------------------------------------------------------------------------
# Workspace and goal
# ---------------------------------------------------------------------------


def ensure_workspace_layout(workspace: Path) -> None:
    for name in RCB_WORKSPACE_DIRS:
        (workspace / name).mkdir(parents=True, exist_ok=True)


def build_benchmark_goal(
    workspace: Path,
    instructions: str,
    output_format: str = DEFAULT_OUTPUT_FORMAT,
) -> str:
    """Wrap the benchmark instructions in an explicit output contract.

    The goal is injected verbatim into every stage prompt, so stating the workspace
    contract here is what makes each stage write to the benchmark's paths instead of only
    to the AutoR run tree.
    """
    resolved = workspace.resolve()
    report_instruction = (
        "Stage 07 (Writing) writes this file as its primary deliverable. Keep the copy here in "
        "sync with it."
        if resolve_output_format(output_format) == "markdown"
        else "Write this file during Stage 07 (Writing) at the latest, in addition to the "
        "normal LaTeX paper package. Do not defer it to the end of the run."
    )
    return "\n\n".join(
        [
            "# Benchmark Run: ResearchClawBench",
            (
                "This run is being scored by ResearchClawBench. There is no human available at "
                "any point: no one will answer a question, approve a plan, or grant a permission. "
                "Make the best judgement you can from the data and keep going."
            ),
            "## Benchmark Workspace Contract",
            (
                f"The benchmark workspace is `{resolved}`. It is separate from the AutoR run tree "
                "and it is the only thing the judge will read. Alongside the normal AutoR stage "
                "artifacts, every stage must keep these paths up to date:\n\n"
                f"- `{resolved}/data/` — input datasets. **Read-only. Never modify or delete.**\n"
                f"- `{resolved}/related_work/` — reference papers. **Read-only.**\n"
                f"- `{resolved}/code/` — all analysis code you write.\n"
                f"- `{resolved}/outputs/` — intermediate results, tables, and derived data.\n"
                f"- `{resolved}/report/images/` — every figure, saved as **PNG only** "
                "(no PDF, EPS, SVG, TIFF, or BMP — the judge cannot render them).\n"
                f"- `{resolved}/report/report.md` — the final research report.\n"
            ),
            "## Report Requirements",
            (
                f"`{resolved}/report/report.md` is the scored deliverable. It must be a standalone "
                "markdown research report containing methodology, quantitative results, figures, "
                "and discussion, written in academic style. Reference figures with paths relative "
                "to the report itself, for example `![Result](images/main_result.png)` — never "
                "with absolute paths. Report concrete numbers, not adjectives; the judge compares "
                "your results against the original paper's and is explicitly sceptical of "
                "plausible-sounding claims with no evidence behind them. Length is not rewarded.\n\n"
                f"{report_instruction}"
            ),
            "## Research Task",
            instructions.strip(),
        ]
    )


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _iter_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in EXPORT_SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        files.append(path)
    return files


def mirror_tree(source: Path, destination: Path) -> int:
    """Copy every file under *source* into *destination*, preserving relative layout."""
    copied = 0
    for path in _iter_files(source):
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
    return copied


def collect_figures(paths: RunPaths, workspace: Path) -> list[str]:
    """Copy run-tree PNGs into ``report/images/`` and return the report-relative names.

    Figures already written straight to ``report/images/`` are included without being
    recopied, so the goal contract and this fallback sweep cannot produce duplicates.
    """
    images_dir = workspace / "report" / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    names = {path.name for path in images_dir.iterdir() if path.is_file() and path.suffix.lower() in FIGURE_SUFFIXES}

    # The run tree's own report/images/ comes first: in markdown mode those are the figures the
    # report actually references by name, so they must keep their filenames. A same-named figure
    # swept up later from figures/ or results/ is the one that gets qualified.
    for source_root in (
        paths.report_images_dir,
        paths.figures_dir,
        paths.writing_dir,
        paths.results_dir,
        paths.artifacts_dir,
    ):
        for path in _iter_files(source_root):
            if path.suffix.lower() not in FIGURE_SUFFIXES:
                continue
            target_name = path.name
            if target_name in names:
                existing = images_dir / target_name
                if filecmp.cmp(path, existing, shallow=False):
                    # The same figure, already exported by the pipeline itself.
                    continue
                # A genuinely different figure sharing a basename: qualify rather than clobber.
                target_name = f"{source_root.name}_{path.stem}{path.suffix}"
                if target_name in names:
                    continue
            shutil.copy2(path, images_dir / target_name)
            names.add(target_name)

    return sorted(names)


def build_fallback_report(
    *,
    paths: RunPaths,
    figures: list[str],
    pipeline_completed: bool,
    auto_skipped_stages: list[str],
) -> str:
    """Assemble a report from approved stage summaries with no model call.

    This is deliberately honest rather than flattering: it says which stages were skipped,
    because a report that hides a gap is worse than one the judge can calibrate against.
    """
    sections: list[str] = ["# Research Report", ""]

    if not pipeline_completed:
        sections.extend(
            [
                "> **Incomplete run.** The AutoR pipeline did not finish every stage. This report "
                "was assembled from the stages that were approved.",
                "",
            ]
        )
    if auto_skipped_stages:
        sections.extend(
            [
                "> **Auto-skipped stages:** " + ", ".join(auto_skipped_stages) + ".",
                "",
            ]
        )

    for stage_path in sorted(paths.stages_dir.glob("*.md")) if paths.stages_dir.exists() else []:
        if stage_path.name.endswith(".tmp.md"):
            continue
        body = read_text(stage_path).strip()
        if body:
            sections.extend([body, "", "---", ""])

    if len(sections) <= 2:
        summaries = approved_stage_summaries(read_text(paths.memory)) if paths.memory.exists() else "None yet."
        sections.extend([summaries if summaries != "None yet." else "_No approved stage output was produced._", ""])

    if figures:
        sections.extend(["## Figures", ""])
        for name in figures:
            sections.extend([f"![{Path(name).stem}](images/{name})", ""])

    return "\n".join(sections).rstrip() + "\n"


def _report_digest(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def _matches_export_marker(workspace: Path, report_text: str) -> bool:
    """True when the report at the benchmark path is one AutoR itself exported earlier.

    The marker records the digest of what was written; this comparison is the only thing
    that makes it worth writing. An unreadable or absent marker means "assume the agent
    wrote it", which is the conservative answer: it preserves a real report.
    """
    if not report_text:
        return False
    marker_path = workspace / EXPORT_MARKER_NAME
    if not marker_path.exists():
        return False
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("report_sha256") == _report_digest(report_text)


def _publish_report(workspace: Path, report_path: Path, text: str, source: str) -> None:
    """Write the benchmark report and record that AutoR, not the agent, authored it."""
    body = text.strip() + "\n"
    write_text(report_path, body)
    marker = {"report_source": source, "report_sha256": _report_digest(body)}
    (workspace / EXPORT_MARKER_NAME).write_text(
        json.dumps(marker, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def export_run(
    *,
    paths: RunPaths,
    workspace: Path,
    pipeline_completed: bool,
    auto_skipped_stages: list[str] | None = None,
    synthesize: "ReportSynthesizer | None" = None,
) -> ExportResult:
    """Translate a finished AutoR run tree into the ResearchClawBench deliverables."""
    ensure_workspace_layout(workspace)
    auto_skipped_stages = auto_skipped_stages or []

    code_files = mirror_tree(paths.code_dir, workspace / "code")
    output_files = mirror_tree(paths.results_dir, workspace / "outputs")
    output_files += mirror_tree(paths.notes_dir, workspace / "outputs" / "notes")
    figures = collect_figures(paths, workspace)

    report_path = workspace / "report" / "report.md"

    def result(source: str) -> ExportResult:
        return ExportResult(
            report_path=report_path,
            report_source=source,
            figures=figures,
            code_files=code_files,
            output_files=output_files,
        )

    existing = read_text(report_path).strip() if report_path.exists() else ""
    # A report AutoR exported on an earlier pass is not the agent's own work, and must not
    # outrank a Stage 07 report written since. Without this check `--export-only` after an
    # interrupted run keeps re-publishing the first fallback forever.
    existing_is_ours = _matches_export_marker(workspace, existing)
    if len(existing) >= MIN_REPORT_CHARS and not existing_is_ours:
        return result("agent")

    # In markdown mode Stage 07's deliverable is workspace/report/report.md *inside the run
    # tree*. Promoting it is the normal path, not a fallback: it is a validated, gate-checked
    # report, so it outranks both a stub at the benchmark path and a fresh synthesis call.
    stage_report = read_text(paths.report_file).strip() if paths.report_file.exists() else ""
    if len(stage_report) >= MIN_REPORT_CHARS:
        _publish_report(workspace, report_path, stage_report, "stage")
        return result("stage")

    if synthesize is not None:
        synthesized = synthesize(paths=paths, workspace=workspace, figures=figures)
        if synthesized and len(synthesized.strip()) >= MIN_REPORT_CHARS:
            _publish_report(workspace, report_path, synthesized.strip(), "synthesized")
            return result("synthesized")
        # A synthesis attempt that came back thin is worse than the deterministic assembly,
        # so fall through rather than shipping it.

    _publish_report(
        workspace,
        report_path,
        build_fallback_report(
            paths=paths,
            figures=figures,
            pipeline_completed=pipeline_completed,
            auto_skipped_stages=auto_skipped_stages,
        ),
        "fallback",
    )
    return result("fallback")


# ---------------------------------------------------------------------------
# Operator-backed report synthesis
# ---------------------------------------------------------------------------


class ReportSynthesizer:
    """Turn approved run artifacts into ``report/report.md`` with one operator call.

    Uses the same private invocation seam as :class:`src.approval_agent.AutomatedReviewer`,
    so it works with either operator backend without widening ``OperatorProtocol``.
    """

    def __init__(self, operator: Any) -> None:
        self.operator = operator

    def supported(self) -> bool:
        return all(
            hasattr(self.operator, name)
            for name in ("_prepare_invocation", "_run_streaming_command")
        )

    def __call__(self, *, paths: RunPaths, workspace: Path, figures: list[str]) -> str | None:
        if not self.supported():
            return None

        report_path = workspace / "report" / "report.md"
        prompt_path = paths.prompt_cache_dir / "09_benchmark_report.prompt.md"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        write_text(prompt_path, self.build_prompt(paths=paths, workspace=workspace, figures=figures))

        session_id = str(uuid.uuid4())
        try:
            command, cwd, stdin_text = self.operator._prepare_invocation(  # noqa: SLF001
                prompt_path,
                session_id,
                paths=paths,
                resume=False,
            )
            exit_code, _stdout, _stderr, _session, _meta = self.operator._run_streaming_command(  # noqa: SLF001
                command=command,
                cwd=cwd,
                stage=REPORT_STAGE,
                attempt_no=1,
                paths=paths,
                mode="benchmark_report",
                stdin_text=stdin_text,
            )
        except Exception:  # noqa: BLE001 - synthesis is best-effort; the fallback still runs
            return None

        if exit_code != 0 or not report_path.exists():
            return None
        return read_text(report_path)

    def build_prompt(self, *, paths: RunPaths, workspace: Path, figures: list[str]) -> str:
        resolved_report = (workspace / "report" / "report.md").resolve()
        figure_lines = (
            "\n".join(f"- `images/{name}`" for name in figures)
            if figures
            else "- (no figures were produced; generate them from the run's data if you can)"
        )
        return (
            "# AutoR Task: Benchmark Report\n\n"
            "You are assembling the single scored deliverable for a ResearchClawBench run. "
            "The AutoR research pipeline has already executed; your job is to turn its approved "
            "artifacts into the report the benchmark judge will read.\n\n"
            f"Write the report to `{resolved_report}`, overwriting whatever is there.\n\n"
            "## Requirements\n"
            "- Standalone markdown. Sections at minimum: Introduction / Problem, Data, "
            "Methodology, Results, Discussion, Limitations.\n"
            "- Report concrete quantitative results — actual numbers, metrics, and units taken "
            "from the run's artifacts. The judge compares them against a published paper and is "
            "explicitly sceptical of unsupported claims.\n"
            "- Never invent a number, a citation, or a result. If the run did not measure "
            "something, say so plainly under Limitations.\n"
            "- Reference figures with report-relative paths only, for example "
            "`![Main result](images/main_result.png)`.\n"
            "- Do not pad. Length is not rewarded; evidence is.\n"
            "- Read the workspace artifacts listed below before writing. Do not write the report "
            "from this prompt alone.\n\n"
            "## Available Figures\n\n"
            f"{figure_lines}\n\n"
            "## Run Artifacts To Read\n\n"
            f"- run root: `{paths.run_root.resolve()}`\n"
            f"- approved stage summaries: `{paths.stages_dir.resolve()}`\n"
            f"- workspace results: `{paths.results_dir.resolve()}`\n"
            f"- workspace code: `{paths.code_dir.resolve()}`\n"
            f"- experiment manifest: `{paths.experiment_manifest.resolve()}`\n"
            f"- artifact index: `{paths.artifact_index.resolve()}`\n"
            f"- LaTeX paper package: `{paths.writing_dir.resolve()}`\n"
            f"- benchmark workspace: `{workspace.resolve()}`\n\n"
            "## Original Task\n\n"
            f"{truncate_text(read_text(paths.user_input), max_chars=8000)}\n\n"
            "## Approved Memory\n\n"
            f"{truncate_text(read_text(paths.memory), max_chars=16000)}\n"
        )


# ---------------------------------------------------------------------------
# Progress events
# ---------------------------------------------------------------------------


def emit_event(payload: dict[str, Any], stream: TextIO | None = None) -> None:
    """Write one JSON line to stdout for the harness's run log."""
    target = stream if stream is not None else sys.stdout
    target.write(json.dumps(payload, ensure_ascii=False) + "\n")
    target.flush()


def resolve_instructions(
    *,
    prompt: str | None,
    prompt_file: str | Path | None,
    workspace: Path,
) -> str:
    """Resolve the benchmark instructions from the flag, a file, or the workspace default."""
    if prompt and prompt.strip():
        return prompt.strip()

    candidates: list[Path] = []
    if prompt_file:
        candidates.append(Path(prompt_file).expanduser())
    candidates.append(workspace / "INSTRUCTIONS.md")

    for candidate in candidates:
        if candidate.exists():
            text = candidate.read_text(encoding="utf-8").strip()
            if text:
                return text

    raise ValueError(
        "No benchmark instructions found. Pass --prompt or --prompt-file, or place "
        f"INSTRUCTIONS.md in {workspace}."
    )


def runs_dir_for(workspace: Path) -> Path:
    return workspace / AUTOR_RUNS_DIRNAME


def latest_run_root(runs_dir: Path) -> Path | None:
    if not runs_dir.exists():
        return None
    candidates = sorted(path for path in runs_dir.iterdir() if path.is_dir())
    return candidates[-1] if candidates else None


def build_run_paths_for_workspace(workspace: Path) -> RunPaths | None:
    run_root = latest_run_root(runs_dir_for(workspace))
    return build_run_paths(run_root) if run_root is not None else None
