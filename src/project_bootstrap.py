from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .utils import RunPaths
from .utils import STAGES

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_SCAN_FILES = 500
_MAX_SCAN_DEPTH = 6
_MAX_TEXT_PER_FILE = 4000

# File classification sets
_CODE_SUFFIXES = {".py", ".ipynb", ".r", ".jl", ".sh", ".js", ".ts", ".cpp", ".c", ".h", ".java", ".go", ".rs"}
_CONFIG_SUFFIXES = {".yaml", ".yml", ".json", ".toml", ".cfg", ".ini"}
_DATA_SUFFIXES = {".csv", ".tsv", ".parquet", ".jsonl", ".npz", ".npy", ".h5", ".hdf5", ".pkl", ".pickle"}
_RESULT_SUFFIXES = {".csv", ".tsv", ".json", ".jsonl", ".npz", ".npy", ".pkl", ".log", ".txt"}
_FIGURE_SUFFIXES = {".png", ".pdf", ".svg", ".jpg", ".jpeg", ".eps"}
_TEX_SUFFIXES = {".tex", ".bib", ".bibtex", ".bbl", ".sty", ".cls"}
_CHECKPOINT_SUFFIXES = {".pt", ".pth", ".ckpt", ".safetensors", ".bin", ".h5"}
_LOG_SUFFIXES = {".log", ".txt", ".out", ".err"}

# Directories to skip
_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".tox", ".mypy_cache",
    ".pytest_cache", ".venv", "venv", "env", ".env", ".eggs",
    "dist", "build", "egg-info", ".idea", ".vscode",
}

# Heuristic directory names for each category
_CODE_DIRS = {"src", "lib", "models", "model", "modules", "core", "utils", "scripts"}
_EXPERIMENT_DIRS = {"experiments", "exp", "configs", "config", "runs", "outputs", "output", "logs", "wandb", "mlruns", "tensorboard"}
_RESULT_DIRS = {"results", "output", "outputs", "eval", "evaluation", "metrics", "benchmarks"}
_FIGURE_DIRS = {"figures", "figs", "plots", "images", "imgs", "visualizations"}
_WRITING_DIRS = {"paper", "papers", "draft", "drafts", "writing", "manuscript", "latex", "tex", "doc", "docs"}
_DATA_DIRS = {"data", "datasets", "dataset", "raw", "processed", "cache"}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FileEntry:
    """A single file found during repo scanning."""
    relative_path: str
    category: str  # "code", "config", "data", "result", "figure", "writing", "checkpoint", "log", "other"
    size_bytes: int
    suffix: str


@dataclass
class CodeState:
    """Summary of the code found in the repo."""
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    module_dirs: list[str] = field(default_factory=list)
    dependency_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    total_code_files: int = 0
    status: str = "not_started"  # "not_started", "partial", "complete"
    evidence: list[str] = field(default_factory=list)


@dataclass
class ExperimentState:
    """Summary of experiments found in the repo."""
    config_files: list[str] = field(default_factory=list)
    result_files: list[str] = field(default_factory=list)
    checkpoint_files: list[str] = field(default_factory=list)
    log_files: list[str] = field(default_factory=list)
    figure_files: list[str] = field(default_factory=list)
    total_experiments_configured: int = 0
    total_experiments_with_results: int = 0
    status: str = "not_started"
    evidence: list[str] = field(default_factory=list)


@dataclass
class WritingState:
    """Summary of writing artifacts found in the repo."""
    tex_files: list[str] = field(default_factory=list)
    bib_files: list[str] = field(default_factory=list)
    draft_pdfs: list[str] = field(default_factory=list)
    sections_found: list[str] = field(default_factory=list)
    total_tex_chars: int = 0
    has_abstract: bool = False
    has_introduction: bool = False
    has_related_work: bool = False
    has_method: bool = False
    has_experiments: bool = False
    has_conclusion: bool = False
    status: str = "not_started"
    evidence: list[str] = field(default_factory=list)


