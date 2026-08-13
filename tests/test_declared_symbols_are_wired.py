"""A symbol can be declared, tested, documented, and reached by nothing.

``tests/test_cli_flags_are_read.py`` gates one shape of this: a flag argparse accepts and no
line reads. The same hole is open one level down, and it has cost more. ``propose_exploration``
was declared on ``Archive``, unit-tested, and named in that module's docstring while no
production line called it, so the exploration half of the learning loop was shut;
``tools/archive_sample_complexity.py`` crashed on its first record while the test guarding
it stayed green, because that test only checked the file mentioned the right symbol names
(``tests/test_archive_exploration_wiring.py`` says so). ``AutomatedReviewer.parse_decision``
still says "panel members parse the same decision grammar" and ``src/review_panel.py`` does
not call it. ``src/information_flow.py`` still opens with "**The graph is inspectable.**
``dependency_edges()`` returns the producer -> consumer pairs, so the information topology
can be printed, tested, and diffed", ``README.md`` repeats the claim, and nothing calls
``dependency_edges``: the sentence is true of the function and false of the product.

None of those was found by the suite. All of them were found by reading, one at a time.

What this gate refuses
----------------------
A public symbol defined under ``src/`` that no line of production code references. Every
one is wired, deleted, or listed in :data:`ALLOWLIST` with a written reason.

The reference roots are :data:`ENTRY_POINTS` plus every module under ``src/`` -- every
place the product actually starts from, including ``studio.py``, without which the whole
``src/backend/`` package would read as dead.

``tests/`` and ``tools/`` are deliberately *not* roots. A test is the thing that keeps a
dead symbol green -- twenty-one of the thirty-one symbols listed below have one -- so
counting a test as wiring would make the gate assert nothing. An instrument is not evidence:
``archive_sample_complexity`` was importing ``RunRecord`` and crashing on it at the same
time. A symbol that only ``tools/`` reaches is still exempt, but by a line somebody wrote,
and :attr:`Exempt.reached_from` makes that line checkable.

Why a flat reference check, and what it costs
---------------------------------------------
This does not build a call graph. It asks one question per symbol: does its name appear, as
an identifier, anywhere in production outside its own definition? Reachability from an
entry point is the interesting question and the wrong one to automate here -- it needs a
resolver for imports, aliases, methods, duck typing and callbacks, and each gap in the
resolver is a false accusation against working code.

The price is false negatives, and here is a measured one. ``format_manifest_status`` has
exactly one call site in the tree, inside ``ResearchManager.describe_run_status``, which
this gate flags as unreferenced because nothing calls *it*. So no entry point reaches
either. The flat check flags only the second, because the first has a reference and a
reference is what it measures. That is the trade made here on purpose: under-report rather
than accuse.

Measured precision, the day this landed
---------------------------------------
1108 public definitions over 1008 distinct names in ``src/``; 32 referenced by nothing
outside ``tests/`` and ``tools/``. All 32 were then checked by hand against every textual
occurrence of the name in ``main.py``, ``studio.py``, ``rcb_agent.py`` and ``src/``: each
has exactly one executable occurrence, its own definition, and every other hit is a
docstring or a comment. **False-positive rate 0/32.** One of the 32 -- ``DATA_DIRNAME`` --
had a one-line wiring fix and got it, which is why the list below has 31 entries.

Re-derive all of that, including the occurrence-by-occurrence evidence behind the
false-positive rate::

    python3 -m tests.test_declared_symbols_are_wired --census

The population figures drift as the tree grows; the census is the instrument, and
:meth:`AllowlistIsHonestTests.test_the_allowlist_is_exactly_what_the_scan_finds` is what
keeps the 31 honest.
"""

from __future__ import annotations

import ast
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parent.parent

#: Where the product starts, alongside every module under ``src/``.
#:
#: ``studio.py`` is a two-line launcher and is here because it is the only thing that
#: reaches ``src/backend/``; without it that package reads as dead. ``rcb_agent.py`` is here
#: because the benchmark front end has diverged from ``main.py`` before -- that divergence
#: is what ``tests/test_cli_flags_are_read.py`` exists for.
ENTRY_POINTS = ("main.py", "studio.py", "rcb_agent.py")

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


