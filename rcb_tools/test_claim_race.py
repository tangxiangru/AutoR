#!/usr/bin/env python3
"""The claim protocol must let exactly one launcher run a task.

Every test here is a real incident or a hole an adversarial review reproduced against this
file, not a hypothesis. The protocol has now been wrong four times, each time in a way that
looked fixed, so each test names the shape it holds down:

  1. Takeover was a bare `_record_owner` -- an unconditional write, so every launcher that
     reached the same verdict "won". Eleven `main40` tasks ran 2-3 times on 2026-08-19.
  2. Numbered `takeover-<n>` directories, each launcher computing n from a fresh glob. The
     second arrival saw 000, worked out 001 was free, and took it: noticing that somebody
     else had taken over became the reason to take over as well. 12 contenders, 3 winners.
  3. A stale-lock reaper that did `rmdir` then `mkdir`. Two launchers that both judged the
     lock stale both deleted it, and the second deletion took the first one's *live* lock.
     12/12 trials multi-winner at n=12; 4/10 across four real Slurm nodes, winners on
     different hosts.
  4. The same reaper rewritten as an atomic `rename`. That fixes who wins the reap, not what
     is reaped: a launcher holding a moment-old verdict renames away a live successor's
     lock. 12/25 trials multi-winner. There is now no reaper -- the lock fails closed.

Also covered: the first-claimant window (`mkdir` then stamp left the claim briefly unowned)
and `_owner_alive` calling a live sibling process dead because it shared a job id.

Run with `python3 test_claim_race.py`. No pytest, no network, no Slurm. Temporary roots go
on /rmeng_data because that is the NFSv3 mount the protocol actually has to hold on.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_arm  # noqa: E402

#: Enough contenders that a lost race is not a coin flip. The reproduced holes needed
#: n >= 3 to appear at all and were near-certain by n = 12.
CONTENDERS = 12
#: The multi-winner holes were intermittent. One green run means little.
TRIALS = 15
#: The shared mount, not /tmp: three of the four holes were found on NFS behaviour.
SCRATCH = "/rmeng_data/robtang/_tmp"


def _seize_worker(claim_str: str, barrier, out) -> None:
    """A launcher that has just decided the owner is gone."""
    claim = Path(claim_str)
    token = run_arm._owner_token(claim)   # the verdict's evidence, read before the race
    barrier.wait()
    out.put(run_arm._seize(claim, token))


def _stake_worker(claim_str: str, barrier, out) -> None:
    """A launcher reaching a task nobody has claimed yet."""
    claim = Path(claim_str)
    barrier.wait()
    out.put(run_arm._stake(claim))


def _acquire_worker(claim_str: str, barrier, out) -> None:
    """The shipped decision, whole. `run_arm.acquire`, not a paraphrase of it.

    Paraphrasing is how this file produced its own wrong answer: a worker that re-implemented
    the acquire logic and omitted the `_claimed_recently` guard reported two winners against
    code that was correct. The real call site is one line -- `acquire(claim, root, task)` --
    so the test can be too.
    """
    claim = Path(claim_str)
    root, task = claim.parent.parent, claim.name
    barrier.wait()
    took, _ = run_arm.acquire(claim, root, task)
    out.put(took)


def _race(target, claim: Path, n: int = CONTENDERS) -> int:
    ctx = mp.get_context("fork")
    barrier, out = ctx.Barrier(n), ctx.Queue()
    procs = [ctx.Process(target=target, args=(str(claim), barrier, out)) for _ in range(n)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
    return sum(out.get() for _ in range(n))


class ExactlyOneRunnerTests(unittest.TestCase):
    """The only property that matters: never two agents on one task."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.root = Path(self.tmp.name)
    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _claim(self, i: int, *, exists: bool) -> Path:
        c = self.root / f"t{i}" / ".claims" / "Math_001"
        (c if exists else c.parent).mkdir(parents=True)
        return c

    def test_seizing_a_dead_claim(self) -> None:
        """Holes 1-4. Run repeatedly: every one of them was intermittent."""
        counts = [_race(_seize_worker, self._claim(i, exists=True)) for i in range(TRIALS)]
        self.assertEqual([c for c in counts if c != 1], [], f"winners per trial: {counts}")

    def test_staking_a_claim_nobody_holds(self) -> None:
        counts = [_race(_stake_worker, self._claim(i, exists=False)) for i in range(TRIALS)]
        self.assertEqual([c for c in counts if c != 1], [], f"winners per trial: {counts}")

    def test_the_whole_acquire_path_from_nothing(self) -> None:
        """The first-claimant hole, through the shipped `acquire`: stake racing seize."""
        counts = [_race(_acquire_worker, self._claim(i, exists=False))
                  for i in range(TRIALS)]
        self.assertEqual([c for c in counts if c != 1], [], f"winners per trial: {counts}")

    def test_small_contender_counts_too(self) -> None:
        """Hole 3 needed n>=3 and was invisible at n=2. Do not only test the easy case."""
        for n in (2, 3, 4, 6):
            counts = [_race(_seize_worker, self._claim(100 + n * 10 + i, exists=True), n)
                      for i in range(8)]
            self.assertEqual([c for c in counts if c != 1], [],
                             f"n={n} winners per trial: {counts}")


