#!/usr/bin/env python3
"""Record and compare local baseline/prewalk task runs without telemetry."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys


def _record(args: argparse.Namespace) -> int:
    record = {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "task": args.task,
        "input_tokens": args.input_tokens,
        "output_tokens": args.output_tokens,
        "duration_seconds": args.duration_seconds,
        "passed": args.passed,
        "notes": args.notes,
    }
    path = Path(args.file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"recorded {args.mode} run for {args.task!r} in {path}")
    return 0


def _load(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: {exc.msg}") from exc
            if value.get("mode") not in ("baseline", "prewalk"):
                raise ValueError(f"{path}:{line_number}: invalid mode")
            records.append(value)
    return records


def _mean(records: list[dict], key: str) -> float:
    return statistics.fmean(float(record.get(key, 0)) for record in records)


def _report(args: argparse.Namespace) -> int:
    path = Path(args.file)
    try:
        records = _load(path)
    except (OSError, ValueError) as exc:
        print(f"benchmark: {exc}", file=sys.stderr)
        return 1
    if not records:
        print("benchmark: no records", file=sys.stderr)
        return 1

    groups = {mode: [record for record in records if record["mode"] == mode]
              for mode in ("baseline", "prewalk")}
    print("mode      runs  pass-rate  avg-total-tokens  avg-seconds")
    for mode, group in groups.items():
        if not group:
            continue
        pass_rate = sum(bool(record.get("passed")) for record in group) / len(group)
        tokens = _mean(group, "input_tokens") + _mean(group, "output_tokens")
        print(f"{mode:<9} {len(group):>4}  {pass_rate:>8.1%}  {tokens:>16.1f}  {_mean(group, 'duration_seconds'):>11.1f}")

    if groups["baseline"] and groups["prewalk"]:
        baseline_tokens = _mean(groups["baseline"], "input_tokens") + _mean(
            groups["baseline"], "output_tokens"
        )
        prewalk_tokens = _mean(groups["prewalk"], "input_tokens") + _mean(
            groups["prewalk"], "output_tokens"
        )
        delta = ((prewalk_tokens / baseline_tokens) - 1) * 100 if baseline_tokens else 0
        print(f"prewalk token delta vs baseline: {delta:+.1f}%")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record", help="append one run to a JSONL file")
    record.add_argument("file")
    record.add_argument("--mode", choices=("baseline", "prewalk"), required=True)
    record.add_argument("--task", required=True)
    record.add_argument("--input-tokens", type=int, required=True)
    record.add_argument("--output-tokens", type=int, required=True)
    record.add_argument("--duration-seconds", type=float, required=True)
    outcome = record.add_mutually_exclusive_group(required=True)
    outcome.add_argument("--passed", dest="passed", action="store_true")
    outcome.add_argument("--failed", dest="passed", action="store_false")
    record.add_argument("--notes", default="")
    record.set_defaults(func=_record)

    report = commands.add_parser("report", help="summarize baseline and prewalk runs")
    report.add_argument("file")
    report.set_defaults(func=_report)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
