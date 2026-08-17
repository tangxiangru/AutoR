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
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


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
