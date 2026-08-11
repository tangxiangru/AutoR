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

from .approval_agent import DECISION_TO_CHOICE, AutomatedReviewer, ReviewDecision
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
    #: How much of the other seats' round-1 output this member sees when deliberating.
    #: Uniform full exposure makes the second round a convergence machine; withholding it
    #: from the seats whose value is independence is what keeps a lone correct objection
    #: alive long enough to be heard.
    exposure: str = "full"
    #: A chair breaks ties and writes the final decision. Exactly one role must have it.
    chair: bool = False


#: Every seat is handed the same context block, so charter wording is the only thing making
#: five reads uncorrelated. Two rules follow from that, and both are load-bearing:
#:
#: 1. **Name the failure modes.** :mod:`src.validity_review` already reports, in this repo, why
#:    an open-ended critique "reliably returns prose quality, which is not what is dangerous
#:    here", and answers it with a fixed list of named categories. A charter that says "you care
#:    about validity" is that open-ended critique wearing a title. So each seat gets 3-5 named
#:    failure modes with a one-line definition, borrowing ``VALIDITY_CATEGORIES`` spellings where
#:    one applies so a concern can still be classified downstream.
#: 2. **Send each seat to different files.** Distinct mandates over identical evidence is the
#:    weakest form of independence available. Until ``PanelRole`` can carry a per-seat reading
#:    list, the charter names the artifacts that seat opens first.
#:
#: Seats also say which stages they are for. Nothing here filters the roster by stage yet, so
#: the instrument is the abstention path: a seat with no artifact matching its mandate says so
#: in one line instead of manufacturing a framing objection.
DEFAULT_PANEL: tuple[PanelRole, ...] = (
    PanelRole(
        key="pi",
        title="Principal Investigator",
        chair=True,
        charter=(
            "You own the research question and the go/no-go. You are the only seat with that "
            "authority — spend it on direction and on whether this run should keep going. "
            "Whether the evidence holds is covered by three other seats; do not re-argue it "
            "here.\n\n"
            "Open first: the original goal, the approved memory of the earlier stages, and "
            "`workspace/notes/round_decision.json` if a research round has been closed.\n\n"
            "Failure modes you own:\n"
            "- **drift** — the run is now answering a question earlier stages did not commit "
            "to, and no one decided to change it.\n"
            "- **busywork** — the stage is complete and moves the central claim nowhere; "
            "another attempt would produce the same artifact.\n"
            "- **sunk cost** — the remaining round budget is going to a question this run has "
            "already shown it cannot answer with the time and compute it has.\n\n"
            "You are seated at every gate, because you also chair the panel."
        ),
        looks_for=(
            "Does this stage advance the central claim, or is it busywork?",
            "Has the narrative drifted from what earlier stages committed to?",
            "Is this still the right question, given what the run now knows?",
            "Should the remaining round budget go to another round, or should this run stop here?",
        ),
    ),
    PanelRole(
        key="domain",
        title="Domain Expert",
        charter=(
            "You know this field. Your seat exists for Intake, Literature Survey, Hypothesis "
            "Generation and Writing — the stages where a specialist catches what no gate can. "
            "At the other stages, abstain unless the summary states something about the field "
            "that is wrong.\n\n"
            "Open first: `workspace/literature/sources.json` and "
            "`workspace/literature/claims.json`. Check each claim against the source it cites, "
            "not against the summary's description of it.\n\n"
            "Failure modes you own:\n"
            "- **misattribution** — a cited work is described as doing something it does not do.\n"
            "- **false novelty** — a gap or first-ever claim that a specialist could answer with "
            "one counterexample, or that rests on what the run failed to recall rather than on "
            "a search it actually ran and recorded.\n"
            "- **term drift** — a term used in a sense the field does not use, quietly widening "
            "or narrowing what is being claimed.\n"
            "- **missing load-bearing reference** — the one paper this work has to be positioned "
            "against is absent."
        ),
        looks_for=(
            "Is anything stated as fact that a specialist would dispute?",
            "Is the prior work represented accurately, and is anything load-bearing missing?",
            "Is every 'no prior work does X' backed by a recorded search rather than by "
            "absence of recall?",
            "Is the terminology used the way the field uses it?",
        ),
        skill="citation-discipline",
    ),
    PanelRole(
        key="method",
        title="Methodologist",
        charter=(
            "You are a conformance auditor, not an open-ended critic. You check what ran against "
            "what the run froze, field by field. Whether the result is interesting, and what "
            "else could explain it, belong to other seats.\n\n"
            "Your seat runs from Hypothesis Generation through Analysis (Stages 02-06); abstain "
            "outside them. Open first: `workspace/notes/experimental_protocol.json`, "
            "`workspace/notes/preregistration.json` and "
            "`workspace/results/hypothesis_outcomes.json`. At a stage that predates one of "
            "those files, audit the ones that exist.\n\n"
            "Failure modes you own:\n"
            "- **protocol deviation** — planned_seeds, primary_metric, a planned ablation or a "
            "baseline's tuning_budget differs from what the protocol froze, and the difference "
            "is not reported as a deviation.\n"
            "- **metric_cherry_picking** — a verdict applies a decision rule chosen after seeing "
            "the number, instead of that hypothesis's own preregistered rule.\n"
            "- **weak_baseline** — the method got a search budget the baselines did not, so the "
            "comparison measures tuning effort.\n"
            "- **leakage** — the evaluation split was read, tuned against, or selected on before "
            "the final run.\n"
            "- **effect_within_noise** — the reported gap sits inside its own stated dispersion, "
            "or rests on a single run with no dispersion stated at all.\n\n"
            "The `result-table` skill is for Analysis, where the results table is the artifact "
            "you are auditing."
        ),
        looks_for=(
            "Field by field, does what ran match `notes/experimental_protocol.json` — "
            "planned_seeds, primary_metric, and each baseline's tuning_budget?",
            "Does every verdict in `results/hypothesis_outcomes.json` apply that hypothesis's "
            "own decision rule from `notes/preregistration.json`, or one chosen after the "
            "number was known?",
            "Is any reported gap inside its own stated dispersion?",
        ),
        skill="result-table",
        # This seat wants ``exposure="objections"`` — an auditor shown a room full of approvals
        # audits less, and the middle setting is implemented and used by nobody. It is left at
        # full because a seat that sees only objections sees nothing when it is the sole
        # objector, and `test_peer_positions_are_anonymised_in_cross_examination` asserts every
        # round-2 prompt names an anonymised peer. That assertion, not the setting, is what
        # needs the edit.
    ),
    PanelRole(
        key="repro",
        title="Reproducibility Engineer",
        charter=(
            "You care whether someone else could rerun this and get these numbers. Recomputing "
            "one number beats re-listing ten files: `validate_stage_artifacts` already checked "
            "that the named artifacts exist and are non-trivial before this panel was called, "
            "so re-deriving that verdict spends your seat on a result the run already has.\n\n"
            "Your seat runs from Implementation through Dissemination (Stages 04-08); abstain "
            "earlier, when there is nothing yet to rerun. Open first: the listing of "
            "`workspace/results/`, the code under `workspace/code/`, and "
            "`workspace/notes/smoke_run.txt` — the command, exit code and output Stage 04 "
            "recorded. Open the artifacts rather than trusting the summary's description of "
            "them.\n\n"
            "Failure modes you own:\n"
            "- **number with no source** — a figure quoted in the summary appears in no file in "
            "the run.\n"
            "- **recomputation mismatch** — you open the raw file and get a different value from "
            "the one reported.\n"
            "- **irreproducible_procedure** — the command, seed or environment needed to rerun "
            "this is written down nowhere.\n"
            "- **untraceable figure** — a plot that no file in the run could have produced."
        ),
        looks_for=(
            "Pick the single most load-bearing number in the stage summary, open the raw file "
            "it came from, re-derive it, and report both values.",
            "Does every number in the summary trace to a file in the run?",
            "Could a stranger rerun this stage from what is on disk?",
        ),
        skill="reproducibility-check",
    ),
    PanelRole(
        key="skeptic",
        title="Adversarial Reviewer",
        charter=(
            "You are Reviewer 2. Your job is to find the reason this should be rejected, and the "
            "reason you own is the explanation nobody in the room proposed. Assume the work is "
            "weaker than it looks and go looking for the evidence. Do not manufacture "
            "objections — but do not soften a real one to be agreeable.\n\n"
            "Design conformance is the Methodologist's audit: seeds, tuning budgets, planned "
            "ablations and protocol deviations are not your seat, and raising them here is how "
            "five reviewers collapse into one. A counter-hypothesis is generated, not looked "
            "up, so read the stage summary and the results and nothing else. Your seat runs "
            "from Intake through Analysis; at Writing and Dissemination, abstain unless the "
            "write-up asserts something the run did not establish.\n\n"
            "Failure modes you own:\n"
            "- **confound** — a concrete alternative mechanism would produce this exact result "
            "without the claimed effect.\n"
            "- **trivial explanation** — the same number would fall out of a shuffled label, a "
            "constant predictor, or the easy subset of the data.\n"
            "- **unsupported_generalization** — the conclusion is stated for a population, "
            "scale or setting the run never touched.\n"
            "- **overclaim** — the result is sold harder than the evidence carries, or the "
            "caveat that qualifies it is buried where a reader will not meet it.\n"
            "- **the attack you would lead with** — the first thing an unsympathetic reviewer "
            "would go after, said plainly."
        ),
        looks_for=(
            "What is the strongest argument that this stage's conclusion is wrong?",
            "Propose a concrete alternative mechanism that would produce this exact result "
            "without the claimed effect, and say what evidence in the run rules it in or out.",
            "What would an unsympathetic reviewer attack first?",
        ),
        # The seat whose whole job is to not go along with the room is the seat that must
        # not be shown the room.
        exposure="none",
    ),
)

