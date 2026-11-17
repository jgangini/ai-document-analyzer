#!/usr/bin/env bash
set -euo pipefail

mkdir -p \
  /app/apps/backend/data \
  /app/apps/backend/wallet \
  /app/apps/backend/keys \
  /app/apps/backend/logs

if [[ -f /app/apps/backend/.env.example && ! -f /app/apps/backend/.env ]]; then
  cp /app/apps/backend/.env.example /app/apps/backend/.env
fi

python -m uvicorn apps.backend.app.main:app --host 127.0.0.1 --port 8012 &
backend_pid="$!"

cleanup() {
  if kill -0 "$backend_pid" 2>/dev/null; then
    kill "$backend_pid" 2>/dev/null || true
    wait "$backend_pid" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

nginx -g 'daemon off;' &
nginx_pid="$!"

wait -n "$backend_pid" "$nginx_pid"
exit_code="$?"

cleanup
if kill -0 "$nginx_pid" 2>/dev/null; then
  kill "$nginx_pid" 2>/dev/null || true
  wait "$nginx_pid" 2>/dev/null || true
fi

exit "$exit_code"
