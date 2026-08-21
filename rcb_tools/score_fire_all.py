#!/usr/bin/env python3
"""Score every cell of the FIRE-Bench paired trial, in parallel, resumably.

    python3 score_fire_all.py [--workers N]

One draw is not one API call. The evaluator extracts atomic claims from the conclusion and
from the reference and checks each pair, so a draw is minutes, and a 115-second probe kills
it mid-flight and looks exactly like a transport failure. That mistake cost an hour here.

The judge's key is read from ~/api.txt at call time and exported into the child only. It is
never written to FIRE-Bench/.env, which sits inside a git checkout.

`FIREBENCH_EVAL_MODEL` is pinned to gpt-5.1: the deployment does host gpt-5.2, but every
number in this project's other benchmark was taken under gpt-5.1 and a judge swap is worth
about 16 points there. Both arms get the same one, which is what the paired comparison
needs; the absolute F1 is not comparable to a published FIRE-Bench figure either way.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path("/rmeng_data/robtang/fire_pair")
BENCH = Path("/home/robtang_google_com/FIRE-Bench")
SCORER = Path("/home/robtang_google_com/autor-fire-with/tools/score_fire_run.py")
_lock = threading.Lock()


def log(msg: str) -> None:
    with _lock:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def done(cell: Path) -> bool:
    s = cell / "draws" / "summary.json"
    if not s.exists():
        return False
    try:
        return int(json.loads(s.read_text()).get("scored") or 0) > 0
    except ValueError:
        return False


def one(cell: Path, sem: threading.Semaphore, env: dict) -> None:
    with sem:
        if done(cell):
            log(f"SKIP {cell.parent.name}/{cell.name}")
            return
        started = time.time()
        rc = subprocess.run(
            [sys.executable, str(SCORER), "--bench-root", str(BENCH),
             "--log-file", str(cell / "log.log"), "--task", cell.name,
             "--draws", "3", "--out-dir", str(cell / "draws")],
            stdout=(cell / "score_stdout.txt").open("w"), stderr=subprocess.STDOUT,
            cwd=SCORER.parent.parent, env=env,
        ).returncode
        summary = cell / "draws" / "summary.json"
        note = "no summary"
        if summary.exists():
            try:
                d = json.loads(summary.read_text())
                note = f"scored={d.get('scored')} median={d.get('median_draw')}"
            except ValueError:
                note = "unreadable summary"
        log(f"DONE {cell.parent.name}/{cell.name} rc={rc} {note} {time.time()-started:.0f}s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    env = dict(os.environ)
    env["OPENAI_API_KEY"] = Path.home().joinpath("api.txt").read_text().strip()
    env["FIREBENCH_EVAL_MODEL"] = "gpt-5.1"
    cells = [c for arm in ("with", "without")
             for c in sorted((ROOT / arm).glob("*"))
             if (c / "log.log").exists() and (c / "log.log").stat().st_size > 200]
    log(f"{len(cells)} cells, {sum(1 for c in cells if done(c))} already scored")
    sem = threading.Semaphore(args.workers)
    threads = [threading.Thread(target=one, args=(c, sem, env)) for c in cells]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    log("all cells attempted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