#: Seats that exist but are not seated by default; ``--panel-roles`` calls them up.
#:
#: The Area Chair is the one mandate no default seat holds: both writing prompts carry a
#: self-review phase precisely because nothing outside the writing agent reads the artifact as
#: a document, and `paper-writing` / `venue-checklist` are bound to no seat at all. It is out
#: of :data:`DEFAULT_PANEL` because nothing filters the roster by stage yet, so seating it
#: would buy one extra model call at all nine gates for a mandate that exists at two. Seating
#: it by default is a one-line change here plus the two roster counts in
#: ``tests/test_review_panel.py`` and the seat table in ``docs/review-panel.md``.
OPTIONAL_ROLES: tuple[PanelRole, ...] = (
    PanelRole(
        key="reader",
        title="Area Chair",
        charter=(
            "You judge the artifact as a communication, not as a set of claims. You read the "
            "abstract, the first figure and the results table, in that order, and you say what "
            "verdict you would form in ten minutes. You are the only seat that reads for "
            "structure, narrative, figure legibility and venue conformance.\n\n"
            "Your seat is Writing and Dissemination; abstain elsewhere. Open first: "
            "`workspace/report/report.md` or `workspace/writing/main.tex`, the images under "
            "`workspace/report/images/` or `workspace/figures/`, and the target venue in the "
            "run configuration — the `venue-checklist` skill carries what that venue expects.\n\n"
            "Failure modes you own:\n"
            "- **unreadable contribution** — after the abstract and the first figure you cannot "
            "say what was contributed, or what you can say is not what the authors intended.\n"
            "- **decorative figure** — a figure that is unlabelled, illegible at print size, or "
            "doing no work the text does not already do.\n"
            "- **buried result** — the document's order makes the reader find the contribution "
            "instead of being handed it.\n"
            "- **venue nonconformance** — a required section, disclosure or format the target "
            "venue asks for is missing."
        ),
        looks_for=(
            "After the abstract and the first figure, what do you believe the contribution is "
            "— and is that what the authors intended?",
            "Is any figure unreadable, unlabelled, or doing no work?",
            "Does the document conform to what the target venue expects?",
        ),
        skill="paper-writing",
    ),
)

