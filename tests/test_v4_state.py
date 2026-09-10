from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import prewalk_engine as core  # noqa: E402


PACKET = """## Goal
Persist the handoff.
## Files Read
core and tests
## Constraints And Existing Patterns
locked JSON store
## Full Todo List
three real tasks
## Task 1 Changes
durable schema
## Verification Already Run
unit tests passed
## Remaining Work
adapters and docs
## Risks / Do Not Repeat
do not repeat task 1
"""


def checkpoint_todos() -> list[core.Todo]:
    return [
        core.Todo("1", "Implement state and test persistence", "completed"),
        core.Todo("2", "Update adapters and verify hooks", "pending"),
        core.Todo("3", "Update docs and check examples", "pending"),
    ]


class V4StateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = Path(self.temp_dir.name) / "state.json"
        self.session_id = "root-session"
        self.workspace_id = core.workspace_identity(self.temp_dir.name)

    def planning_state(self, session_id: str | None = None) -> core.V4State:
        return core.new_v4_state(
            session_id or self.session_id,
            self.workspace_id,
            "codex",
            executor_model="executor-model",
            now="2026-08-20T10:00:00Z",
        )

    def create_checkpoint(self) -> core.V4State:
        core.create_v4_state(self.store, self.planning_state())
        return core.apply_v4_transition(
            self.store,
            self.session_id,
            expected_phases=[core.V4_PLANNING],
            target_phase=core.V4_CHECKPOINT_READY,
            event_id="stop-1",
            now="2026-08-20T10:01:00Z",
            updates={
                "todos": checkpoint_todos(),
                "packet": PACKET,
                "verification_evidence": ["pytest: passed"],
                "checkpoint_at": "2026-08-20T10:01:00Z",
            },
        )

    def test_checkpoint_survives_a_fresh_process_without_transcript_input(self) -> None:
        checkpoint = self.create_checkpoint()
        self.assertEqual(checkpoint.phase, core.V4_CHECKPOINT_READY)

        script = """
import json, sys
import prewalk_engine as core
result = core.load_v4_state(sys.argv[1], sys.argv[2], workspace_id=sys.argv[3])
print(json.dumps({
    "status": result.status,
    "packet": result.state.packet if result.state else "",
    "todos": [todo.content for todo in result.state.todos] if result.state else [],
    "evidence": result.state.verification_evidence if result.state else [],
}))
"""
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        result = subprocess.run(
            [sys.executable, "-c", script, str(self.store), self.session_id, self.workspace_id],
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        loaded = json.loads(result.stdout)
        self.assertEqual(loaded["status"], "ok")
        self.assertEqual(loaded["packet"], PACKET)
        self.assertEqual(len(loaded["todos"]), 3)
        self.assertEqual(loaded["evidence"], ["pytest: passed"])

    def test_transition_is_atomic_and_duplicate_event_is_idempotent(self) -> None:
        first = self.create_checkpoint()
        duplicate = core.apply_v4_transition(
            self.store,
            self.session_id,
            expected_phases=[core.V4_PLANNING],
            target_phase=core.V4_CHECKPOINT_READY,
            event_id="stop-1",
            updates={"packet": "this must not replace the durable packet"},
            now="2026-08-20T10:09:00Z",
        )
        self.assertEqual(duplicate.packet, PACKET)
        self.assertEqual(duplicate.revision, first.revision)
        self.assertEqual(duplicate.updated_at, first.updated_at)
        self.assertEqual(duplicate.processed_event_ids, ["stop-1"])

        with self.assertRaisesRegex(core.V4StateError, "cannot transition"):
            core.apply_v4_transition(
                self.store,
                self.session_id,
                expected_phases=[core.V4_PLANNING],
                target_phase=core.V4_CHECKPOINT_READY,
                event_id="different-stop",
            )

    def test_route_identity_and_failure_phase_invariants(self) -> None:
        self.create_checkpoint()
        requested = core.apply_v4_transition(
            self.store,
            self.session_id,
            expected_phases=[core.V4_CHECKPOINT_READY],
            target_phase=core.V4_HANDOFF_REQUESTED,
            event_id="route-1",
            updates={
                "route_token": "secret-token",
                "route_task_name": "prewalk_executor_1",
                "route_attempt": 1,
                "route_requested_at": "2026-08-20T10:02:00Z",
            },
            now="2026-08-20T10:02:00Z",
        )
        self.assertEqual(requested.phase, core.V4_HANDOFF_REQUESTED)

        running = core.apply_v4_transition(
            self.store,
            self.session_id,
            expected_phases=[core.V4_HANDOFF_REQUESTED],
            target_phase=core.V4_EXECUTOR_RUNNING,
            event_id="agent-start-1",
            updates={
                "route_tool_use_id": "tool-1",
                "executor_agent_id": "agent-1",
                "executor_started_at": "2026-08-20T10:03:00Z",
            },
            now="2026-08-20T10:03:00Z",
        )
        self.assertEqual(running.executor_agent_id, "agent-1")

        with self.assertRaisesRegex(core.V4StateError, "recovery error"):
            core.apply_v4_transition(
                self.store,
                self.session_id,
                expected_phases=[core.V4_EXECUTOR_RUNNING],
                target_phase=core.V4_INCOMPLETE,
                event_id="agent-stop-1",
                updates={"last_error": ""},
            )

        stale = core.apply_v4_transition(
            self.store,
            self.session_id,
            expected_phases=[core.V4_EXECUTOR_RUNNING],
            target_phase=core.V4_STALE,
            event_id="stale-deadline-1",
            updates={"last_error": "executor liveness is unknown"},
            now="2026-08-20T10:04:00Z",
        )
        self.assertEqual(stale.phase, core.V4_STALE)
        recovery = core.load_v4_state(
            self.store, self.session_id, workspace_id=self.workspace_id
        )
        self.assertEqual(recovery.status, "stale")
        self.assertEqual(recovery.next_command, "pw-reconcile")
        self.assertIn("still running", recovery.message)

    def test_v3_record_is_reset_without_touching_another_session(self) -> None:
        legacy = core.PrewalkState(session_id=self.session_id)
        core.save_state(self.store, legacy)
        other = self.planning_state("other-root")
        core.create_v4_state(self.store, other)

        result = core.load_v4_state(self.store, self.session_id)

        self.assertEqual(result.status, "legacy_reset")
        self.assertEqual(result.next_command, "prewalk")
        self.assertIn("0.3.x", result.message)
        self.assertIsNone(core.load_state(self.store, self.session_id))
        other_result = core.load_v4_state(
            self.store, "other-root", workspace_id=self.workspace_id
        )
        self.assertEqual(other_result.status, "ok")

    def test_unknown_future_schema_is_preserved_and_fails_closed(self) -> None:
        future = self.planning_state().to_dict()
        future["schema_version"] = 5
        self.store.write_text(
            json.dumps({self.session_id: future}), encoding="utf-8"
        )

        result = core.load_v4_state(self.store, self.session_id)

        self.assertEqual(result.status, "unsupported_version")
        self.assertEqual(result.next_command, "pw-doctor")
        self.assertIn("was not changed", result.message)
        stored = json.loads(self.store.read_text(encoding="utf-8"))
        self.assertEqual(stored[self.session_id]["schema_version"], 5)

    def test_corrupt_partial_and_workspace_mismatch_have_deterministic_recovery(self) -> None:
        self.store.write_text("{not json", encoding="utf-8")
        corrupt = core.load_v4_state(self.store, self.session_id)
        self.assertEqual(corrupt.status, "corrupt_store")
        self.assertEqual(corrupt.next_command, "prewalk")
        self.assertTrue(self.store.with_name("state.json.corrupt").is_file())

        self.store.write_text(json.dumps({self.session_id: {
            "schema_version": 4,
            "root_session_id": self.session_id,
        }}), encoding="utf-8")
        partial = core.load_v4_state(self.store, self.session_id)
        self.assertEqual(partial.status, "invalid")
        self.assertEqual(partial.next_command, "pw-off")
        self.assertIn("partial", partial.message)

        self.store.write_text(json.dumps({self.session_id: {
            **self.planning_state().to_dict(),
            "created_at": "not-a-timestamp",
        }}), encoding="utf-8")
        invalid_timestamp = core.load_v4_state(self.store, self.session_id)
        self.assertEqual(invalid_timestamp.status, "invalid")
        self.assertIn("ISO-8601", invalid_timestamp.message)

        self.store.unlink()
        core.create_v4_state(self.store, self.planning_state())
        mismatch = core.load_v4_state(
            self.store, self.session_id, workspace_id="ws-another-workspace"
        )
        self.assertEqual(mismatch.status, "workspace_mismatch")
        self.assertEqual(mismatch.next_command, "pw-doctor")
        self.assertEqual(
            core.load_v4_state(
                self.store, self.session_id, workspace_id=self.workspace_id
            ).status,
            "ok",
        )

    def test_pause_todo_and_unproven_checkpoint_are_rejected(self) -> None:
        state = self.planning_state()
        state.phase = core.V4_CHECKPOINT_READY
        state.todos = checkpoint_todos() + [
            core.Todo("pause", "PAUSE for handoff", "in_progress")
        ]
        state.packet = PACKET
        state.checkpoint_at = "2026-08-20T10:01:00Z"
        state.updated_at = "2026-08-20T10:01:00Z"
        state.last_event_at = "2026-08-20T10:01:00Z"
        state.verification_evidence = ["tests passed"]
        with self.assertRaisesRegex(core.V4StateError, "PAUSE"):
            core.validate_v4_state(state)

        state.todos = checkpoint_todos()
        state.verification_evidence = []
        with self.assertRaisesRegex(core.V4StateError, "evidence or an explicit warning"):
            core.validate_v4_state(state)
        state.verification_warning = "Task 1 changed docs only; no executable check was available."
        core.validate_v4_state(state)

    def test_concurrent_processes_preserve_every_root_record(self) -> None:
        script = """
import sys
import prewalk_engine as core
state = core.new_v4_state(
    sys.argv[2], sys.argv[3], "codex", executor_model="executor-model"
)
core.create_v4_state(sys.argv[1], state)
"""
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", script, str(self.store), f"root-{index}", self.workspace_id],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for index in range(8)
        ]
        errors = []
        for process in processes:
            _, stderr = process.communicate(timeout=10)
            if process.returncode:
                errors.append(stderr)
        self.assertEqual(errors, [])
        stored = json.loads(self.store.read_text(encoding="utf-8"))
        self.assertEqual(set(stored), {f"root-{index}" for index in range(8)})


if __name__ == "__main__":
    unittest.main()
