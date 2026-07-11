#!/usr/bin/env bash
# PostToolUse hook: after Claude edits/writes a .py file, verify it still parses.
# Exit 2 feeds stderr back to Claude as feedback (see Claude Code hooks docs).
set -euo pipefail

input=$(cat)
file_path=$(echo "$input" | jq -r '.tool_input.file_path // empty')

if [[ -z "$file_path" || "$file_path" != *.py || ! -f "$file_path" ]]; then
  exit 0
fi

if ! error=$(python3 -m py_compile "$file_path" 2>&1); then
  echo "Syntax error in $file_path:" >&2
  echo "$error" >&2
  exit 2
fi

exit 0
