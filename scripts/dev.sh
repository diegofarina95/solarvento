#!/usr/bin/env bash
#
# dev.sh — Entorno DEV en este equipo (no toca prod nunca).
#
# Uso:
#   scripts/dev.sh test     # tests de backend (pytest, sin integración) + frontend (node --test)
#   scripts/dev.sh serve    # build del frontend + uvicorn en :8120 sirviendo el dist (como prod)
#   scripts/dev.sh api      # solo backend con --reload en :8120 (para tocar Python)
#   scripts/dev.sh web      # solo frontend con Vite hot-reload (para tocar la UI)
#   scripts/dev.sh stop     # para la instancia dev de :8120
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"
PORT=8120
PY=backend/.venv/bin/python

cmd="${1:-serve}"
case "$cmd" in
  test)
    echo "== backend =="
    if [ -x "$PY" ] && "$PY" -c "import pytest" 2>/dev/null; then
      ( cd backend && .venv/bin/python -m pytest tests -q -m "not integration" )
    else echo "(pytest no disponible en backend/.venv; saltado)"; fi
    echo "== frontend =="
    ( cd frontend && node --test ) || true
    ;;
  serve)
    ( cd frontend && npm run build )
    echo "Backend DEV (sirve dist) en http://127.0.0.1:$PORT"
    ( cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT" )
    ;;
  api)
    echo "Backend DEV --reload en http://127.0.0.1:$PORT"
    ( cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --reload )
    ;;
  web)
    ( cd frontend && npm run dev )
    ;;
  stop)
    pids="$(ss -ltnp 2>/dev/null | grep ":$PORT " | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u || true)"
    if [ -n "$pids" ]; then echo "$pids" | xargs -r kill && echo "Parada instancia dev :$PORT (pids: $pids)"; else echo "(no hay nada en :$PORT)"; fi
    ;;
  *) echo "Uso: scripts/dev.sh {test|serve|api|web|stop}"; exit 1 ;;
esac
