---
name: pw-doctor
description: Diagnose the Prewalk installation, presets, hook manifest, state directory, and Codex model-routing capability.
---

# Prewalk Doctor

Inspect the live `spawn_agent` schema, then pass exactly the fields it exposes:

```bash
python3 hooks/_arm.py doctor "${CODEX_THREAD_ID:-${CODEX_SESSION_ID:-}}" \
  --schema-fields=<comma-separated live field names>
```

Omit absent fields and do not call the tool. A missing model argument means
spawn handoff cannot honor presets with
`require_model_routing=true`; recommend the manual model + `pw-resume` fallback.
Also report a missing or mismatched `CODEX_THREAD_ID`. Native session binding
requires Codex CLI 0.146.0 or newer; after upgrading, restart the Codex thread.
