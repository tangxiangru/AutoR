# Recursive self-improvement

AutoR's stages are a directed graph the run navigates, its drafts are measured
and ratcheted so a stage can only get better, and what it learns about its own
topology accumulates across runs.

This page is the whole mechanism: what each part does, what it refuses to do, and
why the refusals are the load-bearing half.

All of it is on by default. The strict 01-through-08 sequence is still there and
still runs through the same engine — which is what keeps it exercised by every test
of the adaptive path.

```bash
# Everything below is what this does.
python main.py --goal "..."

# What the archive has learned across runs so far.
python main.py --archive-report

# Spend more on improvement, or none at all.
python main.py --goal "..." --evolve-rounds 4
python main.py --goal "..." --evolve-rounds 0     # measure and ratchet, no extra passes

# Opt out entirely.
python main.py --goal "..." --stage-graph linear --routing off --no-evolve --no-archive
```

### What each default costs

| | Default | Backend calls it adds |
| --- | --- | --- |
| `--stage-graph adaptive` | on | none |
| `--routing auto` | on | one short prompt per node with more than one live move |
| measuring + the ratchet | on | **none** — the rubric reads the run off disk |
| `--evolve-rounds 2` | on | up to two stage executions per stage, none where the rubric sees no headroom |
| archive recording | on | none |
| `--archive-steer` | **off** | none |

The split between measuring and polishing is the reason the defaults are
defensible. They were one setting to begin with, which made the free half opt-in
for no reason: a run that never polishes still gets the property that matters most,
that the promoted draft is the best one rather than the most recent.

---

## 1. The stage graph

`src/stage_graph.py`

Research is not a pipeline. Analysis finds that the experiment answered a
different question than the one that was asked. Writing finds that a claim has no
result behind it. Each of those is a *backward* move, and a linear stage list has
no way to express one — so AutoR's response to "Stage 06 shows the design was
wrong" was to write up the wrong design more carefully.

Nodes are stages. Edges are the moves allowed between them.

| Topology | Edges | Behaviour |
| --- | --- | --- |
| `linear` | the eight advance edges, unguarded, plus the abandonment terminal — nine in all | identical to the sequence AutoR has always run |
| `adaptive` **(default)** | the eight advance edges with six guards, the abandonment terminal, and thirteen backward moves — twenty-two in all | the run can return to an earlier stage when a later one shows it has to |

The backward edges exist for named research conditions, not as an error path:

| Move | Taken when |
| --- | --- |
| `06 → 05` | the results are real but insufficient to decide a hypothesis |
| `06 → 03` | the analysis exposed a confound the results cannot repair |
| `06 → 02` | the evidence refutes the hypotheses and points somewhere specific |
| `07 → 06` | a claim has no analysis behind it, or a figure does not show what the text says |
| `07 → 05` | the write-up needs a result that was never produced |
| `05 → 03` | running it showed the comparison cannot distinguish the hypotheses |
| `04 → 03` | the design is not executable as specified |

Full list in `REVISIT_EDGES`.

### Guards

Each edge carries a guard evaluated against artifacts on disk. The one that
matters is on the edge into `07_writing`: **the hypotheses must be frozen and
every one of them adjudicated.** Writing up before adjudication is how a
manuscript ends up claiming a result the run never established, and an agent asked
where to go next reaches for the deliverable.

Guards apply in the adaptive topology only. On a linear graph there is one edge
out of each node, so a guard could only halt the run, and the condition it would
halt on is already a stage validation error with a better message. Two gates over
one condition is one gate too many, and the one that fires second is the one
nobody maintains.

### A guard is a routing preference, not a gate

A closed edge is removed from the *menu the agent chooses from*. It is not removed
from the graph. When a guard has closed the forward edge and nobody has chosen
anything else, the run advances anyway, and the route records that the precondition
was unmet.

This looks like a hole and is the opposite of one. The correctness gate is the
stage's own validation, which is unchanged and still refuses a Stage 07 that writes
up unadjudicated hypotheses. Treating the guard as an absolute barrier would mean a
run that genuinely cannot satisfy it produces *nothing*, where the linear pipeline
would have produced a deliverable and failed the gate honestly. Halting is not the
safer outcome; it is the same refusal with the evidence thrown away.

