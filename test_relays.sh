#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PINS_DEFAULT="4,22,6,26"
PULSE_MS_DEFAULT="900"
GAP_SECONDS_DEFAULT="2.0"
OPEN_SECONDS_DEFAULT="0.0"
CLOSE_SECONDS_DEFAULT="2.0"
POST_OPEN_SECONDS_DEFAULT="1.0"

PINS="${1:-$PINS_DEFAULT}"
PULSE_MS="${2:-$PULSE_MS_DEFAULT}"
GAP_SECONDS="${3:-$GAP_SECONDS_DEFAULT}"
OPEN_SECONDS="${4:-$OPEN_SECONDS_DEFAULT}"
CLOSE_SECONDS="${5:-$CLOSE_SECONDS_DEFAULT}"
POST_OPEN_SECONDS="${6:-$POST_OPEN_SECONDS_DEFAULT}"
MODE="${7:-high}"

cat <<EOF
Relay click test (shield NOT connected to fireplace terminals)

This will pulse these BCM pins: ${PINS}
Naming convention (used by fireplace.py):
  low_flame  -> BCM 4
  high_flame -> BCM 22
  aux_1      -> BCM 6
  aux_2      -> BCM 26
Pulse width: ${PULSE_MS}ms
Gap between pins: ${GAP_SECONDS}s
OPEN-DEACTIVATE phase: ${OPEN_SECONDS}s
CLOSE-ACTIVATE phase: ${CLOSE_SECONDS}s
POST-OPEN-DEACTIVATE phase: ${POST_OPEN_SECONDS}s

Listen for relay clicks / watch channel LEDs.
Mode:
  - high: ACTIVE-HIGH only (default; confirmed on this installed shield)
  - low:  ACTIVE-LOW only (inverted)
  - both: run ACTIVE-HIGH then ACTIVE-LOW

Tip: The correct mode is the one where the relay is ON during the printed CLOSE-ACTIVATE phase.
EOF

IFS=',' read -r -a PINS_ARR <<< "$PINS"

run_pass() {
  local pass_name="$1"
  local active_low_flag="$2"

  echo
  read -r -p "Press ENTER to start ${pass_name} pass..." _

  for pin in "${PINS_ARR[@]}"; do
    pin="${pin//[[:space:]]/}"
    [[ -z "$pin" ]] && continue
    echo
    echo "=== ${pass_name}: BCM ${pin} ==="
    read -r -p "Press ENTER to pulse BCM ${pin}..." _
    python3 fireplace.py probe ${active_low_flag} \
      --pins "$pin" \
      --pulse-ms "$PULSE_MS" \
      --open-seconds "$OPEN_SECONDS" \
      --close-seconds "$CLOSE_SECONDS" \
      --post-open-seconds "$POST_OPEN_SECONDS"
    sleep "$GAP_SECONDS"
  done
}

case "$MODE" in
  high)
    echo
    echo "Running ACTIVE-HIGH pass only (default for KS0212 docs)."
    run_pass "ACTIVE-HIGH" ""
    ;;
  low)
    echo
    echo "Running ACTIVE-LOW pass only (inverted polarity)."
    run_pass "ACTIVE-LOW" "--active-low"
    ;;
  both)
    run_pass "ACTIVE-HIGH" ""
    run_pass "ACTIVE-LOW" "--active-low"
    ;;
  *)
    echo "Unknown mode '$MODE'. Use: high | low | both" >&2
    exit 2
    ;;
esac

echo
echo "Done. Tell me which BCM pin clicked and which relay channel LED blinked (CH1-CH4)."