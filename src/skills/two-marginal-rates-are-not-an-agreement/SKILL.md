---
name: two-marginal-rates-are-not-an-agreement
description: Use at analysis and writing whenever your method and a reference implementation have been run over the same instances, and whenever a source figure plots one against the other. Covers reading a two-method scatter as an agreement claim that owes a number, the four paired quantities that number needs, and why a disagreement statistic of your own invention does not discharge the source's agreement statistic.
benchmarks: researchclawbench
stages: 06_analysis, 07_writing
applies_when: score used to quantify similarity
---

# Running both tools on the same instances buys a paired design. Do not throw the pairing away.

Two tools, one population, N instances each. What most runs then compute is each
tool's own rate over that population — detection above a cutoff, mean score,
fraction solved — and place the two rates side by side. That is a marginal
comparison. It says how often each tool clears a bar. It says nothing about
whether the two tools agree on any particular instance, and the two claims come
apart in both directions: two rates can match the source to a decimal place
while the per-instance values disagree badly, and two tools that agree almost
perfectly can straddle a cutoff and post different rates.

You paid for the pairing when you ran both tools on the same inputs. It is the
more informative half and it is one line of code away.

## A scatter is a statistic you have not written down

Look at the source's own figures. If one of them has the new method on one axis
and the reference on the other, with the identity line drawn, the result that
figure carries is *agreement* — and agreement is a number, usually a correlation
or a mean absolute deviation, usually stated in the caption or the first line of
the results paragraph. Reproducing the panel and not the number reproduces the
picture of the claim.

The same applies to a scatter you draw yourself. A panel that plots your value
against a reference's is an agreement claim with the number left off.

## The four quantities

From the joined per-instance table, and each is one line:

1. **The correlation over the population the source used**, with n stated. Name
   which instances are in it — the ones both tools scored is a different number
   from all the ones either scored, and the difference has to be visible.
2. **The signed difference**, mean and median. This is the direction and size of
   the bias: which tool reads higher, by how much.
3. **The absolute difference**, mean and median, plus the fraction of instances
   inside a tolerance you name before you look.
4. **The worst disagreement, identified**. Not "the maximum was 0.05" — the
   instance's own name, its two values, and one sentence on what is different
   about it.

State the normalisation once and use it throughout; a paired difference between
two quantities normalised differently is not a difference.

## Compute the source's paired statistic before your own

The expensive trap is not omission, it is substitution. A run notices something
genuinely interesting in the paired table — the two tools pick different
solutions on most instances, say — invents a disagreement rate to measure it,
finds the rate is large, and then spends a section establishing that the rate is
mostly an artefact of tie-breaking. All of that can be right, and it still
leaves the source's own agreement number uncomputed, in a report that now reads
as a run that measured disagreement and explained it away.

Order it: the source's paired statistic first, in the same table, under the same
population; your invented one after, with the reason it was worth adding.

## Checklist

- [ ] The per-instance joined table exists, with both tools' values in one row.
- [ ] Correlation, signed difference, absolute difference and named worst case are all in the report.
- [ ] The population behind each is stated, with n.
- [ ] Where the source published an agreement statistic, the same statistic is published under the same normalisation.
- [ ] No comparison rests only on two marginal rates over the same population.
- [ ] Any paired statistic you invented sits after the source's, not instead of it.

## Why this is here

Measured on a structural-alignment reproduction whose source figure is a scatter
of the new method's score against the reference's, captioned with a correlation
above 0.95. The run drew that scatter, published three marginal detection rates
at the 0.65 cutoff, and computed no correlation at all: the words "correlation"
and "Pearson" occur zero times in its report. Its own
`outputs/benchmark_931_raw.jsonl` holds both tools' scores for 928 pairs, from
which r = 0.9661 and 0.9942 for the two modes, with mean absolute differences of
0.0309 and 0.0042 — four lines of arithmetic over a file already on disk. What
the run published from that same table instead was a disagreement rate of its
own construction (27.71%) and a section arguing it was a tie-break artefact. The
bare comparison agent reported r = 0.970 and 0.986 and scored 26.7 against this
run's 18.3 on the criterion that names the correlation, the heaviest criterion
on the task.
