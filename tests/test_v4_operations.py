from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import prewalk_engine as core  # noqa: E402


PACKET = """## Goal
Recover one native route.
## Files Read
core and operations
## Constraints And Existing Patterns
never clear an unknown agent
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
    core.Todo("2", "Implement recovery and verify it", "pending"),
    core.Todo("3", "Update operations docs and check", "pending"),
]


class V4OperationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.store = self.root / "state.json"
        self.session_id = "root-operations"
        preset = core.Preset("native", "executor-model", require_model_routing=True)
        core.start_v4_run(
            self.store,
            self.session_id,
            self.root,
            "codex",
            preset,
            now="2026-08-20T10:00:00Z",
        )
        captured = core.capture_v4_checkpoint(
            self.store,
            self.session_id,
            packet=PACKET,
            todos=TODOS,
            now="2026-08-20T10:01:00Z",
        )
        self.assertEqual(captured.status, "checkpoint_ready")

    def load(self) -> core.V4State | None:
        return core.load_v4_state(self.store, self.session_id).state

    def request(self) -> core.V4State:
        result = core.request_codex_handoff(
            self.store,
            self.session_id,
            schema_fields={"task_name", "message", "fork_turns", "model"},
        )
        return result.state

    def make_incomplete(self, reason: str = "launch failed") -> core.V4State:
        state = self.request()
        decision = core.validate_codex_spawn(
            self.store,
            self.session_id,
            {
                "task_name": state.route_task_name,
                "message": core.codex_route_message(state),
                "fork_turns": "none",
                "model": state.executor_model,
            },
            tool_use_id="tool-failed",
        )
        self.assertTrue(decision.allowed)
        failed = core.bind_codex_executor(
            self.store, self.session_id, tool_use_id="tool-failed", agent_id="",
            success=False, detail=reason,
        )
        self.assertEqual(failed.state.phase, "incomplete")
        return failed.state

    def test_status_exposes_operations_but_never_token_or_packet(self) -> None:
        state = self.request()
        loaded = core.load_v4_state(self.store, self.session_id)
        status = core.format_v4_status(loaded)

        self.assertIn("handoff_requested", status)
        self.assertIn("host: codex", status)
        self.assertIn("evidence: verified", status)
        self.assertIn("remaining(2)", status)
        self.assertIn("token=sha256:", status)
        self.assertNotIn(state.route_token, status)
        self.assertNotIn(state.route_token[:8], status)
        self.assertNotIn(PACKET, status)
        self.assertIn("next: $prewalk:pw-go", status)

    def test_idle_and_failure_statuses_recommend_exactly_one_safe_command(self) -> None:
        idle = core.format_v4_status(core.load_v4_state(self.store, "missing"))
        self.assertEqual(idle.count("next:"), 1)
        self.assertIn("$prewalk:prewalk", idle)

        self.make_incomplete()
        incomplete = core.format_v4_status(
            core.load_v4_state(self.store, self.session_id)
        )
        self.assertEqual(incomplete.count("next:"), 1)
        self.assertIn("$prewalk:pw-retry", incomplete)

    def test_stale_detection_never_clears_or_unbinds_unknown_executor(self) -> None:
        state = self.request()
        core.validate_codex_spawn(
            self.store,
            self.session_id,
            {
                "task_name": state.route_task_name,
                "message": core.codex_route_message(state),
                "fork_turns": "none",
                "model": state.executor_model,
            },
            tool_use_id="tool-route",
        )
        running = core.bind_codex_executor(
            self.store,
            self.session_id,
            tool_use_id="tool-route",
            agent_id="agent-live-or-unknown",
            success=True,
        ).state
        marked = core.detect_v4_stale(
            self.store,
            self.session_id,
            # Far-future clock: request_codex_handoff stamps the route with the
            # real current time, so a fixed 2026 date goes stale on real clocks
            # past it (upstream time bomb). Use 2030 like the revise test.
            now="2030-08-22T10:00:00Z",
            timeout_seconds=60,
        )

        self.assertEqual(marked.status, "stale")
        self.assertEqual(marked.state.executor_agent_id, running.executor_agent_id)
        self.assertIn("no agent was stopped or cleared", marked.state.last_error)
        self.assertIn("next: $prewalk:pw-reconcile", core.format_v4_status(
            core.load_v4_state(self.store, self.session_id)
        ))

    def test_reconcile_requires_explicit_liveness_confirmation_and_is_idempotent(self) -> None:
        self.request()
        unchanged = core.reconcile_v4_route(
            self.store, self.session_id, confirmed_not_running=False
        )
        self.assertEqual(unchanged.status, "confirmation_required")
        self.assertEqual(self.load().phase, core.V4_HANDOFF_REQUESTED)

        reconciled = core.reconcile_v4_route(
            self.store,
            self.session_id,
            confirmed_not_running=True,
            detail="native agent list proves no matching agent",
        )
        duplicate = core.reconcile_v4_route(
            self.store,
            self.session_id,
            confirmed_not_running=True,
            detail="native agent list proves no matching agent",
        )
        self.assertEqual(reconciled.state.phase, core.V4_INCOMPLETE)
        self.assertEqual(duplicate.state.revision, reconciled.state.revision)

    def test_retry_retains_checkpoint_and_cannot_duplicate_pending_route(self) -> None:
        failed = self.make_incomplete()
        prepared = core.prepare_v4_retry(self.store, self.session_id)

        self.assertEqual(prepared.state.phase, core.V4_CHECKPOINT_READY)
        self.assertEqual(prepared.state.packet, PACKET)
        self.assertEqual(prepared.state.todos, failed.todos)
        self.assertEqual(prepared.state.todos[0].status, "completed")
        requested = core.request_codex_handoff(
            self.store,
            self.session_id,
            schema_fields={"task_name", "message", "fork_turns", "model"},
        )
        duplicate = core.prepare_v4_retry(self.store, self.session_id)
        self.assertEqual(duplicate.status, "handoff_requested")
        self.assertEqual(duplicate.state.route_token, requested.state.route_token)
        self.assertEqual(duplicate.state.route_attempt, requested.state.route_attempt)

    def test_incomplete_can_be_revised_but_stale_cannot_bypass_reconcile(self) -> None:
        self.make_incomplete()
        revised = core.revise_v4_checkpoint(
            self.store, self.session_id, "change the remaining adapter work"
        )
        self.assertEqual(revised.state.phase, core.V4_PLANNING)
        self.assertEqual(revised.state.route_token, "")
        self.assertNotIn("repeat task #1", revised.message.lower())

        core.clear_state(self.store, self.session_id)
        preset = core.Preset("native", "executor-model", require_model_routing=True)
        core.start_v4_run(self.store, self.session_id, self.root, "codex", preset)
        core.capture_v4_checkpoint(
            self.store, self.session_id, packet=PACKET, todos=TODOS
        )
        self.request()
        core.detect_v4_stale(
            self.store,
            self.session_id,
            now="2030-08-22T10:00:00Z",
            timeout_seconds=1,
        )
        blocked = core.revise_v4_checkpoint(self.store, self.session_id, "change it")
        self.assertEqual(blocked.status, "not_ready")
        self.assertEqual(self.load().phase, core.V4_STALE)


if __name__ == "__main__":
    unittest.main()
