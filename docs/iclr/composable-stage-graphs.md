# Composable Stage Graphs

*Design notes for the AutoR framework paper. This document states the model, the
mechanisms that implement it, and what each one is measured against. It is written to be
lifted into a paper, so every claim here is either implemented and tested in this
repository or marked as not yet.*

---

## 1. The problem: a research run is not a pipeline, and a pipeline is not a graph

AutoR runs a research project as eight stages. Real research does not walk them once.
Analysis discovers that the experiment answered a different question than the one that was
asked; writing discovers that a claim has no result behind it; a result nobody planned for
turns out to be worth more than the one that was. Each of those is a *backward* move, and
AutoR's topology admits thirteen of them.

Admitting a backward move is the easy half. The hard half is what the move does to the run.
A stage that has been visited has changed the shared workspace: it wrote data, code,
figures, notes, manifests. A backward edge that leaves those changes in place does not undo
a decision, it merely stops talking about it — and the run continues on top of the state the
abandoned decision produced.

This is the failure a graph topology invites and a pipeline never had to face. It has two
halves, and they are orthogonal:

- **What a stage changed.** When a stage is withdrawn, the modifications it made to the
  shared workspace must be undone — completely, and without taking anything else with them.
- **What a stage read.** A stage's approval is a claim about a state: *given these inputs,
  this output was accepted.* When an input moves, that claim expires, and the run has to
  know which claims those are.

We call the first **temporal composability** and the second **spatial composability**. They
are independent: a system can undo perfectly and still act on a stale approval, or track
dependencies perfectly and still leave withdrawn artifacts on disk. AutoR did the second
badly and the first not at all.

### 1.1 What it cost, measured

Six of the graph's forward edges are guarded by counting files under `workspace/`. Before
the work described here, rolling back was a manifest edit — it set `status`, `approved`,
`dirty`, `stale` on the entries at and after the target and left the workspace untouched.
So the count those guards read still included everything the abandoned stages had written:

```
gate before rollback: True | 1 machine-readable design artifact(s) and a declared protocol
gate after  rollback: True | 1 machine-readable design artifact(s) and a declared protocol
files still on disk: ['design_matrix.csv']
```

A run that reached Stage 06, found the design wrong and went back to Stage 03 met an edge
out of Stage 03 that was **already open** — opened by the data Stages 04 and 05 had produced
under the design being abandoned. The gate whose purpose is to prove that *this* visit did
the work was answering for the visit the run had just repudiated.

The system was aware of the invariant it did not have. One guard's own comment reads:

> Every other guard here reads stage artifacts, which a rollback invalidates. This one
> reads a ledger, so the scoping has to be explicit.

The sentence was the stated reason for scoping one guard narrowly and leaving five broad.
It was false for all five. And the same class of defect had already been patched once, by
hand, at one path: a skipped stage's round declaration was "never consumed and never
unlinked", so the next visit closed its round from the previous visit's file, "inheriting a
conclusion drawn from results it did not produce." One instance, one patch, no mechanism.

---

## 2. The model

We model a run as a set of **stages** over a shared **run context**. A stage is a triple:

| Component | Meaning |
| --- | --- |
| **declared inputs** | the channels this stage reads, each naming the stage that produces it |
| **provision** | the channels and artifact families this stage may write |
| **effect** | what it does to the context when it runs, together with how to take that back |

Two derived notions drive everything below.

**A stage's contribution is attributable.** Every change to the shared workspace belongs to
exactly one stage. Without this, "withdraw Stage 04's contribution" has no referent, and
neither undo nor staleness can be defined. This is a precondition that most agent pipelines
leave implicit and therefore do not have.

**A stage's approval carries the state it was given against.** Not just *that* the stage was
approved, but *what it was reading* when the approval was given. The pair is what makes
"is this approval still good" a comparison rather than an inference from stage numbering.

---

## 3. Temporal composability: withdrawal that is exact

### 3.1 Inverses, not snapshots

A snapshot of the run is all-or-nothing. It can restore the state before Stage 04, and it
cannot withdraw Stage 04 while Stage 06 stands, because it holds no representation of one
stage's contribution separately from the run's. That distinction is the entire reason the
topology is a graph: a late finding invalidates *a* decision, not every decision that
happened to follow it in wall-clock order. A rollback that discards Stage 05's honest
measurement along with Stage 04's wrong design has thrown away the evidence that justified
the move.

So each write carries the operation that undoes it, and the run accumulates those per
stage. Withdrawing a range is applying its accumulators in reverse. Two properties follow
without further assumptions:

