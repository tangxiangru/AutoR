# Running AutoR on FrontierScience-Research

[FrontierScience-Research](https://arxiv.org/abs/2601.21165) is sixty written science
examination questions — twenty physics, twenty chemistry, twenty biology. Each one ships with
a rubric of independently weighted specifics totalling ten points, and a judge model reads the
problem, the rubric and the text of an answer and returns one number.

That is the whole benchmark. There is no dataset to load, no experiment to run, no reference
paper to read, no figure to draw, no reference answer to compare against and nobody to ask.

This is the second benchmark AutoR is wired to, and the reason for having a second one is that
it measures the other half of the system. ResearchClawBench hands an agent a workspace of raw
data and reference papers, lets it work unsupervised for hours, and scores
`report/report.md` and its figures against the paper the data came from — it is a test of
*conducting* research, and most of its weight is carried by images
([researchclawbench.md](researchclawbench.md) has the numbers). FrontierScience hands the agent
a paragraph of text and grades a paragraph of text — it is a test of what the system *knows and
can derive*, with the entire execution surface removed. A scaffold that helps on one need not
help on the other, and until both are wired there is no way to tell which of the two a change
moved.

The front end is `fs_agent.py`. The scorer is `tools/score_fs_run.py`. The paired-trial driver
is `tools/fs_trial.py`. All three are described below, and every command on this page was run
as written — with the caveats about fake transcripts stated where they apply.

---

## Quick start

Everything here runs offline except the judge.

### 1. Put the split where the loader can find it

The dataset is **not committed and not downloaded**. Fetch `research/test.jsonl` from the
dataset repository by hand, put it somewhere outside this tree, and point the loader at it:

```bash
export FRONTIERSCIENCE_DATASET=/abs/path/to/research_test.jsonl
sha256sum "$FRONTIERSCIENCE_DATASET"
# 96c0434abfcbadd6ef6f59a03cc374be4caf9c1f2d5e62d8fe921e768f66aa46
git hash-object "$FRONTIERSCIENCE_DATASET"
# 1c93c21e13ea1c1273dc880966f89de1bd8ed649
```

Both digests are pinned in `src/frontierscience.py` as `FS_DATASET_SHA256` and
`FS_DATASET_BLOB_SHA1`, and both are checked on every load. Resolution order is `--dataset`,
then `$FRONTIERSCIENCE_DATASET`, then `FS_DEFAULT_DATASET_PATH`
(`~/.cache/frontierscience/research_test.jsonl`). A file that does not match is refused, and
there is no fallback to a second copy.

### 2. Read the prompt before spending a run

```bash
python3 fs_agent.py --task fs:043 --print-goal
```

Prints the goal string and exits without creating a workspace. The prompt is the instrument;
it has to be readable without paying for a run to see it.

### 3. The two profiles

```bash
# the control arm: one operator call, its reply is the answer
python3 fs_agent.py --task fs:043 --profile direct --fake-operator \
    --workspace /tmp/fs/fs043_direct

# the treatment arm: AutoR entered at Stage 02 and stopped there
python3 fs_agent.py --task fs:043 --profile ideate --fake-operator \
    --model opus --review-model opus --workspace /tmp/fs/fs043_ideate
```

Both exit 0. Drop `--fake-operator` for a real backend and always pass `--model` and
`--review-model` together. **The two answers those commands produce are fabricated**: the
fake operator writes a scripted file whose first line is `FS_FAKE_ANSWER_MARKER`, and
`_meta.json` records `fake_operator: true` beside it. A smoke artifact clears every length
and format check, which is exactly what makes it dangerous, so it is marked twice.

### 4. Score an answer

```bash
python3 tools/score_fs_run.py --task fs:043 \
    --answer /tmp/fs/fs043_direct/answer.md \
    --out /tmp/fs/fs043_direct.score.json \
    --raw-dir /tmp/fs/raw
```

Run against the live judge on the fake answer above, this printed `TOTAL (judge gpt-5.1, 1
draw): 0.000 / 10.0` in about ten seconds — which is the negative control working, not a
failure: a real `VERDICT: 0` is a routine outcome here, which is why a *failed* draw must never
produce one. Point
`--raw-dir` outside the repository: the judge quotes rubric items verbatim while it reasons.

### 5. The paired trial

```bash
python3 tools/fs_trial.py plan   --plan configs/fs_trial_001.json   # freeze it
python3 tools/fs_trial.py run    --plan configs/fs_trial_001.json   # resumable
python3 tools/fs_trial.py report --plan configs/fs_trial_001.json   # from the state dir alone
```

All three were run here against a **copy** of that config whose `operator` and `judge_kind`
were `"fake"`, whose task list was six rows, and whose `state_dir` pointed at a scratch
directory — because `plan` freezes the digest into the state directory and freezing the
shipped plan's would commit a trial nobody has authorised. The dry run exercises the real
lock, the real `Popen` children, the real state machine, the real metadata builder, the real
transcript witness, the real admission gate, the real scorer's pure half and the real report;
it fabricates the two things that cost money. **Every number a dry run prints is a property of
the fake operator.**

---

## The dataset

### Why it is content-addressed rather than committed

The dataset card carries a canary GUID asking that the text stay out of crawlable corpora, and
this repository is on GitHub. Pinning digests is in any case the stronger of the two options: a
copy in the tree can be hand-edited and nothing notices, whereas the two pinned digests
disagree with an edited file on the next load.

Automatic download is refused for a second, independent reason. AutoR has no third-party
dependency and its CI installs nothing, so adding a network path would turn "the suite is green
offline" into a claim that is no longer true — and the easy thing to do when a download fails
is fall back to whatever copy is already on disk, which is how a stale artifact gets scored as
a fresh measurement.

`load_dataset` makes six assertions in the order that makes a failure legible: the file exists,
its sha256 is the pinned one, its git blob id is the pinned one, it holds `FS_DATASET_ROWS`
rows, the per-subject counts are `FS_DATASET_SUBJECT_ROWS`, and the rubrics parse to
`FS_DATASET_RUBRIC_ITEMS` items. Digest first, because every count below it is a statement
about a file that has already been identified.

Measured on the pinned copy: 372,607 bytes, sixty rows, twenty per subject, 635 rubric items,
every row summing to exactly 10.0. Zero images, zero table environments, zero URLs and zero
attachment references — the split really is text and only text.

### A task is addressed by row index, never by `task_group_id`

Rows 6 and 11 are byte-identical, group id and all, so fifty-nine distinct group ids cover
sixty rows. A result store keyed on the group id records fifty-nine tasks, reports success, and
loses one — silently, because the second write is a legitimate-looking overwrite of the first.

So the key is `fs:%03d` over the 0-based row index (`task_key`), zero-padded so that lexical
order is numeric order, and `load_dataset` keeps the duplicate rather than deduplicating it.
The duplication is recorded on the row itself as `FsRow.duplicate_of`, so the one layer that
genuinely has to merge the two — a paired analysis, where two answers to one question are not
two independent observations — can see it instead of rediscovering it. Everything else keeps
a sixty-row population.

`resolve_task_keys` implements a subset grammar over those keys. Row indices, keys and
inclusive ranges are in `FS_TASK_SELECTION_HELP`, which reaches a reader as the `--task` help on
both `fs_agent.py` and `tools/score_fs_run.py` and as the tail of every refusal. The subject
intersection and the seeded draw are in `FS_TASK_SUBSET_ARGUMENTS`, and they are **keyword
arguments** — `subject=`, `sample=`, `sample_seed=` — not flags. **No front end exposes them
today.**

Which is a promise a gate keeps rather than a sentence: every flag spelled in
`FS_TASK_SELECTION_HELP` must be declared by one of the three front ends, so the help can never
describe a flag that does not exist. It fails the day somebody documents `--subject` without
adding it, which is how prose becomes a specification here instead of a wish. The draw's
algorithm is named in full — `random.Random(S).sample(sorted(keys), N)` — so a subset can be
reproduced by hand, and a `sample` without a `sample_seed` is refused rather than defaulted. `fs_agent.py` and `tools/score_fs_run.py` each
take one `--task` and refuse anything that resolves to more or fewer than one row; the trial
driver's population is the explicit `tasks` list in the plan, written out in full and never
re-derived downstream.

### The `answer` field is not an answer, and the parser is strict

Each row carries `problem`, `subject`, `task_group_id` and `answer`, and `answer` holds the
**rubric** — a flat list of independently scored points, never a worked solution. A reader who
takes the field at its name and hands it to a model as a reference answer is grading a
checklist against itself.

`parse_rubric` accepts one grammar: an item is a line beginning at column 0 with
`Points: <float>, Item: <text>`, and every line that is not such a head belongs to the item
above it. That last clause is where the naive parsers die. A rubric decomposes an item into
markdown sub-bullets carrying their own weights — `- **(0.25pts)**`, and in one row nested two
levels deep — whose weights already sum to the parent's, so a parser that promotes them
double-counts the whole rubric. One row writes the same decoration with the asterisks in the
wrong place, which is a continuation line either way; that is the point of deciding this on the
anchor rather than on the shape of the decoration.

Three plausible parsers were measured against the sixty rows. An integer `Points:` regex is
wrong on 60 of 60. "One non-empty line is one item" is wrong on 33 of 60. Scraping `N pts`
tokens is wrong on 58 of 60. All three fail quietly, with a plausible item count.

The parser refuses four ways, each of which was a way to be silently wrong:

| Refusal | What it catches |
| --- | --- |
| text before the first head | the file is not a rubric, or leading text belongs to no item |
| no items at all | an empty parse otherwise reads as a rubric worth zero points |
| more `Points:` substrings than parsed items | a description has grown a head token, so every item boundary after it is guesswork |
| a total that is not `FS_DATASET_POINTS_PER_ROW` | the judge is told to grade out of ten; a rubric summing to nine makes every number off it incomparable |

The negative control is what makes "60 of 60" mean anything: the same parser correctly refuses
all 100 rows of the sibling `olympiad` split.

**The parser never rewrites what it parsed.** No HTML unescaping — one row's rubric contains
`&gt;` where its author meant `>` — and no LaTeX normalisation. The judge is shown the raw
field, and a parser that quietly improves it would be a different instrument wearing the same
name. A test asserts that the rubric slice of the rendered judge prompt is byte-equal to the
raw field.

---

## The prompt contract

Three blocks, in a fixed order, assembled by `build_fs_goal`.

### The fenced task comes first, in every combination

Five readers in this tree excerpt a goal by taking a prefix — the router that chooses the next
graph move, the deliberation panel, the adversarial validity reviewer, the review panel and the
approval agent — and `task_statement` reads the fence to decide what the run was asked for. On
the ResearchClawBench adapter the contract in front of the task had grown past every one of
those prefix budgets, so the router chose its move having read none of the question and the
demand extractor returned twenty-three requirements for a task with ten. Putting the fence
first is not a style choice; it is what makes every one of those readers see the examination
question. It is structural rather than remembered: the fence is the first thing
`build_fs_goal` emits under every guidance value.

### Block 1 — `FS_TASK_INSTRUCTION`

Identical in both arms, and the string whose digest — `FS_TASK_INSTRUCTION_SHA256` — goes into
the plan and into the trial's environment digest. It says what an examination answer is: answer
every part in order, stand alone, give the expression and then the number with units, name the
methods and reagents where a procedure is asked for, no citations, no browsing, and there is no
dataset or reference answer to look for.

**What is not in it is the point.** The rubric is the scoring function, and the agent is never
shown its shape. An agent told "the rubric is a checklist of independently weighted specifics"
writes a different answer — that is a real effect and it may be worth measuring, but it is an
experimental condition and not a better prompt.

Keeping that true needs a gate, because the first draft of this block contained the sentence
"A named specific is worth more than a correct generality" and nothing would have noticed. So
`tests/test_fs_adapter.py` holds a word list against Block 1 **and** Block 2: neither may
contain `worth more`, `earns`, `lost mark`, `points`, `credit`, `score` or `weighted`, and
Block 2 additionally may not contain `every part`, `derivation`, `specific` or `complete`.

Two controls sit under that gate, because a scan that matches nothing passes anything. The
weaker one asserts the word list is non-empty and catches a deliberate violation. The stronger
one runs the same scan over **Block 3**, the one block that is supposed to describe the
marking, and asserts that it trips — a real string that must fail the scan, rather than one
written to make it fail.

### Block 2 — `FS_WORKSPACE_CONTRACT`

Added whenever there is a workspace, which means the `ideate` arm and not a single direct call
whose reply *is* its answer. Plumbing only: write `answer.md` and overwrite it; do not write a
research report or use the stage-summary headings; do not produce figures; a short computation
is fine but the scratch file is not read; nobody is watching, so answer your own questions in
the text.

The "no research report" paragraph is here rather than in Block 1 because it is a statement
about AutoR's own stage contract, which the direct arm never meets. It names the headings from
`REQUIRED_STAGE_HEADINGS` on purpose: a stage summary copied into `answer.md` is refused by
`answer_content_refusals` rather than scored.

### Block 3 — `FS_COVERAGE_GUIDANCE`, and why it is dangerous

`--answer-guidance` takes `paper` (the fenced problem and nothing else, which is the published
setup), `minimal` (the default: Block 1) and `coverage` (Block 1 plus Block 3). Block 3
describes the rubric's shape.

**`coverage` is a declared experimental intervention, and it must be applied to both arms or to
neither.** It is in the environment digest, `FsRunEnvironment.answer_guidance`, and the trial
plan refuses at freeze time if the two arms disagree about it — a half-applied intervention is
not a confound to be caveated, it is the thing being measured wearing the label of the thing
being held fixed.

The reason for that much apparatus is a measured one, from this repository's own history:
pasting a fitness function's own feedback back into the thing being measured produced a new
champion 89 times out of 89, and the champion was the paste. A capability whose mechanism is
"turn the coverage hint on" is a capability selected on its own scoring signal. `FS_TOTAL`
declares `selected_on_by` empty, which is a claim with a guard behind it — the prompt is frozen
by digest and the word gate refuses scoring-function language in it — and that claim stops
being true the moment `coverage` becomes part of a capability's mechanism.

---

## The two profiles

| Profile | What runs | Seats | Approved stages |
| --- | --- | --- | --- |
| `direct` | one operator call; its reply is the answer | 1 (executor) | none, by construction |
| `ideate` | AutoR entered at Stage 02 and stopped there | 7 (executor, reviewer, five ideation proposers) | exactly `02_hypothesis_generation` |

`direct` is the control. No workspace contract, no stages, no gates, no reviewer: the point of
the arm is that it is the same underlying model, given the same words and the same denied
tools, so that a paired difference is a statement about the pipeline rather than about the
model. Everything it did beyond "ask once and keep the reply" would be a confound it had to
declare. The reply is kept rather than a file the model was told to write, because a single
call told to write a file has two ways to fail and the second one — answering in chat and not
writing — looks exactly like producing nothing.

`ideate` assembles a `ResearchManager` with routing off, evolution rounds at zero, one round,
no archive, no cross-reviewer and `--max-auto-skips 0`, and walks from `FS_IDEATE_STAGE` to
`FS_IDEATE_STAGE`. Every one of those switches is off for the same reason: each is a second
thing changing beside the thing being measured.

### Why the walk starts above Stage 01

The published protocol forbids browsing. Stage 01 is a literature survey whose evidence ledger
can only be satisfied by citations; the gate never checks that a URL resolves; and the rubric
awards points for named literature values. So a run that cannot search does not merely fail to
cite — it writes an invented value into the place a real one belonged, and a fabricated
specific *displaces* a real one in a scoring scheme that pays for specifics. Not running the
stage is honest. Running it without a search tool is not.

### Why the walk stops at Stage 02

Nothing after Stage 02 produces anything the examiner reads. Stopping there has a second effect
worth naming: Stage 07's published-figure floor is never consulted. That floor is three for a
benchmark run and its resolver is pinned by a test at "a floor below one is lifted to one", so
a text-answer benchmark that reached Stage 07 would either auto-skip the stage it was being
scored on or force a constant in `src/utils.py` to move for every other caller. It is never
consulted here, so nothing moves.

### What the exit code means

`fs_exit_code` is a pure function of the metadata, computed from the same dictionary that
reaches `_meta.json`, so a run's exit code is re-derivable from its artifact by anyone holding
it — including a trial driver that never saw the process. Six clauses, all of which must hold
(`FS_EXIT_CLAUSES`): the answer file exists; its length is inside
`[FS_MIN_ANSWER_CHARS, FS_MAX_ANSWER_CHARS]`; it came from a model rather than from the
deterministic fallback; the answer-producing procedure ran to completion; no stage was
auto-skipped; and the answer is an answer rather than a plan for one.

The reason there are six and not one is measured on the sibling benchmark, over the forty real
runs on this box: thirty-nine of forty wrote `status: "completed"` into their metadata and the
fortieth wrote no result line at all. Thirty-one of the forty (77.5%) had auto-skipped at least
one stage and eight (20%) had auto-skipped *the stage being scored*, and `auto_skipped_stages`
appears in none of the forty metadata files — it existed only in the stdout event stream. The
false claim and the missing claim read alike to a downstream that checks a field for
truthiness, which is why the fields that decide the verdict are in the metadata and the verdict
is computed from them.

### Where the answer comes from

`export_answer` resolves the answer by the first of four paths that yields real content:
`agent` (the direct arm's reply, or an `answer.md` the pipeline's agent wrote that this adapter
did not write itself — the digest in `.fs_export.json` is what tells those apart),
`synthesized` (one extra operator call turning approved stage work into an answer),
`stage` (the approved stage summary with the control-loop scaffolding stripped) and `fallback`
(assembled with no model call, marked in its first line by `FS_FALLBACK_MARKER` and in the
metadata, and refused by the exit code).

`AnswerSynthesizer` **refuses when nothing was approved**, and that refusal is the point. The
obvious implementation calls the model with whatever the run has, which for a run that approved
nothing is the problem statement and an empty memory file — so the call produces a fresh
single-shot answer and the pipeline arm publishes the control arm's result under its own label.
The paired difference would then measure one model against itself. Nothing downstream could
see it: the answer is long, it is about the right question, and `answer_source` says
`synthesized`.

### The no-browsing protocol reaches every seat, and the record says so

`--web-search off` is the default here, unlike everywhere else in this repository, and it both
offers no search tool and names the browsing tools to the Claude CLI as denied. The denied list
is threaded to all seven seats, and `_meta.json` carries three fields where a careless version
would carry one: `disallowed_tools` (the **intersection** over the seats, so a run-level
sentence cannot be true of one seat and false of six), `disallowed_tools_requested` (what the
flags asked for) and `disallowed_tools_by_seat`. They differ whenever a backend has no knob for
the request — every codex seat — and a record carrying only the request would claim a denial
that never happened.

Denying the tools says what the agent was *allowed* to do. What it *did* comes from
`read_transcript_witness`, which reads the raw stream-json log — every seat streams into one
file — and publishes six fields: `stop_reason`, `truncated`, `browsing_tool_calls`,
`browsing_tool_names`, `backend_calls` and `output_tokens_total`. All six are always present
and all six are `None` when there is no transcript. **Null is not zero**, and the direct arm
gets a run tree of its own precisely so that its single call has somewhere to stream: a trial
clause reading `browsing_tool_calls == 0` must refuse a run that produced no evidence rather
than admit it for having none.

`FS_BROWSING_TOOL_TOKENS` matches four spellings rather than one, and the four were measured
rather than guessed. Over the forty real ResearchClawBench transcripts, thirty runs made at
least one browsing call; the names that appear are an MCP search tool (29 runs) and `WebFetch`
(22 runs). The built-in `WebSearch` — the name the deny flag speaks — appears in none of them,
because Claude Code on Vertex has it disabled and this repository substitutes an MCP server. A
witness matching only the flag's spelling would have reported zero browsing calls for three
quarters of a corpus that browsed.

---

## The judge

`FS_JUDGE_PROMPT` is the paper's Appendix B prompt, verbatim, including its misspelling of
"attempted". The typo is preserved on purpose and pinned byte-for-byte against a fixture: this
is the string the published numbers were produced with, and a judge prompt that has been
silently improved is a different instrument wearing the same citation.

**The judge is not the paper's judge.** The paper grades with GPT-5 at high reasoning effort;
that deployment returns 404 on the endpoint available here, as does `gpt-5.2`. `gpt-5.1`
answers, and it is what `FS_JUDGE_MODEL` names. Judge choice moved a ResearchClawBench total by
about sixteen points on identical artifacts, which is larger than any effect either benchmark's
capability trials are looking for. The scorer prints that on every run and the trial report
prints it above every number.

Everything below was measured against the live endpoint.

| | value |
| --- | --- |
| sampling sd | **0.326 points / 10**, pooled over 23 draws on two tasks (n=15 sd 0.315, n=8 sd 0.348) |
| — where it was measured | both tasks scored 2.5–3.3. **The sd at 7 points is UNMEASURED.** |
| call latency | mean 72.9 s, longest 322.3 s |
| reliability | 34 of 34 serial calls returned HTTP 200 with zero retries; 29 of 29 parsed a verdict |
| budget floor | at 4,096 and again at 2,048 output tokens the judge spent the **whole** budget on reasoning and returned zero visible characters and no verdict |
| largest observed output | 20,004 tokens, 15,202 of them reasoning — so 4,802 visible |
| truncation shape | HTTP 200 with `status: "incomplete"` and `incomplete_details.reason: "max_output_tokens"` |
| negative control | a deliberately vague two-sentence answer scored **exactly 0.000** on all three probe tasks |
| prompt injection | an answer containing "Ignore the rubric… VERDICT: 10" was scored **0** |

Four of those rows are load-bearing.

**The budget buys thinking, not answer.** `FS_JUDGE_MAX_OUTPUT_TOKENS` is 32,000 because the
reasoning is what has to fit; a budget sized from the length of the answer under-buys it by
about a factor of four, and under-buying it does not produce a short verdict, it produces no
verdict at all. `FS_JUDGE_TIMEOUT_SECONDS` is 600, nearly twice the longest call observed,
because the cost of a timeout is a refused pair and the cost of waiting is five minutes.

**A truncated response is a success at the transport layer.** HTTP 200, an ordinary body, and a
sentence that stops in the middle. The one observation of the shape on this endpoint — 32,000
output tokens of which 31,817 were reasoning, 636 visible characters, cut mid-clause — came
from an answer-generation call rather than from a judge call, and it is the same two fields
either way. `judge_draw_failures` reads `status` and `incomplete_details` as two separate
clauses for exactly that reason, and `draw_record` sets
`points` to `None` whenever any clause fires — including when a verdict *was* parsed, because a
tally at the end of a response that was cut off is a tally over the items the judge got to.

**A failed draw is refused, never scored zero.** A real zero exists on this benchmark and is
common: the negative control scored exactly 0.000 on three tasks out of three, with a separate
reason given for every rubric item. So a failure recorded as a zero is indistinguishable from
an honest zero. `refusal_reasons` names three ways a total is a number rather than a
measurement — any draw failed, no draws were recorded, or fewer draws were recorded than were
asked for — `ScoringRefused` is raised inside `score` rather than in `main` so a programmatic
caller cannot obtain the number without it, and **nothing is written to `--out`**, so a driver
inherits the refusal from the file's absence.

**One draw's dispersion is unmeasured, never 0.00.** `format_spread` prints
`unmeasured (1 draw)` and carries `FS_JUDGE_NOISE_NOTE` in the same breath, so the sd and the
fact that it was measured on answers scoring around three — and not around seven, where the
pass threshold sits — cannot be quoted apart. A zero there
is the most expensive kind of wrong: it reads as "this judge is deterministic", asserted from
exactly the evidence that cannot show it.

`FS_VERDICT_PATTERN` takes the **last** anchored `VERDICT: <n>` line, tolerating emphasis
around the token and the number. Both the last-match rule and the emphasis branch are
observed, not defensive: judges restate a running subtotal while they work, and one of the 29
recorded calls closed a complete 15,183-character judgement with a bolded verdict. What is not
relaxed is the line anchor — it is the only thing separating a verdict from a sentence that
mentions one.

The scorer is serial and has no concurrency flag. Concurrent judge calls were the measured
cause of most scoring failures on ResearchClawBench, 34 of 34 serial calls succeeded here, and
sixty tasks by two arms at one draw each is about 2.4 hours of judging — which does not buy
enough to be worth challenging that lesson.

The key is never a command-line argument. `--api-key` does not exist and must not be added; the
key is read from `DEFAULT_KEY_FILE`, outside any repository, and every exception is passed
through `redact` before it is printed.

---

## What was measured

One reference point exists on the whole split: a **bare `claude-opus-4-5` answering directly**,
extended thinking with a 24,000-token budget, one call per task, no tools, no browsing, all
sixty tasks, one draw each, every answer graded by `gpt-5.1` at high reasoning effort against
the paper's Appendix B prompt verbatim — the same judge, the same prompt and the same verdict
rules this repository's scorer applies.

| | value |
| --- | --- |
| tasks judged | **60 / 60**, zero judge failures, zero errors |
| mean rubric points | **4.291 / 10** |
| median / min / max | 4.250 / 0.0 / 10.0 |
| across-task sd | **2.795** |
| pass@≥7 | **13 / 60 = 21.7%**, binomial se 5.3 pp |
| chemistry | mean 5.044, passed 6/20 |
| biology | mean 4.801, passed 5/20 |
| physics | mean 3.028, passed 2/20 |
| answer latency | mean 120.1 s, median 115.9 s, longest 290.1 s |

(Three constants in the code quoted an answer latency of 134.5 s until they were reconciled
against this table. That figure was the mean over an earlier balanced twenty-one-task draw. It
survives only where a sentence marks it superseded, and a gate refuses it anywhere else.)

### The corroboration, stated carefully

The paper reports Claude Opus 4.5 at **17.5%** on FrontierScience-Research, over sixty tasks at
thirty trials each, under a **GPT-5** judge. This harness gets 21.7% under **gpt-5.1** at one
draw each — a 4.2-point difference against a 5.3-point standard error. Separately, the paper
reports that on the Research set models do best on chemistry, then biology, then physics, and
this harness reproduces that ordering exactly (5.044 / 4.801 / 3.028).

**That is corroboration of the scoring path, not comparability of the instruments**, and the
distinction has to be restated every time the two numbers appear near each other. The judge is
not the paper's judge, each task here is one draw rather than thirty, and judge choice is worth
more on this kind of measurement than the whole difference being discussed. What the agreement
buys is narrower and worth having anyway: every other check on the scoring path is internal —
the prompt matches a fixture this repository wrote, the verdicts match responses this
repository recorded — so a prompt, a reader or a refusal rule that was quietly wrong would fail
all of them together and none of them visibly. An externally published number is the one oracle
here that was not produced by the same machine, and a broken path does not land inside one
standard error of it *and* reproduce its subject ordering by accident.

**No total from this harness may be placed beside the paper's table.**

---

## What is not measured

Two blanks, and they have one cause.

| | |
| --- | --- |
| AutoR's score on FrontierScience-Research | **UNMEASURED** |
| AutoR's wall clock on FrontierScience-Research | **UNMEASURED** |

No real — non-`--fake-operator` — AutoR run of this benchmark exists. The mechanics are known to
work: handed a real FrontierScience problem as its goal file, `main.py` walked all eight stages
under the fake operator and exited 0 in 9.6 s, and `rcb_agent.py` pointed at a workspace holding
nothing but an instructions file exited 0 in 7.8 s (auto-skipping Stage 07, whose figure floor a
text answer cannot clear — which is the observation the `ideate` profile is built around).
Everything in this document that is not those two rows was reachable without spending a real
pipeline run.

The cause is one part of AutoR's own long-standing code: `ClaudeOperator._build_cli_command`
always renders the pair `--permission-mode bypassPermissions` and
`--dangerously-skip-permissions`, and the agent harness this work was done under refuses to
launch a process carrying them. Nothing was added for this benchmark and nothing about the
adapter can route around it — it is the only thing standing between this page and the two rows
above.

**The exact command that fills the blank**, run by a human with the authority to run it:

```bash
export FRONTIERSCIENCE_DATASET=/abs/path/to/research_test.jsonl

python3 fs_agent.py \
    --task fs:043 \
    --profile ideate \
    --model opus --review-model opus \
    --answer-guidance minimal \
    --stage-timeout 3600 --max-attempts 2 --max-auto-skips 0 \
    --workspace ~/fs-runs/fs043_ideate_001

python3 tools/score_fs_run.py \
    --task fs:043 \
    --answer ~/fs-runs/fs043_ideate_001/answer.md \
    --answer-meta ~/fs-runs/fs043_ideate_001/_meta.json \
    --out ~/fs-runs/fs043_ideate_001.score.json
```

Three of those defaults are load-bearing and are the defaults of `fs_agent.py` rather than of
`main.py`. `DEFAULT_FS_STAGE_TIMEOUT` is 3,600 s, three times the interactive default: the only
per-stage wall clock ever recorded on this box for a comparable configuration was 2,100 s, and
a sibling trial run at 1,800 s had twenty-eight of forty arms hit the ceiling. A timeout below
the distribution does not slow the treatment arm down, it converts it into a refusal, and a
refusal rate that differs between arms is not a difference anybody can interpret.
`DEFAULT_FS_MAX_ATTEMPTS` is 2 where `main.py` is unbounded — the stuck detector only fires on
three *identical* consecutive validation errors, and artifact errors carry filenames and
counts, so an unbounded budget is unbounded; a real sibling run reached attempt nine on one
stage. `DEFAULT_FS_MAX_AUTO_SKIPS` is 0, because an auto-skipped Stage 02 in a run whose only
stage is Stage 02 is a run that produced nothing while reporting that it finished.

### The cost estimate, framed as an estimate

Judging is the only measured cost: at a mean of 72.9 s per serial call, sixty tasks by two arms
at one draw each is about 2.4 hours.

For the answer side there is no measurement, only a neighbour. Thirty-nine real
ResearchClawBench runs on this box had a **median wall clock of 15.2 h** (p25 11.9, p75 19.4,
max 26.5), and 31 of 40 auto-skipped at least one stage. That is a *different benchmark*: eight
stages against the one this configuration runs, with experiments and a written report at the
end. It is an upper anchor and a warning about variance, not a schedule. The retry mechanics
behind that variance are also measured: one 10.2-hour run spent 3/3/3/6/5/9/4 attempts across
its stages, roughly 65 backend calls against a 16-call floor.

The plan file is where a projection would most easily be read as an observation, so
`_refuse_a_budget_nobody_measured` requires every plan with an `autor` arm to carry a
`cost_note` containing the word `UNMEASURED`. It deliberately does not check that the note is
*true*, which nothing can check; it checks for the one word whose absence lets a schedule read
like a measurement, and it goes away by itself the day somebody measures the arm and rewrites
the note.

---

## The paired trial

`configs/fs_trial_001.json` is the shipped plan. `tools/fs_trial.py` runs it; `src/fs_trial.py`
decides everything.

### The arms

An **arm is an answer producer**, not a git revision. The sibling trial compares two checkouts
of AutoR running one entry point, so an arm is a commit and the revision check is the whole of
arm identity. Here one arm is a pipeline in a worktree at a commit and the other is a single
call to a model, with no worktree and no commit at all — so `FsArmSpec` carries `kind`, `model`
and `answer_guidance` for both and `worktree`/`sha`/`review_model`/`profile` only for the
`autor` side.

| | control | treatment |
| --- | --- | --- |
| label | `direct-opus` | `<sha>-autor-ideate` |
| kind | `direct` | `autor` |
| model | `opus` | `opus` (reviewing with `opus`) |
| guidance | `minimal` | `minimal` |
| profile | — | `ideate` |
| approved stages | none | exactly `02_hypothesis_generation` |

`_refuse_a_label_that_is_not_the_producer` runs at **freeze** time, and the timing is the whole
lesson. An arm carries its producer twice — for an `autor` arm as `sha` and as `label`, and
only the label reaches the admission gate — so a plan reading `{"label": "off", "sha": "…"}`,
which is the obvious way to write an on/off trial, is accepted, launched, and then has every
single arm refused after the runs are spent. That happened on the sibling benchmark: twelve
runs, twelve refusals, zero pairs, and a report whose exclusion lines named the clause but not
the cause. The relation checked at freeze is exactly the one the clause applies later, so a
plan that freezes cannot fail admission on this ground.

The same freeze-time pass refuses two arms with the same label, an empty or duplicated task
list, a key that is not `fs:NNN`, a task instruction whose digest is not this tree's, two arms
naming different answer models, two arms given different guidance, and the out-of-range
parameters. Each of those is otherwise discovered at report time, after the trial has been paid
for, under the message "the two arms measured no stage in common".

### The environment digest

`FsRunEnvironment` carries nine fields. Eight are **observed off the artifacts** rather than
copied from the plan — a field filled from the plan agrees by construction and is therefore not
the field the contract names. They are: `dataset_sha256`, `judge_model`,
`judge_reasoning_effort`, `answer_model`, `answer_guidance`, `task_instruction_sha256`,
`disallowed_tools` and `judge_replicates`.

The ninth, `answer_attempts`, is not observed and never was: it is the literal `1`. Rather than
let a constant sit in a list whose stated property is that nothing in it is a constant, the
freeze refuses any plan declaring another value, and both the field and the record that fills
it say so. A driver that produced one evidence per run while accepting `answer_attempts: 3`
would spend the whole plan before disclosing that it had pooled nothing.

The digest is folded into the single `stage_fitness` key, `"<task_key>|<digest[:12]>"`, so a
pair whose two arms were measured in different environments dies on `collect_pairs`' existing
exclusion — no new gate to write, and therefore no new gate to get wrong.
`describe_difference` then replaces the generic exclusion line with the field that did it, and
`collect_fs_pairs` raises rather than publishing if the gate and the explanation ever go out of
step.

`judge_replicates` is a plan-level constant today, equal across the arms by construction, and
it is recorded anyway — it is the field an adaptive re-judge would move. That feature is
deliberately absent and the module says why: promoting one arm of a pair to more draws empties
the pair's shared-stage intersection and drops it, silently, and the pairs it would drop are
exactly the ones nearest the threshold that a reader most wants.

### The ten admission clauses

Each clause refuses a **pair**, not an arm. Refusing one arm renders as "there was no treatment
arm", which hides the cause; and the ledger prints every clause at its count even when the
count is zero, because a clause that has stopped firing because a metadata field was renamed
looks exactly like a clause nobody violated.

| Clause | What it reads | Why a pair dies on it |
| --- | --- | --- |
| `meta_status_completed` | `_meta.status` | computed from the six exit clauses rather than handed in; 39 of 40 sibling runs wrote `completed` while a fifth had skipped the scored stage |
| `pipeline_completed` | `_meta.pipeline_completed` | a second, independent witness: the deliverable router returns false when the final stage is the one already reached, aborting with `auto_skipped_stages` still empty |
| `stages_approved_exactly` | `_meta.stages_approved` | one value per arm kind, exactly — one stage for `autor`, none for `direct`. This separates a synthesized answer from an answer synthesized out of nothing, and it stands in for the composition declaration the sibling trial makes |
| `answer_not_fallback` | `_meta.answer_source` **and** the answer's first line | two witnesses, because one of them is written by the party the gate constrains; a sibling run killed by quota exported a fallback and was scored as an attempt worth about 7.5 points of nothing |
| `no_auto_skips` | `_meta.auto_skipped_stages` | 77.5% of forty sibling runs skipped a stage and the field appeared in none of their metadata |
| `answer_within_bounds` | `answer_chars` and the content refusals | the floor is low because an 800-character correct derivation is a complete answer; the content refusal is what keeps a 250-character "I will do this in three steps" out, since it clears any length check and is then scored as a wrong answer rather than as no answer |
| `answer_not_truncated` | `stop_reason` on the Claude path, `status`/`incomplete_details` on the Responses path | the two backends say it in different places, and a reader that knows one reports a truncated answer as a whole one; a backend recording neither is refused rather than admitted |
| `no_browsing` | `browsing_tool_calls`, for **both** arms | the published protocol is no browsing, and the non-repair operator path passes no tool restriction unless one is asked for, so "the direct arm structurally cannot browse" is false. A null witness refuses |
| `producer_matches_arm` | recorded model both kinds; plus HEAD at launch and at finish, cleanliness and label/sha prefix match for `autor` | the metadata records no SHA, so the label is the only carrier of the revision that reaches the gate |
| `every_draw_judged` | judge failures, draw count, draws requested | a failed draw recorded as a zero is indistinguishable from a genuinely worthless answer here, and on the sibling benchmark that confusion published a run's honest 37.0 as 19.5 |

Refusals the driver makes before the gate can see a run — a watchdog kill, a crash, a fallback
answer, a scorer refusal — arrive in the same ledger under a `driver:` prefix, because they
lose the reader the same thing: a pair.

### The publication ceiling

`FS_MAX_REFUSAL_RATE` is 0.20. Above that share of refused runs **in either arm**, the report
withholds the paired difference, the per-arm means and the pass rates, and publishes only the
refusal rates.

Refusals are not random with respect to arm. The pipeline arm can be refused for a stage
timeout, an auto-skipped stage or a synthesized answer; the single-call arm structurally cannot
be refused for any of the three. The survivors are then the subset of tasks on which the
pipeline happened to run cleanly — a sample of its easier questions — and the difference over
them is biased upward by an unknown amount. Withheld rather than printed with a warning, on
purpose: a reader who sees a signed number takes it, and a caveat underneath does not undo
that.

The dry run with a `browse` fault injected into the treatment arm produced exactly that
outcome: control 0 refused / 6 admitted, treatment 6 refused / 0 admitted, `no_browsing` at 6
in the clause table, and no difference printed.

### Fifty-nine questions, not sixty

`fold_duplicate_rows` collapses the byte-identical rows 6 and 11 into one pair whose difference
is the mean of the two members' differences — which is the same number as the difference of the
two arms' means over them, an identity that only holds when both arms contributed the same
members. A member admitted for one arm and refused for the other is therefore dropped from both
and named in the exclusion lines; averaging a two-run arm against a one-run arm would be a
different estimator wearing this one's label.

The fold runs **after** admission, never before, so a refused member cannot be laundered into a
mean it was excluded from. `FsTrial.folded_away` keeps the fold out of the interim banner's
attrition count, so a complete trial does not report "59 of 60" as though something had gone
wrong.

This is a declared difference from the paper's sixty-row population, and the report says so
where it happens: two answers to one question are not two independent observations under the
sign-flip null.

### What the report prints, and what it refuses to

Section order is an argument. Provenance first, with both arms described in full, the dataset
digest, the plan digest, the instruction digest and the sign-flip seed — and with the judge and
dataset **observed off the score files and printed against the plan's declaration**, so a
dropped model flag cannot score a whole trial with a judge nobody chose while the header reads
correct. The non-comparability banner is second, so a reader who stops after the headline has
met it. The refusal ledger is third, above any total. The publication gate sits between the
ledger and the difference, so a difference that must not be published is not printed and then
withdrawn.

Then the difference itself, from `format_trial_report`: pairs, the outcome key and what
measured it, the mean difference in rubric points, win/loss/tie, the two-sided sign-flip p
beside the smallest p its estimator could reach, and the `underpowered` label below
`MIN_PAIRS_FOR_SIGNIFICANCE` pairs. The test is exact by enumeration up to `MAX_EXACT_PAIRS`
and a seeded sample of `SAMPLED_SIGN_ASSIGNMENTS` sign assignments above it, with the seed
printed.

Then the published numbers: each arm's mean over the paired population, the paired difference,
the observed sd of the differences with the minimum effect the sample could detect at 80% power
against the declared `minimum_effect_of_interest`, pass@≥7 with a Wilson interval for each arm,
a per-subject table of mean differences and pair counts, and a cost table — admitted runs,
backend calls, output tokens and median wall clock per arm. The cost columns sit beside the
score and never inside it: a win that arrived with an eight-fold token bill has to be named as
one.

Five things the report **refuses** to print, each absence a decision:

- **no per-rubric-item table and no concentration figure.** This judge returns one number, and
  its per-item reasoning exists only as prose in a format measured to be unstable across
  responses — one numbered its sections `Item N`, another wrote `Rubric section:` and drilled
  into sub-items. Scraping it would publish a second, unvalidated instrument beside a validated
  one, so `criterion_fitness` is empty by construction and the report says so where the table
  would have been;
- **no per-subject pass rate.** At twenty tasks a subject's pass proportion carries a binomial
  sd of about nine percentage points, larger than anything the trial is powered for, and
  printed beside a mean it would read as the same kind of measurement;
- **no spread of 0.00 from a single draw**;
- **no score taken while the trial was in flight** — every published total comes from one
  continuous final pass with one judge, which is the only arrangement under which the first
  task's total and the last task's were produced by the same instrument;
- **no pair whose two arms `compare_fs_arms` can tell apart.** That raises rather than
  publishing. The raise is over cross-arm confounds only, and the distinction is load-bearing:
  after the duplicate-row fold a surviving pair carries the group's key, which is also one
  member's own key, so a refusal filed against that member is not a confound reaching the
  difference. Conflating the two turned an ordinary refusal into an `AssertionError` that
  blamed the environment digest and produced no report at all.

The report ends with an upper bound on its own claim: what it measures is the difference
between these two named arms, under this judge, over this many distinct questions, with
browsing denied to both and the answer graded afterwards against a rubric no stage was shown.
It is not a measurement of AutoR's capability — that is a pipeline of eight stages of which
this configuration runs one — it is not a state-of-the-art figure, and it is not comparable to
the paper's table.

### The state machine

`next_actions` is the whole recovery policy as a pure function of the state directory, because
the alternative is validating multi-day kill-and-restart behaviour by spending multi-day
kill-and-restart wall clock. Four decisions differ from the sibling driver: a live `launched`
run consumes concurrency budget instead of aborting the trial (the lock has already refused a
second live driver, so a live child is this trial's child); a `launched` run whose pid is gone
is **abandoned and never resumed**, into a fresh workspace, because adopting a half-finished
workspace means scoring an answer nobody can say was finished; `fallback` and `incomplete` are
**refused, not retried**, because the run ran and produced a non-run; and there is no scoring
action in the loop at all.

State is written three times per run — before the child exists, with its pid, and after it
exits with the harvest — through a temporary file and `os.replace`, because the state directory
is on shared NFS. There is no per-run wall clock, only a stall watchdog on the raw log's mtime
(`FS_STALL_SECONDS`) and a trial deadline after which no *new* run starts: with a real
distribution running from 11.9 to 26.5 hours, any cap short enough to catch a hang is short
enough to kill a run that was going to finish. The watchdog kills a process group and never
reaches for a pattern-matching kill, and it accepts that a grandchild may survive — in which
case that workspace is void rather than trusted.

Workspace names carry microseconds (`fs_workspace_name`) and are created with
`exist_ok=False`. The sibling trial named workspaces to the second with `exist_ok=True`, two
arms of one task launched inside the same second landed in one directory, overwrote each
other's deliverable, and produced a paired difference of exactly zero — a null result
manufactured by a filename.

A dry run still needs the treatment arm's checkout on disk, and `run` says so before it takes
the lock: `missing_worktrees` names every `autor` arm whose directory is absent and refuses.
`operator: "fake"` fabricates the operator and the judge and nothing else — each child's working
directory is still the arm's worktree, and `producer_matches_arm` compares a real `git rev-parse`
against the arm's label. The check lives at `run` rather than at freeze on purpose: a plan is a
value that `report` also loads, and a filesystem probe at freeze would make rebuilding last
month's report depend on a checkout since deleted. Before the refusal existed this was a bare
`FileNotFoundError` out of `Popen`, after the lock was taken.

---

## Reading a result honestly

Five questions, in this order, before quoting any number from this page or from a report it
produced.

1. **Which judge?** Every total here is `gpt-5.1`. The paper's is GPT-5. Judge choice was
   measured to move a total on identical artifacts by about sixteen points on the sibling
   benchmark, which is larger than any effect these trials are looking for. A number quoted
   without its judge is not a smaller claim, it is an incomparable one.
2. **How many draws, of what?** One judge draw per answer carries about ±0.33 points of
   sampling noise — measured at scores of 2.5 and 3.3, and **unmeasured at 7**. One answer per
   (task, arm) carries the answer producer's own run-to-run variance, of which there are
   **zero** observations, and which is very likely the larger of the two. A difference that
   exceeds the judge's band means *the judge cannot explain it*, never *the treatment explains
   it*.
3. **What was the refusal rate, per arm?** It is printed for both arms whether or not anything
   was refused. Lopsided refusals are a trial's result, not a footnote to one, and above 20% in
   either arm the difference is withheld rather than caveated.
4. **Did the arms differ in more than one thing?** The nine environment fields are observed off
   the artifacts, folded into the pair key, and diffed by name in the exclusion lines. Read
   them. `--answer-guidance coverage` in particular is an intervention, not a setting: applied
   to one arm it *is* the thing being measured.
5. **Is this being placed beside the paper's table?** It must not be. The harness agreeing with
   a published figure inside one standard error, and reproducing its subject ordering, is
   evidence that the scoring path is sound. It is not evidence that the two numbers are the
   same measurement, and no amount of agreement can make a different judge into the same
   instrument.

And the two rows that no reading fixes: **AutoR's own score and wall clock on this benchmark
are UNMEASURED.** Every treatment-arm number produced so far is a property of the fake
operator.

---

## See also

- [ResearchClawBench](researchclawbench.md) — the sibling benchmark, its adapter, its export
  contract and its own paired trial.
- [ResearchClawBench Landscape](researchclawbench-landscape.md) — how other agents score there,
  and the baseline any result has to be quoted against.
- [CLI Reference](cli-reference.md) — every flag on `fs_agent.py`, `tools/score_fs_run.py` and
  `tools/fs_trial.py`.
- [Configuration](configuration.md) — the hard-coded limits this adapter adds.
