"""The part of a paired-trial driver that knows nothing about which benchmark it drives.

``tools/rcb_trial.py`` was written for ResearchClawBench and about a fifth of it is not
about ResearchClawBench at all: an ``os.link`` lock with a three-condition liveness test,
a ``/proc`` census that separates a process *running* an agent from a shell *mentioning*
one, atomic state writes for a directory on shared NFS, a stall watchdog that kills a
process group without ever reaching for ``pkill -f``, and three ``git`` readers. None of
it mentions a checklist, a judge or a task id. All of it is exactly what a second
benchmark's driver needs on the first day it exists.

**Why one module and not two copies.** The alternative was considered and is worse in a
way this repository has already paid for. Every function here encodes a defect that was
found by losing something real:

* the lock's liveness test checks the pid *and* its ``cmdline`` *and* the boot id,
  because each one alone gives a wrong answer -- a pid is reused, a cmdline cannot be
  read for a pid that is gone, and after a reboot a live pid with a matching cmdline can
  be somebody else entirely;
* ``claim_stale_lock`` takes a dead driver's lock over through ``os.link`` on a token
  named after that particular stale lock, because the bare ``os.replace`` it replaces
  let two drivers both read one stale lock and both proceed -- reproduced at two races
  in five on a ~1 ms window;
* ``is_backed_run`` requires the script to be an *argument after a python interpreter*,
  because the first version joined ``/proc/<pid>/cmdline`` and substring-matched it, so
  a shell scanning for the agent refused the driver by existing.

A copy inherits the code and not the reason. The second copy is edited by somebody
fixing a symptom on the day of a live trial, the two diverge, and the divergence is
invisible: both files pass their own tests, and the failure is a *pair* of drivers whose
answers to "is anyone else spending the quota" disagree. That is not a hypothetical
here. ``MEMORY``'s divergence lens is a list of two-encodings-of-one-idea defects found
in this tree, and the broker audit closed seven of them whose single cause was
guard-parity between two copies of one loader.

So: one module, imported by every driver, and the benchmark-specific half -- what a
finished workspace holds, what the judge is shown, what the plan means -- stays in the
driver that owns it.

**What is deliberately not here.** ``instructions_digest`` hashes the background file
one benchmark hands its judge; ``harvest`` reads a finished workspace the way that
benchmark's admission gate needs it read; ``bench_image_sweep`` reproduces the order
that benchmark's scorer picks images in. Those are statements about one benchmark and
belong to it. The line is not "does it touch the filesystem" but "does it name a file,
a field or a score that only one benchmark has" -- and the line is a test, not a
convention: ``tests/test_trial_driver.py`` reads this file and refuses either
benchmark's vocabulary in it.

``autor_pids`` sits closest to that line and is on this side of it by a hair, so the
hair is written down: it answers "is a pid I launched still alive", which is a different
question from ``is_backed_run``'s "is somebody else spending the quota", and it answers
it with the script names of *the driver asking*. It is not widened to
:data:`AGENT_SCRIPT_NAMES`, because a driver that counted another benchmark's agent as
one of its own live children would read a dead run as running and wait forever. A second
driver needs its own census, not this one; what it shares is the ``/proc`` reading
underneath.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence


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
# Watching one child
# ---------------------------------------------------------------------------


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
# The worktree under test
# ---------------------------------------------------------------------------


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
