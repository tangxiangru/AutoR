---
name: astronomy-sample-the-published-table-into-chains
description: Use at study design and implementation when the source's constraints reach you as a table of best-fit values with 1-sigma errors for two or more models and no posterior samples were released. Covers rebuilding the ensemble that table describes, writing it in the layout this field's posterior tools read, and what to state about the construction so it is evidence rather than decoration.
benchmarks: researchclawbench
applies_when: constraints on cosmological parameters
stages: 03_study_design, 04_implementation, 06_analysis
---

# A published mean and sigma is a posterior handed to you, not a number told to you

A table of `parameter: mean, 1-sigma` for each of several models is a posterior in
compressed form. It was produced by a sampler you cannot re-run — the likelihood stack,
the emulator and the chains are usually not public — and the table is the only form of
that posterior that was released. So rebuild the ensemble it specifies, early, before
your own likelihood exists. It costs a page of code, it introduces no assumption you do
not already make when you quote the table, and it is the only form in which the source's
constraint can be drawn on the same axes as anything else.

Draw a large ensemble per model — enough points that the 95% contour comes out smooth
rather than ragged, which puts you in the tens of thousands, and twenty thousand is a
common choice — from the multivariate normal the table specifies: independent Gaussians
unless the source publishes correlation coefficients or releases a covariance, in which
case use them. Sample **every row the table carries for that model**, not the subset your
own analysis will touch, and add the model-specific rows (an extra energy component's
amplitude and epoch, a dark-energy equation-of-state pair) alongside the shared ones.

Write it out in the layout the field's posterior tooling reads, not into a private NumPy
array. For cosmology that is GetDist's chain layout, which the other packages also
accept: one text file `<root>_1.txt` per model whose first two columns are the sample
weight and `-log L` — weight 1 and a constant likelihood are correct for a synthetic
ensemble — followed by one column per parameter, beside a `<root>.paramnames` file with
one `name   LaTeX label` line per column in the same order. Once those files exist,
`getdist`, `corner` and `ChainConsumer` will each draw the published constraint without
further work, and the triangle plot the field expects becomes a three-line call rather
than a project.

This is also what fills the parameters your own fit can never reach. A background-only or
distance-only likelihood constrains nothing about an optical depth, a primordial
amplitude or a spectral tilt — but the table gives each of them a mean and a sigma, so
each of them has a distribution, so each of them has an axis. "No fit of this run
constrains it" is a true sentence about your sampler and a wrong reason to leave a
tabulated parameter out of the comparison.

State the construction once, in Methods, in the form a reader can check: the distribution
family assumed, the number of samples per model, which published table each set of means
and errors came from, and which correlations you did not have. Independent Gaussians give
axis-aligned elliptical contours; that is a property of the published summary you were
given, it is worth one sentence, and it is not a reason to withhold the figure.

Keep the ensemble in its own lane. It is the published answer redrawn and it contains no
information the table did not: no chi-square, no goodness-of-fit and no evidence ratio
comes out of it, and it never enters a fit as data. When you also run your own sampler,
give the two ensembles separate chain roots and separate legend entries, overlay them,
and never merge them into one set of samples. If your audit finds a table row that
disagrees with the archival release, sample the row as published and annotate the
disagreement — the reader is checking the published constraint, and a row you deleted is
a constraint you did not show.

## Why this is here

Measured on Astronomy_001 of ResearchClawBench, rescored with gpt-5.1 over three draws.
The task ships one 2,010-byte file whose parameter block gives seven parameters shared by
all three models — matter density, Hubble constant, sigma-8, spectral index, baryon
density, log primordial amplitude and optical depth — each as a mean with a 1-sigma
error, plus the model-specific rows. The criterion for that step carries 0.2 of the task
and asks for simulated chains at the table's means and errors, twenty thousand points per
model, in a GetDist-compatible form; the AutoR run scored **1.0 out of 100** on it
against **11.7** for a bare agent, and both judgements say the same thing — the step is
absent, replaced in each case by that run's own sampler over its own parameter set.

What the block was for is settled by the figure the next criterion grades against: a 7×7
corner plot whose axes are exactly those seven rows in exactly the file's order, three
models overlaid, and whose contours are axis-aligned ellipses — the signature of
independent Gaussians drawn from a table of means and sigmas, and nothing else. Neither
arm built it. The strings `triangle`, `corner plot` and `getdist` match no file under the
AutoR run's `code/`, `outputs/`, `report/` or stage records, while the source paper's
full text, which the run itself fetched to
`.autor/*/workspace/literature/target_paper_2503.24343_fulltext.txt`, carries the
sentence "we use GetDist ... to display the posteriors". Its Stage 01 had already written
down the enabling assumption in as many words — that it would treat the published
marginals as Gaussian — and spent it only on converting parameter shifts into sigmas. Its
parameter figure is a row of five one-dimensional error bars, one of them an internal
sampler parameter the published block does not carry, while the tabulated optical depth
and log amplitude get no axis at all. The phrase "optical depth" does not occur in the
57,594-character report, and every τ in it is the sampler's autocorrelation time.
