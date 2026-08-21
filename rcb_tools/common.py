"""Shared setup for every ResearchClawBench script here.

Everything lives on durable storage. The previous generation of these scripts, the RCB
checkout and both batches' state files were all under /tmp, which was reclaimed when the
disk filled -- taking the running batches with it. The workspaces survived only because
they had already been moved to /rmeng_data. So: code in ~/rcb_tools (NFS home), checkout
and workspaces on /rmeng_data, nothing that matters under /tmp.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
RCB = Path("/rmeng_data/robtang/rcb/ResearchClawBench")
RUNS = Path("/rmeng_data/robtang/rcb_runs")
RESULTS = Path.home() / "rcb_results"

sys.path.insert(0, str(RCB))
sys.path.insert(0, str(TOOLS))

# score.py refuses to run unless all three are set, and returns `{"error": ...}` rather than
# raising -- which a caller records as "no usable score", indistinguishable from a judge that
# answered and failed. Key and endpoint are placeholders because Gpt51Judge reads the real
# ones from disk; JUDGE_MODEL_NAME is not a placeholder and was once the one missing.
os.environ.setdefault("JUDGE_API_KEY", "unused")
os.environ.setdefault("JUDGE_API_BASE", "unused")
os.environ.setdefault("JUDGE_MODEL_NAME", "gpt-5.1")


def use_workspace_root(root: Path):
    """Point RCB's harness at `root`. Both modules bind the constant at import."""
    root.mkdir(parents=True, exist_ok=True)
    import evaluation.config as cfg
    import evaluation.run_task as rt
    cfg.WORKSPACES_DIR = root
    rt.WORKSPACES_DIR = root
    return root


def judged_scorer():
    """`evaluation.score` with the gpt-5.1 judge swapped in."""
    import gpt51_judge
    import evaluation.score as score_mod
    score_mod.LLMAgent = gpt51_judge.Gpt51Judge
    return score_mod
