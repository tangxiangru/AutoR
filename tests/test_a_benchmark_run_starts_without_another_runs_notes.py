"""Claude Code's memory store is keyed on an ancestor directory, so runs share it.

The store is not per-run and not per-workspace. Probed against the real binary (2.1.229) on
this box, a session whose cwd was `/rmeng_data/robtang/memprobe` -- one directory down -- and a
benchmark stage whose cwd was five directories down, a per-task workspace's `.autor/<timestamp>`
directory, both reported the same `memory_paths.auto`:

    /home/robtang_google_com/.claude/projects/-rmeng-data-robtang/memory/

The four levels between them are the measurement: the key is an *ancestor* of the cwd, so no
amount of nesting under one results directory separates two runs.

Every run under one results directory therefore reads and writes one store, whose `MEMORY.md`
index is loaded into each agent's context at session start. That is a channel between the
runs of a benchmark, and on the sixty-task trial of 2026-08-19 -- run against a benchmark
since removed from this repository, which does not unmake the measurement -- it carried
traffic: the two most-read files in a 1,456-file store were notes an earlier run had written
about how that harness chose the answer it published -- `fs-ideate-write-answer-md-yourself-to-preempt-synthesis`
at 92 reads and `an-existing-answer-md-outranks-the-synthesizer` at 56, both still in the store
above, which outlives the adapter -- and in the chemistry block the read was the *first* tool
call of the run, in both arms, before the agent had looked at the problem.
It is asymmetric, too: 32 of 37 pipeline runs reached the store against 8 of 37 direct ones,
so it does not cancel out of a paired comparison.

**The default stays off, and the control for that is a test here.** AutoR's ordinary use is a
researcher's own project, where carrying notes between sessions is the feature working; only
a measurement needs every run to start from the same state. So the isolation is opt-in: a
benchmark front end that needs it asks for it, and nothing else changes -- including the
sibling benchmarks that were mid-flight when this landed.

The front-end half of this file went with that benchmark. Two classes used to live below --
one asserting that its front end asked for isolation, one asserting that its `_meta.json`
recorded the answer as a tri-state where `None` means "never asked" -- and both were about
code that has been deleted, so they were removed with it. What is left, `TheFlagTests`, is
the guard on `ClaudeOperator(isolate_auto_memory=...)` itself. Nothing in the tree passes it
today -- the front end that did was the deleted one -- so this file is now the only thing
holding the flag correct, and the measurement above is the only recorded reason it exists.
Both are here so the next paired trial can ask for isolation rather than rediscover why it
needs to.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.operator import ClaudeOperator  # noqa: E402

SETTINGS_FLAG = "--settings"


def command_for(**kwargs) -> list[str]:
    operator = ClaudeOperator(model="opus", fake_mode=True, **kwargs)
    return operator._build_cli_command(  # noqa: SLF001
        Path("/tmp/p.md"), "sess-1", resume=False
    )


def settings_payloads(command: list[str]) -> list[dict]:
    return [
        json.loads(command[i + 1])
        for i, arg in enumerate(command)
        if arg == SETTINGS_FLAG and i + 1 < len(command)
    ]


class TheFlagTests(unittest.TestCase):
    def test_an_isolated_operator_turns_the_memory_off(self) -> None:
        self.assertEqual(
            settings_payloads(command_for(isolate_auto_memory=True)),
            [{"autoMemoryEnabled": False}],
        )

    def test_the_value_is_false_and_not_merely_present(self) -> None:
        """A settings blob saying `true` would pass any check that only looks for the key.

        Worth its own assertion because the flag's whole content is one boolean: a mutation
        that writes the opposite one leaves the command line the right shape and the right
        length, and turns the isolation into a no-op that still records itself as applied.
        """
        payload = settings_payloads(command_for(isolate_auto_memory=True))[0]
        self.assertIn("autoMemoryEnabled", payload)
        self.assertIs(payload["autoMemoryEnabled"], False)

    def test_the_key_is_spelled_the_way_the_binary_spells_it(self) -> None:
        """`autoMemoryEnabled`, exactly. An unknown key is accepted and does nothing.

        This is the failure mode with no symptom: the CLI does not reject a settings blob it
        does not recognise, so a misspelling produces a run that looks isolated in its own
        metadata, reads the shared store anyway, and reports nothing unusual. The spelling
        was taken off the binary's own symbol table and confirmed by probing a real run's
        `init` event: **no `memory_paths` key at all** with the flag, the shared path without
        it. Note the shape -- the key is omitted, not nulled, so a reader that does
        `init["memory_paths"] is None` raises `KeyError` on exactly the run it is checking
        for, and `.get()` cannot distinguish isolation from a malformed event.

        Re-probed 2026-08-19 against 2.1.229 from a compute node with cwd inside the live
        run tree (`/rmeng_data/robtang/rcb_runs/topo_adaptive`), which is the case that
        matters here and is not the case the FrontierScience probe covered.
        """
        self.assertEqual(
            list(settings_payloads(command_for(isolate_auto_memory=True))[0]), ["autoMemoryEnabled"]
        )

    def test_an_ordinary_operator_is_left_alone(self) -> None:
        self.assertEqual(settings_payloads(command_for(isolate_auto_memory=False)), [])
        self.assertNotIn(SETTINGS_FLAG, command_for(isolate_auto_memory=False))

    def test_the_default_is_not_isolated(self) -> None:
        """The control on the blast radius: every other AutoR path keeps its memory.

        Without this, flipping the default would be invisible -- every other test in the
        repo passes either way, and the change would silently take the feature away from
        the researcher-facing use it was built for.
        """
        self.assertIs(ClaudeOperator(model="opus", fake_mode=True).isolate_auto_memory, False)
        self.assertNotIn(SETTINGS_FLAG, command_for())

    def test_isolation_does_not_disturb_the_rest_of_the_command(self) -> None:
        """`--settings` adds to the settings in force; it must not displace anything here.

        The two commands are compared with the flag and its payload removed, so the test
        fails if isolation reorders, drops or duplicates any other argument -- the model,
        the permission mode, the session id.
        """
        isolated = command_for(isolate_auto_memory=True)
        plain = command_for(isolate_auto_memory=False)
        stripped = [
            arg
            for i, arg in enumerate(isolated)
            if arg != SETTINGS_FLAG and (i == 0 or isolated[i - 1] != SETTINGS_FLAG)
        ]
        self.assertEqual(stripped, plain)

    def test_it_survives_the_other_options(self) -> None:
        operator = ClaudeOperator(
            model="opus", fake_mode=True, isolate_auto_memory=True,
            disallowed_tools=["WebSearch", "WebFetch"],
        )
        command = operator._build_cli_command(  # noqa: SLF001
            Path("/tmp/p.md"), "sess-1", resume=True, tools="Bash,Read",
            mcp_config=Path("/tmp/mcp.json"), disallowed_tools=["WebSearch"],
        )
        self.assertEqual(settings_payloads(command), [{"autoMemoryEnabled": False}])
        self.assertIn("--resume", command)
        self.assertIn("--mcp-config", command)


class EverySeatOrItIsNotAnIsolationTests(unittest.TestCase):
    """The reviewer builds its own operator, and forwarding a flag did not reach it.

    Measured on the running topology ablation 9.5 hours in, from the recorded `command` of
    every CLI invocation across all 80 workspaces of both arms:

        4,513 invocations recorded
        2,752 carried --settings {"autoMemoryEnabled": false}   -- every stage call
        1,761 did not                                            -- every reviewer call

    The split was exact: 0 of 1,761 `review_start`/`review_verdict_start` calls had the
    flag and 0 of 2,752 stage calls lacked it. All 80 workspaces reached the store, and
    the traffic was one-directional -- the adaptive arm wrote 10 times, the linear arm 0 --
    on notes about the review mechanism itself, read by the seat that decides whether a
    stage is approved. `approval_agent.py`'s own comment already said why this matters:
    "a protocol that denies a tool has to reach every seat or it is not the protocol."

    So the choice moved from a parameter each seat must remember to forward, to a
    process-wide default every seat inherits. These tests pin that, and they are the ones
    that were missing: the front-end tests below all passed while every reviewer in the
    system read the shared store.
    """

    def setUp(self) -> None:
        from src.operator import isolate_auto_memory_by_default

        self.addCleanup(isolate_auto_memory_by_default, False)

    def reviewer_operator(self):
        from src.approval_agent import AutomatedReviewer

        return AutomatedReviewer("claude", model="opus", fake_mode=True)._operator  # noqa: SLF001

    def command_of(self, operator) -> list[str]:
        return operator._build_cli_command(Path("/tmp/p.md"), "sess-1", resume=False)  # noqa: SLF001

    def test_the_reviewer_seat_is_isolated_too(self) -> None:
        from src.operator import isolate_auto_memory_by_default

        isolate_auto_memory_by_default(True)
        self.assertEqual(
            settings_payloads(self.command_of(self.reviewer_operator())),
            [{"autoMemoryEnabled": False}],
        )

    def test_the_stage_seat_is_isolated_by_the_same_switch(self) -> None:
        from src.operator import isolate_auto_memory_by_default

        isolate_auto_memory_by_default(True)
        self.assertEqual(
            settings_payloads(self.command_of(ClaudeOperator(model="opus", fake_mode=True))),
            [{"autoMemoryEnabled": False}],
        )

    def test_a_researchers_own_reviewer_keeps_its_memory(self) -> None:
        """The control on the blast radius, for the seat this change adds.

        Without it, moving the default into the process would silently take the feature
        away from interactive use, where carrying notes between sessions is the point.
        """
        from src.operator import auto_memory_isolated_by_default

        self.assertIs(auto_memory_isolated_by_default(), False)
        self.assertEqual(settings_payloads(self.command_of(self.reviewer_operator())), [])

    def test_an_explicit_argument_still_wins_over_the_default(self) -> None:
        from src.operator import isolate_auto_memory_by_default

        isolate_auto_memory_by_default(True)
        opt_out = ClaudeOperator(model="opus", fake_mode=True, isolate_auto_memory=False)
        self.assertIs(opt_out.isolate_auto_memory, False)
        self.assertEqual(settings_payloads(self.command_of(opt_out)), [])

    def test_the_benchmark_front_end_sets_it(self) -> None:
        """Reading the source, because calling `main()` would start a benchmark run.

        One front end now, not two: the other was removed with its benchmark in #308.
        """
        source = (Path(__file__).resolve().parents[1] / "rcb_agent.py").read_text()
        self.assertIn(
            "isolate_auto_memory_by_default(True)",
            source,
            "rcb_agent.py runs measurements and must cut every seat off from the store",
        )


class WhatTheResearchClawBenchFrontEndAsksForTests(unittest.TestCase):
    """The sibling benchmark, whose paired ablation is the worst case for the channel.

    FrontierScience runs one arm per task. ResearchClawBench's topology ablation runs
    *two* arms over the same forty tasks under one results directory, so the store is not
    a channel from last week's run into this one -- it is a channel between the two things
    being compared, carrying notes filed under the name of the task both arms are working
    on right now. Measured on 2026-08-19 while the first attempt was in flight: 378 writes
    to `-rmeng-data-robtang/memory/` that day, 29 of them named after a specific task in
    `tasks40.txt`.

    The direction is the damaging one. A channel that makes each arm partly a copy of the
    other shrinks the difference the ablation exists to measure, so a real topology effect
    would present as absent, and the run would look like a clean null result.
    """

    def operator_for(self, backend: str):
        from rcb_agent import create_operator

        return create_operator(
            backend=backend, model="opus", fake_mode=True, ui=None, stage_timeout=60,
            disallowed_tools=["WebSearch"], codex_sandbox="danger-full-access",
            codex_command="codex",
        )

    def test_the_researchclawbench_front_end_isolates(self) -> None:
        self.assertIs(self.operator_for("claude").isolate_auto_memory, True)

    def test_the_command_it_builds_carries_the_flag(self) -> None:
        """Not just the attribute: the argument that reaches the binary.

        The attribute assertion above passes on a front end that sets the field on an
        operator whose command builder never reads it. This one fails there.
        """
        command = self.operator_for("claude")._build_cli_command(  # noqa: SLF001
            Path("/tmp/p.md"), "sess-1", resume=False
        )
        self.assertEqual(settings_payloads(command), [{"autoMemoryEnabled": False}])

    def test_a_codex_seat_is_untouched_here_too(self) -> None:
        self.assertIs(self.operator_for("codex").isolate_auto_memory, False)


if __name__ == "__main__":
    unittest.main()
