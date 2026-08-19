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
#:
#: **gRPC status names are matched case-sensitively.** They are SCREAMING_SNAKE constants
#: on the wire, and the lowercase English words they are spelled from are ordinary research
#: prose. Over 1,110 real stage outputs from the topology ablation's run trees — text the
#: model wrote, not backend output — the case-insensitive version reads 263 (23.7%) as a
#: dead backend, on lines like "stress-tests delayed and unavailable Scotland-England
#: boundary expansion". The case-sensitive version reads none of them, and still classifies
#: all 18 archived `403 ACCESS_TOKEN_SCOPE_INSUFFICIENT` captures as `auth`.
_TOKENS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (QUOTA, re.compile(r"RESOURCE_EXHAUSTED|(?i:Quota exceeded|rate[_ ]limit_error)")),
    (AUTH, re.compile(
        r"PERMISSION_DENIED|UNAUTHENTICATED|(?i:authentication_error|invalid[_ ]api[_ ]key)")),
    (UPSTREAM, re.compile(r"UNAVAILABLE|INTERNAL|(?i:overloaded_error|api_error|Connection error)")),
)

#: Numeric statuses, which mean nothing on their own. A bare ``\b5\d{2}\b`` matched the
#: line number in a prompt echo — ``520\t  - Status: carried | Tested by: H2; H3`` — so a
#: three-digit number only counts where the same line also frames it as a status.
_CODES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (QUOTA, re.compile(r"\b429\b")),
    (AUTH, re.compile(r"\b40[13]\b")),
    (UPSTREAM, re.compile(r"\b5\d{2}\b")),
)

#: What has to be on the line before a bare number is read as an HTTP status.
_CODE_CONTEXT = re.compile(r"(?i:API Error|HTTP/|status[_ ]code)|\"(?:code|status)\"\s*:")

#: A line has to look like a reported error before its status code counts for anything.
#:
#: ``\bstatus\b`` used to be in here, which made every ``- Status: carried`` line of
#: AutoR's own stage formatting an "error line"; with the bare 5xx pattern above, two pieces
#: of ordinary formatting were enough to declare the provider down. The gRPC names stay
#: case-sensitive here for the same reason they are above — and note that a name in *both*
#: lists is a token that satisfies the error-line gate and the signature gate by itself,
#: which is the two-gate design collapsing to one. That is tolerable for a SCREAMING_SNAKE
#: wire constant and was not tolerable for an English word.
_ERROR_LINE = re.compile(r"(?i:API Error|error[\"']?\s*:|Error:)|RESOURCE_EXHAUSTED|"
                         r"PERMISSION_DENIED|UNAUTHENTICATED|UNAVAILABLE")

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
    # Line by line, not over the joined lines. Joining let a bare "520" on one line be read
    # together with the word "Error:" on another, so two unrelated fragments of a stage
    # summary could compose into a provider outage that appeared nowhere in the text.
    for line in text.splitlines():
        if not _ERROR_LINE.search(line):
            continue
        for cause, pattern in _TOKENS:
            if pattern.search(line):
                return cause
        if _CODE_CONTEXT.search(line):
            for cause, pattern in _CODES:
                if pattern.search(line):
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