class Exempt(NamedTuple):
    """Why a declared symbol is allowed to have no production reference.

    *reason* has to say what wiring it would take, because the next reader's question is
    never "is this dead" -- the gate already answered that -- it is "what would I have to
    decide to bring it back".

    *reached_from* names files outside the reference roots that do use the symbol. It is
    not decoration: :meth:`AllowlistIsHonestTests.test_a_named_consumer_really_consumes_it`
    reads each named file and fails if the symbol is not in it, so "reached only from
    ``tools/rcb_trial.py``" stops being true the moment the driver stops importing it.
    """

    reason: str
    reached_from: tuple[str, ...] = ()


#: Shared by the ``src/rcb_trial.py`` symbols the paired-trial driver imports. They are one
#: decision, not six, and writing it six times would invite six different edits to it.
_DRIVER_ONLY = (
    "Reached only from `tools/rcb_trial.py`, the shipped paired-trial driver, which this "
    "gate does not count as a reference root: `tools/archive_sample_complexity.py` was "
    "importing `RunRecord` and crashing on it at the same time, so being imported by an "
    "instrument is not evidence a symbol still works. Nothing a run executes touches this. "
    "Wiring it means moving the driver's decision logic into the run, the opposite of what "
    "the seam is for; the honest alternative is to leave it here and check the claim, "
    "which `reached_from` does."
)

