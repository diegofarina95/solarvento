#!/bin/bash
# Vigilante de SolarVento. systemd ya cubre los CRASHES (Restart=on-failure en
# solvento-backend.service); esto cubre lo que systemd no ve:
#   1. CUELGUES: proceso vivo que no responde → reinicia el backend.
#   2. TÚNEL caído: salud local OK pero la web pública no → reinicia cloudflared.
# Lo lanza solvento-watchdog.timer cada 2 minutos. Log: journalctl -t solvento-watchdog
set -u

local_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:8000/api/health || true)
if [ "$local_code" != "200" ]; then
  echo "salud local=$local_code — reiniciando solvento-backend" | systemd-cat -t solvento-watchdog -p err
  systemctl restart solvento-backend
  exit 0
fi

public_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 https://solarvento.es/api/health || true)
if [ "$public_code" != "200" ]; then
  echo "salud pública=$public_code con local OK — reiniciando cloudflared" | systemd-cat -t solvento-watchdog -p err
  systemctl restart cloudflared
fi
exit 0
