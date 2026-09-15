# Windows equivalent of run.sh - clones %APPDATA%\OCUT on first run,
# updates it to the latest commit on every later run, then starts the
# native GUI (gui.py). git and Python are both installed automatically
# via winget if either is missing.
#
#   irm https://raw.githubusercontent.com/scp-oss/OCUT/claude/gifted-thompson-3q1e6m/run.ps1 | iex

$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/scp-oss/OCUT"
$Branch = "claude/gifted-thompson-3q1e6m"
$RepoDir = Join-Path $env:APPDATA "OCUT"

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

# Same idea, same $PythonCmd-full-path pattern as $GitCmd above, for
# Python - just as often missing on a fresh Windows machine as git is.
$PythonCmd = $null

function Resolve-Python {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
        $script:PythonCmd = $cmd.Source
        return $true
    }
    return $false
}

function Ensure-Python {
    if (Resolve-Python) {
        return
    }
    Write-Host "python not found - attempting to install it via winget..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Python.Python.3 -e --source winget --accept-source-agreements --accept-package-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("Path", "User")
    } else {
        Write-Host "winget is not available. Install Python manually from https://www.python.org/downloads/windows/ (tick 'Add python.exe to PATH'), then re-run this script." -ForegroundColor Red
        exit 1
    }
    if (-not (Resolve-Python)) {
        Write-Host "Python was installed but isn't on PATH in this session yet. Open a new PowerShell window and re-run this script." -ForegroundColor Red
        exit 1
    }
}

Ensure-Git
Ensure-Python

if (Test-Path (Join-Path $RepoDir ".git")) {
    & $GitCmd -C $RepoDir fetch origin
    & $GitCmd -C $RepoDir checkout $Branch
    & $GitCmd -C $RepoDir reset --hard "origin/$Branch"
} else {
    & $GitCmd clone -b $Branch $RepoUrl $RepoDir
}

Set-Location $RepoDir

# PySide6 not being importable yet (first run) makes `python -c "import
# PySide6"` exit non-zero and print a traceback to stderr - exactly the
# signal we're checking for, but under $ErrorActionPreference = "Stop"
# a redirected (`2>`) native-command stderr line gets promoted to a
# terminating error before the redirect ever discards it, crashing this
# script instead of just letting us read $LASTEXITCODE. try/catch treats
# that promoted error the same as a normal non-zero exit: PySide6 needs
# installing.
$needsPySide6 = $true
try {
    & $PythonCmd -c "import PySide6" 2>$null
    $needsPySide6 = ($LASTEXITCODE -ne 0)
} catch {
    $needsPySide6 = $true
}
if ($needsPySide6) {
    Write-Host "Installing PySide6 (one-time)..."
    # OCUT_PYPI_PROXY (optional) points pip at a self-hosted Cloudflare
    # Worker (see cf_worker/) instead of pypi.org/files.pythonhosted.org
    # directly - for an ISP that throttles that direct connection
    # specifically (the wheels here are 70-170MB, a very visible target).
    $pipArgs = @()
    if ($env:OCUT_PYPI_PROXY) {
        $proxy = $env:OCUT_PYPI_PROXY.TrimEnd('/')
        $pipArgs = @("--index-url", "$proxy/simple/")
    }
    & $PythonCmd -m pip install --user @pipArgs -r requirements.txt
}

& $PythonCmd gui.py
