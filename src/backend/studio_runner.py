"""Studio runner — the real Claude-backed AutoR pipeline.

This is the canonical Studio runner. It wires the existing
``ResearchManager`` from ``src/manager.py`` into the Studio's approve/feedback
gate by substituting a custom ``TerminalUI`` subclass (``_StudioTerminalUI``)
that blocks on a per-run event instead of stdin.

**Requires the Claude CLI to be on PATH** (``claude`` binary). If the CLI is
missing the service falls back to ``src/backend/mock_runner.py`` which
simulates stages with templated content.

Usage from the service:

    runner = StudioRunner(runs_dir=..., project_root=...)
    run_id = runner.start_run(project_id="...", goal="...")
    runner.approve_stage(run_id, stage_slug)          # sets gate → "5"
    runner.submit_feedback(run_id, stage_slug, "...") # sets gate → "4" + text

The interface is identical to ``MockStudioRunner`` so the service can swap
between them based on Claude availability without changing any HTTP
endpoint.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..manager import ResearchManager
from ..operator import ClaudeOperator
from ..terminal_ui import TerminalUI


@dataclass
class _RunControl:
    run_id: str
    project_id: str
    goal: str
    thread: Optional[threading.Thread] = None
    # Gate is triggered by the HTTP approve/feedback handlers. When it fires,
    # the UI subclass returns the action + feedback back to ResearchManager.
    gate: threading.Event = field(default_factory=threading.Event)
    action: str = ""          # "5" = approve, "4" = feedback, "6" = abort
    feedback: str = ""
    stopped: bool = False
    manifest_run_id: Optional[str] = None  # set by ResearchManager after _create_run


class _StudioTerminalUI(TerminalUI):
    """Studio-gate-aware TerminalUI — blocks on control.gate instead of stdin."""

    def __init__(self, control: _RunControl, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._control = control

    # --- approval gate ---
    def choose_action(self, suggestions):  # type: ignore[override]
        control = self._control
        control.gate.clear()
        control.action = ""
        while not control.gate.is_set():
            if control.stopped:
                return "6"
            control.gate.wait(timeout=1.0)
        action = control.action or "5"
        return action

    def read_multiline_feedback(self):  # type: ignore[override]
        return self._control.feedback or "Please revise the current stage."

    # --- suppress interactive prompts that would otherwise hang ---
    def read_single_line(self, prompt: str) -> str:  # type: ignore[override]
        return ""

    def read_line(self, prompt: str = "") -> str:  # type: ignore[override]
        return ""


class StudioRunner:
    """Drives real Claude-backed AutoR runs under the Studio's HITL gate."""

    def __init__(self, runs_dir: Path, project_root: Path, model: str = "sonnet") -> None:
        self.runs_dir = runs_dir
        self.project_root = project_root
        self.model = model
        self._runs: dict[str, _RunControl] = {}
        self._lock = threading.Lock()

    @staticmethod
    def is_available() -> bool:
        """True iff the Claude CLI is installed and callable.

        The service uses this to decide whether to construct a real
        ``StudioRunner`` or fall back to the simulated ``MockStudioRunner``.
        """
        return shutil.which("claude") is not None

    # ---- Lifecycle ----

    def start_run(self, project_id: str, goal: str) -> str:
        if not self.is_available():
            raise RuntimeError(
                "Claude CLI not available on PATH. Install it, or set "
                "AUTOR_STUDIO_USE_MOCK=1 to use the simulated runner instead."
            )
        # Create the control block before we know the run_id; ResearchManager
        # will allocate the actual run directory inside ``run()`` and the UI
        # subclass will remember it via a callback.
        control = _RunControl(
            run_id="",  # filled in once manager creates the run dir
            project_id=project_id,
            goal=goal.strip(),
        )
        thread = threading.Thread(
            target=self._drive,
            args=(control,),
            name=f"real-runner-{project_id}",
            daemon=True,
        )
        control.thread = thread
        thread.start()

        # Wait up to 10s for the run directory to be allocated so we can
        # return a real run_id to the caller.
        deadline = threading.Event()
        for _ in range(100):
            if control.run_id:
                break
            deadline.wait(0.1)
        if not control.run_id:
            raise RuntimeError("ResearchManager did not allocate a run directory in time.")
        with self._lock:
            self._runs[control.run_id] = control
        return control.run_id

    def approve_stage(self, run_id: str, stage_slug: str) -> None:
        control = self._require(run_id)
        control.action = "5"
        control.feedback = ""
        control.gate.set()

    def submit_feedback(self, run_id: str, stage_slug: str, feedback: str) -> None:
        control = self._require(run_id)
        control.action = "4"
        control.feedback = feedback.strip() or "Please revise the current stage."
        control.gate.set()

    def abort(self, run_id: str) -> None:
        control = self._require(run_id)
        control.stopped = True
        control.action = "6"
        control.gate.set()

    def is_active(self, run_id: str) -> bool:
        with self._lock:
            c = self._runs.get(run_id)
        return bool(c and c.thread and c.thread.is_alive())

    # ---- Internals ----

    def _require(self, run_id: str) -> _RunControl:
        """Return a live control block for run_id, lazy-resuming if needed.

        After a server restart (or any time the in-memory ``_runs`` map is
        empty for an existing run), this method spins up a new
        ``ResearchManager.resume_run`` worker thread that re-attaches to the
        on-disk manifest. The Studio gate is wired through the same
        ``_StudioTerminalUI`` so the next ``approve_stage`` / ``submit_feedback``
        call advances the existing pipeline as if no restart had happened.
        """
        with self._lock:
            c = self._runs.get(run_id)
            if c is not None and c.thread is not None and c.thread.is_alive():
                return c

        # Need to resume. The on-disk manifest must exist.
        run_root = self.runs_dir / run_id
        if not (run_root / "run_manifest.json").exists():
            raise KeyError(
                f"No run directory for run_id={run_id}. The manifest is missing on disk."
            )

        # Read the goal so the resumed worker has the right context for any
        # stage prompts that need it.
        goal = ""
        try:
            goal = (run_root / "user_input.txt").read_text(encoding="utf-8").strip()
        except Exception:
            pass
        project_id = ""
        try:
            cfg = json.loads((run_root / "run_config.json").read_text(encoding="utf-8"))
            project_id = str(cfg.get("project_id") or "")
        except Exception:
            pass

        control = _RunControl(
            run_id=run_id,
            project_id=project_id,
            goal=goal,
        )
        with self._lock:
            self._runs[run_id] = control

        # Inspect the manifest to decide HOW to resume.
        #
        # If the next non-approved stage already has a draft markdown on disk
        # (either ``.md`` or ``.tmp.md``), we wait at the gate so the human
        # can decide what to do with the existing draft instead of spawning
        # a worker that immediately re-runs the stage from scratch and burns
        # a Claude call. This handles ``human_review``, ``failed``, and even
        # ``running`` stages whose previous worker died across restarts.
        from ..manifest import ensure_run_manifest
        from ..utils import STAGES, build_run_paths
        paths = build_run_paths(run_root)
        manifest = ensure_run_manifest(paths)
        next_pending = next((s for s in manifest.stages if not s.settled), None)
        is_at_gate = False
        if next_pending is not None:
            spec = next((s for s in STAGES if s.slug == next_pending.slug), None)
            if spec is not None:
                draft = paths.stage_tmp_file(spec)
                final = paths.stage_file(spec)
                if final.exists() or draft.exists():
                    is_at_gate = True

        target = self._drive_resume_at_gate if is_at_gate else self._drive_resume_normal
        thread = threading.Thread(
            target=target,
            args=(control, run_root),
            name=f"studio-runner-resume-{run_id}",
            daemon=True,
        )
        control.thread = thread
        thread.start()

        # Give the resumed worker a beat to enter the gate wait before the
        # HTTP handler signals it.
        time.sleep(0.1)
        return control

    def _drive_resume_normal(self, control: _RunControl, run_root: Path) -> None:
        """Worker entry point for a resumed run that needs Claude execution."""
        ui = _StudioTerminalUI(control=control)
        operator = ClaudeOperator(
            command="claude",
            model=self.model,
            fake_mode=False,
            ui=ui,
        )
        manager = ResearchManager(
            project_root=self.project_root,
            runs_dir=self.runs_dir,
            operator=operator,
            ui=ui,
        )
        try:
            manager.resume_run(run_root=run_root)
        except Exception as exc:  # pragma: no cover - defensive
            import traceback
            traceback.print_exc()
            try:
                from ..manifest import update_manifest_run_status
                from ..utils import build_run_paths as _brp
                paths = _brp(run_root)
                update_manifest_run_status(
                    paths,
                    run_status="failed",
                    last_event="run.resume_failed",
                    last_error=str(exc),
                )
            except Exception:
                pass

    def _drive_resume_at_gate(self, control: _RunControl, run_root: Path) -> None:
        """Resume into a wait-on-gate state without re-calling Claude.

        The current stage already has a draft markdown sitting at
        ``human_review``. We block until the HTTP handler sets ``control.action``
        and ``control.gate``. On **approve**, we promote the draft to the final
        path, mark the stage approved in the manifest, append the summary to
        memory.md, and then hand control off to a normal ResearchManager
        ``resume_run`` starting from the NEXT stage. On **feedback**, we hand
        off to the normal resume so ResearchManager re-runs the current stage
        through its standard ``_run_stage`` loop (which will see the feedback
        via ``_StudioTerminalUI``).
        """
        from ..manifest import (
            ensure_run_manifest,
            mark_stage_approved_manifest,
            update_manifest_run_status,
        )
        from ..utils import (
            STAGES,
            append_approved_stage_summary,
            build_run_paths,
            read_text,
        )
        import shutil

        paths = build_run_paths(run_root)
        manifest = ensure_run_manifest(paths)
        gate_entry = next((s for s in manifest.stages if not s.settled), None)
        if gate_entry is None:
            # Nothing to do — everything's approved.
            update_manifest_run_status(
                paths,
                run_status="completed",
                last_event="run.resume_noop",
                current_stage_slug=None,
            )
            return
        gate_stage_spec = next((s for s in STAGES if s.slug == gate_entry.slug), None)
        if gate_stage_spec is None:
            return

        # Wait for the human's decision.
        control.gate.clear()
        control.action = ""
        while not control.gate.is_set():
            if control.stopped:
                return
            control.gate.wait(timeout=1.0)
        action = control.action or "5"
        control.action = ""

        if action == "5":
            # APPROVE: promote draft → final, mark approved, append memory.
            final_path = paths.stage_file(gate_stage_spec)
            draft_path = paths.stage_tmp_file(gate_stage_spec)
            if not final_path.exists() and draft_path.exists():
                try:
                    shutil.copyfile(draft_path, final_path)
                except Exception:
                    pass
            # Defensive: read whichever file exists; fall back to empty if both
            # are somehow missing (corrupted on-disk state).
            stage_markdown = ""
            if final_path.exists():
                stage_markdown = read_text(final_path)
            elif draft_path.exists():
                stage_markdown = read_text(draft_path)
            if stage_markdown:
                try:
                    append_approved_stage_summary(paths.memory, gate_stage_spec, stage_markdown)
                except Exception:
                    pass
            mark_stage_approved_manifest(
                paths,
                gate_stage_spec,
                attempt_no=gate_entry.attempt_count or 1,
                artifact_paths=list(gate_entry.artifact_paths),
            )
            # Now continue from the next stage. If this was the last stage,
            # mark the run completed.
            next_stage_spec = next(
                (s for s in STAGES if s.number > gate_stage_spec.number),
                None,
            )
            if next_stage_spec is None:
                update_manifest_run_status(
                    paths,
                    run_status="completed",
                    last_event="run.completed",
                    current_stage_slug=None,
                )
                return
            # Spawn the normal resume into ResearchManager from next_stage_spec.
            ui = _StudioTerminalUI(control=control)
            operator = ClaudeOperator(
                command="claude",
                model=self.model,
                fake_mode=False,
                ui=ui,
            )
            manager = ResearchManager(
                project_root=self.project_root,
                runs_dir=self.runs_dir,
                operator=operator,
                ui=ui,
            )
            try:
                manager.resume_run(run_root=run_root, start_stage=next_stage_spec)
            except Exception as exc:
                import traceback
                traceback.print_exc()
                update_manifest_run_status(
                    paths,
                    run_status="failed",
                    last_event="run.resume_failed",
                    last_error=str(exc),
                )
            return

        if action == "4":
            # FEEDBACK: re-run the current stage with the user's feedback in
            # the FIRST attempt's prompt (not the second). We do this by
            # writing the feedback to a "pending feedback" file that
            # ResearchManager._run_stage picks up at the top of its loop. If
            # the file doesn't exist (CLI runs), behavior is unchanged.
            paths.operator_state_dir.mkdir(parents=True, exist_ok=True)
            pending_path = paths.operator_state_dir / f"{gate_stage_spec.slug}.pending_feedback.txt"
            pending_path.write_text(control.feedback or "Please revise this stage.", encoding="utf-8")

            ui = _StudioTerminalUI(control=control)
            operator = ClaudeOperator(
                command="claude",
                model=self.model,
                fake_mode=False,
                ui=ui,
            )
            manager = ResearchManager(
                project_root=self.project_root,
                runs_dir=self.runs_dir,
                operator=operator,
                ui=ui,
            )
            try:
                manager.resume_run(run_root=run_root, start_stage=gate_stage_spec)
            except Exception as exc:
                import traceback
                traceback.print_exc()
                update_manifest_run_status(
                    paths,
                    run_status="failed",
                    last_event="run.resume_failed",
                    last_error=str(exc),
                )
            return

        if action == "6":
            update_manifest_run_status(
                paths,
                run_status="cancelled",
                last_event="run.cancelled",
                current_stage_slug=gate_stage_spec.slug,
            )
            return

    def _drive(self, control: _RunControl) -> None:
        # Install the Studio UI and build the operator + manager.
        ui = _StudioTerminalUI(control=control)
        operator = ClaudeOperator(
            command="claude",
            model=self.model,
            fake_mode=False,
            ui=ui,
        )
        manager = ResearchManager(
            project_root=self.project_root,
            runs_dir=self.runs_dir,
            operator=operator,
            ui=ui,
        )
        # Patch _create_run to remember the allocated run_id so start_run()
        # can return it to the caller immediately.
        original_create_run = manager._create_run

        def _patched_create_run(user_goal, **kw):
            paths = original_create_run(user_goal, **kw)
            control.run_id = paths.run_root.name
            with self._lock:
                self._runs[control.run_id] = control
            return paths

        manager._create_run = _patched_create_run  # type: ignore[method-assign]

        try:
            manager.run(
                user_goal=control.goal,
                skip_intake=True,   # skip interactive intake
                research_diagram=False,
            )
        except Exception as exc:  # pragma: no cover - defensive
            import traceback
            traceback.print_exc()
            # Best-effort mark the run as failed if we know the run_id.
            if control.run_id:
                try:
                    from ..manifest import update_manifest_run_status
                    from ..utils import build_run_paths
                    paths = build_run_paths(self.runs_dir / control.run_id)
                    update_manifest_run_status(
                        paths,
                        run_status="failed",
                        last_event="run.failed",
                        last_error=str(exc),
                    )
                except Exception:
                    pass
