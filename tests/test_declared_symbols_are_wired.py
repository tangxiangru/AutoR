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
one is wired, deleted, or listed in :data:`ALLOWLIST` with a written reason. Note the
shape of the largest group: a *tool* is not a reference root, so moving a tool's shared
half into ``src/`` -- which is the right thing to do the moment a second tool needs it --
converts every public function in it into an accusation here. That is the gate working,
not the gate misfiring: the code did become reachable from more places and less
reachable from a run, and :data:`_TRIAL_DRIVER_ONLY` is where that trade is written down.

The reference roots are :data:`ENTRY_POINTS` plus every module under ``src/`` -- every
place the product actually starts from, including ``studio.py``, without which the whole
``src/backend/`` package would read as dead.

``tests/`` and ``tools/`` are deliberately *not* roots. A test is the thing that keeps a
dead symbol green -- thirty-eight of the fifty symbols listed below have one -- so
counting a test as wiring would make the gate assert nothing. An instrument is not evidence:
``archive_sample_complexity`` was importing ``RunRecord`` and crashing on it at the same
time. A symbol that only ``tools/`` reaches is still exempt, but by a line somebody wrote,
and :attr:`Exempt.reached_from` makes that line checkable.

That thirty-eight is :func:`allowlisted_symbols_with_a_test`, printed by the census and pinned
against this sentence by
:meth:`AllowlistIsHonestTests.test_the_stated_count_of_tested_symbols_is_the_measured_one`,
because two earlier versions of the sentence were wrong: it said twenty-one when the
measurement said twenty, and then twenty when the measurement had moved to twenty-one.
Neither could be contradicted by anything in the file.

Why a flat reference check, and what it costs
---------------------------------------------
This does not build a call graph. It asks one question per symbol: does its name appear, as
an identifier, anywhere in production outside its own definition? Reachability from an
entry point is the interesting question and the wrong one to automate here -- it needs a
resolver for imports, aliases, methods, duck typing and callbacks, and each gap in the
resolver is a false accusation against working code.

The price is mostly false negatives, and here is a measured one. ``format_manifest_status``
has exactly one call site in the tree, inside ``ResearchManager.describe_run_status``, which
this gate flags as unreferenced because nothing calls *it*. So no entry point reaches
either. The flat check flags only the second, because the first has a reference and a
reference is what it measures. That is the trade made here on purpose: under-report rather
than accuse.

There is one false-positive shape it will hit, and it is a matter of time rather than of
luck: a method a *framework* dispatches by name is referenced by nobody in this tree.
``src/backend/studio_http.py`` subclasses ``BaseHTTPRequestHandler``, and its ``do_GET`` is
invisible to this gate only because ``StudioHandler`` is nested inside ``build_handler``
and :func:`public_definitions` walks ``tree.body``. Hoist that class to module level and
the gate accuses ``do_GET``.
:meth:`ScanBehaviourTests.test_a_framework_dispatched_method_is_a_known_false_positive`
pins the shape so the next reader meets it as a measured cost rather than as a surprise;
the answer, when it happens, is an allowlist entry naming the framework that calls it.

Measured precision
------------------
1838 public definitions over 1644 distinct names in ``src/``, and 50 referenced by
nothing outside ``tests/`` and ``tools/``. One of them was ``DATA_DIRNAME`` until a one-line
wiring fix in ``src/rcb.py`` took it off the list, so reverting that line puts the population
back up by one -- stated as a delta rather than as the absolute it used to be, because the
absolute drifts with the tree and the sentence outlived two of them. Nineteen more arrived
with FrontierScience: four are its *scorer*, a separate program from the agent that answers
the questions and reached only from ``tools/score_fs_run.py`` (:data:`_FS_SCORER_ONLY`);
ten are the benchmark-agnostic half of ``tools/rcb_trial.py``, which moved into
``src/trial_driver.py`` so that the second benchmark's driver would share it rather than copy
it (:data:`_TRIAL_DRIVER_ONLY`); and five are that second driver's own decision layer
(:data:`_FS_DRIVER_ONLY`), which is in ``src/`` for the same reason the first driver's is --
a policy that decides whether a finished run is a measurement has to be testable without
spending a run. The dataset reader is no longer among them: ``fs_agent.py``
landed, it is in :data:`ENTRY_POINTS`, and ``load_dataset`` and ``resolve_task_keys`` came off
the list -- which is what that exemption said would happen and why it was written that way.