@dataclass
class StageAssessment:
    """Per-stage assessment of completion."""
    stage_number: int
    stage_name: str
    status: str  # "not_started", "partial", "complete"
    confidence: str  # "high", "medium", "low"
    evidence: list[str] = field(default_factory=list)


@dataclass
class ProjectBootstrapResult:
    """Complete result of scanning a project repo."""
    project_root: str
    scanned_at: str
    total_files: int
    code_state: CodeState
    experiment_state: ExperimentState
    writing_state: WritingState
    stage_assessments: list[StageAssessment]
    recommended_entry_stage: int  # stage number to start from
    summary: str = ""
    file_tree_sample: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Repo scanning
# ---------------------------------------------------------------------------


def scan_project(project_root: Path) -> ProjectBootstrapResult:
    """Scan a project repository and classify its contents."""
    project_root = project_root.expanduser().resolve()
    if not project_root.exists():
        raise FileNotFoundError(f"Project root not found: {project_root}")
    if not project_root.is_dir():
        raise NotADirectoryError(f"Project root is not a directory: {project_root}")

    files = _collect_files(project_root)
    file_tree_sample = _build_tree_sample(files, limit=80)

    code_state = _analyze_code(files, project_root)
    experiment_state = _analyze_experiments(files, project_root)
    writing_state = _analyze_writing(files, project_root)

    stage_assessments = _assess_stages(code_state, experiment_state, writing_state)
    entry_stage = recommend_entry_stage(stage_assessments)

    return ProjectBootstrapResult(
        project_root=str(project_root),
        scanned_at=datetime.now().isoformat(timespec="seconds"),
        total_files=len(files),
        code_state=code_state,
        experiment_state=experiment_state,
        writing_state=writing_state,
        stage_assessments=stage_assessments,
        recommended_entry_stage=entry_stage,
        file_tree_sample=file_tree_sample,
    )


def _collect_files(root: Path) -> list[FileEntry]:
    """Walk the repo and classify each file."""
    entries: list[FileEntry] = []
    count = 0

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden/build directories
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS and not d.startswith(".")
        ]

        depth = Path(dirpath).relative_to(root).parts
        if len(depth) > _MAX_SCAN_DEPTH:
            dirnames.clear()
            continue

        for fname in filenames:
            if fname.startswith("."):
                continue
            fpath = Path(dirpath) / fname
            try:
                size = fpath.stat().st_size
            except OSError:
                continue

            rel = str(fpath.relative_to(root))
            suffix = fpath.suffix.lower()
            category = _classify_file(rel, suffix)
            entries.append(FileEntry(
                relative_path=rel,
                category=category,
                size_bytes=size,
                suffix=suffix,
            ))

            count += 1
            if count >= _MAX_SCAN_FILES:
                return entries

    return entries


def _classify_file(relative_path: str, suffix: str) -> str:
    """Classify a file by its suffix and path context."""
    parts = Path(relative_path).parts
    parent_dirs = {p.lower() for p in parts[:-1]}

    # Checkpoints first (they overlap with data suffixes)
    if suffix in _CHECKPOINT_SUFFIXES:
        return "checkpoint"

    # Writing context
    if suffix in _TEX_SUFFIXES or parent_dirs & _WRITING_DIRS:
        if suffix in {".tex", ".bib", ".bibtex", ".bbl", ".sty", ".cls"}:
            return "writing"

    # Figures
    if suffix in _FIGURE_SUFFIXES and parent_dirs & _FIGURE_DIRS:
        return "figure"

    # Results (check dir context to distinguish from general data)
    if suffix in _RESULT_SUFFIXES and parent_dirs & _RESULT_DIRS:
        return "result"

    # Code
    if suffix in _CODE_SUFFIXES:
        return "code"

    # Config
    if suffix in _CONFIG_SUFFIXES:
        if parent_dirs & _EXPERIMENT_DIRS:
            return "config"
        return "config"

    # Data
    if suffix in _DATA_SUFFIXES:
        return "data"

    # Figures by suffix alone
    if suffix in _FIGURE_SUFFIXES:
        return "figure"

    # Log files
    if suffix in _LOG_SUFFIXES and parent_dirs & _EXPERIMENT_DIRS:
        return "log"

    return "other"


