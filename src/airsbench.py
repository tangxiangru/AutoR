"""AIRS-Bench adapter: run AutoR as an unattended AIRS-Bench agent.

`AIRS-Bench <https://github.com/facebookresearch/airs-bench>`_ is the third benchmark
AutoR is wired to, and it measures a different thing from the other two. ResearchClawBench
scores a *report* with a model judge and FIRE-Bench scores a *conclusion* claim by claim --
both through a model reading what the run wrote. AIRS-Bench scores a *file of predictions*
with ``scipy``. There is no judge, no rubric and no prose anywhere in the loop: twenty
tasks, each a ``<problem, dataset, metric>`` triplet with a SOTA value from a published
paper, and the whole of a run's score is what ``submission.csv`` gets on the held-out
split.

Three things have to be bridged for AutoR to run in it:

1. **No human, same as ResearchClawBench.** The approval gate becomes the reviewer agent
   and every terminal prompt becomes a hard error. :mod:`src.rcb` already did this work;
   this module reuses its event stream and run-directory convention verbatim.
2. **A different deliverable.** AutoR's stage contract is built around a report and its
   figures. Here the report is worth exactly zero and ``submission.csv`` is worth
   everything. :func:`export_submission` performs the translation, and it is deliberately
   the *only* place a submission can come from — it never writes one, and a run that
   produced no predictions is recorded as having produced none.
3. **A benchmark that owns its own data pipeline.** Each task ships ``prepare.py``,
   ``evaluate_prepare.py`` and ``evaluate.py``. AutoR does not reimplement any of them:
   :func:`prepare_workspace` and :func:`score_submission` shell out to the benchmark's own
   scripts, so the number this adapter reports is the number the benchmark computes.

**What this adapter deliberately does not tell the agent.** ``metadata.yaml`` carries the
SOTA score, the estimated worst score and the optimal score for every task, because the
normalized score needs all three. ``project_description.md`` — the file the benchmark
hands its own agents — carries none of them. :func:`build_airs_goal` therefore composes
the goal out of the description and the workspace contract only, and
``tests/test_airsbench.py`` asserts that none of the three numbers appears in it. An
adapter that quietly handed the agent the target it is being measured against would
produce a number that means nothing next to the published leaderboard.

The normalized score itself is reproduced from the benchmark's README rather than
approximated:

.. math::

    NS_t^a = \\frac{\\phi_t(s_t^a) - \\phi_t(s_t^{min})}{\\phi_t(s_t^{sota}) - \\phi_t(s_t^{min})},
    \\qquad \\phi_t(s) = -\\log_{10}(|s - s_t^{opt}|)

so a task's score is comparable with the fourteen agents in the published table, subject to
the usual caveats about model and seed count that :mod:`tools.score_airs_run` prints.
"""

from __future__ import annotations

import csv
import json
import math
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .rcb import AUTOR_RUNS_DIRNAME, emit_event  # noqa: F401 - emit_event is re-exported on purpose
from .utils import (
    TASK_BEGIN_MARKER,
    TASK_END_MARKER,
    RunPaths,
    build_run_paths,
    code_version,
    read_text,
    write_text,
)


#: Where the ``aira-dojo``-shaped task specifications live inside an airs-bench checkout.
#: The ``mlgym`` tree beside it is a *conversion* of these, produced by the benchmark's own
#: ``scripts/converter_rad_mlgym_enhanced.py``, so ``rad`` is the source of truth and the
#: only tree this adapter reads.
RAD_TASKS_RELPATH = ("airsbench", "tasks", "rad")

#: The five files a task specification is made of. ``utils.py``, ``custom_labels.py`` and
#: ``testing_util.py`` are optional helpers some tasks add beside them.
TASK_SPEC_FILES = ("metadata.yaml", "project_description.md", "prepare.py", "evaluate.py", "evaluate_prepare.py")

#: Directories the adapter creates inside a task workspace. ``data/`` is what the
#: benchmark's own ``prepare.py`` writes into and is the agent's only view of the dataset;
#: the rest exist so the goal contract has somewhere to point.
AIRS_WORKSPACE_DIRS = ("data", "code", "outputs", "logs")

#: The scored artifact. Every one of the twenty shipped tasks declares exactly this in its
#: ``file_export_globs``; :func:`load_task` refuses a task that declares something else
#: rather than silently exporting the wrong file.
SUBMISSION_NAME = "submission.csv"

#: Run-tree locations searched for a submission the agent wrote somewhere other than the
#: contract path, best first. A submission at the contract path always wins.
SUBMISSION_FALLBACK_DIRS = ("results", "code", "artifacts", "data")

#: ``evaluate.py`` prints this line and then a JSON object. Matched rather than assumed:
#: :func:`parse_evaluation_output` falls back to the last JSON object in the stream, because
#: a task is free to print its own banner and two of the twenty already print extra lines
#: after the result.
EVALUATION_BANNER = "--- EVALUATION RESULT ---"

#: Written into a workspace by :func:`prepare_workspace`: what the benchmark's own
#: ``prepare.py`` actually produced, as opposed to what the task description says it
#: produces. A dotfile, so it does not show up in the agent's view of its own workspace as
#: something to act on.
PREPARED_MARKER_NAME = ".airs_prepared.json"

#: What ``|s - s_opt|`` becomes when a submission hits the optimum exactly, which would
#: otherwise send :math:`\\phi` to infinity. **Not a choice**: the benchmark's own
#: ``normalize_score_log`` in ``notebooks/create_summary_plots.ipynb`` substitutes
#: ``|0.999 - optimal|`` in that case, so a perfect score on a higher-is-better task
#: transforms as ``-log10(0.001) = 3`` rather than as infinity. An earlier version of this
#: adapter used a 1e-12 floor, which would have reported 12 where the benchmark reports 3.
#: No run has hit an optimum, so nothing measured here changes; the number that would be
#: reported if one did is now the benchmark's.
PHI_OPTIMUM_SUBSTITUTE = 0.999

#: Value ``normalize_score_log`` substitutes for a non-finite normalized score.
PHI_INFINITY_SUBSTITUTE = 100.0


# ---------------------------------------------------------------------------
# metadata.yaml
# ---------------------------------------------------------------------------


class MetadataError(ValueError):
    """A task's ``metadata.yaml`` is missing, unparseable, or missing a field we need."""


