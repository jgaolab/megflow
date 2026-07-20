import ast
import os
import re
import shlex
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
UNITTEST_GATE = REPO_ROOT / "scripts" / "validation" / "run_unittest_gate.py"
VALIDATION_RUNNER = REPO_ROOT / "scripts" / "validation" / "run_validation.sh"
WINDOWS_INSTALL_VALIDATOR = REPO_ROOT / "scripts" / "validation" / "validate_windows_installer.py"
ROUTING_CONTRACT_TEST = REPO_ROOT / "tests" / "test_nextflow_execution_config.py"


class ValidationRunnerTests(unittest.TestCase):
    def run_gate(self, module_name, fixture_text):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir = Path(temp_dir)
            (temp_dir / f"{module_name}.py").write_text(
                textwrap.dedent(fixture_text), encoding="utf-8"
            )
            env = dict(os.environ)
            env["PYTHONPATH"] = os.pathsep.join(
                part
                for part in (str(temp_dir), env.get("PYTHONPATH", ""))
                if part
            )
            return subprocess.run(
                [sys.executable, str(UNITTEST_GATE), module_name],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
            )

    def test_unittest_gate_rejects_skipped_tests(self):
        result = self.run_gate(
            "deliberately_skipped_validation_fixture",
            """
            import unittest

            class DeliberatelySkippedTest(unittest.TestCase):
                @unittest.skip("deliberate validation sentinel")
                def test_must_not_be_silently_green(self):
                    self.fail("skip sentinel unexpectedly ran")
            """,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("Unexpected skipped tests", result.stderr)
        self.assertIn("deliberate validation sentinel", result.stderr)

    def test_unittest_gate_rejects_an_empty_suite(self):
        result = self.run_gate(
            "empty_validation_fixture",
            """
            VALUE = 1
            """,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("discovered zero tests", result.stderr)

    def test_mandatory_routing_contracts_do_not_conditionally_skip(self):
        text = ROUTING_CONTRACT_TEST.read_text(encoding="utf-8")
        self.assertNotIn("self.skipTest", text)
        self.assertNotIn("not packaged in the image", text)

    def test_every_tracked_test_module_uses_unittest_discovery(self):
        tracked_tests = subprocess.run(
            ["git", "ls-files", "tests/test_*.py"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        undiscoverable = []
        for relative_path in tracked_tests.stdout.splitlines():
            text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
            tree = ast.parse(text, filename=relative_path)
            has_test_case = any(
                isinstance(node, ast.ClassDef)
                and any(
                    (
                        isinstance(base, ast.Attribute)
                        and base.attr == "TestCase"
                    )
                    or (isinstance(base, ast.Name) and base.id == "TestCase")
                    for base in node.bases
                )
                for node in ast.walk(tree)
            )
            if not has_test_case:
                undiscoverable.append(relative_path)
        self.assertEqual(
            undiscoverable,
            [],
            "run_unittest_gate.py cannot discover module-level pytest functions",
        )

    def test_sphinx_download_targets_are_tracked(self):
        tracked_files = set(
            subprocess.run(
                ["git", "ls-files"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.splitlines()
        )
        missing_targets = []
        rst_sources = sorted(
            REPO_ROOT / relative_path
            for relative_path in tracked_files
            if relative_path.startswith("docs/source/")
            and relative_path.endswith(".rst")
            and not any(
                part.startswith("._") for part in Path(relative_path).parts
            )
        )
        for source_path in rst_sources:
            text = source_path.read_text(encoding="utf-8")
            for match in re.finditer(r":download:`([^`]+)`", text, re.DOTALL):
                body = match.group(1).strip()
                explicit_target = re.search(r"<([^<>]+)>\s*$", body)
                target = explicit_target.group(1) if explicit_target else body
                resolved_target = (source_path.parent / target).resolve()
                try:
                    relative_target = resolved_target.relative_to(
                        REPO_ROOT
                    ).as_posix()
                except ValueError:
                    missing_targets.append(
                        f"{source_path.relative_to(REPO_ROOT)}: {target}"
                    )
                    continue
                if relative_target not in tracked_files:
                    missing_targets.append(
                        f"{source_path.relative_to(REPO_ROOT)}: {relative_target}"
                    )
        self.assertEqual(
            missing_targets,
            [],
            "Sphinx download targets must exist in a clean Git checkout",
        )

    def test_shell_runner_rejects_unknown_modes_before_running_a_gate(self):
        result = subprocess.run(
            ["bash", str(VALIDATION_RUNNER), "not-a-validation-mode"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("unknown validation mode", result.stderr)

    def test_shipped_config_discovery_does_not_require_git_dash_c(self):
        text = VALIDATION_RUNNER.read_text(encoding="utf-8")
        self.assertNotIn('git -C "${ROOT_DIR}"', text)
        self.assertIn('cd "${ROOT_DIR}"', text)
        self.assertIn("git ls-files 'nextflow/*.config'", text)

    def test_public_shell_script_contracts_run_in_both_routing_gates(self):
        text = VALIDATION_RUNNER.read_text(encoding="utf-8")
        function_pattern = re.compile(
            r"(?ms)^[ \t]*(?P<name>[A-Za-z_][A-Za-z0-9_]*)[ \t]*"
            r"\([ \t]*\)[ \t]*\{[ \t]*(?:#[^\n]*)?\n"
            r"(?P<body>.*?)(?=^[ \t]*\}[ \t]*(?:#[^\n]*)?$)"
        )
        active_argument_pattern = re.compile(
            r"(?m)^[ \t]*test_public_shell_scripts(?:[ \t]+\\)?[ \t]*$"
        )
        function_bodies = {
            match.group("name"): match.group("body")
            for match in function_pattern.finditer(text)
        }
        expected_functions = {"run_routing_ci", "run_routing"}

        self.assertTrue(expected_functions.issubset(function_bodies))
        for function_name in expected_functions:
            self.assertEqual(
                len(
                    active_argument_pattern.findall(
                        function_bodies[function_name]
                    )
                ),
                1,
                f"{function_name} must run test_public_shell_scripts exactly once",
            )

        unexpected_functions = {
            function_name: len(active_argument_pattern.findall(body))
            for function_name, body in function_bodies.items()
            if function_name not in expected_functions
            and active_argument_pattern.search(body)
        }
        self.assertEqual(unexpected_functions, {})
        self.assertEqual(len(active_argument_pattern.findall(text)), 2)

    def test_windows_validator_rejects_a_missing_powershell_parser(self):
        with tempfile.TemporaryDirectory() as empty_path:
            env = dict(os.environ)
            env["PATH"] = empty_path
            result = subprocess.run(
                [sys.executable, str(WINDOWS_INSTALL_VALIDATOR)],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
            )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("PowerShell is required", result.stderr)

    def test_windows_validator_routes_the_installer_to_powershell(self):
        with tempfile.TemporaryDirectory() as stub_path:
            powershell = Path(stub_path) / "pwsh"
            expected_installer = REPO_ROOT / "scripts" / "install" / "install_megflow_windows.ps1"
            powershell.write_text(
                "#!/bin/bash\n"
                "set -euo pipefail\n"
                '[[ "$1" == "-NoProfile" ]]\n'
                '[[ "$2" == "-NonInteractive" ]]\n'
                '[[ "$3" == "-Command" ]]\n'
                '[[ "$4" == *"Parser]::ParseFile"* ]]\n'
                f'[[ "$MEGFLOW_WINDOWS_INSTALLER" == {shlex.quote(str(expected_installer))} ]]\n',
                encoding="utf-8",
            )
            powershell.chmod(0o755)
            env = dict(os.environ)
            env["PATH"] = stub_path
            result = subprocess.run(
                [sys.executable, str(WINDOWS_INSTALL_VALIDATOR)],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PowerShell syntax is valid", result.stdout)


if __name__ == "__main__":
    unittest.main()
