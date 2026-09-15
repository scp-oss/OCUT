#!/usr/bin/env bash
# One-command deploy for the PyPI proxy Worker (see worker.js for why:
# routes pip's PySide6 download through Cloudflare's edge instead of a
# direct connection to files.pythonhosted.org, for an ISP that throttles
# that direct connection specifically). Needs Node.js (for `npx
# wrangler`) and a Cloudflare account - the free plan is enough for
# personal use.
#
#   bash cf_worker/deploy.sh
#
# On Windows, run this from Git Bash (ships with Git for Windows, which
# run.ps1 already installs automatically if it's missing) - wrangler
# itself is cross-platform via npx.
set -e

cd "$(dirname "$0")"

if ! command -v npx >/dev/null 2>&1; then
    echo "Node.js (npx) not found. Install it from https://nodejs.org/ (LTS), then re-run this script." >&2
    exit 1
fi

if [ -z "$CLOUDFLARE_API_TOKEN" ]; then
    echo "Cloudflare needs an API token to deploy to your account."
    echo "Create one at https://dash.cloudflare.com/profile/api-tokens (the \"Edit Cloudflare Workers\" template is enough)."
    read -rp "Paste your Cloudflare API token: " CLOUDFLARE_API_TOKEN
    export CLOUDFLARE_API_TOKEN
fi

npx --yes wrangler deploy

echo
echo "Deployed. Copy the worker URL printed above"
echo "(https://ocut-pypi-proxy.<your-subdomain>.workers.dev) and set it"
echo "before running run.sh/run.ps1, e.g.:"
echo
echo "  OCUT_PYPI_PROXY=https://ocut-pypi-proxy.<your-subdomain>.workers.dev bash run.sh"