def parse_simple_yaml(text: str) -> Any:
    """Parse the subset of YAML the twenty shipped ``metadata.yaml`` files use.

    AutoR's test suite runs with no third-party dependency, and ``PyYAML`` is not one of
    them. Rather than making the adapter's core conditional on an optional import — which
    is two code paths and therefore two behaviours — this parses the subset directly:
    block mappings, block sequences of scalars, block sequences of mappings, and scalars
    that are quoted strings, integers, floats, booleans, nulls or bare text.

    That is not general YAML and does not try to be. What keeps it honest is
    ``tests/test_airsbench.py``, which parses every shipped ``metadata.yaml`` with this
    function *and* with ``PyYAML`` when it is importable and asserts the two agree. A
    format change upstream fails a test rather than producing a plausible wrong task.
    """
    root: dict[str, Any] = {}
    # (indent, container). A container is a dict, a list, or a _PendingBlock -- a key
    # whose block has been opened but whose kind the next line decides.
    stack: list[list[Any]] = [[-1, root]]

    for raw_line in text.splitlines():
        line = raw_line.split(" #", 1)[0].rstrip() if " #" in raw_line else raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        body = line.strip()

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        frame = stack[-1]

        if body.startswith("- ") or body == "-":
            item = body[2:].strip()
            sequence = _as_sequence(frame, raw_line)
            if _SEQUENCE_MAPPING.match(item):
                # A sequence of mappings: the first key sits on the dash line, and the
                # dash and its space count as part of the child mapping's indentation.
                entry: dict[str, Any] = {}
                sequence.append(entry)
                child: list[Any] = [indent + 1, entry]
                stack.append(child)
                _assign(entry, item, stack, indent + 2)
            else:
                sequence.append(_scalar(item))
            continue

        _assign(_as_mapping(frame, raw_line), body, stack, indent)

    return root


#: A ``- key: value`` line, as opposed to a scalar that happens to contain a colon. Every
#: mapping key in the shipped metadata is a plain identifier, so requiring one keeps
#: ``- https://example.com/x`` a string rather than a one-key mapping.
_SEQUENCE_MAPPING = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*\s*:(\s|$)")


class _PendingBlock:
    """A key whose block has been opened but whose kind is not known yet.

    ``sota:`` is followed by ``  - sota_paper_title: ...`` and becomes a list;
    ``logging_info:`` is followed by ``  name: ...`` and becomes a mapping. The two are
    indistinguishable on the line that opens them, so the container is created by the
    first child line and written into its parent at that moment.
    """

    __slots__ = ("parent", "key")

    def __init__(self, parent: dict[str, Any], key: str) -> None:
        self.parent = parent
        self.key = key

    def materialize(self, empty: Any) -> Any:
        existing = self.parent.get(self.key)
        if existing is None:
            self.parent[self.key] = empty
            return empty
        if type(existing) is not type(empty):
            raise MetadataError(f"{self.key!r} received both mapping and sequence children")
        return existing


def _as_sequence(frame: list[Any], raw_line: str) -> list[Any]:
    """Resolve *frame*'s container to the list this ``- `` line belongs to."""
    container = frame[1]
    if isinstance(container, _PendingBlock):
        container = container.materialize([])
        frame[1] = container
    if not isinstance(container, list):
        raise MetadataError(f"sequence item outside a sequence: {raw_line!r}")
    return container


def _as_mapping(frame: list[Any], raw_line: str) -> dict[str, Any]:
    """Resolve *frame*'s container to the mapping this ``key:`` line belongs to."""
    container = frame[1]
    if isinstance(container, _PendingBlock):
        container = container.materialize({})
        frame[1] = container
    if not isinstance(container, dict):
        raise MetadataError(f"mapping key inside a sequence: {raw_line!r}")
    return container


def _assign(container: dict[str, Any], body: str, stack: list[list[Any]], indent: int) -> None:
    if ":" not in body:
        raise MetadataError(f"not a mapping entry: {body!r}")
    key, _, rest = body.partition(":")
    key = key.strip()
    rest = rest.strip()
    if rest:
        container[key] = _scalar(rest)
        return
    # An empty value opens a block whose kind the next line decides.
    stack.append([indent, _PendingBlock(container, key)])


def _scalar(text: str) -> Any:
    value = text.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        # Flow sequence. Two of the twenty write ``shape`` this way and eighteen write it
        # as a string, so a parser that returned the brackets verbatim would hand two
        # tasks a different type for the same field.
        inner = value[1:-1].strip()
        return [_scalar(part) for part in inner.split(",")] if inner else []
    lowered = value.casefold()
    if lowered in {"null", "~", ""}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AirsTask:
    """One AIRS-Bench task, read off its own specification files."""

    name: str
    task_dir: Path
    description: str
    #: Metric name as ``metadata.yaml`` records it. The key ``evaluate.py`` prints is
    #: usually but not always the same string, so scoring reads the printed key rather
    #: than assuming this one.
    metric: str
    dataset: str
    config: str
    #: Path under the shared raw-data directory that this task's ``prepare.py`` reads,
    #: extracted from the script rather than composed from ``dataset``/``config``. It
    #: happens to equal ``<dataset>/<config>`` for all twenty today, and it is still read
    #: from the script: the script is what has to find the data, and the two fields are a
    #: description of it. The path is also not always one ``os.path.join`` argument -- two
    #: tasks pass the dataset and the config separately -- which is what
    #: :data:`_RAW_PATH_PATTERN` is shaped around.
    raw_relpath: str
    lower_is_better: bool
    optimal_score: float
    worst_score: float
    sota_score: float
    #: Rows the task's own ``metadata.yaml`` and ``project_description.md`` *claim* the
    #: submission must have, from ``logging_info.shape``. A claim, not a measurement, and
    #: on at least one shipped task it is wrong: ``CoreferenceResolutionWinograndeAccuracy``
    #: says ``(1531, 1)`` while its ``prepare.py`` hands the agent the 1,267-row validation
    #: split and its ``evaluate.py`` scores against that. An agent that believes the
    #: description scores nothing. So this is never the number a submission is checked
    #: against when the prepared split can be measured -- see :func:`expected_rows_for`.
    #: ``None`` when the shape is not readable as a row count.
    declared_rows: int | None
    scoring_column: str
    category: str
    research_problem: str
    requirements: tuple[str, ...] = ()
    eval_requirements: tuple[str, ...] = ()

    def phi(self, score: float) -> float:
        """The benchmark's non-linear transform :math:`-\\log_{10}(|s - s^{opt}|)`.

        The exact-optimum case follows ``normalize_score_log`` rather than a floor of our
        own: see :data:`PHI_OPTIMUM_SUBSTITUTE`.
        """
        difference = abs(score - self.optimal_score)
        if difference == 0:
            difference = abs(PHI_OPTIMUM_SUBSTITUTE - self.optimal_score)
        return -math.log10(difference)

    def normalized(self, score: float) -> float:
        """The raw ratio, before the benchmark's clip. Use :meth:`reported` to report.

        Kept unclipped because a score below the estimated worst is real information about
        a run, and the clip destroys it. It is not what the benchmark publishes.
        """
        denominator = self.phi(self.sota_score) - self.phi(self.worst_score)
        if denominator == 0:
            raise MetadataError(f"{self.name}: SOTA and worst score transform identically")
        return (self.phi(score) - self.phi(self.worst_score)) / denominator

    def reported(self, score: float | None) -> float:
        """The number AIRS-Bench publishes for one run: ``fillna(0).replace(inf,100).clip(0)``.

        Three rules, all of them the benchmark's, all of them load-bearing:

        ``None`` becomes **0.0**, not "excluded". A run with no scoreable submission is a
        zero in the mean, which is the whole reason *valid submission rate* is a headline
        metric beside it rather than a footnote. Dropping the task instead — which is what
        this repository's first AIRS write-up did — silently removes an arm's worst
        outcome from its own average.

        A non-finite ratio becomes **100**, and a negative one becomes **0**. There is no
        upper clip: the published figure calls out agents above human SOTA, and 1.0 is not
        a ceiling.
        """
        if score is None:
            return 0.0
        value = self.normalized(score)
        if not math.isfinite(value):
            return PHI_INFINITY_SUBSTITUTE
        return max(0.0, value)


