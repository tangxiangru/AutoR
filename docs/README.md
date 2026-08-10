# AutoR Documentation

This directory is the reference documentation for AutoR. The
[root README](../README.md) is the project pitch; everything here is the
detail behind it.

## Start here

| If you want to… | Read |
| --- | --- |
| Install AutoR and run your first project end to end | [English Guide](tutorial_en.md) · [中文教程](tutorial_zh.md) |
| Look up a command-line flag | [CLI Reference](cli-reference.md) |
| Run AutoR unattended, or benchmark it on ResearchClawBench | [ResearchClawBench](researchclawbench.md) |
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
| Fix an error you just hit | [Troubleshooting](troubleshooting.md) |

## The whole documentation set

### User guides

- **[tutorial_en.md](tutorial_en.md)** — the full end-to-end user guide.
  Installation, first run, how to review each stage, how to write feedback
  that actually improves output, and the fastest path to a strong final PDF.
- **[tutorial_zh.md](tutorial_zh.md)** — the same guide in Chinese.

### Reference

- **[cli-reference.md](cli-reference.md)** — every flag on `main.py` and
  `studio.py`, what each one defaults to, what is persisted on resume, and
  which flags are mutually exclusive.
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
- **[researchclawbench-landscape.md](researchclawbench-landscape.md)** — how the
  other agents on the ResearchClawBench leaderboard score, which of their
  published numbers reproduce from the public data, and the same-model baseline
  any AutoR result has to be quoted against.

### Internals

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
