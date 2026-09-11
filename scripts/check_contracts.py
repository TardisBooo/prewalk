#!/usr/bin/env python3
"""Static native-contract checks that do not require either host CLI.

Covers the invariants a release must hold: skill/agent inventories, version
agreement across every manifest and engine copy, namespaced commands in
user-facing documents, hook registration shapes, and the absence of known
obsolete artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys


class ContractError(ValueError):
    pass


def parse_frontmatter(path: Path) -> dict[str, str]:
    """Parse the tiny YAML subset allowed in SKILL.md/agent frontmatter."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ContractError(f"{path}: missing opening frontmatter delimiter")
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise ContractError(f"{path}: missing closing frontmatter delimiter") from exc

    metadata: dict[str, str] = {}
    for line_number, raw in enumerate(lines[1:end], 2):
        if not raw.strip():
            continue
        if raw[:1].isspace() or ":" not in raw:
            raise ContractError(f"{path}:{line_number}: unsupported frontmatter syntax")
        key, value = raw.split(":", 1)
        key, value = key.strip(), value.strip()
        if not key or not value or key in metadata:
            raise ContractError(f"{path}:{line_number}: invalid or duplicate metadata field")
        if value.startswith('"'):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ContractError(f"{path}:{line_number}: invalid quoted YAML scalar") from exc
        elif value.startswith("'"):
            if len(value) < 2 or not value.endswith("'"):
                raise ContractError(f"{path}:{line_number}: invalid quoted YAML scalar")
            value = value[1:-1].replace("''", "'")
        elif ": " in value:
            raise ContractError(
                f"{path}:{line_number}: quote plain scalars containing a colon and space"
            )
        metadata[key] = value
    for required in ("name", "description"):
        if not metadata.get(required, "").strip():
            raise ContractError(f"{path}: missing non-empty {required}")
    return metadata


def validate_repo(root: Path) -> None:
    # --- Skill and agent inventories ------------------------------------------
    skills = sorted((root / "hosts" / "claude" / "skills").glob("*/SKILL.md"))
    agents = sorted((root / "hosts" / "claude" / "agents").glob("*.md"))
    skill_names = {parse_frontmatter(path)["name"] for path in skills}
    agent_names = {parse_frontmatter(path)["name"] for path in agents}
    expected_skills = {
        "prewalk", "pw-doctor", "pw-go", "pw-off", "pw-reconcile", "pw-resume",
        "pw-retry", "pw-revise", "pw-status"
    }
    if skill_names != expected_skills:
        raise ContractError(f"Claude skill inventory mismatch: {sorted(skill_names)}")
    if agent_names != {"prewalk-executor"}:
        raise ContractError(f"Claude agent inventory mismatch: {sorted(agent_names)}")

    # --- Version agreement: manifests, marketplaces, engine copies ------------
    claude_manifest = json.loads(
        (root / "hosts" / "claude" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    codex_manifest = json.loads(
        (root / "hosts" / "codex" / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    claude_marketplace = json.loads(
        (root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    codex_marketplace = json.loads(
        (root / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
    )
    versions = {
        claude_manifest["version"],
        codex_manifest["version"],
        claude_marketplace["plugins"][0]["version"],
    }
    codex_marketplace_version = codex_marketplace["plugins"][0].get("version")
    if codex_marketplace_version:
        versions.add(codex_marketplace_version)
    if len(versions) != 1:
        raise ContractError(f"plugin and marketplace versions disagree: {sorted(versions)}")
    release_version = next(iter(versions))

    protocol_copies = [
        root / "prewalk_engine" / "protocol.py",
        root / "hosts" / "codex" / "hooks" / "prewalk_engine" / "protocol.py",
        root / "hosts" / "claude" / "hooks" / "prewalk_engine" / "protocol.py",
    ]
    for path in protocol_copies:
        match = re.search(r'^VERSION = "([^"]+)"$', path.read_text(encoding="utf-8"), re.MULTILINE)
        if not match or match.group(1) != release_version:
            raise ContractError(
                f"{path}: engine version does not match plugin version {release_version}"
            )

    release_documents = {
        "changelog": root / "CHANGELOG.md",
        "migration guide": root / "MIGRATION.md",
        "release checklist": root / "RELEASE_CHECKLIST.md",
    }
    for label, path in release_documents.items():
        text = path.read_text(encoding="utf-8")
        if release_version not in text:
            raise ContractError(f"{label} does not declare release {release_version}")

    # --- Commands stay plugin-namespaced in user-facing text -------------------
    short_command = re.compile(
        r"(?m)(?:^|`)(/(?:prewalk(?!:)|pw-(?:go|status|revise|off|doctor|reconcile|resume|retry))\b)"
    )
    for path in [root / "hosts" / "claude" / "README.md", *skills]:
        match = short_command.search(path.read_text(encoding="utf-8"))
        if match:
            raise ContractError(f"{path}: unsupported unnamespaced command {match.group(1)}")

    install_text = (root / "install.sh").read_text(encoding="utf-8")
    if "planner/executor models" in install_text:
        raise ContractError("installer must not claim that presets select the root planner")

    # --- Hook registration shapes ----------------------------------------------
    hooks = json.loads(
        (root / "hosts" / "claude" / "hooks" / "hooks.json").read_text(encoding="utf-8")
    )["hooks"]
    for event in ("SubagentStart", "SubagentStop"):
        matchers = [group.get("matcher") for group in hooks.get(event, [])]
        if matchers != ["^(prewalk:)?prewalk-executor$"]:
            raise ContractError(
                f"{event} must bind only the executor's native lifecycle names: {matchers}"
            )

    codex_hooks = json.loads(
        (root / "hosts" / "codex" / "hooks" / "hooks.json").read_text(encoding="utf-8")
    )["hooks"]
    spawn_matcher = r"^(((functions|collaboration)\.)?spawn_agent|multi_agent_v[0-9]+__spawn_agent)$"
    if [group.get("matcher") for group in codex_hooks.get("PreToolUse", [])] != [spawn_matcher]:
        raise ContractError("Codex PreToolUse must validate only native spawn_agent calls")
    post_matchers = [group.get("matcher") for group in codex_hooks.get("PostToolUse", [])]
    if spawn_matcher not in post_matchers:
        raise ContractError("Codex PostToolUse must bind native spawn_agent results")
    if len(codex_hooks.get("SubagentStop", [])) != 1:
        raise ContractError("Codex must register exactly one SubagentStop lifecycle hook")
    expected_windows_hooks = {
        "Stop": "pause_detect.py",
        "PreToolUse": "executor_router.py",
        "SubagentStop": "executor_router.py",
    }
    for event, script in expected_windows_hooks.items():
        for group in codex_hooks.get(event, []):
            for hook in group.get("hooks", []):
                command = hook.get("commandWindows", "")
                if script not in command or "${PLUGIN_ROOT}" not in command:
                    raise ContractError(
                        f"Codex {event} must register a PLUGIN_ROOT Windows command for {script}"
                    )
    for group in codex_hooks.get("PostToolUse", []):
        for hook in group.get("hooks", []):
            command = hook.get("commandWindows", "")
            if not command or "${PLUGIN_ROOT}" not in command:
                raise ContractError("every Codex PostToolUse hook needs a Windows command")
    if (root / "hosts" / "codex" / "agents" / "prewalk-executor.toml").exists():
        raise ContractError("Codex executor must be supplied by the native route, not an unused TOML")

def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        validate_repo(root)
    except (ContractError, json.JSONDecodeError) as exc:
        print(f"contract check failed: {exc}", file=sys.stderr)
        return 1
    print("static native contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
