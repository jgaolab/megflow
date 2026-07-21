import os
import re
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
    REPO_ROOT / "examples/run_scripts/single_dataset_sif.sh",
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
        for path in PUBLIC_SCRIPTS:
            result = subprocess.run(
                ["bash", "-n", str(path)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, f"{path}: {result.stderr}")

    def test_public_scripts_share_the_portable_contract(self):
        for path in PUBLIC_SCRIPTS:
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("#!/usr/bin/env bash\n"), path)
            self.assertIn("set -euo pipefail", text, path)
            self.assertNotIn("/data/liaopan", text, path)
            self.assertNotIn("/opt/singularity", text, path)
            result = self._run_script(path, "--help")
            self.assertEqual(result.returncode, 0, f"{path}: {result.stderr}")

    def test_run_script_guide_lists_every_help_option(self):
        guide = (REPO_ROOT / "examples" / "run_scripts" / "README.md").read_text(
            encoding="utf-8"
        )
        for index, script in enumerate(RUN_SCRIPTS):
            heading = f"### `{script.name}`"
            start = guide.index(heading)
            following_starts = [
                guide.find(f"### `{candidate.name}`", start + len(heading))
                for candidate in RUN_SCRIPTS[index + 1 :]
            ]
            following_starts.append(guide.find("## Troubleshooting", start))
            end = min(position for position in following_starts if position >= 0)
            section = guide[start:end]
            help_result = self._run_script(script, "--help")
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            options = set(re.findall(r"(?m)^\s+(--[a-z][a-z-]*)", help_result.stdout))
            for option in options:
                with self.subTest(script=script.name, option=option):
                    self.assertIn(f"`{option}", section)

    def test_cleanup_helper_is_preview_first_and_clean_docker_is_out_of_scope(self):
        text = DEVELOPMENT_SCRIPTS[-1].read_text(encoding="utf-8")
        self.assertIn('APPLY=false', text)
        self.assertIn('--yes', text)
        self.assertIn('if [ "$APPLY" != true ]', text)
        self.assertNotIn("clean_docker.sh", text)

    def test_development_helpers_assemble_safe_build_commands(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            env, calls_path = self._stub_environment(root, "python")
            self._write_stub(root / "bin", "apptainer", "exit 0\n")

            build = self._run_script(DEVELOPMENT_SCRIPTS[0], "--dry-run", env=env)
            docs = self._run_script(DEVELOPMENT_SCRIPTS[1], "--strict", env=env)
            sif = self._run_script(
                DEVELOPMENT_SCRIPTS[2], "--dry-run", "--runtime", "apptainer", env=env
            )

            self.assertEqual(build.returncode, 0, build.stderr)
            self.assertIn("build", build.stdout)
            self.assertIn("cplmeg/megflow:local", build.stdout)
            self.assertEqual(docs.returncode, 0, docs.stderr)
            docs_output = docs.stdout + calls_path.read_text(encoding="utf-8")
            self.assertIn("python", docs_output)
            self.assertIn("sphinx", docs_output)
            self.assertEqual(sif.returncode, 0, sif.stderr)
            self.assertIn("docker-daemon://cplmeg/megflow:local", sif.stdout)

    def test_docs_clean_rejects_an_output_that_resolves_outside_docs_build(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            env, _ = self._stub_environment(root, "python")

            result = self._run_script(
                DEVELOPMENT_SCRIPTS[1],
                "--clean", "--output", "docs/build/../outside", env=env,
            )

            self.assertEqual(result.returncode, 2, result.stderr)

    def test_docs_rejects_nonexistent_output_beneath_symlink_escape(self):
        docs_build = REPO_ROOT / "docs" / "build"
        docs_build.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=docs_build) as inside_directory:
            with tempfile.TemporaryDirectory() as outside_directory:
                escape = Path(inside_directory) / "escape"
                escape.symlink_to(outside_directory, target_is_directory=True)
                root = Path(outside_directory)
                env, _ = self._stub_environment(root, "python")

                result = self._run_script(
                    DEVELOPMENT_SCRIPTS[1],
                    "--output", str(escape / "new-html"),
                    env=env,
                )

                self.assertEqual(result.returncode, 2, result.stderr)

    def test_cleanup_helper_help_and_empty_preview_never_apply_deletions(self):
        text = DEVELOPMENT_SCRIPTS[-1].read_text(encoding="utf-8")
        self.assertIn('APPLY=false', text)
        self.assertIn('if [ "$APPLY" != true ]', text)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self._write_stub(
                bin_dir,
                "docker",
                '''
                if [ "$1" = "images" ]; then
                    exit 0
                fi
                exit 99
                ''',
            )
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"

            help_result = self._run_script(DEVELOPMENT_SCRIPTS[-1], "--help", env=env)
            preview = self._run_script(DEVELOPMENT_SCRIPTS[-1], env=env)

            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertIn("No dangling Docker images found", preview.stdout)

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

    def test_corpus_discovery_avoids_gnu_only_find_depth_options(self):
        text = RUN_SCRIPTS[1].read_text(encoding="utf-8")
        self.assertNotIn("-mindepth", text)
        self.assertNotIn("-maxdepth", text)

    def test_single_dataset_docker_assembles_entrypoint_arguments(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_directory = root / "input"
            input_directory.mkdir()
            output = root / "output"
            smri = root / "smri"
            license_file = root / "license.txt"
            license_file.write_text("test-license\n", encoding="utf-8")
            config = root / "quickstart.config"
            config.write_text("params { }\n", encoding="utf-8")
            env, calls_path = self._stub_environment(root, "docker")

            result = self._run_script(
                RUN_SCRIPTS[0],
                "--input", str(input_directory),
                "--output", str(output),
                "--config", str(config),
                "--smri", str(smri),
                "--license", str(license_file),
                "--steps", "meg_ica",
                "--anat-method", "deepprep",
                "--resume",
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            calls = calls_path.read_text(encoding="utf-8")
            self.assertIn(f"{input_directory}:/input:ro", calls)
            self.assertIn(f"{output}:/output", calls)
            self.assertIn(f"{config}:/config/nextflow.config:ro", calls)
            self.assertIn(f"{smri}:/smri", calls)
            self.assertIn(f"{license_file}:/fs_license.txt:ro", calls)
            self.assertIn("--fs_subjects_dir\n/smri", calls)
            self.assertIn("--fs_license_file\n/fs_license.txt", calls)
            self.assertIn("--anat-method\ndeepprep", calls)
            self.assertIn("--steps\nmeg_ica", calls)
            self.assertIn("--resume", calls)

    def test_single_dataset_sif_assembles_runtime_and_entrypoint_arguments(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_directory = root / "input"
            input_directory.mkdir()
            output = root / "output"
            smri = root / "smri"
            license_file = root / "license.txt"
            license_file.write_text("test-license\n", encoding="utf-8")
            config = root / "quickstart.config"
            config.write_text("params { }\n", encoding="utf-8")
            sif = root / "megflow.sif"
            sif.write_text("test-sif\n", encoding="utf-8")
            env, calls_path = self._stub_environment(root, "apptainer")

            result = self._run_script(
                RUN_SCRIPTS[4],
                "--input", str(input_directory),
                "--output", str(output),
                "--sif", str(sif),
                "--config", str(config),
                "--smri", str(smri),
                "--license", str(license_file),
                "--steps", "meg_ica",
                "--anat-method", "deepprep",
                "--runtime", "apptainer",
                "--resume",
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            calls = calls_path.read_text(encoding="utf-8")
            self.assertIn("run\n--cleanenv", calls)
            self.assertIn(f"{input_directory}:/input:ro", calls)
            self.assertIn(f"{output}:/output", calls)
            self.assertIn(f"{config}:/config/nextflow.config:ro", calls)
            self.assertIn(f"{smri}:/smri", calls)
            self.assertIn(f"{license_file}:/fs_license.txt:ro", calls)
            self.assertIn(str(sif), calls)
            self.assertIn("--config\n/config/nextflow.config", calls)
            self.assertIn("--fs_subjects_dir\n/smri", calls)
            self.assertIn("--fs_license_file\n/fs_license.txt", calls)
            self.assertIn("--anat-method\ndeepprep", calls)
            self.assertIn("--steps\nmeg_ica", calls)
            self.assertIn("--resume", calls)
            source = RUN_SCRIPTS[4].read_text(encoding="utf-8")
            self.assertNotIn("--writable-tmpfs", source)

    def test_corpus_source_assembles_local_strict_nextflow_profile(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output = root / "output"
            config = root / "corpus.config"
            config.write_text(
                "params {\n"
                "    megflow {\n"
                f'        output_dir = "{output}"\n'
                "    }\n"
                "}\n",
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
            self.assertIn(f"-w\n{output / 'work'}", source_calls)
            self.assertIn(
                f"-log\n{output / 'corpus_static_html_report' / 'nextflow' / 'nextflow.log'}",
                source_calls,
            )

    def test_interactive_report_maps_the_viewer_port_and_report_option(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output = root / "output"
            output.mkdir()
            env, calls_path = self._stub_environment(root, "docker")

            result = self._run_script(
                RUN_SCRIPTS[3],
                "--output", str(output),
                "--port", "9123",
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report_calls = calls_path.read_text(encoding="utf-8")
            self.assertIn("-r", report_calls)
            self.assertIn("9123:8501", report_calls)
            self.assertIn("Viewer: http://localhost:9123", result.stdout)

    def test_docker_launchers_resolve_relative_host_paths_before_mounting(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_directory = root / "input"
            input_directory.mkdir()
            corpus = root / "corpus"
            (corpus / "dataset_a").mkdir(parents=True)
            output = root / "output"
            corpus_output = root / "corpus_output"
            report_output = root / "report_output"
            report_output.mkdir()
            config = root / "config"
            config.write_text("params { }\n", encoding="utf-8")
            env, calls_path = self._stub_environment(root, "docker")

            single = self._run_script(
                RUN_SCRIPTS[0],
                "--input", "input", "--output", "output", "--config", "config",
                env=env, cwd=root,
            )
            corpus_result = self._run_script(
                RUN_SCRIPTS[1],
                "--input", "corpus", "--output", "corpus_output", "--config", "config",
                env=env, cwd=root,
            )
            report = self._run_script(
                RUN_SCRIPTS[3], "--output", "report_output", env=env, cwd=root
            )

            self.assertEqual(single.returncode, 0, single.stderr)
            self.assertEqual(corpus_result.returncode, 0, corpus_result.stderr)
            self.assertEqual(report.returncode, 0, report.stderr)
            calls = calls_path.read_text(encoding="utf-8")
            self.assertIn(f"{input_directory}:/input:ro", calls)
            self.assertIn(f"{output}:/output", calls)
            self.assertIn(f"{corpus}:/input:ro", calls)
            self.assertIn(f"{corpus_output}:/output", calls)
            self.assertIn(f"{report_output}:/output", calls)

    def test_source_launcher_rejects_unwritable_work_destination_before_launch(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config = root / "corpus.config"
            config.write_text("params { }\n", encoding="utf-8")
            pipeline = root / "megflow.nf"
            pipeline.write_text("nextflow.enable.dsl=2\n", encoding="utf-8")
            work_file = root / "not_a_directory"
            work_file.write_text("blocked\n", encoding="utf-8")
            env, calls_path = self._stub_environment(root, "nextflow")

            result = self._run_script(
                RUN_SCRIPTS[2],
                "--config", str(config), "--pipeline", str(pipeline),
                "--work-dir", str(work_file), env=env,
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertFalse(calls_path.exists())

    def test_docker_launcher_rejects_an_untraversable_input_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_directory = root / "input"
            input_directory.mkdir()
            input_directory.chmod(0o600)
            config = root / "quickstart.config"
            config.write_text("params { }\n", encoding="utf-8")
            try:
                result = self._run_script(
                    RUN_SCRIPTS[0],
                    "--input", str(input_directory),
                    "--output", str(root / "output"),
                    "--config", str(config),
                    "--dry-run",
                )
            finally:
                input_directory.chmod(0o700)

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("traversable", result.stderr)

    def test_launchers_normalize_external_failure_to_one(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            self._write_stub(bin_dir, "docker", "exit 42\n")
            self._write_stub(bin_dir, "nextflow", "exit 42\n")
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
            input_directory = root / "input"
            input_directory.mkdir()
            corpus = root / "corpus"
            (corpus / "dataset_a").mkdir(parents=True)
            report_output = root / "report_output"
            report_output.mkdir()
            config = root / "config"
            config.write_text("params { }\n", encoding="utf-8")
            source_config = root / "source.config"
            source_config.write_text("params { }\n", encoding="utf-8")
            pipeline = root / "megflow.nf"
            pipeline.write_text("nextflow.enable.dsl=2\n", encoding="utf-8")

            results = (
                self._run_script(RUN_SCRIPTS[0], "--input", str(input_directory), "--output", str(root / "output"), "--config", str(config), env=env),
                self._run_script(RUN_SCRIPTS[1], "--input", str(corpus), "--output", str(root / "corpus_output"), "--config", str(config), env=env),
                self._run_script(RUN_SCRIPTS[2], "--config", str(source_config), "--pipeline", str(pipeline), env=env),
                self._run_script(RUN_SCRIPTS[3], "--output", str(report_output), env=env),
            )

            self.assertTrue(all(result.returncode == 1 for result in results))

    def test_launchers_reject_unknown_and_missing_options(self):
        missing_value_options = (
            (RUN_SCRIPTS[0], "--input"),
            (RUN_SCRIPTS[1], "--input"),
            (RUN_SCRIPTS[2], "--config"),
            (RUN_SCRIPTS[3], "--output"),
        )
        for script, option in missing_value_options:
            self.assertEqual(self._run_script(script, option).returncode, 2, script)
            self.assertEqual(self._run_script(script, "--unknown").returncode, 2, script)

        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "output"
            output.mkdir()
            result = self._run_script(
                RUN_SCRIPTS[3], "--output", str(output), "--port", "9" * 100
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertNotIn("integer expression expected", result.stderr)

    def test_value_options_reject_an_adjacent_option_as_their_value(self):
        cases = (
            (RUN_SCRIPTS[0], ("--input", "--output")),
            (RUN_SCRIPTS[1], ("--input", "--output")),
            (RUN_SCRIPTS[2], ("--profile", "--no-resume")),
            (RUN_SCRIPTS[3], ("--output", "--dry-run")),
            (DEVELOPMENT_SCRIPTS[0], ("--image", "--dry-run")),
            (DEVELOPMENT_SCRIPTS[1], ("--output", "--strict")),
            (DEVELOPMENT_SCRIPTS[2], ("--runtime", "--dry-run")),
        )
        for script, arguments in cases:
            with self.subTest(script=script.name):
                result = self._run_script(script, *arguments)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("requires a value", result.stderr)

    def test_required_cli_options_ignore_undocumented_environment_values(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_directory = root / "input"
            input_directory.mkdir()
            corpus = root / "corpus"
            (corpus / "dataset_a").mkdir(parents=True)
            output = root / "output"
            output.mkdir()
            config = root / "config"
            config.write_text("params { }\n", encoding="utf-8")
            pipeline = root / "megflow.nf"
            pipeline.write_text("nextflow.enable.dsl=2\n", encoding="utf-8")
            env = os.environ.copy()
            env.update(
                {
                    "MEGFLOW_INPUT": str(input_directory),
                    "MEGFLOW_OUTPUT": str(output),
                    "MEGFLOW_CONFIG": str(config),
                    "MEGFLOW_PIPELINE": str(pipeline),
                }
            )

            results = (
                self._run_script(RUN_SCRIPTS[0], "--dry-run", env=env),
                self._run_script(RUN_SCRIPTS[1], "--dry-run", env=env),
                self._run_script(RUN_SCRIPTS[2], "--dry-run", env=env),
                self._run_script(RUN_SCRIPTS[3], "--dry-run", env=env),
            )

            self.assertTrue(all(result.returncode == 2 for result in results))

    def test_dry_run_launchers_do_not_call_external_runtimes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_directory = root / "input"
            input_directory.mkdir()
            corpus = root / "corpus"
            (corpus / "dataset_a").mkdir(parents=True)
            report_output = root / "report_output"
            report_output.mkdir()
            config = root / "config"
            config.write_text("params { }\n", encoding="utf-8")
            pipeline = root / "megflow.nf"
            pipeline.write_text("nextflow.enable.dsl=2\n", encoding="utf-8")
            env, calls_path = self._stub_environment(root, "docker")
            self._write_stub(root / "bin", "nextflow", "printf 'called\\n' >> \"$MEGFLOW_TEST_CALLS\"\n")

            results = (
                self._run_script(RUN_SCRIPTS[0], "--input", str(input_directory), "--output", str(root / "output"), "--config", str(config), "--dry-run", env=env),
                self._run_script(RUN_SCRIPTS[1], "--input", str(corpus), "--output", str(root / "corpus_output"), "--config", str(config), "--dry-run", env=env),
                self._run_script(RUN_SCRIPTS[2], "--config", str(config), "--pipeline", str(pipeline), "--dry-run", env=env),
                self._run_script(RUN_SCRIPTS[3], "--output", str(report_output), "--dry-run", env=env),
            )

            self.assertTrue(all(result.returncode == 0 for result in results))
            self.assertFalse(calls_path.exists())
