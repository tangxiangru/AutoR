# What the Comparison Changed

*The implementation record behind [round-loop-and-stage-graph.md](round-loop-and-stage-graph.md).
That document is the reading: what AMAP-ML's LongHorizon-Harness does, what AutoR does, and
which differences are worth acting on. This one is what happened when the list was worked
through — what landed, what was refused and by what, and every number the decisions rest on.*

**Every figure here carries an as-of date and the command that produces it.** That is not
decoration. The archive under `/rmeng_data/robtang/rcb_runs` is written to continuously by
runs in flight, and the first version of this document quoted a dozen numbers taken from
`[:40]`, `[:120]` and `[:200]` slices of it as though they described a fixed population.
Section 3 is what that cost.

---

## 1. What landed

| PR | What it does |
| --- | --- |
| #254 | The reading itself, plus the channel count that had rotted while `docs/iclr/` sat outside the doc-count scan |
| #256 | §4.7 (1) and (2): obligations vanishing from every retry; a second entry to a stage replaying a spent session id |
| #258 | §4.1: a content census of the run root around every reviewer subprocess |
| #267 | §4.5: the deliverables gate stops being conditional on the output format |
| #271 | **Not from the list.** A launch race in the FrontierScience trial driver, found because it was reddening every pull request |
| #268 | §4.3: the closing sentence is derived from the record rather than asserted |
| #273 | §4.6: the cost ledger gets a reader, and the supervisor rule is *refused* one |
| #278 | §4.2: an overridden refusal stops being recorded as an approval |
| #279 | §4.4: a channel declares what it may spend; the run records what it spent |
| #282 | §4.7 (3): the prompt stops asserting a conversation it cannot know about |

Three items on the list were deliberately not built (§4), and one shipped change had to be
corrected afterwards (§3.1).

---

## 2. Every number, and how to get it again

### 2.1 The reviewer custody census (#258)

    python3 tools/review_custody_replay.py

Over the four runs the tool pins by name: **152 reviewer episodes**. An mtime census fires
on **152 of 152** with no exclusion list and **4 of 152** with one, all four in
`Astronomy_000_20260814_175426`, touching seven files, every one `workspace/results/*.json`.

All four are one behaviour, and it is the behaviour a reviewer is supposed to have:
re-running the doer's producer scripts in place to check they reproduce. Both of the two
approvals among them say so in their own recorded reason. **That is why the shipped census
compares content and not modification time.** None of the seven carries a self-describing
generation timestamp; two carry ISO-8601 strings echoed from upstream artifacts rather than
read off the clock, so a deterministic re-run of the producer reproduces the same bytes.

The replay can only ever be an upper bound — an archive keeps one modification time per
file, so how far below 4 the content-keyed rate sits **cannot be settled from disk**. Hence
`--review-custody` defaults to `record`.

Cost, `src.review_custody.census` on the same four roots, warm cache, ten repetitions:
medians **516, 567, 1188, 1278 ms**, full observed range 428–1541 ms. Two per episode, so
roughly 1–3 s per episode and 3–7 minutes over a run.

What the census cannot see: in the same 152 episodes there are **three tool-level writes**
(two `Write`, one `Edit`), and **two go to a `~/.claude/projects/.../memory/` directory
outside any run root**. The claim it supports is *"the reviewer changed nothing it was
judging"*, not *"the reviewer changed nothing"*.

> **This population moved under the pin, and the tool caught it.** These figures were 138
> and 4 when #258 landed. `Chemistry_000_20260816_173127` was still executing when it was
> named in `MEASURED_RUNS`, so it kept producing episodes: 138 → 152, fires unchanged at 4.
> The tool printed `population: DRIFTED` until the constants were re-pinned. Pinning a
> still-running directory as a population is the same mistake as §3.2, caught by a
> mechanism that existed for exactly this.

### 2.2 Prompt and channel sizes (#279, #282)

All as of **2026-08-18**, over `/rmeng_data/robtang/rcb_runs`, 13,671 attempt prompts
(review, panel, repair and route prompts excluded) across ~394 run roots.

| | median | p90 | max |
| --- | --- | --- | --- |
| `memory.md` (n=438 roots) | 173 KB | 237 KB | 290 KB |
| stage prompt, all stages | ~156 KiB | — | **3.17 MB** |
| stage prompt at `01_literature_survey` | 20 KB | — | — |
| stage prompt at `07_writing` | 277 KB | 358 KB | — |
| `# Original User Request` | 13.6 KB | 15.3 KB | 16.7 KB |
| `# Approved Memory` (build_prompt path only) | — | ~175 KB | 301 KB |
| `# Stage Handoff Context` | — | ~123 KB | — |

`MAX_RETRY_GOAL_CHARS = 24_000` is set against the goal row — above its observed maximum,
so it clips nothing the archive contains — while approved memory stays a pointer on the
retry path because of the row below it.

Per-channel bodies, extracted from the archived prompts by each channel's own `heading`,
which is the quantity `_render` compares to `max_chars`:

