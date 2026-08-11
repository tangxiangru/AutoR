"""Think hard, but only where thinking hard pays.

AutoR spends the same effort on every step. Most steps deserve that: copying a dataset,
writing a plotting script, filling in a section. A few do not. The choice of identification
strategy, the reading of an anomalous result, the decision about what the central claim is —
those are the places a human researcher stops, argues with colleagues, reads for a day, and
sits with it. Doing them at the same tempo as the mechanical steps is how a run produces work
that is complete and shallow.

So this module lets the executing agent **raise a crux**: name a specific question it is stuck
on, say what breaks if it gets it wrong, and ask for either more perspectives, expert
grounding, or both. AutoR convenes a focused deliberation on that one question and hands back
a resolution the next attempt can use.

**Why selective and not uniform.** The pre-registered comparison in
`arXiv:2607.14713 <https://arxiv.org/abs/2607.14713>`_ found multi-agent deliberation losing
to a single pass when applied uniformly to every paper — and its authors close by saying the
design "does not identify the occasions on which the more elaborate tools would pay". That is
the open question, and it is the one this answers: deliberation is expensive, so spend it only
where the agent doing the work says it is stuck, and then measure whether it changed anything.

**What makes this different from the two existing panels.** :mod:`src.review_panel` judges a
finished draft and converges on a gate decision. :mod:`src.ideation_panel` generates candidates
and stays diverged. Neither answers a *question*. A crux deliberation takes a proposition,
collects positions that must argue against themselves, and resolves to an answer that names
its own falsifier — the thing that would change it. An answer with no stated falsifier is an
opinion, and the point of stopping to think was to get past opinions.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .approval_agent import AutomatedReviewer
from .terminal_ui import TerminalUI
from .utils import (
    RunPaths,
    StageSpec,
    append_log_entry,
    read_text,
    truncate_text,
    write_text,
)


#: Where the executing agent raises a crux. A file rather than a prompt convention: the
#: operator is a coding agent with file tools, and a file is unambiguous and inspectable.
REQUEST_FILENAME = "deliberation_request.json"

#: Where resolutions accumulate, one per crux, for the run and for later stages to read.
LEDGER_FILENAME = "deliberations.json"

#: How many cruxes a run may escalate by default. "Think hard here" is only meaningful if it
#: is scarce; an agent that can escalate everything has not prioritised anything.
DEFAULT_MAX_DELIBERATIONS = 3

#: Below this a question is too vague to deliberate — "what should we do about the data?" has
#: no answer, and a panel asked it will produce five essays.
MIN_QUESTION_CHARS = 25

HELP_KINDS = ("perspectives", "expertise", "both")


@dataclass(frozen=True)
class Voice:
    """One participant in a crux deliberation."""

    key: str
    title: str
    charter: str
    backend: str | None = None
    model: str | None = None


DEFAULT_VOICES: tuple[Voice, ...] = (
    Voice(
        key="theorist",
        title="Theorist",
        charter=(
            "Answer from what the theory requires. Which option is consistent with the "
            "mechanism the run has committed to, and which one quietly assumes something the "
            "theory does not license?"
        ),
    ),
    Voice(
        key="empiricist",
        title="Empiricist",
        charter=(
            "Answer from what the data can actually support. Which option can be estimated "
            "with the data in this run, at a precision that would let anyone distinguish the "
            "answers? An option that is right in principle and unidentified in practice is the "
            "wrong answer here."
        ),
    ),
    Voice(
        key="critic",
        title="Critic",
        charter=(
            "Answer by finding the failure. For each option, name the way it goes wrong and how "
            "a referee would attack it. You are allowed to conclude that both options are wrong "
            "and the question is mis-posed — say so if it is true."
        ),
    ),
    Voice(
        key="pragmatist",
        title="Pragmatist",
        charter=(
            "Answer from what this run can finish. Weigh the cost of each option against the "
            "time and artifacts available, and say plainly when the more rigorous option is out "
            "of reach — but never dress up the cheap option as the correct one."
        ),
    ),
)

VOICES_BY_KEY = {voice.key: voice for voice in DEFAULT_VOICES}


def resolve_voices(keys: list[str] | None) -> tuple[Voice, ...]:
    if not keys:
        return DEFAULT_VOICES
    voices: list[Voice] = []
    for key in keys:
        normalized = key.strip().lower()
        if normalized not in VOICES_BY_KEY:
            known = ", ".join(sorted(VOICES_BY_KEY))
            raise ValueError(f"Unknown deliberation voice: {key}. Known voices: {known}.")
        voice = VOICES_BY_KEY[normalized]
        if voice not in voices:
            voices.append(voice)
    return tuple(voices)


def apply_voice_models(voices: tuple[Voice, ...], assignments: list[str] | None) -> tuple[Voice, ...]:
    """Assign a backend and model per voice from ``voice=[backend:]model`` strings."""
    if not assignments:
        return voices
    by_key = {voice.key: voice for voice in voices}
    updated = dict(by_key)
    for raw in assignments:
        if "=" not in raw:
            raise ValueError(
                f"Bad deliberation model assignment: {raw!r}. Expected voice=model or voice=backend:model."
            )
        key, _, spec = raw.partition("=")
        key, spec = key.strip().lower(), spec.strip()
        if key not in by_key:
            known = ", ".join(sorted(by_key))
            raise ValueError(f"Unknown deliberation voice in model assignment: {key}. Seated: {known}.")
        if not spec:
            raise ValueError(f"Bad deliberation model assignment: {raw!r}. No model given.")
        backend, _, model = spec.partition(":") if ":" in spec else (None, "", spec)
        model = model.strip()
        if not model:
            raise ValueError(f"Bad deliberation model assignment: {raw!r}. No model given.")
        current = updated[key]
        updated[key] = Voice(**{**current.__dict__, "backend": backend or current.backend, "model": model})
    return tuple(updated[voice.key] for voice in voices)


# ---------------------------------------------------------------------------
# The request
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CruxRequest:
    question: str
    why_it_matters: str = ""
    already_considered: tuple[str, ...] = ()
    working_answer: str = ""
    help_wanted: str = "both"
    stage_slug: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_requests(payload: Any, *, stage: StageSpec) -> list[CruxRequest]:
    """Read crux requests the executing agent left behind.

    Tolerant of shape — a single object or a list — because this file is written by a model
    mid-stage, and a malformed escalation should cost the escalation, not the stage.
    """
    entries = payload if isinstance(payload, list) else [payload]
    requests: list[CruxRequest] = []
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        question = str(raw.get("question") or "").strip()
        if len(question) < MIN_QUESTION_CHARS:
            continue
        considered = raw.get("already_considered")
        help_wanted = str(raw.get("help_wanted") or "both").strip().lower()
        requests.append(
            CruxRequest(
                question=question,
                why_it_matters=str(raw.get("why_it_matters") or "").strip(),
                already_considered=tuple(
                    str(item).strip() for item in considered if str(item).strip()
                ) if isinstance(considered, list) else (),
                working_answer=str(raw.get("working_answer") or raw.get("current_answer") or "").strip(),
                help_wanted=help_wanted if help_wanted in HELP_KINDS else "both",
                stage_slug=stage.slug,
            )
        )
    return requests


def read_requests(paths: RunPaths, stage: StageSpec) -> list[CruxRequest]:
    path = paths.notes_dir / REQUEST_FILENAME
    if not path.exists():
        return []
    try:
        payload = json.loads(read_text(path))
    except (OSError, json.JSONDecodeError):
        return []
    return parse_requests(payload, stage=stage)


def clear_requests(paths: RunPaths) -> None:
    """Consume the request file so one crux is not deliberated twice."""
    path = paths.notes_dir / REQUEST_FILENAME
    if path.exists():
        path.unlink()


# ---------------------------------------------------------------------------
# The result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Position:
    voice: str
    title: str
    backend: str
    model: str
    answer: str
    argument: str = ""
    against_self: str = ""
    failed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Resolution:
    request: CruxRequest
    positions: list[Position] = field(default_factory=list)
    brief: str = ""
    answer: str = ""
    reason: str = ""
    falsifier: str = ""
    dissent: str = ""
    voice_calls: int = 0
    changed_the_answer: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "brief": self.brief,
            "positions": [position.to_dict() for position in self.positions],
            "answer": self.answer,
            "reason": self.reason,
            "falsifier": self.falsifier,
            "dissent": self.dissent,
            "voice_calls": self.voice_calls,
            "distinct_answers": self.distinct_answers,
            "unreachable": self.unreachable,
            "changed_the_answer": self.changed_the_answer,
            "verdict": self.verdict(),
        }

    @property
    def unreachable(self) -> int:
        """Voices whose backend never answered.

        Kept separate from "the voice answered and said nothing useful". A panel that could
        not be convened and a panel that convened and added nothing are different outcomes,
        and reporting them with one sentence hides an outage behind a research finding.
        """
        return sum(1 for position in self.positions if position.failed)

    @property
    def all_voices_unreachable(self) -> bool:
        return bool(self.positions) and self.unreachable == len(self.positions)

    @property
    def distinct_answers(self) -> int:
        from .ideation_panel import similarity

        answers = [position.answer for position in self.positions if position.answer and not position.failed]
        distinct: list[str] = []
        for answer in answers:
            if not any(similarity(answer, kept) >= 0.5 for kept in distinct):
                distinct.append(answer)
        return len(distinct)

    def verdict(self) -> str:
        """Whether stopping to think was worth the calls it cost."""
        if self.all_voices_unreachable:
            return (
                f"No voice could be reached ({self.unreachable} of {len(self.positions)} "
                "failed); the panel never sat. The stage keeps its own answer, and this crux "
                "went un-deliberated rather than being settled."
            )
        if not self.answer:
            unreachable = (
                f" {self.unreachable} of {len(self.positions)} voice(s) could not be reached."
                if self.unreachable
                else ""
            )
            return (
                "The deliberation produced no answer; the stage keeps its own." + unreachable
            )
        if self.changed_the_answer is False:
            return (
                f"The panel reached the same answer the agent already had, at {self.voice_calls} "
                "calls. This crux did not need escalating."
            )
        if self.changed_the_answer is True:
            return (
                f"The panel reached a different answer than the agent's working one, at "
                f"{self.voice_calls} calls, from {self.distinct_answers} distinct position(s)."
            )
        return (
            f"Resolved from {self.distinct_answers} distinct position(s) at {self.voice_calls} "
            "calls; the agent had no working answer to compare against."
        )


# ---------------------------------------------------------------------------
# The deliberation
# ---------------------------------------------------------------------------


class CruxPanel:
    """Convene a focused deliberation on one question the agent got stuck on."""

    def __init__(
        self,
        voices: tuple[Voice, ...] = DEFAULT_VOICES,
        *,
        backend_name: str,
        model: str,
        fake_mode: bool = False,
        ui: TerminalUI | None = None,
        stage_timeout: int = 14400,
        max_deliberations: int = DEFAULT_MAX_DELIBERATIONS,
    ) -> None:
        if not voices:
            raise ValueError("A crux deliberation needs at least one voice.")
        self.voices = voices
        self.backend_name = backend_name
        self.model = model
        self.fake_mode = fake_mode
        self.ui = ui or TerminalUI()
        self.max_deliberations = max(0, max_deliberations)
        self.spent = 0
        self._members = {
            voice.key: AutomatedReviewer(
                voice.backend or backend_name,
                model=voice.model or model,
                fake_mode=fake_mode,
                ui=self.ui,
                stage_timeout=stage_timeout,
            )
            for voice in voices
        }

    @property
    def budget_left(self) -> int:
        return max(0, self.max_deliberations - self.spent)

    def deliberate(
        self, *, paths: RunPaths, stage: StageSpec, attempt_no: int, request: CruxRequest
    ) -> Resolution | None:
        """Run one crux to a resolution, or None when the budget is spent."""
        if self.fake_mode or self.budget_left == 0:
            return None
        self.spent += 1
        resolution = Resolution(request=request)

        if request.help_wanted in ("expertise", "both"):
            resolution.brief = self._expert_brief(paths, stage, attempt_no, request)

        for voice in self.voices:
            member = self._members[voice.key]
            self.ui.show_status(f"Crux deliberation: {voice.title} is thinking...", level="info")
            exit_code, stdout_text, _stderr = member.run_prompt(
                paths=paths,
                stage=stage,
                attempt_no=attempt_no,
                prompt=self._position_prompt(paths, request, voice, resolution.brief),
                label=f"crux_{voice.key}",
            )
            resolution.voice_calls += 1
            payload = member._extract_json_payload(stdout_text) if exit_code == 0 else None  # noqa: SLF001
            if not isinstance(payload, dict) or not str(payload.get("answer") or "").strip():
                resolution.positions.append(
                    Position(voice=voice.key, title=voice.title, backend=member.backend_name,
                             model=member.model, answer="", failed=True)
                )
                continue
            resolution.positions.append(
                Position(
                    voice=voice.key,
                    title=voice.title,
                    backend=member.backend_name,
                    model=member.model,
                    answer=str(payload["answer"]).strip(),
                    argument=str(payload.get("argument") or "").strip(),
                    against_self=str(payload.get("against_self") or payload.get("strongest_objection") or "").strip(),
                )
            )

        self._resolve(paths, stage, attempt_no, resolution)
        return resolution

    def _expert_brief(
        self, paths: RunPaths, stage: StageSpec, attempt_no: int, request: CruxRequest
    ) -> str:
        """Ground the question in what the run already knows before anyone opines.

        Opinions arrive faster than evidence, so the evidence goes first. A panel that argues
        before reading is a panel arguing from priors.
        """
        member = self._members[self.voices[0].key]
        self.ui.show_status("Crux deliberation: assembling the expert brief...", level="info")
        exit_code, stdout_text, _stderr = member.run_prompt(
            paths=paths,
            stage=stage,
            attempt_no=attempt_no,
            prompt=(
                "# AutoR Crux: Expert Brief\n\n"
                "Before a panel argues about the question below, establish what is already "
                "known. You are not answering the question — you are giving the panel the "
                "ground truth it should argue from.\n\n"
                "Read the run's literature directory and any relevant installed skill. Report:\n\n"
                "- what the field's standard practice is on this question, and where it is contested\n"
                "- what this run's own artifacts already settle or rule out\n"
                "- the specific facts a wrong answer here would contradict\n\n"
                "Prose, under 400 words, no recommendation. Say plainly where you found nothing.\n\n"
                f"# Question\n\n{request.question}\n\n"
                f"# Why It Matters\n\n{request.why_it_matters or '(not stated)'}\n\n"
                f"# Literature\n\n`{paths.literature_dir.resolve()}`\n\n"
                f"# Workspace\n\n`{paths.workspace_root.resolve()}`\n\n"
                "# Approved Memory\n\n"
                f"{truncate_text(_excerpt(paths.memory), max_chars=8000)}\n"
            ),
            label="crux_brief",
        )
        return stdout_text.strip() if exit_code == 0 else ""

    def _position_prompt(self, paths: RunPaths, request: CruxRequest, voice: Voice, brief: str) -> str:
        considered = (
            "\n".join(f"- {item}" for item in request.already_considered)
            if request.already_considered
            else "- (the agent did not say)"
        )
        return (
            f"# AutoR Crux Deliberation: {voice.title}\n\n"
            "The agent doing this research stopped and said it is stuck on one question. You are "
            "one of several people it pulled in. Answer the question — do not review the stage, "
            "do not broaden the scope, and do not hedge into 'it depends' without saying what it "
            f"depends on.\n\n## Your Angle\n\n{voice.charter}\n\n"
            "## Discipline\n\n"
            "- Commit to an answer. A panel of maybes resolves nothing.\n"
            "- Then argue **against your own answer** as hard as you can. The strongest objection "
            "to your position is the most useful thing you can contribute, and a position with no "
            "stated weakness has not been thought about.\n"
            "- Ground claims in the run's artifacts and literature, not in general knowledge.\n"
            "- If the question is mis-posed, say what the right question is instead of answering "
            "the wrong one.\n\n"
            "## Return Format\n\n"
            "Return JSON only:\n"
            '{"answer":"","argument":"","against_self":""}\n\n'
            f"# The Question\n\n{request.question}\n\n"
            f"# Why It Matters\n\n{request.why_it_matters or '(not stated)'}\n\n"
            f"# What The Agent Already Considered\n\n{considered}\n\n"
            + (f"# The Agent's Working Answer\n\n{request.working_answer}\n\n" if request.working_answer else "")
            + (f"# Expert Brief\n\n{brief}\n\n" if brief else "")
            + "# Research Goal\n\n"
            f"{truncate_text(_excerpt(paths.user_input), max_chars=3000)}\n\n"
            "# Approved Memory\n\n"
            f"{truncate_text(_excerpt(paths.memory), max_chars=8000)}\n"
        )

    def _resolve(
        self, paths: RunPaths, stage: StageSpec, attempt_no: int, resolution: Resolution
    ) -> None:
        live = [position for position in resolution.positions if not position.failed]
        if not live:
            return

        member = self._members[self.voices[0].key]
        self.ui.show_status("Crux deliberation: resolving...", level="info")
        positions = "\n\n".join(
            f"**Voice {chr(ord('A') + index)}**\nAnswer: {position.answer}"
            + (f"\nArgument: {position.argument}" if position.argument else "")
            + (f"\nStrongest objection to their own answer: {position.against_self}" if position.against_self else "")
            for index, position in enumerate(live)
        )
        exit_code, stdout_text, _stderr = member.run_prompt(
            paths=paths,
            stage=stage,
            attempt_no=attempt_no,
            prompt=(
                "# AutoR Crux: Resolution\n\n"
                "Several people answered the question below, each having also argued against "
                "themselves. Turn that into one answer the research can act on. Their identities "
                "are withheld so you weigh each on its argument.\n\n"
                "## What The Answer Must Contain\n\n"
                "- **answer** — what the research should do, concretely enough to act on today.\n"
                "- **reason** — why, in terms of the evidence, not the vote count. One well-argued "
                "position outranks three assertions.\n"
                "- **falsifier** — what observation or check would change this answer. An answer "
                "that nothing could overturn is an opinion, and the point of stopping to think "
                "was to get past opinions. This field may not be empty.\n"
                "- **dissent** — the strongest surviving objection, kept rather than smoothed away.\n\n"
                "Return JSON only:\n"
                '{"answer":"","reason":"","falsifier":"","dissent":""}\n\n'
                f"# The Question\n\n{resolution.request.question}\n\n"
                + (f"# Expert Brief\n\n{resolution.brief}\n\n" if resolution.brief else "")
                + f"# Positions\n\n{positions}\n"
            ),
            label="crux_resolve",
        )
        resolution.voice_calls += 1
        if exit_code != 0:
            return
        payload = member._extract_json_payload(stdout_text)  # noqa: SLF001
        if not isinstance(payload, dict):
            return
        resolution.answer = str(payload.get("answer") or "").strip()
        resolution.reason = str(payload.get("reason") or "").strip()
        resolution.falsifier = str(payload.get("falsifier") or "").strip()
        resolution.dissent = str(payload.get("dissent") or "").strip()

        if resolution.request.working_answer and resolution.answer:
            from .ideation_panel import similarity

            resolution.changed_the_answer = (
                similarity(resolution.answer, resolution.request.working_answer) < 0.5
            )


def _excerpt(path) -> str:
    return read_text(path).strip() if path.exists() else "(missing)"


# ---------------------------------------------------------------------------
# Prompt blocks and records
# ---------------------------------------------------------------------------


def escalation_offer(paths: RunPaths, budget_left: int) -> str:
    """The block that tells a stage it is allowed to stop and think."""
    if budget_left <= 0:
        return (
            "# Raising A Crux\n\n"
            "This run has spent its deliberation budget. Work through remaining difficulties "
            "yourself and record the ones you are least sure about in `Decision Ledger`."
        )
    return (
        "# Raising A Crux\n\n"
        "Most of this stage is execution: do it. But if you hit a question where the right "
        "answer is genuinely unclear and getting it wrong would invalidate work downstream, you "
        "may stop and pull in help rather than guessing and moving on.\n\n"
        f"Write `{(paths.notes_dir / REQUEST_FILENAME).resolve()}`:\n\n"
        "```json\n"
        '{"question": "the specific question, answerable and decidable",\n'
        ' "why_it_matters": "what breaks downstream if this is wrong",\n'
        ' "already_considered": ["what you have already ruled out, and why"],\n'
        ' "working_answer": "your best answer right now, so the panel can disagree with it",\n'
        ' "help_wanted": "perspectives | expertise | both"}\n'
        "```\n\n"
        "Then **finish the stage with your working answer**. A panel will be convened on that "
        "question and its resolution handed to you on the next pass; you are not blocked.\n\n"
        f"You may raise {budget_left} more this run. Spend them on the questions a reviewer would "
        "attack first, not on things you can settle by reading a file. An escalation that turns "
        "out to have had an obvious answer costs the run a round it needed elsewhere."
    )


def format_resolution_for_prompt(resolutions: list[Resolution]) -> str:
    """Hand the resolutions back to the stage that asked for them."""
    if not resolutions:
        return ""
    lines = [
        "You raised the following as cruxes. A panel deliberated on each and resolved it. "
        "Apply the answer, or say in `Decision Ledger` why you are departing from it — these "
        "are conclusions with reasons attached, not orders, and the dissent is included so you "
        "can weigh it yourself.",
        "",
    ]
    for index, resolution in enumerate(resolutions, start=1):
        lines.extend([f"### Crux {index}: {resolution.request.question}", ""])
        if resolution.answer:
            lines.extend([f"**Answer.** {resolution.answer}", ""])
        if resolution.reason:
            lines.extend([f"**Why.** {resolution.reason}", ""])
        if resolution.falsifier:
            lines.extend([f"**What would change this.** {resolution.falsifier}", ""])
        if resolution.dissent:
            lines.extend([f"**Surviving dissent.** {resolution.dissent}", ""])
        if not resolution.answer:
            lines.extend(["The panel did not reach an answer; keep your own and note the uncertainty.", ""])
    return "\n".join(lines).rstrip() + "\n"


#: How alike two crux questions must read before the second is treated as a repeat.
#: Calibrated on the questions from a live run rather than guessed:
#:
#:     verbatim re-escalation across attempts   1.00   <- the observed failure
#:     paraphrase of the same question          0.34
#:     narrowed follow-up that builds on the    0.21
#:       answer, i.e. a genuinely new crux
#:     a different crux from the same stage     0.06
#:
#: 0.6 sits well above the paraphrase, which is deliberate. Suppressing a deliberation
#: the agent actually needed costs correctness; paying four calls to re-argue a paraphrase
#: costs four calls. The threshold is set to fail in the cheap direction.
REPEAT_THRESHOLD = 0.6


def read_ledger(paths: RunPaths) -> list[dict[str, Any]]:
    """Every crux this run has already put to a panel. Empty when there is no ledger yet."""
    path = paths.reviews_dir / LEDGER_FILENAME
    if not path.exists():
        return []
    try:
        payload = json.loads(read_text(path))
    except (OSError, json.JSONDecodeError):
        return []
    entries = payload.get("deliberations") if isinstance(payload, dict) else None
    return [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []


def settled_answer(entries: list[dict[str, Any]], request: CruxRequest) -> dict[str, Any] | None:
    """An earlier deliberation of the same question that actually produced an answer.

    A stage that fails its gate is sent back, regenerates its escalation from the same state,
    and asks the identical question again. Re-running the panel on a question it has already
    settled spends the budget re-deriving an answer already on disk, and the ledger then counts
    it as a second crux — inflating the very number that is supposed to say how much thinking
    the run needed.

    Returns None when the question is new, or when the earlier attempt produced nothing: a
    panel that could not be reached last time may be reachable now, and that retry is fair.
    """
    from .ideation_panel import similarity

    for entry in reversed(entries):
        prior = entry.get("request")
        if not isinstance(prior, dict) or not str(entry.get("answer") or "").strip():
            continue
        question = str(prior.get("question") or "")
        if question and similarity(question, request.question) >= REPEAT_THRESHOLD:
            return entry
    return None


def record_resolution(paths: RunPaths, stage: StageSpec, resolution: Resolution) -> dict[str, Any]:
    """Persist the crux, every position, and whether escalating changed anything."""
    path = paths.reviews_dir / LEDGER_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)

    ledger: dict[str, Any] = {"deliberations": []}
    if path.exists():
        try:
            existing = json.loads(read_text(path))
            if isinstance(existing, dict) and isinstance(existing.get("deliberations"), list):
                ledger = existing
        except (OSError, json.JSONDecodeError):
            ledger = {"deliberations": []}

    ledger["deliberations"].append({"stage": stage.slug, **resolution.to_dict()})
    ledger["summary"] = _summary(ledger["deliberations"])
    write_text(path, json.dumps(ledger, indent=2, ensure_ascii=False))

    append_log_entry(
        paths.logs,
        f"{stage.slug} crux_deliberation",
        f"question: {resolution.request.question}\n{resolution.verdict()}",
    )
    return ledger


def _entry_was_never_deliberated(entry: dict[str, Any]) -> bool:
    """True when every voice on this crux failed, so no panel actually sat."""
    positions = entry.get("positions")
    if not isinstance(positions, list) or not positions:
        return False
    return all(isinstance(p, dict) and p.get("failed") is True for p in positions)


def _summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    calls = sum(int(entry.get("voice_calls") or 0) for entry in entries)
    changed = sum(1 for entry in entries if entry.get("changed_the_answer") is True)
    unchanged = sum(1 for entry in entries if entry.get("changed_the_answer") is False)
    never_sat = sum(1 for entry in entries if _entry_was_never_deliberated(entry))
    return {
        "cruxes_raised": len(entries),
        "changed_the_agents_answer": changed,
        "confirmed_the_agents_answer": unchanged,
        "never_deliberated": never_sat,
        "voice_calls": calls,
        "verdict": _summary_verdict(len(entries), changed, unchanged, calls, never_sat),
    }


def _summary_verdict(
    total: int, changed: int, unchanged: int, calls: int, never_sat: int = 0
) -> str:
    if total == 0:
        return "No cruxes were raised."
    if never_sat == total:
        return (
            f"{total} crux(es) escalated at {calls} calls, and not one panel could be "
            "convened — every voice's backend failed. This says nothing about whether "
            "deliberation helps; it was never tried. Check the backend before reading "
            "any deliberation result from this run."
        )
    if never_sat:
        return (
            f"{total} crux(es) escalated at {calls} calls, of which {never_sat} never "
            "reached a panel because every voice's backend failed. The remaining "
            f"{total - never_sat} are the only ones this run can speak to."
        )
    if unchanged and not changed:
        return (
            f"{total} crux(es) escalated at {calls} calls, and the panel confirmed the agent's "
            "own answer every time. On this run stopping to think changed nothing — the agent "
            "was escalating questions it had already settled."
        )
    if changed:
        return (
            f"{total} crux(es) escalated at {calls} calls; the panel changed the answer on "
            f"{changed} of them."
        )
    return f"{total} crux(es) escalated at {calls} calls; no working answer was offered to compare against."
