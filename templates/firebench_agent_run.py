#!/usr/bin/env python3
"""Drop-in ``agents/autor/run.py`` for a FIRE-Bench checkout.

Copy this file to ``<FIRE-Bench>/agents/autor/run.py`` and AutoR becomes a FIRE-Bench
agent::

    mkdir -p ~/FIRE-Bench/agents/autor
    cp ~/AutoR/templates/firebench_agent_run.py ~/FIRE-Bench/agents/autor/run.py
    cd ~/FIRE-Bench && bash run_experiment.sh --agents autor --tasks cot_in_planning --models opus

The harness's whole contract with an agent is three environment variables in
(``AGENT_ID``, ``TASK_ID``, ``LLM_MODEL``), no argv, cwd at the checkout root, and one
log file out at ``log/<agent_id>/<llm_model>/<task_id>/<timestamp>/log.log`` whose last
line parses as ``{"result": "<conclusion>"}``. Everything else this file does is passing
that through to ``fire_agent.py``.

**Three environment variables of its own**, all optional:

``AUTOR_ROOT``
    Where the AutoR checkout is. Defaults to ``~/AutoR``. This file deliberately does not
    vendor any AutoR code -- a copy of the adapter inside the benchmark checkout is a
    copy that stops matching the one that is tested.
``AUTOR_PROFILE``
    ``pipeline`` (default) or ``direct``. The two arms.
``AUTOR_EXTRA_ARGS``
    Appended to the ``fire_agent.py`` command line, split on whitespace. How a trial
    varies one thing between arms without a second copy of this file.

**Why the sandbox is not under the checkout.** Every shipped agent puts its sandbox in
``<checkout>/runs/``, and runs with ``--dangerously-skip-permissions``. From there,
``../../benchmark/papers/<task_id>/conclusion.txt`` is the answer key, two directories
away, readable. ``fire_agent.py`` defaults its workspace to ``$FIREBENCH_RUNS_DIR``
(``~/fire-bench-runs``) instead, and this file does not override that.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

BENCH_ROOT = Path.cwd()
AUTOR_ROOT = Path(os.environ.get("AUTOR_ROOT", "~/AutoR")).expanduser().resolve()


def main() -> int:
    agent_id = os.environ.get("AGENT_ID", "autor")
    task_id = os.environ.get("TASK_ID", "")
    model = os.environ.get("LLM_MODEL", "opus")
    profile = os.environ.get("AUTOR_PROFILE", "pipeline")
    if not task_id:
        print("TASK_ID is not set; the harness sets it. Nothing to run.", file=sys.stderr)
        return 2

    agent = AUTOR_ROOT / "fire_agent.py"
    if not agent.is_file():
        print(f"No AutoR adapter at {agent}. Set AUTOR_ROOT.", file=sys.stderr)
        return 2

    timestamp = time.strftime("%Y%m%d%H%M%S")
    log_file = BENCH_ROOT / "log" / agent_id / model / task_id / timestamp / "log.log"

    command = [
        sys.executable,
        str(agent),
        "--bench-root", str(BENCH_ROOT),
        "--task", task_id,
        "--agent-id", agent_id,
        "--model", model,
        "--profile", profile,
        "--log-file", str(log_file),
    ]
    command += shlex.split(os.environ.get("AUTOR_EXTRA_ARGS", ""))

    env = os.environ.copy()
    # The two idle-timeout knobs are shell environment, not CLI configuration, and a
    # detached launcher that does not re-export them falls back to a 300 s floor that
    # kills any call whose model thinks for five minutes before its first token. Set here
    # so a run driven through `run_experiment.sh` from cron behaves like one driven from
    # a terminal.
    env.setdefault("CLAUDE_STREAM_IDLE_TIMEOUT_MS", "1800000")
    env.setdefault("CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS", "1800000")
    # The agent's own experiments run in a subprocess of the operator, which inherits
    # this. Without it every `LLMInference(provider="openai", ...)` in the sandbox goes to
    # api.openai.com.
    if os.environ.get("OPENAI_BASE_URL"):
        env["OPENAI_BASE_URL"] = os.environ["OPENAI_BASE_URL"]

    print("[autor] " + " ".join(shlex.quote(part) for part in command), flush=True)
    completed = subprocess.run(command, env=env, cwd=str(BENCH_ROOT))
    print(f"[autor] exit={completed.returncode} log={log_file}", flush=True)
    # The harness ignores the return code -- `run_agent.py` prints "completed" whatever
    # happens -- so this is for whoever reads the console, and for a driver that runs
    # this file directly.
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
