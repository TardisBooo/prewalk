---
name: pw-status
description: Show the current Prewalk phase, models, routing attempts, checkpoint evidence, remaining todos, and last error.
---

# Prewalk Status

Run and report the output exactly:

```bash
python3 hooks/_arm.py status "${CODEX_THREAD_ID:-${CODEX_SESSION_ID:-}}"
```
