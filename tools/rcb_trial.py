"""Run a paired ResearchClawBench trial, one arm at a time, and survive being killed.

The shell around :mod:`src.rcb_trial`. Everything here touches a process, a clock or a
filesystem; everything that decides anything lives in the module and is a pure function
of already-parsed data, because the alternative is validating multi-day
kill-and-restart behaviour by spending multi-day kill-and-restart wall clock.

**Why a driver at all.** AutoR has no serial multi-run driver. ``studio_runner`` starts
a thread per project with no queue and no restart recovery; ``main.py`` runs one run;
``rcb_agent.py`` never touches the archive, so a run through the benchmark entry point
produces no tagged ``RunRecord`` at all. And the runs have to be strictly serialised:
this box has been observed running three AutoR processes against one Vertex project at
once, which is precisely the concurrency that exhausts the quota that then kills them.

**Four operational facts the design is bent around**, each measured here rather than
assumed:

1. A 429 lands in the run's own ``logs.txt``, never on the driver's stdout — the
   operator catches the API error. A retry loop that greps stdout has never fired.
2. A ``setsid`` driver survives ``pkill`` on its children, so "I killed it and
   relaunched" silently yields two drivers racing. The lock is ``os.link`` (atomic on
   NFS, unlike ``O_CREAT|O_EXCL``) plus a liveness test that checks the pid, its
   ``cmdline`` and the boot id, so a pid reused after a reboot reads as stale.
3. Measured run durations here are 3426 / 57011 / 50536 / 11360 seconds. There is no
   per-run wall clock: any cap short enough to catch a hang would have killed the
   15.8-hour run that finished properly. A stall watchdog on ``logs_raw.jsonl``'s mtime
   — the only second-granularity heartbeat a run emits — plus a trial deadline after
   which no *new* run starts.
4. State is written twice per run, before launch and after finish, tmp plus
   ``os.replace``. A ``kill -9`` costs the run in flight and nothing else, and scoring
   happens inside the loop so a systematically-refusing gate is visible after run one
   rather than after day five.

The dry-run path (``operator: "fake"``, ``judge_kind: "fake"`` in the plan) fabricates
workspaces and scores instead of spending four hours per task. It exercises the real
lock, the real subprocess and process-group handling, the real state machine, the real
admission gate and the real report — everything except the two things that cost money.

Usage::

    python3 tools/rcb_trial.py plan --plan plan.json      # freeze it
    python3 tools/rcb_trial.py run  --plan plan.json      # serial, resumable
    python3 tools/rcb_trial.py report --plan plan.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.rcb_trial import (  # noqa: E402
    SETTLED_REASONING_HEADING,
    ArmEvidence,
    Refusal,
    RunEnvironment,
    TrialPlan,
    classify_run,
    collect_rcb_pairs,
    count_quota_hits,
    driver_clause,
    format_rcb_trial_report,
    items_from_score_payloads,
    judge_draws_in,
    next_action,
)

#: Extensions the benchmark's image sweep recognises. Duplicated here on purpose: the
#: admission clause has to count what the scorer would show the judge, and importing
#: the bench's config at gate time would make the gate depend on a checkout being
#: present when the gate is exactly what runs when things have gone wrong.
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg")


# ---------------------------------------------------------------------------
# Atomic state
# ---------------------------------------------------------------------------


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Replace, never truncate-and-write. ``/home`` here is shared NFS."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def digest_bytes(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def instructions_digest(workspace: Path) -> str:
    """The judge's background text, with the one thing that differs by construction out.

    ``INSTRUCTIONS.md`` is rendered with the workspace path in it, and the two arms of a
    pair are in different directories by design — reusing a directory is how two runs
    overwrite each other's report. Digesting the file raw therefore reports *every*
    pair as an environment difference, which the first dry run duly did: a gate that
    fires on everything refuses nothing, because the reader stops believing it. What
    the digest is asking is whether the two arms were handed the same background, so
    the path is normalised out and everything else is held byte for byte.
    """
    path = workspace / "INSTRUCTIONS.md"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return hashlib.sha256(
        text.replace(str(workspace), "<WORKSPACE>").encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# The lock
# ---------------------------------------------------------------------------


def boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:  # pragma: no cover - not Linux
        return ""


def process_cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode("utf-8", "replace")


def process_argv(pid: int) -> list[str]:
    """The real argument vector, not the joined string.

    ``/proc/pid/cmdline`` is NUL-separated, and joining it before matching is what
    turns *mentioning* a script into *running* one. A shell running
    ``grep rcb_agent.py`` -- or the diagnostic one-liner someone types to check
    whether a run is up -- has ``rcb_agent.py`` in its joined command line and is
    not a run.
    """
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]


def lock_is_live(payload: Mapping[str, Any], *, marker: str = "rcb_trial.py") -> bool:
    """Three conditions, all required. Any one alone gives a false answer.

    The pid alone is reused; the cmdline alone cannot be read for a pid that is gone;
    and after a reboot a pid *and* a matching cmdline can both be somebody else's
    process entirely, which is why the boot id is in the lock file.
    """
    pid = int(payload.get("pid") or 0)
    if pid <= 0 or not Path(f"/proc/{pid}").exists():
        return False
    if marker not in process_cmdline(pid):
        return False
    recorded = str(payload.get("boot_id") or "")
    return not recorded or recorded == boot_id()


def claim_stale_lock(
    state_dir: Path, existing: Mapping[str, Any], tmp: Path, lock: Path
) -> bool:
    """Take a dead driver's lock over — atomically, or not at all.

    The bare ``os.replace`` this replaces threw away everything the ``os.link`` on the
    create path was for: two drivers that both read the same stale lock both replaced it
    and both proceeded, which is precisely the two-drivers-on-one-state-directory case
    the lock exists to prevent. And a stale lock is not the exotic entry point to it — it
    is what ``kill -9`` on a driver leaves behind, i.e. the documented "I killed it and
    relaunched" case. Reproduced at two of five races on a ~1 ms window.

    So the takeover is decided by the same primitive as the creation: a token named after
    the *particular* stale lock being taken over, created with ``os.link``, which exactly
    one process can win. The token is deliberately never deleted — deleting it after the
    replace reopens a window of the same shape, because a driver that read the stale lock
    before the replace would find the token gone, create it, and take the lock in turn.
    """
    token = state_dir / (
        f"driver.lock.taken.{existing.get('pid', 'unknown')}."
        f"{existing.get('started_at', 'unknown')}"
    )
    try:
        os.link(tmp, token)
    except FileExistsError:
        return False
    os.replace(tmp, lock)
    return True


def acquire_lock(state_dir: Path) -> Path:
    """``os.link``, because ``O_CREAT|O_EXCL`` is not reliably atomic on NFS."""
    state_dir.mkdir(parents=True, exist_ok=True)
    lock = state_dir / "driver.lock"
    payload = {
        "pid": os.getpid(),
        "pgid": os.getpgid(0),
        "boot_id": boot_id(),
        "argv": sys.argv,
        "started_at": time.time(),
    }
    tmp = state_dir / f"driver.lock.{os.getpid()}"
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        os.link(tmp, lock)
    except FileExistsError:
        existing = read_json(lock)
        if lock_is_live(existing):
            tmp.unlink(missing_ok=True)
            raise SystemExit(
                f"another driver holds {lock} (pid {existing.get('pid')}). Two drivers "
                "racing is the concurrency that exhausts the quota. Wait for it, or kill "
                f"that pid and re-run."
            )
        if not claim_stale_lock(state_dir, existing, tmp, lock):
            tmp.unlink(missing_ok=True)
            raise SystemExit(
                f"another driver is taking over the stale lock at {lock} (it was pid "
                f"{existing.get('pid')}). Two near-simultaneous relaunches after a "
                "`kill -9` is exactly how this box came to be running three AutoR "
                "processes against one Vertex project; this one is standing down."
            )
        return lock
    tmp.unlink(missing_ok=True)
    return lock


def release_lock(lock: Path) -> None:
    if read_json(lock).get("pid") == os.getpid():
        lock.unlink(missing_ok=True)


def autor_pids() -> frozenset[int]:
    """Live pids whose command line is an agent run — ours or anybody's."""
    found: set[int] = set()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        line = process_cmdline(int(entry.name))
        if "rcb_agent.py" in line or "rcb_trial.py fake-run" in line:
            found.add(int(entry.name))
    return frozenset(found)


