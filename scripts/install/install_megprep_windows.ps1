param(
    [string]$ImageTag = "latest"
)

$ErrorActionPreference = "Stop"
$Image = "cmrlab/megprep:$ImageTag"

function Write-Log {
    param([string]$Message)
    Write-Host "[megprep-install][windows] $Message"
}

function Test-Input {
    if ([string]::IsNullOrWhiteSpace($ImageTag)) {
        throw "ImageTag cannot be empty."
    }
}

function Ensure-DockerDesktop {
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        Write-Log "Docker CLI is already installed."
    }
    else {
        Write-Log "Docker not found. Installing Docker Desktop via winget."
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw "winget not found. Please install Docker Desktop manually and retry."
        }
        winget install --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
    }

    try {
        docker info | Out-Null
    }
    catch {
        Write-Log "Docker daemon is not ready. Trying to launch Docker Desktop."
        Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe" -ErrorAction SilentlyContinue
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 2
            try {
                docker info | Out-Null
                break
            }
            catch {
            }
        }
    }

    docker info | Out-Null
}

Test-Input
Write-Log "Target image: $Image"
Ensure-DockerDesktop

Write-Log "Pulling MEGPrep Docker image..."
docker pull $Image

Write-Log "Running '-h' to validate installation (help output should print below)..."
docker run --rm $Image -h

Write-Log "Validation completed."
