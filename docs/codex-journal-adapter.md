# Plugin-only collaboration journal adapter

This supersedes the runtime-change recommendation in the September 11
checkpoint investigation. No Codex native code, configuration or journal is
modified. The only writes are plugin source/cache and Prewalk's own state.

## Why this route

The reference implementation at
https://github.com/TerenceLiu98/prewalk/blob/main/codex/hooks/executor_router.py
also depends on spawn tool hooks and SubagentStop, and recognizes agent/thread
IDs rather than the collaboration surface's canonical task-name return value.
Copying that adapter does not solve absent lifecycle events.

Our collaboration runtime does persist a usable evidence chain in its own
journals. `_pw.py observe <root-session>` verifies all of the following:

1. Exactly one journal with the exact armed root session ID.
2. Exactly one collaboration spawn naming this route's unique task name,
   no earlier than the route request, with the required model/effort and fresh
   context. Duplicate launches are ambiguous, never silently selected.
3. The matching call's own result returns that canonical task path.
4. Exactly one child session records that root as parent and that task path,
   with matching workspace and a non-stale creation timestamp.
5. Child turn contexts independently confirm the actual model and effort.
6. Only the child's terminal event supplies COMPLETE/INCOMPLETE, never a
   statement from the parent or arguments provided to the observer command.
   A newer active child turn prevents an old completion from being consumed.

After binding the real child UUID, the existing state machine handles its
terminal marker. Under the existing contract, successful completion clears
the active run; an invalid or incomplete marker retains an incomplete run.
Rechecking completed state is harmless. Missing/ambiguous/mismatched evidence
retains the route and instructs the caller not to spawn again.

The root Stop hook performs observation for pending routes. The pw-go skill
also requests it after launch and after waiting. Repeated `go` on an already
pending route observes it rather than printing another spawn request.

## Deliberate limits

- This is **post-launch evidence**, not pre-launch enforcement. A runtime that
  omits pre-tool hooks cannot offer a plugin a denial point for that tool.
- Plaintext spawn packets must equal the durable route. Some journals contain
  encrypted `gAAAAA...` message bodies; those are not decrypted and their
  exact packet equality is **not** claimed. The identity/model/effort/result
  evidence chain is still required in full.
- Only the observed `collaboration.spawn_agent` task-name/fork-turns journal
  shape is supported by this fallback. Native hook-backed routes remain
  available; unsupported journal shapes fail closed.
- Ephemeral sessions, deleted journals, partial writes and missing turn
  contexts cannot prove completion. Keep the checkpoint and retry observation
  after the evidence becomes available; do not relaunch blindly.
- Journal parsing reads local runtime metadata; it does not reconstruct or
  replace the durable handoff packet from historical conversation text.

## Verification

`python -m unittest discover -s tests -p test_codex_journal_observer.py` covers
11 cases: completion/idempotence/read-only journals, wrong model, wrong effort,
duplicate launch, duplicate child, wrong parent, root-only completion, missing
marker, newer active turn, altered plaintext packet and partial journal.

The previous actual Luna run (root `01a08e97-04db-7be0-a65e-8ba2eb9c4927`, child
`01a08e99-adc0-7862-9763-ac10fb808e3d`) was successfully closed by the observer
using its runtime evidence. No completion text was supplied to the helper.

### Fresh installed-plugin acceptance

Root `01a08ee3-bc05-7661-8beb-fc108f03f529`, child
`01a08ee5-168f-70c1-8b3a-ea5bc2fca843`, Codex 0.154.0:

- Used the installed 1.0.9 plugin cache with the local adapter hotfix. No
  `PREWALK_ENGINE` override, no Codex configuration overrides or source edits.
- An isolated `observer-live-state.json` kept production state out of scope.
- `--fast` Stop captured the three-task packet and automatically continued
  into pw-go. Root verified only the README task.
- The observer independently confirmed the spawned Luna/max child and moved
  the route into `executor_running` while the child was still working.
- Child completed `observer-two.txt` and `observer-three.txt`; independent
  exact text checks returned true for `two` and `three` respectively.
- Child returned `PREWALK_COMPLETE`. Final active state was `{}` and a repeated
  observe reported no pending route. No manual confirm/complete or hook replay.
- The live CLI exited successfully. No benchmark or USStockDeck work ran.

Targeted checks passed: 11 journal observer + 10 checkpoint + 10 Codex route +
15 hook adapter + 1 subprocess flow tests (47 total), static contracts, engine
copy consistency and `git diff --check`.

Local hotfix changes only plugin files, not installation registration or Codex
configuration. The installed cache directory/version label remains 1.0.9;
the code change is tracked by its Git commit, not a claimed version upgrade.

Cleanup inventory: `E:/Workspaces/_verification/prewalk-checkpoint-20260911`,
29 files / 29,870 bytes at acceptance. Producer: this test and Git initialization;
consumer: local review only; regeneration: repeat the three-task fixture above
with an isolated PREWALK_STATE_FILE. Retained as a cleanup candidate awaiting
approval; no Codex session journals are included in the deletion candidate.