**The default never goes backward.** That was tried and it was wrong, observably:
Stage 04's forward guard fails when `workspace/code` holds nothing executable, the
only backward edge out of Stage 04 leads to study design, and study design is not
the stage that writes code. The default would have sent the run somewhere that
could not fix what blocked it, attached the guard's message as though it were a
justification, and done it again next time round. Which backward edge addresses a
given block is a judgement about the research, not a computation over the graph —
so it belongs to the agent, and a run nobody is steering goes straight down the
pipeline.

A budget block is different and is never overridden. A guard says something about
the research; a budget says something about the run, and the run stopping is what a
budget is for.

---

## 2. Routing

`src/router.py`

`--routing auto`, the default, asks the backend to choose wherever more than one
move is live. On a linear graph that is never, so `auto` costs nothing there.
`--routing agent` asks at every node; `--routing off` always takes the default.

The division of labour is the point:

- **AutoR decides what is possible.** Guards are evaluated against disk. A gated
  edge is not on the menu, however the agent argues for it.
- **The agent decides what is sensible.** It has just done the work and is the only
  party that knows whether the results decided anything.
- **AutoR decides what happens when they disagree.** A choice outside the menu is
  refused, recorded, and replaced by the default edge — which at every node is the
  forward one, so a refusal degrades to the old pipeline rather than to a stall.

### A research round's decision goes through the router too

`src/research_rounds.py` closes a round at Stage 06 with `converged`,
`refine_design` (back to 03), `new_hypothesis` (back to 02) or `abandon`. The two
backward decisions are edges the graph already has, and they used to reach them by
setting `_jump_target_stage` — around the router entirely.

That had two costs. The run's most consequential routing decisions arrived at the
archive marked `bypassed` with no choice set, so the estimator excluded exactly the
moves it most wanted to learn about. And the jump happened whatever the guards said.

A closed round now *declares* an intent, and the router treats it as a proposal that
outranks the backend — the round has already reasoned about the results and written
its conclusion to disk, so asking again would be buying an opinion on a settled
question. What it does not outrank is the guards. A refused intent falls to the
forward edge and the round ledger records that it was not acted on, which it could
not do before: `record_round` runs at approval, before the router has ruled, so the
ledger could claim a round was acted on when its move was refused.

Blocked moves are shown to the agent *with the reason they are blocked*. Hiding
them is the more obvious design and it is the wrong one: an agent that can see
"`07_writing` is closed because H2 has no verdict" routes to the analysis stage
that would fix it. An agent shown only the open moves picks the best of them and
never learns what it missed.

Four refusals, each falling forward:

| Refusal | Why |
| --- | --- |
| the move is blocked | a guard failed; the reason is attached |
| the move does not exist | not an edge out of this node |
| no reason given | "continue the workflow" is not a routing decision |
| **the same reason twice** | the run has already gone back there on those grounds and it did not resolve; that is a loop, not an iteration |

The last one is checked against the *recorded reason*, not a counter, so going
back for a genuinely different reason is never penalised for the earlier trip.

Two budgets bound the walk: `--graph-max-visits` (default 3) per stage, and
`--graph-max-steps` (default 20) over the whole run.

---

## 3. Measured improvement rounds

`src/rubric.py`, `src/evolution.py`, `src/pareto.py`

AutoR already iterated: a reviewer asks for changes, the stage runs again, the new
draft replaces the old one. Nothing compared the two. A refinement that dropped a
resolving file reference or replaced a measured number with a hedge was promoted
on exactly the same terms as one that fixed something. "Refine" was a hope.

Measuring supplies the missing ordering, and it is on by default because it costs
nothing to have.

### The rubric

Eight criteria, all read off disk rather than off the prose, so the score moves
when the work moves and not when the wording does.

