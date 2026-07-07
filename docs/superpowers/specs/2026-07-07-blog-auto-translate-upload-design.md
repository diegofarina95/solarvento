# Traducción automática al subir — diseño (2026-07-07)

## Problema

Con la publicación programada en marcha, Diego no quiere que los artículos
queden «pendientes de traducción»: los grupos deberían nacer completos. Hoy la
traducción es un paso manual posterior (botón «Traducir (n)»).

## Decisiones (validadas con Diego)

- **Traducir automáticamente al subir**: el mismo `POST /upload` genera las 4
  traducciones (EN/CA/GL/EU) con OpenAI, en paralelo, antes de redirigir al
  preview. La subida pasa a tardar ~30-60 s.
- **Fallos no bloqueantes**: si falla un idioma, OpenAI entero o no hay clave
  de API, la subida NO se pierde: el español queda como borrador y los idiomas
  fallidos quedan sin traducir, con el botón «Traducir (n)» de siempre como
  reintento. Nada de todo-o-nada.
- **Sin bloqueos de publicación**: «Publicar todo lo pendiente» y la
  programación siguen aceptando grupos incompletos (elegido explícitamente
  frente a la opción de bloquear).

## Cambios

1. **Helper compartido** `generate_missing_translations(stem) -> tuple[list[str], dict[str, str]]`
   en `portal.py`: lee el original, traduce en paralelo los idiomas que falten
   (ThreadPoolExecutor, como hoy), escribe los borradores y devuelve
   `(idiomas_escritos, errores_por_idioma)`. Asume el LOCK cogido y NO ejecuta
   el generador (eso queda en el caller). Sin clave de API → devuelve
   `([], {"*": "sin OPENAI_API_KEY"})` sin intentar nada.
   - `/translate` se refactoriza para usarlo (mismo comportamiento externo).
   - Si el generador rechaza las traducciones escritas, se borran y se
     regenera (rollback actual de `/translate`, que conserva el caller).
2. **`/upload`**: tras el `run_generate()` que valida el español, llama al
   helper; si escribió algo, segundo `run_generate()` (con el mismo rollback
   de traducciones si fallara). Después, redirect al preview como siempre.
   Los errores de traducción no cambian el código de respuesta.
3. **Preview**: gana la fila de chips de idiomas del grupo (`lang_chips`,
   la misma del índice) para ver qué salió y qué falló, sin banners nuevos.
4. **Copy**: el botón del formulario de subida pasa a «Subir, traducir y
   previsualizar» y la ayuda menciona que las traducciones se generan solas
   (el botón «Traducir» queda como reintento).

## Casos borde

- Sin `OPENAI_API_KEY`: la subida funciona como hasta ahora (solo español).
- Traducciones parciales: se escriben las que salieron; las fallidas se
  reintentarán con «Traducir (n)».
- El generador rechaza una traducción: rollback de las traducciones escritas
  (el español ya validado se queda), regenerar, subida sigue OK.
- `/translate` mantiene sus validaciones (404 sin original, 409 sin idiomas
  que faltar, 500 sin clave — este último solo en la ruta manual; en la subida
  la falta de clave es silenciosa por diseño).

## Tests

- La subida escribe los 4 borradores traducidos (OpenAI simulado) y redirige
  al preview.
- Fallo parcial: quedan los idiomas buenos, la subida responde 303.
- Sin clave de API: subida 303 sin traducciones.
- El generador rechaza traducciones en la subida: rollback y 303.
- `/translate` sigue igual tras el refactor (tests existentes en verde).
- El preview muestra los chips de idiomas.
