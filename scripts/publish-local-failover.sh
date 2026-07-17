#!/usr/bin/env bash
# Refresca el dist/ LOCAL (el que sirve solvento-app :8120, primario desde el
# 2026-07-14 con prod 10.10.1.38 abandonado) con TODO lo publicado en git,
# excluyendo los borradores (untracked en content/blog). Lo llama el watcher
# solvento-failover-sync tras cada publicación del portal, y deploy.sh al
# reconstruir. (Nombre "failover" heredado del incidente; hoy es el camino
# normal.) Este script hace el último paso, en local y limpio.
#
#   scripts/publish-local-failover.sh
#
# Seguro: aparta los borradores, purga public/blog (el generador no lo poda),
# reconstruye, y RESTAURA los borradores pase lo que pase (trap).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PATH="$(ls -d "$HOME"/.local/share/fnm/node-versions/*/installation/bin 2>/dev/null | sort | tail -1):$PATH"

ASIDE="$(mktemp -d)"
mapfile -t DRAFTS < <(git status --porcelain --untracked-files=all -- frontend/content/blog | awk '$1=="??"{print $2}')

restore() {
  for f in "${DRAFTS[@]}"; do
    rel="${f#frontend/content/blog/}"
    [ -f "$ASIDE/$rel" ] && { mkdir -p "$(dirname "$f")"; mv "$ASIDE/$rel" "$f"; }
  done
  ( cd frontend && node scripts/generate-static-pages.mjs >/dev/null 2>&1 ) || true
  rm -rf "$ASIDE"
}
trap restore EXIT

echo "Apartando ${#DRAFTS[@]} ficheros de borrador…"
for f in "${DRAFTS[@]}"; do
  rel="${f#frontend/content/blog/}"
  mkdir -p "$ASIDE/$(dirname "$rel")"
  mv "$f" "$ASIDE/$rel"
done

echo "Reconstruyendo dist/ solo con lo publicado…"
rm -rf frontend/public/blog          # el generador no poda lo obsoleto
( cd frontend && npm run build >/dev/null 2>&1 )

echo "✓ dist actualizado: $(find frontend/dist/blog -name index.html | wc -l) páginas de blog."
echo "  (los borradores se restauran al salir)"
