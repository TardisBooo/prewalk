#!/usr/bin/env python3
"""Track launch success/failure for the exact routed Agent tool call.

Serves the three result-ish events registered in ``hooks.json``
(``PostToolUse`` / ``PostToolUseFailure`` / ``PermissionDenied`` on
``Task|Agent``): a clean response acknowledges the launch and moves the
route to ``executor_running``; any failure fails the route back to
``incomplete`` so ``pw-retry`` can re-mint it.
"""

from __future__ import annotations

import _engine  # noqa: F401  (locates prewalk_engine)
import _common  # type: ignore[import-not-found]
import prewalk_engine as core  # noqa: E402


def _response_text(value) -> str:
    """Flatten arbitrary response envelopes into text for logging/diagnostics."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_response_text(item) for item in value)
    if not isinstance(value, dict):
        return ""
    parts: list[str] = []
    for key, item in value.items():
        if key in ("text", "content", "result", "output", "data", "message", "error"):
            parts.append(_response_text(item))
    return "\n".join(part for part in parts if part)


def main() -> int:
    payload = _common.read_input()
    sid = _common.session_id(payload)
    store = _common.store_file()
    if not sid:
        return 0

    tool_use_id = str(payload.get("tool_use_id") or payload.get("toolUseId") or "").strip()
    event = str(payload.get("hook_event_name") or payload.get("hookEventName") or "PostToolUse")
    failed_event = event in ("PostToolUseFailure", "PermissionDenied")
    response = payload.get("tool_response", payload.get("toolResponse"))
    result = _response_text(response)
    if failed_event:
        error = str(payload.get("error") or payload.get("reason") or result).strip()
        reason = error.splitlines()[0] if error else "executor Task failed or was rejected"
        decision = core.fail_claude_agent_call(
            store, sid, tool_use_id=tool_use_id, reason=reason
        )
        if decision.handled:
            _common.emit(core.HookAction(system_message=decision.message), event=event)
        return 0

    decision = core.acknowledge_claude_agent_call(
        store, sid, tool_use_id=tool_use_id
    )
    if decision.handled:
        _common.emit(core.HookAction(system_message=decision.message), event=event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
