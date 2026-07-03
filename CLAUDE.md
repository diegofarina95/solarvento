# SolVento

Este proyecto se gestiona desde **Taller** (panel en el servidor de Diego).

- Carpeta del proyecto: `/home/diego/taller-projects/solvento`
- Tipo: Custom
- Taller arranca tu app con este comando (host/puerto los inyecta Taller):

  ```
  cd backend && .venv/bin/uvicorn app.main:app --host {host} --port {port}
  ```

Reglas:
- La app DEBE escuchar en el host y puerto que se le pasan (no hardcodees otros).
- Trabaja siempre dentro de esta carpeta.
- Mantén las dependencias dentro del proyecto (venv para Python, package.json para Node).
- Cuando termines un cambio, dile al usuario que reinicie el servidor desde el panel para verlo.
