"""Tell an unusable backend apart from an unproductive one.

When a stage produces no summary at all, AutoR writes a local fallback draft, normalizes it
into the required section structure, and carries on. That is the right move when the model ran
and wrote something unusable: the run keeps its shape, the next attempt gets another go, and
the fallback is visibly a fallback.

It is the wrong move when the model never ran. A first live run of this workflow hit Vertex
quota exhaustion and every single call came back ``429 RESOURCE_EXHAUSTED``. AutoR responded
by manufacturing a structurally valid Stage 01 summary — every required heading present, so
`validate_stage_markdown` passed it — and moving on to attempt 2. Left alone it would have
spent the whole attempt budget, auto-skipped, and finished with a report assembled from
nothing but its own error messages.

That is the failure this module exists to prevent. A backend refusing every request is an
infrastructure problem, and the honest response is to stop and say which one, not to convert
it into research-shaped output. A run that cannot reach a model has not produced weak
findings; it has produced none.

The distinction is deliberately narrow. Only causes that no amount of retrying inside this run
will fix count as fatal — quota, credentials, a backend that is simply down. A model that ran
and wrote badly is not this, and keeps the fallback path it was designed for.
"""

from __future__ import annotations

import re

QUOTA = "quota"
AUTH = "auth"
UPSTREAM = "upstream"

#: Patterns that mean the request never reached a working model.
#:
#: Anchored on the shapes a CLI actually emits — ``API Error``, an HTTP status, a named
#: gRPC status — rather than on bare words. "quota" and "429" appear in ordinary research
#: prose, and a Stage 01 summary discussing rate limits must not read as a dead backend.
_SIGNATURES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (QUOTA, re.compile(r"RESOURCE_EXHAUSTED|Quota exceeded|rate[_ ]limit_error|\b429\b", re.IGNORECASE)),
    (AUTH, re.compile(
        r"\b40[13]\b|PERMISSION_DENIED|UNAUTHENTICATED|authentication_error|invalid[_ ]api[_ ]key",
        re.IGNORECASE)),
    (UPSTREAM, re.compile(
        r"\b5\d{2}\b|UNAVAILABLE|INTERNAL|overloaded_error|api_error|Connection error",
        re.IGNORECASE)),
)

#: A line has to look like a reported error before its status code counts for anything.
_ERROR_LINE = re.compile(r"API Error|error[\"']?\s*:|Error:|\bstatus\b|RESOURCE_EXHAUSTED|"
                         r"PERMISSION_DENIED|UNAUTHENTICATED|UNAVAILABLE", re.IGNORECASE)

_CAUSE_TEXT = {
    QUOTA: (
        "The model backend is refusing every request because the quota is exhausted. "
        "No amount of retrying inside this run will change that."
    ),
    AUTH: (
        "The model backend is rejecting this run's credentials. Retrying will not fix it."
    ),
    UPSTREAM: (
        "The model backend is failing every request. This is the provider, not the research."
    ),
}


def classify(text: str) -> str | None:
    """Name the infrastructure cause in captured backend output, or None.

    Every candidate line must look like a reported error *and* carry a recognised signature.
    Requiring both is what keeps a research summary that happens to discuss rate limiting from
    being read as a dead backend.
    """
    if not text:
        return None
    lines = [line for line in text.splitlines() if _ERROR_LINE.search(line)]
    if not lines:
        return None
    haystack = "\n".join(lines)
    for cause, pattern in _SIGNATURES:
        if pattern.search(haystack):
            return cause
    return None


def describe(cause: str, excerpt: str = "") -> str:
    """The message a human needs in order to know this is not their research failing."""
    head = _CAUSE_TEXT.get(cause, "The model backend is unusable.")
    body = (
        f"{head}\n\n"
        "AutoR stopped instead of writing a locally generated stage summary and continuing. "
        "A run that cannot reach a model has not produced weak findings, it has produced none, "
        "and a fallback draft here would have been indistinguishable from research at the end "
        "of the run."
    )
    if excerpt:
        body += f"\n\nBackend said:\n{excerpt.strip()[:600]}"
    return body


class BackendUnavailable(RuntimeError):
    """Raised when the backend has refused everything and the run should stop."""

    def __init__(self, cause: str, excerpt: str = "") -> None:
        self.cause = cause
        self.excerpt = excerpt
        super().__init__(describe(cause, excerpt))
