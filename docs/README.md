# AutoR Documentation

This directory is the reference documentation for AutoR. The
[root README](../README.md) is the project pitch; everything here is the
detail behind it.

## Start here

| If you want to… | Read |
| --- | --- |
| Understand what AutoR is as a system — design, modules, novelty, contribution | **[The Framework](framework.md)** |
| Install AutoR and run your first project end to end | [English Guide](tutorial_en.md) · [中文教程](tutorial_zh.md) |
| Look up a command-line flag | [CLI Reference](cli-reference.md) |
| Run AutoR unattended, or benchmark it on ResearchClawBench | [ResearchClawBench](researchclawbench.md) |
| See what every full benchmark run scored, and which predictions it broke | [RCB Experiment Log](rcb-experiment-log.md) |
| Answer and score a written science exam question | [FrontierScience-Research](frontierscience.md) |
| Rediscover a published finding by running experiments, under a one-hour clock | [FIRE-Bench](firebench.md) |
| Understand what a run leaves on disk | [Run Artifacts](run-artifacts.md) |
| Know exactly what a stage must produce to be accepted | [Stage Contract](stage-contract.md) |
| Choose how much optional machinery a run uses | [Rigor](rigor.md) |
| Replace the reviewer agent with a panel that argues before it decides | [Review Panel](review-panel.md) |
| Send back one passage instead of the whole stage | [Anchored Review Comments](stage-comments.md) |
| Widen Stage 02's hypotheses with a panel that proposes instead of deciding | [Ideation Panel](ideation-panel.md) |
| Let a stage stop and think hard when it hits a genuine crux | [Raising a Crux](deliberation.md) |
| Spend effort where the research needs it instead of evenly | [Effort Tiers](effort-tiers.md) |
| Find out which optional machinery actually earned its cost | [Scorecard](scorecard.md) |
| Configure venues, backends, sandboxes, or API keys | [Configuration](configuration.md) |
| Use or script the browser UI | [Studio Guide & HTTP API](studio.md) |
| Understand how the code is organized | [Architecture](architecture.md) |
| Hack on AutoR, run the tests, add a stage or a venue | [Development](development.md) |
| Know when the backend, not the research, is what failed | [Backend Health](backend-health.md) |
| Fix an error you just hit | [Troubleshooting](troubleshooting.md) |

## The whole documentation set

### Design

- **[framework.md](framework.md)** — the design document. The problem AutoR is
  built for, the six commitments that determine its architecture, the control
  loop, every module and what it owns, what is new here, what it contributes,
  and what has *not* been established.

### User guides

- **[tutorial_en.md](tutorial_en.md)** — the full end-to-end user guide.
  Installation, first run, how to review each stage, how to write feedback
  that actually improves output, and the fastest path to a strong final PDF.
- **[tutorial_zh.md](tutorial_zh.md)** — the same guide in Chinese.

### Reference

- **[cli-reference.md](cli-reference.md)** — every flag on `main.py`,
  `rcb_agent.py`, `fs_agent.py` and `studio.py`, what each one defaults to, what
  is persisted on resume, and which flags are mutually exclusive.
- **[configuration.md](configuration.md)** — `run_config.json`, the venue
  registry, the optional Gemini diagram config, environment variables, and
  which settings survive a resume.
- **[run-artifacts.md](run-artifacts.md)** — the run directory layout and the
  JSON schema of every machine-readable file AutoR writes or validates.
- **[stage-contract.md](stage-contract.md)** — the stage summary markdown
  contract and the per-stage artifact gate, as enforced by
  `validate_stage_markdown` and `validate_stage_artifacts`.
- **[studio.md](studio.md)** — running the local browser workspace, what each
  page does, and the complete HTTP API surface.