def _build_tree_sample(files: list[FileEntry], limit: int = 80) -> list[str]:
    """Build a directory-tree-like sample for prompt context."""
    paths = sorted(f.relative_path for f in files)
    return paths[:limit]


# ---------------------------------------------------------------------------
# Code analysis
# ---------------------------------------------------------------------------

_FRAMEWORK_PATTERNS = {
    "pytorch": re.compile(r"import torch|from torch"),
    "tensorflow": re.compile(r"import tensorflow|from tensorflow"),
    "jax": re.compile(r"import jax|from jax"),
    "sklearn": re.compile(r"from sklearn|import sklearn"),
    "huggingface": re.compile(r"from transformers|import transformers"),
    "lightning": re.compile(r"import lightning|from lightning|import pytorch_lightning"),
}

_ENTRY_POINT_NAMES = {"main.py", "train.py", "run.py", "run_experiment.py", "evaluate.py", "eval.py", "inference.py"}
_DEPENDENCY_FILES = {"requirements.txt", "setup.py", "pyproject.toml", "environment.yml", "Pipfile", "setup.cfg"}


def _analyze_code(files: list[FileEntry], root: Path) -> CodeState:
    code_files = [f for f in files if f.category == "code"]
    if not code_files:
        return CodeState(status="not_started", evidence=["No code files found"])

    state = CodeState(total_code_files=len(code_files))

    # Languages
    lang_map = {".py": "Python", ".r": "R", ".jl": "Julia", ".cpp": "C++",
                ".c": "C", ".java": "Java", ".go": "Go", ".rs": "Rust",
                ".js": "JavaScript", ".ts": "TypeScript"}
    seen_langs = set()
    for f in code_files:
        lang = lang_map.get(f.suffix)
        if lang:
            seen_langs.add(lang)
    state.languages = sorted(seen_langs)

    # Entry points
    for f in code_files:
        fname = Path(f.relative_path).name
        if fname in _ENTRY_POINT_NAMES:
            state.entry_points.append(f.relative_path)

    # Dependencies
    for f in files:
        fname = Path(f.relative_path).name
        if fname in _DEPENDENCY_FILES:
            state.dependency_files.append(f.relative_path)

    # Test files
    for f in code_files:
        name = Path(f.relative_path).name
        if name.startswith("test_") or name.endswith("_test.py") or "tests/" in f.relative_path:
            state.test_files.append(f.relative_path)

    # Module directories
    for f in code_files:
        parts = Path(f.relative_path).parts
        if len(parts) > 1:
            top_dir = parts[0].lower()
            if top_dir in _CODE_DIRS:
                if parts[0] not in state.module_dirs:
                    state.module_dirs.append(parts[0])

    # Framework detection (sample first few .py files)
    py_files = [f for f in code_files if f.suffix == ".py"]
    for f in py_files[:20]:
        try:
            text = (root / f.relative_path).read_text(encoding="utf-8", errors="replace")[:2000]
        except Exception:
            continue
        for framework, pattern in _FRAMEWORK_PATTERNS.items():
            if pattern.search(text) and framework not in state.frameworks:
                state.frameworks.append(framework)

    # Status assessment
    evidence = []
    if state.total_code_files > 0:
        evidence.append(f"{state.total_code_files} code files found")
    if state.entry_points:
        evidence.append(f"Entry points: {', '.join(state.entry_points)}")
    if state.frameworks:
        evidence.append(f"Frameworks: {', '.join(state.frameworks)}")
    if state.dependency_files:
        evidence.append(f"Dependencies declared: {', '.join(state.dependency_files)}")
    if state.test_files:
        evidence.append(f"{len(state.test_files)} test file(s)")

    state.evidence = evidence

    if state.entry_points and state.total_code_files >= 3 and state.dependency_files:
        state.status = "complete"
    elif state.total_code_files >= 2:
        state.status = "partial"
    else:
        state.status = "not_started"

    return state


