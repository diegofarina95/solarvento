#!/usr/bin/env bash
#
# deploy.sh — Despliegue LOCAL de SolarVento.
#
# Esta máquina es el PRIMARIO desde el 2026-07-14: el server 10.10.1.38 se
# abandonó por caerse cada pocos días. Ya NO hay servidor remoto; "desplegar"
# aquí significa:
#
#   1. Gate: build del frontend + import del backend + tests. Si algo falla,
#      NO se toca la app viva (sigue sirviendo la versión anterior).
#   2. Reconstruir el dist/ limpio (aparta los borradores del blog, purga
#      public/blog y reconstruye) — reutiliza publish-local-failover.sh.
#   3. Reiniciar solvento-app (uvicorn :8120) para recoger los cambios de
#      backend.
#   4. Health-check en :8120 con reintentos.
#
# La app la sirve solvento-app y la publica solarvento.es vía el Worker de
# Cloudflare → Funnel de Tailscale. El blog se auto-refresca aparte con
# solvento-failover-sync tras cada publicación del portal.
#
# Uso:
#   scripts/deploy.sh            # gate + rebuild + restart (pide confirmación)
#   scripts/deploy.sh --yes      # sin preguntar
#   scripts/deploy.sh --check    # SOLO el gate (no reconstruye ni reinicia)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"
# node vía fnm (los servicios --user no heredan el PATH del shell interactivo)
export PATH="$(ls -d "$HOME"/.local/share/fnm/node-versions/*/installation/bin 2>/dev/null | sort | tail -1):$PATH"

if [ -t 1 ]; then C_G=$'\e[32m'; C_Y=$'\e[33m'; C_R=$'\e[31m'; C_B=$'\e[1m'; C_0=$'\e[0m'; else C_G=; C_Y=; C_R=; C_B=; C_0=; fi
info() { printf '%s==>%s %s\n' "$C_B" "$C_0" "$*"; }
ok()   { printf '%s✓%s %s\n' "$C_G" "$C_0" "$*"; }
warn() { printf '%s!%s %s\n' "$C_Y" "$C_0" "$*"; }
die()  { printf '%s✗ %s%s\n' "$C_R" "$*" "$C_0" >&2; exit 1; }

CHECK_ONLY=0; ASSUME_YES=0
for a in "$@"; do
  case "$a" in
    --check)  CHECK_ONLY=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    *) die "Flag desconocido: $a" ;;
  esac
done

SERVICE="solvento-app"
HEALTH="http://127.0.0.1:8120/api/health"

# ============================================================
# 1) GATE — si esto falla, la app viva ni se entera
# ============================================================
info "Gate: build del frontend"
( cd frontend && npm run build ) >/dev/null 2>&1 || die "Build del frontend FALLA. Aborto (app intacta)."
ok "Frontend construye"

if [ -x backend/.venv/bin/python ]; then
  backend/.venv/bin/python -c "import sys; sys.path.insert(0,'backend'); import app.main" 2>/dev/null \
    || die "import app.main FALLA. Aborto (app intacta)."
  ok "Backend importa"
  if backend/.venv/bin/python -c "import pytest" 2>/dev/null; then
    ( cd backend && .venv/bin/python -m pytest tests -q -m "not integration" ) >/dev/null 2>&1 \
      || die "Tests de backend FALLAN. Aborto (app intacta)."
    ok "Tests de backend pasan"
  else
    warn "pytest no está en el venv; me salto los tests"
  fi
else
  warn "No hay backend/.venv; me salto el import-check y los tests"
fi

if [ "$CHECK_ONLY" -eq 1 ]; then ok "Gate OK. No se ha tocado la app (--check)."; exit 0; fi

if [ "$ASSUME_YES" -ne 1 ]; then
  printf '%s¿Reconstruir dist y reiniciar %s? [y/N] %s' "$C_Y" "$SERVICE" "$C_0"; read -r ans
  case "$ans" in y|Y|yes|si|s) ;; *) die "Cancelado por el usuario."; esac
fi

# ============================================================
# 2) Reconstruir dist limpio (borradores apartados) y 3) reiniciar
# ============================================================
info "Reconstruyendo dist/ solo con lo publicado"
scripts/publish-local-failover.sh || die "El rebuild del dist FALLA. Aborto (app intacta)."

info "Reiniciando $SERVICE"
systemctl --user restart "$SERVICE" || die "restart de $SERVICE falló."

# ============================================================
# 4) Health-check con reintentos
# ============================================================
info "Health-check ($HEALTH)"
code="$(curl -s --retry 10 --retry-delay 1 --retry-all-errors -o /dev/null -w '%{http_code}' "$HEALTH" 2>/dev/null | tr -d '[:space:]' || true)"
[ "$code" = "200" ] || die "Salud tras el restart = '$code' (esperaba 200). Revisa: journalctl --user -u $SERVICE -n50"
ok "Salud 200 — despliegue local vivo."