#: The symbols this repository knowingly declares and does not reach, each with the reason.
#:
#: Keyed ``<path>::<name>`` and matched exactly, so an entry has to be a decision somebody
#: wrote down rather than a prefix that quietly grew to cover its neighbours. Seeded from
#: the census described in this module's docstring.
ALLOWLIST: dict[str, Exempt] = {
    # -- declared for an instrument, not for a run ---------------------------------------
    "src/rcb_trial.py::collect_rcb_pairs": Exempt(_DRIVER_ONLY, ("tools/rcb_trial.py",)),
    "src/rcb_trial.py::count_quota_hits": Exempt(_DRIVER_ONLY, ("tools/rcb_trial.py",)),
    "src/rcb_trial.py::driver_clause": Exempt(_DRIVER_ONLY, ("tools/rcb_trial.py",)),
    "src/rcb_trial.py::format_rcb_trial_report": Exempt(_DRIVER_ONLY, ("tools/rcb_trial.py",)),
    "src/rcb_trial.py::items_from_score_payloads": Exempt(_DRIVER_ONLY, ("tools/rcb_trial.py",)),
    "src/rcb_trial.py::next_action": Exempt(_DRIVER_ONLY, ("tools/rcb_trial.py",)),
    # -- a prompt renderer with no channel to render into --------------------------------
    "src/experimental_protocol.py::format_protocol_for_prompt": Exempt(
        "A stage prompt is assembled from `information_flow.CHANNELS`, so a renderer "
        "reaches a stage only by becoming a channel. Adding one moves `CHANNELS`, the "
        "mermaid dotted-edge count, and the spelled-out counts `tests/test_doc_counts.py` "
        "pins in README.md and docs/architecture.md. That is a channel change with its own "
        "argument to make -- which stage consumes it and why the narrowing is right -- not "
        "a missing reference."
    ),
    "src/run_skills.py::format_skills_for_prompt": Exempt(
        "Same channel problem, plus its input is already dropped: `_install_skills` returns "
        "the installed names and both call sites in `manager.py` discard the return value. "
        "So wiring the renderer means first deciding that a stage should be told which "
        "skills exist -- the pack is pull-based by design, and telling every stage about it "
        "up front is the cost the skill mechanism was built to avoid."
    ),
    # -- a documented claim about a function nothing calls --------------------------------
    "src/information_flow.py::dependency_edges": Exempt(
        "This module's own docstring says 'The graph is inspectable. `dependency_edges()` "
        "returns the producer -> consumer pairs, so the information topology can be "
        "printed, tested, and diffed', and README.md repeats the claim. Both are true of "
        "the function and false of the product: only `test_information_flow.py` calls it, "
        "so the topology is tested and never printed. Wiring means giving the inspection an "
        "output -- a CLI subcommand or a run artifact -- which is a new surface."
    ),
    "src/stage_graph.py::admissible_moves": Exempt(
        "This module's docstring says '`admissible_moves` withdraws a revisit whose "
        "justification has not changed', and nothing calls it. It is a one-line filter over "
        "`moves()`, and that filter is written inline at five other sites instead -- two in "
        "`stage_graph.py`, three in `router.py`. The fix is to delete it and correct the "
        "docstring, or to make the five sites call it; either way `StageGraph` is the "
        "graph's public surface and the choice belongs with the people editing it."
    ),
    "src/approval_agent.py::parse_decision": Exempt(
        "Its docstring calls it a 'Public alias: panel members parse the same decision "
        "grammar'. The panel members do not use it: `review_panel.py` calls "
        "`parse_with_retry` at both of its sites, which is the path that re-asks before it "
        "gives up, and going through the bare alias is the bug that path was split out to "
        "fix. So the alias is a public method describing a collaboration that stopped "
        "happening. Deleting it removes a documented `AutomatedReviewer` method."
    ),
    "src/run_skills.py::validate_skill_pack": Exempt(
        "docs/development.md says '`validate_skill_pack` is what defines well-formed'. "
        "`read_skill_pack` defines it instead, with its own inline frontmatter check, and "
        "silently skips what it rejects. Two encodings of one rule. Wiring means having "
        "`read_skill_pack` refuse through the validator, which changes what installs and "
        "needs a decision about whether a malformed skill should stop a run."
    ),
    # -- a writer with no writer, a reader with no reader ---------------------------------
    "src/bootstrap.py::save_bootstrap_result": Exempt(
        "docs/run-artifacts.md already says of `corpus_manifest.json` that it is a file "
        "'which no live code path writes -- `save_bootstrap_result` is its only writer and "
        "nothing outside the tests calls it', and that the bootstrap gate refuses on it "
        "anyway. The documentation admitted the gap and nothing gated it. Closing it is the "
        "bootstrap-artifact question, not a reference."
    ),
    "src/bootstrap.py::load_corpus_manifest": Exempt(
        "The reader for the file `save_bootstrap_result` never writes. `scan_corpus` builds "
        "a `CorpusManifest` in memory at `manager.py` and nothing persists it, so there is "
        "nothing on disk for this to load. It goes when its writer goes."
    ),
    "src/backend/sessions.py::append_event": Exempt(
        "The session log's only writer, and nothing writes. Studio reads stage sessions "
        "through `parse_real_session`, which parses the operator CLI's own JSONL, so the "
        "AutoR-authored half of the log has a format, a lock and no events. Wiring means "
        "choosing which manager events belong in a session view -- a product decision about "
        "the Studio, made in the Studio."
    ),
    # -- a convenience wrapper its callers inline instead ---------------------------------
    "src/artifact_index.py::ensure_artifact_index": Exempt(
        "The caching variant of `write_artifact_index`. Both live callers -- "
        "`information_flow._artifact_index` and `writing_manifest.build_writing_manifest` -- "
        "call the rewriting one, and they are right to: an index served from cache during a "
        "run would describe a workspace that has since changed. Wiring this is a freshness "
        "decision, and the current answer is 'never'."
    ),
    "src/web_search.py::resolve_source_url": Exempt(
        "A one-line projection of `resolve_source`, dropping the page title. Every "
        "production caller wants the title, so the projection has no user. Deletion "
        "candidate; `src/web_search.py` is live search plumbing and a gate is not where that "
        "edit belongs."
    ),
    "src/review_policy.py::rules_from": Exempt(
        "Filters `ReviewPolicy.rules` by source. `manager.py` imports `load_policy`, "
        "`policy_summary` and `record_correction`; `approval_agent.py` imports "
        "`format_policy_for_prompt` and `load_policy`. Nothing asks for a subset, and no "
        "test does either -- it is referenced nowhere in the tree. Deletion candidate."
    ),
    "src/rcb_trial.py::clause_by_name": Exempt(
        "Referenced nowhere in the tree at all: not production, not `tools/`, not a test. "
        "`admit_arm` already returns the failed clause *names* and every reader works from "
        "that list, so the lookup has no caller and no coverage. Deletion candidate, held "
        "back only because `src/rcb_trial.py` is under concurrent edit."
    ),
    "src/research_rounds.py::current_round_number": Exempt(
        "`latest_round` is what the manager reads. The 1-based counter beside it is read "
        "only by `test_research_rounds.py`, and `_close_round` recomputes its body inline as "
        "`len(load_rounds(paths))`. One expression written twice; collapsing them is a "
        "refactor of the round bookkeeping."
    ),
    "src/writing_manifest.py::scan_figures": Exempt(
        "Superseded by the artifact index: `build_writing_manifest` fills `figures` from "
        "`indexed_artifacts_for_category`. The two return different shapes -- "
        "`filename`/`rel_path`/`size_bytes` here against the index's records -- so putting "
        "this back is a manifest schema change, not a reference."
    ),
    "src/writing_manifest.py::scan_results": Exempt(
        "Superseded by the artifact index in the same way as `scan_figures`, and with less "
        "claim on life: no test calls this one either."
    ),
    "src/intake.py::build_intake_from_goal": Exempt(
        "Labelled a convenience builder for `--skip-intake` backward compatibility. The "
        "non-interactive path constructs `IntakeContext(goal=..., original_goal=...)` inline "
        "in `manager.py` instead. One line each way; replacing the construction is safe but "
        "belongs to whoever owns the intake path, not to a gate."
    ),
    "src/intake.py::build_intake_from_resources": Exempt(
        "The same label, but not interchangeable with what `manager.py` does: this takes raw "
        "path strings and classifies them, while the live site already holds ingested "
        "`ResourceEntry` objects. Wiring it means moving classification earlier in the "
        "intake flow."
    ),
    # -- a method no surface exposes ------------------------------------------------------
    "src/manager.py::describe_run_status": Exempt(
        "A public `ResearchManager` method with no caller anywhere in the tree, not even a "
        "test -- and it is the only caller of `format_manifest_status`, which is why that "
        "function is not flagged here (see this module's docstring). Wiring means giving a "
        "front end a `--status` path; deleting means removing a manager method and its "
        "formatter together. `src/manager.py` is the largest module in the tree and is under "
        "concurrent edit, so a gate-only change is the wrong place to decide."
    ),
    "src/backend/studio_runner.py::is_active": Exempt(
        "A liveness query on `StudioRunner` that the HTTP layer never asks. "
        "`backend/studio_http.py` routes to `StudioService`, and the service reads run state "
        "from the manifest rather than from the thread. Wiring means adding a route and "
        "deciding which of the two answers is authoritative when they disagree."
    ),
    "src/terminal_ui.py::show_intake_summary": Exempt(
        "A panel renderer on `TerminalUI` with no caller; the interactive intake session "
        "prints its own summary through `panel()` directly. Wiring means choosing where in "
        "the intake flow it belongs, which is a terminal-UX decision."
    ),
    # -- a constant nothing consults ------------------------------------------------------
    "src/rigor.py::FEATURE_NOTES": Exempt(
        "Its own comment says it exists 'so `--rigor --help` can say more than a list', and "
        "`help_text()` never reads it. The only thing that touches it is a test asserting "
        "its keys match `feature_flags()` -- which is exactly how a dead table stays green. "
        "Wiring it means deciding how much of the note text belongs in an argparse help "
        "string on two front ends: a layout decision, not a reference."
    ),
    "src/utils.py::OUTPUT_FORMAT_CHOICES": Exempt(
        "The canonical pair. Both front ends advertise `OUTPUT_FORMAT_CLI_CHOICES` and every "
        "caller resolves through `_OUTPUT_FORMAT_ALIASES`, so nothing consults the canonical "
        "tuple at run time. Wiring it means making `resolve_output_format` assert its answer "
        "is a member, which turns an alias-table typo from a silent fall back to "
        "`DEFAULT_OUTPUT_FORMAT` into a raise -- a behaviour change."
    ),
    "src/research_rounds.py::ROUND_FIRST_STAGE_NUMBER": Exempt(
        "`ROUND_CLOSING_STAGE_NUMBER` is read by `manager.py` and by this module; its "
        "opening counterpart is read by nothing. A round's entry point is chosen by slug "
        "through `DECISION_ENTRY_STAGE`, so the number and the slug table are the same fact "
        "twice and wiring the constant means deciding which one is authoritative."
    ),
    # -- correct in itself, unreachable in this tree ---------------------------------------
    "src/inference.py::paired_floor": Exempt(
        "docs/architecture.md lists it beside `unpaired_floor`, which is wired through "
        "`minimum_arms_for` into the archive's minimum-observation rule. The paired floor "
        "has no caller because no comparison in the tree is paired: `unpaired_permutation` "
        "is the only test statistic `src/` runs. It is the arithmetic a paired trial would "
        "need and there is no paired trial."
    ),
}


