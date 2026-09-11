"""Plugin process tests for one-shot gating and exact-journal recovery."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_v4_checkpoint import PACKET_TODO_SNAPSHOT, ROOT
import prewalk_engine as core


class FastRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.sid = "gate-test"
        self.store = self.root / ".prewalk/state.json"
        self.env = dict(os.environ, CODEX_HOME=str(self.home), CODEX_THREAD_ID=self.sid,
                        PYTHONIOENCODING="utf-8")
        self.env.pop("PREWALK_STATE_FILE", None)
        self.env.pop("PREWALK_ENGINE", None)
        core.start_v4_run(self.store, self.sid, self.root, "codex", core.Preset("luna", "gpt-5.6-luna"), fast_mode=True)

    def run_script(self, name, *args, payload=None):
        return subprocess.run([sys.executable, str(ROOT / "hosts/codex/hooks" / name), *args],
                              env=self.env, cwd=self.root, input=json.dumps(payload) if payload else None,
                              capture_output=True, text=True, encoding="utf-8", timeout=30)

    def hook(self, name, tool, response):
        result = self.run_script(name, payload={"session_id": self.sid, "cwd": str(self.root),
            "hook_event_name": "PostToolUse", "tool_name": tool,
            "tool_input": {"operation": "view"}, "tool_response": response})
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def state(self):
        return core.load_v4_state(self.store, self.sid).state

    def test_successful_view_then_write_triggers_once(self):
        self.hook("edit_tracker.py", "write", {"ok": True})
        self.assertFalse(self.state().fast_gate_open)
        self.hook("todo_tracker.py", "todo", {"isError": True})
        self.assertFalse(self.state().plan_seen)
        self.hook("todo_tracker.py", "todo", {"ok": True})
        self.assertTrue(self.state().plan_seen)
        self.hook("edit_tracker.py", "write", {"details": {"xdev": {"tier": "read"}}})
        self.assertFalse(self.state().fast_gate_open)
        first = self.hook("edit_tracker.py", "write", {"details": {"xdev": {"tier": "write"}}})
        self.assertTrue(self.state().fast_gate_open)
        self.assertIn("fast gate opened", first)
        second = self.hook("edit_tracker.py", "write", {"ok": True})
        self.assertNotIn("fast gate opened", second)

    def test_manual_does_not_open_fast_gate(self):
        core.apply_v4_transition(self.store, self.sid, expected_phases=["planning"],
            target_phase="planning", event_id="manual", updates={"fast_mode": False})
        self.hook("todo_tracker.py", "todo", {"ok": True})
        self.hook("edit_tracker.py", "write", {"ok": True})
        self.assertFalse(self.state().fast_gate_open)

    def test_recovery_lists_without_writes_then_captures_exact_ordinal(self):
        session_dir = self.home / "sessions"
        session_dir.mkdir()
        journal = session_dir / f"rollout-{self.sid}.jsonl"
        timestamp = self.state().created_at
        events = [
            {"type": "session_meta", "payload": {"id": self.sid, "cwd": str(self.root)}},
            {"type": "response_item", "timestamp": timestamp, "ordinal": 116,
             "payload": {"type": "message", "role": "assistant", "phase": "final_answer",
                         "content": [{"type": "output_text", "text": PACKET_TODO_SNAPSHOT}]}}]
        journal.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
        original_journal = journal.read_bytes()
        original_state = self.store.read_bytes()
        listed = self.run_script("_pw.py", "recover", self.sid)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(json.loads(listed.stdout)["candidates"][0]["ordinal"], 116)
        self.assertEqual(self.store.read_bytes(), original_state)
        wrong = self.run_script("_pw.py", "recover", self.sid, "--ordinal=115")
        self.assertNotEqual(wrong.returncode, 0)
        recovered = self.run_script("_pw.py", "recover", self.sid, "--ordinal=116")
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertEqual(self.state().packet, PACKET_TODO_SNAPSHOT)
        self.assertEqual(journal.read_bytes(), original_journal)

    def test_permission_failure_cannot_be_blindly_retried(self):
        core.capture_v4_checkpoint(self.store, self.sid, packet=PACKET_TODO_SNAPSHOT)
        route = core.request_codex_handoff(self.store, self.sid,
            schema_fields={"message", "task_name", "fork_turns", "model"}).state
        core.validate_codex_spawn(self.store, self.sid,
            {"message": core.codex_route_message(route), "task_name": route.route_task_name,
             "fork_turns": "none", "model": route.executor_model}, tool_use_id="failed-launch")
        core.bind_codex_executor(self.store, self.sid, tool_use_id="failed-launch",
            agent_id="", success=False, detail="Permission denied: .git is read-only")
        retry = self.run_script("_pw.py", "retry", self.sid,
                                "--schema-fields=message,task_name,fork_turns,model")
        self.assertNotEqual(retry.returncode, 0)
        self.assertIn("prerequisite", retry.stderr)
        self.assertEqual(self.state().phase, "incomplete")
        self.assertEqual(self.state().route_attempt, 1)

    def test_fast_revision_requires_new_review(self):
        core.capture_v4_checkpoint(self.store, self.sid, packet=PACKET_TODO_SNAPSHOT)
        result = core.revise_v4_checkpoint(self.store, self.sid, "revise final task")
        self.assertEqual(result.status, "planning")
        self.assertFalse(result.state.fast_mode)
        self.assertFalse(result.state.plan_seen)
        self.assertFalse(result.state.fast_gate_open)

    def test_utf8_stop_packet_survives_windows_gbk_process_defaults(self):
        packet = PACKET_TODO_SNAPSHOT.replace("Ship the checkpoint workflow.", "完成中文计划与检查点交接。🔧")
        wire = json.dumps({"hook_event_name": "Stop", "session_id": self.sid,
                           "cwd": str(self.root), "last_assistant_message": packet},
                          ensure_ascii=False).encode("utf-8")
        env = dict(self.env, PYTHONIOENCODING="gbk", PYTHONUTF8="0")
        result = subprocess.run([sys.executable, str(ROOT / "hosts/codex/hooks/pause_detect.py")],
            cwd=self.root, env=env, input=wire, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(self.state().phase, "checkpoint_ready")
        self.assertEqual(self.state().packet, packet)
        json.loads(result.stdout.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
