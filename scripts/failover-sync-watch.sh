#!/usr/bin/env bash
# Watcher de publicación del blog. Esta máquina es el PRIMARIO desde el
# 2026-07-14 (prod 10.10.1.38 abandonado por inestable): el portal commitea las
# publicaciones a git, y este watcher detecta cada commit nuevo y ejecuta
# publish-local-failover.sh para empujar lo publicado al dist/ local que sirve
# solvento-app. (Nombre "failover" heredado del incidente; hoy es el camino
# normal y único de publicación.)
#
# Seguro frente al portal: espera si .drafts-aside existe (el portal está a
# mitad de un publish_group) para no manipular los mismos ficheros a la vez.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

applied=""
while true; do
  cur="$(git rev-parse HEAD 2>/dev/null || echo none)"
  if [ "$cur" != "$applied" ] && [ ! -e "$ROOT/.drafts-aside" ]; then
    sleep 15  # settle: deja que el portal termine (commit va antes del restore)
    if [ ! -e "$ROOT/.drafts-aside" ] && [ "$(git rev-parse HEAD 2>/dev/null)" = "$cur" ]; then
      echo "[failover-sync] commit ${cur:0:9} → refrescando dist local"
      if scripts/publish-local-failover.sh; then
        applied="$cur"
        echo "[failover-sync] OK"
      else
        echo "[failover-sync] fallo al refrescar; reintento en el próximo ciclo"
      fi
    fi
  fi
  sleep 30
done
