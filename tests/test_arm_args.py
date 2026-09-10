from __future__ import annotations

import io
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HOSTS = ROOT / "hosts"

# Everything a host's ``_arm`` pulls in transitively; evicted before and
# after each load so hosts never share a cached engine copy.
_MANAGED = ("_engine", "_common", "prewalk_engine")


def _evict_managed() -> dict[str, object]:
    saved = {}
    for name in list(sys.modules):
        if name in _MANAGED or name.startswith("prewalk_engine."):
            saved[name] = sys.modules.pop(name)
    return saved


def load_arm(host: str):
    hooks = HOSTS / host / "hooks"
    saved_modules = _evict_managed()
    sys.path.insert(0, str(hooks))
    try:
        spec = importlib.util.spec_from_file_location(f"{host}_arm", hooks / "_arm.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)
        _evict_managed()
        sys.modules.update(saved_modules)


class ArmArgumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.modules = {host: load_arm(host) for host in ("codex", "claude")}
        cls.parsers = [module._parse_args for module in cls.modules.values()]

    def assert_parses(self, arguments: list[str], expected: tuple[str | None, bool]) -> None:
        for parse in self.parsers:
            with self.subTest(parser=parse.__module__, arguments=arguments):
                self.assertEqual(parse(arguments), expected)

    def test_freeform_task_never_selects_a_preset(self) -> None:
        self.assert_parses(["code-value refactor the hook"], (None, False))
        self.assert_parses(["fast", "refactor", "the", "hook"], (None, False))

    def test_quoted_skill_arguments_detect_leading_options(self) -> None:
        self.assert_parses(
            ["--preset code-value --no-pause refactor the hook"],
            ("code-value", True),
        )
        self.assert_parses(["--fast refactor the hook"], (None, True))

    def test_task_text_stops_option_parsing(self) -> None:
        self.assert_parses(["document --no-pause and --preset fast"], (None, False))
        self.assert_parses(["--", "--preset", "fast"], (None, False))

    def test_explicit_preset_forms(self) -> None:
        self.assert_parses(["--preset", "fast", "task"], ("fast", False))
        self.assert_parses(["--preset=fast", "task"], ("fast", False))

    def test_missing_preset_name_is_rejected(self) -> None:
        for parse in self.parsers:
            with self.subTest(parser=parse.__module__):
                with self.assertRaisesRegex(ValueError, "requires a name"):
                    parse(["--preset"])

    def test_codex_catalog_extracts_native_model_slugs(self) -> None:
        parse = self.modules["codex"]._codex_catalog_ids
        self.assertEqual(
            parse({"models": [{"slug": "gpt-5.6-sol"}, {"slug": " gpt-5.6-terra "}]}),
            {"gpt-5.6-sol", "gpt-5.6-terra"},
        )

    def test_codex_catalog_rejects_missing_or_empty_models(self) -> None:
        parse = self.modules["codex"]._codex_catalog_ids
        for payload in ({}, {"models": []}, {"models": [{"display_name": "unknown"}]}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    parse(payload)

    def test_codex_catalog_decode_failure_is_a_warning_not_a_crash(self) -> None:
        module = self.modules["codex"]
        completed = mock.Mock(returncode=0, stdout=None, stderr=None)
        with mock.patch.object(module.subprocess, "run", return_value=completed) as run:
            models, detail = module._codex_model_catalog()
        self.assertIsNone(models)
        self.assertIn("invalid response", detail)
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(run.call_args.kwargs["errors"], "replace")

    def test_unknown_preset_fails_instead_of_silently_falling_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = {
                "codex": root / "presets.toml",
                "claude": root / "presets.json",
            }
            paths["codex"].write_text(
                'default_preset = "known"\n[presets.known]\nexecutor = "executor"\n',
                encoding="utf-8",
            )
            paths["claude"].write_text(
                '{"default": "known", "presets": {"known": {"executor": "haiku"}}}',
                encoding="utf-8",
            )
            for host, module in self.modules.items():
                with self.subTest(host=host), mock.patch.object(
                    module._common, "resolve_session_id", return_value="session"
                ), mock.patch.object(
                    module._common, "presets_file", return_value=str(paths[host])
                ), mock.patch.object(module.core, "start_v4_run") as start, mock.patch(
                    "sys.stderr", new_callable=io.StringIO
                ) as stderr:
                    self.assertEqual(module.cmd_arm("session", ["--preset", "missing"]), 2)
                    self.assertIn("unknown preset 'missing'", stderr.getvalue())
                    start.assert_not_called()

    def test_arm_reports_state_permission_failure_without_traceback(self) -> None:
        for host, module in self.modules.items():
            with self.subTest(host=host), mock.patch.object(
                module._common, "resolve_session_id", return_value="session"
            ), mock.patch.object(
                module._common, "presets_file", return_value="missing-presets"
            ), mock.patch.object(
                module._common, "store_file", return_value="X:/blocked/prewalk-state.json"
            ), mock.patch.object(
                module.core, "start_v4_run", side_effect=PermissionError(13, "denied")
            ), mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                self.assertEqual(module.cmd_arm("session", ["Build and test feature"]), 1)
                output = stderr.getvalue()
                self.assertIn("durable state store is not writable", output)
                self.assertIn("No Prewalk checkpoint was created", output)
                self.assertNotIn("Traceback", output)

    def test_windows_cli_resolution_prefers_cmd_shims(self) -> None:
        pairs = (("codex", self.modules["codex"]), ("claude", self.modules["claude"]))
        for name, module in pairs:
            expected = f"C:/tools/{name}.cmd"

            def resolve(candidate: str, *, expected=expected, name=name):
                return expected if candidate == f"{name}.cmd" else None

            with self.subTest(name=name), mock.patch.object(module.os, "name", "nt"), mock.patch.object(
                module.shutil, "which", side_effect=resolve
            ):
                self.assertEqual(module._cli_executable(name), expected)


if __name__ == "__main__":
    unittest.main()
