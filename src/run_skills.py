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

**Which skills a run is offered is itself a decision, and it was not being made.**
Before this module grew a router, every run in a field received the same pack, and
the model chose from it: measured over a 40-task ResearchClawBench arm, 16 skills
per run and 78 ``Skill`` calls in 789 hours of agent time, 1.75 distinct skills per
run. A description competes against every other description in the listing — 30
entries once Claude Code's own bundled skills are counted — so the pack gets less
useful as it grows, which is the wrong direction for a pack meant to grow.

Two filters narrow it, in order:

* ``discipline`` — a skill named ``<field>-...`` is installed only for a run in
  that field. Coarse: four tasks share a field, so this cannot distinguish them.
* ``applies_when`` / ``applies_unless`` — a regex over the run's own **research
  brief**, so a skill written for one shape of task is offered only to tasks of
  that shape. This is what makes two runs in the same field receive different
  packs.

The predicate deliberately reads the brief and not the task's identifier. A table
keyed on benchmark task ids would select the same tasks and generalise to nothing;
a predicate over what the task *asks for* is a claim about a kind of research
problem, and it can be wrong in public. ``tools/skill_selectivity.py`` prints what
each predicate selects over a directory of task statements, which is how a claim
of "this fires on the tasks it was written for" is checked before it lands.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .utils import STAGES, RunPaths, read_text, task_statement


SKILL_FILENAME = "SKILL.md"

#: Stage slugs a `stages:` field may name. Derived, not listed: a stage renamed in
#: `utils.STAGES` must not leave a skill pointing at a slug that no longer exists.
KNOWN_STAGE_SLUGS = frozenset(stage.slug for stage in STAGES)

#: A skill carrying neither predicate is offered to every run, which is what all
#: forty-two skills did before the router existed.
UNCONDITIONAL = ""


@dataclass(frozen=True)
class SkillPackEntry:
    name: str
    description: str
    source_dir: Path
    #: Case-insensitive regex over the research brief. Empty means "always".
    applies_when: str = UNCONDITIONAL
    #: Case-insensitive regex that vetoes the skill even when ``applies_when``
    #: matches. Empty means "never vetoed".
    applies_unless: str = UNCONDITIONAL
    #: Stage slugs whose prompt should name this skill. Empty means the skill is
    #: pull-only and no prompt announces it.
    stages: frozenset[str] = field(default_factory=frozenset)

    @property
    def task_scoped(self) -> bool:
        return bool(self.applies_when or self.applies_unless)

    def applies_to(self, brief: str) -> bool:
        """Whether this skill is offered to a run with this research brief.

        A malformed regex is treated as "does not apply" rather than raising:
        ``validate_skill_pack`` is the place that refuses one, and a run must not
        die because a skill file is wrong. The same reasoning as
        ``Manager._install_skills`` catching ``OSError``.
        """
        if not self.task_scoped:
            return True
        try:
            if self.applies_when and not re.search(self.applies_when, brief, re.IGNORECASE):
                return False
            if self.applies_unless and re.search(self.applies_unless, brief, re.IGNORECASE):
                return False
        except re.error:
            return False
        return True


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
        entries.append(
            SkillPackEntry(
                name=name,
                description=description,
                source_dir=child,
                applies_when=fields.get("applies_when", UNCONDITIONAL),
                applies_unless=fields.get("applies_unless", UNCONDITIONAL),
                stages=frozenset(
                    slug.strip() for slug in fields.get("stages", "").split(",") if slug.strip()
                ),
            )
        )
    return entries


