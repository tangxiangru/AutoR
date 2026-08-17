# AutoR User Guide

> This guide is for first-time AutoR users.
>
> The goal is not just to make the command run. The goal is to help you understand how to install AutoR, how to use it correctly, how to supervise each stage so outputs do not stay toy-level, and how to get to a strong final deliverable — a markdown report by default, or a compiled PDF with `--output-format latex` — as quickly as possible.

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

> **Want the design instead of the steps?** This guide is the operating manual. [framework.md](framework.md) is the argument: why every gate is a function that reads the filesystem rather than the transcript, why the improvement loop is scored by something it cannot influence, and — stated just as plainly — what has *not* been established. Read it if you want to know why AutoR is shaped the way it is; you do not need it to run your first project.

---

## 2. What AutoR Can Do

The current mainline is built for these workflows:

- start from a concrete research goal
- walk eight research stages that are **nodes in a directed graph**, not steps in a fixed list: the default move is always forward, but a stage that exposes an earlier mistake can send the run back
- call a real execution backend at every stage
- write prompts, logs, stage summaries, code, data, figures, writing sources, reports, and PDFs to `runs/<run_id>/`
- resume an existing run
- redo from a specific stage
- roll back to an earlier stage and invalidate downstream work
- stop early at a chosen stage (`--final-stage`)
- start from an existing project repository
- start from your own prior paper corpus
- produce either a markdown report (the default) or a venue-aware LaTeX package with a compiled PDF (`--output-format latex`)
- choose how much optional machinery a run uses with one dial (`--rigor`)
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
- AutoR's `--full-auto` still means automated approval: a strict reviewer agent replaces the waiting human gate, while the eight-stage research workflow itself stays unchanged. Note that `--full-auto` is a shortcut for `--approval-mode agent` **plus** `--unattended`, so it also stops the run from ever blocking on terminal input, and a stage that burns its whole retry budget is auto-skipped rather than aborting the run (up to `--max-auto-skips`, default 3).
- The stages are a **graph**, not a list. `--stage-graph` defaults to `adaptive`, where an analysis that exposes a design flaw can route back to Stage 03 instead of writing up around it. `--stage-graph linear` gives the strict 01-through-08 sequence, except that a round which concludes the question cannot be answered still finishes at Stage 06. See [8.1](#81-the-shape-of-the-walk) and [8.2](#82-when-a-late-finding-sends-the-run-back).
- The optional machinery is behind one dial. `--rigor` picks a level (`fast`, `standard`, `thorough`, `max`) instead of asking you to know four separate switches; `standard` is the default. See [6.5](#65-one-dial-you-should-meet-early---rigor).
- Stage 07's default deliverable is a markdown report at `workspace/report/report.md` with embedded figures. The submission-style LaTeX package and compiled PDF are still there, behind `--output-format latex`.

---

## 3. What You Need Before Installation

Recommended environment:

| Item | Required | Notes |
| --- | --- | --- |
| Python 3.10+ | Required | AutoR runs through `python main.py` |
| Git | Required | Needed to clone the repository |
| Node.js 18+ | Strongly recommended | Claude Code officially requires Node 18+, and Codex CLI is also installed via npm |
| Claude Code or Codex CLI | Required for real runs | You need at least one execution backend |
| TeX toolchain | Optional | Only needed for `--output-format latex`, where Stage 07 compiles a PDF |
| `PyMuPDF` | Optional | Recommended if you use `--paper-corpus` and want PDF text extraction |
| `google-genai` / `Pillow` / `PyYAML` | Optional | Needed for `--research-diagram`; `google-genai` is also what `--web-search gemini` and `--cross-review` use |

AutoR's own runtime imports nothing outside the Python standard library, so there is no install step and no requirements file to fight with. Everything in the *Optional* rows above degrades to a recorded "unavailable" rather than a crash.

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
1. clone https://github.com/tangxiangru/AutoR.git
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
git clone https://github.com/tangxiangru/AutoR.git
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

One thing a smoke test cannot show you: with `--fake-operator` there is no backend to ask which move to take, so the router always takes the graph's default edge. A fake run therefore walks straight through 01 to 08 and never demonstrates a backward move.

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

One more Studio limitation worth knowing before you pick an interface: Studio exposes no stage-graph or routing switches. It drives the same `ResearchManager` the terminal does, so graph routing and backward moves are available there too — but every Studio run gets the defaults (the adaptive graph, `--routing auto`), and there is no browser equivalent of `--stage-graph linear --routing off`.

### 6.5 One Dial You Should Meet Early: `--rigor`

AutoR has a set of optional mechanisms — cheaper prompts for settled stages, a crux panel, an ideation panel, a five-seat review panel. You do not have to learn four switches to use them. One flag picks a level:

| `--rigor` | effort tiers | crux deliberation | ideation panel | review panel |
| --- | :---: | :---: | :---: | :---: |
| `fast` | – | – | – | – |
| `standard` *(the default)* | **on** | – | – | – |
| `thorough` | **on** | **on** | **on** | – |
| `max` | **on** | **on** | **on** | **on** |

Each level adds to the one above it, and the table is `_LEVEL_FEATURES` in [../src/rigor.py](../src/rigor.py), which is the single source of truth for it — `python main.py --help` prints the same rows.

What each one is:

- **effort tiers** (`--effort-tiers`) — runs each stage as *routine* or *deliberative* instead of treating them alike. By default `04_implementation`, `05_experimentation` and `08_dissemination` start routine: a leaner prompt, one reviewer, no polish rounds. A routine stage that keeps failing its gate is promoted automatically. This is the only one of the four that makes a run **cheaper**, which is why it is on at the default level.
- **crux deliberation** (`--deliberation`) — lets a stage stop and pull in a four-voice panel when it hits a genuine crux. Budgeted: `--max-deliberations` defaults to 3.
- **ideation panel** (`--ideation-panel`) — widens Stage 02 with five proposers working from distinct lenses. It proposes; it decides nothing.
- **review panel** (`--review-panel`) — replaces the single reviewer with five role-differentiated seats (PI, domain expert, methodologist, reproducibility engineer, adversarial reviewer) that review blind, cross-examine, then have a chair synthesize one decision. `--panel-roles` can reseat it, including an optional sixth `reader` seat.

An explicit switch always beats the level, in both directions:

```bash
python main.py --rigor thorough --no-ideation-panel --goal "..."
python main.py --rigor fast --deliberation --goal "..."
```

**The warning that matters most on this page:**

> `--rigor max` implies `--review-panel`, and `--review-panel` **removes the human from the approval gate**. The panel *is* an approval gate, so there is nobody left to answer a terminal prompt: `resolve_unattended` in [../main.py](../main.py) returns true for `--review-panel` exactly as it does for `--unattended` and `--full-auto`, and `--rigor` is resolved *before* it. A plain `python main.py --rigor max --goal "..."` is therefore an unattended, agent-gated run — the flag that reads like *more review* is the flag that takes away *your* review.

If you want the extra machinery but intend to approve the stages yourself, ask for it without the panel:

```bash
python main.py --rigor thorough --goal "..."          # deliberation + ideation, human still at the gate
python main.py --rigor max --no-review-panel --goal "..."   # same effect, stated the other way round
```

For a new user, `standard` (that is, passing nothing) is the right starting point. Details, and how the levels read back in the run log: [rigor.md](rigor.md).

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

One thing those goals do **not** do: asking for a PDF in the goal text does not produce one. The deliverable is chosen by `--output-format`, which defaults to `markdown`. Add `--output-format latex` if you want the LaTeX package and the compiled PDF.

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

Three boundaries matter here:

- `--full-auto` does **not** change the stage graph; it swaps the manual approval gate for a strict reviewer agent
- it *does* change what happens when a stage fails. `--full-auto` is a shortcut for `--approval-mode agent` plus `--unattended`, and an unattended stage that exhausts `--max-attempts` (default 5) is auto-skipped instead of stopping the run, up to `--max-auto-skips` (default 3). A skipped stage is recorded as skipped, not as approved, but the run keeps going without it
- for serious research work, the default human-reviewed mode is still the recommended path; `--full-auto` is more useful for unattended sweeps, overnight dry runs, or pipeline pressure tests

Three flags put an agent in the approval seat: `--approval-mode agent`, `--full-auto`, and `--review-panel` (including the `--review-panel` that `--rigor max` turns on for you). Each sets `approval_mode` to `agent` and, through `resolve_unattended`, also marks the run unattended.

`--unattended` on its own is the fourth input to `resolve_unattended` but is *not* one of those three. It only says nobody is at the terminal; `approval_mode` stays `manual`, so no reviewer agent is installed and the first approval menu has nobody to answer it — the terminal UI raises `UnattendedInputError` instead of the gate being decided. Removing the human and installing an agent are different things, and only the three flags above do both. If you meant to review the stages yourself, pass none of the four.

### 7.2 A Few More Flags Worth Knowing on a First Real Run

You do not need the full flag list to start, but these come up almost immediately. Every flag, its default, and what is preserved on resume: **[cli-reference.md](cli-reference.md)**.

| Flag | Default | Why a first-time user wants it |
| --- | --- | --- |
| `--goal-file PATH` | — | Read the goal from a file instead of `--goal`. A serious goal is usually several paragraphs, and shell quoting stops being fun quickly. Mutually exclusive with `--goal`. |
| `--output-format {markdown,latex}` | `markdown` | `markdown` writes `workspace/report/report.md` with figures under `workspace/report/images/`. `latex` produces the submission-style package instead: `main.tex`, `sections/*.tex`, a bibliography, and a compiled PDF. Preserved when resuming. |
| `--final-stage STAGE` | run everything | Stop after this stage instead of running the whole workflow, e.g. `--final-stage 07_writing` when you want the report but not the dissemination package. |
| `--max-attempts N` | `5` | Attempts per stage before AutoR escalates (or, unattended, auto-skips). Each retry re-runs the stage with the previous attempt's validation errors attached. Raise it for a stubborn stage. |
| `--stage-timeout SECONDS` | `14400` (4 hours) | Wall-clock ceiling for one stage attempt. Raise it before a heavy Stage 05, not after it times out. |
| `--web-search {auto,gemini,native,off}` | `auto` | How the agent searches. `gemini` routes searches through the Gemini API, which is what you need where the backend's own web search is disabled (Claude Code on Vertex AI, for example). `native` leaves the backend's own tool in charge. `auto` uses Gemini when a key is available and falls back to native. `off` gives the agent no search tool and denies `WebSearch` and `WebFetch` to the CLI. |
| `--fake-operator` | off | A dry run with no backend and no tokens. See [6.3](#63-optional-run-a-smoke-test-first). |
| `--resume-run ID`, `--redo-stage STAGE`, `--rollback-stage STAGE` | — | Continue, re-run, or invalidate. See [12.1](#121---redo-stage-vs---rollback-stage). |

### 7.3 Choose the Venue Early

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

The registry ships 12 venue keys today:

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

The authoritative list is [../templates/registry.yaml](../templates/registry.yaml). `resolve_venue_key` accepts a registry key, the display name (`ICLR 2026`), or the style-package name (`iclr2026_conference`), with the comparison ignoring case, spaces, and every other non-alphanumeric character. A value it cannot match to any of those three is **not** quietly replaced by the default: it raises `Unknown venue: <value>`, and because the resolution happens while the CLI is still assembling the run configuration, the process prints `Error: Unknown venue: <value>`, exits 1, and never creates a run directory. (`python main.py --fake-operator --goal x --venue neurips2027` does exactly that.) The silent fallback belongs to `resolve_output_format`, which does return the default for an unrecognized value — not to the venue.

Notes:

- if you do not specify `--venue`, the default is `neurips_2025`
- the venue profile matters most in `--output-format latex`, where Stage 07 is told the venue's type, page limit, citation style, and preferred style package, and the stage gate refuses a `main.tex` it cannot match to the configured venue
- in the default `markdown` mode the venue key is still recorded in `run_config.json` and shown to the writing stage, but a markdown report has no style package or page budget to hit, so the effect is much smaller
- this does not mean the repo vendors the complete official submission system for that venue

### 7.4 Strongly Prefer Starting with Resources

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

With one caveat worth knowing: a directory is classified as a whole, not file by file. A directory containing `.py` or `.ipynb` files is ingested as code into `workspace/code/`; any other directory lands in `workspace/artifacts/`. Individual files are classified by suffix, so PDFs and `.bib` files passed *individually* go to `workspace/literature/`, where the survey stage expects them. If the literature location matters to you, pass the papers as files.

### 7.5 If You Need to Teach AutoR a Specific "Skill"

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

### 7.6 When to Provide Those Skill Resources

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

### 7.7 Resources Alone Are Not Enough: Put Hard Constraints in the Goal

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

### 7.8 Where to Check Whether AutoR Actually Learned It

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

### 7.9 A Practical Refinement Prompt for This Case

If AutoR failed to follow the cluster workflow you gave it, you can use feedback like this:

```text
Do not continue with local-only experiments.
Use the provided rjob workflow to submit real GPU jobs.
Create reusable submission scripts and save the submit command, job config, job IDs, logs, and machine-readable results under workspace/code and workspace/results.
Local execution is only for smoke tests.
```

### 7.10 What Usually Does Not Work

These approaches are usually too weak:

- saying only "please learn rjob"
- giving a single command with no context
- saying only "use GPU" without specifying submission flow, output locations, or success criteria
- failing to check, during approval, whether the workflow was actually followed

The short version is:

**if you want AutoR to learn a skill, package that skill as executable resources and then enforce it through human approval at the critical stages.**

---

## 8. How AutoR Runs

### 8.1 The Shape of the Walk

There are **eight** research stages (`STAGES` in [../src/utils.py](../src/utils.py)):

1. `01_literature_survey`
2. `02_hypothesis_generation`
3. `03_study_design`
4. `04_implementation`
5. `05_experimentation`
6. `06_analysis`
7. `07_writing`
8. `08_dissemination`

`00_intake` is **not** one of them. It runs once before the walk starts, and it is skipped by `--skip-intake` — and also whenever stdin is not a terminal, because there would be nobody to answer its questions.

Those eight stages are nodes in a directed graph, not entries in a list. The default topology (`--stage-graph adaptive`) has 22 edges: eight that advance, of which six carry a guard; thirteen that go backward; and one conditional terminal that lets a round which concluded the question cannot be answered finish from Stage 06 instead of writing up anyway. `--stage-graph linear` drops the thirteen backward edges and the six forward guards, leaving nine edges: the eight unguarded forward edges (01 → 02 → … → 08, then `08_dissemination → finish`) and — still guarded — that same conditional terminal out of Stage 06. Keeping it is deliberate, and it is load-bearing: `_preempted_by_a_conclusion` makes a live conditional terminal the *only* admissible move at its node, so a linear run whose round records that the question cannot be answered also stops at Stage 06 rather than writing up. `linear` is a strict sequence of *stages*, not a promise that the run will keep going after it has said it cannot.

The forward path is still the normal path, and it is the one this guide walks. What the graph buys you is [8.2](#82-when-a-late-finding-sends-the-run-back).

| Stage | What it does | What you should check |
| --- | --- | --- |
| `00_intake` *(before the walk)* | Aligns the goal, resources, constraints, evaluation direction, and target writing style before formal research begins. | Answer the clarification questions, add hard constraints, and confirm the problem is narrow enough to execute. |
| `01_literature_survey` | Organizes related work, task background, benchmarks, baselines, and the real research gap. | Do not accept shallow paper lists; look for structured literature files, comparisons, and evidence ledgers. |
| `02_hypothesis_generation` | Converts the direction into testable hypotheses and provisional paper claims. | Make sure it converges to a falsifiable main line instead of continuing to brainstorm. |
| `03_study_design` | Turns the hypothesis into an executable experimental design. | Check datasets, metrics, baselines, ablations, budgets, seeds, failure criteria, and data artifacts. |
| `04_implementation` | Builds real code, configs, data-prep scripts, and sanity checks. | Do not approve skeletons; require runnable scripts, commands, configs, and logs. |
| `05_experimentation` | Runs the planned experiments and writes machine-readable results. | Distinguish smoke tests from real experiments; require baselines, repeats, result files, and failure records. |
| `06_analysis` | Interprets results, creates figures, analyzes failures, and explains mechanisms. | Do not accept metric narration only; require plots, failure cases, ablation interpretation, and boundaries. |
| `07_writing` | Produces the final deliverable: a markdown report with embedded figures by default, or venue-aware LaTeX sources and a compiled PDF with `--output-format latex`. | Verify that every major claim is backed by experiments, figures, or literature. |
| `08_dissemination` | Builds review, release, readiness, reproduction, and presentation materials. | Confirm the run can be inspected, reproduced, and shown to others, not just read as a paper. |

### 8.2 When a Late Finding Sends the Run Back

The expensive failure in an automated research run is not a stage that fails loudly. It is a run that reaches Stage 06, discovers the design cannot answer the question, and writes it up anyway because there was nowhere else to go.

So the graph has thirteen backward edges (`REVISIT_EDGES` in [../src/stage_graph.py](../src/stage_graph.py)). Three of them, as examples:

- **06 → 03.** The analysis exposed a design flaw the results cannot repair — a confound, a leak, or a comparison that was never fair. Going back to the study design is cheaper than writing around it.
- **07 → 06.** Writing it up showed a claim has no analysis behind it, or a figure does not show what the text says it shows. This edge is open only once results exist.
- **05 → 04.** The experiment could not run, or it ran and produced something the implementation is clearly responsible for.

There are ten more, including 02 → 01 (stating the hypotheses showed the "gap" is not a gap), 06 → 02 (the evidence refutes the hypotheses and points somewhere specific), and 07 → 01 (the finding relates to work the survey missed).

How a move actually gets chosen, and where you sit in it:

1. **AutoR decides which moves are legal**, by evaluating each edge's guard against the files on disk — not against anything the agent claims. The move into Stage 07, for example, stays closed until every preregistered empirical hypothesis has a verdict and at least one figure exists.
2. **The backend picks among the legal moves and has to state a reason.** With `--routing auto` (the default) it is only asked where more than one move is live, which on a linear graph is never. With `--routing off` it is never asked at all and the walk takes the default edge — with one exception that is not a routing decision: a closed research round's own choice of where to resume (which `--max-rounds 2` or more makes possible) is honoured under every routing mode, provided the edge it names is legal at that stage. An off-menu pick, or one with no stated reason, is refused and replaced by the forward edge.
3. **The default is always forward.** A refusal, a routing failure, or a run nobody is steering all come out as the plain 01-through-08 pipeline rather than as a stall. A backward move only happens as a deliberate, justified choice, and a revisit whose justification repeats a reason already on the path is refused as a loop.
4. **You still approve every stage.** The routing decision is made *after* your approval and does not replace it: what the graph chooses is which stage runs next, not whether the finished one was good enough. Every stage the run enters — including one it re-enters — goes through the same approval menu.
5. **A backward move invalidates the work downstream of it.** AutoR prints a preview of what is about to go stale and marks those stages in `run_manifest.json`, so a later stage cannot quietly keep describing work the revisit is replacing.

Two bounds keep this from becoming an infinite loop: `--graph-max-visits` (default 3) caps how many times one stage may be entered, and `--graph-max-steps` (default 20) caps the whole walk.

If you want none of this, `--stage-graph linear --routing off` gives the strict sequence back — with one exception that neither flag turns off. The conditional terminal out of Stage 06 is present on both topologies, and a live conditional terminal preempts every other move at its node, so a round that ends in abandonment finishes at Stage 06 under `--routing off` as well. Refusing to write up a question the run has just said it cannot settle is a correctness property, not a routing preference.

### 8.3 The Stage Loop and the Approval Menu

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

- the run's own backward moves ([8.2](#82-when-a-late-finding-sends-the-run-back)) are chosen by AutoR and the backend, from the moves the guards leave open; `/back` is the same capability with your hand on the wheel, and it is not filtered by those guards
- so if you want to bypass the current stage for now, or return to an earlier stage and rebuild from there, you do not have to abandon the whole run

Notes:

- `/back` is for earlier stages, not for jumping forward
- `/back` invalidates the same way a graph revisit does: the target stage becomes pending and everything after it is marked stale
- if the current stage exhausts the retry limit, AutoR shows a recovery menu so you can directly choose to skip the stage, roll back to an earlier one, or abort

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
| `07_writing` | A report whose every figure reference resolves and whose every claim carries a number (or, in `latex` mode, LaTeX, BibTeX, and a compilable PDF) | it is paper-shaped but thin: captions with no figure, adjectives with no measurement, unsupported claims | "Do not stop at paper-shaped output. Make sure every core claim is backed by experiments or literature, and complete citation verification." |
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

**One approval is not like the others.** Approving `04_implementation` freezes the hypothesis set: AutoR copies the typed hypotheses into `workspace/notes/preregistration.json`, hashes them, and never overwrites that file. From Stage 05 onward every empirical hypothesis is adjudicated against the frozen set, and changing it later has to arrive as a recorded amendment rather than a quiet edit. Read the hypotheses before you press `5` on Stage 04, not after.

Approving `03_study_design` has a smaller version of the same property: the report plan — which figures the write-up will carry, and which claim each supports — is stamped outside `workspace/` at that moment.

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
| Read a long goal from a file | `python main.py --goal-file goal.md` |
| Use Claude as the backend | `python main.py --operator claude --model sonnet --goal "..."` |
| Use Codex as the backend | `python main.py --operator codex --model default --goal "..."` |
| Allow Codex-backed SSH / remote GPU execution | `python main.py --operator codex --codex-sandbox danger-full-access --goal "..."` |
| Set a target venue | `python main.py --venue neurips_2025 --goal "..."` |
| Produce a LaTeX package and PDF instead of a markdown report | `python main.py --output-format latex --goal "..."` |
| Stop once the report is written | `python main.py --final-stage 07_writing --goal "..."` |
| Start with resources | `python main.py --goal "..." --resources paper.pdf refs.bib data.csv notes.md` |
| Store runs on another disk | `python main.py --runs-dir /path/to/runs --goal "..."` |
| Skip intake | `python main.py --skip-intake --goal "..."` |
| Run a smoke test | `python main.py --fake-operator --goal "Smoke test"` |
| Turn up the optional machinery, human still at the gate | `python main.py --rigor thorough --goal "..."` |
| Turn all of it off | `python main.py --rigor fast --goal "..."` |
| Hand the gate to a reviewer agent | `python main.py --full-auto --goal "..."` |
| Take the strict 01-through-08 sequence (an abandoned round still finishes at 06) | `python main.py --stage-graph linear --routing off --goal "..."` |
| Let Stages 03-06 run more than once | `python main.py --max-rounds 2 --goal "..."` |
| Search the web where the backend's own search is disabled | `python main.py --web-search gemini --goal "..."` |
| Resume the latest run | `python main.py --resume-run latest` |
| Resume a specific run | `python main.py --resume-run 20260415_120000` |
| Redo from a stage | `python main.py --resume-run latest --redo-stage 05` |
| Roll back to a stage | `python main.py --resume-run latest --rollback-stage 03` |
| Scan an existing project and recommend a re-entry stage | `python main.py --goal "..." --project-root /path/to/project` |
| Build a researcher profile from prior papers | `python main.py --goal "..." --paper-corpus /path/to/papers` |
| Generate and insert a method diagram | `python main.py --goal "..." --research-diagram` |
| Increase per-stage timeout | `python main.py --goal "..." --stage-timeout 28800` |
| Give a stubborn stage more retries | `python main.py --goal "..." --max-attempts 10` |
| See what the cross-run archive has learned, then exit | `python main.py --archive-report` |

This is the short list, not the whole surface: `main.py` has 61 flags. For every one of them, its default, and what survives a resume, see **[cli-reference.md](cli-reference.md)**.

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

The same three forms work for `--rollback-stage`, `--final-stage`, and the `/back` control command.

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
- the written deliverable itself (`report.md`, or the PDF in `latex` mode)
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

### Trick 6: Set `--venue` and `--output-format` Early

If you already know whether you want a conference-style or journal-style draft, set the venue from the beginning. That makes Stage 07 more stable — and if you want the LaTeX package and a compiled PDF rather than the default markdown report, pass `--output-format latex` in the same command. Both are recorded in the run and preserved when you resume, so setting them at the start is cheaper than switching at Stage 07.

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

If you want AutoR to generate a method illustration after Stage 07 and insert it into the deliverable — `report.md` in markdown mode, `method.tex` in latex mode:

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
- `workspace/notes/preregistration.json`
- `workspace/results/experiment_manifest.json`
- `workspace/results/hypothesis_outcomes.json`
- `workspace/artifacts/citation_verification.json`

Roughly speaking:

- `sources.json` / `claims.json`: structured evidence ledgers for literature claims
- `hypothesis_manifest.json`: typed hypotheses distilled in Stage 02
- `preregistration.json`: the hypothesis set as it was frozen when you approved Stage 04, before any result existed. It is written once and never overwritten; a later change has to arrive as a recorded amendment
- `experiment_manifest.json`: a machine-readable experiment bundle for analysis and writing
- `hypothesis_outcomes.json`: one verdict per preregistered *empirical* hypothesis, each `supported` or `refuted` one citing an evidence file that has to exist. Theoretical propositions and paper claims are frozen alongside them but are not adjudicated here, and a verdict written for one is rejected. This is also what closes or opens the move into Stage 07
- `citation_verification.json`: structured claim-to-citation coverage checks in Stage 07

If these files are missing, empty, or obviously inconsistent with the report, the run is usually not yet solid.

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

### Step 3: Ask for the PDF, and Set the Venue

A PDF is not the default deliverable. `--output-format` defaults to `markdown`, which writes a standalone report instead. If you want the submission-style package, say so at the start — the setting is recorded in the run and preserved when you resume:

```bash
python main.py \
  --operator claude \
  --model sonnet \
  --output-format latex \
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

In `latex` mode, a strong Stage 07 should include at least:

- LaTeX sources
- bibliography
- a compilable PDF
- citation verification output
- experiments and figures behind the main claims

In the default `markdown` mode the shape is different but the bar is not: `workspace/report/report.md`, the figures it references actually present under `workspace/report/images/`, citation verification output, and a number behind every claim.

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
| `runs/<run_id>/intake_context.json` | the approved intake brief, its resources, and the clarification Q&A |
| `runs/<run_id>/run_config.json` | backend, model, venue, output format, stage graph, and other core run config |
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
| `runs/<run_id>/workspace/results/hypothesis_outcomes.json` | one verdict per preregistered *empirical* hypothesis — `supported`, `refuted`, `inconclusive`, or `not_tested` — with every `supported` or `refuted` one citing an evidence file that exists |
| `runs/<run_id>/workspace/figures/` | figures |
| `runs/<run_id>/workspace/report/report.md` | the markdown report, which is the default deliverable |
| `runs/<run_id>/workspace/report/images/` | the figures embedded in that report |
| `runs/<run_id>/workspace/writing/` | LaTeX paper sources, in `--output-format latex` runs |
| `runs/<run_id>/workspace/artifacts/` | PDFs, build logs, and packaged outputs |
| `runs/<run_id>/workspace/artifacts/citation_verification.json` | citation and claim coverage checks from writing |
| `runs/<run_id>/workspace/notes/hypothesis_manifest.json` | structured hypotheses from Stage 02 |
| `runs/<run_id>/workspace/notes/preregistration.json` | the hypothesis set frozen at Stage 04 approval |
| `runs/<run_id>/workspace/notes/research_rounds.json` | how each Stage 03-06 round closed, and why |
| `runs/<run_id>/evolution/` | rubric scores, losing drafts, routing refusals — the search, kept out of `workspace/` |
| `runs/<run_id>/workspace/reviews/` | review / release materials |

If you are looking for the final deliverable, check these first:

- `workspace/report/` in the default markdown mode
- `workspace/artifacts/` and `workspace/writing/` in `--output-format latex` runs

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

### 17.7 Why Did the Run Go Back to an Earlier Stage?

Because the stages are a graph and something later in the run said an earlier one was wrong. See [8.2](#82-when-a-late-finding-sends-the-run-back).

Where to look for the reason:

- the terminal prints the chosen move and its stated reason at the moment it is taken
- `run_manifest.json` shows which stages were marked stale, and the reason recorded for it
- `evolution/routing_refusals.jsonl` records a move the backend asked for and did **not** get

If you never want this, run with `--stage-graph linear --routing off`.

### 17.8 What Should I Read Next If I Want to Understand the Project Faster?

A practical order is:

1. read [../README.md](../README.md)
2. run one smoke test
3. run one real experiment with `--resources`
4. inspect the resulting `runs/<run_id>/` structure

Then, depending on what you want:

| You want | Read |
| --- | --- |
| Every flag, its default, and what survives a resume | [cli-reference.md](cli-reference.md) |
| Why the system is built this way, and what has *not* been established | [framework.md](framework.md) |
| What each stage must produce before it is allowed to advance | [stage-contract.md](stage-contract.md) |
| What is in a run directory, file by file | [run-artifacts.md](run-artifacts.md) |
| The `--rigor` levels in detail | [rigor.md](rigor.md) |
| A stage that keeps failing its gate | [troubleshooting.md](troubleshooting.md) |

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
