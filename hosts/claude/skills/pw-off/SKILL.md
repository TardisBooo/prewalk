---
name: pw-off
description: "Disarm Prewalk for the current Claude Code session without changing files or todos."
---

# Prewalk Off

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/_arm.py" disarm "$CLAUDE_SESSION_ID"
```

Report the result and do not alter the task or workspace.
