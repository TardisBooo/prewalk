"""Real hook/helper subprocess regression, without model calls or benchmarks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_v4_checkpoint import PACKET_TODO_SNAPSHOT, ROOT
import prewalk_engine as core


class CheckpointProcessFlow(unittest.TestCase):
    def test_rejected_stop_go_corrected_stop_and_route(self):
        with tempfile.TemporaryDirectory(prefix="prewalk-checkpoint-") as directory:
            root = Path(directory)
            state_file = root / "state.json"
            sid = "checkpoint-process-fixture"
            core.start_v4_run(state_file, sid, root, "codex",
                              core.Preset("luna", "gpt-5.6-luna", executor_effort="max"))
            env = dict(os.environ, PREWALK_STATE_FILE=str(state_file),
                       CODEX_THREAD_ID=sid, CODEX_SESSION_ID=sid,
                       PYTHONIOENCODING="utf-8")
            env.pop("PREWALK_ENGINE", None)
            hooks = ROOT / "hosts/codex/hooks"

            def run(script, args=(), payload=None):
                result = subprocess.run(
                    [sys.executable, str(hooks / script), *args], env=env,
                    input=json.dumps(payload, ensure_ascii=False) if payload else None,
                    capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout

            def stop(packet):
                return json.loads(run("pause_detect.py", payload={
                    "hook_event_name": "Stop", "session_id": sid,
                    "last_assistant_message": packet}))

            bad = PACKET_TODO_SNAPSHOT.replace("Implement capture and test it", "Write documentation")
            self.assertEqual(stop(bad)["decision"], "block")
            go = run("_pw.py", ["go", sid, "--schema-fields=message,model,fork_context,reasoning_effort"])
            self.assertIn("Last checkpoint error:", go)
            self.assertIn("source=packet", go)
            stop(go)
            self.assertEqual(core.load_v4_state(state_file, sid).state.phase, "planning")
            good = PACKET_TODO_SNAPSHOT.replace("Implement capture and test it", "更新 docs/PLAN.md；verify: 文档检查通过")
            self.assertIn("checkpoint ready", stop(good)["systemMessage"])
            self.assertEqual(core.load_v4_state(state_file, sid).state.packet, good)
            route = run("_pw.py", ["go", sid, "--schema-fields=message,model,fork_context,reasoning_effort"])
            self.assertIn("PREWALK_EXECUTOR_MODEL: gpt-5.6-luna", route)
            self.assertIn("PREWALK_FORK_CONTEXT: false", route)
            self.assertEqual(core.load_v4_state(state_file, sid).state.phase, "handoff_requested")


if __name__ == "__main__":
    unittest.main()
