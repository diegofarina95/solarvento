"""Caché clave-valor persistente en SQLite con TTL.

PVGIS devuelve siempre lo mismo para las mismas coordenadas, así que cachear
por clave (endpoint + coords redondeadas + parámetros) con TTL largo evita
llamadas repetidas a la API.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class TTLCache:
    def __init__(self, db_path: str | Path, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, created_at REAL NOT NULL)"
        )
        self._conn.commit()

    def get(self, key: str) -> Any | None:
        row = self._conn.execute(
            "SELECT value, created_at FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        value, created_at = row
        if time.time() - created_at > self.ttl_seconds:
            self._conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            self._conn.commit()
            return None
        return json.loads(value)

    def set(self, key: str, value: Any) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(value), time.time()),
        )
        self._conn.commit()

    def purge_expired(self) -> None:
        """Borra físicamente las filas caducadas (get() solo borra al leerlas).

        Importante para la caché de facturas: sin esto, una sesión que nunca
        dispara el beacon de purga dejaría sus entradas en el fichero SQLite
        para siempre aunque el TTL las haga invisibles."""
        self._conn.execute(
            "DELETE FROM cache WHERE created_at < ?", (time.time() - self.ttl_seconds,)
        )
        self._conn.commit()

    def delete_prefix(self, prefix: str) -> None:
        """Borra todas las entradas cuya clave empieza por el prefijo dado."""
        escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        self._conn.execute(
            "DELETE FROM cache WHERE key LIKE ? ESCAPE '\\'", (escaped + "%",)
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