class LockFailsClosedTests(unittest.TestCase):
    """No reaper. A lock nobody releases costs a delayed re-run, never a duplicate."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.claim = Path(self.tmp.name) / "Math_001"
        self.claim.mkdir(parents=True)
    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_a_leaked_lock_blocks_rather_than_being_reaped(self) -> None:
        """The deliberate trade. If this starts passing by seizing, a reaper is back."""
        lock = self.claim / ".seize.lock"
        lock.mkdir()
        old = time.time() - 86400
        os.utime(lock, (old, old))
        saved, run_arm.LOCK_WAIT_SECONDS = run_arm.LOCK_WAIT_SECONDS, 0.3
        try:
            self.assertFalse(run_arm._seize(self.claim, run_arm._owner_token(self.claim)),
                             "a day-old lock was reaped; reaping cannot be done safely here")
        finally:
            run_arm.LOCK_WAIT_SECONDS = saved

    def test_the_lock_is_released_on_the_way_out(self) -> None:
        """Failing closed is only tolerable if the normal path never leaks."""
        self.assertTrue(run_arm._seize(self.claim, run_arm._owner_token(self.claim)))
        self.assertFalse((self.claim / ".seize.lock").exists())


class OwnerIdentityTests(unittest.TestCase):
    """`_owner_alive` returning False lets the caller override a live heartbeat, so False has
    to mean certainly dead. It did not: any owner sharing this job id was called dead, which
    includes a live sibling process. Three nodes TOOK one task through that branch."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.claim = Path(self.tmp.name) / "Math_001"
        self.claim.mkdir(parents=True)
        self.saved = dict(os.environ)
        os.environ["SLURM_JOB_ID"] = "48874"
        os.environ.pop("SLURM_RESTART_COUNT", None)
    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.saved)
        self.tmp.cleanup()

    def _stamp(self, text: str) -> None:
        (self.claim / "owner").write_text(text, encoding="utf-8")

    def test_a_sibling_process_of_this_allocation_is_not_called_dead(self) -> None:
        self._stamp(f"48874:0:{os.getpid() + 1}@somewhere")
        self.assertIsNone(run_arm._owner_alive(self.claim),
                          "a live sibling was reported dead; that is the three-node hole")

    def test_my_own_earlier_allocation_is_dead(self) -> None:
        """The requeue case the self-stamp check exists for. Slurm keeps the job id."""
        os.environ["SLURM_RESTART_COUNT"] = "2"
        self._stamp("48874:1:12345@somewhere")
        self.assertIs(run_arm._owner_alive(self.claim), False)

    def test_this_very_process_is_alive(self) -> None:
        self._stamp(run_arm._this_job())
        self.assertIs(run_arm._owner_alive(self.claim), True)

    def test_an_unstamped_claim_is_unanswerable(self) -> None:
        """Claims written before the stamp existed must fall back, not be declared dead."""
        self.assertIsNone(run_arm._owner_alive(self.claim))

    def test_the_stamp_distinguishes_the_three_cases(self) -> None:
        self.assertEqual(run_arm._parse_owner(run_arm._this_job()),
                         ("48874", 0, os.getpid()))


class StakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.root = Path(self.tmp.name)
    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_a_staked_claim_is_owned_the_moment_it_exists(self) -> None:
        """The window the old `mkdir`-then-stamp left open."""
        claim = self.root / ".claims" / "Math_001"
        claim.parent.mkdir(parents=True)
        self.assertTrue(run_arm._stake(claim))
        self.assertNotEqual(run_arm._owner_token(claim), ("", 0))

    def test_staking_an_existing_claim_fails(self) -> None:
        """Including a legacy EMPTY one: renaming a staged directory would have replaced it."""
        claim = self.root / ".claims" / "Math_001"
        claim.mkdir(parents=True)
        self.assertFalse(run_arm._stake(claim))

    def test_a_fresh_stampless_claim_reads_as_settling(self) -> None:
        claim = self.root / ".claims" / "Physics_000"
        claim.mkdir(parents=True)
        self.assertTrue(run_arm._claim_settling(claim))

    def test_a_legacy_stampless_claim_does_not_block_for_ever(self) -> None:
        """29 of these are on disk, written before the stamp existed."""
        claim = self.root / ".claims" / "Earth_000"
        claim.mkdir(parents=True)
        old = time.time() - run_arm.STAKE_SETTLE_SECONDS - 60
        os.utime(claim, (old, old))
        self.assertFalse(run_arm._claim_settling(claim))

    def test_a_staked_claim_is_not_settling(self) -> None:
        claim = self.root / ".claims" / "Life_002"
        claim.parent.mkdir(parents=True)
        self.assertTrue(run_arm._stake(claim))
        self.assertFalse(run_arm._claim_settling(claim))


if __name__ == "__main__":
    unittest.main(verbosity=2)