| Criterion | Weight | Measures | From |
| --- | --- | --- | --- |
| `contract` | 2.0 | stage markdown contract errors | all stages |
| `grounding` | 3.0 | every path the draft names resolves, and how much of the narrative is anchored in one | all stages |
| `artifact_breadth` | 2.0 | artifact kinds written *during this stage's execution* | 03 |
| `quantification` | 2.0 | findings in Key Results carrying numbers | 04 |
| `numeric_fidelity` | 3.0 | **every reported number appears in a results artifact** | 05 |
| `traceability` | 1.5 | the four decision-ledger buckets, filled and distinct | all stages |
| `commitment` | 1.5 | reports completed work rather than intentions | all stages |
| `reproducibility` | 3.0 | the machine-readable validity chain for this stage | all stages |

`numeric_fidelity` is the deep-review check. It extracts every measurement the
draft reports and looks for it in `workspace/results` and `workspace/data`,
matching a percentage against its fraction (`74.1%` is satisfied by `0.741`) with
a tolerance of half the last reported decimal. It catches the failure mode
independent evaluations of automated science keep finding — a fluent write-up
quoting metrics that exist nowhere in the run. Every other gate passes such a
draft: the sections are present, the files it names exist, the prose is
quantified. The number is simply invented.

### The ratchet

| Round outcome | What happens |
| --- | --- |
| `first` | the first measured draft becomes the champion |
| `promoted` | beat the champion by at least `min_gain`; becomes the champion |
| `frontier` | lost on the total but is the only draft holding some criterion; kept for a merge round, draft reverted |
| `regressed` | no better; **the champion's markdown is written back over the draft** |
| `verdict_drift` | the round changed what the run concluded; rejected outright |
| `directed` | a human or the reviewer asked for this one; it stands whatever it measures |

The champion is what gets promoted at approval — not the last draft. The reviewer
and the human see the best candidate the run produced.

`directed` matters as much as the rest. The ratchet governs AutoR's own polish
rounds; it does not govern a person asking for a change. AutoR silently reverting
a requested edit because a rubric preferred the previous wording would be the
opposite of the arrangement this project is built on. The delta is still measured
and written to the ledger, so the human keeps the decision and gets the number.

### The directive

A polish round is not told "make it better". It is told which criteria lost
points, what was measured, and what would raise each one — and told to leave alone
anything already at full marks, because a round aimed at a saturated criterion
produces churn.

When the Pareto frontier holds two drafts with complementary strengths and merging
them has more headroom than fixing the champion's weakest criterion, the round
becomes a **merge** instead: both candidates are on disk, the directive names what
each one uniquely holds, and asks for the draft that keeps both.

Every directive ends with the same prohibitions, because the ways a scored loop
cheats are predictable: pad the prose, restate an unverified number more
confidently, delete a weak section to raise an average, or move the finding.

### Budgets

Polish rounds are counted separately from `--max-attempts`, which bounds a stage
that is *failing*. Charging improvement rounds to the repair budget would make a
stage being made better look like one that was thrashing, and would leave nothing
if a later round broke something.

Rounds stop at `--evolve-rounds`, after two consecutive rounds with no gain, or —
before any round is paid for — when no criterion has a shortfall worth `min_gain`.
That last stop is what makes the default affordable: the other two only fire *after*
a stage execution has been bought, so without it a clean stage would pay two rounds
to reword a draft already at the ceiling of what the rubric can see.

A stage re-entered by a backward move gets a fresh round budget. Its champion
survives — that is the ratchet — but a stage doing new work because a later stage
found a problem should not be charged for the rounds its previous visit spent.

`--fake-operator` runs spend no rounds at all. A scripted operator emits the same
draft whatever the directive says, so every round would be bought, measured as a
regression and reverted. Measuring still happens, which is how the fake pipeline
keeps exercising the ratchet and the ledger.

---

## 4. The cross-run archive

`src/archive.py`

A run that navigates its own topology produces something a linear pipeline never
could: evidence about the topology. One run means nothing. Forty mean the backward
edge out of Stage 06 is worth taking, and that is a fact about the harness.

For each edge, the archive compares decisions that took it against decisions that
were **offered it and declined**.

