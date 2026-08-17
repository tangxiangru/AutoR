---
name: latex-repair
description: Use when a LaTeX build fails or produces a broken PDF in Stage 07 (Writing) — undefined control sequences, missing style packages, unresolved citations or references, float placement blowing the page budget, or a build_log.txt full of errors you need to triage.
stages: 07_writing
---

# LaTeX repair

Stage 07's gate wants `workspace/writing/main.tex`, section files, a
bibliography, a compiled PDF, and `workspace/artifacts/build_log.txt`. When the
build fails, the loop to avoid is: change something, recompile, read the same
error, change something else. LaTeX reports the *first* thing that broke, and
one real cause usually generates a cascade of downstream errors.

## Triage order

Read `build_log.txt` from the top and fix in this order. Recompile after each
class, not after each edit.

1. **Missing style package** — `LaTeX Error: File 'neurips_2025.sty' not found`.
   AutoR does not vendor official style files (`templates/registry.yaml` says so
   and carries the venue's `official_url`). Either fetch the style package to
   `workspace/writing/`, or fall back to a standard class and record the
   substitution honestly in the stage summary. Do **not** silently switch venue.
2. **Undefined control sequence** — a command from a package that is not loaded,
   or a typo. Check the preamble before assuming the command is wrong.
3. **Missing `$` / runaway argument** — almost always an unescaped `_`, `%`, `&`
   or `#` in prose that came from a variable name or a file path. These are
   common when text was assembled from JSON results.
4. **Undefined references and citations** — `LaTeX Warning: Citation 'x'
   undefined`. Requires a bibtex/biber pass and then two more LaTeX passes.
   A single compile will always report these.
5. **Overfull boxes and float drift** — cosmetic until they push the paper past
   the venue page limit, at which point they are a submission blocker.

## Compile sequence

A one-shot compile cannot resolve cross-references or citations. The minimum is:

```
pdflatex main.tex   # writes .aux
bibtex main         # or biber, per the venue's citation_style
pdflatex main.tex   # resolves citations
pdflatex main.tex   # resolves page-dependent references
```

If `latexmk` is available, `latexmk -pdf main.tex` does this correctly and is
the better default. Whatever you run, tee the full output to
`workspace/artifacts/build_log.txt` — the gate reads that file, and a log
containing only the last pass hides the errors from the earlier ones.

## When the toolchain is not installed

If no LaTeX toolchain exists in the environment, say so in the stage summary
and in `build_log.txt`, and do not fabricate a PDF. A file named `main.pdf`
that is not a PDF fails later and more confusingly than a missing one. Check
whether the run should be using `--output-format markdown` instead — that path
has no LaTeX dependency at all.

## Errors that are really content problems

| Log line | Actual cause |
| --- | --- |
| `Citation 'foo2024' undefined` after a full bibtex cycle | The key is not in the `.bib`. Use the `citation-discipline` skill; do not invent the entry. |
| `Reference 'fig:main' undefined` | The figure was cited before it was written, or the label is on the wrong element. |
| `File 'figures/main.pdf' not found` | Stage 06 wrote figures under `workspace/figures/`; the path in the `.tex` is relative to the main file, not to the workspace root. |
| Page count over the venue limit | Not a LaTeX bug. Check `templates/registry.yaml` for `page_limit` and `refs_in_limit`, then cut content rather than shrinking margins — most venues reject the second. |

## Before you finish

- The PDF opens and has the expected number of pages.
- No `??` or `[?]` markers survive in the rendered text.
- `build_log.txt` contains the whole build, including the passes that succeeded.
- If a style package was substituted, the stage summary says which and why.
