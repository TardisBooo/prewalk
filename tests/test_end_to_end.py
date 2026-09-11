from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HOSTS = ROOT / "hosts"

PACKET = """## Goal
Exercise the host Stop adapter.
## Files Read
core and hooks
## Constraints And Existing Patterns
persist exact root output
## Full Todo List
three real tasks
## Task 1 Changes
checkpoint capture
## Verification Already Run
adapter test passed
## Remaining Work
native routing
## Risks / Do Not Repeat
do not reconstruct the packet
"""

PACKET_WITH_CHECKLIST = PACKET.replace(
    "three real tasks",
    """1. [x] Implement core and test it
2. [ ] Update adapters and verify them
3. [ ] Update docs and check contracts""",
)


class EndToEndFlowTests(unittest.TestCase):
    """Drive every host hook script as a real subprocess, like the host would."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def run_script(
        self,
        host: str,
        script: str,
        *arguments: str,
        payload: dict | None = None,
        extra_env: dict[str, str | None] | None = None,
        expected_returncode: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        config = Path(self.temp_dir.name) / host
        config.mkdir(exist_ok=True)
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if host == "codex":
            env["CODEX_HOME"] = str(config)
            env.pop("CODEX_THREAD_ID", None)
            env.pop("CODEX_SESSION_ID", None)
        else:
            env["CLAUDE_CONFIG_DIR"] = str(config)
            env["CLAUDE_PLUGIN_ROOT"] = str(HOSTS / "claude")
        for key, value in (extra_env or {}).items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        result = subprocess.run(
            [sys.executable, str(HOSTS / host / "hooks" / script), *arguments],
            input=json.dumps(payload) if payload is not None else None,
            text=True,
            capture_output=True,
            env=env,
            cwd=ROOT,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, expected_returncode, result.stdout + result.stderr)
        return result

    @staticmethod
    def handoff_token(output: str) -> str:
        match = re.search(r"PREWALK_HANDOFF_TOKEN: ([A-Za-z0-9_-]+)", output)
        if not match:
            raise AssertionError("handoff output did not contain a token")
        return match.group(1)

    @staticmethod
    def todo_payload(session_id: str, host: str, *, completed: bool = False) -> dict:
        status = "completed" if completed else "pending"
        items = [
            {"content": "Implement core and test", "status": "completed"},
            {"content": "Update adapters and verify", "status": status},
            {"content": "Update docs and check", "status": status},
        ]
        key = "plan" if host == "codex" else "todos"
        return {
            "session_id": session_id,
            "hook_event_name": "PostToolUse",
            "tool_input": {key: items},
            "tool_response": {"success": True},
        }

    def arm_codex_checkpoint(self, session_id: str, *, extra_env=None) -> None:
        self.run_script(
            "codex", "_arm.py", "arm", session_id, "Build the feature", extra_env=extra_env
        )
        self.run_script(
            "codex", "todo_tracker.py",
            payload=self.todo_payload(session_id, "codex"), extra_env=extra_env,
        )
        self.run_script("codex", "pause_detect.py", payload={
            "session_id": session_id,
            "hook_event_name": "Stop",
            "last_assistant_message": PACKET,
        }, extra_env=extra_env)

    def arm_claude_checkpoint(
        self, session_id: str, *, fast: bool = False, extra_env=None
    ) -> None:
        goal = "--fast Build the feature" if fast else "Build the feature"
        self.run_script(
            "claude", "_arm.py", "arm", session_id, goal, extra_env=extra_env
        )
        self.run_script(
            "claude", "todo_tracker.py",
            payload=self.todo_payload(session_id, "claude"), extra_env=extra_env,
        )
        self.run_script("claude", "pause_detect.py", payload={
            "session_id": session_id,
            "hook_event_name": "Stop",
            "last_assistant_message": PACKET,
        }, extra_env=extra_env)

    def claude_state(self, session_id: str) -> dict | None:
        store = Path(self.temp_dir.name) / "claude" / "prewalk-state.json"
        return json.loads(store.read_text(encoding="utf-8")).get(session_id)

    def codex_state(self, session_id: str) -> dict | None:
        store = Path(self.temp_dir.name) / "codex" / "prewalk-state.json"
        return json.loads(store.read_text(encoding="utf-8")).get(session_id)

    def request_codex_route(self, session_id: str, *, extra_env=None) -> dict:
        handoff = self.run_script(
            "codex", "_pw.py", "go", session_id,
            "--schema-fields=task_name,message,fork_turns,model,reasoning_effort",
            extra_env=extra_env,
        )
        fields = dict(re.findall(r"^PREWALK_([A-Z_]+): (.+)$", handoff.stdout, re.M))
        message = re.search(
            r"PREWALK_MESSAGE_BEGIN\n(.*)\nPREWALK_MESSAGE_END", handoff.stdout, re.S
        )
        self.assertIsNotNone(message)
        tool_input = {
            "task_name": fields["TASK_NAME"],
            "message": message.group(1),
            "fork_turns": fields["FORK_TURNS"],
            "model": fields["EXECUTOR_MODEL"],
        }
        if "EXECUTOR_EFFORT" in fields:
            tool_input["reasoning_effort"] = fields["EXECUTOR_EFFORT"]
        return tool_input

    def test_codex_scripts_complete_a_full_handoff(self) -> None:
        session_id = "codex-e2e"
        self.arm_codex_checkpoint(session_id)
        tool_input = self.request_codex_route(session_id)
        self.assertEqual(tool_input["fork_turns"], "all")
        self.assertEqual(tool_input["model"], "gpt-5.6-terra")
        # The durable packet is included so current Codex can use a fresh
        # context when pinning an executor model.
        self.assertIn("PREWALK HANDOFF:", tool_input["message"])
        self.assertIn(PACKET, tool_input["message"])

        accepted = self.run_script("codex", "executor_router.py", payload={
            "session_id": session_id,
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "tool_use_id": "spawn-1",
            "tool_input": tool_input,
        })
        self.assertEqual(accepted.stdout, "")
        self.run_script("codex", "executor_router.py", payload={
            "session_id": session_id,
            "hook_event_name": "PostToolUse",
            "tool_name": "spawn_agent",
            "tool_use_id": "spawn-1",
            "tool_response": {"agent_id": "agent-1", "success": True},
        })
        self.run_script("codex", "executor_router.py", payload={
            "session_id": session_id,
            "hook_event_name": "SubagentStop",
            "agent_id": "agent-unrelated",
            "last_assistant_message": "PREWALK_COMPLETE",
        })
        running = self.run_script("codex", "_arm.py", "status", session_id)
        self.assertIn("executor_running", running.stdout)
        self.run_script("codex", "executor_router.py", payload={
            "session_id": session_id,
            "hook_event_name": "SubagentStop",
            "agent_id": "agent-1",
            "last_assistant_message": "Done\nPREWALK_COMPLETE",
        })
        status = self.run_script("codex", "_arm.py", "status", session_id)
        self.assertIn("idle", status.stdout)

    def test_codex_current_multi_agent_schema_completes_a_full_handoff(self) -> None:
        session_id = "codex-current-schema"
        self.arm_codex_checkpoint(session_id)
        handoff = self.run_script(
            "codex", "_pw.py", "go", session_id,
            "--schema-fields=fork_context,items,message,model,reasoning_effort",
        )
        fields = dict(re.findall(r"^PREWALK_([A-Z_]+): (.+)$", handoff.stdout, re.M))
        message = re.search(
            r"PREWALK_MESSAGE_BEGIN\n(.*)\nPREWALK_MESSAGE_END", handoff.stdout, re.S
        ).group(1)
        self.assertEqual(fields["SPAWN_PROFILE"], "fork_context")
        self.assertEqual(fields["FORK_CONTEXT"], "false")
        self.assertNotIn("TASK_NAME", fields)
        tool_input = {
            "fork_context": False,
            "message": message,
            "model": fields["EXECUTOR_MODEL"],
        }
        if "EXECUTOR_EFFORT" in fields:
            tool_input["reasoning_effort"] = fields["EXECUTOR_EFFORT"]
        accepted = self.run_script("codex", "executor_router.py", payload={
            "session_id": session_id,
            "hook_event_name": "PreToolUse",
            "tool_name": "multi_agent_v1__spawn_agent",
            "tool_use_id": "spawn-current",
            "tool_input": tool_input,
        })
        self.assertEqual(accepted.stdout, "")
        self.run_script("codex", "executor_router.py", payload={
            "session_id": session_id,
            "hook_event_name": "PostToolUse",
            "tool_name": "multi_agent_v1__spawn_agent",
            "tool_use_id": "spawn-current",
            "tool_response": {"agent_id": "agent-current", "success": True},
        })
        running = self.run_script("codex", "_arm.py", "status", session_id)
        self.assertIn("executor_running", running.stdout)

    def test_codex_stop_recovers_checklist_when_plan_tool_is_absent(self) -> None:
        session_id = "codex-packet-todos"
        self.run_script("codex", "_arm.py", "arm", session_id, "Build the feature")

        stopped = self.run_script("codex", "pause_detect.py", payload={
            "session_id": session_id,
            "hook_event_name": "Stop",
            "last_assistant_message": PACKET_WITH_CHECKLIST,
        })

        self.assertIn("checkpoint ready", stopped.stdout)
        state = self.codex_state(session_id)
        self.assertEqual(state["phase"], "checkpoint_ready")
        self.assertEqual(
            [item["status"] for item in state["todos"]],
            ["completed", "pending", "pending"],
        )

    def test_codex_failed_handoff_is_retryable(self) -> None:
        session_id = "codex-retry"
        self.arm_codex_checkpoint(session_id)
        tool_input = self.request_codex_route(session_id)
        tool_input["fork_turns"] = "none"
        denied = self.run_script("codex", "executor_router.py", payload={
            "session_id": session_id,
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "tool_use_id": "spawn-bad",
            "tool_input": tool_input,
        })
        output = json.loads(denied.stdout)
        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"], "deny"
        )
        self.assertIn("fork_turns", output["hookSpecificOutput"]["permissionDecisionReason"])
        status = self.run_script("codex", "_arm.py", "status", session_id)
        self.assertIn("incomplete", status.stdout)
        self.assertIn("next: $prewalk:pw-retry", status.stdout)

    def test_codex_retry_reuses_one_new_route_and_preserves_task_one(self) -> None:
        session_id = "codex-retry-idempotent"
        self.arm_codex_checkpoint(session_id)
        tool_input = self.request_codex_route(session_id)
        tool_input["fork_turns"] = "none"
        self.run_script("codex", "executor_router.py", payload={
            "session_id": session_id,
            "hook_event_name": "PreToolUse",
            "tool_name": "spawn_agent",
            "tool_use_id": "spawn-failed",
            "tool_input": tool_input,
        })

        arguments = (
            "--schema-fields=task_name,message,fork_turns,model,reasoning_effort",
        )
        first = self.run_script("codex", "_pw.py", "retry", session_id, *arguments)
        second = self.run_script("codex", "_pw.py", "retry", session_id, *arguments)
        self.assertEqual(first.stdout, second.stdout)
        self.assertIn("PREWALK_FORK_TURNS: all", first.stdout)
        self.assertIn("PREWALK HANDOFF:", first.stdout)
        self.assertIn(PACKET, first.stdout)
        state = self.codex_state(session_id)
        self.assertEqual(state["route_attempt"], 2)
        self.assertEqual(state["todos"][0]["status"], "completed")

    def test_codex_reconcile_requires_explicit_no_live_agent_proof(self) -> None:
        session_id = "codex-reconcile"
        self.arm_codex_checkpoint(session_id)
        self.request_codex_route(session_id)
        before = self.codex_state(session_id)

        refused = self.run_script("codex", "_pw.py", "reconcile", session_id)
        self.assertIn("did not change state", refused.stdout)
        self.assertEqual(self.codex_state(session_id)["revision"], before["revision"])
        accepted = self.run_script(
            "codex", "_pw.py", "reconcile", session_id,
            "--confirmed-not-running", "native agent list is empty",
        )
        self.assertIn("marked the prior route incomplete", accepted.stdout)
        state = self.codex_state(session_id)
        self.assertEqual(state["phase"], "incomplete")
        self.assertEqual(state["packet"], PACKET)

    def test_codex_fast_mode_requests_the_same_native_route_once(self) -> None:
        session_id = "codex-fast"
        self.run_script(
            "codex", "_arm.py", "arm", session_id, "--fast", "Build the feature"
        )
        self.run_script(
            "codex", "todo_tracker.py", payload=self.todo_payload(session_id, "codex")
        )
        payload = {
            "session_id": session_id,
            "hook_event_name": "Stop",
            "event_id": "stop-fast",
            "last_assistant_message": PACKET,
        }
        first = self.run_script("codex", "pause_detect.py", payload=payload)
        output = json.loads(first.stdout)
        self.assertEqual(output["decision"], "block")
        self.assertIn("spawn_agent schema", output["reason"])
        second = self.run_script("codex", "pause_detect.py", payload=payload)
        output = json.loads(second.stdout)
        self.assertNotIn("decision", output)

    def test_codex_interleaved_threads_remain_isolated(self) -> None:
        sessions = ("thread-a", "thread-b")
        routes = {}
        for session_id in sessions:
            env = {"CODEX_THREAD_ID": session_id, "CODEX_SESSION_ID": None}
            self.arm_codex_checkpoint(session_id, extra_env=env)
            routes[session_id] = self.request_codex_route(session_id, extra_env=env)
            self.run_script("codex", "executor_router.py", payload={
                "session_id": session_id,
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "tool_use_id": f"spawn-{session_id}",
                "tool_input": routes[session_id],
            }, extra_env=env)
        wrong = self.run_script("codex", "executor_router.py", payload={
            "session_id": "thread-a",
            "hook_event_name": "PostToolUse",
            "tool_name": "spawn_agent",
            "tool_use_id": "spawn-thread-b",
            "tool_response": {"agent_id": "agent-b", "success": True},
        }, extra_env={"CODEX_THREAD_ID": "thread-a"})
        self.assertEqual(wrong.stdout, "")
        status_a = self.run_script(
            "codex", "_arm.py", "status", "thread-a",
            extra_env={"CODEX_THREAD_ID": "thread-a"},
        )
        status_b = self.run_script(
            "codex", "_arm.py", "status", "thread-b",
            extra_env={"CODEX_THREAD_ID": "thread-b"},
        )
        self.assertIn("handoff_requested", status_a.stdout)
        self.assertIn("handoff_requested", status_b.stdout)

        mismatch = self.run_script(
            "codex", "_arm.py", "status", "thread-b",
            extra_env={"CODEX_THREAD_ID": "thread-a"}, expected_returncode=1,
        )
        self.assertIn("conflicts", mismatch.stderr)
        self.assertIn(
            "handoff_requested",
            self.run_script(
                "codex", "_arm.py", "status", "thread-a",
                extra_env={"CODEX_THREAD_ID": "thread-a"},
            ).stdout,
        )

    def test_codex_missing_identity_does_not_create_state(self) -> None:
        result = self.run_script(
            "codex", "_arm.py", "arm", "", "Build the feature",
            extra_env={"CODEX_THREAD_ID": None, "CODEX_SESSION_ID": None},
            expected_returncode=1,
        )
        self.assertIn("cannot continue", result.stderr)
        store = Path(self.temp_dir.name) / "codex" / "prewalk-state.json"
        self.assertFalse(store.exists())

    def test_codex_doctor_reports_version_and_identity_remediation(self) -> None:
        result = self.run_script(
            "codex", "_arm.py", "doctor", "",
            extra_env={"CODEX_THREAD_ID": None, "CODEX_SESSION_ID": None},
            expected_returncode=1,
        )
        self.assertIn("Codex CLI >= 0.146.0", result.stdout)
        self.assertIn("thread identity", result.stdout)
        self.assertIn("upgrade Codex and restart the thread", result.stdout)

    def test_codex_root_stop_persists_exact_v4_checkpoint(self) -> None:
        session_id = "codex-v4-stop"
        self.run_script("codex", "_arm.py", "arm", session_id, "Build the feature")
        snapshot = self.todo_payload(session_id, "codex")
        self.run_script("codex", "todo_tracker.py", payload=snapshot)

        stopped = self.run_script("codex", "pause_detect.py", payload={
            "session_id": session_id,
            "hook_event_name": "Stop",
            "last_assistant_message": PACKET,
        })
        self.assertIn("checkpoint ready", stopped.stdout)
        status = self.run_script("codex", "_arm.py", "status", session_id)
        self.assertIn("checkpoint_ready", status.stdout)
        handoff = self.run_script(
            "codex", "_pw.py", "go", session_id,
            "--schema-fields=task_name,message,fork_turns,model,reasoning_effort",
        )
        self.assertIn("PREWALK_FORK_TURNS: all", handoff.stdout)
        self.assertIn("PREWALK HANDOFF:", handoff.stdout)
        self.assertIn(PACKET, handoff.stdout)

        store = Path(self.temp_dir.name) / "codex" / "prewalk-state.json"
        record = json.loads(store.read_text(encoding="utf-8"))[session_id]
        self.assertEqual(record["schema_version"], 4)
        self.assertEqual(record["packet"], PACKET)
        self.assertFalse(any("PAUSE" in item["content"] for item in record["todos"]))

    def test_claude_root_stop_uses_persisted_real_todos_and_exact_packet(self) -> None:
        session_id = "claude-v4-stop"
        self.run_script("claude", "_arm.py", "arm", session_id, "Build the feature")
        snapshot = self.todo_payload(session_id, "claude")
        self.run_script("claude", "todo_tracker.py", payload=snapshot)

        stopped = self.run_script("claude", "pause_detect.py", payload={
            "session_id": session_id,
            "hook_event_name": "Stop",
            "last_assistant_message": PACKET,
        })
        self.assertIn("checkpoint ready", stopped.stdout)
        status = self.run_script("claude", "_arm.py", "status", session_id)
        self.assertIn("checkpoint_ready", status.stdout)
        handoff = self.run_script("claude", "_pw.py", "go", session_id)
        self.assertIn(PACKET, handoff.stdout)

        store = Path(self.temp_dir.name) / "claude" / "prewalk-state.json"
        record = json.loads(store.read_text(encoding="utf-8"))[session_id]
        self.assertEqual(record["schema_version"], 4)
        self.assertEqual(record["packet"], PACKET)

    def test_claude_scripts_route_and_complete_a_full_handoff(self) -> None:
        session_id = "claude-e2e"
        armed = self.run_script("claude", "_arm.py", "arm", session_id, "Build the feature")
        self.assertIn("prewalk ARMED", armed.stdout)
        self.assertIn("planner : active root session", armed.stdout)
        self.assertIn("configured: executor=haiku", armed.stdout)
        self.assertIn("proven    : model=hook-rewrite", armed.stdout)
        self.assertNotIn("Switch this session", armed.stdout)

        self.run_script(
            "claude",
            "todo_tracker.py",
            payload=self.todo_payload(session_id, "claude"),
        )
        self.run_script("claude", "edit_tracker.py", payload={
            "session_id": session_id,
            "tool_response": {"filePath": "/tmp/example", "success": True},
        })
        self.run_script("claude", "pause_detect.py", payload={
            "session_id": session_id,
            "hook_event_name": "Stop",
            "last_assistant_message": PACKET,
        })
        handoff = self.run_script("claude", "_pw.py", "go", session_id)
        self.assertIn("spawn ONE Task", handoff.stdout)
        token = self.handoff_token(handoff.stdout)

        routed = self.run_script("claude", "handoff_router.py", payload={
            "session_id": session_id,
            "hook_event_name": "PreToolUse",
            "tool_use_id": "tool-prewalk",
            "tool_input": {
                "prompt": f"Finish the remaining plan\nPREWALK_HANDOFF_TOKEN: {token}",
                "subagent_type": "general-purpose",
            },
        })
        output = json.loads(routed.stdout)
        updated = output["hookSpecificOutput"]["updatedInput"]
        self.assertEqual(updated["model"], "haiku")
        self.assertEqual(updated["subagent_type"], "prewalk:prewalk-executor")
        self.assertIn(PACKET, updated["prompt"])
        self.assertEqual(self.claude_state(session_id)["route_tool_use_id"], "tool-prewalk")

        self.run_script("claude", "handoff_result.py", payload={
            "session_id": session_id,
            "hook_event_name": "PostToolUse",
            "tool_use_id": "tool-prewalk",
            "tool_response": {"success": True, "content": "background agent launched"},
        })
        self.assertTrue(self.claude_state(session_id)["launch_acknowledged"])

        self.run_script("claude", "handoff_lifecycle.py", payload={
            "session_id": session_id,
            "hook_event_name": "SubagentStart",
            "agent_id": "agent-prewalk",
            "agent_type": "prewalk:prewalk-executor",
        })
        running = self.claude_state(session_id)
        self.assertEqual(running["phase"], "executor_running")
        self.assertEqual(running["executor_agent_id"], "agent-prewalk")

        # Global plugin hooks also fire in subagents. Their todo updates must
        # not finish the root run before the bound SubagentStop marker arrives.
        executor_todos = self.todo_payload(session_id, "claude", completed=True)
        executor_todos.update({
            "agent_id": "agent-prewalk",
            "agent_type": "prewalk:prewalk-executor",
        })
        self.run_script("claude", "todo_tracker.py", payload=executor_todos)
        self.assertIn(
            "executor",
            self.run_script("claude", "_arm.py", "status", session_id).stdout,
        )

        # A different executor-shaped event cannot clear the bound run.
        self.run_script("claude", "handoff_lifecycle.py", payload={
            "session_id": session_id,
            "hook_event_name": "SubagentStop",
            "agent_id": "agent-unrelated",
            "agent_type": "prewalk:prewalk-executor",
            "last_assistant_message": "PREWALK_COMPLETE",
        })
        self.assertIn(
            "executor",
            self.run_script("claude", "_arm.py", "status", session_id).stdout,
        )

        self.run_script("claude", "handoff_lifecycle.py", payload={
            "session_id": session_id,
            "hook_event_name": "SubagentStop",
            "agent_id": "agent-prewalk",
            "agent_type": "prewalk:prewalk-executor",
            "last_assistant_message": "Done\nPREWALK_COMPLETE",
        })
        status = self.run_script("claude", "_arm.py", "status", session_id)
        self.assertIn("idle", status.stdout)

    def test_claude_conflicting_executor_override_refuses_to_arm(self) -> None:
        session_id = "claude-route-conflict"
        result = self.run_script(
            "claude",
            "_arm.py",
            "arm",
            session_id,
            "Build the feature",
            extra_env={"CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"},
            expected_returncode=1,
        )

        self.assertIn("cannot arm", result.stderr)
        self.assertIn("override-conflict", result.stderr)
        store = Path(self.temp_dir.name) / "claude" / "prewalk-state.json"
        self.assertFalse(store.exists())

    def test_claude_failed_task_restores_retryable_checkpoint(self) -> None:
        session_id = "claude-retry"
        self.arm_claude_checkpoint(session_id)
        handoff = self.run_script("claude", "_pw.py", "go", session_id)
        token = self.handoff_token(handoff.stdout)
        self.run_script("claude", "handoff_router.py", payload={
            "session_id": session_id,
            "hook_event_name": "PreToolUse",
            "tool_use_id": "tool-failed",
            "tool_input": {
                "prompt": f"Finish the remaining plan\nPREWALK_HANDOFF_TOKEN: {token}"
            },
        })
        self.run_script("claude", "handoff_result.py", payload={
            "session_id": session_id,
            "hook_event_name": "PostToolUseFailure",
            "tool_use_id": "tool-failed",
            "error": "model unavailable",
        })
        state = self.claude_state(session_id)
        self.assertEqual(state["phase"], "incomplete")
        self.assertEqual(state["last_error"], "model unavailable")
        first = self.run_script("claude", "_pw.py", "retry", session_id)
        second = self.run_script("claude", "_pw.py", "retry", session_id)
        self.assertEqual(first.stdout, second.stdout)
        self.assertIn(PACKET, first.stdout)
        self.assertEqual(self.claude_state(session_id)["route_attempt"], 2)

    def test_claude_status_reports_route_without_leaking_token(self) -> None:
        session_id = "claude-safe-status"
        self.arm_claude_checkpoint(session_id)
        handoff = self.run_script("claude", "_pw.py", "go", session_id)
        token = self.handoff_token(handoff.stdout)

        status = self.run_script("claude", "_arm.py", "status", session_id)
        self.assertIn("host: claude", status.stdout)
        self.assertIn("token=sha256:", status.stdout)
        self.assertIn("remaining(2)", status.stdout)
        self.assertIn("next: /prewalk:pw-go", status.stdout)
        self.assertNotIn(token, status.stdout)
        self.assertNotIn(token[:8], status.stdout)
        self.assertNotIn(PACKET, status.stdout)

    def test_claude_missing_marker_and_duplicate_lifecycle_are_retryable(self) -> None:
        session_id = "claude-missing-marker"
        self.arm_claude_checkpoint(session_id)
        handoff = self.run_script("claude", "_pw.py", "go", session_id)
        token = self.handoff_token(handoff.stdout)
        self.run_script("claude", "handoff_router.py", payload={
            "session_id": session_id,
            "hook_event_name": "PreToolUse",
            "tool_use_id": "tool-missing",
            "tool_input": {"prompt": f"packet\nPREWALK_HANDOFF_TOKEN: {token}"},
        })
        start = {
            "session_id": session_id,
            "hook_event_name": "SubagentStart",
            "agent_id": "agent-missing",
            "agent_type": "prewalk:prewalk-executor",
        }
        self.run_script("claude", "handoff_lifecycle.py", payload=start)
        self.run_script("claude", "handoff_lifecycle.py", payload=start)
        self.run_script("claude", "handoff_lifecycle.py", payload={
            **start,
            "hook_event_name": "SubagentStop",
            "last_assistant_message": "Finished but omitted the marker",
        })
        state = self.claude_state(session_id)
        self.assertEqual(state["phase"], "incomplete")
        self.assertIn("without a valid final marker", state["last_error"])

    def test_claude_unrelated_agent_events_leave_pending_handoff_unchanged(self) -> None:
        session_id = "claude-unrelated"
        self.arm_claude_checkpoint(session_id)
        handoff = self.run_script("claude", "_pw.py", "go", session_id)
        token = self.handoff_token(handoff.stdout)
        unrelated = self.run_script("claude", "handoff_router.py", payload={
            "session_id": session_id,
            "hook_event_name": "PreToolUse",
            "tool_use_id": "tool-unrelated",
            "tool_input": {"prompt": "unrelated Agent request"},
        })
        self.assertEqual(unrelated.stdout, "")
        self.run_script("claude", "handoff_result.py", payload={
            "session_id": session_id,
            "hook_event_name": "PostToolUse",
            "tool_use_id": "tool-unrelated",
            "tool_response": {"success": True, "content": "PREWALK_COMPLETE"},
        })
        state = self.claude_state(session_id)
        self.assertEqual(state["phase"], "handoff_requested")
        self.assertEqual(state["route_tool_use_id"], "")

        nested = self.run_script("claude", "handoff_router.py", payload={
            "session_id": session_id,
            "hook_event_name": "PreToolUse",
            "tool_use_id": "tool-nested",
            "agent_id": "parent-agent",
            "tool_input": {"prompt": f"packet\nPREWALK_HANDOFF_TOKEN: {token}"},
        })
        self.assertEqual(nested.stdout, "")
        self.assertEqual(self.claude_state(session_id)["route_tool_use_id"], "")

    def test_claude_foreground_lifecycle_completes_before_agent_posttooluse(self) -> None:
        session_id = "claude-foreground"
        self.arm_claude_checkpoint(session_id)
        handoff = self.run_script("claude", "_pw.py", "go", session_id)
        token = self.handoff_token(handoff.stdout)
        self.run_script("claude", "handoff_router.py", payload={
            "session_id": session_id,
            "hook_event_name": "PreToolUse",
            "tool_use_id": "tool-foreground",
            "tool_input": {"prompt": f"packet\nPREWALK_HANDOFF_TOKEN: {token}"},
        })
        lifecycle = {
            "session_id": session_id,
            "agent_id": "agent-foreground",
            "agent_type": "prewalk:prewalk-executor",
        }
        self.run_script(
            "claude", "handoff_lifecycle.py",
            payload={**lifecycle, "hook_event_name": "SubagentStart"},
        )
        self.run_script(
            "claude", "handoff_lifecycle.py",
            payload={
                **lifecycle,
                "hook_event_name": "SubagentStop",
                "last_assistant_message": "PREWALK_COMPLETE",
            },
        )
        # Foreground Agent PostToolUse arrives after SubagentStop and is harmless.
        self.run_script("claude", "handoff_result.py", payload={
            "session_id": session_id,
            "hook_event_name": "PostToolUse",
            "tool_use_id": "tool-foreground",
            "tool_response": {"success": True},
        })
        self.assertIn(
            "idle",
            self.run_script("claude", "_arm.py", "status", session_id).stdout,
        )

    def test_claude_token_call_without_tool_identity_is_denied_and_retryable(self) -> None:
        session_id = "claude-no-tool-id"
        self.arm_claude_checkpoint(session_id)
        handoff = self.run_script("claude", "_pw.py", "go", session_id)
        token = self.handoff_token(handoff.stdout)
        denied = self.run_script("claude", "handoff_router.py", payload={
            "session_id": session_id,
            "hook_event_name": "PreToolUse",
            "tool_input": {"prompt": f"packet\nPREWALK_HANDOFF_TOKEN: {token}"},
        })
        output = json.loads(denied.stdout)
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")
        state = self.claude_state(session_id)
        self.assertEqual(state["phase"], "incomplete")
        self.assertIn("tool_use_id", state["last_error"])

    def test_claude_fast_mode_requests_handoff_from_stop_hook(self) -> None:
        session_id = "claude-fast"
        self.run_script(
            "claude", "_arm.py", "arm", session_id, "--fast Build the feature"
        )
        self.run_script(
            "claude", "todo_tracker.py",
            payload=self.todo_payload(session_id, "claude"),
        )
        stopped = self.run_script("claude", "pause_detect.py", payload={
            "session_id": session_id,
            "hook_event_name": "Stop",
            "last_assistant_message": PACKET,
        })
        output = json.loads(stopped.stdout)
        self.assertEqual(output["decision"], "block")
        self.assertIn("spawn ONE Task", output["reason"])
        status = self.run_script("claude", "_arm.py", "status", session_id)
        self.assertIn("handoff_requested", status.stdout)


if __name__ == "__main__":
    unittest.main()