# ---------------------------------------------------------------------------
# Experiment analysis
# ---------------------------------------------------------------------------


def _analyze_experiments(files: list[FileEntry], root: Path) -> ExperimentState:
    state = ExperimentState()

    for f in files:
        if f.category == "config" and _is_experiment_config(f):
            state.config_files.append(f.relative_path)
        elif f.category == "result":
            state.result_files.append(f.relative_path)
        elif f.category == "checkpoint":
            state.checkpoint_files.append(f.relative_path)
        elif f.category == "log":
            state.log_files.append(f.relative_path)
        elif f.category == "figure":
            state.figure_files.append(f.relative_path)

    state.total_experiments_configured = len(state.config_files)
    state.total_experiments_with_results = len(state.result_files)

    evidence = []
    if state.config_files:
        evidence.append(f"{len(state.config_files)} experiment config(s)")
    if state.result_files:
        evidence.append(f"{len(state.result_files)} result file(s)")
    if state.checkpoint_files:
        evidence.append(f"{len(state.checkpoint_files)} checkpoint(s)")
    if state.log_files:
        evidence.append(f"{len(state.log_files)} log file(s)")
    if state.figure_files:
        evidence.append(f"{len(state.figure_files)} figure(s)")
    if not evidence:
        evidence.append("No experiment artifacts found")

    state.evidence = evidence

    has_configs = bool(state.config_files)
    has_results = bool(state.result_files) or bool(state.checkpoint_files)
    has_figures = bool(state.figure_files)

    if has_results and has_figures:
        state.status = "complete"
    elif has_results or has_configs:
        state.status = "partial"
    else:
        state.status = "not_started"

    return state


def _is_experiment_config(f: FileEntry) -> bool:
    """Heuristic: is this config file likely an experiment config?"""
    parts = {p.lower() for p in Path(f.relative_path).parts}
    return bool(parts & _EXPERIMENT_DIRS) or any(
        kw in f.relative_path.lower()
        for kw in ("experiment", "config", "hparam", "sweep")
    )


# ---------------------------------------------------------------------------
# Writing analysis
# ---------------------------------------------------------------------------

_TEX_SECTION_RE = re.compile(r"\\section\s*\{(.+?)\}")
_TEX_ABSTRACT_RE = re.compile(r"\\begin\{abstract\}", re.IGNORECASE)

_SECTION_MAP = {
    "abstract": "has_abstract",
    "introduction": "has_introduction",
    "related work": "has_related_work",
    "background": "has_related_work",
    "method": "has_method",
    "methodology": "has_method",
    "approach": "has_method",
    "model": "has_method",
    "experiment": "has_experiments",
    "evaluation": "has_experiments",
    "result": "has_experiments",
    "conclusion": "has_conclusion",
    "discussion": "has_conclusion",
}


