#!/usr/bin/env bash
# Universal launcher: clones ~/OCUT on first run, updates it to the latest
# commit on every later run, then starts the server. Safe to re-run anytime
# to pick up updates - local edits inside the repo are not expected (this
# is a managed checkout), components.json (gitignored, your own tracked-kext
# list) is untouched by `git reset --hard` either way.
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
exec python3 server.py "$@"
