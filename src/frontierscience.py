"""FrontierScience-Research: the dataset, its rubric grammar, and how a task is named.

`FrontierScience-Research <https://arxiv.org/abs/2601.21165>`_ is sixty written science
examination questions — twenty physics, twenty chemistry, twenty biology — each shipped
with a rubric that a judge model grades an answer against. This module is the shared
vocabulary for every other FrontierScience file in the tree: it reads the dataset,
refuses one it cannot identify, parses the rubric, and decides what a task is called.
Nothing here opens a socket or starts a process, because everything here is a decision
and the decisions are what have to be testable without a network.

**The ``answer`` field is not an answer.** Each row has ``problem``, ``subject``,
``task_group_id`` and ``answer``, and ``answer`` holds the rubric — a flat list of
independently scored points, never a worked solution. A reader who takes the field at
its name and hands it to a model as a reference answer is grading against a checklist
of things the checklist itself asks for. :func:`parse_rubric` exists so that the shape
of that field is asserted once, out loud, rather than assumed in four places.

**Addressing is by row index, never by ``task_group_id``.** Rows 6 and 11 of
``research/test.jsonl`` are byte-identical, group id and all, so fifty-nine distinct
group ids cover sixty rows. A result store keyed on the group id silently records
fifty-nine tasks, reports success, and loses one — and there is no error anywhere,
because the second write is a legitimate-looking overwrite of the first. So the key is
``fs:%03d`` over the 0-based row index, :func:`load_dataset` asserts sixty rows and
keeps the duplicate, and the duplication is recorded on the row itself as
:attr:`FsRow.duplicate_of` so that the one layer that genuinely has to merge the two —
a paired analysis, where two draws of one question are not two independent pairs —
can see it instead of rediscovering it.

**The dataset is pinned, not committed, and not downloaded.** Its card carries a canary
GUID asking that the text stay out of crawlable corpora, and this repository is on
GitHub. Pinning three digests is in any case stronger than committing a copy: a copy in
the tree can be hand-edited and nothing notices, whereas
:data:`FS_DATASET_SHA256` and :data:`FS_DATASET_BLOB_SHA1` disagree with an edited file
immediately. Automatic download is refused for a second reason: AutoR has no
third-party dependency and its CI installs nothing, so adding a network path would turn
"the suite is green offline" into a claim that is no longer true — and the easy thing to
do when a download fails is fall back to a local copy, which is how a stale artifact
gets scored as a fresh measurement.

**The parser is an assertion, not a transformation.** :func:`parse_rubric` returns items
and never returns a rewritten rubric, and no caller may hand a rewritten one to the
judge. That is not tidiness. One row's rubric contains ``&gt;`` where the author meant
``>``, and several contain LaTeX; unescaping the entity or normalising the mathematics
would produce a *different instrument* from the one the published numbers came from,
and the difference would be invisible in the output. ``tests/test_fs_scoring.py``
asserts that the rubric slice of the rendered judge prompt is byte-equal to the raw
field for exactly this reason.

**Strictness is the whole value of the parser.** Three parsers that look reasonable were
measured against the sixty rows: an integer ``Points: (\\d+),`` regex is wrong on 60 of
60, "one non-empty line is one item" is wrong on 33 of 60, and scraping ``N pts`` tokens
is wrong on 58 of 60. The third is wrong because the rubric decomposes an item into
markdown sub-bullets carrying their own weights — ``- **(0.25pts)**`` — which sum to the
parent item's points and are not items. All three fail quietly, with a plausible item
count. The grammar here parses 60 of 60 into 635 items totalling exactly 10.0 each, and
rejects 100 of 100 rows of the sibling ``olympiad`` split, which is the negative control
that makes the first number mean something.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .manifest import load_run_manifest
from .rcb import AUTOR_RUNS_DIRNAME, _research_body
from .utils import (
    REQUIRED_STAGE_HEADINGS,
    TASK_BEGIN_MARKER,
    TASK_END_MARKER,
    RunPaths,
    StageSpec,
    code_version,
    contains_placeholder_text,
    extract_fenced_task,
    read_text,
    stage_summary_files,
    truncate_text,
    write_text,
)


#: Where the pinned file comes from. Named in the refusal :func:`resolve_dataset_path`
#: raises, because "no dataset" and "here is the one command that fixes it" are the same
#: message, and splitting them is how a reader ends up downloading the wrong split.
FS_DATASET_URL = (
    "https://huggingface.co/datasets/openai/frontierscience/resolve/main/research/test.jsonl"
)

#: Content digest of ``research/test.jsonl``, 372,607 bytes. Measured on the copy this
#: work was done against, and checked on every load: a dataset that cannot be identified
#: is refused outright rather than scored, because a benchmark number whose input is
#: unknown is not a measurement of anything.
FS_DATASET_SHA256 = "96c0434abfcbadd6ef6f59a03cc374be4caf9c1f2d5e62d8fe921e768f66aa46"

#: The same bytes under git's blob hash, which is what the Hugging Face file listing
#: publishes as ``oid``. A second witness costs one line and answers a different
#: question: sha256 says "this is the file I measured", the blob id says "this is the
#: file the host is serving", and the two can be checked without downloading twice.
FS_DATASET_BLOB_SHA1 = "1c93c21e13ea1c1273dc880966f89de1bd8ed649"

#: Sixty rows. Asserted rather than trusted because the duplicate at rows 6 and 11 makes
#: a silently deduplicated read produce fifty-nine and look fine.
FS_DATASET_ROWS = 60

#: Rubric items across the whole split, under the grammar :func:`parse_rubric` accepts.
#: This is the number that distinguishes a working parser from one of the three plausible
#: wrong ones described in this module's docstring, so it is a load-time assertion and not
#: a comment.
FS_DATASET_RUBRIC_ITEMS = 635

#: Every row's rubric sums to this, in all sixty rows, to within 1e-9. The paper's
#: correctness threshold is 7 of these, so the scale is not incidental: an item is worth
#: a tenth of a task and a parser that loses one loses a tenth of a task's score.
FS_DATASET_POINTS_PER_ROW = 10.0

#: Absolute tolerance on that sum. Rubrics decompose into eighths and quarters, so the
#: total is a float accumulation and exact equality is the wrong test. 1e-6 is five orders
#: of magnitude below the smallest sub-bullet weight in the split (0.1) and more than five
#: below the smallest weight a whole item carries (0.25), so no rounding this tolerates
#: could hide a lost item.
FS_POINTS_TOLERANCE = 1e-6

#: Rows per subject. Checked on load because a truncated or filtered file still parses,
#: still totals 10.0 per row, and still looks like the dataset — and the split is sorted
#: by subject, so the first thing a truncation costs is an entire discipline.
FS_DATASET_SUBJECT_ROWS = {"physics": 20, "chemistry": 20, "biology": 20}

#: Second place :func:`resolve_dataset_path` looks. An environment variable rather than a
#: config file so that a trial driver can point every subprocess at one copy without
#: threading a flag through code it does not own.
FS_DATASET_ENV_VAR = "FRONTIERSCIENCE_DATASET"

#: Third and last place. Outside the repository on purpose, the same decision as the
#: judge key file: a default path inside the tree is one ``git add -A`` away from
#: committing text whose own dataset card asks that it not be committed.
FS_DEFAULT_DATASET_PATH = Path.home() / ".cache" / "frontierscience" / "research_test.jsonl"

#: Task keys are ``fs:`` plus the 0-based row index, zero-padded to three digits so that
#: lexical order is numeric order — every report in this tree sorts keys as strings, and
#: ``fs:10`` sorting before ``fs:2`` is the kind of thing that is only noticed in a table
#: someone has already published.
FS_TASK_KEY_PREFIX = "fs:"

#: One sentence for both readers of the ``--tasks`` grammar: the argparse help and the
#: refusal raised when a spec does not parse. Written once because a help string and an
#: error message that describe the same grammar in two places are two encodings of one
#: rule, and the one nobody reads is the one that goes stale.
FS_TASK_SELECTION_HELP = (
    "Task subset. Either `all`, or a comma-separated list whose parts are row indices "
    "(`0,3,7`), task keys (`fs:000`) or inclusive index ranges (`10-19,40-49`). "
    "Combined with --subject by intersection. --sample N --sample-seed S then draws a "
    "subset as `random.Random(S).sample(sorted(keys), N)`, reported in sorted order, so "
    "the selection can be reproduced by hand. Defaults to all sixty rows."
)

#: Head of a rubric item, anchored at column 0. Every one of the 635 ``Points:``
#: substrings in the split sits at the start of a line, so the anchor is safe; the
#: unanchored count is compared against the parsed count in :func:`parse_rubric` so that
#: the day one stops being true is the day the parser refuses rather than the day it
#: silently merges two items.
FS_RUBRIC_HEAD_PATTERN = re.compile(r"^Points:\s*([0-9]*\.?[0-9]+)\s*,\s*Item:\s?(.*)$")

#: The literal the anchored pattern above is anchored on. Kept as its own constant
#: because it is used twice for two different purposes — to find item heads and to count
#: how many there should have been — and the second use is what catches a description
#: that has grown a ``Points:`` of its own.
FS_RUBRIC_HEAD_TOKEN = "Points:"


class RubricParseError(ValueError):
    """A rubric that does not satisfy the grammar, refused instead of half-parsed.

    Raised rather than returned because there is no useful partial answer: a rubric
    parsed into the wrong items produces a judge prompt that is still well formed and a
    score that is still a number.
    """


class DatasetRefused(ValueError):
    """The dataset on disk is not the pinned one, or the task selection is not a set.

    Never paired with a fallback. The failure mode this exists against is the ordinary
    one — a download fails, or a path is wrong, and the cheapest repair is to carry on
    with whatever copy is lying around — which produces a complete, plausible result
    file measured against an input nobody can name.
    """


@dataclass(frozen=True)
class RubricItem:
    """One independently scored point.

    ``description`` is the item text with its continuation lines joined by newlines and
    trailing whitespace stripped, and it is *not* used to build the judge prompt: the
    judge is shown the raw rubric field. This object is for counting, for asserting, and
    for saying how many points a task is out of.
    """

    index: int
    points: float
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "points": self.points, "description": self.description}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RubricItem":
        """Coerce, default, never raise — a malformed record reads as an empty item."""
        try:
            points = float(payload.get("points", 0.0))
        except (TypeError, ValueError):
            points = 0.0
        try:
            index = int(payload.get("index", 0))
        except (TypeError, ValueError):
            index = 0
        return cls(index=index, points=points, description=str(payload.get("description", "")))


@dataclass(frozen=True)
class FsRow:
    """One examination question, addressed by row index.

    Two serialisations, and the split between them is deliberate. :meth:`to_dict` is the
    round-trippable one and carries the text; it is for holding a row in memory or
    caching it outside the repository. :meth:`task_block` carries digests, counts and
    identifiers and no text at all, and that is the one a result file gets — a scored
    run's JSON travels, and the dataset card asks that this text not travel with it.
    """

    key: str
    row_index: int
    subject: str
    task_group_id: str
    problem: str
    rubric: str
    problem_sha256: str
    rubric_sha256: str
    rubric_items: int
    rubric_points_total: float
    #: Row index of the first row with byte-identical problem and rubric, or ``None``.
    #: Filled by :func:`load_dataset`, which is the only place that can see the whole
    #: file; a row cannot know it is a duplicate on its own.
    duplicate_of: int | None = None

    @classmethod
    def from_payload(cls, row_index: int, payload: Mapping[str, Any]) -> "FsRow":
        """Build a row from one parsed JSONL object, parsing its rubric on the way.

        The rubric is parsed here rather than on demand so that a file which loads at all
        has had all sixty rubrics accepted by the grammar. A lazy parse would let a
        malformed row survive until the judge call that costs money.
        """
        problem = str(payload.get("problem", ""))
        rubric = str(payload.get("answer", ""))
        items = parse_rubric(rubric)
        return cls(
            key=task_key(row_index),
            row_index=row_index,
            subject=str(payload.get("subject", "")),
            task_group_id=str(payload.get("task_group_id", "")),
            problem=problem,
            rubric=rubric,
            problem_sha256=_sha256_text(problem),
            rubric_sha256=_sha256_text(rubric),
            rubric_items=len(items),
            rubric_points_total=round(sum(item.points for item in items), 6),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "row_index": self.row_index,
            "subject": self.subject,
            "task_group_id": self.task_group_id,
            "problem": self.problem,
            "rubric": self.rubric,
            "problem_sha256": self.problem_sha256,
            "rubric_sha256": self.rubric_sha256,
            "rubric_items": self.rubric_items,
            "rubric_points_total": self.rubric_points_total,
            "duplicate_of": self.duplicate_of,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FsRow":
        """Coerce, default, skip — never raise. A record that cannot be read is not a run."""
        try:
            row_index = int(payload.get("row_index", 0))
        except (TypeError, ValueError):
            row_index = 0
        try:
            items = int(payload.get("rubric_items", 0))
        except (TypeError, ValueError):
            items = 0
        try:
            total = float(payload.get("rubric_points_total", 0.0))
        except (TypeError, ValueError):
            total = 0.0
        raw_duplicate = payload.get("duplicate_of")
        try:
            duplicate = None if raw_duplicate is None else int(raw_duplicate)
        except (TypeError, ValueError):
            duplicate = None
        return cls(
            key=str(payload.get("key", "")) or task_key(row_index),
            row_index=row_index,
            subject=str(payload.get("subject", "")),
            task_group_id=str(payload.get("task_group_id", "")),
            problem=str(payload.get("problem", "")),
            rubric=str(payload.get("rubric", "")),
            problem_sha256=str(payload.get("problem_sha256", "")),
            rubric_sha256=str(payload.get("rubric_sha256", "")),
            rubric_items=items,
            rubric_points_total=total,
            duplicate_of=duplicate,
        )

    def task_block(self) -> dict[str, Any]:
        """The identifiers and sizes, with no examination text in it.

        Every field here is either a digest, a count or a name, so a result file can say
        exactly which question was scored and a reader can check that claim against their
        own copy of the dataset — without the result file carrying a line of the dataset.
        """
        return {
            "key": self.key,
            "row_index": self.row_index,
            "subject": self.subject,
            "task_group_id": self.task_group_id,
            "duplicate_of": self.duplicate_of,
            "problem_sha256": self.problem_sha256,
            "problem_chars": len(self.problem),
            "rubric_sha256": self.rubric_sha256,
            "rubric_chars": len(self.rubric),
            "rubric_items_expected": self.rubric_items,
            "rubric_points_total": self.rubric_points_total,
        }


def task_key(row_index: int) -> str:
    """``fs:007`` for row 7. The only place the key format is written."""
    return f"{FS_TASK_KEY_PREFIX}{int(row_index):03d}"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _blob_sha1(data: bytes) -> str:
    """Git's object id for these bytes, which is what the file host publishes as ``oid``."""
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def parse_rubric(text: str) -> list[RubricItem]:
    """Parse a rubric field into its independently scored items. Strict; read-only.

    The grammar, verified over all sixty rows::

        rubric       := item+
        item         := "Points: " FLOAT ", Item: " REST_OF_LINE ("\\n" CONTINUATION)*
        CONTINUATION := any line that does not start, at column 0, with "Points:"

    Everything that is not a head line belongs to the item above it, including the
    markdown sub-bullets that decompose an item into weighted parts. Those look exactly
    like items — ``- **(0.25pts)**``, and in one row nested two levels deep — and their
    weights already sum to the parent's, so a parser that promotes them double-counts the
    whole rubric. One row writes the same decoration with the asterisks in the wrong place
    (``(**0.125pts)``); it is a continuation line either way, which is the point of
    deciding this on the anchor rather than on the shape of the decoration.

    Four refusals, each of which was a way to be silently wrong:

    * a line before the first head — the file is not a rubric, or the leading text is an
      instruction that belongs to no item;
    * no items at all — an empty parse otherwise reads as a rubric worth zero points;
    * more ``Points:`` substrings than parsed items — some description has grown a
      ``Points:`` of its own, and every item boundary after it is guesswork;
    * a total that is not :data:`FS_DATASET_POINTS_PER_ROW` — the scale the judge is told
      to grade on is 10, so a rubric that sums to 9 or 11 makes every number derived from
      it incomparable with every other task.

    The text handed in is never modified and never returned. No HTML unescaping, no LaTeX
    normalisation: the judge is shown the raw field, and a parser that quietly improves it
    would be a different instrument wearing the same name.
    """
    items: list[RubricItem] = []
    buffer: list[str] | None = None

    for line in text.split("\n"):
        head = FS_RUBRIC_HEAD_PATTERN.match(line)
        if head is not None:
            if buffer is not None:
                items[-1] = replace(items[-1], description="\n".join(buffer).rstrip())
            items.append(RubricItem(index=len(items), points=float(head.group(1)), description=""))
            buffer = [head.group(2)]
        elif buffer is None:
            if line.strip():
                raise RubricParseError(f"text before the first rubric item: {line[:80]!r}")
        else:
            buffer.append(line)

    if buffer is not None:
        items[-1] = replace(items[-1], description="\n".join(buffer).rstrip())

    if not items:
        raise RubricParseError("no rubric items found; an empty rubric is not a rubric worth 0")

    heads = text.count(FS_RUBRIC_HEAD_TOKEN)
    if heads != len(items):
        raise RubricParseError(
            f"{heads} {FS_RUBRIC_HEAD_TOKEN!r} substrings but {len(items)} parsed items; "
            "an item description contains the head token, so the boundaries are guesses"
        )

    total = round(sum(item.points for item in items), 6)
    if abs(total - FS_DATASET_POINTS_PER_ROW) > FS_POINTS_TOLERANCE:
        raise RubricParseError(
            f"rubric points sum to {total}, not {FS_DATASET_POINTS_PER_ROW}"
        )
    return items


