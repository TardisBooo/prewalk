from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "tests" / "fixtures" / "native_workflow_contracts.json"


def test_inventory() -> set[str]:
    inventory: set[str] = set()
    for path in (ROOT / "tests").glob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name.startswith("test_"):
                    inventory.add(f"{path.stem}.{node.name}.{member.name}")
    return inventory


class NativeWorkflowMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_host_fixtures_are_versioned_and_schema_derived(self) -> None:
        self.assertEqual(self.contract["schema_version"], 1)
        self.assertEqual(set(self.contract["hosts"]), {"codex", "claude"})
        for host, contract in self.contract["hosts"].items():
            with self.subTest(host=host):
                self.assertRegex(contract["minimum_version"], r"^\d+\.\d+\.\d+$")
                self.assertIn(contract["source"]["kind"], {"generated", "documented"})
                self.assertTrue(contract["events"])

    def test_documented_event_examples_contain_every_required_field(self) -> None:
        for host, contract in self.contract["hosts"].items():
            for event, schema in contract["events"].items():
                with self.subTest(host=host, event=event):
                    self.assertEqual(schema["example"]["hook_event_name"], event)
                    self.assertFalse(set(schema["required"]) - set(schema["example"]))

    def test_codex_spawn_fixture_proves_model_and_optional_effort_routing(self) -> None:
        spawn = self.contract["hosts"]["codex"]["spawn_agent"]
        self.assertFalse(set(spawn["required"]) - set(spawn["example"]))
        self.assertFalse(set(spawn["optional"]) - set(spawn["example"]))
        self.assertEqual(spawn["example"]["fork_turns"], "all")
        self.assertTrue(spawn["example"]["model"])

    def test_every_required_matrix_scenario_resolves_to_executable_tests(self) -> None:
        required = {
            "foreground_and_background",
            "concurrent_and_foreign_events",
            "compaction_resume_durable_and_v3_reset",
            "routing_and_permission_failures",
            "launch_interrupt_marker_and_stale",
            "trivial_one_remaining_normal_and_fast",
            "plugin_install_upgrade_and_core_equivalence",
        }
        scenarios = self.contract["matrix"]["scenarios"]
        self.assertEqual(set(scenarios), required)
        inventory = test_inventory()
        for scenario, tests in scenarios.items():
            with self.subTest(scenario=scenario):
                self.assertTrue(tests)
                self.assertFalse(set(tests) - inventory)

    def test_native_ci_matrix_covers_both_hosts_os_families_and_version_tracks(self) -> None:
        matrix = self.contract["matrix"]
        self.assertEqual(set(matrix["operating_systems"]), {"ubuntu-latest", "macos-latest"})
        self.assertEqual(set(matrix["version_tracks"]), {"minimum", "latest"})
        workflow = (ROOT / ".github" / "workflows" / "check.yml").read_text(encoding="utf-8")
        for value in (*matrix["operating_systems"], "2.1.145", "0.146.0", "latest"):
            self.assertIn(value, workflow)
        self.assertIn('PREWALK_REQUIRE_NATIVE_CLIS: "1"', workflow)

    def test_native_cli_contract_executes_install_version_and_clean_upgrade_checks(self) -> None:
        script = (ROOT / "scripts" / "check_native_clis.sh").read_text(encoding="utf-8")
        for required in (
            "claude plugin validate --strict",
            "claude plugin marketplace add",
            "codex plugin marketplace add",
            "assert_plugin_version",
            "prepare_upgrade_fixture",
            "0.3.1",
            "1.0.7",
            "PREWALK_REQUIRE_NATIVE_CLIS",
        ):
            self.assertIn(required, script)
        self.assertNotIn("SKIP native contracts: covered", script)

    def test_codex_hooks_have_native_windows_commands(self) -> None:
        hooks = json.loads((ROOT / "hosts" / "codex" / "hooks" / "hooks.json").read_text(encoding="utf-8"))[
            "hooks"
        ]
        commands = [
            hook["commandWindows"]
            for groups in hooks.values()
            for group in groups
            for hook in group["hooks"]
        ]
        self.assertEqual(len(commands), 6)
        self.assertTrue(all("${PLUGIN_ROOT}" in command for command in commands))
        self.assertTrue(all("$env:" not in command and not command.startswith("& ") for command in commands))
        self.assertTrue(any("pause_detect.py" in command for command in commands))
        self.assertTrue(any("todo_tracker.py" in command for command in commands))
        self.assertTrue(any("edit_tracker.py" in command for command in commands))
        self.assertEqual(sum("executor_router.py" in command for command in commands), 3)


if __name__ == "__main__":
    unittest.main()
