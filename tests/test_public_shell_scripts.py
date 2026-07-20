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

    def _stub_environment(self, root: Path, command: str):
        bin_dir = root / "bin"
        bin_dir.mkdir()
        self._write_stub(
            bin_dir,
            command,
            '''
            printf '%s\\n' "$@" >> "$MEGFLOW_TEST_CALLS"
            ''',
        )
        calls = root / "calls.txt"
        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
        env["MEGFLOW_TEST_CALLS"] = str(calls)
        return env, calls

    def test_corpus_docker_assembles_corpus_entrypoint_arguments(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            corpus = root / "corpus"
            (corpus / "dataset_a").mkdir(parents=True)
            output = root / "output"
            smri = root / "smri"
            config = root / "corpus.config"
            config.write_text("params { }\\n", encoding="utf-8")
            env, calls_path = self._stub_environment(root, "docker")

            result = self._run_script(
                RUN_SCRIPTS[1],
                "--input", str(corpus),
                "--output", str(output),
                "--smri", str(smri),
                "--config", str(config),
                "--steps", "meg_ica",
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            calls = calls_path.read_text(encoding="utf-8")
            self.assertIn("--corpus", calls)
            self.assertIn("--steps\nmeg_ica", calls)

    def test_single_dataset_docker_assembles_entrypoint_arguments(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_directory = root / "input"
            input_directory.mkdir()
            output = root / "output"
            config = root / "quickstart.config"
            config.write_text("params { }\n", encoding="utf-8")
            env, calls_path = self._stub_environment(root, "docker")

            result = self._run_script(
                RUN_SCRIPTS[0],
                "--input", str(input_directory),
                "--output", str(output),
                "--config", str(config),
                "--steps", "meg_ica",
                "--resume",
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            calls = calls_path.read_text(encoding="utf-8")
            self.assertIn(f"{input_directory}:/input:ro", calls)
            self.assertIn(f"{output}:/output", calls)
            self.assertIn(f"{config}:/config/nextflow.config:ro", calls)
            self.assertIn("--steps\nmeg_ica", calls)
            self.assertIn("--resume", calls)

    def test_corpus_source_assembles_local_strict_nextflow_profile(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output = root / "output"
            config = root / "corpus.config"
            config.write_text(
                f'params {{ megflow {{ output_dir = "{output}" }} }}\n',
                encoding="utf-8",
            )
            pipeline = root / "megflow.nf"
            pipeline.write_text("nextflow.enable.dsl=2\n", encoding="utf-8")
            env, calls_path = self._stub_environment(root, "nextflow")

            result = self._run_script(
                RUN_SCRIPTS[2],
                "--config", str(config),
                "--pipeline", str(pipeline),
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            source_calls = calls_path.read_text(encoding="utf-8")
            self.assertIn("-profile\nlocal,strict", source_calls)

    def test_interactive_report_maps_the_viewer_port_and_report_option(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output = root / "output"
            output.mkdir()
            env, calls_path = self._stub_environment(root, "docker")

            result = self._run_script(
                RUN_SCRIPTS[3], "--output", str(output), env=env
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report_calls = calls_path.read_text(encoding="utf-8")
            self.assertIn("-r", report_calls)
            self.assertIn("8501:8501", report_calls)
