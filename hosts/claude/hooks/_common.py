#!/usr/bin/env python3
"""Shared I/O plumbing for the Claude Code adapter.

Every entry script (``pause_detect``, ``todo_tracker``, ``edit_tracker``,
``handoff_router``, ``handoff_result``, ``handoff_lifecycle``) and the
``_arm``/``_pw`` helpers import from here. The module is a thin shim over
the vendored engine: it resolves state and preset files under the Claude
config directory, normalizes Claude Code's payload shapes (TodoWrite *and*
the newer Task tools) into engine types, namespaces command names through
the plugin prefix, and renders engine :class:`~prewalk_engine.HookAction`
decisions into the host's hook-output JSON.

Two Claude Code realities shape this adapter:

* **Call rewriting exists.** PreToolUse may return ``updatedInput``, so
  routing works by *rewriting* the model's own Agent/Task call onto the
  executor agent and model — no strict deny-unless-exact dance needed.
* **Session identity is awkward.** The session id reaches hooks via stdin
  but not the Bash-tool environment (anthropics/claude-code#20132), so
  ``export_session_id.py`` mirrors it into ``$CLAUDE_ENV_FILE`` and
  ``resolve_session_id`` falls back to the newest transcript of this
  project. Subagent events are only honored when explicitly allowed, and
  only for the executor lifecycle.
"""

from __future__ import annotations

import glob
import json
import os
from pathlib import Path
import re
import sys

import _engine  # noqa: F401  (makes prewalk_engine importable)
import prewalk_engine as core  # noqa: E402


# --- Files and namespacing ------------------------------------------------------


def config_home() -> str:
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def store_file() -> str:
    override = os.environ.get("PREWALK_STATE_FILE", "").strip()
    if override:
        return str(Path(os.path.expandvars(override)).expanduser())
    return os.path.join(config_home(), "prewalk-state.json")


def state_store_access() -> tuple[bool, str]:
    """Probe the exact lock path used by the store and return a diagnostic."""
    path = Path(store_file())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path.with_name(path.name + ".lock"), "a+b"):
            pass
    except OSError as exc:
        return False, f"{path}: {exc}"
    return True, str(path)


def presets_file() -> str:
    return os.path.join(config_home(), "prewalk-presets.json")


def claude_commands(text: str) -> str:
    """Render shared-engine command names through the plugin skill namespace.

    ``/pw-go`` becomes ``/prewalk:pw-go``; a bare ``/prewalk`` becomes
    ``/prewalk:prewalk`` — the namespaced forms Claude Code resolves inside
    a plugin.
    """
    text = text.replace("/pw-", "/prewalk:pw-")
    return re.sub(r"(?<![A-Za-z0-9_.~-])/prewalk(?!:)", "/prewalk:prewalk", text)


def read_input() -> dict:
    """Parse the hook payload from stdin; malformed input becomes empty."""
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


# --- Session identity -------------------------------------------------------------


def session_id(payload: dict, *, allow_subagent: bool = False) -> str:
    """Return the payload's session id — ignoring subagent events by default.

    Plugin hooks also fire inside subagents; only the executor lifecycle is
    allowed to act on a subagent payload, and it opts in explicitly.
    """
    if not allow_subagent and (payload.get("agent_id") or payload.get("agentId")):
        return ""
    return str(payload.get("session_id") or payload.get("sessionId") or "")


def resolve_session_id(given: str) -> str:
    """Return a non-empty session id, deriving one if the caller passed none.

    The ``/prewalk`` skill passes ``$CLAUDE_SESSION_ID``, which stays empty
    unless a SessionStart hook populated it via ``CLAUDE_ENV_FILE`` (see
    ``export_session_id.py``). As a last resort, derive the id from the
    most-recently-modified transcript of this project — Claude Code stores
    them under ``~/.claude/projects/<cwd-with-/→->/`` with the sessionId as
    the filename.
    """
    given = (given or "").strip()
    if given:
        return given
    dashed = os.getcwd().replace("/", "-")
    proj_dir = os.path.join(os.path.expanduser("~/.claude/projects"), dashed)
    try:
        files = sorted(
            glob.glob(os.path.join(proj_dir, "*.jsonl")),
            key=os.path.getmtime,
            reverse=True,
        )
    except OSError:
        files = []
    if files:
        return os.path.basename(files[0])[:-6]  # strip .jsonl
    return ""


# --- Payload field access -----------------------------------------------------------


def _event_part(payload: dict, snake_name: str, camel_name: str):
    if snake_name in payload:
        return payload[snake_name]
    return payload.get(camel_name)


