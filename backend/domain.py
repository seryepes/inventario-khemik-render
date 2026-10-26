from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

SIN_UBICAR = "SIN UBICAR"
_POSICION = re.compile(r"^(?:(\d{1,3})[\s-]*([A-Z]{1,2})|([A-Z]{1,2})[\s-]*(\d{1,3}))$")


@dataclass
class Movimiento:
    fecha: str = ""
    mvto: str = "Ingreso"
    posicion: str = SIN_UBICAR
    producto: str = "Otro"
    presentacion: str = "Otra"
    lote: str = "-"
    cantidad: int = 0
    observaciones: str = ""
    id: int | None = None
    posicion_destino: str = ""
    traslado_id: str | None = None
    es_traslado: bool = False
    creado_por: str = ""
    creado_en: str = ""

    def __post_init__(self) -> None:
        self.id = int(self.id) if self.id not in (None, "") else None
        self.fecha = self.normalizar_fecha(self.fecha)
        self.mvto = self.normalizar_movimiento(self.mvto)
        self.posicion = self.normalizar_posicion(self.posicion)
        self.posicion_destino = self.normalizar_posicion(self.posicion_destino) if self.posicion_destino else ""
        self.producto = str(self.producto or "Otro").strip()
        self.presentacion = self.normalizar_presentacion(self.presentacion)
        self.lote = self.normalizar_lote(self.lote)
        try:
            self.cantidad = int(self.cantidad or 0)
        except (TypeError, ValueError):
            raise ValueError(f"Cantidad inválida: {self.cantidad!r}.") from None
        self.observaciones = str(self.observaciones or "").strip()[:500]
        self.es_traslado = bool(self.es_traslado or self.traslado_id)

    @staticmethod
    def normalizar_fecha(value: Any) -> str:
        texto = str(value or date.today().isoformat()).split("T")[0].strip()
        try:
            return date.fromisoformat(texto).isoformat()
        except ValueError:
            raise ValueError(f"Fecha inválida: {texto!r}. Usa el formato AAAA-MM-DD.") from None

    @staticmethod
    def normalizar_presentacion(value: Any) -> str:
        clean = "".join(str(value or "").strip().lower().split())
        if clean in {"125g", "0.125kg", "125kg", "125"}:
            return "125 kg"
        if clean in {"200kg", "200"}:
            return "200 kg"
        return str(value).strip() if value else "Otra"

    @staticmethod
    def normalizar_movimiento(value: Any) -> str:
        clean = str(value or "").strip().lower()
        values = {"ingreso": "Ingreso", "salida": "Salida", "traslado": "Traslado", "sin ubicar": "Sin ubicar"}
        return values.get(clean, str(value).strip() if value else "Ingreso")

    @staticmethod
    def normalizar_posicion(value: Any) -> str:
        """Devuelve el código canónico fila+columna (p. ej. "12C"), aceptando "C12", "12-c" o "12 C"."""
        texto = str(value or "").strip().upper()
        if not texto or texto in {"-", "0", "SINUBICAR", SIN_UBICAR}:
            return SIN_UBICAR
        match = _POSICION.match(texto)
        if match:
            fila = match.group(1) or match.group(4)
            columna = match.group(2) or match.group(3)
            return f"{int(fila)}{columna}"
        return texto

    @staticmethod
    def normalizar_lote(value: Any) -> str:
        return str(value or "").strip().upper()[:60] or "-"

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
            "esTraslado": self.es_traslado, "creadoPor": self.creado_por, "creadoEn": self.creado_en,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Movimiento":
        if not isinstance(data, dict):
            raise ValueError("Cada registro debe ser un objeto JSON.")
        return cls(
            id=data.get("id"), fecha=data.get("fecha"), mvto=data.get("mvto"),
            posicion=data.get("posicion"), posicion_destino=data.get("posicionDestino", data.get("posicion_destino", "")),
            producto=data.get("producto"), presentacion=data.get("presentacion"),
            lote=data.get("lote"), cantidad=data.get("cantidad"), observaciones=data.get("observaciones"),
            traslado_id=data.get("trasladoId", data.get("traslado_id")),
            es_traslado=data.get("esTraslado", data.get("es_traslado", False)),
        )
