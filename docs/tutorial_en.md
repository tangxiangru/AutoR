# AutoR User Guide

> This guide is for first-time AutoR users.
>
> The goal is not just to make the command run. The goal is to help you understand how to install AutoR, how to use it correctly, how to supervise each stage so outputs do not stay toy-level, and how to get to a strong final PDF as quickly as possible.

## 1. AutoR in One Sentence

AutoR is not a black-box paper generator, and it is not a chat demo that writes a few research paragraphs.

The more accurate description is:

- a **human-centered** research harness
- a **research loop** built on top of a lower-level coding agent
- a **run-based** system that writes prompts, logs, code, data, figures, writing sources, and outputs to disk

The most important principle is simple:

**AI handles execution. Humans own the direction.**

So when you use AutoR, the highest-leverage thing is not pressing Enter once. It is:

- reviewing every stage carefully
- asking AutoR to redo work when outputs are still toy, incomplete, or weak
- refusing to approve a stage until it is actually useful for the next stage

If you use that loop well, AutoR becomes much stronger.

---

## 2. What AutoR Can Do

The current mainline is built for these workflows:

- start from a concrete research goal
- move through a fixed multi-stage research pipeline
- call a real execution backend at every stage
- write prompts, logs, stage summaries, code, data, figures, writing sources, and PDFs to `runs/<run_id>/`
- resume an existing run
- redo from a specific stage
- roll back to an earlier stage and invalidate downstream work
- start from an existing project repository
- start from your own prior paper corpus
- organize Stage 07 writing around a target venue profile
- support literature organization, citation verification, experiment manifests, artifact indexing, and packaging

The current execution backends are:

- `claude`
- `codex`

AutoR is the higher-level research loop. It is not trying to replace the underlying coding agent.

### 2.1 Recent Updates You Should Know

Several recent mainline changes matter for real use:

- `00_intake` now has a dedicated clarification flow. The first intake pass asks questions one by one; each question can be answered with a model-proposed option, a custom answer, or skip. The revised pass then shows a compact intake brief instead of treating those questions as normal suggestions.
- The terminal UI is better suited for real runs and recordings: panel body rows keep colored borders, long lines, long paths, and wide characters wrap inside the frame, and Stage 0 plus approval menus support keyboard navigation.
- The Codex backend now uses the current Codex CLI `--sandbox workspace-write` execution flag, so it should not emit the deprecated Codex CLI `--full-auto` warning. This is separate from AutoR's own `--full-auto` approval mode.
- If a Codex-backed run needs remote SSH / GPU execution, you can explicitly use `--codex-sandbox danger-full-access`. The default remains the safer `workspace-write`; do not use unrestricted mode by default.
- AutoR's `--full-auto` still means automated approval: a strict reviewer agent replaces the waiting human gate, while the 9-stage research workflow itself stays unchanged.

---

## 3. What You Need Before Installation

Recommended environment:

| Item | Required | Notes |
| --- | --- | --- |
| Python 3.10+ | Required | AutoR runs through `python main.py` |
| Git | Required | Needed to clone the repository |
| Node.js 18+ | Strongly recommended | Claude Code officially requires Node 18+, and Codex CLI is also installed via npm |
| Claude Code or Codex CLI | Required for real runs | You need at least one execution backend |
| TeX toolchain | Optional but recommended | Helps Stage 07 produce stable compilable PDFs |
| `PyMuPDF` | Optional | Recommended if you use `--paper-corpus` and want PDF text extraction |
| `google-genai` / `Pillow` / `PyYAML` | Optional | Only needed for `--research-diagram` |

Platform notes:

- macOS / Linux is the easiest path
- on Windows, WSL is strongly recommended

---

## 4. Step One: Install the Execution Backend First

Do not think of the workflow as "install AutoR first, then install the agent."

The more practical order is:

1. install `Codex` or `Claude Code`
2. then let that tool help you install and use AutoR

### 4.1 Install Codex

According to OpenAI's official documentation, the Codex CLI can be installed with npm:

```bash
npm install -g @openai/codex
```

If global npm permissions are broken on your machine, fix your Node / npm setup instead of forcing it with `sudo`.

Common authentication paths:

Option A: sign in

```bash
codex --login
```

Option B: use an API key

```bash
export OPENAI_API_KEY="your OpenAI API key"
```

Check that installation worked:

```bash
codex --version
```

If you already have an eligible ChatGPT plan, you can also follow the official sign-in flow.

### 4.2 Install Claude Code

According to Anthropic's official documentation, the standard install command is:

```bash
npm install -g @anthropic-ai/claude-code
```

If you hit permission issues, fix npm permissions instead of using `sudo npm install -g`.

Then verify the environment:

```bash
claude doctor
```

Then run it once to complete sign-in or authentication:

```bash
claude
```

Claude Code supports multiple auth sources, including:

- Claude App / Claude.ai
- Anthropic Console
- Amazon Bedrock
- Google Vertex AI

### 4.3 Official Docs

If backend installation goes wrong, check the official docs first:

- Codex CLI: <https://help.openai.com/en/articles/11096431>
- Codex access and sign-in: <https://help.openai.com/en/articles/11369540-icodex-in-chatgpt>
- Claude Code setup: <https://docs.anthropic.com/en/docs/claude-code/setup>

---

## 5. Step Two: Let Codex or Claude Code Install AutoR for You

This is the most practical way to get started.

Go to the parent directory where you want AutoR to live, then start your preferred backend:

```bash
codex
```

or:

```bash
claude
```

Then give it something like this:

```text
Please install AutoR in the current directory:
1. clone https://github.com/AutoX-AI-Labs/AutoR.git
2. enter the repo and read the README plus python main.py --help
3. create a Python virtual environment if needed
4. install the minimum dependencies required to run the current repo
5. run one smoke test: python main.py --fake-operator --goal "UI smoke test"
6. tell me the minimal command for a real run
Do not modify the main logic and do not do unrelated refactors.
```

Why this is useful:

- you do not need to understand the full repo first
- the backend can inspect your environment and spot missing tools
- it can help you get the minimal runnable path working faster

### 5.1 Manual Setup as a Fallback

If you prefer to do it manually:

```bash
git clone https://github.com/AutoX-AI-Labs/AutoR.git
cd AutoR
python main.py --help
```

The current mainline is not designed around "first install a huge requirements file, then run."

The core path is:

- clone the repo
- make sure the backend exists
- run `python main.py`

If you want optional enhancements, install only what you need:

```bash
pip install pymupdf
pip install google-genai pillow pyyaml
```

Where:

- `pymupdf` is for `--paper-corpus`
- `google-genai pillow pyyaml` is for `--research-diagram`

---

## 6. Step Three: Most Users Should Start with `python main.py`

For most real users, the best daily usage pattern is not to begin with a long command full of flags.

It is:

```bash
python main.py
```

Then you respond to the prompts inside the terminal.

That is the right default because AutoR is terminal-first and human-in-the-loop by design. In real use, many important decisions happen through:

- how you phrase the research goal
- whether you add existing resources
- how you review each stage
- how you ask for refinement inside the approval menu

So if you are new, or if you want a natural human-in-the-loop workflow instead of a scripted batch run, **start with plain `python main.py`**.

### 6.1 What Happens in Interactive Mode

When you run:

```bash
python main.py
```

AutoR will:

- ask you to enter the research goal directly in the terminal
- accept multi-line input
- ask whether you want to include existing resources before intake starts

This is very beginner-friendly because you do not need to memorize flags first.

One useful detail that is easy to miss:

- resources do not have to come only from `--resources`
- in interactive mode, you can enter files or directories one by one
- you can also attach a short description to each resource

That makes the first run much easier.

### 6.2 When to Switch to Explicit Flags

Once you already know the workflow, explicit flags become more useful when you want to:

- fix the backend, model, or venue in advance
- reproduce a run
- launch repeated runs
- call AutoR from scripts

So the rule of thumb is:

- for daily human use, interactive mode is usually the better default
- for reproducibility and automation, explicit flags are more convenient

### 6.3 Optional: Run a Smoke Test First

If you want to validate the local CLI path without using a real backend, run:

```bash
python main.py --fake-operator --goal "UI smoke test"
```

You should see:

- the startup banner
- stage panels
- structured terminal output
- the approval menu after each stage
- a complete `runs/<run_id>/` directory

But be careful:

**`--fake-operator` is only for smoke tests and demos. It does not prove real research quality.**

Its purpose is only to check:

- whether the CLI works
- whether the directory structure is created correctly
- whether the approval loop behaves correctly

Do not mistake a smoke test for a real research run.

### 6.4 Optional: Use AutoR Studio in the Browser

If you prefer approving stages, reading the paper, and watching progress from a browser, you can use **AutoR Studio** instead of staying in the terminal the whole time.

Start it with:

```bash
python studio.py
```

Then open:

```text
http://127.0.0.1:8000/studio/
```

Studio is useful when you want to:

- review stage outputs in a browser instead of a terminal panel
- approve or send feedback with a clearer visual workflow
- inspect the paper, LaTeX sources, and build log in one place
- browse version history and session traces during a long run
- record a cleaner demo than a pure terminal session

The most important thing to understand is that **Studio is not a separate workflow**.

It uses the same run directories, the same stage summaries, the same manifests, and the same artifact layout under `runs/<run_id>/`. In other words:

- terminal mode and Studio are two interfaces over the same research system
- the browser UI does not create a second hidden project format
- what you see in Studio should still exist on disk in the run directory

Current limitation:

- Studio is currently **Claude-backed**
- the terminal workflow supports both `claude` and `codex`
- so if you need Codex today, use `python main.py`

Good rule of thumb:

- use `python main.py` when you want the most direct, scriptable, backend-flexible workflow
- use `python studio.py` when you want a more visual approval, review, and demo experience

---

## 7. Step Four: Use Explicit Flags When You Need Fixed Configuration

### 7.1 Minimal Explicit Commands

If you use Claude:

```bash
python main.py \
  --operator claude \
  --model sonnet \
  --goal "Study whether retrieval-augmented chain-of-thought improves factual QA under a fixed token budget, and produce a submission-style PDF."
```

