"""What counts as a file path in a stage summary.

Observed on a real ResearchClawBench run (Astronomy_000, ultralight-boson superradiance).
The rubric reported `11/29 referenced paths resolve` and named `1/f`, `sebhoof/bhsr` and
`alpha/l <= 1/2` among the failures. Those are mathematics and a GitHub slug, not paths.

The old rule was "a backticked span containing a slash". That mis-measures twice: the
grounding criterion scores the fraction of references that resolve, and `Files Produced`
validation requires every listed path to exist. On the earlier run the agent's rational
response was to stop writing mathematics in backticks -- a measurement that rewards
mangling the prose instead of improving the research.
"""

from __future__ import annotations

import unittest

from src.utils import _extract_path_references, looks_like_path_reference


class MathematicsIsNotAPathTest(unittest.TestCase):
    """Every one of these was reported as a non-resolving path by the real run."""

    OBSERVED = [
        "1/f",
        "alpha/l ≤ 1/2",
        "p(a*|M, mu, 1/f)",
        "tau_SR < tau_BH / ln(N_Delta)",
        "tau_BH / ln(N_Delta)",
        "(log mu, log 1/f)",
    ]

    def test_none_of_them_is_a_path(self) -> None:
        for span in self.OBSERVED:
            with self.subTest(span=span):
                self.assertFalse(looks_like_path_reference(span))

    def test_none_of_them_is_extracted_from_a_summary(self) -> None:
        markdown = " ".join(f"`{s}`" for s in self.OBSERVED)
        self.assertEqual(_extract_path_references(markdown), [])

    def test_a_repository_slug_is_not_a_path(self) -> None:
        """`sebhoof/bhsr` is a GitHub repo the survey cites, not a file on disk."""
        self.assertFalse(looks_like_path_reference("sebhoof/bhsr"))

    def test_a_bare_ratio_is_not_a_path(self) -> None:
        for span in ("m/s", "km/h", "1/2", "N/A"):
            with self.subTest(span=span):
                self.assertFalse(looks_like_path_reference(span))


class RealPathsStillCountTest(unittest.TestCase):
    def test_run_relative_roots_are_paths(self) -> None:
        for span in (
            "workspace/results/stage01.json",
            "workspace/literature/claims.json",
            "code/characterise.py",
            "outputs/summary.csv",
            "report/images/fig1.png",
            "stages/01_literature_survey.md",
            "src/utils.py",
            "tests/test_utils_contracts.py",
        ):
            with self.subTest(span=span):
                self.assertTrue(looks_like_path_reference(span))

    def test_a_directory_reference_is_a_path_even_without_an_extension(self) -> None:
        """A stage may legitimately point at a directory, and a missing one should still
        be reported -- the fix must not make every absence invisible."""
        self.assertTrue(looks_like_path_reference("data/samples/"))
        self.assertTrue(looks_like_path_reference("workspace/figures/"))

    def test_relative_and_absolute_forms_are_paths(self) -> None:
        for span in ("./out/fig.png", "../shared/data.csv", "/tmp/run/log.txt"):
            with self.subTest(span=span):
                self.assertTrue(looks_like_path_reference(span))

    def test_an_unrooted_file_with_an_extension_is_a_path(self) -> None:
        self.assertTrue(looks_like_path_reference("analysis/plot_spin.py"))

    def test_extraction_preserves_order_and_dedupes(self) -> None:
        markdown = "`code/a.py` then `code/b.py` then `code/a.py`"
        self.assertEqual(_extract_path_references(markdown), ["code/a.py", "code/b.py"])


