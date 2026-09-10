---
name: pw-retry
description: Retry one proven-incomplete Prewalk route from its durable packet without repeating task 1.
---

# Prewalk Retry

Inspect the live `spawn_agent` schema exactly as for `$prewalk:pw-go`, then run:

```bash
python3 hooks/_pw.py retry "${CODEX_THREAD_ID:-${CODEX_SESSION_ID:-}}" \
  --schema-fields=task_name,message,fork_turns,model,reasoning_effort
```

Omit schema fields that are absent. If the helper emits a route, make exactly
the native `spawn_agent` call it specifies. Do not change the message, inherit
prior turns, use a named agent, restart planning, or repeat task 1.

If an executor may still be running, do not spawn. Report the helper's
`pw-reconcile` direction instead.