That distinction is the estimator. The obvious control arm — runs that reached the
node and did not take the edge — pools four unrelated states: the guard was shut,
`--final-stage` pruned the move, the visit budget was spent, or the topology never
had the edge at all. Only the first kind of "did not" is a *choice*, and only a
choice is evidence about a choice.

It is not a fine distinction. Five of the seven guards read the same disk predicates
the rubric scores, so a shut guard is correlated with a weak run. Pooling those into
the control arm makes the guard a selection mechanism on the outcome, and the
contrast then measures how much worse a run is when its artifacts are missing while
reporting it as the payoff of an edge nobody could have taken. On a fixture where
routing has no effect at all, the two arms give opposite signs.

The choice set is recorded on every visit (`offered`), so "was declined" is a fact
on disk rather than an inference. The older run-level contrast is still computed and
still printed, under a heading saying it is not acted on, so the two can be seen to
disagree.

```
| Edge                            | Took | Mean  | Skipped | Mean  | Delta  | Believable |
| 06_analysis->05_experimentation | 7    | 0.842 | 9       | 0.671 | +0.171 | yes        |
| 07_writing->01_literature_survey| 1    | 0.910 | 15      | 0.706 | +0.204 | no         |
```

A believable payoff produces a child variant of the incumbent topology with **one
edge's priority moved by one step** — enough to be attributable, which a variant
that reshuffled five edges would not be. The child explains itself in the archive:
the numbers that justified it are in its note.

**What a priority actually reaches, stated honestly.** It orders the move table the
routing agent is shown, and at present that is the whole of it. It does *not* change
what a run does when nobody is steering.

`default_move` ranks only forward edges, and at most one of them is ever live at a
node: seven of the eight have a single forward edge, and Stage 06 has two — the
advance into writing and the abandonment terminal — of which the terminal is shut
unless a round concluded `abandon`, and preempts everything else when it is open.
So a priority never decides between two available forward moves.

Measured over 50 random priority assignments across all 8 nodes: **0/400** default
moves change. That half is exact and holds at every seed tried. The menu ordering
does change — around 250 of 400 — but the figure is seed-dependent and no single
integer is a stable statement of it, so the test asserts only that it is non-zero.
Both halves are pinned, the second because a test asserting "no difference" alone
would stay green if the mechanism were deleted entirely.

So the archive's influence today is advisory: it changes what the agent sees first,
not what happens if the agent is not asked. That is a smaller claim than "the
harness learns which edges pay", and it is the true one. Widening it is a decision
about wiring a learned statistic into a decision, and it should not be taken until
the estimator underneath is worth acting on.

### The composition of a run is not allowed to be the improvement

A stage's score is a weighted mean over the criteria that apply to it, and the late
stages face more of them — Stage 02 is scored on five criteria worth 11, Stage 06 on
eight worth 18, including `numeric_fidelity`, the hardest. (Not *strictly* more at
every step: 01 and 02 face the same set, and so do 05 through 08. The count is
non-decreasing and it rises twice.) So the *set of stages a run reached* is a free
parameter of the objective.

On a scripted `--fake-operator` run — the only composition that can be re-derived on
demand, and one whose scores measure the script rather than any research — the gap
is not subtle:

| Run reached | Mean fitness |
| --- | --- |
| stages 01-02 | 0.973 |
| stages 01-04 | 0.904 |
| all eight | 0.817 |

Pool those and **"stop early" is worth nearly eight times what a promotion needs**
(0.156 against a `min_gain` of 0.02). The archive would have found it, and promoted
whichever topology halted soonest — a system whose measured self-improvement
consists of producing less.

Re-derive with `--fake-operator --full-auto` and read `evolution/summary.json`. The
figures moved slightly from the ones first published here, entirely in `grounding`;
the rubric-v2 change that excluded AutoR's own bookkeeping from `artifact_breadth`
moved none of them on this fixture.

