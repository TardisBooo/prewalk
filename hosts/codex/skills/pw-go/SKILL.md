---
name: pw-go
description: Request a capability-safe executor handoff from a durable Prewalk Stop checkpoint.
---

# $prewalk:pw-go - hand off to the executor

Inspect the live `spawn_agent` schema first. Pass the field names it actually
exposes to the state transition helper, then follow its output exactly:

```bash
python3 hooks/_pw.py go "${CODEX_THREAD_ID:-${CODEX_SESSION_ID:-}}" \
  --schema-fields=task_name,message,fork_turns,model,reasoning_effort
```

Omit any field name that is absent from the live schema. Do not claim support
from a preset or documentation; only the current tool schema is proof.

If no active checkpoint exists, report that in one line and stop.

## Native spawn path

1. If the helper reports an unsupported route, do not spawn. The durable
   checkpoint remains ready for diagnosis or recovery.
2. When routing is supported, call `spawn_agent` exactly once with the helper's
   generated `task_name`, the exact text between `PREWALK_MESSAGE_BEGIN` and
   `PREWALK_MESSAGE_END` as `message`, the `PREWALK_FORK_TURNS` value printed
   by the helper (`"all"` inherits the planner's full trajectory — default;
   `"none"` starts a fresh packet-only context), and the configured executor
   `model`. Include `reasoning_effort` only when the helper prints it. Do not
   use a named plugin agent and do not alter the message.
3. Wait for the bound executor. Codex hooks bind the agent ID returned by this
   exact tool call and consume only that agent's `SubagentStop` marker.

Do not run manual confirm/complete commands. Spawn denial, failure, interruption,
missing markers, and incomplete markers remain durable for `pw-retry` recovery.