| channel | p50 | p90 | p99 | max | budget |
| --- | --- | --- | --- | --- | --- |
| `decision_ledger` | 25,476 | 48,703 | 68,838 | 91,431 | 120,000 |
| `hypotheses` | 22,914 | 31,362 | 45,480 | 79,284 | 96,000 |
| `preregistration` | 12,078 | 18,431 | 27,908 | 71,386 | 96,000 |
| `writing_manifest` | 10,431 | 20,195 | 138,788 | **2,774,270** | 160,000 |
| `report_plan` | 13,897 | 19,802 | 25,792 | 28,291 | 30,000 |
| `validity_findings` | 16,046 | 20,375 | 23,526 | 26,460 | 32,000 |
| `hypothesis_verdicts` | 13,836 | 19,244 | 23,427 | 25,198 | 32,000 |
| `research_rounds` | 4,880 | 7,005 | 14,842 | 19,614 | 24,000 |
| `experimental_protocol` | 4,877 | 6,618 | 8,249 | 9,558 | 12,000 |
| `task_shaped_skills` | 2,485 | 4,592 | 6,698 | 7,411 | 12,000 |
| `artifact_index` | 1,820 | 2,281 | 2,718 | 4,552 | 6,000 |
| `experiment_manifest` | 1,492 | 1,679 | 1,823 | 1,896 | 6,000 |
| `intake_resources` | 1,430 | 1,517 | 1,620 | 1,620 | 4,000 |

Every budget sits above its channel's observed maximum **except `writing_manifest`**, and
that one is deliberate: a maximum two hundred times the p99 is an outlier, and a ceiling
above it would be no ceiling. Four channels render nothing anywhere in this archive
(`project_context`, `idea_pool`, `researcher_profile`, and the unbudgeted
`settled_reasoning`), so their ceilings are stated guesses rather than measurements.

### 2.3 The send-back override (#278)

One pass, one instant, **as of 2026-08-18T21:23:09Z**, over 394 `logs.txt`, counting
headings matching `=== <ts> | <slug> attempt <n> sendback_refused ===` with a Python scan:

- **131 of 394 runs (33%)** contain at least one override
- **2212 override events**, median **15** per affected run, maximum **52**
- of **5534** recorded `choice: 5` lines, **2212 — 40% — are the harness overruling a
  refusal** rather than a reviewer accepting the work

Two things the number is not. The archive mixes builds: every run containing an override is
from 2026-08-17 or later, so the archive-wide share **understates** the rate inside the arms
that can produce one. And overrides are a *subset* of the `choice: 5` population rather than
a comparison class — every overridden refusal is rewritten to `5` and then logged as one.

**Do not count these with `grep -c`.** 44 of the 394 logs contain bytes GNU grep treats as
binary; `grep -c` on those prints nothing at all and exits 1, which a shell reads as a zero.

### 2.4 The launch race in the trial driver (#271)

Not from the list. Found because `tests/test_fs_trial_driver.py` was failing about one
module run in three under load — a different test each time, never in isolation.

The defect is proven on a pure function. `next_actions` abandons a `launched` run whose
`child_pid` is not in `autor_pids(...)`, and neither end of that test is observable when a
run has just started: `tools/fs_trial.py` writes the state file *before* `Popen` with no pid
at all, and `autor_pids` walks `/proc` — **31–37 ms on a quiet box, longer under load**,
most of it the walk rather than the child. A healthy run could be pronounced dead
microseconds after starting, its replacement given a fresh workspace, and both paid for.

`FS_LAUNCH_GRACE_SECONDS = 60` closes it: three orders of magnitude above that latency and
**forty-five times below `FS_STALL_SECONDS` (2700)**, the same module's existing statement
about how long a run may be silent before anyone worries.

**The attribution is not proven.** Eight loaded module runs with the fix and eight without
both came back clean, so that comparison has no power. Since the fix landed the module has
gone **8 consecutive clean runs** and CI has passed first time on six successive pull
requests; against a 1-in-3 per-run failure rate eight clean runs has probability 0.039 —
evidence, not proof, and a clean sample cannot distinguish "fixed" from "not triggered".

### 2.5 The two smaller populations

