"""Claude Code's memory store is keyed on an ancestor directory, so runs share it.

The store is not per-run and not per-workspace. Probed against the real binary (2.1.229) on
this box, a session whose cwd was `/rmeng_data/robtang/memprobe` and a benchmark stage whose
cwd was `/rmeng_data/robtang/fs-trial-skills/workspaces/fs024_direct-opus_.../.autor/<ts>`
both reported the same `memory_paths.auto`:

    /home/robtang_google_com/.claude/projects/-rmeng-data-robtang/memory/

Every run under one results directory therefore reads and writes one store, whose `MEMORY.md`
index is loaded into each agent's context at session start. That is a channel between the
runs of a benchmark, and on the sixty-task FrontierScience trial it carried traffic: the two
most-read files in a 1,456-file store were notes an earlier run had written about this
harness's own exit clauses -- `fs-ideate-write-answer-md-yourself-to-preempt-synthesis` at 92
reads and `an-existing-answer-md-outranks-the-synthesizer` at 56 -- and in the chemistry block
the read was the *first* tool call of the run, in both arms, before the agent had looked at
the problem. It is asymmetric, too: 32 of 37 pipeline runs reached the store against 8 of 37
direct ones, so it does not cancel out of a paired comparison.

**The default stays off, and the control for that is a test here.** AutoR's ordinary use is a
researcher's own project, where carrying notes between sessions is the feature working; only
a measurement needs every run to start from the same state. So the isolation is opt-in, the
FrontierScience front end opts in, and nothing else changes -- including the sibling
benchmarks that were mid-flight when this landed.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.frontierscience import FS_SOURCE_AGENT, FsAnswer, build_fs_meta  # noqa: E402
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
        was taken off the binary's own symbol table and confirmed by probing
        `memory_paths`: the shared path without the flag, and with it **no `memory_paths`
        key at all** rather than a `null` one. Re-probed from `/rmeng_data/robtang` on
        2026-08-19 against 2.1.229, because the difference matters to whoever reads an
        init event next -- a check written as `init["memory_paths"] is None` raises
        `KeyError` on exactly the run it exists to recognise.
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


class WhatTheFrontEndAsksForTests(unittest.TestCase):
    def operator_for(self, backend: str):
        from fs_agent import create_operator

        return create_operator(
            backend=backend, model="opus", fake_mode=True, ui=None, stage_timeout=60,
            disallowed_tools=["WebSearch"], codex_sandbox="danger-full-access",
            codex_command="codex",
        )

    def test_the_frontierscience_front_end_isolates(self) -> None:
        self.assertIs(self.operator_for("claude").isolate_auto_memory, True)

    def test_a_claude_seat_reports_what_it_did(self) -> None:
        from fs_agent import auto_memory_isolation_for

        operator = self.operator_for("claude")
        self.assertIs(auto_memory_isolation_for(operator, "claude"), True)
        operator.isolate_auto_memory = False
        self.assertIs(auto_memory_isolation_for(operator, "claude"), False)

    def test_a_codex_seat_claims_nothing(self) -> None:
        """It never starts Claude Code, so the store is not a fact about it either way.

        The trap this pins: `CodexOperator` subclasses `ClaudeOperator`, so it *inherits*
        the attribute and a plain read returns `False` -- a codex run would record "the
        memory store was reachable" about a binary it never ran. The assertion on the
        inherited attribute is here so the test states why the branch exists rather than
        looking like a redundant null check somebody could delete.
        """
        from fs_agent import auto_memory_isolation_for

        operator = self.operator_for("codex")
        self.assertIs(operator.isolate_auto_memory, False)
        self.assertIsNone(auto_memory_isolation_for(operator, "codex"))

    def test_an_operator_without_the_attribute_is_not_an_exception(self) -> None:
        from fs_agent import auto_memory_isolation_for

        self.assertIs(auto_memory_isolation_for(object(), "claude"), False)


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


class WhatTheRecordSaysTests(unittest.TestCase):
    """Tri-state, because "not isolated" and "not recorded" are different facts."""

    def meta(self, **kwargs) -> dict:
        return build_fs_meta(
            workspace=Path("/tmp/ws"), task="fs:000", profile="direct",
            answer_guidance="minimal", model="opus", review_model="opus",
            operator="claude", pipeline_completed=True,
            answer=FsAnswer(
                path=Path("/tmp/ws/answer.md"), source=FS_SOURCE_AGENT,
                chars=900, sha256="0" * 64, refusals=[],
            ),
            auto_skipped_stages=[], stages_approved=[], disallowed_tools=[],
            dataset_path=None, dataset_sha256="d", run_id="r", duration_seconds=1,
            **kwargs,
        )

    def test_true_is_recorded(self) -> None:
        self.assertIs(self.meta(auto_memory_isolated=True)["auto_memory_isolated"], True)

    def test_false_is_recorded(self) -> None:
        self.assertIs(self.meta(auto_memory_isolated=False)["auto_memory_isolated"], False)

    def test_a_record_that_was_never_asked_says_so(self) -> None:
        """`None`, not `False`. The sixty-task trials on disk are exactly this case.

        They ran with the store open and no field to say so. Defaulting the omission to
        `False` would assert a measurement nobody made; defaulting it to `True` would let
        them claim an isolation they did not have. The field is present either way, so a
        reader gets `null` rather than a `KeyError` they might paper over.
        """
        payload = self.meta()
        self.assertIn("auto_memory_isolated", payload)
        self.assertIsNone(payload["auto_memory_isolated"])

    def test_the_field_survives_a_round_trip(self) -> None:
        self.assertIs(
            json.loads(json.dumps(self.meta(auto_memory_isolated=True)))["auto_memory_isolated"],
            True,
        )


if __name__ == "__main__":
    unittest.main()
