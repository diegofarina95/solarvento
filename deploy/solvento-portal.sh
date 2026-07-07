#!/usr/bin/env bash
# Launcher del portal del blog: SOLO en la máquina de dev.
# Hace bind a la IP de Tailscale (si tailscaled aún no está listo, systemd
# reintenta vía Restart=on-failure). El puerto se puede cambiar con PORTAL_PORT.
set -euo pipefail

REPO="/home/diego/taller-projects/solvento"
IP="$(tailscale ip -4 | head -n1)"
[ -n "$IP" ] || { echo "sin IP de Tailscale" >&2; exit 1; }

# node (fnm) para el generador de páginas, por si el PATH del servicio es mínimo
NODE_BIN="$(ls -d "$HOME"/.local/share/fnm/node-versions/*/installation/bin 2>/dev/null | sort | tail -n1 || true)"
[ -n "${NODE_BIN}" ] && export PATH="$NODE_BIN:$PATH"

cd "$REPO/backend"
exec .venv/bin/uvicorn app.portal:app --host "$IP" --port "${PORTAL_PORT:-8130}"
