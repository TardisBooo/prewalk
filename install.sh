#!/usr/bin/env bash
# prewalk installer.
#
#   ./install.sh claude [CLAUDE_CONFIG_DIR]
#   ./install.sh codex  [CODEX_HOME]
#
# - claude: copies skills + presets into ~/.claude (or $CLAUDE_CONFIG_DIR),
#   merges the prewalk hooks into settings.json, and patches plugin-root
#   references in the copied skills to the absolute source path.
# - codex: copies presets into ~/.codex (or $CODEX_HOME). The plugin itself is
#   installed via the Codex marketplace (`codex plugin marketplace add` +
#   `codex plugin add`); this only stages presets.
#
# Re-runnable: replaces older prewalk hook registrations without duplicating
# unrelated user hooks.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-}"

die() { echo "install: $*" >&2; exit 1; }

install_claude() {
  local CFG="${2:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}}"
  local SRC="$ROOT/hosts/claude"
  command -v python3 >/dev/null || die "python3 not found on PATH"
  mkdir -p "$CFG/skills"
  cp -R "$SRC/skills/"* "$CFG/skills/"
  cp "$SRC/presets.example.json" "$CFG/prewalk-presets.json"
  echo "✓ copied skills + presets → $CFG"

  # Loose installs do not set CLAUDE_PLUGIN_ROOT, so bake in the source path.
  python3 - "$CFG" "$SRC" <<'PY'
import json, os, sys
cfg, src = sys.argv[1], sys.argv[2]
import glob
for md in glob.glob(os.path.join(cfg, "skills", "*", "SKILL.md")):
    t = open(md).read()
    t = t.replace("${CLAUDE_PLUGIN_ROOT}", src).replace("<PLUGIN_ROOT>", src)
    open(md, "w").write(t)
print("✓ patched plugin root in skills")
PY

  # Merge hooks into settings.json.
  python3 - "$CFG/settings.json" "$SRC/hooks" <<'PY'
import json, os, sys
path, hooks = sys.argv[1], sys.argv[2]
existing = {}
if os.path.exists(path):
    try: existing = json.load(open(path))
    except Exception:
        import shutil; shutil.copy(path, path + ".bak"); existing = {}
h = existing.get("hooks", {})
def cmd(p): return f'python3 "{os.path.join(hooks, p)}"'

# Remove current and legacy registrations owned by this checkout before adding
# the current set. Leave every unrelated user hook untouched.
managed = {
    "export_session_id.py", "todo_tracker.py", "edit_tracker.py",
    "handoff_router.py", "handoff_result.py", "handoff_lifecycle.py",
    "pause_detect.py", "edit_gate.py",
}
def owned(group):
    commands = [entry.get("command", "") for entry in group.get("hooks", [])]
    return any(os.path.join(hooks, name) in command for command in commands for name in managed)
for event in list(h):
    h[event] = [group for group in h[event] if not owned(group)]
    if not h[event]:
        del h[event]

for ev, grp in {
    "Stop": [{"hooks":[{"type":"command","command":cmd("pause_detect.py")}]}],
    "SessionStart": [{"hooks":[{"type":"command","command":cmd("export_session_id.py")}]}],
    "PostToolUse": [
        {"matcher":"TodoWrite|TaskCreate|TaskUpdate|TaskList",
         "hooks":[{"type":"command","command":cmd("todo_tracker.py")} ]},
        {"matcher":"Write|Edit|MultiEdit|Bash|rp|RepoPrompt",
         "hooks":[{"type":"command","command":cmd("edit_tracker.py")} ]},
        {"matcher":"Task|Agent",
         "hooks":[{"type":"command","command":cmd("handoff_result.py")} ]},
    ],
    "SubagentStart": [
        {"matcher":"^(prewalk:)?prewalk-executor$",
         "hooks":[{"type":"command","command":cmd("handoff_lifecycle.py")} ]},
    ],
    "SubagentStop": [
        {"matcher":"^(prewalk:)?prewalk-executor$",
         "hooks":[{"type":"command","command":cmd("handoff_lifecycle.py")} ]},
    ],
    "PostToolUseFailure": [
        {"matcher":"Task|Agent",
         "hooks":[{"type":"command","command":cmd("handoff_result.py")} ]},
    ],
    "PermissionDenied": [
        {"matcher":"Task|Agent",
         "hooks":[{"type":"command","command":cmd("handoff_result.py")} ]},
    ],
    "PreToolUse": [{"matcher":"Task|Agent","hooks":[{"type":"command","command":cmd("handoff_router.py")}]}],
}.items():
    h.setdefault(ev, []).extend(grp)
existing["hooks"] = h
json.dump(existing, open(path, "w"), indent=2, ensure_ascii=False)
print(f"✓ merged hooks → {path}")
PY

  echo
  echo "Done. Edit $CFG/prewalk-presets.json (executor routes), then restart Claude Code."
}

install_codex() {
  local HOME_DIR="${2:-${CODEX_HOME:-$HOME/.codex}}"
  command -v python3 >/dev/null || die "python3 not found on PATH"
  mkdir -p "$HOME_DIR"
  cp "$ROOT/hosts/codex/presets.example.toml" "$HOME_DIR/prewalk-presets.toml"
  echo "✓ copied presets → $HOME_DIR/prewalk-presets.toml"
  echo
  echo "Install the plugin itself (Codex uses a marketplace model, not 'plugin install'):"
  echo "  codex plugin marketplace add \"$ROOT\""
  echo "  codex plugin add prewalk@prewalk-marketplace"
  echo "  # or, once pushed to GitHub:"
  echo "  codex plugin marketplace add TardisBooo/prewalk"
  echo "  codex plugin add prewalk@prewalk-marketplace"
  echo
  echo "Then edit $HOME_DIR/prewalk-presets.toml and restart Codex."
}

case "$TARGET" in
  claude) install_claude "$@" ;;
  codex)  install_codex "$@" ;;
  *) die "usage: $0 claude|codex  (got: '$TARGET')";;
esac
