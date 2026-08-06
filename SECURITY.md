# Security Policy

## Reporting a vulnerability

Please do **not** open a public issue for a security vulnerability.

Report it privately through
[GitHub Security Advisories](https://github.com/tangxiangru/AutoR/security/advisories/new),
which lets us discuss and fix the issue before it is disclosed.

Please include:

- What the issue is and where in the code it lives.
- How to reproduce it, ideally as a minimal case.
- What an attacker could achieve.
- Any suggested fix.

We will acknowledge the report, work with you on a fix, and credit you in the
advisory unless you prefer otherwise.

## Supported versions

AutoR is developed on `main`. Security fixes land there. There are no
long-term support branches.

---

## The security model, and why it matters

Read this before running AutoR on anything you care about. **AutoR is a
harness that runs a coding agent with permission prompts disabled, on your
machine, with your credentials.** That is the design — it is what makes an
unattended multi-hour research run possible — and it has consequences you
should choose deliberately rather than discover.

### What AutoR grants the agent

Every stage runs the backend CLI with its approval gate off:

```bash
claude --permission-mode bypassPermissions --dangerously-skip-permissions ...
codex exec --sandbox workspace-write ...
```

In practice the agent can read and write files, run arbitrary shell commands,
install packages, and reach the network — under **your** user account, with
whatever credentials that account has.

AutoR does not sandbox this. It never asks the agent's permission system to
confirm an action, because a run that stops every few minutes for a
confirmation is not a run you can leave overnight.

**Treat an AutoR run the way you would treat running a script you have not
read.**

### The threat that matters most: the goal is an instruction

Your research goal, your `--resources`, your `--paper-corpus`, and the web
pages the agent reads during a literature survey all become part of a prompt
that drives a shell-capable agent. A malicious PDF or web page can attempt
prompt injection, and the agent has no sandbox to fall back on.

- Only ingest resources you trust.
- Be wary of goals that direct the agent to fetch and act on arbitrary
  external content.
- Read `logs_raw.jsonl` if a run does something surprising — every tool call
  is recorded there.

### Codex sandbox modes

For `--operator codex`, AutoR exposes the Codex CLI's sandbox:

| Mode | Grants |
| --- | --- |
| `read-only` | Read the workspace, no writes. |
| `workspace-write` | **Default.** Read and write inside the run workspace. |
| `danger-full-access` | **No sandbox.** Arbitrary local commands, SSH, remote hosts, external GPUs. |

Use `danger-full-access` only when a specific verified experiment needs remote
execution, and only for a goal and resource set you trust completely. It is
opt-in for a reason, and it is recorded in `run_config.json` so a resumed run
does not silently inherit it by accident — check that field before resuming
someone else's run.

The Claude backend has no equivalent tiering: it runs with permissions
bypassed. If you need containment there, run AutoR inside a container or VM.

### Recommended containment

For untrusted goals or untrusted input materials:

- Run inside a container or a dedicated VM.
- Use a user account with no access to credentials, SSH keys, or cloud
  configuration you would not hand to a stranger.
- Point `--runs-dir` at an isolated volume.
- Do not run AutoR in a directory that also contains secrets — the agent can
  read the filesystem.

---

## Studio

`python studio.py` starts an HTTP server with **no authentication and no
authorization**. Any client that can reach it can:

- list, read, and traverse every run directory
- read arbitrary files under a run root
- start new Claude-backed agent runs
- approve stages, which advances a run past its human gate

It binds to `127.0.0.1` by default, which is the right default. **Do not use
`--host 0.0.0.0` on an untrusted network.** For remote access use an SSH
tunnel:

```bash
ssh -L 8000:127.0.0.1:8000 you@host
# then browse http://127.0.0.1:8000/studio/ locally
```

Path traversal is guarded — static asset and run-file handlers reject paths
that escape their root — but that is a single control, not a substitute for
network isolation.

---

## Secrets

**AutoR stores no credentials.** Backend authentication belongs to the
`claude` or `codex` CLI and is configured there.

The one key AutoR reads directly is the optional Gemini key for
`--research-diagram`, from `GOOGLE_API_KEY`, `GEMINI_API_KEY`, or
`configs/diagram_config.yaml` — which is gitignored and should stay that way.

### Before sharing a run directory

Run directories are designed to be shareable, and are therefore easy to share
carelessly. Before you publish one, check:

| Path | May contain |
| --- | --- |
| `user_input.txt`, `memory.md` | your unpublished research direction |
| `prompt_cache/` | every prompt, including ingested resource content |
| `logs_raw.jsonl` | every command run, every file path touched, command output |
| `workspace/` | your data, and anything the agent copied into it |
| `intake_context.json` | absolute paths to your local files |

`runs/` is gitignored so a run cannot be committed by accident. That protects
the repository, not a tarball you email to a collaborator.

---

## What is out of scope

- **Agent behaviour.** AutoR cannot prevent a model from writing bad or
  harmful code. Structural validation checks that files exist and parse, not
  what they do. Review generated code before running it anywhere that matters.
- **Backend CLI vulnerabilities.** Report those to Anthropic or OpenAI
  respectively.
- **The absence of a sandbox.** That is a documented design decision, not a
  vulnerability. A concrete escape from a control AutoR *does* claim — the
  Codex sandbox mode, the Studio path-traversal guards, the gitignore of
  secrets — is in scope, and we want to hear about it.