def _tool_name(payload: dict) -> str:
    raw = payload.get("tool_name") or payload.get("toolName") or payload.get("name") or ""
    return str(raw).rsplit(".", 1)[-1].lower()


# --- Todo normalization -----------------------------------------------------------


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


def _task_to_todo(item: dict) -> core.Todo | None:
    """Coerce one task dict (TodoWrite OR the newer TaskCreate/TaskList shape).

    TodoWrite items: ``{content, status, activeForm}``.
    New task system: ``{id/uuid, subject, description, status, ...}``.
    """
    if not isinstance(item, dict):
        return None
    content = str(
        item.get("content")
        or item.get("subject")
        or item.get("description")
        or item.get("text")
        or item.get("step")
        or item.get("title")
        or ""
    )
    status = str(item.get("status") or item.get("state") or "").lower()
    # Both systems share the pending/in_progress/completed vocabulary.
    return core.Todo(
        id=str(item.get("id") or item.get("uuid") or content[:40]),
        content=content,
        status=status,
    )


def normalize_todos(payload: dict) -> list[core.Todo]:
    """Read the current task list from a tool event — both task systems.

    Preference order: a full list in ``tool_input`` (TodoWrite) or
    ``tool_response`` (TaskList / TodoWrite echo) beats a single created or
    updated task in ``tool_input`` (TaskCreate/TaskUpdate).
    """
    out: list[core.Todo] = []

    for holder in (
        _event_part(payload, "tool_input", "toolInput"),
        _event_part(payload, "tool_response", "toolResponse"),
    ):
        items = _todo_items(holder)
        if items:
            for it in items:
                todo = _task_to_todo(it) if isinstance(it, dict) else None
                if todo:
                    out.append(todo)
            if out:
                return out  # a full list beats a single item

    tool_input = _event_part(payload, "tool_input", "toolInput") or {}
    if isinstance(tool_input, dict) and (tool_input.get("subject") or tool_input.get("description")):
        todo = _task_to_todo(tool_input)
        if todo:
            # TaskCreate implies a new pending item; TaskUpdate carries its own status.
            if not todo.status:
                todo.status = "pending"
            out.append(todo)
    return out


def has_complete_todo_snapshot(payload: dict) -> bool:
    """Return whether this event carries a list, rather than one task mutation."""
    return any(
        bool(_todo_items(holder))
        for holder in (
            _event_part(payload, "tool_input", "toolInput"),
            _event_part(payload, "tool_response", "toolResponse"),
        )
    )


# --- Edit / mutation normalization ----------------------------------------------------


def normalize_edit_success(payload: dict) -> bool:
    """Return whether a PostToolUse edit payload represents a successful edit."""
    response = _event_part(payload, "tool_response", "toolResponse")
    if response is None or response is False:
        return False
    return not has_explicit_failure(response)


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


_ORCHESTRATOR_PATCH_RE = re.compile(r"\btools(?:\.[A-Za-z0-9_]+)*\.apply_patch\s*\(")


def _orchestrator_applies_patch(payload: dict) -> bool:
    """Recognize apply_patch calls nested in a free-form orchestration tool."""
    tool_input = _event_part(payload, "tool_input", "toolInput")
    if isinstance(tool_input, str):
        source = tool_input
    elif isinstance(tool_input, dict):
        source = tool_input.get("input") or tool_input.get("code") or tool_input.get("script") or ""
    else:
        source = ""
    return bool(_ORCHESTRATOR_PATCH_RE.search(str(source)))


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
        return _shell_applies_patch(payload) or _orchestrator_applies_patch(payload)
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


# --- Hook output ---------------------------------------------------------------------


def emit(action: core.HookAction | None, *, event: str, deny_as_permission: bool = False) -> None:
    """Render an engine HookAction to Claude Code stdout JSON (or print nothing).

    ``decision: block`` + ``reason`` is the Stop/PostToolUse block shape;
    PreToolUse uniquely carries its deny decision inside
    ``hookSpecificOutput.permissionDecision``. ``additionalContext`` reaches
    the model on PostToolUse. All text passes through the command
    namespacer so skill references stay plugin-qualified.
    """
    if action is None:
        return
    out: dict = {}
    if action.system_message:
        out["systemMessage"] = claude_commands(action.system_message)
    if not action.proceed:
        if deny_as_permission:
            out["hookSpecificOutput"] = {
                "hookEventName": event or "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": claude_commands(action.block_reason),
            }
        else:
            out["decision"] = "block"
            out["reason"] = claude_commands(action.block_reason)
    elif action.additional_context:
        out["hookSpecificOutput"] = {
            "hookEventName": event or "PostToolUse",
            "additionalContext": claude_commands(action.additional_context),
        }
    if out:
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
