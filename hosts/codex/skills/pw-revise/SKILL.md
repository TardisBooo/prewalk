---
name: pw-revise
description: Revise a durable Prewalk checkpoint in the active root session, re-verifying task 1 when needed.
---

# /pw-revise `<changes>` — revise the plan on the frontier

Run this to fetch the revision instructions for the current checkpoint:

```bash
python3 hooks/_pw.py revise "${CODEX_THREAD_ID:-${CODEX_SESSION_ID:-}}" "$ARGUMENTS"
```

Then follow its output:

- **Re-explore only what the revision affects** — do not redo the whole
  exploration.
- **Update the todo list** (`update_plan` / `todo`) to reflect the requested
  changes (each item still needs a concrete file path + a verification word).
- **Re-verify task #1** only if the revision changed it.
- Keep only real work in the plan and **STOP** again with an updated structured
  Handoff Packet.

You stay on the frontier (planner) model. When the revised plan is ready, the
user runs `/pw-go` to hand off. If the script says there is no active
checkpoint, reply with a single line saying so and end your turn.
