---
name: pw-go
description: Request a capability-safe executor handoff from a durable Prewalk Stop checkpoint.
---

# $prewalk:pw-go - hand off to the executor

Inspect the live `spawn_agent` schema first. Pass the field names it actually
exposes to the state transition helper, then follow its output exactly:

```bash
python3 hooks/_pw.py go "${CODEX_THREAD_ID:-${CODEX_SESSION_ID:-}}" \
  --schema-fields=<comma-separated live field names>
```

Omit any field name that is absent from the live schema. Do not claim support
from a preset or documentation; only the current tool schema is proof.

If no active checkpoint exists, report the helper's phase and last checkpoint
error and stop. Do not disarm or label the task trivial. A planning run stays
recoverable until a valid packet is captured or the user explicitly ends it.

## Native spawn path

1. If the helper reports an unsupported route, do not spawn. The durable
   checkpoint remains ready for diagnosis or recovery.
2. When routing is supported, call `spawn_agent` exactly once with the exact
   text between `PREWALK_MESSAGE_BEGIN` and `PREWALK_MESSAGE_END` as `message`
   and the configured executor `model`. Include `reasoning_effort` only when
   the helper prints it. Follow the printed spawn profile exactly:
   - `task_name`: pass `PREWALK_TASK_NAME` as `task_name` and
     `PREWALK_FORK_TURNS` as `fork_turns`.
   - `fork_context`: pass `PREWALK_FORK_CONTEXT` as the boolean
     `fork_context`; do not invent `task_name` or `fork_turns` fields.
   Do not use a named plugin agent and do not alter the message.
3. Wait for the bound executor. Codex hooks bind the agent ID returned by this
   exact tool call and consume only that agent's `SubagentStop` marker.
   On collaboration runtimes without these hooks, run the same helper with
   `observe <session_id>` after spawn and after the executor returns. It reads
   the runtime's own journals to verify the exact call, parent/child identity,
   actual model/effort and child terminal event. Never supply completion text
   or an agent ID yourself. An unresolved observation retains state; do not
   spawn again. This fallback observes launches after the fact; it cannot
   enforce pre-launch denial on a host that omits tool hooks.

Do not run manual confirm/complete commands. Spawn denial, failure, interruption,
missing markers, and incomplete markers remain durable for `pw-retry` recovery.