def resolve_dataset_path(path: str | Path | None = None, *, environ: Mapping[str, str] | None = None) -> Path:
    """``--dataset PATH``, then ``$FRONTIERSCIENCE_DATASET``, then the cache path.

    *environ* is a parameter rather than a read of :data:`os.environ` so that the
    resolution order is testable without mutating the process, which is the shape that
    makes an order-of-precedence test order-dependent on the rest of the suite.
    """
    values = os.environ if environ is None else environ
    if path:
        return Path(path).expanduser()
    from_env = (values.get(FS_DATASET_ENV_VAR) or "").strip()
    if from_env:
        return Path(from_env).expanduser()
    return FS_DEFAULT_DATASET_PATH


def load_dataset(
    path: str | Path | None = None, *, environ: Mapping[str, str] | None = None
) -> list[FsRow]:
    """Read the pinned dataset, or refuse. There is no fallback and no download.

    Six assertions, in the order that makes the failure legible: the file exists, its
    sha256 is the pinned one, its git blob id is the pinned one, it holds sixty rows, the
    subject counts are twenty each, and the rubrics parse to 635 items. Digest first,
    because every count below it is a statement about a file that has already been
    identified — reporting "59 rows" about an unknown file sends the reader after the
    wrong bug.

    The duplicate pass at the end is not deduplication. Rows 6 and 11 are byte-identical
    and both stay; each row is told which earlier row it repeats, so the one consumer that
    must merge them can, and every other consumer keeps a sixty-row population.
    """
    resolved = resolve_dataset_path(path, environ=environ)
    if not resolved.is_file():
        raise DatasetRefused(
            f"No FrontierScience dataset at {resolved}. Fetch {FS_DATASET_URL} and put it "
            f"there, point ${FS_DATASET_ENV_VAR} at it, or pass --dataset. It is not "
            "downloaded automatically: this tree has no network dependency, and a download "
            "that fails invites a fall back to whatever copy is already on disk."
        )

    data = resolved.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != FS_DATASET_SHA256:
        raise DatasetRefused(
            f"{resolved} has sha256 {digest}, not the pinned {FS_DATASET_SHA256}. Refusing "
            "rather than scoring: a benchmark number whose input cannot be named is not a "
            "measurement of anything, and there is no second copy to fall back to."
        )
    blob = _blob_sha1(data)
    if blob != FS_DATASET_BLOB_SHA1:
        raise DatasetRefused(
            f"{resolved} has git blob id {blob}, not the pinned {FS_DATASET_BLOB_SHA1}, "
            "while its sha256 matched. Two digests over the same bytes cannot disagree, so "
            "one of the two pins in this module is wrong."
        )

    rows: list[FsRow] = []
    for index, line in enumerate(data.decode("utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetRefused(f"{resolved} line {index + 1} is not JSON: {exc}") from exc
        rows.append(FsRow.from_payload(len(rows), payload))

    if len(rows) != FS_DATASET_ROWS:
        raise DatasetRefused(
            f"{resolved} holds {len(rows)} rows, not {FS_DATASET_ROWS}"
        )

    counts: dict[str, int] = {}
    for row in rows:
        counts[row.subject] = counts.get(row.subject, 0) + 1
    if counts != FS_DATASET_SUBJECT_ROWS:
        raise DatasetRefused(
            f"{resolved} has subject counts {counts}, not {FS_DATASET_SUBJECT_ROWS}"
        )

    total_items = sum(row.rubric_items for row in rows)
    if total_items != FS_DATASET_RUBRIC_ITEMS:
        raise DatasetRefused(
            f"{resolved} parsed to {total_items} rubric items, not {FS_DATASET_RUBRIC_ITEMS}; "
            "the file is the pinned one, so the grammar in parse_rubric has moved"
        )

    first_seen: dict[tuple[str, str], int] = {}
    resolved_rows: list[FsRow] = []
    for row in rows:
        identity = (row.problem_sha256, row.rubric_sha256)
        earlier = first_seen.get(identity)
        if earlier is None:
            first_seen[identity] = row.row_index
        resolved_rows.append(replace(row, duplicate_of=earlier))
    return resolved_rows


def rows_by_key(rows: Iterable[FsRow]) -> dict[str, FsRow]:
    """Index rows on :attr:`FsRow.key`, which is the only identifier that is unique.

    Written once and used everywhere a row has to be looked up, because the obvious
    alternative — indexing on ``task_group_id`` — builds a fifty-nine entry map from a
    sixty-row file and reports nothing.
    """
    return {row.key: row for row in rows}


def _parse_task_token(token: str, *, valid: set[str]) -> list[str]:
    """One comma-separated part of a ``--tasks`` spec, as a list of keys."""
    text = token.strip()
    if not text:
        return []
    if text.startswith(FS_TASK_KEY_PREFIX):
        if text not in valid:
            raise DatasetRefused(f"unknown task key {text!r}. {FS_TASK_SELECTION_HELP}")
        return [text]
    range_match = re.fullmatch(r"([0-9]+)\s*-\s*([0-9]+)", text)
    if range_match is not None:
        low, high = int(range_match.group(1)), int(range_match.group(2))
        if low > high:
            raise DatasetRefused(
                f"range {text!r} counts down. {FS_TASK_SELECTION_HELP}"
            )
        keys = [task_key(index) for index in range(low, high + 1)]
    elif re.fullmatch(r"[0-9]+", text):
        keys = [task_key(int(text))]
    else:
        raise DatasetRefused(f"cannot read task spec {text!r}. {FS_TASK_SELECTION_HELP}")
    unknown = [key for key in keys if key not in valid]
    if unknown:
        raise DatasetRefused(
            f"task spec {text!r} names rows outside the dataset: {', '.join(unknown)}. "
            f"{FS_TASK_SELECTION_HELP}"
        )
    return keys


def resolve_task_keys(
    rows: Sequence[FsRow],
    *,
    tasks: str | None = None,
    subject: str | None = None,
    sample: int | None = None,
    sample_seed: int | None = None,
) -> list[str]:
    """Turn the three subset flags into one explicit, sorted list of task keys.

    The list this returns is what goes into the plan and into the result file verbatim.
    Nothing downstream re-derives it: a subset recomputed from ``--sample 10
    --sample-seed 7`` a week later against a dataset that has moved is a different
    population wearing the same flags, and the report would have no way to say so.

    Three refusals rather than three conveniences. An index outside the dataset is an
    error, not a row to skip, because a spec of ``0-99`` against sixty rows means the
    author believed something false. ``--sample`` without ``--sample-seed`` is refused
    because an unseeded draw cannot be reproduced and a benchmark subset that cannot be
    reproduced is not a subset anyone can argue with. ``--sample`` larger than the
    selection is refused rather than truncated, for the same reason: silently returning
    forty rows for ``--sample 100`` publishes a number about a population the flags do
    not describe.
    """
    by_key = rows_by_key(rows)
    valid = set(by_key)
    if not valid:
        raise DatasetRefused("no rows to select from")

    if tasks is None or tasks.strip().lower() == "all":
        selected = set(valid)
    else:
        selected = set()
        for token in tasks.split(","):
            selected.update(_parse_task_token(token, valid=valid))
        if not selected:
            raise DatasetRefused(f"task spec {tasks!r} selects nothing. {FS_TASK_SELECTION_HELP}")

    if subject:
        wanted = subject.strip().lower()
        if wanted not in FS_DATASET_SUBJECT_ROWS:
            raise DatasetRefused(
                f"unknown subject {subject!r}; the split holds "
                f"{', '.join(sorted(FS_DATASET_SUBJECT_ROWS))}"
            )
        by_subject = {key for key, row in by_key.items() if row.subject.lower() == wanted}
        selected &= by_subject
        if not selected:
            raise DatasetRefused(
                f"the intersection of {tasks!r} and subject {wanted!r} is empty"
            )

    keys = sorted(selected)
    if sample is None:
        return keys

    if sample_seed is None:
        raise DatasetRefused(
            "--sample needs --sample-seed: an unseeded draw cannot be reproduced, and a "
            "benchmark subset nobody can redraw cannot be argued with"
        )
    if sample < 1:
        raise DatasetRefused(f"--sample {sample} asks for no tasks")
    if sample > len(keys):
        raise DatasetRefused(
            f"--sample {sample} exceeds the {len(keys)} task(s) the other flags select; "
            "refusing rather than truncating, which would publish a number about a "
            "population the flags do not describe"
        )
    return sorted(random.Random(sample_seed).sample(keys, sample))


# ---------------------------------------------------------------------------
# The prompt contract
# ---------------------------------------------------------------------------
#
# Three blocks, in a fixed order, and the fenced task is first in every
# combination of them. Five readers in this tree excerpt a goal by taking a
# prefix -- the router that chooses the next graph move, the deliberation panel,
# the adversarial validity reviewer, the review panel and the approval agent --
# and :func:`src.utils.task_statement` reads the fence to decide what the run was
# asked for. On the ResearchClawBench adapter the contract in front of the task
# had grown past every one of those budgets, so the router chose its move having
# read none of the question and `demanding_sentences` returned 23 requirements
# for a task with 10. Putting the fence first is not a style choice; it is what
# makes every one of those readers see the examination question.


#: Block 1. The whole task instruction, identical in both arms, and the string
#: whose digest goes into a trial's environment digest.
#:
#: What is *not* in it is the point. The rubric is the scoring function, it is a
#: checklist of independently weighted specifics, and an agent told that shape
#: writes a different answer -- so this text may not describe how the answer is
#: marked. ``tests/test_fs_adapter.py`` holds a word list against this constant
#: and against :data:`FS_WORKSPACE_CONTRACT`, because the first draft of this
#: block contained "A named specific is worth more than a correct generality"
#: and nothing would have noticed. Telling the agent the rubric's shape is a
#: legitimate experiment, and it has a flag of its own
#: (:data:`FS_COVERAGE_GUIDANCE`) that has to be declared and applied to both
#: arms; it is not something this block may do by accident.
FS_TASK_INSTRUCTION = """# FrontierScience-Research — Written Examination Answer

{task_begin}
{problem}
{task_end}

## What is being asked of you

This is a written science examination question. It is not a research project. An
independent examiner reads exactly one thing: the text of your answer. Nothing else you
produce is read or seen.

- Answer the problem above in full. If it has numbered parts, answer each part, in order,
  under its own heading.
- Your answer must **stand alone**. The examiner has the problem and your answer and
  nothing else. Do not refer to files, to earlier work, to "the analysis above" outside
  the answer itself, or to anything you have not written down here.
- Where the problem asks for a quantity, give the expression and then the number with
  units. Where it asks for a procedure, name the methods, reagents, instruments,
  constants, parameters or software you would use.
- **No citations.** No reference list, no DOIs, no arXiv identifiers, no URLs, no author
  names offered as evidence. You cannot check a reference on this run, and an invented
  citation is worse than no citation.
- **No browsing.** Web search and web fetch are disabled for this run. Any attempt to
  reach the network is recorded and voids the result. Answer from what you know and what
  you can derive.
- There is no dataset, no reference paper, no starter code, no reference answer and no
  one to ask. There is nothing to download, nothing to load and nothing to measure.
- Length is whatever the problem needs."""

#: The digest of Block 1 above, frozen here and pinned byte-for-byte against
#: ``tests/fixtures/fs_task_instruction.txt``.
#:
#: Two jobs, and neither is served by recomputing it at read time. A trial plan
#: records it so that two arms can be shown to have been given the same
#: instruction, and a result file records it so that a number can be traced to
#: the words that produced it. A constant that is recomputed from the very string
#: it is meant to pin agrees with itself by construction and witnesses nothing;
#: this one disagrees the moment the block is edited, which is the day somebody
#: has to decide whether the old numbers still stand.
FS_TASK_INSTRUCTION_SHA256 = "cae42a4c27402b4387ba83722dcb938b4af446ef2b285fefff0076e71a81fbd7"

#: Block 2. Plumbing, and only plumbing: where the file goes, what it must not
#: contain, and that nobody is waiting to be asked a question. Added only when
#: there is a workspace -- the pipeline arm has one, a single direct call does
#: not, because its answer is its reply.
#:
#: The "no research report" paragraph is here rather than in Block 1 because it
#: is a statement about AutoR's own stage contract, which the direct arm never
#: meets. It names the headings from :data:`src.utils.REQUIRED_STAGE_HEADINGS`
#: on purpose: those headings are exactly what a stage summary carries, and a
#: stage summary copied into ``answer.md`` is refused by
#: :func:`answer_content_refusals` rather than scored.
FS_WORKSPACE_CONTRACT = """## Where the answer goes

- Write the finished answer to `{answer_path}`, in Markdown, in English.
- `answer.md` is the deliverable and the only deliverable. Overwrite it; do not create
  `answer_v2.md`, `draft.md` or `final.md`.
- Do **not** write a research report. No abstract, no related work, no "Objective",
  "What I Did", "Files Produced", "Decision Ledger", "Suggestions for Refinement" or
  "Your Options" headings — those belong in your stage summary, not in `answer.md`.
- Do **not** produce figures, images, plots or `![](...)` references. This task has no
  data to plot, and an image is not read by the examiner.
- You may run a short computation — arithmetic, symbolic algebra, a numeric check — if it
  makes an answer correct. Put the result in `answer.md`; the scratch file is not read.
- Nobody is watching. There is no one to ask and no menu to wait on. Every question you
  would put to a human, answer yourself in the text and say which reading you took.

## Done means

`answer.md` exists, is not empty, contains no placeholder text, and would be
understandable to an examiner who has read nothing but the problem."""

#: Block 3, added only by ``--answer-guidance coverage``.
#:
#: This is a *declared prompt intervention*, not a better prompt. It tells the
#: agent the shape of the scoring function, which is the one thing the other two
#: blocks are forbidden to do, so it must be applied to both arms or to neither
#: and it must enter the trial's environment digest. A capability whose mechanism
#: is "turn this on" is a capability selected on its own fitness signal: pasting a
#: fitness function's own feedback back into the thing being measured produced a
#: new champion 89 times out of 89 in this repository's history, and the champion
#: was the paste.
FS_COVERAGE_GUIDANCE = """## How this is graded

The rubric is a checklist of independently scored, specific points totalling 10. You earn
each point you state correctly and lose each one you omit; there is no penalty for a
correct statement the rubric does not happen to ask about. A named specific is worth more
than a correct generality. Padding earns nothing; an unanswered part is a lost mark.
Prefer stating one more correct specific over polishing one you have already stated."""

#: What ``--answer-guidance`` accepts, and what each value means.
#:
#: ``paper`` is the published setup: the fenced problem and not one word more.
#: ``minimal`` is Block 1, which says what an examination answer is without saying
#: how it is marked. ``coverage`` adds Block 3. The default is ``minimal`` because
#: ``paper`` under this harness produces answers that ignore the workspace
#: entirely, and ``coverage`` is an experimental condition rather than a setting.
FS_ANSWER_GUIDANCE_CHOICES = ("paper", "minimal", "coverage")
DEFAULT_FS_ANSWER_GUIDANCE = "minimal"

#: The two arms. ``direct`` is one operator call whose reply is the answer;
#: ``ideate`` is AutoR entered at Stage 02 and stopped there.
FS_PROFILE_CHOICES = ("direct", "ideate")
DEFAULT_FS_PROFILE = "direct"

#: The stage both ends of the ``ideate`` walk sit on.
#:
#: Starting above Stage 01 is deliberate and it is the protocol, not a saving.
#: Stage 01 is a literature survey whose evidence ledger can only be satisfied by
#: citations; a run that cannot browse has only invented ones, the gate never
#: checks that a URL resolves, and the rubric awards points for named literature
#: values — so a fabricated value does not merely fail to score, it displaces a
#: real one in the answer. Stopping at Stage 02 is what keeps Stage 07's figure
#: floor out of the picture as well: it is never consulted, so no benchmark
#: constant in :mod:`src.utils` has to move for this benchmark to run.
FS_IDEATE_STAGE = "02_hypothesis_generation"


# ---------------------------------------------------------------------------
# Workspace layout, answers and refusals
# ---------------------------------------------------------------------------

#: The one scored file. Named here rather than spelled in five places because the
#: prompt tells the agent this name, the exporter writes it, the scorer reads it
#: and a trial admits a run on its length.
FS_ANSWER_FILENAME = "answer.md"

#: The AutoR run tree lives inside the workspace, so a run is self-contained and a
#: trial can archive or delete one directory. Taken from the ResearchClawBench
#: adapter rather than spelled again: "where a run tree goes inside a benchmark
#: workspace" is one convention, and a second copy of the string is a directory
#: that two tools would look in different places for after somebody renames it.
FS_RUNS_DIRNAME = AUTOR_RUNS_DIRNAME

#: Records the digest of the answer this adapter last exported, so a re-export can
#: tell its own output from one the agent wrote. Without it, ``--export-only``
#: after an interrupted run re-publishes its own fallback forever and calls it the
#: agent's work.
FS_EXPORT_MARKER_NAME = ".fs_export.json"

#: First line of a fallback answer, written into the file itself.
#:
#: ``_meta.json`` also records ``answer_source``, and this is the second witness:
#: a metadata field can be regenerated by a later pass over a workspace, whereas
#: a line in the scored file travels with the thing that gets scored. A trial
#: admission clause reads both and refuses if either says fallback.
FS_FALLBACK_MARKER = "<!-- fs:fallback -->"

#: First line of an answer produced by ``--fake-operator``. A smoke run writes a
#: file long enough to clear every length check, which is exactly what makes it
#: dangerous: nothing else in the artifact says the model was never called.
#: ``_meta.json`` carries ``fake_operator`` as well, for the same
#: two-witness reason as :data:`FS_FALLBACK_MARKER`.
FS_FAKE_ANSWER_MARKER = "<!-- fs:fake-operator -->"

#: Below this an answer is not an answer. Deliberately not the 1200 the
#: ResearchClawBench report floor uses: this benchmark is answered in prose and
#: arithmetic, an 800-character correct derivation of a period and its damping
#: term is a complete answer to one of these questions, and a floor set for a
#: research report would refuse it. 200 is the length at which a file stops being
#: a stub and starts being a paragraph.
FS_MIN_ANSWER_CHARS = 200

#: Above this the run is refused. **A refusal threshold, not a truncation.**
#: Truncating would hand the judge a sentence that stops mid-clause and score it,
#: which is the failure this benchmark's own probe already produced once from the
#: other end (a judge response cut at its token budget returned HTTP 200, an
#: ``incomplete`` status and 636 characters of a graded verdict). Real AutoR
#: reports on the sibling benchmark run to a median of 37 kB and a maximum of
#: 75 kB, so this is twice the largest thing the pipeline has ever produced: an
#: answer past it is a runaway, not a thorough answer.
FS_MAX_ANSWER_CHARS = 150_000

#: The answer file came from the model itself — the direct arm's reply, or an
#: ``answer.md`` the pipeline arm's agent wrote.
FS_SOURCE_AGENT = "agent"
#: One extra operator call turned approved stage work into an answer.
FS_SOURCE_SYNTHESIZED = "synthesized"
#: The approved stage summary, with AutoR's control-loop scaffolding stripped.
FS_SOURCE_STAGE = "stage"
#: Assembled with no model call. Never scored; the exit code refuses it.
FS_SOURCE_FALLBACK = "fallback"

#: Recorded when the answer is a plan for an answer. A 250-character "To answer
#: this I will (1)... (2)... (3)..." clears every length and format check, scores
#: near zero, and is indistinguishable in the results from a genuinely wrong
#: answer — so the two are separated here, before the judge is paid, rather than
#: afterwards by reading transcripts.
FS_REFUSAL_ANSWER_IS_A_PLAN = "driver:answer_is_a_plan"

#: Recorded when synthesis was reachable and there was nothing approved to
#: synthesize from. With zero approved summaries an "answer synthesis" call is the
#: problem asked a second time with the word answer in front of it, and its output
#: is a fresh single-shot answer wearing the pipeline arm's label — which is the
#: control arm's result recorded as the treatment's.
FS_REFUSAL_NO_APPROVED_STAGE = "driver:no_approved_stage"

#: Recorded when the answer is missing, too short or past the ceiling.
FS_REFUSAL_ANSWER_LENGTH = "driver:answer_out_of_bounds"

#: Version tag on the ``_meta.json`` this adapter writes.
FS_META_SCHEMA = "fs_meta/1"

#: Synthetic stage used only to label this adapter's own operator calls in the run
#: log. Numbered 9 like the ResearchClawBench report synthesizer's, and for the
#: same reason: it is not one of the eight, and a real stage number would put it
#: in the manifest.
FS_ANSWER_STAGE = StageSpec(9, "09_fs_answer", "FrontierScience Answer")


def fs_runs_dir_for(workspace: Path) -> Path:
    """Where the AutoR run tree goes for this workspace."""
    return workspace / FS_RUNS_DIRNAME


def answer_path_for(workspace: Path) -> Path:
    """The one scored file."""
    return workspace / FS_ANSWER_FILENAME


def ensure_fs_workspace(workspace: Path) -> None:
    """Create the workspace and the run-tree parent, and nothing else.

    Deliberately three lines. The ResearchClawBench adapter creates ``code/``,
    ``outputs/``, ``report/`` and ``report/images/`` because its harness reads all
    four; this benchmark reads one file. An empty ``outputs/`` here would be an
    invitation to a stage to fill it, and a stage that spends its attempt writing
    a figure has spent it on something the examiner never sees.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    fs_runs_dir_for(workspace).mkdir(parents=True, exist_ok=True)


def infer_fs_task_key(workspace: Path) -> str | None:
    """Recover ``fs:043`` from a workspace directory named ``fs043_<anything>``.

    A colon is legal in a POSIX directory name and is still the wrong thing to put
    in one: it is the field separator in ``PATH`` and in a dozen tool arguments,
    and a path with a colon in it is quoted correctly almost everywhere. So the
    directory drops the colon and this puts it back. Returns ``None`` rather than
    guessing when the name does not carry a key -- a task the adapter had to infer
    wrongly would score one question's answer against another question's rubric,
    and there is no digest in the result file that would catch it.
    """
    match = re.match(r"^fs(\d{3})(?:[_-]|$)", workspace.resolve().name)
    return task_key(int(match.group(1))) if match is not None else None


def fs_workspace_name(key: str, label: str, *, now: "datetime | None" = None) -> str:
    """``fs043_direct-opus_20260817_034109_512334``.

    Microseconds are in the name because a second is not enough. The
    ResearchClawBench trial named workspaces to the second and created them with
    ``exist_ok=True``: two arms of one task launched inside the same second landed
    in one directory, overwrote each other's deliverable, and produced a paired
    difference of exactly zero -- a null result manufactured by a filename.
    """
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S_%f")
    slug = re.sub(r"[^A-Za-z0-9.-]+", "-", label).strip("-") or "arm"
    return f"{key.replace(FS_TASK_KEY_PREFIX, 'fs')}_{slug}_{stamp}"


def resolve_answer_guidance(value: str | None) -> str:
    """Normalise ``--answer-guidance``, refusing an unknown value.

    Refused rather than defaulted, unlike :func:`src.utils.resolve_output_format`.
    An output format read back from an old run config may legitimately be absent;
    this one only ever arrives from a flag or a plan, both of which were written
    on purpose, and silently reading ``covrage`` as ``minimal`` would publish a
    paired comparison whose two arms were told different things.
    """
    text = (value or DEFAULT_FS_ANSWER_GUIDANCE).strip().lower()
    if text not in FS_ANSWER_GUIDANCE_CHOICES:
        raise DatasetRefused(
            f"unknown --answer-guidance {value!r}; choose one of "
            f"{', '.join(FS_ANSWER_GUIDANCE_CHOICES)}"
        )
    return text


def build_fs_goal(
    problem: str,
    *,
    workspace: Path | None = None,
    answer_guidance: str = DEFAULT_FS_ANSWER_GUIDANCE,
) -> str:
    """The goal string the agent is given, fenced task first.

    Three blocks and one ordering rule. ``paper`` is the fenced problem alone,
    which is what the published evaluation gave its models; ``minimal`` adds
    Block 1; ``coverage`` adds Block 3 on top. Block 2 is added whenever there is
    a workspace, in every guidance mode including ``paper`` -- a pipeline run with
    no workspace contract has nowhere to put an answer, and a goal that produces
    no answer file is not a fair rendering of the paper's setup either. ``paper``
    is a direct-arm setting; the combination is legal so that it is testable
    rather than special.

    The fence goes first in all six combinations. :func:`src.utils.task_statement`
    and the five prefix readers named at the top of this section decide what the
    run is about by reading it, and the only way to keep that true as the contract
    grows is to make the position structural instead of remembered.
    """
    guidance = resolve_answer_guidance(answer_guidance)
    fenced = f"{TASK_BEGIN_MARKER}\n{problem.strip()}\n{TASK_END_MARKER}"

    blocks: list[str] = []
    if guidance == "paper":
        blocks.append(fenced)
    else:
        blocks.append(
            FS_TASK_INSTRUCTION.format(
                task_begin=TASK_BEGIN_MARKER,
                problem=problem.strip(),
                task_end=TASK_END_MARKER,
            )
        )
    if workspace is not None:
        blocks.append(
            FS_WORKSPACE_CONTRACT.format(answer_path=answer_path_for(workspace.resolve()))
        )
    if guidance == "coverage":
        blocks.append(FS_COVERAGE_GUIDANCE)
    return "\n\n".join(blocks)


#: A stage summary's headings, matched as headings rather than as substrings.
#:
#: The design this was written from said "contains any of
#: ``REQUIRED_STAGE_HEADINGS``", and a bare substring test is the wrong instrument
#: for two of the seven: "Objective" and "Key Results" are ordinary English, and a
#: correct answer that opens "The objective is to show that..." would be refused
#: and never scored -- a false refusal costs the whole task, where a missed
#: detection costs one low score in a population of sixty. Anchored as a markdown
#: heading, the pattern catches what it is for, which is a stage summary or a
#: stage-shaped plan reaching ``answer.md``, and
#: ``tests/test_fs_adapter.py`` carries the control that proves the prose use
#: survives.
FS_STAGE_HEADING_PATTERN = re.compile(
    r"^\s{0,3}#{1,6}\s*(?:\*\*)?(" + "|".join(re.escape(h) for h in REQUIRED_STAGE_HEADINGS) + r")",
    re.MULTILINE,
)


def answer_content_refusals(text: str) -> list[str]:
    """Reasons this text is a plan for an answer rather than an answer.

    Two witnesses, both cheap, both fired before the judge is paid. The first is
    AutoR's own placeholder vocabulary -- ``[TODO]``, ``[Pending]``, ``[In
    progress]`` -- which every stage gate in this tree already refuses and which a
    single-shot answer has no excuse for. The second is a stage summary's heading
    structure, which reaches ``answer.md`` in exactly one way: the pipeline arm
    copied its control-loop output into the deliverable.

    Returns a list, possibly empty, because the caller records every reason rather
    than the first: "it was refused" is not an answer to "why", and the trial's
    refusal ledger prints the clause names.
    """
    reasons: list[str] = []
    if contains_placeholder_text(text):
        reasons.append(FS_REFUSAL_ANSWER_IS_A_PLAN + ":placeholder")
    headings = sorted({match.group(1) for match in FS_STAGE_HEADING_PATTERN.finditer(text)})
    if headings:
        reasons.append(FS_REFUSAL_ANSWER_IS_A_PLAN + ":" + ",".join(headings))
    return reasons


def answer_length_refusals(text: str) -> list[str]:
    """Reasons this text is outside the length band, named with the bound it broke."""
    chars = len(text.strip())
    if chars < FS_MIN_ANSWER_CHARS:
        return [f"{FS_REFUSAL_ANSWER_LENGTH}:{chars} < {FS_MIN_ANSWER_CHARS}"]
    if chars > FS_MAX_ANSWER_CHARS:
        return [f"{FS_REFUSAL_ANSWER_LENGTH}:{chars} > {FS_MAX_ANSWER_CHARS}"]
    return []


def has_refusal(reasons: Iterable[str], prefix: str) -> bool:
    """Whether any recorded reason belongs to *prefix*'s clause.

    Reasons are namespaced strings, ``driver:answer_is_a_plan:Objective``, so that
    the ledger can print what was actually wrong without the clause name having to
    be re-derived from prose. Everything that decides on a clause goes through
    here, so the namespace is one rule rather than a startswith written in six
    places, five of which would eventually be an equality test that misses the
    detail suffix.
    """
    return any(reason == prefix or reason.startswith(prefix + ":") for reason in reasons)


@dataclass(frozen=True)
class FsAnswer:
    """The answer that reached the workspace, and how it got there.

    The one frozen dataclass in this module with no ``to_dict``/``from_dict`` pair, and
    the omission is deliberate. These five values are flattened into ``_meta.json`` by
    :func:`build_fs_meta` under the names the exit clauses and a trial's admission clauses
    read -- ``answer_source``, ``answer_chars``, ``answer_sha256``, ``refusals``. A second
    serialisation of the same five under different names would be a second encoding of one
    record, and the one nobody reads is the one that drifts.
    """

    path: Path
    source: str
    chars: int
    sha256: str
    refusals: list[str]


def _answer_digest(text: str) -> str:
    return _sha256_text(text.strip())


def _matches_export_marker(workspace: Path, text: str) -> bool:
    """True when the answer on disk is one this adapter exported earlier.

    An unreadable or absent marker reads as "the agent wrote it", which is the
    conservative answer: it preserves a real answer at the cost of occasionally
    crediting the exporter's own work to the agent, and the alternative loses the
    only answer the run produced.
    """
    if not text.strip():
        return False
    marker_path = workspace / FS_EXPORT_MARKER_NAME
    if not marker_path.exists():
        return False
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("answer_sha256") == _answer_digest(text)


def _publish_answer(workspace: Path, text: str, source: str) -> str:
    """Write the answer and record that this adapter, not the agent, authored it."""
    body = text.strip() + "\n"
    write_text(answer_path_for(workspace), body)
    (workspace / FS_EXPORT_MARKER_NAME).write_text(
        json.dumps(
            {"answer_source": source, "answer_sha256": _answer_digest(body)},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return body


def stage_answer_bodies(paths: RunPaths) -> list[str]:
    """Approved stage summaries with AutoR's control-loop scaffolding removed.

    The stripper is :func:`src.rcb._research_body`, imported rather than rewritten.
    Two copies of "what part of a stage summary reads as research" would be two
    encodings of one rule, and the copy nobody edits is the one that keeps
    ``## Your Options / 1. Use suggestion 1 ... 6. Abort`` in a scored artifact.
    """
    return [
        body
        for body in (_research_body(read_text(path)) for path in stage_summary_files(paths))
        if body.strip()
    ]


def build_fallback_answer(*, paths: RunPaths | None, reasons: Sequence[str]) -> str:
    """Assemble something with no model call, marked as what it is.

    This exists so that a workspace is never empty and the reason a run failed is
    legible in the scored file rather than only in a log. It is never a scored
    answer: the first line is :data:`FS_FALLBACK_MARKER`, ``answer_source`` says
    ``fallback``, and the exit code refuses it. Both witnesses are written because
    a metadata field can be regenerated by a later pass over the workspace and a
    line inside the file travels with the file.
    """
    lines = [
        FS_FALLBACK_MARKER,
        "",
        "# No answer was produced",
        "",
        "This run did not produce an examination answer. This file is a record of that, "
        "assembled without a model call, and it is not an answer to the problem.",
        "",
    ]
    if reasons:
        lines.extend(["## Why", ""] + [f"- `{reason}`" for reason in reasons] + [""])
    bodies = stage_answer_bodies(paths) if paths is not None else []
    if bodies:
        lines.extend(["## What the run did produce", ""])
        for body in bodies:
            lines.extend([body, ""])
    return "\n".join(lines).rstrip() + "\n"


def export_answer(
    *,
    workspace: Path,
    paths: RunPaths | None = None,
    direct_answer: str | None = None,
    stages_approved: Sequence[str] = (),
    synthesize: "AnswerSynthesizer | None" = None,
    problem: str = "",
) -> FsAnswer:
    """Resolve the answer by the first of four paths that yields real content.

    ``agent``
        The model wrote it: the direct arm's reply, or an ``answer.md`` at the
        workspace path that this adapter did not write itself. The digest in
        ``.fs_export.json`` is what distinguishes the second from a re-export of
        our own earlier output.
    ``synthesized``
        One extra operator call turned approved stage work into an answer.
        **Only when at least one stage was approved.** With nothing approved that
        call has no material and produces a fresh single-shot answer, which is the
        control arm's result recorded under the treatment arm's label; the refusal
        is recorded as :data:`FS_REFUSAL_NO_APPROVED_STAGE` instead.
    ``stage``
        The approved stage summary itself, scaffolding stripped.
    ``fallback``
        Assembled with no model call, marked in the file and in the metadata, and
        refused by the exit code.

    Content refusals are evaluated against whatever wins, not against the file
    that happens to be on disk first, and they do not change the source: an
    ``answer.md`` the agent wrote that turns out to be a plan is still sourced
    ``agent``. What it is and whether it may be scored are two questions, and
    collapsing them would make "the pipeline produced nothing" and "the pipeline
    produced a plan" indistinguishable in the ledger.
    """
    ensure_fs_workspace(workspace)
    refusals: list[str] = []

    existing = read_text(answer_path_for(workspace)).strip() if answer_path_for(workspace).exists() else ""
    chosen: tuple[str, str] | None = None

    if direct_answer is not None and len(direct_answer.strip()) >= FS_MIN_ANSWER_CHARS:
        chosen = (FS_SOURCE_AGENT, direct_answer.strip())
    elif direct_answer is not None:
        # Recorded here rather than left to the length check below, which will run
        # against the fallback and find it perfectly well formed. Without this line the
        # ledger says only "fallback", and "the model replied with forty characters" and
        # "the call never came back" are the same entry.
        refusals.extend(answer_length_refusals(direct_answer))

    if chosen is None and len(existing) >= FS_MIN_ANSWER_CHARS and not _matches_export_marker(workspace, existing):
        chosen = (FS_SOURCE_AGENT, existing)

    if chosen is None and synthesize is not None:
        if not stages_approved:
            refusals.append(FS_REFUSAL_NO_APPROVED_STAGE)
        elif paths is not None:
            synthesized = synthesize(
                paths=paths,
                workspace=workspace,
                problem=problem,
                stages_approved=stages_approved,
            )
            if synthesized and len(synthesized.strip()) >= FS_MIN_ANSWER_CHARS:
                chosen = (FS_SOURCE_SYNTHESIZED, synthesized.strip())

    if chosen is None and paths is not None:
        bodies = stage_answer_bodies(paths)
        if bodies:
            joined = "\n\n".join(bodies).strip()
            if len(joined) >= FS_MIN_ANSWER_CHARS:
                chosen = (FS_SOURCE_STAGE, joined)

    if chosen is None:
        source = FS_SOURCE_FALLBACK
        body = _publish_answer(
            workspace,
            build_fallback_answer(paths=paths, reasons=refusals),
            FS_SOURCE_FALLBACK,
        )
    else:
        source, text = chosen
        if source == FS_SOURCE_AGENT and text == existing:
            # Already at the scored path in the agent's own bytes. Rewriting it
            # would record our digest in the marker and make the next --export-only
            # read the agent's answer as this adapter's output.
            body = existing + "\n"
        else:
            body = _publish_answer(workspace, text, source)

    if source != FS_SOURCE_FALLBACK:
        # Not run against the fallback, and that is not leniency. The fallback is this
        # module's own boilerplate plus whatever the run left behind, so measuring it
        # against the answer bounds reports on the assembly rather than on the run --
        # and since it quotes the stage summaries, the content check would attribute
        # "this answer is a plan" to a run whose actual failure was producing no answer
        # at all. The fallback is already refused, by name, by its own clause.
        refusals.extend(answer_length_refusals(body))
        refusals.extend(answer_content_refusals(body))
    return FsAnswer(
        path=answer_path_for(workspace),
        source=source,
        chars=len(body.strip()),
        sha256=_answer_digest(body),
        refusals=refusals,
    )


# ---------------------------------------------------------------------------
# The two ways an answer gets written
# ---------------------------------------------------------------------------


class _OperatorCall:
    """The one seam both answer producers use to make a single operator call.

    ``OperatorProtocol.run_stage`` is not usable here: it renders AutoR's stage
    contract, and a stage summary is precisely the shape :func:`answer_content_refusals`
    refuses. So both producers go through ``_prepare_invocation`` /
    ``_run_streaming_command``, the same private pair
    :class:`src.rcb.ReportSynthesizer` uses, which keeps the invocation, the MCP
    config, the denied tools and the raw log identical to a stage's without
    widening the protocol.

    **A fake operator does not fake this call.** ``_prepare_invocation`` builds the
    real CLI command whatever ``fake_mode`` says -- only ``run_stage`` branches --
    so a producer that reached this seam under ``--fake-operator`` would spawn the
    real backend. Every subclass therefore answers :meth:`supported` with
    ``False`` under a fake operator and the caller takes the next path. That is
    also why ``--fake-operator`` smoke runs exercise the ``stage`` export path
    rather than the synthesis one.
    """

    def __init__(self, operator: Any) -> None:
        self.operator = operator

    @property
    def fake(self) -> bool:
        return bool(getattr(self.operator, "fake_mode", False))

    def supported(self) -> bool:
        if self.fake:
            return False
        return all(
            hasattr(self.operator, name)
            for name in ("_prepare_invocation", "_run_streaming_command")
        )

    @staticmethod
    def fake_answer(*, title: str, question: str, note: str) -> str:
        """A scripted reply for ``--fake-operator``, marked as one in its first line.

        Long enough to clear :data:`FS_MIN_ANSWER_CHARS`, because a smoke run has to
        exercise the same export, metadata and exit-code path a real run takes. Marked in
        the file *and* in ``_meta.json`` because an artifact that clears every length and
        format check while no model was ever called is the exact shape of a fake result
        being counted as an attempt.

        It deliberately does not echo any of the run's own artifacts. A fake answer
        assembled out of stage summaries would carry their headings, be refused by
        :func:`answer_content_refusals`, and turn the smoke test into an assertion about
        the fake rather than about the adapter.
        """
        return "\n".join(
            [
                FS_FAKE_ANSWER_MARKER,
                "",
                f"# {title}",
                "",
                note,
                "",
                "## The question this run was given",
                "",
                truncate_text(question, max_chars=2000),
            ]
        )

    def invoke(self, *, paths: RunPaths, prompt: str, label: str, attempt: int) -> tuple[int, str]:
        """Run one operator call and return its exit code and captured reply."""
        import uuid

        prompt_path = paths.prompt_cache_dir / f"{FS_ANSWER_STAGE.slug}_{label}.prompt.md"
        write_text(prompt_path, prompt)
        command, cwd, stdin_text = self.operator._prepare_invocation(  # noqa: SLF001
            prompt_path,
            str(uuid.uuid4()),
            paths=paths,
            resume=False,
        )
        exit_code, stdout, _stderr, _session, _meta = self.operator._run_streaming_command(  # noqa: SLF001
            command=command,
            cwd=cwd,
            stage=FS_ANSWER_STAGE,
            attempt_no=attempt,
            paths=paths,
            mode=label,
            stdin_text=stdin_text,
        )
        return exit_code, stdout or ""


class DirectAnswerWriter(_OperatorCall):
    """The control arm: one operator call, and its reply is the answer.

    No workspace contract, no stages, no reviewer, no gates. The point of the arm
    is that it is the same underlying model given the same problem and the same
    denied tools, so that a paired difference is a statement about the pipeline
    rather than about the model -- which means everything this class does beyond
    "ask once and keep the reply" is a confound it would have to declare.

    The reply is kept rather than a file the model was asked to write. A single
    call told to write a file has two ways to fail (it can answer and not write,
    or write and not answer) and the second is invisible: an empty workspace is
    scored as a refusal when what happened was that the model answered in chat.
    """

    #: Attempts at the one call. Two, not one and not the pipeline's eight: an
    #: empty reply here is almost always transport, and a retry costs one answer
    #: latency (measured at a mean of 134.5 s on this benchmark for a direct
    #: model call) where the alternative is a refused pair.
    MAX_ATTEMPTS = 2

    def __init__(self, operator: Any, max_attempts: int = MAX_ATTEMPTS) -> None:
        super().__init__(operator)
        self.max_attempts = max(1, int(max_attempts))

    def __call__(self, *, paths: RunPaths, goal: str) -> str | None:
        if self.fake:
            return self.fake_answer(
                title="Fake operator answer",
                question=extract_fenced_task(goal) or goal,
                note=(
                    "This file was produced by `--fake-operator` to exercise the "
                    "FrontierScience adapter's export, metadata and exit-code paths without "
                    "calling a model. It is not an answer to the question below and must "
                    "never be scored; `_meta.json` records `fake_operator: true` beside it."
                ),
            )
        if not self.supported():
            return None
        for attempt in range(1, self.max_attempts + 1):
            try:
                _exit_code, reply = self.invoke(
                    paths=paths, prompt=goal, label="fs_direct_answer", attempt=attempt
                )
            except Exception:  # noqa: BLE001 - a failed call is a short answer, not a crash
                continue
            # The exit code is not the deliverable, the text is. A call killed at
            # `--answer-timeout` having already streamed a complete answer exits
            # non-zero, and discarding that would throw away the whole task over
            # how the process ended.
            if len(reply.strip()) >= FS_MIN_ANSWER_CHARS:
                return reply.strip()
        return None


class AnswerSynthesizer(_OperatorCall):
    """One operator call that turns approved stage work into an examination answer.

    **It refuses when nothing was approved, and that refusal is the point.** The
    obvious implementation calls the model with whatever the run has, which for a
    run that approved nothing is the problem statement and an empty memory file --
    so the call produces a fresh single-shot answer and the pipeline arm publishes
    the control arm's result under its own label. The paired difference then
    measures the variance of one model against itself and reports it as the
    treatment's effect. Nothing downstream could see it: the answer is long, it is
    about the right question, and ``answer_source`` says ``synthesized``.

    The guard is here as well as in :func:`export_answer` because the two answer
    different questions. This one refuses to make the call at all, which is
    checkable with a stub operator that counts invocations; the exporter records
    :data:`FS_REFUSAL_NO_APPROVED_STAGE` in the run's refusal ledger, which is what
    a trial reads.
    """

    #: Attempts at the synthesis call. The pipeline behind it has already spent
    #: hours by the time this runs, so a lost call is expensive; three is what the
    #: sibling benchmark's report synthesizer settled on for the same reason.
    MAX_ATTEMPTS = 3

    def __init__(self, operator: Any, max_attempts: int = MAX_ATTEMPTS) -> None:
        super().__init__(operator)
        self.max_attempts = max(1, int(max_attempts))

    def __call__(
        self,
        *,
        paths: RunPaths,
        workspace: Path,
        problem: str,
        stages_approved: Sequence[str],
    ) -> str | None:
        if not stages_approved:
            return None
        if self.fake:
            return self.fake_answer(
                title="Fake operator synthesis",
                question=problem,
                note=(
                    "This file was produced by `--fake-operator`: the pipeline arm reached "
                    "the synthesis step with "
                    f"{len(stages_approved)} approved stage(s) and no model was called. It "
                    "is not an answer to the question below and must never be scored; "
                    "`_meta.json` records `fake_operator: true` beside it."
                ),
            )
        if not self.supported():
            return None
        prompt = self.build_prompt(
            paths=paths, workspace=workspace, problem=problem, stages_approved=stages_approved
        )
        answer_file = answer_path_for(workspace)
        # What was at the scored path before the call. The prompt asks the model to write
        # that file, so the file is the first place to look for the result -- but reaching
        # here means the exporter already rejected whatever was there, typically this
        # adapter's own fallback from an earlier pass. Without this snapshot, a synthesis
        # call that produced nothing would hand the old file back and it would be
        # published as ``synthesized``: a fallback relabelled as a model's work.
        before = read_text(answer_file).strip() if answer_file.exists() else ""
        for attempt in range(1, self.max_attempts + 1):
            try:
                _exit_code, reply = self.invoke(
                    paths=paths, prompt=prompt, label="fs_synthesis", attempt=attempt
                )
            except Exception:  # noqa: BLE001 - the stage path is still available
                continue
            written = read_text(answer_file).strip() if answer_file.exists() else ""
            candidates = ([written] if written and written != before else []) + [reply.strip()]
            for candidate in candidates:
                if len(candidate) >= FS_MIN_ANSWER_CHARS:
                    return candidate
        return None

    def build_prompt(
        self,
        *,
        paths: RunPaths,
        workspace: Path,
        problem: str,
        stages_approved: Sequence[str],
    ) -> str:
        """The synthesis prompt: the question, the approved work, and where to put it.

        The question is included whole. A prefix of the goal is not a substitute --
        the sibling benchmark's synthesizer was handed 8,000 characters of a goal
        whose contract had grown to 7,600, so the one call that decides what the
        scored artifact is *about* received 331 characters of the subject.
        """
        approved = "\n\n".join(stage_answer_bodies(paths)) or "(nothing was approved)"
        return "\n\n".join(
            [
                "# FrontierScience-Research — Write The Answer",
                (
                    "An AutoR run has finished its hypothesis work on the examination question "
                    "below. Your only job is to write the answer an examiner will read. This is "
                    "not a report about the run: nobody reads what the run did, only what the "
                    "answer says."
                ),
                f"Write it to `{answer_path_for(workspace.resolve())}`, overwriting whatever is there.",
                "## Requirements",
                (
                    "- Answer the question. If it has numbered parts, answer each part in order "
                    "under its own heading.\n"
                    "- Standalone prose and mathematics. No abstract, no related work, no "
                    "workflow headings, no figures, no citations, no URLs.\n"
                    "- Give expressions and then numbers with units. Name methods, reagents, "
                    "instruments, constants and parameters where the question asks for a "
                    "procedure.\n"
                    "- Never invent a citation or a literature value. Say what you can derive "
                    "and what you know.\n"
                    "- Do not describe this prompt, the run, or the stages."
                ),
                "## The Question",
                f"{TASK_BEGIN_MARKER}\n{problem.strip()}\n{TASK_END_MARKER}",
                "## What The Run Approved",
                f"Stages approved: {', '.join(stages_approved)}.",
                truncate_text(approved, max_chars=24000),
            ]
        )


# ---------------------------------------------------------------------------
# What the run says about itself, and whether that is a success
# ---------------------------------------------------------------------------


def stages_approved_in(paths: RunPaths) -> list[str]:
    """Stage slugs a reviewer actually approved, from the run manifest.

    The manifest rather than ``memory.md``, and the distinction is load-bearing:
    :func:`src.utils.append_approved_stage_summary` is called for a *skipped*
    stage too, so approved memory contains an entry for a stage nobody reviewed.
    :attr:`src.manifest.StageManifestEntry.approved` is the narrower claim, and
    ``settled`` -- the one the resume cursor uses -- is the wider one that a
    skipped stage also satisfies. This function wants the narrow one.
    """
    manifest = load_run_manifest(paths.run_manifest)
    if manifest is None:
        return []
    return [entry.slug for entry in manifest.stages if entry.approved and not entry.skipped]


def _answer_present(meta: Mapping[str, Any]) -> bool:
    path = meta.get("answer_path")
    return bool(path) and Path(str(path)).exists()


def _answer_within_bounds(meta: Mapping[str, Any]) -> bool:
    chars = meta.get("answer_chars")
    return isinstance(chars, int) and FS_MIN_ANSWER_CHARS <= chars <= FS_MAX_ANSWER_CHARS


def _answer_not_fallback(meta: Mapping[str, Any]) -> bool:
    return meta.get("answer_source") != FS_SOURCE_FALLBACK


def _pipeline_completed(meta: Mapping[str, Any]) -> bool:
    return meta.get("pipeline_completed") is True


def _no_auto_skips(meta: Mapping[str, Any]) -> bool:
    skipped = meta.get("auto_skipped_stages")
    return isinstance(skipped, list) and not skipped


def _no_content_refusal(meta: Mapping[str, Any]) -> bool:
    refusals = meta.get("refusals")
    refusals = [str(item) for item in refusals] if isinstance(refusals, list) else []
    return not has_refusal(refusals, FS_REFUSAL_ANSWER_IS_A_PLAN)


#: The six things that must all be true for this adapter to exit 0: a name, the question
#: the clause answers, and the predicate that answers it.
#:
#: One list rather than a list beside an ``if`` ladder. A declared set of clauses and a
#: checker that re-implements them are two encodings of one rule, and the encoding nobody
#: edits is the one that goes stale -- a clause could be renamed here, printed in a
#: refusal ledger, and never evaluated, which is a guard that reports on itself.
#: :func:`fs_exit_failures` walks this and nothing else.
#:
#: The list exists because of a measured defect on the sibling benchmark, and it is the
#: most important thing in this file. Forty of forty real ResearchClawBench runs wrote
#: ``status: "completed"``; 77.5% of them had auto-skipped at least one stage and 17.5%
#: had auto-skipped *the stage being scored*, and ``auto_skipped_stages`` appeared only in
#: the stdout event stream and never in ``_meta.json``. Every downstream that read the
#: metadata -- the scorer, the leaderboard importer, the trial driver -- recorded those as
#: successes. So the fields below are in the metadata, the exit code is computed from the
#: metadata, and the two cannot disagree.
FS_EXIT_CLAUSES: tuple[tuple[str, str, "Callable[[Mapping[str, Any]], bool]"], ...] = (
    ("answer_present", "an answer file exists at the workspace path", _answer_present),
    (
        "answer_within_bounds",
        "its length is inside [FS_MIN_ANSWER_CHARS, FS_MAX_ANSWER_CHARS]",
        _answer_within_bounds,
    ),
    (
        "answer_not_fallback",
        "the answer came from a model, not from the deterministic assembly",
        _answer_not_fallback,
    ),
    (
        "pipeline_completed",
        "the run's answer-producing procedure ran to completion",
        _pipeline_completed,
    ),
    ("no_auto_skips", "no stage was auto-skipped after exhausting its retries", _no_auto_skips),
    ("no_content_refusal", "the answer is an answer, not a plan for one", _no_content_refusal),
)


def fs_exit_failures(meta: Mapping[str, Any]) -> list[str]:
    """Which of :data:`FS_EXIT_CLAUSES` this run's metadata fails, in declaration order.

    A pure function of the recorded metadata, so the exit code is re-derivable from the
    artifact by anyone holding it -- including a trial driver that never saw the process.
    A run whose exit code and whose ``_meta.json`` disagree is the failure this whole
    arrangement exists against, and the only way to make them agree is for one to be
    computed from the other.
    """
    return [name for name, _reason, holds in FS_EXIT_CLAUSES if not holds(meta)]


def fs_exit_code(meta: Mapping[str, Any]) -> int:
    """0 when every clause in :data:`FS_EXIT_CLAUSES` holds, 1 otherwise."""
    return 1 if fs_exit_failures(meta) else 0


def build_fs_meta(
    *,
    workspace: Path,
    task: str,
    profile: str,
    answer_guidance: str,
    model: str,
    review_model: str,
    operator: str,
    answer: FsAnswer,
    pipeline_completed: bool,
    auto_skipped_stages: Sequence[str],
    stages_approved: Sequence[str],
    disallowed_tools: Sequence[str],
    dataset_path: Path | None,
    dataset_sha256: str,
    run_id: str,
    duration_seconds: int,
    attempt_index: int = 0,
    fake_operator: bool = False,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The metadata record, assembled before it is written or judged.

    Separated from :func:`write_fs_meta` so that the exit code can be computed
    from the same dictionary that reaches disk, and so a test can build one
    without a filesystem. Every field the exit code reads is here, and so is every
    field a trial's admission clauses read: what was answered, by whom, under
    which instruction, with which tools denied, and whether the pipeline actually
    finished.
    """
    payload: dict[str, Any] = {
        "schema": FS_META_SCHEMA,
        "benchmark": "frontierscience-research",
        "task": task,
        "profile": profile,
        "answer_guidance": answer_guidance,
        "model": model,
        "review_model": review_model,
        "operator": operator,
        "fake_operator": bool(fake_operator),
        "attempt_index": int(attempt_index),
        "workspace": str(workspace),
        "run_id": run_id,
        "duration_seconds": int(duration_seconds),
        "code_version": code_version(),
        "task_instruction_sha256": FS_TASK_INSTRUCTION_SHA256,
        "dataset_path": str(dataset_path) if dataset_path is not None else "",
        "dataset_sha256": dataset_sha256,
        "disallowed_tools": list(disallowed_tools),
        "pipeline_completed": bool(pipeline_completed),
        "auto_skipped_stages": list(auto_skipped_stages),
        "stages_approved": list(stages_approved),
        "answer_path": str(answer.path),
        "answer_source": answer.source,
        "answer_chars": answer.chars,
        "answer_sha256": answer.sha256,
        "refusals": list(answer.refusals),
    }
    if extra:
        payload.update(dict(extra))
    payload["exit_clause_failures"] = fs_exit_failures(payload)
    # Last, and computed rather than passed: a status somebody hands in is a claim,
    # and a claim is what forty of forty runs on the sibling benchmark got wrong.
    payload["status"] = "completed" if not payload["exit_clause_failures"] else "failed"
    return payload


def write_fs_meta(workspace: Path, payload: Mapping[str, Any]) -> Path:
    """Write ``_meta.json``, preserving fields an outer harness already set.

    Merged rather than replaced for the same reason the ResearchClawBench adapter
    merges: a trial driver writes ``agent_cmd`` and the arm label into the
    workspace before launching, and losing those makes a finished run
    unattributable to the arm that produced it.
    """
    meta_path = workspace / "_meta.json"
    existing: dict[str, Any] = {}
    if meta_path.exists():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        if isinstance(loaded, dict):
            existing = loaded
    existing.update(dict(payload))
    meta_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return meta_path


@dataclass(frozen=True)
class FsRunResult:
    """What one ``fs_agent.py`` invocation did, and whether it counts."""

    workspace: Path
    meta: dict[str, Any]

    @property
    def exit_code(self) -> int:
        return fs_exit_code(self.meta)

    @property
    def failures(self) -> list[str]:
        return fs_exit_failures(self.meta)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace": str(self.workspace),
            "exit_code": self.exit_code,
            "exit_clause_failures": self.failures,
            "meta": dict(self.meta),
        }