#: Scripts whose execution is a run competing for the same per-base-model quota.
_RUN_SCRIPTS = ("rcb_agent.py", "main.py")


def is_backed_run(argv: Sequence[str]) -> bool:
    """True only for a process that will actually call a model.

    Two false positives cost a live trial ten minutes each, and on a busy box they
    cost it forever:

    * **A mention is not an execution.** The first version joined ``cmdline`` and
      substring-matched it, so a shell scanning ``/proc`` for ``rcb_agent.py``
      refused the driver by existing. The script has to be an *argument*, and after
      the interpreter -- ``argv[0]`` is the python binary.
    * **A fake operator makes no backend calls at all.** ``--fake-operator`` is what
      the test suite runs, constantly, and a driver that stands down for the unit
      tests never starts on a machine anybody is developing on. It contends for
      nothing, so it is not contention.
    """
    if not argv or "--fake-operator" in argv:
        return False
    # argv[0] must be the interpreter. Without this, ``grep -rn rcb_agent.py .``
    # reads as a run: the script name is a bare argument there too. A shebang
    # execution still shows the interpreter first -- the kernel rewrites argv --
    # so requiring it costs nothing real.
    binary = argv[0].rsplit("/", 1)[-1]
    if not binary.startswith("python"):
        return False
    script_args = argv[1:]
    for arg in script_args:
        if arg.startswith("-"):
            continue
        name = arg.rsplit("/", 1)[-1]
        if name == "rcb_agent.py":
            return True
        if name == "main.py":
            return any(a == "--goal" or a.startswith("--goal") for a in script_args)
    return False


def foreign_runs() -> list[str]:
    """Any AutoR process that is not ours. Refuse to start alongside one."""
    found: list[str] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == os.getpid():
            continue
        argv = process_argv(pid)
        if is_backed_run(argv):
            found.append(f"{pid} {' '.join(argv).strip()[:110]}")
    return found


# ---------------------------------------------------------------------------
# Reading a finished workspace
# ---------------------------------------------------------------------------


def latest_run_root(workspace: Path) -> Path | None:
    roots = sorted(p for p in (workspace / ".autor").glob("*") if p.is_dir())
    return roots[-1] if roots else None


def search_level(stdout_path: Path) -> str:
    """The resolved web-search level, from the one place it is ever stated.

    Not from ``run_config.json``, which records the *request* (``"auto"``). The same
    command line produced ``level: info`` twice and ``level: warn`` once here, the warn
    being a run whose Stage 01 could not search at all because ``google.genai`` was not
    importable by that day's interpreter. That is the largest uncontrolled variable
    found in the real data and it is only ever announced as a progress event.
    """
    try:
        text = stdout_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    level = ""
    for line in text.splitlines():
        if '"web_search"' not in line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("stage") == "web_search":
            level = str(payload.get("level") or "")
    return level


def bench_image_sweep(workspace: Path) -> list[Path]:
    """The list ``evaluation/score._find_generated_images`` builds, in its order.

    ``outputs/`` and then ``report/``, and the judge is shown the first five of it
    against *every* image criterion. Duplicated here for the same reason
    :data:`IMAGE_SUFFIXES` is: what the gate and the report need to know is what the
    scorer would show, and importing the bench at report time makes the report depend on
    a checkout being present exactly when things have gone wrong.
    """
    found: list[Path] = []
    for directory in (workspace / "outputs", workspace / "report"):
        if not directory.exists():
            continue
        found.extend(
            sorted(
                path
                for path in directory.rglob("*")
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
            )
        )
    return found


