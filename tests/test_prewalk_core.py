"""Legacy 0.3 machine behavior plus vendored-package integrity."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import prewalk_engine as core  # noqa: E402


class PrewalkEngineLegacyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = Path(self.temp_dir.name) / "state.json"
        self.session_id = "test-session"
        self.preset = core.Preset(
            name="test",
            executor_model="executor-model",
            executor_effort="medium",
        )

    def start_ready_run(self) -> core.PrewalkState:
        state = core.start_run(
            self.store,
            self.session_id,
            self.preset,
            auto_swap=False,
        )
        state.phase = core.READY
        state.first_edit_landed = True
        core.save_state(self.store, state)
        return state

    def checkpoint_run(self) -> core.PrewalkState:
        self.start_ready_run()
        action = core.on_todos_changed(self.store, self.session_id, [
            core.Todo("1", "Update core and test", "completed"),
            core.Todo("2", "Update adapters and verify", "pending"),
            core.Todo("3", "Update docs and check", "pending"),
            core.Todo("pause", "PAUSE for handoff", "in_progress"),
        ])
        self.assertEqual(action.system_message, core.PAUSED_HINT)
        state = core.load_state(self.store, self.session_id)
        self.assertIsNotNone(state)
        return state

    def test_ready_checkpoint_stays_ready_and_surfaces_pause_hint(self) -> None:
        self.start_ready_run()
        todos = [
            core.Todo("1", "Update core and test", "completed"),
            core.Todo("2", "Update adapters and verify", "pending"),
            core.Todo("3", "Update docs and check", "pending"),
            core.Todo("pause", "PAUSE for handoff", "in_progress"),
        ]

        action = core.on_todos_changed(self.store, self.session_id, todos)

        self.assertIsNotNone(action)
        self.assertEqual(action.system_message, core.PAUSED_HINT)
        state = core.load_state(self.store, self.session_id)
        self.assertIsNotNone(state)
        self.assertEqual(state.phase, core.PAUSED)
        self.assertEqual(state.todos_remaining, 2)
        self.assertEqual(state.checkpoint_evidence, "observed-edit")

    def test_checkpoint_rejects_an_incomplete_task_one(self) -> None:
        self.start_ready_run()

        action = core.on_todos_changed(self.store, self.session_id, [
            core.Todo("1", "Update core and test", "in_progress"),
            core.Todo("2", "Update adapters and verify", "pending"),
            core.Todo("pause", "PAUSE for handoff", "in_progress"),
        ])

        self.assertIn("task #1 must be completed", action.system_message)
        self.assertEqual(core.load_state(self.store, self.session_id).phase, core.READY)

    def test_codex_handoff_is_explicit_and_idempotent(self) -> None:
        self.checkpoint_run()

        action = core.on_pw_go(self.store, self.session_id, host="codex")

        self.assertIn("`model=\"executor-model\"`", action.additional_context)
        self.assertIn("`task_name=\"prewalk_executor_1\"`", action.additional_context)
        self.assertIn("`fork_turns=\"all\"`", action.additional_context)
        self.assertIn("`reasoning_effort=\"medium\"`", action.additional_context)
        state = core.load_state(self.store, self.session_id)
        self.assertIsNotNone(state)
        self.assertEqual(state.phase, core.HANDOFF_REQUESTED)
        self.assertFalse(state.handoff_done)

        duplicate = core.on_pw_go(self.store, self.session_id, host="codex")
        self.assertIn("pending confirmation", duplicate.additional_context)

        confirmed = core.on_handoff_confirm(self.store, self.session_id)
        self.assertIn("confirmed", confirmed.system_message)
        self.assertEqual(core.load_state(self.store, self.session_id).phase, core.EXECUTOR)

    def test_claude_launch_and_agent_binding_require_exact_ids(self) -> None:
        self.checkpoint_run()
        core.on_pw_go(self.store, self.session_id, host="claude")
        state = core.load_state(self.store, self.session_id)
        state.handoff_routed = True
        state.handoff_token = ""
        state.handoff_tool_use_id = "tool-1"
        core.save_state(self.store, state)

        self.assertIsNone(core.on_handoff_launch_ack(self.store, self.session_id, "tool-other"))
        ack = core.on_handoff_launch_ack(self.store, self.session_id, "tool-1")
        self.assertIsNotNone(ack)
        self.assertEqual(core.load_state(self.store, self.session_id).phase, core.HANDOFF_REQUESTED)

        started = core.on_executor_started(self.store, self.session_id, "agent-1")
        self.assertIsNotNone(started)
        state = core.load_state(self.store, self.session_id)
        self.assertEqual(state.phase, core.EXECUTOR)
        self.assertEqual(state.executor_agent_id, "agent-1")
        self.assertIsNone(core.on_executor_started(self.store, self.session_id, "agent-2"))

    def test_failed_handoff_and_incomplete_executor_restore_checkpoint(self) -> None:
        self.checkpoint_run()
        core.on_pw_go(self.store, self.session_id, host="codex")

        failed = core.on_handoff_failed(self.store, self.session_id, "tool schema has no model")
        self.assertIn("retryable", failed.system_message)
        state = core.load_state(self.store, self.session_id)
        self.assertEqual(state.phase, core.PAUSED)
        self.assertEqual(state.last_handoff_error, "tool schema has no model")

        core.on_pw_go(self.store, self.session_id, host="codex")
        core.on_handoff_confirm(self.store, self.session_id)
        incomplete = core.on_executor_result(
            self.store, self.session_id, complete=False, detail="two todos remain"
        )
        self.assertIn("incomplete", incomplete.system_message)
        self.assertEqual(core.load_state(self.store, self.session_id).phase, core.PAUSED)

    def test_executor_result_cannot_clear_an_unconfirmed_handoff(self) -> None:
        self.checkpoint_run()
        core.on_pw_go(self.store, self.session_id, host="codex")

        action = core.on_executor_result(self.store, self.session_id, complete=True)

        self.assertIn("before handoff confirmation", action.additional_context)
        self.assertEqual(core.load_state(self.store, self.session_id).phase, core.HANDOFF_REQUESTED)

    def test_claude_handoff_waits_for_router_confirmation(self) -> None:
        self.checkpoint_run()

        action = core.on_pw_go(self.store, self.session_id, host="claude")

        self.assertIn("spawn ONE Task", action.additional_context)
        state = core.load_state(self.store, self.session_id)
        self.assertIsNotNone(state)
        self.assertEqual(state.phase, core.HANDOFF_REQUESTED)
        self.assertFalse(state.handoff_done)
        self.assertTrue(state.handoff_token)
        self.assertIn(
            "PREWALK_HANDOFF_TOKEN: " + state.handoff_token,
            action.additional_context,
        )

    def test_fast_mode_requests_handoff_once_at_turn_end(self) -> None:
        state = core.start_run(self.store, self.session_id, self.preset, auto_swap=True)
        state.phase = core.READY
        state.first_edit_landed = True
        core.save_state(self.store, state)
        checkpoint = core.on_todos_changed(self.store, self.session_id, [
            core.Todo("1", "Update core and test", "completed"),
            core.Todo("2", "Update adapters and verify", "pending"),
            core.Todo("3", "Update docs and check", "pending"),
            core.Todo("pause", "PAUSE for handoff", "in_progress"),
        ])
        self.assertIn("Stop hook", checkpoint.system_message)

        action = core.on_fast_handoff(self.store, self.session_id, host="codex")
        self.assertFalse(action.proceed)
        self.assertIn("spawn_agent", action.block_reason)
        self.assertEqual(core.load_state(self.store, self.session_id).phase, core.HANDOFF_REQUESTED)
        self.assertIsNone(core.on_fast_handoff(self.store, self.session_id, host="codex"))

    def test_corrupt_store_is_quarantined_and_recovers(self) -> None:
        self.store.write_text('{"broken":', encoding="utf-8")

        self.assertIsNone(core.load_state(self.store, self.session_id))
        backup = self.store.with_name(self.store.name + ".corrupt")
        self.assertEqual(backup.read_text(encoding="utf-8"), '{"broken":')

        state = core.start_run(self.store, self.session_id, self.preset, auto_swap=False)
        self.assertEqual(core.load_state(self.store, self.session_id), state)
        self.assertIsInstance(json.loads(self.store.read_text(encoding="utf-8")), dict)

    def test_preset_parser_ignores_legacy_planner_and_maps_executor_effort(self) -> None:
        toml_path = Path(self.temp_dir.name) / "presets.toml"
        toml_path.write_text(
            '\n'.join([
                '[presets.fast]',
                'planner = "planner"',
                'executor = "executor"',
                'planner_thinking = "high"',
                'executor_thinking = "low"',
                'handoff_mode = "manual-model"',
                'require_model_routing = false',
            ]),
            encoding="utf-8",
        )
        preset = core.load_presets_toml(toml_path)["fast"]
        self.assertEqual(preset.planner_model, "active-session")
        self.assertEqual(preset.planner_thinking, "")
        self.assertEqual(preset.executor_effort, "low")
        self.assertEqual(len(preset.deprecation_warnings), 3)
        self.assertTrue(any("planner is deprecated" in item for item in preset.deprecation_warnings))
        self.assertEqual(preset.handoff_mode, "manual-model")
        self.assertFalse(preset.require_model_routing)

    def test_concurrent_processes_preserve_all_sessions(self) -> None:
        script = """