class Definition(NamedTuple):
    """One public symbol declared under ``src/``."""

    name: str
    module: str
    lineno: int
    node: ast.AST

    @property
    def key(self) -> str:
        return f"{self.module}::{self.name}"


class Scan(NamedTuple):
    definitions: tuple[Definition, ...]
    unreferenced: tuple[Definition, ...]


def production_files(root: Path = REPO) -> list[Path]:
    """The reference roots: the entry points plus every module under ``src/``."""
    entries = [root / name for name in ENTRY_POINTS if (root / name).is_file()]
    return entries + sorted((root / "src").rglob("*.py"))


def public_definitions(module: str, tree: ast.Module) -> list[Definition]:
    """Public top-level functions, classes and constants, plus public methods of them.

    Methods are in scope because the instance that motivated this gate was one:
    ``Archive.propose_exploration``. Members of a private class are not -- ``_StudioTerminalUI``
    is not a public symbol, so neither is anything hanging off it.

    Constants are restricted to SCREAMING_CASE. A module-level lowercase binding is usually
    a singleton or a re-export, and the two read very differently to whoever has to decide
    what an unreferenced one means.
    """
    found: list[Definition] = []
    for node in tree.body:
        if isinstance(node, _FUNCTIONS + (ast.ClassDef,)):
            if node.name.startswith("_"):
                continue
            found.append(Definition(node.name, module, node.lineno, node))
            if isinstance(node, ast.ClassDef):
                for member in node.body:
                    if isinstance(member, _FUNCTIONS) and not member.name.startswith("_"):
                        found.append(Definition(member.name, module, member.lineno, member))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id.isupper() and not target.id.startswith("_"):
                    found.append(Definition(target.id, module, node.lineno, node))
    return found