def tasks_root(repo_root: Path) -> Path:
    return Path(repo_root).expanduser().resolve().joinpath(*RAD_TASKS_RELPATH)


def available_tasks(repo_root: Path) -> list[str]:
    root = tasks_root(repo_root)
    if not root.is_dir():
        return []
    return sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and (path / "metadata.yaml").is_file()
    )


def resolve_task_name(repo_root: Path, name: str) -> str:
    """Accept a task name case-insensitively, and refuse an ambiguous or unknown one."""
    names = available_tasks(repo_root)
    if name in names:
        return name
    matches = [candidate for candidate in names if candidate.casefold() == name.casefold()]
    if len(matches) == 1:
        return matches[0]
    raise MetadataError(
        f"Unknown AIRS-Bench task {name!r}. Available under {tasks_root(repo_root)}:\n  "
        + "\n  ".join(names)
    )


#: ``os.path.join(global_shared_data_dir, 'A/B', 'C')`` -- the whole argument list, not the
#: first argument. Two of the twenty tasks pass the dataset and the config as *separate*
#: arguments, and a pattern that captured only the first read ``Yelp/yelp_review_full``
#: where the script means ``Yelp/yelp_review_full/yelp_review_full``. That mistake staged
#: the data one directory from where the script looks and cost two tasks of an arm; worse,
#: it read as a defect in the benchmark until the third argument was noticed.
_RAW_PATH_PATTERN = re.compile(
    r"global_shared_data_dir\s*,\s*((?:['\"][^'\"]+['\"]\s*,?\s*)+)\)"
)
_QUOTED = re.compile(r"['\"]([^'\"]+)['\"]")


def raw_relpath_for(task_dir: Path) -> str:
    """Where this task's ``prepare.py`` expects its raw dataset to be staged.

    Read out of the script, because that is the path that has to exist. Composing
    ``<dataset>/<config>`` from ``metadata.yaml`` is right for eighteen of the twenty and
    wrong for the other two, and the failure mode is a ``FileNotFoundError`` an hour into
    a run rather than at setup time.
    """
    sources = [task_dir / "prepare.py", task_dir / "evaluate_prepare.py"]
    found: list[str] = []
    for source in sources:
        if not source.is_file():
            continue
        for match in _RAW_PATH_PATTERN.finditer(read_text(source)):
            parts = _QUOTED.findall(match.group(1))
            joined = "/".join(part.strip("/") for part in parts if part)
            if joined and joined not in found:
                found.append(joined)
    if not found:
        raise MetadataError(f"{task_dir.name}: no raw dataset path found in prepare.py")
    if len(found) > 1:
        raise MetadataError(
            f"{task_dir.name}: prepare scripts read {len(found)} raw dataset paths "
            f"({', '.join(found)}); this adapter stages one per task."
        )
    return found[0]


def _declared_rows(shape: Any) -> int | None:
    """First dimension of ``logging_info.shape``, whatever shape that field is in.

    The twenty tasks write it five different ways — ``(4906,)``, ``[1531]``, ``300,1``,
    ``(19210,2)`` and a YAML sequence — so this reads the first integer rather than a
    format.
    """
    if isinstance(shape, (list, tuple)):
        shape = shape[0] if shape else None
    if isinstance(shape, bool):
        return None
    if isinstance(shape, int):
        return shape
    if shape is None:
        return None
    match = re.search(r"\d+", str(shape))
    return int(match.group(0)) if match else None


def load_task(repo_root: Path, name: str) -> AirsTask:
    """Read one task's specification. Every field this adapter needs is required."""
    repo_root = Path(repo_root).expanduser().resolve()
    resolved = resolve_task_name(repo_root, name)
    task_dir = tasks_root(repo_root) / resolved

    missing = [f for f in TASK_SPEC_FILES if not (task_dir / f).is_file()]
    if missing:
        raise MetadataError(f"{resolved}: task specification is missing {', '.join(missing)}")

    metadata = parse_simple_yaml(read_text(task_dir / "metadata.yaml"))
    if not isinstance(metadata, dict):
        raise MetadataError(f"{resolved}: metadata.yaml did not parse into a mapping")

    globs = metadata.get("file_export_globs") or []
    if list(globs) != [SUBMISSION_NAME]:
        raise MetadataError(
            f"{resolved}: exports {globs!r} rather than [{SUBMISSION_NAME!r}]. This adapter "
            "exports one predictions file per task; a task with a different contract needs "
            "the export path taught about it rather than silently mis-exported."
        )

    info = metadata.get("logging_info") or {}
    if not isinstance(info, dict):
        raise MetadataError(f"{resolved}: logging_info did not parse into a mapping")

    sota_entries = metadata.get("logging_info", {}).get("sota") or []
    if not sota_entries:
        raise MetadataError(f"{resolved}: metadata.yaml records no SOTA entry")
    sota_score = _require_float(sota_entries[0].get("sota_score"), f"{resolved}: sota_score")

    return AirsTask(
        name=resolved,
        task_dir=task_dir,
        description=read_text(task_dir / "project_description.md").strip(),
        metric=str(info.get("metric") or "").strip(),
        dataset=str(info.get("dataset") or "").strip(),
        config=str(info.get("config") or "").strip(),
        raw_relpath=raw_relpath_for(task_dir),
        lower_is_better=bool(metadata.get("metric_lower_is_better")),
        optimal_score=_require_float(info.get("optimal_score"), f"{resolved}: optimal_score"),
        worst_score=_require_float(info.get("estimated_worst_score"), f"{resolved}: estimated_worst_score"),
        sota_score=sota_score,
        declared_rows=_declared_rows(info.get("shape")),
        scoring_column=str(info.get("scoring_column") or "").strip(),
        category=str(info.get("category") or "").strip(),
        research_problem=str(info.get("research_problem") or "").strip(),
        requirements=tuple(str(item) for item in (metadata.get("container_python_requirements") or [])),
        eval_requirements=tuple(str(item) for item in (metadata.get("evaluate_container_python_requirements") or [])),
    )


