from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import prewalk_engine as core  # noqa: E402


PACKET = """Preface retained exactly.
## Goal
Ship the checkpoint workflow.
## Files Read
core, adapters, and tests
## Constraints And Existing Patterns
Use the locked state store.
## Full Todo List
Three real tasks.
## Task 1 Changes
Implemented durable capture.
## Verification Already Run
- python3 -m unittest tests.test_v4_checkpoint: passed
## Remaining Work
Implement both native routes.
## Risks / Do Not Repeat
Do not reconstruct this packet.
"""


def todos(*, first: str = "completed", remaining: int = 2) -> list[core.Todo]:
    items = [core.Todo("1", "Implement capture and test it", first)]
    for index in range(remaining):
        items.append(core.Todo(str(index + 2), f"Update adapter {index} and verify it", "pending"))
    return items


class V4CheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.store = self.root / "state.json"
        self.session_id = "root-stop-session"
        self.preset = core.Preset("native", "executor-model", executor_effort="medium")
        core.start_v4_run(
            self.store, self.session_id, self.root, "codex", self.preset
        )

    def load(self) -> core.V4State | None:
        return core.load_v4_state(self.store, self.session_id).state

    def test_root_stop_persists_exact_packet_and_fresh_process_can_prepare_handoff(self) -> None:
        result = core.capture_v4_checkpoint(
            self.store,
            self.session_id,
            packet=PACKET,
            todos=todos(),
            event_id="root-stop-1",
        )

        self.assertEqual(result.status, "checkpoint_ready")
        self.assertEqual(result.state.packet, PACKET)
        self.assertEqual(result.state.verification_evidence, [
            "python3 -m unittest tests.test_v4_checkpoint: passed"
        ])

        script = """
import json, sys
sys.path.insert(0, sys.argv[1])
import prewalk_engine as core
result = core.v4_handoff_context(sys.argv[2], sys.argv[3])
print(json.dumps({"status": result.status, "message": result.message, "packet": result.state.packet}))
"""
        process = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                str(ROOT),
                str(self.store),
                self.session_id,
            ],
            text=True,
            capture_output=True,
            check=True,
        )
        loaded = json.loads(process.stdout)
        self.assertEqual(loaded["status"], "checkpoint_ready")
        self.assertEqual(loaded["packet"], PACKET)
        self.assertIn(PACKET, loaded["message"])

    def test_invalid_inputs_never_claim_checkpoint_ready(self) -> None:
        cases = [
            ("incomplete_task_one", todos(first="in_progress"), PACKET),
            (
                "invalid_todos",
                todos() + [core.Todo("pause", "PAUSE for handoff", "in_progress")],
                PACKET,
            ),
            ("invalid_packet", todos(), "## Goal\nMissing the other sections."),
            (
                "missing_evidence",
                todos(),
                PACKET.replace(
                    "- python3 -m unittest tests.test_v4_checkpoint: passed", ""
                ),
            ),
        ]

        for expected, snapshot, packet in cases:
            with self.subTest(expected=expected):
                result = core.capture_v4_checkpoint(
                    self.store,
                    self.session_id,
                    packet=packet,
                    todos=snapshot,
                )
                self.assertEqual(result.status, expected)
                self.assertEqual(self.load().phase, core.V4_PLANNING)

    def test_packet_without_todos_is_rejected_instead_of_treated_as_trivial(self) -> None:
        result = core.capture_v4_checkpoint(
            self.store, self.session_id, packet=PACKET
        )

        self.assertEqual(result.status, "missing_todos")
        self.assertEqual(self.load().phase, core.V4_PLANNING)

    def test_explicit_verification_warning_is_not_reported_as_evidence(self) -> None:
        packet = PACKET.replace(
            "- python3 -m unittest tests.test_v4_checkpoint: passed",
            "WARNING: no executable check was available for documentation-only task 1.",
        )

        result = core.capture_v4_checkpoint(
            self.store, self.session_id, packet=packet, todos=todos()
        )

        self.assertEqual(result.status, "checkpoint_ready")
        self.assertEqual(result.state.verification_evidence, [])
        self.assertIn("WARNING", result.state.verification_warning)

    def test_zero_or_one_remaining_stays_in_the_root_session(self) -> None:
        for remaining, expected in ((0, "complete"), (1, "one_remaining")):
            with self.subTest(remaining=remaining):
                core.start_v4_run(
                    self.store, self.session_id, self.root, "codex", self.preset
                )
                result = core.capture_v4_checkpoint(
                    self.store,
                    self.session_id,
                    packet=PACKET,
                    todos=todos(remaining=remaining),
                )
                self.assertEqual(result.status, expected)
                self.assertIsNone(self.load())

    def test_todo_updates_record_real_work_without_advancing_phase(self) -> None:
        recorded = core.record_v4_todos(self.store, self.session_id, todos())
        duplicate = core.record_v4_todos(self.store, self.session_id, todos())

        self.assertEqual(recorded.status, "recorded")
        self.assertEqual(duplicate.state.revision, recorded.state.revision)
        self.assertEqual(duplicate.state.phase, core.V4_PLANNING)
        self.assertEqual([item.id for item in duplicate.state.todos], ["1", "2", "3"])

    def test_revision_clears_packet_and_requires_a_new_root_stop(self) -> None:
        core.capture_v4_checkpoint(
            self.store, self.session_id, packet=PACKET, todos=todos()
        )

        revised = core.revise_v4_checkpoint(
            self.store, self.session_id, "Use the existing adapter helper."
        )

        self.assertEqual(revised.status, "planning")
        self.assertEqual(revised.state.phase, core.V4_PLANNING)
        self.assertEqual(revised.state.packet, "")
        self.assertEqual(revised.state.verification_evidence, [])
        self.assertIn("Use the existing adapter helper", revised.message)
        self.assertEqual(
            core.v4_handoff_context(self.store, self.session_id).status, "not_ready"
        )


if __name__ == "__main__":
    unittest.main()
