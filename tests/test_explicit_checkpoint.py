"""No-model process acceptance for explicit manual/fast checkpoint receipts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_v4_checkpoint import PACKET_TODO_SNAPSHOT, ROOT
import prewalk_engine as core


class ExplicitCheckpointTests(unittest.TestCase):
    def exercise(self, fast=False, invalid=False):
        with tempfile.TemporaryDirectory(prefix="prewalk-explicit-") as directory:
            workspace = Path(directory)
            home = workspace / "home"
            sessions = home / "sessions"
            sessions.mkdir(parents=True)
            sid = "explicit-test"
            (sessions / f"rollout-{sid}.jsonl").write_text(json.dumps({
                "type": "session_meta", "payload": {"id": sid, "cwd": str(workspace)}}) + "\n", encoding="utf-8")
            env = dict(os.environ, CODEX_HOME=str(home), CODEX_THREAD_ID=sid,
                       PYTHONIOENCODING="utf-8")
            env.pop("PREWALK_STATE_FILE", None)
            env.pop("PREWALK_ENGINE", None)
            hooks = ROOT / "hosts/codex/hooks"

            def run(script, *args, payload=None):
                return subprocess.run([sys.executable, str(hooks / script), *args],
                    cwd=hooks.parent, env=env, capture_output=True, text=True,
                    input=json.dumps(payload) if payload else None, encoding="utf-8", timeout=30)

            armed = run("_arm.py", "arm", sid, *( ["--fast"] if fast else []))
            self.assertEqual(armed.returncode, 0, armed.stderr)
            store = workspace / ".prewalk/state.json"
            state = core.load_v4_state(store, sid).state
            self.assertEqual(state.workspace_id, core.workspace_identity(workspace))
            self.assertEqual(state.fast_mode, fast)
            self.assertFalse((home / "prewalk-state.json").exists())
            packet = workspace / "packet.md"
            text = PACKET_TODO_SNAPSHOT
            if invalid:
                text = text.replace("1. [x]", "1. [ ]")
            packet.write_text(text, encoding="utf-8")
            submitted = run("_pw.py", "checkpoint", sid, str(packet))
            if invalid:
                self.assertNotEqual(submitted.returncode, 0)
                self.assertEqual(core.load_v4_state(store, sid).state.phase, "planning")
                self.assertIn("incomplete_task_one", submitted.stdout)
                return
            self.assertEqual(submitted.returncode, 0, submitted.stderr)
            receipt = json.loads(submitted.stdout)
            self.assertEqual(receipt["next"], "pw-go" if fast else "await_user_review")
            self.assertEqual(core.load_v4_state(store, sid).state.phase, "checkpoint_ready")
            repeated = run("_pw.py", "checkpoint", sid, str(packet))
            self.assertEqual(json.loads(repeated.stdout)["revision"], receipt["revision"])
            packet.write_text(text + "\nChanged plan", encoding="utf-8")
            self.assertNotEqual(run("_pw.py", "checkpoint", sid, str(packet)).returncode, 0)
            go = run("_pw.py", "go", sid, "--schema-fields=message,model,task_name,fork_turns,reasoning_effort")
            self.assertEqual(go.returncode, 0, go.stderr)
            self.assertIn("PREWALK_MESSAGE_BEGIN", go.stdout)
            self.assertEqual(core.load_v4_state(store, sid).state.phase, "handoff_requested")

    def test_manual_without_any_stop_hook_from_plugin_cwd(self):
        self.exercise()

    def test_fast_without_any_stop_hook_from_plugin_cwd(self):
        self.exercise(fast=True)

    def test_unfinished_first_task_is_not_a_checkpoint(self):
        self.exercise(invalid=True)


if __name__ == "__main__":
    unittest.main()