def _require_float(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MetadataError(f"{where} is {value!r}, not a number")
    return float(value)


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------


def ensure_workspace_layout(workspace: Path) -> None:
    for name in AIRS_WORKSPACE_DIRS:
        (workspace / name).mkdir(parents=True, exist_ok=True)


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


@dataclass(frozen=True)
class ScriptRun:
    """One invocation of a benchmark-owned script, kept whole for the run record."""

    script: str
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "script": self.script,
            "command": self.command,
            "exit_code": self.exit_code,
            # Tails, not heads: a traceback is at the end of the stream and that is the
            # part worth keeping when something failed.
            "stdout_tail": self.stdout[-4000:],
            "stderr_tail": self.stderr[-4000:],
        }


def run_task_script(
    *,
    task: AirsTask,
    script: str,
    python: str,
    raw_dir: Path,
    data_mount_dir: Path,
    agent_log_dir: Path | None = None,
    cwd: Path | None = None,
    timeout: int = 3600,
    env: dict[str, str] | None = None,
) -> ScriptRun:
    """Run one of the benchmark's own scripts with the arguments it documents.

    The adapter never reimplements ``prepare.py`` or ``evaluate.py``. Whatever the
    benchmark computes is what gets reported, including its failures.
    """
    data_mount_dir.mkdir(parents=True, exist_ok=True)
    command = [
        python,
        str(task.task_dir / script),
        "--global-shared-data-dir",
        str(Path(raw_dir).resolve()),
        "--agent-data-mount-dir",
        str(Path(data_mount_dir).resolve()),
    ]
    if agent_log_dir is not None:
        command += ["--agent-log-dir", str(Path(agent_log_dir).resolve())]
    completed = subprocess.run(  # noqa: S603 - the command is composed here, not user text
        command,
        cwd=str(cwd) if cwd is not None else str(task.task_dir),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return ScriptRun(
        script=script,
        command=command,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def prepare_workspace(
    *,
    task: AirsTask,
    raw_dir: Path,
    workspace: Path,
    python: str = sys.executable,
    timeout: int = 3600,
    force: bool = False,
) -> ScriptRun | None:
    """Stage the agent's view of the dataset with the task's own ``prepare.py``.

    Returns ``None`` when the data is already staged and *force* is not set, so re-entering
    a workspace after a crash does not re-download and re-serialise a dataset that is
    already there. The prepared manifest is written either way: a workspace that was staged
    by an older run still has to be able to say how many rows its test split holds, and
    that is the number every later check is made against.
    """
    workspace = Path(workspace)
    ensure_workspace_layout(workspace)
    data_dir = workspace / "data"
    result: ScriptRun | None = None
    if force or not any(data_dir.iterdir()):
        staged = Path(raw_dir).expanduser().resolve() / task.raw_relpath
        if not staged.exists():
            raise FileNotFoundError(
                f"{task.name}: raw dataset not staged at {staged}. Run tools/airs_setup.py "
                f"--task {task.name} first."
            )
        result = run_task_script(
            task=task,
            script="prepare.py",
            python=python,
            raw_dir=raw_dir,
            data_mount_dir=data_dir,
            timeout=timeout,
        )
        if not result.ok:
            raise RuntimeError(
                f"{task.name}: prepare.py exited {result.exit_code}\n{result.stderr[-4000:]}"
            )

    marker = workspace / PREPARED_MARKER_NAME
    if force or not marker.is_file():
        measured = measure_test_rows(workspace, python=python)
        marker.write_text(
            json.dumps(
                {
                    "task": task.name,
                    "splits": sorted(path.name for path in data_dir.iterdir() if path.is_dir()),
                    "test_rows": measured,
                    "declared_rows": task.declared_rows,
                    # Recorded rather than asserted. The benchmark ships at least one task
                    # where these two disagree, and a harness whose reaction to that is an
                    # exception cannot run the task at all.
                    "rows_disagree": (
                        measured is not None
                        and task.declared_rows is not None
                        and measured != task.declared_rows
                    ),
                    "raw_relpath": task.raw_relpath,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return result



def measure_test_rows(workspace: Path, python: str = sys.executable) -> int | None:
    """Rows in the prepared test split, counted with the same reader ``evaluate.py`` uses.

    Counted rather than read out of ``dataset_info.json``, whose ``splits`` block describes
    the *source* dataset and survives both a column drop and a row selection. The number
    that matters is what ``load_from_disk`` returns, so that is what is asked for.
    """
    test_dir = Path(workspace) / "data" / "test"
    if not test_dir.is_dir():
        return None
    snippet = "from datasets import load_from_disk;print(len(load_from_disk(%r)))" % str(test_dir)
    try:
        completed = subprocess.run(  # noqa: S603 - composed here, not user text
            [python, "-c", snippet], capture_output=True, text=True, timeout=600
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    try:
        return int(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def prepared_manifest(workspace: Path) -> dict[str, Any]:
    """What :func:`prepare_workspace` recorded about this workspace, or ``{}``."""
    path = Path(workspace) / PREPARED_MARKER_NAME
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def expected_rows_for(task: AirsTask, workspace: Path) -> int | None:
    """How many rows this workspace's submission must have. Measured beats declared.

    ``CoreferenceResolutionWinograndeAccuracy`` is why this function exists rather than a
    field lookup. Its ``project_description.md`` tells the agent *"it should be of shape
    (1531, 1)"* and its ``metadata.yaml`` says ``shape: [1531]``, while its ``prepare.py``
    hands over ``winogrande_xl``'s **1,267**-row validation split and its ``evaluate.py``
    scores against exactly that. An agent that does what the description says produces 1,531
    rows and the evaluator refuses the file outright — so on that task the benchmark's own
    specification scores zero. Believing the declaration here would make this adapter refuse
    a correct submission and accept a wrong one, in that order.

    The measurement is not a hint the agent is not entitled to: it is
    ``len(load_from_disk('./data/test'))``, one line inside the workspace it was given.
    """
    measured = prepared_manifest(workspace).get("test_rows")
    if isinstance(measured, int) and measured > 0:
        return measured
    return task.declared_rows


def rows_disagreement(task: AirsTask, workspace: Path) -> tuple[int, int] | None:
    """``(declared, measured)`` when the task's own two answers differ, else ``None``."""
    measured = prepared_manifest(workspace).get("test_rows")
    if not isinstance(measured, int) or task.declared_rows is None:
        return None
    return (task.declared_rows, measured) if measured != task.declared_rows else None


# ---------------------------------------------------------------------------
# Goal
# ---------------------------------------------------------------------------


def fence_research_task(description: str) -> str:
    """Fence the whole project description.

    Unlike ResearchClawBench's ``INSTRUCTIONS.md``, which is mostly harness boilerplate
    wrapped around a research question, ``project_description.md`` is the question and
    nothing else: overview, dataset schema, submission format, evaluation script. Every
    sentence in it is a demand the run should be held to, so the fence goes round all of it.
    """
    text = description.strip()
    return f"{TASK_BEGIN_MARKER}\n{text}\n{TASK_END_MARKER}"


def describe_environment(*, python: str, extra: str = "") -> str:
    lines = [
        f"- Python interpreter for all task code: `{python}`. Use it explicitly — "
        "`python` on `PATH` is a different interpreter and does not have the task's "
        "packages.",
        f"- Install anything else you need into that environment with "
        f"`{python} -m pip install <package>`. You have network access for PyPI and the "
        "Hugging Face hub.",
        "- Check for GPUs with `nvidia-smi` before assuming CPU. If several are visible, "
        "others are using them too: pin one with `CUDA_VISIBLE_DEVICES` rather than "
        "taking the machine.",
    ]
    if extra.strip():
        lines.append(f"- {extra.strip()}")
    return "\n".join(lines)


#: The one paragraph in the goal that is about AutoR rather than about the task. It is
#: separated out because the control arm for any claim about this adapter is the same model
#: on the same task with no scaffold, and a control that was handed a different brief is
#: not a control. :func:`build_task_brief` is what both arms get, byte for byte;
#: :func:`build_airs_goal` is that brief plus this.
AUTOR_STAGE_NOTE = (
    "## A Note On This Pipeline's Own Deliverables\n\n"
    "AutoR's stage contract asks every stage for summaries, hypotheses, a report plan, "
    "figures and a decision ledger, and its gates will refuse a stage that does not "
    "produce them. Produce them honestly — they are how this run stays inspectable — but "
    "do not confuse them with the deliverable. None of them is scored. Where a stage has "
    "to choose between a better model and a better write-up of the model it already has, "
    "choose the model, and say in the summary that you did."
)


def build_task_brief(
    *,
    task: AirsTask,
    workspace: Path,
    python: str = sys.executable,
    environment_notes: str = "",
    expected_rows: int | None = None,
    declared_rows_note: tuple[int, int] | None = None,
) -> str:
    """The task, the workspace contract and the scoring rule, with no scaffold in it.

    This is what a bare CLI control arm is given and what :func:`build_airs_goal` starts
    from, so the two arms differ in the scaffold and in nothing else. The RCB work found
    that the published margin between AutoR and a bare CLI was unreliable because the two
    arms had not been given the same budget; being able to point at one function and say
    "both arms got exactly this" is the cheapest half of not repeating that.

    The task goes first. Four readers inside AutoR excerpt ``user_input.txt`` by taking a
    prefix — the router, the deliberation panel, the adversarial validity reviewer and the
    report synthesizer — so what those readers see is decided by what this function puts
    first, exactly as it is on the ResearchClawBench path.

    Nothing in the returned text names the SOTA score, the estimated worst score or the
    optimal score. Those live in ``metadata.yaml``, the benchmark does not put them in
    ``project_description.md``, and handing them to the agent would make this run's number
    incomparable with every number on the published leaderboard.
    """
    resolved = Path(workspace).resolve()
    submission = resolved / SUBMISSION_NAME
    rows = expected_rows if expected_rows is not None else task.declared_rows
    row_note = (
        f"It must have exactly **{rows} data rows** plus the header row, in the same order "
        "as the test split."
        if rows is not None
        else "It must have one data row per test example, in the order of the test split, "
        "plus the header row."
    )
    if declared_rows_note is not None:
        declared, measured = declared_rows_note
        row_note += (
            f" **The task description above says {declared}; the test split you have been "
            f"given holds {measured}.** The evaluator counts the split, not the description, "
            "so the split wins — and check it yourself with "
            "`len(load_from_disk('./data/test'))` before you write the file."
        )
    return "\n\n".join(
        [
            "# Benchmark Run: AIRS-Bench",
            (
                "This run is being scored by AIRS-Bench. There is no human available at any "
                "point: no one will answer a question, approve a plan, or grant a permission. "
                "Make the best judgement you can from the data and keep going."
            ),
            "## Research Task",
            fence_research_task(task.description),
            "## Benchmark Workspace Contract",
            (
                f"The benchmark workspace is `{resolved}`. It is separate from the AutoR run "
                "tree, and one file inside it is the entire deliverable. Every stage must keep "
                "these paths up to date:\n\n"
                f"- `{resolved}/data/` — the prepared dataset, already staged by the "
                "benchmark's own `prepare.py`. **Read-only. Never modify or delete.** Load it "
                "with `datasets.load_from_disk`, e.g. "
                f"`load_from_disk('{resolved}/data/train')`.\n"
                f"- `{resolved}/code/` — all modelling and inference code you write.\n"
                f"- `{resolved}/outputs/` — checkpoints, intermediate predictions, logs, "
                "anything derived.\n"
                f"- `{submission}` — **the scored artifact.**\n"
            ),
            "## How This Run Is Scored",
            (
                f"There is no judge and no rubric. AIRS-Bench runs the task's own "
                f"`evaluate.py` over `{SUBMISSION_NAME}` against held-out labels you do not "
                f"have, computes **{task.metric or 'the task metric'}**, and that number is "
                "the whole result. Three consequences worth acting on, because they invert "
                "what most of this pipeline is shaped for:\n\n"
                f"1. **A missing or malformed `{SUBMISSION_NAME}` scores nothing at all.** "
                "Not a low score — no score. Produce a valid submission from a simple "
                "baseline early, then improve it in place. A sophisticated method that is "
                "still training when the run ends is worth less than a mean predictor that "
                "finished.\n"
                f"2. {row_note} The evaluator reads it with "
                "`pd.read_csv(path, header=0)` and then `df.values.squeeze()`, and refuses a "
                "row count that does not match the test set. Check the count yourself before "
                "you finish; a shape error is the single most common way to score zero on a "
                "task that was otherwise solved.\n"
                "3. **No report, figure or paragraph reaches the benchmark.** Prose is not a "
                "lever here and neither is presentation; the predictions are the entire "
                "result. Spend the run's time on them.\n\n"
                "Hold out part of the training data and measure yourself on it. You cannot see "
                "the test labels, so a local validation split is the only evidence you will "
                "have that a change helped — and every hypothesis this run adjudicates has to "
                "rest on one."
            ),
            "## Rules",
            (
                # AIRS-Bench's own agents run in a container with no network, so for them
                # this rule is enforced by the environment. Here it is not: the datasets are
                # public and the held-out labels are one `load_dataset` call away. Stating
                # the rule is what makes a run auditable -- `tools/airs_arm.py` greps every
                # arm's stream log for exactly these routes afterwards -- and a benchmark
                # number from an un-containerised run that does not state it is worth
                # nothing.
                f"- **Use only the data under `{resolved}/data/`.** Do not download this "
                "dataset from the Hugging Face hub or anywhere else, do not load it from a "
                "local cache, and do not go looking for the held-out labels. They exist on "
                "this machine and on the internet; obtaining them by any route other than "
                "your own model predicting them makes the run worthless and it will be "
                "audited.\n"
                f"- **Stay inside `{resolved}`**, except to install packages. Nothing outside "
                "it is yours to read or write.\n"
                "- Write code that a reader could re-run. A number you cannot reproduce is "
                "not a result you have."
            ),
            "## Execution Environment",
            describe_environment(python=python, extra=environment_notes),
            "## What Counts As Done",
            (
                f"A run is finished when `{submission}` exists, has the right number of rows, "
                "and holds the best predictions this run was able to produce — with the code "
                f"that generated it under `{resolved}/code/` and a validation number you "
                "measured yourself recorded in the results."
            ),
        ]
    )


def build_airs_goal(
    *,
    task: AirsTask,
    workspace: Path,
    python: str = sys.executable,
    environment_notes: str = "",
) -> str:
    """The goal AutoR walks its stage graph against: the shared brief plus one paragraph.

    The brief is returned verbatim as a prefix, which is what makes a bare-CLI arm on the
    same task a control rather than a second experiment.
    """
    brief = build_task_brief(
        task=task,
        workspace=workspace,
        python=python,
        environment_notes=environment_notes,
        expected_rows=expected_rows_for(task, workspace),
        declared_rows_note=rows_disagreement(task, workspace),
    )
    return f"{brief}\n\n{AUTOR_STAGE_NOTE}"


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubmissionCheck:
    """What is actually in a submission file, without opening a scorer."""

    path: Path | None
    exists: bool
    rows: int | None = None
    columns: int | None = None
    header: list[str] = field(default_factory=list)
    expected_rows: int | None = None
    problem: str = ""

    @property
    def valid(self) -> bool:
        return self.exists and not self.problem

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["path"] = str(self.path) if self.path is not None else None
        payload["valid"] = self.valid
        return payload


def inspect_submission(
    path: Path | None, task: AirsTask, expected_rows: int | None = None
) -> SubmissionCheck:
    """Read a submission far enough to say whether the evaluator will accept it.

    This mirrors what ``evaluate.py`` does — ``read_csv(header=0)`` then a row-count
    comparison — and stops there. It never repairs, pads or truncates: a submission with
    the wrong number of rows is a run that did not finish the task, and rewriting it into
    something scoreable would turn a non-attempt into a measurement.
    """
    rows_wanted = expected_rows if expected_rows is not None else task.declared_rows
    if path is None or not Path(path).is_file():
        return SubmissionCheck(path=Path(path) if path else None, exists=False,
                               expected_rows=rows_wanted,
                               problem="no submission.csv was produced")
    path = Path(path)
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            rows = [row for row in reader if row and any(cell.strip() for cell in row)]
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        return SubmissionCheck(path=path, exists=True, expected_rows=rows_wanted,
                               problem=f"unreadable as CSV: {exc}")
    if not rows:
        return SubmissionCheck(path=path, exists=True, rows=0, expected_rows=rows_wanted,
                               problem="file is empty")
    header, body = rows[0], rows[1:]
    problem = ""
    if rows_wanted is not None and len(body) != rows_wanted:
        problem = f"{len(body)} data rows, expected {rows_wanted}"
    return SubmissionCheck(
        path=path,
        exists=True,
        rows=len(body),
        columns=len(header),
        header=list(header),
        expected_rows=rows_wanted,
        problem=problem,
    )


def find_submission(paths: RunPaths | None, workspace: Path) -> Path | None:
    """The submission the agent produced, wherever it put it. Contract path wins.

    A run that wrote the file where the goal said to is unambiguous. A run that wrote it
    into the AutoR run tree instead did the research and missed the contract, and losing
    the task over a directory would be measuring the adapter rather than the agent — so the
    run tree is searched too, nearest-to-the-results first. Nothing outside those two trees
    is looked at, and no file is ever created here.
    """
    contract = Path(workspace) / SUBMISSION_NAME
    if contract.is_file():
        return contract
    if paths is None:
        return None
    for name in SUBMISSION_FALLBACK_DIRS:
        candidate = paths.workspace_root / name / SUBMISSION_NAME
        if candidate.is_file():
            return candidate
    matches = sorted(
        (path for path in paths.run_root.rglob(SUBMISSION_NAME) if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


@dataclass(frozen=True)
class ExportResult:
    submission: SubmissionCheck
    #: Where the exported file came from: ``contract`` when the agent wrote it at the
    #: path the goal named, ``run_tree`` when it was recovered from AutoR's own workspace,
    #: ``missing`` when there was nothing to export.
    source: str
    code_files: int = 0
    output_files: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "code_files": self.code_files,
            "output_files": self.output_files,
            "submission": self.submission.to_dict(),
        }


def export_submission(*, paths: RunPaths | None, workspace: Path, task: AirsTask) -> ExportResult:
    """Put the run's predictions and code where the benchmark reads them.

    The submission is copied to the contract path when it was found elsewhere, and left
    alone when it is already there. Code and outputs are mirrored for the record — nothing
    scores them, but a submission with no code behind it is not a reproducible result.
    """
    workspace = Path(workspace).resolve()
    ensure_workspace_layout(workspace)

    code_files = output_files = 0
    if paths is not None:
        code_files = _mirror_tree(paths.code_dir, workspace / "code")
        output_files = _mirror_tree(paths.results_dir, workspace / "outputs" / "results")
        output_files += _mirror_tree(paths.notes_dir, workspace / "outputs" / "notes")

    rows_wanted = expected_rows_for(task, workspace)
    found = find_submission(paths, workspace)
    contract = workspace / SUBMISSION_NAME
    if found is None:
        return ExportResult(submission=inspect_submission(None, task, rows_wanted),
                            source="missing",
                            code_files=code_files, output_files=output_files)
    source = "contract" if found.resolve() == contract.resolve() else "run_tree"
    if source == "run_tree":
        shutil.copy2(found, contract)
    return ExportResult(
        submission=inspect_submission(contract, task, rows_wanted),
        source=source,
        code_files=code_files,
        output_files=output_files,
    )


def _mirror_tree(source: Path, destination: Path) -> int:
    if not source.exists():
        return 0
    copied = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        if any(part in {"__pycache__", ".git", ".ipynb_checkpoints"} for part in path.relative_to(source).parts):
            continue
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
    return copied


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def parse_evaluation_output(stdout: str) -> dict[str, float]:
    """The metric dictionary ``evaluate.py`` printed.

    The banner is looked for first and the last JSON object in the stream is the fallback,
    because a task's evaluator is free to print whatever it likes around its result and
    several of them do.
    """
    tail = stdout
    index = stdout.rfind(EVALUATION_BANNER)
    if index != -1:
        tail = stdout[index + len(EVALUATION_BANNER):]
    for candidate in reversed(_json_objects(tail) or _json_objects(stdout)):
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload:
            numeric = {
                key: float(value)
                for key, value in payload.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            }
            if numeric:
                return numeric
    return {}


def _json_objects(text: str) -> list[str]:
    """Every balanced ``{...}`` span in *text*, outermost only, in order of appearance."""
    spans: list[str] = []
    depth = 0
    start = -1
    for position, character in enumerate(text):
        if character == "{":
            if depth == 0:
                start = position
            depth += 1
        elif character == "}" and depth:
            depth -= 1
            if depth == 0 and start != -1:
                spans.append(text[start: position + 1])
                start = -1
    return spans


@dataclass(frozen=True)
class TaskScore:
    """The benchmark's own number for one run, plus what it normalises to."""

    task: str
    metric: str
    #: ``None`` when there was no scoreable submission. Distinct from ``0.0``, which is a
    #: real metric value on several of these tasks.
    value: float | None
    #: The raw ratio, unclipped, ``None`` when there is no value. Diagnostic.
    normalized: float | None
    valid_submission: bool
    sota_score: float
    worst_score: float
    optimal_score: float
    lower_is_better: bool
    #: The number AIRS-Bench itself would publish for this run: ``AirsTask.reported``,
    #: so a run with no submission carries **0.0** here while ``value`` and ``normalized``
    #: stay ``None``. Both are needed and they are not redundant -- the first is what goes
    #: into the arm's mean, the second is what says the mean has a hole in it.
    reported: float = 0.0
    submission: dict[str, Any] = field(default_factory=dict)
    all_metrics: dict[str, float] = field(default_factory=dict)
    reason: str = ""
    scripts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_submission(
    *,
    task: AirsTask,
    raw_dir: Path,
    workspace: Path,
    score_dir: Path,
    python: str = sys.executable,
    timeout: int = 3600,
    keep_score_dir: bool = False,
) -> TaskScore:
    """Score a workspace with the benchmark's own ``evaluate_prepare.py`` + ``evaluate.py``.

    Scoring happens in *score_dir*, never in the workspace. ``evaluate_prepare.py`` writes
    the test split **with its labels** into the directory it is given, and writing that
    into a workspace an agent can still read would put the answers next to the question.

    A submission that fails :func:`inspect_submission` is not sent to the evaluator at all.
    The evaluator would raise on a row-count mismatch anyway, but an evaluator error and a
    malformed submission are different findings and only one of them is about the run.
    """
    workspace = Path(workspace).resolve()
    score_dir = Path(score_dir).expanduser().resolve()
    scripts: list[dict[str, Any]] = []

    def failure(reason: str, check: SubmissionCheck) -> TaskScore:
        return TaskScore(
            task=task.name, metric=task.metric, value=None, normalized=None, reported=0.0,
            valid_submission=False, sota_score=task.sota_score, worst_score=task.worst_score,
            optimal_score=task.optimal_score, lower_is_better=task.lower_is_better,
            submission=check.to_dict(), reason=reason, scripts=scripts,
        )

    check = inspect_submission(
        workspace / SUBMISSION_NAME, task, expected_rows_for(task, workspace)
    )
    if not check.valid:
        return failure(check.problem or "submission is not valid", check)

    score_dir.mkdir(parents=True, exist_ok=True)
    data_mount = score_dir / "data"
    try:
        prepared = run_task_script(
            task=task,
            script="evaluate_prepare.py",
            python=python,
            raw_dir=raw_dir,
            data_mount_dir=data_mount,
            agent_log_dir=workspace,
            cwd=score_dir,
            timeout=timeout,
        )
        scripts.append(prepared.to_dict())
        if not prepared.ok:
            return failure(f"evaluate_prepare.py exited {prepared.exit_code}", check)

        command = [
            python,
            str(task.task_dir / "evaluate.py"),
            "--submission-file",
            str(data_mount / SUBMISSION_NAME),
        ]
        completed = subprocess.run(  # noqa: S603 - composed here, not user text
            command, cwd=str(score_dir), capture_output=True, text=True, timeout=timeout
        )
        evaluated = ScriptRun(
            script="evaluate.py", command=command, exit_code=completed.returncode,
            stdout=completed.stdout, stderr=completed.stderr,
        )
        scripts.append(evaluated.to_dict())
        if not evaluated.ok:
            return failure(f"evaluate.py exited {evaluated.exit_code}", check)

        metrics = parse_evaluation_output(evaluated.stdout)
        if not metrics:
            return failure("evaluate.py printed no parseable metric", check)
        value = _primary_metric(metrics, task)
        if value is None or not math.isfinite(value):
            return failure(f"metric is {value!r}, not a finite number", check)
        return TaskScore(
            task=task.name,
            metric=_primary_metric_name(metrics, task),
            value=value,
            normalized=task.normalized(value),
            reported=task.reported(value),
            valid_submission=True,
            sota_score=task.sota_score,
            worst_score=task.worst_score,
            optimal_score=task.optimal_score,
            lower_is_better=task.lower_is_better,
            submission=check.to_dict(),
            all_metrics=metrics,
            scripts=scripts,
        )
    finally:
        if not keep_score_dir:
            shutil.rmtree(score_dir, ignore_errors=True)


def _primary_metric_name(metrics: dict[str, float], task: AirsTask) -> str:
    """Prefer the key ``metadata.yaml`` names; fall back to the only key there is.

    ``evaluate.py`` decides its own key and does not always echo the metadata's spelling,
    so matching is case-folded and the single-key case is accepted outright. A multi-key
    result whose keys none of that resolves is a task this adapter has not been taught,
    and :func:`_primary_metric` returns ``None`` rather than picking one.
    """
    if task.metric in metrics:
        return task.metric
    folded = {key.casefold(): key for key in metrics}
    if task.metric.casefold() in folded:
        return folded[task.metric.casefold()]
    if len(metrics) == 1:
        return next(iter(metrics))
    return task.metric


def _primary_metric(metrics: dict[str, float], task: AirsTask) -> float | None:
    name = _primary_metric_name(metrics, task)
    return metrics.get(name)


# ---------------------------------------------------------------------------
# Run metadata
# ---------------------------------------------------------------------------


def write_run_meta(
    workspace: Path,
    *,
    task_id: str,
    run_id: str,
    status: str,
    duration_seconds: int,
    model: str,
    agent_name: str = "AutoR",
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write the ``_meta.json`` an arm runner and the scorer read.

    Shaped like :func:`src.rcb.write_run_meta` so one reader can handle both benchmarks,
    and updated rather than replaced so a field a batch runner already set survives.
    """
    meta_path = Path(workspace) / "_meta.json"
    meta: dict[str, Any] = {}
    if meta_path.exists():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        if isinstance(loaded, dict):
            meta = loaded

    meta.update(
        {
            "benchmark": "airs-bench",
            "task_id": task_id or meta.get("task_id"),
            "run_id": meta.get("run_id") or run_id,
            "status": status,
            "workspace": str(workspace),
            "agent_name": meta.get("agent_name") or agent_name,
            "duration_seconds": duration_seconds,
            "model": model,
            "code_version": code_version(),
        }
    )
    if extra:
        meta.update(extra)
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return meta_path


def write_task_card(workspace: Path, task: AirsTask) -> Path:
    """Leave the task's own description in the workspace, for a reader and for a re-run.

    Not read by anything in the pipeline: the goal is composed from the task specification
    directly. It exists because a workspace should say what it is without needing the
    airs-bench checkout that produced it.
    """
    path = Path(workspace) / "TASK.md"
    write_text(path, task.description.strip() + "\n")
    return path


@dataclass(frozen=True)
class BenchmarkResult:
    workspace: Path
    run_root: Path
    task: str
    pipeline_completed: bool
    export: ExportResult
    auto_skipped_stages: list[str] = field(default_factory=list)
    aborted_with: str = ""

    @property
    def aborted(self) -> bool:
        return bool(self.aborted_with)

    @property
    def status(self) -> str:
        """Four outcomes, and the submission decides three of them.

        ``completed``  — the walk finished and a valid submission exists.
        ``aborted``    — an exception ended the walk, whatever else survived.
        ``incomplete`` — the walk finished but the submission is missing or malformed.

        A report-scored benchmark can call a partial run a degraded success, because a
        partial report still scores. Here it cannot: a submission with the wrong number of
        rows is refused by the evaluator, so there is no such thing as a partially scored
        one and saying ``completed`` would be saying something false about a run that
        produced no number.
        """
        if self.aborted:
            return "aborted"
        return "completed" if self.export.submission.valid else "incomplete"

    @property
    def exit_code(self) -> int:
        return 0 if self.status == "completed" else 1


def collect_task_resources(task: AirsTask, workspace: Path) -> list[Any]:
    """AIRS-Bench ships no reference papers, so a run starts with no resources.

    Kept as a named seam rather than an omission: the ResearchClawBench adapter's
    equivalent is what puts the task's papers in front of Stage 01, and a reader comparing
    the two adapters should find the difference stated instead of having to notice it.
    """
    return []


def summarize_tasks(repo_root: Path) -> list[dict[str, Any]]:
    """One row per shipped task. Used by ``tools/airs_setup.py --list`` and by tests."""
    rows: list[dict[str, Any]] = []
    for name in available_tasks(repo_root):
        task = load_task(repo_root, name)
        rows.append(
            {
                "task": task.name,
                "metric": task.metric,
                "dataset": task.dataset,
                "raw_relpath": task.raw_relpath,
                "lower_is_better": task.lower_is_better,
                "sota": task.sota_score,
                "worst": task.worst_score,
                "optimal": task.optimal_score,
                "declared_rows": task.declared_rows,
                "category": task.category,
            }
        )
    return rows


__all__: Sequence[str] = (
    "AIRS_WORKSPACE_DIRS",
    "AirsTask",
    "BenchmarkResult",
    "ExportResult",
    "MetadataError",
    "PHI_INFINITY_SUBSTITUTE",
    "PHI_OPTIMUM_SUBSTITUTE",
    "RAD_TASKS_RELPATH",
    "SUBMISSION_NAME",
    "ScriptRun",
    "SubmissionCheck",
    "TaskScore",
    "AUTOR_STAGE_NOTE",
    "available_tasks",
    "build_airs_goal",
    "build_task_brief",
    "build_run_paths_for_workspace",
    "collect_task_resources",
    "describe_environment",
    "emit_event",
    "PREPARED_MARKER_NAME",
    "ensure_workspace_layout",
    "expected_rows_for",
    "export_submission",
    "fence_research_task",
    "find_submission",
    "inspect_submission",
    "latest_run_root",
    "load_task",
    "parse_evaluation_output",
    "parse_simple_yaml",
    "measure_test_rows",
    "prepare_workspace",
    "prepared_manifest",
    "raw_relpath_for",
    "resolve_task_name",
    "rows_disagreement",
    "run_task_script",
    "runs_dir_for",
    "score_submission",
    "summarize_tasks",
    "tasks_root",
    "write_run_meta",
    "write_task_card",
)
