"""Every gate in the tree, and where the field it decides on is written.

The operator runs with ``bypassPermissions --dangerously-skip-permissions`` at
``cwd=run_root``, and every stage prompt directs the agent at ``workspace/``. So a gate
whose refusal turns on a field under ``workspace/`` is reading an answer written by the
party it constrains. Two reviewers found that shape independently on the same day and it
produced two merges — #203 stamped the frozen preregistration outside ``workspace/``,
#206 closed the reset that survived it — and neither enumerated the family. This is the
enumeration, as a test rather than a document, so a gate that reads an agent-written
verdict has to be classified on the way in.

**The classes**, which are :data:`TRUST_LEVELS` and are pinned to it by
``test_the_docstring_names_every_trust_level`` — a prose list of classes that has fallen
one behind the tuple is the same defect one level up from the one this file is about.

``HARNESS``
    Every decisive field is written by AutoR somewhere the stage prompts do not name.
``COUNTED``
    The agent wrote it and the gate reads it as a count, a shape, or the work itself. A
    count of the files a stage made is what it is; it cannot claim the stage passed.
``CROSS_CHECKED``
    The agent wrote a claim and the gate re-derives it against something the agent did
    not author for this purpose — a stamp outside ``workspace/``, a file that has to
    exist, text that has to appear in the report.
``BELIEVED``
    The agent can write it and the gate takes it at its word. This is the defect, so
    these are an explicit allowlist and every entry carries a reason **and a witness**:
    a test below that edits the field and shows the verdict move. An allowlist of
    reasons nobody ran is how a false positive gets inherited.
``NO_FIELD``
    The gate reads nothing, so there is nobody to trust. It is a class rather than an
    omission because a guard that reads nothing and a guard nobody classified look
    identical from outside, and only one of them is fine.

**What is derived and what is declared.** The population is derived: the ``validate_*``
functions are parsed out of ``src/*.py`` at module scope and on classes, the guards come
from ``stage_graph.GUARDS`` and the assessors from ``scorecard.FEATURES``, so a new gate
fails this file rather than joining the tree unclassified. Each declared path is resolved
against ``build_run_paths``, so a renamed ``RunPaths`` field fails too, and *whether a path
is under* ``workspace/`` is computed rather than asserted.

The class itself is a judgement, recorded with its reason. The implication the test can
check is one-way: a gate with a decisive path under ``workspace/`` may not call itself
``HARNESS``. The converse does not hold — the stage draft is agent-written and lives in
``stages/`` at the run root — which is also the boundary #206 wrote down: everything under
``run_root`` is writable by the party the gate constrains. ``workspace/`` is where the
prompts send the agent, not the edge of what it can reach.
"""

from __future__ import annotations

import ast
import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Callable, NamedTuple

from src.scorecard import DROP, FEATURES, KEEP, build_scorecard
from src.stage_graph import GUARDS, GraphState, Visit
from src.utils import STAGES, RunPaths, build_run_paths, ensure_run_layout

REPO = Path(__file__).resolve().parent.parent

HARNESS = "harness"
COUNTED = "counted"
CROSS_CHECKED = "cross_checked"
BELIEVED = "believed"
NO_FIELD = "no_field"

TRUST_LEVELS = (HARNESS, COUNTED, CROSS_CHECKED, BELIEVED, NO_FIELD)


class Gate(NamedTuple):
    #: ``module.function`` for a validator, ``guard:<name>``, or ``scorecard:<key>``.
    name: str
    #: ``RunPaths`` field names, run-root-relative filenames, or ``repo:<path>``.
    decides_on: tuple[str, ...]
    trust: str
    why: str


