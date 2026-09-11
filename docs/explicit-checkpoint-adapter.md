# Explicit checkpoint adapter

Live acceptance and registration results are in
[codex-acceptance-20260911.md](codex-acceptance-20260911.md).

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

Codex now accepts one remaining task. Successful todo/view events persist
`plan_seen`; the first subsequent successful workspace mutation persists
`fast_gate_open` and emits the handoff-preparation nudge once. Failed todo calls,
read-only device calls and manual mode cannot open that gate. Fast without host
events is driven by the skill's explicit packet submission. The verified-task-one
and structured-packet rules remain intentional safety requirements for fresh child
context; this is not oh-my-pi's native same-session model setter.

Stop receipt/capture diagnostics go to plugin-local `events.jsonl`, without prompt
contents. Explicit recovery lists exact-session final packet ordinals read-only,
then captures only a selected ordinal. Both Codex `phase: final_answer` and
`channel: final` formats are supported. Global legacy state and journals remain
unchanged; recovery writes the correctly bound project-local checkpoint.

Registration was repaired with plugin management commands after user approval.
The invalid atom-agent-lab registration was removed and recorded in
`D:/Catalog/SessionMaps/prewalk-plugin-registration-20260911.md`. Prewalk is bound
to this canonical local repository and installed through `codex plugin add`.

## Checks (no models or benchmarks)

Run from the repository with `python -m unittest discover -s tests -p <file>`:

- `test_explicit_checkpoint.py`: manual/fast no-Stop transactions, script executed
  from plugin cwd, journal workspace binding, project-local storage, idempotent
  receipt, conflicting packet rejection, incomplete task-one rejection, route minting.
- `test_checkpoint_process_flow.py`: legacy Stop correction and route workflow.
- `test_hook_adapters.py`, `test_arm_args.py`, `test_v4_checkpoint.py`,
  `test_v4_codex_route.py`, `test_codex_journal_observer.py`: affected regressions.

Process tests simulate host payloads/metadata and are distinct from real model
acceptance. Both manual and fast CLI scenarios have now been run with normal
workspace-write and no hook-trust bypass. See the acceptance report for native
session identities, the failed Git-commit fixture, successful corrected fixture,
and independent model/content/terminal checks. No benchmark or business research
was rerun.
