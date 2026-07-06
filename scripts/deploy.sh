#!/usr/bin/env bash
#
# deploy.sh — Despliegue SEGURO de SolarVento desde este equipo (DEV) a producción.
#
# Filosofía dev/prod: este equipo es DEV (aquí se edita y prueba); el servidor
# 10.10.1.38 es PROD. Este script hace que un despliegue roto NO tumbe prod:
#
#   1. Gate local: build del frontend + import del backend (+ tests si hay).
#      Si algo falla aquí, NO se toca prod.
#   2. Snapshot en prod (commit git) como punto de rollback.
#   3. rsync local -> prod (con exclusiones, sin --delete).
#   4. build + import-check en prod. Si fallan: rollback y NO se reinicia
#      (prod sigue sirviendo la versión anterior, intacta).
#   5. restart + health-check con reintentos. Si la salud no da 200:
#      ROLLBACK AUTOMÁTICO a la versión anterior (reset + rebuild + restart).
#   6. Solo si todo va bien: commit del estado desplegado en prod.
#
# Uso:
#   scripts/deploy.sh --dry-run       # solo muestra qué cambiaría (no toca prod)
#   scripts/deploy.sh                 # despliega (pide confirmación)
#   scripts/deploy.sh --yes           # despliega sin preguntar
#   scripts/deploy.sh --allow-dirty   # continúa aunque prod tenga ediciones directas
#
# Guarda anti-pisotones: si el árbol git de PROD tiene cambios sin commitear
# (alguien editó en el servidor), el deploy ABORTA: ese trabajo no existe en
# local y el rsync lo pisaría. Recupéralo a local primero.
#
set -euo pipefail

# --- localización del proyecto y .env ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
cd "$ROOT_DIR"

# --- colores / logging ---
if [ -t 1 ]; then C_G=$'\e[32m'; C_Y=$'\e[33m'; C_R=$'\e[31m'; C_B=$'\e[1m'; C_0=$'\e[0m'; else C_G=; C_Y=; C_R=; C_B=; C_0=; fi
info() { printf '%s==>%s %s\n' "$C_B" "$C_0" "$*"; }
ok()   { printf '%s✓%s %s\n' "$C_G" "$C_0" "$*"; }
warn() { printf '%s!%s %s\n' "$C_Y" "$C_0" "$*"; }
die()  { printf '%s✗ %s%s\n' "$C_R" "$*" "$C_0" >&2; exit 1; }

# --- flags ---
DRY_RUN=0; ASSUME_YES=0; ALLOW_DIRTY=0
for a in "$@"; do
  case "$a" in
    --dry-run)     DRY_RUN=1 ;;
    --yes|-y)      ASSUME_YES=1 ;;
    --allow-dirty) ALLOW_DIRTY=1 ;;
    *) die "Flag desconocido: $a" ;;
  esac
done

# --- leer .env (formato "CLAVE: valor") ---
[ -f "$ENV_FILE" ] || die "No encuentro .env en $ENV_FILE"
get_env() { grep -iE "^$1[[:space:]]*:" "$ENV_FILE" | head -1 | sed 's/^[^:]*:[[:space:]]*//'; }
SSH_ADDRESS="$(get_env SSH_ADDRESS)"
SSH_PORT="$(get_env SSH_PORT)"
SSH_USER="$(get_env SSH_USER)"
SSH_PASSWORD="$(get_env SSH_PASSWORD)"
REMOTE_PATH="$(get_env PATH)"
[ -n "$SSH_ADDRESS" ] && [ -n "$SSH_USER" ] && [ -n "$REMOTE_PATH" ] || die "Faltan claves en .env (SSH_ADDRESS/SSH_USER/PATH)"
SSH_PORT="${SSH_PORT:-22}"
command -v sshpass >/dev/null || die "sshpass no instalado"
command -v rsync   >/dev/null || die "rsync no instalado"

# --- helpers remotos ---
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -p "$SSH_PORT")
rsh() { sshpass -p "$SSH_PASSWORD" ssh "${SSH_OPTS[@]}" "$SSH_USER@$SSH_ADDRESS" "$@"; }
# ejecuta un comando remoto con sudo usando la misma contraseña por stdin
rsudo() { rsh "echo '$SSH_PASSWORD' | sudo -S -p '' $*"; }

SERVICE="solvento-backend"
HEALTH="http://127.0.0.1:8000/api/health"
EXCLUDES=(--exclude='.git' --exclude='.venv' --exclude='node_modules' --exclude='dist' \
          --exclude='__pycache__' --exclude='*.pyc' --exclude='.env' --exclude='*.db' \
          --exclude='.claude' --exclude='.pytest_cache' --exclude='*.egg-info' --exclude='.taller')

# ============================================================
# 0) GUARDA — ¿prod tiene ediciones directas sin commitear?
#    (Incidente 2026-07-06: una feature de privacidad editada a mano en prod
#    fue pisada por el rsync. Si el árbol de prod no está limpio, hay trabajo
#    que NO existe en local: recupéralo antes de desplegar.)
# ============================================================
info "Comprobando que prod no tiene ediciones directas sin commitear"
DIRTY="$(rsh "cd '$REMOTE_PATH' && git status --porcelain" 2>/dev/null || true)"
if [ -n "$DIRTY" ]; then
  printf '%s\n' "$DIRTY" | head -20
  if [ "$ALLOW_DIRTY" -eq 1 ]; then
    warn "Prod tiene ediciones directas; continúo por --allow-dirty (el snapshot pre-deploy las preservará en git)"
  else
    die "PROD tiene ediciones directas sin commitear (lista arriba). Tráelas a local antes de desplegar, o relanza con --allow-dirty para continuar (quedarán en el snapshot git de prod, pero el rsync puede pisarlas en el árbol)."
  fi
