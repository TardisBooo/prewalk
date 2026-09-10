#!/usr/bin/env python3
"""Claude PostToolUse hook that persists complete real-work task snapshots.

Runs on TodoWrite and the Task* tools. Only full list snapshots are recorded
— a single-task mutation is not a plan. An invalid snapshot (wrong shape,
over the cap, missing verification criteria) is echoed back to the model as
additionalContext immediately, so the planner fixes its task list on the
next step instead of failing the Stop checkpoint much later.
"""

from __future__ import annotations

import _engine  # noqa: F401  (locates prewalk_engine)
import _common  # type: ignore[import-not-found]
import prewalk_engine as core  # noqa: E402


def main() -> int:
    payload = _common.read_input()
    sid = _common.session_id(payload)
    store = _common.store_file()
    loaded = core.load_v4_state(store, sid)
    if loaded.state is None or loaded.state.phase != core.V4_PLANNING:
        return 0

    todos = _common.normalize_todos(payload)
    if not todos or not _common.has_complete_todo_snapshot(payload):
        return 0

    result = core.record_v4_todos(store, sid, todos)
    if result.status == "invalid_todos":
        # additionalContext reaches the model (systemMessage does not); the
        # planner can fix the task list on its next step instead of failing
        # the Stop checkpoint later.
        _common.emit(core.HookAction(
            additional_context=f"prewalk todo check: {result.message}",
            system_message="prewalk: todo snapshot rejected; correction requested.",
        ), event="PostToolUse")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
