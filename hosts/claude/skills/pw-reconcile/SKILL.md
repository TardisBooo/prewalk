---
name: pw-reconcile
description: "Reconcile an ambiguous Prewalk executor only after proving it is no longer running."
---

# Prewalk Reconcile

Inspect the matching Claude Agent lifecycle first. Never stop or terminate an
agent as part of this skill. If it is still running or liveness is unknown,
report that and stop.

Only after Claude Code proves the persisted agent is absent/stopped, or the
user explicitly confirms it was interrupted, run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/_pw.py" reconcile "$CLAUDE_SESSION_ID" \
  --confirmed-not-running "<evidence or user confirmation>"
```

Without that proof, omit `--confirmed-not-running`; the helper must leave state
unchanged. Reconciliation retains task 1 and the packet, then directs the user
to `/prewalk:pw-retry`.
