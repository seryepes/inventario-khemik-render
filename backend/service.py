from __future__ import annotations

import re
import secrets
import uuid
from contextlib import contextmanager
from datetime import date
from typing import Any, Iterator, Optional

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from . import models as m
from .domain import SIN_UBICAR, Movimiento
from .repository import InventarioRepository

MAX_REGISTROS_POR_CARGA = 5000
_CODIGO_GRILLA = re.compile(r"^(\d{1,3})([A-Z]{1,2})$")

Clave = tuple  # (ubicacion_id, producto_id, presentacion_id, lote)


class ConflictoError(ValueError):
    """El recurso ya existe (se responde con HTTP 409)."""


class ServicioBase:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    @contextmanager
    def transaccion(self) -> Iterator[InventarioRepository]:
        """Unidad de trabajo: confirma al salir o deshace todo si ocurre un error."""
        with self._session_factory.begin() as session:
            yield InventarioRepository(session)


class InventarioService(ServicioBase):

    # --- Conversión ------------------------------------------------------

    @staticmethod
    def _a_dominio(fila: m.Movimiento) -> Movimiento:
        return Movimiento(
            id=fila.id, fecha=fila.fecha.isoformat(), mvto=fila.tipo,
            posicion=fila.ubicacion.codigo if fila.ubicacion else SIN_UBICAR,
            producto=fila.producto.nombre, presentacion=fila.presentacion.nombre,
            lote=fila.lote, cantidad=fila.cantidad, observaciones=fila.observaciones,
            traslado_id=fila.traslado_id,
            creado_por=fila.creado_por.username if fila.creado_por else "",
            creado_en=fila.creado_en.isoformat() if fila.creado_en else "",
        )

    @staticmethod
    def _clave(fila: m.Movimiento) -> Clave:
        return (fila.ubicacion_id, fila.producto_id, fila.presentacion_id, fila.lote)

    @staticmethod
    def _describir(fila: m.Movimiento) -> str:
        posicion = fila.ubicacion.codigo if fila.ubicacion else SIN_UBICAR
        return (f"#{fila.id} {fila.tipo} {fila.cantidad} x {fila.producto.nombre} {fila.presentacion.nombre} "
                f"lote {fila.lote} en {posicion}")

    # --- Resolución de catálogos ------------------------------------------

    def _resolver_ubicacion(self, repo: InventarioRepository, codigo: str, bloquear: bool = False,
                            crear_faltantes: bool = False) -> Optional[m.Ubicacion]:
        if codigo == SIN_UBICAR:
            return None
        ubicacion = repo.ubicacion_por_codigo(codigo, bloquear)
        if ubicacion is None and crear_faltantes:
            grilla = _CODIGO_GRILLA.match(codigo)
            ubicacion = repo.agregar(m.Ubicacion(
                codigo=codigo[:20],
                fila=int(grilla.group(1)) if grilla else None,
                columna=grilla.group(2) if grilla else None,
            ))
        if ubicacion is None or not ubicacion.activo:
            raise ValueError(f"La posición '{codigo}' no existe. Usa fila + columna, por ejemplo 12C.")
        return ubicacion

    def _resolver(self, repo: InventarioRepository, mov: Movimiento, bloquear: bool = True,
                  crear_faltantes: bool = False) -> tuple[m.Producto, m.Presentacion, Optional[m.Ubicacion]]:
        # Bloquear la fila del producto serializa las escrituras concurrentes de ese producto
        # (en PostgreSQL); así dos usuarios no pueden sacar el mismo stock a la vez.
        producto = repo.producto_por_nombre(mov.producto, bloquear=bloquear)
        if producto is None and crear_faltantes:
            producto = repo.agregar(m.Producto(nombre=mov.producto[:60]))
        if producto is None or not producto.activo:
            raise ValueError(f"El producto '{mov.producto}' no está registrado en el catálogo.")
        presentacion = repo.presentacion_por_nombre(mov.presentacion)
        if presentacion is None and crear_faltantes:
            presentacion = repo.agregar(m.Presentacion(nombre=mov.presentacion[:30]))
        if presentacion is None or not presentacion.activo:
            raise ValueError(f"La presentación '{mov.presentacion}' no está registrada en el catálogo.")
        ubicacion = self._resolver_ubicacion(
            repo, mov.posicion, bloquear=bloquear and mov.mvto == "Ingreso", crear_faltantes=crear_faltantes,
        )
        return producto, presentacion, ubicacion

    # --- Reglas de negocio -------------------------------------------------

    @staticmethod
    def _validar_basico(mov: Movimiento) -> None:
        if mov.mvto == "Traslado":
            raise ValueError("Los traslados se registran con la opción Traslado, indicando origen y destino.")
        if mov.mvto not in m.TIPOS_MOVIMIENTO:
            raise ValueError(f"Tipo de movimiento inválido: '{mov.mvto}'.")
        if mov.cantidad <= 0:
            raise ValueError("La cantidad debe ser mayor que cero.")

    @staticmethod
    def _validar_capacidad(repo: InventarioRepository, cantidad: int, presentacion: m.Presentacion,
                           ubicacion: Optional[m.Ubicacion], excluir_id: Optional[int] = None) -> None:
        capacidad = presentacion.capacidad_por_ubicacion
        if ubicacion is None or not capacidad:
            return
        actual = repo.saldo_ubicacion(ubicacion.id, presentacion.id, excluir_id)
        if actual + cantidad > capacidad:
            raise ValueError(
                f"La ubicación {ubicacion.codigo} está llena para {presentacion.nombre}. "
                f"Capacidad máxima: {capacidad} productos; disponibles: {max(0, capacidad - actual)}."
            )

    def _validar_reglas(self, repo: InventarioRepository, mov: Movimiento, producto: m.Producto,
                        presentacion: m.Presentacion, ubicacion: Optional[m.Ubicacion]) -> None:
        self._validar_basico(mov)
        if mov.mvto != "Ingreso":
            return
        if mov.lote != "-" and repo.lote_tiene_salida(mov.lote, producto.id, presentacion.id, mov.id):
            raise ValueError(f"El lote {mov.lote} ya registró una salida y no puede volver a ingresar.")
        self._validar_capacidad(repo, mov.cantidad, presentacion, ubicacion, mov.id)

    @staticmethod
    def _verificar_saldos(repo: InventarioRepository, claves: dict[Clave, str]) -> None:
        """Invariante: ningún lote puede quedar con saldo negativo en ninguna ubicación."""
        for (ubicacion_id, producto_id, presentacion_id, lote), posicion in claves.items():
            saldo = repo.saldo_lote(ubicacion_id, producto_id, presentacion_id, lote)
            if saldo < 0:
                raise ValueError(
                    f"Stock insuficiente del lote {lote} en {posicion}: la operación dejaría el saldo en {saldo}."
                )

    @staticmethod
    def _nueva_fila(mov: Movimiento, tipo: str, producto: m.Producto, presentacion: m.Presentacion,
                    ubicacion: Optional[m.Ubicacion], usuario_id: Optional[int],
                    traslado_id: Optional[str] = None, observaciones: Optional[str] = None) -> m.Movimiento:
        return m.Movimiento(
            fecha=date.fromisoformat(mov.fecha), tipo=tipo, producto=producto, presentacion=presentacion,
            ubicacion=ubicacion, lote=mov.lote, cantidad=mov.cantidad,
            observaciones=mov.observaciones if observaciones is None else observaciones,
            traslado_id=traslado_id, creado_por_id=usuario_id,
        )

    def _registrar(self, repo: InventarioRepository, mov: Movimiento, usuario_id: Optional[int]) -> m.Movimiento:
        """Crea o edita un movimiento individual aplicando todas las reglas."""
        mov.traslado_id, mov.es_traslado = None, False
        claves: dict[Clave, str] = {}
        fila = None
        if mov.id:
            fila = repo.obtener_movimiento(mov.id)
            if fila is None:
                raise LookupError(f"El movimiento #{mov.id} no existe.")
            if fila.traslado_id:
                raise ValueError("Los movimientos de un traslado no se editan: elimina el traslado y regístralo de nuevo.")
            claves[self._clave(fila)] = fila.ubicacion.codigo if fila.ubicacion else SIN_UBICAR

        producto, presentacion, ubicacion = self._resolver(repo, mov)
        self._validar_reglas(repo, mov, producto, presentacion, ubicacion)

        if fila is None:
            fila = repo.agregar(self._nueva_fila(mov, mov.mvto, producto, presentacion, ubicacion, usuario_id))
        else:
            fila.fecha = date.fromisoformat(mov.fecha)
            fila.tipo = mov.mvto
            fila.producto, fila.presentacion, fila.ubicacion = producto, presentacion, ubicacion
            fila.lote, fila.cantidad, fila.observaciones = mov.lote, mov.cantidad, mov.observaciones
            fila.actualizado_por_id, fila.actualizado_en = usuario_id, m.ahora()
            repo.session.flush()
        claves[self._clave(fila)] = ubicacion.codigo if ubicacion else SIN_UBICAR
        self._verificar_saldos(repo, claves)
        return fila

    # --- Casos de uso ------------------------------------------------------

    def verificar_conexion(self) -> None:
        with self.transaccion() as repo:
            repo.session.execute(text("SELECT 1"))

    def listar(self) -> list[dict[str, Any]]:
        with self.transaccion() as repo:
            return [self._a_dominio(fila).to_dict() for fila in repo.listar_movimientos()]

    def guardar_movimiento(self, data: dict[str, Any], usuario_id: Optional[int]) -> dict[str, Any]:
        mov = Movimiento.from_dict(data)
        with self.transaccion() as repo:
            fila = self._registrar(repo, mov, usuario_id)
            repo.registrar_auditoria(usuario_id, "movimiento.editar" if mov.id else "movimiento.crear", self._describir(fila))
            return self._a_dominio(fila).to_dict()

    def guardar_traslado(self, data: dict[str, Any], usuario_id: Optional[int]) -> list[dict[str, Any]]:
        mov = Movimiento.from_dict(data)
        if not mov.posicion_destino or SIN_UBICAR in (mov.posicion, mov.posicion_destino):
            raise ValueError("El traslado requiere una posición de origen y una posición de destino válidas.")
        if mov.posicion == mov.posicion_destino:
            raise ValueError("La posición de origen y destino deben ser diferentes.")
        if mov.cantidad <= 0:
            raise ValueError("La cantidad debe ser mayor que cero.")
        mov.mvto = "Salida"
        with self.transaccion() as repo:
            producto, presentacion, origen = self._resolver(repo, mov)
            destino = self._resolver_ubicacion(repo, mov.posicion_destino, bloquear=True)
            disponible = repo.saldo_lote(origen.id, producto.id, presentacion.id, mov.lote)
            if mov.cantidad > disponible:
                raise ValueError(f"Stock insuficiente para trasladar. Disponible en {origen.codigo}: {disponible}.")
            self._validar_capacidad(repo, mov.cantidad, presentacion, destino)
            traslado_id = f"TR-{uuid.uuid4().hex[:12]}"
            observaciones = mov.observaciones or f"Traslado de {origen.codigo} a {destino.codigo}"
            filas = [
                repo.agregar(self._nueva_fila(mov, tipo, producto, presentacion, ubicacion, usuario_id, traslado_id, observaciones))
                for tipo, ubicacion in (("Salida", origen), ("Ingreso", destino))
            ]
            repo.registrar_auditoria(usuario_id, "traslado.crear", f"{traslado_id}: " + "; ".join(map(self._describir, filas)))
            return [self._a_dominio(fila).to_dict() for fila in filas]

    def eliminar(self, id_: int, usuario_id: Optional[int]) -> None:
        with self.transaccion() as repo:
            fila = repo.obtener_movimiento(id_)
            if fila is None:
                raise LookupError(f"El movimiento #{id_} no existe.")
            repo.producto_por_nombre(fila.producto.nombre, bloquear=True)
            filas = repo.movimientos_de_traslado(fila.traslado_id) if fila.traslado_id else [fila]
            claves = {self._clave(f): (f.ubicacion.codigo if f.ubicacion else SIN_UBICAR) for f in filas}
            descripcion = "; ".join(map(self._describir, filas))
            repo.eliminar_movimientos(filas)
            self._verificar_saldos(repo, claves)
            repo.registrar_auditoria(usuario_id, "movimiento.eliminar", descripcion)

    def borrar_todo(self, usuario_id: Optional[int]) -> int:
        with self.transaccion() as repo:
            borrados = repo.borrar_movimientos()
            repo.registrar_auditoria(usuario_id, "movimientos.borrar_todo", f"{borrados} movimientos eliminados")
            return borrados

    @staticmethod
    def _validar_lista(registros: Any) -> list[Any]:
        if not isinstance(registros, list) or not registros:
            raise ValueError("No se recibieron registros.")
        if len(registros) > MAX_REGISTROS_POR_CARGA:
            raise ValueError(f"Máximo {MAX_REGISTROS_POR_CARGA} registros por carga.")
        return registros

    def importar(self, registros: Any, usuario_id: Optional[int]) -> dict[str, Any]:
        """Importa registros nuevos validando cada uno; los inválidos se rechazan sin detener la carga.

        El frontend envía el Excel en lotes para mostrar el progreso, por eso un lote
        donde todo falla no es un error: se devuelve el detalle de cada rechazo.
        """
        registros = self._validar_lista(registros)

        def orden(item: tuple[int, Any]) -> tuple[str, int]:
            data = item[1] if isinstance(item[1], dict) else {}
            # Por fecha y, en la misma fecha, ingresos antes que salidas.
            return str(data.get("fecha") or ""), 0 if str(data.get("mvto") or "").lower() == "ingreso" else 1

        importados, fallidos = 0, []
        with self.transaccion() as repo:
            for indice, data in sorted(enumerate(registros), key=orden):
                try:
                    with repo.session.begin_nested():
                        mov = Movimiento.from_dict(data)
                        mov.id = None
                        self._registrar(repo, mov, usuario_id)
                    importados += 1
                except (ValueError, LookupError) as error:
                    fallidos.append({"indice": indice, "error": str(error)})
            if importados:
                repo.registrar_auditoria(usuario_id, "movimientos.importar", f"{importados} importados, {len(fallidos)} rechazados")
        fallidos.sort(key=lambda fallo: fallo["indice"])
        return {
            "importados": importados,
            "rechazados": len(fallidos),
            "fallidos": fallidos,
            "errores": [f"Registro {fallo['indice'] + 1}: {fallo['error']}" for fallo in fallidos[:20]],
        }

    def restaurar(self, registros: Any, usuario_id: Optional[int]) -> dict[str, Any]:
        """Reemplaza todos los movimientos por los de un backup. Crea en el catálogo lo que falte."""
        registros = self._validar_lista(registros)
        validos, errores = [], []
        for numero, data in enumerate(registros, 1):
            try:
                mov = Movimiento.from_dict(data)
                self._validar_basico(mov)
                validos.append((mov.id or 0, numero, mov))
            except ValueError as error:
                errores.append(f"Registro {numero}: {error}")
        if not validos:
            raise ValueError("El backup no contiene registros válidos. " + " ".join(errores[:3]))

        with self.transaccion() as repo:
            borrados = repo.borrar_movimientos()
            for _id, _numero, mov in sorted(validos, key=lambda item: item[:2]):
                producto, presentacion, ubicacion = self._resolver(repo, mov, bloquear=False, crear_faltantes=True)
                repo.agregar(self._nueva_fila(mov, mov.mvto, producto, presentacion, ubicacion, usuario_id, mov.traslado_id))
            repo.registrar_auditoria(
                usuario_id, "movimientos.restaurar",
                f"{borrados} reemplazados por {len(validos)} del backup; {len(errores)} rechazados",
            )
        return {"importados": len(validos), "rechazados": len(errores), "errores": errores[:20]}

    def stock(self) -> list[dict[str, Any]]:
        with self.transaccion() as repo:
            return [
                {"posicion": posicion or SIN_UBICAR, "producto": producto, "presentacion": presentacion,
                 "lote": lote, "cantidad": int(saldo)}
                for posicion, producto, presentacion, lote, saldo in repo.stock()
            ]

    def estadisticas(self) -> dict[str, dict[str, int]]:
        result = {product: {"125 kg": 0, "200 kg": 0, "Otra": 0} for product in ("Aluminio", "Magnesio")}
        with self.transaccion() as repo:
            for producto, presentacion, cantidad in repo.ingresos_por_producto():
                if producto in result:
                    clave = "125 kg" if "125" in presentacion else "200 kg" if "200" in presentacion else "Otra"
                    result[producto][clave] += int(cantidad or 0)
        return result

    def mapa_posiciones(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in self.stock():
            if row["posicion"] == SIN_UBICAR:
                continue
            item = result.setdefault(row["posicion"], {"cantidad": 0, "aluminioTotal": 0, "magnesioTotal": 0, "otroTotal": 0})
            item["cantidad"] += row["cantidad"]
            clave = {"Aluminio": "aluminioTotal", "Magnesio": "magnesioTotal"}.get(row["producto"], "otroTotal")
            item[clave] += row["cantidad"]
        return result

    # --- Catálogos ---------------------------------------------------------

    def catalogos(self) -> dict[str, Any]:
        with self.transaccion() as repo:
            return {
                "productos": [{"nombre": p.nombre, "activo": p.activo} for p in repo.listar_productos()],
                "presentaciones": [
                    {"nombre": p.nombre, "capacidad": p.capacidad_por_ubicacion, "activo": p.activo}
                    for p in repo.listar_presentaciones()
                ],
                "ubicaciones": [u.codigo for u in repo.listar_ubicaciones()],
            }

    @staticmethod
    def _validar_nombre(nombre: Any, maximo: int) -> str:
        limpio = " ".join(str(nombre or "").split())
        if not 1 <= len(limpio) <= maximo:
            raise ValueError(f"El nombre debe tener entre 1 y {maximo} caracteres.")
        return limpio

    def crear_producto(self, nombre: Any, usuario_id: Optional[int]) -> dict[str, Any]:
        nombre = self._validar_nombre(nombre, 60)
        with self.transaccion() as repo:
            if repo.producto_por_nombre(nombre):
                raise ConflictoError(f"El producto '{nombre}' ya existe.")
            repo.agregar(m.Producto(nombre=nombre))
            repo.registrar_auditoria(usuario_id, "catalogo.producto", f"Producto creado: {nombre}")
        return {"nombre": nombre, "activo": True}

    def crear_presentacion(self, nombre: Any, capacidad: Any, usuario_id: Optional[int]) -> dict[str, Any]:
        nombre = self._validar_nombre(nombre, 30)
        try:
            capacidad = int(capacidad) if capacidad not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            raise ValueError("La capacidad debe ser un número entero.") from None
        if capacidad is not None and capacidad <= 0:
            raise ValueError("La capacidad debe ser mayor que cero o quedar vacía (sin límite).")
        with self.transaccion() as repo:
            if repo.presentacion_por_nombre(nombre):
                raise ConflictoError(f"La presentación '{nombre}' ya existe.")
            repo.agregar(m.Presentacion(nombre=nombre, capacidad_por_ubicacion=capacidad))
            repo.registrar_auditoria(usuario_id, "catalogo.presentacion", f"Presentación creada: {nombre} (capacidad {capacidad or 'sin límite'})")
        return {"nombre": nombre, "capacidad": capacidad, "activo": True}

    # --- Auditoría y ajustes -----------------------------------------------

    def auditoria(self, limite: int = 100) -> list[dict[str, Any]]:
        with self.transaccion() as repo:
            return [
                {"fecha": a.creado_en.isoformat(), "usuario": a.usuario.username if a.usuario else "",
                 "accion": a.accion, "detalle": a.detalle}
                for a in repo.listar_auditoria(max(1, min(limite, 500)))
            ]

    def obtener_secret_key_local(self) -> str:
        """Solo para desarrollo: en producción la clave llega por KHEMIK_SECRET_KEY."""
        with self.transaccion() as repo:
            valor = repo.obtener_ajuste("secret_key")
            if not valor:
                valor = secrets.token_hex(32)
                repo.guardar_ajuste("secret_key", valor)
            return valor
