"""Run a paired FrontierScience-Research trial, several answers at a time, and survive
being killed.

The shell around :mod:`src.fs_trial`. Everything here touches a process, a clock or a
filesystem; everything that decides anything lives in the module and is a pure function
of already-parsed data, because the alternative is validating multi-day
kill-and-restart behaviour by spending multi-day kill-and-restart wall clock. The lock,
the ``/proc`` census, the atomic state writes and the process-group kill are
:mod:`src.trial_driver`, shared with the ResearchClawBench driver rather than copied from
it -- a copy inherits the code and not the reason, and the failure of two copies is a
*pair* of drivers whose answers to "is anyone else spending the quota" disagree.

**Four operational facts this shell is bent around**, each measured rather than assumed:

1. This driver runs several answers at once and one judge call at a time. Answers are
   independent processes against a per-model quota that this box has been observed
   exhausting with three concurrent AutoR runs; the judge is a single endpoint where 34
   of 34 serial calls succeeded with zero retries, and where the sibling benchmark's
   concurrent calls caused most of its failures.
2. The judge is spent **once**, in one continuous final pass. Scoring in the loop would
   put days between the first workspace's grading and the last, so a judge that drifted
   across the trial would ride into the published difference unmeasured. The early
   warning that buys is free here anyway: nine of the ten admission clauses read
   ``_meta.json``, so this driver announces a run's admission the moment it finishes,
   without a judge call.
3. There is no per-run wall clock, only a stall watchdog on ``logs_raw.jsonl``'s mtime
   and a trial deadline after which no *new* run starts. AutoR's real durations on the
   sibling benchmark run from 11.9 to 26.5 hours with a median of 15.2; any cap short
   enough to catch a hang is short enough to kill a run that was going to finish.
4. State is written three times per run -- before the child exists, with its pid, and
   after it exits with the harvest -- tmp plus ``os.replace``, because the state
   directory is on shared NFS. A ``kill -9`` costs the runs in flight and nothing else.

**AutoR's wall clock and score on this benchmark are UNMEASURED.** No real
(non-fake-operator) run of the pipeline arm against FrontierScience-Research exists. The
dry-run path (``operator: "fake"``, ``judge_kind: "fake"`` in the plan) fabricates
workspaces and verdicts instead: it exercises the real lock, the real
``Popen(start_new_session=True)`` children, the real state machine, the real metadata
builder, the real transcript witness, the real admission gate, the real scorer's pure
half and the real report -- everything except the two things that cost money.

Usage::

    python3 tools/fs_trial.py plan   --plan configs/fs_trial_001.json   # freeze it
    python3 tools/fs_trial.py run    --plan configs/fs_trial_001.json   # resumable
    python3 tools/fs_trial.py report --plan configs/fs_trial_001.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.frontierscience import (  # noqa: E402
    FS_DATASET_POINTS_PER_ROW,
    FS_FALLBACK_MARKER,
    FS_IDEATE_STAGE,
    FsAnswer,
    FsRow,
    answer_path_for,
    build_fs_meta,
    ensure_fs_workspace,
    fs_runs_dir_for,
    fs_workspace_name,
    read_transcript_witness,
    write_fs_meta,
)
from src.fs_scoring import build_result, draw_record  # noqa: E402
from src.fs_trial import (  # noqa: E402
    FsArmEvidence,
    FsRefusal,
    FsRunEnvironment,
    FsTrialPlan,
    admit_fs_arm,
    classify_fs_run,
    collect_fs_pairs,
    format_fs_trial_report,
    fs_driver_clause,
    next_actions,
)
from src.utils import build_run_paths, create_run_root, ensure_run_layout, write_text  # noqa: E402

# The benchmark-agnostic half of every paired-trial driver. Imported into this module's
# own namespace rather than reached through the package, for the same reason
# `tools/rcb_trial.py` does it: `tests/test_fs_trial_driver.py` loads this file with
# `exec_module` and rebinds `tool.foreign_runs` to keep a preflight refusal about this
# box out of a test about something else, and the call sites below resolve the name in
# *these* globals.
from src.trial_driver import (  # noqa: E402,F401
    acquire_lock,
    autor_pids,
    boot_id,
    foreign_runs,
    git_dirty,
    git_head,
    heartbeat,
    kill_group,
    read_json,
    release_lock,
    write_json,
)

#: What one of *this* driver's own children looks like in ``/proc``, for
#: :func:`src.trial_driver.autor_pids`.
#:
#: Deliberately this driver's two and not :data:`src.trial_driver.AGENT_SCRIPT_NAMES`.
#: The question here is "is the child I recorded still alive", asked as a membership test
#: against a pid this driver wrote down itself, so another benchmark's live agent has no
#: business in the set -- and the set is narrow rather than a bare ``/proc`` listing
#: because the operating system hands a dead driver's pid to somebody else's process,
#: which is the ordinary case and not the rare one.
#:
#: ``fake-run`` is a subcommand of this file rather than an agent, and it is here because
#: the dry run launches it as a child exactly like a real run.
OUR_RUN_MARKERS = ("fs_agent.py", "fs_trial.py fake-run")

#: How often the loop wakes to reap children and re-plan. A second: the runs take hours,
#: so the polling cost is nothing, and a long poll is a driver that notices a stall late
#: and a dry run that spends its whole wall clock inside ``sleep``.
POLL_SECONDS = 1.0

#: Tries per judge draw before the draw is written off. Two, and the loop is over
#: *files* of one draw each, so the judge's worst minute costs one draw rather than a
#: whole arm's replication.
JUDGE_TRIES = 2

#: Attempts to find an unused workspace name before giving up. The name carries
#: microseconds, so a collision means two launches inside the same microsecond; five is a
#: bound rather than a schedule, and the sibling driver's answer here -- ``exist_ok=True``
#: plus a 1.1 second sleep on a name with second granularity -- put two arms of one task
#: in one directory, where they overwrote each other's deliverable and made the paired
#: difference identically zero.
WORKSPACE_NAME_TRIES = 5


# ---------------------------------------------------------------------------
# Reading a finished workspace
# ---------------------------------------------------------------------------


def harvest(workspace: Path, *, task_key: str) -> dict[str, Any]:
    """Everything the admission gate and the environment digest read off a workspace.

    All of it out of ``_meta.json`` and the answer file, and none of it out of the
    driver's memory of what it launched. The metadata is written by the party the gate
    constrains, which is why ``answer_not_fallback`` has a second witness -- the marker on
    the answer's own first line -- and why ``meta_present`` is recorded separately: a run
    that wrote no metadata at all and a run whose metadata says it failed are different
    events with different policies, and a reader that checks a field for truthiness
    cannot tell them apart.

    ``task_key`` is passed in and not read out of the metadata. A run the watchdog killed
    has no ``_meta.json``, and a state file with no task key is invisible to
    :func:`src.fs_trial.next_actions`, which then sees no attempts, relaunches attempt 1,
    and does it again for ever.
    """
    meta = read_json(workspace / "_meta.json")
    answer = answer_path_for(workspace)
    first_line_is_fallback: bool | None = None
    if answer.is_file():
        try:
            with answer.open("r", encoding="utf-8", errors="replace") as handle:
                first_line_is_fallback = handle.readline().strip().startswith(
                    FS_FALLBACK_MARKER
                )
        except OSError:  # pragma: no cover - unreadable file on a shared filesystem
            first_line_is_fallback = None
    return {
        "meta_present": bool(meta),
        "meta_status": meta.get("status"),
        "meta_pipeline_completed": meta.get("pipeline_completed"),
        "meta_stages_approved": meta.get("stages_approved"),
        "meta_auto_skipped_stages": meta.get("auto_skipped_stages"),
        "meta_answer_source": meta.get("answer_source"),
        "meta_model": meta.get("model"),
        "meta_review_model": meta.get("review_model"),
        "meta_profile": meta.get("profile"),
        "meta_answer_guidance": meta.get("answer_guidance"),
        "meta_task": meta.get("task") or task_key,
        "meta_task_instruction_sha256": meta.get("task_instruction_sha256"),
        "meta_dataset_sha256": meta.get("dataset_sha256"),
        "meta_disallowed_tools": meta.get("disallowed_tools"),
        "meta_run_id": meta.get("run_id"),
        "answer_path": str(answer),
        "answer_chars": meta.get("answer_chars"),
        "answer_refusals": meta.get("refusals"),
        "answer_first_line_is_fallback": first_line_is_fallback,
        "operator": meta.get("operator"),
        # Null is not zero, all the way through. `read_transcript_witness` writes `None`
        # into every one of these when there is no transcript, and the admission clauses
        # refuse a null rather than reading it as a clean run.
        "stop_reason": meta.get("stop_reason"),
        "truncated": meta.get("truncated"),
        "browsing_tool_calls": meta.get("browsing_tool_calls"),
        "browsing_tool_names": meta.get("browsing_tool_names"),
        "backend_calls": meta.get("backend_calls"),
        "output_tokens_total": meta.get("output_tokens_total"),
        "duration_seconds": meta.get("duration_seconds"),
        # The Responses path's half of `answer_not_truncated`. Absent on the Claude path
        # and absent today on the codex path too, which is why a codex arm is refused
        # rather than admitted: see the clause.
        "responses_status": meta.get("responses_status"),
        "responses_incomplete_reason": meta.get("responses_incomplete_reason"),
    }


# ---------------------------------------------------------------------------
# Launching runs
# ---------------------------------------------------------------------------


def state_path(plan: FsTrialPlan, task: str, arm: str, attempt: int) -> Path:
    slug = task.replace(":", "")
    return Path(plan.state_dir) / "runs" / f"{slug}.{arm}.a{attempt}.json"


def all_states(plan: FsTrialPlan) -> list[dict[str, Any]]:
    directory = Path(plan.state_dir) / "runs"
    return [read_json(path) for path in sorted(directory.glob("*.json"))]


def make_workspace(plan: FsTrialPlan, task: str, arm: str) -> Path:
    """A fresh directory per attempt, created with ``exist_ok=False``.

    Both halves are the sibling driver's scar. It named workspaces to the second and
    created them with ``exist_ok=True``, so two arms of one task launched inside one
    second landed in the same directory, overwrote each other's deliverable, and produced
    a paired difference of exactly zero -- a null result manufactured by a filename.
    :func:`src.frontierscience.fs_workspace_name` carries microseconds and the arm label;
    ``exist_ok=False`` is what turns the remaining collision from silent into loud.
    """
    base = Path(plan.state_dir) / "workspaces"
    base.mkdir(parents=True, exist_ok=True)
    # `candidate` survives the loop and is named in the refusal below. No initialiser
    # above it, because a bound of zero is not a state worth writing an unreachable branch
    # for: the retry count is asserted at `WORKSPACE_NAME_TRIES` by the collision test.
    for _try in range(WORKSPACE_NAME_TRIES):
        candidate = base / fs_workspace_name(task, arm)
        try:
            candidate.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue
        return candidate
    raise SystemExit(
        f"could not find an unused workspace name for {task}/{arm} in "
        f"{WORKSPACE_NAME_TRIES} tries; the last one taken was {candidate}. The name "
        "carries microseconds and the arm label, so this means something else is creating "
        "directories under "
        f"{base}. Refusing rather than reusing: the sibling driver's `exist_ok=True` put "
        "two arms of one task in one directory, where they overwrote each other's "
        "deliverable and made the paired difference identically zero."
    )


def agent_argv(plan: FsTrialPlan, task: str, arm: str, workspace: Path, attempt: int) -> list[str]:
    """The command line for one answer, real or fake.

    The real branch passes ``--model`` and ``--review-model`` together, always. The
    reviewer's model resolves independently of the operator's, so an arm that passes one
    and not the other leaves the review panels on whatever the backend defaults to, where
    they die without ever being classified as anything.
    """
    spec = plan.arm_for(arm)
    if plan.operator == "fake":
        argv = [
            sys.executable, str(Path(__file__).resolve()), "fake-run",
            "--workspace", str(workspace),
            "--task", task,
            "--arm", arm,
            "--kind", spec.kind,
            "--model", spec.model,
            "--review-model", spec.review_model,
            "--profile", spec.profile,
            "--answer-guidance", spec.answer_guidance,
            "--dataset-sha256", plan.dataset_sha256,
            "--disallowed-tools", *plan.disallowed_tools,
            "--attempt-index", str(attempt - 1),
            "--quality", str(plan.fake_quality if arm == plan.treatment.label else 0.0),
        ]
        # The treatment arm, like `fake_quality`, because a fault injected into both
        # arms would produce two refusals and no pair, which exercises the ledger and
        # not the asymmetry the ledger exists to disclose.
        if arm == plan.treatment.label:
            for fault in plan.fake_faults:
                argv += ["--browse", "1"] if fault == "browse" else [f"--{fault}"]
        return argv
    argv = [
        sys.executable,
        str(Path(spec.worktree) / "fs_agent.py" if spec.worktree else REPO_ROOT / "fs_agent.py"),
        "--workspace", str(workspace),
        "--task", task,
        "--dataset", plan.dataset,
        "--profile", spec.profile or "direct",
        "--answer-guidance", spec.answer_guidance,
        "--model", spec.model,
        "--review-model", spec.review_model or spec.model,
        "--operator", plan.operator,
        "--stage-timeout", str(plan.stage_timeout_seconds),
        "--attempt-index", str(attempt - 1),
        "--disallowed-tools", *plan.disallowed_tools,
    ]
    return argv


def start_run(plan: FsTrialPlan, task: str, arm: str, attempt: int) -> dict[str, Any]:
    """Create the workspace, write the state, start the child, and return without waiting.

    Non-blocking on purpose. The plan asks for several answers at once, so the watchdog
    and the reaper are the loop's job rather than a call that sits inside this one -- and
    a blocking launch is what makes a concurrent driver quietly serial.
    """
    spec = plan.arm_for(arm)
    worktree = Path(spec.worktree) if spec.worktree else REPO_ROOT
    workspace = make_workspace(plan, task, arm)
    ensure_fs_workspace(workspace)
    argv = agent_argv(plan, task, arm, workspace, attempt)

    logs = Path(plan.state_dir) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stdout_path = logs / f"{task.replace(':', '')}.{arm}.a{attempt}.log"

    state: dict[str, Any] = {
        "plan_digest": plan.digest,
        "task_key": task,
        "arm": arm,
        "arm_kind": spec.kind,
        "attempt": attempt,
        "phase": "launched",
        "worktree": str(worktree),
        "revision_at_launch": git_head(worktree),
        "worktree_dirty_at_launch": git_dirty(worktree),
        "workspace": str(workspace),
        "argv": argv,
        "launched_at": time.time(),
        "stdout_path": str(stdout_path),
        "boot_id": boot_id(),
    }
    path = state_path(plan, task, arm, attempt)
    write_json(path, state)

    # A file, not a pipe. The front end flushes on every event, and a driver killed while
    # holding the read end leaves the agent taking a BrokenPipe on its next write.
    sink = open(stdout_path, "ab", buffering=0)
    child = subprocess.Popen(
        argv, stdout=sink, stderr=subprocess.STDOUT, start_new_session=True, cwd=str(worktree)
    )
    state["child_pid"] = child.pid
    state["child_pgid"] = os.getpgid(child.pid)
    write_json(path, state)
    return {
        "key": (task, arm),
        "attempt": attempt,
        "child": child,
        "sink": sink,
        "state": state,
        "path": path,
        "workspace": workspace,
        "worktree": worktree,
        "last_beat": time.time(),
    }


def finish_run(plan: FsTrialPlan, record: Mapping[str, Any], *, stalled: bool) -> dict[str, Any]:
    """Harvest the workspace and write the run's last state, once the child is gone."""
    task, arm = record["key"]
    child = record["child"]
    finish = dict(record["state"])
    finish.update(harvest(record["workspace"], task_key=task))
    finish.update(
        {
            "phase": "finished",
            "finished_at": time.time(),
            "exit_code": child.returncode,
            "revision_at_finish": git_head(record["worktree"]),
            "worktree_dirty_at_finish": git_dirty(record["worktree"]),
            "stalled": stalled,
        }
    )
    # One field, both observations, because the clause asks whether the worktree was
    # clean for the whole run and either end being dirty answers it.
    finish["worktree_dirty"] = bool(finish.get("worktree_dirty_at_launch")) or bool(
        finish.get("worktree_dirty_at_finish")
    )
    finish["classification"] = classify_fs_run(finish)
    write_json(record["path"], finish)
    record["sink"].close()
    return finish