- **Reverse-order withdrawal is always sound.** Reverting in the reverse of the order
  applied hands each inverse the state its own application produced, whatever the writes
  were.
- **Composite inverses are free.** A stage author supplies the inverse of each atomic
  operation; the inverse of any sequence is the reverse composition. Teardown is *derived
  from* loading rather than written alongside it, which is what removes it from the set of
  things an author can forget.

### 3.2 Inverses are data, not closures

A run resumes in a new process — resumption is routine and a single stage may run for four
hours — so an inverse held as a Python closure is an inverse that does not survive the event
most likely to require it. Each inverse is a kind plus a JSON payload, appended to a
per-stage log as the stage runs. A crash mid-stage therefore leaves a partial accumulator
that still withdraws everything the stage had managed to do.

### 3.3 Undo has no preconditions

No inverse may fail: deleting a path that is already gone succeeds, restoring bytes creates
the parent directories it needs. An undo that can refuse turns a rollback into a state the
system has no rule for, and turns the recovery it was supposed to perform into a partial one
that nobody records. Where a natural undo *does* carry a precondition, we take the weaker
unconditional operation instead — for a registered child stage, the inverse *retires* it
rather than *removing* it, because removal has premises and retirement does not.

### 3.4 Two ways a write is attributed, and what each costs

A stage's work is performed by an agent process, so the framework has two routes to what it
wrote and uses both.

**Instrumented.** The write primitives are exposed to the agent as tools. A write that comes
through one is attributed to the running stage at the moment it happens, its previous bytes
go into the store *before* the new ones land, and — for a collection — the inverse removes
one entry by identifier.

**Observed.** Anything written directly is picked up by comparing content identities at the
stage boundary.

The second is weaker in three specific ways, which is the argument for the first:

| | Instrumented | Observed |
| --- | --- | --- |
| Grain | one entry in a collection | the whole file |
| When | at the write | at the next stage boundary |
| Large files | inverse regardless of size | delete-only above the limit |

Neither is a fallback for the other: the tools are additive, and a stage that ignores them
is exactly where it was before. That is what makes them safe to offer on every stage — a
server that fails to start degrades to the behaviour that was already there rather than
breaking the run. It also means the design does not depend on the agent's cooperation for
*correctness*, only for *exactness*.

**A tool, not a paragraph.** An instruction to route writes through a helper competes with
everything else in a long prompt; a tool in the model's actual tool list does not. It also
puts each write in the trace as a named call with structured arguments, which is what makes
"what did this stage record" answerable without parsing shell strings.

### 3.5 A row is a version chain, not a state

A file created at Stage 02 and rewritten at Stage 05 has two versions. Rolling back to
Stage 04 does **not** withdraw it — it rewinds it to what Stage 02 left. Withdrawal is for
files whose *creator* is inside the withdrawn range.

Collapsing the two cases into "delete" is the obvious implementation and it is wrong: it
takes Stage 02's honest work along with Stage 05's, which is precisely the loss the graph
exists to avoid. This is the single design decision that most distinguishes withdrawal in a
graph from rollback in a pipeline.

### 3.6 Version identity is a fresh name, never a value

Each version gets an identifier drawn from a counter that only increases and is never
reissued. Two stages can produce byte-identical output — a re-run after a rollback usually
does — and a consumer comparing values could not tell the re-run from the original. A
consumer that recorded `a000007` and now reads `a000019` knows its input changed without
comparing anything about the content.

### 3.7 Two grains of attribution, and a tool that offers the finer one

Observation gives attribution at the grain of a stage boundary. That is enough to withdraw a
stage, and it is weaker than instrumentation in two ways the ledger has to record: a change
is attributed to whichever boundary next observes it, so a write and its attribution are
separated by everything in between; and a version whose bytes were never held can be deleted
on the way back but not rewound to.

So the framework also *offers* the finer grain, as tools in the agent's own tool list rather
than as an instruction in its prompt. A write that comes through a tool is attributed at the
moment it happens, to the stage the run's manifest says is running, with the previous bytes
stored before the new ones land — the inverse is exact rather than reconstructed. Table
writes get their own tools, so one source or one hypothesis can be withdrawn without
rewriting the file that holds it.

Three properties make this safe to offer on every stage:

- **Nothing depends on it being used.** A stage that writes files directly is attributed at
  the next boundary exactly as before. The tool adds exactness where it is used and takes
  nothing away where it is not.
- **A failure degrades rather than breaks.** A server that will not start leaves the run in
  the prior behaviour, which is a working behaviour.
- **Refusals are answers, not errors.** A write that cannot be attributed comes back as a
  result the model can read — *"the manifest names no stage as running; write the file
  directly instead"* — rather than as a protocol error that ends the call with nothing it
  can act on.

