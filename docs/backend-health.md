# When the backend is the problem

The first live run of this workflow never reached a model. Vertex quota was exhausted and
every call came back:

```
API Error: Request rejected (429) · {"code":429,"message":"Quota exceeded for
aiplatform.googleapis.com/... base model: anthropic-claude-sonnet-4-5",
"status":"RESOURCE_EXHAUSTED"}
```

AutoR's response was to write a **local fallback stage summary**, normalize it into the
required section structure so it passed `validate_stage_markdown`, and continue to attempt 2.
Left alone it would have spent the attempt budget, auto-skipped up to `--max-auto-skips`
stages, and finished with a report assembled from its own error messages.

Nothing in the unit tests could have found that. It took running the thing.

## The distinction

The fallback path is *right* when the model ran and wrote something unusable: the run keeps
its shape, the next attempt gets another go, and the fallback is visibly a fallback.

It is *wrong* when the model never ran. A run that cannot reach a backend has not produced
weak findings — it has produced none, and a locally written summary is indistinguishable from
research by the end of the run.

So when a stage's primary attempt **and** its repair both produce nothing, the captured output
is classified before anything is manufactured:

| Cause | Recognised from |
| --- | --- |
| `quota` | `RESOURCE_EXHAUSTED`, `Quota exceeded`, `rate_limit_error`, `429` |
| `auth` | `PERMISSION_DENIED`, `UNAUTHENTICATED`, `401`/`403`, `invalid api key` |
| `upstream` | `UNAVAILABLE`, `overloaded_error`, `5xx`, connection errors |

Any of those stops the run with the cause named. Anything else keeps the fallback it was
designed for.

## Guarding the false positive

A Stage 01 literature survey about API economics could easily contain the words *"429"* and
*"quota exceeded"*. Aborting a run because its research summary discussed rate limiting would
be a worse bug than the one this fixes.

So a line must look like a **reported error** — `API Error`, an `"error":` field, a named gRPC
status — *and* carry a recognised signature. `"We sampled 429 households from the panel"`
classifies as nothing.

## What you see

```
+-- Backend unavailable ------------------------------------------+
| The model backend is refusing every request because the quota   |
| is exhausted. No amount of retrying inside this run will change |
| that.                                                           |
|                                                                 |
| AutoR stopped instead of writing a locally generated stage      |
| summary and continuing.                                         |
+-----------------------------------------------------------------+
```

The run is marked `failed` with `run.backend_unavailable`, and the backend's own words go in
`logs.txt` so the cause is not a guess.

## Limits worth knowing

- **It fires on the second failure, not the first.** By the time a fallback is being
  manufactured, the primary attempt and the repair have both already failed — one transient
  429 that then succeeds will not stop a run.
- **A backend that fails silently is invisible here.** Classification reads what the CLI
  printed; a backend that returns success with empty content still gets the fallback.
- **The signature list is a list.** A provider inventing a new error shape will be treated as
  a content failure until its pattern is added.