#: Every gate that refuses something, and what its refusal turns on.
#:
#: Ordered as the run meets them: the graph's guards, then the validators by stage, then
#: the scorecard, which publishes rather than refuses and is here because its assessors
#: read the same writable surface.
GATES: tuple[Gate, ...] = (
    # ------------------------------------------------------------------ guards
    Gate(
        "guard:always",
        (),
        NO_FIELD,
        "No precondition: the edge is always admissible, so there is no field to trust. "
        "It is in the table because a guard that reads nothing and a guard nobody "
        "classified look the same from outside.",
    ),
    Gate(
        "guard:design_artifacts",
        ("data_dir", "experimental_protocol"),
        COUNTED,
        "Counts machine-readable files under workspace/data and requires the protocol to "
        "*declare* baselines. Neither says the design was good. `declared_at` is "
        "agent-written and unstamped, and no refusal in the tree reads it.",
    ),
    Gate(
        "guard:runnable_code",
        ("code_dir",),
        COUNTED,
        "Counts executable files under workspace/code. A count of the files a stage made "
        "is what it is; nothing in it can claim the code runs.",
    ),
    Gate(
        "guard:results_exist",
        ("results_dir", "experiment_manifest"),
        COUNTED,
        "Counts result files and requires the manifest to index some of them. "
        "`ready_for_analysis` is an agent-written boolean and no refusal reads its value.",
    ),
    Gate(
        "guard:validity_chain",
        ("preregistration", "preregistration_stamp.json", "hypothesis_outcomes", "figures_dir"),
        CROSS_CHECKED,
        "#203. The population is the hypothesis set AutoR stamped outside workspace/, and "
        "the edge is closed while the workspace copy disagrees with it, before the ids are "
        "counted at all.",
    ),
    Gate(
        "guard:report_exists",
        ("report_file", "writing_dir"),
        COUNTED,
        "Whether report.md exists, or workspace/writing holds a manuscript source. "
        "Existence of the agent's own output, which is not a claim about it.",
    ),
    Gate(
        "guard:has_hypotheses",
        ("hypothesis_manifest",),
        COUNTED,
        "Requires at least one empirical hypothesis to be stated. Being on the record "
        "before the design is the whole value; the gate grades nothing.",
    ),
    Gate(
        "guard:round_abandoned",
        ("research_rounds", "evolution_dir"),
        BELIEVED,
        "`research_rounds.json` is written by AutoR (`_write_rounds`) but into "
        "workspace/notes/, and the terminal turns on the word in its `decision` field. The "
        "visit half (`Visit.closed_round`) is harness state under evolution/, so the ledger "
        "is the reachable one. Not fixed here: the same stamp shape closes it and is one PR.",
    ),
    # -------------------------------------------------------------- validators
    Gate(
        "evidence_ledger.validate_literature_evidence",
        ("literature_dir",),
        COUNTED,
        "Shape and internal reference integrity of a bibliography the agent authored: "
        "unique source ids, every claim citing one that is declared. Whether a source is "
        "real is a different lens and a different gate.",
    ),
    Gate(
        "utils.validate_stage_markdown",
        ("stages_dir", "run_root"),
        COUNTED,
        "The stage draft is agent-written, at the run root rather than under workspace/. "
        "The gate reads it for required headings, placeholder text, and whether every file "
        "listed under `Files Produced` exists — shape plus an existence check.",
    ),
    Gate(
        "utils.validate_stage_artifacts",
        (
            "data_dir",
            "results_dir",
            "figures_dir",
            "artifacts_dir",
            "writing_dir",
            "operator_state_dir",
        ),
        COUNTED,
        "The aggregator; every field it dispatches on is a row of its own here. Its inline "
        "checks are counts, file existence, and mtime freshness against "
        "operator_state/<slug>.started_at.txt, which is at the run root.",
    ),
    Gate(
        "run_skills.validate_skill_pack",
        ("repo:src/skills",),
        HARNESS,
        "Reads the AutoR checkout's skill pack, not the run tree, and no run ever calls "
        "it: `tests/test_run_skills.py` is its only caller, so it refuses a malformed "
        "skill at build time. `test_the_skill_pack_gate_has_no_run_time_caller` pins "
        "that, because a run-time caller would make this a gate over installed files.",
    ),
    Gate(
        "experimental_protocol.validate_experimental_protocol",
        ("experimental_protocol",),
        COUNTED,
        "Requires the primary metric, the planned seed count and a competent baseline with "
        "a tuning budget to be *stated*. A declaration on the record can be contradicted "
        "later; the gate reads none of it as a grade.",
    ),
    Gate(
        "preregistration.validate_preregistration",
        ("preregistration", "preregistration_stamp.json", "logs"),
        CROSS_CHECKED,
        "#203 and #206. Three comparisons — the hypotheses against the digest the file "
        "states, that digest against the stamped one, the amendment ledger's length — plus "
        "the freeze witness in the append-only run log.",
    ),
    Gate(
        "experiment_manifest.validate_experiment_manifest",
        ("experiment_manifest",),
        COUNTED,
        "Shape: generated_at, three summary counts, schema metadata per result artifact. "
        "`ready_for_analysis` must be a boolean and its value is never read.",
    ),
    Gate(
        "validity_review.validate_validity_response",
        ("reviews_dir", "validity_review_stamp.json"),
        CROSS_CHECKED,
        "The findings the stage owes an answer to are counted from the stamp at the run "
        "root, and a workspace copy that disagrees with it is refused rather than believed. "
        "Before that stamp existed, deleting the file cleared the obligation.",
    ),
    Gate(
        "preregistration.validate_hypothesis_outcomes",
        ("hypothesis_outcomes", "preregistration"),
        CROSS_CHECKED,
        "The verdict word is the agent's and unavoidably so — nothing can adjudicate a "
        "hypothesis for it. What the gate re-derives: the id is in the stamped set, the "
        "digest matches, and `supported`/`refuted` cites a file that exists.",
    ),
    Gate(
        "experimental_protocol.validate_outcome_statistics",
        ("hypothesis_outcomes",),
        BELIEVED,
        "`statistics.n_seeds` is the agent's count of its own runs and nothing re-derives "
        "it from the result artifacts, so the single-run refusal is cleared by writing a "
        "larger number. Listed rather than fixed: a seed count cannot be recovered from an "
        "arbitrary result file, so closing this needs a declared shape for one.",
    ),
    Gate(
        "research_rounds.validate_round_decision",
        ("round_decision", "research_rounds", "hypothesis_outcomes"),
        BELIEVED,
        "Same ledger as guard:round_abandoned, read from Stage 07 on. `converged` is "
        "cross-checked against the adjudicated verdicts, but the standing-abandonment "
        "refusal turns on a word in workspace/notes/research_rounds.json.",
    ),
    Gate(
        "report_plan.validate_report_plan",
        ("report_plan", "report_plan_stamp.json"),
        CROSS_CHECKED,
        "Whether the plan has ever been declared is read from AutoR's stamp at the run "
        "root, not from the file's own `declared_at`, so the date cannot be backdated.",
    ),
    Gate(
        "report_plan.validate_report_plan_sources",
        ("report_plan", "results_dir", "data_dir"),
        CROSS_CHECKED,
        "Every `source_artifact` the plan names has to resolve to a non-empty file, at the "
        "stage that draws the figures rather than at export.",
    ),
    Gate(
        "report_plan.validate_report_plan_coverage",
        ("report_plan", "report_file", "report_images_dir", "figures_dir"),
        CROSS_CHECKED,
        "Every slot the plan did not drop has to be published *and* referenced by the "
        "report. The claim is checked against the report's own text and images.",
    ),
    Gate(
        "preregistration.validate_claim_provenance",
        ("claim_provenance", "hypothesis_outcomes", "preregistration"),
        CROSS_CHECKED,
        "A confirmatory claim must name a preregistered hypothesis whose verdict is "
        "`supported`, and cite evidence that exists. Self-labelling as exploratory is the "
        "permitted move and is a disclosure, not an exemption.",
    ),
    Gate(
        "utils.validate_markdown_report",
        ("report_file", "report_images_dir", "figures_dir"),
        COUNTED,
        "Length, distinct figure count, and whether each referenced image resolves to a "
        "renderable file on disk.",
    ),
    Gate(
        "deliverables.validate_deliverables_coverage",
        ("artifacts_dir", "report_file", "user_input"),
        CROSS_CHECKED,
        "`addressed: true` is the agent grading itself, and both halves are re-derived: "
        "`task_quote` has to appear verbatim in the task statement, and `where` has to "
        "appear in report.md.",
    ),
    Gate(
        "evidence_ledger.validate_citation_verification",
        ("artifacts_dir",),
        COUNTED,
        "`overall_status` is an agent-written verdict and the gate reads only that it is "
        "non-empty; no refusal in the tree turns on its value, so writing `verified` clears "
        "nothing. The rest is shape.",
    ),
    Gate(
        "writing_manifest.validate_report_review",
        ("artifacts_dir",),
        COUNTED,
        "AutoR computes this file and writes it into workspace/artifacts, so the agent can "
        "rewrite it — but the gate reads only field presence and types, and no refusal "
        "reads `overall_status`. A forged `clean` buys the same pass an honest one gets.",
    ),
    Gate(
        "writing_manifest.validate_layout_review",
        ("artifacts_dir",),
        COUNTED,
        "As report_review.json: presence and types only, and `overall_status` decides "
        "nothing.",
    ),
    # --------------------------------------------------------------- scorecard
    Gate(
        "scorecard:review_panel",
        ("reviews_dir",),
        BELIEVED,
        "AutoR measures the panel and writes reviews/panel/panel_effect.json, then reads "
        "its own counts back to publish keep or drop. The ledger is in the tree the agent "
        "writes. Nothing is gated on it — what is at stake is a published claim about the "
        "run, not a move — so it is listed rather than fixed.",
    ),
    Gate(
        "scorecard:ideation_panel",
        ("notes_dir",),
        BELIEVED,
        "As review_panel, with the ledger at notes/idea_pool.json: `effect."
        "adopted_from_other_proposers` is the number the verdict turns on.",
    ),
    Gate(
        "scorecard:anchored_comments",
        ("reviews_dir",),
        BELIEVED,
        "As review_panel, with the ledger at reviews/comment_ledger.json: "
        "`summary.comments_addressed` is the number the verdict turns on.",
    ),
    Gate(
        "scorecard:deliberation",
        ("reviews_dir",),
        BELIEVED,
        "As review_panel, with the ledger at reviews/deliberations.json: "
        "`summary.changed_the_agents_answer` is the number the verdict turns on.",
    ),
    Gate(
        "scorecard:effort_tiers",
        ("reviews_dir",),
        BELIEVED,
        "As review_panel, with the ledger at reviews/effort.json: `summary.run_as_routine` "
        "is the number the verdict turns on.",
    ),
)


