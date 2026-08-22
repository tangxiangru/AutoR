#!/usr/bin/env python3
"""Launch one arm over all 40 ResearchClawBench tasks.

    python3 run_arm.py control        # bare Claude Code, Opus 5
    python3 run_arm.py autor          # AutoR, pinned checkout

Both arms differ in exactly one thing: the agent command. Same harness, same
INSTRUCTIONS.md, same workspace layout, same machine, same judge afterwards. So the
difference between them is the scaffold and the scaffold alone.

Resumable: a task whose workspace already holds a scoreable report is skipped, so a batch
killed by a disk sweep can be relaunched without paying for the work twice.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

AUTOR_PIN = Path("/home/robtang_google_com/autor-pinned")
AUTOR_PIN233 = Path("/home/robtang_google_com/autor-pinned233")
AUTOR_PIN_SKILLS = Path("/home/robtang_google_com/autor-pinned-skills")
#: origin/main at bb32a8c -- the first tree carrying all three routing layers:
#: skills named at their stage (#237), the `applies_when` shape filter (#242), and
#: `configs/task_skill_pins.json` (#251). 45 skills, 15 tasks pinned, 24 pins.
AUTOR_PIN251 = Path("/home/robtang_google_com/autor-pinned251")
AUTOR_PIN_A9C = Path("/home/robtang_google_com/autor-pin-a9c2b48")
#: main at 95861bd, the first checkout carrying the forty task-scoped skills of #270 and
#: the 280 pins that force them. Its own worktree rather than `autor-pinned-skills`,
#: because that one is under a live array and a benchmark run measures the clone it was
#: launched from.
AUTOR_SKILLS161 = Path("/home/robtang_google_com/autor-skills161")
#: main at 48501e7, all 161 skills and all 280 pins. The pair below is the one-variable
#: control the `autor_skills161` arm could not be: the two trees differ in `src/skills` and
#: `configs/task_skill_pins.json` and in nothing else (`diff -rq` clears everything but
#: .git and __pycache__). `autor-abl40` has the 41 skill directories added by #270 deleted
#: and their 40 pins struck, leaving 120 skills and 240 pins.
#:
#: 280 and 240, not the 4326 and 4286 this comment carried until now and the launchers
#: printed into every run record. `sum(len(v) for v in table.values())` counts the six
#: underscore-prefixed metadata keys too, and five of those are prose, so it was adding
#: 4046 *characters* of `_provenance` and `_maximum` to the pin count. `slurm_pins.sbatch`
#: has said "27 of the forty tasks carry 280 entries between them" the whole time; the two
#: numbers were in the same repository disagreeing by a factor of fifteen.
#:
#: It is not a cosmetic error. Struck against 4326 the ablation reads as 0.9% of the pin
#: table and beneath notice; struck against 280 it is 14%, one entry in seven, which is the
#: size the -2.16 +/- 1.06 arm gap has to be explained against.
#:
#: Forty tasks rather than the twelve #270 was written from, for two reasons. Current main
#: has no 40-task score at all -- the twelve in flight are the tasks that were losing, so
#: their mean is low by construction and comparable to nothing. And the manipulation is not
#: confined to the twelve: measured through the shipped selector, the twelve are offered 4-5
#: of the 41 and the other twenty-eight are offered exactly 1, so the ablation is weak but
#: not null outside the twelve, and dropping them would be assuming the answer.
AUTOR_MAIN40 = Path("/home/robtang_google_com/autor-main40")
AUTOR_ABL40 = Path("/home/robtang_google_com/autor-abl40")

#: One checkout, two arms, one argument between them. `main` at 5737676, the first head
#: whose `rcb_agent.py` accepts `--stage-graph` at all -- see #293: the flag existed on
#: `main.py` since the topology did and never on the benchmark path, so all 398 archived
#: benchmark run configs read `adaptive` and none of them chose it.
#:
#: This is the ablation `docs/framework.md` §6.7 says the document owes and calls "one
#: flag [that] has still never been passed". Its own summary of the system stands until
#: this runs: "a system whose stated contribution is a topology has demonstrated that the
#: topology is inspectable ... It has not demonstrated that the topology helps."
AUTOR_TOPOLOGY = Path("/home/robtang_google_com/autor-topology")

#: One checkout, two arms, one argument between them. `--cross-review` has existed on
#: `rcb_agent.py` since the cross-model reviewer did, defaults to `auto`, and appears in
#: **zero** of the archived `agent_cmd` strings -- every scored run on this cluster,
#: including the 32.19 that is currently the best number here, took the default.
#:
#: It is not a dormant feature. Sampling twelve `full40_pins` runs gives 387 vetoes, about
#: 32 per run. `src/cross_reviewer.py:18` defends the default with "adding it can only make
#: the gate stricter. That is what makes it safe to enable by default." The first clause is
#: a structural invariant that `tests/test_cross_reviewer.py` already holds. The second is a
#: price nobody has paid: on a pipeline whose own account of its losses is stages skipped
#: for want of attempts, a stricter gate buys a report that is reviewed LESS.
AUTOR_XREV = Path("/home/robtang_google_com/autor-xrev")

#: The pin-layer ablation. Two worktrees at f0f469c differing in exactly one file --
#: `autor-pinsoff/configs/task_skill_pins.json` is empty -- verified with `diff -rq`. The
#: discipline filter, the `applies_when` shape filter and all the skills are identical on
#: both sides; only the layer keyed on a *benchmark task identifier* is inert. Measured:
#: the live table pins 27 of the 40 tasks with 280 entries, and an empty one degrades
#: cleanly (`load_task_pins` -> {}, `pins_for(any)` -> nothing) rather than raising.
#:
#: `docs/rcb-skill-routing-arm.md` says outright that no unconfounded test of this layer
#: exists, and the pins were derived from these same tasks' own scored per-criterion
#: losses -- a lookup table keyed on the test set. The in-flight main40/abl40 ablation
#: removes skill *directories* and leaves the table live on both sides, so it does not
#: touch this.
#:
#: Pre-specified: the primary reading is the paired difference over the 27 pinned tasks,
#: and the 13 unpinned ones are a negative control where the manipulation is inert. If the
#: unpinned tasks move, something other than the pin layer changed and the arm is void.
AUTOR_PINSON = Path("/home/robtang_google_com/autor-pinson")
AUTOR_PINSOFF = Path("/home/robtang_google_com/autor-pinsoff")

#: The per-stage operator-call ceiling. `src/utils.py` says it "binds on 50% of stages and
#: refuses 27% of all calls ... every judgement layer those calls buy has been measured, and
#: none of them pays" -- but every number behind that sentence comes from AutoR's own rubric,
#: not from a benchmark score, and the highest benchmark score on this cluster (32.19) was
#: produced by a tree that has no such ceiling at all. `100000` is the documented `None`
#: sentinel's behaviour at the single read site, which compares `spent < ceiling`.
AUTOR_OPCALLS = Path("/home/robtang_google_com/autor-opcalls")

#: The reviewer panel. Across 344 archived scorecards the verdict is `unused` 344/344 and no
#: `panel_effect.json` exists anywhere under the run roots, so this mechanism has never once
#: run on a scored task. It is a real documented claim with no measurement behind it.
#: Expensive: each gate goes from one call to five, serially.
AUTOR_PANEL = Path("/home/robtang_google_com/autor-panel")



ARMS = {
    # RCB's own `claude` preset, verbatim, plus `--model opus` (resolves to
    # claude-opus-5[1m] here) and a 12h cap matching what AutoR's runs consumed. Claude
    # Code's published median is 13.4 min, so the cap cannot be called starvation.
    "control": (
        "Claude Code (Opus 5)",
        "timeout 43200 claude --dangerously-skip-permissions --model opus "
        "-p <PROMPT> --output-format stream-json --verbose",
    ),
    # AutoR driven by gpt-5.4, to sit against the leaderboard's published Codex CLI
    # (GPT-5.4) = 18.42. Same scaffold, same 40 tasks, same gpt-5.1 judge, different base
    # model -- so the pair isolates the scaffold at a model the leaderboard already has a
    # bare-agent number for, and the bare-agent side is codex-as-harness in both.
    #
    # The route is `codex-rcb`, a wrapper with its own CODEX_HOME. The machine's ~/.codex is
    # not read, not written, and keeps its own model; one config serving two experiments is
    # how both end up on a model neither chose. The key reaches codex as an environment
    # variable resolved through `env_key`, never a file and never a command line.
    "autor_gpt54": (
        "AutoR (GPT-5.4)",
        f"python3 {AUTOR_PIN}/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT> "
        "--operator codex --model gpt-5.4 --review-operator codex --review-model gpt-5.4 "
        "--codex-command /home/robtang_google_com/rcb_tools/bin/codex-rcb "
        # Sandbox stays at workspace-write. `--web-search native` turns on codex's own
        # web_search tool, which the Responses API serves, so search works without opening
        # the sandbox's network. The Claude arm uses Gemini search because Claude Code's
        # built-in WebSearch is disabled on Vertex here -- different provider, same
        # capability, and neither arm runs unsandboxed to get it.
        "--codex-sandbox workspace-write --web-search native "
        "--stage-timeout 1800 --max-auto-skips 3",
    ),
    # AutoR on the code carrying the skill pack and the coverage fixes (#217, #219, #220),
    # against the same 40 tasks the earlier arms ran. Separate workspace root so the
    # 3ef61e5 arm stays intact as the before side of the comparison.
    # AutoR at main f16878b: #230's bounded send-backs, measured directed rounds and
    # router grounds, plus #231's withdrawal ledger, #232's walk ratchet and #233's
    # invertible writes. Named for the head it pins, not for one PR in it -- four
    # changes landed between launches and an arm named after the first would be a
    # `agent_cmd` that says less than the checkout does.
    # AutoR at main 9e6aadd: the 75 per-task skills and the 243-slot pin table (#264),
    # plus the single per-stage operator-call ceiling (#257). The question this arm
    # exists to answer is not the score -- it is how many skills a run actually opens.
    # The pack has offered 16 and the model has opened a median of 1 for two arms
    # running; the pins are announced imperatively, and 78% is the measured rate for
    # that form when a prompt names one. Nobody has measured it when a prompt names
    # four or five, which is what this table produces.
    "autor_skills": (
        "AutoR",
        f"python3 {AUTOR_PIN_SKILLS}/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT> "
        "--model opus --review-model opus --web-search gemini "
        "--stage-timeout 1800 --max-auto-skips 3",
    ),
    "autor_head": (
        "AutoR",
        f"python3 {AUTOR_PIN233}/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT> "
        "--model opus --review-model opus --web-search gemini "
        "--stage-timeout 1800 --max-auto-skips 3",
    ),
    # Matches the `2ffaeb4` arm's configuration exactly except for the code: no
    # `--stage-timeout`, so the adapter's 14400 s default applies. The 1800 s the
    # `autor_head` arm carries was measured to sit far below the field's operating
    # point -- 28 of 40 runs hit it, and those 28 averaged 22.08 against 27.06 for the
    # 12 that did not -- so passing it here would confound the code under test with a
    # budget change of the same size as the effect.
    # The arm #270 was launched to be measured by: same model, same harness, same prompt as
    # `autor_v220`, differing only in the forty skills and their pins. Paired against
    # full40_v220 over the twelve tasks those skills were written from.
    #
    # THAT SENTENCE IS FALSE and the delta must not be reported as a skills effect. The two
    # checkouts (autor-skills161 vs autor-pinned) are 47 commits and ~14.8k lines of non-skill
    # runtime apart: the per-stage retry ceiling went 8 -> unlimited, an unconditional run
    # supervisor was added, an operator-call ceiling was added, and seven stage prompts were
    # rewritten. Report it as `main@<sha> vs main@v220`, whole configuration. A one-variable
    # control would be a 95861bd worktree with the forty skill dirs and their pins removed;
    # that arm has not been run.
    #
    # ---------------------------------------------------------------------------
    # `control_search` -- and the claim that used to be written here, which was wrong
    # ---------------------------------------------------------------------------
    # This comment used to say `control` had been measured with no working search at all, on
    # the evidence of a `WebSearch` call returning
    # `Organization Policy constraint constraints/vertexai.allowedPartnerModelFeatures
    # violated`. Re-derived from the 44 transcripts in control_bare_cc:
    #
    #     WebSearch                            16 calls, 16 errored (the org policy, real)
    #     mcp__ai4ai-web-search__web_search    12 calls, 12 SUCCEEDED, across 8 tasks
    #
    # All 44 runs list `ai4ai-web-search` as a *connected* MCP server in their init record --
    # inherited from the user-level config, because no arm passes `--strict-mcp-config`. The
    # control could search and did. full40_v220's 182 successful searches over 32 tasks make
    # this a 15x USAGE gap, not a capability gap, and that server was connected on both sides
    # of the published -2.65, so it is a constant there rather than a confound.
    #
    # The lesson is the one that produced the error: both the "no search" reading and the
    # "search parity" reading came from counting tool NAMES. Pair tool_use ids to tool_result
    # ids and read the body.
    #
    # So this arm is NOT "the control the comparison needs". It adds a second search server on
    # a newer Gemini (3.7 vs the 3.6 both sides already had) to an agent that already had one
    # and mostly declined to use it -- and the in-flight numbers say the treatment is close to
    # a no-op. Availability was added; discoverability was not, because the control's
    # INSTRUCTIONS.md never names the tool while AutoR's stage prompt does.
    #
    # WARNING, larger than either of the above: every arm's init record carries
    # `memory_paths.auto = .../projects/-rmeng-data-robtang/memory/`, a shared Claude Code
    # auto-memory holding 41 `rcb-<task>-target-paper.md` answer keys. 15 of 44 control runs
    # opened their own task's key; 4 of 41 AutoR runs did. Any future arm should be launched
    # with that directory empty or redirected.
    "control_search": (
        "Claude Code (Opus 5)",
        "timeout 43200 claude --dangerously-skip-permissions --model opus "
        "--mcp-config /home/robtang_google_com/rcb_tools/mcp/control_search.json "
        "-p <PROMPT> --output-format stream-json --verbose",
    ),
    "autor_main40": (
        "AutoR",
        f"python3 {AUTOR_MAIN40}/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT> "
        "--model opus --review-model opus --web-search gemini "
        "--stage-timeout 1800 --max-auto-skips 3",
    ),
    "autor_abl40": (
        "AutoR",
        f"python3 {AUTOR_ABL40}/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT> "
        "--model opus --review-model opus --web-search gemini "
        "--stage-timeout 1800 --max-auto-skips 3",
    ),
    "autor_skills161": (
        "AutoR",
        f"python3 {AUTOR_SKILLS161}/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT> "
        "--model opus --review-model opus --web-search gemini "
        "--stage-timeout 1800 --max-auto-skips 3",
    ),
    # The topology ablation. These two command strings are byte-identical except for the
    # value of `--stage-graph`, from one checkout, and they are launched together so box
    # load and any model drift land on both. Everything else mirrors `autor_pins` below,
    # including the deliberate absence of `--stage-timeout`: 28 of 40 runs hit the 1800 s
    # cap and those 28 averaged 22.08 against 27.06 for the 12 that did not, so passing it
    # would put a budget change the size of the effect inside the comparison.
    "topology_adaptive": (
        "AutoR",
        f"python3 {AUTOR_TOPOLOGY}/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT> "
        "--model opus --review-model opus --web-search gemini --stage-graph adaptive",
    ),
    "topology_linear": (
        "AutoR",
        f"python3 {AUTOR_TOPOLOGY}/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT> "
        "--model opus --review-model opus --web-search gemini --stage-graph linear",
    ),
    # Byte-identical but for the value after `--cross-review`. Do not pair either of these
    # against the in-flight `topo_adaptive`: same SHA and same command minus the flag, so it
    # looks free, but that arm runs at a different allocation on a branch that moved twice
    # mid-ablation. A fresh pair is 80 elements against ~190 free slots.
    "xrev_on": (
        "AutoR",
        f"python3 {AUTOR_XREV}/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT> "
        "--model opus --review-model opus --web-search gemini --stage-graph adaptive "
        "--cross-review auto",
    ),
    "xrev_off": (
        "AutoR",
        f"python3 {AUTOR_XREV}/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT> "
        "--model opus --review-model opus --web-search gemini --stage-graph adaptive "
        "--cross-review off",
    ),
    # Identical command strings; the only difference is which worktree they name, and those
    # differ in one JSON file. `run_config.json` cannot tell these two apart -- it has never
    # carried `skill_pins` -- so the durable marker is `agent_cmd` in `_meta.json`.
    "pins_on": (
        "AutoR",
        f"python3 {AUTOR_PINSON}/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT> "
        "--model opus --review-model opus --web-search gemini --stage-graph adaptive",
    ),
    "pins_off": (
        "AutoR",
        f"python3 {AUTOR_PINSOFF}/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT> "
        "--model opus --review-model opus --web-search gemini --stage-graph adaptive",
    ),
    # Byte-identical but for the ceiling. `--max-operator-calls-per-stage` has never appeared
    # in an archived command string.
    "opcalls_on": (
        "AutoR",
        f"python3 {AUTOR_OPCALLS}/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT> "
        "--model opus --review-model opus --web-search gemini --stage-graph adaptive",
    ),
    "opcalls_off": (
        "AutoR",
        f"python3 {AUTOR_OPCALLS}/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT> "
        "--model opus --review-model opus --web-search gemini --stage-graph adaptive "
        "--max-operator-calls-per-stage 100000",
    ),
    # The panel has never run on a scored task: 344/344 scorecards say `unused`.
    "panel_on": (
        "AutoR",
        f"python3 {AUTOR_PANEL}/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT> "
        "--model opus --review-model opus --web-search gemini --stage-graph adaptive "
        "--review-panel",
    ),
    "panel_off": (
        "AutoR",
        f"python3 {AUTOR_PANEL}/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT> "
        "--model opus --review-model opus --web-search gemini --stage-graph adaptive "
        "--no-review-panel",
    ),
    "autor_pins": (
        "AutoR",
        f"python3 {AUTOR_PIN251}/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT> "
        "--model opus --review-model opus --web-search gemini",
    ),
    # Current `main`, paired against `autor_pins` above. The command string is byte-identical
    # to that one except for the checkout it names, which is the whole point: the two arms
    # differ by `bb32a8c..a9c2b48` -- 10 PRs, 190 files, +31,571 lines -- and by nothing in
    # how they are invoked. No `--stage-timeout`, so both take the adapter's 14400 s default;
    # same model, same review model, same search backend.
    #
    # What the pair can and cannot answer. It answers "is current main better than the tree
    # measured at 34.65". It does NOT isolate the 75 skills #264 added, even though that is
    # the headline change and the skill count goes 45 -> 120: the same range also carries
    # #261 (a UnicodeDecodeError in schema inference that could end a run mid-stage -- it
    # ended one in the `autor_pins` arm), #262 (an aborted run was being recorded as
    # completed), #256 and #258. A skills-only control would be an `a9c2b48` worktree with
    # the 75 new skill directories and their pin entries removed, and that arm does not exist.
    "autor_a9c": (
        "AutoR",
        f"python3 {AUTOR_PIN_A9C}/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT> "
        "--model opus --review-model opus --web-search gemini",
    ),
    "autor_v220": (
        "AutoR",
        f"python3 {AUTOR_PIN}/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT> "
        "--model opus --review-model opus --web-search gemini "
        "--stage-timeout 1800 --max-auto-skips 3",
    ),
    "autor": (
        "AutoR",
        f"python3 {AUTOR_PIN}/rcb_agent.py --workspace <WORKSPACE> --prompt <PROMPT> "
        "--model opus --review-model opus --web-search gemini "
        "--stage-timeout 1800 --max-auto-skips 3",
    ),
}

#: Tasks one launcher process runs at once. Overridable because the launcher is now
#: used two ways: one array element per task, where it is 1 and irrelevant, and a few
#: fat nodes each carrying a slice, where it is the slice size. Five AutoR tasks want a
#: 44-CPU node -- one alone was OOM-killed at 31 GB.
MAX_CONCURRENT = int(os.environ.get("RCB_MAX_CONCURRENT", "8"))
MIN_FREE_GB = 50
MIN_SCOREABLE_BYTES = 1200

_lock = threading.Lock()
_state: dict[str, dict] = {}


def log(msg: str) -> None:
    print(f"[{datetime.now():%m-%d %H:%M:%S}] {msg}", flush=True)


#: Slurm states in which the job stamped on a claim will still get to run its task.
#: PENDING counts: a requeued element is between allocations rather than dead, and taking
#: its task from it only means both run it once it starts.
_LIVE_SLURM_STATES = frozenset({
    "PENDING", "RUNNING", "COMPLETING", "CONFIGURING", "RESIZING", "SUSPENDED", "REQUEUED",
})


def _scoreable(ws: Path) -> bool:
    """Did this workspace produce a report a scorer should be handed?

    Size alone is not the test. AutoR writes report.md as it goes, so an agent killed at
    stage one leaves a large file with `"status": "failed"` and exit 143 recorded beside
    it -- Math_003 was SIGTERMed at 2 h 18 m holding 16659 bytes and one approved stage.
    Both the claim check and the resume check ask this one function so the two cannot
    drift: the resume check already demanded `status == "completed"` while the claim check
    took any file over MIN_SCOREABLE_BYTES, and that gap is how two fragments came to
    occupy main40 slots that no re-run could reclaim.
    """
    report, meta = ws / "report" / "report.md", ws / "_meta.json"
    if not (report.exists() and meta.exists()):
        return False
    if report.stat().st_size < MIN_SCOREABLE_BYTES:
        return False
    try:
        return json.loads(meta.read_text()).get("status") == "completed"
    except (OSError, json.JSONDecodeError):
        return False


def _this_job() -> str:
    """Who this process is, precisely enough to tell three cases apart.

    A bare Slurm job id cannot, and that cost two of the five holes an adversarial review
    reproduced against this file. All three of these share one job id:

      * me, right now
      * my predecessor -- the same element before Slurm requeued it, which keeps the id
      * my sibling -- another process of the same allocation working a different task

    Only the middle one is dead. The old stamp collapsed all three, so `_owner_alive`
    answered "dead" for a live sibling and two launchers ran one task. Restart count
    separates the predecessor (strictly lower) and pid separates the sibling.
    """
    job = os.environ.get("SLURM_JOB_ID")
    if not job:
        return f"local:{os.uname().nodename}:{os.getpid()}"
    # Unset on a first allocation and set from 1 upwards after a requeue, so "0" is the
    # right default rather than a placeholder.
    restart = os.environ.get("SLURM_RESTART_COUNT", "0")
    return f"{job}:{restart}:{os.getpid()}@{os.uname().nodename}"


def _parse_owner(stamp: str) -> tuple[str, int, int] | None:
    """(job, restart, pid) from a stamp, or None for anything older or foreign."""
    try:
        job, restart, rest = stamp.split(":", 2)
        pid = rest.split("@", 1)[0]
        return (job, int(restart), int(pid))
    except (ValueError, IndexError):
        return None


def _record_owner(claim: Path) -> None:
    """Stamp a claim with the process that intends to run the task."""
    try:
        (claim / "owner").write_text(_this_job(), encoding="utf-8")
    except OSError:
        pass  # an unstamped claim still works; it just falls back to the mtime heartbeat


#: How long a fresh claim is believed on its own say-so. A launcher that has just won a
#: task has not written `_agent_output.jsonl` yet, so the heartbeat cannot see it and the
#: next launcher along would read the silence as a dead owner. Slurm answers for its own
#: jobs through `_owner_alive`; this covers the cases it cannot -- a run started outside
#: Slurm, and the seconds between winning a claim and the agent's first write.
SEIZE_GRACE_SECONDS = 900


def _claimed_recently(claim: Path) -> bool:
    """Did somebody take this claim within the grace window?

    Every winner stamps `owner`, so that file's mtime is "when this task was last claimed"
    regardless of whether a workspace exists yet.
    """
    try:
        return time.time() - (claim / "owner").stat().st_mtime < SEIZE_GRACE_SECONDS
    except OSError:
        return False


#: Waiting longer than the section can possibly take buys nothing; a launcher that cannot get
#: in leaves the task to whoever is inside.
LOCK_WAIT_SECONDS = 20


@contextlib.contextmanager
def _exclusive(lock: Path):
    """Mutual exclusion on a shared filesystem, yielding whether it was obtained.

    `mkdir`, not `flock`: /rmeng_data is NFSv3, where `flock` is served by a lock manager
    that has historically been the flaky part of the stack, while directory creation is
    atomic by protocol. The claim protocol above already rests on that, so this rests on
    the same thing rather than adding a second assumption.

    **There is no stale-lock reaper, and two attempts at one are why.** A lock left behind
    by a killed holder is real -- `finally` does not run on SIGKILL -- so recovering it
    automatically is tempting. It cannot be done correctly from inside the acquire path:

      1. `rmdir` then `mkdir` is delete-and-retry, not test-and-set. Two launchers that both
         judged the lock stale both deleted it, and the second deletion took the *first
         one's live lock*, because `rmdir` unlinks the path rather than the directory that
         was stat'ed. Measured on this mount with no fault injection: 12 of 12 trials with
         more than one winner at twelve contenders, and 4 of 10 across four real nodes with
         the winners on different hosts.
      2. Reaping by atomic `rename` fixes who *wins the reap* and not what is reaped. The
         staleness verdict is formed against the old directory and the rename acts on the
         path, so a launcher still holding a verdict from a moment ago renames away a live
         lock that a successor has already created and already confirmed. Adding a holder
         nonce inside the lock does not close it either -- 12 of 25 trials at twelve
         contenders. A confirmation cannot outrun a reaper that acts on the path.

    So the lock only ever fails closed. A leaked `.seize.lock` costs one task a delayed
    re-run, and it is cleared by hand with `rmdir`, the same gesture this file already
    documents for a claim that needs re-running. Two live agents on one task costs a paid
    duplicate run and silently corrupts an arm, which is the failure worth engineering
    against.
    """
    nonce, deadline, held = uuid.uuid4().hex, time.time() + LOCK_WAIT_SECONDS, False
    while time.time() < deadline:
        try:
            lock.mkdir()
        except FileExistsError:
            time.sleep(0.05)
            continue
        except OSError:
            break
        # Held, provisionally. Confirm with a second `mkdir` rather than assuming: nothing
        # here reaps, but a human clearing a wedged lock by hand can still land between
        # these two lines, and seeing another holder's marker has to mean failure. A written
        # -then-read-back nonce would not do -- two holders overwrite each other's file and
        # both read back their own. `O_CREAT|O_EXCL` is the one primitive NFSv3 cannot make
        # atomic; directory creation is.
        try:
            (lock / f"h.{nonce}").mkdir()
            held = [p.name for p in lock.glob("h.*")] == [f"h.{nonce}"]
        except OSError:
            held = False
        break
    try:
        yield held
    finally:
        if held:
            shutil.rmtree(lock, ignore_errors=True)


#: How long a claim directory with no owner in it is read as "somebody is mid-stake" rather
#: than "nobody is here". Covers one write on a mount that can stall; anything older is a
#: claim from before the stamp existed, and there are legacy ones on disk.
STAKE_SETTLE_SECONDS = 120


def _stake(claim: Path) -> bool:
    """Take a task nobody has claimed. True if this process created the claim.

    `mkdir` then `_record_owner` is two steps, and between them the claim exists with no
    owner -- the one state every reader treats as "nobody is here". A second launcher
    landing in that window reads an empty token, gets None from `_owner_alive`, finds no
    heartbeat because the first has not started an agent yet, and seizes. Both run. An
    adversarial review reproduced it, and a forty-task arm is forty chances for a small
    window to land.

    Staging the directory elsewhere and `rename`-ing it into place looks like the fix and is
    not, on this filesystem or any POSIX one: renaming a directory onto an **empty**
    directory *succeeds and replaces it*, and it fails only when the target is non-empty
    (measured here: ENOTEMPTY, errno 39). Every claim written before the owner stamp existed
    is an empty directory -- there are 29 of them under `full40_main40` alone -- so a staking
    launcher would silently displace a live claim rather than lose to it.

    So exclusion stays with `mkdir`, the primitive that has never been the wrong one here,
    and the unowned window is closed by reading rather than writing: `_claim_settling` below
    treats a stampless claim younger than `STAKE_SETTLE_SECONDS` as somebody mid-stake.
    """
    try:
        claim.mkdir()
    except OSError:
        return False
    _record_owner(claim)
    return True


def _claim_settling(claim: Path) -> bool:
    """A claim with no owner yet, new enough that somebody is probably still staking it.

    An old stampless claim is a different thing -- one written before this file grew the
    stamp -- and must fall through to the heartbeat instead of blocking for ever.
    """
    if (claim / "owner").exists():
        return False
    try:
        return time.time() - claim.stat().st_mtime < STAKE_SETTLE_SECONDS
    except OSError:
        return False


def _owner_token(claim: Path) -> tuple[str, int]:
    """Who owns this claim and when they said so -- the state a takeover verdict rests on."""
    owner = claim / "owner"
    try:
        return (owner.read_text(encoding="utf-8").strip(), owner.stat().st_mtime_ns)
    except OSError:
        return ("", 0)


def _seize(claim: Path, token: tuple[str, int]) -> bool:
    """Take a claim whose owner is gone. True only for the launcher that wins it.

    The claim directory cannot be the atomic primitive a second time. It already exists, so
    `mkdir` has nothing left to fail on, and the takeover was a bare `_record_owner` -- a
    plain write that the loser of a race completes just as successfully as the winner. Two
    launchers that both observed a dead owner therefore both proceeded. On 2026-08-19 that
    put two or three live runs on each of eleven `main40` tasks: `Math_001` alone holds a
    02:06 run that failed and 05:53 and 06:40 runs racing each other, all three paid for.

    Numbering the takeovers and letting each launcher `mkdir` its own generation does not
    fix it, and the way it fails is worth recording because it looks like a fix. Whoever
    arrives second sees `takeover-000` already there, works out that the next free slot is
    001, and takes it -- so noticing that somebody else has taken over becomes the reason to
    take over as well. Twelve contenders against that scheme produced three winners.

    What makes it exclusive is that the *verdict and the acquisition* happen together.
    `token` is the owner and stamp time the caller read before it went off to ask Slurm
    whether that owner still exists. Under the lock, this compares that token against the
    claim as it is now: unchanged means the caller is the first to act on a state that is
    still true, and it stamps its own id, which changes the token and turns every other
    contender's verdict stale. A launcher that cannot get the lock loses by default, because
    the only thing behind the lock is somebody in the middle of taking the same task.
    """
    with _exclusive(claim / ".seize.lock") as held:
        if not held or _owner_token(claim) != token:
            return False
        _record_owner(claim)
        return True


def _owner_alive(claim: Path) -> bool | None:
    """Is the job stamped on this claim still known to the scheduler?

    True and False answer the question. None means it cannot be answered here -- no owner
    recorded (a claim written before this file grew the stamp), an owner from outside
    Slurm, or a `squeue` that did not respond -- and the caller falls back to mtime.

    **False has to mean certainly dead**, because the caller lets a False override a live
    heartbeat, and a wrong False is a second agent on somebody else's task. The old version
    returned False for any owner sharing this process's job id, which was written for the
    requeue case and also fired for a live sibling process of the same allocation. An
    adversarial review reproduced three nodes TAKEing one task through that branch. So the
    only same-job owner now called dead is one from a strictly earlier allocation.
    """
    try:
        owner = (claim / "owner").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    mine, theirs = _parse_owner(_this_job()), _parse_owner(owner)
    if theirs is not None and mine is not None and theirs[0] == mine[0]:
        if theirs[1] < mine[1]:
            return False       # my predecessor: same element, allocation before the requeue
        if theirs[2] == mine[2]:
            return True        # literally this process
        return None            # a sibling, or a stamp from the future: not mine to judge
    job = owner if owner.isdigit() else (theirs[0] if theirs else "")
    if not job.isdigit():
        return None
    owner = job
    try:
        out = subprocess.run(["squeue", "-h", "-j", owner, "-o", "%T"],
                             capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        # `Invalid job id specified` is how squeue reports a job it has already forgotten,
        # which is a dead owner rather than an unanswerable question.
        return False if "Invalid job id" in out.stderr else None
    return bool({s.strip() for s in out.stdout.split() if s.strip()} & _LIVE_SLURM_STATES)


def acquire(claim: Path, root: Path, task: str) -> tuple[bool, str]:
    """May this launcher run `task`? `(True, why)` to proceed, `(False, why)` to stand down.

    A function rather than a block inside `run_one` so that `test_claim_race.py` exercises
    the decision that ships instead of a paraphrase of it. That distinction is not academic:
    a test worker that re-implemented this logic and left out one guard reported two winners
    against code that was correct, which is a fifth wrong answer about this protocol from a
    test rather than from the thing under test.
    """
    if _stake(claim):
        return True, ""

    # Already claimed. Stand down unless it produced nothing, in which case the claimant died
    # and this launcher takes over rather than leaving a hole in the arm.
    #
    # Read who owns it first. Everything below is evidence about the claim as it stood at
    # this instant, and the seize has to be pinned to that same instant or it is not an
    # interlock -- `_seize` says why at length.
    token = _owner_token(claim)
    if any(_scoreable(w) for w in root.glob(f"{task}_*")):
        return False, "claimed by another launcher"
    recent = any((w / "_agent_output.jsonl").exists()
                 and time.time() - (w / "_agent_output.jsonl").stat().st_mtime < 1800
                 for w in root.glob(f"{task}_*"))
    # A heartbeat cannot tell "another launcher is working" from "the last launcher was
    # killed nine minutes ago". Restarting slurmd on a node kills its jobs and Slurm requeues
    # them under the SAME job id, so the element comes back well inside the 1800 s window,
    # reads its own dying heartbeat as somebody else's, and skips the very task it was
    # requeued to run. That failure is silent: exit 0, two seconds, one SKIP line, and a hole
    # in the arm nobody counts. It took nine main40 elements on 2026-08-19 to notice.
    #
    # So ask the scheduler, which knows whether the claimant still exists, and keep the
    # heartbeat for the claims it cannot answer for -- ones stamped before this check
    # existed, ones taken outside Slurm, and a squeue that times out.
    owner = _owner_alive(claim)
    # Evidence of life beats a verdict of death from anywhere except the one place that is
    # certain. `owner is False` now means only "my own earlier allocation", which is the
    # requeue case the heartbeat gets wrong on purpose; everything else that cannot be
    # established lands on None and lets the files decide.
    if ((owner is True) or _claim_settling(claim) or _claimed_recently(claim)
            or (recent and owner is not False)):
        return False, "claimed by another launcher"
    # Deciding the owner is dead is not the same as being the one who replaces it. Every
    # launcher that reaches this line reached the same verdict, so the replacement has to be
    # won rather than announced -- see `_seize`.
    if not _seize(claim, token):
        return False, "another launcher took the dead claim first"
    return True, "claim exists but nothing is running or finished"


def run_one(task: str, sem: threading.Semaphore, root: Path, cmd: str, name: str,
            state_path: Path) -> None:
    from evaluation.run_task import TaskRunner

    def save() -> None:
        with _lock:
            state_path.write_text(json.dumps(_state, indent=2), encoding="utf-8")

    def summarize(ws: Path) -> dict:
        report, images = ws / "report" / "report.md", ws / "report" / "images"
        meta = {}
        try:
            meta = json.loads((ws / "_meta.json").read_text())
        except (OSError, json.JSONDecodeError):
            pass
        stages = sum(len([p for p in s.glob("*.md")
                          if not p.name.endswith((".tmp.md", ".skip_stub.md"))])
                     for s in (ws / ".autor").glob("*/stages"))
        return {
            "status": meta.get("status"), "exit_code": meta.get("exit_code"),
            "model": meta.get("model"), "code_version": meta.get("code_version"),
            "duration_seconds": meta.get("duration_seconds"), "workspace": str(ws),
            "report_bytes": report.stat().st_size if report.exists() else 0,
            "images": len(list(images.glob("*.png"))) if images.exists() else 0,
            "approved_stages": stages,
        }

    with sem:
        # Claim the task on the shared filesystem before doing anything expensive. Two
        # launchers now run against one workspace root -- this node's batch and one slurm
        # job per task on the eval partition -- and without a claim both would start the
        # same task and pay twice for it. `mkdir` is the atomic primitive: it either creates
        # the directory or raises, with no window between checking and creating.
        #
        # A claim is never released. It records "some launcher took this", and a task that
        # needs re-running gets its claim removed by hand along with its workspace, which is
        # the same gesture that already deletes a failed run.
        claim = root / ".claims" / task
        claim.parent.mkdir(parents=True, exist_ok=True)
        verdict, why = acquire(claim, root, task)
        if not verdict:
            log(f"SKIP  {task}: {why}")
            return
        if why:
            log(f"TAKE  {task}: {why}")

        for ws in sorted(root.glob(f"{task}_*"), reverse=True):
            if _scoreable(ws):
                with _lock:
                    _state[task] = summarize(ws) | {"resumed": True}
                save()
                log(f"SKIP  {task}: already has a report")
                return
        if shutil.disk_usage(root).free / 1e9 < MIN_FREE_GB:
            log(f"SKIP  {task}: low disk")
            return

        started = time.time()
        log(f"START {task}")
        try:
            runner = TaskRunner(task, agent_cmd=cmd, agent_name=name)
            runner.setup_workspace()
            with _lock:
                _state[task] = {"status": "running", "workspace": str(runner.workspace)}
            save()
            runner.run()
            entry = summarize(runner.workspace)
        except Exception as exc:  # noqa: BLE001 - one bad task must not stop the batch
            entry = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        entry["wall_seconds"] = round(time.time() - started)
        with _lock:
            _state[task] = entry
        save()
        log(f"DONE  {task}: {entry.get('status')} model={entry.get('model')} "
            f"stages={entry.get('approved_stages')} report={entry.get('report_bytes', 0)}B "
            f"imgs={entry.get('images', 0)} {entry['wall_seconds']}s")


def main(argv: list[str]) -> int:
    arm, *only = argv
    name, cmd = ARMS[arm]
    root = common.use_workspace_root(common.RUNS / {
        "control": "control_bare_cc", "autor": "full40", "autor_v220": "full40_v220", "autor_head": "full40_head", "autor_skills": "full40_skills", "autor_skills161": "full40_skills161", "autor_main40": "full40_main40", "autor_abl40": "full40_abl40", "control_search": "control_search_g37", "xrev_on": "xrev_on", "xrev_off": "xrev_off", "pins_on": "pins_on", "pins_off": "pins_off", "opcalls_on": "opcalls_on", "opcalls_off": "opcalls_off", "panel_on": "panel_on", "panel_off": "panel_off", "autor_pins": "full40_pins", "autor_a9c": "full40_a9c2b48", "autor_gpt54": "full40_gpt54", "topology_adaptive": "topo_adaptive", "topology_linear": "topo_linear",
    }[arm])
    suffix = "" if len(argv) == 1 else "_" + "_".join(argv[1:])[:40]
    state_path = common.RESULTS / f"{arm}{suffix}_state.json"

    from evaluation.config import TASKS_DIR
    tasks = sorted(p.name for p in TASKS_DIR.iterdir()
                   if p.is_dir() and (p / "task_info.json").exists())
    # Named tasks run through the same command, concurrency and resume rule as a full pass.
    # A one-off re-run written as its own script is how two arms silently stop being
    # comparable, so a re-run is a filter on this one rather than a second launcher.
    if only:
        unknown = [t for t in only if t not in tasks]
        if unknown:
            raise SystemExit(f"unknown task(s): {unknown}")
        tasks = only

    if arm == "autor":
        sha = subprocess.run(["git", "-C", str(AUTOR_PIN), "rev-parse", "--short=12", "HEAD"],
                             capture_output=True, text=True).stdout.strip()
        log(f"pinned AutoR: {AUTOR_PIN} @ {sha}")
    log(f"arm={arm} ({name})")
    log(f"cmd: {cmd}")
    log(f"workspaces: {root} ({shutil.disk_usage(root).free/1e9:.0f} GB free)")
    log(f"{len(tasks)} tasks at concurrency {MAX_CONCURRENT}; state -> {state_path}")

    sem = threading.Semaphore(MAX_CONCURRENT)
    threads = [threading.Thread(target=run_one, args=(t, sem, root, cmd, name, state_path))
               for t in tasks]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ok = [t for t, v in _state.items() if v.get("report_bytes", 0) >= MIN_SCOREABLE_BYTES]
    log(f"ARM COMPLETE: {len(ok)}/{len(tasks)} produced a scoreable report; "
        f"models seen: {sorted({v.get('model') for v in _state.values() if v.get('model')})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
