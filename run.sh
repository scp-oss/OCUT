#!/usr/bin/env bash
# Universal launcher: clones ~/OCUT on first run, updates it to the latest
# commit on every later run, then starts the native GUI (gui.py). Safe to
# re-run anytime to pick up updates - local edits inside the repo are not
# expected (this is a managed checkout), components.json (gitignored,
# your own tracked-kext list) is untouched by `git reset --hard` either way.
set -e

REPO_URL="https://github.com/scp-oss/OCUT"
BRANCH="claude/gifted-thompson-3q1e6m"
REPO_DIR="$HOME/OCUT"

SUDO_CMD=""
if [ "$(id -u)" != "0" ] && command -v sudo >/dev/null 2>&1; then
    SUDO_CMD="sudo"
fi

# Covers macOS (Homebrew, or a nudge toward Xcode Command Line Tools if
# Homebrew itself isn't installed) and the common Linux package managers -
# minimal/server/container images (exactly the kind of environment someone
# following a curl|bash quick start is likely running from) often don't
# ship git at all.
ensure_git() {
    if command -v git >/dev/null 2>&1; then
        return
    fi
    echo "git not found - attempting to install it..."
    if [ "$(uname)" = "Darwin" ]; then
        if command -v brew >/dev/null 2>&1; then
            brew install git
        else
            echo "git is missing and Homebrew isn't installed. Run 'xcode-select --install' (opens a one-click installer), or install Homebrew first, then re-run this script." >&2
            exit 1
        fi
    elif command -v apt-get >/dev/null 2>&1; then
        $SUDO_CMD apt-get update && $SUDO_CMD apt-get install -y git
    elif command -v dnf >/dev/null 2>&1; then
        $SUDO_CMD dnf install -y git
    elif command -v yum >/dev/null 2>&1; then
        $SUDO_CMD yum install -y git
    elif command -v pacman >/dev/null 2>&1; then
        $SUDO_CMD pacman -Sy --noconfirm git
    elif command -v zypper >/dev/null 2>&1; then
        $SUDO_CMD zypper install -y git
    elif command -v apk >/dev/null 2>&1; then
        $SUDO_CMD apk add git
    elif command -v brew >/dev/null 2>&1; then
        brew install git
    else
        echo "Could not detect a package manager to install git automatically. Please install git manually and re-run this script." >&2
        exit 1
    fi
    if ! command -v git >/dev/null 2>&1; then
        echo "git installation appears to have failed. Please install git manually and re-run this script." >&2
        exit 1
    fi
}

# Same idea as ensure_git() - python3 (plus its pip module, needed a few
# lines down to install PySide6) is just as often missing from a minimal
# Linux image as git is.
ensure_python() {
    if command -v python3 >/dev/null 2>&1; then
        return
    fi
    echo "python3 not found - attempting to install it..."
    if [ "$(uname)" = "Darwin" ]; then
        if command -v brew >/dev/null 2>&1; then
            brew install python3
        else
            echo "python3 is missing and Homebrew isn't installed. Install Python 3 from https://www.python.org/downloads/macos/, or install Homebrew first, then re-run this script." >&2
            exit 1
        fi
    elif command -v apt-get >/dev/null 2>&1; then
        $SUDO_CMD apt-get update && $SUDO_CMD apt-get install -y python3 python3-pip
    elif command -v dnf >/dev/null 2>&1; then
        $SUDO_CMD dnf install -y python3 python3-pip
    elif command -v yum >/dev/null 2>&1; then
        $SUDO_CMD yum install -y python3 python3-pip
    elif command -v pacman >/dev/null 2>&1; then
        $SUDO_CMD pacman -Sy --noconfirm python python-pip
    elif command -v zypper >/dev/null 2>&1; then
        $SUDO_CMD zypper install -y python3 python3-pip
    elif command -v apk >/dev/null 2>&1; then
        $SUDO_CMD apk add python3 py3-pip
    elif command -v brew >/dev/null 2>&1; then
        brew install python3
    else
        echo "Could not detect a package manager to install python3 automatically. Please install it manually and re-run this script." >&2
        exit 1
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        echo "python3 installation appears to have failed. Please install it manually and re-run this script." >&2
        exit 1
    fi
}

ensure_git
ensure_python

if [ -d "$REPO_DIR/.git" ]; then
    git -C "$REPO_DIR" fetch origin
    git -C "$REPO_DIR" checkout "$BRANCH"
    git -C "$REPO_DIR" reset --hard "origin/$BRANCH"
else
    git clone -b "$BRANCH" "$REPO_URL" "$REPO_DIR"
fi

cd "$REPO_DIR"

# The native GUI needs PySide6 - the one pip dependency this project
# accepts (tkinter ships with Python but can't get anywhere near the
# modern/native look the GUI was built for). Installed once on first run;
# every later run just imports the already-installed package.
if ! python3 -c "import PySide6" >/dev/null 2>&1; then
    echo "Installing PySide6 (one-time)..."
    python3 -m pip install --user -r requirements.txt
fi

exec python3 gui.py "$@"
