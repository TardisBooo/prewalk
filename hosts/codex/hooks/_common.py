#!/usr/bin/env python3
"""Shared I/O plumbing for the Codex adapter.

Every entry script (``pause_detect``, ``todo_tracker``, ``edit_tracker``,
``executor_router``, and the ``_arm``/``_pw`` helpers) imports from here.
The module is a thin shim over the vendored engine: it resolves the state
and preset files under ``CODEX_HOME``, normalizes Codex's payload shapes
into engine types, and renders engine :class:`~prewalk_engine.HookAction`
decisions into the host's hook-output JSON.

Two Codex realities shape this adapter:

* **No call rewriting.** Codex hooks cannot alter a tool call mid-flight
  (there is no ``updatedInput``), so routing works by *validating* the
  model's own ``spawn_agent`` call against the minted route — any mismatch
  is denied before execution.
* **Thread identity is authoritative.** When ``CODEX_THREAD_ID`` is set,
  a payload whose ``session_id`` disagrees is treated as foreign, and the
  adapter never guesses identity from the newest rollout file on disk.
"""

from __future__ import annotations

import json
import os
import sys

import _engine  # noqa: F401  (makes prewalk_engine importable)
import prewalk_engine as core  # noqa: E402


def codex_home() -> str:
    return os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")


def store_file() -> str:
    return os.path.join(codex_home(), "prewalk-state.json")


def presets_file() -> str:
    return os.path.join(codex_home(), "prewalk-presets.toml")


def read_input() -> dict:
    """Parse the hook payload from stdin; malformed input becomes empty."""
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


# --- Session identity ---------------------------------------------------------


def session_id(payload: dict) -> str:
    """Return the payload's session id, but only when it matches the thread.

    A hook payload without an id, or one naming a different thread than the
    process is running in, is not this session's business.
    """
    payload_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
    thread_id = os.environ.get("CODEX_THREAD_ID", "").strip()
    if not payload_id or (thread_id and payload_id != thread_id):
        return ""
    return payload_id


def resolve_session_id(given: str) -> str:
    """Resolve a helper's state key without guessing another active thread."""
    given = (given or "").strip()
    thread_id = os.environ.get("CODEX_THREAD_ID", "").strip()
    if thread_id:
        return thread_id if not given or given == thread_id else ""
    if given:
        return given
    return os.environ.get("CODEX_SESSION_ID", "").strip()


# --- Payload field access -------------------------------------------------------


def _event_part(payload: dict, snake_name: str, camel_name: str):
    if snake_name in payload:
        return payload[snake_name]
    return payload.get(camel_name)


def _tool_name(payload: dict) -> str:
    raw = payload.get("tool_name") or payload.get("toolName") or payload.get("name") or ""
    return str(raw).rsplit(".", 1)[-1].lower()


# --- Todo normalization ---------------------------------------------------------


def _todo_items(holder) -> list[dict]:
    """Find a todo list through the small set of wrappers used by hook tools."""
    if isinstance(holder, str):
        try:
            holder = json.loads(holder)
        except json.JSONDecodeError:
            return []
    if isinstance(holder, list):
        return [item for item in holder if _looks_like_todo(item)]
    if not isinstance(holder, dict):
        return []
    for key in ("todos", "tasks", "plan", "items", "steps"):
        if isinstance(holder.get(key), list):
            return [item for item in holder[key] if _looks_like_todo(item)]
    for key in ("result", "output", "data", "structured_content", "structuredContent"):
        items = _todo_items(holder.get(key))
        if items:
            return items
    return []


def _looks_like_todo(item) -> bool:
    if not isinstance(item, dict):
        return False
    has_content = any(
        key in item for key in ("content", "text", "step", "subject", "description", "title")
    )
    has_identity_or_status = any(key in item for key in ("id", "uuid", "status", "state"))
    return has_content and has_identity_or_status


def _item_to_todo(item: dict) -> core.Todo:
    content = str(
        item.get("content")
        or item.get("text")
        or item.get("step")
        or item.get("subject")
        or item.get("description")
        or item.get("title")
        or ""
    )
    status = str(item.get("status") or item.get("state") or "").lower()
    return core.Todo(
        id=str(item.get("id") or item.get("uuid") or content[:40]),
        content=content,
        status=status,
    )


def normalize_todos(payload: dict) -> list[core.Todo]:
    """Read todos from tool_input (PreToolUse) or tool_response (PostToolUse/Stop).

    Codex's plan/todo tools carry items as dicts; field names vary by tool
    (``update_plan`` vs ``todo``), so content and status are accepted under
    any of the common keys.
    """
    for holder in (
        _event_part(payload, "tool_input", "toolInput"),
        _event_part(payload, "tool_response", "toolResponse"),
    ):
        items = _todo_items(holder)
        if items:
            return [_item_to_todo(item) for item in items]
    return []


def has_complete_todo_snapshot(payload: dict) -> bool:
    """Return whether this event carries a list, rather than one task mutation."""
    return any(
        bool(_todo_items(holder))
        for holder in (
            _event_part(payload, "tool_input", "toolInput"),
            _event_part(payload, "tool_response", "toolResponse"),
        )
    )


# --- Edit / mutation normalization ------------------------------------------------


def normalize_edit_success(payload: dict) -> bool:
    """Return whether a PostToolUse edit payload represents a successful edit."""
    response = _event_part(payload, "tool_response", "toolResponse")
    if response is None or response is False:
        return False
    return not _has_explicit_failure(response)