Each of those 50 has exactly one *executable* occurrence of its name across ``main.py``,
``studio.py``, ``rcb_agent.py``, ``fs_agent.py`` and ``src/`` -- its own definition -- and
every other textual hit is a comment or a docstring. **False-positive rate 0/50.** That is
not the scan
marking its own homework. :func:`code_lines_naming` re-reads the roots with ``tokenize``,
which cannot see inside a string or a comment and knows nothing about reference units;
:func:`accusations_with_a_second_code_line` is where the two readers are made to agree, and
:meth:`AllowlistIsHonestTests.test_no_accusation_survives_the_second_reader` fails the suite
when they do not. So the 0 is a gate, not a sentence.

The census prints the rate and the evidence under it, every occurrence labelled ``code`` or
``prose``::

    python3 -m tests.test_declared_symbols_are_wired --census

Its header carries 1838, 1644, 50, 38 and the rate, so those drift with the
tree and none of them has to be believed.
:meth:`AllowlistIsHonestTests.test_the_allowlist_is_exactly_what_the_scan_finds` keeps the
allowlist exactly the scan's output, so none of the four can go stale in one direction
only.
"""

from __future__ import annotations

import ast
import io
import re
import shutil
import sys
import tempfile
import tokenize
import unittest
from pathlib import Path
from typing import NamedTuple

from tests.test_doc_counts import spelled

REPO = Path(__file__).resolve().parent.parent

#: Where the product starts, alongside every module under ``src/``.
#:
#: ``studio.py`` is a two-line launcher and is here because it is the only thing that
#: reaches ``src/backend/``; without it that package reads as dead. ``rcb_agent.py`` and
#: ``fs_agent.py`` are here because a benchmark front end has diverged from ``main.py``
#: before -- that divergence is what ``tests/test_cli_flags_are_read.py`` exists for -- and
#: because each is the only thing that reaches its own benchmark's adapter module. Adding
#: ``fs_agent.py`` is the decision :data:`_FS_SCORER_ONLY` said would have to be made when
#: the FrontierScience front end landed: it is a product entry point, a way this repository
#: is actually started, and not an instrument reading the library from outside.
#: ``fire_agent.py`` is here on the same argument one benchmark later: it is the only
#: thing that reaches ``src/firebench.py``, and leaving it out would make every symbol in
#: that module read as dead while the front end that calls them ships beside it.
#: ``airs_agent.py`` is here for the same reason and ``src/airsbench.py``.
ENTRY_POINTS = ("main.py", "studio.py", "rcb_agent.py", "fs_agent.py", "fire_agent.py",
                "airs_agent.py")

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


class Exempt(NamedTuple):
    """Why a declared symbol is allowed to have no production reference.

    *reason* has to say what wiring it would take, because the next reader's question is
    never "is this dead" -- the gate already answered that -- it is "what would I have to
    decide to bring it back".

    *reached_from* names files outside the reference roots that do use the symbol. It is
    not decoration: :meth:`AllowlistIsHonestTests.test_a_named_consumer_really_consumes_it`
    parses each named file and fails unless :func:`names_used` finds the symbol in it, so
    "reached only from ``tools/rcb_trial.py``" stops being true the moment the driver stops
    *referencing* it -- a leftover mention of the name in the driver's prose does not hold
    the exemption up. The first version of this check was ``assertRegex`` over the
    consumer's raw text, and it was the same defect this module exists to gate: deleting
    ``next_action`` from the driver's import list and rewriting its call site left the
    docstring sentence that names it, and every test here stayed green.

    Consumers must be Python, because that is the only thing this rule can read;
    :meth:`AllowlistIsHonestTests.test_a_named_consumer_is_a_module_this_check_can_parse`
    refuses anything else rather than silently falling back to a text match.
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

