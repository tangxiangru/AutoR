"""`--web-search off` has to mean off, in both readers and at the command line.

Five defects, one flag.

The first: ``src.web_search`` has two readers of the mode string and they had the same
shape and the same hole. ``resolve_web_search_context`` returned early for ``"native"``
and let everything else fall through to ``build_web_search_prompt_section()``;
``web_search_notice`` returned early for ``"native"`` and let everything else fall
through to a credential probe. Adding ``"off"`` to ``WEB_SEARCH_MODE_CHOICES`` and to one
of them would have produced a flag named `off` that injected the Gemini search prompt
section and warned about a missing API key -- the opposite of both halves of its name.
The fix is a single mapping both readers consult, so a fifth mode cannot be added to one
of them alone.

The second: ``ClaudeOperator._build_cli_command`` built a fixed command line and passed
tool restrictions only on the repair path, so a run conducted "without browsing" still
had ``WebSearch`` and ``WebFetch`` in the agent's tool list. Being told not to search is
not the same as not being able to, and the difference matters for a benchmark whose
published protocol is the former.

The third: ``main.configure_effort`` built the routine-tier operator -- the one that runs
whole stages under ``--effort-tiers --routine-model`` -- with no denied tools, so the
flag held for the stages the effort plan sent to the strong tier and not for the others.
``rcb_agent.py`` passed the list at the same construction, so the two front ends
disagreed about what one flag meant.

The fourth is a defect in the guard rather than in the code it guards, and is why the
call sites are read with ``ast`` here rather than grepped. The first version of this
module asserted ``"disallowed_tools=disallowed_tools_for(" in source``, and both files
contain that string more than once: deleting the fresh-run wiring in `main.py` -- the
line every ordinary ``python main.py --web-search off`` executes -- kept the suite green
on the strength of the ``--resume-run`` branch's copy, and no substring could have seen
the routine tier above at all.

The fifth is what these tests are careful *not* to claim. ``Bash`` is still available --
the stages cannot run without it -- and ``curl`` lives inside ``Bash``. So the flag
narrows the path to the network and does not close it, and every assertion below is about
what reaches the command line, never about what a run could not possibly do.
"""

from __future__ import annotations

import ast
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import main as autor_main
import rcb_agent
from src.utils import WEB_SEARCH_MODE_CHOICES, build_run_paths, ensure_run_layout
from src.web_search import (
    NO_BROWSING_DISALLOWED_TOOLS,
    NOTICES_DECIDED_WITHOUT_A_PROBE,
    disallowed_tools_for,
    resolve_web_search_context,
    web_search_notice,
)


#: The two front-end files, found through the imported module rather than through the
#: working directory: `unittest discover` is run from the repository root today, and a
#: source-reading test that silently reads nothing when it is not is a test that reports
#: green for the wrong reason.
REPO_ROOT = Path(autor_main.__file__).resolve().parent


def _no_key():
    """The key file this box may actually have is not part of any of these questions."""
    return patch("src.web_search.DIAGRAM_CONFIG_PATH", Path("/nonexistent/diagram.yaml"))


class TheOffModeIsAKnownModeTest(unittest.TestCase):
    def test_the_constant_offers_it(self) -> None:
        self.assertIn("off", WEB_SEARCH_MODE_CHOICES)

    def test_both_front_ends_accept_it(self) -> None:
        """The two CLIs used to declare their choices separately, and had drifted.

        `main.py` derived its list from ``WEB_SEARCH_MODE_CHOICES`` and `rcb_agent.py`
        wrote the three values out by hand, so a mode added to the constant reached one
        front end and not the other. Both are asked here.
        """
        with patch.object(sys, "argv", ["main.py", "--web-search", "off", "--goal", "g"]):
            self.assertEqual(autor_main.parse_args().web_search, "off")
        self.assertEqual(rcb_agent.parse_args(["--web-search", "off"]).web_search, "off")

    def test_a_run_can_record_it_and_read_it_back(self) -> None:
        """A mode the config cannot store is silently downgraded on resume."""
        from src.utils import load_run_config, normalize_web_search_mode, save_run_config

        self.assertEqual(normalize_web_search_mode("off"), "off")
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "run")
            ensure_run_layout(paths)
            save_run_config(paths, {"web_search": "off"})
            self.assertEqual(load_run_config(paths)["web_search"], "off")