The fix is a *comparability basis*: the rubric version plus the exact set of stages
measured. Two runs may only be contrasted within a basis, per-basis contrasts are
pooled rather than the raw means, and a basis with only one arm contributes nothing
— it carries no contrast, so counting its runs would inflate the number that
decides believability without adding anything to the delta. Promotion is a
head-to-head within each basis, and a challenger that loses on *any* composition is
refused: winning on average while losing on one shape of run is the signature of a
variant that traded one kind of run for another.

This is the same rule the archive already applied to rubric versions, generalised.
Two numbers that do not measure the same thing are not two measurements of one
thing.

Three further refusals hold this together:

- **A run that did not finish is not recorded at all.** A halted or aborted run
  measured some stages and stopped, so its mean sits on an easier composition than a
  run that finished.
- **A move the run did not make is not recorded either.** A resume that starts
  somewhere other than where the last closed visit was heading is an operator
  overruling that move; it went off the router with no choice set, so it is marked
  bypassed rather than counted as a traversal.
- **Below `min_observations` on each side, nothing is acted on — and that bound is
  now derived.** An exact two-sided permutation test over arms of *a* and *b* has
  `C(a+b,a)` labellings, so no result can go below `2/C(a+b,a)`. Three a side bottoms
  out at `p = 0.10`; against a family the size of the adaptive graph's edge set the
  corrected threshold needs six. `minimum_arms_for` computes it, and the family is
  computed rather than written down — the graph has gone from eighteen edges to
  twenty-two, and a fixed divisor would have under-corrected from the first edge
  added. The previous value was three, with a docstring about intent, which meant the
  archive was licensing topology changes at a sample size where the arithmetic forbids
  the claim.

  Two families, not one, and the difference is deliberate. `min_observations` is
  derived against the whole declared edge family — `len(REVISIT_EDGES) + len(STAGES)`,
  twenty-one today — because the sample size has to be fixed before anyone looks. The
  per-row believability threshold is corrected only for the contrasts the archive
  actually holds, which on a young archive is a much weaker correction. That is the
  right shape (you cannot be penalised for comparisons you did not make) but it is not
  the same divisor, and the two should not be described with one phrase. The margin on
  the first is thinner than it looks: `minimum_arms_for(0.05, family=f)` is 6 for every
  `f` from 7 to 23 and becomes 7 at 24, so three more edges would raise the bar with no
  other change.
- **A p-value is never reported without the floor its sample size could attain.**
  *Did not show an effect* and *could not have shown one* print identically as "not
  significant" and mean opposite things.
- **A run is only compared against runs that walked the same topology, measured the
  same stages, and were driven by a real backend.** A fake operator's scores measure
  the script. A linear run never had the revisit edges, so counting it as one that
  "reached the node and declined" puts a run that was never offered the choice into
  the control arm — measured, that flips the sign of the payoff.
- **One row per run.** The archive is written on both the fresh and the resume path
  and keyed by run directory, so a resumed run would otherwise be a second free
  observation.
- **Scores from different rubric versions are never compared.** A reweight would
  otherwise read as every archived run having improved overnight.
- **A learned prior can only reorder preferences.** It cannot open a guarded edge,
  add an edge that was not declared, or remove one. The guards are the correctness
  argument for letting an agent route at all, and the component that learns from
  outcomes is exactly the one that must not be able to weaken them — the cheapest
  way to raise mean fitness across an archive would be to stop checking whether
  hypotheses were adjudicated before writing up.

Parents are sampled by fitness with a novelty bonus for under-observed variants.
Pure fitness-proportional sampling locks onto whatever won first and stops
generating the observations that would overturn it.

### What the archive is allowed to do with what it learned

Nothing, until `--archive-steer`. And then only this: **show the agent the numbers.**

