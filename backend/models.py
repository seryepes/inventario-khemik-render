from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

ROLES = ("admin", "operador", "consulta")
TIPOS_MOVIMIENTO = ("Ingreso", "Salida", "Sin ubicar")


def ahora() -> datetime:
    return datetime.now(timezone.utc)


class Producto(Base):
    __tablename__ = "productos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(60), unique=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)


class Presentacion(Base):
    __tablename__ = "presentaciones"
    __table_args__ = (
        CheckConstraint("capacidad_por_ubicacion IS NULL OR capacidad_por_ubicacion > 0", name="ck_presentacion_capacidad"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(30), unique=True)
    # Máximo de unidades de esta presentación por ubicación; NULL = sin límite.
    capacidad_por_ubicacion: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)


class Ubicacion(Base):
    __tablename__ = "ubicaciones"
    __table_args__ = (UniqueConstraint("fila", "columna", name="uq_ubicacion_fila_columna"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), unique=True)
    # Fila/columna son nulas en ubicaciones especiales fuera de la cuadrícula.
    fila: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    columna: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = (CheckConstraint(f"rol IN {ROLES}", name="ck_usuario_rol"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True)  # siempre en minúsculas
    password_hash: Mapped[str] = mapped_column(String(255))
    rol: Mapped[str] = mapped_column(String(20), default="operador")
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    intentos_fallidos: Mapped[int] = mapped_column(Integer, default=0)
    bloqueado_hasta: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ultimo_acceso: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)


class Movimiento(Base):
    __tablename__ = "movimientos"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="ck_movimiento_cantidad"),
        CheckConstraint(f"tipo IN {TIPOS_MOVIMIENTO}", name="ck_movimiento_tipo"),
        Index("ix_movimientos_saldo", "ubicacion_id", "producto_id", "presentacion_id", "lote"),
        Index("ix_movimientos_lote", "lote"),
        Index("ix_movimientos_traslado", "traslado_id"),
        Index("ix_movimientos_fecha", "fecha"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[date] = mapped_column(Date)
    tipo: Mapped[str] = mapped_column(String(12))
    # NULL = "Sin ubicar".
    ubicacion_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ubicaciones.id", ondelete="RESTRICT"), nullable=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id", ondelete="RESTRICT"))
    presentacion_id: Mapped[int] = mapped_column(ForeignKey("presentaciones.id", ondelete="RESTRICT"))
    lote: Mapped[str] = mapped_column(String(60), default="-")
    cantidad: Mapped[int] = mapped_column(Integer)
    observaciones: Mapped[str] = mapped_column(Text, default="")
    # Las dos filas (salida + ingreso) de un traslado comparten este identificador.
    traslado_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    creado_por_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    actualizado_por_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    actualizado_en: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    producto: Mapped[Producto] = relationship(lazy="joined")
    presentacion: Mapped[Presentacion] = relationship(lazy="joined")
    ubicacion: Mapped[Optional[Ubicacion]] = relationship(lazy="joined")
    creado_por: Mapped[Optional[Usuario]] = relationship(foreign_keys=[creado_por_id], lazy="joined")


class Auditoria(Base):
    __tablename__ = "auditoria"
    __table_args__ = (Index("ix_auditoria_creado_en", "creado_en"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[Optional[int]] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    accion: Mapped[str] = mapped_column(String(40))
    detalle: Mapped[str] = mapped_column(Text, default="")
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)

    usuario: Mapped[Optional[Usuario]] = relationship(lazy="joined")


class Ajuste(Base):
    __tablename__ = "ajustes"

    clave: Mapped[str] = mapped_column(String(60), primary_key=True)
    valor: Mapped[str] = mapped_column(Text)