# ---------------------------------------------------------------------------
# The population, derived from live symbols
# ---------------------------------------------------------------------------


def _validators_in(source: str, module: str) -> set[str]:
    """``validate_*`` functions at module scope or on a class, by AST rather than by grep.

    A regex over the text would also match the name in a docstring or an import, and this
    file's whole job is to notice a gate nobody classified — a discovery step with false
    positives would be silenced by exempting them.

    Class bodies are descended into, and function bodies are not. Every validator in the
    tree today is module-level, but "a new gate fails this file rather than joining the
    tree unclassified" is false the moment one arrives as a method, and a gate written as
    ``class Something: def validate_x`` is not an exotic shape — ``ValidityReviewer`` and
    ``AutomatedReviewer`` are both classes. A ``def validate_x`` nested inside another
    function is a local helper, not a gate anything outside can call, and admitting those
    would put false positives into the very check that is supposed to have none.
    """
    def walk(body: list[ast.stmt], prefix: str) -> set[str]:
        found: set[str] = set()
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("validate_"):
                    found.add(f"{prefix}.{node.name}")
            elif isinstance(node, ast.ClassDef):
                found |= walk(node.body, f"{prefix}.{node.name}")
        return found

    return walk(ast.parse(source).body, module)


def _gates_in_the_tree() -> set[str]:
    found: set[str] = set()
    for path in sorted((REPO / "src").glob("*.py")):
        found |= _validators_in(path.read_text(encoding="utf-8"), path.stem)
    found |= {f"guard:{name}" for name in GUARDS}
    found |= {f"scorecard:{feature['key']}" for feature in FEATURES}
    return found