import sys
import time
sys.path.insert(0, sys.argv[1])
import prewalk_engine as core
time.sleep(0.15)
state = core.PrewalkState(session_id=sys.argv[3], preset=sys.argv[3])
core.save_state(sys.argv[2], state)
"""
        session_ids = [f"session-{index}" for index in range(20)]
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", script, str(ROOT), str(self.store), session_id],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for session_id in session_ids
        ]
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, stdout + stderr)

        data = json.loads(self.store.read_text(encoding="utf-8"))
        self.assertEqual(set(data), set(session_ids))
        for session_id in session_ids:
            self.assertEqual(core.load_state(self.store, session_id).preset, session_id)

    def test_vendored_engine_copies_match_canonical_package(self) -> None:
        def package_files(directory: Path) -> dict[str, bytes]:
            return {
                str(path.relative_to(directory)): path.read_bytes()
                for path in sorted(directory.rglob("*.py"))
            }

        canonical = package_files(ROOT / "prewalk_engine")
        vendored = [
            ROOT / "hosts" / "codex" / "hooks" / "prewalk_engine",
            ROOT / "hosts" / "claude" / "hooks" / "prewalk_engine",
        ]

        for path in vendored:
            with self.subTest(path=path):
                self.assertEqual(package_files(path), canonical)


if __name__ == "__main__":
    unittest.main()