def harvest(
    workspace: Path, stdout_path: Path | None = None, *, task_id: str = ""
) -> dict[str, Any]:
    """Everything the admission gate and the environment digest read off a workspace.

    ``task_id`` is the identity of the run being harvested and has to be passed in.
    ``rcb_agent.py`` writes ``_meta.json`` once, at the very end, so every run the stall
    watchdog killed — the case the watchdog exists for — has none, and reading the id out
    of a file that is not there yields ``None``. ``next_action`` keys on
    ``(task_id, arm)``, so a ``None`` there does not lose one field: it makes the whole
    attempt invisible to the planner, which sees no attempts, relaunches attempt 1, and
    does it again forever — the automated version of the kill-and-relaunch disaster this
    driver was written to prevent.
    """
    meta = read_json(workspace / "_meta.json")
    roots = sorted(p for p in (workspace / ".autor").glob("*") if p.is_dir())
    root = roots[-1] if roots else None
    manifest = read_json(root / "run_manifest.json") if root else {}
    config = read_json(root / "run_config.json") if root else {}
    log_text = ""
    if root and (root / "logs.txt").exists():
        log_text = (root / "logs.txt").read_text(encoding="utf-8", errors="replace")

    images_under_outputs = sum(
        1
        for path in (workspace / "outputs").rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    report_md_count = len(list((workspace / "report").glob("*.md")))
    # Counting is not naming. score.py falls back to the first *.md an unsorted glob
    # yields when report.md is absent, so "exactly one markdown file" is satisfied by a
    # workspace holding only `draft.md` -- and the draft is then scored as the
    # deliverable with nothing recording which file was read.
    report_md_present = (workspace / "report" / "report.md").is_file()

    stages: list[str] = []
    if root:
        summary = read_json(root / "evolution" / "summary.json")
        stages = sorted(str(key) for key in (summary.get("stages") or {}))

    dose = False
    if root:
        for prompt in (root / "prompt_cache").glob("07_*.prompt.md"):
            body = prompt.read_text(encoding="utf-8", errors="replace")
            # The channel's own heading, not `build_block`'s crux sub-heading: a block
            # made of rejected idea-pool candidates alone carries no crux sub-heading and
            # is still a delivered dose of the channel under test.
            if SETTLED_REASONING_HEADING in body:
                dose = True
                break

    return {
        "meta_status": meta.get("status"),
        "meta_report_source": meta.get("report_source"),
        "meta_pipeline_completed": meta.get("pipeline_completed"),
        "meta_duration_seconds": meta.get("duration_seconds"),
        "run_id": meta.get("run_id") or workspace.name,
        "task_id": meta.get("task_id") or task_id,
        "autor_run_count": len(roots),
        "run_root": str(root) if root else "",
        "run_status": manifest.get("run_status"),
        "last_event": manifest.get("last_event"),
        "run_log_text": log_text,
        "resource_exhausted_hits": count_quota_hits(log_text),
        "images_under_outputs": images_under_outputs,
        "report_md_count": report_md_count,
        "report_md_present": report_md_present,
        "agent_model": config.get("model", ""),
        "review_model": config.get("review_model", ""),
        "web_search_level": search_level(stdout_path) if stdout_path else "",
        # The request, next to the resolved level, because the level stopped separating
        # the two things it was added to separate: `--web-search off` announces itself at
        # `level: info` and so does an `auto` that found a working backend. Taken from
        # `run_config.json` rather than from the command line the driver remembers, so a
        # run relaunched by hand is described by what it recorded.
        "web_search_mode": str(config.get("web_search") or ""),
        "instructions_digest": instructions_digest(workspace),
        "autor_stages_scored": stages,
        "settled_reasoning_dose": dose,
    }


def git_head(worktree: Path) -> str:
    out = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    return out.stdout.strip() if out.returncode == 0 else ""


def git_dirty(worktree: Path) -> bool:
    out = subprocess.run(
        ["git", "-C", str(worktree), "status", "--porcelain"],
        capture_output=True, text=True, check=False,
    )
    return out.returncode != 0 or bool(out.stdout.strip())


def contrast_log(worktree: Path, control: str, treatment: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(worktree), "log", "--oneline", f"{control}..{treatment}"],
        capture_output=True, text=True, check=False,
    )
    return out.stdout if out.returncode == 0 else "(git log unavailable)"


# ---------------------------------------------------------------------------
# Launching one run
# ---------------------------------------------------------------------------


def state_path(plan: TrialPlan, task: str, arm: str, attempt: int) -> Path:
    return Path(plan.state_dir) / "runs" / f"{task}.{arm}.a{attempt}.json"


def all_states(plan: TrialPlan) -> list[dict[str, Any]]:
    directory = Path(plan.state_dir) / "runs"
    return [read_json(path) for path in sorted(directory.glob("*.json"))]


def make_workspace(plan: TrialPlan, task: str) -> Path:
    """Never reuse a directory, never pre-create the whole set.

    Two arms of one task pre-created in the same second land in the same directory —
    the benchmark names workspaces ``<TaskId>_<%Y%m%d_%H%M%S>`` and creates them with
    ``exist_ok=True`` — and then overwrite each other's report, making the paired
    difference identically zero.
    """
    base = Path(plan.state_dir) / "workspaces"
    base.mkdir(parents=True, exist_ok=True)
    while True:
        candidate = base / f"{task}_{time.strftime('%Y%m%d_%H%M%S')}"
        if not candidate.exists():
            candidate.mkdir(parents=True)
            return candidate
        time.sleep(1.1)


def setup_workspace(plan: TrialPlan, task: str, workspace: Path) -> None:
    """``rcb_agent.py`` creates four directories and nothing else.

    It does not copy ``data/`` or ``related_work/`` and does not write
    ``INSTRUCTIONS.md``, which the judge reads as background — so the driver has to do
    what ``TaskRunner.setup_workspace`` does, or the two arms are scored against
    different background text.
    """
    for name in ("code", "outputs", "report", "report/images"):
        (workspace / name).mkdir(parents=True, exist_ok=True)
    bench = Path(plan.bench)
    task_dir = bench / "tasks" / task
    import shutil

    for name in ("data", "related_work"):
        source = task_dir / name
        if source.is_dir():
            shutil.copytree(source, workspace / name, dirs_exist_ok=True)
    info = read_json(task_dir / "task_info.json")
    (workspace / "INSTRUCTIONS.md").write_text(
        f"# Task\n\n{info.get('task_description', '')}\n\nWorkspace: {workspace}\n",
        encoding="utf-8",
    )


