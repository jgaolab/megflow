param(
    [string]$ImageTag = "1.0.0"
)

$ErrorActionPreference = "Stop"
$Image = "cplmeg/megflow:$ImageTag"
$script:DockerCommand = $null

function Write-Log {
    param([string]$Message)
    Write-Host "[megflow-install][windows] $Message"
}

function Test-Input {
    if ([string]::IsNullOrWhiteSpace($ImageTag)) {
        throw "ImageTag cannot be empty."
    }
}

function Resolve-DockerCommand {
    $Command = Get-Command docker -ErrorAction SilentlyContinue
    if ($Command) {
        return $Command.Source
    }

    $DefaultDockerCli = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe"
    if (Test-Path $DefaultDockerCli) {
        return $DefaultDockerCli
    }

    return $null
}

function Invoke-NativeDocker {
    param(
        [string[]]$Arguments,
        [switch]$DiscardOutput
    )

    $PreviousErrorActionPreference = $ErrorActionPreference
    $ExitCode = 1
    try {
        # Windows PowerShell 5.1 wraps native stderr as NativeCommandError.
        # Docker can emit warnings on stderr even when it exits successfully.
        $ErrorActionPreference = "Continue"
        if ($DiscardOutput) {
            & $script:DockerCommand @Arguments *> $null
        }
        else {
            & $script:DockerCommand @Arguments 2>&1 | Out-Host
        }
        $ExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }

    return $ExitCode
}

function Test-DockerDaemon {
    $ExitCode = Invoke-NativeDocker -Arguments @("info") -DiscardOutput
    return $ExitCode -eq 0
}

function Invoke-Docker {
    param([string[]]$Arguments)

    $ExitCode = Invoke-NativeDocker -Arguments $Arguments
    if ($ExitCode -ne 0) {
        throw "Docker command failed with exit code ${ExitCode}: docker $($Arguments -join ' ')"
    }
}

function Ensure-DockerDesktop {
    $script:DockerCommand = Resolve-DockerCommand
    if ($script:DockerCommand) {
        Write-Log "Docker CLI is already installed."
    }
    else {
        Write-Log "Docker not found. Installing Docker Desktop via winget."
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw "winget not found. Please install Docker Desktop manually and retry."
        }
        winget install --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            throw "winget failed to install Docker Desktop (exit code ${LASTEXITCODE})."
        }

        $script:DockerCommand = Resolve-DockerCommand
        if (-not $script:DockerCommand) {
            throw "Docker Desktop was installed, but docker.exe was not found. Restart PowerShell and retry."
        }
    }

    if (-not (Test-DockerDaemon)) {
        Write-Log "Docker daemon is not ready. Trying to launch Docker Desktop."
        $DockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
        if (-not (Test-Path $DockerDesktop)) {
            throw "Docker Desktop executable was not found at: $DockerDesktop"
        }
        Start-Process $DockerDesktop
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 2
            if (Test-DockerDaemon) {
                break
            }
        }
    }

    if (-not (Test-DockerDaemon)) {
        throw "Docker is still not ready. Start Docker Desktop manually and retry."
    }
}

Test-Input
Write-Log "Target image: $Image"
Ensure-DockerDesktop

Write-Log "Pulling MEGFlow Docker image..."
Invoke-Docker -Arguments @("pull", $Image)

Write-Log "Running '-h' to validate installation (help output should print below)..."
Invoke-Docker -Arguments @("run", "--rm", $Image, "-h")

Write-Log "Validation completed."