def _analyze_writing(files: list[FileEntry], root: Path) -> WritingState:
    state = WritingState()

    for f in files:
        if f.category != "writing":
            continue
        if f.suffix in {".tex"}:
            state.tex_files.append(f.relative_path)
        elif f.suffix in {".bib", ".bibtex"}:
            state.bib_files.append(f.relative_path)

    # Check for draft PDFs in writing directories
    for f in files:
        if f.suffix == ".pdf":
            parts = {p.lower() for p in Path(f.relative_path).parts}
            if parts & _WRITING_DIRS or "draft" in f.relative_path.lower():
                state.draft_pdfs.append(f.relative_path)

    # Analyze .tex content
    for tex_path in state.tex_files:
        try:
            text = (root / tex_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        state.total_tex_chars += len(text)

        if _TEX_ABSTRACT_RE.search(text):
            state.has_abstract = True

        for match in _TEX_SECTION_RE.finditer(text):
            section_name = match.group(1).strip()
            state.sections_found.append(section_name)
            section_lower = section_name.lower()
            for keyword, attr in _SECTION_MAP.items():
                if keyword in section_lower:
                    setattr(state, attr, True)

    evidence = []
    if state.tex_files:
        evidence.append(f"{len(state.tex_files)} .tex file(s), {state.total_tex_chars} chars total")
    if state.bib_files:
        evidence.append(f"{len(state.bib_files)} .bib file(s)")
    if state.draft_pdfs:
        evidence.append(f"{len(state.draft_pdfs)} draft PDF(s)")
    if state.sections_found:
        evidence.append(f"Sections: {', '.join(state.sections_found)}")
    section_flags = []
    for attr_name in ["has_abstract", "has_introduction", "has_related_work",
                       "has_method", "has_experiments", "has_conclusion"]:
        if getattr(state, attr_name):
            section_flags.append(attr_name.replace("has_", ""))
    if section_flags:
        evidence.append(f"Sections with content: {', '.join(section_flags)}")
    if not evidence:
        evidence.append("No writing artifacts found")

    state.evidence = evidence

    if state.tex_files and state.total_tex_chars > 5000 and state.has_abstract and state.has_conclusion:
        state.status = "complete"
    elif state.tex_files and state.total_tex_chars > 1000:
        state.status = "partial"
    elif state.tex_files:
        state.status = "partial"
    else:
        state.status = "not_started"

    return state


# ---------------------------------------------------------------------------
# Stage assessment
# ---------------------------------------------------------------------------


def _assess_stages(
    code: CodeState,
    experiments: ExperimentState,
    writing: WritingState,
) -> list[StageAssessment]:
    """Map code/experiment/writing state to per-stage assessments."""
    assessments = []

    # Stage 01: Literature Survey — check for .bib files with substantial references
    has_bib = bool(writing.bib_files)
    has_related_work = writing.has_related_work
    if has_bib and has_related_work:
        s01 = StageAssessment(1, "Literature Survey", "complete", "medium",
                              [f"Has .bib files: {', '.join(writing.bib_files)}",
                               "Related work section found in .tex"])
    elif has_bib:
        s01 = StageAssessment(1, "Literature Survey", "partial", "low",
                              [f"Has .bib files but no related work section in .tex"])
    else:
        s01 = StageAssessment(1, "Literature Survey", "not_started", "low",
                              ["No .bib files or literature review found"])
    assessments.append(s01)

    # Stage 02: Hypothesis Generation — hard to infer, mark based on downstream evidence
    if code.status in ("partial", "complete"):
        s02 = StageAssessment(2, "Hypothesis Generation", "complete", "low",
                              ["Inferred from downstream implementation work"])
    else:
        s02 = StageAssessment(2, "Hypothesis Generation", "not_started", "low",
                              ["Cannot reliably infer hypothesis stage from repo artifacts"])
    assessments.append(s02)

    # Stage 03: Study Design — check for experiment configs
    if experiments.config_files:
        s03 = StageAssessment(3, "Study Design", "complete", "medium",
                              [f"{len(experiments.config_files)} experiment config(s) found"] + experiments.config_files[:5])
    elif code.status in ("partial", "complete"):
        s03 = StageAssessment(3, "Study Design", "partial", "low",
                              ["Code exists but no explicit experiment configs"])
    else:
        s03 = StageAssessment(3, "Study Design", "not_started", "medium",
                              ["No experiment configurations found"])
    assessments.append(s03)

    # Stage 04: Implementation
    s04 = StageAssessment(4, "Implementation", code.status,
                          "high" if code.total_code_files > 10 else "medium",
                          code.evidence)
    assessments.append(s04)

    # Stage 05: Experimentation
    if experiments.result_files or experiments.checkpoint_files or experiments.log_files:
        status = "complete" if experiments.result_files else "partial"
        conf = "high" if experiments.result_files else "medium"
        s05 = StageAssessment(5, "Experimentation", status, conf, experiments.evidence)
    elif experiments.config_files:
        s05 = StageAssessment(5, "Experimentation", "partial", "low",
                              ["Configs exist but no results/logs found"])
    else:
        s05 = StageAssessment(5, "Experimentation", "not_started", "medium",
                              ["No experiment artifacts found"])
    assessments.append(s05)

    # Stage 06: Analysis
    has_analysis_figures = bool(experiments.figure_files)
    has_results = bool(experiments.result_files)
    if has_analysis_figures and has_results:
        s06 = StageAssessment(6, "Analysis", "complete", "medium",
                              [f"{len(experiments.figure_files)} figures",
                               f"{len(experiments.result_files)} result files"])
    elif has_analysis_figures or has_results:
        s06 = StageAssessment(6, "Analysis", "partial", "low",
                              experiments.evidence)
    else:
        s06 = StageAssessment(6, "Analysis", "not_started", "medium",
                              ["No analysis artifacts found"])
    assessments.append(s06)

    # Stage 07: Writing
    s07 = StageAssessment(7, "Writing", writing.status,
                          "high" if writing.total_tex_chars > 10000 else "medium",
                          writing.evidence)
    assessments.append(s07)

    # Stage 08: Dissemination
    if writing.draft_pdfs and writing.status == "complete":
        s08 = StageAssessment(8, "Dissemination", "partial", "low",
                              ["Draft PDF exists; submission status unknown"])
    else:
        s08 = StageAssessment(8, "Dissemination", "not_started", "medium",
                              ["No dissemination artifacts found"])
    assessments.append(s08)

    return assessments


def recommend_entry_stage(assessments: list[StageAssessment]) -> int:
    """Pick a practical re-entry stage from bootstrap assessments.

    Later complete work should usually let the run re-enter downstream, but a
    high-confidence earlier gap still pulls the entry point back to that stage.
    This preserves useful midstream handoff while respecting explicit evidence
    that a prerequisite stage still needs real work.
    """
    if not assessments:
        return 1

    last_complete = 0
    for assessment in assessments:
        if assessment.status == "complete":
            last_complete = assessment.stage_number

    for assessment in assessments:
        if assessment.stage_number >= last_complete:
            break
        if assessment.status != "complete" and assessment.confidence == "high":
            return assessment.stage_number

    for assessment in assessments:
        if assessment.stage_number <= last_complete:
            continue
        if assessment.status != "complete":
            return assessment.stage_number

    return assessments[-1].stage_number


# ---------------------------------------------------------------------------
# Save / load artifacts
# ---------------------------------------------------------------------------


def save_project_bootstrap(paths: RunPaths, result: ProjectBootstrapResult) -> None:
    """Write all bootstrap artifacts to workspace/bootstrap/."""
    bdir = paths.bootstrap_dir
    bdir.mkdir(parents=True, exist_ok=True)

    _write_json(bdir / "project_state.json", asdict(result.code_state))
    _write_json(bdir / "experiment_inventory.json", asdict(result.experiment_state))
    _write_json(bdir / "writing_state.json", asdict(result.writing_state))
    _write_json(bdir / "stage_assessments.json", [asdict(a) for a in result.stage_assessments])
    _write_json(bdir / "scan_metadata.json", {
        "project_root": result.project_root,
        "scanned_at": result.scanned_at,
        "total_files": result.total_files,
        "recommended_entry_stage": result.recommended_entry_stage,
    })

    summary_text = result.summary or _generate_summary_text(result)
    (bdir / "bootstrap_summary.md").write_text(summary_text.rstrip() + "\n", encoding="utf-8")


def load_project_bootstrap_summary(paths: RunPaths) -> str | None:
    summary_path = paths.bootstrap_dir / "bootstrap_summary.md"
    if not summary_path.exists():
        return None
    return summary_path.read_text(encoding="utf-8").strip()


def load_stage_assessments(paths: RunPaths) -> list[StageAssessment] | None:
    sa_path = paths.bootstrap_dir / "stage_assessments.json"
    if not sa_path.exists():
        return None
    try:
        data = json.loads(sa_path.read_text(encoding="utf-8"))
        return [StageAssessment(**a) for a in data]
    except (json.JSONDecodeError, TypeError):
        return None


def load_recommended_entry_stage(paths: RunPaths) -> int | None:
    meta_path = paths.bootstrap_dir / "scan_metadata.json"
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        value = data.get("recommended_entry_stage")
        if isinstance(value, int) and any(stage.number == value for stage in STAGES):
            return value
        return None
    except (json.JSONDecodeError, TypeError):
        return None


def save_recommended_entry_stage(paths: RunPaths, entry_stage: int) -> None:
    meta_path = paths.bootstrap_dir / "scan_metadata.json"
    payload: dict[str, object] = {}
    if meta_path.exists():
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, TypeError):
            payload = {}
    payload["recommended_entry_stage"] = entry_stage
    _write_json(meta_path, payload)


