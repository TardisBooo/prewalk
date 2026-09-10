---
name: pw-doctor
description: "Diagnose the Prewalk installation, presets, hook manifest, state directory, and Claude Task routing setup."
---

# Prewalk Doctor

Run and report every PASS, WARN, and FAIL line:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/_arm.py" doctor "$CLAUDE_SESSION_ID"
```
