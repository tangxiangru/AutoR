"""Skills a run writes for the runs that come after it.

The skill pack ships two layers that are fixed before any run starts: guidance that holds
for all research, and guidance that holds for one field. Neither can know what this
particular corpus turns out to punish -- that a given data archive stores its grid
transposed, that a field's reference implementation needs a flag nobody documents, that the
obvious plotting choice hides the effect. A run learns those the hard way, once, and then
the next run learns them the hard way again.

This is the third layer: after a run finishes, it writes down what it would tell the next
run in the same field, and a later run in that field reads it as an ordinary skill.

Three rules keep the layer from becoming a rumour mill.

**Earned, not guessed.** A note may only describe something this run actually hit -- an
error it saw, a check that caught a mistake, a step that turned out to be required. A run
speculating about what might help is writing prose, and prose accumulates.

**Field-scoped.** A note is filed under the field it was learned in and offered only to runs
in that field. What is true of weather archives is not true of protein structures, and a
pool that mixes them is a pool nobody can route through.

**Bounded and dated.** The pool is capped and the oldest notes fall out. A cap is what
stops a slow drift into a second, unreviewed prompt: guidance that matters keeps being
rediscovered and re-filed, guidance that does not ages out.

What this layer must never carry is a *result*. "The value is 0.42" is an answer, and an
answer travelling between tasks is contamination whatever it is filed as. Notes carry
method: what to check, what to run, what to look at. `looks_like_a_result` refuses the rest.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .utils import RunPaths, read_text, write_text


#: Where learned notes accumulate across runs. Outside any run directory, because the point
#: is to outlive the run that wrote it.
DEFAULT_POOL = Path.home() / ".autor" / "learned_skills"

#: Notes kept per field. Past this the oldest go; see the module docstring on why a cap.
MAX_NOTES_PER_DISCIPLINE = 12

#: A note shorter than this is a slogan. One much longer is a stage summary in disguise.
MIN_NOTE_CHARS = 120
MAX_NOTE_CHARS = 1200

#: Numbers with three or more significant decimals read as measurements, and a measurement
#: crossing between tasks is the one thing this channel must not carry.
_RESULT_VALUE = re.compile(r"(?<![\w.])\d+\.\d{3,}(?![\w])")
_RESULT_CLAIM = re.compile(
    r"\b(we (found|measured|obtained|achieved)|the (answer|result|value) (is|was)"
    r"|accuracy of \d|rmse of \d|scored \d)", re.IGNORECASE
)


@dataclass(frozen=True)
class LearnedNote:
    discipline: str
    title: str
    body: str
    learned_in: str
    recorded_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "discipline": self.discipline, "title": self.title, "body": self.body,
            "learned_in": self.learned_in, "recorded_at": self.recorded_at,
        }


def looks_like_a_result(text: str) -> str:
    """Why this note carries a finding rather than a method, or "" if it does not.

    The test is deliberately blunt. A note is allowed to say "check the grid orientation
    before computing zonal means"; it is not allowed to say what the zonal mean came out as.
    Erring strict costs one note; erring loose leaks a previous task's answer into a later
    task and invalidates both.
    """
    hit = _RESULT_VALUE.search(text)
    if hit:
        return f"carries a measured value ({hit.group(0)}); notes describe method, not findings"
    claim = _RESULT_CLAIM.search(text)
    if claim:
        return f"states a finding ({claim.group(0)!r}); notes describe method, not findings"
    return ""


def validate_note(discipline: str, title: str, body: str) -> list[str]:
    problems: list[str] = []
    if not discipline.strip():
        problems.append("a note must name the field it was learned in.")
    if len(title.strip()) < 8:
        problems.append("a note needs a title a later run can route on.")
    text = body.strip()
    if len(text) < MIN_NOTE_CHARS:
        problems.append(f"a note under {MIN_NOTE_CHARS} characters is a slogan, not guidance.")
    if len(text) > MAX_NOTE_CHARS:
        problems.append(
            f"a note over {MAX_NOTE_CHARS} characters is a stage summary; keep the reusable part."
        )
    leak = looks_like_a_result(f"{title}\n{text}")
    if leak:
        problems.append(f"refused: the note {leak}.")
    return problems


#: Filename the notes for one field land in, under the pool directory. Named so the gate
#: table can point at a real file: the note's text is what `validate_note` decides on, and
#: this is where an accepted one comes to rest.
POOL_FILENAME = "learned_notes.json"


def _pool_file(pool: Path, discipline: str) -> Path:
    safe = re.sub(r"[^a-z0-9]+", "_", discipline.casefold()).strip("_") or "general"
    return pool / safe / POOL_FILENAME


def load_notes(discipline: str, *, pool: Path = DEFAULT_POOL) -> list[LearnedNote]:
    path = _pool_file(pool, discipline)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    notes = []
    for row in payload if isinstance(payload, list) else []:
        if isinstance(row, dict) and row.get("body"):
            notes.append(LearnedNote(
                discipline=str(row.get("discipline") or discipline),
                title=str(row.get("title") or ""), body=str(row.get("body") or ""),
                learned_in=str(row.get("learned_in") or ""),
                recorded_at=str(row.get("recorded_at") or ""),
            ))
    return notes


def record_note(
    discipline: str, title: str, body: str, learned_in: str,
    *, pool: Path = DEFAULT_POOL, now: str | None = None,
) -> tuple[LearnedNote | None, list[str]]:
    """File a note, or refuse it and say why. Never raises on a bad note."""
    problems = validate_note(discipline, title, body)
    if problems:
        return None, problems
    note = LearnedNote(
        discipline=discipline.strip(), title=title.strip(), body=body.strip(),
        learned_in=learned_in.strip(),
        recorded_at=now or datetime.now().isoformat(timespec="seconds"),
    )
    existing = load_notes(discipline, pool=pool)
    # One note per title: a run rediscovering a lesson refreshes it rather than doubling it.
    kept = [x for x in existing if x.title.casefold() != note.title.casefold()]
    kept.append(note)
    kept = kept[-MAX_NOTES_PER_DISCIPLINE:]
    path = _pool_file(pool, discipline)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([x.to_dict() for x in kept], indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return note, []


def install_learned_skill(paths: RunPaths, discipline: str, *, pool: Path = DEFAULT_POOL) -> str:
    """Write the field's learned notes into the run as one skill. Returns its name, or "".

    One skill rather than one per note: they are short, they are all about the same field,
    and a pool that installs twelve descriptions crowds out the twenty-nine the pack already
    has. The model reads the file when the field comes up and finds every note in it.
    """
    notes = load_notes(discipline, pool=pool)
    if not notes:
        return ""
    name = "learned-from-earlier-runs"
    target = paths.skills_dir / name
    target.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"name: {name}",
        f"description: Use when working in {discipline} at any stage. Notes earlier "
        f"{discipline} runs on this system recorded for whoever came next: pitfalls they hit, "
        "checks that caught real mistakes, and steps that turned out to be required. "
        "Read it early; it is short.",
        "---",
        "",
        f"# What earlier {discipline} runs learned",
        "",
        "These were written by previous runs on this system after they finished, each one "
        "describing something it actually hit. They are method, never findings: no note here "
        "tells you what a result came out as, and if one seems to, ignore it and measure.",
        "",
    ]
    for note in notes:
        lines += [f"## {note.title}", "", note.body.strip(), "",
                  f"_Learned in {note.learned_in or 'an earlier run'}, {note.recorded_at}._", ""]
    write_text(target / "SKILL.md", "\n".join(lines))
    return name

