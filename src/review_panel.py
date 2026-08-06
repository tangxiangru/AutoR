"""A deliberating review panel in place of a single approval agent.

AutoR's thesis is that a human owns direction while an agent owns execution. The reviewer
agent (:mod:`src.approval_agent`) exists so an unattended run still has *something* standing
at the stage gate — but one model, asked once, with one framing, is a weak stand-in for the
thing it replaces. Real research is not approved by one reader. It is argued over by people
who want different things from it: the PI wants the claim to land, the methodologist wants
the design to hold, the reproducibility engineer wants to be able to rerun it, and Reviewer 2
wants to reject it.

This module simulates that room.

**Why a panel and not just more tokens.** Asking one reviewer to "consider many perspectives"
produces one voice listing perspectives it already agreed with. Independent reviewers, each
given a distinct mandate, a distinct model, and no sight of the others, produce genuinely
different reads — and the disagreement between them is information a single reviewer cannot
generate. So round one is blind on purpose.

**Why deliberation and not just voting.** A vote throws away the reasons. Round two shows each
member what the others found and lets them revise, which is where a domain expert's objection
teaches the methodologist something and vice versa. Only then does the chair decide.

**What stops the panel rubber-stamping.** A member may mark an objection ``blocking``. If any
blocking objection survives the final round, approval is refused *in code* — not by asking the
chair nicely. A prompt-level rule that the chair can talk itself out of is not a rule, and a
gate that cannot say no is not a gate.

Every position, including dissent that lost, is written to ``workspace/reviews/panel/``. A
panel that hides how it split is less auditable than the single reviewer it replaced.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .approval_agent import AutomatedReviewer, ReviewDecision
from .terminal_ui import TerminalUI
from .utils import RunPaths, StageSpec, append_log_entry, read_text, truncate_text, write_text


#: Choices that leave the stage unapproved. Used to decide whether a panel actually converged.
_REFINEMENT_CHOICES = {"1", "2", "3", "4"}


@dataclass(frozen=True)
class PanelRole:
    """One seat at the table.

    ``backend`` and ``model`` are what make the panel more than one model in five hats: a
    verdict from a different harness is the only kind that is genuinely uncorrelated. Both are
    optional and fall back to the run's reviewer defaults, because a single-backend deployment
    should still get the benefit of distinct mandates.
    """

    key: str
    title: str
    charter: str
    looks_for: tuple[str, ...]
    skill: str | None = None
    backend: str | None = None
    model: str | None = None
    #: A chair breaks ties and writes the final decision. Exactly one role must have it.
    chair: bool = False


DEFAULT_PANEL: tuple[PanelRole, ...] = (
    PanelRole(
        key="pi",
        title="Principal Investigator",
        chair=True,
        charter=(
            "You own the research question and the go/no-go. You care whether this stage moves "
            "the central claim forward, whether the story still holds together, and whether the "
            "run is spending its effort on the thing that matters. You are the one who has to "
            "defend this work publicly."
        ),
        looks_for=(
            "Does this stage advance the central claim, or is it busywork?",
            "Has the narrative drifted from what earlier stages committed to?",
            "Is the strongest available result being buried or oversold?",
        ),
    ),
    PanelRole(
        key="domain",
        title="Domain Expert",
        charter=(
            "You know this field. You care whether the framing, terminology, and prior work are "
            "right, whether the claim is actually novel, and whether a specialist reading this "
            "would find an obvious error or an obvious missing reference."
        ),
        looks_for=(
            "Is anything stated as fact that a specialist would dispute?",
            "Is the prior work represented accurately, and is anything load-bearing missing?",
            "Is the terminology used the way the field uses it?",
        ),
        skill="citation-discipline",
    ),
    PanelRole(
        key="method",
        title="Methodologist",
        charter=(
            "You own study design and statistical validity. You care about confounds, sample "
            "size, baselines, ablations, leakage between train and test, and whether the "
            "measurement actually measures the thing being claimed."
        ),
        looks_for=(
            "Does the design support the causal or comparative claim being made?",
            "Are baselines, controls, and ablations present and fair?",
            "Are uncertainties, sample sizes, and failure cases reported?",
        ),
        skill="result-table",
    ),
    PanelRole(
        key="repro",
        title="Reproducibility Engineer",
        charter=(
            "You care about whether someone else could rerun this. Numbers must trace to files, "
            "files must exist, code must be runnable, and figures must come from the data they "
            "claim to. You open the artifacts rather than trusting the summary's description "
            "of them."
        ),
        looks_for=(
            "Does every number in the summary trace to a file in the run?",
            "Do the listed artifacts actually exist, and are they non-trivial?",
            "Could a stranger rerun this stage from what is on disk?",
        ),
        skill="reproducibility-check",
    ),
    PanelRole(
        key="skeptic",
        title="Adversarial Reviewer",
        charter=(
            "You are Reviewer 2. Your job is to find the reason this should be rejected. Assume "
            "the work is weaker than it looks and go looking for the evidence. You are not being "
            "unfair; you are the reason the other four have to be right. Do not manufacture "
            "objections — but do not soften a real one to be agreeable."
        ),
        looks_for=(
            "What is the strongest argument that this stage's conclusion is wrong?",
            "Which claim has the thinnest evidence behind it?",
            "What would an unsympathetic reviewer attack first?",
        ),
    ),
)

PANEL_ROLES_BY_KEY = {role.key: role for role in DEFAULT_PANEL}


@dataclass(frozen=True)
class PanelVerdict:
    role_key: str
    role_title: str
    backend: str
    model: str
    choice: str
    decision_token: str
    blocking: bool
    reason: str
    feedback: str
    concerns: tuple[str, ...] = ()
    failed: bool = False

    @property
    def approves(self) -> bool:
        return self.choice == "5" and not self.blocking

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role_key,
            "title": self.role_title,
            "backend": self.backend,
            "model": self.model,
            "choice": self.choice,
            "decision": self.decision_token,
            "blocking": self.blocking,
            "reason": self.reason,
            "feedback": self.feedback,
            "concerns": list(self.concerns),
            "failed": self.failed,
        }


@dataclass
class PanelDeliberation:
    stage_slug: str
    attempt_no: int
    rounds: list[list[PanelVerdict]] = field(default_factory=list)
    decision: ReviewDecision | None = None
    chair_overridden: bool = False
    override_reason: str = ""

    @property
    def final_round(self) -> list[PanelVerdict]:
        return self.rounds[-1] if self.rounds else []

    def blocking_verdicts(self) -> list[PanelVerdict]:
        return [verdict for verdict in self.final_round if verdict.blocking]

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage_slug,
            "attempt": self.attempt_no,
            "rounds": [[verdict.to_dict() for verdict in group] for group in self.rounds],
            "blocking_after_deliberation": [v.role_key for v in self.blocking_verdicts()],
            "chair_overridden": self.chair_overridden,
            "override_reason": self.override_reason,
            "final_choice": self.decision.choice if self.decision else None,
            "final_reason": self.decision.reason if self.decision else "",
            "final_feedback": self.decision.feedback if self.decision else "",
        }


def resolve_roles(keys: list[str] | None) -> tuple[PanelRole, ...]:
    """Resolve a roster from role keys, preserving the caller's order.

    An unknown key is an error rather than a silent drop: a panel that quietly seats four
    members when five were asked for is a panel whose composition nobody can trust.
    """
    if not keys:
        return DEFAULT_PANEL

    roles: list[PanelRole] = []
    for key in keys:
        normalized = key.strip().lower()
        if normalized not in PANEL_ROLES_BY_KEY:
            known = ", ".join(sorted(PANEL_ROLES_BY_KEY))
            raise ValueError(f"Unknown panel role: {key}. Known roles: {known}.")
        role = PANEL_ROLES_BY_KEY[normalized]
        if role not in roles:
            roles.append(role)

    if not any(role.chair for role in roles):
        # Somebody has to write the final decision; the first seat takes the gavel.
        first = roles[0]
        roles[0] = PanelRole(**{**first.__dict__, "chair": True})
    return tuple(roles)


class ReviewPanel:
    """A drop-in for :class:`~src.approval_agent.AutomatedReviewer` that deliberates first.

    Duck-types ``review_stage`` plus the ``backend_name``/``model`` attributes the manager
    reads, so the approval loop does not need to know whether it is talking to one reviewer or
    five.
    """

    def __init__(
        self,
        roles: tuple[PanelRole, ...] = DEFAULT_PANEL,
        *,
        backend_name: str,
        model: str,
        fake_mode: bool = False,
        ui: TerminalUI | None = None,
        stage_timeout: int = 14400,
        persona_text: str = "",
        deliberation_rounds: int = 2,
    ) -> None:
        if not roles:
            raise ValueError("A review panel needs at least one role.")
        self.roles = roles
        self.backend_name = backend_name
        self.model = model
        self.fake_mode = fake_mode
        self.ui = ui or TerminalUI()
        self.persona_text = persona_text.strip()
        self.deliberation_rounds = max(1, deliberation_rounds)
        self._members: dict[str, AutomatedReviewer] = {
            role.key: AutomatedReviewer(
                role.backend or backend_name,
                model=role.model or model,
                fake_mode=fake_mode,
                ui=self.ui,
                stage_timeout=stage_timeout,
            )
            for role in roles
        }
        self.chair = next(role for role in roles if role.chair)

    # -- the manager-facing contract -----------------------------------------

    def review_stage(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        stage_markdown: str,
        suggestions: list[str],
    ) -> ReviewDecision:
        if self.fake_mode:
            return ReviewDecision(
                choice="5",
                decision_token="approve",
                reason="Fake panel mode auto-approved this stage for smoke validation.",
                raw_response='{"decision":"approve","reason":"fake panel"}',
            )

        deliberation = PanelDeliberation(stage_slug=stage.slug, attempt_no=attempt_no)

        verdicts = self._round(
            paths=paths,
            stage=stage,
            attempt_no=attempt_no,
            stage_markdown=stage_markdown,
            suggestions=suggestions,
            previous=None,
            round_no=1,
        )
        deliberation.rounds.append(verdicts)

        # A unanimous, unblocked room has nothing to deliberate about, and a second round
        # would only invite it to talk itself out of an agreement it already reached.
        for round_no in range(2, self.deliberation_rounds + 1):
            if self._is_unanimous(verdicts):
                break
            verdicts = self._round(
                paths=paths,
                stage=stage,
                attempt_no=attempt_no,
                stage_markdown=stage_markdown,
                suggestions=suggestions,
                previous=verdicts,
                round_no=round_no,
            )
            deliberation.rounds.append(verdicts)

        decision = self._synthesize(
            paths=paths,
            stage=stage,
            attempt_no=attempt_no,
            stage_markdown=stage_markdown,
            suggestions=suggestions,
            deliberation=deliberation,
        )
        deliberation.decision = decision

        decision = self._enforce_blocking_objections(deliberation)
        self._record(paths, deliberation)
        self._render(deliberation)
        return decision

    # -- rounds ---------------------------------------------------------------

    def _round(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        stage_markdown: str,
        suggestions: list[str],
        previous: list[PanelVerdict] | None,
        round_no: int,
    ) -> list[PanelVerdict]:
        verdicts: list[PanelVerdict] = []
        for role in self.roles:
            member = self._members[role.key]
            self.ui.show_status(
                f"Panel round {round_no}: {role.title} is reviewing {stage.stage_title}...",
                level="info",
            )
            prompt = self._build_member_prompt(
                paths=paths,
                stage=stage,
                attempt_no=attempt_no,
                stage_markdown=stage_markdown,
                suggestions=suggestions,
                role=role,
                previous=previous,
                round_no=round_no,
            )
            exit_code, stdout_text, stderr_text = member.run_prompt(
                paths=paths,
                stage=stage,
                attempt_no=attempt_no,
                prompt=prompt,
                label=f"panel_{role.key}_r{round_no}",
            )
            verdicts.append(
                self._verdict_from_output(
                    role=role,
                    member=member,
                    exit_code=exit_code,
                    stdout_text=stdout_text,
                    stderr_text=stderr_text,
                )
            )
        return verdicts

    def _verdict_from_output(
        self,
        *,
        role: PanelRole,
        member: AutomatedReviewer,
        exit_code: int,
        stdout_text: str,
        stderr_text: str,
    ) -> PanelVerdict:
        if exit_code != 0:
            # A member that could not be reached does not get to be counted as agreeing.
            return PanelVerdict(
                role_key=role.key,
                role_title=role.title,
                backend=member.backend_name,
                model=member.model,
                choice="4",
                decision_token="custom_feedback",
                blocking=False,
                reason=f"{role.title} could not be reached (exit code {exit_code}).",
                feedback="",
                failed=True,
            )

        decision = member.parse_decision(stdout_text)
        payload = self._payload(stdout_text)
        blocking = bool(payload.get("blocking")) if isinstance(payload, dict) else False
        concerns: tuple[str, ...] = ()
        if isinstance(payload, dict) and isinstance(payload.get("concerns"), list):
            concerns = tuple(str(item).strip() for item in payload["concerns"] if str(item).strip())

        return PanelVerdict(
            role_key=role.key,
            role_title=role.title,
            backend=member.backend_name,
            model=member.model,
            choice=decision.choice,
            decision_token=decision.decision_token,
            # An unparseable answer degrades to abort in `parse_decision`; treat that as a
            # non-blocking failure rather than letting one bad response veto the run.
            blocking=blocking and decision.choice != "6",
            reason=decision.reason,
            feedback=decision.feedback,
            concerns=concerns,
        )

    def _payload(self, raw_response: str) -> dict[str, Any] | None:
        member = next(iter(self._members.values()))
        return member._extract_json_payload(raw_response)  # noqa: SLF001

    @staticmethod
    def _is_unanimous(verdicts: list[PanelVerdict]) -> bool:
        if any(verdict.failed for verdict in verdicts):
            return False
        return all(verdict.approves for verdict in verdicts) or len({v.choice for v in verdicts}) == 1

    # -- synthesis and enforcement -------------------------------------------

    def _synthesize(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        stage_markdown: str,
        suggestions: list[str],
        deliberation: PanelDeliberation,
    ) -> ReviewDecision:
        verdicts = deliberation.final_round
        if self._is_unanimous(verdicts) and verdicts and verdicts[0].approves:
            return ReviewDecision(
                choice="5",
                decision_token="approve",
                reason=f"All {len(verdicts)} panel members approved without a blocking objection.",
                raw_response=json.dumps(deliberation.to_dict()),
            )

        chair = self._members[self.chair.key]
        self.ui.show_status(f"Panel chair ({self.chair.title}) is synthesizing the decision...", level="info")
        exit_code, stdout_text, stderr_text = chair.run_prompt(
            paths=paths,
            stage=stage,
            attempt_no=attempt_no,
            prompt=self._build_chair_prompt(
                paths=paths,
                stage=stage,
                attempt_no=attempt_no,
                stage_markdown=stage_markdown,
                suggestions=suggestions,
                deliberation=deliberation,
            ),
            label="panel_chair",
        )
        if exit_code != 0:
            return self._decision_from_dissent(
                verdicts,
                reason=f"Panel chair could not be reached (exit code {exit_code}); "
                "falling back to the panel's own objections.",
            )
        return chair.parse_decision(stdout_text)

    def _enforce_blocking_objections(self, deliberation: PanelDeliberation) -> ReviewDecision:
        """Refuse approval while a blocking objection stands.

        This is deliberately mechanical. The chair is a model, and a model asked to weigh
        dissent can be argued into discounting it; the point of a blocking flag is that it
        cannot be. If the chair approves anyway, the approval is converted into refinement and
        the conversion is recorded.
        """
        decision = deliberation.decision
        assert decision is not None
        blockers = deliberation.blocking_verdicts()
        if not blockers or decision.choice != "5":
            return decision

        objections = "\n".join(
            f"- **{verdict.role_title}**: {verdict.reason or verdict.feedback or 'blocking objection'}"
            for verdict in blockers
        )
        names = ", ".join(verdict.role_title for verdict in blockers)
        feedback = (
            "The panel chair moved to approve, but the following blocking objections were "
            "unresolved. Address each one concretely before this stage can be approved.\n\n"
            f"{objections}"
        )
        deliberation.chair_overridden = True
        deliberation.override_reason = f"Blocking objection from {names} outranks the chair's approval."
        overridden = ReviewDecision(
            choice="4",
            decision_token="custom_feedback",
            reason=deliberation.override_reason,
            feedback=feedback,
            raw_response=decision.raw_response,
        )
        deliberation.decision = overridden
        return overridden

    def _decision_from_dissent(self, verdicts: list[PanelVerdict], *, reason: str) -> ReviewDecision:
        objections = [v for v in verdicts if not v.approves and not v.failed]
        if not objections:
            return ReviewDecision(choice="5", decision_token="approve", reason=reason)
        feedback = "\n".join(
            f"- **{verdict.role_title}**: {verdict.feedback or verdict.reason}"
            for verdict in objections
            if verdict.feedback or verdict.reason
        )
        return ReviewDecision(
            choice="4",
            decision_token="custom_feedback",
            reason=reason,
            feedback=feedback or "The panel did not converge on approval.",
        )

    # -- prompts --------------------------------------------------------------

    def _persona_block(self) -> str:
        if not self.persona_text:
            return ""
        return (
            "\n# The Researcher You Are Standing In For\n\n"
            "This run has a named human owner. Their standards are the standards you apply; "
            "where the charter and this description disagree, this description wins.\n\n"
            f"{truncate_text(self.persona_text, max_chars=4000)}\n"
        )

    def _build_member_prompt(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        stage_markdown: str,
        suggestions: list[str],
        role: PanelRole,
        previous: list[PanelVerdict] | None,
        round_no: int,
    ) -> str:
        looks_for = "\n".join(f"- {item}" for item in role.looks_for)
        skill_line = (
            f"\nA skill named `{role.skill}` is installed in this run. Use it — it encodes the "
            "checks your seat is responsible for.\n"
            if role.skill
            else ""
        )

        if previous is None:
            round_block = (
                "## Round 1 of the panel: independent review\n\n"
                "You have not seen the other members' views and you should not speculate about "
                "them. Form your own judgement from the artifacts. Disagreement between members "
                "is useful to this run; agreement you did not actually reach is not.\n"
            )
        else:
            positions = "\n\n".join(
                f"**{verdict.role_title}** -> {verdict.decision_token}"
                + (" (BLOCKING)" if verdict.blocking else "")
                + (f"\nReason: {verdict.reason}" if verdict.reason else "")
                + (f"\nConcerns: {'; '.join(verdict.concerns)}" if verdict.concerns else "")
                for verdict in previous
                if verdict.role_key != role.key
            )
            own = next((v for v in previous if v.role_key == role.key), None)
            round_block = (
                f"## Round {round_no} of the panel: cross-examination\n\n"
                "The panel did not agree. Below is what every other member concluded. Read them "
                "as colleagues who looked at the same artifacts and saw something you did not.\n\n"
                "Change your position if they found something real. Hold it if they did not — "
                "converging to be agreeable is the failure mode this round exists to avoid, and "
                "a lone correct objection is worth more than a comfortable consensus.\n\n"
                f"{positions}\n"
                + (
                    f"\nYour own round-1 position was `{own.decision_token}`"
                    + (f": {own.reason}" if own.reason else "")
                    + "\n"
                    if own
                    else ""
                )
            )

        return (
            f"# AutoR Review Panel: {role.title}\n\n"
            f"You are the **{role.title}** on the review panel for {stage.stage_title}. You are a "
            "simulated human reviewer standing at an approval gate, not the execution agent. Do "
            "not edit files. Inspect and judge.\n\n"
            f"## Your Charter\n\n{role.charter}\n\n"
            f"## What Your Seat Is Responsible For\n\n{looks_for}\n"
            f"{skill_line}\n"
            "Other seats cover other concerns. Do not try to cover the whole review — review "
            "your part of it properly and trust the panel for the rest.\n\n"
            f"{round_block}\n"
            "## Review Policy\n\n"
            "- Approve only if this stage is materially complete for its current milestone.\n"
            "- Do not demand final-paper quality from early stages, but do demand real progress "
            "and real artifacts.\n"
            "- Open the artifacts. A summary's description of a file is not evidence the file "
            "says what it claims.\n"
            "- Mark `blocking` true only for a defect that must be fixed before this stage can "
            "be approved at all. A blocking objection cannot be overruled by the chair, so use "
            "it for real defects and not for preferences.\n\n"
            "## Return Format\n\n"
            "Return JSON only, with no prose outside the JSON object:\n"
            '{"decision":"approve|suggestion_1|suggestion_2|suggestion_3|custom_feedback|abort",'
            '"blocking":false,"concerns":["..."],"feedback":"","reason":""}\n\n'
            "- `feedback` must be non-empty when `decision` is `custom_feedback`.\n"
            "- `concerns` is a short list of the specific things you checked and found wanting.\n"
            "- `reason` should be concise and specific to your seat.\n"
            f"{self._persona_block()}\n"
            "# Suggested Refinements Available To The Panel\n\n"
            f"1. {suggestions[0]}\n2. {suggestions[1]}\n3. {suggestions[2]}\n\n"
            f"{self._context_block(paths=paths, stage=stage, attempt_no=attempt_no, stage_markdown=stage_markdown)}"
        )

    def _build_chair_prompt(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        stage_markdown: str,
        suggestions: list[str],
        deliberation: PanelDeliberation,
    ) -> str:
        transcript_parts: list[str] = []
        for index, group in enumerate(deliberation.rounds, start=1):
            lines = [f"### Round {index}", ""]
            for verdict in group:
                lines.append(
                    f"**{verdict.role_title}** ({verdict.backend}/{verdict.model}) -> "
                    f"`{verdict.decision_token}`" + ("  **BLOCKING**" if verdict.blocking else "")
                )
                if verdict.reason:
                    lines.append(f"- Reason: {verdict.reason}")
                if verdict.concerns:
                    lines.extend(f"- Concern: {item}" for item in verdict.concerns)
                if verdict.feedback:
                    lines.append(f"- Requested change: {verdict.feedback}")
                if verdict.failed:
                    lines.append("- (this member could not be reached)")
                lines.append("")
            transcript_parts.append("\n".join(lines))
        transcript = "\n".join(transcript_parts)

        blockers = deliberation.blocking_verdicts()
        blocking_note = (
            "\n**There are unresolved blocking objections from: "
            + ", ".join(verdict.role_title for verdict in blockers)
            + ". You cannot approve over them — if you try, the decision will be converted to "
            "a refinement automatically. Fold their requirements into your feedback instead.**\n"
            if blockers
            else ""
        )

        return (
            f"# AutoR Review Panel: Chair Synthesis\n\n"
            f"You are the **{self.chair.title}**, chairing the review panel for "
            f"{stage.stage_title}. The panel has deliberated and did not simply agree. Your job "
            "is to turn their positions into the single decision the workflow will act on.\n\n"
            "## How To Decide\n\n"
            "- Weigh the objections on their evidence, not on how many members raised them. One "
            "member who opened the artifacts and found a real problem outranks three who did not.\n"
            "- Address the dissent explicitly in your reason. A synthesis that ignores a member's "
            "objection is not a synthesis.\n"
            "- If the objections are concrete and fixable, choose `custom_feedback` and write "
            "instructions that would satisfy the members who raised them.\n"
            "- If a built-in suggestion already captures the panel's ask, select it instead.\n"
            "- Use `abort` only if continuing automatically would be irresponsible.\n"
            f"{blocking_note}\n"
            "## Return Format\n\n"
            "Return JSON only, with no prose outside the JSON object:\n"
            '{"decision":"approve|suggestion_1|suggestion_2|suggestion_3|custom_feedback|abort",'
            '"feedback":"","reason":""}\n\n'
            f"{self._persona_block()}\n"
            "# Panel Transcript\n\n"
            f"{transcript}\n"
            "# Suggested Refinements Available To The Panel\n\n"
            f"1. {suggestions[0]}\n2. {suggestions[1]}\n3. {suggestions[2]}\n\n"
            f"{self._context_block(paths=paths, stage=stage, attempt_no=attempt_no, stage_markdown=stage_markdown)}"
        )

    def _context_block(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        stage_markdown: str,
    ) -> str:
        def excerpt(path: Path, max_chars: int, tail: bool = False) -> str:
            if not path.exists():
                return "(missing)"
            text = read_text(path).strip()
            if not text:
                return "(empty)"
            if len(text) <= max_chars:
                return text
            return ("..." + text[-(max_chars - 3):].lstrip()) if tail else truncate_text(text, max_chars=max_chars)

        return (
            "# Run Context\n\n"
            f"- run root: `{paths.run_root.resolve()}`\n"
            f"- current attempt: {attempt_no}\n"
            f"- stage draft under review: `{paths.stage_tmp_file(stage).resolve()}`\n"
            f"- artifact index: `{paths.artifact_index.resolve()}`\n"
            f"- experiment manifest: `{paths.experiment_manifest.resolve()}`\n"
            f"- workspace root: `{paths.workspace_root.resolve()}`\n\n"
            "# Original Goal\n\n"
            f"{excerpt(paths.user_input, 3000)}\n\n"
            "# Approved Memory\n\n"
            f"{excerpt(paths.memory, 10000)}\n\n"
            "# Current Stage Summary\n\n"
            f"{truncate_text(stage_markdown, max_chars=16000)}\n\n"
            "# Artifact Index Excerpt\n\n"
            f"{excerpt(paths.artifact_index, 5000)}\n\n"
            "# Experiment Manifest Excerpt\n\n"
            f"{excerpt(paths.experiment_manifest, 5000)}\n"
        )

    # -- recording ------------------------------------------------------------

    def _record(self, paths: RunPaths, deliberation: PanelDeliberation) -> None:
        """Persist the whole room, including the dissent that lost.

        Stage 08 reads ``workspace/reviews/``, and a run's auditability is the product's whole
        claim. A panel that reported only its verdict would be less inspectable than the single
        reviewer it replaced.
        """
        panel_dir = paths.reviews_dir / "panel"
        panel_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{deliberation.stage_slug}_attempt_{deliberation.attempt_no:02d}"

        write_text(
            panel_dir / f"{stem}.json",
            json.dumps(deliberation.to_dict(), indent=2, ensure_ascii=False),
        )
        write_text(panel_dir / f"{stem}.md", self._render_markdown(deliberation))

        summary = "; ".join(
            f"{verdict.role_title}={verdict.decision_token}" + ("(blocking)" if verdict.blocking else "")
            for verdict in deliberation.final_round
        )
        append_log_entry(
            paths.logs,
            f"{deliberation.stage_slug} attempt {deliberation.attempt_no} panel_decision",
            (
                f"rounds: {len(deliberation.rounds)}\n"
                f"positions: {summary}\n"
                f"chair_overridden: {deliberation.chair_overridden}\n"
                f"final_choice: {deliberation.decision.choice if deliberation.decision else '?'}"
            ),
        )

    def _render_markdown(self, deliberation: PanelDeliberation) -> str:
        lines = [
            f"# Review Panel: {deliberation.stage_slug} (attempt {deliberation.attempt_no})",
            "",
        ]
        for index, group in enumerate(deliberation.rounds, start=1):
            lines.extend([f"## Round {index}", ""])
            for verdict in group:
                flag = " **BLOCKING**" if verdict.blocking else ""
                lines.append(f"### {verdict.role_title} -> `{verdict.decision_token}`{flag}")
                lines.append(f"_{verdict.backend} / {verdict.model}_")
                lines.append("")
                if verdict.reason:
                    lines.extend([verdict.reason, ""])
                if verdict.concerns:
                    lines.extend([f"- {item}" for item in verdict.concerns] + [""])
                if verdict.feedback:
                    lines.extend(["Requested change:", "", verdict.feedback, ""])
                if verdict.failed:
                    lines.extend(["_This member could not be reached._", ""])
        decision = deliberation.decision
        lines.extend(["## Outcome", ""])
        if deliberation.chair_overridden:
            lines.extend([f"> Chair approval overridden: {deliberation.override_reason}", ""])
        if decision is not None:
            lines.append(f"- Decision: `{decision.decision_token}` (choice {decision.choice})")
            if decision.reason:
                lines.append(f"- Reason: {decision.reason}")
            if decision.feedback:
                lines.extend(["", "### Feedback to the execution agent", "", decision.feedback])
        return "\n".join(lines).rstrip() + "\n"

    def _render(self, deliberation: PanelDeliberation) -> None:
        body = [f"Rounds   : {len(deliberation.rounds)}"]
        for verdict in deliberation.final_round:
            flag = "  [BLOCKING]" if verdict.blocking else ""
            body.append(f"{verdict.role_title:<26}: {verdict.decision_token}{flag}")
        if deliberation.chair_overridden:
            body.extend(["", f"Chair approval overridden: {deliberation.override_reason}"])
        if deliberation.decision is not None:
            body.extend(["", f"Decision : {deliberation.decision.decision_token}"])
            if deliberation.decision.reason:
                body.append(f"Reason   : {deliberation.decision.reason}")
        self.ui.panel("Review Panel", body, color=self.ui.FG_MAGENTA)


def load_persona(path: Path | str | None) -> str:
    """Read a persona description, or return empty when none is configured."""
    if not path:
        return ""
    resolved = Path(path).expanduser()
    if not resolved.exists():
        raise FileNotFoundError(f"Persona file not found: {resolved}")
    return read_text(resolved).strip()