If you use Codex:

```bash
python main.py \
  --operator codex \
  --model default \
  --goal "Study whether retrieval-augmented chain-of-thought improves factual QA under a fixed token budget, and produce a submission-style PDF."
```

If your Codex-backed run needs to submit remote GPU jobs through SSH, for example after you have manually verified `ssh gpu-server "hostname && nvidia-smi"`, explicitly relax the Codex sandbox:

```bash
python main.py \
  --operator codex \
  --codex-sandbox danger-full-access \
  --goal "Run the planned experiments on the remote GPU server and produce a submission-style PDF."
```

This gives the Codex backend unrestricted local and remote execution ability. Use it only for trusted tasks where remote execution is intentional.

Useful defaults to remember:

- for a new run, if you omit `--operator`, AutoR defaults to `claude`
- for a new run, Claude defaults to `sonnet` and Codex defaults to `default`
- when resuming a run, AutoR preserves the existing backend, model, and venue unless you explicitly override them

If you want a fully unattended approval path, you can enable the automated reviewer gate:

```bash
python main.py \
  --operator claude \
  --model sonnet \
  --full-auto \
  --goal "..."
```

You can also separate the execution backend from the reviewer backend:

```bash
python main.py \
  --operator codex \
  --model default \
  --full-auto \
  --review-operator claude \
  --review-model opus \
  --goal "..."
```

Two boundaries matter here:

- `--full-auto` does **not** change the main research pipeline; it only swaps the manual approval gate for a strict reviewer agent
- for serious research work, the default human-reviewed mode is still the recommended path; `--full-auto` is more useful for unattended sweeps, overnight dry runs, or pipeline pressure tests

### 7.2 Choose the Venue Early

If you already know the target writing style, set the venue from the beginning:

```bash
python main.py \
  --operator claude \
  --model sonnet \
  --venue neurips_2025 \
  --goal "..."
```

or:

```bash
python main.py \
  --operator codex \
  --model default \
  --venue jmlr \
  --goal "..."
```

Common venue profiles include:

- `neurips_2025`
- `neurips_2026`
- `iclr_2026`
- `icml_2026`
- `cvpr_2026`
- `acl_2026`
- `aaai_2026`
- `ieee_journal`
- `ieee_conference`
- `nature`
- `nature_communications`
- `jmlr`

See the full list in [../templates/registry.yaml](../templates/registry.yaml).

Notes:

- if you do not specify `--venue`, the default is `neurips_2025`
- AutoR uses the venue profile to shape Stage 07 writing and packaging
- this does not mean the repo vendors the complete official submission system for that venue

### 7.3 Strongly Prefer Starting with Resources

If you already have papers, BibTeX, data, code, or notes, do not start from a blank slate if you can avoid it.

```bash
python main.py \
  --operator claude \
  --model sonnet \
  --venue neurips_2025 \
  --goal "Evaluate whether small MoE routing changes improve training stability without increasing parameter count." \
  --resources papers/key_paper_1.pdf papers/key_paper_2.pdf refs.bib data/baseline.csv notes/ideas.md
```

Good candidates for `--resources`:

- PDF papers
- `.bib` / `.bibtex`
- data files
- code directories
- experiment notes
- any pre-existing related material

This is one of the fastest ways to improve output quality.

One more practical detail:

**`--resources` accepts directories as well as individual files.**

So if you already have a small code repo, a data folder, or a bundle of reading materials, you can ingest the whole thing instead of splitting it manually.

### 7.4 If You Need to Teach AutoR a Specific "Skill"

In real usage, this happens often:

- your lab has its own GPU submission flow such as `rjob`
- you have a fixed data preprocessing pipeline
- you have internal benchmark rules
- you have a standard paper organization style, output layout, or naming convention

The key principle is:

**do not try to teach that skill with a single sentence. Turn it into an executable playbook.**

The most effective pattern is to package that skill as resources and give those resources to AutoR:

- a written guide, such as `rjob_guide.md`
- one or more command templates or scripts, such as `submit_rjob.sh`
- a known-good example config
- environment notes, such as conda environments, module loads, data paths, and output paths
- one real successful log or result example

In other words, what you should give AutoR is not a vague instruction. It is a combination of:

- rules
- examples
- templates
- successful cases

### 7.5 When to Provide Those Skill Resources

There are three especially practical ways to do it:

1. start with `python main.py` and add those files or directories during the interactive resource import step
2. pass the playbook directory through `--resources`
3. if the workflow is part of a long-lived project, keep it in the repo and use `--project-root`

If you expect to reuse the same operational knowledge repeatedly, a stable directory layout is usually best. For example:

```text
lab_playbooks/
  rjob/
  slurm/
  data_prep/
  eval_rules/
```

Then include the relevant directory in each run.

### 7.6 Resources Alone Are Not Enough: Put Hard Constraints in the Goal

If some rules are mandatory, do not rely on AutoR to infer them implicitly.

State them directly in the goal or in approval feedback.

For example:

```text
Use the provided rjob workflow for all non-trivial training and evaluation.
Local runs are only allowed for smoke tests under 5 minutes.
All real experiments must be submitted through rjob to GPU nodes.
Save job scripts, job IDs, logs, and machine-readable results into the run workspace.
```