**Coverage (#267).** Every archived run config is `output_format: markdown`; zero latex.
The count was **335 when the branch was written, 379 at merge, 437 as of 2026-08-18** — the
population grew, the finding did not change. So moving `validate_deliverables_coverage` out
of the markdown branch changes no archived run's verdict, which §3.3 returns to.

**Supervisor (#273).** Replayed over `tools/supervisor_threshold_replay.py`'s
`MEASURED_RUNS`, concatenating prior visits' failure digests into the repeat rule changes
**0 of 22 visits**; only **2 of 20 stages** in that population were visited more than once,
and neither repeated a digest. Both re-derived independently.

---

## 3. Where a measurement said the wrong thing

Four times. This is the most transferable part of the record.

### 3.1 A budget measured on a sample clipped the median render

`Channel.max_chars` shipped in #279 with the claim that every ceiling sat above its
channel's observed maximum. It was measured over a **40-run-root sample**. Over the full
13,671 prompts, **six of sixteen budgets were below the real maximum and two were below the
median**: `decision_ledger` clipped **53.6%** of renders and `writing_manifest` **72.0%**.

A budget that bites the median render is not headroom — it is a silent edit to every prompt.
The six were raised, and the full table now sits in `information_flow.py` beside the field.
The sample was not merely small; it was unrepresentative in a knowable way, because a
channel that appears late in a run is under-sampled by any slice of a directory that is
still filling up.

### 3.2 A ratio of two numbers taken ten hours apart

The override rate was first published as **45%** — 1270 events over 2802 approvals. Those
counts were taken about ten hours apart from a growing archive. At the moment 2802 held
there were 512 events; at the moment 1270 held there were 4-and-a-bit thousand approvals.
**The two were never simultaneously true, and no single-instant snapshot of the archive
yields 45%.** §2.3 is one pass at one timestamp.

### 3.3 A population with no instance of the case cannot price it

The supervisor replay said the change was free — 0 of 22 visits. It was also wrong: feeding
the closed rows into `unchanging_failure` ends a revisit at its first repeated attempt, and
two tests already in the tree are this repository's decision the other way. The replay had
no multi-visit repeat in it, so it could not see the case at all. **"The blast radius is
zero" is not "the change is right."**

The same shape twice more. The coverage measurement said 335 of 335 archived runs are
markdown, so lifting the gate out of the markdown branch was free — and the *test suite*
then found what the archive could not, because the fake operator carried the same coupling
in a second place and no archived run exercised either. And the custody population moved
under its own pin (§2.1) because a run named in it was still executing.

### 3.4 A number read while it is being written is not a measurement

Mid-work five benchmark scores were reported from `<workspace>/_score.json` and moved
between two readings. They were the wrong artifact: the authoritative scores are written by
`score_items.py` into `rcb_results/gpt51_*/` by the gpt-5.1 judge this repository's own rule
names. The `_score.json` files were being rewritten by a scoring pass in flight.

---

## 4. What was refused, and by what

| Proposal | What refused it |
| --- | --- |
| Feed closed visits' digests to the supervisor's repeat rule (§4.6) | Two existing tests. A revisit is entitled to its own attempts even when it meets the objection that ended the last one. `TheRepeatRuleDeliberatelyStopsAtTheVisitBoundaryTests` pins the refusal. |
| A guard on the `finish` edge (§4.3) | Three measured decisions: the forward gate must still count a skipped stage's artifacts; `_route_to_deliverable` bypasses the writing guards on purpose; `default_move` excludes `finish` from its last-resort fallback. The fix went on the *label*. |
| A fourth `run_status` value (§4.3) | Six places in `src/frontend/static/app.js` test `=== "completed"` for settledness, plus `humanStatus` and a CSS class — a wide change across a surface this suite does not cover, for a defect entirely in a sentence. |
| A `promotion_basis` vocabulary (§4.2) | The skip paths already record authority through `skip_kind` and the nine-value outcome ledger, and an overridden refusal is a *third* state: the reviewer did read the draft and scored every mechanical criterion. |
| A `prior_refusals` channel into the doer (§4.6) | Measured adversely already: `review_policy` excludes rules whose origin stage is this stage, because doing otherwise raised the bar one requirement per attempt and prevented convergence. |
| Attempt-grained artifact attribution (§5) | Nothing consumes it, and the natural fix is the one `composable-stage-graphs.md` measured and reversed. |
| A recovery rung for a spent session id (§4.7) | After the cause is fixed nothing can hand `--session-id` an id it has already spent. A rung with no caller is the mistake this repository names in its own design notes. |

---

## 5. Still open

- **The three largest prompt blocks are still uncapped.** Approved memory and the handoff
  context are arguments to `build_prompt` rather than channels, so `Channel.max_chars` does
  not reach them — and at ~175 KB and ~123 KB at p90 they are larger than every channel put
  together. The repair prompt still inlines whole stdout, stderr, original prompt, draft and
  promoted file, while the same module caps stdout at 2000 characters for its *log* excerpt.
- **The deliverables contract is still checked once, at the end.** #267 made it
  format-independent; it did not give the coverage artifact an earlier writer or a reviewer
  axis.
- **`--review-custody` defaults to `record`.** Arming the demotion waits on a live arm's
  ledger, for the reason in §2.1.
- **Whether #271 removed the flake is unverified.** §2.4.
- **Four channel budgets are untested**, because those channels render nothing in this
  archive. §2.2.

---

## 6. What this cost, and what it did not buy

Ten merged changes plus one correction. Four are behaviour changes; the rest change what the
record says. Every one carries a test that goes red without it.

None has been measured on a run. The benchmark arms in flight during this work were pinned
to commits that predate all of it, deliberately — a measurement whose instrument changes
underneath it is not a measurement. So the honest summary is the one this repository already
applies to its own machinery: **a mechanism that improves the record and is never measured
on a run has improved the record.** Whether any of it moves a score is unknown, and nothing
here should be quoted as if it did.
