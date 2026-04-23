#!/usr/bin/env bash
set -euo pipefail

PID_FILE="/var/run/hello-devops.pid"

if [[ -f "${PID_FILE}" ]]; then
  CURRENT_PID="$(cat "${PID_FILE}")"
  python3 - <<PY
import os
import signal

pid = int("${CURRENT_PID}")
try:
    os.kill(pid, signal.SIGTERM)
except ProcessLookupError:
    pass
PY
  rm -f "${PID_FILE}"
fi