def reap(plan: FsTrialPlan, running: dict[tuple[str, str], dict[str, Any]]) -> None:
    """Finish every child that has exited, and kill every child that has stopped beating.

    The watchdog is here rather than in :func:`src.trial_driver.watch` because that one
    blocks on a single child, which is the right shape for a serial driver and the wrong
    one for this. The heartbeat it reads is the same: ``logs_raw.jsonl``'s mtime, the only
    second-granularity signal an AutoR run emits.
    """
    for key in sorted(running):
        record = running[key]
        child = record["child"]
        if child.poll() is None:
            beat = heartbeat(record["workspace"])
            if beat > record["last_beat"]:
                record["last_beat"] = beat
            if time.time() - record["last_beat"] > plan.stall_seconds:
                print(f"  STALLED: {key[0]}/{key[1]} -- killing its process group")
                kill_group(child)
                child.wait()
                finish_run(plan, record, stalled=True)
                running.pop(key)
            continue
        finish = finish_run(plan, record, stalled=False)
        running.pop(key)
        print(f"  finished {key[0]}/{key[1]}: {finish.get('classification')}")
        announce_admission(plan, finish)


def announce_admission(plan: FsTrialPlan, state: Mapping[str, Any]) -> None:
    """Say straight away whether that run can ever become a number, without a judge.

    Nine of the ten clauses read ``_meta.json``. The sibling driver buys this warning
    with a judge call per run because its clauses read a score file; here it is free, so
    there is no reason to learn on day five that a gate has been refusing everything
    since run one. The tenth clause, ``every_draw_judged``, is the only one a judge can
    answer, and it is reported as pending rather than as passing.
    """
    probe = FsArmEvidence(
        task_key=str(state.get("task_key") or ""),
        spec=plan.arm_for(str(state.get("arm") or "")),
        run_id=str(state.get("meta_run_id") or ""),
        workspace=str(state.get("workspace") or ""),
        env=FsRunEnvironment(),
        total_points=0.0,
        published_total=0.0,
        facts=dict(state),
    )
    _ok, failed = admit_fs_arm(probe)
    judged = "every_draw_judged"
    pending = judged in failed
    blocking = [name for name in failed if name != judged]
    verdict = "ADMISSIBLE so far" if not blocking else "REFUSED -- " + ", ".join(blocking)
    print(f"  admission: {verdict}")
    if pending:
        print("    (`every_draw_judged` is not answerable until the final pass runs)")


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_path(plan: FsTrialPlan, task: str, arm: str, attempt: int, draw: int) -> Path:
    slug = task.replace(":", "")
    return Path(plan.state_dir) / "scores" / f"{slug}.{arm}.a{attempt}.final.r{draw}.json"


