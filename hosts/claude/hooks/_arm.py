#!/usr/bin/env python3
"""Skill-side helper for the Claude Code host: arm, status, disarm, doctor.

Invoked by the ``/prewalk`` skills:

  _arm.py arm    <session_id> [--preset NAME] [--fast] [task ...]
  _arm.py status <session_id>
  _arm.py disarm <session_id>
  _arm.py doctor <session_id>

Presets are read from ``~/.claude/prewalk-presets.json``; durable state is
written to ``~/.claude/prewalk-state.json`` (the same store the hook scripts
use). Unlike Codex, arm *gates* on routing capability: if the executor model
cannot be proven reachable (hook rewrite or ``CLAUDE_CODE_SUBAGENT_MODEL``),
arming fails rather than promising a handoff that cannot land.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

import _engine  # noqa: F401  (locates prewalk_engine)
import _common  # type: ignore[import-not-found]  # noqa: E402
import prewalk_engine as core  # noqa: E402


# ---------------------------------------------------------------- arm --------


def _parse_args(rest: list[str]) -> tuple[str | None, bool]:
    """Split leading options off the front of a freeform ``arm`` command line.

    Skills deliver ``$ARGUMENTS`` as one quoted blob; humans may pass separate
    argv tokens. Both forms are accepted here, and option parsing stops at the
    first bare token — everything after that is task text.
    """
    tokens = shlex.split(rest[0]) if len(rest) == 1 else rest
    auto_swap = False
    preset: str | None = None
    index = 0
    while index < len(tokens):
        tok = tokens[index]
        if tok == "--":
            break
        if tok in ("--no-pause", "--fast"):
            auto_swap = True
        elif tok == "--preset":
            if index + 1 >= len(tokens):
                raise ValueError("--preset requires a name")
            index += 1
            preset = tokens[index]
        elif tok.startswith("--preset="):
            preset = tok.partition("=")[2]
            if not preset:
                raise ValueError("--preset requires a name")
        else:
            break
        index += 1
    return preset, auto_swap


def cmd_arm(session_id: str, rest: list[str]) -> int:
    session_id = _common.resolve_session_id(session_id)
    if not session_id:
        print("prewalk: cannot arm — could not determine the session id. "
              "Ensure the SessionStart hook (export_session_id.py) is registered, "
              "or pass the id explicitly: _arm.py arm <session_id> ...",
              file=sys.stderr)
        return 1
    try:
        preset_name, auto_swap = _parse_args(rest)
    except (ValueError, shlex.Error) as exc:
        print(f"prewalk: invalid arm arguments: {exc}", file=sys.stderr)
        return 2

    # No user presets on disk? Warn and continue with a sane built-in pair
    # rather than refusing to arm — the run is still useful without routing.
    presets_path = _common.presets_file()
    presets = core.load_presets_json(presets_path)
    if not presets:
        print(
            "prewalk: no presets found at " + presets_path + ". Copy "
            "hosts/claude/presets.example.json there first. Falling back to built-in defaults.",
            file=sys.stderr,
        )
        preset = core.Preset(
            name="default",
            executor_model="haiku",
            description="built-in fallback",
            max_todos=core.DEFAULT_MAX_TODOS,
        )
    else:
        name = preset_name or core.default_preset_json(presets_path)
        preset = presets.get(name)
        if preset is None:
            available = ", ".join(sorted(presets))
            print(
                f"prewalk: unknown preset {name!r}; available presets: {available}.",
                file=sys.stderr,
            )
            return 2

    report = core.evaluate_capabilities(preset, "claude", environment=dict(os.environ))
    if not report.routing_allowed:
        print("prewalk: cannot arm because required executor routing is not provable.", file=sys.stderr)
        print(core.format_capability_report(report), file=sys.stderr)
        return 1
    try:
        core.start_v4_run(
            _common.store_file(), session_id, os.getcwd(), "claude", preset, fast_mode=auto_swap
        )
    except OSError as exc:
        print(
            "prewalk: cannot arm because the durable state store is not writable: "
            f"{_common.store_file()} ({exc}).",
            file=sys.stderr,
        )
        print(
            "Grant write access, or set PREWALK_STATE_FILE to one absolute path inherited "
            "by Claude Code and all plugin hooks. No Prewalk checkpoint was created.",
            file=sys.stderr,
        )
        return 1
    print(f"prewalk ARMED  [{preset.name}]  auto_swap={auto_swap}")
    print("  planner : active root session (Prewalk does not change it)")
    print(f"  handoff : {preset.handoff_mode} (model routing required={preset.require_model_routing})")
    print(core.format_capability_report(report))
    print()
    print("Continue in this active session and follow /prewalk:prewalk.")
    return 0


# ------------------------------------------------------------- doctor -------


MIN_CLAUDE_VERSION = (2, 1, 145)


def _cli_executable(name: str) -> str:
    """Resolve npm command shims on Windows without requiring a shell."""
    candidates = (f"{name}.cmd", f"{name}.exe", name) if os.name == "nt" else (name,)
    return next((path for item in candidates if (path := shutil.which(item))), name)


def _claude_version() -> tuple[tuple[int, int, int] | None, str]:
    """Ask the ``claude`` binary for its version, tolerating any output shape."""
    try:
        result = subprocess.run(
            [_cli_executable("claude"), "--version"],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None, "not found"
    lines = (result.stdout or result.stderr or "").strip().splitlines()
    detail = lines[-1] if lines else f"exit {result.returncode} with no output"
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", detail)
    return (tuple(map(int, match.groups())) if match else None), detail


def cmd_doctor(given_session_id: str) -> int:
    failures = 0

    def check(ok: bool, label: str, detail: str = "") -> None:
        nonlocal failures
        print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f": {detail}" if detail else ""))
        failures += 0 if ok else 1

    check(sys.version_info >= (3, 10), "Python", sys.version.split()[0])
    check(core.VERSION == "1.0.6", "shared core", core.VERSION)
    version, version_text = _claude_version()
    check(
        version is not None and version >= MIN_CLAUDE_VERSION,
        "Claude Code >= 2.1.145",
        version_text,
    )
    resolved = _common.resolve_session_id(given_session_id)
    check(
        bool(resolved),
        "root session identity",
        "SessionStart identity available" if resolved else "missing; restart after plugin install",
    )
    presets_path = Path(_common.presets_file())
    presets = core.load_presets_json(presets_path)
    if presets_path.is_file():
        check(bool(presets), "preset parse", f"{len(presets)} preset(s) in {presets_path}")
    else:
        print(f"WARN  preset file: {presets_path} is absent; built-in defaults will be used")
    for preset_name, configured in presets.items():
        check(
            bool(configured.executor_model.strip()),
            f"model catalog/config [{preset_name}]",
            configured.executor_model or "missing executor model",
        )
        for warning in configured.deprecation_warnings:
            print(f"WARN  config deprecation [{preset_name}]: {warning}")
    manifest = Path(__file__).resolve().with_name("hooks.json")
    try:
        hooks = json.loads(manifest.read_text(encoding="utf-8"))["hooks"]
        required_events = {
            "PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionDenied",
            "SubagentStart", "SubagentStop", "Stop", "SessionStart",
        }
        lifecycle_matcher = "^(prewalk:)?prewalk-executor$"
        manifest_ok = required_events.issubset(hooks) and all(
            [group.get("matcher") for group in hooks[event]] == [lifecycle_matcher]
            for event in ("SubagentStart", "SubagentStop")
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        manifest_ok = False
    check(manifest_ok, "plugin hooks", str(manifest))
    store_ok, store_detail = _common.state_store_access()
    check(store_ok, "state store", store_detail)
    preset = (
        presets.get(core.default_preset_json(presets_path)) or next(iter(presets.values()))
        if presets else core.Preset("default", "haiku")
    )
    report = core.evaluate_capabilities(preset, "claude", environment=dict(os.environ))
    print(core.format_capability_report(report))
    check(report.routing_allowed, "live executor routing", report.model_proven)
    print("WARN  model catalog API: Claude exposes no non-billable catalog; availability is launch-time")
    print("PASS  model availability policy: configured IDs are validated by Claude at Agent launch")
    return 1 if failures else 0


# --------------------------------------------------------------- main --------


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    sub, session_id = sys.argv[1], sys.argv[2]
    rest = sys.argv[3:]
    store = _common.store_file()
    if sub == "arm":
        return cmd_arm(session_id, rest)
    if sub == "status":
        workspace_id = core.workspace_identity(os.getcwd())
        core.detect_v4_stale(store, session_id, workspace_id=workspace_id)
        loaded = core.load_v4_state(
            store, session_id, workspace_id=workspace_id
        )
        print(_common.claude_commands(
            core.format_v4_status(loaded, host="claude")
        ))
        return 0
    if sub == "disarm":
        print(core.disarm(store, session_id))
        return 0
    if sub == "doctor":
        return cmd_doctor(session_id)
    print("unknown subcommand: " + sub, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
