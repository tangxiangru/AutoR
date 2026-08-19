---
name: the-same-refusal-twice-is-a-shape-error
description: Use when a validation gate refuses an artifact you believe is correct, and especially when the same refusal comes back after you rewrote the content. Covers how to tell a complaint about your prose from a complaint about your JSON's shape, and why rewording is the one repair that cannot work on the second kind.
---

# A gate that refuses the same file twice is not reading what you think

A refusal you cannot satisfy is almost never a disagreement about content. It is
a gate reading a different part of the file from the part you rewrote.

The shape of the mistake is always the same. You write a rich, correct artifact.
A key name, a type, or a path is not the one the reader expects. The reader takes
the absent key as an empty value and reports it as empty. You open the file, see
full sentences where it says there is nothing, conclude the gate is broken or
being pedantic about wording, and rewrite the sentences. The next attempt fails
identically, because the sentences were never the problem.

Measured on a forty-task benchmark arm: one such mismatch — a plan written under
`task_item`/`produced_by`/`note` where the reader looks for
`stated`/`covered_by`/`why_not` — cost 62 attempts across 25 of the 40 runs, and
eleven stages were skipped entirely. Every one of those runs had written a
correct plan on the first attempt.

## The check, before the second attempt

When a refusal repeats, stop editing content and do this instead:

- **Read the message literally.** "States nothing", "names no source", "is empty",
  "has no X" are claims about a *field being absent*, not about what you wrote in
  it. A gate complaining about quality uses different words.
- **Find the reader.** The message names the file and usually the field. Find the
  code or the prompt that specifies it and copy the key names from there,
  character for character. A worked example in the stage prompt is the
  specification; prose describing the field is not, and where the two disagree the
  example wins.
- **Compare keys, not values.** Diff the key names in your file against the ones
  in the specification. Then the types: a string where a list is expected, a
  number written as `"3"`, a path with a leading `workspace/` where a
  workspace-relative one was asked for.
- **Check that you wrote the file the gate reads.** Two paths that differ by a
  directory — `outputs/report_plan.json` and `outputs/notes/report_plan.json` —
  are two files, and only one of them is being validated.

## What not to do

Do not soften, expand or reword the content in response to a structural refusal.
Do not add a second copy of the field under the name you already used. Do not
work around the gate by deleting the entries it complains about — a plan with
three deliverables listed instead of eleven passes the gate and loses the score
the gate existed to protect.

## If it still refuses after the shape is right

Then it is a content refusal, and it will have changed its wording. A message
that is byte-identical to the last one is telling you that nothing you changed
was read.
