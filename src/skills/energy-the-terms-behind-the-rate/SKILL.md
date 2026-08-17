---
name: energy-the-terms-behind-the-rate
description: Use at analysis and writing whenever a headline number is a share, rate or fraction, and especially when your share lands close to a published one. Covers choosing the denominator's population by where the mechanism acts rather than by the model's outer edge, publishing the absolute terms of the balance beside every share, and reconciling with a published study term by term instead of on the ratio.
stages: 06_analysis, 07_writing
---

# A share is not a result until its terms and its population are published

## When this applies

Analysis and writing, from the moment a headline number is a share, rate, fraction
or percentage of something -- and especially when your share lands close to a
published one.

Two shipped skills touch this. `energy-counterfactual-pair-and-hierarchy-closure`
requires every rate to be stated with its numerator, its denominator and the
population the denominator covers, and requires components to sum.
`the-unit-of-analysis` requires per-unit reporting instead of one pooled number.
This file is the part neither states: the population is chosen by *where the
mechanism acts*, which is usually neither the whole modelled system nor a grouping
column the data hands you; and the comparison with a published study is done term
by term, because a share can agree while both of its terms are wrong.

## What goes wrong

### The denominator defaults to the widest population available

The solved model hands you totals over everything, so the share gets computed over
everything. The mechanism acts on a subset -- the units behind the binding element,
the assets downstream of the intervention, the exposed stratum -- and members
outside that subset dilute numerator and denominator unequally. Your number then
differs from anyone else's for a reason that is not physical, and the difference
reads as a modelling error rather than a denominator choice.

### The share agrees and the terms do not

Two studies can report the same percentage from totals that differ by a fifth. That
is not a reproduction, it is a coincidence you have not ruled out; and it is how a
construction error hides, because if numerator and denominator are inflated by the
same factor the ratio is immune to it and so is every check you run on the ratio.
The reverse case is as common: the terms match and the share does not, which
localises the defect in the definition of the share.

### Only the share reaches the prose

The per-unit arrays are on disk, the totals are one sum away, and the body text
carries percentages. A quantity that exists only in an output file, or only inside a
figure annotation, has not been reported: a reader cannot rebuild your case from it
and cannot line your terms up against the source's. Every share in the body gets its
absolute terms, in the input's or the source's units, beside it.

## What to produce

### 1. Define the affected population before you sum anything

Write it as a list of ids taken from the input files -- which units, which nodes,
which steps -- and persist that list beside the results. Where membership is a
judgement call, compute both readings rather than picking one silently.

### 2. A term table: one block per population, one per arm

Rows are the terms of the conservation identity your share is built on: what was
available, what was realised, each loss or rejection channel, and the residual.
Columns are your value in physical units, the source's published value where it has
one, and the difference. The rows must sum to the total; a residual you cannot name
is a channel you are not tracking, so add the row rather than rounding it away.
State the share under each block with its denominator named in words, so the reading
over the affected population and the reading over the whole system are both on the
page and cannot be confused for each other.

### 3. Reconcile term by term, then the share

- Both terms off by roughly the same factor: a population or scaling mismatch. Name
  the population you summed and the one you believe the source summed.
- One term off: a different mechanism, or a loss channel you are not modelling.
- Terms agree, share disagrees: the definition of the share differs -- check what is
  excluded from the denominator.
- Share agrees, terms disagree: say so in the sentence that reports the agreement,
  and do not present it as confirmation until the terms are reconciled.

### 4. Keep the source's name for the population

Where the shipped data contradicts the brief's or the source's name for a region,
era, scenario or entity, keep the name, add one sentence stating the contradiction,
and say what you refuse to do because of it. Substituting a neutral name of your own
removes the only key a reader has for aligning your rows with the source's, and buys
nothing a footnote does not. See `use-the-sources-own-names`.

## Checklist

- [ ] The affected population is defined by input-file ids and written down before
      the sums are taken.
- [ ] Every headline share appears once per population, with its denominator named
      in words.
- [ ] The term table is in the body, in physical units, and its rows sum.
- [ ] Every share in the body has its absolute terms adjacent; nothing quantitative
      lives only in a figure annotation or an output file.
- [ ] Each arm you solved has a block with the same rows.
- [ ] Every term the source publishes has a comparison line of its own, not only the
      headline share.
- [ ] Populations carry the brief's and the source's names, with contradictions
      footnoted rather than renamed.
