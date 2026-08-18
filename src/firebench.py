"""FIRE-Bench: the dataset, the workspace, the goal contract, and the scored artifact.

`FIRE-Bench <https://github.com/maitrix-org/FIRE-Bench>`_ turns empirical-analysis papers
into agent tasks: the agent is handed a research question and a list of resources, has to
*design and run its own experiments*, and is scored on the conclusion it states at the
end. Thirty-five human-curated tasks, one hundred and fifty-three machine-generated ones.
It is AutoR's third benchmark, and the third different shape:

===================  =====================  =============================  ==================
benchmark            deliverable            scored against                 execution?
===================  =====================  =============================  ==================
ResearchClawBench    ``report/report.md``   a weighted checklist, images    yes
FrontierScience      one written answer     a rubric summing to 10 points   no
FIRE-Bench           one written conclusion a reference conclusion, by      yes
                                            atomic claim: P / R / F1
===================  =====================  =============================  ==================

**Four measured properties of this benchmark decide the whole design of the adapter.**
They are not preferences; each one was read out of the harness or the shipped tasks, and
each one breaks a habit carried over from the other two adapters.

1. **The scored text is short, and longer is strictly worse.** The thirty-five reference
   conclusions in ``benchmark/papers/*/conclusion.txt`` are one to three sentences:
   :data:`REFERENCE_CONCLUSION_CHARS` — median 255 characters, shortest 117, longest 372.
   Precision is *the fraction of the agent's own atomic claims that the reference
   supports* (``eval/RAGChecker/eval.py``), so every extra claim is a coin flip against
   the score. This inverts ResearchClawBench, where an uncovered result scores zero and
   coverage beats polish; here an uncovered claim costs recall once, and a superfluous
   claim costs precision forever. AutoR's own writing stage produces 35 kB reports, so
   the goal contract has to say this in the prompt or the pipeline will lose on length
   alone.

2. **Numbers are deleted before scoring.** ``eval.py`` pipes the extracted text through
   ``extract_core_idea``, whose system prompt is "extract only the core insight or main
   idea, omitting all concrete values, specific numbers, background details, methods,
   file names, or references to artifacts". A conclusion that is a table of measurements
   is scored as whatever generalisation a summariser reads out of it. Experiments still
   decide whether the generalisation is *true* -- they are just not what is read.

3. **The harness kills the agent at one hour.** ``FIRE-Bench/run_agent.py`` runs each
   agent under ``subprocess.run(..., timeout=3600)``. A measured ResearchClawBench run of
   this pipeline took 27,005 seconds and a FrontierScience single-stage run's median was
   4,320. So the adapter is deadline-driven rather than stage-count-driven: see
   :class:`Deadline`, and :data:`DEFAULT_FINAL_STAGE`.

4. **The scored artifact is the last line of a log file, and two other patterns can
   steal it.** ``eval/RAGChecker/utils.py:extract_single_final_thought`` tries three
   readers *in order*: an OpenHands ``final_thought='...', outputs=`` regex anywhere in
   the file, then -- if the file holds three or more ``[YYYY-MM-DDTHH:MM:SS]`` stamps --
   the text between the third-last and the last of them, and only then the last line as
   ``{"result": ...}``. An agent trajectory pasted into that file verbatim will trip one
   of the first two and be scored on a fragment of its own log. :func:`sanitise_log_body`
   is the whole of the defence, and :func:`publish_conclusion_line` the whole of the
   contract.

**What is deliberately not here.** No scorer. FIRE-Bench's own evaluator is a
third-party pipeline (RAGChecker + refchecker) that needs its own environment, and a
second implementation of a claim-level F1 would be a second answer to the question of
what the score is. ``tools/score_fire_run.py`` drives the shipped one.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .frontierscience import _OperatorCall, has_refusal, stage_answer_bodies, stages_approved_in
from .rcb import AUTOR_RUNS_DIRNAME, emit_event, fence_research_task, mirror_tree
from .utils import (
    RunPaths,
    StageSpec,
    code_version,
    contains_placeholder_text,
    read_text,
    truncate_text,
    write_text,
)

# ---------------------------------------------------------------------------
# The benchmark, as measured
# ---------------------------------------------------------------------------

#: Upstream repository, pinned so a future reader can tell what was read.
FIREBENCH_REPO = "https://github.com/maitrix-org/FIRE-Bench"

#: Length of every shipped reference conclusion, in characters, sorted. Measured over
#: ``benchmark/papers/*/conclusion.txt`` at commit a7017c9 -- 35 files, min 117, median
#: 255, max 372. It is a constant rather than a sentence in a docstring because
#: :func:`conclusion_length_refusals` derives its band from it, and a band whose
#: justification is prose is a band nobody re-measures.
REFERENCE_CONCLUSION_CHARS = (
    117, 135, 140, 148, 157, 163, 165, 171, 176, 181, 185, 190, 197, 203, 211, 218, 224,
    255, 258, 263, 268, 274, 278, 281, 288, 295, 301, 309, 316, 324, 333, 344, 352, 359, 372,
)

#: Split directories inside the FIRE-Bench checkout.
SPLIT_DIRS = {"verified": "benchmark/papers", "unverified": "benchmark/papers_unverified"}

#: Where the harness puts each run's log, relative to the FIRE-Bench checkout:
#: ``log/<agent_id>/<llm_model>/<task_id>/<timestamp>/log.log``. Reproduced here because
#: the adapter has to be able to build the path when it is driven directly rather than
#: through ``agents/autor/run.py``.
LOG_TEMPLATE = "log/{agent_id}/{llm_model}/{task_id}/{timestamp}/log.log"

#: The three metadata lines and the rule that ends the header, verbatim from
#: ``agents/claude/run.py``. ``read_log_metadata`` in the evaluator's ``utils.py`` parses
#: the first three; nothing parses the rule, but every shipped agent writes it.
LOG_HEADER_RULE = "=" * 40


# ---------------------------------------------------------------------------
# Workspace and deliverable
# ---------------------------------------------------------------------------

#: Directories created in the sandbox before the walk starts.
#:
#: No ``report/`` and no ``report/images/``, unlike ResearchClawBench. Nothing reads a
#: report here, and :func:`src.frontierscience.ensure_fs_workspace` already paid for the
#: lesson that an empty directory named after a deliverable is an invitation for a stage
#: to fill it. ``figures/`` is absent for the same reason and one more: the figure gates
#: in :mod:`src.utils` fire from Stage 06, and this adapter's default walk stops before
#: them (see :data:`DEFAULT_FINAL_STAGE`).
FIREBENCH_WORKSPACE_DIRS = ("code", "outputs")

#: The file a stage is told to write. Also where the exporter's first source looks.
CONCLUSION_FILENAME = "conclusion.md"

#: Written beside the conclusion so a re-export can tell "the agent wrote this" from
#: "a previous export published this". Same device, same reason, as ``.autor_export.json``
#: in :mod:`src.rcb` and ``.fs_export.json`` in :mod:`src.frontierscience`.
EXPORT_MARKER_NAME = ".autor_fire_export.json"

#: Floor for a publishable conclusion. Below the shortest reference conclusion (117) on
#: purpose: the reference is a *summary of a paper*, and an agent that says the same thing
#: in ninety characters has answered, not failed. What this refuses is the empty string,
#: the single word, and the "I was unable to..." sentence.
FIRE_MIN_CONCLUSION_CHARS = 80

#: Ceiling. Four times the longest reference conclusion (372). A conclusion past this is
#: not a conclusion, it is a report -- and against a precision metric computed over the
#: agent's own atomic claims, a report is the failure mode with the highest prior. It is a
#: *refusal*, not a truncation: cutting the text at a character count would silently
#: publish half a sentence and score it.
FIRE_MAX_CONCLUSION_CHARS = 1500

#: Marker on a conclusion assembled by this module rather than written by a model, kept
#: on the first line so it survives being pasted anywhere. Nothing that carries it is
#: allowed to exit zero -- see :data:`FIRE_EXIT_CLAUSES`.
FIRE_FALLBACK_MARKER = "<!-- autor:firebench-fallback -->"

#: Refusal ids. Strings rather than an enum because they are written into ``_meta.json``
#: and read back by a scorer that does not import this module.
FIRE_REFUSAL_NO_APPROVED_STAGE = "driver:no_approved_stage"
FIRE_REFUSAL_TOO_SHORT = "length:below_floor"
FIRE_REFUSAL_TOO_LONG = "length:above_ceiling"
FIRE_REFUSAL_PLACEHOLDER = "content:placeholder_text"
FIRE_REFUSAL_IS_A_PLAN = "content:conclusion_is_a_plan"
FIRE_REFUSAL_IS_A_LOG = "content:conclusion_is_a_transcript"

#: The synthetic stage the one-shot calls are logged under, so their raw streams land in
#: ``logs_raw.jsonl`` beside the pipeline's. Number 9 for the same reason
#: :data:`src.frontierscience.FS_ANSWER_STAGE` uses it: past every real stage, so nothing
#: that orders by number mistakes it for part of the walk.
FIRE_CONCLUSION_STAGE = StageSpec(9, "09_fire_conclusion", "FIRE-Bench Conclusion")

#: Where the walk stops by default.
#:
#: Stage 06 is the first stage that requires figures -- ``src/utils.py`` fails any stage
#: at or past it whose ``workspace/figures`` holds no PNG, and
#: ``resolve_min_report_figures`` clamps the floor to at least one, so there is no
#: configuration that turns it off. FIRE-Bench scores no images at all. Stopping at Stage
#: 05 therefore costs nothing that is scored and buys the whole figure budget back as
#: experiment time, inside a one-hour deadline. The analysis that Stage 06 would have
#: done is what :class:`ConclusionSynthesizer` is for, and it is one call rather than a
#: stage with a reviewer and a figure gate.
DEFAULT_FINAL_STAGE = "05_experimentation"

#: Where the walk starts by default.
#:
#: Stage 01 is a literature survey. Every FIRE-Bench task is a *rediscovery* of a
#: published finding, and the paper it came from is on the open web with its conclusion in
#: the abstract -- so a literature survey on this benchmark is a search for the answer
#: key, and a run that does it is not measuring what the benchmark says it measures.
#: Starting at Stage 02 is the cheapest honest answer; ``--web-search off`` (this
#: adapter's default) is the other half of it, and the two are independent because Stage
#: 02 can still be told about prior work through the task statement.
DEFAULT_FIRST_STAGE = "02_hypothesis_generation"


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


class TaskNotFound(ValueError):
    """Raised when a task id does not resolve inside the FIRE-Bench checkout.

    Carries the candidates it looked at, because the two splits use the same directory
    layout and picking the wrong one is the likely mistake.
    """


@dataclass(frozen=True)
class FireTask:
    """One FIRE-Bench task, read off disk.

    ``instruction_gt`` and ``conclusion`` are deliberately **not** fields. They exist in
    the same directory as ``instruction.txt``; loading them into the object that the goal
    builder receives is one refactor away from putting the answer in the prompt. The
    scorer reads them from disk itself.
    """

    task_id: str
    split: str
    root: Path
    instruction: str

    @property
    def data_dir(self) -> Path | None:
        """The task's bundled data, if it ships any. 17 of the 35 verified tasks do."""
        candidate = self.root / "data"
        return candidate if candidate.is_dir() else None

    @property
    def instruction_sha256(self) -> str:
        return hashlib.sha256(self.instruction.encode("utf-8")).hexdigest()

    def dataset_note(self) -> str:
        """``dataset.txt``, when the curators pointed at an upstream source instead."""
        candidate = self.root / "dataset.txt"
        return read_text(candidate).strip() if candidate.is_file() else ""


