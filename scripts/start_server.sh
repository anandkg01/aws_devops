#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/hello-devops"
LOG_DIR="/var/log/hello-devops"
PID_FILE="/var/run/hello-devops.pid"

mkdir -p "${LOG_DIR}"

if [[ -f "${PID_FILE}" ]]; then
  CURRENT_PID="$(cat "${PID_FILE}")"
  if python3 -c "import os; os.kill(int('${CURRENT_PID}'), 0)" 2>/dev/null; then
    echo "App is already running"
    exit 0
  fi
fi

cd "${APP_DIR}"
PORT=80 nohup python3 app.py >> "${LOG_DIR}/app.log" 2>&1 &
echo $! > "${PID_FILE}"
