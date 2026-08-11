"""The result panel must not say a call both failed and succeeded.

`is_error` and `subtype` come from different places in the CLI's stream-json and
can disagree: a response cut mid-stream arrives as `is_error: true` with
`subtype: "success"`, because the CLI did finish emitting. Rendered
independently that produced

    | Claude Failed          |
    | Status     : success   |

which is the worst thing to read when reconstructing an unattended run hours
after it stopped — it asserts both that the call failed and that it did not.
Encountered for real while diagnosing an aborted four-hour benchmark run.
"""

from __future__ import annotations

import io
import unittest

from src.terminal_ui import TerminalUI


def _render(payload: dict) -> str:
    stream = io.StringIO()
    ui = TerminalUI(output_stream=stream)
    ui._render_result_event(payload)  # noqa: SLF001
    return stream.getvalue()


class ResultPanelTest(unittest.TestCase):
    def test_a_clean_success_reads_as_one(self) -> None:
        text = _render({"subtype": "success", "is_error": False, "num_turns": 3})
        self.assertIn("Claude Finished", text)
        self.assertIn("success", text)
        self.assertNotIn("flagged", text)

    def test_a_clean_failure_reads_as_one(self) -> None:
        text = _render({"subtype": "error", "is_error": True})
        self.assertIn("Claude Failed", text)
        self.assertNotIn("flagged", text)

    def test_a_disagreement_is_stated_rather_than_resolved_silently(self) -> None:
        """The real case: stream cut mid-response."""
        text = _render({"subtype": "success", "is_error": True, "num_turns": 32})
        self.assertIn("Claude Failed", text)
        self.assertIn("success", text, "the backend's own subtype is still worth showing")
        self.assertIn("flagged this call as failed", text)

    def test_a_missing_subtype_falls_back_to_the_error_flag(self) -> None:
        self.assertIn("error", _render({"is_error": True}))
        self.assertIn("success", _render({"is_error": False}))

    def test_the_panel_never_shows_an_unqualified_success_on_a_failed_call(self) -> None:
        """The property, independent of wording."""
        for subtype in ("success", "completed", "done"):
            with self.subTest(subtype=subtype):
                text = _render({"subtype": subtype, "is_error": True})
                status_line = next(
                    line for line in text.splitlines() if "Status" in line
                )
                self.assertNotEqual(
                    status_line.split(":", 1)[1].strip().rstrip("|").strip(),
                    subtype,
                    "a failed call renders a bare success status",
                )


if __name__ == "__main__":
    unittest.main()
