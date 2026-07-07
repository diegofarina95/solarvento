# Publicación programada en el portal del blog — diseño (2026-07-07)

## Problema

Publicar desde el portal es manual: subes el borrador, lo revisas, traduces y
pulsas «Publicar todo lo pendiente». Diego quiere poder dejar artículos
preparados y **programar la hora a la que salen** (p. ej. subir tres artículos
el domingo y que salgan lunes, miércoles y viernes), sin tener que estar
delante a esa hora.

## Decisiones (validadas con Diego)

- **Programación por artículo**, no de la acción global: cada grupo (original
  en español + sus traducciones) tiene su propia fecha/hora opcional.
- **A la hora T se publica el grupo entero tal como esté**: el español más las
  traducciones que existan como borrador en ese momento. Si faltan idiomas,
  salen después a mano (o con otra publicación).
- **Recuperación manual**: si la hora pasó mientras el portal estaba caído, la
  programación queda «vencida» (`stale`) y espera confirmación en el dashboard;
  NO se publica sola al arrancar. Lo mismo si un intento de publicar falla
  (`error`): sin reintentos automáticos.
- **Planificador dentro del portal** (enfoque elegido frente a timers de
  systemd o `publish_at:` en frontmatter): un hilo del propio proceso + un
  archivo JSON de estado. Un solo proceso, un solo archivo, fácil de testear.
- El botón «Publicar todo lo pendiente» y el flujo de traducción no cambian.

## Estado y planificador

**Archivo**: `.blog-schedule.json` en la raíz del repo, gitignored (como
`.env`). Una entrada por grupo, clave = `stem` (nombre en disco, la misma
clave que usa el resto del portal):

```json
{
  "como-leer-tu-factura": {
    "publish_at": "2026-07-09T09:00",
    "state": "pending",
    "error": null
  }
}
```

Estados:

- `pending` — esperando la hora.
- `stale` — la hora pasó **antes de arrancar el servicio** (portal caído en el
  momento T). Espera confirmación manual.
- `error` — el intento de publicación falló (p. ej. rsync caído). Guarda el
  mensaje en `error` y espera confirmación manual.

**Hilo planificador**: arranca con el lifespan de FastAPI, demonio, tick cada
30 s:

1. Primer tick tras el arranque: toda entrada `pending` con `publish_at` <
   hora de arranque del servicio pasa a `stale`.
2. Tick normal: una entrada `pending` con `publish_at` <= ahora se publica con
   `publish_group()`. Si el `LOCK` está ocupado (otra operación en curso), se
   reintenta al tick siguiente sin cambiar de estado.
3. Éxito → la entrada se elimina del JSON. Fallo → `state: "error"` + mensaje.

Las horas son hora local de la máquina (Europe/Madrid), strings naive de
`datetime-local` (`YYYY-MM-DDTHH:MM`). Sin zonas horarias explícitas.

## Publicación selectiva de un grupo (`publish_group`)

Hoy `/publish` publica todos los borradores a la vez porque el generador
regenera índices/hreflang/sitemap con todo lo que hay en disco. Para publicar
solo un grupo sin arrastrar los demás borradores a git/prod:

1. Con el `LOCK` cogido, los archivos `.html` de los **otros** grupos con
   borrador se mueven temporalmente a `.drafts-aside/` (raíz del repo,
   gitignored), conservando su subruta (`en/foo.html` → `.drafts-aside/en/foo.html`).
2. `run_generate()`: `public/blog/` queda con lo commiteado + el grupo a
   publicar.
3. `commit_paths("Blog: publica «título» [es, en, …] (programado, portal)")` +
   `sync_to_prod()` + `check_live_url()` de cada URL del grupo — la misma
   maquinaria del publish actual.
4. Los borradores apartados vuelven a su sitio y se ejecuta `run_generate()`
   otra vez para que sus previews sigan funcionando.

**Recuperación ante fallos**: el paso 4 va en `finally` (se restaura aunque
falle commit o rsync). Además, al arrancar el portal restaura cualquier resto
de `.drafts-aside/` (crash a mitad de publicación) antes de arrancar el
planificador. Los borradores nunca se pierden.

**Reutilización**: `publish_group()` la usan el planificador (hora T) y el
botón «Publicar ahora» de entradas `stale`/`error`. Si el fallo fue solo del
sync (commit hecho), el reintento reutiliza la semántica actual: commit sin
cambios es no-op («sin cambios que commitear») y se repite el rsync.

## Rutas nuevas

- `POST /schedule/{stem}` — form con `publish_at` (`datetime-local`). Valida:
  grupo existente con borradores pendientes, hora futura. Programar de nuevo
  sobrescribe (así se cambia la hora). Redirige al índice.
- `POST /unschedule/{stem}` — elimina la entrada. Redirige al índice.
- `POST /publish-group/{stem}` — «Publicar ahora»: dispara `publish_group()` a
  mano. Válido si el grupo tiene borradores pendientes **o** una entrada en el
  JSON (`stale`/`error`): tras un fallo de solo-sync el commit ya está hecho y
  el grupo no tiene borradores, pero el reintento debe poder ejecutarse (commit
  no-op + rsync). Muestra la página de resultado (URLs + check en vivo), como
  el publish actual.

## Interfaz

En la tarjeta del índice de cada grupo con borradores y en el preview:

- Sin programación: `datetime-local` (por defecto mañana 09:00) + botón
  **«Programar»**.
- Programado (`pending`): insignia «⏰ sale el mié 9 jul, 09:00» + botón
  **«Cancelar programación»**.
- `stale`: aviso en ámbar «⏰ venció el … con el portal parado» + botones
  **«Publicar ahora»** y «Cancelar programación».
- `error`: aviso en rojo con el mensaje guardado + los mismos dos botones.

## Casos borde

- Descartar o borrar un borrador con programación elimina también su entrada
  del JSON (en `/discard` y `/delete`).
- No se puede programar un grupo sin borradores pendientes (400).
- No se puede programar una hora pasada (400).
- JSON corrupto o ilegible → se trata como vacío y se loggea; programar de
  nuevo lo reescribe.
- El grupo programado puede ganar traducciones entre la programación y la hora
  T: se publican también (decisión «grupo entero tal como esté»).

## Tests

Siguiendo el estilo de los tests actuales del portal:

- Almacén: leer/escribir/sobrescribir/eliminar entradas; JSON corrupto.
- Regla stale-al-arrancar y transición pending→publicado / pending→error
  (llamando a la función de tick directamente, sin esperas reales; hora
  inyectable).
- `publish_group`: los otros borradores se apartan y restauran (también cuando
  commit o rsync fallan); solo el grupo objetivo llega a git.
- Restauración de `.drafts-aside/` al arrancar.
- Limpieza de programación en `/discard` y `/delete`.
- Rutas: validaciones de `/schedule` (hora pasada, grupo inexistente),
  `/unschedule`, `/publish-group`.
- Índice: las insignias/botones correctos por estado en el HTML.
