# Changelog

## 1.0.1

- Make the state-file location explicitly configurable with
  `PREWALK_STATE_FILE`, probe the real lock path in `pw-doctor`, and turn state
  permission failures into actionable arm errors instead of tracebacks.
- Resolve Windows npm command shims such as `codex.cmd` during capability
  checks, and reject unknown preset names instead of silently selecting the
  first preset.
- Accept quoted and bare dotted TOML preset names such as `grok-4.6`.
- Capture a strict checkbox todo snapshot from the Handoff Packet when the host
  has no native plan/todo tool, and recognize patches issued through Codex's
  current `tools.apply_patch` orchestration surface.

## 1.0.0

Initial release of the dual-host prewalk plugin: one host-agnostic engine
package, two native adapters.

- Keep the active Codex or Claude Code root session as the planner; presets
  configure only the executor model, effort request, and routing policy.
- Replace model-authored pause sentinels with a validated root `Stop`
  checkpoint containing real todos, verification evidence, and a durable
  handoff packet.
- Persist a workspace- and session-scoped v4 state machine with atomic writes,
  exact route tokens, executor identity binding, retry, reconcile, and stale
  detection that never terminates an unknown agent.
- Route Codex through native `spawn_agent` fields — defaulting to
  `fork_turns: "all"` so the executor inherits the planner's trajectory
  instead of re-reading a prose packet — and Claude Code through a token-bound
  Agent call plus native SubagentStart/SubagentStop lifecycle.
- Re-arm a rejected checkpoint in place (bounded retry) and nudge the planner
  back to planning after too many planning-phase mutations.
- Add `pw-retry` and `pw-reconcile`, expanded doctor/status diagnostics, and a
  Linux/macOS minimum/latest native CLI integration matrix.
- Vendor the engine into each host subtree (`scripts/sync_engine.py` keeps the
  copies byte-identical) so both plugin marketplaces install a self-contained
  plugin.
