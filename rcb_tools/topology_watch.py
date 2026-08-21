#!/usr/bin/env python3
"""Wait for the topology ablation to finish, score it, and write the paired result.

The experiment is `docs/framework.md` §6.7's: `--stage-graph adaptive` against
`--stage-graph linear`, same model, same judge, same forty tasks, paired. The two arms
are one checkout and one argument apart -- `ARMS["topology_adaptive"]` and
`ARMS["topology_linear"]` in run_arm.py, both naming /home/robtang_google_com/autor-topology.

Three things this deliberately does not do.

**It does not invent a statistic.** The sign-flip test is `src.trials.sign_flip_p`, the
one the rest of this repository quotes, with `sign_flip_estimator` naming which branch
ran and `attainable_p_floor` printing the floor beside the p. Reimplementing the test
inside the script that reports it is how a measurement comes out right about a program
that does something else.

**It does not average over an incomplete population.** A task counts only when *both*
arms have a score, because an unpaired task is not a pair and a mean over "whichever
finished first" is a mean over the easy ones -- which this project has already published
once and had to correct. The partial table is written every poll so progress is visible,
and it is labelled partial until n reaches 40.

**It does not report a snapshot without saying when.** Every figure carries an as-of
timestamp and the count it was taken over.

Scoring is incremental and cached: `score_items.py` skips a task whose result file
already holds items, so polling costs judge calls once per task and nothing thereafter.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path("/home/robtang_google_com/rcb_tools")
RUNS = Path("/rmeng_data/robtang/rcb_runs")
RESULTS = Path("/home/robtang_google_com/rcb_results")
REPO = Path("/home/robtang_google_com/AutoR")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(TOOLS))

ARMS = {"adaptive": ("topology_adaptive", "topo_adaptive", "gpt51_topo_adaptive"),
        "linear": ("topology_linear", "topo_linear", "gpt51_topo_linear")}
TASKS = [t.strip() for t in (TOOLS / "tasks40.txt").read_text().split() if t.strip()]
OUT = RESULTS / "topology_ablation.md"
POLL_SECONDS = 600
#: Stop after this long rather than polling for ever. The last element of this attempt
#: hits its 24h slurm wall at 2026-08-20T18:54Z, so 30 hours from an 18:54Z launch covers
#: the whole experiment plus scoring. 96 was three days past the point where anything can
#: still change, and a watcher that outlives its experiment does not sit quiet -- it keeps
#: rewriting `topology_ablation.md` with a fresh "As of" line over a frozen partial
#: result, so the file looks live while the data has been dead for days.
DEADLINE_HOURS = 30
MIN_SCOREABLE_BYTES = 1_200


#: Statuses `run_arm.py` writes when a task is over, either way.
_TERMINAL = {"completed", "failed"}


def terminal(arm: str, task: str) -> bool:
    """Has the runner recorded this task as over?

    A size check on `report.md` cannot answer this. The report is live in the workspace
    for the whole run, and `collect_figures` trims `report/images/` down to the
    referenced set only at export -- so a task scored while it is still running is
    scored on a different image set than the same task scored after it finishes, and
    image criteria carry 60.6% of this benchmark's weight. `watch_pins.py` gates on the
    runner's own status for exactly this reason and measured the window: the agent kept
    writing for a median of 992 s after the last write to `report.md`.
    """
    for path in RESULTS.glob(f"{arm}_*_state.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entry = payload.get(task)
        if isinstance(entry, dict) and entry.get("status") in _TERMINAL:
            return True
    return False


def finished(root: str, task: str, arm: str) -> bool:
    if not terminal(arm, task):
        return False
    for ws in (RUNS / root).glob(f"{task}_*"):
        report = ws / "report" / "report.md"
        try:
            if report.is_file() and report.stat().st_size >= MIN_SCOREABLE_BYTES:
                return True
        except OSError:
            continue
    return False


def score(arm: str, out_name: str, tasks: list[str]) -> None:
    """Run the scorer, and say so when it refuses.

    `capture_output=True` with the result dropped is how the arm-key bug survived: the
    scorer was pointed at a directory that does not exist, wrote forty error stubs, and
    exited 0, and this function would have hidden a non-zero exit as well. Anything the
    scorer says about a failure has to reach the operator's log or the next person reads
    an empty score directory as "nothing has finished yet".
    """
    if not tasks:
        return
    try:
        done = subprocess.run([sys.executable, str(TOOLS / "score_items.py"), arm, out_name, *tasks],
                              cwd=str(TOOLS), capture_output=True, text=True, timeout=7200)
    except subprocess.TimeoutExpired:
        # Not fatal. This runs unattended for a day or more against a judge API, and a
        # single slow scoring pass killing the watcher would leave the experiment
        # finishing with nothing watching it -- the failure would be silent, because the
        # last report on disk keeps its plausible "As of" line.
        print(f"[{time.strftime('%F %T')}] scorer TIMED OUT after 7200s for {arm} -> "
              f"{out_name}; {len(tasks)} task(s) still unscored. Continuing.", flush=True)
        return
    if done.returncode != 0:
        print(f"[{time.strftime('%F %T')}] scorer exit={done.returncode} for {arm} -> {out_name}: "
              f"{(done.stderr or done.stdout).strip()[:400]}", flush=True)


def scores(out_name: str, root: str) -> dict[str, float]:
    """Scores for the run of each task that is in the arm root *now*.

    The generation check is the point. `score_items.py` caches on the output filename --
    `if dest.exists() and json.loads(...).get("items"): return "cached"` -- with no
    comparison of run_id or workspace. This ablation has been launched three times, and
    the first two attempts left scores in these directories: three of them, whose run_ids
    named workspaces that had already been moved aside as evidence. Without this check
    those three tasks enter `done` on the first poll, are never re-scored for the current
    attempt, and `main()` returns the moment 40 pairs exist -- so the watcher would have
    announced a complete result carrying three scores from a cancelled run.

    Reading the run_id rather than the file's mtime because a stale score is not an old
    file; it is a score of the wrong run, and a re-score of a cancelled workspace would
    refresh the mtime while staying just as wrong.
    """
    found: dict[str, float] = {}
    directory = RESULTS / out_name
    if not directory.is_dir():
        return found
    for path in directory.glob("*.json"):
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("total_score") is None:
            continue
        run_id = payload.get("run_id")
        if run_id and not (RUNS / root / str(run_id)).is_dir():
            print(f"[{time.strftime('%F %T')}] ignoring {out_name}/{path.name}: run_id "
                  f"{run_id} is not in {root}; a previous attempt's score", flush=True)
            continue
        found[path.stem] = float(payload["total_score"])
    return found


def stage_progress(root: str) -> tuple[int, float, int]:
    """(runs seen, mean approved stages, runs still going) across every workspace in an arm.

    Defined for an *unfinished* run, which is the point. The arms censor differentially --
    the adaptive graph re-enters stages, so it is slower, so more of its runs hit the wall
    unscored -- and every score-based figure is computed over the survivors. Approved
    stages is the one number that exists for a run that never finished, so it is the only
    per-arm quantity here the censoring cannot select on.
    """
    # One run per task, the newest workspace. A task whose element died and was
    # resubmitted has two workspace directories and both keep a manifest -- adaptive
    # `Astronomy_000` has `..._20260819_185333`, silent for 6.4 hours, beside
    # `..._20260820_004507`, which is writing now. Counting manifests instead of tasks
    # made the arm 41 runs and averaged a dead run's frozen stage count into the live
    # figure, which is the wrong direction: an abandoned run drags the mean down exactly
    # where a resubmit was needed.
    latest: dict[str, Path] = {}
    for manifest in sorted((RUNS / root).glob("*_*/.autor/*/run_manifest.json")):
        workspace = manifest.parents[2]
        task = workspace.name.rsplit("_", 2)[0]
        if task not in latest or workspace.name > latest[task].parents[2].name:
            latest[task] = manifest
    approved = 0
    running = 0
    for manifest in latest.values():
        try:
            payload = json.loads(manifest.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        approved += sum(1 for stage in payload.get("stages", []) if stage.get("approved"))
        if payload.get("run_status") not in {"completed", "failed", "cancelled", "halted"}:
            running += 1
    seen = len(latest)
    return seen, (approved / seen if seen else 0.0), running


def report(adaptive: dict[str, float], linear: dict[str, float], produced: dict[str, int]) -> str:
    from src.trials import attainable_p_floor, sign_flip_estimator, sign_flip_p

    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    paired = [(t, adaptive[t], linear[t]) for t in TASKS if t in adaptive and t in linear]
    diffs = [a - l for _, a, l in paired]
    lines = [
        "# Topology ablation: `--stage-graph adaptive` against `--stage-graph linear`",
        "",
        f"*As of {stamp}. Written by `rcb_tools/topology_watch.py`; re-run it to refresh.*",
        "",
        "The experiment `docs/framework.md` §6.7 says the document owes. Both arms are one",
        "checkout (`autor-topology`, pinned) and one argument apart; every other flag, the",
        "model, the judge and the forty tasks are shared, and the two arms were launched",
        "interleaved so box load and any drift in the model endpoint land on both sides of",
        "each pair.",
        "",
        "## Progress",
        "",
        f"- runs finished and eligible to score: adaptive {produced['adaptive']}/40, "
        f"linear {produced['linear']}/40",
        "  (a run counts here only once its state file is terminal *and* its report is over "
        "1200 bytes, so a run still writing a large report is absent from this line, and "
        "the line is not a count of report files on disk)",
        f"- scored by `gpt-5.1`: adaptive {len(adaptive)}/40, linear {len(linear)}/40",
        f"- **complete pairs: {len(paired)}/40**",
        "",
        "## Approved stages, over every run including the unfinished ones",
        "",
    ]
    # Co-primary, per rcb_results/topology_exclusion_prereg.md. The arms censor
    # differentially -- the adaptive graph re-enters stages, so it is slower, so more of
    # its runs hit the 24h wall unscored -- and every score-based figure above is computed
    # over the survivors. Approved stages is defined for a run that never finished, so it
    # is the only per-arm quantity here that the censoring cannot select on.
    progress = {key: stage_progress(root) for key, (_, root, _) in ARMS.items()}
    for key in ("adaptive", "linear"):
        seen, mean_stages, still_going = progress[key]
        lines.append(f"- {key}: **{mean_stages:.2f}** of 8, over all {seen} runs "
                     f"({still_going} still going)")
    gap = progress["adaptive"][1] - progress["linear"][1]
    still = progress["adaptive"][2] - progress["linear"][2]
    lines += [
        "",
        f"Adaptive is {gap:+.2f} stages against linear here, with {still:+d} more runs still",
        "going. If that gap is negative while the paired difference above is positive, the two",
        "are not in conflict: a pair survives only when **both** arms are scored, so the pairs",
        "that exist are enriched for the tasks the *adaptive* arm finished quickly, and the",
        "paired difference is biased toward adaptive. Read the completion counts first.",
        "",
    ]
    if len(paired) < len(TASKS):
        lines += [
            f"> **Partial.** {len(paired)} of 40 pairs. A task counts only when both arms have",
            "> a score: an unpaired task is not a pair, and a mean over whichever arm finished",
            "> first is a mean over the tasks that finish fastest. Read nothing below as the",
            "> result until this line says 40.",
            "",
        ]
    if not paired:
        return "\n".join(lines) + "\n_No complete pair yet._\n"

    mean_a = statistics.mean(a for _, a, _ in paired)
    mean_l = statistics.mean(l for _, _, l in paired)
    mean_d = statistics.mean(diffs)
    sd = statistics.stdev(diffs) if len(diffs) > 1 else float("nan")
    stderr = sd / (len(diffs) ** 0.5) if len(diffs) > 1 else float("nan")
    wins = sum(1 for d in diffs if d > 0)
    losses = sum(1 for d in diffs if d < 0)
    ties = sum(1 for d in diffs if d == 0)
    p = sign_flip_p(diffs)
    floor = attainable_p_floor(len(diffs))

    # Bold only at the full population. A partial table is not a weaker version of the
    # result; it is a different population -- the tasks that finish first are the tasks
    # that are quickest to finish, and nothing about this experiment makes that set a
    # random sample of the forty. Formatting is the whole defence here, because a reader
    # scanning for the answer reads the bolded number and not the blockquote above it, and
    # this file rewrites itself every ten minutes for as long as three days.
    complete = len(paired) == len(TASKS)
    em = "**" if complete else ""
    heading = "The difference" if complete else "The difference so far (NOT the result)"
    lines += [
        f"## {heading}",
        "",
    ]
    if not complete:
        lines += [
            f"These {len(paired)} pairs are the {len(paired)} tasks that finished first, on both",
            "arms, out of forty. Fast tasks are shorter and simpler than slow ones, so this is a",
            "biased subset by construction, not a small random sample of the forty. The figures",
            "are here to show the apparatus works, and they are deliberately not emphasised.",
            "",
        ]
    lines += [
        f"- mean, adaptive: {em}{mean_a:.2f}{em}",
        f"- mean, linear: {em}{mean_l:.2f}{em}",
        f"- paired mean difference (adaptive − linear): {em}{mean_d:+.3f}{em}",
        f"- observed sd of the paired differences: {sd:.3f}; standard error {stderr:.3f}",
        f"- adaptive won {wins}, lost {losses}, tied {ties}",
        f"- two-sided sign-flip p: {em}{p:.4f}{em} (floor at n={len(diffs)}: {floor:.4f})",
        f"- estimator: {sign_flip_estimator(diffs)}",
        "",
        "The sign-flip test is `src.trials.sign_flip_p`, the one the rest of this repository",
        "quotes, rather than a second implementation written next to the number it reports.",
        "",
        "## Per task",
        "",
        "| task | adaptive | linear | difference |",
        "| --- | ---: | ---: | ---: |",
    ]
    for task, a, l in paired:
        lines.append(f"| {task} | {a:.2f} | {l:.2f} | {a - l:+.2f} |")
    lines += [
        "",
        "## What this is a measurement of",
        "",
        "The upper bound on the claim: under a `gpt-5.1` judge, the difference between the",
        "eight-stage graph with its thirteen backward edges and the same eight stages walked",
        "as a strict sequence, over forty ResearchClawBench tasks, one draw each, with the",
        "same model on both sides. It is not a measurement of whether the graph would help a",
        "different task set, a different model, or more than one draw per cell: single-draw",
        "noise on one task of this benchmark is about 8.5 points, which is why the claim is",
        "the paired mean and never a per-task row.",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    # A banner, because this log is append-only across restarts and three eras of this
    # script have already been concatenated into it with nothing marking the seams -- the
    # first era counted the cancelled v1 tree and read `a=1 l=3` off workspaces that were
    # not the experiment. A reader scrolling back has no way to know which code produced a
    # line unless the code says so.
    import hashlib
    import os

    source = Path(__file__).read_bytes()
    print(
        f"[{time.strftime('%F %T')}] start pid={os.getpid()} "
        f"script_sha256={hashlib.sha256(source).hexdigest()[:12]} "
        f"arms={{{', '.join(f'{k}:{v[1]}' for k, v in ARMS.items())}}} "
        f"poll={POLL_SECONDS}s deadline={DEADLINE_HOURS}h",
        flush=True,
    )
    deadline = time.monotonic() + DEADLINE_HOURS * 3600
    while True:
        produced = {}
        for key, (arm, root, out_name) in ARMS.items():
            ready = [t for t in TASKS if finished(root, t, arm)]
            produced[key] = len(ready)
            done = set(scores(out_name, root))
            # `root`, not `arm`. `score_items.py` resolves its first argument as
            # RUNS/<name>, so it wants the runs-directory name (`topo_linear`), while
            # `arm` is run_arm.py's key for the same thing (`topology_linear`). Passing
            # `arm` pointed the scorer at /rmeng_data/robtang/rcb_runs/topology_linear,
            # which has never existed, so every task resolved to "no workspace" and this
            # loop wrote error stubs for the whole arm without ever failing. The two
            # names differing by one word is the entire bug; `finished()` above was
            # already using `root` and was right.
            score(root, out_name, [t for t in ready if t not in done])
        adaptive = scores(ARMS["adaptive"][2], ARMS["adaptive"][1])
        linear = scores(ARMS["linear"][2], ARMS["linear"][1])
        OUT.write_text(report(adaptive, linear, produced), encoding="utf-8")
        complete = sum(1 for t in TASKS if t in adaptive and t in linear)
        print(f"[{time.strftime('%F %T')}] pairs {complete}/40 "
              f"(produced a={produced['adaptive']} l={produced['linear']}) -> {OUT}", flush=True)
        if complete >= len(TASKS) or time.monotonic() > deadline:
            print(f"[{time.strftime('%F %T')}] stopping: "
                  + ("all pairs complete" if complete >= len(TASKS) else "deadline reached"), flush=True)
            return 0
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