def names_used(node: ast.AST) -> set[str]:
    """Every identifier this node *uses*.

    By AST, not by regex over the text, because a name in a comment or a docstring is a
    mention and not a reference. The repository has already paid for that difference: the
    first version of ``test_archive_exploration_wiring.py`` searched for the string
    ``propose_exploration`` and was satisfied by the explanatory comment beside the call, so
    deleting the call left it green. Two symbols here -- ``collect_rcb_pairs`` and
    ``dependency_edges`` -- are named in prose inside ``src/`` and nowhere else, and a
    text scan reports both as wired.

    A string literal counts only when the whole literal is an identifier. That is what keeps
    ``getattr(obj, "name")``, ``__all__`` and registry keys reachable without letting the
    docstring back in.
    """
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
        elif isinstance(child, ast.alias):
            names.add(child.name.split(".")[0])
            names.add(child.name)
            if child.asname:
                names.add(child.asname)
        elif isinstance(child, ast.keyword) and child.arg:
            names.add(child.arg)
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            if child.value.isidentifier():
                names.add(child.value)
    return names


def reference_units(tree: ast.Module) -> list[tuple[ast.AST, set[str]]]:
    """One entry per place a reference can live, so a definition can be excluded from itself.

    A class is split into its header -- decorators, bases, keywords -- and one entry per
    member. That split is what lets a method calling a sibling count as a reference to the
    sibling, while a class naming itself anywhere inside its own body does not count as a
    reference to the class. Without it, recursion and self-typing would each be enough to
    keep a dead symbol alive.
    """
    units: list[tuple[ast.AST, set[str]]] = []
    for statement in tree.body:
        if isinstance(statement, ast.ClassDef):
            header: set[str] = set()
            for part in list(statement.decorator_list) + list(statement.bases) + list(statement.keywords):
                header |= names_used(part)
            units.append((statement, header))
            units.extend((member, names_used(member)) for member in statement.body)
        else:
            units.append((statement, names_used(statement)))
    return units