This works well because it explicitly defines:

- what must happen
- what must not happen
- what acceptable artifacts look like

### 7.7 Where to Check Whether AutoR Actually Learned It

This kind of skill is best enforced at a few specific stages:

- `00_intake`: did it actually understand the workflow and constraints
- `03_study_design`: did the design encode that workflow correctly
- `04_implementation`: did it write reusable scripts, configs, and execution instructions
- `05_experimentation`: did it actually follow the workflow instead of quietly doing local-only experiments

Using `rjob` as an example, by Stage 04 or 05 you should ideally see:

- reusable submission scripts
- real job configs
- job IDs or submission records
- execution logs
- machine-readable result files

If those are missing, approval is usually premature.

### 7.8 A Practical Refinement Prompt for This Case

If AutoR failed to follow the cluster workflow you gave it, you can use feedback like this:

```text
Do not continue with local-only experiments.
Use the provided rjob workflow to submit real GPU jobs.
Create reusable submission scripts and save the submit command, job config, job IDs, logs, and machine-readable results under workspace/code and workspace/results.
Local execution is only for smoke tests.
```

### 7.9 What Usually Does Not Work

These approaches are usually too weak:

- saying only "please learn rjob"
- giving a single command with no context
- saying only "use GPU" without specifying submission flow, output locations, or success criteria
- failing to check, during approval, whether the workflow was actually followed

The short version is:

**if you want AutoR to learn a skill, package that skill as executable resources and then enforce it through human approval at the critical stages.**

---

## 8. How AutoR Runs

The typical pipeline is:

0. `00_intake` (optional)
1. `01_literature_survey`
2. `02_hypothesis_generation`
3. `03_study_design`
4. `04_implementation`
5. `05_experimentation`
6. `06_analysis`
7. `07_writing`
8. `08_dissemination`

In practice, that is **1 intake stage + 8 formal research stages = 9 stages**.

| Stage | What it does | What you should check |
| --- | --- | --- |
| `00_intake` | Aligns the goal, resources, constraints, evaluation direction, and target writing style before formal research begins. | Answer the clarification questions, add hard constraints, and confirm the problem is narrow enough to execute. |
| `01_literature_survey` | Organizes related work, task background, benchmarks, baselines, and the real research gap. | Do not accept shallow paper lists; look for structured literature files, comparisons, and evidence ledgers. |
| `02_hypothesis_generation` | Converts the direction into testable hypotheses and provisional paper claims. | Make sure it converges to a falsifiable main line instead of continuing to brainstorm. |
| `03_study_design` | Turns the hypothesis into an executable experimental design. | Check datasets, metrics, baselines, ablations, budgets, seeds, failure criteria, and data artifacts. |
| `04_implementation` | Builds real code, configs, data-prep scripts, and sanity checks. | Do not approve skeletons; require runnable scripts, commands, configs, and logs. |
| `05_experimentation` | Runs the planned experiments and writes machine-readable results. | Distinguish smoke tests from real experiments; require baselines, repeats, result files, and failure records. |
| `06_analysis` | Interprets results, creates figures, analyzes failures, and explains mechanisms. | Do not accept metric narration only; require plots, failure cases, ablation interpretation, and boundaries. |
| `07_writing` | Produces venue-aware paper sources, BibTeX, a compiled PDF, and citation checks. | Verify that every major claim is backed by experiments, figures, or literature. |
| `08_dissemination` | Builds review, release, readiness, reproduction, and presentation materials. | Confirm the run can be inspected, reproduced, and shown to others, not just read as a paper. |

The shape of every stage is similar:

1. AutoR builds the stage prompt
2. the execution backend starts working
3. the output is streamed to the terminal
4. the stage ends with a structured stage summary
5. you decide whether to refine or approve

From `01_literature_survey` through `08_dissemination`, the approval menu has 6 actions:

1. use suggestion 1
2. use suggestion 2
3. use suggestion 3
4. refine with your own feedback
5. approve and continue
6. abort

`00_intake` is special:

- the first pass does not ask you to use suggestion 1/2/3; it treats the three items as clarification questions and asks them one by one
- each question supports model-proposed options, a custom answer, or skip
- after the questions, you can still add extra custom guidance
- the second pass regenerates the intake brief and only asks you to refine, approve, or abort

The two most important actions in real use are:

- `4`: give your own feedback
- `5`: approve only when the stage is genuinely ready

Inside the same stage, AutoR tries to continue the same session instead of opening a fresh one every time. That matters because stage refinement is usually incremental.

There is also one especially practical control feature:

when you choose `4` and enter custom feedback, you can also enter control commands directly:

- `/skip`: skip the current stage and continue
- `/back 03`: roll back to an earlier stage such as Stage 03
- `/back 01_literature_survey`: full stage slugs also work

That means:

- the default workflow is still sequential
- but if you intentionally want to bypass the current stage for now, or return to an earlier stage and rebuild from there, you do not have to abandon the whole run

Notes:

- `/back` is for earlier stages, not for jumping forward
- if the current stage exhausts the retry limit, AutoR now also shows a recovery menu so you can directly choose to skip the stage or roll back to an earlier one

