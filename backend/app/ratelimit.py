"""Limitador de peticiones por IP, persistente en SQLite.

Se usa para /api/parse-bill, que dispara una llamada de pago a OpenAI por cada
factura: sin tope, un bot podría vaciar la cuota. La ventana es deslizante.
"""

import sqlite3
import time
from pathlib import Path


class RateLimiter:
    def __init__(self, db_path: str | Path, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS upload_events (ip TEXT NOT NULL, ts REAL NOT NULL)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_upload_events_ip ON upload_events (ip)"
        )
        self._conn.commit()

    def check_and_record(self, ip: str) -> tuple[bool, int]:
        """Registra un intento. Devuelve (permitido, restantes_tras_este).

        Si ya se alcanzó el límite en la ventana, no registra y devuelve (False, 0).
        """
        now = time.time()
        cutoff = now - self.window_seconds
        self._conn.execute("DELETE FROM upload_events WHERE ts < ?", (cutoff,))
        used = self._conn.execute(
            "SELECT COUNT(*) FROM upload_events WHERE ip = ?", (ip,)
        ).fetchone()[0]
        if used >= self.limit:
            self._conn.commit()
            return False, 0
        self._conn.execute(
            "INSERT INTO upload_events (ip, ts) VALUES (?, ?)", (ip, now)
        )
        self._conn.commit()
        return True, self.limit - used - 1

    def close(self) -> None:
        self._conn.close()