def project_bootstrap_exists(paths: RunPaths) -> bool:
    return (paths.bootstrap_dir / "bootstrap_summary.md").exists()


# ---------------------------------------------------------------------------
# Prompt formatting
# ---------------------------------------------------------------------------


def format_project_scan_for_prompt(result: ProjectBootstrapResult) -> str:
    """Format the scan results for Claude's bootstrap analysis prompt."""
    parts: list[str] = []

    # File tree sample
    parts.append("## Repository File Tree (sample)")
    parts.append("```")
    parts.extend(result.file_tree_sample)
    parts.append("```")

    # Code state
    parts.append("\n## Code Analysis")
    for e in result.code_state.evidence:
        parts.append(f"- {e}")

    # Experiment state
    parts.append("\n## Experiment Analysis")
    for e in result.experiment_state.evidence:
        parts.append(f"- {e}")

    # Writing state
    parts.append("\n## Writing Analysis")
    for e in result.writing_state.evidence:
        parts.append(f"- {e}")

    # Stage assessments (heuristic, for Claude to review)
    parts.append("\n## Heuristic Stage Assessments (for your review)")
    parts.append("These are automated heuristic assessments. Review them against the actual repo content and adjust.")
    for a in result.stage_assessments:
        parts.append(f"\n### Stage {a.stage_number:02d}: {a.stage_name}")
        parts.append(f"- **Status:** {a.status} (confidence: {a.confidence})")
        for e in a.evidence:
            parts.append(f"- {e}")

    parts.append(f"\n**Heuristic recommended entry stage:** Stage {result.recommended_entry_stage:02d}")

    return "\n".join(parts)


