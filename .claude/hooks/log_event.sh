#!/usr/bin/env bash
# Logging-only hook: appends every hook invocation's payload to a local log file.
# Always exits 0 — never blocks, never gives feedback, purely observational.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
log_dir="$script_dir/../logs"
mkdir -p "$log_dir"
log_file="$log_dir/hooks.log"

input=$(cat)
event=$(echo "$input" | jq -r '.hook_event_name // "unknown"' 2>/dev/null || echo "unknown")
ts=$(date '+%Y-%m-%dT%H:%M:%S%z')

{
  printf '[%s] %s\n' "$ts" "$event"
  echo "$input" | jq -c . 2>/dev/null || echo "$input"
} >> "$log_file"

exit 0
