<div align="center">

# prewalk

**Let the frontier model make the one edit that matters — then hand the verified start to a cheaper executor.**

_One engine · Two native hosts · Trajectory-inheritance handoff · Durable checkpoints · Fail-closed routing_

[![CI](https://github.com/TardisBooo/prewalk/actions/workflows/check.yml/badge.svg)](https://github.com/TardisBooo/prewalk/actions/workflows/check.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-32CD32.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Codex CLI](https://img.shields.io/badge/Codex%20CLI-0.146%2B-8A2BE2)
![Claude Code](https://img.shields.io/badge/Claude%20Code-2.1.145%2B-D97757)

**English** | [简体中文](README.zh-CN.md)

</div>

---

## 📋 Quick Navigation

[What is prewalk?](#-what-is-prewalk) ·
[Where it comes from](#-where-it-comes-from) ·
[What we built](#-what-we-built) ·
[Benchmark](#-benchmark) ·
[Quick Start](#-quick-start) ·
[Commands](#-commands) ·
[Presets](#-presets) ·
[Development](#-development)

---

## 🚶 What is prewalk?

Prewalk is a two-phase cost structure for coding agents. A frontier **planner** (your active
session) does the most expensive part of a change — understanding the repository, writing a
bounded plan, and completing **and verifying** task 1. A cheaper **executor** then finishes the
remaining tasks from that verified start:

```text
planner:  explore -> bounded plan -> complete & verify task 1 -> root Stop checkpoint
                                                                        |
                                          review with pw-go, or auto-release with --fast
                                                                        |
executor: inherit the trajectory (or a structured packet) -> finish the rest -> verify -> PREWALK_COMPLETE / PREWALK_INCOMPLETE
```

Reach for prewalk when *understanding the repository is a real part of the work* — new features
that must follow existing patterns, cross-cutting refactors, changes gated on tests you have to
discover first. A one- or two-file fix does not need it.

## 🧭 Where it comes from

The technique was proposed by **Can Bölük** (Stencil Labs) in
["You only need the frontier model for one single edit"](https://stencil.so/blog/prewalk),
based on a token-distribution analysis of ~2 million agent tool calls: the frontier model earns
its price during planning and the first edit, and the remaining edits do not need it. The post
ships the idea as `/prewalk` and `/plan` modes for a pi-lineage harness, and it is implemented
natively in [oh-my-pi](https://github.com/can1357/oh-my-pi); the community has since ported it
to other coding agents, including
[Codex CLI](https://github.com/TerenceLiu98/prewalk),
[OpenCode](https://github.com/Daniel-97/opencode-prewalk),
[Hermes](https://github.com/ildunari/hermes-prewalk), and Claude Code hooks.

This repository is an independent, dual-host implementation of the technique for
**Codex CLI** and **Claude Code**, with trajectory-inheritance handoff as the default route.
The rest of this page describes how to use it and what we adapted for these two hosts.

## ⚙️ How a run works

1. **Arm** — in your planner session, run the `prewalk` command with the task. The plugin
   persists a run record and returns the planning protocol (real todos only).
2. **Plan and verify** — the planner explores, plans, and completes task 1 with real
   verification. When it stops, the Stop hook validates the checkpoint (todo quality, packet
   structure, verification evidence) and persists it atomically.
3. **Review** — inspect the checkpoint, or pass `--fast` to skip human review (validation is
   identical). `pw-revise` sends it back for changes.
4. **Hand off** — `pw-go` probes the host's real capabilities, mints exactly one route token,
   and spawns the executor. On Codex the executor inherits the planner's whole trajectory by
   default (`fork_turns: "all"`); on Claude Code it runs as a scoped subagent seeded with the
   persisted packet.
5. **Finish** — only the bound executor's stop event with a `PREWALK_COMPLETE` /
   `PREWALK_INCOMPLETE: <reason>` marker ends the run. Anything else leaves a recoverable,
   explicitly reported state with exactly one recommended next command.

## 🛠️ What we built

### 1. Trajectory-inheritance handoff — the default route

Codex's `spawn_agent` accepts `fork_turns`, so the executor can start from the planner's
context instead of a document:

- **`fork_turns: "all"` (default)** — the executor inherits the planner's full turn history.
  The exploration, the todo list, and the already-verified first edit are in its context, and
  the handoff message is a short phase-2 note. The executor does not re-read files.
- **`fork_turns: "none"` (opt-in preset)** — classic fresh-context handoff seeded with the
  full structured packet, for when you want a minimal executor context.

The packet is always captured and persisted for recovery and audit; with fork handoff it is no
longer the executor's primary context. On our benchmark (below) fork handoff is the only arm
that beat a frontier one-shot on both cost and duration at equal pass rate.

### 2. One engine, two native adapters

```text
prewalk_engine/            host-independent engine (stdlib only)
  protocol    frozen names, limits, todo rules (imports nothing local)
  store       cross-process lock + atomic JSON persistence
  records     v4 record types + transition kernel (event-idempotent)
  checkpoint / routing / operations    the three v4 workflows
  presets / capabilities    configuration + host capability probing (fail-closed)
  prompts / legacy          model-facing copy (leaves) + frozen 0.3 event machine
hosts/codex/    native spawn_agent route validation, CODEX_THREAD_ID identity, shell wrappers
hosts/claude/   token-bound Agent PreToolUse rewrite, subagent lifecycle binding
```

The engine never imports a host; adapters only normalize payloads and render hook output. Each
adapter vendors a byte-identical engine copy (`scripts/sync_engine.py --check` enforces this in
CI), so the plugin installed from either marketplace is self-contained, and both hosts share
one tested state machine.

### 3. Checkpoint reject-retry loop

When root Stop validation fails (unqualified todos, missing packet sections, no verification
evidence), the plugin records the reason and attempt count (limit 3) and **blocks the stop**
with the exact defect. The planner repairs its todo list or packet in place and stops again —
no manual re-prompting, and both hosts behave identically.

### 4. Planner mutation budget

Every successful planning-phase file mutation is counted. From the sixth mutation the model
receives an explicit nudge to finish planning; past the limit (twelve) the nudge instructs it
to stop coding and hand off. The budget never edits files or blocks a tool call — it is model
guidance backed by durable counters, so the planner keeps control of its own edits while
prewalk keeps its cost structure intact.

### 5. Durable v4 state machine

Six phases — `planning / checkpoint_ready / handoff_requested / executor_running /
incomplete / stale` — with `idle` meaning "no record". Every transition has exactly one owner;
repeated and out-of-order events are idempotent no-ops. Records are written atomically under a
cross-process lock; corrupt records are quarantined; unknown schema versions fail closed and
are left untouched. Each handoff mints a one-time random route token that may bind at most one
tool-use ID and one agent ID — foreign, nested, or parallel subagent events are ignored. A
timeout enters `stale` but never kills or clears an unknown agent; `pw-reconcile` requires
proof that the bound agent is no longer live.

<details>
<summary><b>Phase reference</b></summary>

| Phase | Meaning | Valid user action |
| --- | --- | --- |
| `planning` | Root session is exploring, planning, completing task 1. | Continue, or `pw-off`. |
| `checkpoint_ready` | Valid checkpoint persisted; review pending. | `pw-go`, `pw-revise`, `pw-off`. |
| `handoff_requested` | Route token minted; spawn not yet bound. | Complete the spawn, `pw-retry`, `pw-off`. |
| `executor_running` | Native agent ID bound. | Wait, inspect with `pw-status`, reconcile after interruption. |
| `incomplete` | Route ended without a complete result; retryable from the checkpoint. | `pw-retry`, `pw-revise`, `pw-off`. |
| `stale` | Timeout/restart left an ambiguous route. | `pw-reconcile`, then as reported. |

</details>

### 6. Fail-closed capability probing

`pw-go` probes the host's live capability before minting a route: on Codex it checks the live
`spawn_agent` schema for `model` / `fork_turns` / `reasoning_effort` (a missing required field
keeps the checkpoint and refuses the route); on Claude Code a PreToolUse rewrite guarantees
the scoped executor type and model, and a conflicting `CLAUDE_CODE_SUBAGENT_MODEL` refuses the
arm (`override-conflict`). With `require_model_routing = true`, prewalk never spawns on a
route it could not prove.

## 📊 Benchmark

13 SWE-bench Verified instances (sympy×7, django×4, sphinx×2; each task base-verified to fail
and gold-verified to pass in its own py3.9 venv), 5 arms, 65 real runs (~14 h).
Planner = gpt-5.6-sol (medium), executor = gpt-5.6-luna (low); Windows 11, Codex CLI 0.152.1.

| Arm | Description | Pass | Cost / task | Time / task |
| --- | --- | --- | --- | --- |
| `oneshot_luna` | cheap model one-shot (lower bound) | 12/13 (92.3%) | $0.023 | 437s |
| `oneshot_sol` | frontier one-shot (upper bound) | 13/13 (100%) | $0.182 | 522s |
| `packet` | document handoff, fresh executor context | 13/13 | $0.177 | 925s |
| **`fork` (this repo's default)** | **trajectory inheritance + short note** | **13/13** | **$0.152** | **743s** |
| `plan` | plan-document handoff | 13/13 | $0.176 | 763s |

Paired comparisons over the 13 shared instances:

- **fork vs packet: −14.3% cost ($1.98 vs $2.31), −19.6% wall time (9665s vs 12030s)**
- **fork vs oneshot_sol: −16.4% cost** at equal pass rate
- plan vs oneshot_sol: −3.0%

The saving is concentrated in the executor phase: executor output tokens drop from 24487 to
**9046 (−63%)** and executor time from 3456s to **2119s (−39%)** — the executor finishes the
work instead of re-reading the repository. Behavioral evidence (sympy-24213, fork executor's
first message): *"There are no remaining planned tasks—the single source fix was completed and
verified. I'm rerunning the relevant unit tests once more."*

**Honest boundaries.** When a task is easy enough for the cheap model alone (92.3% of this
subset), a cheap one-shot is still the best unit economics ($0.023/task). Prewalk pays off in
the mid-to-hard band where you need the frontier's pass rate but want to cut its bill. This
subset's pass-rate ceiling was reached by the frontier one-shot, so the pass dimension does
not discriminate; timings include network noise; costs are computed from list prices.

## ❓ Quick Q&A

**Q: Does prewalk switch my session's model?**
A: **No.** The active root session is always the planner; prewalk never changes, replaces, or
"restores" its model. Presets configure the *executor* only.

**Q: What if the executor fails or is interrupted?**
A: The run enters `incomplete` (or `stale` when liveness is unknown) with exactly one
recommended command — `pw-retry` respawns from the same checkpoint, and task 1 is never
repeated. Unknown agents are never killed automatically.

**Q: Does the handoff survive compaction, restart, or resume?**
A: Yes. The checkpoint packet, todos, and evidence are persisted at Stop, not kept in
conversation memory; any later command reads the durable record.

**Q: What does the planner do to my todo list?**
A: Real work items only, each with a stable ID and a verification criterion — no control
pseudo-todos. Planning mutations beyond the budget trigger explicit nudges to hand off.

## 🚀 Quick Start

### Requirements

- Python 3.10+
- Codex CLI 0.146.0+ **or** Claude Code 2.1.145+

### Install — Codex

```sh
codex plugin marketplace add TardisBooo/prewalk
codex plugin add prewalk@prewalk-marketplace
```

### Install — Claude Code

```sh
claude plugin marketplace add TardisBooo/prewalk
claude plugin install prewalk@prewalk
```

Restart the CLI, then in the session you want as planner:

```text
$prewalk:prewalk Add a settings page with tests    (Codex)
/prewalk:prewalk Add a settings page with tests    (Claude Code)
```

### Three steps to a run

1. **Arm** with the `prewalk` command above and let the planner work: explore, plan, complete
   and verify task 1, then stop.
2. **Review** the persisted checkpoint — or arm with `--fast` to release it automatically
   (checkpoint validation is identical either way).
3. **Hand off** with `pw-go`. The executor finishes the remaining tasks and ends with exactly
   one marker; `pw-status` always shows the phase and the one recommended next command.

## 🧭 Commands

| Action | Codex | Claude Code |
| --- | --- | --- |
| Arm | `$prewalk:prewalk <task>` | `/prewalk:prewalk <task>` |
| Review & hand off | `$prewalk:pw-go` | `/prewalk:pw-go` |
| Revise the plan | `$prewalk:pw-revise <changes>` | `/prewalk:pw-revise <changes>` |
| Inspect state | `$prewalk:pw-status` | `/prewalk:pw-status` |
| Diagnose host & config | `$prewalk:pw-doctor` | `/prewalk:pw-doctor` |
| Retry a failed attempt | `$prewalk:pw-retry` | `/prewalk:pw-retry` |
| Resolve an ambiguous route | `$prewalk:pw-reconcile` | `/prewalk:pw-reconcile` |
| Disarm | `$prewalk:pw-off` | `/prewalk:pw-off` |
| Manual model-compat route | `$prewalk:pw-resume` | `/prewalk:pw-resume` |

`--preset <name>` selects a preset; `--fast` (formerly `--no-pause`) skips human review only —
checkpoint validation and route confirmation are never skipped.

## 🔧 Presets

| Host | Preset file | Format |
| --- | --- | --- |
| Codex | `~/.codex/prewalk-presets.toml` | TOML |
| Claude Code | `~/.claude/prewalk-presets.json` | JSON |

`CODEX_HOME` / `CLAUDE_CONFIG_DIR` relocate presets and state files wholesale. Templates:
[hosts/codex/presets.example.toml](hosts/codex/presets.example.toml),
[hosts/claude/presets.example.json](hosts/claude/presets.example.json).

| Field | Meaning |
| --- | --- |
| `executor` | Host-resolvable executor model |
| `max_todos` | Cap on real work items in the plan |
| `executor_effort` | Effort requested when the host exposes per-spawn control |
| `handoff_mode` | `auto` / `spawn` / `manual-model` |
| `require_model_routing` | `true` refuses spawns that cannot pin the model |
| `fork_turns` | Codex only: `"all"` inherits the planner trajectory (default); `"none"` is packet mode |

```toml
default_preset = "code-value"

[presets.code-value]
executor = "gpt-5.6-terra"
max_todos = 12
executor_effort = "medium"
handoff_mode = "auto"
require_model_routing = true
```

Presets configure the executor only. Legacy `planner` / `planner_thinking` fields are ignored
with a deprecation warning; `executor_thinking` is accepted as a deprecated alias of
`executor_effort`.

## 💻 Development

Python 3.10+ standard library only.

```sh
./scripts/check.sh
```

covers: unit and end-to-end tests (99 passing — state machine, routing, host adapters,
subprocess-driven lifecycles), static contracts, vendored-engine byte identity, JSON manifest
validation, shell entry checks, and install smoke tests. CI runs on Linux/macOS × Python
3.11–3.14 plus a native-contract matrix against minimum and latest Claude Code and Codex CLIs.

- Engine layering and invariants: [docs/adr/0001-v4-native-workflow.md](docs/adr/0001-v4-native-workflow.md)
- Host specifics: [Codex](hosts/codex/README.md) · [Claude Code](hosts/claude/README.md)
- Local benchmark recorder: `python3 scripts/benchmark.py record|report`
- History: [CHANGELOG.md](CHANGELOG.md) · Upgrades: [MIGRATION.md](MIGRATION.md)

## 📄 License and credits

MIT — see [LICENSE](LICENSE).

The prewalk technique comes from Can Bölük's post
["You only need the frontier model for one single edit"](https://stencil.so/blog/prewalk)
(Stencil Labs). This repository is a dual-host refactor of the
[TerenceLiu98/prewalk](https://github.com/TerenceLiu98/prewalk) v4 prototype: one engine with
two host adapters, trajectory-inheritance handoff as the default route, and the reject-retry
loop and planner mutation budget on both hosts.