The stage is resolved per call rather than captured at start-up: the tool server outlives
any one stage, and a captured value would attribute Stage 05's writes to Stage 01 for the
rest of the run.

---

## 4. Spatial composability: staleness as a comparison, not as arithmetic

### 4.1 The declared topology already existed; nothing read it for this

AutoR declares eighteen typed information channels. Each names the stage that produces it
and the set of stages that read it — a producer→consumer topology, written down rather than
approximated. It was used to assemble prompts, and for nothing else.

Meanwhile staleness was decided by arithmetic: a rollback to stage *N* marked every stage
numbered above *N*. That is the same approximation the channel layer was introduced to
remove one level up — "who needs this" approximated by "everyone from here on" — still
deciding whose approval survives a change.

It fails in a direction arithmetic cannot see. `research_rounds` is produced at Stage 06 and
read from Stage 02 onward, because Stages 03–06 repeat as a round: **information genuinely
flows backwards.** A change at Stage 06 leaves every earlier consumer's approval standing,
because 2 is not greater than 6.

### 4.2 Committed view and current view

At approval, a stage records a digest per declared input — its **committed view**. At any
later point the same digests can be taken again — the **current view**. The stage is stale
exactly when they differ, and the channels that differ are the reason, which the declared
topology turns into the name of the stage that caused it.

Three properties of the choice:

**The view is over what the stage reads, not over the files behind it.** A channel is a
rendered block, and that block is what the stage actually saw. Going through files instead
would require a second declaration of which file backs which channel, and two spellings of
one mapping is how they drift apart. It also gives the comparison the right grain: *two
states of the run are the same, for this stage, exactly when no channel it reads can tell
them apart.*

**Only channels with a producer are in the view.** Run configuration, project context and
the artifact index come from outside the stage graph. They are the environment the run sits
in, not a dependency on another stage's work, and a withdrawal does not touch them.

**One producer channel is excluded by name, with a measurement behind it.** The experiment
manifest is the framework's own inventory, and rendering it rewrites it with a fresh
timestamp — so its digest moves on research that did not. Left in the view it would mark
four stages stale at every boundary. A test renders every producer channel across a boundary
and requires it to be either stable or named in the exclusion list, so the list cannot grow
by assertion.

### 4.3 The rule, and why it is additive

> A stage is stale when its own output was withdrawn, **or** when its committed view no
> longer matches.

The first clause is the old stage-number rule and it is kept, because above the withdrawal
target the stage's own artifacts are gone and its approval is void whatever it reads.
Replacing it would leave stages approved with their outputs deleted. The second clause is
the new one, and it catches what numbering cannot: an approval below the target that was
given against something the withdrawal moved.

The mechanism is not only for withdrawals. Drift can be asked at any point, which makes the
same machinery answer a question the run could not previously ask: *has any approved stage's
input changed under it?*

---

## 5. Which withdrawals may be selective

Reverse-order withdrawal always works. Withdrawing *one* stage and leaving the later ones
standing is what the graph is actually for, and it needs a condition.

Two writes to different shared locations never interfere. Two writes to the same location
interfere unless the location is one where they cannot. So we classify each shared location:

| Kind | Example | Withdrawable out of order? |
| --- | --- | --- |
| **Commutative** — a collection whose entries are added and removed independently | the source set, the hypothesis set, the results directory | yes |
| **Ordered** — a sequence whose entries see each other | the manuscript draft, the run log | no |

Two registrations into a table, in either order, leave a table that answers every read
alike, and either can be withdrawn while the other stands. A paragraph written after another
reads differently without it, and neither order can be withdrawn without disturbing the
rest.

Ordered locations are not a defect to be engineered away. They are where the
order-sensitive part of the run lives, and naming them is what licenses reordering
everywhere else. The design guidance that falls out is concrete: **anything you want to be
selectively withdrawable belongs in a collection keyed by identifier, not in a narrative.**

A location in neither class is treated as ordered and *reported as unclassified*. The two
are different findings — the first is a fact about the research, the second is a fact about
the codebase — and reporting them alike hides the one that has a fix.

---

## 6. The system boundary: what an inverse cannot reach

An inverse works because the run owns the location: it can change it exclusively and it can
put the previous state back. Not everything a stage does is like that.

- An **acquisition** installs a record the run owns — a file it created, a handle it holds.
  It is withdrawable.
- An **emission** pushes data where other parties can already read it — a pull request, a
  spent quota, a row in a shared leaderboard. No inverse the run holds takes it back.

