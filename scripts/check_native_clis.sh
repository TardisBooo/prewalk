#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-all}"
REQUIRE="${PREWALK_REQUIRE_NATIVE_CLIS:-0}"
if [[ "${PREWALK_SKIP_NATIVE_CLIS:-0}" == "1" ]]; then
  echo "PASS native contracts delegated to required minimum/latest CLI jobs"
  exit 0
fi
cd "$ROOT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

skip_or_fail() {
  local cli="$1"
  if [[ "$REQUIRE" == "1" ]]; then
    echo "FAIL native contract: $cli is required but absent" >&2
    exit 1
  fi
  echo "SKIP native contract: $cli is not installed"
}

version_at_least() {
  python3 - "$1" "$2" <<'PY'
import re, sys
found = re.search(r"(\d+)\.(\d+)\.(\d+)", sys.argv[1])
required = tuple(map(int, sys.argv[2].split(".")))
raise SystemExit(0 if found and tuple(map(int, found.groups())) >= required else 1)
PY
}

prepare_upgrade_fixture() {
  local fixture="$1" host="$2" version="$3"
  rm -rf "$fixture"
  # The marketplace manifests resolve their plugin source as ./hosts/<host>,
  # so the fixture must reproduce that exact directory shape.
  mkdir -p "$fixture/hosts"
  if [[ "$host" == "claude" ]]; then
    cp -R "$ROOT/.claude-plugin" "$fixture/"
    cp -R "$ROOT/hosts/claude" "$fixture/hosts/"
  else
    cp -R "$ROOT/.agents" "$fixture/"
    cp -R "$ROOT/hosts/codex" "$fixture/hosts/"
  fi
  python3 - "$fixture" "$host" "$version" <<'PY'
import json, sys
from pathlib import Path
root, host, version = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
if host == "claude":
    paths = [root / ".claude-plugin/marketplace.json", root / "hosts/claude/.claude-plugin/plugin.json"]
else:
    paths = [root / ".agents/plugins/marketplace.json", root / "hosts/codex/.codex-plugin/plugin.json"]
for path in paths:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "plugins" in data:
        data["plugins"][0]["version"] = version
    else:
        data["version"] = version
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY
}

assert_plugin_version() {
  python3 - "$1" "$2" "$3" <<'PY'
import json, sys
data, host, version = json.load(open(sys.argv[1], encoding="utf-8")), sys.argv[2], sys.argv[3]
items = data if host == "claude" else data["installed"]
key = "id" if host == "claude" else "pluginId"
expected = "prewalk@prewalk" if host == "claude" else "prewalk@prewalk-marketplace"
matches = [item for item in items if item[key] == expected]
assert len(matches) == 1 and matches[0]["version"] == version
PY
}

