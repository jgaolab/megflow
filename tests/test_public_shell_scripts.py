import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_SCRIPTS = (
    REPO_ROOT / "examples/run_scripts/single_dataset_docker.sh",
    REPO_ROOT / "examples/run_scripts/corpus_docker.sh",
    REPO_ROOT / "examples/run_scripts/corpus_source.sh",
    REPO_ROOT / "examples/run_scripts/interactive_report.sh",
)
DEVELOPMENT_SCRIPTS = (
    REPO_ROOT / "scripts/development/build_megflow.sh",
    REPO_ROOT / "scripts/development/build_docs.sh",
    REPO_ROOT / "scripts/development/docker2sif.sh",
    REPO_ROOT / "scripts/development/rm_none_docker.sh",
)
PUBLIC_SCRIPTS = RUN_SCRIPTS + DEVELOPMENT_SCRIPTS


class PublicShellScriptContractTests(unittest.TestCase):
    def _write_stub(self, root: Path, name: str, body: str) -> Path:
        path = root / name
        path.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body), encoding="utf-8")
        path.chmod(0o755)
        return path

    def _run_script(self, script: Path, *args: str, env=None, cwd=None):
        return subprocess.run(
            ["bash", str(script), *args],
            cwd=cwd or REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_canonical_public_scripts_exist_and_parse(self):
        self.assertTrue(all(path.is_file() for path in PUBLIC_SCRIPTS))
        result = subprocess.run(
            ["bash", "-n", *(str(path) for path in PUBLIC_SCRIPTS)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_public_scripts_share_the_portable_contract(self):
        for path in PUBLIC_SCRIPTS:
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("#!/usr/bin/env bash\n"), path)
            self.assertIn("set -euo pipefail", text, path)
            self.assertNotIn("/data/liaopan", text, path)
            self.assertNotIn("/opt/singularity", text, path)
            result = self._run_script(path, "--help")
            self.assertEqual(result.returncode, 0, f"{path}: {result.stderr}")

    def test_cleanup_helper_is_preview_first_and_clean_docker_is_out_of_scope(self):
        text = DEVELOPMENT_SCRIPTS[-1].read_text(encoding="utf-8")
        self.assertIn('APPLY=false', text)
        self.assertIn('--yes', text)
        self.assertIn('if [ "$APPLY" != true ]', text)
        self.assertNotIn("clean_docker.sh", text)
