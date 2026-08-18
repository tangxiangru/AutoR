#!/usr/bin/env python3
"""Stage AIRS-Bench raw data and build a task workspace.

AIRS-Bench ships the task specifications but not the data: every task reads a Hugging Face
dataset that has been saved to disk under a shared raw-data directory, and its own
``prepare.py`` then carves the agent's view out of it. This tool does both halves and
nothing else, so the same workspace can be handed to :mod:`airs_agent` or to a bare CLI
control arm and the two arms differ only in the agent.

::

    python tools/airs_setup.py --list
    python tools/airs_setup.py --task TextualSimilaritySickSpearmanCorrelation \\
        --repo ~/airs-bench --raw-dir /data/airs-raw --workspace /runs/sick_autor

``--download-only`` stops after the raw dataset is on disk, which is the part that is
shared between every workspace for a task and worth doing once.

Two interpreters, because one cannot do both halves. Nine of the sixteen datasets are
script-based on the hub and ``datasets>=4`` refuses to load a script at all, while the
tasks themselves declare ``datasets==4.0.0``; ``--download-python`` therefore points at an
environment with ``datasets<4`` and ``--python`` at the task's own. Neither is imported
here — both are subprocesses — so this file and AutoR's test suite stay free of the
dependency.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.airsbench import (  # noqa: E402
    AirsTask,
    available_tasks,
    load_task,
    prepare_workspace,
    summarize_tasks,
    write_task_card,
)


def dataset_coordinates(task: AirsTask) -> tuple[str, str | None]:
    """``(hub repo id, config)`` for the dataset this task's ``prepare.py`` reads.

    Derived from the on-disk path the script expects rather than from ``metadata.yaml``'s
    ``dataset``/``config`` pair, because two tasks disagree with that pair: ``Pavithree/eli5``
    and ``Yelp/yelp_review_full`` are read without a config component. Staging by the
    composed name would put the data one directory away from where the script looks and the
    run would fail at Stage 04 with a ``FileNotFoundError`` instead of here.
    """
    parts = [part for part in task.raw_relpath.split("/") if part]
    if len(parts) >= 3:
        return "/".join(parts[:2]), parts[2]
    if len(parts) == 2:
        return "/".join(parts), (task.config or None)
    raise ValueError(f"{task.name}: cannot read a hub dataset id out of {task.raw_relpath!r}")


#: Downloader run in its own interpreter. See :func:`download_dataset` for why it is a
#: subprocess and not an import.
_DOWNLOAD_SNIPPET = """
import json, shutil, sys
from pathlib import Path
from datasets import load_dataset

repo_id, config, destination = sys.argv[1], sys.argv[2] or None, Path(sys.argv[3])
kwargs = {"name": config} if config else {}
try:
    dataset = load_dataset(repo_id, trust_remote_code=True, **kwargs)
except TypeError:
    # datasets >= 4 removed the argument along with the scripts it enabled.
    dataset = load_dataset(repo_id, **kwargs)
staging = destination.with_name(destination.name + ".partial")
if staging.exists():
    shutil.rmtree(staging)
staging.parent.mkdir(parents=True, exist_ok=True)
dataset.save_to_disk(str(staging))
if destination.exists():
    shutil.rmtree(destination)