- **[researchclawbench.md](researchclawbench.md)** — running AutoR with no
  human in the loop: the unattended execution model, the
  [ResearchClawBench](https://github.com/InternScience/ResearchClawBench)
  adapter and its output contract, and the Gemini-backed web search used where
  the coding agent's own `WebSearch` tool is disabled.
- **[rcb-experiment-log.md](rcb-experiment-log.md)** — every full 40-task run of
  AutoR on ResearchClawBench under one fixed judge and image window: the score, the
  prediction the run was launched to test, and where the prediction was wrong. Four of
  five entries contradict something their own PR predicted.
- **[researchclawbench-landscape.md](researchclawbench-landscape.md)** — how the
  other agents on the ResearchClawBench leaderboard score, which of their
  published numbers reproduce from the public data, and the same-model baseline
  any AutoR result has to be quoted against.
- **[frontierscience.md](frontierscience.md)** — the second benchmark: sixty
  written science examination questions graded against a ten-point rubric by a
  judge model, with no data, no reference paper and no reference answer. The
  pinned dataset and its strict rubric parser, the prompt contract and its word
  gate, the `direct` and `ideate` profiles, the judge's measured sampling noise
  and refusal rules, the paired trial's ten admission clauses, and the two
  numbers about AutoR itself that are **not** measured.

### Internals

- **[self-improvement.md](self-improvement.md)** — the stage graph and its
  guards, routing, the rigour rubric and the champion ratchet, the cross-run
  archive and its comparability basis, paired trials — and the constraints that
  stop a scored loop from optimising toward a nicer answer.
- **[rigor.md](rigor.md)** — the one dial: which optional machinery each level
  turns on, and how an explicit flag overrides it.
- **[effort-tiers.md](effort-tiers.md)** — routine vs deliberative stages, tier
  promotion, and concentrating the strong model where something is undecided.
- **[review-panel.md](review-panel.md)** — the five seats, the blind round and
  the cross-examination, blocking objections, and the solo baseline every panel
  run measures itself against.
- **[ideation-panel.md](ideation-panel.md)** — the five proposer lenses, Jaccard
  deduplication, and the adoption measurement taken after approval.
- **[deliberation.md](deliberation.md)** — when a stage may stop and escalate a
  crux, the four voices, and the falsifier the resolution must name.
- **[stage-comments.md](stage-comments.md)** — anchored review comments and the
  collateral-change diff.
- **[scorecard.md](scorecard.md)** — the five self-measurement ledgers and the
  end-of-run verdict on which flags earned their cost.
- **[backend-health.md](backend-health.md)** — telling "the model was
  unreachable" apart from "the research failed".
- **[architecture.md](architecture.md)** — layers, module map, the stage
  attempt loop, how prompts are assembled, how recovery works, and the
  extension points.
- **[development.md](development.md)** — dev environment, tests, CI, coding
  conventions, and step-by-step recipes for adding a stage, a venue, or an
  execution backend.
- **[troubleshooting.md](troubleshooting.md)** — symptom-to-fix table for the
  errors AutoR actually raises.

### Design notes

- **[ui-design/](ui-design/)** — the Studio design record: information
  architecture, screen specs, system architecture, development plan, and
  reference screenshots. These are design documents, not user documentation.
- **[iclr/](iclr/)** — the framework-paper notes.
  [composable-stage-graphs.md](iclr/composable-stage-graphs.md) states the
  composition model behind rollback, staleness and the walk ratchet;
  [round-loop-and-stage-graph.md](iclr/round-loop-and-stage-graph.md) reads
  AMAP-ML's LongHorizon-Harness against it and records what the stage graph
  should take from a round loop, and what it should not.

### Project notices

- **[star-activity-notice.md](star-activity-notice.md)** — maintainer
  statement on unusual star activity on the repository.

## Project-level documents

Outside this directory:

- [../README.md](../README.md) — overview, showcase, quick start.
- [../LICENSE](../LICENSE) — **AutoR is proprietary software, not open source.**
  Publication of the repository grants no right to use, run, modify, or fork
  it; any use requires written permission. [../NOTICE](../NOTICE) is the short
  form.
- [../CONTRIBUTING.md](../CONTRIBUTING.md) — how to propose and land changes,
  and the contribution-assignment terms that come with doing so.
- [../SECURITY.md](../SECURITY.md) — the security model, the sandbox
  trade-offs, and how to report a vulnerability.
- [../CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) — community expectations.

## Documentation conventions

- Paths written as `workspace/results/` are relative to a single run root,
  `runs/<run_id>/`.
- Paths written as `src/utils.py` are relative to the repository root.
- Stage identifiers are written in their canonical slug form
  (`03_study_design`). Every CLI flag that takes a stage also accepts `3` and
  `03`.
- Anything described as *validated* is checked in code, and the source of that
  check is named so you can read it yourself.
- Symbols are cited by name rather than by `file.py:NNN`. Line anchors drift
  with every refactor, and an anchor pointing at the wrong line is worse than
  no anchor; a symbol name can be grepped.