else
  ok "Árbol de prod limpio"
fi

# ============================================================
# 1) GATE LOCAL — si esto falla, prod ni se entera
# ============================================================
info "Gate local (DEV): build de frontend + import de backend"
( cd frontend && npm run build ) >/dev/null 2>&1 || die "Build del frontend FALLA en local. Aborto (prod intacto)."
ok "Frontend construye en local"

if [ -x backend/.venv/bin/python ]; then
  backend/.venv/bin/python -c "import sys; sys.path.insert(0,'backend'); import app.main" 2>/dev/null \
    || die "import app.main FALLA en local. Aborto (prod intacto)."
  ok "Backend importa en local"
  if backend/.venv/bin/python -c "import pytest" 2>/dev/null; then
    ( cd backend && .venv/bin/python -m pytest tests -q -m "not integration" ) || die "Tests de backend FALLAN. Aborto."
    ok "Tests de backend pasan"
  else
    warn "pytest no está en el venv local; me salto los tests de backend"
  fi
else
  warn "No hay backend/.venv local; me salto el import-check local"
fi

# ============================================================
# 2) DRY-RUN rsync (siempre se muestra)
# ============================================================
info "Diferencias que se enviarían a PROD ($SSH_USER@$SSH_ADDRESS:$REMOTE_PATH):"
sshpass -p "$SSH_PASSWORD" rsync -az --itemize-changes --dry-run "${EXCLUDES[@]}" \
  -e "ssh ${SSH_OPTS[*]}" ./ "$SSH_USER@$SSH_ADDRESS:$REMOTE_PATH/" \
  | grep -vE '^\.d\.\.t\.\.\.\.\.\. ' || true

if [ "$DRY_RUN" -eq 1 ]; then ok "Dry-run completado. No se ha tocado prod."; exit 0; fi

if [ "$ASSUME_YES" -ne 1 ]; then
  printf '%s¿Desplegar a PROD? [y/N] %s' "$C_Y" "$C_0"; read -r ans
  case "$ans" in y|Y|yes|si|s) ;; *) die "Cancelado por el usuario."; esac
fi

# ============================================================
# 3) SNAPSHOT en prod (punto de rollback)
# ============================================================
info "Snapshot de rollback en prod"
rsh "cd '$REMOTE_PATH' && git add -A && (git commit -q -m 'pre-deploy snapshot' || true)"
PREV="$(rsh "cd '$REMOTE_PATH' && git rev-parse HEAD" | tr -d '[:space:]')"
[ -n "$PREV" ] || die "No pude capturar el commit de rollback en prod."
ok "Punto de rollback: $PREV"

rollback() {
  warn "ROLLBACK -> $PREV (reset + clean + rebuild + restart)"
  rsh "cd '$REMOTE_PATH' && git reset --hard '$PREV' && git clean -fd" || true
  rsh "cd '$REMOTE_PATH/frontend' && npm run build" >/dev/null 2>&1 || warn "rebuild en rollback dio error"
  rsudo "systemctl restart $SERVICE" || true
}

# ============================================================
# 4) rsync -> prod
# ============================================================
info "Enviando cambios a prod (rsync, sin --delete)"
sshpass -p "$SSH_PASSWORD" rsync -az "${EXCLUDES[@]}" \
  -e "ssh ${SSH_OPTS[*]}" ./ "$SSH_USER@$SSH_ADDRESS:$REMOTE_PATH/" || { rollback; die "rsync falló; revertido."; }
ok "Archivos sincronizados"

# ============================================================
# 5) build + import-check en prod (SIN reiniciar todavía)
# ============================================================
info "Build de frontend en prod"
if ! rsh "cd '$REMOTE_PATH/frontend' && npm run build" >/dev/null 2>&1; then
  rollback; die "Build FALLA en prod. Revertido; el servicio seguía con la versión anterior."
fi
ok "Frontend construido en prod"

info "Import-check de backend en prod"
if ! rsh "cd '$REMOTE_PATH/backend' && .venv/bin/python -c 'import app.main'" >/dev/null 2>&1; then
  rollback; die "import app.main FALLA en prod. Revertido; servicio intacto."
fi
ok "Backend importa en prod"

# ============================================================
# 6) restart + health-check con reintentos (+ rollback auto)
# ============================================================
info "Reiniciando $SERVICE"
rsudo "systemctl restart $SERVICE" || { rollback; die "restart falló; revertido."; }

info "Health-check ($HEALTH)"
# curl reintenta en el propio remoto (sin sleep en el shell local): tolera el
# arranque de uvicorn tras el restart.
code="$(rsh "curl -s --retry 10 --retry-delay 1 --retry-all-errors -o /dev/null -w '%{http_code}' '$HEALTH'" 2>/dev/null | tr -d '[:space:]' || true)"
if [ "$code" != "200" ]; then
  rollback
  # revalidar tras rollback
  code2="$(rsh "curl -s -o /dev/null -w '%{http_code}' '$HEALTH'" 2>/dev/null | tr -d '[:space:]' || true)"
  die "Salud tras deploy = '$code'. ROLLBACK aplicado (salud tras revertir = '$code2')."
fi
ok "Salud 200 — despliegue vivo"

# ============================================================
# 7) commit del estado desplegado
# ============================================================
rsh "cd '$REMOTE_PATH' && git add -A && (git commit -q -m 'deploy: sync desde dev (auto)' || true)"
ok "Despliegue completado y verificado en prod."