def _resolve(paths: RunPaths, token: str) -> Path:
    if token.startswith("repo:"):
        return REPO / token[len("repo:") :]
    if hasattr(paths, token):
        return getattr(paths, token)
    return paths.run_root / token


def _src_blob() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((REPO / "src").glob("*.py"))
    )


# ---------------------------------------------------------------------------
# Witnesses: the BELIEVED rows, demonstrated rather than asserted
# ---------------------------------------------------------------------------


def _fresh_run(stack: tempfile.TemporaryDirectory) -> RunPaths:
    paths = build_run_paths(Path(stack.name) / "run")
    ensure_run_layout(paths)
    return paths


def _round_ledger(decision: str) -> str:
    return json.dumps(
        {
            "updated_at": "2026-08-13T00:00:00",
            "rounds": [
                {
                    "round": 1,
                    "decision": decision,
                    "rationale": "the effect cannot be separated from the noise at this budget",
                    "what_we_learned": "the measurement is dominated by seed variance",
                    "what_changes_next": "",
                    "negative_result": False,
                    "hypothesis_verdicts": {},
                    "recorded_at": "2026-08-13T00:00:00",
                    "acted_on": True,
                    "budget_note": "",
                    "reopens_round": 0,
                }
            ],
        }
    )


def _witness_round_abandoned(paths: RunPaths) -> tuple[object, object]:
    """One word in a harness-written ledger, and a terminal edge stops firing."""
    guard = GUARDS["round_abandoned"]
    state = GraphState(path=[Visit(stage="06_analysis", entered_at="t", closed_round=1)])
    paths.research_rounds.write_text(_round_ledger("abandon"), encoding="utf-8")
    before = guard(paths, state).ok
    paths.research_rounds.write_text(_round_ledger("converged"), encoding="utf-8")
    return before, guard(paths, state).ok