#: Written after each assessment line, saying what this run did with that reading
#: rather than restating the reading. ``_adopt_project_bootstrap_baseline`` accepts
#: every stage below the recommended entry stage as already done and writes it an
#: approved stage summary; the entry stage and everything after it are the run's
#: own work. The distinction cannot be in ``bootstrap_summary.md``: that file is
#: written by ``save_project_bootstrap`` before the operator's turn, and the entry
#: stage is decided and stored by ``save_recommended_entry_stage`` after it. Nor is
#: it in any one place in ``memory.md``. This mark is where it is written down.
CARRIED_FORWARD_MARK = "carried forward: this run accepted it and did not redo it"
STILL_OWED_MARK = "still owed: this run has to do this stage itself"


def format_project_context_for_prompt(paths: RunPaths) -> str | None:
    """Format the project bootstrap context for injection into stage prompts.

    Delivered by the ``project_context`` channel in ``src.information_flow``.

    **Every assessment is listed, and the overlap with approved memory is real.**
    An earlier version of this function dropped the assessments below the
    recommended entry stage, on the argument that
    ``_adopt_project_bootstrap_baseline`` had already written each of them into
    ``memory.md`` as an approved stage summary, so listing them here would send
    the same reading twice. The measurement that retired that argument is that
    memory's copy is not durable: ``append_approved_stage_summary`` keeps only
    the entries numbered below the stage being written, so any approval at a
    stage below the re-entry point erases the carry-forward entries above it.
    Take ``07_writing → 01_literature_survey`` (a ``guard="always"`` revisit
    edge) on a run that re-entered at Stage 07: approving that Stage 01 leaves
    memory holding Stage 01 alone, and the readings for Stages 02-06 exist
    nowhere but here. A block that had narrowed them away would have deleted the
    last copy of what the run was told about the repository it is working in.
    ``test_an_approval_below_the_entry_stage_erases_memorys_copy`` runs that path.

    **The summary section above the list is not a second copy to fall back on.**
    ``save_project_bootstrap`` writes ``bootstrap_summary.md`` once, from
    ``result.summary or _generate_summary_text(result)``, before the bootstrap
    operator's turn; ``src/prompts/project_bootstrap.md`` then instructs the agent
    to write ``{{WORKSPACE_BOOTSTRAP_DIR}}/bootstrap_summary.md`` as prose, and
    that placeholder resolves to ``paths.bootstrap_dir`` — the same path
    ``load_project_bootstrap_summary`` reads, in the directory the operator runs
    against. So the section this function puts above the list is agent-owned from
    the first approved bootstrap onward and may contain no per-stage line at all.
    That is not an argument against the list; it is the reason the list has to be
    complete, because it is the only part of this block whose per-stage coverage
    is decided by code. ``test_the_summary_above_the_list_is_agent_owned``
    measures it by overwriting the file the template names.

    What the list adds over the summary above it is therefore ``CARRIED_FORWARD_MARK``
    versus ``STILL_OWED_MARK`` — which stages this run accepted from the scan and
    which it still owes — plus, whenever the agent has rewritten the summary, the
    per-stage readings themselves. With no entry stage recorded nothing was carried
    forward, so every stage is marked owed.
    """
    if not project_bootstrap_exists(paths):
        return None

    parts: list[str] = []

    summary = load_project_bootstrap_summary(paths)
    if summary:
        parts.append(f"## Project Bootstrap Summary\n\n{summary}")

    entry_stage = load_recommended_entry_stage(paths)
    assessments = load_stage_assessments(paths) or []
    if assessments:
        lines = ["## Project Stage Assessments"]
        for a in assessments:
            carried = entry_stage is not None and a.stage_number < entry_stage
            mark = CARRIED_FORWARD_MARK if carried else STILL_OWED_MARK
            lines.append(f"- **Stage {a.stage_number:02d} ({a.stage_name}):** "
                        f"{a.status} (confidence: {a.confidence}) — {mark}")
        parts.append("\n".join(lines))

    return "\n\n".join(parts) if parts else None


