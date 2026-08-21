---
name: information-port-every-branch-of-the-released-dispatch
description: Use at implementation, when you are about to re-implement a released method by hand because its pinned environment will not install here, and at literature survey when you first read its entry point. Covers why a hand port silently fixes the arm set to the one path you planned to run, how to shim the release's own dispatch instead, and the smoke pass that turns "we could not afford that variant" into a measured per-branch cost.
benchmarks: researchclawbench
applies_when: training-free framework|task-guided cropping
stages: 01_literature_survey, 04_implementation, 05_experimentation
---

# The port, not the budget, is where the results grid gets truncated

A released implementation is wider than the paper's tables. One function per
algorithm variant behind an `if method ==` chain; one loader per backbone behind a
`--model` switch; one `*_methods.py` per supported host; a name-to-checkpoint
dict; a `run_all.sh` that sweeps the lot. Read the entry point and you are holding
the whole experiment matrix, in code, before you have written a line.

Then the environment fails. The release pins a library version that no longer
exists, or one so old that the model class it imports had not been added yet. So
you write your own port — carefully, faithfully, checked against the authors'
stored notebook outputs — of the path you are planning to run.

**That file is now your arm set, and nothing downstream can widen it.** The other
branches of the dispatch do not appear as decisions you declined; they do not
appear at all. Hours of study-design arithmetic later one of them comes up as a
budget question, gets priced against the wall clock, and is written down as
dropped for cost. The honest sentence in the report — *"the gradient variants were
dropped, each needs an extra backward pass per tile"* — describes an affordability
problem that was never the binding constraint. The code to run them was never
written.

## Port the dispatch, not the path

1. **Vendor the release's method modules into `code/` unmodified** and record the
   commit or blob hashes. Your port is a patch on top of those files, not a
   replacement for them.
2. **Move the environment to the code with the smallest diff you can.** The fixes a
   modern library forces are per-API, not per-branch: arguments that became
   keyword-only, an attention implementation that must now be requested
   explicitly, a dtype, a guard on an integer that evaluates to zero. Five such
   fixes applied to the release's own file give you every branch in it. The same
   five fixes applied to a fresh file you wrote give you one.
3. **Keep every diff in one patch file, each hunk commented with what forced it.**
   That file is also your methods section: it is the exact list of ways your run
   differs from the release, and it is short enough to be read.
4. **Never delete a branch you do not plan to run.** An unused branch costs nothing
   to carry and is one string away from being a table row. Deleting it converts a
   flag into a code change, and a code change is what does not happen at hour ten.
5. **If you genuinely must reimplement from scratch, port the dispatch table
   first** — every branch name the release exposes, each raising
   `NotImplementedError` until it is filled. Then the arm set is visible in your
   own code as holes, and every stage after implementation can see them.

## The smoke pass that prices the branches

Before the design freezes, run *one item through every branch*:

    for model in <every --model choice>:
        for method in <every --method choice>:
            run one item; record seconds; record whether it raised

Minutes of compute. It produces three things nothing else will: proof that each
branch executes here, a measured per-item cost for each one **in the cell you would
report it in**, and an explicit list of the branches that fail — which is a
reproduction finding in itself. A branch that raises in the release's own code, on
the release's own inputs, is worth a paragraph.

Do this once per dataset. A branch that needs an extra pass through the model costs
one extra pass on a single-image input and one per tile on a tiled high-resolution
input; a cost measured on the tiled path is not a price for the flat one, and used
as one it deletes the branch from both.

## The check before you leave implementation

Take the release's argument choices — the `--model` values, the `--method` values,
the entries of its name-to-checkpoint dict — and grep your own port for each. Every
value the release accepts should either be reachable through your entry point or be
a documented `NotImplementedError` with the reason. Your port's public function
should take the release's own spellings (`method="grad_att"`), so that adding a row
to the results table is a string in a loop.

## Why this is here

A run reproducing a training-free cropping method fetched the release, printed its
entry point into its own notes — a `--model` switch over three backbones, a
`--method` switch over eight algorithm variants — and then wrote a 12 KB hand port
holding the relative-attention path and nothing else: the only two occurrences of the
string `grad` in it are `torch.no_grad()`. Two published variants of that same switch
carry a checklist criterion weighted 0.4, and the report explains their absence as
compute cost, quoting a per-item price measured on the expensive tiled path for a
dataset whose map is a single flat pass. The bare-agent control vendored the release's
`core.py` instead, ran all seven arms the source publishes a value for, and scored 48
against this run's 35.3 on that criterion. A working relative-attention port existed at
hour one of a twelve-hour run; the affordability argument that declined the gradient
rows was written at hour five. Only the first of those decided anything.
