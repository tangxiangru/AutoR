from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import re

from .artifact_index import indexed_artifacts_for_category, write_artifact_index
from .utils import (
    MIN_REPORT_CHARS,
    PREFERRED_REPORT_IMAGE_SUFFIX,
    RENDERABLE_IMAGE_SUFFIXES,
    RunPaths,
    extract_markdown_image_targets,
    read_text,
    resolve_report_image,
    selected_output_format,
)


FIGURE_SUFFIXES = {".png", ".pdf", ".svg", ".jpg", ".jpeg", ".eps"}
RESULT_SUFFIXES = {".json", ".jsonl", ".csv", ".tsv", ".parquet", ".npz", ".npy"}
_LATEX_WARNING_SAMPLE_LIMIT = 5
_REPORT_ISSUE_SAMPLE_LIMIT = 5


def build_writing_manifest(paths: RunPaths) -> dict[str, object]:
    artifact_index = write_artifact_index(paths)
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "artifact_index_path": str(paths.artifact_index.relative_to(paths.run_root)),
        "figures": indexed_artifacts_for_category(artifact_index, "figures"),
        "result_files": indexed_artifacts_for_category(artifact_index, "results"),
        "data_files": indexed_artifacts_for_category(artifact_index, "data"),
        "stage_summaries": _collect_stage_summaries(paths),
    }
    if selected_output_format(paths) == "markdown":
        report_review = _load_review_summary(paths, "report_review.json")
        if report_review is not None:
            manifest["report_review"] = report_review
    else:
        layout_review = _load_review_summary(paths, "layout_review.json")
        if layout_review is not None:
            manifest["layout_review"] = layout_review

    paths.writing_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = paths.writing_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def scan_figures(figures_dir: Path) -> list[dict[str, object]]:
    if not figures_dir.exists():
        return []

    figures: list[dict[str, object]] = []
    for path in sorted(figures_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in FIGURE_SUFFIXES:
            figures.append(
                {
                    "filename": path.name,
                    "rel_path": f"figures/{path.relative_to(figures_dir)}",
                    "size_bytes": path.stat().st_size,
                }
            )
    return figures


def scan_results(results_dir: Path) -> list[dict[str, object]]:
    if not results_dir.exists():
        return []

    results: list[dict[str, object]] = []
    for path in sorted(results_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in RESULT_SUFFIXES:
            results.append(
                {
                    "filename": path.name,
                    "rel_path": f"results/{path.relative_to(results_dir)}",
                    "type": path.suffix.lstrip("."),
                }
            )
    return results


def format_manifest_for_prompt(manifest: dict[str, object]) -> str:
    parts: list[str] = []
    artifact_index_path = manifest.get("artifact_index_path")
    if isinstance(artifact_index_path, str) and artifact_index_path.strip():
        parts.append(f"Artifact index: `{artifact_index_path}`")

    layout_review = manifest.get("report_review") or manifest.get("layout_review")
    if isinstance(layout_review, dict):
        parts.append("\n### Report Review" if "report_review" in manifest else "\n### Layout Review")
        review_path = str(layout_review.get("path") or "").strip()
        if review_path:
            parts.append(f"- Layout review artifact: `{review_path}`")
        status = str(layout_review.get("overall_status") or "").strip()
        if status:
            parts.append(f"- Overall status: {status}")
        issue_counts = layout_review.get("issue_counts")
        if isinstance(issue_counts, dict) and issue_counts:
            counts = ", ".join(f"{key}={value}" for key, value in sorted(issue_counts.items()))
            parts.append(f"- Issue counts: {counts}")
        fixes = layout_review.get("priority_fixes")
        if isinstance(fixes, list) and fixes:
            parts.append("- Priority fixes:")
            for fix in fixes[:3]:
                parts.append(f"  - {fix}")

    figures = manifest.get("figures", [])
    if isinstance(figures, list) and figures:
        parts.append("\n### Available Figures")
        for fig in figures:
            if isinstance(fig, dict):
                line = f"- `{fig['rel_path']}` ({fig['size_bytes']} bytes)"
                schema = _format_schema(fig.get("schema"))
                if schema:
                    line += f" | {schema}"
                parts.append(line)

    result_files = manifest.get("result_files", [])
    if isinstance(result_files, list) and result_files:
        parts.append("\n### Available Result Files")
        for result in result_files:
            if isinstance(result, dict):
                line = f"- `{result['rel_path']}` (type: {result.get('suffix', '').lstrip('.') or 'file'})"
                schema = _format_schema(result.get("schema"))
                if schema:
                    line += f" | {schema}"
                parts.append(line)

    data_files = manifest.get("data_files", [])
    if isinstance(data_files, list) and data_files:
        parts.append("\n### Available Data Files")
        for data_file in data_files:
            if isinstance(data_file, dict):
                line = f"- `{data_file['rel_path']}`"
                schema = _format_schema(data_file.get("schema"))
                if schema:
                    line += f" | {schema}"
                parts.append(line)

    stage_summaries = manifest.get("stage_summaries", {})
    if isinstance(stage_summaries, dict) and stage_summaries:
        parts.append("\n### Available Stage Summaries")
        for stage_slug, rel_path in sorted(stage_summaries.items()):
            parts.append(f"- `{stage_slug}` -> `{rel_path}`")

    if not parts:
        parts.append("No experiment artifacts found in workspace.")

    return "\n".join(parts)


def _scan_dir(directory: Path) -> list[str]:
    if not directory.exists():
        return []

    return sorted(
        str(path.relative_to(directory.parent))
        for path in directory.rglob("*")
        if path.is_file()
    )


def _collect_stage_summaries(paths: RunPaths) -> dict[str, str]:
    summaries: dict[str, str] = {}
    if paths.stages_dir.exists():
        for stage_file in sorted(paths.stages_dir.glob("*.md")):
            if not stage_file.name.endswith(".tmp.md"):
                summaries[stage_file.stem] = str(stage_file.relative_to(paths.run_root))
    return summaries


def generate_layout_review(paths: RunPaths) -> dict[str, object]:
    pdf_path = _find_preferred_pdf(paths)
    build_log_path = _find_existing_path(
        [
            paths.artifacts_dir / "build_log.txt",
            paths.writing_dir / "build.log",
            paths.artifacts_dir / "build.log",
            paths.artifacts_dir / "paper_package" / "build.log",
        ]
    )
    build_log_text = read_text(build_log_path) if build_log_path is not None else ""

    overfull_lines = _extract_matching_lines(build_log_text, r"Overfull \\hbox")
    underfull_lines = _extract_matching_lines(build_log_text, r"Underfull \\hbox")
    undefined_ref_lines = _extract_matching_lines(build_log_text, r"Reference [`'][^`']+['`] on page \d+ undefined|Reference [`'][^`']+['`] undefined")
    undefined_citation_lines = _extract_matching_lines(build_log_text, r"Citation [`'][^`']+['`] on page \d+ undefined|Citation [`'][^`']+['`] undefined")
    missing_file_lines = _extract_matching_lines(build_log_text, r"(File|Package).*not found|No file .*")

    issue_counts = {
        "overfull_hboxes": len(overfull_lines),
        "underfull_hboxes": len(underfull_lines),
        "undefined_references": len(undefined_ref_lines),
        "undefined_citations": len(undefined_citation_lines),
        "missing_file_warnings": len(missing_file_lines),
    }
    issue_counts["total"] = sum(issue_counts.values())

    issues: list[dict[str, object]] = []
    if pdf_path is None:
        issues.append(
            {
                "category": "pdf",
                "severity": "major",
                "summary": "Compiled paper PDF was not found under workspace/writing or workspace/artifacts.",
                "evidence": [],
            }
        )
    if overfull_lines:
        issues.append(
            {
                "category": "overfull_hbox",
                "severity": "major" if len(overfull_lines) >= 3 else "minor",
                "summary": f"Detected {len(overfull_lines)} overfull box warning(s) that can indicate text or figure overflow.",
                "evidence": overfull_lines[:_LATEX_WARNING_SAMPLE_LIMIT],
            }
        )
    if underfull_lines:
        issues.append(
            {
                "category": "underfull_hbox",
                "severity": "minor",
                "summary": f"Detected {len(underfull_lines)} underfull box warning(s) that can indicate weak paragraph breaks or spacing.",
                "evidence": underfull_lines[:_LATEX_WARNING_SAMPLE_LIMIT],
            }
        )
    if undefined_ref_lines:
        issues.append(
            {
                "category": "undefined_reference",
                "severity": "major",
                "summary": f"Detected {len(undefined_ref_lines)} undefined reference warning(s).",
                "evidence": undefined_ref_lines[:_LATEX_WARNING_SAMPLE_LIMIT],
            }
        )
    if undefined_citation_lines:
        issues.append(
            {
                "category": "undefined_citation",
                "severity": "major",
                "summary": f"Detected {len(undefined_citation_lines)} undefined citation warning(s).",
                "evidence": undefined_citation_lines[:_LATEX_WARNING_SAMPLE_LIMIT],
            }
        )
    if missing_file_lines:
        issues.append(
            {
                "category": "missing_asset",
                "severity": "major",
                "summary": f"Detected {len(missing_file_lines)} missing-file or missing-package warning(s).",
                "evidence": missing_file_lines[:_LATEX_WARNING_SAMPLE_LIMIT],
            }
        )

    priority_fixes = _suggest_layout_fixes(
        pdf_available=pdf_path is not None,
        overfull_count=len(overfull_lines),
        undefined_ref_count=len(undefined_ref_lines),
        undefined_citation_count=len(undefined_citation_lines),
        missing_file_count=len(missing_file_lines),
        underfull_count=len(underfull_lines),
    )

    review = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "overall_status": "needs_attention" if issues else "clean",
        "pdf_available": pdf_path is not None,
        "pdf_relative_path": str(pdf_path.relative_to(paths.run_root)) if pdf_path is not None else None,
        "estimated_page_count": _estimate_pdf_page_count(pdf_path),
        "build_log_checked": build_log_path is not None,
        "build_log_relative_path": str(build_log_path.relative_to(paths.run_root)) if build_log_path is not None else None,
        "issue_counts": issue_counts,
        "issues": issues,
        "priority_fixes": priority_fixes,
    }
    output_path = paths.artifacts_dir / "layout_review.json"
    output_path.write_text(json.dumps(review, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return review


def generate_report_review(paths: RunPaths) -> dict[str, object]:
    """Audit the markdown deliverable the way the benchmark judge will consume it.

    The judge reads ``report/report.md`` as text and attaches image files it finds on disk.
    Nothing in that path renders markdown, so the failure modes are not typographic like
    LaTeX's: they are a figure reference that points at nothing, a path that only resolves on
    the machine that wrote it, and a format the viewer cannot decode. This mirrors
    :func:`generate_layout_review`'s contract so the stage prompt can carry either one.
    """
    report_path = paths.report_file
    report_exists = report_path.exists()
    report_text = read_text(report_path) if report_exists else ""

    targets = extract_markdown_image_targets(report_text)
    broken: list[str] = []
    non_relative: list[str] = []
    unrenderable: list[str] = []
    non_preferred: list[str] = []
    resolved_names: set[str] = set()

    for target in targets:
        resolved = resolve_report_image(paths.report_dir, target)
        if resolved is None:
            non_relative.append(target)
            continue
        if not resolved.exists():
            broken.append(target)
            continue
        suffix = resolved.suffix.lower()
        if suffix not in RENDERABLE_IMAGE_SUFFIXES:
            unrenderable.append(target)
            continue
        if suffix != PREFERRED_REPORT_IMAGE_SUFFIX:
            non_preferred.append(target)
        resolved_names.add(resolved.resolve().as_posix())

    available = [
        path
        for path in sorted(paths.report_images_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in RENDERABLE_IMAGE_SUFFIXES
    ]
    unreferenced = [path.name for path in available if path.resolve().as_posix() not in resolved_names]

    issue_counts = {
        "broken_image_links": len(broken),
        "non_relative_image_links": len(non_relative),
        "unrenderable_images": len(unrenderable),
        "non_png_images": len(non_preferred),
        "unreferenced_images": len(unreferenced),
    }
    issue_counts["total"] = sum(issue_counts.values())

    issues: list[dict[str, object]] = []
    if not report_exists:
        issues.append(
            {
                "category": "report",
                "severity": "critical",
                "summary": "No markdown research report was found at workspace/report/report.md.",
                "evidence": [],
            }
        )
    elif len(report_text.strip()) < MIN_REPORT_CHARS:
        issues.append(
            {
                "category": "report_length",
                "severity": "critical",
                "summary": (
                    f"report.md holds only {len(report_text.strip())} characters, below the "
                    f"{MIN_REPORT_CHARS}-character floor for a scored research report."
                ),
                "evidence": [],
            }
        )
    if report_exists and not targets:
        issues.append(
            {
                "category": "missing_figures",
                "severity": "critical",
                "summary": "report.md embeds no figures; the judge scores figure criteria against images the report references.",
                "evidence": [],
            }
        )
    if broken:
        issues.append(
            {
                "category": "broken_image_link",
                "severity": "critical",
                "summary": f"{len(broken)} figure reference(s) point at files that do not exist under report/.",
                "evidence": broken[:_REPORT_ISSUE_SAMPLE_LIMIT],
            }
        )
    if non_relative:
        issues.append(
            {
                "category": "non_relative_image_link",
                "severity": "major",
                "summary": (
                    f"{len(non_relative)} figure reference(s) are absolute paths or URLs and will not "
                    "resolve for the judge."
                ),
                "evidence": non_relative[:_REPORT_ISSUE_SAMPLE_LIMIT],
            }
        )
    if unrenderable:
        issues.append(
            {
                "category": "unrenderable_image",
                "severity": "major",
                "summary": f"{len(unrenderable)} figure reference(s) use a format the report viewer cannot render.",
                "evidence": unrenderable[:_REPORT_ISSUE_SAMPLE_LIMIT],
            }
        )
    if non_preferred:
        issues.append(
            {
                "category": "non_png_image",
                "severity": "minor",
                "summary": f"{len(non_preferred)} figure(s) are not PNG; the benchmark asks for PNG only.",
                "evidence": non_preferred[:_REPORT_ISSUE_SAMPLE_LIMIT],
            }
        )
    if unreferenced:
        issues.append(
            {
                "category": "unreferenced_image",
                "severity": "minor",
                "summary": (
                    f"{len(unreferenced)} image(s) under report/images/ are never referenced by report.md "
                    "and carry no caption to be judged against."
                ),
                "evidence": unreferenced[:_REPORT_ISSUE_SAMPLE_LIMIT],
            }
        )

    review = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "overall_status": "needs_attention" if issues else "clean",
        "report_available": report_exists,
        "report_relative_path": str(report_path.relative_to(paths.run_root)) if report_exists else None,
        "report_char_count": len(report_text.strip()),
        "referenced_image_count": len(targets),
        "available_image_count": len(available),
        "issue_counts": issue_counts,
        "issues": issues,
        "priority_fixes": _suggest_report_fixes(
            report_exists=report_exists,
            report_chars=len(report_text.strip()),
            referenced=len(targets),
            broken=len(broken),
            non_relative=len(non_relative),
            unrenderable=len(unrenderable),
            unreferenced=len(unreferenced),
        ),
    }
    paths.artifacts_dir.mkdir(parents=True, exist_ok=True)
    output_path = paths.artifacts_dir / "report_review.json"
    output_path.write_text(json.dumps(review, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return review


def validate_report_review(path: Path) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ["report_review.json is missing."]
    except json.JSONDecodeError as exc:
        return [f"report_review.json is not valid JSON: {exc}"]

    if not isinstance(payload, dict):
        return ["report_review.json must contain a JSON object."]

    problems: list[str] = []
    if not isinstance(payload.get("overall_status"), str) or not str(payload.get("overall_status")).strip():
        problems.append("report_review.json must contain a non-empty string field 'overall_status'.")
    if not isinstance(payload.get("report_available"), bool):
        problems.append("report_review.json must contain a boolean field 'report_available'.")
    if not isinstance(payload.get("referenced_image_count"), int):
        problems.append("report_review.json must contain an integer field 'referenced_image_count'.")
    if not isinstance(payload.get("issue_counts"), dict):
        problems.append("report_review.json must contain an object field 'issue_counts'.")
    if not isinstance(payload.get("issues"), list):
        problems.append("report_review.json must contain a list field 'issues'.")
    priority_fixes = payload.get("priority_fixes")
    if not isinstance(priority_fixes, list) or not all(isinstance(item, str) and item.strip() for item in priority_fixes):
        problems.append("report_review.json must contain a non-empty string list field 'priority_fixes'.")
    return problems


def _suggest_report_fixes(
    *,
    report_exists: bool,
    report_chars: int,
    referenced: int,
    broken: int,
    non_relative: int,
    unrenderable: int,
    unreferenced: int,
) -> list[str]:
    fixes: list[str] = []
    if not report_exists:
        fixes.append("Write the research report to workspace/report/report.md before approval.")
    elif report_chars < MIN_REPORT_CHARS:
        fixes.append("Expand report.md with the actual methodology, quantitative results, and discussion.")
    if broken:
        fixes.append("Repair figure references that point at files missing from report/images/.")
    if non_relative:
        fixes.append("Rewrite absolute or URL figure references as paths relative to report.md, e.g. `images/plot.png`.")
    if unrenderable:
        fixes.append(f"Re-export unrenderable figures as {PREFERRED_REPORT_IMAGE_SUFFIX} files.")
    if referenced == 0 and report_exists:
        fixes.append("Generate figures into report/images/ and embed them with `![Caption](images/name.png)`.")
    if unreferenced and len(fixes) < 3:
        fixes.append("Reference or remove the images in report/images/ that the report never cites.")
    if not fixes:
        fixes.append("No structural report issues were detected; make a final evidence-vs-claim pass before approval.")
    return fixes[:3]


def validate_layout_review(path: Path) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ["layout_review.json is missing."]
    except json.JSONDecodeError as exc:
        return [f"layout_review.json is not valid JSON: {exc}"]

    problems: list[str] = []
    if not isinstance(payload, dict):
        return ["layout_review.json must contain a JSON object."]
    if not isinstance(payload.get("overall_status"), str) or not str(payload.get("overall_status")).strip():
        problems.append("layout_review.json must contain a non-empty string field 'overall_status'.")
    if not isinstance(payload.get("pdf_available"), bool):
        problems.append("layout_review.json must contain a boolean field 'pdf_available'.")
    if not isinstance(payload.get("build_log_checked"), bool):
        problems.append("layout_review.json must contain a boolean field 'build_log_checked'.")
    issue_counts = payload.get("issue_counts")
    if not isinstance(issue_counts, dict):
        problems.append("layout_review.json must contain an object field 'issue_counts'.")
    issues = payload.get("issues")
    if not isinstance(issues, list):
        problems.append("layout_review.json must contain a list field 'issues'.")
    priority_fixes = payload.get("priority_fixes")
    if not isinstance(priority_fixes, list) or not all(isinstance(item, str) and item.strip() for item in priority_fixes):
        problems.append("layout_review.json must contain a non-empty string list field 'priority_fixes'.")
    return problems


def _format_schema(schema: object) -> str:
    if not isinstance(schema, dict) or not schema:
        return ""

    pieces: list[str] = []
    kind = str(schema.get("kind") or schema.get("source") or "").strip()
    if kind:
        pieces.append(kind)
    if isinstance(schema.get("columns"), list) and schema["columns"]:
        pieces.append("columns=" + ", ".join(str(item) for item in schema["columns"][:6]))
    if isinstance(schema.get("keys"), list) and schema["keys"]:
        pieces.append("keys=" + ", ".join(str(item) for item in schema["keys"][:6]))
    if "row_count" in schema:
        pieces.append(f"rows={schema['row_count']}")
    if "item_count" in schema:
        pieces.append(f"items={schema['item_count']}")
    if "sidecar_path" in schema:
        pieces.append(f"schema={schema['sidecar_path']}")

    return ", ".join(pieces)


def _load_review_summary(paths: RunPaths, filename: str) -> dict[str, object] | None:
    path = paths.artifacts_dir / filename
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "path": str(path.relative_to(paths.run_root)),
            "overall_status": "invalid",
            "issue_counts": {},
            "priority_fixes": [],
        }
    if not isinstance(payload, dict):
        return None
    return {
        "path": str(path.relative_to(paths.run_root)),
        "overall_status": payload.get("overall_status"),
        "issue_counts": payload.get("issue_counts") if isinstance(payload.get("issue_counts"), dict) else {},
        "priority_fixes": payload.get("priority_fixes") if isinstance(payload.get("priority_fixes"), list) else [],
    }


def _find_preferred_pdf(paths: RunPaths) -> Path | None:
    preferred = _find_existing_path(
        [
            paths.artifacts_dir / "paper.pdf",
            paths.writing_dir / "main.pdf",
            paths.artifacts_dir / "paper_package" / "paper.pdf",
        ]
    )
    if preferred is not None:
        return preferred
    for directory in [paths.writing_dir, paths.artifacts_dir]:
        for candidate in sorted(directory.rglob("*.pdf")):
            if candidate.is_file():
                return candidate
    return None


def _find_existing_path(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _extract_matching_lines(text: str, pattern: str) -> list[str]:
    matcher = re.compile(pattern)
    return [line.strip() for line in text.splitlines() if matcher.search(line)]


def _estimate_pdf_page_count(path: Path | None) -> int | None:
    if path is None or not path.exists():
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    count = len(re.findall(rb"/Type\s*/Page\b", raw))
    return count or None


def _suggest_layout_fixes(
    *,
    pdf_available: bool,
    overfull_count: int,
    undefined_ref_count: int,
    undefined_citation_count: int,
    missing_file_count: int,
    underfull_count: int,
) -> list[str]:
    fixes: list[str] = []
    if not pdf_available:
        fixes.append("Compile the manuscript to a real PDF and verify the final paper artifact before approval.")
    if undefined_ref_count or undefined_citation_count:
        fixes.append("Resolve undefined references and citations, then recompile until cross-references stabilize.")
    if missing_file_count:
        fixes.append("Fix missing figure, bibliography, or LaTeX package paths referenced by the manuscript.")
    if overfull_count:
        fixes.append("Tighten overflowing paragraphs, captions, and figure/table widths to remove overfull boxes.")
    if underfull_count and len(fixes) < 3:
        fixes.append("Improve paragraph breaks or float placement where underfull box warnings remain.")
    if not fixes:
        fixes.append("No major layout issues were detected from the available build artifacts; perform a final visual pass before approval.")
    return fixes[:3]