check_claude() {
  if ! command -v claude >/dev/null 2>&1; then
    skip_or_fail claude
    return
  fi
  local version details inline_details
  version="$(claude --version)"
  version_at_least "$version" "2.1.145" || {
    echo "FAIL native contract: Claude Code 2.1.145+ required; found $version" >&2
    return 1
  }
  claude plugin validate --strict "$ROOT/hosts/claude"

  CLAUDE_CONFIG_DIR="$TMP/claude" claude plugin marketplace add ./
  CLAUDE_CONFIG_DIR="$TMP/claude" claude plugin install prewalk@prewalk
  details="$(CLAUDE_CONFIG_DIR="$TMP/claude" claude plugin details prewalk@prewalk)"
  [[ "$details" == *"Skills (9)"* ]]
  [[ "$details" == *"Agents (1)"* ]]
  [[ "$details" == *"prewalk, pw-doctor, pw-go, pw-off, pw-reconcile, pw-resume, pw-retry, pw-revise, pw-status"* ]]
  [[ "$details" == *"prewalk-executor"* ]]

  # Exercise the session-only loader path without making a model request.
  inline_details="$(claude --plugin-dir "$ROOT/hosts/claude" plugin details prewalk)"
  [[ "$inline_details" == *"Source: prewalk@inline"* ]]
  [[ "$inline_details" == *"Skills (9)"* ]]
  [[ "$inline_details" == *"prewalk, pw-doctor, pw-go"* ]]

  prepare_upgrade_fixture "$TMP/claude-market" claude 0.3.1
  (
    cd "$TMP/claude-market"
    CLAUDE_CONFIG_DIR="$TMP/claude-upgrade" claude plugin marketplace add ./
  )
  CLAUDE_CONFIG_DIR="$TMP/claude-upgrade" claude plugin install prewalk@prewalk
  CLAUDE_CONFIG_DIR="$TMP/claude-upgrade" claude plugin list --json >"$TMP/claude-old.json"
  assert_plugin_version "$TMP/claude-old.json" claude 0.3.1
  prepare_upgrade_fixture "$TMP/claude-market" claude 1.0.2
  CLAUDE_CONFIG_DIR="$TMP/claude-upgrade" claude plugin marketplace update prewalk
  CLAUDE_CONFIG_DIR="$TMP/claude-upgrade" claude plugin update prewalk@prewalk
  CLAUDE_CONFIG_DIR="$TMP/claude-upgrade" claude plugin list --json >"$TMP/claude-new.json"
  assert_plugin_version "$TMP/claude-new.json" claude 1.0.2
  echo "PASS native contract: Claude $version; 9 skills, 1 agent, plugin-dir loader"
  echo "PASS native upgrade: Claude 0.3.1 -> 1.0.2"
}

check_codex() {
  if ! command -v codex >/dev/null 2>&1; then
    skip_or_fail codex
    return
  fi
  local version
  version="$(codex --version 2>/dev/null)"
  version_at_least "$version" "0.146.0" || {
    echo "FAIL native contract: Codex CLI 0.146.0+ required; found $version" >&2
    return 1
  }
  mkdir -p "$TMP/codex"
  CODEX_HOME="$TMP/codex" codex plugin marketplace add ./ --json >/dev/null
  CODEX_HOME="$TMP/codex" codex plugin add prewalk@prewalk-marketplace --json >/dev/null
  CODEX_HOME="$TMP/codex" codex plugin list --json >"$TMP/codex-plugins.json"
  python3 - "$TMP/codex-plugins.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
matches = [item for item in data["installed"] if item["pluginId"] == "prewalk@prewalk-marketplace"]
assert len(matches) == 1 and matches[0]["installed"] and matches[0]["enabled"]
PY
  prepare_upgrade_fixture "$TMP/codex-market" codex 0.3.1
  mkdir -p "$TMP/codex-upgrade"
  (
    cd "$TMP/codex-market"
    CODEX_HOME="$TMP/codex-upgrade" codex plugin marketplace add ./ --json >/dev/null
  )
  CODEX_HOME="$TMP/codex-upgrade" codex plugin add prewalk@prewalk-marketplace --json >/dev/null
  CODEX_HOME="$TMP/codex-upgrade" codex plugin list --json >"$TMP/codex-old.json"
  assert_plugin_version "$TMP/codex-old.json" codex 0.3.1
  prepare_upgrade_fixture "$TMP/codex-market" codex 1.0.2
  # Local marketplace fixtures refresh through plugin add; the upgrade command
  # intentionally accepts Git marketplaces only.
  CODEX_HOME="$TMP/codex-upgrade" codex plugin add prewalk@prewalk-marketplace --json >/dev/null
  CODEX_HOME="$TMP/codex-upgrade" codex plugin list --json >"$TMP/codex-new.json"
  assert_plugin_version "$TMP/codex-new.json" codex 1.0.2
  echo "PASS native contract: Codex $version; isolated marketplace install discovered"
  echo "PASS native upgrade: Codex 0.3.1 -> 1.0.2"
}

case "$TARGET" in
  claude) check_claude ;;
  codex) check_codex ;;
  all) check_claude; check_codex ;;
  *) echo "usage: $0 [claude|codex|all]" >&2; exit 2 ;;
esac
