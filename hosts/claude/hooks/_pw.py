#!/usr/bin/env python3
"""Skill-side helper for the Claude Code host: handoff and revision commands.

Invoked by the ``/pw-go`` / ``/pw-revise`` / ``/pw-retry`` /
``/pw-reconcile`` / ``/pw-resume`` / ``/pw-off`` skills:

  _pw.py go                  <session_id>
  _pw.py revise              <session_id> [revision text...]
  _pw.py retry               <session_id>
  _pw.py reconcile           <session_id> [--confirmed-not-running] [detail...]
  _pw.py confirm|resume      <session_id>
  _pw.py fail                <session_id> [reason...]
  _pw.py complete|incomplete <session_id> [detail...]

Claude routes are minted from environment capability (no live schema
fields), and completion is accepted only from the bound executor's
SubagentStop marker — hence the manual completions refuse instead of
performing state surgery.
"""

from __future__ import annotations

import os
import sys

import _engine  # noqa: F401  (locates prewalk_engine)
import _common  # type: ignore[import-not-found]  # noqa: E402
import prewalk_engine as core  # noqa: E402


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    sub = sys.argv[1]
    session_id = _common.resolve_session_id(sys.argv[2])
    store = _common.store_file()

    if sub == "go":
        result = core.request_claude_handoff(
            store, session_id, environment=dict(os.environ)
        )
        print(_common.claude_commands(
            result.message or "There is no active prewalk checkpoint in this session."
        ))
        return 0

    if sub == "retry":
        result = core.prepare_v4_retry(store, session_id)
        if result.status in ("checkpoint_ready", "handoff_requested"):
            result = core.request_claude_handoff(
                store, session_id, environment=dict(os.environ)
            )
        print(_common.claude_commands(
            result.message or "There is no retryable prewalk checkpoint in this session."
        ))
        return 0

    if sub == "reconcile":
        confirmed = "--confirmed-not-running" in sys.argv[3:]
        detail = " ".join(
            argument for argument in sys.argv[3:]
            if argument != "--confirmed-not-running"
        )
        result = core.reconcile_v4_route(
            store,
            session_id,
            confirmed_not_running=confirmed,
            detail=detail,
        )
        print(_common.claude_commands(result.message))
        return 0

    if sub == "revise":
        revision = " ".join(sys.argv[3:]).strip()
        result = core.revise_v4_checkpoint(store, session_id, revision)
        print(_common.claude_commands(
            result.message or "There is no active prewalk checkpoint to revise."
        ))
        return 0

    if sub in ("confirm", "resume"):
        print(_common.claude_commands(
            "Claude native routes cannot be completed manually. Run pw-status, then use "
            "pw-reconcile only after proving the prior agent is not running."
        ))
        return 0

    if sub == "fail":
        print(_common.claude_commands(
            "Legacy manual failure is disabled; use pw-reconcile with explicit liveness proof."
        ))
        return 0

    if sub in ("complete", "incomplete"):
        print(
            "Claude completion is accepted only from the bound executor's SubagentStop marker."
        )
        return 0

    print("unknown subcommand: " + sub, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
