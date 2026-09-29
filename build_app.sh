#!/bin/zsh
# Builds dist/CCITT Converter.app. Pass --install to also copy it to /Applications.
set -euo pipefail
cd "$(dirname "$0")"

uv sync
uv run pyinstaller --noconfirm --clean "CCITT Converter.spec"

if [[ "${1:-}" == "--install" ]]; then
  rm -rf "/Applications/CCITT Converter.app"
  cp -R "dist/CCITT Converter.app" /Applications/
  echo "Installed to /Applications/CCITT Converter.app"
else
  echo "Built dist/CCITT Converter.app"
fi
