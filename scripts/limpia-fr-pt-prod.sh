#!/usr/bin/env bash
# Retira de PROD las páginas FR/PT huérfanas (faq/privacidad) tras el deploy
# que eliminó esos idiomas (2026-07-08). Necesario porque deploy.sh hace rsync
# SIN --delete (anti-pisotones): los archivos borrados en dev sobreviven en el
# árbol de prod y el build de Vite los volvería a copiar a dist/.
# Uso: scripts/limpia-fr-pt-prod.sh   (una sola vez, tras el deploy)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
get_env() { grep -iE "^$1[[:space:]]*:" "$ROOT_DIR/.env" | head -1 | sed 's/^[^:]*:[[:space:]]*//'; }
SSH_ADDRESS="$(get_env SSH_ADDRESS)"; SSH_PORT="$(get_env SSH_PORT)"
SSH_USER="$(get_env SSH_USER)"; SSH_PASSWORD="$(get_env SSH_PASSWORD)"
REMOTE_PATH="$(get_env PATH)"
SSH_PORT="${SSH_PORT:-22}"

FILES="faq-fr.html faq-pt.html privacidad-fr.html privacidad-pt.html"
CMD="cd '$REMOTE_PATH/frontend'"
for f in $FILES; do CMD="$CMD && rm -fv public/$f dist/$f"; done
CMD="$CMD && cd '$REMOTE_PATH' && git add -A && (git commit -q -m 'retira páginas FR/PT huérfanas' || true)"

sshpass -p "$SSH_PASSWORD" ssh -o StrictHostKeyChecking=accept-new -p "$SSH_PORT" \
  "$SSH_USER@$SSH_ADDRESS" "$CMD"
echo "✓ páginas FR/PT retiradas de prod (public/ y dist/)"
