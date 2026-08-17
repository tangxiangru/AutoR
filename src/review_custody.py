"""What the run root looked like before a reviewer ran, and after.

Every reviewer in this tree is the same CLI the doer is, launched through
:meth:`src.operator.ClaudeOperator._prepare_invocation`, which hardcodes
``bypassPermissions`` and ``--dangerously-skip-permissions``, mounts the
:mod:`src.mcp_write` server unconditionally and sets the working directory to the run
root. The only thing standing between a reviewer and the artifacts it is judging is one
sentence of prompt text -- *"Do not edit files. Inspect and judge."* -- and a sentence is
not a boundary.

Nothing downstream would notice if it wrote. :func:`src.provenance.observe_artifacts`
runs at exactly three sites, none of them around a review, so a file a reviewer changes
is picked up at the next stage boundary and attributed to **the stage the reviewer just
approved**; and :func:`src.mcp_write` stamps every write with the manifest's current
stage slug whichever process called it. The laundering path is not hypothetical, it is
the default.

This module is the census that closes it: the run root before the subprocess, the run
root after it, and the difference.

Content, not mtime, and the measurement that decided it
-------------------------------------------------------
The obvious census compares modification times, and it is the wrong one. Replayed over
the four finished runs under ``tools/review_custody_replay.py``'s ``MEASURED_RUNS`` --
138 reviewer episodes -- an mtime census fires on **138 of 138** with no exclusion list
and on **4 of 138** with one. All four are the same behaviour, and it is the behaviour a
reviewer is supposed to have: re-running the doer's producer scripts in place to check
they reproduce. Both of the two approvals among those four say so in their own recorded
reason (*"I re-ran all three producers from the workspace"*).

Punishing that would be a gate that fires hardest on the most rigorous reviewer. So the
comparison is over :func:`src.provenance.content_identity`, and a file whose digest is
unchanged is **not** a breach however far its mtime moved. It is recorded as ``touched``,
because "the reviewer re-derived this artifact and it came out identical" is the
strongest verification available and the record should be able to say it happened.

None of the seven files in those four episodes carries a timestamp field, so a
deterministic re-run leaves the bytes alone and this census is silent on all four. That
is an argument, not a measurement: mtime is all an archive retains, so how far below 4
the content-keyed rate sits cannot be settled from disk. It is what the ledger is for,
and it is why ``--review-custody`` defaults to ``record``.

What it costs
-------------
One census over the four archived run roots: 395 ms and 472 ms on the Astronomy roots
(500-630 paths, 110-145 MB) and 1026 ms and 1190 ms on the Chemistry ones (1180-1260
paths, 1.8-4.7 GB). Two per episode, so 0.8-2.4 s of the several minutes an episode
takes, and 2-5 minutes over a whole run's 138 episodes. Hashing dominates, which is why
the cap in :func:`src.provenance.content_identity` is reused rather than re-picked: the
4.7 GB root is mostly files above it, and those are stat-only.

What it cannot see
------------------
The census is rooted at the run root because that is the reviewer's working directory. A
reviewer that writes outside it is invisible here, and that is not hypothetical either:
in the same 138 episodes there are three tool-level writes, and two of them go to a
``~/.claude/projects/.../memory/`` directory far outside any run. What the census claims
is narrower than "the reviewer changed nothing" -- it is "the reviewer changed nothing it
was judging", which is the claim the verdict depends on.

It also holds digests rather than bytes, so it does not restore. AMAP-ML's
LongHorizon-Harness, where this mechanism is borrowed from, advertises a restore and
hardcodes ``verifier_workspace_restored: False``; the demotion is the whole enforcement
there and it is the whole enforcement here. See
``docs/iclr/round-loop-and-stage-graph.md``.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

from .provenance import SKIP_DIR_NAMES, content_identity
from .utils import RunPaths, append_jsonl


CUSTODY_LEDGER_FILENAME = "review_custody.jsonl"

#: What arming the mechanism means. ``off`` takes no census at all; ``record`` takes it
#: and writes the ledger; ``demote`` additionally converts the episode's approval into a
#: send-back. The default is ``record`` and the reason is in the module docstring: the
#: blast radius of the demotion is bounded above by an archive replay and not measured
#: below it, and this repository's own rule is to measure a gate before landing it.
CUSTODY_MODES = ("off", "record", "demote")
DEFAULT_CUSTODY_MODE = "record"

#: The prefix every demoted reason carries, so ``classify_refusal`` and a human reading
#: ``logs.txt`` can both tell this refusal from one the reviewer actually reached.
CUSTODY_REASON_PREFIX = "The reviewer changed the run root while judging it:"


def churn_files(paths: RunPaths) -> frozenset[str]:
    """Run-root files the harness itself writes *while* a reviewer subprocess runs.

    Two, and both are named off the ``RunPaths`` field that writes them rather than
    spelled as literals -- :func:`src.rubric._harness_written_records`'s discipline, so a
    rename cannot leave this list pointing at nothing.

    The rest of the churn the recon turned up needs no entry, because of where the
    boundary is drawn. The prompt file and ``operator_state/mcp_config.json`` are written
    inside ``write_text`` and ``_prepare_invocation``, *before* the before-census; the
    per-call record under ``operator_state/`` is written *after* the after-census. Only
    the two log files grow inside the window, and ``logs_raw.jsonl`` grows on every line
    the stream emits -- it is the one exclusion whose absence fires the gate on every
    review ever taken.
    """

    return frozenset({paths.logs_raw.name, paths.logs.name})


@dataclass(frozen=True)
class CustodyEntry:
    kind: str
    identity: str
    #: Carried alongside the identity, and it is not a second spelling of it. The pair is
    #: what lets the ledger say *"the reviewer rewrote this file and the bytes came out
    #: identical"* -- the case the whole design turns on, and the one an archive replay
    #: cannot see because an archive retains only the last write. A census that stored
    #: the identity alone would have to call that case "no change", which is true of the
    #: artifact and false about the reviewer.
    mtime_ns: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "identity": self.identity}


@dataclass(frozen=True)
class CustodySnapshot:
    entries: dict[str, CustodyEntry] = field(default_factory=dict)
    #: Paths the walk could not read. Never a breach: a census that refuses a review
    #: because it could not stat a file is a precondition no run can promise to meet.
    scan_errors: tuple[str, ...] = ()
    root_missing: bool = False
    took_ms: int = 0


def census(run_root: Path, *, excluded: Iterable[str] = ()) -> CustodySnapshot:
    """Identity per file under *run_root*, skipping *excluded* and the usual noise.

    ``SKIP_DIR_NAMES`` is reused rather than re-picked, and it is load-bearing here for a
    reason the workspace walk never had to care about: a reviewer that imports the doer's
    module leaves a ``__pycache__/*.pyc`` behind and a reviewer that runs ``git status``
    in a cloned repository rewrites ``.git/index``. Replayed without that set both show
    up as writes; neither is one anybody chose to make. Four of the eight fires in the
    archive were of exactly these two kinds.
    """

    started = time.monotonic()
    skip = frozenset(excluded)
    entries: dict[str, CustodyEntry] = {}
    errors: list[str] = []
    if not run_root.is_dir():
        return CustodySnapshot(root_missing=True)

    for path in run_root.rglob("*"):
        try:
            relative = path.relative_to(run_root)
            # Every component, including the last, unlike
            # :func:`src.provenance._walk_workspace`, which only ever looks at files and
            # so can test the parents alone. This walk records directories too, and a
            # reviewer that imports the doer's module creates the `__pycache__` *itself*
            # -- so testing only the parents skips the bytecode and then reports the
            # directory holding it as an addition. The test that found this is
            # `test_a_pyc_left_by_importing_the_doers_module_is_not_a_breach`.
            if any(part in SKIP_DIR_NAMES for part in relative.parts):
                continue
            key = relative.as_posix()
            if key in skip or relative.parts[0] in skip:
                continue
            status = path.lstat()
            if path.is_symlink():
                entries[key] = CustodyEntry("symlink", os.readlink(path), status.st_mtime_ns)
            elif path.is_dir():
                # Recorded so a new directory is an addition, but with neither identity
                # nor mtime: a directory's mtime is a second, noisier encoding of what
                # its children already say, and it moves whenever an excluded child is
                # written.
                entries[key] = CustodyEntry("dir", "")
            else:
                entries[key] = CustodyEntry(
                    "file", content_identity(path, status.st_size), status.st_mtime_ns
                )
        except OSError as error:
            errors.append(f"{path}: {error}")

    return CustodySnapshot(
        entries=entries,
        scan_errors=tuple(errors),
        took_ms=int((time.monotonic() - started) * 1000),
    )


@dataclass(frozen=True)
class CustodyBreach:
    stage_slug: str = ""
    label: str = ""
    added: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()
    type_changed: tuple[str, ...] = ()
    #: Digest unchanged. Not a breach -- see the module docstring -- and recorded anyway,
    #: because a reviewer that re-derived an artifact and got the same bytes did the best
    #: thing it could do and the record should hold that it happened.
    touched: tuple[str, ...] = ()
    scan_errors: tuple[str, ...] = ()
    entries: int = 0
    took_ms: int = 0

    @property
    def mutated(self) -> bool:
        return bool(self.added or self.changed or self.deleted or self.type_changed)

    def paths(self) -> tuple[str, ...]:
        return tuple(sorted({*self.added, *self.changed, *self.deleted, *self.type_changed}))

    def summary(self) -> str:
        if not self.mutated:
            return "no change"
        parts = [
            f"{len(group)} {name}"
            for name, group in (
                ("added", self.added),
                ("changed", self.changed),
                ("deleted", self.deleted),
                ("retyped", self.type_changed),
            )
            if group
        ]
        return ", ".join(parts) + ": " + ", ".join(self.paths()[:8])

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage_slug,
            "label": self.label,
            "mutated": self.mutated,
            "added": list(self.added),
            "changed": list(self.changed),
            "deleted": list(self.deleted),
            "type_changed": list(self.type_changed),
            "touched": list(self.touched),
            "entries": self.entries,
            "took_ms": self.took_ms,
            "scan_errors": list(self.scan_errors),
        }


def compare(
    before: CustodySnapshot,
    after: CustodySnapshot,
    *,
    stage_slug: str = "",
    label: str = "",
) -> CustodyBreach:
    """The difference, or an empty breach when either end is missing.

    Fail-open on absence, the rule ``docs/iclr/composable-stage-graphs.md`` states as its
    third guarantee: a census that never ran, a run root that was not there, or a walk
    that hit an unreadable tree all behave as the run behaved before this module existed.
    A precondition no real run can meet is not a strict gate.
    """

    if before.root_missing or after.root_missing:
        return CustodyBreach(stage_slug=stage_slug, label=label, scan_errors=("census did not run",))

    added, changed, deleted, retyped, touched = [], [], [], [], []
    for key, entry in after.entries.items():
        was = before.entries.get(key)
        if was is None:
            added.append(key)
        elif was.kind != entry.kind:
            retyped.append(key)
        elif was.identity != entry.identity:
            changed.append(key)
        elif entry.kind == "file" and was.mtime_ns != entry.mtime_ns:
            # Rewritten to the same bytes. This is the reviewer re-running the doer's
            # producer and getting the same answer, which is the strongest check
            # available to it, and the archive says it is the only thing an mtime census
            # ever caught here. Counted, never charged.
            touched.append(key)
    for key in before.entries:
        if key not in after.entries:
            deleted.append(key)

    return CustodyBreach(
        stage_slug=stage_slug,
        label=label,
        added=tuple(sorted(added)),
        changed=tuple(sorted(changed)),
        deleted=tuple(sorted(deleted)),
        type_changed=tuple(sorted(retyped)),
        touched=tuple(sorted(touched)),
        scan_errors=tuple(sorted({*before.scan_errors, *after.scan_errors})),
        entries=len(after.entries),
        took_ms=before.took_ms + after.took_ms,
    )


def ledger_path(paths: RunPaths) -> Path:
    return paths.run_root / CUSTODY_LEDGER_FILENAME


def record_episode(paths: RunPaths, breach: CustodyBreach) -> None:
    """One line per episode, always -- not only when something moved.

    :func:`src.supervisor.record_intervention` writes its ledger the same way and for the
    same reason: only-on-breach makes "the census never ran" and "the census found
    nothing" the same record, which is the cheapest way there is to pass a check over
    declared keys.
    """

    append_jsonl(ledger_path(paths), {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **breach.to_dict()})


class CustodyWatch:
    """The sink, in the shape :class:`src.call_cost.CostTally` already has.

    ``run_prompt`` is reached by the approval gate, by every panel seat, by the chair and
    by the verdict-only re-ask, and only some of those callers can act on a breach. A
    widened return type would make all of them restate a fact one of them uses -- the
    argument that method's own docstring already makes about cost.
    """

    def __init__(self, paths: RunPaths, *, mode: str = DEFAULT_CUSTODY_MODE) -> None:
        self.paths = paths
        self.mode = mode if mode in CUSTODY_MODES else DEFAULT_CUSTODY_MODE
        self._excluded = churn_files(paths)
        self._before: CustodySnapshot | None = None
        self.breaches: list[CustodyBreach] = []

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    @property
    def arms_a_demotion(self) -> bool:
        return self.mode == "demote"

    def open(self) -> None:
        self._before = census(self.paths.run_root, excluded=self._excluded) if self.enabled else None

    def close(self, *, stage_slug: str = "", label: str = "") -> CustodyBreach:
        before, self._before = self._before, None
        if before is None:
            return CustodyBreach(stage_slug=stage_slug, label=label)
        breach = compare(
            before,
            census(self.paths.run_root, excluded=self._excluded),
            stage_slug=stage_slug,
            label=label,
        )
        record_episode(self.paths, breach)
        if breach.mutated:
            self.breaches.append(breach)
        return breach

    def rollup(self) -> CustodyBreach | None:
        """The episode's breaches as one, or ``None`` when nothing moved.

        One review is up to twelve subprocesses on the panel path, and a seat that wrote
        changed the tree the other seats then read -- so the unit a verdict is demoted on
        is the whole deliberation, not the one call that did it. Which call it was stays
        legible: every subprocess wrote its own ledger line.
        """

        if not self.breaches:
            return None
        first = self.breaches[0]
        return CustodyBreach(
            stage_slug=first.stage_slug,
            label=",".join(sorted({breach.label for breach in self.breaches if breach.label})),
            added=tuple(sorted({p for b in self.breaches for p in b.added})),
            changed=tuple(sorted({p for b in self.breaches for p in b.changed})),
            deleted=tuple(sorted({p for b in self.breaches for p in b.deleted})),
            type_changed=tuple(sorted({p for b in self.breaches for p in b.type_changed})),
            scan_errors=tuple(sorted({e for b in self.breaches for e in b.scan_errors})),
            entries=first.entries,
            took_ms=sum(b.took_ms for b in self.breaches),
        )


#: The menu digits a demotion may rewrite, and the one it rewrites them to. Exactly one
#: mapping, and it is the only one that makes a later gate *harder*.
APPROVAL_CHOICE = "5"
DEMOTED_CHOICE = "4"


def demote(decision: Any, breach: CustodyBreach | None) -> Any:
    """Turn this episode's approval into a send-back. Never anything else.

    The invariant :mod:`src.supervisor` states for itself holds here in the same words:
    **it may never make a gate pass.** Three things in this function are what hold it,
    rather than this sentence.

    * The only non-identity mapping is ``"5" -> "4"``. A refusal is left exactly as the
      reviewer wrote it -- rewriting a ``"1"`` into a ``"4"`` would throw away a
      suggestion the run had -- and an abort is left alone, because turning a ``"6"``
      into a revise would make a stopped run continue.
    * ``discharged`` is cleared, because closing an inherited debt is a gate passing and
      a reviewer that wrote to the tree does not get to close anything. ``carry_forward``
      is kept: an obligation it attached can only add burden to a later stage.
    * ``comments`` are cleared. An anchored comment makes a refusal *local* -- change
      these spans, leave the rest -- and that is a relaxation of the refusal this
      function just issued.

    ``raw_response`` is kept. A demotion that overwrote the reviewer's own answer would
    make the mechanism unfalsifiable by the next person to read the transcript.
    """

    if breach is None or not breach.mutated or getattr(decision, "choice", "") != APPROVAL_CHOICE:
        return decision
    return replace(
        decision,
        choice=DEMOTED_CHOICE,
        decision_token="custom_feedback",
        reason=f"{CUSTODY_REASON_PREFIX} {breach.summary()}",
        feedback=(
            "This stage was not approved. The reviewer that judged it changed the run "
            "root while doing so, so its verdict is not a reading of the state you "
            "submitted:\n"
            + "\n".join(f"- {path}" for path in breach.paths())
            + "\n\nRe-run whatever produced those files and leave the result in place. "
            "If a check needs to execute the code, execute it somewhere it cannot "
            "overwrite the artifact under review."
        ),
        discharged=[],
        comments=[],
    )