The boundary is drawn **per location, not per medium**. The same directory holds a
two-kilobyte results table the run can rewind and a four-gigabyte checkpoint it cannot, and
the honest record says so per file rather than per directory.

There are two ways to recover from an emission, and we implement the first: **withhold it**
until the state that produced it is settled. A stage registers the intent; the intent is
released when the stage is approved and dropped when the stage is withdrawn. The second —
emit now, compensate later — is available to a caller that needs it and is not free: a
compensating action restores the world only up to an equivalence the application supplies,
coarser than the one the rest of the system reasons in, and nothing in the framework can
check it.

---

## 7. The asymmetry: state is reverted, evidence is retained

Everything in §3–§6 pushes toward one limit: a run whose dynamic history leaves no trace,
that quiesces wherever a run which had gone straight there would have. For a plugin host
that is the goal. For a research run it is half of one, and the wrong half to stop at.

A run that withdraws Stage 04's design and then re-enters Stage 04 with no record of what
was withdrawn has bought itself the right to make the same mistake again — cheaply, and as
many times as its visit budget allows. Recovery so complete that it erases the reason for
the recovery makes a withdrawal indistinguishable from never having tried, and a system
that cannot tell those apart will try the same thing again.

So the run context divides in two, and the division is the design rather than an
implementation detail:

| | Behaviour under withdrawal | What it holds |
| --- | --- | --- |
| **Workspace** | reverted | the state the run stands behind |
| **Ledger** | monotone — only grows | what was tried, what it cost, why it was taken back |

The second is what makes the first safe to use. And it has to *reach* the stage that could
repeat the decision, or it is an archive: the record is delivered as a typed information
channel to every stage a backward edge can land on. That readership is read off the graph's
own backward edges rather than listed by hand, so a new backward edge brings its target into
the readership with it. A stage re-entered after a withdrawal is told what was withdrawn
from it and why, in the same prompt that asks it to try again.

The ledger sits outside the workspace, which puts it beyond every recovery path *by
construction* rather than by an exclusion somebody has to maintain. A withdrawal that could
edit it could withdraw the record of itself.

**What this buys that a purely revertible system does not have.** The convergence argument
for a graph walk is that dead ends leave no residue in the state. The learning argument is
that they leave residue somewhere else. A system with only the first wanders efficiently; a
system with only the second accumulates junk it cannot clean up. The split is what lets a
run explore a backward edge without either consequence.

---

## 8. The ratchet: a backward move that made the run worse is itself taken back

Everything in §3–§7 is about **state**, and none of it says the run gets better. A withdrawal
can be exact, an approval can be retired for the right reason, and the walk can still spend
its budget going in a circle. Keeping the two apart matters, because a system that withdraws
perfectly and wanders is easy to mistake for one that is working.

The graph exists so that a late finding can send the run back. Nothing checked whether going
back *helped*. A run could leave Stage 06 for Stage 03, rebuild the design, walk forward and
arrive at a Stage 06 scoring lower than the one it abandoned — and that outcome was recorded,
promoted and built on exactly like an improvement, because "later" was the only ordering the
walk had.

### 8.1 The excursion

An **excursion** is the interval between leaving a stage by a backward edge and getting back
to it. It opens when the walk leaves stage *S* for something earlier; it closes the next time
the walk leaves a stage numbered *S* or above — the point at which the run has recovered the
ground it gave up and the two states are comparable.

A backward move taken while an excursion is already open **extends the outer one** rather
than nesting inside it. The outer baseline is the state before the run started going
backwards at all, and that is the comparison worth keeping: judging an inner excursion
against a state which is itself under review would let two bad moves ratify each other.

### 8.2 What it is compared on, and why there is no noise band

The excursion was taken to improve *S*'s situation, so *S*'s own score is the measure — the
same stage, before and after. Both numbers are already recorded per visit by the walk, so
nothing is re-scored.

The score is mechanical. It reads the run off disk and never calls a model, so the same
workspace scores the same number twice, and **any drop is a real drop**. The margin is
therefore zero. This is a property of the measure, not an omission: a judged score would
need a margin wider than its own sampling dispersion before two draws could be compared at
all. The margin exists as a named constant precisely so that swapping in a judged score is a
change to a value with an argument attached, rather than a silent reintroduction of the
problem.

This is also why the ratchet belongs at the walk level rather than only inside a stage. A
mechanical score is cheap enough to take at every stage boundary, which is what makes an
excursion judgeable at all.

### 8.3 Where the run goes back to

