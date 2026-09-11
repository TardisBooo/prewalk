from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import prewalk_engine as core  # noqa: E402


PACKET = """## Goal
Route one Codex executor.
## Files Read
core and hooks
## Constraints And Existing Patterns
bind exact identities
## Full Todo List
three real tasks
## Task 1 Changes
checkpoint complete
## Verification Already Run
unit test passed
## Remaining Work
two tasks
## Risks / Do Not Repeat
do not repeat task 1
"""


TODOS = [
    core.Todo("1", "Build checkpoint and test it", "completed"),
    core.Todo("2", "Implement route and verify it", "pending"),
    core.Todo("3", "Update docs and check them", "pending"),
]


class V4CodexRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.store = self.root / "state.json"
        self.session_id = "codex-root"
        self.arm_checkpoint()

    def arm_checkpoint(self) -> None:
        preset = core.Preset(
            "native", "gpt-5.6-terra", executor_effort="medium",
            require_model_routing=True,
        )
        core.start_v4_run(self.store, self.session_id, self.root, "codex", preset)
        captured = core.capture_v4_checkpoint(
            self.store, self.session_id, packet=PACKET, todos=TODOS
        )
        self.assertEqual(captured.status, "checkpoint_ready")

    def load(self) -> core.V4State | None:
        return core.load_v4_state(self.store, self.session_id).state

    def request(self) -> core.V4CheckpointResult:
        return core.request_codex_handoff(
            self.store,
            self.session_id,
            schema_fields={
                "task_name", "message", "fork_turns", "model", "reasoning_effort"
            },
        )

    def exact_input(self, state: core.V4State) -> dict:
        return {
            "task_name": state.route_task_name,
            "message": core.codex_route_message(state),
            "fork_turns": "all",
            "model": state.executor_model,
            "reasoning_effort": state.executor_effort,
        }

    def request_fork_context(self) -> core.V4CheckpointResult:
        return core.request_codex_handoff(
            self.store,
            self.session_id,
            schema_fields={"fork_context", "items", "message", "model", "reasoning_effort"},
        )

    def exact_fork_context_input(self, state: core.V4State) -> dict:
        return {
            "fork_context": False,
            "message": core.codex_route_message(state),
            "model": state.executor_model,
            "reasoning_effort": state.executor_effort,
        }

    def test_live_schema_must_prove_required_model_without_consuming_checkpoint(self) -> None:
        result = core.request_codex_handoff(
            self.store,
            self.session_id,
            schema_fields={"task_name", "message", "fork_turns"},
        )

        self.assertEqual(result.status, "unsupported_route")
        self.assertEqual(self.load().phase, core.V4_CHECKPOINT_READY)
        self.assertIn("retained", result.message)

    def test_route_uses_exact_persisted_packet_and_supported_effort(self) -> None:
        result = self.request()
        state = result.state

        self.assertEqual(result.status, "handoff_requested")
        self.assertTrue(state.model_routing_proven)
        self.assertTrue(state.effort_routing_proven)
        # The durable packet is always present so current-schema model routing
        # can safely use fork_context=false.
        self.assertIn(PACKET, result.message)
        self.assertEqual(result.message, core.codex_route_message(state))
        self.assertIn(state.route_token, result.message)

        core.clear_state(self.store, self.session_id)
        self.arm_checkpoint()
        packet_preset = core.Preset(
            "native", "gpt-5.6-terra", executor_effort="medium",
            require_model_routing=True, fork_turns="none",
        )
        core.start_v4_run(self.store, self.session_id, self.root, "codex", packet_preset)
        core.capture_v4_checkpoint(self.store, self.session_id, packet=PACKET, todos=TODOS)
        packet_mode = core.request_codex_handoff(
            self.store,
            self.session_id,
            schema_fields={"task_name", "message", "fork_turns", "model"},
        )
        self.assertEqual(packet_mode.status, "handoff_requested")
        self.assertIn(PACKET, packet_mode.message)

    def test_current_fork_context_schema_routes_and_validates_exactly(self) -> None:
        result = self.request_fork_context()
        self.assertEqual(result.status, "handoff_requested")
        state = result.state
        accepted = core.validate_codex_spawn(
            self.store,
            self.session_id,
            self.exact_fork_context_input(state),
            tool_use_id="tool-current",
        )
        self.assertTrue(accepted.allowed)
        self.assertEqual(accepted.state.route_tool_use_id, "tool-current")

    def test_current_schema_rejects_wrong_fork_context(self) -> None:
        state = self.request_fork_context().state
        malformed = self.exact_fork_context_input(state)
        malformed["fork_context"] = True
        decision = core.validate_codex_spawn(
            self.store, self.session_id, malformed, tool_use_id="tool-wrong-fork"
        )
        self.assertFalse(decision.allowed)
        self.assertIn("fork_context must be false", decision.message)

    def test_malformed_intended_spawn_is_denied_and_becomes_retryable(self) -> None:
        state = self.request().state
        malformed = self.exact_input(state)
        malformed["fork_turns"] = "none"

        decision = core.validate_codex_spawn(
            self.store, self.session_id, malformed, tool_use_id="tool-bad"
        )

        self.assertTrue(decision.handled)
        self.assertFalse(decision.allowed)
        self.assertIn("fork_turns", decision.message)
        loaded = core.load_v4_state(self.store, self.session_id)
        self.assertEqual(loaded.status, "incomplete")
        self.assertEqual(loaded.next_command, "pw-retry")

    def test_unrelated_spawn_and_agent_cannot_bind_or_complete(self) -> None:
        state = self.request().state
        unrelated = core.validate_codex_spawn(
            self.store,
            self.session_id,
            {"task_name": "other", "message": "other", "fork_turns": "none"},
            tool_use_id="tool-other",
        )
        self.assertFalse(unrelated.handled)

        accepted = core.validate_codex_spawn(
            self.store, self.session_id, self.exact_input(state), tool_use_id="tool-route"
        )
        self.assertTrue(accepted.allowed)
        wrong_post = core.bind_codex_executor(
            self.store,
            self.session_id,
            tool_use_id="tool-other",
            agent_id="agent-other",
            success=True,
        )
        self.assertFalse(wrong_post.handled)
        bound = core.bind_codex_executor(
            self.store,
            self.session_id,
            tool_use_id="tool-route",
            agent_id="agent-route",
            success=True,
        )
        self.assertEqual(bound.state.phase, core.V4_EXECUTOR_RUNNING)
        duplicate = core.bind_codex_executor(
            self.store,
            self.session_id,
            tool_use_id="tool-route",
            agent_id="agent-route",
            success=True,
        )
        self.assertTrue(duplicate.allowed)
        self.assertEqual(duplicate.state.revision, bound.state.revision)

        unrelated_stop = core.finish_v4_executor(
            self.store,
            self.session_id,
            agent_id="agent-other",
            result="PREWALK_COMPLETE",
            event_id="stop-other",
        )
        self.assertFalse(unrelated_stop.handled)
        self.assertEqual(self.load().phase, core.V4_EXECUTOR_RUNNING)

        complete = core.finish_v4_executor(
            self.store,
            self.session_id,
            agent_id="agent-route",
            result="Done\nPREWALK_COMPLETE",
            event_id="stop-route",
        )
        self.assertTrue(complete.allowed)
        self.assertIsNone(self.load())

    def test_spawn_failure_missing_marker_and_interruption_are_incomplete(self) -> None:
        state = self.request().state
        core.validate_codex_spawn(
            self.store, self.session_id, self.exact_input(state), tool_use_id="tool-route"
        )
        failed = core.bind_codex_executor(
            self.store,
            self.session_id,
            tool_use_id="tool-route",
            agent_id="",
            success=False,
            detail="permission denied",
        )
        self.assertFalse(failed.allowed)
        self.assertEqual(failed.state.phase, core.V4_INCOMPLETE)

        self.arm_checkpoint()
        state = self.request().state
        core.validate_codex_spawn(
            self.store, self.session_id, self.exact_input(state), tool_use_id="tool-route"
        )
        core.bind_codex_executor(
            self.store,
            self.session_id,
            tool_use_id="tool-route",
            agent_id="agent-route",
            success=True,
        )
        missing = core.finish_v4_executor(
            self.store,
            self.session_id,
            agent_id="agent-route",
            result="Finished without marker",
            event_id="stop-missing",
        )
        self.assertFalse(missing.allowed)
        self.assertEqual(missing.state.phase, core.V4_INCOMPLETE)

        self.arm_checkpoint()
        state = self.request().state
        core.validate_codex_spawn(
            self.store, self.session_id, self.exact_input(state), tool_use_id="tool-route"
        )
        core.bind_codex_executor(
            self.store,
            self.session_id,
            tool_use_id="tool-route",
            agent_id="agent-route",
            success=True,
        )
        interrupted = core.interrupt_v4_executor(
            self.store,
            self.session_id,
            reason="executor interrupted by user",
            event_id="root-stop-interrupt",
        )
        self.assertTrue(interrupted.handled)
        self.assertEqual(interrupted.state.phase, core.V4_INCOMPLETE)

    def test_explicit_manual_fallback_uses_durable_packet_and_scoped_completion(self) -> None:
        resumed = core.resume_codex_manual(self.store, self.session_id)

        self.assertEqual(resumed.status, "executor_running")
        self.assertIn(PACKET, resumed.message)
        self.assertEqual(
            resumed.state.executor_agent_id, f"manual-root:{self.session_id}"
        )
        completed = core.finish_codex_manual(
            self.store, self.session_id, complete=True
        )
        self.assertEqual(completed.status, "complete")
        self.assertIsNone(self.load())

    def test_manual_completion_cannot_clear_a_native_agent_route(self) -> None:
        state = self.request().state
        core.validate_codex_spawn(
            self.store, self.session_id, self.exact_input(state), tool_use_id="tool-route"
        )
        core.bind_codex_executor(
            self.store,
            self.session_id,
            tool_use_id="tool-route",
            agent_id="agent-route",
            success=True,
        )

        rejected = core.finish_codex_manual(
            self.store, self.session_id, complete=True
        )

        self.assertEqual(rejected.status, "not_manual")
        self.assertEqual(self.load().phase, core.V4_EXECUTOR_RUNNING)


if __name__ == "__main__":
    unittest.main()