def scan(root: Path = REPO) -> Scan:
    """Every public definition under ``src/``, and the ones production never names."""
    files = production_files(root)
    trees = {path: ast.parse(path.read_text(encoding="utf-8")) for path in files}
    src_root = root / "src"

    definitions: list[Definition] = []
    for path in files:
        if path.is_relative_to(src_root):
            definitions.extend(public_definitions(path.relative_to(root).as_posix(), trees[path]))

    mentions: dict[str, set[int]] = {}
    for path in files:
        for node, names in reference_units(trees[path]):
            for name in names:
                mentions.setdefault(name, set()).add(id(node))

    # Keyed on the name, not the definition: when two modules declare the same name, a
    # mention inside either one's body is self-reference, and neither should rescue the
    # other. The stricter direction on purpose -- it can only add candidates for review.
    own: dict[str, set[int]] = {}
    for definition in definitions:
        own.setdefault(definition.name, set()).update(id(n) for n in ast.walk(definition.node))

    unreferenced = tuple(
        definition
        for definition in definitions
        if not (mentions.get(definition.name, set()) - own[definition.name])
    )
    return Scan(tuple(definitions), unreferenced)


def census(root: Path = REPO) -> str:
    """The measurement behind this module's docstring, with its evidence.

    For each unreferenced symbol it prints every textual occurrence of the name across the
    reference roots. That is what makes the false-positive claim checkable rather than
    asserted: a reader confirms line by line that the only executable occurrence is the
    definition and the rest are prose.
    """
    result = scan(root)
    distinct = {definition.name for definition in result.definitions}
    lines = [
        f"{len(result.definitions)} public definitions over {len(distinct)} distinct names in src/",
        f"{len(result.unreferenced)} referenced by nothing outside tests/ and tools/",
        f"{len(ALLOWLIST)} allowlisted",
        "",
    ]
    sources = {path: path.read_text(encoding="utf-8").splitlines() for path in production_files(root)}
    for definition in sorted(result.unreferenced, key=lambda item: item.key):
        exempt = ALLOWLIST.get(definition.key)
        lines.append(f"{definition.key}:{definition.lineno}" + ("" if exempt else "   [NOT ALLOWLISTED]"))
        pattern = re.compile(rf"\b{re.escape(definition.name)}\b")
        for path, text in sources.items():
            for number, line in enumerate(text, 1):
                if pattern.search(line):
                    lines.append(f"    {path.relative_to(root).as_posix()}:{number}: {line.strip()}")
        if exempt and exempt.reached_from:
            lines.append(f"    reached from: {', '.join(exempt.reached_from)}")
        lines.append("")
    return "\n".join(lines)


