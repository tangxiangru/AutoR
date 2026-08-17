---
name: record-what-you-learned
description: Use when a run is finished and the report is written, after the report is written, to record one reusable lesson for the next run in this field. Covers what counts as a lesson worth passing on, what must never be passed on, and how to write it.
stages: 07_writing
---

# Leave one note for the next run in this field

You hit things this run that were in no prompt: an archive that stores its axis in
an unexpected order, a reference implementation needing an undocumented flag, a
check that caught a mistake you would otherwise have shipped, a step the field
treats as obvious and no instruction mentioned.

The next run in this field hits the same thing unless you write it down.

## How

Run this once, at the end:

```
python3 -c "
import sys; sys.path.insert(0, '<AUTOR_ROOT>')
from src.skill_evolution import record_note
note, problems = record_note(
    discipline='<the field, e.g. earth>',
    title='<short, routable, what the lesson is about>',
    body='''<what you hit, and what to do instead next time>''',
    learned_in='<this task id>')
print(problems or 'recorded')
"
```

A good note is one paragraph answering: what surprised you, how it shows up, and
what to do instead. Write it for someone competent who has not seen this corpus.

## What must never go in

**No results.** Not your numbers, not the paper's, not "it came out around X". A
note travels to a *different task*, and a finding that travels is contamination —
it invites the next run to expect an answer instead of measuring one. The recorder
refuses notes containing measured values, and that refusal is not an obstacle to
work around.

**Nothing you did not hit.** A guess about what might help is prose, and prose
accumulates until nobody reads the pool. A run that learned nothing transferable
records nothing. That is a valid outcome.

## One note

Not five. The pool is capped, and a run filing five pushes out four another run
earned. Pick the one you most wish you had known at the start.
