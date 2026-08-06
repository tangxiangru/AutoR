#!/usr/bin/env python3
"""Standalone entry point for AutoR's Gemini-backed web search.

Operators are given the absolute path to this script because they run with the AutoR run
root as their working directory, not the repository root.

    python3 /abs/path/to/AutoR/tools/web_search.py "query terms" [--json] [--max-results N]
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.web_search import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
