# Prewalk for Claude Code

This plugin uses a strong Claude model to explore, plan, and complete the first
verified task, then routes one fresh Task to a configured executor.

See the repository [README](../../README.md) for the user workflow and preset
schema. This document covers the Claude-specific adapter.

## Install

Python 3.10+ and Claude Code 2.1.145+ are required.

```sh
claude plugin marketplace add TardisBooo/prewalk
claude plugin install prewalk@prewalk
```

Restart Claude Code. `~/.claude/prewalk-presets.json` is optional; copy
`presets.example.json` there only when you need custom model routes.

## Use

```text
/prewalk:prewalk <task>
/prewalk:pw-go
```

Use `/prewalk:pw-revise <changes>` instead of `/prewalk:pw-go` to change the
plan. Operational skills are `/prewalk:pw-status`, `/prewalk:pw-off`,
`/prewalk:pw-doctor`, `/prewalk:pw-retry`, and `/prewalk:pw-reconcile`.
`/prewalk:pw-resume` is compatibility guidance only. `--fast` on
`/prewalk:prewalk` automatically requests the handoff at the validated Stop checkpoint.

## Two-phase route

Claude hooks cannot change the main session model. Prewalk therefore uses:

```text
/prewalk:pw-go
  -> state = handoff_requested
Task PreToolUse
  -> require one-time token and persist tool_use_id
  -> updatedInput.model = executor
  -> updatedInput.subagent_type = prewalk:prewalk-executor
SubagentStart (`prewalk-executor`, or plugin-scoped equivalent)
  -> bind matching agent_id and enter executor
Task PostToolUse
  -> acknowledge only the matching launch
SubagentStop
  -> bound agent + PREWALK_COMPLETE: clear state
  -> bound agent + PREWALK_INCOMPLETE: retain durable checkpoint
  -> bound agent + missing marker: retain durable checkpoint
Task failure/rejection
  -> matching tool_use_id retains durable checkpoint
```

Unrelated, nested, and concurrent Agent events cannot advance the route. The
executor receives a structured packet rather than the planner's raw context.

## Hooks

`hooks/hooks.json` registers:

- `SessionStart`: expose the session id to skill subprocesses.
- `PostToolUse` todo tools: persist complete real-work snapshots.
- `PostToolUse` edit/Bash/RepoPrompt tools: never advance checkpoint state.
- `PreToolUse` Task/Agent: route only the token-bearing handoff.
- `SubagentStart`/`SubagentStop`: bind the executor and consume its final marker.
- `PostToolUse` Task/Agent: acknowledge the matching launch only.
- `PostToolUseFailure` and `PermissionDenied` Task/Agent: restore failed routes.
- Root `Stop`: validate todos and persist the exact assistant packet.

The mutation adapter rejects failed/no-op responses and ignores `apply_patch`
text inside shell quotes or comments.

## State

State lives in `~/.claude/prewalk-state.json`, or under `CLAUDE_CONFIG_DIR`.
The plugin uses locked atomic writes and quarantines malformed JSON with a
`.corrupt` suffix.

## Update

```sh
claude plugin marketplace update prewalk
claude plugin update prewalk@prewalk
```

Restart Claude Code after updating.
