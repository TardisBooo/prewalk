# Migrating from Prewalk 0.3.x to 1.0.0

## Upgrading from 1.0.8 to 1.0.9

Prewalk 1.0.9 only changes newly minted Codex task names; existing incomplete
routes remain retryable and require no state migration.

## Upgrading from 1.0.7 to 1.0.8

Prewalk 1.0.8 maps model-pinned routes to fresh-context spawns on both Codex
schema variants. No checkpoint migration is required; the durable packet
already contains the executor context.

## Upgrading from 1.0.6 to 1.0.7

Prewalk 1.0.7 maps current Codex model-pinned routes to
`fork_context=false`; the durable packet supplies the executor context.

## Upgrading from 1.0.5 to 1.0.6

Prewalk 1.0.6 uses Codex's `${PLUGIN_ROOT}` hook placeholder. Reinstall the
plugin so the host resolves absolute adapter paths before invoking `cmd.exe`.

## Upgrading from 1.0.4 to 1.0.5

Prewalk 1.0.5 replaces PowerShell-only `commandWindows` entries with native
`cmd.exe` commands. Reinstall the plugin so Codex loads the corrected hook
manifest.

## Upgrading from 1.0.3 to 1.0.4

Prewalk 1.0.4 moves the Codex hook manifest to the runtime-discovered
`hooks/hooks.json` path. Restart Codex after updating. Checkpoints remain
compatible.

## Upgrading from 1.0.2 to 1.0.3

Prewalk 1.0.3 supports Codex runtimes that expose `fork_context` instead of
`task_name` and `fork_turns`. Existing v4 checkpoints remain compatible.
Restart Codex after updating so the expanded versioned tool-name hook matcher
is active.

## Upgrading from 1.0.1 to 1.0.2

Prewalk 1.0.2 adds the missing native Windows hook commands. Windows users must
restart Codex after updating so resumed and new threads load the repaired Stop
and executor lifecycle hooks. The v4 state schema is unchanged.

## Upgrading from 1.0.0 to 1.0.1

Prewalk 1.0.1 keeps the v4 state schema unchanged. Restart the host after
updating. Existing valid 1.0.0 checkpoints remain readable. If the host sandbox
cannot write under `CODEX_HOME` or `CLAUDE_CONFIG_DIR`, grant that state path
write access or set `PREWALK_STATE_FILE` to an absolute writable file before
starting the host.

Prewalk 1.0.0 replaces the simulated model-switch workflow with host-native
executor orchestration. Upgrade the plugin, restart the host, and begin a new
Prewalk run. Do not reuse an in-flight 0.3.x handoff.

## Upgrade

Codex:

```sh
codex plugin marketplace upgrade prewalk-marketplace
codex plugin add prewalk@prewalk-marketplace
```

Claude Code:

```sh
claude plugin marketplace update prewalk
claude plugin update prewalk@prewalk
```

Use only the namespaced skills shown in the main README. The active root
session remains the planner for the entire planning phase; Prewalk does not
select, replace, or restore its model.

## Presets

Remove `planner` and `planner_thinking` from custom preset files. They are
accepted temporarily so `pw-doctor` can report a deprecation warning, but they
are ignored. Keep `executor`, `max_todos`, `handoff_mode`, and
`require_model_routing`.

Rename `executor_thinking` to `executor_effort`. Codex requests it only when the
live native `spawn_agent` schema exposes `reasoning_effort`. Claude Code does
not currently expose a supported per-subagent effort control, so Prewalk reports
the configured request as unsupported instead of claiming it was applied.

## Checkpoints and todos

Remove the synthetic `PAUSE` checkpoint todo from custom instructions. A v4
todo snapshot contains real work only. The planner completes and verifies task 1,
then its root `Stop` event persists the exact structured handoff packet. Zero or
one remaining real task stays in the root session; two or more may be routed to
one executor after review or through `--fast`.

On Codex the default route is `fork_turns: "all"`: the executor inherits the
planner's turn history and receives a short phase-2 note instead of a re-read
packet. Set `fork_turns: "none"` in a preset to keep the older fresh-context
packet handoff.

## State reset

The v4 durable state schema is intentionally incompatible with v3. On first
load, a v3 record for the current session is reset and Prewalk asks for a new
run; records belonging to other sessions are left untouched. The reset prevents
an old ambiguous handoff from being mistaken for a live native executor.

After upgrading, run the host-specific doctor before arming:

```text
$prewalk:pw-doctor
/prewalk:pw-doctor
```

If a v4 route later becomes `incomplete`, use the namespaced retry command. If
it becomes `stale`, first prove the recorded agent is no longer running, then
use the namespaced reconcile command. Disarming clears Prewalk state only; it
does not stop an executor.