The learned value reached nothing before: over 50 random priority assignments
across all 8 nodes, **0/400** `default_move` answers change. At most one forward
edge is ever live at a node, so a learned priority could only reorder rows in a
table — which it does, at a seed-dependent rate around 250/400. The measurement and
its explanation are the same one given [above](#4-the-cross-run-archive); this
section is what was done about it.

Wiring the statistic into `default_move` was the obvious fix and three independent
reviews refused it, for the same reason: it would put an unrandomised,
guard-selected statistic in charge of what the run does at the moment a guard has
just failed. The route taken instead is that the archive prints what earlier runs
measured — the two means, the sample sizes, the p-value and the floor — into the
routing prompt, and the agent decides. The agent can see this research question; the
archive has only seen other ones.

Three properties hold it:

- **Only believable contrasts appear.** A row must clear the family-corrected
  threshold *and* have been able to. Anything else is omitted rather than shown with
  a caveat, because the caveat would not be read.
- **Numbers, not a recommendation.** No sentence authored by the archive enters the
  prompt, because there would be no gate that could fire on a wrong sentence.
- **Nothing about admissibility depends on it.** Guards and `default_move` are
  untouched, and a test asserts the live move set and the default are identical with
  and without an archive that strongly prefers something else.

A broken archive is a research aid that is unavailable, not a reason to fail a
routing decision.

### Recording is on; steering is not

The archive records every run by default, because recording is free and it is the
only thing that could ever justify a change to the topology — and it cannot be
built retroactively. Whether it is allowed to *act* on what it records is a
separate question with a separate flag, `--archive-steer`, and that one is off.

A run silently using a different topology from the one the operator asked for is
not a surprise a research tool gets to spring on anyone. Turn steering on
deliberately, once `--archive-report` shows the archive has something to say.

---

## 5. Paired trials — does any of this help?

`src/trials.py`

Everything above is argued for from first principles and defended by unit tests.
None of it has evidence that it improves a research output. The rubric measures a
draft; nothing has compared a run that had a mechanism against a run that did not.

The archive cannot supply that. Its comparisons are observational — runs differ by
goal, and goal difficulty swamps everything, so six runs on each side of a contrast
tells you which questions were easier.

A **paired trial** fixes it cheaply. Run the same goal twice, once with the
capability and once without, and the statistic becomes the within-pair difference.
Goal difficulty cancels.

```bash
python main.py --goal "$GOAL" --trial g1 --capability effort_tiers --arm off
python main.py --goal "$GOAL" --trial g1 --capability effort_tiers --arm on --effort-tiers
# ... repeat with g2, g3, ... on different goals
python main.py --trial-report
```

All three tags are required together: a `--trial` with no `--capability` cannot be
grouped with anything, and an `--arm` with no `--trial` is a label on a run nobody
can pair. Both would look like data and be none.

### What it refuses to compute

**It does not compare across a composition difference, even inside a pair.** If the
treatment arm abandoned at Stage 06 and the control ran to Stage 08, their mean
fitness is not one measurement of two configurations — the arm that stopped early
scores higher *for stopping early*. That is the bias the comparability basis exists
to remove, reappearing within a pair. The difference is taken over the stages both
arms measured, and pairs whose shapes differed are counted and reported separately:
a capability that changes how far runs get has done something, and it is not a
score.

**It does not report a total without the criterion decomposition.** A capability
that writes more files raises `artifact_breadth` whether or not the research
improved. The report prints the per-criterion difference and a concentration figure;
above 60% in one criterion it says so. A win concentrated in a single criterion is a
flag, not a result.

**It does not call an unattainable result "not significant".** An exact two-sided
sign-flip test over *n* pairs cannot go below `2 / 2**n` — three pairs bottom out at
0.25, six at 0.031. Below six pairs, no result reaches 0.05 at any effect size. The
floor is printed beside the p-value, so *did not show an effect* stays
distinguishable from *could not have shown one*.

**It does not estimate from fake runs.** One `--fake-operator` arm disqualifies the
pair, because a scripted operator's score measures the script.

### What it does not measure

The rubric score, which is a proxy for rigour and not a measure of insight. A
capability can raise it without making the research better, and can make the
research better without raising it. The decomposition and the shape counts are there
so a reader can argue with the number instead of accepting it.

---

## What has and has not been measured

The mechanisms above are argued for from first principles and defended by unit
tests. That is not the same as evidence that they improve a research output, and
this section exists so a reader can tell the two apart.

**Measured, and re-derivable on demand.** Everything in this document with a number
attached: the criterion weights per stage, the composition gap, the 0/400 reach of a
learned priority, the permutation floors. All of these come from running the code —
mostly with `--fake-operator`, which measures the harness rather than any research —
and every one can be re-derived from the commands named beside it.

One of them is worth singling out because it is the strongest negative result here.
`tools/archive_sample_complexity.py` drives the *real* graph and the *real*
`edge_payoffs` under a forward-only routing policy and asks how many edges become
believable. The answer is zero at every sample size it sweeps — N = 5, 10, 25, 50,
100, 200, 500, 1000, with `P(at least one believable) = 0.00` at each. That is not
"we have not collected enough runs yet"; it is a property of the estimator and the
policy together, and it is why `propose_exploration` exists. The instrument had
itself stopped running at some point — `RunRecord` gained a required field and it
crashed on its first record — which is the reason a fast construction check now
guards it.

The same sweep says something less comfortable about the other end. Under a policy
that *does* explore, clearing the believability gate is not the same as picking the
right edge. Planting a true effect on two edges and asking what `propose_variant`
would then propose:

| Runs in the archive | It proposes something | The edge it picks has no real effect |
| --- | --- | --- |
| 10 | 0% | — |
| 25 | 34% | **77%** |
| 50 | 80% | 7% |
| 100 | 100% | 0% |

(at `sd_run = 0.0027`, the run-to-run spread of `mean_fitness`; the pattern holds
across a sweep from 0.0027 to 0.08, and gets worse as the spread grows — at 0.08 the
picked edge is still a null one 57% of the time at N = 100.) `min_observations = 6`
is a per-edge false-positive control and it is doing its job; it is not, and was
never, a guarantee that the *best* of the surviving edges is a real one. The window
between "the archive starts having opinions" and "the archive is right" is roughly
25 to 50 runs wide, and it is the direct argument for `--archive-steer` defaulting
off rather than a matter of taste.

**Not measured.** Whether any of this makes research better.

- **The cross-run archive has zero real runs.** Every number it can produce today
  comes from synthetic records in the test suite. `--archive-report` on a fresh
  install prints an empty table, and that is the honest state: the estimator, the
  believability gate and the promotion rule are all implemented and none of them has
  ever been fed a real observation.
- **The paired-trial mechanism has never completed a trial.** Six pairs were
  attempted on 2026-08-11 — the same goal twice, `--evolve-rounds 0` against `2`,
  strictly one run at a time with backoff. The result was 46 attempts and **zero
  recorded runs**, every one failing on Vertex quota (`RESOURCE_EXHAUSTED` for
  `anthropic-claude-sonnet-4-5`, 218 errors). A rate-limited run auto-skips its
  stages, and a skipped stage is never scored, so nothing reached the archive. The
  blocker is infrastructure, not the mechanism — but the mechanism is unproven on
  real data either way.

So when this document says a capability *is* better, it is describing an argument.
When it says a capability *measures* better, it means the rubric, on a scripted run.
Nothing here yet says a capability produced better research, and the paired trial is
the thing that would.

---

## The constraint the whole design is built around

A fitness function plus a loop is an optimiser. Point an optimiser at a research
pipeline and the cheapest way to raise the score is to change the finding.

`src/preregistration.py` already stops a human-driven version of that. A scored
improvement loop would reintroduce it with a budget. So:

**No criterion reads a verdict value.** Adjudication records are routed through
`_verdict_blind_outcomes`, which strips the verdict before any scoring code can
see it. Stage 06 is scored on whether every preregistered hypothesis carries a
verdict backed by an artifact that exists — a hypothesis *refuted* cleanly with the
evidence on disk scores higher than one supported on an assertion.

**A round that moves a verdict is rejected.** Blindness removes the gradient; it
does not remove the possibility. `verdict_digest` fingerprints the verdict set, and
a polish round that changed it is reverted with a `verdict_drift` row in the
ledger — regardless of what it scored. Since the rubric is blind, a rewritten
conclusion scores the same, which is exactly why this check cannot be a score
comparison.

**The rubric is mechanical.** An LLM judge scoring drafts written by the same model
family is a fitness function the optimiser can talk to, and the point of a ratchet
is that it cannot be argued with. Qualitative judgement stays where it already is:
the human, or the reviewer agent at the stage boundary, which now sees the best
candidate instead of the most recent one.

Both properties are tested end to end rather than argued for. `tests/test_rubric.py`
flips every verdict on disk and asserts the total does not move; the neighbouring
test asserts the digest does.

---

## What is on disk afterwards

```
runs/<run_id>/evolution/
├── stage_graph.json              # every visit, the move out of it, who chose, the score
├── improvement_ledger.jsonl      # one row per round: criteria, delta, verdict, note
├── routing_refusals.jsonl        # every refused agent choice and what it fell back to
├── summary.json                  # settled champion score per stage
└── <stage_slug>/
    ├── champion.md / champion.json
    ├── frontier.json
    └── candidates/attempt_NN.md  # including the ones that lost
```

The losing candidates are kept deliberately. A discarded draft is the only
evidence that the ratchet discarded anything; without it, a run says "the champion
scored 0.84" and there is no way to tell that from a run that only ever produced
one draft.

`evolution/` sits outside `workspace/` because it records how the run reached its
answer, not part of the answer. A benchmark export that swept it up would ship the
losing drafts alongside the report.

---

## Relation to prior work

Four systems this builds on, and where the research-harness setting required
something different.

**Darwin Gödel Machine** (Zhang et al., [arXiv:2505.22954](https://arxiv.org/abs/2505.22954))
— an archive of self-modified agents, empirical validation instead of proof,
parents sampled from the archive rather than only the incumbent. AutoR keeps the
arrangement and changes the unit of variation from agent source code to
**topology**. A research harness people run on their own machines should not
rewrite its own Python between runs; a topology is data, it diffs, it reverts, and
it can be validated before it is used. Promotion is also stricter: a rigour score
on a research run is noisier than a SWE-bench pass rate, so an improvement has to
replay before it is believed.

**GEPA** (Agrawal et al., [arXiv:2507.19457](https://arxiv.org/abs/2507.19457)) —
natural-language reflection over execution traces in place of scalar reward, and a
Pareto frontier so a specialist is not evicted by an average. AutoR's frontier is
over **rigour criteria** rather than tasks, which fits a research stage better:
there is one task, and the interesting variation is which dimension of it a draft
got right. The reflective mutation is grounded in the criterion that lost points
and the evidence for it, rather than in a free-form trace reading.

**The AI Scientist v2 / v3** (Sakana AI) — tree search over candidates, and a deep
reviewer that checks manuscript claims against raw numerical output. The candidate
tree is here as the champion-plus-frontier, with losers kept. The deep reviewer is
here as `numeric_fidelity`, made mechanical: a check that reads the results files
cannot be talked out of a discrepancy.

**ADAS / Meta Agent Search** (Hu et al., [arXiv:2408.08435](https://arxiv.org/abs/2408.08435))
— a meta agent that writes new agent workflows in code, with an archive of
successful designs. AutoR does the topology part online and typed: instead of a
meta agent inventing a workflow offline, the graph is navigated at runtime with
mechanically-checked guards, and the archive learns edge statistics from measured
outcomes.

The thing none of the four had to solve is the one this page keeps returning to.
Each of them optimises against an external ground truth — a benchmark pass rate, a
task score. Research has none, which is the whole problem. Substituting a rigour
measurement for a quality judgement is what makes the loop safe to run, and making
that measurement blind to the finding is what stops it becoming an automated
p-hacker.

---

## Deliberate non-goals

- **AutoR does not edit its own shipped Python.** The self-edit surface is the
  topology. Prompt-template and skill overlays are the natural next surface and are
  not implemented.
- **No LLM judge in the fitness function.** See above.
- **The archive does not tune prompts.** It learns about moves.
- **A learned prior never touches a guard.** Stated three times on this page
  because it is the property that would be most tempting to relax.
