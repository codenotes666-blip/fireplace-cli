#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

LOW_NAME="low_flame"
HIGH_NAME="high_flame"
HOLD_SECONDS="${1:-3}"
MODE="${2:-high}"

cat <<EOF
Low/High relay demo (safe when NOT connected to fireplace terminals)

This will energize each relay for ${HOLD_SECONDS}s so you can see which channel LED/click maps to:
  - ${LOW_NAME}  (BCM 4)
  - ${HIGH_NAME} (BCM 22)

NOTE: polarity depends on your HAT. This demo runs two passes:
Mode:
  - high: ACTIVE-HIGH only (default; confirmed on this installed shield)
  - low:  ACTIVE-LOW only (inverted)
  - both: run ACTIVE-HIGH then ACTIVE-LOW

Watch which relay channel LED turns ON during the CLOSE-ACTIVATE hold.
EOF

run_pass() {
  local pass_name="$1"
  local active_low_flag="$2"

  echo
  read -r -p "Press ENTER to start ${pass_name}..." _

  echo
  echo "=== ${pass_name}: ${LOW_NAME} ==="
  read -r -p "Press ENTER to energize ${LOW_NAME} for ${HOLD_SECONDS}s..." _
  python3 fireplace.py probe ${active_low_flag} --pins 4 --open-seconds 0.5 --close-seconds "$HOLD_SECONDS" --post-open-seconds 0.5

  sleep 1

  echo
  echo "=== ${pass_name}: ${HIGH_NAME} ==="
  read -r -p "Press ENTER to energize ${HIGH_NAME} for ${HOLD_SECONDS}s..." _
  python3 fireplace.py probe ${active_low_flag} --pins 22 --open-seconds 0.5 --close-seconds "$HOLD_SECONDS" --post-open-seconds 0.5
}

case "$MODE" in
  high)
    run_pass "ACTIVE-HIGH (default)" ""
    ;;
  low)
    run_pass "ACTIVE-LOW (inverted)" "--active-low"
    ;;
  both)
    run_pass "ACTIVE-HIGH (default)" ""
    run_pass "ACTIVE-LOW (inverted)" "--active-low"
    ;;
  *)
    echo "Unknown mode '$MODE'. Use: high | low | both" >&2
    exit 2
    ;;
esac

echo
echo "Done. low_flame should map to physical relay #1; high_flame to #2."
