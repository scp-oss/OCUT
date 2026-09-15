# Windows equivalent of run.sh - clones %USERPROFILE%\OCUT on first run,
# updates it to the latest commit on every later run, then starts the
# native GUI (gui.py). Requires Python 3.9+ (from python.org or the
# Microsoft Store) already on PATH - git is installed automatically via
# winget if it's missing.
#
#   irm https://raw.githubusercontent.com/scp-oss/OCUT/claude/gifted-thompson-3q1e6m/run.ps1 | iex

$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/scp-oss/OCUT"
$Branch = "claude/gifted-thompson-3q1e6m"
$RepoDir = Join-Path $HOME "OCUT"

# Resolved full path to git.exe, set by Ensure-Git. Every later git call in
# this script goes through this variable (`& $GitCmd ...`) instead of the
# bare `git` word - Windows PowerShell can cache a "command not found"
# result for a bare command name for the rest of the session, so even
# after installing git and refreshing $env:Path, a plain `git ...` call
# right after can still fail even though `Get-Command git` itself would
# now succeed. Invoking the resolved .exe path directly sidesteps that
# cache entirely - this is exactly the failure a real run hit (winget
# installed git fine, but the very next `git clone` in the same session
# still errored with "not recognized").
$GitCmd = $null

function Resolve-Git {
    $cmd = Get-Command git -ErrorAction SilentlyContinue
    if ($cmd) {
        $script:GitCmd = $cmd.Source
        return $true
    }
    return $false
}

function Ensure-Git {
    if (Resolve-Git) {
        return
    }
    Write-Host "git not found - attempting to install it via winget..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Git.Git -e --source winget --accept-source-agreements --accept-package-agreements
        # winget updates the machine/user PATH, but this already-running
        # session doesn't pick that up on its own - re-read both from the
        # registry-backed environment provider so `Get-Command git` finds
        # it without having to open a new PowerShell window.
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("Path", "User")
    } else {
        Write-Host "winget is not available. Install Git for Windows manually from https://git-scm.com/download/win, then re-run this script." -ForegroundColor Red
        exit 1
    }
    if (-not (Resolve-Git)) {
        Write-Host "git was installed but isn't on PATH in this session yet. Open a new PowerShell window and re-run this script." -ForegroundColor Red
        exit 1
    }
}

Ensure-Git

if (Test-Path (Join-Path $RepoDir ".git")) {
    & $GitCmd -C $RepoDir fetch origin
    & $GitCmd -C $RepoDir checkout $Branch
    & $GitCmd -C $RepoDir reset --hard "origin/$Branch"
} else {
    & $GitCmd clone -b $Branch $RepoUrl $RepoDir
}

Set-Location $RepoDir

python -c "import PySide6" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing PySide6 (one-time)..."
    python -m pip install --user -r requirements.txt
}

python gui.py
