---
name: pw-resume
description: "Compatibility guidance for older Claude Prewalk recovery; canonical v4 recovery uses pw-reconcile."
---

# Prewalk Resume

This compatibility skill never confirms or completes a native route. Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/_pw.py" resume "$CLAUDE_SESSION_ID"
```

Follow the helper's canonical `/prewalk:pw-status` or
`/prewalk:pw-reconcile` direction. Only the bound SubagentStop marker can
complete a native Claude route.
