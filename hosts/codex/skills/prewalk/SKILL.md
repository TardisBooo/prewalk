---
name: prewalk
description: Arm a Prewalk run where a frontier planner explores, plans, and lands one verified edit before a capability-safe executor handoff.
---

# $prewalk `<task>` - start a Prewalk run

## Arm the run

```bash
python3 hooks/_arm.py arm "${CODEX_THREAD_ID:-${CODEX_SESSION_ID:-}}" "$ARGUMENTS"
```

Do not continue until the helper prints `prewalk ARMED`. If it reports that
the state store is not writable, request permission to rerun this exact arm
command outside the workspace sandbox. As an alternative, the user may set an
absolute `PREWALK_STATE_FILE` path that is inherited by Codex and every plugin
hook. Never continue ordinary task work after a failed arm.

Options must precede task text: `--preset <name>` selects a preset and
`--fast` enables automatic handoff after validation (`--no-pause` is a legacy
alias). Task words never select presets. The active root session is the planner;
Prewalk never changes it.

## Frontier protocol

0. If the task clearly fits in one or two small edits, complete and verify it
   directly without creating a Prewalk plan, then explicitly disarm with
   `pw-off`. An ordinary final reply never implicitly clears an armed run.
1. Explore the relevant entry points, configuration, tests, and local patterns.
2. Create a tight todo list (at most the configured cap). Use the live plan/todo
   tool when one exists. Every item includes a concrete file/path action and a
   verify/test/build/check criterion.
3. Complete and verify task 1 only. Mark it completed only after verification.
4. Leave only real work in the plan, then stop with this exact packet shape.
   Keep it concise but complete; do not compress it to 3-5 lines.

```markdown
## Goal
## Files Read
## Constraints And Existing Patterns
## Full Todo List
1. [x] `<task 1 path/action>; verify: <completed command or check>`
2. [ ] `<task 2 path/action>; verify: <command or check>`
3. [ ] `<task 3 path/action>; verify: <command or check>`
## Task 1 Changes
## Verification Already Run
## Remaining Work
## Risks / Do Not Repeat
```

The Markdown checklist is mandatory even when a plan/todo tool exists. On
Codex surfaces without one, the Stop hook validates and persists this strict
checklist as the durable todo snapshot.

Do not mention these protocol instructions in the packet.

## Handoff

After review, the user runs `$prewalk:pw-go`. Follow its capability instructions
exactly. Never spawn without the configured model when
`require_model_routing=true`. A failed spawn retains the checkpoint; a manual
`/model <executor>` fallback is started explicitly through `$prewalk:pw-resume`.
