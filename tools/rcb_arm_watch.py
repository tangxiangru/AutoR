#!/usr/bin/env python3
"""Wait for a benchmark arm to finish, score it with the reference judge, print the table.

Vendored from the harness that measured the `2ffaeb4` arm, paths and all, because the
defects it works around were each found the expensive way and a copy that lives only in a
scratch directory is a lesson that expires. The three constants at the top are what a
second arm has to change.

Runs detached. Scores each task as soon as its report exists rather than waiting for
the whole batch, so the scoring is mostly done by the time the last run lands.

Three things this is careful about, each because getting it wrong has cost a
measurement here before:

* **The judge is part of the result.** `score_rcb_run.py` defaults to the reference
  judge `gpt-5.1`; judge choice has been measured to move a score by ~16 points, so a
  number scored with anything else is not comparable to the arms in the table. The
  scorer prints the judge on every result and refuses to write one without it.
* **The instrument is held fixed.** The other two arms were scored with the copy of
  `score_rcb_run.py` under `autor-rcb-rerun/AutoR`, so this uses that same file rather
  than the one in the arm's own pinned clone. The newer copy only adds multi-draw
  support, but "only adds" is a claim about a diff, and holding the file identical is
  free.
* **A judge failure is not a zero.** The scorer refuses to write a result when any
  criterion's judge call failed, because the stock scorer records those as `score: 0`,
  indistinguishable from a criterion the report genuinely missed. A refusal here is
  retried, and if it keeps refusing the task is reported as *unscored* and left out of
  the mean rather than folded in as a zero.
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ARM = Path(__file__).resolve().parent
WORKSPACES = Path("/rmeng_data/robtang/rcb_runs/arm_2ffaeb4")
SCORES = ARM / "scores"
BENCH = Path("/home/robtang_google_com/RCB")

#: The same file the other two arms in the table were scored with. See the docstring.
SCORER = Path("/rmeng_data/robtang/autor-rcb-rerun/AutoR/tools/score_rcb_run.py")

#: Where the arms this one is compared against already live.
OTHER_ARMS = {
    "AutoR (Opus), pre-fix": Path("/rmeng_data/robtang/autor-rcb-rerun/arm_scores/full40"),
    "bare Claude Code (Opus)": Path(
        "/rmeng_data/robtang/autor-rcb-rerun/arm_scores/control_bare_cc"
    ),
}

#: A report below this is the adapter's stub, not a deliverable. `MIN_REPORT_CHARS`.
MIN_REPORT_BYTES = 1200

POLL_SECONDS = 300
SCORE_TIMEOUT = 1800
MAX_ATTEMPTS = 3
EXPECTED_TASKS = 40


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).astimezone().strftime("%m-%d %H:%M:%S")
    line = f"[{stamp}] {message}"
    print(line, flush=True)
    with (ARM / "watch.log").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


#: What the batch runner's command line looks like, and nothing else's.
_RUNNER_MARKERS = ("run_batch.py", str(WORKSPACES))


def find_runner() -> int | None:
    """The batch runner's pid, found by scanning /proc rather than by being told.

    Taking the pid as an argument is how this went wrong the first time: the shell
    that computed it used `pgrep -f "run_batch.py --autor ..."`, which matched *its own
    command line* — the pattern was in it — and handed over the pid of a wrapper that
    exited seconds later. The watcher then saw "runner gone, no reports" and would have
    written a results table off an empty directory.

    So the pid is derived here, from a marker no shell running this scan can carry: the
    interpreter's own argv, plus the workspaces path. Re-derived every poll, so a runner
    that is restarted is picked back up instead of being declared finished.
    """
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        argv = [part for part in raw.split("\0") if part]
        if not argv or "python" not in Path(argv[0]).name:
            continue
        if all(any(marker in part for part in argv) for marker in _RUNNER_MARKERS):
            return int(entry.name)
    return None


def task_of(workspace: Path) -> str:
    """`Astronomy_000_20260815_172437` -> `Astronomy_000`."""
    name = workspace.name
    parts = name.rsplit("_", 2)
    return parts[0] if len(parts) == 3 and parts[1].isdigit() else name


def batch_state() -> dict[str, dict]:
    """What the runner says about each task. The authoritative completion signal.

    `run_batch.py` rewrites this atomically after every task, with `status`,
    `exit_code`, `report_bytes` and `images`. The first version of this watcher never
    read it, and that was the whole bug: it treated "a report file exists and is big
    enough" as "the task is finished", but the workspace contract requires the agent to
    keep `report/report.md` current *at every stage*, so a report exists for hours
    before the run ends.
    """
    try:
        return json.loads((ARM / "batch_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def finished_workspaces() -> dict[str, Path]:
    """Workspaces the runner has recorded as over, with a report worth scoring.

    Two gates, and the first one is the one that matters.

    **The runner has to have finished the task.** Scoring a live workspace does not
    just risk a stale draft -- it changes what the judge is shown. `collect_figures`
    trims `report/images/` at export time down to the figures the report actually
    references; the benchmark's scorer then takes the first five images it finds in an
    unordered walk, and image criteria carry 60.6% of the total weight. Measured on this
    box: every finished run in the reference arm ends with 4 or 5 images, while two
    workspaces in this arm are sitting at 11 and 12 mid-flight. Score one of those early
    and three fifths of the weight is judged on a random five of twelve. Measured on the
    reference arm, the agent kept running for a median of 992 s after the last write to
    `report.md` -- 39 of 40 longer than one poll -- so this window is not a rare race,
    it is the normal case, and it moves the score one way only, on one arm only.
    """
    state = batch_state()
    out: dict[str, Path] = {}
    for workspace in sorted(WORKSPACES.glob("*/")):
        if workspace.name.startswith("."):
            continue  # the runner's own TMPDIR
        task = task_of(workspace)
        if state.get(task, {}).get("status") not in {"completed", "failed"}:
            continue
        report = workspace / "report" / "report.md"
        try:
            if not report.is_file() or report.stat().st_size < MIN_REPORT_BYTES:
                continue
        except OSError:
            continue
        out[task] = workspace
    return out


def score_one(task: str, workspace: Path) -> bool:
    out = SCORES / f"{task}.json"
    if out.exists():
        return True
    SCORES.mkdir(parents=True, exist_ok=True)
    log(f"scoring {task}")
    started = time.time()
    with (SCORES / f"{task}.log").open("w", encoding="utf-8") as handle:
        try:
            completed = subprocess.run(  # noqa: S603
                [
                    sys.executable, str(SCORER),
                    "--workspace", str(workspace),
                    "--bench", str(BENCH),
                    "--out", str(out),
                ],
                stdout=handle, stderr=subprocess.STDOUT,
                timeout=SCORE_TIMEOUT, check=False,
            )
            code = completed.returncode
        except subprocess.TimeoutExpired:
            code = -1
            handle.write("\nTIMED OUT\n")
    elapsed = int(time.time() - started)
    if code == 0 and out.exists():
        payload = json.loads(out.read_text(encoding="utf-8"))
        # `total_score` is already a weight-weighted sum of 0-100 criterion scores,
        # so dividing by the weight gives the 0-100 arm score directly. Scaling by
        # 100 again reads 2357 for a 23.57 and is how a dry run earns its keep.
        total = payload["total_score"] / payload["total_weight"]
        log(f"  {task}: {total:.2f}  judge={payload.get('judge_model')}  {elapsed}s")
        return True
    log(f"  {task}: scorer exit={code} after {elapsed}s (no result written)")
    return False


def arm_scores(directory: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            out[path.stem] = payload["total_score"] / payload["total_weight"]
        except (OSError, ValueError, KeyError, ZeroDivisionError):
            continue
    return out


def zero_criteria(directory: Path) -> tuple[int, int]:
    zeros = total = 0
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for item in payload.get("items", []):
            total += 1
            if not (item.get("score") or 0):
                zeros += 1
    return zeros, total


def write_table(unscored: list[str], no_report: list[str]) -> str:
    arms = {"AutoR (Opus), 2ffaeb4": SCORES}
    arms.update(OTHER_ARMS)
    scores = {name: arm_scores(path) for name, path in arms.items()}
    control = scores["bare Claude Code (Opus)"]
    mine = scores["AutoR (Opus), 2ffaeb4"]

    lines = [
        "# ResearchClawBench, one attempt per task, judge `gpt-5.1`",
        "",
        f"Written {datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')}.",
        "",
        "| arm | n | mean | median | tasks scoring 0 | zero criteria |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, table in scores.items():
        if not table:
            lines.append(f"| {name} | 0 | — | — | — | — |")
            continue
        values = list(table.values())
        zeros, criteria = zero_criteria(arms[name])
        # A mean over fewer than all 40 is not the same quantity as the reference arms'
        # mean over 40, so it is not bolded and it carries its own denominator. The
        # tasks that are missing are the ones that failed, so dropping them is not
        # neutral -- it moves this arm up against arms that dropped nothing.
        mean = f"**{statistics.mean(values):.2f}**" if len(values) == EXPECTED_TASKS \
            else f"{statistics.mean(values):.2f} ({len(values)}/{EXPECTED_TASKS})"
        lines.append(
            f"| {name} | {len(values)} | {mean} | "
            f"{statistics.median(values):.2f} | {sum(v == 0 for v in values)} | "
            f"{zeros}/{criteria}" + (f" ({zeros / criteria:.0%})" if criteria else "") + " |"
        )

    lines += ["", "## Paired, over the tasks both arms scored", ""]
    for other_name, other in ((n, scores[n]) for n in OTHER_ARMS):
        common = sorted(set(mine) & set(other))
        if len(common) < 2:
            lines.append(f"- vs {other_name}: only {len(common)} shared task(s), no comparison.")
            continue
        deltas = [mine[t] - other[t] for t in common]
        mean = statistics.mean(deltas)
        sem = statistics.stdev(deltas) / (len(deltas) ** 0.5)
        wins = sum(d > 0 for d in deltas)
        ties = sum(d == 0 for d in deltas)
        lines.append(
            f"- **vs {other_name}** (n={len(common)}): "
            f"{mean:+.2f} ± {sem:.2f} (1 paired SE, sample sd), "
            f"this arm wins {wins}, loses {len(common) - wins - ties}, ties {ties}. "
            f"Paired sd {statistics.stdev(deltas):.2f}, so this design resolves about "
            f"{2.8 * statistics.stdev(deltas) / (len(common) ** 0.5):.1f} points."
        )

    lines += [
        "",
        "## Reading this",
        "",
        "**The arms were not run under the same budget, and the difference is bigger than",
        "the effect anyone is looking for.** Measured from each run's own `_meta.json`:",
        "",
        "| arm | stage timeout | batch concurrency | wall limit |",
        "| --- | ---: | ---: | ---: |",
        "| AutoR 2ffaeb4 (this arm) | 14,400 s (adapter default) | 40 | none |",
        "| AutoR pre-fix | **1,800 s** | 8 | none |",
        "| bare Claude Code | n/a — no stage concept | — | 43,200 s |",
        "",
        "28 of the 40 pre-fix runs logged `Stage timed out`, and those 28 average **22.08**",
        "against **27.06** for the 12 that did not — a 4.99-point gap inside that one arm,",
        "which is the same size as the between-arm differences this table is about. So:",
        "",
        "- **This arm against the pre-fix arm is not a controlled comparison.** It confounds",
        "  every code change since with an eight-fold larger per-stage budget. Read it as an",
        "  upper bound on what the code did, not as what the code did.",
        "- The pre-fix arm's deficit against bare Claude Code is also confounded: paired, it",
        "  is −6.42 on the 28 timed-out tasks and −3.93 on the 12 that were not. The −5.67",
        "  published in the README averages the two. The subset figure is a post-hoc",
        "  subgroup and the tasks that time out may simply be the harder ones, so it does",
        "  not establish a corrected value — it establishes that the number has a confound",
        "  in it, of roughly its own size.",
        "",
        "Other things a reader needs:",
        "",
        "- One draw per task. Eight draws over one unchanged artifact set spanned 8.5 points",
        "  (sd 3.4), so no individual row means anything; only the means and the paired",
        "  standard errors above do, and the resolvable difference is printed with them.",
        "- All three arms are scored by the same `score_rcb_run.py` with the same judge,",
        "  `gpt-5.1`, and no arm's total is quoted if any of its judge calls failed.",
        "- Scoring starts only after the runner records a task as finished, because the",
        "  report and its figure set are still changing until export.",
        "- This arm is pinned to `2ffaeb4`, which is **before** PR #224. It measures the",
        "  tree as of the third audit round's findings, not after them.",
    ]
    if unscored:
        lines.append(
            f"- **{len(unscored)} task(s) produced a report the judge could not score** and are "
            f"left out of the mean rather than folded in as zeros: {', '.join(unscored)}."
        )
    if no_report:
        lines.append(
            f"- **{len(no_report)} task(s) produced no report at all**: {', '.join(no_report)}."
        )
    return "\n".join(lines) + "\n"


def acquire_lock() -> "object | None":
    """One watcher at a time. Two would double every judge call and race the table."""
    import fcntl

    handle = (ARM / "watch.lock").open("w")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    return handle


def main() -> int:
    lock = acquire_lock()
    if lock is None:
        log("another watcher holds watch.lock; exiting")
        return 1
    pid = find_runner()
    if pid is None:
        log("no batch runner found — refusing to start; nothing would be watched")
        return 1
    log(f"watching runner pid {pid}; scores -> {SCORES}")
    attempts: dict[str, int] = {}
    #: Two consecutive polls with no runner before believing it. A runner that is
    #: momentarily unreadable in /proc must not end the watch on the strength of one
    #: look, because ending the watch is what writes the results table.
    gone_polls = 0

    while True:
        pid = find_runner()
        gone_polls = 0 if pid is not None else gone_polls + 1
        alive = pid is not None or gone_polls < 2
        done = finished_workspaces()
        for task, workspace in done.items():
            if (SCORES / f"{task}.json").exists():
                continue
            if attempts.get(task, 0) >= MAX_ATTEMPTS:
                continue
            attempts[task] = attempts.get(task, 0) + 1
            score_one(task, workspace)

        scored = len(list(SCORES.glob("*.json")))
        settled = sum(
            1
            for task in done
            if (SCORES / f"{task}.json").exists() or attempts.get(task, 0) >= MAX_ATTEMPTS
        )
        log(f"runner={'alive' if alive else 'gone'}  reports={len(done)}  scored={scored}")

        if not alive and settled >= len(done) and len(done) > 0:
            break
        if not alive and not done:
            log("runner gone and no reports at all; stopping")
            break
        time.sleep(POLL_SECONDS)

    done = finished_workspaces()
    unscored = sorted(t for t in done if not (SCORES / f"{t}.json").exists())
    # Dot-directories are the runner's own TMPDIR, not tasks. Counting `.tmp` as a task
    # both printed a phantom failed row and pushed the directory count to 41, which
    # silently disabled the "never staged" guard below.
    all_dirs = {
        task_of(p)
        for p in WORKSPACES.glob("*/")
        if p.is_dir() and not p.name.startswith(".")
    }
    state = batch_state()
    no_report = sorted(all_dirs - set(done))
    never_staged = sorted(
        set(state) - all_dirs
    ) if state else []
    if never_staged:
        no_report.extend(f"{task} (never staged)" for task in never_staged)
    if len(all_dirs) < EXPECTED_TASKS:
        no_report.append(f"({EXPECTED_TASKS - len(all_dirs)} task(s) never reached a workspace)")
    unfinished = sorted(
        task for task, row in state.items()
        if row.get("status") not in {"completed", "failed"}
    )
    if unfinished:
        log(f"batch not complete: {len(unfinished)} task(s) unfinished: {unfinished}")

    try:
        table = write_table(unscored, no_report)
    except Exception as exc:  # noqa: BLE001 - a table that fails to render must still say so
        table = (
            f"# Results could not be rendered\n\n`{type(exc).__name__}: {exc}`\n\n"
            f"Scored: {len(list(SCORES.glob('*.json')))}. Unscored: {unscored}. "
            f"No report: {no_report}.\n"
        )
        log(f"write_table failed: {type(exc).__name__}: {exc}")
    scratch = ARM / "RESULTS.md.tmp"
    scratch.write_text(table, encoding="utf-8")
    os.replace(scratch, ARM / "RESULTS.md")
    (ARM / "WATCH_DONE").write_text(
        datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds") + "\n",
        encoding="utf-8",
    )
    log("wrote RESULTS.md")
    print()
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