def bench_root_from(path: Path | str) -> Path:
    """Resolve a FIRE-Bench checkout, refusing anything that is not one.

    The check is for ``run_agent.py`` beside ``benchmark/papers`` rather than for the
    directory's name: a checkout can be called anything, and a directory that merely
    contains ``benchmark/papers`` is more likely to be a copy of the tasks than a
    checkout the harness can run.
    """
    root = Path(path).expanduser().resolve()
    if (root / "run_agent.py").is_file() and (root / SPLIT_DIRS["verified"]).is_dir():
        return root
    raise TaskNotFound(
        f"{root} is not a FIRE-Bench checkout: expected run_agent.py and "
        f"{SPLIT_DIRS['verified']}/ under it. Clone {FIREBENCH_REPO}."
    )


def available_tasks(bench_root: Path, split: str = "verified") -> list[str]:
    """Task ids in a split, in the order the filesystem sorts them."""
    root = bench_root / SPLIT_DIRS[split]
    if not root.is_dir():
        return []
    return sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and (path / "instruction" / "instruction.txt").is_file()
    )


def load_task(bench_root: Path, task_id: str, split: str | None = None) -> FireTask:
    """Read one task, searching both splits when the caller did not name one."""
    splits = [split] if split else ["verified", "unverified"]
    tried: list[str] = []
    for candidate_split in splits:
        if candidate_split not in SPLIT_DIRS:
            raise TaskNotFound(f"Unknown split {candidate_split!r}; expected one of {sorted(SPLIT_DIRS)}.")
        root = bench_root / SPLIT_DIRS[candidate_split] / task_id
        instruction_file = root / "instruction" / "instruction.txt"
        tried.append(str(instruction_file))
        if instruction_file.is_file():
            return FireTask(
                task_id=task_id,
                split=candidate_split,
                root=root,
                instruction=read_text(instruction_file).strip(),
            )
    raise TaskNotFound(
        f"No FIRE-Bench task {task_id!r}. Looked for: " + ", ".join(tried) + "."
    )


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------


