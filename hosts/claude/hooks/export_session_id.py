#!/usr/bin/env python3
"""SessionStart hook — expose the session id to Bash-tool commands.

Claude Code does NOT inject the session id into the Bash-tool subprocess
environment by default (anthropics/claude-code#20132, still open). Hooks,
however, receive ``session_id`` in their stdin JSON, and a SessionStart hook
can persist environment variables into ``$CLAUDE_ENV_FILE`` — everything
written there becomes available to every subsequent Bash command of the
session.

So this hook reads the id from stdin and appends
``export CLAUDE_SESSION_ID="<id>"`` to the env file, after which the skill's
``_arm.py arm "$CLAUDE_SESSION_ID" ...`` works. It must never block a
session from starting: every failure path is swallowed, exit 0 always.
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    sid = str(payload.get("session_id") or payload.get("sessionId") or "")
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if sid and env_file:
        try:
            with open(env_file, "a", encoding="utf-8") as fh:
                fh.write(f'export CLAUDE_SESSION_ID="{sid}"\n')
        except OSError:
            pass  # never block session start
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