#: Shared by the FrontierScience symbols that only ``tools/score_fs_run.py`` reaches. One
#: decision rather than six, for the same reason :data:`_DRIVER_ONLY` is one rather than
#: six: written out six times it would collect six different edits.
_FS_SCORER_ONLY = (
    "Reached only from `tools/score_fs_run.py`, the FrontierScience scorer, which this gate "
    "does not count as a reference root -- and is right not to: "
    "`tools/archive_sample_complexity.py` was importing `RunRecord` and crashing on it at "
    "the same time, so being imported by an instrument is not evidence that a symbol still "
    "works. Nothing a run executes touches this, and that is the design rather than a gap: "
    "the agent answers the question and a judge grades it afterwards, in a separate process, "
    "against a rubric no stage was ever shown. `fs_agent.py` must not import the scorer -- a "
    "front end that could reach the grading code is a front end that could be made to read "
    "the rubric. Wiring it would mean deciding that the answering run may see how it is "
    "marked, which is the one thing this benchmark's prompt contract forbids; until someone "
    "argues for that, `reached_from` is what keeps this claim checkable."
)

#: Shared by the ``src/fs_trial.py`` symbols the FrontierScience paired-trial driver
#: imports. The same trade as :data:`_DRIVER_ONLY` one benchmark over, written separately
#: because the escape clause is not the same one: this module's names are prefixed
#: ``Fs``/``fs_`` precisely so that the sibling's identically-shaped symbols cannot
#: launder them into looking wired. ``git_contrast_log`` is what that costs when it is
#: not done -- it was invisible to this scan for as long as it was called
#: ``contrast_log``, because an unrelated keyword parameter of that name in
#: ``src/rcb_trial.py`` read as a reference.
_FS_DRIVER_ONLY = (
    "Reached only from `tools/fs_trial.py`, the FrontierScience paired-trial driver, "
    "which this gate does not count as a reference root: "
    "`tools/archive_sample_complexity.py` was importing `RunRecord` and crashing on it "
    "at the same time, so being imported by an instrument is not evidence a symbol still "
    "works. Nothing a run executes touches this, and that is the seam rather than a gap "
    "-- the decision of which arm to launch next, and whether a finished run is a "
    "measurement, belongs to a driver watching from outside the run. Wiring it means "
    "having a run decide whether it is admissible, which is the one party a gate over "
    "runs may not ask; `reached_from` is what keeps this claim checkable instead of "
    "asserted."
)

#: Shared by the ``src/trial_driver.py`` functions that only a driver in ``tools/`` calls.
#: One decision rather than ten, for the same reason :data:`_DRIVER_ONLY` is one rather
#: than six.
#:
#: These ten did not become less reachable; they became reachable from *two* drivers
#: instead of one, which is why they moved. Ten and not nine: ``git_contrast_log`` was the
#: tenth all along and the scan could not see it while it was called ``contrast_log``,
#: because a keyword parameter of that name in ``src/rcb_trial.py`` read as a reference. The gate flags them because a tool is not a
#: reference root, and it is right to: nothing a run executes calls an ``os.link`` lock or
#: a ``/proc`` census, and if it ever did that would be the alarming thing.
_TRIAL_DRIVER_ONLY = (
    "Reached only from `tools/rcb_trial.py`, and shortly from a second driver beside it -- "
    "this module is the benchmark-agnostic half of that driver, extracted so that "
    "FrontierScience's driver shares the lock, the `/proc` census and the atomic state "
    "writes instead of copying them. A tool is not a reference root here, on purpose: "
    "`tools/archive_sample_complexity.py` was importing `RunRecord` and crashing on it at "
    "the same time, so being imported by an instrument is not evidence a symbol works. "
    "Wiring it means having a run acquire a trial lock or scan `/proc` for its rivals, "
    "which is the driver's job and the exact thing the seam was cut to keep out of a run; "
    "`reached_from` is what keeps this claim checkable instead of asserted."
)

