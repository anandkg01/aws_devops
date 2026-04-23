#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/hello-devops"
LOG_DIR="/var/log/hello-devops"

mkdir -p "${LOG_DIR}"
python3 -m pip install --upgrade pip
python3 -m pip install -r "${APP_DIR}/requirements.txt"
