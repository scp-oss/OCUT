#!/usr/bin/env bash
# Universal launcher: clones ~/OCUT on first run, updates it to the latest
# commit on every later run, then starts the native GUI (gui.py) by
# default - pass --web as the first argument to launch the old
# browser-based server.py instead (still fully maintained, just no
# longer the default). Safe to re-run anytime to pick up updates - local
# edits inside the repo are not expected (this is a managed checkout),
# components.json (gitignored, your own tracked-kext list) is untouched
# by `git reset --hard` either way.
set -e

REPO_URL="https://github.com/scp-oss/OCUT"
BRANCH="claude/gifted-thompson-3q1e6m"
REPO_DIR="$HOME/OCUT"

if [ -d "$REPO_DIR/.git" ]; then
    git -C "$REPO_DIR" fetch origin
    git -C "$REPO_DIR" checkout "$BRANCH"
    git -C "$REPO_DIR" reset --hard "origin/$BRANCH"
else
    git clone -b "$BRANCH" "$REPO_URL" "$REPO_DIR"
fi

cd "$REPO_DIR"

if [ "$1" = "--web" ]; then
    shift
    exec python3 server.py "$@"
fi

# The native GUI needs PySide6 - the one pip dependency this project
# accepts (tkinter ships with Python but can't get anywhere near the
# modern/native look the GUI was built for). Installed once on first run;
# every later run just imports the already-installed package.
if ! python3 -c "import PySide6" >/dev/null 2>&1; then
    echo "Installing PySide6 (one-time)..."
    python3 -m pip install --user -r requirements.txt
fi

exec python3 gui.py "$@"
