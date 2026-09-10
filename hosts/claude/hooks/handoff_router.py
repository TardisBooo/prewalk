#!/usr/bin/env python3
"""Rewrite only the persisted-token Agent call onto the executor.

Claude Code PreToolUse can return ``updatedInput``, so this host routes by
*rewriting* rather than denying: when the model's Task/Agent call carries
the minted route token, the call is rewritten onto the plugin's executor
agent and the configured executor model. Any deviation is denied and the
durable checkpoint stays retryable.
"""

from __future__ import annotations

import json
import os
import sys

import _engine  # noqa: F401  (locates prewalk_engine)
import _common  # type: ignore[import-not-found]
import prewalk_engine as core  # noqa: E402


def _deny_route(reason: str) -> int:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
        "systemMessage": _common.claude_commands(
            "prewalk: executor route rejected; the durable checkpoint is retryable."
        ),
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


def main() -> int:
    payload = _common.read_input()
    sid = _common.session_id(payload)
    store = _common.store_file()
    if not sid:
        return 0

    # Plugin hooks also run inside subagents. Only the root session may
    # consume the one-time handoff token and bind an executor spawn.
    if payload.get("agent_id") or payload.get("agentId"):
        return 0

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0

    tool_use_id = str(payload.get("tool_use_id") or payload.get("toolUseId") or "").strip()
    decision = core.validate_claude_agent_call(
        store,
        sid,
        tool_input,
        tool_use_id=tool_use_id,
        environment=dict(os.environ),
    )
    if not decision.handled:
        return 0
    if not decision.allowed:
        return _deny_route(decision.message)

    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": decision.updated_input,
        },
        "systemMessage": (
            f"prewalk: routed Agent {tool_use_id} to {core.CLAUDE_EXECUTOR_AGENT} on "
            f"{decision.state.executor_model}; "
            "waiting for the bound subagent lifecycle"
        ),
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
