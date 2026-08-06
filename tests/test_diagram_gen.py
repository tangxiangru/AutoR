from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.diagram_gen import inject_diagram_into_latex, post_writing_diagram_hook


class DiagramGenerationTests(unittest.TestCase):
    def test_inject_diagram_into_latex_inserts_after_section_and_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            method_tex = Path(tmp_dir) / "method.tex"
            method_tex.write_text(
                "\\section{Method}\n"
                "\\label{sec:method}\n"
                "Core method text.\n",
                encoding="utf-8",
            )

            inserted = inject_diagram_into_latex(
                method_tex,
                "../figures/method_overview.jpg",
                "Overview of the proposed method.",
            )

            self.assertTrue(inserted)
            content = method_tex.read_text(encoding="utf-8")
            self.assertIn("\\label{sec:method}", content)
            self.assertIn("\\begin{figure*}[t]", content)
            self.assertIn("\\includegraphics[width=0.95\\textwidth]{../figures/method_overview.jpg}", content)
            self.assertIn("\\label{fig:method_overview}", content)

    def test_inject_diagram_into_latex_does_not_duplicate_real_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            method_tex = Path(tmp_dir) / "method.tex"
            method_tex.write_text(
                "\\section{Method}\n"
                "\\begin{figure*}\n"
                "\\label{fig:method_overview}\n"
                "\\end{figure*}\n",
                encoding="utf-8",
            )

            inserted = inject_diagram_into_latex(
                method_tex,
                "../figures/method_overview.jpg",
                "Overview of the proposed method.",
            )

            self.assertFalse(inserted)
            content = method_tex.read_text(encoding="utf-8")
            self.assertEqual(content.count("\\label{fig:method_overview}"), 1)

    def test_inject_diagram_into_latex_ignores_comment_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            method_tex = Path(tmp_dir) / "method.tex"
            method_tex.write_text(
                "\\section{Method}\n"
                "% METHOD_DIAGRAM_PLACEHOLDER\n"
                "% Figure~\\ref{fig:method_overview} will be inserted later.\n"
                "Core method text.\n",
                encoding="utf-8",
            )

            inserted = inject_diagram_into_latex(
                method_tex,
                "../figures/method_overview.jpg",
                "Overview of the proposed method.",
            )

            self.assertTrue(inserted)
            content = method_tex.read_text(encoding="utf-8")
            self.assertNotIn("METHOD_DIAGRAM_PLACEHOLDER", content)
            self.assertEqual(content.count("\\label{fig:method_overview}"), 1)

    def test_post_writing_diagram_hook_skips_missing_or_short_method(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir) / "run"
            (run_root / "workspace" / "writing" / "sections").mkdir(parents=True, exist_ok=True)

            self.assertIsNone(post_writing_diagram_hook(run_root))

            method_tex = run_root / "workspace" / "writing" / "sections" / "method.tex"
            method_tex.write_text("\\section{Method}\nTiny.\n", encoding="utf-8")

            self.assertIsNone(post_writing_diagram_hook(run_root))

    def test_post_writing_diagram_hook_generates_image_and_injects_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir) / "run"
            method_tex = run_root / "workspace" / "writing" / "sections" / "method.tex"
            figures_dir = run_root / "workspace" / "figures"
            method_tex.parent.mkdir(parents=True, exist_ok=True)
            figures_dir.mkdir(parents=True, exist_ok=True)
            method_tex.write_text(
                "\\section{Method}\n"
                "This method description is intentionally long enough to trigger diagram generation. "
                "It explains the components, data flow, and reasoning behavior in a detailed way.\n",
                encoding="utf-8",
            )
            (run_root / "memory.md").write_text(
                "# Approved Run Memory\n\n## Approved Stage Summaries\n\nStage context.\n",
                encoding="utf-8",
            )

            def _fake_generate(method_text: str, figure_caption: str, output_path: Path, model_name: str = "gemini-2.5-flash") -> Path:
                output_path.write_bytes(b"fake image")
                return output_path

            with patch("src.diagram_gen.generate_method_diagram_sync", side_effect=_fake_generate):
                result = post_writing_diagram_hook(run_root, output_format="latex")

            self.assertEqual(result, figures_dir / "method_overview.jpg")
            self.assertTrue((figures_dir / "method_overview.jpg").exists())
            content = method_tex.read_text(encoding="utf-8")
            self.assertIn("../figures/method_overview.jpg", content)
            self.assertIn("\\label{fig:method_overview}", content)


if __name__ == "__main__":
    unittest.main()
