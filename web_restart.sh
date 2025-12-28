#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

./web_stop.sh
sleep 0.2
./web_start.sh
