from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import prewalk_engine as core  # noqa: E402


PACKET = """## Goal
Route one Claude executor.
## Files Read
core and Claude hooks
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


class V4ClaudeRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.store = self.root / "state.json"
        self.session_id = "claude-root"
        self.arm_checkpoint()

    def arm_checkpoint(self) -> None:
        preset = core.Preset("native", "haiku", require_model_routing=True)
        core.start_v4_run(self.store, self.session_id, self.root, "claude", preset)
        captured = core.capture_v4_checkpoint(
            self.store, self.session_id, packet=PACKET, todos=TODOS
        )
        self.assertEqual(captured.status, "checkpoint_ready")

    def load(self) -> core.V4State | None:
        return core.load_v4_state(self.store, self.session_id).state

    def request(self) -> core.V4State:
        result = core.request_claude_handoff(
            self.store, self.session_id, environment={}
        )
        self.assertEqual(result.status, "handoff_requested")
        return result.state

    @staticmethod
    def token_input(state: core.V4State, **extra) -> dict:
        return {
            "prompt": f"PREWALK_HANDOFF_TOKEN: {state.route_token}",
            **extra,
        }

    def test_rewrite_uses_durable_packet_and_preserves_valid_fields(self) -> None:
        state = self.request()
        decision = core.validate_claude_agent_call(
            self.store,
            self.session_id,
            self.token_input(
                state,
                run_in_background=True,
                isolation="worktree",
                description="caller description",
            ),
            tool_use_id="tool-route",
            environment={},
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(
            decision.updated_input["subagent_type"], core.CLAUDE_EXECUTOR_AGENT
        )
        self.assertEqual(decision.updated_input["model"], "haiku")
        self.assertTrue(decision.updated_input["run_in_background"])
        self.assertEqual(decision.updated_input["isolation"], "worktree")
        self.assertEqual(decision.updated_input["description"], "caller description")
        self.assertIn(PACKET, decision.updated_input["prompt"])
        self.assertEqual(decision.updated_input["prompt"], core.claude_route_message(state))

    def test_unrelated_nested_and_parallel_calls_cannot_consume_route(self) -> None:
        state = self.request()
        unrelated = core.validate_claude_agent_call(
            self.store,
            self.session_id,
            {"prompt": "unrelated"},
            tool_use_id="tool-unrelated",
            environment={},
        )
        self.assertFalse(unrelated.handled)
        accepted = core.validate_claude_agent_call(
            self.store,
            self.session_id,
            self.token_input(state),
            tool_use_id="tool-route",
            environment={},
        )
        self.assertTrue(accepted.allowed)
        parallel = core.validate_claude_agent_call(
            self.store,
            self.session_id,
            self.token_input(state),
            tool_use_id="tool-parallel",
            environment={},
        )
        self.assertTrue(parallel.handled)
        self.assertFalse(parallel.allowed)
        self.assertEqual(self.load().route_tool_use_id, "tool-route")

    def test_runtime_override_conflict_is_retryable(self) -> None:
        state = self.request()
        decision = core.validate_claude_agent_call(
            self.store,
            self.session_id,
            self.token_input(state),
            tool_use_id="tool-conflict",
            environment={"CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"},
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.state.phase, core.V4_INCOMPLETE)
        self.assertIn("override-conflict", decision.message)

    def test_posttooluse_only_acknowledges_then_exact_subagent_owns_completion(self) -> None:
        state = self.request()
        core.validate_claude_agent_call(
            self.store,
            self.session_id,
            self.token_input(state),
            tool_use_id="tool-route",
            environment={},
        )
        acknowledged = core.acknowledge_claude_agent_call(
            self.store, self.session_id, tool_use_id="tool-route"
        )
        self.assertEqual(acknowledged.state.phase, core.V4_HANDOFF_REQUESTED)
        bound = core.bind_claude_executor(
            self.store,
            self.session_id,
            agent_id="agent-route",
            agent_type="prewalk-executor",
        )
        self.assertEqual(bound.state.phase, core.V4_EXECUTOR_RUNNING)
        unrelated = core.finish_v4_executor(
            self.store,
            self.session_id,
            agent_id="agent-other",
            result="PREWALK_COMPLETE",
            event_id="stop-other",
        )
        self.assertFalse(unrelated.handled)
        complete = core.finish_v4_executor(
            self.store,
            self.session_id,
            agent_id="agent-route",
            result="PREWALK_COMPLETE",
            event_id="stop-route",
        )
        self.assertTrue(complete.allowed)
        self.assertIsNone(self.load())

    def test_permission_failure_and_incomplete_marker_retain_checkpoint(self) -> None:
        state = self.request()
        core.validate_claude_agent_call(
            self.store,
            self.session_id,
            self.token_input(state),
            tool_use_id="tool-denied",
            environment={},
        )
        denied = core.fail_claude_agent_call(
            self.store,
            self.session_id,
            tool_use_id="tool-denied",
            reason="permission denied",
        )
        self.assertEqual(denied.state.phase, core.V4_INCOMPLETE)
        self.assertEqual(denied.state.packet, PACKET)

        self.arm_checkpoint()
        state = self.request()
        core.validate_claude_agent_call(
            self.store,
            self.session_id,
            self.token_input(state),
            tool_use_id="tool-route",
            environment={},
        )
        core.bind_claude_executor(
            self.store,
            self.session_id,
            agent_id="agent-route",
            agent_type=core.CLAUDE_EXECUTOR_AGENT,
        )
        incomplete = core.finish_v4_executor(
            self.store,
            self.session_id,
            agent_id="agent-route",
            result="PREWALK_INCOMPLETE: verification failed",
            event_id="stop-incomplete",
        )
        self.assertEqual(incomplete.state.phase, core.V4_INCOMPLETE)
        self.assertEqual(incomplete.state.last_error, "verification failed")

    def test_request_after_reload_still_routes_exact_persisted_packet(self) -> None:
        requested = self.request()
        reloaded = core.load_v4_state(self.store, self.session_id).state

        self.assertEqual(reloaded.route_token, requested.route_token)
        self.assertIn(PACKET, core.claude_route_instruction(reloaded))
        decision = core.validate_claude_agent_call(
            self.store,
            self.session_id,
            self.token_input(reloaded),
            tool_use_id="tool-resumed",
            environment={},
        )
        self.assertEqual(decision.updated_input["prompt"], core.claude_route_message(reloaded))


if __name__ == "__main__":
    unittest.main()
