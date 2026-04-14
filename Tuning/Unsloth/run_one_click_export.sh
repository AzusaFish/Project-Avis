#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:7897}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:7897}"
export ALL_PROXY="${ALL_PROXY:-http://127.0.0.1:7897}"

HF_TOKEN="${HF_TOKEN:-your_huggingface_token_here}"

if ! command -v python >/dev/null 2>&1; then
  echo "Python not found in PATH. Activate your venv first."
  exit 1
fi

python one_click_export.py --token "$HF_TOKEN"
