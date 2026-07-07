# Portal de publicación del blog — diseño (2026-07-07)

## Problema

Publicar un artículo del blog hoy exige tocar el repo a mano (añadir el HTML a
`frontend/content/blog/`, regenerar, commitear y desplegar). Diego quiere subir
el HTML desde el navegador y que aparezca en `https://solarvento.es/blog/` en
segundos, sin abrir un editor ni la terminal. El portal debe ser invisible
desde Internet: solo accesible desde su tailnet (Tailscale).

## Decisiones (validadas con Diego)

- **Publicación rápida vía git + sync selectivo** (no deploy completo, no
  escribir en prod directamente): el portal corre en la máquina de dev, commitea
  en git (fuente de verdad) y sincroniza SOLO los HTML del blog + sitemap al
  `dist/` de prod, que está gitignored → el guard anti-árbol-sucio de
  `deploy.sh` no se ensucia y el siguiente deploy completo regenera lo mismo.
- **Formato de entrada**: el archivo `.html` con el frontmatter del blog
  (`--- title/description/keywords/date/excerpt ---` + cuerpo HTML), el mismo
  formato de `frontend/content/blog/`.
- **Alcance**: subir con preview, listar publicados y borrar con confirmación.
  Sin sobrescritura por re-subida: si el slug existe, se rechaza (para
  actualizar: borrar y volver a subir).

## Arquitectura

Mini-app FastAPI independiente en `backend/app/portal.py` (reutiliza el venv del
backend). Nunca se arranca en prod. Escucha solo en la IP de Tailscale de la
máquina de dev (resuelta al arrancar con `tailscale ip -4`), puerto **8130**.
Acceso: `http://mockwebsite-diego.tailfc8d71.ts.net:8130`.

### Flujo de subida (2 pasos)

1. `POST /upload`: valida el nombre (`^[a-z0-9-]+\.html$`, slug no existente),
   guarda en `frontend/content/blog/` y ejecuta `npm run generate` — la
   validación del frontmatter la hace el generador existente (fuente única de
   verdad, sin parser duplicado). Si falla: se borra el archivo, se re-ejecuta
   generate para restaurar índice/sitemap y se muestra el error exacto.
2. Preview de la página generada (iframe sobre `frontend/public/blog/<slug>.html`)
   con «Publicar» / «Descartar».
   - **Publicar**: `git add` (fuente + generados + sitemap, mantiene verde el
     `--check` anti-deriva) + commit; rsync de `public/blog/` → prod
     `frontend/dist/blog/` (`--delete`) y `sitemap.xml` → prod
     `frontend/dist/sitemap.xml`; verificación con GET a la URL pública.
   - **Descartar**: borra fuente + generado y re-ejecuta generate (determinista
     → índice/sitemap vuelven al estado del último commit).

Un borrador pendiente se detecta por `git status --porcelain` (archivo sin
trackear en `content/blog/`), así sobrevive a reinicios del portal.

### Borrado

Confirmación → borra fuente + generado, regenera, `git rm`/commit, rsync con
`--delete`. El generador exige ≥1 artículo: borrar el último se rechaza con
aviso en vez de romper.

### Sincronización con prod

Credenciales del `.env` local (formato `CLAVE: valor`: SSH_ADDRESS, SSH_PORT,
SSH_USER, SSH_PASSWORD, PATH=/home/diego/solvento), mismas que `deploy.sh`,
vía `sshpass` + `rsync`. Solo se tocan rutas bajo `frontend/dist/` de prod
(gitignored allí). StaticFiles lee de disco → sin reiniciar el backend de prod.
Si el rsync falla tras el commit, git ya es consistente: el portal ofrece
«Reintentar sincronización» (y un deploy completo también lo arreglaría).

### Seguridad

- Bind a la IP de Tailscale → invisible desde LAN e Internet.
- Middleware de defensa en profundidad: rechaza IPs de cliente fuera de
  `100.64.0.0/10` (CGNAT de Tailscale), `fd7a:115c:a1e0::/48` y loopback.
- Límite de subida: 2 MB. Lock global: una operación de escritura a la vez.
- Sin sanitización del HTML: el único autor es Diego (igual que hoy en el repo).

### Servicio

`deploy/solvento-portal.service` (systemd, `After=tailscaled.service`,
`Restart=on-failure`) + launcher `deploy/solvento-portal.sh` que resuelve la IP
de Tailscale y ejecuta uvicorn. Se instala SOLO en la máquina de dev.

## Tests

pytest: validación de slugs, guard de IPs, parser de listado (frontmatter
mínimo), parser del `.env`, y flujo de subida/descarte contra un repo temporal.
