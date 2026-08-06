# Contributing to AutoR

Thanks for considering a contribution. AutoR is a small, deliberately
constrained codebase: stdlib-only, file-based, one loop, no framework. Changes
that keep it that way are the easiest to land.

- **Using AutoR?** Start with the [English Guide](docs/tutorial_en.md) or
  [中文教程](docs/tutorial_zh.md).
- **Hacking on AutoR?** [docs/development.md](docs/development.md) has setup,
  tests, conventions, and extension recipes.

---

## Read this before you start

**AutoR is proprietary software, not an open source project.** Read
[LICENSE](LICENSE) first. Two consequences matter before you write any code:

1. **Running AutoR requires written permission.** Publication of this
   repository grants no right to use, run, modify, or fork it. That includes
   running it locally to develop against, so obtain permission before you begin
   — see Section 5 of the LICENSE.
2. **Contributions are assigned to the copyright holder.** By opening a pull
   request you grant Xiangru Tang a perpetual, irrevocable, worldwide right to
   use, modify, distribute, and **relicense** your contribution under any
   terms, including proprietary terms, with no compensation or attribution
   owed to you. That is Section 6 of the LICENSE, and it is not negotiable per
   contribution. If you are not comfortable with it, or if your employer's
   IP agreement forbids it, do not submit code — a well-written issue is still
   genuinely valuable.

Contributions are welcome under those terms. They are not a route to obtaining
a license to the Software.

---

## Ways to help

| | |
| --- | --- |
| **Report a bug** | Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.yml). Include the command, the relevant `logs.txt` lines, and the stage's `run_manifest.json` entry. |
| **Request a feature** | Use the [feature request template](.github/ISSUE_TEMPLATE/feature_request.yml). Say what research workflow it unblocks — AutoR's roadmap is driven by real research chores, not by framework completeness. |
| **Improve the docs** | Use the [docs issue template](.github/ISSUE_TEMPLATE/docs_issue.yml), or send the fix directly. Documentation fixes need no prior discussion. |
| **Ask a question** | Use the [question template](.github/ISSUE_TEMPLATE/question.yml). |
| **Share a run** | Real runs — what worked, what the model got wrong, where you had to intervene — are among the most useful things you can contribute. |

---

## Development setup

```bash
git clone https://github.com/tangxiangru/AutoR.git
cd AutoR
python -m unittest discover -s tests -p "test_*.py"
```

That is all of it. Python 3.10+, no virtualenv step, no `pip install`, no
build. **AutoR has no third-party Python dependencies** and we would like to
keep it that way — a new dependency needs a reason that outweighs "this repo
runs anywhere Python does".

You do not need a backend CLI installed. Tests run against fakes, and
`--fake-operator` exercises the whole workflow without one.

---

## Before you open a pull request

```bash
python -m py_compile main.py studio.py src/*.py src/*/*.py tests/*.py
python -m unittest discover -s tests -p "test_*.py"
```

Both must pass. CI runs the same two steps on Python 3.12 (with slightly
narrower compile globs), so a green local run is a good predictor.

### Add a test

Every behaviour change needs one. The suite is stdlib `unittest`, it runs in
about ten seconds, and it works on temp directories — there is no reason not
to.

- New validation rule → `tests/test_utils_contracts.py`
- New artifact schema → the test module for that manifest
- Workflow behaviour → `tests/test_manager_smoke.py` or
  `tests/test_manager_workflow.py`
- Studio endpoint → `tests/test_studio_http.py`

A test that would pass before your change is not a test of your change.

### Match the surrounding code

See [docs/development.md](docs/development.md#code-conventions) for the full
list. The load-bearing ones:

- Frozen dataclasses with explicit `to_dict`/`from_dict` for anything written
  to disk.
- Validators return `list[str]` — they never raise and never print.
- Paths come from `RunPaths`, never from manual joins.
- Terminal output goes through `TerminalUI`.
- `from __future__ import annotations` and modern type annotations.

### Update the docs

If you change a flag, a schema, a validation rule, or an endpoint, update the
matching page under [docs/](docs/). A rule that is enforced but undocumented
reads as a bug to the next person who hits it.

---

## Pull requests

**Keep them focused.** One change per PR. A refactor bundled with a feature is
two PRs.

**Describe the behaviour change**, not just the diff:

- What was wrong or missing.
- What the change does.
- How you verified it — the test you added, or the run you did.
- Anything you deliberately left out.

**Do not add a changelog file.** Release notes are derived from PR
descriptions, so put the detail there instead.

**Draft PRs are welcome** for work in progress or for design feedback before
you invest in tests.

### What a reviewer will look for

- Does it hold the invariants? Approved memory as the only cross-stage
  channel; the filesystem as the only state; validation that is structural
  rather than semantic; nothing advancing without a human by default.
- Does the failure path degrade rather than crash? A corrupt artifact should
  produce a problem string, not kill a six-hour run.
- Is the new rule tested by something that would have failed before?
- Does it make AutoR more like a research workflow, or more like a framework?
  The first is the goal.

---

## Design principles

These are the reasons behind most review feedback. Full context in
[docs/architecture.md](docs/architecture.md).

**Human approval is the default, not a mode.** `--full-auto` exists for
unattended sweeps. It must never become the recommended path, and changes to
the automated reviewer should make it stricter rather than more permissive.

**Artifacts over prose.** A stage is judged by files that exist and parse. If
a change lets a stage pass on markdown alone, it is going the wrong way.

**The filesystem is the database.** No runtime services, no schema
migrations, no global state. A run directory is complete on its own.

**Structural validation only.** AutoR checks what a machine can be trusted to
check. It never claims the science is right, and it should not start
pretending to.

**Prompts before code.** Much of AutoR's behaviour lives in
`src/prompts/*.md`. If a prompt edit achieves the goal, prefer it.

### Out of scope

Generic multi-agent orchestration · database-backed runtime state · concurrent
stage execution · heavyweight platform abstractions · dashboard-first
productization.

These are not oversights. Each one has been considered and declined; a PR that
adds one will be closed with a pointer here.

---

## Licensing

Every contribution is submitted under Section 6 of [LICENSE](LICENSE), which
assigns the copyright holder a relicensable right over it. There is no separate
CLA to sign; opening a pull request is the act of agreement.

Do not add SPDX headers, license blocks, or copyright notices to individual
files. The repository carries a single license, held by a single copyright
holder, and per-file notices only create room for that to drift.

---

## Community

Be respectful and factual. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

For security issues, do **not** open a public issue — follow
[SECURITY.md](SECURITY.md).