There is also one important detail many users miss:

every stage summary includes a `Decision Ledger`.

You can think of it as a running decision record for the current research run. It captures things like:

- which key decisions are now locked
- which open questions are still unresolved
- why the current stage made specific tradeoffs

Those decisions are carried into later stages through handoff summaries, so the ledger is not decorative. It is part of how AutoR keeps the research direction stable over time.

---

## 9. The Most Important Usage Principle: First-Pass Output Is Often Toy-Level

This is the mistake new users make most often.

On the first pass, AutoR may already produce:

- a stage summary
- several files
- sometimes even a PDF

That does **not** mean the stage is ready.

Your default assumption should be:

**The first pass is usually a workable draft, not a strong final answer.**

The following are common reasons **not** to approve:

- it wrote text, but no real data files
- it only ran a smoke test, not a real experiment
- it produced a figure, but not machine-readable results
- it produced a PDF, but the claims are not supported
- it cited a few generic papers, but did not do a real survey
- it described future work instead of actually writing files

You should act like the research lead, not like a spectator.

AutoR's strength is not "perfect on the first pass."

Its strength is:

- the AI clears a large amount of execution work
- the human corrects direction at the high-leverage checkpoints
- 1 to 3 rounds of strong feedback can raise the quality substantially

A useful line to remember:

**Do not approve a stage because it looks completed. Approve it only when it creates real value for the next stage.**

---

## 10. How to Review Each Stage

If you are unsure whether a stage should be approved, use the table below.

| Stage | What you should at least see | Typical toy signal | Example feedback |
| --- | --- | --- | --- |
| `00_intake` | clear goal, constraints, resources, and evaluation direction | it mostly repeats your original prompt | "Narrow the problem to one testable core question and define success criteria, failure criteria, and current resources." |
| `01_literature_survey` | relevant prior work, task framing, datasets/benchmarks, differences, and organized literature files | it lists only a few obvious papers without real comparison | "Expand the survey. Do not only list titles. Organize task setup, core methods, evaluation style, strengths, weaknesses, and write them into the literature directory." |
| `02_hypothesis_generation` | a clear, testable main hypothesis and a few secondary hypotheses | it brainstorms many ideas but never converges | "Stop expanding. Lock one main claim and a small number of measurable hypotheses, and explain why they are worth testing." |
| `03_study_design` | datasets, metrics, baselines, ablations, experiment matrix, budget, failure criteria | it stays conceptual and never becomes executable | "This study design is still too toy. Define baselines, metrics, splits, ablations, statistics, and stopping conditions." |
| `04_implementation` | real code, configs, data prep, sanity checks | it only writes skeleton code or pseudocode | "Do not stop at a skeleton. Make the minimum runnable path real, including scripts, configs, data prep, and sanity checks." |
| `05_experimentation` | machine-readable result files, baseline comparisons, repeated runs, failure records | it runs only a demo or a tiny subset once | "The current experiment looks like a smoke test. Add formal runs, baseline comparisons, repetition, and machine-readable result files." |
| `06_analysis` | real figures, error analysis, failure cases, ablation interpretation, mechanism-level conclusions | it only repeats the best metric | "Do not stop at metric narration. Explain why the method works, where it fails, which factors matter, and support that with figures and tables." |
| `07_writing` | LaTeX, BibTeX, a compilable PDF, citation verification, and a structurally complete draft | it has only markdown, or a weak PDF with unsupported claims | "Do not stop at paper-shaped output. Make sure every core claim is backed by experiments or literature, and complete citation verification." |
| `08_dissemination` | review materials, release/package materials, outward-facing deliverables | it stops at the paper and ignores release/readiness | "Add release and review materials so the run can be checked, reproduced, and shown to others." |

One especially practical lesson:

**Most of the final PDF quality is decided in Stages 03 to 06, not in Stage 07.**

If you are lenient early, Stage 07 will often produce a well-formatted but weak paper.

---

## 11. How to Use the Approval Menu

### 11.1 When to Use `1/2/3`

Use `1/2/3` when AutoR's own refinement suggestions already match your judgment closely.

Typical cases:

- it already noticed missing baselines
- it already noticed missing figures
- it already noticed that the survey is too shallow

### 11.2 When to Use `4`

This is usually the highest-value button.

If the problem is specific, or you want to force a directional change, prefer `4`.

Examples:

- "The current experiments only show that the code runs. Add baseline A/B/C and write machine-readable results."
- "Do not expand the topic further. Narrow the project to a single main claim and build the experiment plan around it."
- "The PDF compiles, but the evidence is still weak. Go back and strengthen experiments and analysis before writing further."

### 11.3 When to Use `5`

Approve only when all three are true:

- the direction is correct
- the key gaps are already closed
- the result is genuinely useful for the next stage

That is very different from "looks good enough."

### 11.4 When to Use `6`

Abort when:

- the goal is wrong
- the environment is obviously broken
- you do not want to continue this run

Do not force a bad run forward.

---

## 12. Command Cheat Sheet