def _command_heads(command: str) -> list[str]:
    """Return executable-position words while ignoring quotes and comments.

    A hand-rolled scan (instead of shlex) because the point is *position*:
    ``apply_patch`` only counts when the shell would execute it, not when it
    appears inside a quoted argument or a comment.
    """
    heads: list[str] = []
    word: list[str] = []
    quote = ""
    escaped = False
    expect_head = True

    def finish_word() -> None:
        nonlocal expect_head
        if not word:
            return
        token = "".join(word)
        word.clear()
        if expect_head and "=" not in token:
            heads.append(token)
            expect_head = False

    index = 0
    while index < len(command):
        char = command[index]
        if escaped:
            word.append(char)
            escaped = False
        elif quote:
            if char == quote:
                quote = ""
            elif char == "\\" and quote == '"':
                escaped = True
            else:
                word.append(char)
        elif char in ("'", '"'):
            quote = char
        elif char == "\\":
            escaped = True
        elif char == "#" and not word:
            finish_word()
            while index < len(command) and command[index] != "\n":
                index += 1
            expect_head = True
        elif char.isspace():
            finish_word()
            if char == "\n":
                expect_head = True
        elif char in ";|&()":
            finish_word()
            expect_head = True
        else:
            word.append(char)
        index += 1
    finish_word()
    return heads


def _shell_applies_patch(payload: dict) -> bool:
    tool_input = _event_part(payload, "tool_input", "toolInput") or {}
    if not isinstance(tool_input, dict):
        return False
    command = tool_input.get("cmd") or tool_input.get("command") or ""
    return any(head.rsplit("/", 1)[-1] == "apply_patch" for head in _command_heads(str(command)))


def _repoprompt_mutates(payload: dict) -> bool:
    tool_input = _event_part(payload, "tool_input", "toolInput") or {}
    if not isinstance(tool_input, dict):
        return False
    operation = str(
        tool_input.get("tool") or tool_input.get("tool_name") or tool_input.get("toolName") or ""
    ).lower()
    if operation in ("apply_edits", "apply_patch"):
        return True
    if operation != "file_actions":
        return False
    actions = tool_input.get("actions") or tool_input.get("args") or tool_input.get("arguments") or []
    text = json.dumps(actions, ensure_ascii=True).lower()
    return any(action in text for action in ('"create"', '"delete"', '"move"', '"write"'))


def _has_explicit_noop(value) -> bool:
    if isinstance(value, list):
        return any(_has_explicit_noop(item) for item in value)
    if not isinstance(value, dict):
        return False
    if any(key in value and value.get(key) is False for key in ("changed", "modified", "applied")):
        return True
    if str(value.get("status", "")).lower() in ("noop", "no-op", "no_changes", "unchanged"):
        return True
    return any(
        _has_explicit_noop(value.get(key))
        for key in ("result", "output", "data", "structured_content", "structuredContent")
    )


def normalize_mutation_success(payload: dict) -> bool:
    """True only for a successful tool call that can actually mutate files.

    Read-only results, explicit no-ops, failed calls, and shell commands that
    merely *mention* ``apply_patch`` in quotes or comments all return False —
    the planner budget must only count real file mutations.
    """
    if not normalize_edit_success(payload):
        return False
    response = _event_part(payload, "tool_response", "toolResponse")
    if _has_explicit_noop(response):
        return False
    name = _tool_name(payload)
    if not name:
        return True  # Hook matchers already scoped legacy payloads to edit tools.
    if name in ("apply_patch", "edit", "write", "multiedit"):
        return True
    if name in ("bash", "exec", "exec_command"):
        return _shell_applies_patch(payload)
    if name in ("rp", "repoprompt"):
        return _repoprompt_mutates(payload)
    return False


def _has_explicit_failure(value) -> bool:
    if isinstance(value, list):
        return any(_has_explicit_failure(item) for item in value)
    if not isinstance(value, dict):
        return False
    if value.get("is_error") is True or value.get("isError") is True:
        return True
    if any(value.get(key) is False for key in ("ok", "success", "executed")):
        return True
    if value.get("error"):
        return True
    if str(value.get("status", "")).lower() in ("error", "failed", "failure"):
        return True
    return any(
        _has_explicit_failure(value.get(key))
        for key in ("result", "output", "data", "structured_content", "structuredContent")
    )


def has_explicit_failure(value) -> bool:
    return _has_explicit_failure(value)


# --- Hook output ---------------------------------------------------------------


def emit(action: core.HookAction | None, *, event: str, deny_as_permission: bool = False) -> None:
    """Render an engine HookAction to Codex stdout JSON (or print nothing).

    Codex's Stop/UserPromptSubmit accept top-level ``decision: block`` +
    ``reason``, which creates a new continuation prompt. PreToolUse carries
    its deny decision inside ``hookSpecificOutput.permissionDecision``.
    ``additionalContext`` is supported across events.
    """
    if action is None:
        return
    out: dict = {}
    if action.system_message:
        out["systemMessage"] = action.system_message
    if not action.proceed:
        if deny_as_permission:
            out["hookSpecificOutput"] = {
                "hookEventName": event or "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": action.block_reason,
            }
        else:
            out["decision"] = "block"
            out["reason"] = action.block_reason
    elif action.additional_context:
        out["hookSpecificOutput"] = {
            "hookEventName": event or "Stop",
            "additionalContext": action.additional_context,
        }
    if out:
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
