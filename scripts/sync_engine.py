#!/usr/bin/env python3
"""Keep the vendored engine copies byte-identical to the canonical package.

The plugin marketplaces install only a host subtree, so each host carries
its own copy of ``prewalk_engine`` under ``hooks/``. The canonical source
lives at the repository root; this script is the single sanctioned way to
propagate a change into the vendored copies.

  python scripts/sync_engine.py           # copy root package into both hosts
  python scripts/sync_engine.py --check   # exit 1 if any copy has drifted

Bytecode caches (``__pycache__``) are never copied.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "prewalk_engine"
VENDORED = [
    ROOT / "hosts" / "codex" / "hooks" / "prewalk_engine",
    ROOT / "hosts" / "claude" / "hooks" / "prewalk_engine",
]


def _relative_files(directory: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def sync(check_only: bool) -> int:
    canonical = _relative_files(CANONICAL)
    drifted = False
    for target in VENDORED:
        current = _relative_files(target) if target.is_dir() else {}
        if current == canonical:
            continue
        drifted = True
        if check_only:
            changed = sorted(set(current) ^ set(canonical)) + sorted(
                name for name in set(current) & set(canonical)
                if current[name] != canonical[name]
            )
            print(f"drifted: {target.relative_to(ROOT)} ({', '.join(changed)})")
        else:
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(CANONICAL, target, ignore=shutil.ignore_patterns("__pycache__"))
            print(f"synced: {target.relative_to(ROOT)} ({len(canonical)} files)")
    if check_only and drifted:
        print("run scripts/sync_engine.py to refresh the vendored copies", file=sys.stderr)
        return 1
    if not check_only:
        print(f"engine package synced to {len(VENDORED)} host(s)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify instead of copying")
    return sync(check_only=parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
