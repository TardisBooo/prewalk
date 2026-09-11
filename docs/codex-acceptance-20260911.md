# Codex Prewalk acceptance — 2026-09-11

## Outcome

Manual plan → review → separate go and automatic `--fast` both passed real local
Codex CLI acceptance. These are not mocked model executions. Every successful
scenario ran under `workspace-write`, without `--dangerously-bypass-hook-trust`,
without sandbox bypass and without model/configuration overrides. Native root
code, provider configuration, project trust and historical journals were not edited.

The installed final plugin is `1.0.9+codex.20260911080835`, installed through the
normal plugin CLI from `E:/Workspaces/prewalk/repos/prewalk`. The earlier manual
case used `1.0.9+codex.20260911074321`; subsequent changes added recovery and
deterministic-failure retry guards. Those changes received dedicated process tests.
The first successful fast case used 075603. Subsequent fixes explicitly own UTF-8
inside the plugin, standardize helper paths, and make revisions return to review.
The default-environment Chinese cases below exercise the final installed version.

## Final default-environment Chinese acceptance

Both cases below used the final installed 080835 version, Chinese packet bodies,
normal workspace-write and no PYTHONIOENCODING/PYTHONUTF8 environment assistance.

| Scenario | Root session | Luna/max child | Result |
| --- | --- | --- | --- |
| Chinese manual | `01a08f82-ec5a-7bf1-bc23-883c56a708c2` | `01a08f85-b0f5-70e1-baa0-671e7a5a8a70` | Passed |
| Chinese fast | `01a08f83-da61-7580-a507-b402304f662c` | `01a08f85-b8f7-7e01-8f29-8e82e5ad77de` | Passed |

Manual stopped at the durable review receipt; independent checks confirmed no
two.txt or three.txt before the separate go prompt. Both runs then had exactly
one native Luna/max child, verified two/three contents, PREWALK_COMPLETE and
no remaining active state. The read-only evidence inspector passed both cases.

Final fixtures originated under
`E:/Workspaces/_verification/test/prewalk-utf8-20260911/{manual,fast}`.
Archives are at `D:/AcceptedArtifacts/prewalk/utf8-acceptance-20260911/`:
manual 41 files / 58,953 bytes; fast 38 files / 52,348 bytes. Source/archive file
counts and byte totals match. Neither fixture contains unique source inputs.
These E copies are retained pending cleanup approval. The separate `old-adapter`
linked worktree is retained for review and regenerates from Git commit `23d8e0a`;
it is not a new canonical project or the sole copy of any source.

Installed Python adapter/engine files were also compared with the canonical
source and matched. Final installed status displays the recovered Chinese todos
correctly. Doctor passes Python, CLI, presets, hooks, project state access and
the live model-routing schema/catalog checks.

## Preliminary real evidence (encoding environment set)

These initial runs used a harness that set `PYTHONIOENCODING=utf-8`. This masked a
Windows-default encoding defect and is not evidence of default-locale acceptance.
The harness was corrected to remove both PYTHONIOENCODING and PYTHONUTF8 from its
child environment; new Chinese manual and fast cases are the final acceptance.

| Scenario | Root session | Luna/max child | Result |
| --- | --- | --- | --- |
| Manual | `01a08f6d-3d5b-7b82-ab3d-ed3ea30239dd` | `01a08f70-a507-75e1-a84b-ae9b6a336475` | Passed |
| Final fast | `01a08f77-739b-78c3-bb77-aa142d3bad9f` | `01a08f79-213e-7a30-9610-0a96d9c66b31` | Passed |

Manual first returned `checkpoint_ready`, `next=await_user_review`, route attempt
zero and no child. Independent checks showed neither two.txt nor three.txt existed.
Only after a separate `codex exec ... resume <root-id> '$prewalk:pw-go'` did the
child execute. Both files then passed exact content checks.

Final fast completed the README write/read-back, submitted its packet, received
`next=pw-go`, and launched one child without a second user prompt. The child
created/read two.txt and three.txt. The observer consumed PREWALK_COMPLETE and
closed the active state. Independent inspection verified native child model and
effort contexts, terminal marker, one child per successful run, output contents,
workspace-write root contexts and no remaining active state.

Native journals remain under
`D:/SOFTWARE_DATA/Codex/Home/sessions/2026/09/11/`. Test fixtures originated under
`E:/Workspaces/_verification/test/prewalk-acceptance-20260911/`.
Accepted evidence (including fixture Git histories and CLI logs) is preserved at
`D:/AcceptedArtifacts/prewalk/acceptance-20260911/`: 117 files, 170,372 bytes at
archive creation, with matching source/destination counts and bytes. The E copy
is a deletion candidate pending approval of that exact inventory; original test
research and recovered checkpoint are not in that candidate.

## Failure retained, not hidden

The first fast fixture, root `01a08f70-834b-7f20-8adb-62fc87768a70`, created and
verified both outputs but its planner added a Git commit requirement. The normal
sandbox denied `.git/index.lock`; both attempts correctly ended incomplete rather
than clearing state. This case is not counted as successful final acceptance.

It also exposed blind retry of the same permission blocker. The helper now
rejects permission/configuration retries unless an explicitly verified prerequisite
change is acknowledged; skills prohibit relaunching into unchanged blockers.
The final fixture explicitly assigned Git/log administration to the outer harness,
without weakening sandbox permissions or removing any requested file task.

## Actual old failed session recovered

