import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from backend.database import inicializar_base
from backend.usuarios import UsuarioService


class DatabaseMigrationTests(unittest.TestCase):
    def test_existing_sqlite_users_can_use_coordinator_role(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            url = f"sqlite:///{Path(temp_dir) / 'legacy.db'}"
            engine = create_engine(url)
            with engine.begin() as connection:
                connection.execute(text("""
                    CREATE TABLE usuarios (
                        id INTEGER NOT NULL PRIMARY KEY,
                        username VARCHAR(40) NOT NULL UNIQUE,
                        password_hash VARCHAR(255) NOT NULL,
                        rol VARCHAR(20) NOT NULL,
                        activo BOOLEAN NOT NULL,
                        intentos_fallidos INTEGER NOT NULL,
                        bloqueado_hasta DATETIME,
                        ultimo_acceso DATETIME,
                        creado_en DATETIME NOT NULL,
                        CONSTRAINT ck_usuario_rol
                            CHECK (rol IN ('admin', 'coordinador', 'operador', 'consulta'))
                    )
                """))
                connection.execute(text("""
                    INSERT INTO usuarios
                    (id, username, password_hash, rol, activo, intentos_fallidos, creado_en)
                    VALUES (1, 'admin', 'hash-existente', 'admin', TRUE, 0, '2026-01-01 00:00:00')
                """))

            session_factory = inicializar_base(url)
            try:
                service = UsuarioService(session_factory)
                custom_role = service.crear_rol("Control de calidad", ["ver_inventario"], 1)
                creado = service.crear("coord", "clave-segura", "coordinador", 1, "admin")
                self.assertEqual(creado["role"], "coordinador")
                assigned = service.crear("calidad", "clave-segura", custom_role["codigo"], 1, "admin")
                self.assertEqual(assigned["role"], custom_role["codigo"])
                self.assertEqual(
                    [user["roleName"] for user in service.listar()],
                    ["Administrador", "Control de calidad", "Coordinador logístico"],
                )
                self.assertEqual(inspect(engine).get_check_constraints("usuarios"), [])
                with engine.connect() as connection:
                    self.assertEqual(connection.execute(text("PRAGMA foreign_key_check")).all(), [])
            finally:
                session_factory.kw["bind"].dispose()
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
