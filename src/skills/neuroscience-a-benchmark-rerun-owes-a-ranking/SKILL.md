---
name: neuroscience-a-benchmark-rerun-owes-a-ranking
description: Use at analysis and writing after re-running a published comparison of many methods on many metrics, when you are deciding what the section says. Covers separating the outcome of the comparison from the fidelity of your reproduction, counting the wins over the whole comparator set, and naming the class a claim survives in when a competitor beats the method the task is about.
applies_when: single-cell readouts
stages: 06_analysis, 07_writing
---

# Who won is a different result from how well you reproduced

Re-running a published comparison produces two results, and they are easy to collapse into one. The first is *fidelity*: how close your cells came to theirs — the median absolute difference, the fraction of published values your replicate band contains, the verdict your own preregistered rule returns. The second is the *outcome*: which method leads on which metric, by how much, over what comparator set. Fidelity is a property of your pipeline. The outcome is the science, and it is the thing the benchmark was built to produce. A section that reports only fidelity has published an audit of itself and withheld the finding, and it reads as a run that never answered the question.

Write the outcome as a sentence with a count in it, before the fidelity paragraph and again wherever the report summarises itself at the top. Per metric: the leading method and its margin over the runner-up. Across metrics: how many of the N the method the task is about leads, and who takes the rest. Then the ordering claim — whether the published ranking held, held in part, or inverted, and where. A grid of numbers is not this sentence; a reader who has to scan twelve rows by six columns to find out who won will conclude the answer was avoided.

When a competitor beats the method the task is about, that is a real result and the way to keep it is to say what class the claim survives in rather than going quiet. Supervised methods that see the very label the metric scores against are not in the same class as unsupervised ones and should be marked as such wherever they appear; a method tuned on the evaluation split is in a third class. State the claim at the scope it holds — best unsupervised method on k of N metrics, beaten on the remaining ones by these named arms, and here is which of those arms had label access. Silence plus a table where the reader can find a loss is the worst of both: it neither claims the win nor owns the loss.

Two more things the ranking sentence needs to be honest. A lead smaller than the within-method replicate spread is a tie and must be called one, so report both together and never bold a within-noise margin. And an arm that is broken — a comparator returning one feature where the protocol needs thirty, a selector whose output depends on the thread count — is not a loss for that method, it is a hole in your ladder; label it as unresolved in the ranking rather than counting it as a win for yourself.

Keep your own preregistered verdict out of this slot. A frozen rule returning SUPPORTED or PARTIAL is a statement about a hypothesis you wrote; it is not the comparison's outcome, and putting it where the outcome belongs is how a benchmark rerun ends up with no answer in it.

## Why this is here

On this task the run produced a full twelve-selector by six-metric ladder with published values beside its own, and headlined it "accurate in level, short on containment": coverage 18 of 33, median |delta| 0.0122, verdict PARTIAL. The strings "best unsupervised", "five of six" and "outperform" appear zero times in its 56,830-character report; the ladder's ranking statements are two published orderings kept as harness diagnostics and a competitor's win ("the random forest leads NMI at 0.6272"), and no sentence counts the method's own. The reviewer scored the benchmark criterion 37.0 and wrote that the report "does not systematically demonstrate that [the method] consistently outperforms all other methods" and "explicitly shows cases where other methods meet or exceed" it. The comparator ran the same protocol on the same file, wrote one sentence naming the method best unsupervised on five of six metrics, and scored 47.7 on the same criterion at a weight of 0.25.