#: The symbols this repository knowingly declares and does not reach, each with the reason.
#:
#: Keyed ``<path>::<name>`` and matched exactly, so an entry has to be a decision somebody
#: wrote down rather than a prefix that quietly grew to cover its neighbours. Seeded from
#: the census described in this module's docstring.
ALLOWLIST: dict[str, Exempt] = {
    # -- declared for a gate, and wiring it would be the defect --------------------------
    "src/call_cost.py::INERT_NAMES": Exempt(
        "The list of names no condition under `src/` may read. Production must not "
        "reference it, and that is the whole point rather than an oversight: a module "
        "that imported it would be a module consulting the do-not-decide list at runtime, "
        "which is one refactor away from deciding on the thing the list protects. It is "
        "declared beside the fields it names so a field added to `COST_FIELDS` joins the "
        "gate automatically, and read by "
        "`tests/test_cost_is_recorded_and_unread.py`, which is the only reader it should "
        "ever have. Wiring it means giving a runtime component an opinion about cost, "
        "which is the change this repository refused.",
        ("tests/test_cost_is_recorded_and_unread.py",),
    ),
    # -- declared for an instrument, not for a run ---------------------------------------
    "src/rcb_trial.py::collect_rcb_pairs": Exempt(_DRIVER_ONLY, ("tools/rcb_trial.py",)),
    "src/rcb_trial.py::count_quota_hits": Exempt(_DRIVER_ONLY, ("tools/rcb_trial.py",)),
    "src/rcb_trial.py::driver_clause": Exempt(_DRIVER_ONLY, ("tools/rcb_trial.py",)),
    "src/rcb_trial.py::format_rcb_trial_report": Exempt(_DRIVER_ONLY, ("tools/rcb_trial.py",)),
    "src/rcb_trial.py::items_from_score_payloads": Exempt(_DRIVER_ONLY, ("tools/rcb_trial.py",)),
    "src/rcb_trial.py::judge_draws_in": Exempt(_DRIVER_ONLY, ("tools/rcb_trial.py",)),
    "src/rcb_trial.py::next_action": Exempt(_DRIVER_ONLY, ("tools/rcb_trial.py",)),
    "src/fs_trial.py::collect_fs_pairs": Exempt(_FS_DRIVER_ONLY, ("tools/fs_trial.py",)),
    "src/fs_trial.py::format_fs_trial_report": Exempt(_FS_DRIVER_ONLY, ("tools/fs_trial.py",)),
    "src/fs_trial.py::fs_driver_clause": Exempt(_FS_DRIVER_ONLY, ("tools/fs_trial.py",)),
    "src/fs_trial.py::next_actions": Exempt(_FS_DRIVER_ONLY, ("tools/fs_trial.py",)),
    "src/fs_trial.py::arm_for": Exempt(_FS_DRIVER_ONLY, ("tools/fs_trial.py",)),
    "src/trial_driver.py::acquire_lock": Exempt(_TRIAL_DRIVER_ONLY, ("tools/rcb_trial.py",)),
    "src/trial_driver.py::autor_pids": Exempt(_TRIAL_DRIVER_ONLY, ("tools/rcb_trial.py",)),
    "src/trial_driver.py::digest_bytes": Exempt(_TRIAL_DRIVER_ONLY, ("tools/rcb_trial.py",)),
    "src/trial_driver.py::foreign_runs": Exempt(_TRIAL_DRIVER_ONLY, ("tools/rcb_trial.py",)),
    # `git_contrast_log` was invisible to this scan until it was renamed off
    # `contrast_log`: `src/rcb_trial.py`'s report formatter takes a keyword parameter of
    # that name and reads it, and `names_used` matches bare identifiers, so an unrelated
    # local laundered the symbol into looking wired from inside `src/`. The published 45
    # was therefore one short of the measurement it claimed to be, and the entry could
    # not simply be added -- `test_the_allowlist_is_exactly_what_the_scan_finds` refuses
    # an exemption the scan does not flag.
    "src/trial_driver.py::git_contrast_log": Exempt(
        _TRIAL_DRIVER_ONLY, ("tools/rcb_trial.py",)
    ),
    "src/trial_driver.py::git_dirty": Exempt(_TRIAL_DRIVER_ONLY, ("tools/rcb_trial.py",)),
    "src/trial_driver.py::git_head": Exempt(_TRIAL_DRIVER_ONLY, ("tools/rcb_trial.py",)),
    "src/trial_driver.py::release_lock": Exempt(_TRIAL_DRIVER_ONLY, ("tools/rcb_trial.py",)),
    "src/trial_driver.py::watch_until_stalled": Exempt(
        _TRIAL_DRIVER_ONLY, ("tools/rcb_trial.py",)
    ),
    "src/trial_driver.py::write_json": Exempt(_TRIAL_DRIVER_ONLY, ("tools/rcb_trial.py",)),
    "src/fs_scoring.py::ScoringRefused": Exempt(_FS_SCORER_ONLY, ("tools/score_fs_run.py",)),
    "src/fs_scoring.py::build_result": Exempt(_FS_SCORER_ONLY, ("tools/score_fs_run.py",)),
    "src/fs_scoring.py::draw_record": Exempt(_FS_SCORER_ONLY, ("tools/score_fs_run.py",)),
    "src/fs_scoring.py::render_judge_prompt": Exempt(
        _FS_SCORER_ONLY, ("tools/score_fs_run.py",)
    ),
    # -- called by the operator, not by AutoR ---------------------------------------------
    #
    # `record_note` is the write half of the learned-skills layer, and the writer is the
    # research agent rather than this codebase: the `record-what-you-learned` skill hands it
    # a `python3 -c` line to run at the end of a run. AutoR cannot make the call itself --
    # only the agent knows whether the run learned anything transferable, and a manager-side
    # call would have to invent a note or file an empty one every time.
    #
    # Wiring it the way this gate means would take a stage artifact the agent writes and the
    # manager reads, the shape `deliverables_coverage.json` already has. That is worth doing
    # once the layer has earned its place; it has recorded nothing yet.
    "src/skill_evolution.py::record_note": Exempt(
        "invoked by the research agent through the record-what-you-learned skill, not by "
        "AutoR. Wiring it here would mean a stage artifact the agent writes and the manager "
        "reads; until the layer has produced a note worth keeping, that is machinery ahead "
        "of evidence.",
    ),
    # -- a prompt renderer with no channel to render into --------------------------------
    #
    # `format_protocol_for_prompt` was here until #212 gave it a channel, and
    # `format_skills_for_prompt` until the `task_shaped_skills` channel did the same.
    # Both entries came off on the first rebase after their merge, because the other
    # half of this gate refuses an exemption that has outlived its cause -- an
    # allowlist nobody prunes stops being readable. The second one's argument is worth
    # keeping in view: it said wiring the renderer meant deciding a stage should be
    # told which skills exist, and that telling every stage about the whole pack is the
    # cost the pull mechanism was built to avoid. That argument still holds, and the
    # channel does not violate it -- it carries only the skills a predicate selected
    # for this run's brief, which is a decision the model cannot see any other way.
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
        "The caching variant of `write_artifact_index`, which has six production call sites "
        "in four modules and none of them is this. Three read the returned index -- "
        "`information_flow._artifact_index`, `writing_manifest.build_writing_manifest` and "
        "`experiment_manifest.write_experiment_manifest` -- and three call it for the write "
        "alone: `manager._create_run`, `_run_stage` and `_skip_stage`. All six want the "
        "rewriting one, and they are right to: an index served from cache mid-run would "
        "describe a workspace that has since changed, and the three manager sites call it "
        "precisely at the moments the workspace just did. Wiring this is a freshness "
        "decision, and across a population of six the current answer is 'never'."
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
        "Labelled a convenience builder for `--skip-intake` backward compatibility, and its "
        "body is `IntakeContext(goal=goal, original_goal=goal)`. Neither live site can call "
        "it as written: both `manager.py` constructions carry fields it does not take -- one "
        "passes ingested `resources`, the other five keyword arguments including the carried "
        "`original_goal`, the accumulated `qa_transcript` and the stage `notes`. So wiring it "
        "means widening the builder's signature until it is the constructor again, or "
        "deleting it. That is the intake path's call, not a gate's."
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


def consumer_references(path: Path, symbol: str) -> bool:
    """Does *path* reference *symbol*, by the same rule the scan applies to production?

    :attr:`Exempt.reached_from` is a claim about a file this gate does not scan, so it has
    to be checked by the gate's own rule and not by a weaker one. :func:`names_used` is that
    rule. A ``grep`` here would accept the very thing the scan refuses: the driver's
    docstring mentioning the symbol it stopped calling.
    """
    return symbol in names_used(ast.parse(path.read_text(encoding="utf-8")))


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


def allowlisted_symbols_with_a_test(root: Path = REPO) -> tuple[str, ...]:
    """The allowlisted keys some test file outside this one references.

    The argument for excluding ``tests/`` from the reference roots rests on a count -- how
    many of these dead symbols a test is currently holding green -- and a count written into
    prose rots. This is the count, by :func:`names_used` over the parsed test modules, so a
    test that only names a symbol in a docstring does not raise it, exactly as in ``src/``.
    This module is excluded because :data:`ALLOWLIST` names every one of them by
    construction, so counting itself would answer the question with the question.
    """
    here = Path(__file__).resolve()
    referenced: set[str] = set()
    for path in sorted((root / "tests").glob("*.py")):
        if path.resolve() == here:
            continue
        referenced |= names_used(ast.parse(path.read_text(encoding="utf-8")))
    return tuple(sorted(key for key in ALLOWLIST if key.split("::", 1)[1] in referenced))


def code_lines_naming(path: Path) -> dict[str, set[int]]:
    """Lines of *path* where each identifier appears as a token the interpreter reads.

    A second reader for the false-positive claim, and deliberately not the one the scan
    uses: ``tokenize`` sees ``NAME`` tokens, so a name inside a comment or a string never
    appears here, while the AST pass reasons about reference *units* and self-exclusion.
    When the two agree that a symbol's only executable occurrence is its own definition,
    the accusation was checked twice by two different mechanisms.
    """
    lines: dict[str, set[int]] = {}
    reader = io.StringIO(path.read_text(encoding="utf-8")).readline
    for token in tokenize.generate_tokens(reader):
        if token.type == tokenize.NAME:
            lines.setdefault(token.string, set()).add(token.start[0])
    return lines


def accusations_with_a_second_code_line(root: Path = REPO) -> dict[str, list[str]]:
    """Flagged symbols the *other* reader still finds executed somewhere. The false positives.

    An accusation is correct when the only place the interpreter ever sees the name is the
    definition being accused. :func:`scan` decides that from reference units and
    self-exclusion; this decides it from :func:`code_lines_naming`, which knows nothing
    about either. Every entry in the returned mapping is a symbol the scan called dead and
    the tokenizer found in live code -- a false positive, and a bug in one of the two.
    """
    result = scan(root)
    tokens = {path: code_lines_naming(path) for path in production_files(root)}
    elsewhere: dict[str, list[str]] = {}
    for definition in sorted(result.unreferenced, key=lambda item: item.key):
        hits = [
            f"{path.relative_to(root).as_posix()}:{number}"
            for path, lines in tokens.items()
            for number in sorted(lines.get(definition.name, ()))
            if (path.relative_to(root).as_posix(), number) != (definition.module, definition.lineno)
        ]
        if hits:
            elsewhere[definition.key] = hits
    return elsewhere


def census(root: Path = REPO) -> str:
    """The measurement behind this module's docstring, with its evidence.

    For each unreferenced symbol it prints every textual occurrence of the name across the
    reference roots, each labelled ``code`` or ``prose`` by :func:`code_lines_naming`. That
    is what makes the false-positive rate checkable rather than asserted: an accusation is
    right when exactly one occurrence is ``code`` and it is the definition, and
    :func:`accusations_with_a_second_code_line` counts the ones where it is not, instead of
    asking a reader to.
    """
    result = scan(root)
    distinct = {definition.name for definition in result.definitions}
    tested = allowlisted_symbols_with_a_test(root)
    untested = sorted(set(ALLOWLIST) - set(tested))
    false_positives = accusations_with_a_second_code_line(root)
    sources = {path: path.read_text(encoding="utf-8").splitlines() for path in production_files(root)}
    tokens = {path: code_lines_naming(path) for path in sources}

    body: list[str] = []
    for definition in sorted(result.unreferenced, key=lambda item: item.key):
        exempt = ALLOWLIST.get(definition.key)
        body.append(f"{definition.key}:{definition.lineno}" + ("" if exempt else "   [NOT ALLOWLISTED]"))
        pattern = re.compile(rf"\b{re.escape(definition.name)}\b")
        for path, text in sources.items():
            executable = tokens[path].get(definition.name, set())
            relative = path.relative_to(root).as_posix()
            for number, line in enumerate(text, 1):
                if pattern.search(line):
                    label = "code " if number in executable else "prose"
                    body.append(f"    [{label}] {relative}:{number}: {line.strip()}")
        if exempt and exempt.reached_from:
            body.append(f"    reached from: {', '.join(exempt.reached_from)}")
        body.append("")

    return "\n".join([
        f"{len(result.definitions)} public definitions over {len(distinct)} distinct names in src/",
        f"{len(result.unreferenced)} referenced by nothing outside tests/ and tools/",
        f"{len(ALLOWLIST)} allowlisted",
        f"{len(tested)} of the {len(ALLOWLIST)} allowlisted are referenced by a test; "
        f"{len(untested)} are not:",
        *(f"    {key}" for key in untested),
        f"false-positive rate {len(false_positives)}/{len(result.unreferenced)} -- flagged "
        f"symbols with a code line beyond their own definition: "
        f"{sorted(false_positives) or 'none'}",
        "",
        *body,
    ])


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

    def test_the_stated_count_of_tested_symbols_is_the_measured_one(self) -> None:
        """The one number this module asserts in prose, pinned to the symbol it counts.

        The reason `tests/` is not a reference root is that a test keeps a dead symbol
        green, and the force of that argument is the count. The first version of the
        sentence said twenty-one; the measurement says twenty, and nothing in the file
        could tell the difference. `tests/test_doc_counts.py` pins spelled-out counts in
        the docs against live symbols; this is the same rule turned on this docstring.
        """
        tested = allowlisted_symbols_with_a_test()
        sentence = (
            f"{spelled(len(tested))} of the {spelled(len(ALLOWLIST))} symbols listed "
            "below have one"
        )
        self.assertIn(
            sentence,
            " ".join((__doc__ or "").split()),
            f"this module's docstring does not say '{sentence}'; "
            f"{len(tested)} of {len(ALLOWLIST)} allowlisted symbols are referenced by a "
            "test, run --census for the list of the ones that are not",
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
        """`reached_from` is checked, so "only tools/ uses it" cannot rot into a lie.

        By :func:`consumer_references`, which is :func:`names_used` -- the same rule the
        scan uses -- and not a text match. A text match is satisfied by the driver's own
        prose, which is exactly the failure `tests/test_archive_exploration_wiring.py`
        already made once and this module is written against.
        """
        for key, exempt in ALLOWLIST.items():
            symbol = key.split("::", 1)[1]
            for consumer in exempt.reached_from:
                with self.subTest(symbol=key, consumer=consumer):
                    path = REPO / consumer
                    self.assertTrue(path.is_file(), f"{key}: {consumer} does not exist")
                    self.assertTrue(
                        consumer_references(path, symbol),
                        f"{key}: {consumer} names it in prose at best -- no executable "
                        "reference is left, so the exemption is wrong",
                    )

    def test_a_named_consumer_is_a_module_this_check_can_parse(self) -> None:
        """A non-Python consumer would quietly turn the check above back into a grep."""
        for key, exempt in ALLOWLIST.items():
            for consumer in exempt.reached_from:
                with self.subTest(symbol=key, consumer=consumer):
                    self.assertTrue(
                        consumer.endswith(".py"),
                        f"{key}: reached_from={consumer!r} is not Python, so "
                        "names_used cannot read it; name the module that references the "
                        "symbol, or drop reached_from and say so in the reason",
                    )

    def test_no_accusation_survives_the_second_reader(self) -> None:
        """The false-positive rate this module publishes, asserted instead of printed.

        This module's docstring publishes a false-positive rate and the census prints it;
        without this the rate is a line of output nobody checks, and inverting the
        `code`/`prose` label left every other test in this file green. It is not a
        restatement of the scan:
        :func:`code_lines_naming` reaches the same verdict through ``tokenize``, so this
        fails when the two readers disagree -- which means one of them is wrong.
        """
        elsewhere = accusations_with_a_second_code_line()
        self.assertEqual(
            elsewhere,
            {},
            "the scan called these dead and the tokenizer found the name in live code, "
            f"so an accusation here is a false positive: {elsewhere}",
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

    def test_a_named_consumer_mentioning_it_in_prose_does_not_consume_it(self) -> None:
        """The same rule, applied to the file :attr:`Exempt.reached_from` points at.

        Both halves matter and only one of them was checked before: the prose-only file
        has to fail, or ``reached only from tools/x.py`` survives the driver dropping the
        call, which is the defect that motivated this module.
        """
        root = self._tree({
            "tools/calls_it.py": "from src.thing import orphan\n\nprint(orphan())\n",
            "tools/only_mentions_it.py": '"""Reads a payload; ``orphan`` keys on the same field."""\n\nprint(1)\n',
        })
        self.assertTrue(consumer_references(root / "tools/calls_it.py", "orphan"))
        self.assertFalse(consumer_references(root / "tools/only_mentions_it.py", "orphan"))

    def test_a_name_in_a_comment_or_a_string_is_not_a_code_line(self) -> None:
        """What makes :func:`code_lines_naming` an independent reader and not a grep."""
        root = self._tree({
            "src/thing.py": '"""``orphan`` is the one to read."""\n\n\ndef orphan():\n    # orphan again\n    return "orphan"\n',
        })
        self.assertEqual(code_lines_naming(root / "src/thing.py").get("orphan"), {4})

    def test_the_census_labels_the_evidence_it_prints(self) -> None:
        """The instrument's output is the argument for the published rate, so it is pinned.

        Labelling every occurrence `code` left the rate and every other test in this file
        green while turning the printed evidence into a lie -- the reader is being asked to
        confirm a symbol's only executable occurrence is its definition, and the label is
        the whole of what they are reading.
        """
        root = self._tree({
            "src/thing.py": '"""``orphan`` does the work."""\n\n\ndef orphan():\n    return 2\n',
            "main.py": "import src.thing\n",
        })
        self.assertEqual(
            [line for line in census(root).splitlines() if line.startswith("    [")],
            [
                '    [prose] src/thing.py:1: """``orphan`` does the work."""',
                "    [code ] src/thing.py:4: def orphan():",
            ],
        )

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

    def test_a_framework_dispatched_method_is_a_known_false_positive(self) -> None:
        """The cost this rule pays, pinned rather than described.

        A name only a framework calls has no reference in this tree, so the flat check
        accuses it. `src/backend/studio_http.py` has exactly this shape and escapes only
        because `StudioHandler` is nested inside `build_handler`, which
        :func:`public_definitions` never reaches. Hoisted to module level, as the tree
        below is, `do_GET` is reported. The remedy is an `ALLOWLIST` entry naming the
        framework, and knowing that in advance is the point of this test.
        """
        dead = self._dead({
            "src/serve.py": "from http.server import BaseHTTPRequestHandler\n\n\nclass Handler(BaseHTTPRequestHandler):\n    def do_GET(self):\n        return None\n",
            "main.py": "from src.serve import Handler\n\nprint(Handler)\n",
        })
        self.assertEqual(dead, {"src/serve.py::do_GET"})

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