PANEL_ROLES_BY_KEY = {role.key: role for role in DEFAULT_PANEL + OPTIONAL_ROLES}


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
    abstained: bool = False

    @property
    def approves(self) -> bool:
        return self.choice == "5" and not self.blocking

    @property
    def counts(self) -> bool:
        """Whether this seat contributed a position at all.

        A seat with nothing to say is better silent than padding: forcing every member to
        produce a verdict on every gate is how five reviewers end up raising much the same
        points, which is the mechanism behind the null in the multi-agent feedback literature.
        """
        return not (self.abstained or self.failed)

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
            "abstained": self.abstained,
        }


@dataclass
class PanelDeliberation:
    stage_slug: str
    attempt_no: int
    rounds: list[list[PanelVerdict]] = field(default_factory=list)
    decision: ReviewDecision | None = None
    chair_overridden: bool = False
    override_reason: str = ""
    member_calls: int = 0
    #: Which seat chairs, so :attr:`solo_baseline` can find its round-1 verdict.
    chair_key: str = ""

    @property
    def final_round(self) -> list[PanelVerdict]:
        return self.rounds[-1] if self.rounds else []

    def blocking_verdicts(self) -> list[PanelVerdict]:
        return [verdict for verdict in self.final_round if verdict.blocking]

    @property
    def solo_baseline(self) -> PanelVerdict | None:
        """The chair's round-1 verdict: one model, one call, no peer input.

        Every panel run therefore contains its own control arm for free. Recording it is what
        lets a run answer the only question that matters about this feature — whether the
        deliberation changed a decision the cheapest possible reviewer would have reached
        anyway.
        """
        if not self.rounds:
            return None
        return next((v for v in self.rounds[0] if v.role_key == self.chair_key), None)

    def effect(self) -> dict[str, Any]:
        """What the panel bought over its own single-pass baseline, at this gate."""
        solo = self.solo_baseline
        first = self.rounds[0] if self.rounds else []
        contributing = [v for v in first if v.counts]
        final_choice = self.decision.choice if self.decision else None
        solo_choice = solo.choice if solo is not None else None
        return {
            "stage": self.stage_slug,
            "attempt": self.attempt_no,
            "solo_choice": solo_choice,
            "panel_choice": final_choice,
            "changed_decision": bool(
                solo_choice is not None and final_choice is not None and solo_choice != final_choice
            ),
            "round1_unanimous": len({v.choice for v in contributing}) <= 1,
            "round1_distinct_positions": len({v.choice for v in contributing}),
            "abstentions": sum(1 for v in first if v.abstained),
            "unreachable": sum(1 for v in first if v.failed),
            "blocking_raised": sum(1 for v in first if v.blocking),
            "blocking_survived": len(self.blocking_verdicts()),
            "chair_overridden": self.chair_overridden,
            "rounds": len(self.rounds),
            "member_calls": self.member_calls,
            "solo_calls": 1,
        }

    def to_dict(self) -> dict[str, Any]:
        seats = [(v.backend, v.model) for group in self.rounds for v in group]
        return {
            "stage": self.stage_slug,
            "attempt": self.attempt_no,
            "distinct_backends": sorted({backend for backend, _ in seats}),
            "distinct_models": sorted({model for _, model in seats}),
            # Five prompts against one model are less independent than five seats look.
            "homogeneous_panel": len({seat for seat in seats}) <= 1,
            "rounds": [[verdict.to_dict() for verdict in group] for group in self.rounds],
            "blocking_after_deliberation": [v.role_key for v in self.blocking_verdicts()],
            "chair_overridden": self.chair_overridden,
            "override_reason": self.override_reason,
            "final_choice": self.decision.choice if self.decision else None,
            "final_reason": self.decision.reason if self.decision else "",
            "final_feedback": self.decision.feedback if self.decision else "",
            "effect": self.effect(),
        }