| Use case | Command |
| --- | --- |
| Simplest interactive start | `python main.py` |
| Start a new run | `python main.py --goal "your research goal"` |
| Use Claude as the backend | `python main.py --operator claude --model sonnet --goal "..."` |
| Use Codex as the backend | `python main.py --operator codex --model default --goal "..."` |
| Allow Codex-backed SSH / remote GPU execution | `python main.py --operator codex --codex-sandbox danger-full-access --goal "..."` |
| Set a target venue | `python main.py --venue neurips_2025 --goal "..."` |
| Start with resources | `python main.py --goal "..." --resources paper.pdf refs.bib data.csv notes.md` |
| Store runs on another disk | `python main.py --runs-dir /path/to/runs --goal "..."` |
| Skip intake | `python main.py --skip-intake --goal "..."` |
| Run a smoke test | `python main.py --fake-operator --goal "Smoke test"` |
| Resume the latest run | `python main.py --resume-run latest` |
| Resume a specific run | `python main.py --resume-run 20260415_120000` |
| Redo from a stage | `python main.py --resume-run latest --redo-stage 05` |
| Roll back to a stage | `python main.py --resume-run latest --rollback-stage 03` |
| Scan an existing project and recommend a re-entry stage | `python main.py --goal "..." --project-root /path/to/project` |
| Build a researcher profile from prior papers | `python main.py --goal "..." --paper-corpus /path/to/papers` |
| Generate and insert a method diagram | `python main.py --goal "..." --research-diagram` |
| Increase per-stage timeout | `python main.py --goal "..." --stage-timeout 28800` |

### 12.1 `--redo-stage` vs `--rollback-stage`

`--redo-stage`:

- restarts from a given stage
- best for "this stage was weak, but earlier stages are still valid"

Example:

```bash
python main.py --resume-run latest --redo-stage 05
```

Meaning:

- earlier stages stay in place
- experimentation restarts from Stage 05

`--rollback-stage`:

- marks the target stage and all downstream stages as invalid
- best for "a more fundamental earlier assumption changed"

Example:

```bash
python main.py --resume-run latest --rollback-stage 03
```

Meaning:

- Stage 03 and everything after it should now be treated as stale
- the pipeline restarts from Stage 03

If you changed the research question, core hypothesis, baseline design, or data setup, rollback is usually the right tool.

### 12.2 Stage Identifiers Accept More Than One Format

Many users assume only `03` works.

In practice, AutoR accepts:

- `03`
- `3`
- `03_study_design`

So all of these are valid:

```bash
python main.py --resume-run latest --redo-stage 03
python main.py --resume-run latest --redo-stage 3
python main.py --resume-run latest --redo-stage 03_study_design
```

This matters when you resume runs frequently.

### 12.3 `--runs-dir` Is Useful for Large Experiments

By default, runs are stored under the repo's `runs/` directory.

But if you want to:

- run many experiments
- write large intermediate outputs
- keep runs on a larger disk
- separate repo code from run artifacts

then this is useful:

```bash
python main.py --runs-dir /mnt/large-disk/autor-runs --goal "..."
```

This does not change the workflow itself. It only changes where runs are stored.

---

## 13. Practical Tricks That Improve Output Quality

### Trick 1: Make the Goal Narrow

Bad goal:

```text
study multi-agent systems
```

Better goal:

```text
Study whether increasing the number of experts improves MoE-LoRA generalization under a fixed parameter budget, and produce a submission-style PDF.
```

Your goal should ideally contain:

- the research question
- the task or scenario
- the constraints
- the final deliverable you want

### Trick 2: Start with Resources Whenever Possible

The earlier you provide these, the better:

- key PDFs
- existing `.bib`
- baseline tables
- sample data
- your idea notes
- an existing codebase

Blank-slate runs can work, but they are more likely to stay toy-level on the first pass.

### Trick 3: Do Not Be Too Lenient on the First Pass

Do not approve if the first pass is missing any of these:

- real experiments
- real data files
- figures
- PDFs
- evidence behind the claims
- actual files instead of future plans

If you approve weak work early, you usually pay for it later.

### Trick 4: Feedback Must Be Specific

Weak feedback:

```text
make it better
```

Strong feedback:

```text
The current experiments are still too toy. Add at least two strong baselines, one key ablation set, machine-readable result files, and failure-case analysis. Do not stop at a summary.
```

### Trick 5: Stages 03, 04, and 05 Control Most of the Final Quality

If these stages are weak, Stage 07 often becomes an empty shell with nice formatting.

Be especially strict about:

- whether the study design is executable
- whether the code actually runs
- whether the results are really written to disk

### Trick 6: Set `--venue` Early

If you already know whether you want a conference-style or journal-style draft, set it from the beginning.

That makes Stage 07 more stable.

### Trick 6.5: Most New Users Should Not Rush to `--skip-intake`

If the topic is still fuzzy, or your resources are not yet organized, keep intake enabled.

`--skip-intake` is better when:

- the goal is already clear
- the resources are already prepared
- you know you want to enter the formal stages directly

### Trick 7: Use `--redo-stage` for Local Rework

If only one stage is weak, do not restart the whole run.

For example, if writing is weak but the experiments are fine:

