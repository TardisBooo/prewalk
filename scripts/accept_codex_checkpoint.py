"""Opt-in real Codex smoke run; no benchmarks and no configuration overrides.

Usage: python scripts/accept_codex_checkpoint.py <fixture> manual|fast|go <session?>
The fixture must already exist. Logs are generated inside it. This spends model
tokens only when explicitly invoked, never from the unit-test suite.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    root = Path(sys.argv[1]).resolve()
    mode = sys.argv[2]
    if mode not in ("manual", "fast", "go") or not (root / "README.md").is_file():
        raise ValueError("expected an existing acceptance fixture and manual|fast|go")
    if mode == "go":
        prompt = "$prewalk:pw-go"
    else:
        first = ("1. 仅验证当前目录是 Git 工作区，并读取 README.md，作为任务一。"
                 if mode == "manual" else
                 "1. 阅读 README.md，在末尾添加一行 planner verified，再读取确认，作为任务一。")
        prompt = ("$prewalk:prewalk --preset gpt-5.6-luna " + ("--fast " if mode == "fast" else "") +
                  "按 README.md 完成三个任务。这是显式交接验收，不要以任务小为由跳过 Prewalk。" + first +
                  "2. 交给执行器创建 two.txt，内容为 two，并读取验证。"
                  "3. 交给执行器创建 three.txt，内容为 three，并读取验证。"
                  "根助手只做任务一，不得代做二、三；不运行 benchmark、不联网研究、不改全局配置。" +
                  "这是临时验收夹具，Git 提交和日志归测试宿主管理，不属于根助手或执行器待办，不得加入交接包。" +
                  "交接包正文请使用中文，协议标题保留英文。" +
                  ("完成计划后停下来，等我另发 pw-go。" if mode == "manual" else "按 --fast 自动交接直到完成。"))
    executable = shutil.which("codex.cmd") or shutil.which("codex")
    cmd = [executable, "exec", "-s", "workspace-write", "-C", str(root)]
    if mode == "go":
        cmd += ["resume", sys.argv[3]]
    cmd += ["--json", "-o", str(root / f"{mode}-last.txt"), prompt]
    env = dict(os.environ)
    for name in ("CODEX_THREAD_ID", "CODEX_SESSION_ID", "PREWALK_STATE_FILE", "PREWALK_ENGINE",
                 "PYTHONIOENCODING", "PYTHONUTF8"):
        env.pop(name, None)
    with (root / f"{mode}-events.jsonl").open("w", encoding="utf-8") as output, \
         (root / f"{mode}-stderr.txt").open("w", encoding="utf-8") as errors:
        result = subprocess.run(cmd, cwd=root, env=env, stdout=output, stderr=errors, timeout=900)
    print(json.dumps({"exit_code": result.returncode, "mode": mode, "fixture": str(root)}))
    print((root / f"{mode}-last.txt").read_text(encoding="utf-8") if
          (root / f"{mode}-last.txt").exists() else "No final message")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
