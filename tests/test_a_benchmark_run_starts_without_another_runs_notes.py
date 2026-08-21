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
at 92 reads and `an-existing-answer-md-outranks-the-synthesizer` at 56 -- and in the chemistry
block the read was the *first* tool call of the run, in both arms, before the agent had looked
at the problem.

Those two notes have since been deleted from that store, because what they described is a code
path that no longer exists and an agent following them today would act on nothing. **The store
itself is untouched and still shared**, which is the fact this file is about: it belongs to
Claude Code, it outlives any one benchmark, and the next set of runs under one results
directory will pool their notes in it exactly as these did.
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


if __name__ == "__main__":
    unittest.main()
