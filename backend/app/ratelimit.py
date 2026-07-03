"""Limitador de peticiones persistente en SQLite (ventana deslizante).

Protege los endpoints que cuestan dinero o cupo externo:
- /api/parse-bill: cada subida es una llamada de pago a OpenAI. Tope por
  equipo (IP) y tope GLOBAL diario, para que ni un bot distribuido ni muchos
  usuarios legítimos a la vez puedan vaciar la cuota.
- /api/solar-estimate: cada cálculo lanza hasta 4 llamadas a PVGIS; un abuso
  podría hacer que el JRC bloquee la IP del servidor para todos.
"""

import sqlite3
import time
from pathlib import Path


class RateLimiter:
    def __init__(
        self,
        db_path: str | Path,
        limit: int,
        window_seconds: int,
        *,
        global_limit: int | None = None,
        table: str = "upload_events",
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.global_limit = global_limit
        self.table = table
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute(
            f"CREATE TABLE IF NOT EXISTS {table} (ip TEXT NOT NULL, ts REAL NOT NULL)"
        )
        self._conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_ip ON {table} (ip)")
        self._conn.commit()

    def check_and_record(self, ip: str) -> tuple[bool, str | None]:
        """Registra un intento. Devuelve (permitido, motivo_de_bloqueo).

        motivo: None si se permite, 'ip' si el equipo agotó su cupo, 'global'
        si se alcanzó el tope diario del servicio.
        """
        now = time.time()
        cutoff = now - self.window_seconds
        self._conn.execute(f"DELETE FROM {self.table} WHERE ts < ?", (cutoff,))

        if self.global_limit is not None:
            total = self._conn.execute(
                f"SELECT COUNT(*) FROM {self.table}"
            ).fetchone()[0]
            if total >= self.global_limit:
                self._conn.commit()
                return False, "global"

        used = self._conn.execute(
            f"SELECT COUNT(*) FROM {self.table} WHERE ip = ?", (ip,)
        ).fetchone()[0]
        if used >= self.limit:
            self._conn.commit()
            return False, "ip"

        self._conn.execute(
            f"INSERT INTO {self.table} (ip, ts) VALUES (?, ?)", (ip, now)
        )
        self._conn.commit()
        return True, None

    def close(self) -> None:
        self._conn.close()