def format_scan_stats_for_log(result: ProjectBootstrapResult) -> str:
    """Format scan results for log entries."""
    lines = [
        f"Project root: {result.project_root}",
        f"Scanned at: {result.scanned_at}",
        f"Total files: {result.total_files}",
        f"Code: {result.code_state.status} ({result.code_state.total_code_files} files)",
        f"Experiments: {result.experiment_state.status}",
        f"Writing: {result.writing_state.status}",
        f"Recommended entry stage: {result.recommended_entry_stage}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_summary_text(result: ProjectBootstrapResult) -> str:
    """Generate a default summary from scan results (used if Claude hasn't written one yet)."""
    lines = [
        "# Project Bootstrap Summary",
        "",
        f"**Scanned:** {result.project_root}",
        f"**Total files:** {result.total_files}",
        "",
        "## Stage Status",
        "",
    ]
    for a in result.stage_assessments:
        icon = {"complete": "[x]", "partial": "[-]", "not_started": "[ ]"}.get(a.status, "[ ]")
        lines.append(f"- {icon} Stage {a.stage_number:02d}: {a.stage_name} — {a.status} ({a.confidence} confidence)")
        for e in a.evidence:
            lines.append(f"  - {e}")
    lines.extend([
        "",
        f"**Recommended entry point:** Stage {result.recommended_entry_stage:02d}",
    ])
    return "\n".join(lines)


def _write_json(path: Path, data: dict | list) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
