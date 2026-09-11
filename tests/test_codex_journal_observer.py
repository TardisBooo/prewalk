import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_v4_checkpoint import ROOT, PACKET_TODO_SNAPSHOT
import prewalk_engine as core

HOOKS = ROOT / "hosts/codex/hooks"
sys.path.insert(0, str(HOOKS))
import _observe


class JournalObserverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sessions = self.root / "sessions"
        self.sessions.mkdir()
        self.env = patch.dict(os.environ, {"CODEX_HOME": str(self.root)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = self.root / "state.json"
        self.sid = "fixture-root"
        core.start_v4_run(self.store, self.sid, self.root, "codex", core.Preset("luna", "gpt-5.6-luna", executor_effort="max"))
        core.capture_v4_checkpoint(self.store, self.sid, packet=PACKET_TODO_SNAPSHOT)
        self.state = core.request_codex_handoff(self.store, self.sid, schema_fields={"task_name", "fork_turns", "message", "model", "reasoning_effort"}).state
        self.when = self.state.route_requested_at
        self.task = "/root/" + self.state.route_task_name
        self.parent = [self.event("session_meta", {"id": self.sid, "cwd": str(self.root)}),
            self.event("response_item", {"type": "function_call", "namespace": "collaboration", "name": "spawn_agent", "call_id": "call1", "arguments": json.dumps({"task_name": self.state.route_task_name, "model": "gpt-5.6-luna", "reasoning_effort": "max", "fork_turns": "none", "message": "gAAAAAopaque-runtime-content"})}),
            self.event("response_item", {"type": "function_call_output", "call_id": "call1", "output": json.dumps({"task_name": self.task})})]
        self.child = [self.event("session_meta", {"id": "child-id", "cwd": str(self.root), "source": {"subagent": {"thread_spawn": {"parent_thread_id": self.sid, "agent_path": self.task}}}}),
                      self.event("turn_context", {"model": "gpt-5.6-luna", "effort": "max"}),
                      self.event("event_msg", {"type": "task_started"}),
                      self.event("event_msg", {"type": "task_complete", "last_agent_message": "PREWALK_COMPLETE"})]

    def event(self, kind, payload):
        return {"type": kind, "timestamp": self.when, "payload": payload}

    def write(self):
        for name, events in (("rollout-fixture-root.jsonl", self.parent), ("rollout-child-id.jsonl", self.child)):
            (self.sessions / name).write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")

    def test_observed_completion_and_idempotent_recheck(self):
        self.write()
        original = {p: p.read_bytes() for p in self.sessions.iterdir()}
        self.assertIn("completed all work", _observe.observe(self.store, self.sid))
        self.assertIsNone(core.load_v4_state(self.store, self.sid).state)
        _observe.observe(self.store, self.sid)
        self.assertEqual(original, {p: p.read_bytes() for p in self.sessions.iterdir()})

    def test_wrong_actual_model_never_binds(self):
        self.child[1]["payload"]["model"] = "gpt-6-astra"
        self.write()
        self.assertIn("model not proven", _observe.observe(self.store, self.sid))
        self.assertEqual(core.load_v4_state(self.store, self.sid).state.phase, "handoff_requested")

    def test_duplicate_spawn_never_binds(self):
        self.parent.append(self.parent[1])
        self.write()
        self.assertIn("exactly one", _observe.observe(self.store, self.sid))
        self.assertEqual(core.load_v4_state(self.store, self.sid).state.phase, "handoff_requested")

    def test_parent_completion_is_not_child_completion(self):
        self.parent.append(self.event("event_msg", {"type": "task_complete", "last_agent_message": "PREWALK_COMPLETE"}))
        self.child.pop()
        self.write()
        self.assertIn("executor_running", _observe.observe(self.store, self.sid))
        self.assertEqual(core.load_v4_state(self.store, self.sid).state.phase, "executor_running")

    def test_wrong_parent_retains_route(self):
        self.child[0]["payload"]["source"]["subagent"]["thread_spawn"]["parent_thread_id"] = "other"
        self.write()
        self.assertIn("expected one child", _observe.observe(self.store, self.sid))

    def test_missing_marker_becomes_incomplete(self):
        self.child[-1]["payload"]["last_agent_message"] = "I am done"
        self.write()
        self.assertIn("without a valid final marker", _observe.observe(self.store, self.sid))
        self.assertEqual(core.load_v4_state(self.store, self.sid).state.phase, "incomplete")

    def test_new_active_turn_prevents_old_completion(self):
        self.child.append(self.event("event_msg", {"type": "task_started"}))
        self.write()
        self.assertIn("no terminal result", _observe.observe(self.store, self.sid))

    def test_changed_plaintext_packet_is_rejected(self):
        args = json.loads(self.parent[1]["payload"]["arguments"])
        args["message"] = "Do unrelated work"
        self.parent[1]["payload"]["arguments"] = json.dumps(args)
        self.write()
        self.assertIn("plaintext spawn packet differs", _observe.observe(self.store, self.sid))

    def test_wrong_effort_is_rejected(self):
        self.child[1]["payload"]["effort"] = "low"
        self.write()
        self.assertIn("effort not proven", _observe.observe(self.store, self.sid))

    def test_duplicate_child_is_rejected(self):
        self.write()
        original = self.sessions / "rollout-child-id.jsonl"
        (self.sessions / "duplicate.jsonl").write_bytes(original.read_bytes())
        self.assertIn("expected one child", _observe.observe(self.store, self.sid))

    def test_incomplete_journal_retains_route(self):
        self.write()
        with (self.sessions / "rollout-child-id.jsonl").open("a", encoding="utf-8") as stream:
            stream.write('{"partial":')
        self.assertIn("journal is incomplete", _observe.observe(self.store, self.sid))
        self.assertEqual(core.load_v4_state(self.store, self.sid).state.phase, "handoff_requested")


if __name__ == "__main__":
    unittest.main()
