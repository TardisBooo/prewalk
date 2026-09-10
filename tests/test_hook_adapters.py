from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HOSTS = ROOT / "hosts"

# Module names each host adapter may import while loading; a load must start
# and end with none of them cached, so every host exercises its own engine
# copy rather than whichever one another test imported last.
_MANAGED = ("_engine", "_common", "prewalk_engine")


def _evict_managed() -> dict[str, object]:
    saved = {}
    for name in list(sys.modules):
        if name in _MANAGED or name.startswith("prewalk_engine."):
            saved[name] = sys.modules.pop(name)
    return saved


def load_common(host: str):
    hooks = HOSTS / host / "hooks"
    saved_modules = _evict_managed()
    sys.path.insert(0, str(hooks))
    try:
        spec = importlib.util.spec_from_file_location(f"{host}_common", hooks / "_common.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)
        _evict_managed()
        sys.modules.update(saved_modules)


class HookAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.codex = load_common("codex")
        cls.claude = load_common("claude")

    def test_codex_update_plan_input(self) -> None:
        payload = {
            "session_id": "codex-session",
            "hook_event_name": "PostToolUse",
            "tool_name": "functions.update_plan",
            "tool_input": {
                "explanation": "Implement in order",
                "plan": [
                    {"step": "Patch adapter and test it", "status": "in_progress"},
                    {"step": "Run build checks", "status": "pending"},
                ],
            },
            "tool_response": {"ok": True},
        }
        todos = self.codex.normalize_todos(payload)
        self.assertEqual([todo.content for todo in todos], [
            "Patch adapter and test it",
            "Run build checks",
        ])
        self.assertEqual([todo.status for todo in todos], ["in_progress", "pending"])

    def test_claude_todowrite_input(self) -> None:
        payload = {
            "session_id": "claude-session",
            "hook_event_name": "PostToolUse",
            "tool_name": "TodoWrite",
            "tool_input": {
                "todos": [
                    {
                        "content": "Patch adapter and test it",
                        "status": "in_progress",
                        "activeForm": "Patching adapter",
                    }
                ]
            },
            "tool_response": {"success": True},
        }
        todos = self.claude.normalize_todos(payload)
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0].content, "Patch adapter and test it")
        self.assertEqual(todos[0].status, "in_progress")
        self.assertTrue(self.claude.has_complete_todo_snapshot(payload))

    def test_single_task_update_is_not_a_complete_snapshot(self) -> None:
        payload = {
            "tool_name": "TaskUpdate",
            "tool_input": {
                "taskId": "task-2",
                "subject": "Update adapter and verify it",
                "status": "completed",
            },
            "tool_response": {"success": True},
        }
        self.assertEqual(len(self.claude.normalize_todos(payload)), 1)
        self.assertFalse(self.claude.has_complete_todo_snapshot(payload))

    def test_claude_regular_hooks_ignore_subagent_payloads(self) -> None:
        payload = {
            "session_id": "root-session",
            "agent_id": "nested-agent",
            "agent_type": "prewalk:prewalk-executor",
        }
        self.assertEqual(self.claude.session_id(payload), "")
        self.assertEqual(
            self.claude.session_id(payload, allow_subagent=True),
            "root-session",
        )

    def test_claude_runtime_commands_are_namespaced(self) -> None:
        rendered = self.claude.claude_commands(
            "Run `/pw-go`, `/pw-revise <changes>`, or `/prewalk` again."
        )
        self.assertEqual(
            rendered,
            "Run `/prewalk:pw-go`, `/prewalk:pw-revise <changes>`, or "
            "`/prewalk:prewalk` again.",
        )

    def test_nested_task_list_response_and_camel_case_envelope(self) -> None:
        payload = {
            "sessionId": "session",
            "toolInput": {},
            "toolResponse": {
                "result": {
                    "tasks": [
                        {"uuid": "task-1", "subject": "Run build checks", "state": "COMPLETED"}
                    ]
                }
            },
        }
        for adapter in (self.codex, self.claude):
            with self.subTest(adapter=adapter.__name__):
                todos = adapter.normalize_todos(payload)
                self.assertEqual(len(todos), 1)
                self.assertEqual(todos[0].id, "task-1")
                self.assertEqual(todos[0].content, "Run build checks")
                self.assertEqual(todos[0].status, "completed")

    def test_generic_content_blocks_are_not_todos(self) -> None:
        payload = {
            "tool_input": {},
            "tool_response": [{"type": "text", "text": "Plan updated"}],
        }
        for adapter in (self.codex, self.claude):
            with self.subTest(adapter=adapter.__name__):
                self.assertEqual(adapter.normalize_todos(payload), [])

    def test_successful_edit_payloads(self) -> None:
        fixtures = [
            {"tool_response": {"filePath": "/tmp/example", "success": True}},
            {"tool_response": {"output": {"executed": True}}},
            {"toolResponse": [{"type": "text", "text": "Applied patch"}]},
        ]
        for adapter in (self.codex, self.claude):
            for payload in fixtures:
                with self.subTest(adapter=adapter.__name__, payload=payload):
                    self.assertTrue(adapter.normalize_edit_success(payload))

    def test_failed_or_missing_edit_payloads(self) -> None:
        fixtures = [
            {},
            {"tool_response": None},
            {"tool_response": False},
            {"tool_response": {"success": False}},
            {"tool_response": {"error": "permission denied"}},
            {"tool_response": {"result": {"is_error": True}}},
        ]
        for adapter in (self.codex, self.claude):
            for payload in fixtures:
                with self.subTest(adapter=adapter.__name__, payload=payload):
                    self.assertFalse(adapter.normalize_edit_success(payload))

    def test_codex_thread_identity_is_authoritative(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"CODEX_THREAD_ID": "thread-a", "CODEX_SESSION_ID": "legacy-a"},
            clear=False,
        ):
            self.assertEqual(self.codex.resolve_session_id(""), "thread-a")
            self.assertEqual(self.codex.resolve_session_id("thread-a"), "thread-a")
            self.assertEqual(self.codex.resolve_session_id("thread-b"), "")
            self.assertEqual(self.codex.session_id({"session_id": "thread-a"}), "thread-a")
            self.assertEqual(self.codex.session_id({"session_id": "thread-b"}), "")

    def test_codex_legacy_explicit_id_is_accepted_without_thread_env(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            with mock.patch.dict(
                os.environ, {"CODEX_THREAD_ID": "", "CODEX_SESSION_ID": ""}, clear=False
            ):
                self.assertEqual(self.codex.resolve_session_id("legacy-explicit"), "legacy-explicit")

    def test_codex_never_guesses_the_latest_rollout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp) / "sessions" / "2026" / "08"
            sessions.mkdir(parents=True)
            (sessions / "rollout-2026-08-20-fake-thread.jsonl").write_text("{}\n")
            with mock.patch.dict(
                os.environ,
                {"CODEX_HOME": tmp, "CODEX_THREAD_ID": "", "CODEX_SESSION_ID": ""},
                clear=False,
            ):
                self.assertEqual(self.codex.resolve_session_id(""), "")

    def test_mutation_detection_distinguishes_commands_from_text(self) -> None:
        true_fixtures = [
            {"tool_name": "apply_patch", "tool_response": {"success": True}},
            {
                "tool_name": "functions.exec_command",
                "tool_input": {"cmd": "cd src && apply_patch <<'PATCH'\nPATCH"},
                "tool_response": {"ok": True},
            },
            {
                "tool_name": "rp",
                "tool_input": {"tool": "apply_edits", "args": {"path": "README.md"}},
                "tool_response": {"success": True},
            },
        ]
        false_fixtures = [
            {
                "tool_name": "Bash",
                "tool_input": {"command": "echo 'apply_patch <<PATCH'"},
                "tool_response": {"success": True},
            },
            {
                "tool_name": "exec_command",
                "tool_input": {"cmd": "# apply_patch is documented here\nprintf done"},
                "tool_response": {"ok": True},
            },
            {
                "tool_name": "apply_patch",
                "tool_response": {"success": True, "changed": False},
            },
            {
                "tool_name": "Bash",
                "tool_input": {"command": "apply_patch <<PATCH"},
                "tool_response": {"success": False},
            },
            {
                "tool_name": "rp",
                "tool_input": {"tool": "read_file", "args": {"path": "README.md"}},
                "tool_response": {"success": True},
            },
        ]
        for adapter in (self.codex, self.claude):
            for payload in true_fixtures:
                with self.subTest(adapter=adapter.__name__, payload=payload):
                    self.assertTrue(adapter.normalize_mutation_success(payload))
            for payload in false_fixtures:
                with self.subTest(adapter=adapter.__name__, payload=payload):
                    self.assertFalse(adapter.normalize_mutation_success(payload))


if __name__ == "__main__":
    unittest.main()
