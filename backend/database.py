from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def normalizar_url(url: str) -> str:
    """Neon, Render y Railway entregan URLs postgres://; SQLAlchemy necesita el driver explícito."""
    for prefijo in ("postgres://", "postgresql://"):
        if url.startswith(prefijo):
            return "postgresql+psycopg://" + url[len(prefijo):]
    return url


def es_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def crear_engine(url: str) -> Engine:
    url = normalizar_url(url)
    if not es_sqlite(url):
        # pool_pre_ping evita errores cuando Neon suspende conexiones inactivas.
        return create_engine(url, pool_pre_ping=True, pool_recycle=300, pool_size=5, max_overflow=5)

    ruta = url.split(":///", 1)[-1]
    if ruta and ruta != ":memory:":
        Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 15})

    @event.listens_for(engine, "connect")
    def _configurar_sqlite(dbapi_connection, _record) -> None:
        # Desactiva el manejo implícito de transacciones de pysqlite para que
        # BEGIN/SAVEPOINT funcionen correctamente (necesario en importaciones).
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _begin(conn) -> None:
        conn.exec_driver_sql("BEGIN")

    return engine


def inicializar_base(url: str) -> sessionmaker:
    """Crea las tablas que falten, carga los catálogos iniciales y devuelve la fábrica de sesiones."""
    from . import models  # noqa: F401  registra las tablas en Base.metadata
    from .seed import sembrar_catalogos

    engine = crear_engine(url)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    sembrar_catalogos(session_factory)
    # Con gunicorn --preload la app se carga antes de crear los workers:
    # se cierran las conexiones para que cada worker abra las suyas.
    engine.dispose()
    return session_factory