def apply_model_assignments(roles: tuple[PanelRole, ...], assignments: list[str] | None) -> tuple[PanelRole, ...]:
    """Assign a backend and model per seat from ``role=[backend:]model`` strings.

    This is the lever with the best evidence behind it. The multi-agent literature's own
    critics land on model heterogeneity rather than more rounds: errors idiosyncratic to one
    model survive when that model checks its own work, and correlate less across families than
    within them. Five prompts against one model are five correlated reads wearing five hats.
    """
    if not assignments:
        return roles

    by_key = {role.key: role for role in roles}
    updated = dict(by_key)
    for raw in assignments:
        if "=" not in raw:
            raise ValueError(
                f"Bad panel model assignment: {raw!r}. Expected role=model or role=backend:model."
            )
        key, _, spec = raw.partition("=")
        key = key.strip().lower()
        if key not in by_key:
            known = ", ".join(sorted(by_key))
            raise ValueError(f"Unknown panel role in model assignment: {key}. Seated roles: {known}.")
        spec = spec.strip()
        if not spec:
            raise ValueError(f"Bad panel model assignment: {raw!r}. No model given.")
        if ":" in spec:
            backend, _, model = spec.partition(":")
            backend, model = backend.strip().lower(), model.strip()
        else:
            backend, model = None, spec
        if not model:
            raise ValueError(f"Bad panel model assignment: {raw!r}. No model given.")
        current = updated[key]
        updated[key] = PanelRole(**{**current.__dict__, "backend": backend or current.backend, "model": model})

    return tuple(updated[role.key] for role in roles)


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
        unattended: bool = False,
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
        # Passed down, and it was not. `create_reviewer` takes `unattended` and the
        # panel branch discarded it, so every seat was built attended — while
        # `--review-panel` alone makes `resolve_unattended` true and puts the manager
        # in unattended mode. The gate was holding reviewers configured for a human
        # who was not there.
        self.unattended = unattended
        self._members: dict[str, AutomatedReviewer] = {
            role.key: AutomatedReviewer(
                role.backend or backend_name,
                model=role.model or model,
                fake_mode=fake_mode,
                ui=self.ui,
                stage_timeout=stage_timeout,
                unattended=unattended,
            )
            for role in roles
        }
        self.chair = next(role for role in roles if role.chair)
        self._calls = 0

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

        deliberation = PanelDeliberation(
            stage_slug=stage.slug, attempt_no=attempt_no, chair_key=self.chair.key
        )
        self._calls = 0

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

        deliberation.member_calls = self._calls
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
            self._calls += 1
            verdicts.append(
                self._verdict_from_output(
                    paths=paths,
                    stage=stage,
                    attempt_no=attempt_no,
                    role=role,
                    stage_markdown=stage_markdown,
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
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        role: PanelRole,
        stage_markdown: str = "",
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

        payload = self._payload(stdout_text)
        if isinstance(payload, dict) and self._is_abstention(payload):
            return PanelVerdict(
                role_key=role.key,
                role_title=role.title,
                backend=member.backend_name,
                model=member.model,
                choice="",
                decision_token="abstain",
                blocking=False,
                reason=str(payload.get("reason") or "").strip() or "Nothing to add from this seat.",
                feedback="",
                abstained=True,
            )

        decision = member.parse_with_retry(
            paths=paths,
            stage=stage,
            attempt_no=attempt_no,
            raw_response=stdout_text,
            markdown=stage_markdown,
            label=f"panel_{role.key}_verdict",
        )
        # A veto is only as trustworthy as the answer carrying it. `blocking` is read from
        # the seat's raw payload, so if that payload's own decision is not a word the panel
        # recognises, its blocking flag is not either -- whatever a re-ask later manages to
        # recover. Keyed on the payload rather than on the degraded choice: the old guard
        # (`choice != "6"`) tested a symptom, and stopped holding the moment an unreadable
        # verdict became something the reviewer re-asks instead of aborting on.
        blocking = False
        if isinstance(payload, dict) and payload.get("blocking"):
            token = member._normalize_decision_token(payload.get("decision"))  # noqa: SLF001
            blocking = token in DECISION_TO_CHOICE
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
            # Still suppressed on an explicit abort: a seat that voted to stop the run has
            # said so through `choice`, and does not also need a veto counted against it.
            blocking=blocking and decision.choice != "6",
            reason=decision.reason,
            feedback=decision.feedback,
            concerns=concerns,
        )

    @staticmethod
    def _is_abstention(payload: dict[str, Any]) -> bool:
        token = str(payload.get("decision") or "").strip().lower()
        return token in {"abstain", "abstention", "no_comment", "pass"}

    def _payload(self, raw_response: str) -> dict[str, Any] | None:
        # `decision` identifies a seat's verdict, and without naming it the veto is read off
        # whichever object the seat's transcript happened to contain first -- a data file it
        # quoted. `blocking`, `concerns` and the abstention token all come from here, so a
        # miss does not fail loudly: the seat is recorded as having raised nothing.
        member = next(iter(self._members.values()))
        return member._extract_json_payload(raw_response, verdict_key="decision")  # noqa: SLF001

    @staticmethod
    def _is_unanimous(verdicts: list[PanelVerdict]) -> bool:
        """Unanimous among the seats that actually spoke.

        An unreachable member is not agreement, so it breaks unanimity. A deliberate
        abstention is not disagreement either — it is a seat saying it has nothing to add,
        which is exactly the behaviour that keeps the panel from padding.
        """
        if any(verdict.failed for verdict in verdicts):
            return False
        speaking = [verdict for verdict in verdicts if verdict.counts]
        if not speaking:
            return False
        return all(v.approves for v in speaking) or len({v.choice for v in speaking}) == 1

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
        self._calls += 1
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
        # Through the same read-retry-fall-back path a solo reviewer uses. A bare
        # parse here meant one unparseable synthesis cancelled the run, while an
        # *unreachable* chair fell back to the panel's own objections — the softer
        # failure got the harsher outcome, and the panel already encodes the rule it
        # was breaking: `_round` marks an unreadable seat non-blocking precisely so
        # one bad answer cannot veto.
        return chair.parse_with_retry(
            paths=paths,
            stage=stage,
            attempt_no=attempt_no,
            raw_response=stdout_text,
            markdown=stage_markdown,
            label="panel_chair_verdict",
            on_unreadable=lambda _raw: self._decision_from_dissent(
                verdicts,
                reason="The panel chair's verdict could not be read; falling back to the "
                "panel's own objections.",
            ),
        )

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
                "is useful to this run; agreement you did not actually reach is not.\n\n"
                "If your seat has nothing substantive to add on this stage, return "
                '`{"decision":"abstain"}` with a one-line reason. An abstention costs the panel '
                "nothing; a manufactured objection costs it its credibility.\n"
            )
        elif role.exposure == "none":
            round_block = (
                f"## Round {round_no} of the panel: hold or revise, independently\n\n"
                "The panel did not agree. You are deliberately **not** being shown what the "
                "others concluded, because your value to this panel is that your read is not "
                "downstream of theirs.\n\n"
                "Re-examine the artifacts and state your position again. Change it only if you "
                "find something in the work itself, not because a room you cannot see may "
                "disagree with you.\n"
            )
        else:
            peers = [verdict for verdict in previous if verdict.role_key != role.key and verdict.counts]
            if role.exposure == "objections":
                peers = [verdict for verdict in peers if not verdict.approves]
            # Peer positions are anonymized: a methodologist should weigh an objection on its
            # evidence, not defer to it because the chair signed it.
            positions = "\n\n".join(
                f"**Reviewer {chr(ord('A') + index)}** -> {verdict.decision_token}"
                + (" (BLOCKING)" if verdict.blocking else "")
                + (f"\nReason: {verdict.reason}" if verdict.reason else "")
                + (f"\nConcerns: {'; '.join(verdict.concerns)}" if verdict.concerns else "")
                for index, verdict in enumerate(peers)
            ) or "(no other seat recorded a position)"
            own = next((v for v in previous if v.role_key == role.key), None)
            round_block = (
                f"## Round {round_no} of the panel: cross-examination\n\n"
                "The panel did not agree. Below is what the other members concluded, with their "
                "identities withheld so you weigh each objection on its evidence rather than on "
                "who raised it.\n\n"
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

        effect = record_panel_effect(paths, deliberation)
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
                f"final_choice: {deliberation.decision.choice if deliberation.decision else '?'}\n"
                f"vs single pass: {effect['summary']['verdict']}"
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


#: Where the run's accumulated panel-versus-single-pass comparison is written.
PANEL_EFFECT_FILENAME = "panel_effect.json"


def record_panel_effect(paths: RunPaths, deliberation: PanelDeliberation) -> dict[str, Any]:
    """Accumulate what the panel bought over its own single-pass baseline, across the run.

    The multi-agent feedback literature has a pre-registered null at its centre: authors of 44
    papers ranked a plain single pass *above* two multi-agent tools that spent up to thirty
    times the tokens, and the tools' own builders had predicted the opposite. The mechanism
    the authors reported was that the reports "tended to raise much the same points".

    A panel that cannot be shown to change a decision is that null wearing a costume. So this
    file exists to let a run say, in its own artifacts, that the panel did not earn its cost.
    It is the least flattering thing the feature writes about itself, which is why it writes it.
    """
    path = paths.reviews_dir / "panel" / PANEL_EFFECT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)

    history: list[dict[str, Any]] = []
    if path.exists():
        try:
            previous = json.loads(read_text(path))
            if isinstance(previous, dict) and isinstance(previous.get("gates"), list):
                history = previous["gates"]
        except (OSError, json.JSONDecodeError):
            history = []

    gate = deliberation.effect()
    # A re-review of the same stage attempt replaces its earlier record rather than
    # double-counting it into the rate.
    history = [
        entry
        for entry in history
        if not (entry.get("stage") == gate["stage"] and entry.get("attempt") == gate["attempt"])
    ]
    history.append(gate)

    gates = len(history)
    changed = sum(1 for entry in history if entry.get("changed_decision"))
    contested = sum(1 for entry in history if not entry.get("round1_unanimous", True))
    overrides = sum(1 for entry in history if entry.get("chair_overridden"))
    member_calls = sum(int(entry.get("member_calls") or 0) for entry in history)
    solo_calls = sum(int(entry.get("solo_calls") or 1) for entry in history)

    summary = {
        "gates_reviewed": gates,
        "gates_where_the_panel_changed_the_decision": changed,
        "gates_where_round_1_disagreed": contested,
        "chair_overrides": overrides,
        "panel_calls": member_calls,
        "single_pass_calls": solo_calls,
        "cost_multiple": round(member_calls / solo_calls, 2) if solo_calls else None,
        "verdict": _effect_sentence(gates, changed, member_calls, solo_calls),
    }
    payload = {"summary": summary, "gates": history}
    write_text(path, json.dumps(payload, indent=2, ensure_ascii=False))
    return payload


def _effect_sentence(gates: int, changed: int, member_calls: int, solo_calls: int) -> str:
    """One line a human can act on, written to be unflattering when that is the truth."""
    if gates == 0:
        return "No gates reviewed yet."
    multiple = (member_calls / solo_calls) if solo_calls else 0
    if changed == 0:
        return (
            f"The panel reached the same decision as its own single-pass baseline at all "
            f"{gates} gate(s), at {multiple:.1f}x the reviewer cost. On this run it did not "
            "earn that cost; consider --panel-roles with fewer seats, or dropping the panel."
        )
    return (
        f"The panel changed the decision at {changed} of {gates} gate(s) that a single pass "
        f"would have settled differently, at {multiple:.1f}x the reviewer cost."
    )


def load_persona(path: Path | str | None) -> str:
    """Read a persona description, or return empty when none is configured."""
    if not path:
        return ""
    resolved = Path(path).expanduser()
    if not resolved.exists():
        raise FileNotFoundError(f"Persona file not found: {resolved}")
    return read_text(resolved).strip()
