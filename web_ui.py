#!/usr/bin/env python3
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Optional

from flask import Flask, redirect, render_template_string, request, url_for


APP = Flask(__name__)


FIREPLACE_PY = os.path.join(os.path.dirname(__file__), "fireplace.py")
FIREPLACE_CLI_PYTHON = os.getenv("FIREPLACE_CLI_PYTHON", "python3")


@dataclass
class RunResult:
    when: float
    action: str
    command: str
    exit_code: Optional[int]
    output: str


_lock = threading.Lock()
_last_result: Optional[RunResult] = None
_hold_proc: Optional[subprocess.Popen[str]] = None
_hold_cmd: Optional[str] = None


HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Fireplace Relay UI</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 24px; max-width: 900px; }
    .row { display: flex; gap: 16px; flex-wrap: wrap; }
    .card { border: 1px solid #ddd; border-radius: 10px; padding: 16px; }
    label { display: block; font-size: 14px; margin-top: 10px; }
    input[type=text], input[type=number] { padding: 8px; width: 220px; }
    button { padding: 10px 14px; margin-right: 10px; margin-top: 10px; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
    pre { background: #f6f8fa; padding: 12px; overflow: auto; border-radius: 8px; }
    .small { font-size: 13px; color: #444; }
  </style>
</head>
<body>
  <h1>Fireplace Relay UI (local)</h1>
  <p class="small">Controls <span class="mono">low_flame</span> via <span class="mono">fireplace.py</span>. Bind is local-only by default.</p>

  <div class="row">
    <div class="card" style="flex: 1 1 360px;">
      <h2>Settings</h2>
      <form method="post" action="{{ url_for('run_action') }}">
        <label>Boot guard seconds (applies to ignite/on/off)</label>
        <input type="number" step="0.1" name="boot_guard_seconds" value="{{ boot_guard_seconds }}" />

        <label>Pulse ms (ignite)</label>
        <input type="number" step="1" name="pulse_ms" value="{{ pulse_ms }}" />

        <label>Hold seconds (optional, for Start Hold)</label>
        <input type="number" step="0.1" name="hold_seconds" value="{{ hold_seconds }}" placeholder="blank = hold until Stop" />

        <label style="margin-top: 12px;">
          <input type="checkbox" name="dry_run" {% if dry_run %}checked{% endif %} /> Dry-run (no GPIO)
        </label>
        <label>
          <input type="checkbox" name="active_low" {% if active_low %}checked{% endif %} /> Active-low (invert)
        </label>

        <div>
          <button type="submit" name="action" value="ignite_pulse">Ignite Pulse (low_flame)</button>
          <button type="submit" name="action" value="start_hold">Start Hold (low_flame)</button>
          <button type="submit" name="action" value="stop">Stop (open)</button>
        </div>
      </form>

      <h3>Status</h3>
      <div class="small">
        Hold process: {% if hold_running %}<b>RUNNING</b>{% else %}not running{% endif %}
      </div>
      {% if hold_cmd %}
        <div class="small">Command: <span class="mono">{{ hold_cmd }}</span></div>
      {% endif %}
    </div>

    <div class="card" style="flex: 1 1 460px;">
      <h2>Last Result</h2>
      {% if last %}
        <div class="small">Action: <span class="mono">{{ last.action }}</span></div>
        <div class="small">Exit: <span class="mono">{{ last.exit_code }}</span></div>
        <div class="small">Command: <span class="mono">{{ last.command }}</span></div>
        <pre class="mono">{{ last.output }}</pre>
      {% else %}
        <div class="small">No commands run yet.</div>
      {% endif %}
    </div>
  </div>
</body>
</html>
"""


def _build_common_args(*, boot_guard_seconds: str, dry_run: bool, active_low: bool) -> list[str]:
    # IMPORTANT: default to system python for GPIO access.
    # The dev web server may run in a venv without GPIO pin-factory backends.
    args: list[str] = [FIREPLACE_CLI_PYTHON, FIREPLACE_PY]

    if dry_run:
        args.append("--dry-run")
    if active_low:
        args.append("--active-low")

    # Only meaningful for ignite/on/off, but harmless to include.
    if boot_guard_seconds.strip() != "":
        args += ["--boot-guard-seconds", boot_guard_seconds]

    return args


def _cli_env() -> dict[str, str]:
    env = dict(os.environ)
    # Keep CLI colors off for captured output (web view).
    env["FIREPLACE_COLOR"] = "never"
    env["NO_COLOR"] = "1"
    return env


def _run_sync(action: str, argv: list[str]) -> RunResult:
    started = time.time()
    cmd_str = " ".join(shlex.quote(a) for a in argv)
    try:
        cp = subprocess.run(argv, capture_output=True, text=True, timeout=60, env=_cli_env())
        out = (cp.stdout or "") + (cp.stderr or "")
        return RunResult(when=started, action=action, command=cmd_str, exit_code=cp.returncode, output=out.strip())
    except Exception as e:
        return RunResult(when=started, action=action, command=cmd_str, exit_code=None, output=f"ERROR: {e}")


def _stop_hold_locked() -> RunResult:
    global _hold_proc, _hold_cmd

    started = time.time()
    if _hold_proc is None or _hold_proc.poll() is not None:
        _hold_proc = None
        _hold_cmd = None
        return RunResult(when=started, action="stop", command="(no hold process)", exit_code=0, output="Hold process was not running.")

    proc = _hold_proc
    cmd = _hold_cmd or "(unknown)"

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)

    _hold_proc = None
    _hold_cmd = None

    return RunResult(
        when=started,
        action="stop",
        command=cmd,
        exit_code=0,
        output="Stopped hold process (sent terminate/kill as needed).",
    )


@APP.get("/")
def index():
    with _lock:
        hold_running = _hold_proc is not None and _hold_proc.poll() is None
        hold_cmd = _hold_cmd
        last = _last_result

    # Defaults chosen for safety and convenience.
    return render_template_string(
        HTML,
        boot_guard_seconds=request.args.get("boot_guard_seconds", "12"),
        pulse_ms=request.args.get("pulse_ms", "250"),
        hold_seconds=request.args.get("hold_seconds", ""),
        dry_run=(request.args.get("dry_run", "") == "on"),
        active_low=(request.args.get("active_low", "") == "on"),
        hold_running=hold_running,
        hold_cmd=hold_cmd,
        last=last,
    )


@APP.post("/run")
def run_action():
    global _last_result, _hold_proc, _hold_cmd

    action = (request.form.get("action") or "").strip()
    boot_guard_seconds = request.form.get("boot_guard_seconds", "12")
    pulse_ms = request.form.get("pulse_ms", "250")
    hold_seconds = request.form.get("hold_seconds", "").strip()
    dry_run = request.form.get("dry_run") == "on"
    active_low = request.form.get("active_low") == "on"

    common = _build_common_args(boot_guard_seconds=boot_guard_seconds, dry_run=dry_run, active_low=active_low)

    if action == "ignite_pulse":
        argv = common + ["ignite", "--main-relay", "low_flame", "--pulse-ms", pulse_ms]
        result = _run_sync("ignite_pulse", argv)
        with _lock:
            _last_result = result

    elif action == "start_hold":
        with _lock:
            # If already running, do nothing.
            if _hold_proc is not None and _hold_proc.poll() is None:
                _last_result = RunResult(
                    when=time.time(),
                    action="start_hold",
                    command=_hold_cmd or "(unknown)",
                    exit_code=0,
                    output="Hold process already running.",
                )
            else:
                argv = common + ["on", "--main-relay", "low_flame"]
                if hold_seconds != "":
                    argv += ["--hold-seconds", hold_seconds]

                cmd_str = " ".join(shlex.quote(a) for a in argv)
                try:
                    _hold_proc = subprocess.Popen(
                        argv,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        env=_cli_env(),
                    )
                    _hold_cmd = cmd_str
                    _last_result = RunResult(
                        when=time.time(),
                        action="start_hold",
                        command=cmd_str,
                        exit_code=None,
                        output="Started hold process. Use Stop to open the relay.",
                    )
                except Exception as e:
                    _hold_proc = None
                    _hold_cmd = None
                    _last_result = RunResult(
                        when=time.time(),
                        action="start_hold",
                        command=cmd_str,
                        exit_code=None,
                        output=f"ERROR starting hold: {e}",
                    )

    elif action == "stop":
        with _lock:
            result = _stop_hold_locked()
            _last_result = result

        # Also ensure we actively open the relay via CLI (belt + suspenders).
        argv = common + ["off", "--main-relay", "low_flame"]
        sync = _run_sync("off", argv)
        with _lock:
            _last_result = RunResult(
                when=time.time(),
                action="stop",
                command=f"{result.command}\n{sync.command}",
                exit_code=sync.exit_code,
                output=(result.output + "\n" + (sync.output or "")).strip(),
            )

    else:
        with _lock:
            _last_result = RunResult(when=time.time(), action="unknown", command="", exit_code=1, output="Unknown action")

    # Preserve current form settings in query string for convenience.
    return redirect(
        url_for(
            "index",
            boot_guard_seconds=boot_guard_seconds,
            pulse_ms=pulse_ms,
            hold_seconds=hold_seconds,
            dry_run=("on" if dry_run else ""),
            active_low=("on" if active_low else ""),
        )
    )


def main() -> int:
    host = os.getenv("FIREPLACE_WEB_HOST", "127.0.0.1")
    port = int(os.getenv("FIREPLACE_WEB_PORT", "8080"))
    debug = os.getenv("FIREPLACE_WEB_DEBUG", "").strip().lower() in {"1", "true", "yes", "y"}

    APP.run(host=host, port=port, debug=debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