staging.rename(destination)
print(json.dumps({"splits": list(dataset.keys()), "destination": str(destination)}))
"""


def download_dataset(
    task: AirsTask, raw_dir: Path, *, force: bool = False, python: str = sys.executable
) -> Path:
    """Save the task's dataset to disk in the layout ``prepare.py`` expects.

    Run in a subprocess under *python*, because the download and the task need different
    versions of the same library and there is no version that does both. Nine of the
    sixteen datasets are script-based on the hub, which ``datasets`` 4 removed outright
    (*"Dataset scripts are no longer supported"*) — so the download needs 3.x and
    ``trust_remote_code=True``, exactly as the benchmark's own
    ``datasets/prepare_hf_datasets_text.py`` does it. The tasks in turn declare
    ``datasets==4.0.0``. What crosses the version boundary is the saved Arrow directory,
    which both read with ``load_from_disk``.

    The save is staged under ``<name>.partial`` and renamed, so an interrupted download
    leaves no directory that the next run would mistake for complete data.
    """
    destination = Path(raw_dir).expanduser().resolve() / task.raw_relpath
    if destination.exists() and not force:
        print(f"[setup] {task.name}: raw data already at {destination}")
        return destination

    repo_id, config = dataset_coordinates(task)
    print(f"[setup] {task.name}: downloading {repo_id} (config={config}) -> {destination}")
    completed = subprocess.run(  # noqa: S603 - the command is composed here, not user text
        [python, "-c", _DOWNLOAD_SNIPPET, repo_id, config or "", str(destination)],
        capture_output=True,
        text=True,
    )
    sys.stderr.write(completed.stderr[-4000:])
    if completed.returncode != 0:
        raise RuntimeError(
            f"{task.name}: downloading {repo_id} exited {completed.returncode}. "
            f"The interpreter used was {python}; a script-based dataset needs one with "
            "datasets<4 installed, passed as --download-python."
        )
    print(f"[setup] {task.name}: {completed.stdout.strip().splitlines()[-1]}")
    return destination


def build_workspace(
    *,
    task: AirsTask,
    raw_dir: Path,
    workspace: Path,
    python: str,
    force: bool = False,
) -> dict[str, object]:
    workspace = Path(workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    result = prepare_workspace(
        task=task, raw_dir=raw_dir, workspace=workspace, python=python, force=force
    )
    write_task_card(workspace, task)
    staged = sorted(path.name for path in (workspace / "data").iterdir())
    print(f"[setup] {task.name}: workspace {workspace} data splits {staged}")
    return {
        "task": task.name,
        "workspace": str(workspace),
        "data_splits": staged,
        "prepare_skipped": result is None,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="airs_setup", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default="airs-bench", metavar="PATH",
                        help="Path to an airs-bench checkout.")
    parser.add_argument("--raw-dir", metavar="PATH",
                        help="Shared raw-data directory: where the Hugging Face datasets are "
                             "saved to disk and where every task's prepare.py reads from.")
    parser.add_argument("--task", action="append", default=[], metavar="NAME",
                        help="Task to stage. Repeatable.")
    parser.add_argument("--workspace", metavar="PATH",
                        help="Workspace to build. Only valid with exactly one --task.")
    parser.add_argument("--workspace-root", metavar="PATH",
                        help="Build one workspace per task under this directory, named after "
                             "the task.")
    parser.add_argument("--python", default=sys.executable, metavar="BIN",
                        help="Interpreter used to run the benchmark's prepare.py. Defaults to "
                             "the one running this script, which must therefore have the task's "
                             "packages if it is left at the default.")
    parser.add_argument("--download-python", metavar="BIN",
                        help="Interpreter used for the Hugging Face download. Nine of the "
                             "sixteen datasets are script-based on the hub, which datasets>=4 "
                             "refuses outright, so this usually needs to be an environment with "
                             "datasets<4. Defaults to --python.")
    parser.add_argument("--download-only", action="store_true",
                        help="Stage the raw dataset and stop, building no workspace.")
    parser.add_argument("--force", action="store_true",
                        help="Re-download and re-prepare even when the target already exists.")
    parser.add_argument("--list", action="store_true", help="List the shipped tasks and exit.")
    parser.add_argument("--json", metavar="PATH", help="Write a JSON record of what was staged.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = Path(args.repo).expanduser().resolve()

    if args.list:
        rows = summarize_tasks(repo)
        width = max((len(row["task"]) for row in rows), default=4)
        print(f"{'task'.ljust(width)}  {'metric':22} {'rows*':>7} {'sota':>10}  dataset")
        for row in rows:
            print(f"{row['task'].ljust(width)}  {row['metric']:22} "
                  f"{str(row['declared_rows']):>7} {row['sota']:>10}  {row['raw_relpath']}")
        print("\n* rows is the count the task *declares*. At least one task's declaration "
              "disagrees with the split its own prepare.py produces; the prepared split is "
              "what the evaluator counts.")
        print(f"\n{len(rows)} tasks under {repo}")
        return 0

    if not args.task:
        print("Nothing to do: pass --task NAME (repeatable) or --list.", file=sys.stderr)
        print("Available: " + ", ".join(available_tasks(repo)), file=sys.stderr)
        return 2
    if not args.raw_dir:
        print("--raw-dir is required unless --list is passed.", file=sys.stderr)
        return 2
    if args.workspace and len(args.task) != 1:
        print("--workspace names one directory, so it takes exactly one --task.", file=sys.stderr)
        return 2
    if not args.download_only and not (args.workspace or args.workspace_root):
        print("Pass --workspace, --workspace-root, or --download-only.", file=sys.stderr)
        return 2

    raw_dir = Path(args.raw_dir).expanduser().resolve()
    raw_dir.mkdir(parents=True, exist_ok=True)

    staged: list[dict[str, object]] = []
    for name in args.task:
        task = load_task(repo, name)
        download_dataset(task, raw_dir, force=args.force,
                         python=args.download_python or args.python)
        if args.download_only:
            staged.append({"task": task.name, "raw": str(raw_dir / task.raw_relpath)})
            continue
        workspace = (
            Path(args.workspace) if args.workspace
            else Path(args.workspace_root).expanduser() / task.name
        )
        staged.append(
            build_workspace(task=task, raw_dir=raw_dir, workspace=workspace,
                            python=args.python, force=args.force)
        )

    if args.json:
        Path(args.json).expanduser().write_text(
            json.dumps(staged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
