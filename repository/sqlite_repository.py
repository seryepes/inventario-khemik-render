from __future__ import annotations

import sqlite3
import secrets
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator

from backend.domain import Movimiento

DEFAULT_DATABASE_PATH = Path(__file__).resolve().parent / "inventario.db"
LEGACY_DATABASE_PATH = DEFAULT_DATABASE_PATH.parent.parent / "inventario.db"


class SQLiteInventarioRepository:
    def __init__(
        self,
        database_path: str | Path | None = None,
        legacy_database_path: str | Path | None = None,
    ) -> None:
        use_default_path = database_path is None
        self.database_path = Path(database_path) if database_path is not None else DEFAULT_DATABASE_PATH
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_path = (
            Path(legacy_database_path)
            if legacy_database_path is not None
            else LEGACY_DATABASE_PATH if use_default_path else None
        )
        if not self.database_path.exists() and legacy_path and legacy_path.exists():
            legacy_path.replace(self.database_path)
        self._init_db()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS movimientos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha TEXT NOT NULL,
                    mvto TEXT NOT NULL,
                    posicion TEXT NOT NULL,
                    producto TEXT NOT NULL,
                    presentacion TEXT NOT NULL,
                    lote TEXT NOT NULL,
                    cantidad INTEGER NOT NULL CHECK (cantidad >= 0),
                    observaciones TEXT NOT NULL DEFAULT '',
                    traslado_id TEXT,
                    es_traslado INTEGER NOT NULL DEFAULT 0
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('admin', 'user'))
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(movimientos)")}
            if "registrado_en" not in columns:
                db.execute("ALTER TABLE movimientos ADD COLUMN registrado_en TEXT")

    def get_or_create_secret_key(self) -> str:
        with self._connect() as db:
            row = db.execute("SELECT value FROM app_settings WHERE key='secret_key'").fetchone()
            if row:
                return str(row["value"])
            secret_key = secrets.token_hex(32)
            db.execute("INSERT INTO app_settings (key, value) VALUES ('secret_key', ?)", (secret_key,))
        return secret_key

    def listar_usuarios(self) -> list[dict[str, str]]:
        with self._connect() as db:
            rows = db.execute("SELECT username, role FROM usuarios ORDER BY username COLLATE NOCASE").fetchall()
        return [{"username": row["username"], "role": row["role"]} for row in rows]

    def obtener_usuario(self, username: str) -> dict[str, str] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT username, password_hash, role FROM usuarios WHERE username=?",
                (username,),
            ).fetchone()
        return dict(row) if row else None

    def crear_administrador_inicial(self, username: str, password_hash: str) -> bool:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone():
                return False
            db.execute(
                "INSERT INTO usuarios (username, password_hash, role) VALUES (?, ?, 'admin')",
                (username, password_hash),
            )
        return True

    def crear_usuario(self, username: str, password_hash: str) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO usuarios (username, password_hash, role) VALUES (?, ?, 'user')",
                (username, password_hash),
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Movimiento:
        return Movimiento(
            id=row["id"], fecha=row["fecha"], mvto=row["mvto"], posicion=row["posicion"],
            producto=row["producto"], presentacion=row["presentacion"], lote=row["lote"],
            cantidad=row["cantidad"], observaciones=row["observaciones"], traslado_id=row["traslado_id"],
            es_traslado=bool(row["es_traslado"]), registrado_en=row["registrado_en"],
        )

    @staticmethod
    def _ahora() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _payload(item: Movimiento) -> tuple[Any, ...]:
        return (
            item.fecha, item.mvto, item.posicion, item.producto, item.presentacion,
            item.lote, item.cantidad, item.observaciones, item.traslado_id, int(item.es_traslado),
        )

    def listar(self) -> list[Movimiento]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM movimientos ORDER BY id DESC").fetchall()
        return [self._from_row(row) for row in rows]

    def guardar(self, movimiento: Movimiento) -> Movimiento:
        with self._connect() as db:
            if movimiento.id:
                row = db.execute(
                    "SELECT registrado_en FROM movimientos WHERE id=?",
                    (movimiento.id,),
                ).fetchone()
                db.execute(
                    "UPDATE movimientos SET fecha=?, mvto=?, posicion=?, producto=?, presentacion=?, "
                    "lote=?, cantidad=?, observaciones=? WHERE id=?",
                    (*self._payload(movimiento)[:8], movimiento.id),
                )
                if row:
                    movimiento.registrado_en = row["registrado_en"]
            else:
                movimiento.registrado_en = movimiento.registrado_en or self._ahora()
                cursor = db.execute(
                    "INSERT INTO movimientos "
                    "(fecha,mvto,posicion,producto,presentacion,lote,cantidad,observaciones,traslado_id,es_traslado,registrado_en) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (*self._payload(movimiento), movimiento.registrado_en),
                )
                movimiento.id = cursor.lastrowid
        return movimiento

    def guardar_varios(self, movimientos: list[Movimiento]) -> list[Movimiento]:
        with self._connect() as db:
            for movimiento in movimientos:
                movimiento.registrado_en = movimiento.registrado_en or self._ahora()
                cursor = db.execute(
                    "INSERT INTO movimientos "
                    "(fecha,mvto,posicion,producto,presentacion,lote,cantidad,observaciones,traslado_id,es_traslado,registrado_en) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (*self._payload(movimiento), movimiento.registrado_en),
                )
                movimiento.id = cursor.lastrowid
        return movimientos

    def eliminar(self, id_: int) -> None:
        with self._connect() as db:
            row = db.execute("SELECT traslado_id FROM movimientos WHERE id=?", (id_,)).fetchone()
            if row and row["traslado_id"]:
                db.execute("DELETE FROM movimientos WHERE traslado_id=?", (row["traslado_id"],))
            else:
                db.execute("DELETE FROM movimientos WHERE id=?", (id_,))

    def borrar_todo(self) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM movimientos")

    def restaurar(self, movimientos: list[Movimiento]) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM movimientos")
            for movimiento in movimientos:
                db.execute(
                    "INSERT INTO movimientos "
                    "(id,fecha,mvto,posicion,producto,presentacion,lote,cantidad,observaciones,traslado_id,es_traslado,registrado_en) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (movimiento.id, *self._payload(movimiento), movimiento.registrado_en),
                )
