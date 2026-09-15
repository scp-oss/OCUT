# Windows equivalent of run.sh - clones %USERPROFILE%\OCUT on first run,
# updates it to the latest commit on every later run, then starts the
# native GUI (gui.py). Requires git and Python 3.9+ (from python.org or
# the Microsoft Store) already on PATH.
#
#   irm https://raw.githubusercontent.com/scp-oss/OCUT/claude/gifted-thompson-3q1e6m/run.ps1 | iex
#
# For the old browser-based server.py instead of the native GUI, clone
# manually and run `python server.py` - this one-liner always launches
# the GUI (see run.sh's own --web flag for the bash/macOS/Linux equivalent).

$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/scp-oss/OCUT"
$Branch = "claude/gifted-thompson-3q1e6m"
$RepoDir = Join-Path $HOME "OCUT"

function Ensure-Git {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        return
    }
    Write-Host "git not found - attempting to install it via winget..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Git.Git -e --source winget --accept-source-agreements --accept-package-agreements
        # winget updates the machine/user PATH, but this already-running
        # session doesn't pick that up on its own - re-read both from the
        # registry-backed environment provider so `git` resolves without
        # having to open a new PowerShell window.
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("Path", "User")
    } else {
        Write-Host "winget is not available. Install Git for Windows manually from https://git-scm.com/download/win, then re-run this script." -ForegroundColor Red
        exit 1
    }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Host "git was installed but isn't on PATH in this session yet. Open a new PowerShell window and re-run this script." -ForegroundColor Red
        exit 1
    }
}

Ensure-Git

if (Test-Path (Join-Path $RepoDir ".git")) {
    git -C $RepoDir fetch origin
    git -C $RepoDir checkout $Branch
    git -C $RepoDir reset --hard "origin/$Branch"
} else {
    git clone -b $Branch $RepoUrl $RepoDir
}

Set-Location $RepoDir

python -c "import PySide6" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing PySide6 (one-time)..."
    python -m pip install --user -r requirements.txt
}

python gui.py
