from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .utils import FIGURE_SUFFIXES, MACHINE_DATA_SUFFIXES, RESULT_SUFFIXES, RunPaths


@dataclass(frozen=True)
class ArtifactRecord:
    category: str
    rel_path: str
    filename: str
    suffix: str
    size_bytes: int
    updated_at: str
    schema: dict[str, object] = field(default_factory=dict)
    #: Which stage's execution window this file first appeared in, read off
    #: :mod:`src.provenance`. Empty for a file no stage boundary has observed yet —
    #: this index is written mid-stage as well as at the end of one, and a record
    #: that guessed an attribution would be worse than one that declines to.
    produced_by_stage: str = ""
    #: Which stage last changed the bytes. Equal to ``produced_by_stage`` until
    #: something rewrites the file.
    last_written_by_stage: str = ""
    #: A fresh name for this version, never reused. A consumer that recorded a uid
    #: and reads a different one knows its input changed without comparing values —
    #: which is what a stage re-run after a rollback produces, byte-identical output
    #: and all.
    version_uid: str = ""
    content_hash: str = ""
    #: False once a rollback has withdrawn the stage that produced this file. The
    #: record stays in the index: a reader has to be able to see that the file is
    #: still on disk and no longer counts.
    live: bool = True
    #: True when the stage that last wrote this file was skipped rather than approved.
    #: Orthogonal to ``live``, and deliberately so: the file still counts everywhere a
    #: live one does, because a skip is a decision to continue past a failure rather than
    #: to repudiate the work. What the flag adds is that a reader can tell work the run
    #: accepted from residue it merely kept.
    from_unreviewed_stage: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "rel_path": self.rel_path,
            "filename": self.filename,
            "suffix": self.suffix,
            "size_bytes": self.size_bytes,
            "updated_at": self.updated_at,
            "schema": self.schema,
            "produced_by_stage": self.produced_by_stage,
            "last_written_by_stage": self.last_written_by_stage,
            "version_uid": self.version_uid,
            "content_hash": self.content_hash,
            "live": self.live,
            "from_unreviewed_stage": self.from_unreviewed_stage,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ArtifactRecord":
        return cls(
            category=str(payload.get("category", "")).strip(),
            rel_path=str(payload.get("rel_path", "")).strip(),
            filename=str(payload.get("filename", "")).strip(),
            suffix=str(payload.get("suffix", "")).strip(),
            size_bytes=int(payload.get("size_bytes", 0)),
            updated_at=str(payload.get("updated_at", "")).strip(),
            schema=dict(payload.get("schema", {})),
            produced_by_stage=str(payload.get("produced_by_stage", "")).strip(),
            last_written_by_stage=str(payload.get("last_written_by_stage", "")).strip(),
            version_uid=str(payload.get("version_uid", "")).strip(),
            content_hash=str(payload.get("content_hash", "")).strip(),
            live=bool(payload.get("live", True)),
            from_unreviewed_stage=bool(payload.get("from_unreviewed_stage", False)),
        )


@dataclass(frozen=True)
class ArtifactIndex:
    generated_at: str
    #: Live artifacts only. What a consumer means by "how much has this run produced"
    #: is what still counts, and a withdrawn file counts for nothing — it is on disk
    #: because AutoR could not always restore what preceded it, not because the run
    #: stands behind it.
    artifact_count: int
    counts_by_category: dict[str, int]
    #: Every file found, withdrawn ones included and marked. The count above says what
    #: the run has; this list says what is on the disk, and after a rollback those are
    #: two different questions.
    artifacts: list[ArtifactRecord]
    withdrawn_count: int = 0
    #: How many of the counted artifacts came from a stage that was skipped rather than
    #: approved. Counted *within* ``artifact_count`` rather than subtracted from it.
    unreviewed_count: int = 0

    @property
    def live_artifacts(self) -> list[ArtifactRecord]:
        return [artifact for artifact in self.artifacts if artifact.live]

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "artifact_count": self.artifact_count,
            "withdrawn_count": self.withdrawn_count,
            "unreviewed_count": self.unreviewed_count,
            "counts_by_category": dict(self.counts_by_category),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ArtifactIndex":
        artifacts = [
            ArtifactRecord.from_dict(item)
            for item in payload.get("artifacts", [])
            if isinstance(item, dict)
        ]
        live = [artifact for artifact in artifacts if artifact.live]
        return cls(
            generated_at=str(payload.get("generated_at", "")).strip(),
            artifact_count=int(payload.get("artifact_count", len(live))),
            counts_by_category={
                str(key): int(value)
                for key, value in dict(payload.get("counts_by_category", {})).items()
            },
            artifacts=artifacts,
            withdrawn_count=int(payload.get("withdrawn_count", len(artifacts) - len(live))),
            unreviewed_count=int(
                payload.get(
                    "unreviewed_count",
                    len([item for item in live if item.from_unreviewed_stage]),
                )
            ),
        )


