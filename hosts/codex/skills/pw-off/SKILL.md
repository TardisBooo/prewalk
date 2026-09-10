---
name: pw-off
description: Disarm Prewalk for the current Codex session without changing files or todos.
---

# Prewalk Off

Run:

```bash
python3 hooks/_arm.py disarm "${CODEX_THREAD_ID:-${CODEX_SESSION_ID:-}}"
```

Report the result and do not alter the task or workspace.
