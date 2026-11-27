from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect, text
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


def _migrar_roles_personalizados(engine: Engine) -> None:
    restricciones = inspect(engine).get_check_constraints("usuarios")
    rol_check = next((item for item in restricciones if item["name"] == "ck_usuario_rol"), None)
    if rol_check is None:
        return

    if engine.dialect.name == "sqlite":
        conexion = engine.raw_connection()
        try:
            cursor = conexion.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=OFF")
                cursor.execute("BEGIN")
                cursor.execute("""
                    CREATE TABLE usuarios_nueva (
                        id INTEGER NOT NULL PRIMARY KEY,
                        username VARCHAR(40) NOT NULL UNIQUE,
                        password_hash VARCHAR(255) NOT NULL,
                        rol VARCHAR(20) NOT NULL,
                        activo BOOLEAN NOT NULL,
                        intentos_fallidos INTEGER NOT NULL,
                        bloqueado_hasta DATETIME,
                        ultimo_acceso DATETIME,
                        creado_en DATETIME NOT NULL
                    )
                """)
                cursor.execute("""
                    INSERT INTO usuarios_nueva
                    SELECT id, username, password_hash, rol, activo, intentos_fallidos,
                           bloqueado_hasta, ultimo_acceso, creado_en
                    FROM usuarios
                """)
                cursor.execute("DROP TABLE usuarios")
                cursor.execute("ALTER TABLE usuarios_nueva RENAME TO usuarios")
                conexion.commit()
            except Exception:
                conexion.rollback()
                raise
            finally:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
        finally:
            conexion.close()
    elif engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE usuarios DROP CONSTRAINT ck_usuario_rol"))
    else:
        raise RuntimeError(f"No se puede actualizar los roles en {engine.dialect.name}.")


def _migrar_categorias_producto(engine: Engine) -> None:
    from .models import CATEGORIAS_PRODUCTO

    restricciones = inspect(engine).get_check_constraints("productos")
    categoria_check = next(
        (item for item in restricciones if item["name"] == "ck_producto_categoria"),
        None,
    )
    if categoria_check is None:
        return

    sql_categorias = ", ".join(f"'{categoria}'" for categoria in CATEGORIAS_PRODUCTO)
    if all(categoria in categoria_check["sqltext"] for categoria in CATEGORIAS_PRODUCTO):
        return

    if engine.dialect.name == "sqlite":
        conexion = engine.raw_connection()
        try:
            cursor = conexion.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=OFF")
                cursor.execute("BEGIN")
                cursor.execute(f"""
                    CREATE TABLE productos_nueva (
                        id INTEGER NOT NULL PRIMARY KEY,
                        nombre VARCHAR(60) NOT NULL UNIQUE,
                        categoria VARCHAR(30) NOT NULL,
                        activo BOOLEAN NOT NULL,
                        creado_en DATETIME NOT NULL,
                        CONSTRAINT ck_producto_categoria CHECK (categoria IN ({sql_categorias}))
                    )
                """)
                cursor.execute("""
                    INSERT INTO productos_nueva (id, nombre, categoria, activo, creado_en)
                    SELECT id, nombre, categoria, activo, creado_en FROM productos
                """)
                cursor.execute("DROP TABLE productos")
                cursor.execute("ALTER TABLE productos_nueva RENAME TO productos")
                conexion.commit()
            except Exception:
                conexion.rollback()
                raise
            finally:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
        finally:
            conexion.close()
    elif engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE productos DROP CONSTRAINT ck_producto_categoria"))
            connection.execute(text(
                f"ALTER TABLE productos ADD CONSTRAINT ck_producto_categoria "
                f"CHECK (categoria IN ({sql_categorias}))"
            ))
    else:
        raise RuntimeError(f"No se pueden actualizar las categorías en {engine.dialect.name}.")


def inicializar_base(url: str) -> sessionmaker:
    """Crea las tablas que falten, carga los catálogos iniciales y devuelve la fábrica de sesiones."""
    from . import models  # noqa: F401  registra las tablas en Base.metadata
    from .seed import sembrar_catalogos

    engine = crear_engine(url)
    Base.metadata.create_all(engine)
    _migrar_roles_personalizados(engine)
    if "categoria" not in {column["name"] for column in inspect(engine).get_columns("productos")}:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE productos ADD COLUMN categoria VARCHAR(30) NOT NULL DEFAULT 'materia_prima'"
            ))
            connection.execute(text(
                "UPDATE productos SET categoria = 'producto_terminado' "
                "WHERE nombre IN ('Aluminio', 'Magnesio')"
            ))
    _migrar_categorias_producto(engine)
    columnas_ubicacion = {column["name"] for column in inspect(engine).get_columns("ubicaciones")}
    if "peligrosa" not in columnas_ubicacion:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE ubicaciones ADD COLUMN peligrosa BOOLEAN NOT NULL DEFAULT FALSE"
            ))
    if "titulo_peligro" not in columnas_ubicacion:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE ubicaciones ADD COLUMN titulo_peligro VARCHAR(100)"
            ))
    session_factory = sessionmaker(engine, expire_on_commit=False)
    sembrar_catalogos(session_factory)
    # Con gunicorn --preload la app se carga antes de crear los workers:
    # se cierran las conexiones para que cada worker abra las suyas.
    engine.dispose()
    return session_factory
