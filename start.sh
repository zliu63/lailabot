#!/bin/bash
set -e

cd "$(dirname "$0")"

# Load environment variables
set -a
source .env
set +a

# Activate venv
source .venv/bin/activate

# Start LailaBot
exec python -m lailabot