class TheOffModeInjectsNoSearchPromptTest(unittest.TestCase):
    def test_off_resolves_to_no_prompt_section(self) -> None:
        with patch.dict(os.environ, {"GEMINI_API_KEY": "k"}, clear=True):
            self.assertIsNone(resolve_web_search_context("off"))

    def test_off_resolves_to_no_prompt_section_even_with_a_working_backend(self) -> None:
        """The credential state is not an input to this question, and must not become one."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "k"}, clear=True), \
             patch("src.web_search.genai_sdk_available", return_value=True):
            self.assertIsNone(resolve_web_search_context("off"))

    def test_auto_with_a_usable_backend_still_injects(self) -> None:
        """Control. Without it, a `resolve_web_search_context` that returned None for
        everything would pass the test above."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "k"}, clear=True), \
             patch("src.web_search.genai_sdk_available", return_value=True):
            self.assertIsNotNone(resolve_web_search_context("auto"))

    def test_the_stage_prompt_carries_no_search_heading_under_off(self) -> None:
        """One level down from the resolver: the block's absence at the seam that uses it."""
        from src.utils import STAGES, build_prompt

        with patch.dict(os.environ, {"GEMINI_API_KEY": "k"}, clear=True), \
             patch("src.web_search.genai_sdk_available", return_value=True):
            off_context = resolve_web_search_context("off")
            auto_context = resolve_web_search_context("auto")
        off_prompt = build_prompt(
            STAGES[0], "template", "goal", "memory", web_search_context=off_context
        )
        auto_prompt = build_prompt(
            STAGES[0], "template", "goal", "memory", web_search_context=auto_context
        )
        self.assertNotIn("# Web Search Capability", off_prompt)
        self.assertIn("# Web Search Capability", auto_prompt)


class TheOffModeDoesNotGoLookingForCredentialsTest(unittest.TestCase):
    """A run told not to search has no question for the readiness probe.

    The probe reads the environment, imports a spec for `google-genai` and may open a
    config file, all to decide what to say about credentials. Under `off` the only thing
    it could produce is a sentence about a key nothing was going to use -- and, before
    the fix, a `warn` about it.
    """

    def test_the_notice_for_off_performs_no_readiness_probe(self) -> None:
        with patch("src.web_search.assess_search_readiness") as probe:
            message, level = web_search_notice("off")
        probe.assert_not_called()
        self.assertEqual(level, "info")
        self.assertTrue(message.strip())

    def test_the_notice_for_auto_does_perform_one(self) -> None:
        """Control: the assertion above is about `off`, not about a probe nobody calls."""
        with patch("src.web_search.assess_search_readiness") as probe:
            probe.return_value.blocker = None
            probe.return_value.backend.describe.return_value = "a backend"
            web_search_notice("auto")
        probe.assert_called_once()

    def test_the_notice_for_off_says_off_rather_than_warning_about_a_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True), _no_key():
            message, level = web_search_notice("off")
        self.assertEqual(level, "info")
        self.assertNotIn("GEMINI_API_KEY", message)
        self.assertIn("off", message.lower())

    def test_auto_without_a_key_still_warns(self) -> None:
        """Control for the one above: `off` is quiet because it is off, not because the
        warning was removed."""
        with patch.dict(os.environ, {}, clear=True), _no_key():
            _message, level = web_search_notice("auto")
        self.assertEqual(level, "warn")

    def test_mains_search_context_resolver_skips_the_probe_under_off(self) -> None:
        from src.terminal_ui import TerminalUI

        ui = TerminalUI(output_stream=io.StringIO(), interactive=False)
        with patch("main.assess_search_readiness") as probe:
            context = autor_main.resolve_search_context(
                ui, mode="off", operator="claude", codex_sandbox="workspace-write"
            )
        probe.assert_not_called()
        self.assertIsNone(context)

    def test_mains_search_context_resolver_still_probes_under_auto(self) -> None:
        """Control. `--web-search gemini` is refused on a blocker, and that refusal reads
        the probe; a resolver that stopped probing at all would take the refusal with it."""
        from src.terminal_ui import TerminalUI

        ui = TerminalUI(output_stream=io.StringIO(), interactive=False)
        with patch("main.assess_search_readiness") as probe:
            probe.return_value.blocker = None
            probe.return_value.hard_blocker = None
            probe.return_value.backend.describe.return_value = "a backend"
            probe.return_value.usable = True
            autor_main.resolve_search_context(
                ui, mode="auto", operator="claude", codex_sandbox="workspace-write"
            )
        probe.assert_called_once()


