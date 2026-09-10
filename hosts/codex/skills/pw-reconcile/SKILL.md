---
name: pw-reconcile
description: Reconcile an ambiguous Prewalk executor only after proving it is no longer running.
---

# Prewalk Reconcile

Inspect the native agent lifecycle first. Never interrupt or terminate an agent
as part of this skill. If the bound agent is still running or liveness is
unknown, report that and stop.

Only after the native runtime proves the persisted agent is absent/stopped, or
the user explicitly confirms it was interrupted, run:

```bash
python3 hooks/_pw.py reconcile "${CODEX_THREAD_ID:-${CODEX_SESSION_ID:-}}" \
  --confirmed-not-running "<evidence or user confirmation>"
```

Without that proof, run the helper without `--confirmed-not-running`; it must
leave state unchanged. Reconciliation retains task 1 and the packet, then
directs the user to `$prewalk:pw-retry`.