A **snapshot** of the version pointers in the provenance ledger, taken when the excursion
opened. Restoring it uses the same applier a stage-range withdrawal uses; only the choice of
target version differs — by stage number there, by recorded identifier here. The bytes are
already in the content-addressed store, so a snapshot costs a dictionary rather than a copy
of the workspace, which is what makes it affordable at every departure.

A file whose version has not moved is not in the restore plan. A file created since the
snapshot is deleted. A file that has moved is rewound to the version the snapshot names — and
where an intervening withdrawal has trimmed that version out of the chain, the honest answer
is to delete rather than to leave a later version in place and call it restored.

### 8.4 One rewind per stage

A rewind puts the run back exactly where it was before the backward move — which is also the
state that made the backward move look attractive. Uncapped, the ratchet becomes the loop it
exists to detect.

So a stage may be overruled once. A second excursion from the same stage that also comes back
worse is recorded, and allowed to stand. The run has been told, in the withdrawal ledger and
in the prompt that reaches the stage; a mechanism that keeps overruling the same decision has
stopped being a ratchet and become a wall.

### 8.5 Five verdicts

| Verdict | Meaning |
| --- | --- |
| `improved` | came back higher — what the backward edge is for |
| `held` | came back equal; left standing |
| `rewound` | came back lower; the workspace is put back to the snapshot |
| `worse_but_capped` | came back lower, but this stage has been overruled already |
| `unjudgeable` | one end was never scored, so the excursion is recorded rather than judged |

The distribution over these verdicts is the number a graph-versus-pipeline comparison
actually needs. Not *how many backward edges were taken* — a pipeline takes none and that
says nothing — but **how many of them ended better than they started**.

---

## 9. What is guaranteed, and what is not

Sections 3 to 7 are about **state**; §8 is the only one that speaks to whether the run gets
better. Keeping them apart matters: a system can withdraw perfectly and still wander.

What the mechanisms above do support:

1. **Withdrawal exactness.** Applying a stage's accumulator yields the state the same
   sequence would have produced had the stage never run — up to the equivalence in §4.2, and
   up to the boundary in §6.
2. **No torn approvals.** A stage's approval either stands against the inputs it was given,
   or is marked stale naming the input that moved.
3. **Fail-open on absence.** Anything the ledger has no record of still counts. A run
   started before the ledger existed, a resumed run whose ledger did not survive, a file
   written outside any stage's window — all of these behave as they did before. A
   precondition no real run can meet is not a strict gate; this repository has shipped that
   mistake once and the rule is a response to it.

---

## 10. Not yet implemented

Listed here rather than omitted, because the difference between a design and a system is
which parts are running.

| Piece | Status |
| --- | --- |
| Attribution, version chains, withdrawal plan | implemented |
| Per-stage accumulator, reverse-order withdrawal, blob store | implemented |
| Entry-grained inverses, so one entry in a collection is withdrawable alone | implemented |
| Write primitives in the stage agent's tool list | implemented |
| Commutativity classification and the independence check, reported at every withdrawal | implemented |
| Committed view, drift, topology-derived staleness | implemented |
| Emission withholding | implemented |
| Withdrawal ledger, delivered to every backward-edge target | implemented |
| Snapshot and restore of version pointers | implemented |
| Excursions, and the walk-level ratchet that rewinds one that lost | implemented |
| Selective withdrawal, taken on redo, with a stated fallback | implemented |
| **Intra-stage checkpoints** | pending |

### On selective withdrawal

The action has a caller, and finding it took correcting a wrong conclusion. Reverse-order
withdrawal is the right answer for a *range* — the stages after a withdrawn one were reading
what it produced, so keeping them would leave them standing on a state that no longer
exists — and from that it looked as though selective withdrawal had no place in this
topology at all.

It does: **`--redo-stage`**. Re-running one stage is exactly the single-stage case, and the
redo path had the same defect a rollback used to have, at a finer grain — the previous
attempt's artifacts stayed on disk, counted by the same guards, for the new attempt to write
over whichever of them it happened to touch.

Two conditions are checked, separately, because they cover different writes:

- no later stage wrote a **key** this stage wrote — over the accumulators, the independence
  test of §5;
- no later stage rewrote a **file** this stage wrote — over the observed version chains.

Where either fails the withdrawal falls back to reverse-order and says which files or keys
were contested. That fallback is the honest move rather than a weaker success: leaving a
contested file alone keeps this stage's work standing, and rewinding it discards the later
stage's, and neither of those is "withdrew this stage".

This is the mechanism paying for itself. A design that turned out wrong need not discard the
measurement that revealed it — but only when nothing since has touched the same ground, and
the system can now tell the difference instead of assuming one answer.