class TheTwoReadersCannotDriftAgainTest(unittest.TestCase):
    """Both early exits come from one mapping, so a fifth mode moves both or neither."""

    def test_every_mode_answered_without_a_probe_also_injects_nothing(self) -> None:
        self.assertTrue(NOTICES_DECIDED_WITHOUT_A_PROBE)
        for mode in NOTICES_DECIDED_WITHOUT_A_PROBE:
            with self.subTest(mode=mode):
                with patch("src.web_search.assess_search_readiness") as probe:
                    self.assertIsNone(resolve_web_search_context(mode))
                    web_search_notice(mode)
                probe.assert_not_called()

    def test_every_mode_in_the_mapping_is_a_mode_the_cli_accepts(self) -> None:
        """A notice for a mode nobody can select is a branch no run reaches."""
        for mode in NOTICES_DECIDED_WITHOUT_A_PROBE:
            self.assertIn(mode, WEB_SEARCH_MODE_CHOICES)

    def test_the_modes_outside_the_mapping_are_the_ones_that_need_the_probe(self) -> None:
        """Control: the population the test above scans is not everything."""
        self.assertEqual(
            set(WEB_SEARCH_MODE_CHOICES) - set(NOTICES_DECIDED_WITHOUT_A_PROBE),
            {"auto", "gemini"},
        )


class DisallowedToolsForTest(unittest.TestCase):
    def test_off_denies_the_two_browsing_tools(self) -> None:
        self.assertEqual(disallowed_tools_for("off"), ("WebSearch", "WebFetch"))
        self.assertTrue(disallowed_tools_for("off"))

    def test_every_other_mode_denies_nothing(self) -> None:
        for mode in WEB_SEARCH_MODE_CHOICES:
            if mode == "off":
                continue
            with self.subTest(mode=mode):
                self.assertEqual(disallowed_tools_for(mode), ())

    def test_an_unknown_mode_denies_nothing_rather_than_guessing(self) -> None:
        self.assertEqual(disallowed_tools_for("sideways"), ())

    def test_bash_is_not_denied_and_the_docstring_says_why(self) -> None:
        """The honest limit of this flag, pinned so it cannot be quietly overstated.

        Denying `Bash` would not produce a no-browsing run, it would produce no run: the
        stages write files and execute scripts through it. `curl` is inside it, so this
        narrows the path to the network rather than closing it, and that sentence is part
        of the contract rather than a caveat someone may drop.
        """
        self.assertNotIn("Bash", NO_BROWSING_DISALLOWED_TOOLS)
        doc = " ".join((disallowed_tools_for.__doc__ or "").split())
        self.assertIn("narrows the hole; it does not close it", doc)
        self.assertNotIn("impossible", doc)


