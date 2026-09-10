#!/usr/bin/env python3
"""Bind and finish only the routed prewalk executor subagent.

SubagentStart binds the started agent id to the pending route; SubagentStop
consumes the final marker — but only from the executor identity bound to
this root session's route. Every other subagent event is a no-op.
"""

from __future__ import annotations

import _engine  # noqa: F401  (locates prewalk_engine)
import _common  # type: ignore[import-not-found]
import prewalk_engine as core  # noqa: E402


def main() -> int:
    payload = _common.read_input()
    agent_type = str(payload.get("agent_type") or payload.get("agentType") or "")
    if agent_type not in core.CLAUDE_EXECUTOR_LIFECYCLE_TYPES:
        return 0

    sid = _common.session_id(payload, allow_subagent=True)
    store = _common.store_file()
    if not sid:
        return 0

    event = str(payload.get("hook_event_name") or payload.get("hookEventName") or "")
    agent_id = str(payload.get("agent_id") or payload.get("agentId") or "").strip()
    if event == "SubagentStart":
        decision = core.bind_claude_executor(
            store, sid, agent_id=agent_id, agent_type=agent_type
        )
        if decision.handled:
            _common.emit(core.HookAction(system_message=decision.message), event=event)
        return 0

    if event != "SubagentStop":
        return 0

    result = str(payload.get("last_assistant_message") or payload.get("lastAssistantMessage") or "")
    event_id = str(payload.get("event_id") or payload.get("eventId") or "")
    decision = core.finish_v4_executor(
        store,
        sid,
        agent_id=agent_id,
        result=result,
        event_id=event_id or f"claude-subagent-stop:{agent_id}",
    )
    if decision.handled:
        _common.emit(core.HookAction(system_message=decision.message), event=event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
