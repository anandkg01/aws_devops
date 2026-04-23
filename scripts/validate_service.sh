#!/usr/bin/env bash
set -euo pipefail

HTTP_STATUS="$(curl -s -o /dev/null -w "%{http_code}" http://localhost/health)"
if [[ "${HTTP_STATUS}" != "200" ]]; then
  echo "Health check failed. Status: ${HTTP_STATUS}"
  exit 1
fi

echo "Health check passed"