class TheDisallowFlagReachesTheClaudeCommandTest(unittest.TestCase):
    """Rendered when tools are denied, absent when they are not. Both directions.

    The flag spelling was read off the installed binary: `claude --version` reports
    2.1.229 (Claude Code) and `claude --help` lists
    ``--disallowedTools, --disallowed-tools <tools...>``. A flag invented from memory is
    a silent no-op, and a silent no-op here reads as a protocol that was enforced.
    """

    def _operator(self, **kwargs):
        from src.operator import ClaudeOperator

        return ClaudeOperator(**kwargs)

    def _paths(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        paths = build_run_paths(Path(tmp.name) / "run")
        ensure_run_layout(paths)
        return paths

    def test_the_flag_is_rendered_when_tools_are_passed(self) -> None:
        paths = self._paths()
        command = self._operator()._build_cli_command(
            paths.prompt_cache_dir / "p.md",
            "sid",
            resume=False,
            disallowed_tools=("WebSearch", "WebFetch"),
        )
        self.assertIn("--disallowed-tools", command)
        self.assertEqual(
            command[command.index("--disallowed-tools") + 1], "WebSearch,WebFetch"
        )

    def test_the_flag_is_absent_when_nothing_is_denied(self) -> None:
        paths = self._paths()
        for denied in (None, ()):
            with self.subTest(denied=denied):
                command = self._operator()._build_cli_command(
                    paths.prompt_cache_dir / "p.md",
                    "sid",
                    resume=False,
                    disallowed_tools=denied,
                )
                self.assertNotIn("--disallowed-tools", command)

    def test_the_default_command_is_unchanged(self) -> None:
        """Every existing caller passes nothing, and must produce what it produced before."""
        paths = self._paths()
        command = self._operator()._build_cli_command(
            paths.prompt_cache_dir / "p.md", "sid", resume=False
        )
        self.assertNotIn("--disallowed-tools", command)
        self.assertEqual(command[:2], ["claude", "--model"])

    def test_the_denied_list_is_one_argument_not_several(self) -> None:
        """The CLI declares the option variadic, so a second bare word after it would be
        read as a third tool name and the option would swallow whatever came next."""
        paths = self._paths()
        command = self._operator()._build_cli_command(
            paths.prompt_cache_dir / "p.md",
            "sid",
            resume=False,
            disallowed_tools=("WebSearch", "WebFetch"),
        )
        after = command[command.index("--disallowed-tools") + 2]
        self.assertTrue(after.startswith("-"), after)

    def test_the_operators_own_setting_reaches_the_command(self) -> None:
        """A parameter no constructor can fill is a parameter no run can use."""
        paths = self._paths()
        operator = self._operator(disallowed_tools=("WebSearch", "WebFetch"))
        command, _, _ = operator._prepare_invocation(
            paths.prompt_cache_dir / "p.md", "sid", paths=paths, resume=False
        )
        self.assertIn("--disallowed-tools", command)

    def test_an_operator_built_the_old_way_denies_nothing(self) -> None:
        """Control for the one above, and the RCB regression: every existing construction
        omits the argument and must keep the command line it had."""
        paths = self._paths()
        command, _, _ = self._operator()._prepare_invocation(
            paths.prompt_cache_dir / "p.md", "sid", paths=paths, resume=False
        )
        self.assertNotIn("--disallowed-tools", command)


class TheFrontEndsWireTheModeToTheToolListTest(unittest.TestCase):
    """`--web-search off` and a browsing tool in the tool list is the flag lying."""

    def _claude_operator(self, factory, mode: str, **extra):
        from src.terminal_ui import TerminalUI
        from src.web_search import disallowed_tools_for as helper

        return factory(
            "claude",
            model="sonnet",
            codex_sandbox="workspace-write",
            fake_mode=True,
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
            stage_timeout=60,
            disallowed_tools=helper(mode),
            **extra,
        )

    def test_main_denies_the_browsing_tools_under_off(self) -> None:
        operator = self._claude_operator(autor_main.create_operator, "off")
        self.assertEqual(operator.disallowed_tools, ("WebSearch", "WebFetch"))

    def test_main_denies_nothing_under_the_default_mode(self) -> None:
        operator = self._claude_operator(autor_main.create_operator, "auto")
        self.assertEqual(operator.disallowed_tools, ())

    def test_the_rcb_agent_denies_the_browsing_tools_under_off(self) -> None:
        operator = self._claude_operator(rcb_agent.create_operator, "off")
        self.assertEqual(operator.disallowed_tools, ("WebSearch", "WebFetch"))

    def test_the_rcb_agent_denies_nothing_under_the_default_mode(self) -> None:
        operator = self._claude_operator(rcb_agent.create_operator, "auto")
        self.assertEqual(operator.disallowed_tools, ())


class EveryOperatorTheFrontEndsBuildIsToldWhatToDenyTest(unittest.TestCase):
    """The call sites, not the string. A substring check here missed two live defects.

    The tests above build the operator the way the front end does, so they pass on a
    `main()` that passes nothing. The guard that replaced them was
    ``assertIn("disallowed_tools=disallowed_tools_for(", source)`` over each file's text,
    and a file with two occurrences answers it with one: deleting the fresh-run wiring --
    the line every ordinary ``python main.py --web-search off`` executes -- left the whole
    suite green on the strength of the `--resume-run` branch's surviving copy. It also
    could not see `configure_effort`, which built the routine-tier operator with no
    denied tools at all, so a run with `--effort-tiers --routine-model` kept `WebSearch`
    and `WebFetch` on every stage routed to the cheap tier.

    Reading the calls instead of the file text answers both, and answers them for a call
    site that does not exist yet.
    """

    #: The `create_operator` calls each front end makes today. Pinned, because the
    #: assertion below is a loop over whatever the walk returns and an empty walk passes
    #: it silently -- a renamed function, a call moved behind a factory, a mistake in the
    #: matcher. main.py builds three (the `--resume-run` branch's operator, the fresh
    #: branch's, and the routine-tier one in `configure_effort`); rcb_agent.py builds two
    #: (its own and its routine-tier one). A number that moves here is a call site added
    #: or removed, which is exactly the event that should make someone look.
    CALL_SITES = {"main.py": 3, "rcb_agent.py": 2}

    @staticmethod
    def _create_operator_calls(path: Path) -> list:
        """Every `create_operator(...)` in one file, as AST call nodes."""
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        calls = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.id if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute)
                else ""
            )
            if name == "create_operator":
                calls.append(node)
        return calls

    def test_every_call_site_passes_a_denied_tool_list(self) -> None:
        for name in self.CALL_SITES:
            for call in self._create_operator_calls(REPO_ROOT / name):
                with self.subTest(entry_point=name, line=call.lineno):
                    passed = {keyword.arg for keyword in call.keywords}
                    self.assertIn(
                        "disallowed_tools",
                        passed,
                        f"{name}:{call.lineno} builds an operator without saying what to "
                        f"deny, so `--web-search off` does not reach it",
                    )

    def test_the_walk_finds_the_whole_population_of_call_sites(self) -> None:
        """Control. Without it the assertion above passes on a walk that finds nothing."""
        found = {
            name: len(self._create_operator_calls(REPO_ROOT / name))
            for name in self.CALL_SITES
        }
        self.assertEqual(found, self.CALL_SITES)

    def test_the_walk_can_tell_a_call_that_denies_nothing(self) -> None:
        """Control for the control: the matcher answers `no` on source that omits it.

        The population count and the keyword check are both read off the same walk, so
        a matcher that returned `disallowed_tools` for every call would satisfy the test
        above and hold nothing. This drives it over a file that has one of each.
        """
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "sample.py"
            sample.write_text(
                "create_operator('claude', disallowed_tools=())\n"
                "create_operator('claude')\n",
                encoding="utf-8",
            )
            calls = self._create_operator_calls(sample)
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            [{keyword.arg for keyword in call.keywords} for call in calls],
            [{"disallowed_tools"}, set()],
        )


