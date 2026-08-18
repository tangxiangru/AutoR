---
name: do-not-grade-your-own-result-down
description: Use when drafting limitations, the discussion or the abstract, and any time you are about to call your own result unimproved, inconclusive or unverifiable. Covers the hedge that contradicts the run's own decision record, and the check a caveat has to fail before it is published.
stages: 02_hypothesis_generation, 06_analysis, 07_writing
---

# Do not grade your own result down

A report acquires a defensive register in its last hour. Sentences appear that
grade the work instead of reporting it:

- "This matches the published work rather than improving on it."
- "No check available here discriminates between the two admissible
  conventions."
- "We cannot be confident that our value is competitive."

Each is a claim about the evidence the run holds, written from memory at the end
of a long run by the one reader who will never check it against the artifacts.
Two things follow. A grader will not be more confident in your number than you
are, and will hand your own sentence back as the reason the criterion did not
pass. And the sentences are often false: in one run a question that
implementation had settled with a verbatim source quotation plus a second
independent route shipped as the first limitation, unresolved, warning the reader
that the headline number might be off by orders of magnitude.

This is not a licence to overclaim. State the comparison and let it carry the
verdict. If your number is worse than the published one, say by how much — that
is a measurement. "Not better", with no number beside it, is a verdict you
awarded yourself, and it costs the criterion whether or not it is true.

## The three states

One pass over every sentence in the draft that expresses doubt. Each resolves
into exactly one of three, in the text:

- **Settled.** Name the artifact and the evidence in one clause, then delete the
  hedge: "the convention is the one the source states in §2, and the independent
  route through Eq. (n) agrees (`notes/units_decision.json`)".
- **Open and bounded.** Say what the alternative would do to the headline number,
  and name the one measurement or comparison that would close it. A bounded doubt
  is a service to the reader.
- **Open and unbounded.** Rare. It has to say why no available check reaches it,
  and it may not sit under a deliverable the task named — see the checklist.

## Provenance of the thing you failed against

"Refuted", "inconsistent", "an order of magnitude off" is only as good as the
value you compared against. Before writing any of those words, check where that
value came from. An axis range on a figure, an illustrative setting in a caption,
a round number in a worked example, a default in a code repository: none of these
is a claim the source made. A mismatch against one of them is not a finding, and
writing it up as a refutation turns a correct answer into a self-inflicted
failure — the more so when it reaches the abstract as a count of hypotheses.

The comparator you *do* need — the source's published value for the quantity the
task asks about, printed beside yours in the same unit, under the same criterion
— is `close-the-gap-to-the-published-number` and `reproduce-then-extend`. Build
that row there. This skill is about not talking the reader out of it afterwards.

## Checklist, writing stage

1. Grep the draft for `unresolved`, `cannot`, `no check`, `either way`, `not
   verified`, `ambiguous`, `we assume`, `may be`, `not better`, `rather than an
   improvement`, `at best`. Every hit takes one of the three states.
2. For each hit, search the run's notes and decision artifacts for that question
   by name before keeping the sentence. A doubt you cannot support with an
   artifact is either already resolved on disk or never examined; find out which.
   In a long run, already-resolved is the common case, because the stage that
   settled it is hours behind you.
3. Any sentence that rates the work as a whole — competent, adequate, standard,
   not an improvement, a reimplementation — comes out. Rating is the reader's
   job; yours is the comparison that lets them do it.
4. The abstract states the headline quantity, its uncertainty and its comparator
   before it states anything about your own hypotheses. A count of supported and
   refuted internal hypotheses describes your process, and putting it first
   displaces the number the task asked for.
5. The limitation list holds no item that would, if true, make a named
   deliverable wrong by orders of magnitude and is left undecided. Decide it or
   withdraw the deliverable; an undecided one is a retraction printed under a
   softer heading.
6. Last pass, per named deliverable: read the sentence a reader would quote, and
   ask whether it lets them judge how good the number is. If it only describes
   your method, the comparator is missing. If it tells them not to trust the
   number, go back to step 2.

## Where the inputs to this pass come from

At hypothesis time, every preregistered threshold or window records where it was
read from and whether the source states it as a result — that record is what the
provenance check above reads later. At analysis, every choice between two
admissible conventions (factors of two, normalisations, reference constants, log
bases, per-mole versus per-particle) gets a small decision artifact holding the
alternatives, the evidence, the verdict, and how far the headline moves if the
verdict is wrong. Writing then has something to check against instead of a memory
of having once been unsure.