```bash
python main.py --resume-run latest --redo-stage 07
```

### Trick 8: Use `--rollback-stage` When the Direction Changed

If you changed the core hypothesis, experiment design, or data setup, do not patch over it lazily.

Roll back to the affected stage and rebuild from there.

### Trick 9: Do Not Restart from Zero If You Already Have a Project

If you already have a project repository:

```bash
python main.py \
  --goal "Turn this project into a stronger research package." \
  --project-root /path/to/your/project
```

AutoR will scan the project state and recommend a reasonable re-entry stage.

### Trick 10: Do Not Waste Your Prior Paper Corpus

If you already have a directory of related prior papers:

```bash
python main.py \
  --goal "Build a new paper with continuity from my prior work." \
  --paper-corpus /path/to/your/papers
```

Recommended install:

```bash
pip install pymupdf
```

That makes PDF extraction more useful.

### Trick 11: Increase the Timeout for Heavy Runs

The default timeout per stage is 4 hours.

If you know Stage 05 is heavy:

```bash
python main.py --goal "..." --stage-timeout 28800
```

### Trick 12: `--research-diagram` Is an Enhancement, Not a Requirement

If you want AutoR to generate a method illustration after Stage 07 and insert it into the paper:

```bash
python main.py --goal "..." --research-diagram
```

Recommended install:

```bash
pip install google-genai pillow pyyaml
```

Then provide:

- `GOOGLE_API_KEY`
- or `GEMINI_API_KEY`
- or `configs/diagram_config.yaml`

This is helpful, but it is not the source of research quality.

One more practical detail:

**if diagram generation fails, the entire run does not automatically fail with it.**

Treat it as an enhancement layer, not as a hard dependency for the full workflow.

### Trick 13: Learn to Read the Debugging Files

If you start wondering:

- why a stage keeps failing
- why resume behaves differently than expected
- why writing did not pick up earlier decisions

do not look only at the terminal.

These files are especially useful:

- `run_manifest.json`: current stage lifecycle state such as pending, running, approved, stale, or dirty
- `prompt_cache/`: the exact prompts used for stage attempts and repairs
- `operator_state/`: session, attempt, and recovery state
- `handoff/`: compressed stage-to-stage context passed downstream
- `logs_raw.jsonl`: raw streamed backend output

These files make troubleshooting much easier.

### Trick 14: Pay Attention to Structured Artifacts, Not Just the PDF

The following files are easy to ignore, but they matter a lot:

- `workspace/literature/sources.json`
- `workspace/literature/claims.json`
- `workspace/notes/hypothesis_manifest.json`
- `workspace/results/experiment_manifest.json`
- `workspace/artifacts/citation_verification.json`

Roughly speaking:

- `sources.json` / `claims.json`: structured evidence ledgers for literature claims
- `hypothesis_manifest.json`: typed hypotheses distilled in Stage 02
- `experiment_manifest.json`: a machine-readable experiment bundle for analysis and writing
- `citation_verification.json`: structured claim-to-citation coverage checks in Stage 07

If these files are missing, empty, or obviously inconsistent with the PDF, the run is usually not yet solid.

---

## 14. Copy-Paste Feedback Templates

You can paste these directly when you choose action `4`.

### 14.1 If the Survey Is Too Thin

```text
The current literature survey is still too shallow. Do not only list obvious papers. Expand it into something that can really support project selection, including task setup, key baselines, major differences, evaluation conventions, and current gaps. Write the organized results into the literature directory.
```

### 14.2 If the Hypothesis Is Not Focused Enough

```text
Do not keep expanding the idea space. Converge to one main claim worth testing, and demote the rest to backup ideas or ablations. The goal of this stage is a hypothesis that is testable, falsifiable, and strong enough to become the paper's main thread.
```

### 14.3 If the Study Design Is Still Toy-Level

```text
The current study design is still too toy. Define the datasets, metrics, baselines, ablations, training budget, random seeds, failure criteria, and result recording format. Do not leave this as a conceptual plan. Turn it into an executable experiment matrix.
```

### 14.4 If the Implementation Is Only a Skeleton

```text
The implementation is still at the skeleton stage. Make the minimum runnable path real, including data preparation, core scripts, config files, and sanity checks. Also state clearly which scripts matter and how they are run.
```

### 14.5 If the Experiments Look Like a Smoke Test

```text
The current experiment results are not strong enough to support the paper's claims. They look more like a smoke test. Add formal experiments, baseline comparisons, key ablations, repeated runs, and machine-readable result files. Do not stop at a textual summary or a single demo figure.
```

### 14.6 If the Analysis Only Repeats the Metrics

```text
The current analysis is still mostly metric narration. Add error analysis, failure cases, mechanism-level interpretation, and the figures needed to explain why the method works, where it fails, and how these findings affect the paper's main story.
```

### 14.7 If the PDF Only Looks Like a Paper

```text
The PDF already has the right shape, but the evidence is still weak. Make sure every core claim can be traced to real experiments, figures, or literature support, and complete citation verification. Do not stop at paper-shaped output.
```

---

## 15. Fastest Path to a Strong Final PDF

If your concrete goal is:

