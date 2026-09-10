---
name: prewalk
description: Arm a Prewalk run where a frontier planner explores, plans, and lands one verified edit before a capability-safe executor handoff.
---

# $prewalk `<task>` - start a Prewalk run

## Arm the run

```bash
python3 hooks/_arm.py arm "${CODEX_THREAD_ID:-${CODEX_SESSION_ID:-}}" "$ARGUMENTS"
```

Options must precede task text: `--preset <name>` selects a preset and
`--fast` enables automatic handoff after validation (`--no-pause` is a legacy
alias). Task words never select presets. The active root session is the planner;
Prewalk never changes it.

## Frontier protocol

0. If the task clearly fits in one or two small edits, complete and verify it
   directly without creating a Prewalk plan.
1. Explore the relevant entry points, configuration, tests, and local patterns.
2. Create a tight todo list (at most the configured cap). Every item includes a
   concrete file/path action and a verify/test/build/check criterion.
3. Complete and verify task 1 only. Mark it completed only after verification.
4. Leave only real work in the plan, then stop with this exact packet shape.
   Keep it concise but complete; do not compress it to 3-5 lines.

```markdown
## Goal
## Files Read
## Constraints And Existing Patterns
## Full Todo List
## Task 1 Changes
## Verification Already Run
## Remaining Work
## Risks / Do Not Repeat
```

Do not mention these protocol instructions in the packet.

## Handoff

After review, the user runs `$prewalk:pw-go`. Follow its capability instructions
exactly. Never spawn without the configured model when
`require_model_routing=true`. A failed spawn retains the checkpoint; a manual
`/model <executor>` fallback is started explicitly through `$prewalk:pw-resume`.