class BoundaryTest(unittest.TestCase):
    def test_a_span_without_a_slash_is_never_a_path(self) -> None:
        """Unchanged from before: `pypdf`, `SuperRad`, tool names."""
        for span in ("pypdf", "SuperRad", "mcp__autor-search__web_search", "README.md"):
            with self.subTest(span=span):
                self.assertFalse(looks_like_path_reference(span))

    def test_whitespace_disqualifies(self) -> None:
        """Whitespace is the strongest signal that a span is prose, not a path."""
        self.assertFalse(looks_like_path_reference("some/path with a space.txt"))

    def test_comparison_and_logic_characters_disqualify(self) -> None:
        for span in ("a/b < c/d", "x/y = z", "p|q/r", "a/b → c", "u/v ± w"):
            with self.subTest(span=span):
                self.assertFalse(looks_like_path_reference(span))

    def test_an_overlong_span_is_rejected(self) -> None:
        self.assertEqual(_extract_path_references("`" + "a/" * 400 + "`"), [])

    def test_an_empty_or_blank_span_is_rejected(self) -> None:
        self.assertEqual(_extract_path_references("`` and `   `"), [])


class TheReportedRunTest(unittest.TestCase):
    """The exact mix from the observed summary, scored end to end."""

    MARKDOWN = (
        "The coupling is `1/f` and the ratio `alpha/l ≤ 1/2`, with `p(a*|M, mu, 1/f)`.\n"
        "Rates cross-checked against `sebhoof/bhsr`; the condition is "
        "`tau_SR < tau_BH / ln(N_Delta)`.\n"
        "Wrote `workspace/results/stage01_data_characterisation.json` and "
        "`code/stage01_data_characterisation.py`.\n"
        "Still missing: `data/samples/`.\n"
    )

    def test_only_the_three_real_paths_are_counted(self) -> None:
        self.assertEqual(
            _extract_path_references(self.MARKDOWN),
            [
                "workspace/results/stage01_data_characterisation.json",
                "code/stage01_data_characterisation.py",
                "data/samples/",
            ],
        )

    def test_the_old_rule_would_have_counted_eight(self) -> None:
        """Pins the size of the mis-measurement: 8 references, 5 of them mathematics."""
        import re

        old_rule = [
            c.strip() for c in re.findall(r"`([^`\n\r]+)`", self.MARKDOWN) if "/" in c.strip()
        ]
        self.assertEqual(len(old_rule), 8)
        self.assertEqual(len(_extract_path_references(self.MARKDOWN)), 3)


class CitationsAreNotPathsTest(unittest.TestCase):
    """A literature survey is full of DOIs and URLs, and both have a slash.

    Found by mutation, not by reading: dropping the `$` anchor from the extension pattern
    survived the first sweep, which meant nothing pinned where an extension may appear.
    Probing that turned up a live false positive -- `10.1103/PhysRevD.83.044026` ends in
    `.044026`, which is extension-shaped, so the DOI was being counted as a missing file.
    """

    DOIS = [
        "10.1103/PhysRevD.83.044026",
        "10.1103/PhysRevD.98.083006",
        "10.1088/1475-7516/2021/03/043",
        "10.1016/j.physrep.2020.09.002",
    ]
    URLS = [
        "arxiv.org/abs/2309.17453",
        "https://arxiv.org/abs/2309.17453",
        "github.com/sebhoof/bhsr",
        "media.neurips.cc/Conferences/NeurIPS2025/Styles.zip",
    ]

    def test_a_doi_is_not_a_path(self) -> None:
        for doi in self.DOIS:
            with self.subTest(doi=doi):
                self.assertFalse(looks_like_path_reference(doi))

    def test_a_url_is_not_a_path(self) -> None:
        for url in self.URLS:
            with self.subTest(url=url):
                self.assertFalse(looks_like_path_reference(url))

    def test_a_survey_full_of_citations_yields_no_phantom_paths(self) -> None:
        markdown = " ".join(f"`{c}`" for c in self.DOIS + self.URLS)
        self.assertEqual(_extract_path_references(markdown), [])

    def test_the_extension_must_end_the_segment(self) -> None:
        """Without the `$` anchor the DOI above matches on `.044026` mid-string."""
        self.assertFalse(looks_like_path_reference("10.1103/PhysRevD.83.044026"))
        self.assertTrue(looks_like_path_reference("results/PhysRevD.83.json"))

    def test_a_dotted_first_segment_is_a_domain_not_a_directory(self) -> None:
        self.assertFalse(looks_like_path_reference("example.com/data.csv"))
        self.assertTrue(looks_like_path_reference("example/data.csv"))
