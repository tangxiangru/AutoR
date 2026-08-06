"""Install AutoR's agent skills into a run directory.

The operator runs its agent CLI with ``cwd=run_root`` (see
``ClaudeOperator._prepare_invocation``), and Claude Code discovers project
skills at ``<cwd>/.claude/skills/<name>/SKILL.md``. So a skill only reaches the
operator if it is written into the *run* directory — the AutoR checkout's own
``.claude/`` is never on that path.

Skills are the pull-based half of prompt assembly. Every stage prompt is
concatenated up front — artifact index, manifests, decision ledger, researcher
profile, handoff — and grows monotonically through the run. Long-form craft
guidance (how to structure a results table, how to read a LaTeX error, what a
venue's checklist demands) does not belong there: it is needed by one stage, in
one situation, and paying for it in every prompt is the wrong trade. A skill is
loaded only when the model decides it is relevant.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .utils import RunPaths


SKILL_FILENAME = "SKILL.md"


@dataclass(frozen=True)
class SkillPackEntry:
    name: str
    description: str
    source_dir: Path


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Read the leading ``---`` block. Deliberately minimal — no YAML dependency.

    AutoR ships no third-party Python dependencies, and skill frontmatter is a
    flat ``key: value`` block, so a full parser would buy nothing.
    """
    if not text.startswith("---"):
        return {}
    lines = text.splitlines()
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def read_skill_pack(source_dir: Path) -> list[SkillPackEntry]:
    """Every well-formed skill under ``source_dir``, sorted by name."""
    if not source_dir.is_dir():
        return []
    entries: list[SkillPackEntry] = []
    for child in sorted(source_dir.iterdir()):
        skill_file = child / SKILL_FILENAME
        if not child.is_dir() or not skill_file.is_file():
            continue
        fields = _parse_frontmatter(skill_file.read_text(encoding="utf-8"))
        name = fields.get("name", "")
        description = fields.get("description", "")
        if not name or not description:
            continue
        entries.append(SkillPackEntry(name=name, description=description, source_dir=child))
    return entries


def validate_skill_pack(source_dir: Path) -> list[str]:
    """Problems that would stop a skill being discovered or chosen correctly.

    A malformed skill fails silently: the CLI simply does not list it, and the
    stage runs without guidance nobody notices is missing.
    """
    problems: list[str] = []
    if not source_dir.is_dir():
        return [f"Skill pack directory {source_dir} does not exist."]

    seen: set[str] = set()
    for child in sorted(source_dir.iterdir()):
        if child.name.startswith(".") or not child.is_dir():
            continue
        skill_file = child / SKILL_FILENAME
        if not skill_file.is_file():
            problems.append(f"{child.name}/ has no {SKILL_FILENAME}.")
            continue
        text = skill_file.read_text(encoding="utf-8")
        if not text.startswith("---"):
            problems.append(f"{child.name}/{SKILL_FILENAME} has no YAML frontmatter block.")
            continue
        fields = _parse_frontmatter(text)
        name = fields.get("name", "")
        description = fields.get("description", "")
        if not name:
            problems.append(f"{child.name}/{SKILL_FILENAME} frontmatter has no name.")
        elif name != child.name:
            problems.append(
                f"{child.name}/{SKILL_FILENAME} declares name {name!r}, which does not match its directory."
            )
        if not description:
            problems.append(f"{child.name}/{SKILL_FILENAME} frontmatter has no description.")
        elif len(description) < 40:
            # The description is the only thing the model sees when deciding
            # whether to open a skill. "Writing help" is not a decision input.
            problems.append(
                f"{child.name}/{SKILL_FILENAME} description is too short to route on: {description!r}"
            )
        if name in seen:
            problems.append(f"Duplicate skill name {name!r}.")
        seen.add(name)

    return problems


def install_run_skills(paths: RunPaths, source_dir: Path) -> list[str]:
    """Copy the skill pack into the run's ``.claude/skills/``.

    Idempotent and re-run on resume, so a run picks up skill edits without
    needing a fresh run directory. Returns the installed skill names.
    """
    entries = read_skill_pack(source_dir)
    paths.skills_dir.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []
    for entry in entries:
        destination = paths.skills_dir / entry.name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(entry.source_dir, destination)
        installed.append(entry.name)
    return installed


def format_skills_for_prompt(names: list[str]) -> str:
    if not names:
        return ""
    listed = ", ".join(f"`{name}`" for name in sorted(names))
    return (
        "Skills available in this run: "
        + listed
        + ".\n\nThese are loaded on demand — read one when the situation it "
        "describes comes up, not preemptively."
    )
