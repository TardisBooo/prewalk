# Checkpoint preservation regression and native lifecycle investigation

## Scope and verified fix

An armed planning run used to be deleted when Stop received neither todos nor
a recognizable packet. A normal failed `pw-go` reply therefore became a
false `trivial` completion. Missing input now returns `awaiting_packet` and
retains the run. Explicit `pw-off` remains available for genuinely small work.
Checkpoint rejection reasons survive in `last_error`; Codex `pw-go` reports
them. Stop rejection diagnostics record the todo source, packet character
count and SHA-256, not the conversation text. Successful capture clears the
old error. A missing `V4StateError` import was also corrected.

No benchmark or USStockDeck implementation was run.

## Checks

- `python -m unittest discover -s tests -p test_v4_checkpoint.py`: 10 passed.
- `python -m unittest discover -s tests -p test_v4_codex_route.py`: 10 passed.
- `python -m unittest discover -s tests -p test_hook_adapters.py`: 15 passed.
- `python -m unittest discover -s tests -p test_checkpoint_process_flow.py`:
  1 passed; actual separate Stop/helper processes, malformed packet rejection,
  failed go, retained planning, corrected Chinese packet, then Luna route.
- `python scripts/check_contracts.py`: passed.
- `python scripts/sync_engine.py --check`: passed.
- `git diff --check`: passed.
- Additional native workflow matrix: 6 passed, 1 pre-existing failure:
  `scripts/check_native_clis.sh` still pins 1.0.7 while its test expects 1.0.9.
  No native installation/upgrade benchmark was run.

## Real Codex CLI experiment

Runtime: Codex 0.154.0, installed plugin 1.0.9, canonical patched core supplied
through `PREWALK_ENGINE` for this invocation only. Production plugin cache was
not replaced. `PREWALK_STATE_FILE` isolated all fixture state. Parent session
environment IDs were cleared before launch.

Fixture: `E:/Workspaces/_verification/prewalk-checkpoint-20260911`.
Session: `01a08e97-04db-7be0-a65e-8ba2eb9c4927`.

1. Root armed, checked README, emitted a three-item packet.
2. The real host Stop hook created `checkpoint_ready`, zero rejections.
3. Resumed root requested the exact Luna/max route, fresh context.
4. `collaboration.spawn_agent` returned
   `{"task_name":"/root/prewalk_executor_1_dz1am83u"}`.
5. Executor created `two.txt` and `three.txt`, returned `PREWALK_COMPLETE`.
   Both contents were independently read and matched the requested values.
6. Prewalk remained `handoff_requested`, with empty `route_tool_use_id` and
   `executor_agent_id`, `launch_acknowledged=false`. No corresponding spawn
   Pre/PostToolUse events were visible in the root CLI output. No manual
   binding or completion was used.

This passes real checkpoint capture and executor work, **not** the complete
Prewalk lifecycle. The current collaboration surface is not delivering the
events/identity envelope that the plugin expects. Its adapter also does not
recognize the returned canonical `task_name` as an identity. Adding that key
alone cannot fix absent lifecycle events.

The original USStockDeck rejection is not reproduced in this repaired host.
Both historical final packets pass the installed parser. Without the original
hook input, its first rejection cannot conclusively be attributed to any one
payload/encoding/snapshot issue. New diagnostics support future attribution.

## Remaining solution and acceptance gate

1. Expose a documented lifecycle bridge for the collaboration runtime:
   before-spawn input, after-spawn result and final subagent result. It must
   carry root identity and stable call/agent IDs and preserve denial semantics.
2. Extend the plugin adapter against that actual contract, including canonical
   task-name identities where documented. Never guess an agent from a model
   name or accept an arbitrary completion string from the root.
3. Verify model/effort and token at launch; bind only its returned identity;
   accept completion only from the bound executor. Missing bridge events must
   be reported as unsupported/unobserved, not success or an automatic retry.
4. Repeat one tiny live fixture through `completed`, plus denied spawn and
   interruption retention cases. Do not replay the benchmark.

Changing the Codex collaboration runtime is separate from this plugin fix.
Do not publish an acceptance claim or patch production state to hide that gap.

## Fixture disposition

Retained for review; cleanup candidate, not a promoted project. All source and
reproduction logic are in this repository. No session JSONL was changed or
deleted. Delete the fixture only after the user approves its cleanup inventory.
