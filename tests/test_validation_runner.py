import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
UNITTEST_GATE = REPO_ROOT / "scripts" / "validation" / "run_unittest_gate.py"
VALIDATION_RUNNER = REPO_ROOT / "scripts" / "validation" / "run_validation.sh"


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


if __name__ == "__main__":
    unittest.main()
