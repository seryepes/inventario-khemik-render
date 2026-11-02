from __future__ import annotations

from typing import Any, Iterable, Optional

from sqlalchemy import case, delete, func, select, text
from sqlalchemy.orm import Session

from . import models as m

# Ingreso suma, Salida resta y "Sin ubicar" no afecta el saldo.
SALDO = func.coalesce(func.sum(case(
    (m.Movimiento.tipo == "Ingreso", m.Movimiento.cantidad),
    (m.Movimiento.tipo == "Salida", -m.Movimiento.cantidad),
    else_=0,
)), 0)


class InventarioRepository:
    """Acceso a datos. Opera dentro de la sesión (transacción) que le entrega el servicio."""

    def __init__(self, session: Session) -> None:
        self.session = session

    @property
    def es_postgres(self) -> bool:
        return self.session.get_bind().dialect.name == "postgresql"

    # --- Catálogos -------------------------------------------------------

    def _bloquear(self, query, bloquear: bool):
        return query.with_for_update() if bloquear else query

    def producto_por_nombre(self, nombre: str, bloquear: bool = False) -> Optional[m.Producto]:
        query = select(m.Producto).where(func.lower(m.Producto.nombre) == nombre.strip().lower())
        return self.session.scalar(self._bloquear(query, bloquear))

    def producto_por_id(self, producto_id: int, bloquear: bool = False) -> Optional[m.Producto]:
        query = select(m.Producto).where(m.Producto.id == producto_id)
        return self.session.scalar(self._bloquear(query, bloquear))

    def presentacion_por_nombre(self, nombre: str) -> Optional[m.Presentacion]:
        query = select(m.Presentacion).where(func.lower(m.Presentacion.nombre) == nombre.strip().lower())
        return self.session.scalar(query)

    def ubicacion_por_codigo(self, codigo: str, bloquear: bool = False) -> Optional[m.Ubicacion]:
        query = select(m.Ubicacion).where(m.Ubicacion.codigo == codigo)
        return self.session.scalar(self._bloquear(query, bloquear))

    def estado_lote(self, producto_id: int, lote: str, bloquear: bool = False) -> Optional[m.EstadoLote]:
        query = select(m.EstadoLote).where(
            m.EstadoLote.producto_id == producto_id,
            m.EstadoLote.lote == lote,
        )
        return self.session.scalar(self._bloquear(query, bloquear))

    def listar_ubicaciones(self) -> list[m.Ubicacion]:
        return list(self.session.scalars(
            select(m.Ubicacion).where(m.Ubicacion.activo.is_(True)).order_by(m.Ubicacion.fila, m.Ubicacion.columna)
        ))

    def listar_productos(self) -> list[m.Producto]:
        return list(self.session.scalars(select(m.Producto).order_by(m.Producto.id)))

    def listar_presentaciones(self) -> list[m.Presentacion]:
        return list(self.session.scalars(select(m.Presentacion).order_by(m.Presentacion.id)))

    def agregar(self, entidad: Any) -> Any:
        self.session.add(entidad)
        self.session.flush()
        return entidad

    # --- Movimientos -----------------------------------------------------

    def listar_movimientos(self) -> list[m.Movimiento]:
        return list(self.session.scalars(select(m.Movimiento).order_by(m.Movimiento.id.desc())).unique())

    def obtener_movimiento(self, id_: int) -> Optional[m.Movimiento]:
        return self.session.get(m.Movimiento, id_)

    def movimientos_de_traslado(self, traslado_id: str) -> list[m.Movimiento]:
        return list(self.session.scalars(select(m.Movimiento).where(m.Movimiento.traslado_id == traslado_id)).unique())

    def eliminar_movimientos(self, movimientos: Iterable[m.Movimiento]) -> None:
        for movimiento in movimientos:
            self.session.delete(movimiento)
        self.session.flush()

    def borrar_movimientos(self) -> int:
        return self.session.execute(delete(m.Movimiento)).rowcount or 0

    def borrar_estados_lote(self) -> int:
        return self.session.execute(delete(m.EstadoLote)).rowcount or 0

    def contar_movimientos(self) -> int:
        return self.session.scalar(select(func.count(m.Movimiento.id))) or 0

    def saldo_ubicacion(self, ubicacion_id: int, presentacion_id: int, excluir_id: Optional[int] = None) -> int:
        query = select(SALDO).where(
            m.Movimiento.ubicacion_id == ubicacion_id, m.Movimiento.presentacion_id == presentacion_id,
        )
        if excluir_id:
            query = query.where(m.Movimiento.id != excluir_id)
        return int(self.session.scalar(query) or 0)

    def productos_con_stock_en_ubicacion(
        self, ubicacion_id: int, excluir_id: Optional[int] = None,
    ) -> list[tuple[str, int]]:
        query = (
            select(m.Producto.nombre, SALDO)
            .select_from(m.Movimiento)
            .join(m.Producto, m.Movimiento.producto_id == m.Producto.id)
            .where(m.Movimiento.ubicacion_id == ubicacion_id)
            .group_by(m.Producto.id, m.Producto.nombre)
            .having(SALDO > 0)
        )
        if excluir_id is not None:
            query = query.where(m.Movimiento.id != excluir_id)
        return [(nombre, int(cantidad)) for nombre, cantidad in self.session.execute(query)]

    def saldo_lote(self, ubicacion_id: Optional[int], producto_id: int, presentacion_id: int, lote: str) -> int:
        ubicacion = (m.Movimiento.ubicacion_id.is_(None) if ubicacion_id is None
                     else m.Movimiento.ubicacion_id == ubicacion_id)
        query = select(SALDO).where(
            ubicacion, m.Movimiento.producto_id == producto_id,
            m.Movimiento.presentacion_id == presentacion_id, m.Movimiento.lote == lote,
        )
        return int(self.session.scalar(query) or 0)

    def saldo_producto_lote(self, producto_id: int, lote: str) -> int:
        query = select(SALDO).where(
            m.Movimiento.producto_id == producto_id,
            m.Movimiento.lote == lote,
        )
        return int(self.session.scalar(query) or 0)

    def primer_ingreso_lote(self, producto_id: int, lote: str):
        query = select(func.min(m.Movimiento.creado_en)).where(
            m.Movimiento.producto_id == producto_id,
            m.Movimiento.lote == lote,
            m.Movimiento.tipo == "Ingreso",
        )
        return self.session.scalar(query)

    def lotes_con_stock(self) -> list[Any]:
        query = (
            select(m.Producto.id, m.Producto.nombre, m.Producto.categoria, m.Movimiento.lote, SALDO.label("saldo"))
            .select_from(m.Movimiento)
            .join(m.Producto, m.Movimiento.producto_id == m.Producto.id)
            .group_by(m.Producto.id, m.Producto.nombre, m.Producto.categoria, m.Movimiento.lote)
            .having(SALDO > 0)
            .order_by(m.Producto.nombre, m.Movimiento.lote)
        )
        return list(self.session.execute(query))

    def lote_tiene_salida(self, lote: str, producto_id: int, presentacion_id: int, excluir_id: Optional[int]) -> bool:
        """¿El lote ya salió de la bodega? Las salidas internas de un traslado no cuentan."""
        query = select(m.Movimiento.id).where(
            m.Movimiento.lote == lote, m.Movimiento.producto_id == producto_id,
            m.Movimiento.presentacion_id == presentacion_id, m.Movimiento.tipo == "Salida",
            m.Movimiento.traslado_id.is_(None),
        )
        if excluir_id:
            query = query.where(m.Movimiento.id != excluir_id)
        return self.session.scalar(query.limit(1)) is not None

    def stock(self) -> list[Any]:
        query = (
            select(
                m.Ubicacion.codigo, m.Producto.nombre, m.Producto.categoria,
                m.Presentacion.nombre, m.Movimiento.lote, SALDO.label("saldo"),
            )
            .select_from(m.Movimiento)
            .join(m.Producto, m.Movimiento.producto_id == m.Producto.id)
            .join(m.Presentacion, m.Movimiento.presentacion_id == m.Presentacion.id)
            .outerjoin(m.Ubicacion, m.Movimiento.ubicacion_id == m.Ubicacion.id)
            .group_by(
                m.Ubicacion.codigo, m.Producto.nombre, m.Producto.categoria,
                m.Presentacion.nombre, m.Movimiento.lote,
            )
            .having(SALDO > 0)
            .order_by(m.Ubicacion.codigo, m.Producto.nombre)
        )
        return list(self.session.execute(query))

    def ingresos_por_producto(self) -> list[Any]:
        query = (
            select(m.Producto.nombre, m.Presentacion.nombre, func.sum(m.Movimiento.cantidad))
            .select_from(m.Movimiento)
            .join(m.Producto, m.Movimiento.producto_id == m.Producto.id)
            .join(m.Presentacion, m.Movimiento.presentacion_id == m.Presentacion.id)
            .where(m.Movimiento.tipo == "Ingreso")
            .group_by(m.Producto.nombre, m.Presentacion.nombre)
        )
        return list(self.session.execute(query))

    # --- Usuarios --------------------------------------------------------

    def bloquear_tabla_usuarios(self) -> None:
        """Evita que dos peticiones simultáneas creen dos administradores iniciales."""
        if self.es_postgres:
            self.session.execute(text("LOCK TABLE usuarios IN EXCLUSIVE MODE"))

    def hay_usuarios(self) -> bool:
        return self.session.scalar(select(m.Usuario.id).limit(1)) is not None

    def usuario_por_username(self, username: str) -> Optional[m.Usuario]:
        return self.session.scalar(select(m.Usuario).where(m.Usuario.username == username.strip().lower()))

    def usuario_por_id(self, id_: int) -> Optional[m.Usuario]:
        return self.session.get(m.Usuario, id_)

    def listar_usuarios(self) -> list[m.Usuario]:
        return list(self.session.scalars(select(m.Usuario).order_by(m.Usuario.username)))

    def contar_admins_activos(self) -> int:
        query = select(func.count(m.Usuario.id)).where(m.Usuario.rol == "admin", m.Usuario.activo.is_(True))
        return self.session.scalar(query) or 0

    # --- Auditoría y ajustes ---------------------------------------------

    def registrar_auditoria(self, usuario_id: Optional[int], accion: str, detalle: str = "") -> None:
        self.session.add(m.Auditoria(usuario_id=usuario_id, accion=accion, detalle=detalle[:2000]))

    def listar_auditoria(self, limite: int) -> list[m.Auditoria]:
        query = select(m.Auditoria).order_by(m.Auditoria.id.desc()).limit(limite)
        return list(self.session.scalars(query).unique())

    def obtener_ajuste(self, clave: str) -> Optional[str]:
        ajuste = self.session.get(m.Ajuste, clave)
        return ajuste.valor if ajuste else None

    def guardar_ajuste(self, clave: str, valor: str) -> None:
        self.session.merge(m.Ajuste(clave=clave, valor=valor))
