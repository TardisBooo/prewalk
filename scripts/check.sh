#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 scripts/sync_engine.py --check

python3 -m compileall -q prewalk_engine hosts/codex/hooks hosts/claude/hooks tests
python3 -m unittest discover -s tests -v
python3 scripts/check_contracts.py
./scripts/check_native_clis.sh

python3 - <<'PY'
import json
from pathlib import Path

for path in (
    Path(".claude-plugin/marketplace.json"),
    Path(".agents/plugins/marketplace.json"),
    Path("hosts/claude/.claude-plugin/plugin.json"),
    Path("hosts/claude/hooks/hooks.json"),
    Path("hosts/claude/presets.example.json"),
    Path("hosts/claude/settings.example.json"),
    Path("hosts/codex/.codex-plugin/plugin.json"),
    Path("hosts/codex/hooks.json"),
):
    with path.open(encoding="utf-8") as handle:
        json.load(handle)
PY

bash -n install.sh hosts/codex/scripts/prewalk_pause.sh \
  hosts/codex/scripts/prewalk_edit_tracker.sh \
  hosts/codex/scripts/prewalk_todo_tracker.sh \
  hosts/codex/scripts/prewalk_executor_router.sh

for script in hosts/codex/scripts/*.sh; do
  test -x "$script"
done

CHECK_TMP="$(mktemp -d)"
trap 'rm -rf "$CHECK_TMP"' EXIT

./install.sh claude "$CHECK_TMP/claude" >/dev/null
./install.sh claude "$CHECK_TMP/claude" >/dev/null
./install.sh codex "$CHECK_TMP/codex" >/dev/null

python3 - "$CHECK_TMP" "$ROOT" <<'PY'
import json
from pathlib import Path
import sys

tmp = Path(sys.argv[1])
root = Path(sys.argv[2])
settings = json.loads((tmp / "claude" / "settings.json").read_text(encoding="utf-8"))
hooks = settings["hooks"]
assert len(hooks["SessionStart"]) == 1
assert len(hooks["Stop"]) == 1
assert [group["matcher"] for group in hooks["PostToolUse"]] == [
    "TodoWrite|TaskCreate|TaskUpdate|TaskList",
    "Write|Edit|MultiEdit|Bash|rp|RepoPrompt",
    "Task|Agent",
]
assert [group["matcher"] for group in hooks["PreToolUse"]] == ["Task|Agent"]
assert [group["matcher"] for group in hooks["SubagentStart"]] == ["^(prewalk:)?prewalk-executor$"]
assert [group["matcher"] for group in hooks["SubagentStop"]] == ["^(prewalk:)?prewalk-executor$"]
assert [group["matcher"] for group in hooks["PostToolUseFailure"]] == ["Task|Agent"]
assert [group["matcher"] for group in hooks["PermissionDenied"]] == ["Task|Agent"]

for skill in (tmp / "claude" / "skills").glob("*/SKILL.md"):
    text = skill.read_text(encoding="utf-8")
    assert "<PLUGIN_ROOT>" not in text
    assert "${CLAUDE_PLUGIN_ROOT}" not in text
    # Normalize separators so the check also holds where the installer's
    # baked-in path and the shell's $PWD use different slash styles (Windows).
    assert str(root / "hosts" / "claude").replace("\\", "/") in text

assert (tmp / "claude" / "prewalk-presets.json").is_file()
assert (tmp / "codex" / "prewalk-presets.toml").is_file()

codex_hooks = json.loads((root / "hosts" / "codex" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
spawn_matcher = r"^((functions|collaboration)\.)?spawn_agent$"
assert [group["matcher"] for group in codex_hooks["PreToolUse"]] == [spawn_matcher]
assert spawn_matcher in [group["matcher"] for group in codex_hooks["PostToolUse"]]
assert len(codex_hooks["SubagentStop"]) == 1
PY

git diff --check
echo "prewalk checks passed"