**produce the strongest possible PDF as quickly as possible**

then this is a good practical path.

### Step 1: Narrow the Goal

Do not start from a vague broad topic.

### Step 2: Start with Resources

Ideally include at least:

- 3 to 10 key PDFs
- one `.bib` file if you have it
- any existing baseline results
- your experiment notes

### Step 3: Set the Venue from the Beginning

For example:

```bash
python main.py \
  --operator claude \
  --model sonnet \
  --venue neurips_2025 \
  --goal "..."
```

### Step 4: Be Strict in Stages 03 to 06

This is where the real quality mostly comes from.

Keep asking:

- is there real code
- is there real data
- are there real result files
- are there real figures

### Step 5: Accept Only Verifiable Writing in Stage 07

Do not let a compiled PDF fool you.

A strong Stage 07 should include at least:

- LaTeX sources
- bibliography
- a compilable PDF
- citation verification output
- experiments and figures behind the main claims

### Step 6: If Something Earlier Is Wrong, Redo or Roll Back

Do not try to fix every upstream problem inside Stage 07. That usually fails.

### Step 7: Use Stage 08 to Finish the Outward-Facing Package

That way you end up with more than a standalone PDF. You end up with a fuller research package.

---

## 16. Where to Look in a Run

Every run creates:

```text
runs/<run_id>/
```

The most useful paths are:

| Path | Meaning |
| --- | --- |
| `runs/<run_id>/user_input.txt` | your original research goal |
| `runs/<run_id>/memory.md` | approved cross-stage memory |
| `runs/<run_id>/run_config.json` | backend, model, venue, and other core run config |
| `runs/<run_id>/run_manifest.json` | machine-readable stage lifecycle state |
| `runs/<run_id>/artifact_index.json` | run-wide structured index for data, results, and figures |
| `runs/<run_id>/stages/` | the official stage summaries |
| `runs/<run_id>/handoff/` | compressed handoff summaries passed to later stages |
| `runs/<run_id>/prompt_cache/` | cached prompts for attempts and repairs |
| `runs/<run_id>/operator_state/` | local session / attempt / recovery state |
| `runs/<run_id>/logs.txt` | workflow logs |
| `runs/<run_id>/logs_raw.jsonl` | raw streamed backend output |
| `runs/<run_id>/workspace/literature/` | literature organization artifacts |
| `runs/<run_id>/workspace/code/` | code |
| `runs/<run_id>/workspace/data/` | data |
| `runs/<run_id>/workspace/results/` | machine-readable results |
| `runs/<run_id>/workspace/results/experiment_manifest.json` | standardized experiment manifest used downstream |
| `runs/<run_id>/workspace/figures/` | figures |
| `runs/<run_id>/workspace/writing/` | paper source files |
| `runs/<run_id>/workspace/artifacts/` | PDFs and packaged outputs |
| `runs/<run_id>/workspace/artifacts/citation_verification.json` | citation and claim coverage checks from writing |
| `runs/<run_id>/workspace/notes/hypothesis_manifest.json` | structured hypotheses from Stage 02 |
| `runs/<run_id>/workspace/reviews/` | review / release materials |

If you are looking for the final PDF, check these first:

- `workspace/artifacts/`
- `workspace/writing/`

---

## 17. FAQ

### 17.1 Can I Write the Goal in Chinese?

Yes.

You can write the goal and refinement feedback in Chinese if that is more natural for you.

### 17.2 Do Beginners Need to Read the Source Code?

No.

You can use AutoR purely as a terminal research system and learn the repo later.

### 17.3 Why Is the First Pass Often Not Strong Enough?

Because real research is usually not something you solve in one generation pass.

AutoR is designed around:

- a first draft
- human supervision at stage boundaries
- a few rounds of directed refinement

### 17.4 Does a PDF Mean the Task Is Done?

No.

A PDF is only one part of the result.

If there are no real experiments, figures, result files, or citation support, the PDF may only look like a paper.

### 17.5 Should I Use Redo or Rollback More Often?

As a rule of thumb:

- use `redo` for local quality problems
- use `rollback` when earlier assumptions changed

### 17.6 Can I Switch the Backend Mid-Run?

Yes.

AutoR supports both `claude` and `codex`. When you resume a run, it preserves the existing backend by default, but you can explicitly choose another one.

In practice, if you switch backends, it is usually safest to combine that with a clear re-entry point such as `--redo-stage`.

### 17.7 What Should I Read Next If I Want to Understand the Project Faster?

A practical order is:

1. read [../README.md](../README.md)
2. run one smoke test
3. run one real experiment with `--resources`
4. inspect the resulting `runs/<run_id>/` structure

---

## 18. Final Advice

If you only remember one sentence, remember this:

**AutoR does not replace your decisions. It replaces a large part of your execution load.**

The person who determines the final quality is still you.

Your job is not to "let it run to the end by itself."

Your job is to:

- define the problem clearly
- be strict at the important stages
- use specific feedback to demand real evidence, experiments, and writing quality
- redo or roll back when the upstream quality is not strong enough

That is how you turn AutoR into a high-leverage research system instead of a paper-shaped content generator.
