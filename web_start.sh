#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PY="${FIREPLACE_WEB_PYTHON:-/home/gbrill/.venv/bin/python}"
HOST="${FIREPLACE_WEB_HOST:-127.0.0.1}"
PORT="${FIREPLACE_WEB_PORT:-8080}"
SUDO="${FIREPLACE_WEB_SUDO:-0}"

PIDFILE=".web_ui.pid"
LOGFILE=".web_ui.log"

is_running() {
  if [[ -f "$PIDFILE" ]]; then
    local pid
    pid="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
  fi
  return 1
}

if is_running; then
  echo "Web UI already running (pid=$(cat "$PIDFILE"))."
  echo "URL: http://${HOST}:${PORT}"
  exit 0
fi

# Start in background, write pid, and log output.
# Note: GPIO access may require sudo depending on your Pi setup.
cmd=("$PY" "web_ui.py")

env FIREPLACE_WEB_HOST="$HOST" FIREPLACE_WEB_PORT="$PORT" \
  bash -c "
    set -e
    if [[ '$SUDO' == '1' ]]; then
      nohup sudo -E \"${cmd[0]}\" \"${cmd[1]}\" >> \"$LOGFILE\" 2>&1 &
    else
      nohup \"${cmd[0]}\" \"${cmd[1]}\" >> \"$LOGFILE\" 2>&1 &
    fi
    echo \$! > \"$PIDFILE\"
  "

sleep 0.2

if is_running; then
  echo "Started Web UI (pid=$(cat "$PIDFILE"))."
  echo "URL: http://${HOST}:${PORT}"
  echo "Log: $(pwd)/$LOGFILE"
else
  echo "Failed to start Web UI. Last 60 log lines:" >&2
  tail -n 60 "$LOGFILE" >&2 || true
  exit 1
fi