def is_autor_own_record(paths: RunPaths, path: Path) -> bool:
    """Whether a workspace file is AutoR's own bookkeeping rather than research output.

    One rule with two readers. `write_experiment_manifest` runs on the way *into*
    every stage from 05 on — `information_flow` declares the manifest as an inbound
    channel — so it is rewritten inside the stage's own execution window on every
    run. Counted as output, a Stage 05 that produced literally nothing scored a third
    of `artifact_breadth` off a file whose own body reads `result_artifact_count: 0`.
    At Stages 03 and 04 it was worse than wrong, it was *noisy*: the manifest write
    and the next stage's start marker land in the same clock tick often enough to
    make the score flicker on byte-identical inputs.

    `src.rubric` and this module both had to know the rule and only this one did.
    `RECORD_ARTIFACTS` is the list `experiment_manifest` already keeps of the files
    it excludes from its own result set, so there is no third spelling.
    """
    from .experiment_manifest import RECORD_ARTIFACTS

    if path.name.endswith(".schema.json"):
        return True
    try:
        relative = path.relative_to(paths.workspace_root).as_posix()
    except ValueError:
        return False
    return relative in RECORD_ARTIFACTS



def write_artifact_index(paths: RunPaths) -> ArtifactIndex:
    artifacts = _scan_artifacts(paths)
    live = [artifact for artifact in artifacts if artifact.live]
    counts_by_category = {
        category: len([artifact for artifact in live if artifact.category == category])
        for category in ("data", "results", "figures")
    }
    index = ArtifactIndex(
        generated_at=datetime.now().isoformat(timespec="seconds"),
        artifact_count=len(live),
        counts_by_category=counts_by_category,
        artifacts=artifacts,
        withdrawn_count=len(artifacts) - len(live),
        unreviewed_count=len([item for item in live if item.from_unreviewed_stage]),
    )
    paths.artifact_index.write_text(
        json.dumps(index.to_dict(), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return index


def ensure_artifact_index(paths: RunPaths) -> ArtifactIndex:
    index = load_artifact_index(paths.artifact_index)
    if index is not None:
        return index
    return write_artifact_index(paths)


def load_artifact_index(path: Path) -> ArtifactIndex | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ArtifactIndex.from_dict(payload)


def format_artifact_index_for_prompt(index: ArtifactIndex, max_entries_per_category: int = 5) -> str:
    if not index.live_artifacts:
        return "No structured data, result, or figure artifacts have been indexed yet."

    lines = [
        f"Artifact index generated at: {index.generated_at}",
        f"Indexed artifacts: {index.artifact_count}",
    ]
    if index.withdrawn_count:
        # Said out loud rather than left as a silent subtraction. A stage that sees
        # files under `workspace/data` and an index reporting fewer is owed the reason,
        # and the reason is that a rollback withdrew the stage that wrote them.
        lines.append(
            f"Withdrawn by a rollback and not counted: {index.withdrawn_count} "
            "(still on disk; do not build on them)"
        )
    if index.unreviewed_count:
        # Counted, and flagged. These come from a stage that ran out of attempts and was
        # skipped, so the run never accepted them -- but it did not repudiate them either,
        # and the artifacts are frequently the only thing such a run has. Hiding them
        # would take real measurements away from the stage that has to write up what the
        # run actually found; saying nothing would let that stage treat residue as
        # evidence. The honest position is the third one: they are here, and they are not
        # accepted work.
        lines.append(
            f"Of those, {index.unreviewed_count} were last written by a stage that was "
            "skipped rather than approved. They are real files and may be worth using, "
            "and no reviewer accepted them -- say so if you rely on one."
        )
    for category in ("data", "results", "figures"):
        entries = [
            artifact
            for artifact in index.artifacts
            if artifact.category == category and artifact.live
        ]
        if not entries:
            continue
        lines.append(f"\n### {category.title()}")
        for artifact in entries[:max_entries_per_category]:
            schema_bits = _schema_summary(artifact.schema)
            suffix_label = artifact.suffix.lstrip(".") or "file"
            summary = f"- `{artifact.rel_path}` ({suffix_label}, {artifact.size_bytes} bytes)"
            if schema_bits:
                summary += f" | {schema_bits}"
            lines.append(summary)
        remaining = len(entries) - max_entries_per_category
        if remaining > 0:
            lines.append(f"- ... {remaining} more {category} artifacts indexed.")

    return "\n".join(lines)


def indexed_artifacts_for_category(index: ArtifactIndex, category: str) -> list[dict[str, object]]:
    """The live artifacts of one category.

    Withdrawn ones are dropped here rather than marked, because the two callers —
    ``experiment_manifest`` and ``writing_manifest`` — are building the run's statement
    of what it produced. A manifest that indexed a withdrawn result would hand Stage 07
    a result file to write about that the run had already taken back, which is the
    failure ``_skip_stage`` patched by hand at one path and this closes at all of them.
    """

    return [
        artifact.to_dict()
        for artifact in index.artifacts
        if artifact.category == category and artifact.live
    ]


def _scan_artifacts(paths: RunPaths) -> list[ArtifactRecord]:
    from .provenance import load_ledger, unreviewed_paths

    unreviewed = unreviewed_paths(paths)
    # Read once. The index is rewritten on every stage boundary and by three other
    # callers, and re-reading the ledger per file would make the scan quadratic in a
    # run's own artifact count.
    ledger = load_ledger(paths)
    records: list[ArtifactRecord] = []
    for category, directory, suffixes in (
        ("data", paths.data_dir, MACHINE_DATA_SUFFIXES),
        ("results", paths.results_dir, RESULT_SUFFIXES),
        ("figures", paths.figures_dir, FIGURE_SUFFIXES),
        # In markdown mode the report's own figures live beside it rather than in
        # workspace/figures, and the writing manifest is built from this index — leaving them
        # out would show Stage 07 an empty figure inventory for the figures it just made.
        ("figures", paths.report_images_dir, FIGURE_SUFFIXES),
    ):
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            if is_autor_own_record(paths, path):
                continue
            stat = path.stat()
            rel_path = str(path.relative_to(paths.workspace_root))
            attribution = ledger.entries.get(Path(rel_path).as_posix())
            records.append(
                ArtifactRecord(
                    category=category,
                    rel_path=rel_path,
                    filename=path.name,
                    suffix=path.suffix.lower(),
                    size_bytes=stat.st_size,
                    updated_at=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                    schema=_infer_schema(path, category, paths.workspace_root),
                    produced_by_stage=attribution.produced_by_stage if attribution else "",
                    last_written_by_stage=(
                        attribution.last_written_by_stage if attribution else ""
                    ),
                    version_uid=attribution.version_uid if attribution else "",
                    content_hash=attribution.content_hash if attribution else "",
                    # Unattributed files count. Only an explicit withdrawal takes one
                    # out, for the same reason `provenance.is_live` fails open.
                    live=attribution.live if attribution else True,
                    from_unreviewed_stage=Path(rel_path).as_posix() in unreviewed,
                )
            )
    return records


def _infer_schema(path: Path, category: str, workspace_root: Path) -> dict[str, object]:
    sidecar_path = path.parent / f"{path.name}.schema.json"
    if sidecar_path.exists():
        try:
            declared = json.loads(sidecar_path.read_text(encoding="utf-8"))
            return {
                "source": "declared",
                "sidecar_path": str(sidecar_path.relative_to(workspace_root)),
                "definition": declared,
            }
        except json.JSONDecodeError:
            return {
                "source": "declared",
                "sidecar_path": str(sidecar_path.relative_to(workspace_root)),
                "error": "invalid_json",
            }

    suffix = path.suffix.lower()
    if suffix == ".json":
        return _infer_json_schema(path)
    if suffix == ".jsonl":
        return _infer_jsonl_schema(path)
    if suffix in {".csv", ".tsv"}:
        return _infer_tabular_schema(path, delimiter="\t" if suffix == ".tsv" else ",")
    if suffix in {".yaml", ".yml"}:
        return {"source": "inferred", "kind": "yaml_document"}
    if suffix == ".parquet":
        return {"source": "inferred", "kind": "parquet_table"}
    if suffix == ".npz":
        return {"source": "inferred", "kind": "numpy_archive"}
    if suffix == ".npy":
        return {"source": "inferred", "kind": "numpy_array"}
    if category == "figures":
        return {"source": "inferred", "kind": "figure", "format": suffix.lstrip(".")}
    return {"source": "inferred", "kind": "file"}


def _infer_json_schema(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"source": "inferred", "kind": "json", "error": "invalid_json"}

    if isinstance(payload, dict):
        return {
            "source": "inferred",
            "kind": "object",
            "keys": sorted(str(key) for key in payload.keys())[:20],
        }
    if isinstance(payload, list):
        item_keys: set[str] = set()
        for item in payload[:20]:
            if isinstance(item, dict):
                item_keys.update(str(key) for key in item.keys())
        schema: dict[str, object] = {
            "source": "inferred",
            "kind": "array",
            "item_count": len(payload),
        }
        if item_keys:
            schema["item_keys"] = sorted(item_keys)
        return schema
    return {
        "source": "inferred",
        "kind": type(payload).__name__,
    }


def _infer_jsonl_schema(path: Path) -> dict[str, object]:
    row_count = 0
    keys: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            row_count += 1
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                return {"source": "inferred", "kind": "jsonl", "error": "invalid_jsonl"}
            if isinstance(payload, dict):
                keys.update(str(key) for key in payload.keys())

    schema: dict[str, object] = {
        "source": "inferred",
        "kind": "jsonl",
        "row_count": row_count,
    }
    if keys:
        schema["keys"] = sorted(keys)
    return schema


def _infer_tabular_schema(path: Path, delimiter: str) -> dict[str, object]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        rows = list(reader)

    if not rows:
        return {"source": "inferred", "kind": "table", "columns": [], "row_count": 0}

    header = [column.strip() for column in rows[0]]
    return {
        "source": "inferred",
        "kind": "table",
        "columns": header,
        "row_count": max(len(rows) - 1, 0),
    }


def _schema_summary(schema: dict[str, object]) -> str:
    if not schema:
        return ""

    kind = str(schema.get("kind") or schema.get("source") or "").strip()
    parts: list[str] = [kind] if kind else []

    if isinstance(schema.get("columns"), list) and schema["columns"]:
        columns = ", ".join(str(column) for column in schema["columns"][:6])
        parts.append(f"columns={columns}")
    if isinstance(schema.get("keys"), list) and schema["keys"]:
        keys = ", ".join(str(key) for key in schema["keys"][:6])
        parts.append(f"keys={keys}")
    if isinstance(schema.get("item_keys"), list) and schema["item_keys"]:
        keys = ", ".join(str(key) for key in schema["item_keys"][:6])
        parts.append(f"item_keys={keys}")
    if "row_count" in schema:
        parts.append(f"rows={schema['row_count']}")
    if "item_count" in schema:
        parts.append(f"items={schema['item_count']}")
    if "sidecar_path" in schema:
        parts.append(f"schema={schema['sidecar_path']}")
    if "error" in schema:
        parts.append(f"error={schema['error']}")

    return ", ".join(part for part in parts if part)