class TheRoutineTierIsUnderTheSameProtocolTest(unittest.TestCase):
    """`--effort-tiers --routine-model X` runs whole stages on a second operator.

    It was built with no denied tools, so under `--web-search off` every stage the
    effort plan routed to the cheap tier kept `WebSearch` and `WebFetch` -- a protocol
    that held for some of the run, decided by which stages the tiering happened to send
    where, and recorded nowhere. `rcb_agent.py`'s equivalent construction already passed
    the list, so the two front ends disagreed about what the same flag meant.
    """

    def _manager_with_a_routine_tier(self, mode: str):
        from types import SimpleNamespace

        from src.terminal_ui import TerminalUI

        manager = SimpleNamespace(
            operator=SimpleNamespace(backend_name="claude"),
            concentration=SimpleNamespace(routine_model=None),
            reviewer=None,
            routine_operator=None,
        )
        args = SimpleNamespace(
            rigor="", effort_tiers=True, routine_model="haiku", codex_sandbox=None
        )
        autor_main.configure_effort(
            manager,
            args,
            backend_name="claude",
            model="opus",
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
            fake_mode=True,
            stage_timeout=60,
            web_search_mode=mode,
        )
        return manager

    def test_the_routine_operator_is_denied_the_browsing_tools_under_off(self) -> None:
        manager = self._manager_with_a_routine_tier("off")
        self.assertEqual(manager.routine_operator.disallowed_tools, ("WebSearch", "WebFetch"))

    def test_the_routine_operator_is_denied_nothing_under_the_default_mode(self) -> None:
        """Control: the tier is not simply always denied."""
        manager = self._manager_with_a_routine_tier("auto")
        self.assertEqual(manager.routine_operator.disallowed_tools, ())


