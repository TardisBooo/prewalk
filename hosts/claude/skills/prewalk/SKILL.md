---
name: prewalk
description: "Arm a prewalk run: explore and plan in the root session, land the first verified edit, then persist a Stop checkpoint for handoff."
---

# Prewalk

Arm the current session:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/_arm.py" arm "$CLAUDE_SESSION_ID" "$ARGUMENTS"
```

Do not continue until the helper prints `prewalk ARMED`. If the state store is
not writable, grant write access or set one absolute `PREWALK_STATE_FILE` path
that is inherited by Claude Code and every plugin hook, then rerun the arm.

Options must precede task text: `--preset <name>` selects a preset and
`--fast` enables automatic handoff after validation (`--no-pause` is a legacy
alias). The active root session is the planner; Prewalk never changes it.

If the task is clearly one or two small edits, finish it directly. Otherwise:

1. Explore the relevant entry points, configuration, tests, and existing patterns.
2. Create at most the configured number of todos. Every real todo names concrete
   files or behavior and includes a test/build/verify/check criterion.
3. Complete and verify only real task #1.
4. Update the todo snapshot so task #1 is `completed`; keep only real work in it.
5. Stop with this exact structured packet. Do not start task #2.

```text
Goal:
Files Read:
Constraints And Existing Patterns:
Full Todo List:
1. [x] `<task 1 path/action>; verify: <completed command or check>`
2. [ ] `<task 2 path/action>; verify: <command or check>`
3. [ ] `<task 3 path/action>; verify: <command or check>`
Task 1 Changes:
Verification Already Run:
Remaining Work:
Risks / Do Not Repeat:
```

Keep the checklist in this exact Markdown checkbox form so the Stop hook can
recover a validated todo snapshot if the host does not provide one.

Do not claim that handoff occurred. `/prewalk:pw-go` requests it; the bound
executor's `SubagentStop` hook confirms its final result.
