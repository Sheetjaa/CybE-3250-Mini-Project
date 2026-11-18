# EE / CprE / CybE 3250: Machine Learning in ECpE
# Joseph Zambreno
# 07/29/26
# 3250_install.sh - run this script to install the Python environment and D2L dependencies all in one place

#!/usr/bin/env bash

set -euo pipefail

# Usage:
#   ./3250_install.sh
# If run in 3250-Labs/, it will take unzip the src/d2l/ folder to your 3250-Labs/ directory and install the venv environment 

# Install uv and refresh terminal if it doesn't already exist
if command -v uv >/dev/null 2>&1; then
    echo "uv already installed, moving on..."
else
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source "$HOME/.local/bin/env"
fi


uv venv --clear --python 3.12
uv sync --extra run --extra build --extra pytorch

# Install chromium with playwright
uv run playwright install chromium

# Open up VS Code in this directory so it can find the .venv
code .

