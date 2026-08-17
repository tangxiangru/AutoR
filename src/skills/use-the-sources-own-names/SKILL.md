---
name: use-the-sources-own-names
description: Use at Stage 06 and Stage 07 when writing up a reproduction, and any time you have given a reproduced quantity, equation, figure or sequence a name of your own. Covers why a correct reproduction under private names reads as a missing one, which names have to be carried, and where they have to appear.
---

# A reproduction nobody can recognise is scored as one that did not happen

You rebuilt the source's closed form and matched it on ninety-six of ninety-nine
cases. In your report it is called the "GEO closed form", because that is what
your module is named. The source calls it Equation 3. A reader looking for your
verification of Equation 3 does not find one.

This is the cheapest loss in a reproduction and the hardest to see from inside,
because everything is correct. The work was done, the numbers agree, the figure
is there. Only the labels are yours, and labels are the entire interface between
what you did and what anyone asked for.

## Carry the source's names

For every object you reproduce, the source's name for it appears in your report,
in the sentence that reports your result:

- **Equations and formulae** by the source's number. "We recover Eq. (3) to
  within 0.010 across 96 of 99 interfaces" — not "the GEO closed form agrees".
  Give your own name once, in parentheses, if you need it for the code.
- **Named quantities, sequences and constants** as the source writes them. If the
  paper's series is the Mackay sequence and its own new sequence is 1, 13, 45,
  117, 239, 431, those digits belong in your text. A reader checking whether you
  reproduced the sequence looks for the sequence.
- **Figures** by the source's figure number. "Our Fig. 4 reproduces their Fig. 6d"
  is one clause and it converts an unlabelled plot into a verification.
- **Methods and baselines** by the name the field uses, not by your wrapper's.
  The comparators the task names are found by name or not at all.
- **Metrics** by their published name and definition. A metric you renamed and
  redefined is a third quantity, and its agreement with the published one is
  a coincidence you have not checked.

## Your framing goes second, not instead

There is usually a good reason the private name exists: your framing is more
general, or your version fixed something, or the source's notation is bad. Keep
it — after the source's name, in the same sentence. "Eq. (3) (which we implement
in the more general form G, below)". The order matters because the first name is
the one a reader matches against what they were looking for.

The same holds one level up. If your study reorganised the source's three results
into your own five questions, the report still needs three headings a reader
scanning for the source's results will land on. Your five questions can be the
subsections under them.

## Where the names have to be

Early. A reader forming a verdict on a figure often has the figure and the
opening of the report, and not the section on page four where the symbol is
defined. Put the source's name for the quantity, the equation number and the
target value in the abstract and the first results paragraph — the same place the
headline numbers go — and again in the figure caption and the axis label. A
definition that arrives after the verdict has arrived too late.

## The check

Take the source's own list of results — its numbered equations, its figure
captions, its abstract's claims. For each one this run reproduced, grep your
report for the source's name for it. Every miss is a reproduction you performed
and did not get credit for, and fixing it is a word.

See also `reproduce-then-extend` for the comparison table those names index,
`the-supplied-item-is-the-graded-unit` for the identifier a shipped object keeps,
and `citation-discipline` for pinning the reference the numbering belongs to.
