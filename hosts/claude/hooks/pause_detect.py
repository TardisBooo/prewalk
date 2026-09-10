#!/usr/bin/env python3
"""Claude root Stop hook: validate and durably capture the v4 checkpoint.

Behavior, in order:

1. Run the checkpoint capture over the Stop snapshot.
2. A *valid* checkpoint under fast mode immediately mints the token-bound
   route (Claude capability is proven from the environment, no live schema
   to inspect) and blocks the Stop with the routing instructions.
3. A *malformed* checkpoint is rejected with a bounded number of blocking
   retries so the planner repairs its packet in-session instead of losing
   the checkpoint to a user-only system message.
4. Anything else surfaces as a system message only.
"""

from __future__ import annotations

import os

import _engine  # noqa: F401  (locates prewalk_engine)
import _common  # type: ignore[import-not-found]
import prewalk_engine as core  # noqa: E402


def main() -> int:
    payload = _common.read_input()
    sid = _common.session_id(payload)
    if not sid:
        return 0
    store = _common.store_file()
    packet = str(
        payload.get("last_assistant_message")
        or payload.get("lastAssistantMessage")
        or ""
    )
    event_id = str(payload.get("event_id") or payload.get("eventId") or "")
    result = core.capture_v4_checkpoint(
        store,
        sid,
        packet=packet,
        todos=_common.normalize_todos(payload) or None,
        event_id=event_id,
    )
    if (
        result.status == "checkpoint_ready"
        and result.state is not None
        and result.state.fast_mode
    ):
        route = core.request_claude_handoff(
            store, sid, environment=dict(os.environ)
        )
        if route.status == "handoff_requested":
            _common.emit(
                core.HookAction(proceed=False, block_reason=route.message), event="Stop"
            )
            return 0
    if result.status in (
        "missing_todos",
        "invalid_todos",
        "incomplete_task_one",
        "invalid_packet",
        "missing_evidence",
    ):
        # A malformed checkpoint is recoverable: block the Stop with the
        # reason so the planner emits a corrected packet (bounded retries),
        # instead of dying with a user-only system message.
        count, retry = core.note_v4_checkpoint_reject(store, sid, reason=result.message)
        if retry:
            _common.emit(core.HookAction(
                proceed=False,
                block_reason=(
                    f"Your Prewalk checkpoint was rejected: {result.message} "
                    "Fix it now (todo list and/or final packet), then stop again."
                ),
                system_message=f"prewalk: checkpoint rejected ({count}/"
                f"{core.V4_CHECKPOINT_RETRY_LIMIT}); model asked to correct it.",
            ), event="Stop")
            return 0
    if result.message:
        _common.emit(core.HookAction(system_message=result.message), event="Stop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
