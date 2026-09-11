# Explicit checkpoint adapter (development, not live acceptance)

## Why

The user's normal Codex manual workflow produced a valid final packet but no
durable checkpoint. A Stop-only commit path cannot distinguish missing delivery
from an early hook exit without additional evidence. Prior fast acceptance used
different permissions/trust conditions and does not prove the manual workflow.

The oh-my-pi comparison is pinned to commit
`3b3a6dc9bbd85102ce19d0b1c11bf6870915f6ec`, especially
`packages/coding-agent/src/session/prewalk.ts`. Its native coordinator observes
successful todo calls and subsequent edit/write results, waits for message
persistence, then switches the same session's model. Codex plugins have no
equivalent root-model setter. This adapter retains child routing; it must not
advertise identical same-session execution semantics.

## Implemented surface

- `_pw.py checkpoint <session-id> <absolute-project-packet>` validates an explicit
  checklist, persists it through the existing locked atomic store, reads it back,
  and emits a receipt with workspace, revision, packet hash and next action.
- Manual receipts say `await_user_review`; fast receipts say `pw-go`. Neither
  helper itself launches an agent. The skill performs the appropriate next action.
- Repeating the same submission is idempotent; different content cannot replace
  a ready checkpoint without revision. A wrong workspace cannot submit or go.
- New sessions use `<workspace>/.prewalk/state.json`, avoiding global state locks
  outside the normal workspace sandbox. Explicit state overrides remain supported.
  Existing session records in the global store remain in place, not silently
  migrated or re-armed. Their old permissions/workspace errors still require
  explicit recovery; this change does not claim to repair old runs automatically.
- Workspace identity comes from hook cwd or the exact session's metadata, with
  project cwd as fallback when no journal exists. Plugin-directory fallback is
  rejected rather than binding state to the plugin installation.
- Failed todo results are ignored. Fast mutation nudges require saved todos;
  read-only xd device operations do not qualify as writes.

## Boundaries and remaining work

This is the first independently testable adapter change, not a complete oh-my-pi
port. It retains the engine's verified-task-one and two-remaining-task rules.
Native todo `view` gate parity, a persisted one-shot fast gate, richer Stop
diagnostics, and explicit legacy recovery still need implementation/acceptance.
Fast without host events is driven by the skill's explicit packet submission.

Installation validation is currently blocked: `codex plugin list` fails because
the configured `atom-agent-lab` marketplace points to a legacy directory without
a supported manifest. No native Codex configuration was changed to bypass it.
The plugin update skill requires resolving marketplace provenance before reinstall.

## Checks (no models or benchmarks)

Run from the repository with `python -m unittest discover -s tests -p <file>`:

- `test_explicit_checkpoint.py`: manual/fast no-Stop transactions, script executed
  from plugin cwd, journal workspace binding, project-local storage, idempotent
  receipt, conflicting packet rejection, incomplete task-one rejection, route minting.
- `test_checkpoint_process_flow.py`: legacy Stop correction and route workflow.
- `test_hook_adapters.py`, `test_arm_args.py`, `test_v4_checkpoint.py`,
  `test_v4_codex_route.py`, `test_codex_journal_observer.py`: affected regressions.

Process tests simulate host payloads/metadata; they are not real model acceptance.
After installation is repaired, replay the user's three-task manual sequence and
its `--fast` variant in `E:/Workspaces/_verification`, normal workspace-write,
without bypassing hook trust. Require actual Luna child model/effort evidence,
exact output checks and terminal state. Do not rerun business research or benchmarks.
