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

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "rel_path": self.rel_path,
            "filename": self.filename,
            "suffix": self.suffix,
            "size_bytes": self.size_bytes,
            "updated_at": self.updated_at,
            "schema": self.schema,
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
        )


@dataclass(frozen=True)
class ArtifactIndex:
    generated_at: str
    artifact_count: int
    counts_by_category: dict[str, int]
    artifacts: list[ArtifactRecord]

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "artifact_count": self.artifact_count,
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
        return cls(
            generated_at=str(payload.get("generated_at", "")).strip(),
            artifact_count=int(payload.get("artifact_count", len(artifacts))),
            counts_by_category={
                str(key): int(value)
                for key, value in dict(payload.get("counts_by_category", {})).items()
            },
            artifacts=artifacts,
        )


def write_artifact_index(paths: RunPaths) -> ArtifactIndex:
    artifacts = _scan_artifacts(paths)
    counts_by_category = {
        category: len([artifact for artifact in artifacts if artifact.category == category])
        for category in ("data", "results", "figures")
    }
    index = ArtifactIndex(
        generated_at=datetime.now().isoformat(timespec="seconds"),
        artifact_count=len(artifacts),
        counts_by_category=counts_by_category,
        artifacts=artifacts,
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
    if not index.artifacts:
        return "No structured data, result, or figure artifacts have been indexed yet."

    lines = [
        f"Artifact index generated at: {index.generated_at}",
        f"Indexed artifacts: {index.artifact_count}",
    ]
    for category in ("data", "results", "figures"):
        entries = [artifact for artifact in index.artifacts if artifact.category == category]
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
    return [
        artifact.to_dict()
        for artifact in index.artifacts
        if artifact.category == category
    ]


def _scan_artifacts(paths: RunPaths) -> list[ArtifactRecord]:
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
            if path.name.endswith(".schema.json"):
                continue
            if category == "results" and path.name == "experiment_manifest.json":
                continue
            stat = path.stat()
            records.append(
                ArtifactRecord(
                    category=category,
                    rel_path=str(path.relative_to(paths.workspace_root)),
                    filename=path.name,
                    suffix=path.suffix.lower(),
                    size_bytes=stat.st_size,
                    updated_at=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                    schema=_infer_schema(path, category, paths.workspace_root),
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
