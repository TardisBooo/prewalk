"""Read-only native evidence checks for the opt-in acceptance fixture."""
import json
import os
from pathlib import Path
import sys


def events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def inspect(root, mode):
    cli = events(root / f"{mode}-events.jsonl")
    sid = next(e["thread_id"] for e in cli if e.get("type") == "thread.started")
    sessions = Path(os.environ["CODEX_HOME"]) / "sessions"
    paths = list(sessions.rglob(f"*-{sid}.jsonl"))
    assert len(paths) == 1, "ambiguous root"
    native = events(paths[0])
    contexts = [e["payload"] for e in native if e.get("type") == "turn_context"]
    assert contexts and all(c["sandbox_policy"]["type"] == "workspace-write" for c in contexts)
    children = []
    for path in paths[0].parent.glob("*.jsonl"):
        with path.open(encoding="utf-8") as stream:
            line = stream.readline()
        if not line.strip():
            continue
        meta = json.loads(line).get("payload", {})
        source = meta.get("source", {})
        if not isinstance(source, dict):
            continue
        spawn = source.get("subagent", {}).get("thread_spawn", {})
        if spawn.get("parent_thread_id") != sid:
            continue
        child = events(path)
        turns = [e["payload"] for e in child if e.get("type") == "turn_context"]
        terminals = [e["payload"] for e in child if e.get("type") == "event_msg" and e.get("payload", {}).get("type") == "task_complete"]
        assert turns and all(t.get("model") == "gpt-5.6-luna" and t.get("effort") == "max" for t in turns)
        assert terminals and "PREWALK_COMPLETE" in terminals[-1].get("last_agent_message", "")
        children.append({"id": meta["id"], "model": "gpt-5.6-luna", "effort": "max", "journal": str(path)})
    assert len(children) == 1, f"expected one child, got {len(children)}"
    state = json.loads((root / ".prewalk/state.json").read_text(encoding="utf-8"))
    assert sid not in state, "active state not closed"
    checks = {name: (root / f"{name}.txt").read_text(encoding="utf-8").rstrip("\r\n") == name for name in ("two", "three")}
    assert all(checks.values()), "file content mismatch"
    return {"mode": mode, "root_session": sid, "root_journal": str(paths[0]),
            "sandbox": "workspace-write", "children": children, "content_checks": checks,
            "state_closed": True}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(inspect(Path(sys.argv[1]), sys.argv[2]), indent=2))
