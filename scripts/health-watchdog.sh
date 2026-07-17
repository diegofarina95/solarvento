#!/usr/bin/env bash
# Vigilante de salud de SolarVento.
#
# Esta máquina (dev) es el PRIMARIO desde el 2026-07-14: el server 10.10.1.38 se
# abandonó por caerse cada pocos días. systemd ya reinicia la app si CRASHEA
# (Restart=on-failure en solvento-app.service); este vigilante cubre lo que
# systemd NO ve:
#   1. CUELGUE: el proceso está vivo pero no responde en :8120 → reinicia
#      solvento-app.
#   2. CAÍDA DEL CAMINO PÚBLICO: la salud local es 200 pero solarvento.es no
#      responde → solo AVISA al journal. El camino público va por el Worker de
#      Cloudflare → Funnel de Tailscale, y el Funnel es COMPARTIDO con ~13 apps
#      (diegofarina.com, etc.): NO se reinicia desde aquí; se revisa a mano.
#
# Lo lanza solvento-watchdog.timer cada 2 min.
# Log:  journalctl --user -t solvento-watchdog
set -u

local_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:8120/api/health || true)
if [ "$local_code" != "200" ]; then
  echo "salud local=$local_code en :8120 — reiniciando solvento-app" | systemd-cat -t solvento-watchdog -p err
  systemctl --user restart solvento-app
  exit 0
fi

public_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 https://solarvento.es/api/health || true)
if [ "$public_code" != "200" ]; then
  echo "salud pública=$public_code con local OK — camino público (Worker/Funnel) caído; el Funnel es compartido, NO se toca desde aquí: revisar a mano" \
    | systemd-cat -t solvento-watchdog -p err
fi
exit 0
