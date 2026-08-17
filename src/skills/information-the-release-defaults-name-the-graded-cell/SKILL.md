---
name: information-the-release-defaults-name-the-graded-cell
description: Use at literature survey when you first open the released code, and again at study design when you are deciding which benchmark gets the deepest run and which gets a token arm or two. Covers reading the entry point's default arguments, run-all script and shipped notebook as the source's own statement of its canonical experiment, and why the benchmark where your effect is largest is the wrong place to spend the surplus.
applies_when: fixed-resolution vision encoders|task-guided cropping strategy
stages: 01_literature_survey, 03_study_design, 06_analysis
---

# The source already told you which cell it is about: read the defaults

A reproduction has to choose where the depth goes. Two or three benchmarks, half
a dozen method variants, one clock. Getting a floor sample into every cell before
any cell is deepened is the first rule and it is elsewhere —
`information-fill-the-whole-results-grid` for why an empty cell is worse than a
crude one, `price-the-queue-and-preempt-your-own-arms` for the arithmetic. This is
the rule for where the *surplus* goes once every cell has a number in it, and
neither of those answers it.

The source has already answered. It is written in four places, none of which is
prose, and all of which are read past:

* **The entry point's default argument values.** `--model llava --task textvqa
  --method rel_att` is a sentence: *this is the experiment, and everything else
  is a flag*. Defaults are chosen by an author who ran the thing a thousand
  times.
* **`run_all.sh`, the Makefile target, the README's quick-start command.** The
  authors' own schedule, in their own order.
* **The notebook that ships with its outputs still in it.** Whatever it computes
  is the demonstration the authors wanted a stranger to see first, and its
  stored cells are free ground truth you can diff against before you spend a
  second of compute.
* **The first column, or first row, of the headline table.** Table order is
  not alphabetical.

Rank the cells that way, write the ranking down at literature survey, and let it
decide depth. The deepest cell of your study should be the source's default
cell, in the source's default configuration.

## The pull in the other direction, and why it loses

You will find that your own question separates better somewhere else. The harder
benchmark has smaller targets, so the effect is three times larger there; the
contrast you want to decompose is visible at a sample the easy benchmark cannot
reach. So the arms go there — nine, ten, thirteen of them — and the source's
default benchmark keeps a baseline, the headline method, and an oracle.

That trade buys resolution on a question the source treats as secondary, and
pays for it by leaving the source's own comparison at one method row. When the
work is read against the source, the deep benchmark is a section and the shallow
one is the study. A larger effect size is a reason your extension belongs on
that benchmark. It is not a reason the reproduction moves there.

If the surplus is real, spend it in this order: the missing method rows in the
default cell, then the second host in the default cell, then the sample size of
the default cell, then your own arms anywhere.

## Cheap is usually the same direction

The default cell is often also the cheapest one — a single-image path where the
harder benchmark runs a tiled high-resolution path, small images where the other
has 2000-pixel ones. Price both before you assume otherwise: completing four
method rows on the cheap default can cost less than two extra arms on the
expensive one, and it fills the rows a reader is checking.

## The check at analysis

Before you write, tabulate `arms × items` per dataset from your own results
files, and put the source's ranking beside it. If your largest product is not on
the source's default cell, say why in one sentence, in the report, where the
choice was made — and check that the sentence is about the source's question and
not about yours.

## Why this is here

A run reproducing a training-free cropping method transcribed the source's
headline table at literature survey — four method rows across seven datasets,
with the default dataset in the first column — and then made the *other*
benchmark its study: thirteen arms over twenty-six items, six of nine figures,
the abstract, and the title. The default dataset got three arms over sixty
items. Both quantitative criteria it was graded on, together weighted 0.8, were
on the default dataset, and the gradient rows they name never ran on it. The
run's own design note even proposed the right fix — *spend any surplus on the
gradient row rather than on extending the other benchmark's sample* — and then
proposed it for the wrong dataset's column.
