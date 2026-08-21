# `rcb_tools` — the operator side of the benchmark arms

Everything in `docs/researchclawbench-arms.md` was produced by the scripts in this
directory. They were kept outside the repository until 2026-08-20, which meant the numbers
in that document had no reproducible provenance: the tool that produced a score, the flags
it ran under and the judge it installed all lived on one machine, in one home directory,
under no version control at all. Two of the defects the lab notebook records — a scorer
silently writing forty error stubs, and 721 score files that never recorded their judge —
were defects *in these files*, found only because someone happened to read them.

**These are operator scripts, not library code.** They are here for provenance and review,
not to be imported.

## They are machine-specific, and deliberately not parameterised

Almost every file hardcodes absolute paths for one host:

```
/home/robtang_google_com/AutoR          the checkout under test
/home/robtang_google_com/RCB            the benchmark
/rmeng_data/robtang/rcb_runs/<arm>/     where an arm's workspaces land
/home/robtang_google_com/rcb_results/   score directories and slurm logs
```

That is a property of the record, not an oversight to fix in a later pass. A `.sbatch` that
ran an arm is evidence of what that arm ran under; rewriting its paths to be portable makes
it a different script from the one the numbers came from. If these are ever needed on
another box, copy and edit — do not "clean up" the originals, because
`docs/researchclawbench-arms.md` cites their behaviour.

`slurm_*.sbatch` also carry the two environment knobs that are not CLI configuration:

```bash
export CLAUDE_STREAM_IDLE_TIMEOUT_MS=1800000
export CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS=1800000
```

A batch job that does not re-export those falls back to a 300 s floor, which kills any call
whose model thinks for five minutes before its first token — and what that removes is the
*hard* tasks, so the arm comes back looking easy.

## What each of the main files does

| file | what it is |
|:---|:---|
| `run_arm.py` | Runs one arm over a task list. Claims each task with an atomic `mkdir` under `<arm>/.claims/`, so several launchers can share one arm without racing; its TAKE branch re-adopts a task whose claim exists but whose work is neither running nor finished. |
| `test_claim_race.py` | Reproductions of five holes in that claim protocol, two of which were "fixes" that were themselves races. Not run by CI — CI discovers only `tests/`. |
| `score_arm.py` | Scores an arm into `~/rcb_results/<name>/`, one draw, totals only. Resumable, and caches on the **output name**, so a name that already holds results is never re-scored; use a fresh one to re-measure. |
| `score_items.py` | Same judge, but keeps the per-criterion verdicts, so a lagging task can be read against the rubric it was judged on. Refuses with rc=2 if handed an arm key where a runs-directory name belongs. |
| `gpt51_judge.py` | The benchmark's own judge, `gpt-5.1`, swapped into `evaluation.score` by `common.judged_scorer()`. Reads its key from `~/api.txt` (override with `RCB_JUDGE_KEY_FILE`); no key is stored here. |
| `topology_watch.py` | Waits for the `--stage-graph` ablation, scores it and writes the paired result. Gates on the runner's terminal status, not on report size — see below. |
| `common.py` | Shared paths and the judge swap. The one place `RUNS` and `RESULTS` are defined. |
| `tasks40.txt` | The forty task ids every full arm runs. |

## Two traps these files exist to document

**A scorer pointed at a directory that does not exist must not return forty results.**
`score_items.py` resolves its first argument as `RUNS/<name>`. `topology_watch.py` was
passing `run_arm.py`'s arm key (`topology_linear`) where the runs-directory name
(`topo_linear`) belongs, so every task resolved to "no workspace", the scorer wrote error
stubs for the whole arm and exited 0, and the watcher captured the output and dropped it.
The topology ablation ran for hours with its scoring silently dead. Both halves are fixed:
a missing directory is now rc=2 with the near-miss names printed, and the watcher reports a
non-zero exit instead of swallowing it.

**A report is live in the workspace throughout a run.** `collect_figures` trims
`report/images/` to the referenced set only at export, so a task scored while it is still
running is scored on a different image set — and image criteria carry 60.6% of this
benchmark's weight. Gate on the runner's own `completed`/`failed` status, never on
`report.md` clearing a byte threshold. The agent keeps writing for a median of 992 s after
the last write to `report.md`.

## Judge provenance

Score files written before 2026-08-20 record the *agent's* model and not the judge; 721 of
them across 20 directories assert `gpt-5.1` only by their directory being named `gpt51_*`
or `cap15_*`. Both scorers now write `judge_model`, read off the class
`common.judged_scorer()` actually installs rather than off a constant. The older files are
not retro-stamped — writing provenance after the fact is worse than not having it — and
`~/rcb_results/PROVENANCE.md` records which directories are affected and which have a
checkable counterpart.

## History

This directory was under its own local git repository from 2026-08-19, with five commits,
before being brought here as one. That repository had no remote; the commits are not lost,
they are folded into this one.
