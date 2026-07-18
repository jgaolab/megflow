#!/usr/bin/env python3
"""Parse the shipped Windows installer with the native PowerShell parser."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_INSTALLER = REPO_ROOT / "scripts" / "install" / "install_megflow_windows.ps1"


def main() -> int:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        print("PowerShell is required to validate the Windows installer", file=sys.stderr)
        return 2
    if not WINDOWS_INSTALLER.is_file():
        print(f"Windows installer is missing: {WINDOWS_INSTALLER}", file=sys.stderr)
        return 2

    command = (
        "$tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        "$env:MEGFLOW_WINDOWS_INSTALLER, [ref]$tokens, [ref]$errors) > $null; "
        "if ($errors.Count -gt 0) { "
        "$errors | ForEach-Object { Write-Error $_ }; exit 1 }"
    )
    env = os.environ.copy()
    env["MEGFLOW_WINDOWS_INSTALLER"] = str(WINDOWS_INSTALLER)
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
        env=env,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return result.returncode
    print(f"PowerShell syntax is valid: {WINDOWS_INSTALLER.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
