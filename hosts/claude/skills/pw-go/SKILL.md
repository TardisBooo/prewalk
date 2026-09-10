---
name: pw-go
description: "Request the reviewed prewalk handoff and spawn exactly one routed Claude Task for the remaining todos."
---

# Prewalk Handoff

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/_pw.py" go "$CLAUDE_SESSION_ID"
```

If there is no active checkpoint, report that and stop. If a handoff is already
pending, do not spawn another Task.

For a new handoff request, spawn exactly one `Task`/`Agent` using the complete
structured Handoff Packet and the exact `PREWALK_HANDOFF_TOKEN` line printed by
the helper as its prompt. The PreToolUse hook rewrites only that call to the
configured `prewalk:prewalk-executor` and executor model. Do not edit remaining
work in the main session and do not report success before the executor stops.

Agent PostToolUse acknowledges launch only. The bound executor's SubagentStop
event owns the result:

- `PREWALK_COMPLETE` clears the run.
- `PREWALK_INCOMPLETE: <reason>` restores the checkpoint for revision or retry.
- rejection, failure, or a missing marker also restores a retryable checkpoint.
