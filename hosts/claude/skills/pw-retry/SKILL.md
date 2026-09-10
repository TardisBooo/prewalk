---
name: pw-retry
description: "Retry one proven-incomplete Prewalk route from its durable packet without repeating task 1."
---

# Prewalk Retry

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/_pw.py" retry "$CLAUDE_SESSION_ID"
```

If the helper emits a token-bound route, spawn exactly one `Task`/`Agent` using
the complete text between its message markers. The hook installs the persisted
packet, scoped executor type, and configured model. Do not restart planning or
repeat task 1.

If an executor may still be running, do not spawn. Report the helper's
`/prewalk:pw-reconcile` direction instead.