#: The part of the task statement that states the question. Matching a predicate
#: against the whole of ``user_input.txt`` would match the workspace contract too --
#: "figures are mandatory", "write report/report.md" -- which is identical in every
#: run and would make every predicate fire everywhere. This is the same dilution
#: ``research_brief`` was written to remove from the demand extractor, and the router
#: pays for it the same way.
#:
#: But the router wants one block ``research_brief`` deliberately drops. A file
#: description is not a demand -- it says what the run *has*, not what it owes, which
#: is why admitting it took the demand extractor from 75 clauses to 147 -- and it is
#: some of the sharpest routing signal there is. Chemistry_003 ships three files whose
#: descriptions name Fig. 1, Fig. 3 and Fig. 5e of the source paper, and its answer key
#: is one image criterion per file. The prose brief for that task is 730 characters of
#: Input / Output / Scientific Objective and contains the string "Fig" zero times.
#:
#: So routing reads the manifest and the demand extractor does not. The two questions
#: are different: "what does this run owe" and "what kind of task is this".
_MANIFEST_HEADINGS = re.compile(
    r"^#{1,6}\s*(?:Available Data Files?|Data Files?|Supplied Data|Inputs? Provided)\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_ANY_HEADING = re.compile(r"^#{1,6}\s+\S.*$", re.MULTILINE)


def routing_text(goal: str) -> str:
    """What a skill predicate is matched against: the brief plus the data manifest."""
    from .deliverables import research_brief

    statement = task_statement(goal or "")
    spans = [research_brief(statement)]
    for match in _MANIFEST_HEADINGS.finditer(statement):
        start = match.end()
        nxt = _ANY_HEADING.search(statement, start)
        spans.append(statement[start : nxt.start() if nxt else len(statement)])
    return "\n".join(span for span in spans if span.strip()).strip()


def task_brief(paths: RunPaths) -> str:
    """The routing text this run was given, or "" if there is not one yet."""
    try:
        raw = read_text(paths.user_input)
    except OSError:
        return ""
    return routing_text(raw) if raw else ""


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

        # A predicate that does not compile silently removes the skill from every
        # run -- `applies_to` swallows `re.error` so a run does not die of one --
        # which is exactly the failure mode this validator exists to make loud.
        for key in ("applies_when", "applies_unless"):
            pattern = fields.get(key, "")
            if not pattern:
                continue
            try:
                re.compile(pattern)
            except re.error as exc:
                problems.append(
                    f"{child.name}/{SKILL_FILENAME} {key} is not a valid regex ({exc}): {pattern!r}"
                )
        # A task-scoped skill that no stage announces is offered to a minority of
        # runs and told to none of them: it is strictly worse than an
        # unconditional one, because it also costs a predicate nobody reads.
        if fields.get("applies_when") or fields.get("applies_unless"):
            if not fields.get("stages", "").strip():
                problems.append(
                    f"{child.name}/{SKILL_FILENAME} is task-scoped but names no stages, "
                    "so no prompt would tell the operator it had been selected."
                )
        for slug in (s.strip() for s in fields.get("stages", "").split(",")):
            if slug and slug not in KNOWN_STAGE_SLUGS:
                problems.append(
                    f"{child.name}/{SKILL_FILENAME} names stage {slug!r}, which is not a stage."
                )

    return problems


#: Skills whose name begins with one of these are specific to a research field, and are
#: installed only for a run in that field. Everything else is installed always.
#:
#: A skill reaches the operator by its `description`, and the model picks from what is
#: there. Twenty field-specific skills in one run is twenty descriptions to route past on
#: every decision, nineteen of which describe a field this study is not in -- so the pack
#: gets less useful as it grows, which is the wrong direction for a pack meant to grow.
DISCIPLINE_PREFIXES = (
    "astronomy", "chemistry", "earth", "energy", "information",
    "life", "material", "math", "neuroscience", "physics",
)


def discipline_of(name: str) -> str:
    """The field a skill belongs to, or "" for one that belongs to all of them."""
    head = name.split("-", 1)[0].casefold()
    return head if head in DISCIPLINE_PREFIXES else ""


def select_run_skills(
    entries: list[SkillPackEntry], *, discipline: str | None = None, brief: str = ""
) -> list[SkillPackEntry]:
    """The subset of the pack a run with this field and this brief is offered.

    Two independent narrowings, and a skill has to survive both:

    * the field filter, on the name prefix;
    * the shape filter, on ``applies_when`` / ``applies_unless`` against the brief.

    An empty ``brief`` refuses every task-scoped skill rather than admitting them
    all. That is the safe direction: a task-scoped skill is by construction wrong
    for most runs, so admitting one on missing information adds a description that
    competes with the rest and describes a situation this run is probably not in.
    A run with no brief is a run nothing was asked of yet.
    """
    if discipline:
        wanted = discipline.casefold()
        entries = [
            entry for entry in entries
            if not discipline_of(entry.name) or discipline_of(entry.name) == wanted
        ]
    return [entry for entry in entries if entry.applies_to(brief)]


def install_run_skills(
    paths: RunPaths,
    source_dir: Path,
    *,
    discipline: str | None = None,
    brief: str | None = None,
) -> list[str]:
    """Copy the skills this run is offered into its ``.claude/skills/``.

    Idempotent and re-run on resume, so a run picks up skill edits without
    needing a fresh run directory. Returns the installed skill names.

    ``discipline`` narrows the field-specific half of the pack to one field. Passing None
    installs everything, which is right for a run whose field is unknown and wrong for one
    where it is not: a materials run does not benefit from being offered advice about
    observational astronomy, it just has one more description to read past.

    ``brief`` is the research brief the shape filter matches against. Passing None
    reads it from ``paths.user_input``, which is where every route into a run puts
    it; pass a string to route on something else, and pass ``""`` to install only
    the unconditional skills.
    """
    entries = read_skill_pack(source_dir)
    all_names = {entry.name for entry in entries}
    entries = select_run_skills(
        entries,
        discipline=discipline,
        brief=task_brief(paths) if brief is None else brief,
    )
    paths.skills_dir.mkdir(parents=True, exist_ok=True)
    wanted = {entry.name for entry in entries}
    # Remove a skill this call is not installing but a previous one did. Without this the
    # narrowing is a no-op on any resume: the first install writes every field's skills, the
    # second writes eleven of them, and the run still offers the model all twenty-nine. Only
    # pack members are removed -- `learned-from-earlier-runs` is written by another module
    # into the same directory, and deleting what we do not own is how that layer disappears.
    for existing in paths.skills_dir.iterdir() if paths.skills_dir.is_dir() else []:
        if existing.is_dir() and existing.name in all_names and existing.name not in wanted:
            shutil.rmtree(existing)
    installed: list[str] = []
    for entry in entries:
        destination = paths.skills_dir / entry.name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(entry.source_dir, destination)
        installed.append(entry.name)
    return installed


def format_skills_for_prompt(entries: list[SkillPackEntry], stage_slug: str) -> str:
    """The task-scoped skills this stage should be told about, with their triggers.

    Deliberately *not* a roster of the whole pack. That was the objection this
    renderer sat unwired under for several releases, and it was a good one: the
    pack is pull-based, and reprinting twenty-four descriptions into every stage
    prompt is the cost the pull mechanism exists to avoid.

    What is different about a task-scoped skill is that it was selected *for this
    run*, by a predicate over this run's own brief, and the model has no way to
    know that. It sees the same undifferentiated listing of thirty entries it sees
    on every task. So the block is small by construction -- the skills whose
    predicate matched, that name this stage -- and it says why each one is here.
    A run whose brief matches nothing gets no block at all.

    Named imperatively, because that is the form measured to work: over a 40-task
    arm the one skill a rendered prompt told the operator to *read* fired in 31 of
    40 runs, and the three a prompt said were "installed for this stage" fired in
    none.
    """
    selected = sorted(
        (entry for entry in entries if entry.task_scoped and stage_slug in entry.stages),
        key=lambda entry: entry.name,
    )
    if not selected:
        return ""
    lines = [
        "This run's task has a shape that these skills were written for. **Read each one "
        "before you act on this stage.** They are not installed for every run; they were "
        "selected against the brief you were given.",
        "",
    ]
    lines.extend(f"- `{entry.name}` — {entry.description}" for entry in selected)
    return "\n".join(lines)
