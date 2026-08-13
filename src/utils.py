from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_REGISTRY_PATH = REPO_ROOT / "templates" / "registry.yaml"

#: What `code_version()` reports when it cannot tell. Never an empty string: a field that is
#: sometimes absent and sometimes blank is one a reader has to guess about.
UNKNOWN_CODE_VERSION = "unknown"

_code_version_cache: str | None = None


def code_version() -> str:
    """The commit this run's code came from, with ``+dirty`` when the tree is modified.

    A run could not say what produced it. ``run_manifest.json`` has the run id, timestamps,
    status and stages; ``_meta.json`` has the model and the duration; neither has a version
    of any kind. That is fine until the checkout moves, and on a shared clone it moves
    constantly: during one 12-run benchmark batch this repository advanced twelve commits
    under the running processes, so the first six runs and the last six did not use the same
    code and nothing on disk recorded which was which. The provenance had to be reconstructed
    by hand from shell history, which is not evidence.

    ``+dirty`` matters as much as the sha. A run from a modified tree is not reproducible
    from its commit, and a bare sha would claim it is.

    Best-effort by construction: a tarball with no ``.git``, a missing git binary and a
    non-repository all report :data:`UNKNOWN_CODE_VERSION` rather than failing a run over
    metadata. Cached because it cannot change within a process and every run start would
    otherwise pay for two subprocesses.
    """
    global _code_version_cache
    if _code_version_cache is not None:
        return _code_version_cache

    import subprocess

    def _git(*args: str) -> str | None:
        try:
            done = subprocess.run(
                ["git", "-C", str(REPO_ROOT), *args],
                capture_output=True, text=True, timeout=10, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    sha = _git("rev-parse", "HEAD")
    if not sha:
        _code_version_cache = UNKNOWN_CODE_VERSION
        return _code_version_cache

    # `--porcelain` is empty exactly when the tree matches the commit. A failure to *ask*
    # is not a clean tree, so it is reported as unknown rather than assumed either way.
    status = _git("status", "--porcelain")
    suffix = "" if status == "" else ("+dirty" if status else "+unknown")
    _code_version_cache = sha[:12] + suffix
    return _code_version_cache
DEFAULT_VENUE = "neurips_2025"
#: Attempts a stage may take before AutoR gives up on it. **None means no limit, and
#: None is the default.**
#:
#: It used to be 5, and the ceiling was doing harm rather than good. Exhausting it does not
#: stop the run: it auto-skips the stage and carries on, so the budget's real effect was to
#: convert "this stage is taking a while" into "this stage did not happen" -- silently, in
#: an artifact that still looks like a finished run. A ResearchClawBench run watched live
#: skipped its literature survey and its hypothesis generation that way and went on to write
#: a report standing on neither, and the cause was not the research: the reviewing backend
#: was emitting its verdict after a tool transcript AutoR could not yet parse (#176), so
#: every attempt was refused by the parser and the stage ran out of tries it never needed.
#:
#: A skipped stage is the expensive failure. Waiting is not. An integer still caps, for a
#: caller who wants a bound.
#:
#: The sentinel is ``None`` rather than ``0`` because ``0`` was already a value with a
#: meaning -- "allow no attempts, fail at once", which is how a test forces the skip path.
#: Overloading it would have made that test hang forever instead of failing, and a lever
#: that silently becomes its own opposite is worse than a slightly longer type.
MAX_STAGE_ATTEMPTS: int | None = None


#: Consecutive attempts that may fail *in exactly the same way* before a stage is
#: declared stuck. Removing the attempt ceiling removes the only thing that used to stop
#: a stage that cannot pass, and an unbounded retry of a stage whose fixture can never
#: satisfy its own gate is a run that never ends -- a worse outcome than the skip the
#: ceiling was removed to prevent, because it produces nothing at all rather than
#: something with a hole in it.
#:
#: The stop is *no progress*, not *no patience*. A stage that fails differently each time
#: is working through its problems and gets as many attempts as it needs; a stage whose
#: validation errors are byte-identical three times running has shown that another
#: attempt cannot help. That distinction is the whole reason the count is on repeats
#: rather than on tries.
STUCK_AFTER_IDENTICAL_FAILURES = 3


def is_stuck(recent_failures: Sequence[Sequence[str]]) -> bool:
    """Whether the last :data:`STUCK_AFTER_IDENTICAL_FAILURES` attempts failed identically.

    Order within one attempt's errors is not meaningful -- validators run in whatever
    order they are registered -- so the comparison is over the sorted set. Two attempts
    that surfaced the same problems in a different order made the same amount of
    progress, which is none.
    """
    if len(recent_failures) < STUCK_AFTER_IDENTICAL_FAILURES:
        return False
    window = recent_failures[-STUCK_AFTER_IDENTICAL_FAILURES:]
    signatures = {tuple(sorted(str(item) for item in errors)) for errors in window}
    if len(signatures) != 1:
        return False
    # An attempt that recorded no errors at all did not fail in a way we can compare.
    # Treating an empty signature as a repeat would stop a stage that is failing for a
    # reason no validator named, which is the case most in need of another attempt.
    return bool(next(iter(signatures)))


def attempts_exhausted(attempt_no: int, ceiling: int | None) -> bool:
    """Whether *attempt_no* has run past *ceiling*, with ``None`` meaning no ceiling.

    A predicate rather than four copies of the comparison: the call sites are the places
    a stage can be sent back from, they do not all compare the same way, and one added
    later should not have to remember that None is special.
    """
    return ceiling is not None and attempt_no > ceiling
DEFAULT_CODEX_SANDBOX = "workspace-write"
CODEX_SANDBOX_CHOICES = {"read-only", "workspace-write", "danger-full-access"}

#: Final deliverable produced by Stage 07.
#:
#: ``markdown`` writes ``workspace/report/report.md`` plus ``workspace/report/images/*.png``,
#: which is the artifact automated research benchmarks read (ResearchClawBench scores exactly
#: ``<workspace>/report/report.md``). ``latex`` keeps the original submission-oriented paper
#: package: ``main.tex``, ``sections/*.tex``, a bibliography, and a compiled PDF.
DEFAULT_OUTPUT_FORMAT = "markdown"
OUTPUT_FORMAT_CHOICES = ("markdown", "latex")
#: What the CLIs advertise. A subset of the alias table below, short enough for ``--help``;
#: `test_every_cli_choice_resolves` is what keeps the two from drifting apart.
OUTPUT_FORMAT_CLI_CHOICES = ("markdown", "md", "latex", "tex")
_OUTPUT_FORMAT_ALIASES = {
    "markdown": "markdown",
    "md": "markdown",
    "report": "markdown",
    "latex": "latex",
    "tex": "latex",
    "pdf": "latex",
    "paper": "latex",
}


@dataclass(frozen=True)
class StageSpec:
    number: int
    slug: str
    display_name: str

    @property
    def filename(self) -> str:
        return f"{self.slug}.md"

    @property
    def stage_title(self) -> str:
        return f"Stage {self.number:02d}: {self.display_name}"


@dataclass(frozen=True)
class RunPaths:
    run_root: Path
    user_input: Path
    memory: Path
    run_config: Path
    run_manifest: Path
    artifact_index: Path
    logs: Path
    logs_raw: Path
    prompt_cache_dir: Path
    operator_state_dir: Path
    stages_dir: Path
    handoff_dir: Path
    workspace_root: Path
    literature_dir: Path
    code_dir: Path
    data_dir: Path
    results_dir: Path
    experiment_manifest: Path
    hypothesis_manifest: Path
    preregistration: Path
    experimental_protocol: Path
    #: Which figures the report will carry and which claim each one settles,
    #: declared at Stage 03. Under ``notes/`` rather than ``data/`` on purpose:
    #: ``.json`` is a machine-data suffix, so a plan under ``data/`` would
    #: satisfy the Stage 03 data gate, which exists to prove work happened.
    report_plan: Path
    research_rounds: Path
    round_decision: Path
    hypothesis_outcomes: Path
    claim_provenance: Path
    writing_dir: Path
    report_dir: Path
    report_file: Path
    report_images_dir: Path
    figures_dir: Path
    artifacts_dir: Path
    notes_dir: Path
    reviews_dir: Path
    bootstrap_dir: Path
    profile_dir: Path
    intake_context: Path
    #: Every candidate draft, its measured score, the champion, the Pareto frontier
    #: and the improvement ledger. Outside ``workspace/`` on purpose: it is a record
    #: of how the run reached its answer, not part of the answer, and a benchmark
    #: export that swept it up would ship the losing drafts alongside the report.
    evolution_dir: Path
    #: Where the operator's agent CLI looks for project skills. The operator is
    #: invoked with ``cwd=run_root``, so this is the run's own ``.claude/skills``
    #: and not the AutoR checkout's.
    skills_dir: Path

    def stage_file(self, stage: StageSpec) -> Path:
        return self.stages_dir / stage.filename

    def stage_tmp_file(self, stage: StageSpec) -> Path:
        return self.stages_dir / f"{stage.slug}.tmp.md"

    def stage_session_file(self, stage: StageSpec) -> Path:
        return self.operator_state_dir / f"{stage.slug}.session_id.txt"

    def stage_session_state_file(self, stage: StageSpec) -> Path:
        return self.operator_state_dir / f"{stage.slug}.session.json"

    def stage_attempt_state_file(self, stage: StageSpec, attempt_no: int) -> Path:
        return self.operator_state_dir / f"{stage.slug}.attempt_{attempt_no:02d}.json"

    def stage_execution_marker_file(self, stage: StageSpec) -> Path:
        return self.operator_state_dir / f"{stage.slug}.started_at.txt"


@dataclass(frozen=True)
class OperatorResult:
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    stage_file_path: Path
    session_id: str | None = None


INTAKE_STAGE = StageSpec(0, "00_intake", "Research Intake")

STAGES: list[StageSpec] = [
    StageSpec(1, "01_literature_survey", "Literature Survey"),
    StageSpec(2, "02_hypothesis_generation", "Hypothesis Generation"),
    StageSpec(3, "03_study_design", "Study Design"),
    StageSpec(4, "04_implementation", "Implementation"),
    StageSpec(5, "05_experimentation", "Experimentation"),
    StageSpec(6, "06_analysis", "Analysis"),
    StageSpec(7, "07_writing", "Writing"),
    StageSpec(8, "08_dissemination", "Dissemination"),
]

#: The node that produces the deliverable. Stage 08 comes after it and makes posters and
#: release notes, so it is where a run *ends*, not where its output is written — the
#: distinction matters to anything deciding where to route a run that is out of budget.
WRITING_STAGE = STAGES[6]

REQUIRED_STAGE_HEADINGS = [
    "Objective",
    "What I Did",
    "Key Results",
    "Files Produced",
    "Decision Ledger",
    "Suggestions for Refinement",
    "Your Options",
]

FIXED_STAGE_OPTIONS = [
    "1. Use suggestion 1",
    "2. Use suggestion 2",
    "3. Use suggestion 3",
    "4. Refine with your own feedback",
    "5. Approve and continue",
    "6. Abort",
]

APPROVED_STAGE_ENTRY_PATTERN = re.compile(r"^#{1,6}\s*Stage\s+(\d{2}):.*$", flags=re.MULTILINE)

DEFAULT_REFINEMENT_SUGGESTIONS = [
    "Tighten the scope or decision criteria for this stage before continuing.",
    "Strengthen the evidence quality, artifacts, or justification produced in this stage.",
    "Clarify the main risks, assumptions, and next-step implications before continuing.",
]

PLACEHOLDER_PATTERNS = [
    r"\[in progress[^\]]*\]",
    r"\[pending[^\]]*\]",
    r"\[todo[^\]]*\]",
    r"\[to be determined[^\]]*\]",
    r"\[placeholder[^\]]*\]",
    r"\[to be populated[^\]]*\]",
]

MACHINE_DATA_SUFFIXES = {".json", ".jsonl", ".csv", ".tsv", ".parquet", ".yaml", ".yml"}
RESULT_SUFFIXES = {".json", ".jsonl", ".csv", ".tsv", ".parquet", ".npz", ".npy"}
FIGURE_SUFFIXES = {".png", ".pdf", ".svg", ".jpg", ".jpeg"}
LATEX_SUFFIXES = {".tex"}
PDF_SUFFIXES = {".pdf"}
BIB_SUFFIXES = {".bib"}

#: Image formats a benchmark judge can actually render. ``.pdf``, ``.eps``, ``.tiff`` and
#: friends are deliberately absent: a report that links one shows the judge nothing.
RENDERABLE_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
#: The format the benchmark asks for. Anything else renderable is accepted but flagged.
PREFERRED_REPORT_IMAGE_SUFFIX = ".png"
#: Below this many characters ``report.md`` is a stub, not a deliverable.
MIN_REPORT_CHARS = 1200

#: How many figures may reach the judge.
#:
#: ResearchClawBench's scorer collects one set of agent images per *workspace*, by an
#: unsorted ``rglob`` over ``outputs/`` and then ``report/``, and attaches the first five of
#: that same set to every image checklist item (``generated_images[:5]``) — not five chosen
#: per item. Filesystem order is not alphabetical, so naming cannot influence which five
#: survive; the only way to choose them is to publish no more than five. Image items carry
#: ~61% of the benchmark's total weight, so a sixth figure does not dilute the score, it
#: randomises it.
MAX_REPORT_FIGURES = 5

#: Distinct figures a markdown report must carry. One is the floor for an ordinary research
#: run, where how much the question needs illustrating is the researcher's call.
#:
#: A benchmark run raises it. ResearchClawBench's own instructions ask every agent for "data
#: overview, main results, and validation/comparison plots" — three categories — and 27 of its
#: 40 shipped tasks carry two or more image criteria, which together hold about 61% of the
#: total weight. A single-figure report clears the old gate while structurally forfeiting most
#: of that: one image cannot answer two different questions. The floor is a *count of distinct
#: figures*, never a target to pad toward, and is capped by MAX_REPORT_FIGURES because a sixth
#: figure is not shown to the judge at all.
MIN_REPORT_FIGURES = 1
BENCHMARK_MIN_REPORT_FIGURES = 3

#: ``![alt](target)``, tolerating an optional title and angle-bracketed targets.
MARKDOWN_IMAGE_PATTERN = re.compile(
    r"!\[[^\]]*\]\(\s*(<[^>]*>|[^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\s*\)"
)
#: ``<img src="target">`` for reports that fall back to raw HTML.
HTML_IMAGE_PATTERN = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']", flags=re.IGNORECASE)

TYPED_HYPOTHESIS_HEADINGS = [
    "Theoretical Propositions",
    "Empirical Hypotheses",
    "Paper Claims (Provisional)",
]


def create_run_root(runs_dir: Path) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    base = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = runs_dir / base
    counter = 1

    while candidate.exists():
        candidate = runs_dir / f"{base}_{counter:02d}"
        counter += 1

    return candidate


def build_run_paths(run_root: Path) -> RunPaths:
    workspace_root = run_root / "workspace"
    return RunPaths(
        run_root=run_root,
        user_input=run_root / "user_input.txt",
        memory=run_root / "memory.md",
        run_config=run_root / "run_config.json",
        run_manifest=run_root / "run_manifest.json",
        artifact_index=run_root / "artifact_index.json",
        logs=run_root / "logs.txt",
        logs_raw=run_root / "logs_raw.jsonl",
        skills_dir=run_root / ".claude" / "skills",
        prompt_cache_dir=run_root / "prompt_cache",
        operator_state_dir=run_root / "operator_state",
        stages_dir=run_root / "stages",
        handoff_dir=run_root / "handoff",
        workspace_root=workspace_root,
        literature_dir=workspace_root / "literature",
        code_dir=workspace_root / "code",
        data_dir=workspace_root / "data",
        results_dir=workspace_root / "results",
        experiment_manifest=workspace_root / "results" / "experiment_manifest.json",
        hypothesis_manifest=workspace_root / "notes" / "hypothesis_manifest.json",
        preregistration=workspace_root / "notes" / "preregistration.json",
        experimental_protocol=workspace_root / "notes" / "experimental_protocol.json",
        report_plan=workspace_root / "notes" / "report_plan.json",
        research_rounds=workspace_root / "notes" / "research_rounds.json",
        round_decision=workspace_root / "notes" / "round_decision.json",
        hypothesis_outcomes=workspace_root / "results" / "hypothesis_outcomes.json",
        claim_provenance=workspace_root / "artifacts" / "claim_provenance.json",
        writing_dir=workspace_root / "writing",
        report_dir=workspace_root / "report",
        report_file=workspace_root / "report" / "report.md",
        report_images_dir=workspace_root / "report" / "images",
        figures_dir=workspace_root / "figures",
        artifacts_dir=workspace_root / "artifacts",
        notes_dir=workspace_root / "notes",
        reviews_dir=workspace_root / "reviews",
        bootstrap_dir=workspace_root / "bootstrap",
        profile_dir=workspace_root / "profile",
        intake_context=run_root / "intake_context.json",
        evolution_dir=run_root / "evolution",
    )


def ensure_run_layout(paths: RunPaths) -> None:
    paths.run_root.mkdir(parents=True, exist_ok=True)
    paths.prompt_cache_dir.mkdir(parents=True, exist_ok=True)
    paths.skills_dir.mkdir(parents=True, exist_ok=True)
    paths.operator_state_dir.mkdir(parents=True, exist_ok=True)
    paths.stages_dir.mkdir(parents=True, exist_ok=True)
    paths.handoff_dir.mkdir(parents=True, exist_ok=True)
    paths.workspace_root.mkdir(parents=True, exist_ok=True)

    for directory in workspace_dirs(paths):
        directory.mkdir(parents=True, exist_ok=True)

    for file_path in (paths.user_input, paths.memory, paths.logs, paths.logs_raw):
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch(exist_ok=True)


def workspace_dirs(paths: RunPaths) -> list[Path]:
    return [
        paths.literature_dir,
        paths.code_dir,
        paths.data_dir,
        paths.results_dir,
        paths.writing_dir,
        paths.report_dir,
        paths.report_images_dir,
        paths.figures_dir,
        paths.artifacts_dir,
        paths.notes_dir,
        paths.reviews_dir,
        paths.bootstrap_dir,
        paths.profile_dir,
    ]


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def append_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def append_log_entry(log_path: Path, heading: str, body: str) -> None:
    timestamp = datetime.now().isoformat(timespec="seconds")
    entry = f"\n=== {timestamp} | {heading} ===\n{body.rstrip()}\n"
    append_text(log_path, entry)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    append_text(path, json.dumps(payload, ensure_ascii=True) + "\n")


def initialize_memory(paths: RunPaths, user_goal: str, intake_summary: str | None = None) -> None:
    write_text(paths.memory, build_memory_text(user_goal, [], intake_summary=intake_summary))


def normalize_codex_sandbox(value: Any) -> str:
    if isinstance(value, str):
        normalized = value.strip()
        if normalized in CODEX_SANDBOX_CHOICES:
            return normalized
    return DEFAULT_CODEX_SANDBOX


#: How the run moves between stages. ``linear`` is the historical sequence, one
#: edge out of each node. ``adaptive`` adds the backward moves and lets the run
#: return to an earlier stage when a later one shows it has to.
#:
#: Adaptive is the default because the failure it prevents is the expensive one: a
#: run that reaches Stage 06, discovers the design cannot answer the question, and
#: writes it up anyway because there was nowhere else to go. `--stage-graph linear`
#: restores the strict sequence.
DEFAULT_STAGE_GRAPH = "adaptive"
STAGE_GRAPH_CHOICES = ("linear", "adaptive")

#: Who picks the edge. ``off`` always takes the graph's default, which on a linear
#: topology is the only one. ``auto`` asks the backend wherever more than one move
#: is live; ``agent`` asks at every node.
#:
#: ``auto`` is the default: it asks only where the answer can differ, so a linear
#: run never pays for it, and an adaptive run pays a short prompt at the handful of
#: nodes with a real choice. The stage that just ran is the only party that knows
#: whether its results decided anything, and not asking it throws that away.
DEFAULT_ROUTING_MODE = "auto"
ROUTING_MODE_CHOICES = ("off", "auto", "agent")

#: Polish rounds per stage. See :class:`src.evolution.EvolutionConfig` — this is the
#: half that costs backend calls, and it is bounded further by a headroom check, so
#: a stage the rubric has nothing to say about spends none of it.
DEFAULT_EVOLVE_ROUNDS = 2

#: Whether every valid draft is scored and the champion ratchet runs. Free: the
#: rubric reads the run off disk and never calls a backend. Persisted alongside the
#: rounds budget so a resumed run keeps the arrangement it started under.
DEFAULT_EVOLVE_MEASURE = True

#: Whether the cross-run archive is allowed to change the topology a run uses, as
#: opposed to merely recording what the run did.
#:
#: Off by default, and the split is the point. Recording is free and builds the only
#: dataset that could ever justify a change. Steering means a run silently uses a
#: different topology from the one the operator asked for, and "the harness quietly
#: rerouted itself on run 47" is not a surprise a research tool gets to spring on
#: someone. Turn it on deliberately, once the archive has something to say.
DEFAULT_ARCHIVE_STEER = False


def normalize_walk_settings(source: "Mapping[str, Any]") -> dict[str, Any]:
    """Normalise the three settings that describe how a run walks its stages.

    One definition, called from every run-config reader and writer. The config
    functions each restate the whole field list, so a fourth setting added by hand
    in five places is a setting that will eventually be preserved on resume by four
    of them.
    """
    graph = str(source.get("stage_graph") or "").strip().lower()
    routing = str(source.get("routing_mode") or "").strip().lower()
    rounds = source.get("evolve_rounds")
    try:
        rounds_value = max(0, int(rounds))
    except (TypeError, ValueError):
        rounds_value = DEFAULT_EVOLVE_ROUNDS
    measure = source.get("evolve_measure")
    steer = source.get("archive_steer")
    return {
        "stage_graph": graph if graph in STAGE_GRAPH_CHOICES else DEFAULT_STAGE_GRAPH,
        "routing_mode": routing if routing in ROUTING_MODE_CHOICES else DEFAULT_ROUTING_MODE,
        "evolve_rounds": rounds_value,
        "evolve_measure": DEFAULT_EVOLVE_MEASURE if measure is None else bool(measure),
        "archive_steer": DEFAULT_ARCHIVE_STEER if steer is None else bool(steer),
    }
WEB_SEARCH_MODE_CHOICES = ("auto", "gemini", "native")
DEFAULT_WEB_SEARCH_MODE = "auto"


def normalize_web_search_mode(value: Any) -> str:
    """Clamp a persisted web-search mode to a known one.

    The *mode* is stored, never the resolved backend: `auto` is a question about the
    current environment, and freezing today's answer into the run would make a resumed run
    assert something about the deployment that may no longer be true.
    """
    if isinstance(value, str) and value.strip().lower() in WEB_SEARCH_MODE_CHOICES:
        return value.strip().lower()
    return DEFAULT_WEB_SEARCH_MODE


def resolve_min_report_figures(value: Any) -> int:
    """Clamp a configured figure floor into the range the judge can actually see.

    A floor above :data:`MAX_REPORT_FIGURES` would demand figures the scorer never looks
    at, turning the gate into busywork; below one it would allow a report with no figure
    at all, which no markdown deliverable should be.
    """
    try:
        wanted = int(value)
    except (TypeError, ValueError):
        wanted = MIN_REPORT_FIGURES
    return max(1, min(wanted, MAX_REPORT_FIGURES))


def default_run_config() -> dict[str, Any]:
    """The configuration a run falls back to when run_config.json is absent or unreadable."""
    return {
        "model": "unknown",
        "operator": "claude",
        "venue": DEFAULT_VENUE,
        "output_format": DEFAULT_OUTPUT_FORMAT,
        "approval_mode": "manual",
        "review_operator": "claude",
        "review_model": "sonnet",
        "codex_sandbox": DEFAULT_CODEX_SANDBOX,
        **normalize_walk_settings({}),
        "web_search": DEFAULT_WEB_SEARCH_MODE,
        "min_report_figures": MIN_REPORT_FIGURES,
        # A run whose config could not be read cannot claim a version either. This is the
        # code reading it, not the code that produced it, and the two differ exactly when
        # the question is being asked.
        "code_version": UNKNOWN_CODE_VERSION,
    }


def initialize_run_config(
    paths: RunPaths,
    model: str,
    venue: str | None = None,
    operator: str = "claude",
    approval_mode: str = "manual",
    review_operator: str | None = None,
    review_model: str | None = None,
    codex_sandbox: str | None = None,
    output_format: str | None = None,
    walk: "Mapping[str, Any] | None" = None,
    web_search: str | None = None,
    min_report_figures: int | None = None,
) -> dict[str, Any]:
    normalized_operator = operator.strip().lower() if operator.strip() else "claude"
    normalized_review_operator = (
        review_operator.strip().lower()
        if isinstance(review_operator, str) and review_operator.strip()
        else normalized_operator
    )
    selected_venue = resolve_venue_key(venue)
    config = {
        "model": model,
        "operator": normalized_operator,
        "venue": selected_venue,
        "output_format": resolve_output_format(output_format),
        "approval_mode": "agent" if approval_mode == "agent" else "manual",
        "review_operator": normalized_review_operator,
        "review_model": str(
            review_model
            or ("default" if normalized_review_operator == "codex" else "sonnet")
        ),
        "codex_sandbox": normalize_codex_sandbox(codex_sandbox),
        **normalize_walk_settings(walk or {}),
        "web_search": normalize_web_search_mode(web_search),
        "min_report_figures": resolve_min_report_figures(min_report_figures),
        # Stamped at run start, not read back at resume: it records the code this run began
        # under, which is the question a later reader is asking.
        "code_version": code_version(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_text(paths.run_config, json.dumps(config, indent=2, ensure_ascii=False))
    return config


def load_run_config(paths: RunPaths) -> dict[str, Any]:
    if not paths.run_config.exists():
        return default_run_config()

    try:
        payload = json.loads(read_text(paths.run_config))
    except json.JSONDecodeError:
        return default_run_config()

    if not isinstance(payload, dict):
        return default_run_config()

    model = payload.get("model")
    operator = payload.get("operator")
    venue = payload.get("venue")
    normalized_operator = operator.strip().lower() if isinstance(operator, str) and operator.strip() else "claude"
    review_operator = payload.get("review_operator")
    normalized_review_operator = (
        review_operator.strip().lower()
        if isinstance(review_operator, str) and review_operator.strip()
        else normalized_operator
    )
    review_model = payload.get("review_model")
    approval_mode = payload.get("approval_mode")
    codex_sandbox = payload.get("codex_sandbox")
    config = {
        "model": model if isinstance(model, str) and model.strip() else "unknown",
        "operator": normalized_operator,
        "venue": resolve_venue_key(venue if isinstance(venue, str) else None),
        "output_format": resolve_output_format(payload.get("output_format")),
        "approval_mode": "agent" if approval_mode == "agent" else "manual",
        "review_operator": normalized_review_operator,
        "review_model": (
            review_model.strip()
            if isinstance(review_model, str) and review_model.strip()
            else ("default" if normalized_review_operator == "codex" else "sonnet")
        ),
        "codex_sandbox": normalize_codex_sandbox(codex_sandbox),
        **normalize_walk_settings(payload),
        "web_search": normalize_web_search_mode(payload.get("web_search")),
        "min_report_figures": resolve_min_report_figures(payload.get("min_report_figures")),
        # Read back verbatim, never recomputed. This field answers "which code started this
        # run", and recomputing it on load would answer "which code is reading it" -- the
        # same string on the day the run happens and a different one every day after, which
        # is precisely when a reader is asking. A config written before the field existed
        # says so rather than borrowing today's commit.
        "code_version": (
            payload["code_version"].strip()
            if isinstance(payload.get("code_version"), str) and payload["code_version"].strip()
            else UNKNOWN_CODE_VERSION
        ),
    }
    created_at = payload.get("created_at")
    if isinstance(created_at, str) and created_at.strip():
        config["created_at"] = created_at
    return config


def save_run_config(paths: RunPaths, config: dict[str, Any]) -> None:
    normalized_operator = str(config.get("operator") or "claude").strip().lower() or "claude"
    normalized_review_operator = str(
        config.get("review_operator") or normalized_operator
    ).strip().lower() or normalized_operator
    normalized = {
        "model": str(config.get("model") or "unknown"),
        "operator": normalized_operator,
        "venue": resolve_venue_key(str(config.get("venue") or DEFAULT_VENUE)),
        "output_format": resolve_output_format(config.get("output_format")),
        "approval_mode": "agent" if config.get("approval_mode") == "agent" else "manual",
        "review_operator": normalized_review_operator,
        "review_model": str(
            config.get("review_model")
            or ("default" if normalized_review_operator == "codex" else "sonnet")
        ),
        "codex_sandbox": normalize_codex_sandbox(config.get("codex_sandbox")),
        **normalize_walk_settings(config),
        "web_search": normalize_web_search_mode(config.get("web_search")),
        "min_report_figures": resolve_min_report_figures(config.get("min_report_figures")),
        # Carried through, not recomputed, for the same reason `created_at` below is: this
        # says which code *started* the run. A resume runs newer code over an older run, and
        # stamping today's commit here would quietly rewrite the run's history to claim it
        # always ran on it. A config with nothing recorded says so.
        "code_version": (
            config["code_version"].strip()
            if isinstance(config.get("code_version"), str) and config["code_version"].strip()
            else UNKNOWN_CODE_VERSION
        ),
    }
    created_at = config.get("created_at")
    if isinstance(created_at, str) and created_at.strip():
        normalized["created_at"] = created_at
    else:
        normalized["created_at"] = datetime.now().isoformat(timespec="seconds")
    write_text(paths.run_config, json.dumps(normalized, indent=2, ensure_ascii=False))


def ensure_run_config(
    paths: RunPaths,
    model: str | None = None,
    venue: str | None = None,
    operator: str | None = None,
    approval_mode: str | None = None,
    review_operator: str | None = None,
    review_model: str | None = None,
    codex_sandbox: str | None = None,
    output_format: str | None = None,
    walk: "Mapping[str, Any] | None" = None,
    web_search: str | None = None,
    min_report_figures: int | None = None,
) -> dict[str, Any]:
    current = load_run_config(paths)
    effective_operator = operator or current.get("operator") or "claude"
    effective_review_operator = review_operator or current.get("review_operator") or effective_operator
    updated = {
        "model": model or current.get("model") or "unknown",
        "operator": effective_operator,
        "venue": resolve_venue_key(venue or current.get("venue")),
        "output_format": resolve_output_format(output_format or current.get("output_format")),
        "approval_mode": approval_mode or current.get("approval_mode") or "manual",
        "review_operator": effective_review_operator,
        "review_model": review_model or current.get("review_model") or (
            "default" if effective_review_operator == "codex" else "sonnet"
        ),
        "codex_sandbox": normalize_codex_sandbox(codex_sandbox or current.get("codex_sandbox")),
        "min_report_figures": resolve_min_report_figures(
            min_report_figures if min_report_figures is not None else current.get("min_report_figures")
        ),
        # An explicit setting wins; otherwise the run keeps what it was started
        # with, which is what makes `--resume-run` continue the same walk rather
        # than silently reverting an adaptive run to the linear default.
        **normalize_walk_settings({**current, **(walk or {})}),
        "web_search": normalize_web_search_mode(web_search or current.get("web_search")),
        "created_at": current.get("created_at") or datetime.now().isoformat(timespec="seconds"),
    }
    save_run_config(paths, updated)
    return updated


def resolve_stage(value: str | None) -> StageSpec | None:
    """Resolve a stage slug or number (``06_analysis``, ``6``, ``06``) to its spec."""
    if value is None:
        return None

    normalized = value.strip().lower()
    if not normalized:
        return None

    for stage in STAGES:
        if normalized in {stage.slug.lower(), str(stage.number), f"{stage.number:02d}"}:
            return stage

    raise ValueError(f"Unknown stage identifier: {value}")


def resolve_output_format(value: str | None) -> str:
    """Normalize a user-facing output-format name to a canonical key.

    Unknown values fall back to the default rather than raising: the value reaches this
    function from a run config that a previous version may have written without the field
    at all, and a run is not worth aborting over a spelling.
    """
    if not isinstance(value, str) or not value.strip():
        return DEFAULT_OUTPUT_FORMAT
    return _OUTPUT_FORMAT_ALIASES.get(value.strip().lower(), DEFAULT_OUTPUT_FORMAT)


def selected_output_format(paths: RunPaths) -> str:
    return resolve_output_format(load_run_config(paths).get("output_format"))


def selected_venue_key(paths: RunPaths) -> str:
    config = load_run_config(paths)
    return resolve_venue_key(config.get("venue") if isinstance(config.get("venue"), str) else None)


def selected_venue_profile(paths: RunPaths) -> dict[str, str]:
    registry = _load_template_registry()
    venue_key = selected_venue_key(paths)
    metadata = registry.get(venue_key, {})
    profile = dict(metadata)
    profile["venue_key"] = venue_key
    profile.setdefault("display_name", venue_key)
    profile.setdefault("venue_type", "conference")
    return profile


def format_venue_for_prompt(paths: RunPaths) -> str:
    profile = selected_venue_profile(paths)
    output_format = selected_output_format(paths)
    lines = [
        f"- final output format: `{output_format}`",
        (
            f"- scored deliverable: `{paths.report_file.resolve()}`"
            if output_format == "markdown"
            else f"- scored deliverable: compiled PDF from `{(paths.writing_dir / 'main.tex').resolve()}`"
        ),
        f"- target venue key: `{profile['venue_key']}`",
        f"- display name: {profile.get('display_name', profile['venue_key'])}",
        f"- venue type: {profile.get('venue_type', 'conference')}",
    ]
    if profile.get("page_limit"):
        lines.append(f"- nominal page limit: {profile['page_limit']}")
    if profile.get("citation_style"):
        lines.append(f"- citation style: {profile['citation_style']}")
    if profile.get("style_package"):
        lines.append(f"- preferred style package: `{profile['style_package']}`")
    lines.append(f"- run config: `{paths.run_config.resolve()}`")
    return "\n".join(lines)


def load_prompt_template(prompt_dir: Path, stage: StageSpec, output_format: str | None = None) -> str:
    """Load a stage prompt, preferring a format-specific variant when one exists.

    Only Stage 07 currently ships a variant (``07_writing_markdown.md``). Every other stage
    resolves to its single template, so adding a format never has to touch them.
    """
    candidates: list[Path] = []
    if output_format:
        candidates.append(prompt_dir / f"{stage.slug}_{resolve_output_format(output_format)}.md")
    candidates.append(prompt_dir / stage.filename)

    for template_path in candidates:
        if template_path.exists():
            return read_text(template_path)
    raise FileNotFoundError(f"Missing prompt template: {prompt_dir / stage.filename}")


def format_stage_template(template: str, stage: StageSpec, paths: RunPaths) -> str:
    replacements = {
        "{{STAGE_NUMBER}}": f"{stage.number:02d}",
        "{{STAGE_SLUG}}": stage.slug,
        "{{STAGE_NAME}}": stage.display_name,
        "{{RUN_ROOT}}": str(paths.run_root.resolve()),
        "{{USER_INPUT_PATH}}": str(paths.user_input.resolve()),
        "{{MEMORY_PATH}}": str(paths.memory.resolve()),
        "{{RUN_CONFIG_PATH}}": str(paths.run_config.resolve()),
        "{{LOGS_PATH}}": str(paths.logs.resolve()),
        "{{LOGS_RAW_PATH}}": str(paths.logs_raw.resolve()),
        "{{STAGE_OUTPUT_PATH}}": str(paths.stage_tmp_file(stage).resolve()),
        "{{STAGE_FINAL_OUTPUT_PATH}}": str(paths.stage_file(stage).resolve()),
        "{{WORKSPACE_ROOT}}": str(paths.workspace_root.resolve()),
        "{{WORKSPACE_LITERATURE_DIR}}": str(paths.literature_dir.resolve()),
        "{{WORKSPACE_CODE_DIR}}": str(paths.code_dir.resolve()),
        "{{WORKSPACE_DATA_DIR}}": str(paths.data_dir.resolve()),
        "{{WORKSPACE_RESULTS_DIR}}": str(paths.results_dir.resolve()),
        "{{WORKSPACE_WRITING_DIR}}": str(paths.writing_dir.resolve()),
        "{{WORKSPACE_REPORT_DIR}}": str(paths.report_dir.resolve()),
        "{{WORKSPACE_REPORT_FILE}}": str(paths.report_file.resolve()),
        "{{WORKSPACE_REPORT_IMAGES_DIR}}": str(paths.report_images_dir.resolve()),
        "{{OUTPUT_FORMAT}}": selected_output_format(paths),
        "{{MAX_REPORT_FIGURES}}": str(MAX_REPORT_FIGURES),
        "{{WORKSPACE_FIGURES_DIR}}": str(paths.figures_dir.resolve()),
        "{{WORKSPACE_ARTIFACTS_DIR}}": str(paths.artifacts_dir.resolve()),
        "{{WORKSPACE_NOTES_DIR}}": str(paths.notes_dir.resolve()),
        "{{WORKSPACE_REVIEWS_DIR}}": str(paths.reviews_dir.resolve()),
        "{{WORKSPACE_BOOTSTRAP_DIR}}": str(paths.bootstrap_dir.resolve()),
        "{{WORKSPACE_PROFILE_DIR}}": str(paths.profile_dir.resolve()),
        "{{SELECTED_VENUE}}": selected_venue_key(paths),
    }

    formatted = template
    for placeholder, value in replacements.items():
        formatted = formatted.replace(placeholder, value)
    return formatted


def required_stage_output_template(stage: StageSpec) -> str:
    return (
        f"# Stage {stage.number:02d}: {stage.display_name}\n\n"
        "## Objective\n"
        "[State the exact objective of this stage.]\n\n"
        "## What I Did\n"
        "[Describe what you actually did in this stage.]\n\n"
        "## Key Results\n"
        "[Present the main results, findings, conclusions, or concrete outputs for this stage.]\n\n"
        "## Files Produced\n"
        "- `[relative/path]` - [what it contains]\n\n"
        "## Decision Ledger\n"
        "- **Open Questions**: [unresolved questions to carry forward to later stages]\n"
        "- **Locked Decisions**: [design or method decisions made in this stage, with rationale]\n"
        "- **Assumptions**: [accepted assumptions that downstream stages must respect]\n"
        "- **Rejected Alternatives**: [what was considered and why it was dropped]\n\n"
        "## Suggestions for Refinement\n"
        "1. [Suggestion 1]\n"
        "2. [Suggestion 2]\n"
        "3. [Suggestion 3]\n\n"
        "## Your Options\n"
        + "\n".join(FIXED_STAGE_OPTIONS)
    )


def build_prompt(
    stage: StageSpec,
    stage_template: str,
    user_request: str,
    approved_memory: str,
    handoff_context: str = "",
    revision_feedback: str | None = None,
    intake_context_text: str | None = None,
    web_search_context: str | None = None,
    obligations_context: str | None = None,
) -> str:
    sections = [
        "# Stage Instructions",
        stage_template.strip(),
        "# Required Stage Summary Format",
        (
            "You must create or overwrite the stage summary markdown file using exactly the "
            "top-level heading order below. Do not omit any section. Use exactly 3 numbered "
            "refinement suggestions and exactly the fixed 6 option lines."
        ),
        "```md\n" + required_stage_output_template(stage).strip() + "\n```",
        "# Execution Discipline",
        (
            "1. The stage output path is a temporary draft path for the current attempt, not the final approved stage file.\n"
            "2. The final approved stage file will be promoted separately by the workflow manager after validation.\n"
            "3. Do not write half-finished, in-progress, placeholder, outline-only, or pending content to the stage output file.\n"
            "4. If you need scratch work, drafts, notes, or temporary checkpoints, write them under the workspace directories instead of the stage output file.\n"
            "5. Only write or overwrite the stage output file once you are ready to produce a complete stage summary for the current attempt.\n"
            "6. If any tool, search, or subtask fails, still finish the stage by writing the best complete summary you can, clearly marking limitations in prose rather than leaving placeholders.\n"
            "7. Read the stage output file back before finishing and verify every required heading is present and fully filled.\n"
            "8. Do not leave placeholder text such as [In progress], [Pending], [TODO], [TBD], or similar unfinished in the final file.\n"
            "9. Never leave the stage without a valid stage summary markdown file at the temporary output path."
        ),
        "# Original User Request",
        user_request.strip(),
    ]
    # Placed straight after the request it is derived from: what the task demands, and
    # the artifact that will be checked against those demands. A run can be rigorous
    # about the wrong question, and nothing else in the prompt notices.
    from .deliverables import format_deliverables_for_prompt

    deliverables_block = format_deliverables_for_prompt(task_statement(user_request))
    if deliverables_block:
        sections.extend(["# What the Task Asks For", deliverables_block])
    if obligations_context:
        sections.extend(["# Obligations Carried Forward", obligations_context.strip()])
    if web_search_context:
        sections.extend(["# Web Search Capability", web_search_context.strip()])
    if intake_context_text:
        sections.extend([
            "# Intake Context (User-Provided Resources and Clarifications)",
            intake_context_text.strip(),
        ])
    sections.extend(["# Approved Memory", approved_memory.strip() or "_None yet._"])

    # The handoff is a strict subset of approved memory: `build_handoff_context`
    # renders Objective / Key Results / Files Produced for the last four stages
    # with the Decision Ledger stripped, and `render_approved_stage_entry` puts
    # exactly those sections — plus What I Did — into memory for every approved
    # stage. Sending both put ~350 words of verbatim duplicate into every prompt
    # from Stage 04 on, half the prompt being prior-stage history by Stage 08.
    # The continuation prompt still needs it, because that path sends no memory.
    if not approved_memory.strip():
        sections.extend([
            "# Stage Handoff Context",
            handoff_context.strip() or "No stage handoff summaries available yet.",
        ])

    sections.extend([
        "# Revision Feedback",
        revision_feedback.strip() if revision_feedback else "None.",
    ])
    return "\n\n".join(sections).strip() + "\n"


def build_continuation_prompt(
    stage: StageSpec,
    stage_template: str,
    paths: RunPaths,
    handoff_context: str,
    revision_feedback: str | None,
    intake_context_text: str | None = None,
    attempt_no: int = 1,
    previous_validation_errors: list[str] | None = None,
    web_search_context: str | None = None,
    obligations_context: str | None = None,
) -> str:
    current_draft = paths.stage_tmp_file(stage)
    current_final = paths.stage_file(stage)

    sections = [
        "# Continue Existing Stage Conversation",
        (
            f"You are continuing {stage.stage_title} in the same AutoR conversation for this stage. "
            "This is an incremental improvement pass inside the current stage, not a fresh restart."
        ),
        "# Stage Instructions",
        stage_template.strip(),
        "# Required Stage Summary Format",
        (
            "You must create or overwrite the stage summary markdown file using exactly the "
            "top-level heading order below. Do not omit any section. Use exactly 3 numbered "
            "refinement suggestions and exactly the fixed 6 option lines."
        ),
        "```md\n" + required_stage_output_template(stage).strip() + "\n```",
        "# Continuation Discipline",
        (
            f"1. Read the current draft at `{current_draft.resolve()}` if it exists.\n"
            f"2. Read the last promoted stage summary at `{current_final.resolve()}` if it exists.\n"
            f"3. Read approved memory from `{paths.memory.resolve()}` and the original user goal from `{paths.user_input.resolve()}` if needed.\n"
            f"4. Read prior handoff summaries under `{paths.handoff_dir.resolve()}` when they exist.\n"
            f"4. Treat workspace artifacts already under `{paths.workspace_root.resolve()}` as part of the current stage context and reuse them.\n"
            "5. Preserve all valid work already completed in this stage unless the new feedback requires changing it.\n"
            "6. Fill the missing pieces, fix weak points, and update the stage summary instead of throwing away correct work.\n"
            "7. Overwrite only the draft stage output path once you are ready to produce the updated complete summary.\n"
            "8. Do not leave placeholder text such as [In progress], [Pending], [TODO], [TBD], or similar unfinished markers.\n"
            "9. If the existing stage work is partially correct, keep the correct parts and extend them rather than replacing them blindly.\n"
            "10. **Revision Delta**: Because this is a refinement pass, you MUST insert a `## Revision Delta` section "
            "immediately after the top-level `# Stage ...` heading and before `## Objective`. "
            "This section must contain a concise bullet-point summary of what you changed in this attempt compared to the previous version. Include:\n"
            "   - Which sections were modified and how\n"
            "   - Any files added, removed, or changed\n"
            "   - A one-sentence summary of the overall improvement\n"
            "This block is for the human reviewer only and will be stripped before the stage summary is saved."
        ),
    ]
    if web_search_context:
        sections.extend(["# Web Search Capability", web_search_context.strip()])
    # A contract that only appears on the first attempt is one every retry can forget.
    from .deliverables import format_deliverables_for_prompt

    _deliverables = format_deliverables_for_prompt(task_statement(read_text(paths.user_input)))
    if _deliverables:
        sections.extend(["# What the Task Asks For", _deliverables])
    if intake_context_text:
        sections.extend([
            "# Intake Context (User-Provided Resources and Clarifications)",
            intake_context_text.strip(),
        ])
    if attempt_no >= 3 and previous_validation_errors:
        error_list = "\n".join(f"- {e}" for e in previous_validation_errors)
        sections.extend([
            "# Recovery Context",
            (
                f"This is attempt {attempt_no}. The following validation errors have persisted "
                f"from the previous attempt:\n{error_list}\n\n"
                "If you believe these errors cannot be resolved within the current stage "
                "(e.g. missing external files, impossible constraints), state that clearly "
                "in your stage summary under ## What I Did so the human reviewer can decide "
                "how to proceed."
            ),
        ])
    sections.extend([
        "# Stage Handoff Context",
        handoff_context.strip() or "No stage handoff summaries available yet.",
        "# New Feedback",
        revision_feedback.strip()
        if revision_feedback
        else "Continue improving the current stage output and fix the issues from the previous attempt.",
    ])
    return "\n\n".join(sections).strip() + "\n"


def truncate_text(text: str, max_chars: int = 12000) -> str:
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[: max_chars - 3].rstrip() + "..."


def extract_markdown_section(markdown: str, heading: str) -> str | None:
    pattern = re.compile(
        rf"^## {re.escape(heading)}\s*$\n?(.*?)(?=^## |\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(markdown)
    if not match:
        return None
    return match.group(1).strip()


#: Fences around a verbatim task statement inside an assembled goal.
#:
#: A goal can carry a whole task document — the benchmark adapter writes one — and such
#: a document brings its own ``##`` headings, so :func:`extract_markdown_section` cannot
#: pick it out: the section ends at the first heading *inside* it. These delimit it
#: instead. HTML comments, because a goal is prose an operator reads and a visible fence
#: is a fence it can mistake for an instruction.
TASK_BEGIN_MARKER = "<!-- autor:task:begin -->"
TASK_END_MARKER = "<!-- autor:task:end -->"


def extract_fenced_task(goal: str) -> str | None:
    """The fenced task statement in ``goal``, or ``None`` if there is not one.

    ``None`` means an ordinary goal — one a user typed, or one recorded before the
    fences existed — and is the signal to fall back to reading the goal itself.
    """
    start = goal.find(TASK_BEGIN_MARKER)
    if start < 0:
        return None
    start += len(TASK_BEGIN_MARKER)
    end = goal.find(TASK_END_MARKER, start)
    if end < 0:
        return None
    return goal[start:end].strip() or None


def task_statement(goal: str) -> str:
    """What the *task* asked for, with anything wrapped around it removed.

    A goal is not always only the question. The benchmark adapter builds one that carries
    a workspace contract, a grading rubric and a figure budget alongside the task, and
    :mod:`src.deliverables` reads a goal for the sentences that ask for something. Read
    off the whole thing, ``demanding_sentences`` returned 23 demands for Astronomy_000
    where the task has 10 — thirteen phantoms, the first of which is "Benchmark Run:
    ResearchClawBench". The stage was then told those were its requirements and the
    coverage gate held the report to them.
    """
    return extract_fenced_task(goal) or goal


def goal_excerpt(goal: str, max_chars: int) -> str:
    """An excerpt of ``goal`` that is guaranteed to contain the question.

    Several readers take a *prefix* of the goal to fit a budget: the router that
    chooses the next graph move, the deliberation panel, the adversarial validity
    reviewer. A prefix is only the question while nothing has been prepended to it,
    and on a benchmark run the grading contract in front of the task had grown past
    every one of those budgets — the router chose its move having read none of the
    research question at all. Where a task is fenced, this returns the task and
    truncates from the *tail*, so an overlong one loses its closing notes rather than
    its subject.
    """
    task = extract_fenced_task(goal)
    return truncate_text(task if task is not None else goal, max_chars=max_chars)


def strip_markdown_section(markdown: str, heading: str) -> str:
    pattern = re.compile(
        rf"^## {re.escape(heading)}\s*$\n?(.*?)(?=^## |\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    stripped = pattern.sub("", markdown)
    return re.sub(r"\n{3,}", "\n\n", stripped).strip()


def parse_numbered_list(section_text: str) -> dict[int, str]:
    items: dict[int, str] = {}
    current_id: int | None = None
    current_lines: list[str] = []

    for raw_line in section_text.splitlines():
        line = raw_line.rstrip()
        match = re.match(r"^\s*(\d+)\.\s+(.*)$", line)
        if match:
            if current_lines and current_id is not None:
                items[current_id] = " ".join(current_lines).strip()
            current_id = int(match.group(1))
            current_lines = [match.group(2).strip()]
            continue

        if current_lines and line.strip():
            current_lines.append(line.strip())

    if current_lines and current_id is not None:
        items[current_id] = " ".join(current_lines).strip()

    return items


def parse_numbered_list_sequence(section_text: str) -> list[int]:
    sequence: list[int] = []
    for raw_line in section_text.splitlines():
        match = re.match(r"^\s*(\d+)\.\s+(.*)$", raw_line.rstrip())
        if match:
            sequence.append(int(match.group(1)))
    return sequence


def parse_refinement_suggestions(markdown: str) -> list[str]:
    section = extract_markdown_section(markdown, "Suggestions for Refinement")
    if section is None:
        raise ValueError("Missing 'Suggestions for Refinement' section.")

    items = parse_numbered_list(section)
    missing = [number for number in (1, 2, 3) if number not in items]
    if missing:
        raise ValueError(f"Missing refinement suggestion(s): {missing}")

    return [items[1], items[2], items[3]]


_REVISION_DELTA_RE = re.compile(
    r"^## Revision Delta\s*\n(.*?)(?=^## |\Z)",
    flags=re.MULTILINE | re.DOTALL,
)


def extract_revision_delta(markdown: str) -> str | None:
    """Extract the Revision Delta section content from stage markdown.

    Returns the delta text if present, or None if the section is absent.
    """
    match = _REVISION_DELTA_RE.search(markdown)
    if not match:
        return None
    return match.group(1).strip() or None


def strip_revision_delta(markdown: str) -> str:
    """Remove the Revision Delta section from stage markdown.

    Returns the markdown with the delta block stripped so it is not persisted
    in the final stage summary.
    """
    stripped = _REVISION_DELTA_RE.sub("", markdown)
    # Collapse any triple-or-more blank lines left behind
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)
    return stripped


def contains_placeholder_text(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in PLACEHOLDER_PATTERNS)


def validate_stage_markdown(
    markdown: str,
    stage: StageSpec | None = None,
    paths: RunPaths | None = None,
    artifact_roots: "Sequence[Path] | None" = None,
) -> list[str]:
    problems: list[str] = []

    lines = markdown.splitlines()
    first_nonempty_line = next((line.strip() for line in lines if line.strip()), "")
    if not markdown.startswith("# Stage "):
        problems.append("Stage markdown must begin with '# Stage '.")
    elif stage is not None and first_nonempty_line != f"# {stage.stage_title}":
        problems.append(f"Stage markdown title must be exactly '# {stage.stage_title}'.")

    for heading in REQUIRED_STAGE_HEADINGS:
        section = extract_markdown_section(markdown, heading)
        if section is None:
            problems.append(f"Missing required section: {heading}")
            continue

        if contains_placeholder_text(section):
            problems.append(f"Section '{heading}' still contains placeholder text.")

        if heading == "Files Produced":
            listed_files = _extract_path_references(section)
            if not listed_files:
                problems.append("Section 'Files Produced' must list at least one concrete file path.")
            elif paths is not None:
                missing_files = [
                    file_ref
                    for file_ref in listed_files
                    if not _listed_file_exists(paths.run_root, file_ref, artifact_roots)
                ]
                if missing_files:
                    problems.append(
                        "Section 'Files Produced' references missing file(s): "
                        + ", ".join(f"`{path}`" for path in missing_files)
                    )
        elif heading == "Decision Ledger":
            required_keywords = [
                "Open Questions",
                "Locked Decisions",
                "Assumptions",
                "Rejected Alternatives",
            ]
            if any(keyword not in section for keyword in required_keywords):
                problems.append(
                    "Section 'Decision Ledger' must include Open Questions, Locked Decisions, "
                    "Assumptions, and Rejected Alternatives."
                )

    if stage is not None and stage.slug == "02_hypothesis_generation":
        hypothesis_sections = extract_typed_hypothesis_sections(markdown)
        for heading in TYPED_HYPOTHESIS_HEADINGS:
            if heading not in hypothesis_sections:
                problems.append(
                    "Stage 02 'Key Results' must include typed subsections for Theoretical Propositions, "
                    "Empirical Hypotheses, and Paper Claims (Provisional)."
                )
                break
        identifier_patterns = {
            "Theoretical Propositions": r"\*\*T\d+\*\*:",
            "Empirical Hypotheses": r"\*\*H\d+\*\*:",
            "Paper Claims (Provisional)": r"\*\*C\d+\*\*:",
        }
        for heading, pattern in identifier_patterns.items():
            section = hypothesis_sections.get(heading)
            if section is not None and not re.search(pattern, section):
                problems.append(
                    f"Stage 02 subsection '{heading}' must include at least one typed identifier."
                )

    options_section = extract_markdown_section(markdown, "Your Options")
    if options_section is not None:
        option_sequence = parse_numbered_list_sequence(options_section)
        if option_sequence != [1, 2, 3, 4, 5, 6]:
            problems.append("Section 'Your Options' must contain exactly options 1-6 in order with no extras.")
        option_items = parse_numbered_list(options_section)
        for number in range(1, 7):
            if number not in option_items:
                problems.append(f"Missing option {number} in 'Your Options'.")
                continue
            expected_text = FIXED_STAGE_OPTIONS[number - 1].split(". ", 1)[1]
            if option_items[number] != expected_text:
                problems.append(f"Option {number} in 'Your Options' must be exactly '{expected_text}'.")

    suggestions_section = extract_markdown_section(markdown, "Suggestions for Refinement")
    if suggestions_section is not None:
        suggestion_sequence = parse_numbered_list_sequence(suggestions_section)
        if suggestion_sequence != [1, 2, 3]:
            problems.append(
                "Section 'Suggestions for Refinement' must contain exactly suggestions 1-3 in order with no extras."
            )
    try:
        suggestions = parse_refinement_suggestions(markdown)
        if len(suggestions) != 3:
            problems.append("Expected exactly 3 refinement suggestions.")
        for index, suggestion in enumerate(suggestions, start=1):
            if contains_placeholder_text(suggestion):
                problems.append(
                    f"Suggestion {index} in 'Suggestions for Refinement' still contains placeholder text."
                )
    except ValueError as exc:
        problems.append(str(exc))

    return problems


def extract_markdown_image_targets(markdown: str) -> list[str]:
    """Return every image target referenced by a markdown document, in document order.

    Both ``![alt](target)`` and ``<img src="target">`` count: a report that renders a figure
    through raw HTML still has to point at a file that exists.
    """
    targets: list[tuple[int, str]] = []
    for pattern in (MARKDOWN_IMAGE_PATTERN, HTML_IMAGE_PATTERN):
        for match in pattern.finditer(markdown):
            raw = match.group(1).strip()
            if raw.startswith("<") and raw.endswith(">"):
                raw = raw[1:-1].strip()
            if raw:
                targets.append((match.start(), raw))
    return [target for _, target in sorted(targets, key=lambda item: item[0])]


def _split_image_target(target: str) -> str:
    """Drop a URL fragment or query string so the remainder can be treated as a path."""
    return target.split("#", 1)[0].split("?", 1)[0]


def resolve_report_image(report_dir: Path, target: str) -> Path | None:
    """Resolve a report-relative image target, or None when it is not a local relative path.

    A target that climbs out of the report directory is rejected even when it resolves on
    this machine. Only ``report/`` travels to the benchmark workspace, so ``../figures/x.png``
    is a link that works here and is broken everywhere the report is actually read.
    """
    cleaned = _split_image_target(target).strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    if lowered.startswith(("http://", "https://", "data:", "ftp://", "file://")):
        return None
    candidate = Path(cleaned)
    if candidate.is_absolute():
        return None

    resolved = (report_dir / candidate).resolve()
    try:
        resolved.relative_to(report_dir.resolve())
    except ValueError:
        return None
    return resolved


def validate_markdown_report(paths: RunPaths) -> list[str]:
    """Check the markdown deliverable the benchmark judge will actually read.

    The judge reads ``report/report.md`` as plain text and separately attaches image files it
    finds on disk. A figure reference that does not resolve therefore fails twice over: the
    prose promises a figure and the judge is shown nothing. That is the single most expensive
    defect in this deliverable, so it is a hard gate rather than a warning.
    """
    problems: list[str] = []
    report_path = paths.report_file
    if not report_path.exists():
        return [
            "requires a markdown research report at "
            f"{report_path.relative_to(paths.run_root).as_posix()}."
        ]

    report_text = read_text(report_path)
    if len(report_text.strip()) < MIN_REPORT_CHARS:
        problems.append(
            f"report.md is only {len(report_text.strip())} characters; a scored research report "
            f"needs at least {MIN_REPORT_CHARS} characters of methodology, results, and discussion."
        )

    if contains_placeholder_text(report_text):
        problems.append("report.md still contains placeholder text.")

    targets = extract_markdown_image_targets(report_text)
    if not targets:
        problems.append(
            "report.md references no figures. Generate plots, save them under "
            "report/images/, and embed them with `![Caption](images/name.png)`."
        )

    for target in targets:
        resolved = resolve_report_image(paths.report_dir, target)
        if resolved is None:
            problems.append(
                f"report.md references `{target}`, which is not a report-relative path. "
                "Use paths relative to report.md, for example `images/main_result.png`."
            )
            continue
        if not resolved.exists():
            problems.append(f"report.md references `{target}`, but no such file exists under report/.")
            continue
        if resolved.suffix.lower() not in RENDERABLE_IMAGE_SUFFIXES:
            problems.append(
                f"report.md references `{target}`, whose format cannot be rendered by the "
                f"report viewer. Save figures as {PREFERRED_REPORT_IMAGE_SUFFIX} instead."
            )

    published = _count_files_with_suffixes(paths.report_images_dir, RENDERABLE_IMAGE_SUFFIXES)
    floor = resolve_min_report_figures(load_run_config(paths).get("min_report_figures"))
    if published < floor:
        problems.append(
            f"report/images/ holds {published} rendered figure(s) but this run requires at "
            f"least {floor}. One figure cannot answer more than one question, and a report "
            "that under-illustrates forfeits the criteria it never addresses. Add figures "
            "that settle *different* questions the task asks — a data overview, the main "
            "result, and a validation or comparison are the usual three — rather than more "
            f"views of the same one. Save them as {PREFERRED_REPORT_IMAGE_SUFFIX}."
        )
    elif published > MAX_REPORT_FIGURES:
        problems.append(
            f"report/images/ holds {published} figures but only {MAX_REPORT_FIGURES} reach the "
            "reviewer, chosen in filesystem order rather than by importance. Merge related panels "
            f"into one composite figure or delete the weakest, until at most {MAX_REPORT_FIGURES} "
            "remain."
        )

    return problems


def validate_stage_artifacts(
    stage: StageSpec,
    paths: RunPaths,
    artifact_dirs: "Mapping[str, Sequence[Path]] | None" = None,
) -> list[str]:
    """Check that a stage produced the machine-readable artifacts its gate requires.

    ``artifact_dirs`` adds extra directories to search per category (``data``, ``results``,
    ``figures``). A ResearchClawBench run needs them: its output contract points stages at
    ``<workspace>/outputs/`` and ``<workspace>/report/images/``, which sit outside the run
    tree, so a compliant stage would otherwise look like it produced nothing.

    The benchmark's own read-only ``data/`` is deliberately *not* one of these. It is always
    populated, so counting it would make the stage-03 gate pass without the stage producing
    anything — the gate exists to prove work happened, not that inputs exist.
    """
    problems: list[str] = []
    freshness_cutoff = stage_execution_started_at(paths, stage)

    def dirs_for(category: str, primary: Path) -> list[Path]:
        return [primary, *(artifact_dirs or {}).get(category, ())]

    def count_in(category: str, primary: Path, suffixes) -> int:
        return sum(_count_files_with_suffixes(d, suffixes) for d in dirs_for(category, primary))

    def recent_in(category: str, primary: Path, suffixes, cutoff) -> bool:
        return any(
            _has_recent_files_with_suffixes(d, suffixes, cutoff)
            for d in dirs_for(category, primary)
        )

    if stage.number == 1:
        from .evidence_ledger import validate_literature_evidence

        for problem in validate_literature_evidence(paths):
            problems.append(f"{stage.stage_title}: {problem}")

    # Answering the previous stage's adversarial review. Self-selecting: only
    # Stage 06 (answering 05) and Stage 07 (answering 06) owe anything.
    from .research_rounds import validate_round_decision
    from .validity_review import validate_validity_response

    for problem in validate_validity_response(paths, stage):
        problems.append(f"{stage.stage_title} {problem}")
    for problem in validate_round_decision(paths, stage):
        problems.append(f"{stage.stage_title} {problem}")

    if stage.number >= 2:
        # Held at the stage that writes the hypotheses, for the reason the report-plan
        # comment below spells out: the Stage 02 prompt requires a decision rule on
        # every empirical hypothesis, and the first gate that read one was
        # `validate_preregistration` at Stage 05 — three stages later, after Stage 04
        # froze the set, where the only repair is a rollback.
        from .hypothesis_manifest import validate_hypothesis_decision_rules

        for problem in validate_hypothesis_decision_rules(paths):
            problems.append(f"{stage.stage_title} {problem}")

    if stage.number >= 3:
        if count_in("data", paths.data_dir, MACHINE_DATA_SUFFIXES) == 0:
            problems.append(
                f"{stage.stage_title} requires machine-readable data artifacts under workspace/data, not only markdown notes."
            )
        elif stage.number == 3 and freshness_cutoff is not None and not recent_in(
            "data", paths.data_dir, MACHINE_DATA_SUFFIXES, freshness_cutoff
        ):
            problems.append(
                f"{stage.stage_title} requires machine-readable data artifacts produced or updated during the current stage execution."
            )

        # Which figures the report will carry, held at the stage that writes it.
        # The experimental protocol is the counter-example: the Stage 03 prompt
        # asks for it and the gate first fires at Stage 05, so a Stage 03 that
        # skipped it is approved and the failure surfaces two stages later,
        # where the only repair is a rollback.
        from .report_plan import validate_report_plan

        for problem in validate_report_plan(paths, selected_output_format(paths)):
            problems.append(f"{stage.stage_title} {problem}")

    if stage.number >= 5:
        # The scientific-validity chain, distinct from the artifact gates around
        # it: the hypotheses were frozen before results existed (05), every one
        # of them got a verdict backed by an artifact (06), and every claim the
        # manuscript makes traces to a supported hypothesis or is labelled
        # exploratory (07). Without these, nothing in the pipeline notices a
        # hypothesis that was quietly rewritten to match the result.
        from .experimental_protocol import validate_experimental_protocol
        from .preregistration import validate_preregistration

        for problem in validate_preregistration(paths):
            problems.append(f"{stage.stage_title} {problem}")
        for problem in validate_experimental_protocol(paths):
            problems.append(f"{stage.stage_title} {problem}")

        if count_in("results", paths.results_dir, RESULT_SUFFIXES) == 0:
            problems.append(
                f"{stage.stage_title} requires machine-readable result artifacts under workspace/results."
            )
        if not paths.experiment_manifest.exists():
            problems.append(
                f"{stage.stage_title} requires experiment_manifest.json under workspace/results."
            )
        else:
            from .experiment_manifest import validate_experiment_manifest

            for problem in validate_experiment_manifest(paths.experiment_manifest):
                problems.append(f"{stage.stage_title}: {problem}")

    if stage.number >= 6:
        from .experimental_protocol import validate_outcome_statistics
        from .preregistration import validate_hypothesis_outcomes
        from .report_plan import validate_report_plan_sources

        for problem in validate_hypothesis_outcomes(paths):
            problems.append(f"{stage.stage_title} {problem}")
        for problem in validate_outcome_statistics(paths):
            problems.append(f"{stage.stage_title} {problem}")
        # Never draw a figure from numbers you did not compute — checked at the
        # stage that draws them, where producing the missing file is still a
        # move the run can make.
        for problem in validate_report_plan_sources(
            paths,
            [
                *(artifact_dirs or {}).get("results", ()),
                *(artifact_dirs or {}).get("data", ()),
            ],
        ):
            problems.append(f"{stage.stage_title} {problem}")

        if count_in("figures", paths.figures_dir, FIGURE_SUFFIXES) == 0:
            problems.append(
                f"{stage.stage_title} requires figure artifacts under workspace/figures."
            )
        elif stage.number == 6 and freshness_cutoff is not None and not recent_in(
            "figures", paths.figures_dir, FIGURE_SUFFIXES, freshness_cutoff
        ):
            problems.append(
                f"{stage.stage_title} requires figures produced or updated during the current stage execution."
            )

    if stage.number >= 7:
        from .preregistration import validate_claim_provenance

        for problem in validate_claim_provenance(paths):
            problems.append(f"{stage.stage_title} {problem}")

    if stage.number >= 7 and selected_output_format(paths) == "markdown":
        from .report_plan import validate_report_plan_coverage

        problems.extend(
            f"{stage.stage_title}: {problem}"
            for problem in validate_markdown_report(paths)
        )
        problems.extend(
            f"{stage.stage_title}: {problem}"
            for problem in validate_report_plan_coverage(
                paths, [*(artifact_dirs or {}).get("figures", ())]
            )
        )

        # Rigour about the wrong question still fails the task. Everything above this
        # measures how well the report was made; this measures whether it answered what
        # was asked.
        from .deliverables import validate_deliverables_coverage

        problems.extend(
            f"{stage.stage_title}: {problem}"
            for problem in validate_deliverables_coverage(paths, task_statement(read_text(paths.user_input)))
        )

        if not (paths.artifacts_dir / "citation_verification.json").exists():
            problems.append(
                f"{stage.stage_title} requires citation_verification.json under workspace/artifacts."
            )
        else:
            from .evidence_ledger import validate_citation_verification

            for problem in validate_citation_verification(paths.artifacts_dir / "citation_verification.json"):
                problems.append(f"{stage.stage_title}: {problem}")

        if not (paths.artifacts_dir / "self_review.json").exists():
            problems.append(
                f"{stage.stage_title} requires self_review.json under workspace/artifacts."
            )

        report_review_path = paths.artifacts_dir / "report_review.json"
        if not report_review_path.exists():
            problems.append(
                f"{stage.stage_title} requires report_review.json under workspace/artifacts."
            )
        else:
            from .writing_manifest import validate_report_review

            for problem in validate_report_review(report_review_path):
                problems.append(f"{stage.stage_title}: {problem}")

        if stage.number == 7 and freshness_cutoff is not None:
            stage7_required_files = [
                paths.report_file,
                paths.artifacts_dir / "citation_verification.json",
                paths.artifacts_dir / "self_review.json",
                report_review_path,
            ]
            if not all(path.exists() and path.stat().st_mtime >= freshness_cutoff for path in stage7_required_files):
                problems.append(
                    f"{stage.stage_title} requires report.md and its review artifacts to be produced "
                    "or updated during the current stage execution."
                )

    elif stage.number >= 7:
        main_tex = paths.writing_dir / "main.tex"
        if not main_tex.exists():
            problems.append(
                f"{stage.stage_title} requires main.tex under workspace/writing."
            )
        elif not _looks_like_supported_manuscript(main_tex, selected_venue_key(paths)):
            problems.append(
                f"{stage.stage_title} requires a supported conference or journal manuscript in workspace/writing/main.tex. "
                f"Expected venue: {selected_venue_key(paths)}. Use a matching style package or add a comment such as '% AutoR venue: {selected_venue_key(paths)}' near the top of main.tex."
            )

        bib_files = [path for path in _existing_files(paths.writing_dir) if path.suffix.lower() in BIB_SUFFIXES]
        if not bib_files and not _has_inline_bibliography(paths.writing_dir):
            problems.append(
                f"{stage.stage_title} requires a .bib file or an inline bibliography in the writing package."
            )

        sections_dir = paths.writing_dir / "sections"
        section_tex_files = list(sections_dir.glob("*.tex")) if sections_dir.exists() else []
        if not section_tex_files:
            problems.append(
                f"{stage.stage_title} requires section .tex files under workspace/writing/sections."
            )

        pdf_count = _count_files_with_suffixes(paths.writing_dir, PDF_SUFFIXES)
        pdf_count += _count_files_with_suffixes(paths.artifacts_dir, PDF_SUFFIXES)
        if pdf_count == 0:
            problems.append(
                f"{stage.stage_title} requires a compiled PDF manuscript under workspace/writing or workspace/artifacts."
            )

        if not (paths.artifacts_dir / "build_log.txt").exists():
            problems.append(
                f"{stage.stage_title} requires build_log.txt under workspace/artifacts."
            )

        if not (paths.artifacts_dir / "citation_verification.json").exists():
            problems.append(
                f"{stage.stage_title} requires citation_verification.json under workspace/artifacts."
            )
        else:
            from .evidence_ledger import validate_citation_verification

            for problem in validate_citation_verification(paths.artifacts_dir / "citation_verification.json"):
                problems.append(f"{stage.stage_title}: {problem}")

        if not (paths.artifacts_dir / "self_review.json").exists():
            problems.append(
                f"{stage.stage_title} requires self_review.json under workspace/artifacts."
            )

        if not (paths.artifacts_dir / "layout_review.json").exists():
            problems.append(
                f"{stage.stage_title} requires layout_review.json under workspace/artifacts."
            )
        else:
            from .writing_manifest import validate_layout_review

            for problem in validate_layout_review(paths.artifacts_dir / "layout_review.json"):
                problems.append(f"{stage.stage_title}: {problem}")

        if stage.number == 7 and freshness_cutoff is not None:
            stage7_required_files = [
                main_tex,
                paths.artifacts_dir / "build_log.txt",
                paths.artifacts_dir / "citation_verification.json",
                paths.artifacts_dir / "self_review.json",
                paths.artifacts_dir / "layout_review.json",
            ]
            if not all(path.exists() and path.stat().st_mtime >= freshness_cutoff for path in stage7_required_files):
                problems.append(
                    f"{stage.stage_title} requires the writing package and build metadata to be produced or updated during the current stage execution."
                )
            if not _has_recent_files_with_suffixes(paths.writing_dir, PDF_SUFFIXES, freshness_cutoff) and not _has_recent_files_with_suffixes(
                paths.artifacts_dir, PDF_SUFFIXES, freshness_cutoff
            ):
                problems.append(
                    f"{stage.stage_title} requires a manuscript PDF produced or updated during the current stage execution."
                )
            sections_dir = paths.writing_dir / "sections"
            if not _has_recent_files_with_suffixes(sections_dir, LATEX_SUFFIXES, freshness_cutoff):
                problems.append(
                    f"{stage.stage_title} requires section .tex files produced or updated during the current stage execution."
                )

    if stage.number >= 8:
        review_files = _existing_files(paths.reviews_dir)
        if not review_files:
            problems.append(
                f"{stage.stage_title} requires review/readiness artifacts under workspace/reviews."
            )
        elif freshness_cutoff is not None and not any(path.stat().st_mtime >= freshness_cutoff for path in review_files):
            problems.append(
                f"{stage.stage_title} requires review/readiness artifacts produced or updated during the current stage execution."
            )

    return problems


def render_approved_stage_entry(stage: StageSpec, stage_markdown: str) -> str:
    objective = extract_markdown_section(stage_markdown, "Objective") or "Not provided."
    what_i_did = extract_markdown_section(stage_markdown, "What I Did") or "Not provided."
    key_results = extract_markdown_section(stage_markdown, "Key Results") or "Not provided."
    files_produced = extract_markdown_section(stage_markdown, "Files Produced") or "Not provided."

    return (
        f"### {stage.stage_title}\n\n"
        "#### Objective\n"
        f"{objective}\n\n"
        "#### What I Did\n"
        f"{what_i_did}\n\n"
        "#### Key Results\n"
        f"{key_results}\n\n"
        "#### Files Produced\n"
        f"{files_produced}"
    )


def build_memory_text(
    user_goal: str,
    approved_entries: list[str],
    intake_summary: str | None = None,
) -> str:
    approved_block = "\n\n".join(entry.strip() for entry in approved_entries if entry.strip())
    if not approved_block:
        approved_block = "_None yet._"
    parts = [
        "# Approved Run Memory\n",
        "## Original User Goal\n"
        f"{(user_goal or '').strip()}\n",
    ]
    if intake_summary:
        parts.append(
            "## Intake Resources and Clarifications\n"
            f"{intake_summary.strip()}\n"
        )
    parts.append(
        "## Approved Stage Summaries\n\n"
        f"{approved_block}\n"
    )
    return "\n".join(parts)


def approved_stage_entries(memory_text: str) -> list[tuple[int, str]]:
    summaries = approved_stage_summaries(memory_text)
    if summaries == "None yet.":
        return []

    matches = list(APPROVED_STAGE_ENTRY_PATTERN.finditer(summaries))
    if not matches:
        return []

    entries: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(summaries)
        entries.append((int(match.group(1)), summaries[start:end].strip()))
    return entries


def approved_stage_numbers(memory_text: str) -> set[int]:
    return {number for number, _ in approved_stage_entries(memory_text)}


def filtered_approved_memory(memory_text: str, max_stage_number: int) -> str:
    user_goal = extract_markdown_section(memory_text, "Original User Goal") or ""
    intake_summary = extract_markdown_section(memory_text, "Intake Resources and Clarifications")
    kept_entries = [
        entry
        for number, entry in approved_stage_entries(memory_text)
        if number <= max_stage_number
    ]
    return build_memory_text(user_goal, kept_entries, intake_summary=intake_summary)


def append_approved_stage_summary(memory_path: Path, stage: StageSpec, stage_markdown: str) -> None:
    if stage.number < 0:
        raise ValueError(f"Cannot append pseudo-stage {stage.slug} to approved memory.")
    current = read_text(memory_path)
    user_goal = extract_markdown_section(current, "Original User Goal") or ""
    intake_summary = extract_markdown_section(current, "Intake Resources and Clarifications")
    retained_entries = [
        entry
        for number, entry in approved_stage_entries(current)
        if number < stage.number
    ]
    retained_entries.append(render_approved_stage_entry(stage, stage_markdown))
    write_text(memory_path, build_memory_text(user_goal, retained_entries, intake_summary=intake_summary))


#: Names under ``stages/`` that are not a stage's summary. ``.tmp.md`` is the draft under
#: review; ``.skip_stub.md`` is the audit record kept beside a *rescued* draft, saying the
#: stage was auto-skipped. Both sit in the same directory as the summary and both end in
#: ``.md``, so every reader that globs ``*.md`` has to exclude them or ship them as content.
NON_SUMMARY_STAGE_SUFFIXES = (".tmp.md", ".skip_stub.md")


def stage_summary_files(paths: RunPaths) -> list[Path]:
    """Every stage summary under ``stages/``, and nothing else.

    One function because two readers globbed this directory with different filters and both
    were wrong the same way. ``.skip_stub.md`` is written only when a stage ran out of
    attempts *and* its last draft passed both gates: the draft is promoted to the summary
    and the stub is kept next to it for the audit trail. A reader that takes both gets the
    stage's real research and, immediately after it, a section reading "This stage was
    skipped (auto) and its work was never done" -- about the work sitting above it.
    """
    if not paths.stages_dir.exists():
        return []
    return sorted(
        path
        for path in paths.stages_dir.glob("*.md")
        if not path.name.endswith(NON_SUMMARY_STAGE_SUFFIXES)
    )


def approved_stage_summaries(memory_text: str) -> str:
    marker = "## Approved Stage Summaries"
    if marker not in memory_text:
        return "None yet."
    content = memory_text.split(marker, 1)[1].strip()
    if not content or content == "_None yet._":
        return "None yet."
    return content


def _extract_loose_list_items(section_text: str) -> list[str]:
    items: list[str] = []

    for raw_line in section_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue

        numbered_match = re.match(r"^\d+\.\s+(.*)$", stripped)
        if numbered_match:
            items.append(numbered_match.group(1).strip())
            continue

        bullet_match = re.match(r"^[-*]\s+(.*)$", stripped)
        if bullet_match:
            items.append(bullet_match.group(1).strip())

    return items


def extract_path_references(text: str) -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []

    for candidate in re.findall(r"`([^`]+)`", text):
        normalized = candidate.strip()
        if not normalized or "/" not in normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        paths.append(normalized)

    return paths


def write_stage_handoff(paths: RunPaths, stage: StageSpec, stage_markdown: str) -> Path:
    handoff_path = paths.handoff_dir / f"{stage.slug}.md"
    objective = extract_markdown_section(stage_markdown, "Objective") or "Not provided."
    key_results = extract_markdown_section(stage_markdown, "Key Results") or "Not provided."
    files_produced = extract_markdown_section(stage_markdown, "Files Produced") or "Not provided."
    decision_ledger = extract_markdown_section(stage_markdown, "Decision Ledger")
    parts = [
        f"# Handoff: {stage.stage_title}\n\n"
        "## Objective\n"
        f"{objective}\n\n"
        "## Key Results\n"
        f"{key_results}\n\n"
        "## Files Produced\n"
        f"{files_produced}\n",
    ]
    if decision_ledger:
        parts.append(
            "\n## Decision Ledger\n"
            f"{decision_ledger}\n"
        )
    write_text(handoff_path, "".join(parts))
    return handoff_path


def build_handoff_context(paths: RunPaths, upto_stage: StageSpec | None = None, max_stages: int = 4) -> str:
    handoffs = sorted(path for path in paths.handoff_dir.glob("*.md") if path.is_file())
    if upto_stage is not None:
        handoffs = [path for path in handoffs if path.stem < upto_stage.slug]
    handoffs = handoffs[-max_stages:]
    parts = [
        strip_markdown_section(read_text(path).strip(), "Decision Ledger")
        for path in handoffs
        if path.exists()
    ]
    return "\n\n".join(parts).strip() or "No stage handoff summaries available yet."


def extract_typed_hypothesis_sections(stage_markdown: str) -> dict[str, str]:
    key_results = extract_markdown_section(stage_markdown, "Key Results")
    if not key_results:
        return {}

    pattern = re.compile(
        r"^### (Theoretical Propositions|Empirical Hypotheses|Paper Claims \(Provisional\))\s*$\n?(.*?)(?=^### |\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    sections: dict[str, str] = {}
    for match in pattern.finditer(key_results):
        heading = match.group(1).strip()
        body = match.group(2).strip()
        if body:
            sections[heading] = body
    return sections


def extract_hypothesis_context(stage_markdown: str) -> str | None:
    sections = extract_typed_hypothesis_sections(stage_markdown)
    if not sections:
        return None

    parts = [
        f"### {heading}\n{sections[heading]}"
        for heading in TYPED_HYPOTHESIS_HEADINGS
        if heading in sections
    ]
    return "\n\n".join(parts) if parts else None


def build_hypothesis_context(paths: RunPaths) -> str | None:
    from .hypothesis_manifest import format_hypothesis_manifest_for_prompt, load_hypothesis_manifest

    manifest = load_hypothesis_manifest(paths.hypothesis_manifest)
    if manifest is not None:
        return format_hypothesis_manifest_for_prompt(manifest)

    stage_02_handoff = paths.handoff_dir / "02_hypothesis_generation.md"
    if not stage_02_handoff.exists():
        return None
    return extract_hypothesis_context(read_text(stage_02_handoff))


def build_decision_ledger_context(paths: RunPaths, upto_stage: StageSpec | None = None) -> str | None:
    """Collect Decision Ledger sections from all approved handoff files."""
    handoffs = sorted(path for path in paths.handoff_dir.glob("*.md") if path.is_file())
    if upto_stage is not None:
        handoffs = [path for path in handoffs if path.stem < upto_stage.slug]

    entries: list[str] = []
    for handoff_path in handoffs:
        content = read_text(handoff_path)
        ledger = extract_markdown_section(content, "Decision Ledger")
        if ledger:
            # Extract stage name from the handoff heading
            stage_name = handoff_path.stem.replace("_", " ").title()
            for line in content.splitlines():
                if line.startswith("# Handoff:"):
                    stage_name = line.removeprefix("# Handoff:").strip()
                    break
            entries.append(f"### {stage_name}\n{ledger}")

    if not entries:
        return None
    return "\n\n".join(entries)


#: Directory roots a run-relative path can start with. A backticked span beginning with
#: one of these is a path reference even without a file extension, because a stage may
#: legitimately point at a directory.
PATH_ROOT_PREFIXES = (
    "./", "../", "/",
    "workspace/", "stages/", "prompt_cache/", "operator_state/", "handoff/",
    "literature/", "code/", "data/", "results/", "figures/", "writing/",
    "artifacts/", "notes/", "reviews/", "outputs/", "report/", "src/", "tests/", "docs/",
)

#: A trailing `.ext` on the final segment. The bound rules out `p(a*|M, mu, 1/f)`, whose
#: last segment ends in `f)` rather than an extension.
_FILE_EXTENSION_RE = re.compile(r"\.[A-Za-z0-9_+-]{1,12}$")

#: Characters that appear in mathematics and prose but not in a path AutoR would write.
#: Whitespace is the strongest of these: `tau_SR < tau_BH / ln(N)` is an inequality.
_NOT_IN_A_PATH_RE = re.compile(r"[\s<>|=^≤≥±→,;]")


def looks_like_path_reference(candidate: str) -> bool:
    """Whether a backticked span is a file path rather than mathematics.

    The old rule was "contains a slash", which counted `1/f`, `alpha/l ≤ 1/2`,
    `p(a*|M, mu, 1/f)` and the GitHub slug `sebhoof/bhsr` as paths. That matters twice
    over: `Files Produced` validation demands every listed path exist, and the rubric's
    grounding criterion scores the fraction that resolve — so inline mathematics silently
    drove the score down, and the cheapest way for a stage to recover the points was to
    stop writing mathematics in backticks. A measurement that rewards mangling the prose
    is worse than no measurement.

    Accepted when the span has no path-hostile character and either starts at a known
    run-relative root or ends in a file extension.
    """
    if _NOT_IN_A_PATH_RE.search(candidate):
        return False
    if "/" not in candidate:
        return False
    if candidate.startswith(PATH_ROOT_PREFIXES):
        return True
    # A DOI (`10.1103/PhysRevD.83.044026`) or a URL (`arxiv.org/abs/2309.17453`) has a
    # slash and an extension-shaped tail, and a literature survey is full of both. The
    # tell is a dot in the segment before the first slash, which no run-relative path
    # AutoR writes has.
    first_segment = candidate.split("/", 1)[0]
    if "." in first_segment or "://" in candidate:
        return False
    return bool(_FILE_EXTENSION_RE.search(candidate.rstrip("/").rsplit("/", 1)[-1]))


def _extract_path_references(text: str) -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []

    for candidate in re.findall(r"`([^`\n\r]+)`", text):
        normalized = candidate.strip()
        if not normalized:
            continue

        # Reject multi-line or excessively long strings — not valid file paths
        if "\n" in normalized or "\r" in normalized or len(normalized) > 512:
            continue

        if not looks_like_path_reference(normalized):
            continue

        if normalized in seen:
            continue

        seen.add(normalized)
        paths.append(normalized)

    return paths


#: Characters that make a "Files Produced" entry a pattern rather than a literal path.
PATTERN_CHARS = ("*", "?", "[", "{")


def expand_braces(pattern: str) -> list[str]:
    """Expand ``a{b,c}d`` into ``[abd, acd]``, recursively.

    A stage that produced four files naturally writes
    ``text/paper_00{0,1,2,3}.txt`` rather than four lines. :mod:`glob` does not
    understand braces, so without this the entry is treated as one literal
    filename that cannot exist.
    """
    open_at = pattern.find("{")
    if open_at == -1:
        return [pattern]

    depth = 0
    for index in range(open_at, len(pattern)):
        if pattern[index] == "{":
            depth += 1
        elif pattern[index] == "}":
            depth -= 1
            if depth == 0:
                close_at = index
                break
    else:
        return [pattern]  # unbalanced; treat literally rather than guessing

    prefix, body, suffix = pattern[:open_at], pattern[open_at + 1:close_at], pattern[close_at + 1:]
    options, depth, current = [], 0, ""
    for char in body:
        if char == "," and depth == 0:
            options.append(current)
            current = ""
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        current += char
    options.append(current)

    expanded: list[str] = []
    for option in options:
        for tail in expand_braces(suffix):
            expanded.extend(expand_braces(prefix + option + tail))
    return expanded


def _pattern_matches_under(root: Path, pattern: str) -> bool:
    """True when at least one real file matches *pattern* beneath *root*."""
    for candidate in expand_braces(pattern):
        if any(char in candidate for char in ("*", "?", "[")):
            try:
                if any(root.glob(candidate)):
                    return True
            except (OSError, ValueError, IndexError):
                continue
        elif (root / candidate).exists():
            return True
    return False


def _listed_file_exists(
    run_root: Path,
    listed_path: str,
    extra_roots: "Sequence[Path] | None" = None,
) -> bool:
    """Check whether a file referenced in a stage's "Files Produced" section
    actually exists on disk.

    Stages may legitimately reference files using either of two relative
    base paths:

    1. **Run-root-relative** — e.g. ``workspace/code/run_ablation.py``. This
       is the canonical form the rest of AutoR uses internally.
    2. **Workspace-relative** — e.g. ``code/run_ablation.py``. This is the
       natural form an LLM (or a human) reaches for when describing files
       inside the workspace, since the project's "current directory" while
       the stage runs is effectively ``workspace/``.

    3. **Relative to an extra artifact root** — a run may legitimately write
       outside the run tree. A ResearchClawBench run is told to keep
       ``code/``, ``outputs/`` and ``report/images/`` up to date inside the
       *benchmark workspace*, which is the parent of the run root, so a stage
       that complies and then lists ``outputs/metrics.csv`` is describing a
       real file the first two roots cannot see.

    An entry containing ``*``, ``?``, ``[`` or ``{`` is treated as a **pattern**
    rather than a literal name, and matches when at least one real file matches
    it. A stage that produced four papers writes
    ``text/paper_00{0,1,2,3}.txt`` or ``text/paper_00*.txt`` rather than four
    lines; read literally, those are filenames that cannot exist, and the stage
    is failed for artifacts it genuinely produced. A pattern matching nothing
    still fails, so the gate keeps its teeth.

    We accept all of them. Absolute paths are honored as-is. Each fallback is
    strictly additive — every path that validated before still validates — so
    existing CLI runs are not affected.
    """
    candidate = Path(listed_path)
    is_pattern = any(char in listed_path for char in PATTERN_CHARS)
    try:
        if candidate.is_absolute():
            if not is_pattern:
                return candidate.exists()
            anchor = Path(candidate.anchor)
            return _pattern_matches_under(anchor, str(candidate.relative_to(anchor)))

        roots = [
            run_root,                    # 1. Run-root-relative (canonical AutoR form)
            run_root / "workspace",      # 2. Workspace-relative fallback
            *(extra_roots or ()),        # 3. Extra artifact roots (e.g. a benchmark workspace)
        ]
        for root in roots:
            if is_pattern:
                if _pattern_matches_under(root, listed_path):
                    return True
            elif (root / candidate).exists():
                return True
    except OSError:
        return False
    return False


def _existing_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return [path for path in directory.rglob("*") if path.is_file()]


def _count_files_with_suffixes(directory: Path, suffixes: set[str]) -> int:
    return sum(1 for path in _existing_files(directory) if path.suffix.lower() in suffixes)


def _has_recent_files_with_suffixes(directory: Path, suffixes: set[str], cutoff_timestamp: float) -> bool:
    return any(
        path.suffix.lower() in suffixes and path.stat().st_mtime >= cutoff_timestamp
        for path in _existing_files(directory)
    )


def _count_non_markdown_files(directory: Path) -> int:
    return sum(1 for path in _existing_files(directory) if path.suffix.lower() not in {".md", ".txt"})


def _polish_count_path(paths: RunPaths, stage: StageSpec) -> Path:
    return paths.operator_state_dir / f"{stage.slug}.polish_count.txt"


def read_polish_count(paths: RunPaths, stage: StageSpec) -> int:
    """Improvement rounds this stage has spent, across every entry into it.

    Persisted for the same reason the attempt count is: a stage can be entered more
    than once — a resume, a rollback, a graph revisit — and the attempt number keeps
    counting up across all of them. Subtracting a per-entry polish counter from a
    run-wide attempt number would under-report retries on the second visit, which is
    exactly the number the fake-pipeline gate reads to notice an artifact gate that
    fake mode cannot clear.
    """
    path = _polish_count_path(paths, stage)
    if not path.exists():
        return 0
    text = read_text(path).strip()
    return int(text) if text.isdigit() else 0


def write_polish_count(paths: RunPaths, stage: StageSpec, count: int) -> None:
    write_text(_polish_count_path(paths, stage), str(count))


def read_attempt_count(paths: RunPaths, stage: StageSpec) -> int:
    path = paths.operator_state_dir / f"{stage.slug}.attempt_count.txt"
    if path.exists():
        text = read_text(path).strip()
        if text.isdigit():
            return int(text)
    return 0


def write_attempt_count(paths: RunPaths, stage: StageSpec, count: int) -> None:
    path = paths.operator_state_dir / f"{stage.slug}.attempt_count.txt"
    write_text(path, str(count))


def _load_template_registry() -> dict[str, dict[str, str]]:
    if not TEMPLATE_REGISTRY_PATH.exists():
        return {}

    registry: dict[str, dict[str, str]] = {}
    current_venue: str | None = None

    for raw_line in TEMPLATE_REGISTRY_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            continue

        if not line.startswith(" ") and stripped.endswith(":"):
            current_venue = stripped[:-1]
            registry[current_venue] = {}
            continue

        if current_venue and line.startswith("  ") and ":" in stripped:
            key, value = stripped.split(":", 1)
            registry[current_venue][key.strip()] = value.strip().strip('"').strip("'")

    return registry


def _normalize_marker(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _supported_manuscript_markers() -> set[str]:
    markers: set[str] = set()
    registry = _load_template_registry()

    for venue_id, metadata in registry.items():
        markers.add(_normalize_marker(venue_id))
        display_name = metadata.get("display_name", "")
        style_package = metadata.get("style_package", "")

        if display_name:
            markers.add(_normalize_marker(display_name))
        if style_package:
            markers.add(_normalize_marker(style_package))

    return {marker for marker in markers if marker}


def _extract_explicit_venue_marker(tex_text: str) -> str | None:
    match = re.search(r"autor\s+venue\s*:\s*([a-zA-Z0-9_.-]+)", tex_text, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip().lower()


def resolve_venue_key(value: str | None) -> str:
    registry = _load_template_registry()
    if not value:
        return DEFAULT_VENUE

    candidate = value.strip()
    if not candidate:
        return DEFAULT_VENUE

    if candidate in registry:
        return candidate

    normalized = _normalize_marker(candidate)
    for venue_id, metadata in registry.items():
        aliases = {
            _normalize_marker(venue_id),
            _normalize_marker(metadata.get("display_name", "")),
            _normalize_marker(metadata.get("style_package", "")),
        }
        if normalized in aliases:
            return venue_id

    raise ValueError(f"Unknown venue: {value}")


def mark_stage_execution_started(paths: RunPaths, stage: StageSpec) -> None:
    write_text(paths.stage_execution_marker_file(stage), datetime.now().isoformat(timespec="seconds"))


def stage_execution_started_at(paths: RunPaths, stage: StageSpec) -> float | None:
    marker = paths.stage_execution_marker_file(stage)
    if not marker.exists():
        return None
    return marker.stat().st_mtime


def _markers_for_venue(venue_key: str) -> set[str]:
    registry = _load_template_registry()
    metadata = registry.get(venue_key, {})
    markers = {
        _normalize_marker(venue_key),
        _normalize_marker(metadata.get("display_name", "")),
        _normalize_marker(metadata.get("style_package", "")),
    }
    return {marker for marker in markers if marker}


def _looks_like_supported_manuscript(main_tex: Path, expected_venue: str | None = None) -> bool:
    text = read_text(main_tex)
    explicit_venue = _extract_explicit_venue_marker(text)
    if explicit_venue:
        try:
            explicit_venue = resolve_venue_key(explicit_venue)
        except ValueError:
            explicit_venue = None

    if expected_venue:
        try:
            expected_venue = resolve_venue_key(expected_venue)
        except ValueError:
            expected_venue = DEFAULT_VENUE
    else:
        expected_venue = DEFAULT_VENUE

    if explicit_venue and explicit_venue == expected_venue:
        return True

    normalized_text = _normalize_marker(text)
    for marker in _markers_for_venue(expected_venue):
        if marker and marker in normalized_text:
            return True

    if explicit_venue:
        return explicit_venue == expected_venue

    return False


def _has_inline_bibliography(writing_dir: Path) -> bool:
    bibliography_patterns = (
        r"\\begin\{thebibliography\}",
        r"\\bibliography\{",
        r"\\printbibliography\b",
    )

    for path in _existing_files(writing_dir):
        if path.suffix.lower() != ".tex":
            continue
        text = read_text(path)
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in bibliography_patterns):
            return True

    return False


def canonicalize_stage_markdown(
    stage: StageSpec,
    memory_text: str,
    markdown: str,
    fallback_text: str = "",
    stage_output_path: str | None = None,
) -> str:
    objective = (
        extract_markdown_section(markdown, "Objective")
        or f"Complete {stage.stage_title} and capture the main objective, work performed, results, and produced artifacts."
    )


    what_i_did = extract_markdown_section(markdown, "What I Did")
    if not what_i_did:
        what_i_did = (
            "This stage summary was normalized locally because the Claude-generated markdown was incomplete. "
            "Review the current workspace artifacts and captured terminal output before approval."
        )

    key_results = extract_markdown_section(markdown, "Key Results")
    if not key_results:
        fallback_excerpt = truncate_text(fallback_text, max_chars=1600) if fallback_text.strip() else ""
        key_results = (
            "The original stage output was incomplete, so this file was normalized locally to preserve workflow continuity."
        )
        if fallback_excerpt:
            key_results += (
                "\n\nRecovered execution context (truncated):\n"
                f"```\n{fallback_excerpt}\n```"
            )

    files_produced = extract_markdown_section(markdown, "Files Produced")
    if not files_produced:
        file_refs = _extract_path_references(markdown + "\n" + fallback_text)
        stage_path = stage_output_path or f"stages/{stage.filename}"
        if stage_path not in file_refs:
            file_refs.insert(0, stage_path)
        files_produced = "\n".join(f"- `{path}`" for path in file_refs[:12]) if file_refs else f"- `{stage_path}`"

    suggestions_section = extract_markdown_section(markdown, "Suggestions for Refinement") or ""
    numbered_suggestions = parse_numbered_list(suggestions_section)
    suggestion_items = [numbered_suggestions[key] for key in sorted(numbered_suggestions)] if numbered_suggestions else []
    if not suggestion_items:
        suggestion_items = _extract_loose_list_items(suggestions_section)
    if not suggestion_items:
        suggestion_items = list(DEFAULT_REFINEMENT_SUGGESTIONS)

    for default_suggestion in DEFAULT_REFINEMENT_SUGGESTIONS:
        if len(suggestion_items) >= 3:
            break
        if default_suggestion not in suggestion_items:
            suggestion_items.append(default_suggestion)

    suggestion_items = suggestion_items[:3]

    decision_ledger = extract_markdown_section(markdown, "Decision Ledger")
    if not decision_ledger:
        decision_ledger = (
            "### Open Questions\n\n_None identified._\n\n"
            "### Locked Decisions\n\n_None yet._\n\n"
            "### Assumptions\n\n_None yet._\n\n"
            "### Rejected Alternatives\n\n_None yet._"
        )

    return (
        f"# Stage {stage.number:02d}: {stage.display_name}\n\n"
        "## Objective\n\n"
        f"{objective.strip()}\n\n"
        "## What I Did\n\n"
        f"{what_i_did.strip()}\n\n"
        "## Key Results\n\n"
        f"{key_results.strip()}\n\n"
        "## Files Produced\n\n"
        f"{files_produced.strip()}\n\n"
        "## Decision Ledger\n\n"
        f"{decision_ledger.strip()}\n\n"
        "## Suggestions for Refinement\n"
        f"1. {suggestion_items[0].strip()}\n"
        f"2. {suggestion_items[1].strip()}\n"
        f"3. {suggestion_items[2].strip()}\n\n"
        "## Your Options\n"
        + "\n".join(FIXED_STAGE_OPTIONS)
        + "\n"
    )


def extract_stream_text_fragments(payload: Any) -> list[str]:
    fragments: list[str] = []

    if isinstance(payload, dict):
        for key, value in payload.items():
            key_lower = key.lower()
            if isinstance(value, str) and key_lower in {
                "text",
                "content",
                "message",
                "delta",
                "summary",
                "result",
            }:
                text = value.strip()
                if text:
                    fragments.append(text)
            else:
                fragments.extend(extract_stream_text_fragments(value))
    elif isinstance(payload, list):
        for item in payload:
            fragments.extend(extract_stream_text_fragments(item))

    return fragments


def relative_to_run(path: Path, run_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(run_root.resolve()))
    except ValueError:
        return str(path.resolve())