Session `01a08f25-1f03-77b0-9ba2-e0a4414c877a` had one valid final plan at ordinal
116. Recovery initially revealed its native `phase: final_answer` format, then
the adapter was corrected and tested against that shape. Explicit recovery wrote
`E:/Workspaces/_verification/test/.prewalk/state.json`, phase checkpoint_ready,
bound to the real test workspace. Packet SHA-256:
`d8c131c715502dd92575443cba50ba3e9403b2411b201abfbba93630f5530b34`.

Before/after hashes confirmed the global source state and original journal were
unchanged. The original task-one research file still has SHA-256
`69A81384DB106D1FDED95E195FD0C8B58F457FE20A72E853747845665CF00148`.
No research or old business task was rerun; that checkpoint awaits user review/go.
The earlier Git-check attempt remains legitimately unready because its first task
failed. USStockDeck was not resumed or mutated.

## Registration

With explicit user authorization, plugin CLI removal of the invalid
`atom-agent-lab` source unblocked marketplace listing. Migration catalogues have
no verified replacement for that missing child directory; no fake manifest or
empty replacement was created. Removal affects registration, not source files.
The old registration and restoration instructions are recorded in
`D:/Catalog/SessionMaps/prewalk-plugin-registration-20260911.md`.

Prewalk's marketplace source was changed from Git to the canonical local repo
through `codex plugin marketplace remove/add`, then installed with `plugin add`.
Marketplace listing, plugin manifest and skill validation pass. No manual edits
to Codex config, no trust bypass and no native code patch were used.

## Targeted checks, not benchmarks

89 tests passed across these unittest discovery patterns:

| Pattern | Tests |
| --- | ---: |
| test_v4_state.py | 8 |
| test_v4_operations.py | 6 |
| test_hook_adapters.py | 15 |
| test_arm_args.py | 11 |
| test_v4_claude_route.py | 6 |
| test_v4_checkpoint.py | 10 |
| test_codex_fast_recovery.py | 6 |
| test_explicit_checkpoint.py | 3 |
| test_checkpoint_process_flow.py | 1 |
| test_v4_codex_route.py | 10 |
| test_codex_journal_observer.py | 11 |
| test_contracts.py | 2 |

Command form: `python -m unittest discover -s tests -p <pattern>`.
Also passed `python scripts/sync_engine.py --check`, plugin/skill validators and
`git diff --check`. Old operations fixtures were corrected to simulate an actual
failed launch and the required fresh-context route instead of expecting a valid
spawn to fail. Version contracts now distinguish Codex's supported cachebuster
suffix from the shared release version.

## Reproduction

Use a new Codex thread after plugin installation. In a prepared temporary Git
fixture, ask for the three tasks: root verifies README/worktree, Luna writes and
reads two.txt, Luna writes and reads three.txt. Assign fixture Git administration
to the test harness, not the agent.

1. `$prewalk:prewalk --preset gpt-5.6-luna <three-task request>`.
2. Require a checkpoint receipt with `await_user_review`; confirm no executor files.
3. Send `$prewalk:pw-go` separately; require actual child completion and closed state.
4. In a fresh fixture, use `--fast` and a verified README write for task one;
   require automatic go and the same terminal checks.

Opt-in automation is in `scripts/accept_codex_checkpoint.py`; independent native
evidence checks are in `scripts/inspect_codex_acceptance.py`. These scripts are
not run by the unit-test suite and do spend model tokens when explicitly invoked.

## Compatibility boundary

The adapter borrows oh-my-pi's successful-plan/write gate, one-shot trigger and
persistence-before-handoff ordering. Codex still uses a fresh configured-model
child; it cannot change the root model through a plugin-only interface. Therefore
the root UI may continue to display Astra while Luna performs the executor work.
The adapter additionally requires a verified first task and durable structured
packet to supply the fresh child context. Do not describe this as an identical
native same-session switch.

## Reproduced Windows root cause

This host reports Python stdin/stdout encoding `gbk`, with PYTHONIOENCODING and
PYTHONUTF8 unset. The read-only native command runner inspection shows it sends
`input_json.as_bytes()` to hook stdin and interprets output as UTF-8. The old
plugin read `sys.stdin` with the platform default. Chinese UTF-8 became damaged
text containing surrogate characters. Checkpoint event hashing then failed at
`encoded.encode("utf-8")`, before the planning → checkpoint transition and before
recording a checkpoint rejection. This explains why mutation counts could change
while phase remained planning and last_error stayed empty.

`scripts/replay_hook_wire.py` fed the actual ordinal-116 packet through the old
adapter at Git commit `23d8e0a` and the new adapter, using isolated state and no
encoding environment variables. Full Stop results:

| Adapter | Exit | State | Error |
| --- | ---: | --- | --- |
| Old | 1 | planning | UnicodeEncodeError: surrogate U+DC80 cannot encode as UTF-8 |
| New | 0 | checkpoint_ready | none |

New input SHA-256 exactly matches the original packet hash documented above.
The original global state and native journal were not modified by this replay.
The plugin now explicitly configures stdin/stdout/stderr as UTF-8; no global
environment or Codex configuration change is needed. A regression also forces a
GBK child environment and sends Chinese/emoji UTF-8 bytes, requiring exact packet
preservation and a ready checkpoint.

Historical Hook stderr was not retained, so this is a deterministic reproduction
of the original payload on the original adapter/current local default, not a
claim that every historical failure had the same cause. Wrong workspace binding,
global lock permissions and Stop-only commit coupling were independent defects.
