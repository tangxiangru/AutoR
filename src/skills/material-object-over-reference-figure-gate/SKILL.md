---
name: material-object-over-reference-figure-gate
description: Use when figures are being written or are about to be declared finished and no panel yet draws the run's own generated or predicted objects over their reference population in physical coordinates - the panels so far are rate bars, threshold curves, tables as graphics, or titles carrying hypothesis ids and verdict words. Covers an assertion gate over the plotting code that fails the figure stage until every named deliverable has an object-over-reference panel with units on both axes.
stages: 04_implementation, 06_analysis
---

# Gate every deliverable on an object-over-reference panel, or fail the figure stage

The failure: the figure plan is derived from the run's own hypothesis list, so
each slot is "the claim this settles". What gets drawn is bar charts of rates,
threshold curves, tables rendered as graphics, and titles carrying hypothesis
identifiers, verdict words and a footer of protocol prose. Every panel is a
picture of the run's bookkeeping. A reader looking for "did the generator produce
reasonable objects?" finds a bar chart of pass rates and concludes the objects
were never plotted - which is exactly what a metric-only panel means.

The list of panels this kind of run owes is not new.
`material-as-specified-run-and-stage-diagnostics` names the per-stage defaults
and `the-canonical-figure` names the field-standard ones; read either for the
list, and do not read this skill for it. This one exists because those lists have
been installed, unread, on runs that then shipped none of the panels. Prose does
not fire. An assertion does.

## The rule the gate enforces

For every named deliverable, at least one panel puts **both populations in one
axes, in physical coordinates**: the objects your method produced and the
reference objects they are supposed to resemble. Generated samples over the
supplied support points. Predictions against truth on the identity line. Your
trace and the baseline trace on one axes. The comparison lives inside the
picture, with its scalar annotated in the panel - an overlap, a divergence or a
coverage fraction that exists only as a bar height or a sentence is checkable
against nothing.

Aggregate-rate panels are legitimate as the *second* panel of a slot. They are
never the whole slot.

## The gate

Write it before the plotting code, and call it in the same function as every
`savefig`:

```python
# code/figure_gate.py
import re

BANNED = re.compile(
    r"\b[HTC]\d+\b|\barm\s*\d+\b|SUPPORTED|REFUTED|INCONCLUSIVE|"
    r"pre-?registrat|verdict|holm|bonferroni|westfall", re.I)
REF = re.compile(r"refer|observ|supplied|measured|true|origin|target|baseline", re.I)

def gate(ax, unit_tokens, slot, needs_reference=True):
    """Call immediately before savefig. unit_tokens come from the decode table."""
    series = list(ax.get_lines()) + list(ax.collections) + list(ax.patches)
    labels = [str(s.get_label()) for s in series]
    named = [l for l in labels if not l.startswith("_")]
    if needs_reference:
        ref = [l for l in named if REF.search(l)]
        mine = [l for l in named if l not in ref]
        assert ref and mine, f"{slot}: no reference+model pair in one axes; labels={named}"
    for which, text in (("x", ax.get_xlabel()), ("y", ax.get_ylabel())):
        assert any(u in text for u in unit_tokens), \
            f"{slot}: {which}-label carries no unit from the decode table: {text!r}"
    fig = ax.get_figure()
    strings = [ax.get_title(), ax.get_xlabel(), ax.get_ylabel()] + named \
              + [t.get_text() for t in fig.texts]
    bad = [s for s in strings if BANNED.search(s)]
    assert not bad, f"{slot}: run-internal vocabulary baked into the raster: {bad}"
```

Artists whose label sits on a container rather than on the artist - grouped bars
are the common case - read as unlabelled and fail the reference assertion. That
is the intended default: if a grouped-bar panel genuinely is your object
comparison, label the patches explicitly and say so.

Then once, before the figure stage is allowed to report success: iterate the
deliverable list extracted from the task statement and assert that each entry has
at least one panel that passed with `needs_reference=True`. A deliverable with
zero is a stage failure, not a note in a log.

If the plots come from scripts that do not keep the `Figure` object, gate the
manifest instead: every figure writes a JSON row with `slot`, `series_labels`,
`xlabel`, `ylabel`, `title`, `annotations`, and the same three assertions run over
the rows. The gate is worth having in the weaker form; it is not worth skipping
because the stronger form is awkward.

## What the gate cannot check, and you have to

- that the series labelled reference *is* the supplied population, drawn in its
  own coordinates - a histogram of reference values in one panel and generated
  values in another is two pictures, not a comparison;
- that the unit token in the axis label is the unit you assigned for that array,
  rather than one carried over from a template;
- that the landmark scalar is annotated next to what it describes, inside the
  axes, rather than in the caption.

## Keep the run's vocabulary out of the raster

Text baked into a PNG survives every later edit of the report, and none of the
following means anything outside this run: hypothesis or claim identifiers;
verdict words in a title or suptitle; multiplicity corrections and
pre-registration footers; internal codenames for arms, splits or slots. The title
says what the quantity did, in its unit; the axes carry quantity and unit; the
legend names the method and the reference. A verdict belongs in body text, where
it can be qualified.

## Before the figure stage closes

- [ ] `gate()` is called in the same function as every `savefig`, and a failure aborts the stage rather than printing a warning.
- [ ] Every named deliverable has at least one panel that passed with `needs_reference=True`.
- [ ] Every axis label contains a unit token from the decode table; none says normalised, arbitrary or index unless the caption states why nothing else exists.
- [ ] Every panel's landmark scalar is annotated inside the axes, in units.
- [ ] The banned-vocabulary assertion covers suptitles and figure-level text, not only the axes title.
- [ ] Per deliverable: object panel first, aggregate-rate panel second, never only the second.