def fire_runs_dir_for(workspace: Path) -> Path:
    return workspace / AUTOR_RUNS_DIRNAME


def conclusion_path_for(workspace: Path) -> Path:
    return workspace / CONCLUSION_FILENAME


def fire_workspace_name(task_id: str, label: str, *, stamp: str) -> str:
    """``<task_id>__<label>__<stamp>``.

    Two underscores as the separator because FIRE-Bench task ids contain single ones
    (``to_cot_or_not_to_cot``), so a single-underscore scheme cannot be split back.
    """
    return f"{task_id}__{label}__{stamp}"


def ensure_fire_workspace(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    for name in FIREBENCH_WORKSPACE_DIRS:
        (workspace / name).mkdir(parents=True, exist_ok=True)
    fire_runs_dir_for(workspace).mkdir(parents=True, exist_ok=True)


#: Above this, ``data/`` is linked instead of copied. Two of the thirty-five verified
#: tasks are over it -- ``lost_in_the_middle`` at 875 MB and ``questbench`` at 592 MB --
#: and a paired trial that copies those per arm per repeat writes tens of gigabytes to
#: say nothing new. Under it, copying is worth the disk: the copy is what makes "read
#: only" true rather than merely asked for.
LINK_DATA_ABOVE_BYTES = 200 * 1024 * 1024


def _tree_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def preview_task_inputs(task: FireTask, *, utils_src: Path | None = None) -> dict[str, Any]:
    """What :func:`stage_task_inputs` would report, without creating anything.

    ``--print-goal`` renders the same contract the run will render, and a preview that
    said "this task ships no data" for a task that ships 875 MB of it would make the
    printed contract a different document from the one the agent is given.
    """
    staged: dict[str, Any] = {"data": None, "utils": None, "dataset_note": bool(task.dataset_note())}
    if task.data_dir is not None:
        staged["data"] = sorted(
            str(path.relative_to(task.data_dir)) for path in task.data_dir.rglob("*") if path.is_file()
        )
    if utils_src is not None and utils_src.is_dir():
        staged["utils"] = sorted(
            str(path.relative_to(utils_src)) for path in utils_src.rglob("*.py") if path.is_file()
        )
    return staged


def stage_task_inputs(task: FireTask, workspace: Path, *, utils_src: Path | None = None) -> dict[str, Any]:
    """Copy the task's inputs into the sandbox, and say what was copied.

    Mirrors what ``agents/claude/run.py`` does, with its bug fixed: that file calls
    ``shutil.copytree(benchmark/papers/<task>/data, sandbox)`` unconditionally, and
    **twenty of the thirty-five verified tasks ship no ``data/`` directory at all**, so it
    raises ``FileNotFoundError`` at a line above the one that creates the log directory --
    which means those twenty produce no log file whatsoever, while ``run_agent.py``, which
    never checks a return code, prints that the task "completed".

    ``data/`` is copied rather than symlinked because the goal contract calls it read-only
    and a symlink into the checkout turns an agent's stray ``open(..., "w")`` into an edit
    of the benchmark. The copy *is* the read-only guarantee. Above
    :data:`LINK_DATA_ABOVE_BYTES` that trade stops paying and the directory is linked;
    ``_meta.json`` records which of the two happened, because "the data was read-only"
    is then a claim about a different mechanism.
    """
    staged: dict[str, Any] = {
        "data": None,
        "data_mode": None,
        "utils": None,
        "dataset_note": bool(task.dataset_note()),
    }
    if task.data_dir is not None:
        destination = workspace / "data"
        if destination.is_symlink() or destination.exists():
            if destination.is_symlink():
                destination.unlink()
            else:
                shutil.rmtree(destination)
        size = _tree_bytes(task.data_dir)
        staged["data_bytes"] = size
        if size > LINK_DATA_ABOVE_BYTES:
            destination.symlink_to(task.data_dir.resolve(), target_is_directory=True)
            staged["data_mode"] = "symlink"
        else:
            shutil.copytree(task.data_dir, destination)
            staged["data_mode"] = "copy"
        staged["data"] = sorted(
            str(path.relative_to(destination)) for path in destination.rglob("*") if path.is_file()
        )
    if utils_src is not None and utils_src.is_dir():
        destination = workspace / "utils"
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(utils_src, destination)
        staged["utils"] = sorted(
            str(path.relative_to(destination))
            for path in destination.rglob("*.py")
            if path.is_file()
        )
    if task.dataset_note():
        write_text(workspace / "dataset.txt", task.dataset_note() + "\n")
    return staged


# ---------------------------------------------------------------------------
# Goal contract
# ---------------------------------------------------------------------------


def _reference_length_sentence() -> str:
    lengths = REFERENCE_CONCLUSION_CHARS
    return (
        f"{len(lengths)} reference conclusions ship with the benchmark; they are "
        f"{min(lengths)} to {max(lengths)} characters long, median "
        f"{sorted(lengths)[len(lengths) // 2]}"
    )


def build_fire_goal(
    task: FireTask,
    workspace: Path,
    *,
    model_catalog: Mapping[str, Any] | None = None,
    deadline_seconds: int | None = None,
    staged: Mapping[str, Any] | None = None,
) -> str:
    """Wrap the task instruction in the contract every stage prompt carries.

    The task goes **first**, before any of AutoR's own prose, for the reason
    :func:`src.rcb.build_benchmark_goal` documents: four readers excerpt this document by
    taking a prefix (the router at 2,500 characters, the deliberation panel at 3,000, the
    validity reviewer at 3,000, the synthesizer at 8,000), and whatever is in front of the
    question is what they see instead of it.
    """
    resolved = workspace.resolve()
    staged = dict(staged or {})

    resources_lines = [
        f"- `{resolved}/code/` — every script you write. Keep it runnable and keep it here.",
        f"- `{resolved}/outputs/` — raw results, tables, intermediate data, logs of your own runs.",
        f"- `{resolved}/{CONCLUSION_FILENAME}` — **the scored deliverable.** See below.",
    ]
    if staged.get("data"):
        listed = staged["data"][:20]
        more = "" if len(staged["data"]) <= 20 else f"\n  … and {len(staged['data']) - 20} more file(s)."
        resources_lines.insert(
            0,
            f"- `{resolved}/data/` — the data this task ships, **read-only**:\n"
            + "\n".join(f"  - `data/{name}`" for name in listed)
            + more,
        )
    else:
        resources_lines.insert(
            0,
            f"- `{resolved}/data/` — **this task ships no data.** You generate everything you "
            "measure. That is the task, not an omission.",
        )
    if staged.get("utils"):
        resources_lines.insert(
            1,
            f"- `{resolved}/utils/` — the benchmark's own helper package, already importable "
            f"from `{resolved}`. `from utils.llm_inference import LLMInference` is the call the "
            "task statement means.",
        )

    if model_catalog:
        openai_models = ", ".join(f"`{name}`" for name in model_catalog.get("openai", [])) or "none"
        claude_models = ", ".join(f"`{name}`" for name in model_catalog.get("claude", [])) or "none"
        model_block = (
            "The task statement above names the models the *original paper* used. Most of them "
            "are not served by this deployment, and `utils/llm_inference.py` refuses them at "
            "construction with a `ModelNotAvailable` naming the substitutes rather than failing "
            "four hundred prompts later. What you can actually call:\n\n"
            f"- OpenAI-compatible (`provider=\"openai\"`): {openai_models}\n"
            f"- Anthropic (`provider=\"claude\"`): {claude_models}\n\n"
            "**Substitute deliberately and say so.** Most of these tasks are about a *contrast* "
            "— weak model against strong, short prompt against long, one format against another "
            "— and a contrast survives a substitution as long as the axis does. Pick "
            "substitutes that preserve the axis the question is about, run the experiment, and "
            "name the substitution in your conclusion only if it changes what the conclusion can "
            "claim. Do not silently drop an arm because its model is missing: an experiment with "
            "one arm answers nothing.\n\n"
            "`python -c \"from utils.llm_inference import available_models; "
            "print(available_models())\"` prints this list at runtime."
        )
    else:
        model_block = (
            "No model catalogue was supplied to this run. Probe what `utils/llm_inference.py` "
            "can reach before designing an experiment around a particular model."
        )

    deadline_block = (
        (
            f"**You have about {deadline_seconds // 60} minutes of wall clock in total, for "
            "everything: design, implementation, execution and writing.** The benchmark harness "
            "sends SIGKILL at the end of it and a run with no conclusion on disk scores nothing "
            "at all. Budget backwards from that. Two experiments finished and written up beat "
            "five started. If you are running out of time, stop measuring and write the "
            "conclusion — the conclusion is the only thing that is read."
        )
        if deadline_seconds
        else (
            "No wall-clock limit was passed to this run. The upstream harness imposes one of "
            "3600 s; assume it unless you were told otherwise."
        )
    )

    scoring_block = (
        "Your conclusion is scored by **claim-level precision, recall and F1** against a "
        "reference conclusion written by the humans who did this study. The pipeline is: your "
        "text is summarised into its 'core idea', both texts are broken into atomic claims, and "
        "a judge asks of each claim whether the other text supports it.\n\n"
        "Four consequences, and each of them contradicts an instinct that is right elsewhere:\n\n"
        "1. **Every extra claim is a bet against your own score.** Precision is the fraction of "
        "*your* claims the reference supports. A true, well-evidenced, interesting finding that "
        "the reference does not happen to mention still costs you precision. Say the few things "
        "the question actually asked and stop.\n"
        "2. **Numbers are deleted before you are scored.** The summariser is instructed to omit "
        "'all concrete values, specific numbers, background details, methods, file names, or "
        "references to artifacts'. So `accuracy fell from 0.82 to 0.31` is read as *accuracy "
        "fell*. Run the experiments — they are what makes the direction true, and a claim with "
        "nothing behind it is how a run states the opposite of what it measured — but state the "
        "*direction and the mechanism* in the conclusion, not the table.\n"
        "3. **Length is the dominant failure mode.** "
        f"{_reference_length_sentence()}. Aim for that. A conclusion over "
        f"{FIRE_MAX_CONCLUSION_CHARS} characters is refused by this adapter before it is ever "
        "scored, because at that length it is a report and the precision metric will read every "
        "aside in it as a claim.\n"
        "4. **Answer the question that was asked, at the granularity it was asked.** If the "
        "question is 'does X hold, or is it really Y', the reference conclusion says which, and "
        "then usually one clause about the condition under which it holds. Two to four atomic "
        "claims is the shape. Hedging ('results were mixed', 'further work is needed') is read "
        "as a claim and is almost never one the reference supports."
    )

    return "\n\n".join(
        [
            "# Benchmark Run: FIRE-Bench",
            (
                "This run is scored by FIRE-Bench, which measures whether an agent can "
                "*rediscover* the finding of a published empirical study by running its own "
                "experiments. There is no human available at any point: nobody will answer a "
                "question, approve a plan, or grant a permission. Make the best judgement you "
                "can from what is in front of you and keep going."
            ),
            "## Research Task",
            fence_research_task(task.instruction),
            "## Wall Clock",
            deadline_block,
            "## Workspace",
            (
                f"The sandbox is `{resolved}`. It is yours; the benchmark checkout is not. "
                "Everything you write goes here:\n\n" + "\n".join(resources_lines)
            ),
            "## Models You Can Actually Call",
            model_block,
            "## How The Conclusion Is Scored",
            scoring_block,
            "## The Deliverable",
            (
                f"Write `{resolved}/{CONCLUSION_FILENAME}`: plain prose, no markdown headings, no "
                "bullet list, no preamble about what you did. Just the finding, in the register "
                "of a paper's concluding sentence. It is the only artifact that is scored — the "
                "code, the outputs and the reasoning exist to make it true, and none of them is "
                "read.\n\n"
                "Write it as soon as you have a defensible answer, and rewrite it when you learn "
                "something that changes it. Do not save it for the end: the harness kills this "
                "process on a clock, and the file on disk at that moment is the run."
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Deadline
# ---------------------------------------------------------------------------


@dataclass
class Deadline:
    """One clock, consulted by everything that can spend the budget.

    A deadline is not the same object as a stage timeout, and conflating them is what
    produces a run that is killed with nothing on disk: a stage timeout bounds *one*
    subprocess, and eight of them in sequence can be individually well behaved and
    collectively over budget. This class owns the total, hands out per-stage slices from
    what is left, and keeps a reserve that only the publisher may spend.
    """

    total_seconds: int
    reserve_seconds: int
    started_at: float = field(default_factory=time.monotonic)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def remaining(self) -> float:
        return max(0.0, self.total_seconds - self.elapsed)

    @property
    def remaining_before_reserve(self) -> float:
        """What the walk may still spend. Never negative, so callers cannot pass it on."""
        return max(0.0, self.remaining - self.reserve_seconds)

    def expired(self) -> bool:
        return self.remaining_before_reserve <= 0.0

    def stage_slice(self, stages_left: int, *, floor: int = 240) -> int:
        """Seconds to allow the next stage.

        ``floor`` exists because a slice below it cannot produce anything: the backend's
        own start-up plus a single tool call is most of four minutes. Handing a stage
        thirty seconds does not make it fast, it makes it a timeout with a cost.
        """
        stages_left = max(1, int(stages_left))
        return max(floor, int(self.remaining_before_reserve // stages_left))

    def snapshot(self) -> dict[str, Any]:
        return {
            "deadline_seconds": self.total_seconds,
            "reserve_seconds": self.reserve_seconds,
            "elapsed_seconds": round(self.elapsed, 1),
            "remaining_seconds": round(self.remaining, 1),
        }


# ---------------------------------------------------------------------------
# Conclusion: refusals
# ---------------------------------------------------------------------------

#: Openers that mean the model narrated instead of concluding. Matched at the start of
#: the text only: "we ran" in the middle of a sentence is ordinary prose, at the start it
#: is a trip report. Kept short on purpose -- a long blacklist refuses real answers.
_PLAN_OPENERS = re.compile(
    r"^\s*(?:i\s+(?:will|plan|am\s+going)|we\s+will|next\s+steps?|the\s+plan\b|"
    r"here\s+is\s+(?:my|the)\s+plan|to\s+answer\s+this\s+question,?\s+i\s+will)",
    re.I,
)

#: Shapes that only ever appear in a pasted trajectory.
_TRANSCRIPT_MARKERS = (
    "tool_use",
    "assistant:",
    "```json",
    "Thinking…",
    "<thinking>",
)


def conclusion_length_refusals(text: str) -> list[str]:
    body = text.strip()
    reasons: list[str] = []
    if len(body) < FIRE_MIN_CONCLUSION_CHARS:
        reasons.append(f"{FIRE_REFUSAL_TOO_SHORT}:{len(body)}")
    if len(body) > FIRE_MAX_CONCLUSION_CHARS:
        reasons.append(f"{FIRE_REFUSAL_TOO_LONG}:{len(body)}")
    return reasons


def conclusion_content_refusals(text: str) -> list[str]:
    """What the text is, rather than how long it is.

    Deliberately *not* the FrontierScience content check. That one refuses any text
    carrying one of ``REQUIRED_STAGE_HEADINGS`` -- 'Objective', 'Key Results' -- because a
    FrontierScience answer that carries them is a stage summary. A FIRE-Bench conclusion
    is three sentences of prose, so the same rule would fire on the word 'Key Results'
    appearing inside a legitimate sentence and refuse a good answer. What is refused here
    is a plan, a transcript, and a placeholder.
    """
    body = text.strip()
    reasons: list[str] = []
    if contains_placeholder_text(body):
        reasons.append(FIRE_REFUSAL_PLACEHOLDER)
    if _PLAN_OPENERS.search(body):
        reasons.append(FIRE_REFUSAL_IS_A_PLAN)
    if any(marker in body for marker in _TRANSCRIPT_MARKERS):
        reasons.append(FIRE_REFUSAL_IS_A_LOG)
    return reasons


# ---------------------------------------------------------------------------
# Conclusion: producing one
# ---------------------------------------------------------------------------


def mirror_run_artifacts(workspace: Path, paths: RunPaths | None) -> dict[str, int]:
    """Copy the run tree's code and results into the sandbox the contract promised.

    The goal contract tells the agent that ``<sandbox>/code/`` and ``<sandbox>/outputs/``
    are where its work goes, and AutoR's stage contract tells every stage that the run
    tree's own workspace is. Both are followed, and the sandbox ends up empty -- which
    makes the contract a false statement about the run, and makes an audit of "what did
    it actually measure" start in the wrong directory.

    Nothing downstream scores these files; this is for the record and for the human who
    reads it afterwards. It is a copy rather than a move because the run tree is the
    provenance and must stay intact.
    """
    moved = {"code": 0, "outputs": 0}
    if paths is None:
        return moved
    code_dir = getattr(paths, "code_dir", None)
    if code_dir is not None and Path(code_dir).is_dir():
        moved["code"] = mirror_tree(Path(code_dir), workspace / "code")
    for source in (getattr(paths, "results_dir", None), getattr(paths, "notes_dir", None)):
        if source is not None and Path(source).is_dir():
            moved["outputs"] += mirror_tree(Path(source), workspace / "outputs" / Path(source).name)
    return moved


def result_files(*, workspace: Path, paths: RunPaths | None) -> list[str]:
    """Every file the run produced, from both places a stage might have put it.

    Measured on a real pipeline run: the sandbox's ``code/`` and ``outputs/`` were
    **empty** while the run tree held 272 files including ``results/responses.jsonl``
    and ``results/condition_accuracy.json``. The goal contract asks stages to write into
    the sandbox; AutoR's stage contract points them at the run tree's own workspace, and
    the stages followed the one they are always given. Listing only the sandbox therefore
    handed the synthesizer "(none)" for a run that had made 694 model calls per arm and
    written its accuracies to disk -- so the one call that turns experiments into a
    conclusion was asked to do it without them.

    Paths are printed as absolute when they come from the run tree, because that is where
    the model has to open them.
    """
    names: list[str] = []
    for directory in ("outputs", "code", "data"):
        root = workspace / directory
        if root.is_dir():
            names.extend(
                str(path.relative_to(workspace))
                for path in sorted(root.rglob("*"))
                if path.is_file() and "__pycache__" not in path.parts
            )
    if paths is not None:
        for root in (
            getattr(paths, "results_dir", None),
            getattr(paths, "code_dir", None),
            getattr(paths, "notes_dir", None),
            getattr(paths, "data_dir", None),
        ):
            if root is not None and Path(root).is_dir():
                names.extend(
                    str(path)
                    for path in sorted(Path(root).rglob("*"))
                    if path.is_file() and "__pycache__" not in path.parts
                )
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


class ConclusionSynthesizer(_OperatorCall):
    """One operator call that turns approved stage work into a conclusion.

    Imported seam, not a new one: :class:`src.frontierscience._OperatorCall` already wraps
    ``operator._prepare_invocation`` / ``_run_streaming_command`` -- the pair
    :class:`src.rcb.ReportSynthesizer` also uses -- so a third copy here would be a third
    place for the invocation, the MCP config and the denied-tool list to drift apart.

    **It refuses when nothing was approved.** That guard is the same one
    :class:`src.frontierscience.AnswerSynthesizer` documents, and it matters more here.
    Without it, a pipeline arm whose walk collapsed calls a model with the task statement
    and an empty memory file, gets a competent single-shot answer back, and publishes it
    as the pipeline's result -- so the paired comparison against the single-shot control
    measures one model against itself and reports the variance as the pipeline's effect.
    """

    MAX_ATTEMPTS = 2

    #: How much of each approved stage body the prompt carries. The synthesis call is the
    #: last thing that happens before the deadline, so this is a latency budget as much
    #: as a context one.
    STAGE_BODY_CHARS = 6000

    def __init__(self, operator: Any, max_attempts: int = MAX_ATTEMPTS) -> None:
        super().__init__(operator)
        self.max_attempts = max(1, int(max_attempts))

    def build_prompt(
        self,
        *,
        paths: RunPaths,
        workspace: Path,
        question: str,
        stages_approved: Sequence[str],
    ) -> str:
        bodies = stage_answer_bodies(paths)
        evidence = "\n\n---\n\n".join(
            truncate_text(body, max_chars=self.STAGE_BODY_CHARS) for body in bodies
        )
        outputs = result_files(workspace=workspace, paths=paths)[:40]
        return "\n\n".join(
            [
                "# Write the conclusion for this study",
                (
                    "A research pipeline has just finished running experiments in "
                    f"`{workspace.resolve()}`. Your only job is to state what it found, in the "
                    "form the benchmark scores."
                ),
                "## The question it was asked",
                question.strip(),
                "## Stages it completed",
                ", ".join(stages_approved) or "(none)",
                "## What those stages recorded",
                evidence or "(no stage bodies were recorded)",
                "## Result files on disk",
                ("\n".join(f"- `{name}`" for name in outputs) or "(none)"),
                "## What to write",
                (
                    "Read the result files before you write -- the stage summaries above are "
                    "descriptions of the work, the files are the measurements, and where they "
                    "disagree the files are right.\n\n"
                    f"Write `{workspace.resolve()}/{CONCLUSION_FILENAME}` and put the same text "
                    "in your reply. It must be:\n\n"
                    f"- **Prose. {min(REFERENCE_CONCLUSION_CHARS)}–{max(REFERENCE_CONCLUSION_CHARS)} "
                    "characters, two to four sentences.** No headings, no bullets, no preamble.\n"
                    "- **A finding, not a description of the work.** Not 'we ran three "
                    "experiments comparing…' but the claim those experiments support.\n"
                    "- **Free of specific numbers, file names and method names.** They are "
                    "stripped before scoring, and they crowd out the claim that is scored.\n"
                    "- **Directional and mechanistic.** Which way the effect went, and under "
                    "what condition it holds or breaks.\n"
                    "- **Only what was measured.** Every claim you add that the study did not "
                    "establish costs precision, and no claim you leave out costs anything "
                    "except the one the question asked for.\n\n"
                    "If the experiments did not settle the question, say what they did settle. "
                    "Do not write that further work is needed; that is scored as a claim and it "
                    "is never one the reference makes."
                ),
            ]
        )

    def __call__(
        self,
        *,
        paths: RunPaths,
        workspace: Path,
        question: str,
        stages_approved: Sequence[str],
    ) -> str | None:
        if not stages_approved:
            return None
        if self.fake:
            return None
        if not self.supported():
            return None
        prompt = self.build_prompt(
            paths=paths, workspace=workspace, question=question, stages_approved=stages_approved
        )
        target = conclusion_path_for(workspace)
        before = read_text(target).strip() if target.exists() else ""
        for attempt in range(1, self.max_attempts + 1):
            try:
                _exit_code, reply = self.invoke(
                    paths=paths, prompt=prompt, label="fire_synthesis", attempt=attempt
                )
            except Exception:  # noqa: BLE001 - the stage path is still available
                continue
            written = read_text(target).strip() if target.exists() else ""
            # The file first, then the reply. The prompt asks for both, and the file is
            # the one the model had to be deliberate about; the reply carries the
            # streamed narration around it (`_compose_stdout_text` concatenates every
            # text fragment in the stream, not the final message), which is exactly the
            # shape `conclusion_content_refusals` calls a transcript.
            for candidate in ([written] if written and written != before else []) + [reply.strip()]:
                body = candidate.strip()
                if not body:
                    continue
                if conclusion_length_refusals(body) or conclusion_content_refusals(body):
                    continue
                return body
        return None


class DirectConclusionWriter(_OperatorCall):
    """The control arm: one agentic operator call, and what it leaves behind is the run.

    This is not "one API call". The operator is the backend CLI with its tools, so the
    single call can write code, run it, and iterate -- which is what FIRE-Bench's own
    ``agents/claude`` baseline is, and therefore what a paired difference has to be
    measured against. The difference between this arm and the pipeline arm is AutoR's
    stage graph, its reviewer and its gates, and nothing else.
    """

    MAX_ATTEMPTS = 2

    def __init__(self, operator: Any, max_attempts: int = MAX_ATTEMPTS) -> None:
        super().__init__(operator)
        self.max_attempts = max(1, int(max_attempts))

    def __call__(self, *, paths: RunPaths, workspace: Path, goal: str) -> str | None:
        if self.fake or not self.supported():
            return None
        target = conclusion_path_for(workspace)
        for attempt in range(1, self.max_attempts + 1):
            try:
                _exit_code, reply = self.invoke(
                    paths=paths, prompt=goal, label="fire_direct", attempt=attempt
                )
            except Exception:  # noqa: BLE001 - a failed call is a missing answer, not a crash
                continue
            # The file, not the reply. A single agentic call that has been told to write a
            # file and then keeps working ends its stream with tool narration, so the
            # concatenated reply is a transcript with the answer buried in it -- and this
            # benchmark scores the *whole* extracted text for precision, so the narration
            # would be scored as claims.
            written = read_text(target).strip() if target.exists() else ""
            if written and not conclusion_length_refusals(written) and not conclusion_content_refusals(written):
                return written
            body = reply.strip()
            if body and not conclusion_length_refusals(body) and not conclusion_content_refusals(body):
                return body
        return None


def build_fallback_conclusion(*, paths: RunPaths | None, reasons: Sequence[str]) -> str:
    """A marked, unscoreable placeholder for a run that produced no conclusion.

    It exists so that ``conclusion.md`` is never *absent without explanation*, and it
    carries :data:`FIRE_FALLBACK_MARKER` on its first line so that nothing -- the exit
    code, the log publisher, the scorer -- can mistake it for an answer.
    :func:`publish_conclusion_line` refuses to write a fallback as the scored last line
    of ``log.log``, which is the whole point: a run that failed should be unscoreable,
    not silently scored as a zero that looks like a measurement.
    """
    lines = [FIRE_FALLBACK_MARKER, "", "No conclusion was produced by this run.", ""]
    if reasons:
        lines.append("Refusals recorded:")
        lines.extend(f"- {reason}" for reason in reasons)
        lines.append("")
    run_root = getattr(paths, "run_root", None)
    if run_root is not None:
        lines.append(f"Run tree: `{run_root}`")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Conclusion: publishing one
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FireConclusion:
    path: Path
    source: str
    chars: int
    sha256: str
    refusals: tuple[str, ...]

    @property
    def is_fallback(self) -> bool:
        return self.source == "fallback"

    @property
    def scoreable(self) -> bool:
        return not self.is_fallback and not self.refusals and self.chars > 0


def _digest(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def _matches_export_marker(workspace: Path, text: str) -> bool:
    marker = workspace / EXPORT_MARKER_NAME
    if not marker.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("conclusion_sha256") == _digest(text)


def _publish(workspace: Path, text: str, source: str) -> str:
    body = text.strip()
    write_text(conclusion_path_for(workspace), body + "\n")
    write_text(
        workspace / EXPORT_MARKER_NAME,
        json.dumps({"conclusion_source": source, "conclusion_sha256": _digest(body)}, indent=2) + "\n",
    )
    return body


def export_conclusion(
    *,
    workspace: Path,
    paths: RunPaths | None,
    direct_conclusion: str | None = None,
    stages_approved: Sequence[str] = (),
    synthesize: ConclusionSynthesizer | None = None,
    question: str = "",
) -> FireConclusion:
    """Find the conclusion, in priority order, and record which source produced it.

    ``agent`` → ``synthesized`` → ``fallback``. There is no ``stage`` source, unlike the
    other two adapters: a FIRE-Bench conclusion has to be two to four sentences of prose,
    and a stage summary promoted verbatim is a document with headings that
    :func:`conclusion_content_refusals` refuses and the precision metric would shred. If
    the stages produced work but no conclusion, the honest answer is to spend one call
    turning it into one, which is what ``synthesized`` is.
    """
    refusals: list[str] = []
    on_disk = conclusion_path_for(workspace)

    def _accept(body: str, source: str) -> FireConclusion | None:
        body = body.strip()
        if not body:
            return None
        reasons = conclusion_length_refusals(body) + conclusion_content_refusals(body)
        if reasons:
            # The source is a *suffix*, so the namespace the exit clause reads stays
            # `content:` / `length:`. Prefixing it instead -- `agent:content:...` --
            # was the first version, and it made `has_refusal(reasons, "content")`
            # false for every refusal the exporter had just recorded.
            refusals.extend(f"{reason}:{source}" for reason in reasons)
            return None
        published = _publish(workspace, body, source)
        return FireConclusion(
            path=on_disk,
            source=source,
            chars=len(published),
            sha256=_digest(published),
            refusals=tuple(refusals),
        )

    # 1. The agent's own file, or the direct arm's reply. A file this adapter published
    #    on an earlier pass is not the agent's, and the marker is how they are told apart.
    candidates: list[str] = []
    if direct_conclusion:
        candidates.append(direct_conclusion)
    if on_disk.is_file():
        text = read_text(on_disk).strip()
        if text and not _matches_export_marker(workspace, text) and not text.startswith(FIRE_FALLBACK_MARKER):
            candidates.append(text)
    for candidate in candidates:
        accepted = _accept(candidate, "agent")
        if accepted is not None:
            return accepted

    # 2. One synthesis call over approved stage work.
    if synthesize is not None and paths is not None:
        if not stages_approved:
            refusals.append(FIRE_REFUSAL_NO_APPROVED_STAGE)
        else:
            synthesized = synthesize(
                paths=paths, workspace=workspace, question=question, stages_approved=stages_approved
            )
            if synthesized:
                accepted = _accept(synthesized, "synthesized")
                if accepted is not None:
                    return accepted

    # 3. Nothing. Say so, in a file that cannot be scored.
    body = _publish(workspace, build_fallback_conclusion(paths=paths, reasons=refusals), "fallback")
    return FireConclusion(
        path=on_disk,
        source="fallback",
        chars=len(body),
        sha256=_digest(body),
        refusals=tuple(refusals),
    )


# ---------------------------------------------------------------------------
# The log file the evaluator reads
# ---------------------------------------------------------------------------

#: The two patterns that outrank the last line in FIRE-Bench's extractor, as it matches
#: them. Kept as the evaluator writes them so a future reader can diff the two.
_OPENHANDS_PATTERN = re.compile(r"final_thought\s*=\s*(?:'|\")(.+?)(?:'|\"),\s*outputs=", re.DOTALL)
_CODEX_TIMESTAMP = re.compile(r"\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\]")


def sanitise_log_body(text: str) -> str:
    """Neutralise the two patterns that would steal the score from the last line.

    ``eval/RAGChecker/utils.py:extract_single_final_thought`` reads the log with three
    readers in a fixed order, and the last line is the *third*. Before it gets there:

    1. any ``final_thought='…', outputs=`` anywhere in the file wins, and
    2. failing that, three or more ``[YYYY-MM-DDTHH:MM:SS]`` stamps make it return the
       text between the third-last and the last of them.

    An AutoR trajectory is JSON event lines with ISO timestamps in them. Written through
    verbatim, a run would be scored on a slice of its own progress log -- and the failure
    is invisible, because the extractor returns a plausible paragraph rather than an
    error. Both patterns are broken here by inserting a zero-width space, which changes
    no word and no line count and defeats both regexes.
    """
    if not text:
        return text
    cleaned = _CODEX_TIMESTAMP.sub(lambda m: m.group(0).replace("T", "T​", 1), text)
    cleaned = _OPENHANDS_PATTERN.sub(
        lambda m: m.group(0).replace("final_thought", "final_​thought", 1), cleaned
    )
    return cleaned


def log_path_for(bench_root: Path, *, agent_id: str, llm_model: str, task_id: str, timestamp: str) -> Path:
    return bench_root / LOG_TEMPLATE.format(
        agent_id=agent_id, llm_model=llm_model, task_id=task_id, timestamp=timestamp
    )


def open_log(log_file: Path, *, agent_id: str, task_id: str, llm_model: str) -> Path:
    """Create the log with the header every FIRE-Bench agent writes, and return it."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text(
        f"agent_id: {agent_id}\ntask_id: {task_id}\nllm_model: {llm_model}\n{LOG_HEADER_RULE}\n",
        encoding="utf-8",
    )
    return log_file


def append_log(log_file: Path, text: str) -> None:
    """Append sanitised trajectory text. Never the last line of a finished run."""
    if not text:
        return
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(sanitise_log_body(text.rstrip("\n")) + "\n")


def publish_conclusion_line(log_file: Path, conclusion: FireConclusion, *, body: str) -> bool:
    """Append the one line the evaluator scores, or refuse and say why.

    Appending rather than rewriting is deliberate, and it is what makes the run
    crash-safe: the extractor reads *the last line*, so a better conclusion written later
    simply wins, and a run killed between two of them is scored on the most recent one
    that was complete. A rewrite would have a window in which the file has no result line
    at all, and that window is exactly when the harness's SIGKILL arrives.

    A fallback is never published. A run that produced no conclusion has to be
    *unscoreable* -- the extractor returns ``None`` and the evaluator visibly skips it --
    rather than scored on a placeholder, which is a zero that reads like a measurement.
    """
    if conclusion.is_fallback or not body.strip():
        return False
    line = json.dumps({"result": body.strip()}, ensure_ascii=False)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write("\n" + line + "\n")
    return True


# ---------------------------------------------------------------------------
# Metadata and exit code
# ---------------------------------------------------------------------------

#: Every clause the exit code is made of, as (id, predicate) over ``_meta.json`` itself.
#:
#: The shape is copied from :data:`src.frontierscience.FS_EXIT_CLAUSES`, and the reason is
#: the measurement that produced it: over forty real ResearchClawBench runs, thirty-nine
#: wrote ``status: "completed"`` and the fortieth wrote no result line at all, while
#: thirty-one had auto-skipped a stage and eight had auto-skipped *the stage being
#: scored* -- none of which appeared in the metadata. Deriving the verdict from the same
#: dictionary that is written to disk is what makes it recomputable by anyone holding the
#: artifact.
FIRE_EXIT_CLAUSES: tuple[tuple[str, Any], ...] = (
    ("conclusion_present", lambda m: bool(m.get("conclusion_chars"))),
    ("conclusion_not_fallback", lambda m: m.get("conclusion_source") != "fallback"),
    (
        "conclusion_within_bounds",
        lambda m: isinstance(m.get("conclusion_chars"), int)
        and FIRE_MIN_CONCLUSION_CHARS <= m["conclusion_chars"] <= FIRE_MAX_CONCLUSION_CHARS,
    ),
    ("conclusion_published_to_log", lambda m: bool(m.get("log_result_line_written"))),
    ("no_content_refusal", lambda m: not has_refusal(m.get("refusals") or (), "content")),
    ("procedure_completed", lambda m: m.get("pipeline_completed") is True),
)


def fire_exit_failures(meta: Mapping[str, Any]) -> list[str]:
    return [name for name, clause in FIRE_EXIT_CLAUSES if not clause(meta)]


def fire_exit_code(meta: Mapping[str, Any]) -> int:
    return 1 if fire_exit_failures(meta) else 0


def build_fire_meta(
    *,
    workspace: Path,
    task: FireTask,
    profile: str,
    model: str,
    review_model: str,
    operator: str,
    conclusion: FireConclusion,
    conclusion_body: str,
    log_file: Path | None,
    log_result_line_written: bool,
    pipeline_completed: bool,
    auto_skipped_stages: Sequence[str],
    stages_approved: Sequence[str],
    disallowed_tools: Sequence[str],
    disallowed_tools_by_seat: Mapping[str, Sequence[str]],
    witness: Mapping[str, Any],
    run_id: str,
    deadline: Deadline,
    deadline_hit: bool,
    staged: Mapping[str, Any],
    fake_operator: bool = False,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": "fire_meta/1",
        "benchmark": "fire-bench",
        "task_id": task.task_id,
        "split": task.split,
        "profile": profile,
        "model": model,
        "review_model": review_model,
        "operator": operator,
        "fake_operator": bool(fake_operator),
        "workspace": str(workspace.resolve()),
        "run_id": run_id,
        "code_version": code_version(),
        "task_instruction_sha256": task.instruction_sha256,
        "staged_inputs": dict(staged),
        "disallowed_tools": list(disallowed_tools),
        "disallowed_tools_by_seat": {k: list(v) for k, v in disallowed_tools_by_seat.items()},
        "pipeline_completed": bool(pipeline_completed),
        "auto_skipped_stages": list(auto_skipped_stages),
        "stages_approved": list(stages_approved),
        "conclusion_path": str(conclusion.path),
        "conclusion_source": conclusion.source,
        "conclusion_chars": conclusion.chars,
        "conclusion_sha256": conclusion.sha256,
        "conclusion_text": conclusion_body if conclusion.scoreable else "",
        "refusals": list(conclusion.refusals),
        "log_file": str(log_file) if log_file else "",
        "log_result_line_written": bool(log_result_line_written),
        "deadline_hit": bool(deadline_hit),
    }
    payload.update(deadline.snapshot())
    payload.update(dict(witness))
    if extra:
        payload["extra"] = dict(extra)
    payload["exit_clause_failures"] = fire_exit_failures(payload)
    payload["status"] = "completed" if not payload["exit_clause_failures"] else "failed"
    return payload


def write_fire_meta(workspace: Path, payload: Mapping[str, Any]) -> Path:
    """Merge, never overwrite.

    A driver writes the arm label and the command line into ``_meta.json`` before the run
    starts, and a run that replaced the file would delete the only record of which arm
    produced it.
    """
    path = workspace / "_meta.json"
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, json.JSONDecodeError):
            existing = {}
    existing.update(payload)
    path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


@dataclass
class FireRunResult:
    workspace: Path
    meta: dict[str, Any]

    @property
    def exit_code(self) -> int:
        return fire_exit_code(self.meta)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.meta.get("status", "failed"),
            "task_id": self.meta.get("task_id"),
            "profile": self.meta.get("profile"),
            "workspace": str(self.workspace),
            "conclusion_source": self.meta.get("conclusion_source"),
            "conclusion_chars": self.meta.get("conclusion_chars"),
            "log_file": self.meta.get("log_file"),
            "exit_clause_failures": self.meta.get("exit_clause_failures", []),
            "deadline_hit": self.meta.get("deadline_hit"),
        }
