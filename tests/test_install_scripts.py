import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LINUX_INSTALLER = REPO_ROOT / "scripts/install/install_megflow_linux.sh"
MACOS_INSTALLER = REPO_ROOT / "scripts/install/install_megflow_macos.sh"
DEV_INSTALLER = REPO_ROOT / "scripts/install-dev/install_megflow_dev_linux.sh"
WINDOWS_INSTALLER = REPO_ROOT / "scripts/install/install_megflow_windows.ps1"
INSTALL_README = REPO_ROOT / "scripts/install/README.md"
DEV_INSTALL_README = REPO_ROOT / "scripts/install-dev/README.md"
PROJECT_README = REPO_ROOT / "README.md"
INSTALLATION_DOC = REPO_ROOT / "docs/source/quickstart/installation.rst"


class _InstallerContractTestCase(unittest.TestCase):
    def _write_stub(self, bin_dir: Path, name: str, body: str) -> None:
        path = bin_dir / name
        path.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body), encoding="utf-8")
        path.chmod(0o755)

    def _run_with_stubs(
        self,
        script: Path,
        *args: str,
        platform: str,
        runtime: str,
        runtime_body: str,
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            calls_file = root / "calls.txt"
            self._write_stub(bin_dir, "uname", f'echo "{platform}"\n')
            self._write_stub(bin_dir, runtime, runtime_body)

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            env["MEGFLOW_INSTALL_CALLS"] = str(calls_file)
            result = subprocess.run(
                ["bash", str(script), *args],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            calls = (
                calls_file.read_text(encoding="utf-8").splitlines()
                if calls_file.exists()
                else []
            )
            return result, calls


class InstallerMetadataContractTests(unittest.TestCase):
    def test_container_install_docs_use_version_pinned_standalone_downloads(self):
        documents = (PROJECT_README, INSTALLATION_DOC, INSTALL_README)
        raw_base = (
            "https://raw.githubusercontent.com/jgaolab/megflow/"
            "v${MEGFLOW_VERSION}/scripts/install"
        )

        for document in documents:
            with self.subTest(document=document.name):
                text = document.read_text(encoding="utf-8")
                self.assertIn("MEGFLOW_VERSION=1.0.0", text)
                self.assertIn(f"{raw_base}/install_megflow_linux.sh", text)
                self.assertIn(f"{raw_base}/install_megflow_macos.sh", text)
                self.assertIn(
                    f"{raw_base}/install_megflow_windows.ps1",
                    text,
                )
                self.assertNotIn("wget ", text)

        install_readme = INSTALL_README.read_text(encoding="utf-8")
        self.assertIn("default image tag is `1.0.0`", install_readme)
        self.assertIn("apptainer run --cleanenv", install_readme)
        self.assertIn("--bind /data/bids:/input", install_readme)

    def test_source_install_docs_download_the_installer_without_a_checkout(self):
        installer_url = (
            "https://raw.githubusercontent.com/jgaolab/megflow/main/"
            "scripts/install-dev/install_megflow_dev_linux.sh"
        )

        for document in (PROJECT_README, INSTALLATION_DOC, DEV_INSTALL_README):
            with self.subTest(document=document.name):
                text = document.read_text(encoding="utf-8")
                normalized = text.lower()
                self.assertIn(installer_url, text)
                self.assertIn("do not need to clone", normalized)
                self.assertIn("any writable directory", normalized)
                self.assertIn("~/.megflow-dev/src/megflow", text)

    def test_source_installer_defaults_to_public_https_repository(self):
        script = DEV_INSTALLER.read_text(encoding="utf-8")
        self.assertIn(
            'REPO_URL="https://github.com/jgaolab/megflow.git"',
            script,
        )
        self.assertNotIn("git@github.com:jgaolab/megflow.git", script)
        self.assertIn(
            "bash install_megflow_dev_linux.sh [options]",
            script,
        )


class WindowsInstallerContractTests(unittest.TestCase):
    def test_windows_installer_checks_native_docker_exit_codes(self):
        script = WINDOWS_INSTALLER.read_text(encoding="utf-8")
        self.assertIn('[string]$ImageTag = "1.0.0"', script)
        self.assertIn("$LASTEXITCODE", script)
        self.assertIn("function Test-DockerDaemon", script)
        self.assertIn('Invoke-Docker -Arguments @("pull", $Image)', script)
        self.assertIn('Invoke-Docker -Arguments @("run", "--rm", $Image, "-h")', script)

    def test_windows_installer_allows_native_stderr_when_docker_succeeds(self):
        script = WINDOWS_INSTALLER.read_text(encoding="utf-8")
        self.assertIn("function Invoke-NativeDocker", script)
        self.assertIn('$ErrorActionPreference = "Continue"', script)
        self.assertIn(
            'Invoke-NativeDocker -Arguments @("info") -DiscardOutput',
            script,
        )
        self.assertIn("Invoke-NativeDocker -Arguments $Arguments", script)

        if os.name != "nt":
            return

        powershell = shutil.which("powershell")
        self.assertIsNotNone(
            powershell,
            "Windows PowerShell 5.1 is required for the native stderr regression test.",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            calls_file = root / "docker-calls.txt"
            docker = bin_dir / "docker.cmd"
            docker.write_text(
                textwrap.dedent(
                    """\
                    @echo off
                    echo WARNING: simulated Docker stderr warning 1>&2
                    echo %*>>"%MEGFLOW_INSTALL_CALLS%"
                    exit /b 0
                    """
                ),
                encoding="ascii",
            )
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            env["MEGFLOW_INSTALL_CALLS"] = str(calls_file)

            result = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(WINDOWS_INSTALLER),
                    "-ImageTag",
                    "1.0.0",
                ],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                calls_file.read_text(encoding="utf-8").splitlines(),
                [
                    "info",
                    "info",
                    "pull cplmeg/megflow:1.0.0",
                    "run --rm cplmeg/megflow:1.0.0 -h",
                ],
            )


class LinuxInstallerContractTests(_InstallerContractTestCase):
    def test_linux_bash_installers_parse(self):
        result = subprocess.run(
            ["bash", "-n", str(LINUX_INSTALLER), str(DEV_INSTALLER)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_linux_apptainer_arguments_pull_and_validate_requested_tag(self):
        result, calls = self._run_with_stubs(
            LINUX_INSTALLER,
            "1.0.0",
            "apptainer",
            platform="Linux",
            runtime="apptainer",
            runtime_body='printf "%s\\n" "$*" >> "$MEGFLOW_INSTALL_CALLS"\n',
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            calls,
            [
                "pull --force ./megflow_1.0.0.sif docker://cplmeg/megflow:1.0.0",
                "run ./megflow_1.0.0.sif -h",
            ],
        )

    def test_linux_singularity_alias_uses_the_sif_flow(self):
        result, calls = self._run_with_stubs(
            LINUX_INSTALLER,
            "1.0.0",
            "singularity",
            platform="Linux",
            runtime="singularity",
            runtime_body='printf "%s\\n" "$*" >> "$MEGFLOW_INSTALL_CALLS"\n',
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            calls,
            [
                "pull --force ./megflow_1.0.0.sif docker://cplmeg/megflow:1.0.0",
                "run ./megflow_1.0.0.sif -h",
            ],
        )

    def test_linux_default_arguments_use_release_and_auto_select_docker(self):
        result, calls = self._run_with_stubs(
            LINUX_INSTALLER,
            platform="Linux",
            runtime="docker",
            runtime_body='printf "%s\\n" "$*" >> "$MEGFLOW_INSTALL_CALLS"\n',
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            calls,
            [
                "info",
                "info",
                "pull cplmeg/megflow:1.0.0",
                "run --rm cplmeg/megflow:1.0.0 -h",
            ],
        )

    def test_linux_tag_only_keeps_auto_runtime_selection(self):
        result, calls = self._run_with_stubs(
            LINUX_INSTALLER,
            "1.0.0",
            platform="Linux",
            runtime="docker",
            runtime_body='printf "%s\\n" "$*" >> "$MEGFLOW_INSTALL_CALLS"\n',
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[-2:], [
            "pull cplmeg/megflow:1.0.0",
            "run --rm cplmeg/megflow:1.0.0 -h",
        ])

    def test_linux_rejects_unknown_runtime_before_invoking_a_runtime(self):
        result, calls = self._run_with_stubs(
            LINUX_INSTALLER,
            "1.0.0",
            "podman",
            platform="Linux",
            runtime="docker",
            runtime_body='printf "%s\\n" "$*" >> "$MEGFLOW_INSTALL_CALLS"\n',
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid runtime mode: podman", result.stdout)
        self.assertEqual(calls, [])

    def test_linux_apptainer_fallback_executes_the_image_entrypoint(self):
        result, calls = self._run_with_stubs(
            LINUX_INSTALLER,
            "1.0.0",
            "apptainer",
            platform="Linux",
            runtime="apptainer",
            runtime_body="""
                printf "%s\\n" "$*" >> "$MEGFLOW_INSTALL_CALLS"
                [[ "$1" == "run" ]] && exit 1
                exit 0
            """,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            calls[-1],
            "exec ./megflow_1.0.0.sif /program/nextflow/run.sh -h",
        )

    def test_linux_docker_arguments_pull_and_validate_requested_tag(self):
        result, calls = self._run_with_stubs(
            LINUX_INSTALLER,
            "1.0.0",
            "docker",
            platform="Linux",
            runtime="docker",
            runtime_body='printf "%s\\n" "$*" >> "$MEGFLOW_INSTALL_CALLS"\n',
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            calls,
            [
                "info",
                "pull cplmeg/megflow:1.0.0",
                "run --rm cplmeg/megflow:1.0.0 -h",
            ],
        )


class MacOSInstallerContractTests(_InstallerContractTestCase):
    def test_macos_bash_installer_parses(self):
        result = subprocess.run(
            ["bash", "-n", str(MACOS_INSTALLER)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_macos_docker_arguments_pull_and_validate_requested_tag(self):
        result, calls = self._run_with_stubs(
            MACOS_INSTALLER,
            "1.0.0",
            platform="Darwin",
            runtime="docker",
            runtime_body='printf "%s\\n" "$*" >> "$MEGFLOW_INSTALL_CALLS"\n',
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            calls,
            [
                "info",
                "info",
                "pull cplmeg/megflow:1.0.0",
                "run --rm cplmeg/megflow:1.0.0 -h",
            ],
        )

    def test_macos_default_argument_uses_release(self):
        result, calls = self._run_with_stubs(
            MACOS_INSTALLER,
            platform="Darwin",
            runtime="docker",
            runtime_body='printf "%s\\n" "$*" >> "$MEGFLOW_INSTALL_CALLS"\n',
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[-2:], [
            "pull cplmeg/megflow:1.0.0",
            "run --rm cplmeg/megflow:1.0.0 -h",
        ])


if __name__ == "__main__":
    unittest.main()
