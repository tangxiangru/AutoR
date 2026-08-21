---
name: information-a-training-free-method-owes-a-second-backbone
description: Use when the method under study is training-free, plug-in, prompt-level or described as model-agnostic: at literature survey to enumerate which host models the released code actually supports and where that support came from, at study design to price the second host, at experimentation to run it. Covers finding hosts in dispatch tables and third-party contributions, choosing the cheapest one, and the three readings a two-host table owes.
benchmarks: researchclawbench
stages: 01_literature_survey, 03_study_design, 05_experimentation
---

# A training-free method owes a second backbone

"Training-free", "plug-and-play", "model-agnostic", "requires no fine-tuning",
"works with any MLLM/LLM/encoder", "wraps the frozen model" — these are one
claim, and the claim is about a set of host models, not about one of them. A
study that measures one host has measured that host. It cannot separate "the
method works" from "this host was weak on this benchmark", which is the first
question a reader asks of a wrapper.

This is an axis, not a nicety. If the source's tables carry a backbone column or
a second model block, that structure *is* the paper's generality argument, and a
study confined to one cell of it has not attempted the headline claim.
`information-fill-the-whole-results-grid` lists backbones as one grid dimension
among several; this skill is the part it leaves out — how to find out which
hosts are reachable, which one to pick, and what to report about the pair.

## Enumerate the hosts from the code, not from the paper

At literature survey, when you fetch the reference implementation, enumerate its
host models before you enumerate anything else. Do this from the repository
listing, not from the paper's method section:

- the `--model` / `--backbone` argparse `choices`, and the name-to-function
  dispatch dict it feeds;
- per-model implementation files and notebooks — one file per supported host is
  the usual layout, and the file names are the host names;
- config enums, YAML keys, registry decorators, entries in a run-all script;
- **the repository's open and merged pull requests, forks, branches, issues and
  the README's news or changelog section.** Support for host models released
  after the paper lands as third-party contributions and appears nowhere in the
  paper. This is frequently the only place a cheap, modern host exists, and the
  contribution route is itself a reportable fact about the method's modularity.

Write it down as a literature-survey deliverable: one line per supported host
with its parameter count, the file that implements it, the exact invocation, and
whether it came from the authors or a contributor (with the PR or fork it came
in through). A host that exists in the tree and is absent from this list is a
host you will never budget.

## Pick the smallest supported host, not the most impressive

The deliverable is the second row. Cost scales with the host, so take the
smallest one the code supports, run it on the cheapest slice in the study, at a
reduced and labelled N. A two-host table at small N answers a question a
one-host table at large N cannot. Price it as a ledger row like any other and
put it above every condition you invented.

## What to produce

One table, the same conditions on both hosts, same slice, same N:

| host | params | source of support | baseline | variant 1 | variant 2 | ... | delta |

Then three readings, in the text, each of which is a measurement you make and
not a conclusion you assume:

1. **Both baselines, printed.** State each host's unmodified accuracy on the
   shared slice. Then say what the difference between them implies for this
   study: what room each host leaves the method to work in, and whether deltas
   measured on top of two different baselines are comparable at all. Write that
   reading out; a reader will not derive it from your table.
2. **Does the variant ordering survive the host swap?** Rank the variants on
   each host and compare the rankings in both directions. Whether the ordering
   is preserved is the portability result, and it must be stated as a sentence,
   not left implicit in two tables.
3. **A coincidence is a result; go find its cause in the code.** If two or more
   variants return the same score on a host, do not write it off as noise or as
   a small-N artifact. Check whether their intermediate objects also coincide —
   the same selected region, the same retrieved set, the same routing, the same
   token subset — and then read that host's adapter in the released source
   and report what its code path actually does with each variant. Report the
   mechanism you found in the code, not a plausible story about it. The numbers
   alone cannot settle it; the adapter can.

## Checklist

- [ ] Supported-host list extracted from the code, run scripts, PRs, forks and
      README news at literature survey, with parameter counts and provenance.
- [ ] Second host chosen as the smallest supported one, priced per item on the
      cheapest slice, and entered in the ledger above any condition I invented.
- [ ] The same variant set run on both hosts, same slice, same N, labelled.
- [ ] Both baselines printed, with an explicit sentence on what their gap means
      for the deltas measured on top of them.
- [ ] Variant ordering compared across hosts, stated in words.
- [ ] Any exact tie between variants chased first into the intermediate objects
      and then into that host's adapter source, with the code-level finding
      written down.
- [ ] Provenance of the second host's support named in the report — authors or
      contributor, and through what route.
- [ ] If the second host is genuinely unreachable, the reason is a measured
      per-item cost against a clock, not a sentence in Limitations.

## Why this is here

Inference-time and wrapper methods are graded on portability, and a run that
measures one host deeply reads as never having attempted the generality claim —
usually the paper's headline claim. The second host is also the cheapest large
result available: a smaller model, the light slice, a small labelled N, and a
port that already exists in the released code, sometimes only on a branch or in
a merged contribution.