class TheBenchmarkFrontEndSkipsTheProbeUnderOffTest(unittest.TestCase):
    """`main.py` has this test already; `rcb_agent.py` had the same code and none.

    The two copies of the conditional are two lines apiece and read the same literal, and
    the copy on the benchmark path was asserted only in the pull request's prose --
    reverting it to the eager call left the whole suite green. This drives `rcb_agent.run`
    as far as the notice and stops it there.

    The conditional is deliberately still written out in both front ends rather than
    factored into `src.web_search`: the probe is reached through each front end's own
    module global, which is the seam `main.assess_search_readiness` patches in four
    existing tests and which `test_the_rcb_adapter_resolves_the_same_way` pins by
    identity. Moving the call would relocate that seam to buy the removal of one
    two-line ternary, and both copies are now covered from the outside anyway.
    """

    class _Stop(BaseException):
        """Abort `run()` just past the notice; the pipeline is not the question."""

    def _run_to_the_notice(self, mode: str):
        with tempfile.TemporaryDirectory() as tmp:
            args = rcb_agent.parse_args(
                ["--workspace", tmp, "--web-search", mode, "--fake-operator"]
            )
            with patch("rcb_agent.assess_search_readiness") as probe, \
                 patch("rcb_agent.resolve_web_search_context", side_effect=self._Stop), \
                 patch("rcb_agent.emit_event"):
                probe.return_value.hard_blocker = None
                probe.return_value.blocker = None
                probe.return_value.backend.describe.return_value = "a backend"
                # `run` builds its own non-interactive UI on stdout; the notice it prints
                # is the thing under test, not something the suite's log needs.
                try:
                    with redirect_stdout(io.StringIO()):
                        rcb_agent.run(args)
                except self._Stop:
                    pass
        return probe

    def test_the_benchmark_front_end_does_not_probe_under_off(self) -> None:
        self._run_to_the_notice("off").assert_not_called()

    def test_the_benchmark_front_end_still_probes_under_auto(self) -> None:
        """Control. `--web-search gemini` is refused on a hard blocker and that refusal
        reads the probe, so a front end that stopped probing at all would take the
        benchmark's own refusal with it."""
        self._run_to_the_notice("auto").assert_called_once()


if __name__ == "__main__":
    unittest.main()
