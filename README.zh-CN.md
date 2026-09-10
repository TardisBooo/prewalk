<div align="center">

# prewalk

**让前沿模型完成真正需要它的那一次编辑 —— 再把经过验证的起点交给更便宜的执行模型。**

_单引擎 · 双原生宿主 · 轨迹继承交接 · 持久化检查点 · fail-closed 路由_

[![CI](https://github.com/TardisBooo/prewalk/actions/workflows/check.yml/badge.svg)](https://github.com/TardisBooo/prewalk/actions/workflows/check.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-32CD32.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Codex CLI](https://img.shields.io/badge/Codex%20CLI-0.146%2B-8A2BE2)
![Claude Code](https://img.shields.io/badge/Claude%20Code-2.1.145%2B-D97757)

[English](README.md) | **简体中文**

</div>

---

## 📋 快速导航

[什么是 prewalk？](#-什么是-prewalk) ·
[技术出处](#-技术出处) ·
[我们做了什么](#-我们做了什么) ·
[基准测试](#-基准测试) ·
[快速上手](#-快速上手) ·
[命令一览](#-命令一览) ·
[预设](#-预设) ·
[开发](#-开发)

---

## 🚶 什么是 prewalk？

prewalk 是编码代理的两阶段成本结构：让前沿模型做一次改动里最昂贵的部分 —— 理解仓库、
写出有上限的计划、**完成并验证**任务 1 —— 然后由更便宜的执行模型从这份经过验证的起点
接手剩余任务：

```text
planner:  探索 -> 有上限的计划 -> 完成并验证任务 1 -> root Stop 检查点
                                                        |
                                  人工复核 pw-go，或 --fast 自动放行
                                                        |
executor: 继承轨迹（或结构化 packet）-> 完成剩余任务 -> 验证 -> PREWALK_COMPLETE / PREWALK_INCOMPLETE
```

适合“理解仓库本身就是工作的重要部分”的改动：需要遵循既有模式的新功能、跨模块重构、
必须先摸清测试再动手的修改。一两个文件的小修不需要它。

## 🧭 技术出处

这一技术由 **Can Bölük**（Stencil Labs）在
["You only need the frontier model for one single edit"](https://stencil.so/blog/prewalk)
一文中提出，依据是对约 200 万次代理工具调用的 token 分布分析：前沿模型的价值集中在
规划与第一次编辑，其后的编辑并不需要它。原文以 pi 系 harness 的 `/prewalk` 与 `/plan`
模式交付，并在 [oh-my-pi](https://github.com/can1357/oh-my-pi) 中原生实现；社区随后将其
移植到了其他编码代理，包括
[Codex CLI](https://github.com/TerenceLiu98/prewalk)、
[OpenCode](https://github.com/Daniel-97/opencode-prewalk)、
[Hermes](https://github.com/ildunari/hermes-prewalk) 以及 Claude Code hooks。

本仓库是面向 **Codex CLI** 与 **Claude Code** 的独立双宿主实现，默认路由为轨迹继承交接。
本页其余部分说明它的用法，以及我们为这两个宿主所做的专门适配。

## ⚙️ 一次运行如何进行

1. **武装** —— 在用作 planner 的会话里带任务运行 `prewalk` 命令。插件持久化运行记录，
   并返回规划协议（只允许真实任务项）。
2. **规划并验证** —— planner 探索、规划、完成并验证任务 1。停止时，Stop 钩子校验
   检查点（todo 质量、packet 结构、验证证据）并原子化持久化。
3. **复核** —— 检查检查点，或用 `--fast` 跳过人工复核（校验完全相同）；
   `pw-revise` 将其退回修改。
4. **交接** —— `pw-go` 探测宿主真实能力，铸造恰好一个 route token，并 spawn executor。
   Codex 上默认继承 planner 全部轨迹（`fork_turns: "all"`）；Claude Code 上以携带持久化
   packet 的受限子代理运行。
5. **收尾** —— 只有被绑定的 executor 的停止事件携带 `PREWALK_COMPLETE` /
   `PREWALK_INCOMPLETE: <原因>` 标记才能结束运行；其余一切都会落入可恢复的、
   明确报告的状态，并给出恰好一条推荐命令。

## 🛠️ 我们做了什么

### 1. 轨迹继承交接 —— 默认路由

Codex 的 `spawn_agent` 支持 `fork_turns`，executor 可以从 planner 的上下文起步，
而不是从一份文档起步：

- **`fork_turns: "all"`（默认）**：executor 继承 planner 的全部回合轨迹。探索过程、
  todo 列表、已验证的第一次编辑都已在它的上下文里，交接消息只是一条简短的 phase-2
  注记，executor 不再重读文件。
- **`fork_turns: "none"`（可选预设）**：经典的新上下文交接，以完整结构化 packet 起步，
  适合需要最小 executor 上下文的场景。

packet 始终会被捕获并持久化（供恢复与审计）；fork 交接下它不再是 executor 的主要上下文。
在下方基准中，fork 交接是唯一在同等 pass 率下同时省成本、省时长的 arm。

### 2. 单引擎、双原生适配器

```text
prewalk_engine/            与宿主无关的引擎（仅标准库）
  protocol    冻结名称、限制、todo 规则（不 import 任何本地模块）
  store       跨进程锁 + 原子 JSON 持久化
  records     v4 记录类型 + 状态转移内核（事件幂等）
  checkpoint / routing / operations    三个 v4 工作流
  presets / capabilities    配置 + 宿主能力探测（fail-closed）
  prompts / legacy          模型文案（叶子）+ 冻结的 0.3 事件机
hosts/codex/    原生 spawn_agent 路由校验、CODEX_THREAD_ID 身份、shell 包装
hosts/claude/   token 绑定的 Agent PreToolUse 改写、子代理生命周期绑定
```

引擎从不 import 宿主；适配器只做 payload 归一化与 hook 输出渲染。每个适配器内嵌一份
字节一致的引擎拷贝（CI 中的 `scripts/sync_engine.py --check` 把关），因此从任一市场安装的
插件都自包含，两个宿主共享同一套经过测试的状态机。

### 3. 检查点拒绝-重试闭环

root Stop 校验失败（todo 不合格、packet 缺段、无验证证据）时，插件记录原因与次数
（上限 3 次）并**阻塞停止**，明确指出缺陷。planner 原地修复 todo 或 packet 后再次停止
即可 —— 无需人工重新引导，两个宿主行为一致。

### 4. planner 变更预算

planning 阶段每次成功的文件变更都会计数：第 6 次起向模型注入明确的提醒；超过上限
（12 次）后明确要求停止编码、进行交接。预算从不编辑文件、也不阻断工具调用 —— 它是
由持久计数支撑的模型引导：planner 保持对自己编辑的控制，prewalk 保住自己的成本结构。

### 5. 持久化 v4 状态机

六个阶段 —— `planning / checkpoint_ready / handoff_requested / executor_running /
incomplete / stale`，`idle` 即“无记录”。每次转移恰好一个 owner；重复与乱序事件幂等
no-op。记录在跨进程锁下原子写入；损坏记录被隔离；未知 schema 版本 fail-closed、
原样保留。每次交接铸造一次性随机 route token，最多绑定一个 tool-use ID 与一个
agent ID —— 无关、嵌套、并发的子代理事件一律忽略。超时进入 `stale` 但从不清理或
终止未知 agent；`pw-reconcile` 要求先证明被绑定 agent 已不在运行。

<details>
<summary><b>阶段速查</b></summary>

| 阶段 | 含义 | 可用操作 |
| --- | --- | --- |
| `planning` | 根会话探索、规划、完成任务 1。 | 继续，或 `pw-off`。 |
| `checkpoint_ready` | 有效检查点已持久化，等待复核。 | `pw-go`、`pw-revise`、`pw-off`。 |
| `handoff_requested` | 路由令牌已铸造，spawn 尚未绑定。 | 完成 spawn、`pw-retry`、`pw-off`。 |
| `executor_running` | 已绑定原生 agent ID。 | 等待、`pw-status` 查看、中断后 reconcile。 |
| `incomplete` | 路由未产生完整结果；可从检查点重试。 | `pw-retry`、`pw-revise`、`pw-off`。 |
| `stale` | 超时/重启导致路由状态不明。 | `pw-reconcile`，再按报告操作。 |

</details>

### 6. 能力探测 fail-closed

`pw-go` 在铸造路由前探测宿主的真实能力：Codex 侧检查 live `spawn_agent` schema 是否
含 `model` / `fork_turns` / `reasoning_effort`（缺必需项则保留检查点、拒绝放行）；
Claude 侧用 PreToolUse 改写保证受限 executor 类型与模型，检测到
`CLAUDE_CODE_SUBAGENT_MODEL` 冲突时拒绝 arm（`override-conflict`）。
`require_model_routing = true` 时，绝不在未能证明的路由上 spawn。

## 📊 基准测试

13 个 SWE-bench Verified 实例（sympy×7、django×4、sphinx×2；每个任务在独立 py3.9 venv
中做了 base 必挂 / gold 必过的双向校验），5 臂，65 次真实运行（约 14 小时）。
planner = gpt-5.6-sol（medium），executor = gpt-5.6-luna（low）；Windows 11，
Codex CLI 0.152.1。

| 臂 | 说明 | pass | 成本/例 | 时长/例 |
| --- | --- | --- | --- | --- |
| `oneshot_luna` | 便宜模型一次性（下界参照） | 12/13 (92.3%) | $0.023 | 437s |
| `oneshot_sol` | 前沿模型一次性（上界参照） | 13/13 (100%) | $0.182 | 522s |
| `packet` | 文档式交接，executor 新上下文 | 13/13 | $0.177 | 925s |
| **`fork`（本仓库默认）** | **轨迹继承 + 短交接注记** | **13/13** | **$0.152** | **743s** |
| `plan` | 计划文档式交接 | 13/13 | $0.176 | 763s |

13 个共同实例上的成对比较：

- **fork vs packet：成本 −14.3%（$1.98 vs $2.31），时长 −19.6%（9665s vs 12030s）**
- **fork vs oneshot_sol：同等 pass 率下成本 −16.4%**
- plan vs oneshot_sol：−3.0%

节省集中在 executor 阶段：executor 输出 token 从 24487 降到 **9046（−63%）**，时长从
3456s 降到 **2119s（−39%）** —— executor 直接收尾，而不是重读仓库。行为学证据
（sympy-24213，fork executor 的第一条消息）：*"There are no remaining planned tasks—the
single source fix was completed and verified. I'm rerunning the relevant unit tests once
more."*

**诚实的边界。** 任务简单到便宜模型能独自通过时（本子集的 92.3%），便宜模型一次性仍是
最好的单位经济（$0.023/例）。prewalk 的价值区间是“需要前沿 pass 率、又想压成本”的
中高难度任务。本子集 pass 率天花板被前沿一次性触及，pass 维度无区分度；时长含网络
噪声；成本按目录价折算。

## ❓ 常见问题

**问：prewalk 会切换我会话的模型吗？**
答：**不会。** 活动根会话永远是 planner；prewalk 从不更换、替换或“恢复”它的模型。
预设只配置 *executor*。

**问：executor 失败或被中断怎么办？**
答：运行进入 `incomplete`（存活状态不明时为 `stale`），并给出恰好一条推荐命令 ——
`pw-retry` 从同一检查点重新 spawn，任务 1 绝不重复；未知 agent 从不被自动终止。

**问：交接能扛住 compaction、重启、会话恢复吗？**
答：能。检查点 packet、todo 与证据在 Stop 时持久化，不依赖对话记忆；任何后续命令
读取的都是持久记录。

**问：planner 会对我的 todo 列表做什么？**
答：只保留真实任务项，每项有稳定 ID 与验证标准 —— 没有控制类伪 todo。规划阶段变更
超出预算会触发明确的交接提醒。

## 🚀 快速上手

### 环境要求

- Python 3.10+
- Codex CLI 0.146.0+ **或** Claude Code 2.1.145+

### 安装 —— Codex

```sh
codex plugin marketplace add TardisBooo/prewalk
codex plugin add prewalk@prewalk-marketplace
```

### 安装 —— Claude Code

```sh
claude plugin marketplace add TardisBooo/prewalk
claude plugin install prewalk@prewalk
```

重启 CLI，在想用作 planner 的会话里：

```text
$prewalk:prewalk Add a settings page with tests    (Codex)
/prewalk:prewalk Add a settings page with tests    (Claude Code)
```

### 三步完成一次运行

1. 用上面的 `prewalk` 命令**武装**，让 planner 工作：探索、规划、完成并验证任务 1，
   然后停止。
2. **复核**持久化的检查点 —— 或武装时带 `--fast` 自动放行（检查点校验两种方式完全
   相同）。
3. 用 `pw-go` **交接**。executor 完成剩余任务并以恰好一个标记结束；`pw-status` 随时
   显示阶段与唯一推荐的下一步命令。

## 🧭 命令一览

| 动作 | Codex | Claude Code |
| --- | --- | --- |
| 武装 | `$prewalk:prewalk <task>` | `/prewalk:prewalk <task>` |
| 复核并交接 | `$prewalk:pw-go` | `/prewalk:pw-go` |
| 修改计划 | `$prewalk:pw-revise <changes>` | `/prewalk:pw-revise <changes>` |
| 查看状态 | `$prewalk:pw-status` | `/prewalk:pw-status` |
| 诊断环境与配置 | `$prewalk:pw-doctor` | `/prewalk:pw-doctor` |
| 重试失败尝试 | `$prewalk:pw-retry` | `/prewalk:pw-retry` |
| 处理模糊路由 | `$prewalk:pw-reconcile` | `/prewalk:pw-reconcile` |
| 解除武装 | `$prewalk:pw-off` | `/prewalk:pw-off` |
| 手动模型兼容路径 | `$prewalk:pw-resume` | `/prewalk:pw-resume` |

`--preset <name>` 选择预设；`--fast`（旧名 `--no-pause`）只跳过人工复核 —— 检查点
校验与路由确认从不跳过。

## 🔧 预设

| 宿主 | 预设文件 | 格式 |
| --- | --- | --- |
| Codex | `~/.codex/prewalk-presets.toml` | TOML |
| Claude Code | `~/.claude/prewalk-presets.json` | JSON |

`CODEX_HOME` / `CLAUDE_CONFIG_DIR` 可整体迁移预设与状态文件。模板：
[hosts/codex/presets.example.toml](hosts/codex/presets.example.toml)、
[hosts/claude/presets.example.json](hosts/claude/presets.example.json)。

| 字段 | 含义 |
| --- | --- |
| `executor` | 宿主可解析的 executor 模型 |
| `max_todos` | 计划中的最大真实任务数 |
| `executor_effort` | 宿主提供按次 spawn 控制时申请的 effort |
| `handoff_mode` | `auto` / `spawn` / `manual-model` |
| `require_model_routing` | `true` 时拒绝无法钉死模型的 spawn |
| `fork_turns` | 仅 Codex：`"all"` 继承 planner 轨迹（默认）；`"none"` 为 packet 模式 |

```toml
default_preset = "code-value"

[presets.code-value]
executor = "gpt-5.6-terra"
max_todos = 12
executor_effort = "medium"
handoff_mode = "auto"
require_model_routing = true
```

预设只配置 executor。旧字段 `planner` / `planner_thinking` 被忽略并给出弃用警告；
`executor_thinking` 作为 `executor_effort` 的弃用别名被接受。

## 💻 开发

仅用 Python 3.10+ 标准库。

```sh
./scripts/check.sh
```

覆盖：单元与端到端测试（99 项全绿 —— 状态机、路由、宿主适配器、以真实子进程驱动的
生命周期）、静态契约、vendored 引擎字节一致性、JSON manifest 校验、shell 入口检查、
安装冒烟。CI 在 Linux/macOS × Python 3.11–3.14 上运行，另有针对 minimum/latest 两个
版本 Claude Code 与 Codex CLI 的原生契约矩阵。

- 引擎分层与不变量：[docs/adr/0001-v4-native-workflow.md](docs/adr/0001-v4-native-workflow.md)
- 宿主细节：[Codex](hosts/codex/README.md) · [Claude Code](hosts/claude/README.md)
- 本地基准记录工具：`python3 scripts/benchmark.py record|report`
- 版本历史：[CHANGELOG.md](CHANGELOG.md) · 升级说明：[MIGRATION.md](MIGRATION.md)

## 📄 许可与致谢

MIT —— 见 [LICENSE](LICENSE)。

prewalk 技术来自 Can Bölük 的文章
["You only need the frontier model for one single edit"](https://stencil.so/blog/prewalk)
（Stencil Labs）。本仓库由 [TerenceLiu98/prewalk](https://github.com/TerenceLiu98/prewalk)
的 v4 原型重构而来：单引擎双宿主适配器架构、默认轨迹继承交接，并把拒绝-重试闭环与
planner 变更预算带到两个宿主。
