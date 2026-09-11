"""Read-only replay of one real final packet through old/new hook input readers."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    journal, ordinal, old_hooks, new_hooks, temp_root = sys.argv[1:]
    records = [json.loads(line) for line in Path(journal).read_text(encoding="utf-8").splitlines()]
    event = next(e for e in records if e.get("ordinal") == int(ordinal))
    packet = "\n".join(p["text"] for p in event["payload"]["content"] if "text" in p)
    expected = hashlib.sha256(packet.encode("utf-8")).hexdigest()
    wire = json.dumps({"hook_event_name": "Stop", "session_id": "wire-test",
                       "last_assistant_message": packet}, ensure_ascii=False).encode("utf-8")
    env = dict(os.environ)
    env.pop("PYTHONIOENCODING", None)
    env.pop("PYTHONUTF8", None)
    script = ("import _common,hashlib,json; p=_common.read_input(); "
              "print(json.dumps({'sha256':hashlib.sha256(p['last_assistant_message'].encode('utf-8')).hexdigest()}))")
    results = {}
    for name, hooks in (("old", old_hooks), ("new", new_hooks)):
        result = subprocess.run([sys.executable, "-c", script], cwd=hooks, env=env,
                                input=wire, capture_output=True, timeout=20)
        results[name] = {"exit_code": result.returncode,
                         "stdout": result.stdout.decode("ascii", errors="replace").strip(),
                         "error_tail": result.stderr.decode("ascii", errors="replace").splitlines()[-1:]}
    print(json.dumps({"expected_sha256": expected, "results": results}, indent=2))
    assert results["new"]["exit_code"] == 0
    assert json.loads(results["new"]["stdout"])["sha256"] == expected
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import prewalk_engine as core
    for name, hooks in (("old", old_hooks), ("new", new_hooks)):
        with tempfile.TemporaryDirectory(prefix="wire-stop-", dir=temp_root) as directory:
            store = Path(directory) / "state.json"
            core.start_v4_run(store, "wire-test", directory, "codex", core.Preset("luna", "gpt-5.6-luna"))
            child_env = dict(env, CODEX_THREAD_ID="wire-test", PREWALK_STATE_FILE=str(store))
            result = subprocess.run([sys.executable, str(Path(hooks) / "pause_detect.py")],
                cwd=directory, env=child_env, input=wire, capture_output=True, timeout=20)
            phase = core.load_v4_state(store, "wire-test").state.phase
            print(json.dumps({"stop_adapter": name, "exit_code": result.returncode,
                              "phase": phase, "error_tail": result.stderr.decode("ascii", errors="replace").splitlines()[-1:]}))
            if name == "new":
                assert result.returncode == 0 and phase == "checkpoint_ready"


if __name__ == "__main__":
    main()
