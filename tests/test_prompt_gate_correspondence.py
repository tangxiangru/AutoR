"""The prompts and the validators are two encodings of one contract.

``validate_stage_artifacts`` refuses a stage that did not write
``hypothesis_outcomes.json``. ``src/prompts/06_analysis.md`` is the only thing
that ever tells an agent to write it. Nothing connected them, so a prompt edit
that tidied the instruction away would produce runs that burn all five attempts,
get auto-skipped, and never say why — and every unit test would still pass.

**How the requirement list is derived.** Not by parsing the gate messages. A
first attempt did that and was useless twice over: every message is prefixed
with its own stage title, so a set difference never subtracts and Stage 08 looks
like it introduces fifteen requirements Stage 05 actually introduced; and worse,
conditional gates are invisible against an empty run, because
``validate_hypothesis_outcomes`` returns early when no preregistration exists.
A mutant that renamed ``hypothesis_outcomes.json`` to "the outcomes file"
passed.

So the list is derived from behaviour instead. A complete fake run is produced,
then each of its workspace artifacts is deleted in turn and every stage
revalidated. An artifact is load-bearing for the earliest stage whose gate
output changes when it disappears. That finds conditional gates, needs no
knowledge of message wording, and cannot drift from what the validators do.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.utils import STAGES, RunPaths, build_run_paths, validate_stage_artifacts


REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPT_DIR = REPO_ROOT / "src" / "prompts"

#: Artifacts no stage template needs to name, each paired with the thing that
#: does produce or request it. An exemption stated in prose is unrunnable, so
#: each names a file and a marker the test asserts is still there — an
#: exemption whose justification stops being true fails rather than sitting in a
#: comment.
SERVED_ELSEWHERE: dict[str, tuple[str, str]] = {
    # Written by the manager when Stage 06 is approved, from round_decision.json.
    "notes/research_rounds.json": ("src/research_rounds.py", "def record_round"),
    # The response format is injected at runtime, and only when the adversarial
    # reviewer actually raised something. With no findings there is no
    # requirement, so putting it in every template would be noise.
    "reviews/validity_response_05_experimentation.json": (
        "src/validity_review.py",
        "def format_findings_for_prompt",
    ),
    "reviews/validity_response_06_analysis.json": (
        "src/validity_review.py",
        "def format_findings_for_prompt",
    ),
    # AutoR writes these, and the agent must not. They became load-bearing when the
    # gate started refusing a workspace copy that disagrees with the stamp outside
    # `workspace/`; asking a prompt to tell the agent to produce the record of the
    # objections raised against it is the defect that refusal exists to close.
    "reviews/validity_review_05_experimentation.json": (
        "src/validity_review.py",
        "def _write_review_file",
    ),
    "reviews/validity_review_06_analysis.json": (
        "src/validity_review.py",
        "def _write_review_file",
    ),
}

#: Where a prompt should point when the agent chooses the filename itself.
DIRECTORY_PLACEHOLDER = {
    "figures": "{{WORKSPACE_FIGURES_DIR}}",
    "results": "{{WORKSPACE_RESULTS_DIR}}",
    "data": "{{WORKSPACE_DATA_DIR}}",
    "code": "{{WORKSPACE_CODE_DIR}}",
    "report/images": "{{WORKSPACE_REPORT_IMAGES_DIR}}",
    "reviews": "{{WORKSPACE_REVIEWS_DIR}}",
    "notes": "{{WORKSPACE_NOTES_DIR}}",
    "artifacts": "{{WORKSPACE_ARTIFACTS_DIR}}",
    "writing": "{{WORKSPACE_WRITING_DIR}}",
    "literature": "{{WORKSPACE_LITERATURE_DIR}}",
}

#: Source files that define what a stage must produce. A filename appearing
#: literally in one of them is a name the validators know, so the prompt has to
#: use that exact name; anything else is a name the agent invented for this run
#: and only the directory can be required. Deriving it beats hand-listing:
#: a hand-list of "agent-chosen" paths is where a fixed name goes to hide.
VALIDATOR_SOURCES = (
    "utils.py",
    "preregistration.py",
    "experimental_protocol.py",
    "report_plan.py",
    "validity_review.py",
    "research_rounds.py",
    "evidence_ledger.py",
    "experiment_manifest.py",
    "writing_manifest.py",
)


def _names_the_validators_know() -> set[str]:
    blob = "\n".join(
        (REPO_ROOT / "src" / name).read_text(encoding="utf-8")
        for name in VALIDATOR_SOURCES
        if (REPO_ROOT / "src" / name).is_file()
    )
    return set(re.findall(r"[\w]+\.(?:json|md|tex|txt|png|bib|pdf)", blob))


def _complete_run(destination: Path) -> RunPaths:
    """A fake run that passes every gate, used as the fixture to break."""
    result = subprocess.run(
        [
            sys.executable,
            "main.py",
            "--fake-operator",
            "--full-auto",
            "--goal",
            "Prompt/gate correspondence fixture.",
            "--runs-dir",
            str(destination),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=300,
    )
    roots = sorted(path for path in destination.iterdir() if path.is_dir())
    if result.returncode != 0 or len(roots) != 1:
        raise AssertionError(f"fixture run failed: {result.stdout[-3000:]}")
    return build_run_paths(roots[0])


def _load_bearing(paths: RunPaths) -> dict[str, str]:
    """Map each workspace artifact to the earliest stage that breaks without it."""
    baseline = {stage.slug: set(validate_stage_artifacts(stage, paths)) for stage in STAGES}
    owners: dict[str, str] = {}
    artifacts = sorted(
        item.relative_to(paths.workspace_root).as_posix()
        for item in paths.workspace_root.rglob("*")
        if item.is_file()
    )
    for relative in artifacts:
        with tempfile.TemporaryDirectory() as tmp:
            copy_root = Path(tmp) / "run"
            shutil.copytree(paths.run_root, copy_root)
            copy = build_run_paths(copy_root)
            (copy.workspace_root / relative).unlink()
            for stage in STAGES:
                if set(validate_stage_artifacts(stage, copy)) - baseline[stage.slug]:
                    owners[relative] = stage.slug
                    break
    return owners


def _prompts_for(slug: str, output_format: str) -> list[Path]:
    """The template(s) actually used for this stage in this run.

    Stage 07 forks on the output format. Accepting either file would let the
    LaTeX prompt cover for a requirement the markdown prompt dropped, and only
    one of them is ever loaded for a given run.
    """
    candidates = sorted(PROMPT_DIR.glob(f"{slug[:2]}_*.md"))
    markdown_variants = [path for path in candidates if path.stem.endswith("_markdown")]
    if not markdown_variants:
        return candidates
    if output_format == "markdown":
        return markdown_variants
    return [path for path in candidates if not path.stem.endswith("_markdown")]


class PromptGateCorrespondenceTest(unittest.TestCase):
    owners: dict[str, str]

    output_format: str

    @classmethod
    def setUpClass(cls) -> None:
        from src.utils import selected_output_format

        cls._tmp = tempfile.TemporaryDirectory()
        paths = _complete_run(Path(cls._tmp.name) / "runs")
        cls.output_format = selected_output_format(paths)
        cls.owners = _load_bearing(paths)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_the_fixture_actually_found_load_bearing_artifacts(self) -> None:
        """Control. Without this the real test passes vacuously on an empty map."""
        self.assertGreaterEqual(len(self.owners), 15, sorted(self.owners))
        for expected in (
            "literature/sources.json",
            "results/hypothesis_outcomes.json",
            "notes/round_decision.json",
            "artifacts/claim_provenance.json",
        ):
            self.assertIn(expected, self.owners)

    def test_every_load_bearing_artifact_is_asked_for(self) -> None:
        known = _names_the_validators_know()
        unserved: list[str] = []
        for relative, slug in sorted(self.owners.items()):
            if relative in SERVED_ELSEWHERE:
                continue
            candidates = _prompts_for(slug, self.output_format)
            self.assertTrue(candidates, f"no prompt found for {slug}")
            texts = [path.read_text(encoding="utf-8") for path in candidates]

            filename = Path(relative).name
            if filename in known:
                # The validators know this exact name, so the prompt must use it.
                needle = filename
            else:
                directory = relative.rsplit("/", 1)[0] if "/" in relative else ""
                needle = DIRECTORY_PLACEHOLDER.get(directory)
                if needle is None:
                    unserved.append(
                        f"{relative} is load-bearing for {slug} but lives in `{directory}`, "
                        "which has no placeholder a prompt could point at"
                    )
                    continue
            if not any(needle in text for text in texts):
                unserved.append(
                    f"{slug} breaks without `{relative}` but "
                    f"{[path.name for path in candidates]} does not ask for `{needle}`"
                )
        self.assertEqual(unserved, [], "\n" + "\n".join(unserved))

    def test_the_validator_name_list_is_not_empty(self) -> None:
        """Control: an empty `known` set turns every fixed name into a directory check."""
        known = _names_the_validators_know()
        for expected in ("hypothesis_outcomes.json", "claim_provenance.json", "round_decision.json"):
            self.assertIn(expected, known)

    def test_every_exemption_names_something_that_still_exists(self) -> None:
        for relative, (path_str, marker) in sorted(SERVED_ELSEWHERE.items()):
            with self.subTest(artifact=relative):
                path = REPO_ROOT / path_str
                self.assertTrue(path.is_file(), f"{path_str} is gone")
                self.assertIn(
                    marker,
                    path.read_text(encoding="utf-8"),
                    msg=f"the exemption for {relative} points at {path_str}, which no longer has {marker!r}",
                )

    def test_no_exemption_has_become_unnecessary(self) -> None:
        """A stale exemption silently hides a requirement from the test above."""
        stale = [
            relative
            for relative in SERVED_ELSEWHERE
            if relative in self.owners
            and any(
                Path(relative).name in path.read_text(encoding="utf-8")
                for path in _prompts_for(self.owners[relative], self.output_format)
            )
        ]
        self.assertEqual(stale, [], f"exempted but now named in the prompt: {stale}")


class PromptPlaceholderTest(unittest.TestCase):
    """A placeholder nothing substitutes is emitted literally into the prompt."""

    def test_no_prompt_uses_an_unknown_placeholder(self) -> None:
        substituter = (REPO_ROOT / "src" / "utils.py").read_text(encoding="utf-8")
        known = set(re.findall(r'"(\{\{[A-Z_]+\}\})"', substituter))
        self.assertGreater(len(known), 15, "failed to locate the substitution table")

        problems = [
            f"{path.name} uses {token}, which nothing substitutes"
            for path in sorted(PROMPT_DIR.glob("*.md"))
            for token in sorted(set(re.findall(r"\{\{[A-Z_]+\}\}", path.read_text(encoding="utf-8"))))
            if token not in known
        ]
        self.assertEqual(problems, [], "\n".join(problems))


class StageSummaryContractTest(unittest.TestCase):
    """Every stage prompt must still ask for the summary sections the validator requires."""

    def test_every_stage_prompt_names_its_output_path(self) -> None:
        for path in sorted(PROMPT_DIR.glob("0*.md")):
            with self.subTest(prompt=path.name):
                self.assertIn("{{STAGE_OUTPUT_PATH}}", path.read_text(encoding="utf-8"))

    def test_every_required_heading_is_shown_to_the_agent(self) -> None:
        """The contract lives in one place, and that place must still carry it.

        ``required_stage_output_template`` is appended to every stage prompt, so
        the templates legitimately do not restate the section list. That makes
        it the single point of failure: if a heading disappears from there,
        every stage starts failing ``validate_stage_markdown`` at once.
        """
        from src.utils import REQUIRED_STAGE_HEADINGS, required_stage_output_template

        shown = required_stage_output_template(STAGES[0])
        missing = [heading for heading in REQUIRED_STAGE_HEADINGS if f"## {heading}" not in shown]
        self.assertEqual(missing, [], f"the shared output template omits: {missing}")

    def test_the_shared_template_reaches_the_assembled_prompt(self) -> None:
        """A contract nothing injects is a contract the agent never sees."""
        assembler = (REPO_ROOT / "src" / "utils.py").read_text(encoding="utf-8")
        self.assertIn("required_stage_output_template(", assembler)


if __name__ == "__main__":
    unittest.main()
