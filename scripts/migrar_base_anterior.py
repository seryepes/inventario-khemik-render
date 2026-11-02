"""Copia los datos de la base SQLite anterior (repository/inventario.db) al nuevo modelo.

Uso (desde la raíz del proyecto):

    python -m scripts.migrar_base_anterior                    # destino: base local instance/khemik.db
    python -m scripts.migrar_base_anterior --origen C:/ruta/inventario.db

Para subir los datos a Neon, define antes DATABASE_URL con la cadena de conexión:

    PowerShell:  $env:DATABASE_URL = "postgresql://usuario:clave@host/neondb?sslmode=require"
    macOS/Linux: export DATABASE_URL="postgresql://usuario:clave@host/neondb?sslmode=require"

Los usuarios conservan su contraseña. El rol "user" anterior pasa a ser "operador".
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

from backend.config import BASE_DIR, cargar_config
from backend.database import inicializar_base, normalizar_url
from backend.service import InventarioService
from backend.usuarios import UsuarioService

ORIGENES_POSIBLES = (BASE_DIR / "repository" / "inventario.db", BASE_DIR / "inventario.db")


def leer_origen(ruta: Path) -> tuple[list[dict], list[dict]]:
    conexion = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    conexion.row_factory = sqlite3.Row
    try:
        tablas = {fila[0] for fila in conexion.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "movimientos" not in tablas:
            sys.exit(f"{ruta} no tiene la tabla 'movimientos': no parece ser la base anterior de Khemik.")
        movimientos = [dict(fila) for fila in conexion.execute("SELECT * FROM movimientos ORDER BY id")]
        usuarios = ([dict(fila) for fila in conexion.execute("SELECT username, password_hash, role FROM usuarios")]
                    if "usuarios" in tablas else [])
    finally:
        conexion.close()
    return movimientos, usuarios


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--origen", type=Path, help="Ruta a la base anterior (por defecto repository/inventario.db).")
    parser.add_argument("--forzar", action="store_true", help="Reemplaza los movimientos que ya tenga el destino.")
    args = parser.parse_args()

    origen = args.origen or next((ruta for ruta in ORIGENES_POSIBLES if ruta.exists()), None)
    if origen is None or not origen.exists():
        sys.exit("No se encontró la base anterior. Indica la ruta con --origen.")

    destino = cargar_config({"PRODUCTION": False})["DATABASE_URL"]
    print(f"Origen:  {origen}")
    print(f"Destino: {make_url(normalizar_url(destino)).render_as_string(hide_password=True)}")

    movimientos, usuarios_origen = leer_origen(origen)
    session_factory = inicializar_base(destino)
    inventario = InventarioService(session_factory)
    usuarios = UsuarioService(session_factory)

    with inventario.transaccion() as repo:
        existentes = repo.contar_movimientos()
    if existentes and not args.forzar:
        sys.exit(f"El destino ya tiene {existentes} movimientos. Usa --forzar para reemplazarlos.")

    creados = 0
    for usuario in usuarios_origen:
        rol = "admin" if usuario["role"] == "admin" else "operador"
        try:
            creados += usuarios.importar_existente(usuario["username"], usuario["password_hash"], rol)
        except ValueError as error:
            print(f"  Usuario omitido ({usuario['username']}): {error}")
    print(f"Usuarios migrados: {creados} de {len(usuarios_origen)}")

    if not movimientos:
        print("La base anterior no tiene movimientos.")
        return
    resultado = inventario.restaurar(movimientos, None)
    print(f"Movimientos migrados: {resultado['importados']}; rechazados: {resultado['rechazados']}")
    for detalle in resultado["errores"]:
        print(f"  {detalle}")


if __name__ == "__main__":
    main()