def launch(plan: TrialPlan, task: str, arm: str, attempt: int) -> dict[str, Any]:
    spec = plan.control if arm == plan.control.label else plan.treatment
    worktree = Path(spec.worktree)
    workspace = make_workspace(plan, task)
    setup_workspace(plan, task, workspace)

    if plan.operator == "fake":
        argv = [
            sys.executable, str(Path(__file__).resolve()), "fake-run",
            "--workspace", str(workspace), "--task", task, "--arm", arm,
            "--sha", spec.sha, "--model", plan.agent_model,
            "--review-model", plan.review_model,
            "--treatment-label", plan.treatment.label,
            "--quality", str(plan.fake_quality if arm == plan.treatment.label else 0.0),
        ]
    else:
        argv = [
            sys.executable, str(worktree / "rcb_agent.py"),
            "--workspace", str(workspace),
            # Both, always. The reviewer model is resolved independently of the
            # operator's, so `--model opus` alone leaves the panels on the exhausted
            # sonnet pool, where they die without ever being classified as a quota
            # failure.
            "--model", plan.agent_model, "--review-model", plan.review_model,
        ]

    logs = Path(plan.state_dir) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stdout_path = logs / f"{task}.{arm}.a{attempt}.log"

    state = {
        "plan_digest": plan.digest,
        "task_id": task,
        "arm": arm,
        "attempt": attempt,
        "phase": "launched",
        "worktree": str(worktree),
        "revision_at_launch": git_head(worktree),
        "worktree_dirty_at_launch": git_dirty(worktree),
        "workspace": str(workspace),
        "argv": argv,
        "launched_at": time.time(),
        "stdout_path": str(stdout_path),
        "env": {
            "ANTHROPIC_VERTEX_PROJECT_ID": os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID", ""),
            "CLOUD_ML_REGION": os.environ.get("CLOUD_ML_REGION", ""),
            "python": sys.executable,
        },
        "foreign_pids_at_launch": foreign_runs(),
    }
    path = state_path(plan, task, arm, attempt)
    write_json(path, state)

    # A file, not a pipe. `emit_event` flushes on every event, and a driver killed
    # while holding the read end leaves the agent taking a BrokenPipe on its next write.
    with open(stdout_path, "ab", buffering=0) as sink:
        child = subprocess.Popen(
            argv, stdout=sink, stderr=subprocess.STDOUT, start_new_session=True, cwd=str(worktree)
        )
    state["child_pid"] = child.pid
    state["child_pgid"] = os.getpgid(child.pid)
    write_json(path, state)

    stalled = watch(child, workspace, plan.stall_seconds)

    finish = dict(state)
    finish.update(harvest(workspace, stdout_path, task_id=task))
    finish.update(
        {
            "phase": "finished",
            "finished_at": time.time(),
            "exit_code": child.returncode,
            "revision_at_finish": git_head(worktree),
            "worktree_dirty_at_finish": git_dirty(worktree),
            "stalled": stalled,
        }
    )
    finish["classification"] = classify_run(finish)
    # The log text can be tens of megabytes; it was read to classify and is not state.
    finish.pop("run_log_text", None)
    write_json(path, finish)
    return finish


def watch(child: subprocess.Popen, workspace: Path, stall_seconds: int) -> bool:
    """Wait, killing only on a stalled heartbeat. No per-run wall clock."""
    last_seen = time.time()
    while child.poll() is None:
        # A second. The run takes hours, so the polling cost is nothing, and the
        # alternative — a long poll — is a driver that notices a stall late and a dry
        # run that spends its whole wall clock inside `sleep`.
        time.sleep(1)
        beat = heartbeat(workspace)
        if beat > last_seen:
            last_seen = beat
        if time.time() - last_seen > stall_seconds:
            kill_group(child)
            return True
    return False


def heartbeat(workspace: Path) -> float:
    """``logs_raw.jsonl``'s mtime, and nothing else.

    ``run_manifest.json`` updates on stage transitions — one measured run was eight
    minutes stale while healthy — and ``_meta.json`` is written once, at the end.
    """
    latest = 0.0
    for path in (workspace / ".autor").glob("*/logs_raw.jsonl"):
        try:
            latest = max(latest, path.stat().st_mtime)
        except OSError:  # pragma: no cover
            continue
    return latest


