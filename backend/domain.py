from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass
class Movimiento:
    fecha: str = ""
    mvto: str = "Ingreso"
    posicion: str = "Sin Ubicar"
    producto: str = "Otro"
    presentacion: str = "Otra"
    lote: str = "-"
    cantidad: int = 0
    observaciones: str = ""
    id: int | None = None
    posicion_destino: str = ""
    traslado_id: str | None = None
    es_traslado: bool = False

    def __post_init__(self) -> None:
        self.id = int(self.id) if self.id not in (None, "") else None
        self.fecha = str(self.fecha or date.today().isoformat()).split("T")[0]
        self.mvto = self.normalizar_movimiento(self.mvto)
        self.posicion = self.normalizar_posicion(self.posicion)
        self.posicion_destino = self.normalizar_posicion(self.posicion_destino) if self.posicion_destino else ""
        self.producto = str(self.producto or "Otro").strip()
        self.presentacion = self.normalizar_presentacion(self.presentacion)
        self.lote = str(self.lote or "-").strip()
        self.cantidad = int(self.cantidad or 0)
        self.observaciones = str(self.observaciones or "").strip()
        self.es_traslado = bool(self.es_traslado)

    @staticmethod
    def normalizar_presentacion(value: Any) -> str:
        clean = "".join(str(value or "").strip().lower().split())
        if clean in {"125g", "0.125kg", "125kg"}:
            return "125 kg"
        if clean == "200kg":
            return "200 kg"
        return str(value).strip() if value else "Otra"

    @staticmethod
    def normalizar_movimiento(value: Any) -> str:
        clean = str(value or "").strip().lower()
        values = {"ingreso": "Ingreso", "salida": "Salida", "traslado": "Traslado", "sin ubicar": "Sin ubicar"}
        return values.get(clean, str(value).strip() if value else "Ingreso")

    @staticmethod
    def normalizar_posicion(value: Any) -> str:
        return str(value).strip().upper() if value else "Sin Ubicar"

    @property
    def factor(self) -> int:
        return 1 if self.mvto == "Ingreso" else -1 if self.mvto == "Salida" else 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "fecha": self.fecha, "mvto": self.mvto,
            "posicion": self.posicion, "posicionDestino": self.posicion_destino,
            "producto": self.producto, "presentacion": self.presentacion,
            "lote": self.lote, "cantidad": self.cantidad,
            "observaciones": self.observaciones, "trasladoId": self.traslado_id,
            "esTraslado": self.es_traslado,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Movimiento":
        return cls(
            id=data.get("id"), fecha=data.get("fecha"), mvto=data.get("mvto"),
            posicion=data.get("posicion"), posicion_destino=data.get("posicionDestino", data.get("posicion_destino", "")),
            producto=data.get("producto"), presentacion=data.get("presentacion"),
            lote=data.get("lote"), cantidad=data.get("cantidad"), observaciones=data.get("observaciones"),
            traslado_id=data.get("trasladoId", data.get("traslado_id")),
            es_traslado=data.get("esTraslado", data.get("es_traslado", False)),
        )
