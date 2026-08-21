---
name: material-trajectory-health-is-a-panel
description: Use at experimentation when a dynamics or sampling run is launched (MD, Monte Carlo, annealing, any iterative sampler), and again at analysis and writing when its result is drawn. Covers the health channels to append to disk while the loop is running, the numbers to state against thresholds you declared, and the trace panel that makes the run checkable — without changing the configuration the protocol specified.
benchmarks: researchclawbench
stages: 05_experimentation, 06_analysis, 07_writing
---

# The trajectory's health is a panel, not a boolean

A result computed from a dynamics or sampling run carries a second claim
underneath the first: that the run was a valid one. The distribution, average or
landmark you plot does not carry it — a curve computed from a run that fell
apart still looks like a curve — and neither does a flag in a results file.

The standard-figure lists in `the-canonical-figure` and
`material-as-specified-run-and-stage-diagnostics` are shaped for fitting
pipelines: objective against epoch, parity against reference, best-so-far
against evaluation count. For a trajectory this is the entry those lists are
missing, and it is the one nobody draws.

## This is not "run it longer"

Run the length, step size, step count, temperature, cell and ensemble the
protocol specifies. That run is the foreground result, and its numbers are the
ones reported (`material-as-specified-run-and-stage-diagnostics`). A longer,
better-equilibrated or larger run is an addition placed beside it, with its own
length stated, and it does not silently replace the as-specified number — a
reader comparing you against the specified protocol is comparing against the
specified protocol.

What is usually missing is not compute. It is any evidence that the specified
run did what it was supposed to do, and that evidence costs nothing next to the
force or energy evaluations you already paid for.

## Log it while it exists

Inside the loop, every few steps, append to a file on disk — not to a list in
memory that goes out of scope when the function returns:

- step index and elapsed simulated time in physical units;
- every controlled variable instantaneously: temperature, pressure, chemical
  potential, acceptance rate, whatever the ensemble or sampler holds;
- total and potential energy, per particle where the system size varies;
- one or two sanity quantities whose violation means the run stopped being
  physical: closest approach between entities that should not overlap, longest
  bond within a pair that started bonded, count of entities that changed
  identity or left the box;
- the index of the first frame entering the average.

## Turn the log into numbers with declared thresholds

Every one of these is a value against a bound. Declare the bound before the run;
a number with no bound beside it is not a check.

- steps completed against steps requested, and the simulated duration in
  physical units;
- mean and standard deviation of each controlled variable over the averaged
  window, next to its setpoint. Report the gap whatever it is. A large gap is a
  finding to state beside the as-specified result, not a reason to quietly swap
  in a different run;
- energy behaviour over the run: fluctuation amplitude, and drift measured as
  the difference between block means rather than eyeballed;
- closest approach against the floor you set; worst bond length against the
  ceiling you set; number of dissociation or identity-change events;
- frames entering the average and the length discarded;
- the seed-to-seed spread of the reported landmark, from at least two
  independent starts, quoted as its error bar.

## Ship the panel and say the sentence

The deliverable figure gets a companion panel — in the same figure, or the
figure immediately beside it: controlled variable against time, energy against
time, sanity quantity against time, with the discard boundary drawn as a
vertical line and the setpoint as a horizontal one. Its caption states the
simulated duration in physical units, the frame count, the mean controlled
variable against its setpoint, and the two threshold comparisons as numbers.

Then one sentence in the results prose that introduces the deliverable figure,
in plain words: whether the run was stable, for how long in physical units, at
what conditions, and against which thresholds. It goes there, next to the
result, not in a later section and not only in a caption. A stability claim that
arrives tens of thousands of characters after the figure is read as absent, and
`stable: true` in a JSON artifact discharges nothing — nobody reading the report
can see it.

If the run genuinely was not sound, that sentence says so with the same numbers.
An honest failure in physical units is a result; an unqualified curve is not.

## Checklist

- [ ] The as-specified configuration was run and is the foreground result.
- [ ] Health channels were appended to disk inside the loop, not collected at
      the end.
- [ ] Simulated duration in physical units and frame count are stated in the
      caption.
- [ ] Each controlled variable's mean over the averaged window is printed next
      to its setpoint.
- [ ] Each sanity quantity is printed next to the bound declared before the run.
- [ ] At least two independent seeds; the spread is the quoted error bar.
- [ ] A trace panel exists in the shipped figure set, discard boundary and
      setpoint drawn.
- [ ] The words describing stability appear in the results prose beside the
      deliverable figure, with numbers, not only in an artifact.
