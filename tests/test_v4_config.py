from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import prewalk_engine as core  # noqa: E402


class V4ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def test_executor_only_json_preset_never_requires_a_planner(self) -> None:
        path = self.root / "presets.json"
        path.write_text(json.dumps({
            "default": "native",
            "presets": {
                "native": {
                    "executor": "sonnet",
                    "max_todos": 9,
                    "handoff_mode": "spawn",
                    "require_model_routing": True,
                }
            },
        }), encoding="utf-8")

        preset = core.load_presets_json(path)["native"]

        self.assertEqual(preset.executor_model, "sonnet")
        self.assertEqual(preset.planner_model, "active-session")
        self.assertEqual(preset.planner_thinking, "")
        self.assertEqual(preset.deprecation_warnings, [])

    def test_toml_preset_names_accept_model_style_dots(self) -> None:
        path = self.root / "presets.toml"
        path.write_text(
            '\n'.join([
                'default_preset = "grok-4.6"',
                '[presets."grok-4.6"]',
                'executor = "grok-4.6"',
                '',
                '[presets.compat.v1]',
                'executor = "gpt-5.6-terra"',
            ]),
            encoding="utf-8",
        )

        presets = core.load_presets_toml(path)

        self.assertEqual(set(presets), {"grok-4.6", "compat.v1"})
        self.assertEqual(presets["grok-4.6"].executor_model, "grok-4.6")
        self.assertEqual(core.default_preset_toml(path), "grok-4.6")

    def test_legacy_planner_fields_load_only_as_deprecation_warnings(self) -> None:
        path = self.root / "presets.json"
        path.write_text(json.dumps({
            "presets": {
                "legacy": {
                    "planner": "opus",
                    "planner_thinking": "high",
                    "executor": "haiku",
                    "executor_thinking": "low",
                }
            },
        }), encoding="utf-8")

        preset = core.load_presets_json(path)["legacy"]

        self.assertEqual(preset.executor_model, "haiku")
        self.assertEqual(preset.executor_effort, "low")
        self.assertEqual(len(preset.deprecation_warnings), 3)
        self.assertNotIn("opus", core.format_capability_report(
            core.evaluate_capabilities(preset, "claude", environment={})
        ))

    def test_codex_capabilities_change_only_with_the_live_schema(self) -> None:
        preset = core.Preset(
            "native", "gpt-5.6-terra", executor_effort="medium",
            require_model_routing=True,
        )

        unknown = core.evaluate_capabilities(preset, "codex")
        self.assertEqual(unknown.model_requested, "pending-live-schema")
        self.assertEqual(unknown.model_proven, "unproven")
        self.assertEqual(unknown.effort_proven, "unproven")

        supported = core.evaluate_capabilities(
            preset, "codex", schema_fields={"task_name", "message", "model", "reasoning_effort"}
        )
        self.assertTrue(supported.routing_allowed)
        self.assertEqual(supported.model_requested, "yes")
        self.assertEqual(supported.model_proven, "supported")
        self.assertEqual(supported.effort_requested, "yes")
        self.assertEqual(supported.effort_proven, "supported")

        no_controls = core.evaluate_capabilities(
            preset, "codex", schema_fields={"task_name", "message"}
        )
        self.assertFalse(no_controls.routing_allowed)
        self.assertEqual(no_controls.model_requested, "no")
        self.assertEqual(no_controls.effort_requested, "no")
        self.assertIn("cannot prove", no_controls.errors[0])

    def test_claude_effort_is_never_reported_as_applied(self) -> None:
        preset = core.Preset("native", "sonnet", executor_effort="high")

        report = core.evaluate_capabilities(preset, "claude", environment={})

        self.assertTrue(report.routing_allowed)
        self.assertEqual(report.model_proven, "hook-rewrite")
        self.assertEqual(report.effort_requested, "no")
        self.assertEqual(report.effort_proven, "unsupported")
        self.assertTrue(any("does not expose" in warning for warning in report.warnings))

    def test_claude_conflicting_subagent_override_fails_closed_when_required(self) -> None:
        required = core.Preset("native", "sonnet", require_model_routing=True)
        conflict = core.evaluate_capabilities(
            required,
            "claude",
            environment={"CLAUDE_CODE_SUBAGENT_MODEL": "haiku"},
        )
        self.assertFalse(conflict.routing_allowed)
        self.assertEqual(conflict.model_proven, "override-conflict")
        self.assertIn("conflicts", conflict.errors[0])

        optional = core.Preset("native", "sonnet", require_model_routing=False)
        overridden = core.evaluate_capabilities(
            optional,
            "claude",
            environment={"CLAUDE_CODE_SUBAGENT_MODEL": "haiku"},
        )
        self.assertTrue(overridden.routing_allowed)
        self.assertEqual(overridden.model_proven, "overridden")
        self.assertIn("conflicts", overridden.warnings[0])


if __name__ == "__main__":
    unittest.main()
