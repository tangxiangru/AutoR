#!/usr/bin/env python3
"""Run one FIRE-Bench task through both skill packs, or score what has run.

    python3 fire_pair.py run <task> [<task> ...]
    python3 fire_pair.py report

The generalisation test the ResearchClawBench numbers cannot answer. The 75 skills in
#264 were written from the per-item losses of 25 scored ResearchClawBench tasks, so a gain
there says that writing guidance from a measured loss works -- not that the guidance helps
anywhere else. FIRE-Bench's 35 tasks were never looked at while writing them, and the
benchmark inverts what ResearchClawBench rewards: the scored text is one to three
sentences, a superfluous claim costs precision permanently, numbers are deleted before
scoring, and the harness kills the agent at one hour.

So this can come out negative, and that is the point. A skill pack tuned on one benchmark
and dumped into another's listing is exactly the case where "the pack gets less useful as
it grows" would bite: a FIRE-Bench run installs 117 skills under the `with` arm against 42
under `without`, because these skills are general-prefixed and carry no `applies_when`, and
pins never fire here -- FIRE-Bench task ids are not in the table.

The two checkouts differ in `src/skills` and `configs/task_skill_pins.json` and in nothing
else; both are `db9d667`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

BENCH = Path("/home/robtang_google_com/FIRE-Bench")
ARMS = {
    "with": Path("/home/robtang_google_com/autor-fire-with"),
    "without": Path("/home/robtang_google_com/autor-fire-without"),
}
ROOT = Path("/rmeng_data/robtang/fire_pair")
MAX_CONCURRENT = int(os.environ.get("FIRE_MAX_CONCURRENT", "6"))
_print = threading.Lock()


def log(message: str) -> None:
    with _print:
        print(f"[{time.strftime('%m-%d %H:%M:%S')}] {message}", flush=True)


def claim(arm: str, task: str) -> bool:
    """Atomic, so two launchers cannot both run one cell."""
    d = ROOT / ".claims" / f"{arm}__{task}"
    try:
        d.mkdir(parents=True)
        return True
    except FileExistsError:
        return False


def one(arm: str, task: str, sem: threading.Semaphore) -> None:
    with sem:
        cell = ROOT / arm / task
        logfile = cell / "log.log"
        if logfile.exists() and logfile.stat().st_size > 200:
            log(f"SKIP  {arm}/{task}: already has a log")
            return
        if not claim(arm, task):
            log(f"SKIP  {arm}/{task}: claimed elsewhere")
            return
        cell.mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable, str(ARMS[arm] / "fire_agent.py"),
            "--bench-root", str(BENCH), "--task", task,
            "--profile", "pipeline", "--model", "opus", "--review-model", "opus",
            "--workspace", str(cell / "ws"), "--log-file", str(logfile),
        ]
        started = time.time()
        log(f"START {arm}/{task}")
        with (cell / "stdout.txt").open("w") as out:
            rc = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT,
                                cwd=ARMS[arm]).returncode
        size = logfile.stat().st_size if logfile.exists() else 0
        (cell / "cell.json").write_text(json.dumps({
            "arm": arm, "task": task, "returncode": rc,
            "log_bytes": size, "seconds": round(time.time() - started),
        }, indent=1))
        log(f"DONE  {arm}/{task}: rc={rc} log={size}B {time.time()-started:.0f}s")


def run(tasks: list[str]) -> int:
    sem = threading.Semaphore(MAX_CONCURRENT)
    threads = [threading.Thread(target=one, args=(arm, task, sem))
               for task in tasks for arm in ARMS]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return 0


def report() -> int:
    import statistics as st
    rows: dict[str, dict[str, float]] = {}
    for arm in ARMS:
        for cell in sorted((ROOT / arm).glob("*")) if (ROOT / arm).exists() else []:
            f = cell / "score.json"
            if not f.exists():
                continue
            try:
                d = json.loads(f.read_text())
            except ValueError:
                continue
            v = d.get("f1_mean", d.get("f1"))
            if v is None:
                continue
            rows.setdefault(cell.name, {})[arm] = float(v)
    both = sorted(t for t, v in rows.items() if len(v) == 2)
    print(f"paired tasks: {len(both)}")
    if not both:
        return 0
    for arm in ARMS:
        print(f"  {arm:<8} F1 mean {st.mean(rows[t][arm] for t in both):.4f}")
    d = [rows[t]["with"] - rows[t]["without"] for t in both]
    tstat = st.mean(d) / (st.stdev(d) / len(d) ** 0.5) if len(d) > 1 and st.stdev(d) else 0.0
    print(f"  with − without: {st.mean(d):+.4f}  t={tstat:+.2f}  "
          f"won {sum(1 for x in d if x > 0)}/{len(d)}")
    return 0


if __name__ == "__main__":
    if sys.argv[1] == "report":
        raise SystemExit(report())
    raise SystemExit(run(sys.argv[2:]))