class AllowlistIsHonestTests(unittest.TestCase):
    """The gate itself: the scan and the written record have to agree, both ways."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.result = scan()

    def test_the_allowlist_is_exactly_what_the_scan_finds(self) -> None:
        found = {definition.key for definition in self.result.unreferenced}
        missing = sorted(found - set(ALLOWLIST))
        self.assertEqual(
            missing,
            [],
            "these public symbols in src/ are referenced by nothing outside tests/ and "
            "tools/. Wire one, delete it, or add it to ALLOWLIST with a reason that says "
            f"what wiring it would take: {missing}",
        )

    def test_no_exemption_names_a_symbol_that_is_gone(self) -> None:
        """An allowlist entry for a deleted symbol is a lie the next reader inherits."""
        declared = {definition.key for definition in self.result.definitions}
        stale = sorted(set(ALLOWLIST) - declared)
        self.assertEqual(
            stale,
            [],
            f"ALLOWLIST names symbols that src/ no longer declares; drop them: {stale}",
        )

    def test_no_exemption_names_a_symbol_that_is_now_wired(self) -> None:
        """The other half. An exemption that outlives its cause makes the list unreadable."""
        unreferenced = {definition.key for definition in self.result.unreferenced}
        declared = {definition.key for definition in self.result.definitions}
        wired = sorted((set(ALLOWLIST) & declared) - unreferenced)
        self.assertEqual(
            wired,
            [],
            f"these are referenced by production now; drop them from ALLOWLIST: {wired}",
        )

    def test_every_exemption_gives_a_reason(self) -> None:
        for key, exempt in ALLOWLIST.items():
            with self.subTest(symbol=key):
                self.assertGreaterEqual(
                    len(exempt.reason),
                    120,
                    f"{key}: a reason has to say what wiring it would take, not that it is unused",
                )
                self.assertTrue(exempt.reason.endswith("."), f"{key}: the reason is cut off")
                for placeholder in ("TODO", "FIXME", "XXX"):
                    self.assertNotIn(
                        placeholder,
                        exempt.reason,
                        f"{key}: {placeholder} is an intention, not a decision",
                    )
                self.assertNotIn(
                    "?",
                    exempt.reason,
                    f"{key}: a reason that asks a question has not made the decision",
                )

    def test_a_named_consumer_really_consumes_it(self) -> None:
        """`reached_from` is checked, so "only tools/ uses it" cannot rot into a lie."""
        for key, exempt in ALLOWLIST.items():
            symbol = key.split("::", 1)[1]
            pattern = re.compile(rf"\b{re.escape(symbol)}\b")
            for consumer in exempt.reached_from:
                with self.subTest(symbol=key, consumer=consumer):
                    path = REPO / consumer
                    self.assertTrue(path.is_file(), f"{key}: {consumer} does not exist")
                    self.assertRegex(
                        path.read_text(encoding="utf-8"),
                        pattern,
                        f"{key}: {consumer} no longer references it, so the exemption is wrong",
                    )

    def test_every_entry_point_exists(self) -> None:
        """A typo in ENTRY_POINTS would silently drop a reference root and flag live code."""
        for name in ENTRY_POINTS:
            with self.subTest(entry_point=name):
                self.assertTrue((REPO / name).is_file(), f"{name} is not a file")

    def test_the_scan_read_the_real_tree(self) -> None:
        """A parser that quietly found nothing would make every assertion above vacuous."""
        self.assertGreater(
            len(self.result.definitions),
            900,
            "the scan found almost no public symbols in src/; it is not reading the tree",
        )
        self.assertGreater(len(production_files()), 50)


class ScanBehaviourTests(unittest.TestCase):
    """What the scan does, checked on trees this file builds.

    The assertions above pass whether or not the scan works -- an empty result satisfies
    every one of them except the population floor. These pin the rule itself.
    """

    def _tree(self, files: dict[str, str]) -> Path:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        for relative, text in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return root

    def _dead(self, files: dict[str, str]) -> set[str]:
        return {definition.key for definition in scan(self._tree(files)).unreferenced}

    def test_a_symbol_nothing_uses_is_flagged(self) -> None:
        self.assertEqual(
            self._dead({"src/thing.py": "def used():\n    return 1\n\n\ndef orphan():\n    return 2\n",
                        "main.py": "from src.thing import used\n\nprint(used())\n"}),
            {"src/thing.py::orphan"},
        )

    def test_a_symbol_a_sibling_module_calls_is_not_flagged(self) -> None:
        self.assertEqual(
            self._dead({
                "src/a.py": "def helper():\n    return 1\n",
                "src/b.py": "from .a import helper\n\n\ndef entry():\n    return helper()\n",
                "main.py": "from src.b import entry\n\nprint(entry())\n",
            }),
            set(),
        )

    def test_a_mention_in_prose_is_not_a_reference(self) -> None:
        """The lesson `collect_rcb_pairs` and `dependency_edges` teach in the live tree."""
        dead = self._dead({
            "src/thing.py": '"""See :func:`orphan`, which does the work."""\n\n\ndef orphan():\n    # orphan is called from nowhere\n    return 2\n',
            "main.py": "import src.thing\n",
        })
        self.assertEqual(dead, {"src/thing.py::orphan"})

    def test_recursion_does_not_save_a_symbol(self) -> None:
        dead = self._dead({
            "src/thing.py": "def orphan(n):\n    return 1 if n <= 0 else orphan(n - 1)\n",
            "main.py": "import src.thing\n",
        })
        self.assertEqual(dead, {"src/thing.py::orphan"})

    def test_a_class_naming_itself_does_not_save_itself(self) -> None:
        """`main.py` names the method, so only the class name is under test here."""
        dead = self._dead({
            "src/thing.py": "class Orphan:\n    def clone(self) -> \"Orphan\":\n        return Orphan()\n",
            "main.py": "def go(box):\n    return box.clone()\n",
        })
        self.assertEqual(dead, {"src/thing.py::Orphan"})

    def test_recursion_inside_a_method_does_not_save_it(self) -> None:
        """Why :func:`reference_units` splits a class into its members.

        Folded into one unit, the class body's names include everything its methods say
        about themselves, and a method whose only mention of its own name is the recursive
        call reads as called. Found by mutation: collapsing the split survived every other
        test in this class.
        """
        dead = self._dead({
            "src/thing.py": "class Box:\n    def used(self):\n        return 1\n\n    def orphan(self, n):\n        return 1 if n <= 0 else self.orphan(n - 1)\n",
            "main.py": "from src.thing import Box\n\nprint(Box().used())\n",
        })
        self.assertEqual(dead, {"src/thing.py::orphan"})

    def test_a_method_a_sibling_method_calls_is_not_flagged(self) -> None:
        dead = self._dead({
            "src/thing.py": "class Box:\n    def outer(self):\n        return self.inner()\n\n    def inner(self):\n        return 1\n",
            "main.py": "from src.thing import Box\n\nprint(Box().outer())\n",
        })
        self.assertEqual(dead, set())

    def test_a_method_nothing_calls_is_flagged(self) -> None:
        """The shape of `Archive.propose_exploration` before it was wired."""
        dead = self._dead({
            "src/thing.py": "class Box:\n    def used(self):\n        return 1\n\n    def orphan(self):\n        return 2\n",
            "main.py": "from src.thing import Box\n\nprint(Box().used())\n",
        })
        self.assertEqual(dead, {"src/thing.py::orphan"})

    def test_a_private_class_contributes_no_public_methods(self) -> None:
        dead = self._dead({
            "src/thing.py": "class _Hidden:\n    def orphan(self):\n        return 1\n",
            "main.py": "import src.thing\n",
        })
        self.assertEqual(dead, set())

    def test_a_test_or_a_tool_is_not_a_reference(self) -> None:
        dead = self._dead({
            "src/thing.py": "def orphan():\n    return 1\n",
            "main.py": "import src.thing\n",
            "tests/test_thing.py": "from src.thing import orphan\n\nprint(orphan())\n",
            "tools/probe.py": "from src.thing import orphan\n\nprint(orphan())\n",
        })
        self.assertEqual(dead, {"src/thing.py::orphan"})

    def test_a_string_that_is_an_identifier_counts_as_a_reference(self) -> None:
        """Registry and `getattr` wiring is real wiring, and it is invisible to a Name scan."""
        dead = self._dead({
            "src/thing.py": "def orphan():\n    return 1\n",
            "main.py": "import src.thing\n\nprint(getattr(src.thing, \"orphan\")())\n",
        })
        self.assertEqual(dead, set())

    def test_a_screaming_case_constant_is_in_scope(self) -> None:
        dead = self._dead({
            "src/thing.py": "LIVE = 1\nDEAD = 2\n",
            "main.py": "from src.thing import LIVE\n\nprint(LIVE)\n",
        })
        self.assertEqual(dead, {"src/thing.py::DEAD"})

    def test_an_underscore_symbol_is_not_public(self) -> None:
        dead = self._dead({
            "src/thing.py": "_PRIVATE = 1\n\n\ndef _helper():\n    return _PRIVATE\n",
            "main.py": "import src.thing\n",
        })
        self.assertEqual(dead, set())

    def test_the_studio_launcher_is_a_reference_root(self) -> None:
        """Without `studio.py`, every symbol under `src/backend/` would read as dead."""
        dead = self._dead({
            "src/backend/serve.py": "def main():\n    return 0\n",
            "studio.py": "from src.backend.serve import main\n\nraise SystemExit(main())\n",
        })
        self.assertEqual(dead, set())


if __name__ == "__main__":
    if "--census" in sys.argv:
        print(census())
    else:
        unittest.main()