def kill_group(child: subprocess.Popen) -> None:
    """Kill the child's group, then give up loudly rather than use ``pkill -f``.

    Grandchildren survive: the operator's Bash tool puts each command in its own
    process group, so ``killpg`` on the driver's group does not reach them. A workspace
    whose long-running python may still be writing is marked void rather than trusted.
    """
    try:
        os.killpg(os.getpgid(child.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):  # pragma: no cover
        return
    try:
        child.wait(timeout=60)
    except subprocess.TimeoutExpired:  # pragma: no cover
        try:
            os.killpg(os.getpgid(child.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_path(plan: TrialPlan, task: str, arm: str, attempt: int, label: str, rep: int) -> Path:
    return (
        Path(plan.state_dir) / "scores" / f"{task}.{arm}.a{attempt}.{label}.r{rep}.json"
    )


def score_once(plan: TrialPlan, state: Mapping[str, Any], out: Path, *, draws: int) -> bool:
    """One score file, holding ``draws`` judge passes over the same workspace.

    ``draws`` is keyword-only and has no default, which is the whole of the fix for the
    knob that did not arrive. The plan declared ``replicates: 3`` and this function built
    a command line with no ``--draws`` on it, so ``score_rcb_run.py`` took its own default
    of 1 and every score file the driver has ever written says ``"draws": 1`` and
    ``"total_spread": null`` — including the one the first live pair's 8.5-point gap was
    read off. The plan's count reached ``final_pass``'s file loop and stopped there, one
    layer above the process that talks to the judge, on a path a trial in flight has not
    taken yet. A default here would have let the same call site keep saying nothing;
    naming the count at each of the two call sites is what makes the spend legible.

    The two realisations are equivalent and :func:`judge_draws_in` is what makes them so:
    ``final_pass`` spends the budget as ``replicates`` separately checkpointed files of
    one draw each, so a judge flake costs one draw rather than all of them, and the
    in-loop score has only one file and spends it as one file of ``replicates`` draws.
    Either way the arm's recorded draw count is the plan's.
    """
    workspace = Path(str(state["workspace"]))
    if plan.judge_kind == "fake":
        return fake_score(plan, workspace, out, draws=draws)
    argv = [
        sys.executable, str(REPO_ROOT / "tools" / "score_rcb_run.py"),
        "--workspace", str(workspace), "--bench", plan.bench,
        "--judge", plan.judge_kind, "--model", plan.judge_model, "--out", str(out),
        "--draws", str(draws),
    ]
    env = dict(os.environ)
    # Only pins the iteration order of the bench's `IMAGE_EXTENSIONS` set, which decides
    # *which five* images every image criterion is shown. It does not pin `rglob`'s
    # order, so this narrows the variance rather than removing it.
    env["PYTHONHASHSEED"] = "0"
    done = subprocess.run(argv, env=env, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        sys.stderr.write(done.stdout[-4000:] + done.stderr[-4000:])
    # The tool exits 1 and writes nothing when any judge call failed. That refusal is
    # the pair-killing gate, inherited rather than reimplemented.
    return done.returncode == 0 and out.exists()


def fake_score(plan: TrialPlan, workspace: Path, out: Path, *, draws: int = 1) -> bool:
    """A deterministic stand-in judge, for exercising the harness without spending it.

    It reads the real checklist, so weights, item count, types and ordering are the
    benchmark's; only the scores are fabricated. The fake report carries a
    ``FAKE_QUALITY`` line, which is the one thing the fake judge reads out of it, so a
    dry run produces a real, signed, non-zero difference instead of two identical
    columns that would let a broken seam pass.

    ``draws`` is folded by :func:`tools.score_rcb_run.aggregate_draws`, the function the
    real scorer folds with, and the fabricated score moves with the draw index. Both
    halves are the point. A fake judge that ignored ``draws`` would write ``"draws": 1``
    into every dry run, so the seam this branch exists to exercise — a declared replicate
    count arriving at the process that talks to the judge — would be exercised on the one
    path no test can afford to take. And a fake judge that repeated an identical draw
    would report a spread of exactly 0.0 over three of them, which is the reading
    ``resolution_is_measured`` exists to keep off the page: a stochastic judge that
    resolved every item perfectly.
    """
    from tools.score_rcb_run import aggregate_draws

    meta = read_json(workspace / "_meta.json")
    task = str(meta.get("task_id") or "")
    checklist = json.loads(
        (Path(plan.bench) / "tasks" / task / "target_study" / "checklist.json").read_text(
            encoding="utf-8"
        )
    )
    report = workspace / "report" / "report.md"
    text = report.read_text(encoding="utf-8") if report.exists() else ""
    quality = 0.0
    for line in text.splitlines():
        if line.startswith("FAKE_QUALITY:"):
            quality = float(line.split(":", 1)[1])
    drawn: list[dict] = []
    for draw_no in range(max(1, draws)):
        items = []
        total_weighted = 0.0
        total_weight = 0.0
        for index, entry in enumerate(checklist):
            weight = float(entry.get("weight", 0.0))
            seed = hashlib.sha256(
                f"{task}|{index}|{workspace.name}|{out.name}|{draw_no}".encode("utf-8")
            ).digest()
            jitter = seed[0] % 5
            score = max(0, min(100, int(20 + quality + jitter)))
            items.append(
                {
                    "index": index,
                    "type": entry.get("type", "text"),
                    "content": str(entry.get("content", ""))[:200],
                    "weight": weight,
                    "score": score,
                    "reasoning": "fake judge",
                }
            )
            total_weighted += weight * score
            total_weight += weight
        drawn.append(
            {
                "run_id": meta.get("run_id"),
                "task_id": task,
                "items": items,
                "total_weight": total_weight,
                "total_score": round(total_weighted / total_weight, 2) if total_weight else 0,
                "judge_model": plan.judge_model,
                "judge_calls": len(items),
                "judge_failures": [],
                "checklist_items_expected": len(checklist),
                # The real sweep, not an empty list: which images the judge is shown is
                # 60.6% of the benchmark's weight, and a dry run that reports none of them
                # exercises none of the reporting that exists to say so.
                "images_shown": [str(path) for path in bench_image_sweep(workspace)[:5]],
                "images_available": len(bench_image_sweep(workspace)),
                "bench_revision": "fake-bench",
            }
        )
    write_json(out, aggregate_draws(drawn))
    return True


def final_pass(plan: TrialPlan) -> None:
    """Re-score every admitted workspace, back to back, at the end.

    Scoring inside the loop is early warning and never enters a number: it is minutes
    old for the first workspace and days old for the last, so a judge that drifted
    across the trial would ride into the published difference unmeasured. The published
    scores all come from one continuous pass with the same judge, and the replicates
    inside it are what turn the noise band from folklore into a measurement.

    ``draws=1`` per file, and the loop is the replication. That split is the reason a
    lost draw costs one draw: the scorer writes nothing at all when any judge call in an
    invocation fails, so asking one invocation for all three would make the judge's worst
    minute cost the whole arm's replication rather than a third of it.
    """
    lost: list[str] = []
    for state in all_states(plan):
        if state.get("phase") != "finished" or state.get("classification") != "ok":
            continue
        for rep in range(plan.replicates):
            out = score_path(
                plan, str(state["task_id"]), str(state["arm"]), int(state["attempt"]), "final", rep
            )
            if out.exists():
                continue
            for _try in range(2):
                # A judge failure inside one replicate is a reason to redraw that
                # replicate, not to kill the pair. Escalating on the first flake would
                # hand a four-day trial to the judge's worst minute.
                if score_once(plan, state, out, draws=1):
                    break
            else:
                # Giving up quietly is how an arm scored once was published as an arm
                # scored three times. The count reaches the report through
                # `RunEnvironment.judge_replicates`; this is the operator's copy, on the
                # stdout they are watching while it happens.
                lost.append(out.name)
                print(f"  LOST REPLICATE: {out.name} could not be scored in two tries")
    write_json(
        Path(plan.state_dir) / "final_pass.json",
        {"done": True, "at": time.time(), "unscored_replicates": sorted(lost)},
    )


# ---------------------------------------------------------------------------
# Building evidence and reporting
# ---------------------------------------------------------------------------


def evidence_for(plan: TrialPlan, state: Mapping[str, Any]) -> ArmEvidence | None:
    task = str(state.get("task_id") or "")
    arm = str(state.get("arm") or "")
    attempt = int(state.get("attempt") or 1)
    payloads = []
    for rep in range(plan.replicates):
        path = score_path(plan, task, arm, attempt, "final", rep)
        if path.exists():
            payloads.append(read_json(path))
    if not payloads:
        return None

    first = payloads[0]
    checklist = Path(plan.bench) / "tasks" / task / "target_study" / "checklist.json"
    env = RunEnvironment(
        checklist_digest=digest_bytes(checklist),
        judge_model=str(first.get("judge_model") or ""),
        agent_model=str(state.get("agent_model") or ""),
        review_model=str(state.get("review_model") or ""),
        web_search_level=str(state.get("web_search_level") or ""),
        web_search_mode=str(state.get("web_search_mode") or ""),
        instructions_digest=str(state.get("instructions_digest") or ""),
        bench_revision=str(first.get("bench_revision") or ""),
        # Whatever landed on disk, never what the plan asked for. Two arms averaged over
        # different numbers of judge draws are not comparable, and putting the count in
        # the digest is what makes the composition refusal that already exists say so.
        # `judge_draws_in` and not `len(payloads)`: a file is a checkpoint, not a draw,
        # and one file the scorer wrote with `--draws 3` used to be counted as one.
        judge_replicates=judge_draws_in(payloads),
    )
    facts = {
        "meta_status": state.get("meta_status"),
        "meta_pipeline_completed": state.get("meta_pipeline_completed"),
        "meta_report_source": state.get("meta_report_source"),
        "autor_run_count": state.get("autor_run_count"),
        "images_under_outputs": state.get("images_under_outputs"),
        "report_md_count": state.get("report_md_count"),
        "report_md_present": state.get("report_md_present"),
        "last_event": state.get("last_event"),
        # Reported, never gated. `run_status: cancelled` is how the manifest records a
        # run whose auto-skip budget ran out and which was routed to the deliverable
        # stage to write what it had; two of the three finished runs of the live
        # stage-graph trial ended that way. It comes off `run_manifest.json`, which is
        # inside the run root and therefore writable by the party a gate would
        # constrain, so no admission clause reads it and none may: it is a label on a
        # number, not a verdict.
        "run_status": state.get("run_status"),
        "resource_exhausted_hits": state.get("resource_exhausted_hits", 0),
        "revision_at_launch": state.get("revision_at_launch"),
        "revision_at_finish": state.get("revision_at_finish"),
        "worktree_dirty": bool(state.get("worktree_dirty_at_launch"))
        or bool(state.get("worktree_dirty_at_finish")),
    }
    failures: list[str] = []
    for payload in payloads:
        failures.extend(str(item) for item in (payload.get("judge_failures") or []))
    return ArmEvidence(
        task_id=task,
        arm=arm,
        run_id=str(state.get("run_id") or Path(str(state.get("workspace", ""))).name),
        workspace=str(state.get("workspace") or ""),
        env=env,
        items=items_from_score_payloads(payloads),
        published_total=float(first.get("total_score") or 0.0),
        replicates_requested=int(plan.replicates),
        images_shown=len(first.get("images_shown") or []),
        images_available=int(
            first.get("images_available") or len(first.get("images_shown") or [])
        ),
        judge_failures=tuple(failures),
        checklist_items_expected=int(
            first.get("checklist_items_expected") or len(first.get("items") or [])
        ),
        facts=facts,
        autor_stages_scored=tuple(state.get("autor_stages_scored") or ()),
        settled_reasoning_dose=bool(state.get("settled_reasoning_dose")),
    )


def driver_refusals(
    states: Sequence[Mapping[str, Any]],
    scored: set[tuple[str, str]],
    *,
    final_pass_done: bool,
) -> list[Refusal]:
    """Every run that died before the admission gate could ever look at it.

    ``final_pass`` scores only ``classification == "ok"`` and ``evidence_for`` returns
    ``None`` without score files, so a run killed by quota, by the watchdog, by a backend
    outage, by a fallback report, by an incomplete pipeline or by the scorer's own
    refusal produces no evidence, reaches no clause, and used to be rendered as "no
    `<arm>` arm" — the same sentence as an arm that was never launched. The report tells
    the reader to judge the difference on the per-arm death counts; those counts were
    structurally zero for exactly the deaths the paragraph warns about.

    ``phase == "launched"`` is not here: a run in flight has not died, and calling it a
    refusal would report every interim run as an attrition. Neither is a healthy run with
    no score file until the final pass has been over it — before that it is a run waiting
    to be scored, and the report runs at any moment by design.
    """
    worst: dict[tuple[str, str], str] = {}
    for state in states:
        key = (str(state.get("task_id") or ""), str(state.get("arm") or ""))
        if not key[0] or not key[1]:
            continue
        phase = str(state.get("phase") or "")
        classification = str(state.get("classification") or "")
        if phase == "refused":
            # The driver's last word on this (task, arm), so it wins over whatever the
            # individual attempts were classified as.
            worst[key] = classification or "refused"
        elif phase == "abandoned":
            worst.setdefault(key, "abandoned")
        elif phase == "finished":
            if classification and classification != "ok":
                worst.setdefault(key, classification)
            elif key not in scored and final_pass_done:
                # Ran, was admissible, the final pass has been over it and no score file
                # exists: the judge failed every draw, or the scorer could not write. A
                # whole trial of these published `pairs: 0` with an empty ledger, no
                # exclusion line and no diagnosis anywhere.
                worst.setdefault(key, "unscored")
    return [
        Refusal(task, arm, (driver_clause(cause),))
        for (task, arm), cause in sorted(worst.items())
    ]


def build_report(plan: TrialPlan) -> str:
    """A pure function of the state directory: nothing derived survives between runs.

    Every artifact under the state directory is rebuilt from ``runs/`` and ``scores/``
    on each invocation, so re-running after fixing a bug in the producer cannot leave
    half of an old answer behind.
    """
    states = all_states(plan)
    evidences = []
    scored: set[tuple[str, str]] = set()
    for state in states:
        if state.get("phase") != "finished":
            continue
        item = evidence_for(plan, state)
        if item is not None:
            evidences.append(item)
            scored.add((item.task_id, item.arm))

    trial = collect_rcb_pairs(
        evidences,
        capability=plan.capability,
        control_arm=plan.control.label,
        treatment_arm=plan.treatment.label,
        planned_pairs=plan.planned_pairs,
        driver_refusals=driver_refusals(
            states, scored,
            final_pass_done=(Path(plan.state_dir) / "final_pass.json").exists(),
        ),
    )
    # Observed, then declared. The header used to print the plan's field whatever had
    # actually scored the runs, which is the one line a reader would use to decide the
    # number is comparable to a published figure.
    observed = sorted({item.env.judge_model for item in evidences if item.env.judge_model})
    return format_rcb_trial_report(
        trial,
        contrast_log=contrast_log(Path(plan.treatment.worktree), plan.control.sha, plan.treatment.sha),
        plan_digest=plan.digest,
        judge_model=", ".join(observed) or plan.judge_model,
        planned_judge_model=plan.judge_model,
    )


# ---------------------------------------------------------------------------
# The fake operator
# ---------------------------------------------------------------------------


def fake_run(args: argparse.Namespace) -> int:
    """Fabricate a workspace shaped exactly like a finished AutoR run.

    Deliberately a real subprocess launched with ``start_new_session``: the state
    machine, the lock, the process-group handling and the heartbeat are the parts most
    likely to be wrong, and a fake that runs in-process would test none of them.
    """
    workspace = Path(args.workspace)
    root = workspace / ".autor" / time.strftime("%Y%m%d_%H%M%S")
    (root / "evolution").mkdir(parents=True, exist_ok=True)
    (root / "prompt_cache").mkdir(parents=True, exist_ok=True)

    # The treatment arm is the one that carries the settled-reasoning block; a run that
    # argued nothing sends nothing, which is the zero-dose case the report refuses to
    # call a test of the channel.
    if args.arm == args.treatment_label:
        (root / "prompt_cache" / "07_report_attempt_01.prompt.md").write_text(
            # The channel's heading above the block, which is what a real Stage 07 prompt
            # carries. Writing only `build_block`'s crux sub-heading here is what let the
            # detector read that sub-heading and still look correct in the dry run.
            f"{SETTLED_REASONING_HEADING}\n\n"
            "## Methodological questions this run settled\n\nfake\n",
            encoding="utf-8",
        )
    else:
        (root / "prompt_cache" / "07_report_attempt_01.prompt.md").write_text(
            "no settled reasoning\n", encoding="utf-8"
        )

    for beat in range(3):
        with open(root / "logs_raw.jsonl", "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"beat": beat, "at": time.time()}) + "\n")
        time.sleep(0.2)
    (root / "logs.txt").write_text("=== fake | run ===\nnothing went wrong\n", encoding="utf-8")
    write_json(root / "run_manifest.json", {"run_status": "completed", "last_event": "run.completed"})
    write_json(root / "run_config.json", {"model": args.model, "review_model": args.review_model})
    write_json(root / "evolution" / "summary.json", {"stages": {f"0{n}_s": {} for n in range(1, 9)}})

    (workspace / "report").mkdir(parents=True, exist_ok=True)
    (workspace / "report" / "report.md").write_text(
        f"# {args.task}\n\nFAKE_QUALITY: {args.quality}\n\n## Discussion\n\nfake.\n",
        encoding="utf-8",
    )
    # On stdout, exactly where the real harness announces it, so `search_level` is
    # exercised by the dry run rather than short-circuited for it.
    print(json.dumps({"type": "progress", "stage": "web_search", "level": "info"}), flush=True)
    write_json(
        workspace / "_meta.json",
        {
            "task_id": args.task,
            "run_id": workspace.name,
            "status": "completed",
            "report_source": "agent",
            "pipeline_completed": True,
            "duration_seconds": 1,
            "workspace": str(workspace),
        },
    )
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def load_plan(path: Path) -> TrialPlan:
    payload = read_json(path)
    if not payload:
        raise SystemExit(f"no plan at {path}")
    plan = TrialPlan.from_dict(payload)
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


def cmd_plan(plan: TrialPlan) -> int:
    frozen = Path(plan.state_dir) / "plan.json"
    if frozen.exists():
        print(f"already frozen: {read_json(frozen).get('digest', '')[:16]}")
        return 0
    payload = plan.to_dict()
    payload["digest"] = plan.digest
    payload["frozen_at"] = time.time()
    write_json(frozen, payload)
    print(f"frozen {plan.planned_pairs} planned pairs, digest {plan.digest[:16]}")
    return 0


def cmd_run(plan: TrialPlan) -> int:
    if not (Path(plan.state_dir) / "plan.json").exists():
        raise SystemExit("freeze the plan first: `rcb_trial.py plan --plan <path>`")
    intruders = foreign_runs()
    if intruders:
        print("REFUSING TO START. AutoR is already running here:", file=sys.stderr)
        for line in intruders:
            print(f"  {line}", file=sys.stderr)
        print(
            "Two drivers is the concurrency that exhausts the quota that then kills "
            "both. Wait, or kill those pids by pgid (never `pkill -f`).",
            file=sys.stderr,
        )
        return 2

    lock = acquire_lock(Path(plan.state_dir))
    try:
        while True:
            states = all_states(plan)
            done_marker = Path(plan.state_dir) / "final_pass.json"
            action = next_action(
                plan,
                states,
                now=time.time(),
                # Only AutoR-shaped pids. A bare `/proc` listing would abort the trial on
                # any pid the kernel happened to hand to somebody else's process after
                # the driver died, which is the ordinary case rather than the rare one.
                live_pids=autor_pids(),
                final_pass_done=done_marker.exists(),
            )
            print(f"[{time.strftime('%H:%M:%S')}] {action}")
            if action.kind == "done":
                break
            if action.kind == "abort":
                print(action.reason, file=sys.stderr)
                return 2
            if action.kind == "abandon":
                path = state_path(plan, action.task_id, action.arm, action.attempt)
                state = read_json(path)
                state["phase"] = "abandoned"
                state["abandoned_reason"] = action.reason
                write_json(path, state)
                continue
            if action.kind == "refuse":
                path = state_path(plan, action.task_id, action.arm, 0)
                write_json(
                    path,
                    {
                        "task_id": action.task_id, "arm": action.arm, "attempt": 0,
                        "phase": "refused", "classification": action.reason,
                        "plan_digest": plan.digest,
                    },
                )
                continue
            if action.kind == "backoff":
                print(f"  quota backoff {action.seconds}s: {action.reason}")
                time.sleep(action.seconds)
                launch(plan, action.task_id, action.arm, action.attempt)
                continue
            if action.kind == "launch":
                finished = launch(plan, action.task_id, action.arm, action.attempt)
                print(f"  classification: {finished.get('classification')}")
                continue
            if action.kind == "score":
                path = state_path(plan, action.task_id, action.arm, action.attempt)
                state = read_json(path)
                out = score_path(
                    plan, action.task_id, action.arm, action.attempt, "early", 0
                )
                # `draws=plan.replicates`, because this is the one score that exists while
                # a trial is in flight and it is what anybody reads for days. Left at one
                # draw it published `total_spread: null` beside a gap of 8.5 points, on a
                # judge whose measured spread over eight draws of one unchanged artifact
                # set was 8.5 — so the number on screen could not say whether it had
                # measured anything. One file rather than `replicates` of them: the early
                # score is not checkpointed and is thrown away by `final_pass`, so there is
                # nothing here for a per-file retry to salvage.
                score_once(plan, state, out, draws=plan.replicates)
                # The in-loop score exists so a systematically-refusing gate is visible
                # after run one instead of after day five. It never enters a number.
                evidence_state = dict(state)
                state["scored"] = True
                state["early_score_path"] = str(out) if out.exists() else ""
                write_json(path, state)
                _announce_admission(plan, evidence_state, out)
                continue
            if action.kind == "final_pass":
                final_pass(plan)
                continue
    finally:
        release_lock(lock)

    report = build_report(plan)
    (Path(plan.state_dir) / "report.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


def _announce_admission(plan: TrialPlan, state: Mapping[str, Any], out: Path) -> None:
    """Say straight away whether that run can ever become a number.

    Ten clauses of heuristic over internal artifacts can plausibly admit nothing at
    all: of four real workspaces on this box, one has ``report_source == "synthesized"``
    and one was still running. Finding that out after the first run costs hours;
    finding it out from the report costs the whole trial.
    """
    from src.rcb_trial import admit_arm

    if not out.exists():
        print("  admission: no score file — the scorer refused or the judge failed")
        return
    payload = read_json(out)
    probe = dict(state)
    probe["early"] = True
    evidence = ArmEvidence(
        task_id=str(state.get("task_id") or ""),
        arm=str(state.get("arm") or ""),
        run_id=str(state.get("run_id") or ""),
        workspace=str(state.get("workspace") or ""),
        # Only the draw count is filled: the rest of the environment is a gate the final
        # pass applies and this is a one-arm probe, but a probe that said "0 draws" over
        # a file the scorer had drawn three times would misreport the one thing this
        # branch just changed.
        env=RunEnvironment(judge_replicates=judge_draws_in([payload])),
        items=items_from_score_payloads([payload]),
        published_total=float(payload.get("total_score") or 0.0),
        replicates_requested=int(plan.replicates),
        judge_failures=tuple(str(x) for x in (payload.get("judge_failures") or [])),
        checklist_items_expected=int(
            payload.get("checklist_items_expected") or len(payload.get("items") or [])
        ),
        facts={
            "meta_status": state.get("meta_status"),
            "meta_pipeline_completed": state.get("meta_pipeline_completed"),
            "meta_report_source": state.get("meta_report_source"),
            "autor_run_count": state.get("autor_run_count"),
            "images_under_outputs": state.get("images_under_outputs"),
            "report_md_count": state.get("report_md_count"),
            "report_md_present": state.get("report_md_present"),
            "last_event": state.get("last_event"),
            "resource_exhausted_hits": state.get("resource_exhausted_hits", 0),
            "revision_at_launch": state.get("revision_at_launch"),
            "revision_at_finish": state.get("revision_at_finish"),
            "worktree_dirty": bool(state.get("worktree_dirty_at_launch")),
        },
    )
    ok, failed = admit_arm(evidence)
    print(f"  admission: {'ADMITTED' if ok else 'REFUSED — ' + ', '.join(failed)}")
    # On the operator's stdout while it happens, for the same reason the report prints it:
    # a total whose sampling is unstated cannot be compared with another one, and this is
    # the number they will be reading for the four days before the final pass exists.
    print(
        f"  judge draws: {evidence.replicates} of {plan.replicates} planned"
        + ("" if evidence.replicates > 1 else "  (spread unmeasured)")
    )
    if state.get("run_status") and state.get("run_status") != "completed":
        print(
            f"  run_status: {state.get('run_status')} — the deliverable this score is of "
            "was truncated"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run", "report"):
        child = sub.add_parser(name)
        child.add_argument("--plan", required=True, type=Path)
    faker = sub.add_parser("fake-run")
    faker.add_argument("--workspace", required=True)
    faker.add_argument("--task", required=True)
    faker.add_argument("--arm", required=True)
    faker.add_argument("--sha", default="")
    faker.add_argument("--model", default="")
    faker.add_argument("--review-model", default="")
    faker.add_argument("--quality", type=float, default=0.0)
    faker.add_argument("--treatment-label", default="")
    args = parser.parse_args(argv)

    if args.command == "fake-run":
        return fake_run(args)

    plan = load_plan(args.plan)
    if args.command == "plan":
        return cmd_plan(plan)
    if args.command == "run":
        return cmd_run(plan)
    report = build_report(plan)
    (Path(plan.state_dir) / "report.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