def _witness_round_decision(paths: RunPaths) -> tuple[object, object]:
    from src.research_rounds import validate_round_decision

    stage07 = STAGES[6]
    paths.research_rounds.write_text(_round_ledger("abandon"), encoding="utf-8")
    before = bool(validate_round_decision(paths, stage07))
    paths.research_rounds.write_text(_round_ledger("converged"), encoding="utf-8")
    return before, bool(validate_round_decision(paths, stage07))


def _witness_outcome_statistics(paths: RunPaths) -> tuple[object, object]:
    """`n_seeds` is the agent's count of its own runs, and no artifact is consulted."""
    from src.experimental_protocol import validate_outcome_statistics

    def outcomes(seeds: int) -> str:
        return json.dumps(
            {
                "outcomes": [
                    {
                        "id": "H1",
                        "verdict": "supported",
                        "rationale": "the gap exceeds the spread",
                        "evidence": ["results/main.json"],
                        "statistics": {
                            "n_seeds": seeds,
                            "dispersion_type": "std",
                            "dispersion": 0.01,
                        },
                    }
                ]
            }
        )

    paths.hypothesis_outcomes.write_text(outcomes(1), encoding="utf-8")
    before = any("single run" in problem for problem in validate_outcome_statistics(paths))
    paths.hypothesis_outcomes.write_text(outcomes(5), encoding="utf-8")
    return before, any("single run" in problem for problem in validate_outcome_statistics(paths))


#: The counts each scorecard ledger has to carry to read as ``drop``, and the single field
#: to rewrite to make it read as ``keep``. Driven off ``FEATURES`` for the location, so a
#: feature that moves its ledger moves this witness with it.
_SCORECARD_LEDGERS: dict[str, tuple[dict, tuple[str, ...], object]] = {
    "review_panel": (
        {"summary": {"gates_reviewed": 3, "gates_where_the_panel_changed_the_decision": 0}},
        ("summary", "gates_where_the_panel_changed_the_decision"),
        3,
    ),
    "ideation_panel": (
        {"effect": {"adoption_measured": True, "adopted_from_other_proposers": 0}},
        ("effect", "adopted_from_other_proposers"),
        2,
    ),
    "anchored_comments": (
        {"summary": {"rounds": 2, "comments_addressed": 0}},
        ("summary", "comments_addressed"),
        4,
    ),
    "deliberation": (
        {"summary": {"cruxes_raised": 1, "changed_the_agents_answer": 0, "confirmed_the_agents_answer": 1}},
        ("summary", "changed_the_agents_answer"),
        1,
    ),
    "effort_tiers": (
        {"enabled": True, "summary": {"stages_planned": 8, "run_as_routine": 0}},
        ("summary", "run_as_routine"),
        3,
    ),
}


