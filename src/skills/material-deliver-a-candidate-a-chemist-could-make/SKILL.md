---
name: material-deliver-a-candidate-a-chemist-could-make
description: Use when a design, screening or generation task ends in candidates a human would have to synthesise or fabricate, and the brief asks for an experimental validation you cannot run. Covers the component-pinned search that makes a candidate orderable, drawing the delivered candidate as chemistry, and putting every existing measurement on the same property axis as your prediction.
benchmarks: researchclawbench
stages: 05_experimentation, 06_analysis, 07_writing
---

# Deliver a material, not a coordinate

The design half finishes and the deliverable is reported as a count and a gap:
so many new candidates, median such-and-such from target, none of them in the
supplied set. No structure is drawn, no component is named, nothing could be
ordered. And the one place in the whole problem where a real number from a real
instrument exists — the candidate someone has already made and measured,
reported in the source study — appears as a quoted sentence, or as one bar
inside an aggregate error budget, or not at all.

These briefs usually end with a clause you cannot execute: synthesise, measure,
characterise, validate the selected candidates experimentally. You will not have
a lab. That is not why that stage scores zero. It scores zero when nothing in
the report *looks like* the step: no candidate rendered as chemistry, no
comparison against any measurement, no engagement with the behaviours that
define the material class. "Not performed — no wet lab exists here" is accurate,
complete and worth nothing on its own. Produce the largest part of the stage
that does not need the instrument, then say which part needed it.

`a-value-you-did-not-measure-still-has-a-source` is the general form of that
argument — cite the field's value, stand your own quantity beside it. What
follows is the materials-side procedure it does not contain: how to end up with
a candidate that could be ordered, and what the comparison has to look like as a
picture.

## Analysis: five things to produce, and most of them are panels

Material criteria are read off images. A markdown table in the report body is
not where they are read, so everything below that is described as a table is a
table **and** a rendered panel.

**1. A constrained design run beside the free one.** Pin one component to
something that can actually be bought and search only the rest of the structure.
Choose the pinned component the way a chemist would: the workhorse of this
material class, named as such in a supplier catalogue, in the field's review
literature, or from your own knowledge of the class. Do not pick it by frequency
in the supplied pool — a combinatorially enumerated pool has no workhorse, its
modal component may occur a handful of times across thousands of rows, and
frequency then selects an arbitrary molecule. The pinned component is allowed to
be absent from the supplied data entirely; your scorer consumes a structure, not
a row index. Report both searches. The constraint costs you something in the
target property, and that cost is a result — it is the price of synthesisability,
stated as a number.

**2. Each delivered candidate as chemistry, drawn.** For the best candidate at
each target: component names, SMILES or formulae, molecular weight,
functional-group counts, and a synthetic-accessibility or commercial-availability
score per component shown against the distribution of that score over the pool.
Render it as a structure grid — the drawn molecules, annotated with those
numbers — and mark which components already occur in the supplied data and which
are new.

**3. The measurement axis.** Collect every value anyone has actually measured
for this material or its nearest published relative — the source study's own
experimental section, the related work, a handbook — and plot them on the **same
property axis** as your predicted value for that same or nearest candidate, with
your interval. One panel, physical units, every point labelled with the
technique that produced it and attributed to whoever measured it. Quoting these
numbers in prose does not do it, and neither does folding them into a log-scale
error budget with everything else: the comparison has to be legible as a
picture, at the scale of the property.

**4. The class-defining behaviours, one row each, drawn as a panel.** A material
class is named for behaviour beyond the single property you optimised — cycle
life for an electrode, corrosion resistance for an alloy, turnover and
selectivity for a catalyst, creep and fatigue for a structural composite.
Derive your own class's list from the class name and from the behaviours the
source study treats as definitional when it characterises the material;
typically three to six. Fill each row with exactly one of: a computed structural
proxy you can evaluate on the candidate (the bond or motif that enables the
behaviour and its chemistry, network connectivity, crosslink density, a
descriptor), a literature value for the closest measured system with its
citation, or an explicit "no route in this environment" naming the instrument
required. Draw the filled table as an annotated panel, keyed by which of the
three each cell is. Rows, never a paragraph, and never a silent omission — the
omission is what reads as the stage having been skipped.

**5. The handover protocol.** Four to eight lines: components and stoichiometry,
processing or cure conditions, the measurement that would confirm the design and
the value it should return with your interval, and the observation that would
falsify it. This converts the stage from a disclaimer into a deliverable and
costs one paragraph.

## Writing

The experimental section is a section with figures in it, placed where the
source's experimental results would be — not a two-sentence note at the end of
the results. Its lead panel is item 3. If part of it genuinely could not be
done, that sentence goes **after** the panels, naming the instrument, not
instead of them. A section heading that announces the stage was not performed,
sitting above no figures, is the cheapest way there is to score zero on work you
could largely have delivered.

## Checklist

- [ ] Component-pinned design run exists beside the free one, the pinned
      component justified by availability rather than pool frequency, and the
      cost of the constraint measured in the target property.
- [ ] Best candidate per target reported with names, SMILES/formulae and drawn
      structures, rendered as a panel.
- [ ] Availability or synthesisability score per component, against the pool's
      own distribution.
- [ ] One panel: every existing measured value for this material or its nearest
      relative, on the same property axis as your prediction and its interval,
      each point labelled with its technique and attributed.
- [ ] Class-behaviour panel: one row each, computed proxy / cited value / named
      missing instrument.
- [ ] A synthesis-and-characterisation protocol a human could follow.
- [ ] "Not performed" appears, if it must, after all of the above.
