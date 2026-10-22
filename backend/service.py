from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from .domain import Movimiento
from repository import SQLiteInventarioRepository

CAPACIDAD_POR_PRESENTACION = {"125 kg": 5, "200 kg": 4}


class InventarioService:
    def __init__(self, database_path: str | Path | None = None) -> None:
        self.repository = SQLiteInventarioRepository(database_path)
        self.database_path = str(self.repository.database_path)

    def listar(self) -> list[Movimiento]:
        return self.repository.listar()

    @staticmethod
    def _normalizar_lote(lote: Any) -> str:
        return str(lote or "").strip().upper()

    def _cantidad_posicion(self, posicion: str, presentacion: str, movimientos: list[Movimiento], excluir_id: int | None = None) -> int:
        return sum(item.cantidad * item.factor for item in movimientos
                   if item.posicion == posicion and item.presentacion == presentacion and item.id != excluir_id)

    def _validar_capacidad(self, movimiento: Movimiento, movimientos: list[Movimiento], posicion: str | None = None) -> None:
        posicion = Movimiento.normalizar_posicion(posicion or movimiento.posicion)
        capacidad = CAPACIDAD_POR_PRESENTACION.get(movimiento.presentacion)
        if movimiento.mvto != "Ingreso" or not capacidad or posicion == "SIN UBICAR":
            return
        actual = self._cantidad_posicion(posicion, movimiento.presentacion, movimientos, movimiento.id)
        if actual + movimiento.cantidad > capacidad:
            disponible = max(0, capacidad - actual)
            raise ValueError(f"La ubicación {posicion} está llena para {movimiento.presentacion}. Capacidad máxima: {capacidad} productos; disponibles: {disponible}.")

    def _validar_duplicado(self, movimiento: Movimiento, movimientos: list[Movimiento]) -> None:
        lote = self._normalizar_lote(movimiento.lote)
        if not lote or lote == "-" or movimiento.mvto != "Ingreso" or movimiento.es_traslado:
            return
        for item in movimientos:
            if item.id != movimiento.id and self._normalizar_lote(item.lote) == lote and item.producto == movimiento.producto and item.presentacion == movimiento.presentacion and item.mvto == "Salida":
                raise ValueError(f"El lote {lote} ya existe como salida y no puede registrarse como ingreso.")

    def guardar_movimiento(self, data: dict[str, Any]) -> Movimiento:
        movimiento = Movimiento.from_dict(data)
        if movimiento.cantidad <= 0:
            raise ValueError("La cantidad debe ser mayor que cero.")
        movimientos = self.listar()
        self._validar_duplicado(movimiento, movimientos)
        self._validar_capacidad(movimiento, movimientos)
        return self.repository.guardar(movimiento)

    def _stock_lote(self, movimiento: Movimiento, posicion: str, movimientos: list[Movimiento]) -> int:
        return sum(item.cantidad * item.factor for item in movimientos if item.posicion == posicion and self._normalizar_lote(item.lote) == self._normalizar_lote(movimiento.lote) and item.producto == movimiento.producto and item.presentacion == movimiento.presentacion)

    def guardar_traslado(self, data: dict[str, Any]) -> list[Movimiento]:
        movimiento = Movimiento.from_dict(data)
        origen, destino = movimiento.posicion, movimiento.posicion_destino
        if not destino or origen == "SIN UBICAR" or destino == "SIN UBICAR":
            raise ValueError("El traslado requiere una posición de origen y una posición de destino válidas.")
        if origen == destino:
            raise ValueError("La posición de origen y destino deben ser diferentes.")
        movimientos = self.listar()
        disponible = self._stock_lote(movimiento, origen, movimientos)
        if movimiento.cantidad <= 0 or movimiento.cantidad > disponible:
            raise ValueError(f"Stock insuficiente para trasladar. Disponible en {origen}: {disponible}.")
        ingreso = Movimiento.from_dict({**data, "mvto": "Ingreso", "posicion": destino})
        self._validar_capacidad(ingreso, movimientos, destino)
        traslado_id = f"TR-{uuid.uuid4().hex[:12]}"
        observaciones = movimiento.observaciones or f"Traslado de {origen} a {destino}"
        salida = Movimiento.from_dict({**data, "mvto": "Salida", "posicion": origen, "posicionDestino": "", "trasladoId": traslado_id, "esTraslado": True, "observaciones": observaciones})
        ingreso = Movimiento.from_dict({**salida.to_dict(), "mvto": "Ingreso", "posicion": destino})
        return self.repository.guardar_varios([salida, ingreso])

    def eliminar(self, id_: int) -> None:
        self.repository.eliminar(id_)

    def borrar_todo(self) -> None:
        self.repository.borrar_todo()

    def importar(self, registros: list[dict[str, Any]]) -> dict[str, int]:
        movimientos = self.listar()
        validos: list[Movimiento] = []
        rechazados = 0
        for data in registros:
            item = Movimiento.from_dict(data)
            try:
                base = movimientos + validos
                self._validar_duplicado(item, base)
                self._validar_capacidad(item, base)
                validos.append(item)
            except ValueError:
                rechazados += 1
        if not validos:
            raise ValueError("No se pudo importar ningún registro válido.")
        self.repository.guardar_varios(validos)
        return {"importados": len(validos), "rechazados": rechazados}

    def restaurar(self, registros: list[dict[str, Any]]) -> None:
        self.repository.restaurar([Movimiento.from_dict(data) for data in registros])

    def stock(self) -> list[dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for item in self.listar():
            if item.factor == 0:
                continue
            key = (item.posicion, item.producto, item.presentacion, item.lote)
            row = result.setdefault(key, {"posicion": item.posicion, "producto": item.producto, "presentacion": item.presentacion, "lote": item.lote, "cantidad": 0})
            row["cantidad"] += item.cantidad * item.factor
        return [row for row in result.values() if row["cantidad"] > 0]

    def estadisticas(self) -> dict[str, dict[str, int]]:
        result = {product: {"125 kg": 0, "200 kg": 0, "Otra": 0} for product in ("Aluminio", "Magnesio")}
        for item in self.listar():
            if item.mvto == "Ingreso" and item.producto in result:
                presentation = "125 kg" if "125" in item.presentacion else "200 kg" if "200" in item.presentacion else "Otra"
                result[item.producto][presentation] += item.cantidad
        return result

    def mapa_posiciones(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for item in self.listar():
            if not item.posicion or item.posicion == "SIN UBICAR" or item.factor == 0:
                continue
            row = result.setdefault(item.posicion, {"cantidad": 0, "aluminioTotal": 0, "magnesioTotal": 0, "otroTotal": 0})
            amount = item.cantidad * item.factor
            row["cantidad"] += amount
            key = "aluminioTotal" if item.producto == "Aluminio" else "magnesioTotal" if item.producto == "Magnesio" else "otroTotal"
            row[key] += amount
        return result