def _scorecard_witness(key: str) -> Callable[[RunPaths], tuple[object, object]]:
    def witness(paths: RunPaths) -> tuple[object, object]:
        feature = next(item for item in FEATURES if item["key"] == key)
        path = feature["locate"](paths)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload, field_path, forged = _SCORECARD_LEDGERS[key]
        payload = json.loads(json.dumps(payload))

        def verdict() -> str:
            path.write_text(json.dumps(payload), encoding="utf-8")
            report = next(r for r in build_scorecard(paths).features if r.key == key)
            return report.verdict

        as_measured = verdict()
        payload[field_path[0]][field_path[1]] = forged
        return as_measured, verdict()

    return witness


#: Rows whose decisive fields are agent-written but sit outside ``workspace/``, with the
#: reason each one does. The exemption exists because ``workspace/`` is where the prompts
#: send the agent, not the edge of what it can write, and a row here is the reader's
#: warning that the derived check below says nothing about it. Deliberately exact rather
#: than a rule: a second entry should have to be argued for.
AGENT_WRITTEN_OUTSIDE_WORKSPACE: dict[str, str] = {
    "utils.validate_stage_markdown": (
        "The stage draft is the agent's own prose and the operator writes it to "
        "stages/<slug>.tmp.md, at the run root. Nothing about it is under workspace/, so "
        "the workspace test cannot see it; it is COUNTED because the gate reads headings, "
        "placeholder text and whether the files it names exist."
    ),
}

#: One executable demonstration per ``BELIEVED`` row. ``test_every_believed_row_has_a
#: _witness`` pins this to the table, so a row cannot be added to the allowlist on the
#: strength of a sentence.
WITNESSES: dict[str, Callable[[RunPaths], tuple[object, object]]] = {
    "guard:round_abandoned": _witness_round_abandoned,
    "research_rounds.validate_round_decision": _witness_round_decision,
    "experimental_protocol.validate_outcome_statistics": _witness_outcome_statistics,
    **{f"scorecard:{key}": _scorecard_witness(key) for key in _SCORECARD_LEDGERS},
}


class EveryGateIsClassifiedTests(unittest.TestCase):
    def test_the_table_covers_every_gate_in_the_tree(self) -> None:
        """A new gate joins this table or fails here. That is the whole point of the file."""
        declared = {gate.name for gate in GATES}
        found = _gates_in_the_tree()
        self.assertEqual(
            sorted(found - declared),
            [],
            "these gates decide something and are not classified: "
            f"{sorted(found - declared)}",
        )
        self.assertEqual(
            sorted(declared - found),
            [],
            f"these rows name a gate that no longer exists: {sorted(declared - found)}",
        )

    def test_the_docstring_names_every_trust_level(self) -> None:
        """The module's own prose, held to the tuple it describes.

        This file exists because a classification kept in prose rots. Its own class list
        is prose, and it was written naming four of the five — ``NO_FIELD`` was in
        ``TRUST_LEVELS`` and in ``guard:always``'s row and not in the list a reader of
        the header would take as complete. Adding a sixth level now has to add a
        paragraph.
        """
        docstring = __doc__ or ""
        for level in TRUST_LEVELS:
            with self.subTest(level=level):
                self.assertIn(
                    f"``{level.upper()}``",
                    docstring,
                    f"{level} is a trust level this module's header does not describe",
                )
        described = re.findall(r"^``([A-Z_]+)``$", docstring, re.M)
        self.assertEqual(
            sorted(described),
            sorted(level.upper() for level in TRUST_LEVELS),
            "the header describes a class that is not in TRUST_LEVELS",
        )

    def test_the_table_has_no_duplicate_rows(self) -> None:
        names = [gate.name for gate in GATES]
        self.assertEqual(sorted(names), sorted(set(names)))

    def test_the_scan_would_notice_a_gate_nobody_classified(self) -> None:
        """Control. The assertion above passes whether or not the scan still finds anything."""
        fabricated = (
            "import json\n"
            "def helper():\n    return []\n"
            "def validate_something_new(paths):\n    return []\n"
        )
        self.assertEqual(
            _validators_in(fabricated, "fake"), {"fake.validate_something_new"}
        )
        self.assertGreater(len(_gates_in_the_tree()), 25)

    def test_a_gate_written_as_a_method_is_not_invisible_to_the_scan(self) -> None:
        """The shape the docstring's promise breaks on if the scan stops at module scope.

        Every validator in the tree is module-level today, so a scan over
        ``ast.parse(source).body`` alone finds the same 20 names and looks correct. It
        stops being correct the first time a gate lands as ``class Reviewer: def
        validate_x`` — two of this tree's reviewers are already classes — and the failure
        mode is the silent one: the new gate never appears in ``found - declared`` and
        joins the tree unclassified, which is the exact event this file exists to refuse.
        """
        as_a_method = (
            "class _Gate:\n"
            "    def validate_hidden_thing(self, paths):\n        return []\n"
            "    class Inner:\n"
            "        def validate_deeper(self, paths):\n            return []\n"
        )
        self.assertEqual(
            _validators_in(as_a_method, "fake"),
            {"fake._Gate.validate_hidden_thing", "fake._Gate.Inner.validate_deeper"},
        )

    def test_a_local_helper_is_not_mistaken_for_a_gate(self) -> None:
        """The other half: a discovery step with false positives gets exempted into silence.

        A ``def validate_*`` inside a function body is a closure nothing outside can call,
        so classifying it would mean adding rows for names that gate nothing — and a table
        that carries junk rows is one people learn to add exemptions to.
        """
        nested = (
            "def outer(paths):\n"
            "    def validate_inner(x):\n        return []\n"
            "    return validate_inner(paths)\n"
        )
        self.assertEqual(_validators_in(nested, "fake"), set())


class TheDeclaredFieldsAreRealTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = _fresh_run(self._tmp)

    def test_every_declared_path_resolves(self) -> None:
        """A stale ``RunPaths`` field name would leave a row describing a gate that moved."""
        known_filenames = _src_blob()
        for gate in GATES:
            for token in gate.decides_on:
                with self.subTest(gate=gate.name, token=token):
                    if token.startswith("repo:"):
                        self.assertTrue(_resolve(self.paths, token).exists(), token)
                    elif hasattr(self.paths, token):
                        self.assertIsInstance(getattr(self.paths, token), Path)
                    else:
                        self.assertIn(
                            ".", token, f"{token} is neither a RunPaths field nor a filename"
                        )
                        self.assertIn(
                            Path(token).name,
                            known_filenames,
                            f"no module under src/ mentions {token}",
                        )

    def test_a_gate_that_reads_workspace_may_not_call_itself_harness(self) -> None:
        """The one implication the tree can check for itself.

        Not the converse: ``stages/`` is at the run root and the agent writes it. What
        ``workspace/`` marks is where every stage prompt sends the agent, which is why a
        stamp moved out of it is worth something at all.
        """
        for gate in GATES:
            writable = [
                token
                for token in gate.decides_on
                if not token.startswith("repo:")
                and _resolve(self.paths, token).is_relative_to(self.paths.workspace_root)
            ]
            with self.subTest(gate=gate.name):
                if gate.trust == HARNESS:
                    self.assertEqual(
                        writable, [], f"{gate.name} is called harness-written but reads {writable}"
                    )
                elif gate.trust != NO_FIELD and not writable:
                    self.assertIn(
                        gate.name,
                        AGENT_WRITTEN_OUTSIDE_WORKSPACE,
                        f"{gate.name} claims {gate.trust} but declares nothing under "
                        "workspace/; either it is harness-written, or a field is missing, "
                        "or it belongs in AGENT_WRITTEN_OUTSIDE_WORKSPACE with a reason",
                    )

    def test_the_outside_workspace_exemptions_are_still_needed(self) -> None:
        """An exemption for a row that now reads workspace/ is a lie the next reader inherits."""
        by_name = {gate.name: gate for gate in GATES}
        for name, reason in sorted(AGENT_WRITTEN_OUTSIDE_WORKSPACE.items()):
            with self.subTest(gate=name):
                self.assertIn(name, by_name, f"{name} is exempted and is not in the table")
                self.assertGreaterEqual(len(reason), 60)
                self.assertEqual(
                    [
                        token
                        for token in by_name[name].decides_on
                        if not token.startswith("repo:")
                        and _resolve(self.paths, token).is_relative_to(self.paths.workspace_root)
                    ],
                    [],
                    f"{name} now reads workspace/; drop it from AGENT_WRITTEN_OUTSIDE_WORKSPACE",
                )

    def test_the_skill_pack_gate_has_no_run_time_caller(self) -> None:
        """The one row whose reason turns on a caller nobody has, so the reason is checked.

        ``run_skills.validate_skill_pack`` is HARNESS on two grounds: it reads
        ``src/skills/`` in the AutoR checkout, and nothing in a run invokes it — the suite
        is what runs it, over the shipped pack. The first ground is checked by
        ``test_a_gate_that_reads_workspace_may_not_call_itself_harness``; this checks the
        second. If a stage or the manager starts calling it, it becomes a gate over the
        copy installed at ``.claude/skills/`` inside the run, which is a different row.
        """
        callers = [
            path.name
            for path in [REPO / "main.py", *sorted((REPO / "src").glob("*.py"))]
            if "validate_skill_pack(" in path.read_text(encoding="utf-8")
            and path.name != "run_skills.py"
        ]
        self.assertEqual(
            callers,
            [],
            "validate_skill_pack now runs inside a run; reclassify the row against the "
            f"pack installed under the run's .claude/skills/ (callers: {callers})",
        )
        source = (REPO / "src" / "run_skills.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("validate_skill_pack("), 1, "only the definition")

    def test_every_row_carries_a_trust_level_and_a_reason(self) -> None:
        for gate in GATES:
            with self.subTest(gate=gate.name):
                self.assertIn(gate.trust, TRUST_LEVELS)
                self.assertGreaterEqual(
                    len(gate.why), 60, f"{gate.name}'s reason is too short to be one"
                )
                if gate.trust == NO_FIELD:
                    self.assertEqual(gate.decides_on, ())
                else:
                    self.assertTrue(gate.decides_on, f"{gate.name} declares no field")


class TheBelievedAllowlistTests(unittest.TestCase):
    """The defect class, held to a demonstration rather than to a sentence."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_every_believed_row_has_a_witness(self) -> None:
        believed = {gate.name for gate in GATES if gate.trust == BELIEVED}
        self.assertEqual(
            sorted(believed),
            sorted(WITNESSES),
            "a row may only be called believed with a test that shows the field moving "
            "the verdict",
        )

    def test_each_witness_shows_the_field_moving_the_verdict(self) -> None:
        for name, witness in sorted(WITNESSES.items()):
            with self.subTest(gate=name):
                before, after = witness(_fresh_run(self._tmp))
                self.assertNotEqual(
                    before, after, f"{name} is on the believed list but the edit changed nothing"
                )

    def test_the_scorecard_rewrite_turns_drop_into_keep(self) -> None:
        """Named outcomes, because ``before != after`` would also pass on two wrong ones.

        The card is the run's answer to "which of these should I have turned on". Rewriting
        one integer in a ledger AutoR wrote — into a directory the agent is told to work in
        — moves it from "changed nothing and can be turned off" to "earned its cost".
        """
        for key in sorted(_SCORECARD_LEDGERS):
            with self.subTest(feature=key):
                measured, forged = _scorecard_witness(key)(_fresh_run(self._tmp))
                self.assertEqual((measured, forged), (DROP, KEEP))

    def test_the_fixed_row_stays_fixed(self) -> None:
        """#203, #206 and this branch. A regression here is the family reopening.

        Named individually because these three are the ones a stamp already closed, so a
        row of theirs quietly moving to ``believed`` would look like an honest
        reclassification rather than a lost gate.
        """
        by_name = {gate.name: gate for gate in GATES}
        for name in (
            "preregistration.validate_preregistration",
            "report_plan.validate_report_plan",
            "validity_review.validate_validity_response",
            "guard:validity_chain",
        ):
            self.assertEqual(by_name[name].trust, CROSS_CHECKED, name)

    def test_each_stamp_a_row_relies_on_is_outside_the_workspace(self) -> None:
        paths = _fresh_run(self._tmp)
        for token in (
            "preregistration_stamp.json",
            "report_plan_stamp.json",
            "validity_review_stamp.json",
        ):
            with self.subTest(stamp=token):
                stamp = _resolve(paths, token)
                self.assertFalse(stamp.is_relative_to(paths.workspace_root))
                self.assertTrue(stamp.is_relative_to(paths.run_root))


if __name__ == "__main__":
    unittest.main()
