from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from .domain import POSICIONES_PISO
from .models import Presentacion, Producto, Ubicacion

PRODUCTOS_INICIALES = {
    "Aluminio": "producto_terminado",
    "Magnesio": "producto_terminado",
    "Otro": "materia_prima",
}
# nombre -> capacidad máxima por ubicación (None = sin límite)
PRESENTACIONES_INICIALES = {"125 kg": 5, "200 kg": 4, "Otra": None}
FILAS = range(1, 45)
COLUMNAS = ("A", "B", "C", "D", "E", "F")


def sembrar_catalogos(session_factory: sessionmaker) -> None:
    """Inserta los catálogos base solo si están vacíos (es seguro llamarlo en cada arranque)."""
    try:
        with session_factory.begin() as session:
            if session.scalar(select(Producto.id).limit(1)) is None:
                session.add_all(
                    Producto(nombre=nombre, categoria=categoria)
                    for nombre, categoria in PRODUCTOS_INICIALES.items()
                )
            if session.scalar(select(Presentacion.id).limit(1)) is None:
                session.add_all(
                    Presentacion(nombre=nombre, capacidad_por_ubicacion=capacidad)
                    for nombre, capacidad in PRESENTACIONES_INICIALES.items()
                )
            if session.scalar(select(Ubicacion.id).limit(1)) is None:
                session.add_all(
                    Ubicacion(codigo=f"{fila}{columna}", fila=fila, columna=columna)
                    for fila in FILAS for columna in COLUMNAS
                )
            ubicaciones = set(session.scalars(select(Ubicacion.codigo)))
            session.add_all(
                Ubicacion(codigo=codigo)
                for codigo in POSICIONES_PISO if codigo not in ubicaciones
            )
    except IntegrityError:
        # Otro proceso sembró los catálogos al mismo tiempo.
        pass
