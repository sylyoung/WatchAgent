#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SPEC_FILE="$ROOT_DIR/project.yml"

if ! command -v xcodegen >/dev/null 2>&1; then
  echo "xcodegen not found. Install with: brew install xcodegen"
  exit 1
fi

cd "$ROOT_DIR"
xcodegen --spec "$SPEC_FILE"
echo "Generated: $ROOT_DIR/WatchAgent.xcodeproj"
