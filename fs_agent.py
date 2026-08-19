#!/usr/bin/env python3
"""Answer one FrontierScience-Research question, in one of two ways, and say which.

`FrontierScience-Research <https://arxiv.org/abs/2601.21165>`_ is sixty written science
examination questions. There is no dataset to load, no experiment to run, no reference
paper to read and nobody to ask: an examiner is handed the problem and the text of the
answer, and grades it against a rubric of independently weighted specifics. That is a
different shape from every other benchmark this repository has been pointed at, and the
front end has to be a different shape too.

Two profiles, which are the two arms of the comparison this adapter exists to make.

``--profile direct``
    One operator call. The problem, the task instruction, the browsing tools denied, and
    the reply is the answer. No stages, no gates, no reviewer, nothing else. This is the
    control: the same underlying model, the same words, the same denied tools, so that a
    paired difference is a statement about the pipeline rather than about the model.

``--profile ideate``
    AutoR, entered at Stage 02 and stopped there. One stage, its reviewer, and the
    ideation panel if it is asked for. Everything else -- routing, evolution rounds, the
    archive, the cross-reviewer, rounds past the first -- is off, because each of them is
    a second thing changing at the same time as the thing being measured.

**Why the walk starts above Stage 01.** The published protocol forbids browsing. Stage 01
is a literature survey whose evidence ledger can only be satisfied by citations, the gate
never checks that a URL resolves, and the rubric awards points for named literature
values -- so a run that cannot search does not merely fail to cite, it writes an invented
value into the place a real one belonged. Not running the stage is honest. Running it
without a search tool is not. Stopping at Stage 02 has a second effect worth naming: the
writing stage's figure floor is never consulted, so nothing in :mod:`src.utils` has to
move for this benchmark to run at all.

**What the exit code means, and why it is not "the pipeline said completed".** Measured
over the forty real ResearchClawBench runs under
``/rmeng_data/robtang/autor-rcb-rerun/workspaces/``: thirty-nine of forty wrote
``status: "completed"`` into ``_meta.json``, and the fortieth wrote no result line at all
-- it crashed, leaving seven keys, ``status: "running"`` and no ``pipeline_completed``.
Thirty-one of the forty (77.5%) had auto-skipped at least one stage and eight (20%) had
auto-skipped *the stage being scored*, and ``auto_skipped_stages`` appears in none of the
forty metadata files: it existed only in the stdout event stream. Both shapes are the same
defect from two directions -- neither the thirty-nine nor the one was distinguishable from
success by anything that read the metadata, because the false claim and the missing claim
read alike to a downstream that checks a field for truthiness. So this adapter writes the
fields that decide the verdict into ``_meta.json``, computes the exit code from that same
dictionary through :func:`src.frontierscience.fs_exit_code`, and refuses six separate ways
rather than one: the answer file has to exist, be inside the length band, have come from a
model rather than from the deterministic assembly, follow a procedure that ran to
completion, follow a walk that auto-skipped nothing, and be an answer rather than a plan
for one.

**The no-browsing protocol reaches every seat, and the record says which.** The published
protocol forbids browsing, and the ``ideate`` arm seats seven models: the executor, the
reviewer, and five ideation proposers. The denied-tool list is threaded to all seven
through :func:`build_manager`, and ``_meta.json`` records ``disallowed_tools_by_seat``
beside the run-level ``disallowed_tools`` -- which is the intersection over the seats, so
the run-level sentence cannot be true of one seat and false of six.
``disallowed_tools_requested`` is kept separately because a backend without the knob
(every codex seat: ``CodexOperator`` has no ``disallowed_tools`` parameter) applies
nothing, and a record that carried only the request would claim a denial that never
happened.

**What the transcript witnesses, and what a null in it means.**
:func:`src.frontierscience.read_transcript_witness` reads ``logs_raw.jsonl`` -- every
seat streams into one file -- and writes ``stop_reason``, ``truncated``,
``browsing_tool_calls``, ``browsing_tool_names``, ``backend_calls`` and
``output_tokens_total`` into the metadata. All six are always present and all six are
``None`` when there is no transcript, which is what a ``--fake-operator`` run and a run
that crashed before its first call both produce. ``None`` is not zero on purpose: a trial
clause reading ``browsing_tool_calls == 0`` must refuse a run that produced no evidence
rather than admit it for having none.

Nothing here reads stdin, and every prompt that would block raises instead of hanging.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
import traceback
from pathlib import Path
from typing import Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.approval_agent import AutomatedReviewer  # noqa: E402
from src.cross_reviewer import resolve_cross_reviewer  # noqa: E402
from src.evolution import EvolutionConfig  # noqa: E402
from src.frontierscience import (  # noqa: E402
    DEFAULT_FS_ANSWER_GUIDANCE,
    DEFAULT_FS_PROFILE,
    FS_ANSWER_GUIDANCE_CHOICES,
    FS_IDEATE_STAGE,
    FS_PROFILE_CHOICES,
    AnswerSynthesizer,
    DatasetRefused,
    DirectAnswerWriter,
    FsRow,
    FsRunResult,
    build_fs_goal,
    build_fs_meta,
    ensure_fs_workspace,
    export_answer,
    fs_runs_dir_for,
    fs_workspace_name,
    infer_fs_task_key,
    load_dataset,
    read_transcript_witness,
    resolve_answer_guidance,
    resolve_dataset_path,
    resolve_task_keys,
    rows_by_key,
    stages_approved_in,
    write_fs_meta,
)
from src.manager import ResearchManager  # noqa: E402
from src.operator import ClaudeOperator  # noqa: E402
from src.operator_codex import CodexOperator  # noqa: E402
from src.rcb import emit_event  # noqa: E402
from src.stage_graph import StageGraph  # noqa: E402
from src.terminal_ui import TerminalUI  # noqa: E402
from src.utils import (  # noqa: E402
    DEFAULT_OUTPUT_FORMAT,
    OUTPUT_FORMAT_CLI_CHOICES,
    WEB_SEARCH_MODE_CHOICES,
    build_run_paths,
    create_run_root,
    ensure_run_layout,
    resolve_output_format,
    resolve_stage,
    write_text,
)
from src.web_search import (  # noqa: E402
    assess_search_readiness,
    disallowed_tools_for,
    resolve_web_search_context,
    web_search_notice,
)


#: Seconds allowed per stage attempt in the ``ideate`` arm.
#:
#: Load-bearing, and three times the interactive default for a measured reason: the only
#: per-stage wall clock ever recorded on this box for a comparable configuration was
#: 2,100 seconds, and a trial run at 1,800 had twenty-eight of forty arms hit the ceiling.
#: A timeout below the distribution does not slow a treatment arm down, it converts it
#: into a refusal, and a refusal rate that differs between the arms is not a difference
#: anybody can interpret.
DEFAULT_FS_STAGE_TIMEOUT = 3600

#: Seconds allowed for the ``direct`` arm's single call. Measured over the **whole
#: sixty-row split**, a direct model call on this benchmark takes a mean of 120.1 s, a
#: median of 115.9 s and at most 290.1 s (60 of 60 judged, zero judge failures), and the
#: longest observed answer spent 34,313 output tokens -- so this is six times the slowest
#: call anybody has recorded here. The earlier figure of 134.5 s was the mean over a
#: balanced twenty-one-task draw and is superseded. It is not the stage timeout: there is
#: no stage, and reusing one number for two things is how a knob ends up tuned for the
#: wrong one.
DEFAULT_FS_ANSWER_TIMEOUT = 1800

#: Attempts per stage before the stage is auto-skipped. Two, where the interactive default
#: is unbounded: ``is_stuck`` only fires when three consecutive validation errors are
#: *identical*, and artifact errors carry filenames and counts, so an unbounded budget is
#: an unbounded budget. A real run on the sibling benchmark reached attempt nine on one
#: stage, and that run's seven stages cost sixty-five backend calls between them.
DEFAULT_FS_MAX_ATTEMPTS = 2

#: How many stages may be auto-skipped. **Zero, and this is the point of the adapter.**
#: An auto-skipped Stage 02 in a run whose only stage is Stage 02 is a run that produced
#: nothing while reporting that it finished. There is no budget here to spend.
DEFAULT_FS_MAX_AUTO_SKIPS = 0

#: The five skills every ``ideate`` run of this benchmark is given, unless
#: ``--no-forced-skills`` says otherwise.
#:
#: Forced rather than routed, for two reasons that are both about this adapter and not
#: about skills in general. The first is a live failure mode: ``select_run_skills`` fails
#: closed on an empty brief and refuses *every* task-scoped skill silently, so a run whose
#: ``user_input.txt`` has not landed yet gets none of them and says nothing about it. The
#: second is that the decision behind these five is not a claim about the shape of one
#: task -- it is a claim about a sixty-task population, measured on a paired trial of it,
#: which is neither what an ``applies_when`` predicate says nor what a pin says.
#:
#: They are written against that trial's measured losses. See each SKILL.md's "Why this is
#: here" for the task ids, the rubric item numbers and the per-item deltas. Not set for
#: the ``direct`` profile: the control arm is one operator call with no run directory to
#: install a skill into, and giving one arm guidance is the difference being measured.
FS_FORCED_SKILLS = frozenset({
    "bind-every-deliverable-to-the-file-that-is-graded",
    "every-printed-part-gets-its-own-answered-section",
    "grant-the-expected-reading-before-you-depart-from-it",
    "answer-in-the-symbols-the-problem-printed",
    "one-visible-line-per-quantity-the-answer-owes",
})

#: What ``skill_force_source`` records in ``run_config.json``. The symbol, not a prose
#: description of it: a reader who finds this string in a run config can grep the tree for
#: the set that produced it, which is the whole point of recording who forced them.
FS_FORCED_SKILLS_SOURCE = "fs_agent:FS_FORCED_SKILLS"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fs_agent",
        description="Answer one FrontierScience-Research question with AutoR or with one "
                    "direct model call.",
    )
    parser.add_argument(
        "--workspace",
        metavar="PATH",
        help="Directory to run in. Created if it does not exist. Defaults to a fresh "
             "directory named <task>_<profile>_<timestamp with microseconds> under the "
             "current directory, so two arms of one task launched in the same second "
             "cannot land in the same place.",
    )
    parser.add_argument(
        "--dataset",
        metavar="PATH",
        help="Path to research_test.jsonl. Falls back to $FRONTIERSCIENCE_DATASET and "
             "then to ~/.cache/frontierscience/research_test.jsonl. The file is checked "
             "against a pinned digest and refused if it does not match; it is never "
             "downloaded.",
    )
    parser.add_argument(
        "--task",
        metavar="KEY",
        help="Which question to answer, as a row index (43) or a task key (fs:043). "
             "Exactly one: this front end answers one question per run, and a set is the "
             "trial driver's job. Defaults to the key the workspace directory name "
             "carries (fs043_...), which is what a trial driver relies on; with neither, "
             "the run is refused rather than defaulted to row zero.",
    )
    parser.add_argument(
        "--profile",
        choices=list(FS_PROFILE_CHOICES),
        default=DEFAULT_FS_PROFILE,
        help="Which arm to run. 'direct' makes one operator call and keeps the reply. "
             "'ideate' runs AutoR entered at Stage 02 and stopped there. "
             f"Defaults to {DEFAULT_FS_PROFILE}.",
    )
    parser.add_argument(
        "--answer-guidance",
        choices=list(FS_ANSWER_GUIDANCE_CHOICES),
        default=DEFAULT_FS_ANSWER_GUIDANCE,
        help="How much the agent is told about what an answer is. 'paper' gives the "
             "fenced problem and nothing else, which is the published setup. 'minimal' "
             "adds the task instruction. 'coverage' additionally describes the rubric's "
             "shape, which is a declared experimental intervention and must be applied to "
             f"both arms or to neither. Defaults to {DEFAULT_FS_ANSWER_GUIDANCE}.",
    )
    parser.add_argument(
        "--model",
        help="Model for the execution backend. Defaults to the backend default. Always "
             "pass it together with --review-model: an arm is the pair.",
    )
    parser.add_argument(
        "--review-model",
        help="Model for the reviewer agent that replaces the human approval gate. "
             "Defaults to the backend default.",
    )
    parser.add_argument(
        "--operator",
        choices=["claude", "codex"],
        default="claude",
        help="Execution backend. Defaults to claude.",
    )
    parser.add_argument(
        "--review-operator",
        choices=["claude", "codex"],
        help="Backend for the reviewer agent. Defaults to the execution backend.",
    )
    parser.add_argument(
        "--codex-command",
        default="codex",
        metavar="BIN",
        help="Executable to invoke as the Codex CLI, used only with --operator codex. "
             "Defaults to `codex`.",
    )
    parser.add_argument(
        "--codex-sandbox",
        default="workspace-write",
        help="Codex CLI sandbox mode, used only with --operator codex. Defaults to "
             "workspace-write.",
    )
    parser.add_argument(
        "--answer-timeout",
        type=int,
        default=DEFAULT_FS_ANSWER_TIMEOUT,
        help="Seconds allowed for the direct arm's single call. Defaults to "
             f"{DEFAULT_FS_ANSWER_TIMEOUT}.",
    )
    parser.add_argument(
        "--first-stage",
        default=FS_IDEATE_STAGE,
        metavar="STAGE",
        help="Where the ideate arm's walk begins. Defaults to "
             f"{FS_IDEATE_STAGE}: under a no-browsing protocol the literature survey's "
             "evidence ledger can only be satisfied by invented citations, and the rubric "
             "awards points for named literature values, so a fabricated one displaces a "
             "real one.",
    )
    parser.add_argument(
        "--final-stage",
        default=FS_IDEATE_STAGE,
        metavar="STAGE",
        help="Where the ideate arm's walk stops. Defaults to "
             f"{FS_IDEATE_STAGE}. Nothing after it produces anything the examiner reads.",
    )
    parser.add_argument(
        "--ideation-panel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Widen Stage 02's hypotheses with a panel of proposers working from distinct "
             "lenses. On by default here, unlike everywhere else in this repository: the "
             "coverage hypothesis this adapter exists to test is a hypothesis about the "
             "panel, so a run without it is the control arm with extra steps.",
    )
    parser.add_argument(
        "--ideation-lenses",
        nargs="+",
        metavar="LENS",
        help="Seat only these ideation lenses. Defaults to all five.",
    )
    parser.add_argument(
        "--ideation-models",
        nargs="+",
        metavar="LENS=MODEL",
        help="Assign a model per ideation lens, as lens=model or lens=backend:model.",
    )
    parser.add_argument(
        "--ideas-per-proposer",
        type=int,
        default=2,
        help="Candidate hypotheses each proposer may return. Defaults to 2.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=DEFAULT_FS_MAX_ATTEMPTS,
        help="Attempts allowed per stage before it is auto-skipped. Defaults to "
             f"{DEFAULT_FS_MAX_ATTEMPTS}.",
    )
    parser.add_argument(
        "--stage-timeout",
        type=int,
        default=DEFAULT_FS_STAGE_TIMEOUT,
        help="Seconds allowed per stage attempt in the ideate arm. Defaults to "
             f"{DEFAULT_FS_STAGE_TIMEOUT}, which is above the only per-stage duration ever "
             "measured for a comparable configuration on this machine.",
    )
    parser.add_argument(
        "--max-auto-skips",
        type=int,
        default=DEFAULT_FS_MAX_AUTO_SKIPS,
        help="How many stages may be auto-skipped after exhausting retries. Defaults to "
             f"{DEFAULT_FS_MAX_AUTO_SKIPS}: the run has one stage, and skipping it "
             "produces a workspace that looks finished and holds nothing.",
    )
    parser.add_argument(
        "--web-search",
        choices=list(WEB_SEARCH_MODE_CHOICES),
        default="off",
        help="Search provider for the operators. Defaults to off here, unlike everywhere "
             "else in this repository: the published protocol for this benchmark forbids "
             "browsing, and 'off' both offers no search tool and denies WebSearch and "
             "WebFetch to every Claude seat the run builds -- the executor, the reviewer "
             "and each ideation proposer. The codex backend has no denied-tool parameter, "
             "so a codex run records that it denied nothing rather than claiming it did.",
    )
    parser.add_argument(
        "--disallowed-tools",
        nargs="+",
        metavar="TOOL",
        help="Tool names to deny the agent, overriding what --web-search implies. Both "
             "arms must be given the same list for a paired comparison to mean anything, "
             "so the metadata records the list that was asked for, the list every seat "
             "actually carries, and the per-seat breakdown -- three fields, because a "
             "backend without the knob makes the first two differ.",
    )
    parser.add_argument(
        "--cross-review",
        choices=["auto", "gemini", "off"],
        default="off",
        help="Independent second opinion on each approval from a different model family. "
             "Defaults to off here: it is a second thing changing beside the thing being "
             "measured, and it is not part of either arm's description.",
    )
    parser.add_argument(
        "--cross-review-model",
        help="Model for the cross-model reviewer. Defaults to the cross reviewer's own "
             "default.",
    )
    parser.add_argument(
        "--runs-dir",
        metavar="PATH",
        help="Where the AutoR run tree goes. Defaults to <workspace>/.autor, which keeps "
             "a run self-contained so a trial can archive or delete one directory.",
    )
    parser.add_argument(
        "--output-format",
        choices=list(OUTPUT_FORMAT_CLI_CHOICES),
        default=DEFAULT_OUTPUT_FORMAT,
        help="Deliverable format recorded on the run. The examiner reads answer.md either "
             f"way; this only reaches the run config. Defaults to {DEFAULT_OUTPUT_FORMAT}.",
    )
    parser.add_argument(
        "--attempt-index",
        type=int,
        default=0,
        help="Which repeat of this (task, arm) this run is, recorded in the metadata so "
             "that between-attempt variance can be estimated instead of assumed. "
             "Defaults to 0.",
    )
    parser.add_argument(
        "--print-goal",
        action="store_true",
        help="Print the goal the agent would be given and exit, without running anything. "
             "The prompt is the instrument, so it has to be readable without spending a "
             "run to see it.",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Skip the answer-producing step and only re-export the most recent run in "
             "the workspace. Useful after an interrupted run.",
    )
    parser.add_argument(
        "--no-forced-skills",
        action="store_true",
        help="Run the ideate arm without the five skills this adapter installs on every "
             "run of this benchmark. This is the control arm and it is not optional: a "
             "run with the skills and a run without them are two configurations, and "
             "both arms have to come out of the same binary for the difference between "
             "them to be a measurement. Has no effect on the direct profile, which has "
             "no run directory to install a skill into.",
    )
    parser.add_argument(
        "--fake-operator",
        action="store_true",
        help="Use the fake operator instead of a real backend. For smoke-testing the "
             "adapter. The answer it produces is marked in its first line and in "
             "_meta.json, because a smoke artifact clears every length check.",
    )
    return parser.parse_args(argv)


def default_model_for(backend: str) -> str:
    return "default" if backend == "codex" else "sonnet"


def create_operator(
    backend: str,
    *,
    model: str,
    codex_sandbox: str,
    fake_mode: bool,
    ui: TerminalUI,
    stage_timeout: int,
    codex_command: str = "codex",
    disallowed_tools: Sequence[str] = (),
):
    """Build the execution backend.

    No ``web_search_mcp`` parameter and no ``codex_web_search``: this benchmark's protocol
    forbids browsing, so handing either operator a search tool is not a configuration this
    front end offers. ``--web-search`` still exists because it is what computes the denied
    tool list and because a run that wanted to measure the protocol's cost could set it --
    but the default is ``off`` and the search-tool wiring is deliberately absent rather
    than merely unset.

    ``disallowed_tools`` reaches the Claude backend and not the codex one, because
    ``CodexOperator`` has no such parameter. That asymmetry is recorded rather than
    papered over: :func:`operator_seats` reads the list back off whatever was built, so a
    codex run's metadata says it denied nothing.
    """
    if backend == "codex":
        return CodexOperator(
            model=model,
            codex_sandbox=codex_sandbox,
            fake_mode=fake_mode,
            ui=ui,
            stage_timeout=stage_timeout,
            command=codex_command,
            web_search=False,
        )
    return ClaudeOperator(
        model=model,
        fake_mode=fake_mode,
        ui=ui,
        stage_timeout=stage_timeout,
        web_search_mcp=False,
        disallowed_tools=disallowed_tools,
    )


def resolve_task_row(
    *, dataset: str | None, task: str | None, workspace: Path | None
) -> FsRow:
    """The one row this run answers, or a refusal naming what was missing.

    Three sources for the key, in order: ``--task``, the workspace directory name, and
    nothing. The third is a refusal rather than a default, because there is no defensible
    default -- answering row zero because nobody said otherwise produces a result file
    that names a task the operator never chose, and every digest in it would agree with
    itself.
    """
    # The key is resolved before the file is opened. Reading sixty rows to discover
    # that nobody said which one is wasted work, and it makes the refusal depend on
    # whether a dataset happens to be on the machine: the message a user needs is
    # "name a task", not "no dataset at ~/.cache/...".
    key = task.strip() if task and task.strip() else None
    if key is None and workspace is not None:
        key = infer_fs_task_key(workspace)
    if key is None:
        raise DatasetRefused(
            "No task selected. Pass --task (a row index like 43, or a key like fs:043), "
            "or name the workspace directory fs043_<anything> so the key can be read off "
            "it. There is no default: answering an unnamed question would produce a "
            "result file whose digests all agree with each other and with nothing else."
        )
    rows = load_dataset(dataset)
    selected = resolve_task_keys(rows, tasks=key)
    if len(selected) != 1:
        raise DatasetRefused(
            f"--task {key!r} selects {len(selected)} rows; this front end answers exactly "
            "one question per run. Use the trial driver to run a set."
        )
    return rows_by_key(rows)[selected[0]]


def resolve_workspace(args: argparse.Namespace, key: str) -> Path:
    """Where this run happens: the flag, or a fresh timestamped directory."""
    if args.workspace:
        return Path(args.workspace).expanduser().resolve()
    return (Path.cwd() / fs_workspace_name(key, args.profile)).resolve()


def build_manager(
    args: argparse.Namespace,
    *,
    workspace: Path,
    runs_dir: Path,
    operator,
    ui: TerminalUI,
    review_backend: str,
    review_model: str,
    web_search_context: str | None = None,
    disallowed_tools: Sequence[str] = (),
) -> ResearchManager:
    """Assemble the ``ideate`` arm: one stage, its reviewer, and nothing else.

    Every argument that is off is off for the same reason: it is a second thing changing
    beside the thing being measured. Routing chooses a different next stage, which there
    is not one of; evolution rounds buy further attempts at a stage that already passed,
    which doubles the arm's cost without being part of its description; the archive stores
    a fitness in [0, 1] and this benchmark's score is a rubric total out of ten; the
    cross-reviewer adds a second model family to a comparison whose whole claim is that
    only one thing differs.

    The ideation panel is assigned after construction because it is an attribute of the
    manager and not a constructor keyword. That is a real distinction rather than a
    stylistic one -- passing it as a keyword raises ``TypeError`` -- and it is the shape
    ``rcb_agent.py`` already uses.

    **``disallowed_tools`` reaches every seat this function builds, not just the one it
    is handed.** The published protocol for this benchmark is "no browsing", and this arm
    seats seven models: the executor, the reviewer, and five proposers. Denying the
    browsing tools to the executor alone leaves six that can search, in the arm whose
    whole claim is that it differs from the control by the pipeline and not by what the
    models could reach -- so a treatment-arm win would be indistinguishable from a win at
    browsing while the artifact recorded that browsing was denied. The two constructors
    below take the list with a default of ``()``, which is every other caller in the tree.
    """
    reviewer = AutomatedReviewer(
        review_backend,
        codex_command=args.codex_command,
        model=review_model,
        fake_mode=args.fake_operator,
        ui=ui,
        stage_timeout=args.stage_timeout,
        # There is no human on this run, and aborting at the approval gate forfeits the
        # question outright.
        unattended=True,
        disallowed_tools=disallowed_tools,
    )
    manager = ResearchManager(
        project_root=REPO_ROOT,
        runs_dir=runs_dir,
        operator=operator,
        ui=ui,
        reviewer=reviewer,
        approval_mode="agent",
        review_operator=review_backend,
        review_model=review_model,
        unattended=True,
        max_auto_skips=args.max_auto_skips,
        max_stage_attempts=args.max_attempts,
        max_rounds=1,
        # Passed in rather than resolved here. `resolve_web_search_context` needs the
        # readiness assessment, `run` has already made it, and making it twice is how the
        # manager ends up describing a search setup the operator was not built with.
        web_search_context=web_search_context,
        web_search_mode=args.web_search,
        artifact_roots=[workspace],
        stage_graph=StageGraph.linear(),
        routing_mode="off",
        evolution=EvolutionConfig(rounds=0),
        archive=None,
        cross_reviewer=resolve_cross_reviewer(args.cross_review, args.cross_review_model),
    )
    if args.ideation_panel:
        from src.ideation_panel import IdeationPanel, apply_lens_models, resolve_lenses

        manager.ideation_panel = IdeationPanel(
            apply_lens_models(resolve_lenses(args.ideation_lenses), args.ideation_models),
            backend_name=review_backend,
            model=review_model,
            fake_mode=args.fake_operator,
            ui=ui,
            stage_timeout=args.stage_timeout,
            ideas_per_proposer=args.ideas_per_proposer,
            disallowed_tools=disallowed_tools,
        )
    # Set after construction for the same reason the panel is: these are attributes of the
    # manager rather than constructor keywords. `skill_discipline` is deliberately left
    # unset -- FrontierScience's `biology` is not one of `DISCIPLINE_PREFIXES` (the pack
    # spells that field `life`), so assigning the subject straight through would withhold
    # every `life-*` skill from a biology run and install no field skills at all. Mapping
    # `biology` to `life` is a separate decision with its own evidence, and it must not
    # ride along on this one.
    #
    # Both attributes, and clearing `skill_force` alone would not have been enough. The
    # five carry `applies_when: intermediate derivations`, which is a phrase in this
    # benchmark's own closing instruction and occurs in 60 of its 60 task statements -- so
    # with the force cleared the shape filter installs exactly the same five and announces
    # them under the shape banner. Measured on a `--fake-operator` run: the control arm
    # differed from the treatment arm by one paragraph of prompt. `skill_withhold` is what
    # makes `--no-forced-skills` an arm rather than a rewording.
    manager.skill_force = frozenset() if args.no_forced_skills else FS_FORCED_SKILLS
    manager.skill_force_source = FS_FORCED_SKILLS_SOURCE
    manager.skill_withhold = FS_FORCED_SKILLS if args.no_forced_skills else frozenset()
    return manager


#: How a seat is named in ``disallowed_tools_by_seat``. One prefix rather than a bare lens
#: key so that a reader of the metadata can tell the five proposers from the two seats that
#: are not proposers without holding the lens vocabulary in their head.
FS_PROPOSER_SEAT_PREFIX = "proposer:"


def operator_seats(operator, manager: ResearchManager | None = None) -> dict[str, tuple[str, ...]]:
    """Every model seat a run built, and the denied-tool list each one is carrying.

    Read off the objects rather than assembled from the flags, because the flag says what
    was asked for and the object says what was applied, and those are two different
    sentences whenever a backend has no knob for it -- ``CodexOperator`` has no
    ``disallowed_tools`` parameter, so a codex seat reports ``()`` here however the run
    was invoked. Recording the request instead would put "WebSearch and WebFetch were
    denied" in the artifact of a run that denied nothing.

    Seven seats on the ``ideate`` arm and one on ``direct``. The count is the point: the
    first version of this adapter denied the browsing tools to the executor and recorded a
    single run-level list, which was a true statement about one seat published as a
    statement about the run.
    """
    seats: dict[str, tuple[str, ...]] = {
        "executor": tuple(getattr(operator, "disallowed_tools", ()))
    }
    if manager is None:
        return seats
    reviewer = getattr(manager, "reviewer", None)
    if reviewer is not None:
        seats["reviewer"] = tuple(getattr(reviewer, "disallowed_tools", ()))
    panel = getattr(manager, "ideation_panel", None)
    if panel is not None:
        for key, member in sorted(getattr(panel, "_members", {}).items()):  # noqa: SLF001
            seats[f"{FS_PROPOSER_SEAT_PREFIX}{key}"] = tuple(getattr(member, "disallowed_tools", ()))
    return seats


def tools_denied_on_every_seat(seats: Mapping[str, Sequence[str]]) -> tuple[str, ...]:
    """The tools no model in this run could reach: the intersection, in first-seen order.

    A run-level sentence about a run with seven seats has to be true of all seven. The
    intersection is the only summary with that property -- a union would let one denied
    seat speak for six undenied ones, which is the shape the artifact had before
    :func:`operator_seats` existed.
    """
    if not seats:
        return ()
    ordered = list(dict.fromkeys(tool for tools in seats.values() for tool in tools))
    return tuple(tool for tool in ordered if all(tool in tools for tools in seats.values()))


def skills_this_run_got(manager: ResearchManager | None) -> tuple[list[str], list[str]]:
    """``(forced and installed, forced and withheld)``, for the record and for the digest.

    Read off ``Manager._forced_skills``, which is the set the installer intersected with
    what it actually wrote into the run's ``.claude/skills/``, and never off
    ``args.no_forced_skills`` or off :data:`FS_FORCED_SKILLS`. The flag says what was
    asked for; a name that has been renamed out of the pack, or withheld by a filter the
    front end does not know about, is asked for by the flag and installed by nothing --
    and the arm would then be described in its own metadata as carrying five skills it
    never saw. The same rule as ``disallowed_tools``: what the seats are carrying, not
    what the flags requested.

    The second half is a subtraction rather than a copy of ``manager.skill_withhold``, for
    the same reason: what a comparison needs to know is which of this benchmark's forced
    names did not reach the model, whatever stopped them.

    ``None`` covers the two runs that have no manager -- the ``direct`` arm, which makes
    one call with no run directory to install a skill into, and ``--export-only``, which
    observed no walk at all. Both get ``([], [])``: nothing was installed and, since this
    front end forces nothing on a run without a manager, nothing was withheld either.
    """
    if manager is None:
        return [], []
    installed = frozenset(getattr(manager, "_forced_skills", None) or frozenset())
    return sorted(installed), sorted(FS_FORCED_SKILLS - installed)


def run(args: argparse.Namespace) -> FsRunResult:
    started_at = time.monotonic()
    guidance = resolve_answer_guidance(args.answer_guidance)
    dataset_path = resolve_dataset_path(args.dataset)
    workspace_hint = Path(args.workspace).expanduser().resolve() if args.workspace else None
    row = resolve_task_row(dataset=args.dataset, task=args.task, workspace=workspace_hint)
    workspace = resolve_workspace(args, row.key)

    ideate = args.profile == "ideate"
    goal = build_fs_goal(
        row.problem,
        workspace=workspace if ideate else None,
        answer_guidance=guidance,
    )
    # Before the workspace is created, so that reading the contract leaves nothing behind.
    # A directory a `--print-goal` produced is a directory a trial driver's sweep would
    # later find and count as a run that was started.
    if args.print_goal:
        print(goal)
        return FsRunResult(workspace=workspace, meta={"printed_goal": True, "status": "printed"})

    ensure_fs_workspace(workspace)
    # Measured, not copied from the pin. `load_dataset` refuses a file whose digest is not
    # `FS_DATASET_SHA256`, so today the two agree by construction -- and a field that
    # agrees by construction is not the one the contract names. What a result file has to
    # say is which bytes were answered, which stays true if the pin is ever relaxed.
    dataset_sha256 = hashlib.sha256(dataset_path.read_bytes()).hexdigest()

    operator_backend = args.operator
    model = args.model or default_model_for(operator_backend)
    review_backend = args.review_operator or operator_backend
    review_model = args.review_model or default_model_for(review_backend)
    runs_dir = Path(args.runs_dir).expanduser().resolve() if args.runs_dir else fs_runs_dir_for(workspace)

    # stdout carries the run log, so the UI must never try to read from stdin. The stream
    # is passed explicitly rather than defaulted: `TerminalUI`'s default is bound to
    # `sys.stdout` at import time, so a caller that redirects stdout -- a test, or a
    # driver capturing one arm's log -- gets the frames on the real terminal anyway.
    ui = TerminalUI(output_stream=sys.stdout, interactive=False)
    emit_event(
        {
            "type": "system",
            "subtype": "init",
            "agent": "autor-frontierscience",
            "profile": args.profile,
            "task": row.key,
            "subject": row.subject,
            "model": model,
            "review_model": review_model,
            "answer_guidance": guidance,
            "workspace": str(workspace),
        }
    )

    # Not assessed under `off`, which is this front end's default: the assessment exists
    # to say what a run that is going to search can search with, and this one is not.
    readiness = (
        None if args.web_search == "off"
        else assess_search_readiness(operator=operator_backend, codex_sandbox=args.codex_sandbox)
    )
    notice, level = web_search_notice(args.web_search, readiness=readiness)
    emit_event({"type": "progress", "stage": "web_search", "level": level, "message": notice})
    ui.show_status(notice, level=level)
    web_search_context = (
        None if args.web_search == "off"
        else resolve_web_search_context(args.web_search, readiness=readiness)
    )

    disallowed_tools = (
        tuple(args.disallowed_tools)
        if args.disallowed_tools
        else disallowed_tools_for(args.web_search)
    )
    operator = create_operator(
        operator_backend,
        model=model,
        codex_sandbox=args.codex_sandbox,
        fake_mode=args.fake_operator,
        ui=ui,
        stage_timeout=args.stage_timeout if ideate else args.answer_timeout,
        codex_command=args.codex_command,
        disallowed_tools=disallowed_tools,
    )

    pipeline_completed = False
    auto_skipped_stages: list[str] = []
    stages_approved: list[str] = []
    direct_answer: str | None = None
    paths = None
    manager = None

    if args.export_only:
        # `pipeline_completed` keeps the False it was initialised with, and that is the
        # record rather than an oversight: a re-export cannot observe the walk that
        # produced the run tree, so it must not claim anything about it. The exit code is
        # therefore non-zero, which is correct -- a recovered workspace is evidence to
        # look at, not a scored result. Nothing in this branch may set it true.
        run_root = _latest_run_root(runs_dir)
        if run_root is None:
            raise FileNotFoundError(f"No AutoR run found under {runs_dir}; nothing to export.")
        paths = build_run_paths(run_root)
        stages_approved = stages_approved_in(paths)
    elif ideate:
        manager = build_manager(
            args,
            workspace=workspace,
            runs_dir=runs_dir,
            operator=operator,
            ui=ui,
            review_backend=review_backend,
            review_model=review_model,
            web_search_context=web_search_context,
            disallowed_tools=disallowed_tools,
        )
        try:
            pipeline_completed = manager.run(
                goal,
                skip_intake=True,
                output_format=resolve_output_format(args.output_format),
                resources=None,
                start_stage=resolve_stage(args.first_stage),
                final_stage=resolve_stage(args.final_stage),
            )
        except Exception:  # noqa: BLE001 - a crashed pipeline must still export what it produced
            emit_event({"type": "error", "where": "pipeline", "traceback": traceback.format_exc()})
        auto_skipped_stages = list(manager.auto_skipped_stages)
        run_root = manager.last_run_paths.run_root if manager.last_run_paths else _latest_run_root(runs_dir)
        if run_root is not None:
            paths = build_run_paths(run_root)
            stages_approved = stages_approved_in(paths)
    else:
        paths = _fresh_run_tree(runs_dir, goal)
        direct_answer = DirectAnswerWriter(operator)(paths=paths, goal=goal)
        # There is no pipeline in this arm, so "completed" is the honest name for the one
        # thing that had to happen: the single call came back with usable text. Recorded
        # under the same key the other arm uses because the exit code reads one field, and
        # two names for one clause is how a downstream ends up checking neither.
        pipeline_completed = direct_answer is not None

    answer = export_answer(
        workspace=workspace,
        paths=paths,
        direct_answer=direct_answer,
        stages_approved=stages_approved,
        synthesize=AnswerSynthesizer(operator) if ideate else None,
        problem=row.problem,
    )
    # Read off the objects that were built, after they have been used. What the flags
    # asked for is `disallowed_tools`; what the seven seats are carrying is this, and the
    # two disagree on any backend without the knob.
    seats = operator_seats(operator, manager)
    forced_skills, withheld_skills = skills_this_run_got(manager)
    meta = build_fs_meta(
        workspace=workspace,
        task=row.key,
        profile=args.profile,
        answer_guidance=guidance,
        model=model,
        review_model=review_model,
        operator=operator_backend,
        answer=answer,
        pipeline_completed=pipeline_completed,
        auto_skipped_stages=auto_skipped_stages,
        stages_approved=stages_approved,
        disallowed_tools=tools_denied_on_every_seat(seats),
        disallowed_tools_requested=disallowed_tools,
        disallowed_tools_by_seat=seats,
        skill_forced=forced_skills,
        skill_withheld=withheld_skills,
        witness=read_transcript_witness(paths),
        dataset_path=dataset_path,
        dataset_sha256=dataset_sha256,
        run_id=paths.run_root.name if paths is not None else "",
        duration_seconds=round(time.monotonic() - started_at),
        attempt_index=args.attempt_index,
        fake_operator=args.fake_operator,
        extra={
            "subject": row.subject,
            "export_only": bool(args.export_only),
            "task_block": row.task_block(),
        },
    )
    write_fs_meta(workspace, meta)
    return FsRunResult(workspace=workspace, meta=meta)


def _latest_run_root(runs_dir: Path) -> Path | None:
    if not runs_dir.exists():
        return None
    candidates = sorted(path for path in runs_dir.iterdir() if path.is_dir())
    return candidates[-1] if candidates else None


def _fresh_run_tree(runs_dir: Path, goal: str):
    """A run directory for the direct arm's single call.

    The direct arm has no pipeline, but the operator seam it uses writes prompts, session
    ids and the raw JSONL transcript into a run tree, and the transcript is the only
    witness for whether the agent reached for a browsing tool. A call with nowhere to log
    is a call nobody can audit afterwards, which on a benchmark whose protocol is "no
    browsing" is the one thing that must not be true.
    """
    paths = build_run_paths(create_run_root(runs_dir))
    ensure_run_layout(paths)
    write_text(paths.user_input, goal)
    return paths


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run(args)
    except Exception as exc:  # noqa: BLE001 - the caller only sees stdout and the exit code
        emit_event({"type": "result", "status": "failed", "error": str(exc)})
        print(traceback.format_exc(), file=sys.stderr)
        return 1

    if result.meta.get("printed_goal"):
        return 0
    emit_event({"type": "result", **result.to_dict()})
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
