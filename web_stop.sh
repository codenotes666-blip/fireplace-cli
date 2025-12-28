#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PIDFILE=".web_ui.pid"
LOGFILE=".web_ui.log"

stop_pid() {
  local pid="$1"
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi

  kill "$pid" 2>/dev/null || true
  for _ in {1..30}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 0.1
  done

  kill -9 "$pid" 2>/dev/null || true
}

if [[ -f "$PIDFILE" ]]; then
  pid="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "$pid" ]]; then
    echo "Stopping Web UI (pid=$pid)..."
    stop_pid "$pid" || true
  fi
  rm -f "$PIDFILE"
else
  echo "No PID file found. Attempting to stop any web_ui.py process..."
  pkill -f "web_ui.py" 2>/dev/null || true
fi

echo "Stopped. (Log: $(pwd)/$LOGFILE)"