def score_once(plan: FsTrialPlan, state: Mapping[str, Any], out: Path) -> bool:
    """One score file, holding exactly one judge draw over one answer.

    One draw per file and the replication is the loop above, so a judge flake costs one
    draw rather than an arm's whole replication -- the scorer writes *nothing at all*
    when any draw in an invocation fails, which is the refusal this driver inherits
    rather than reimplements, by reading ``returncode == 0 and out.exists()``.
    """
    workspace = Path(str(state["workspace"]))
    if plan.judge_kind == "fake":
        return fake_score(plan, state, out)
    argv = [
        sys.executable, str(REPO_ROOT / "tools" / "score_fs_run.py"),
        "--task", str(state["task_key"]),
        "--answer", str(answer_path_for(workspace)),
        "--answer-meta", str(workspace / "_meta.json"),
        "--dataset", plan.dataset,
        "--model", plan.judge_model,
        "--reasoning-effort", plan.judge_reasoning_effort,
        "--judge-max-tokens", str(plan.judge_max_output_tokens),
        "--judge-timeout", str(plan.judge_timeout_seconds),
        "--draws", "1",
        "--out", str(out),
    ]
    if plan.judge_endpoint:
        argv += ["--endpoint", plan.judge_endpoint]
    if plan.judge_raw_dir:
        argv += ["--raw-dir", plan.judge_raw_dir]
    done = subprocess.run(argv, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        sys.stderr.write(done.stdout[-4000:] + done.stderr[-4000:])
    return done.returncode == 0 and out.exists()


def fake_score(plan: FsTrialPlan, state: Mapping[str, Any], out: Path) -> bool:
    """A deterministic stand-in judge, for exercising the harness without spending it.

    It fabricates a *judge response* and hands it to the real
    :func:`src.fs_scoring.draw_record` and :func:`src.fs_scoring.build_result`, so the
    dry run exercises the verdict grammar, the draw-failure rules, the aggregation and
    the refusal that the real path uses. Only the sentence the judge writes is invented.

    Two properties are the point. The verdict moves with the answer's ``FAKE_QUALITY``
    line, so a dry run produces a real, signed, non-zero difference instead of two
    identical columns that a broken seam would pass; and it moves with the draw index, so
    a multi-draw dry run reports a spread the sibling's repeated draw could not -- a
    stochastic judge that resolved every answer perfectly is the reading this whole
    apparatus refuses to print.
    """
    workspace = Path(str(state["workspace"]))
    meta = read_json(workspace / "_meta.json")
    block = meta.get("task_block")
    row = FsRow.from_dict(block if isinstance(block, dict) else {"key": state["task_key"]})
    answer_path = answer_path_for(workspace)
    text = answer_path.read_text(encoding="utf-8") if answer_path.is_file() else ""
    quality = 0.0
    for line in text.splitlines():
        if line.startswith("FAKE_QUALITY:"):
            quality = float(line.split(":", 1)[1])

    draw = int(out.name.rsplit(".r", 1)[-1].split(".")[0])
    seed = hashlib.sha256(
        f"{row.key}|{state['arm']}|{workspace.name}|{draw}".encode("utf-8")
    ).digest()
    jitter = (seed[0] % 7) / 10.0
    points = max(0.0, min(row.rubric_points_total or FS_DATASET_POINTS_PER_ROW, 2.0 + quality + jitter))
    payload = {
        "status": "completed",
        "incomplete_details": None,
        "output": [
            {
                "type": "message",
                "content": [{"text": f"Fake grading of {row.key}.\nVERDICT: {points:.3f}"}],
            }
        ],
        "usage": {"output_tokens": 1000 + seed[1], "output_tokens_details": {"reasoning_tokens": 900}},
    }
    record = draw_record(
        payload,
        index=draw,
        latency_seconds=0.01,
        rubric_points_total=row.rubric_points_total or FS_DATASET_POINTS_PER_ROW,
    )
    result = build_result(
        row=row,
        dataset={"path": plan.dataset, "sha256": plan.dataset_sha256, "rows": 0},
        answer={
            "path": str(answer_path),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "chars": len(text),
            **{key: value for key, value in meta.items() if key != "task_block"},
        },
        judge={
            "model": plan.judge_model,
            "endpoint": "fake",
            "reasoning_effort": plan.judge_reasoning_effort,
            "max_output_tokens": plan.judge_max_output_tokens,
            "timeout_seconds": plan.judge_timeout_seconds,
            "concurrency": plan.judge_concurrency,
            "prompt_sha256": "",
            "prompt_chars": 0,
        },
        draws=[record],
        draws_requested=1,
        scored_at="1970-01-01T00:00:00Z",
        code_version="fake",
        pass_threshold=plan.pass_threshold,
    )
    if result["refused"]:
        # The same inheritance the real path relies on: a refused total writes no file,
        # so the driver reads the refusal off the file's absence and never off a flag.
        return False
    write_json(out, result)
    return True


def final_pass(plan: FsTrialPlan) -> None:
    """Grade every finished, unrefused workspace, back to back, at the end.

    One continuous pass with one judge, serially, because that is the only arrangement
    under which the published totals of the first task and the last were produced by the
    same instrument. Progress is printed per file: the judge is the one part of this
    trial nothing can warn about early, so an operator watching a wrong endpoint refuse
    every call should see it on the second line rather than in the report.
    """
    lost: list[str] = []
    for state in all_states(plan):
        if state.get("phase") != "finished" or state.get("classification") != "ok":
            continue
        task, arm = str(state["task_key"]), str(state["arm"])
        for draw in range(plan.judge_replicates):
            out = score_path(plan, task, arm, int(state.get("attempt") or 1), draw)
            if out.exists():
                continue
            for _try in range(JUDGE_TRIES):
                if score_once(plan, state, out):
                    break
            else:
                # Giving up quietly is how an arm scored once is published as an arm
                # scored three times. The count reaches the report through
                # `FsRunEnvironment.judge_replicates`; this is the operator's copy.
                lost.append(out.name)
                print(f"  LOST DRAW: {out.name} could not be scored in {JUDGE_TRIES} tries")
                continue
            payload = read_json(out)
            print(f"  scored {task}/{arm} draw {draw}: {payload.get('total_score')}")
    write_json(
        Path(plan.state_dir) / "final_pass.json",
        {"done": True, "at": time.time(), "unscored_draws": sorted(lost)},
    )


# ---------------------------------------------------------------------------
# Building evidence and reporting
# ---------------------------------------------------------------------------


def evidence_for(plan: FsTrialPlan, state: Mapping[str, Any]) -> FsArmEvidence | None:
    """One admitted-or-refused arm, assembled from the state file and the score files.

    Every environment field is read off what landed on disk and never off the plan. A
    field filled from the plan agrees by construction, and the confounds worth catching
    are the ones where the plan said one thing and the run did another -- a dropped
    ``--model``, an instruction edited between the two arms, a backend that had no
    denied-tool knob and denied nothing.
    """
    task, arm = str(state.get("task_key") or ""), str(state.get("arm") or "")
    attempt = int(state.get("attempt") or 1)
    payloads = []
    for draw in range(plan.judge_replicates):
        path = score_path(plan, task, arm, attempt, draw)
        if path.exists():
            payloads.append(read_json(path))
    if not payloads:
        return None

    first = payloads[0]
    block = first.get("task") if isinstance(first.get("task"), dict) else {}
    points: list[float] = []
    failures: list[str] = []
    published: list[float] = []
    for payload in payloads:
        for row in payload.get("draws") or []:
            value = row.get("points")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                points.append(float(value))
            else:
                failures.append(f"draw with no points in {payload.get('scored_at')}")
        failures.extend(str(item) for item in (payload.get("judge_failures") or []))
        total = payload.get("total_score")
        if isinstance(total, (int, float)) and not isinstance(total, bool):
            published.append(float(total))

    judge = first.get("judge") if isinstance(first.get("judge"), dict) else {}
    tools = state.get("meta_disallowed_tools")
    env = FsRunEnvironment(
        dataset_sha256=str(state.get("meta_dataset_sha256") or ""),
        judge_model=str(judge.get("model") or ""),
        judge_reasoning_effort=str(judge.get("reasoning_effort") or ""),
        answer_model=str(state.get("meta_model") or ""),
        answer_guidance=str(state.get("meta_answer_guidance") or ""),
        task_instruction_sha256=str(state.get("meta_task_instruction_sha256") or ""),
        disallowed_tools=tuple(sorted(str(item) for item in tools)) if isinstance(tools, list) else (),
        # One, always, and a constant rather than an observation -- there is nothing on
        # disk to read it off, because this driver produces one evidence per run and pools
        # nothing. Writing `plan.answer_attempts` here instead would make the field agree
        # with the plan by construction while still being a constant, which is the worse
        # of the two. `_refuse_a_plan_that_cannot_produce_a_pair` refuses a plan that asks
        # for any other value, so the constant and the declaration cannot disagree; it is
        # in the digest so that an arm pooled over three attempts, the day pooling is
        # built, could never be averaged against an arm that ran once.
        answer_attempts=1,
        judge_replicates=len(points),
    )
    return FsArmEvidence(
        task_key=task,
        spec=plan.arm_for(arm),
        run_id=str(state.get("meta_run_id") or Path(str(state.get("workspace", ""))).name),
        workspace=str(state.get("workspace") or ""),
        env=env,
        total_points=sum(points) / len(points) if points else 0.0,
        published_total=sum(published) / len(published) if published else 0.0,
        draw_points=tuple(points),
        draws_requested=int(plan.judge_replicates),
        judge_failures=tuple(failures),
        subject=str(block.get("subject") or ""),
        row_index=int(block.get("row_index") or -1),
        duplicate_of=block.get("duplicate_of"),
        rubric_points_total=float(block.get("rubric_points_total") or FS_DATASET_POINTS_PER_ROW),
        facts=dict(state),
    )


def driver_refusals(
    states: Sequence[Mapping[str, Any]],
    scored: set[tuple[str, str]],
    *,
    final_pass_done: bool,
) -> list[FsRefusal]:
    """Every run that died before the admission gate could ever look at it.

    ``final_pass`` grades only ``classification == "ok"`` and ``evidence_for`` returns
    ``None`` without score files, so a run killed by the watchdog, by a crash, by a
    fallback answer, by an incomplete pipeline or by the scorer's own refusal produces no
    evidence, reaches no clause, and used to be rendered as "no `<arm>` arm" -- the same
    sentence as an arm that was never launched. The report tells the reader to judge the
    difference on the per-arm death counts, and those counts were structurally zero for
    exactly the deaths the paragraph warns about.

    ``phase == "launched"`` is not here: a run in flight has not died, and calling it a
    refusal would report every interim run as an attrition. Neither is a healthy run with
    no score file until the final pass has been over it.
    """
    worst: dict[tuple[str, str], str] = {}
    for state in states:
        key = (str(state.get("task_key") or ""), str(state.get("arm") or ""))
        if not key[0] or not key[1]:
            continue
        phase = str(state.get("phase") or "")
        classification = str(state.get("classification") or "")
        if phase == "refused":
            worst[key] = classification or "refused"
        elif phase == "abandoned":
            worst.setdefault(key, "abandoned")
        elif phase == "finished":
            if classification and classification != "ok":
                worst.setdefault(key, classification)
            elif key not in scored and final_pass_done:
                # Ran, was admissible, the final pass has been over it and no score file
                # exists: the judge failed every draw, or the scorer could not write. A
                # whole trial of these would publish `pairs: 0` with an empty ledger.
                worst.setdefault(key, "unscored")
    return [
        FsRefusal(task, arm, (fs_driver_clause(cause),))
        for (task, arm), cause in sorted(worst.items())
    ]


def build_report(plan: FsTrialPlan) -> str:
    """A pure function of the state directory: nothing derived survives between runs.

    Every artifact under the state directory is rebuilt from ``runs/`` and ``scores/`` on
    each invocation, so re-running after fixing a bug in the producer cannot leave half of
    an old answer behind.
    """
    states = all_states(plan)
    evidences: list[FsArmEvidence] = []
    scored: set[tuple[str, str]] = set()
    for state in states:
        if state.get("phase") != "finished":
            continue
        item = evidence_for(plan, state)
        if item is not None:
            evidences.append(item)
            scored.add((item.task_key, item.arm))

    trial = collect_fs_pairs(
        evidences,
        capability=plan.capability,
        control=plan.control,
        treatment=plan.treatment,
        planned_pairs=plan.planned_pairs,
        dedupe_pairs=plan.dedupe_pairs,
        driver_refusals=driver_refusals(
            states,
            scored,
            final_pass_done=(Path(plan.state_dir) / "final_pass.json").exists(),
        ),
    )
    # Observed, then declared. The header used to print the plan's field whatever had
    # actually graded the runs, which is the one line a reader would use to decide the
    # number is comparable to a published figure.
    observed = sorted({item.env.judge_model for item in evidences if item.env.judge_model})
    # No contrast log, unlike the sibling driver. There the two arms *are* two
    # revisions and `git log --oneline <control>..<treatment>` is the description of the
    # difference; here one arm is a commit and the other is a model with no worktree at
    # all, so there is no range to print and a one-commit "contrast" would be a section
    # that looks like the sibling's and says nothing. The arms' full descriptions are in
    # the provenance block instead.
    return format_fs_trial_report(trial, plan=plan, judge_model=", ".join(observed))


# ---------------------------------------------------------------------------
# The fake operator
# ---------------------------------------------------------------------------


def fake_run(args: argparse.Namespace) -> int:
    """Fabricate a workspace shaped exactly like a finished ``fs_agent.py`` run.

    Deliberately a real subprocess launched with ``start_new_session``: the state
    machine, the lock, the process-group handling and the heartbeat are the parts most
    likely to be wrong, and a fake that ran in-process would exercise none of them.

    It writes a real run tree and a real stream-json transcript and then reads it back
    through :func:`src.frontierscience.read_transcript_witness`, and it assembles its
    metadata through :func:`src.frontierscience.build_fs_meta`. So the dry run exercises
    the witness, the six exit clauses and the status field that is computed from them
    rather than handed in -- the three places the sibling benchmark's forty real runs all
    got wrong at once.

    ``--no-transcript`` and ``--browse`` exist so that the two ways ``no_browsing`` must
    refuse -- a null witness and a real browsing call -- are reachable end to end and not
    only in a unit test with a hand-written fact dictionary.
    """
    workspace = Path(args.workspace)
    ensure_fs_workspace(workspace)
    paths = build_run_paths(create_run_root(fs_runs_dir_for(workspace)))
    ensure_run_layout(paths)
    write_text(paths.user_input, f"fake goal for {args.task}")

    if not args.no_transcript:
        with paths.logs_raw.open("a", encoding="utf-8") as handle:
            for index in range(args.browse):
                handle.write(
                    json.dumps(
                        {
                            "type": "assistant",
                            "message": {
                                "content": [
                                    {"type": "tool_use", "name": "WebFetch", "input": {}}
                                ]
                            },
                        }
                    )
                    + "\n"
                )
                handle.flush()
            for beat in range(3):
                handle.write(
                    json.dumps(
                        {
                            "type": "result",
                            "stop_reason": "max_tokens" if args.truncate else "end_turn",
                            "usage": {"output_tokens": 1000 + beat},
                            "beat": beat,
                            "at": time.time(),
                        }
                    )
                    + "\n"
                )
                handle.flush()
                time.sleep(0.05)

    body = (
        f"# {args.task}\n\nFAKE_QUALITY: {args.quality}\n\n"
        + ("A fabricated answer. " * 30)
        + "\n"
    )
    answer = answer_path_for(workspace)
    write_text(answer, body)

    stages = [FS_IDEATE_STAGE] if args.kind == "autor" else []
    meta = build_fs_meta(
        workspace=workspace,
        task=args.task,
        profile=args.profile,
        answer_guidance=args.answer_guidance,
        model=args.model,
        review_model=args.review_model,
        operator="claude",
        answer=FsAnswer(
            path=answer,
            source="agent",
            chars=len(body),
            sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            refusals=[],
        ),
        pipeline_completed=True,
        auto_skipped_stages=[],
        stages_approved=stages,
        disallowed_tools=list(args.disallowed_tools),
        dataset_path=None,
        dataset_sha256=args.dataset_sha256,
        run_id=paths.run_root.name,
        duration_seconds=1,
        attempt_index=args.attempt_index,
        witness=read_transcript_witness(paths),
        extra={
            # The arm label, for the same reason `write_fs_meta` merges rather than
            # replaces: a finished workspace that cannot be attributed to the arm that
            # produced it is a workspace a reader has to trust a filename for.
            "arm": args.arm,
            "subject": _fake_subject(args.task),
            # The same block the real front end records, and the only place the fake
            # judge learns what it is grading.
            "task_block": _fake_task_block(args.task),
        },
    )
    write_fs_meta(workspace, meta)
    print(json.dumps({"type": "result", "status": meta["status"]}), flush=True)
    return 0 if meta["status"] == "completed" else 1


#: The split's real layout: rows 0-19 physics, 20-39 chemistry, 40-59 biology. Copied
#: into the dry run so that the per-subject table is exercised by something with more
#: than one subject in it; a dry run whose tasks all read ``<unrecorded>`` would render
#: the table and hold nothing.
_FAKE_SUBJECTS = ("physics", "chemistry", "biology")


def _fake_subject(task: str) -> str:
    index = int(task.rsplit(":", 1)[-1])
    return _FAKE_SUBJECTS[min(index // 20, len(_FAKE_SUBJECTS) - 1)]


#: The one duplicate the real split holds: rows 6 and 11 are byte-identical, so the
#: sixty-row file addresses fifty-nine distinct questions. Reproduced here rather than
#: parameterised, for the same reason :data:`_FAKE_SUBJECTS` is: the driver never opens
#: the dataset, so a dry run that could not produce a duplicate would leave the fold that
#: turns sixty pairs into fifty-nine exercised by nothing but a unit test.
_FAKE_DUPLICATE_ROWS: dict[int, int] = {11: 6}


def _fake_task_block(task: str) -> dict[str, Any]:
    index = int(task.rsplit(":", 1)[-1])
    return {
        "key": task,
        "row_index": index,
        "subject": _fake_subject(task),
        "task_group_id": f"fake-{index:03d}",
        "duplicate_of": _FAKE_DUPLICATE_ROWS.get(index),
        "problem_sha256": hashlib.sha256(task.encode("utf-8")).hexdigest(),
        "rubric_sha256": hashlib.sha256(f"rubric-{task}".encode("utf-8")).hexdigest(),
        "rubric_items": 10,
        "rubric_points_total": FS_DATASET_POINTS_PER_ROW,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def load_plan(path: Path) -> FsTrialPlan:
    payload = read_json(path)
    if not payload:
        raise SystemExit(f"no plan at {path}")
    plan = FsTrialPlan.from_dict(payload)
    frozen = Path(plan.state_dir) / "plan.json"
    if frozen.exists():
        recorded = read_json(frozen).get("digest")
        if recorded and recorded != plan.digest:
            raise SystemExit(
                f"the plan has changed since it was frozen ({recorded[:12]} -> "
                f"{plan.digest[:12]}). Editing the plan mid-trial changes what the arms "
                "mean, and an apparatus that can be re-planned while it runs is an "
                "apparatus that can be stopped when the sign looks good."
            )
    return plan


def cmd_plan(plan: FsTrialPlan) -> int:
    frozen = Path(plan.state_dir) / "plan.json"
    if frozen.exists():
        print(f"already frozen: {read_json(frozen).get('digest', '')[:16]}")
        return 0
    payload = plan.to_dict()
    payload["digest"] = plan.digest
    payload["frozen_at"] = time.time()
    write_json(frozen, payload)
    print(f"frozen {plan.planned_pairs} planned pairs, digest {plan.digest[:16]}")
    print(f"  control:   {plan.control.describe()}")
    print(f"  treatment: {plan.treatment.describe()}")
    print(f"  judge:     {plan.judge_model} at {plan.judge_reasoning_effort} effort, "
          f"{plan.judge_replicates} draw(s), serial")
    print(f"  cost note: {plan.cost_note}")
    return 0


def missing_worktrees(plan: FsTrialPlan) -> list[str]:
    """Every ``autor`` arm whose ``worktree`` is not a directory on this box.

    A launch-time question and not a freeze-time one, deliberately. A plan is a value: it
    is loaded by ``report`` as well as by ``run``, and by whoever reads a finished trial
    on a second machine, so a filesystem probe inside
    :meth:`src.fs_trial.FsTrialPlan.from_dict` would make rebuilding an old report depend
    on a checkout somebody has since deleted. ``run`` is the one verb that needs the
    directory to be there.

    It has to be there even under ``operator: "fake"``. The child's cwd is the arm's
    worktree, and ``revision_at_launch`` / ``revision_at_finish`` / ``worktree_dirty`` are
    real ``git`` readings off it that ``producer_matches_arm`` compares against the arm's
    label -- the dry run fabricates the operator and the judge, and nothing else. Without
    this the shipped plan died at ``Popen`` with a bare ``FileNotFoundError`` naming no
    arm, after the lock was taken and the state directory created.
    """
    return [
        f"{spec.label}: {spec.worktree or '<unset>'}"
        for spec in (plan.control, plan.treatment)
        if spec.kind == "autor" and not Path(spec.worktree).is_dir()
    ]


def cmd_run(plan: FsTrialPlan) -> int:
    if not (Path(plan.state_dir) / "plan.json").exists():
        raise SystemExit("freeze the plan first: `fs_trial.py plan --plan <path>`")
    absent = missing_worktrees(plan)
    if absent:
        raise SystemExit(
            "these `autor` arms name a worktree that is not a directory here:\n  "
            + "\n  ".join(absent)
            + "\nEvery run of such an arm is launched with that directory as its working "
            "directory and has its revision read out of it, so this is not a dry-run "
            "exemption: `operator: \"fake\"` fabricates the operator and the judge and "
            "nothing else, and `producer_matches_arm` compares a real `git rev-parse` "
            "against the arm's label. Point the arm at a real checkout at its sha, or run "
            "a plan whose arms are both `direct`."
        )
    known = {
        int(state["child_pid"])
        for state in all_states(plan)
        if isinstance(state.get("child_pid"), int)
    }
    # Our own recorded children are excluded, and that is not a loosening: this driver
    # runs several agents at once, so the pids it wrote down itself are the ordinary
    # state after a restart, and `next_actions` counts them against the budget rather
    # than aborting. What the preflight is for is somebody *else's* run.
    intruders = [
        line for line in foreign_runs() if int(line.split(" ", 1)[0]) not in known
    ]
    if intruders:
        print("REFUSING TO START. AutoR is already running here:", file=sys.stderr)
        for line in intruders:
            print(f"  {line}", file=sys.stderr)
        print(
            "Two trials is the concurrency that exhausts the quota that then kills both. "
            "Wait, or kill those pids by pgid (never `pkill -f`).",
            file=sys.stderr,
        )
        return 2

    # Named, because the kernel refuses to guess. A driver that let the marker default
    # would ask whether a process of *somebody else's* kind holds the lock, be told no,
    # and take over a lock a live sibling is holding.
    lock = acquire_lock(Path(plan.state_dir), marker="fs_trial.py")
    running: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        while True:
            reap(plan, running)
            actions = next_actions(
                plan,
                all_states(plan),
                now=time.time(),
                # Only this driver's own shape of child. A bare `/proc` listing would
                # count any pid the kernel happened to hand to somebody else's process
                # after this driver died, which is the ordinary case rather than the rare
                # one; and the markers are named here, by the driver that knows what it
                # launches, rather than assumed by the shared kernel.
                live_pids=autor_pids(markers=OUR_RUN_MARKERS),
                final_pass_done=(Path(plan.state_dir) / "final_pass.json").exists(),
            )
            stop = False
            for action in actions:
                print(f"[{time.strftime('%H:%M:%S')}] {action}")
                if action.kind == "done":
                    stop = True
                    break
                if action.kind == "wait":
                    time.sleep(POLL_SECONDS)
                    continue
                if action.kind == "abandon":
                    path = state_path(plan, action.task_key, action.arm, action.attempt)
                    state = read_json(path)
                    state["phase"] = "abandoned"
                    state["abandoned_reason"] = action.reason
                    write_json(path, state)
                    continue
                if action.kind == "refuse":
                    write_json(
                        state_path(plan, action.task_key, action.arm, 0),
                        {
                            "task_key": action.task_key,
                            "arm": action.arm,
                            "attempt": 0,
                            "phase": "refused",
                            "classification": action.reason,
                            "plan_digest": plan.digest,
                        },
                    )
                    continue
                if action.kind == "launch":
                    running[(action.task_key, action.arm)] = start_run(
                        plan, action.task_key, action.arm, action.attempt
                    )
                    continue
                if action.kind == "final_pass":
                    final_pass(plan)
                    continue
            if stop:
                break
    finally:
        for record in list(running.values()):
            record["sink"].close()
        release_lock(lock)

    report = build_report(plan)
    (Path(plan.state_dir) / "report.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


def cmd_report(plan: FsTrialPlan) -> int:
    report = build_report(plan)
    (Path(plan.state_dir) / "report.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fs_trial",
        description="Run a paired FrontierScience-Research trial and report it.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, blurb in (
        ("plan", "Freeze the plan and print its digest."),
        ("run", "Launch, watch, grade and report. Resumable."),
        ("report", "Rebuild the report from the state directory alone."),
    ):
        child = sub.add_parser(name, help=blurb, description=blurb)
        child.add_argument(
            "--plan",
            required=True,
            type=Path,
            metavar="PATH",
            help="The trial plan to read. Required: there is no default plan, because a "
                 "default would be a trial nobody chose the parameters of.",
        )
    faker = sub.add_parser(
        "fake-run",
        help="Fabricate one finished workspace. Launched by the dry run as a child.",
        description="Fabricate one finished workspace, shaped like a real fs_agent.py run.",
    )
    faker.add_argument("--workspace", required=True, metavar="PATH",
                       help="Where to write the fabricated run. Required.")
    faker.add_argument("--task", required=True, metavar="KEY",
                       help="The task key this fake answer is for, as fs:NNN. Required.")
    faker.add_argument("--arm", required=True, metavar="LABEL",
                       help="The arm label this run belongs to. Required.")
    faker.add_argument("--kind", default="direct", choices=("direct", "autor"),
                       help="Which producer to imitate, which decides whether a stage is "
                            "recorded as approved. Defaults to direct.")
    faker.add_argument("--model", default="", metavar="NAME",
                       help="Model to record as the answer's producer. Defaults to empty.")
    faker.add_argument("--review-model", default="", metavar="NAME",
                       help="Review model to record. Defaults to empty.")
    faker.add_argument("--profile", default="", metavar="NAME",
                       help="Profile to record. Defaults to empty.")
    faker.add_argument("--answer-guidance", default="minimal", metavar="NAME",
                       help="Guidance to record. Defaults to minimal.")
    faker.add_argument("--dataset-sha256", default="", metavar="HEX",
                       help="Dataset digest to record. Defaults to empty.")
    faker.add_argument("--disallowed-tools", nargs="*", default=[], metavar="TOOL",
                       help="Tool names to record as denied on every seat. Defaults to none.")
    faker.add_argument("--attempt-index", type=int, default=0, metavar="N",
                       help="Which repeat of this (task, arm) this is. Defaults to 0.")
    faker.add_argument("--quality", type=float, default=0.0, metavar="POINTS",
                       help="How many rubric points better than the floor the fake judge "
                            "should grade this answer. Defaults to 0.0.")
    faker.add_argument("--no-transcript", action="store_true",
                       help="Write no stream-json transcript, so the browsing witness is "
                            "null and the pair must be refused rather than admitted.")
    faker.add_argument("--browse", type=int, default=0, metavar="N",
                       help="Record N browsing tool calls in the transcript, so the "
                            "no-browsing clause is reachable end to end. Defaults to 0.")
    faker.add_argument("--truncate", action="store_true",
                       help="Record the run as having stopped at its token ceiling, so "
                            "the truncation clause is reachable end to end.")
    args = parser.parse_args(argv)

    if args.command == "fake-run":
        return fake_run(args)

    plan = load_plan(args.plan)
    if args.command == "plan":
        return cmd_plan(plan)
    if args.command == "run":
        return cmd_run(plan)
    return cmd_report(plan)


if __name__ == "__main__":
    raise SystemExit(main())
