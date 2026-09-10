---
name: pw-resume
description: Start the explicit manual-root fallback after switching the current Codex thread to the configured executor model.
---

# $prewalk:pw-resume - continue after a manual model switch

Run this only after `pw-go` requested the manual fallback and the user completed
`/model <executor>`:

```bash
python3 hooks/_pw.py resume "${CODEX_THREAD_ID:-${CODEX_SESSION_ID:-}}"
```

The helper reloads and prints the durable Handoff Packet. Continue the remaining
todos in the current thread, strictly in order; do not reconstruct context,
restart exploration, or repeat task 1. Verify every item before completing it.
Record the explicit manual fallback result with:

```bash
python3 hooks/_pw.py complete "${CODEX_THREAD_ID:-${CODEX_SESSION_ID:-}}"
python3 hooks/_pw.py incomplete "${CODEX_THREAD_ID:-${CODEX_SESSION_ID:-}}" "<reason>"
```

These commands reject native agent routes; native completion remains owned by
the bound agent's `SubagentStop` hook.
