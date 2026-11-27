from __future__ import annotations

import csv
import io
from typing import Any

from flask import Blueprint, current_app, g, jsonify, request, session
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException

from .seguridad import error, requiere_permiso, requiere_rol, solicitud_sin_csrf
from .service import ConflictoError, InventarioService
from .usuarios import CredencialesInvalidas, PermisoUsuarioError, UsuarioService

bp = Blueprint("api", __name__, url_prefix="/api")

PUBLICOS = {"api.health", "api.auth_status", "api.auth_setup", "api.auth_login"}


def inventario() -> InventarioService:
    return current_app.extensions["khemik"]["inventario"]


def usuarios() -> UsuarioService:
    return current_app.extensions["khemik"]["usuarios"]


def cuerpo_json(permitir_lista: bool = False) -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict) and not (permitir_lista and isinstance(data, list)):
        raise ValueError("El cuerpo de la solicitud debe ser un objeto JSON válido.")
    return data


def usuario_id() -> int:
    return g.usuario["id"]


def usuario_publico(usuario: dict[str, Any]) -> dict[str, Any]:
    return {**UsuarioService.publico(usuario), **usuarios().informacion_rol(usuario["role"])}


def iniciar_sesion(usuario: dict[str, Any]) -> None:
    session.clear()
    session.permanent = True
    session["uid"] = usuario["id"]
    session["huella"] = usuario["huella"]


@bp.before_request
def proteger():
    if solicitud_sin_csrf():
        return error("Solicitud rechazada por protección CSRF.", 403)
    g.usuario = None
    if "uid" in session:
        usuario = usuarios().obtener_activo(session.get("uid"))
        # Si la cuenta se desactivó o cambió la contraseña, la sesión deja de valer.
        if usuario and usuario["huella"] == session.get("huella"):
            usuario.update(usuarios().informacion_rol(usuario["role"]))
            g.usuario = usuario
        else:
            session.clear()
    if request.endpoint in PUBLICOS:
        return None
    if g.usuario is None:
        return error("Debes iniciar sesión para continuar.", 401)
    return None


# --- Errores ---------------------------------------------------------------

@bp.errorhandler(ConflictoError)
def conflicto(exc: ConflictoError):
    return error(str(exc), 409)


@bp.errorhandler(ValueError)
def dato_invalido(exc: ValueError):
    return error(str(exc), 400)


@bp.errorhandler(LookupError)
def no_encontrado(exc: LookupError):
    return error(str(exc), 404)


@bp.errorhandler(CredencialesInvalidas)
def credenciales(exc: CredencialesInvalidas):
    return error(str(exc), exc.status)


@bp.errorhandler(PermisoUsuarioError)
def permiso_usuario(exc: PermisoUsuarioError):
    return error(str(exc), 403)


@bp.errorhandler(IntegrityError)
def integridad(_exc: IntegrityError):
    return error("La operación entra en conflicto con datos existentes. Recarga e intenta de nuevo.", 409)


@bp.errorhandler(HTTPException)
def http(exc: HTTPException):
    return error(exc.description or exc.name, exc.code or 500)


@bp.errorhandler(Exception)
def inesperado(exc: Exception):
    current_app.logger.exception("Error no controlado en %s", request.path)
    return error("Error interno del servidor.", 500)


# --- Salud y autenticación -------------------------------------------------

@bp.get("/health")
def health():
    inventario().verificar_conexion()
    return jsonify({"ok": True, "service": "inventario-khemik"})


@bp.get("/auth/status")
def auth_status():
    usuario = usuario_publico(g.usuario) if g.usuario else None
    return jsonify({"setupRequired": not usuarios().hay_usuarios(), "user": usuario})


@bp.post("/auth/setup")
def auth_setup():
    data = cuerpo_json()
    usuario = usuarios().crear_admin_inicial(data.get("username"), data.get("password"))
    if usuario is None:
        return error("El administrador inicial ya fue creado.", 409)
    iniciar_sesion(usuario)
    return jsonify({"user": usuario_publico(usuario)}), 201


@bp.post("/auth/login")
def auth_login():
    data = cuerpo_json()
    usuario = usuarios().autenticar(data.get("username"), data.get("password"), request.remote_addr or "")
    iniciar_sesion(usuario)
    return jsonify({"user": usuario_publico(usuario)})


@bp.post("/auth/logout")
def auth_logout():
    session.clear()
    return jsonify({"ok": True})


@bp.get("/auth/users")
@requiere_permiso("gestionar_usuarios")
def auth_users():
    return jsonify(usuarios().listar())


@bp.post("/auth/users")
@requiere_permiso("gestionar_usuarios")
def auth_create_user():
    data = cuerpo_json()
    usuario = usuarios().crear(
        data.get("username"), data.get("password"), data.get("role"), usuario_id(), g.usuario["role"],
    )
    return jsonify(usuario), 201


@bp.patch("/auth/users/<username>")
@requiere_permiso("gestionar_usuarios")
def auth_update_user(username: str):
    return jsonify(usuarios().actualizar(username, cuerpo_json(), usuario_id(), g.usuario["role"]))


@bp.get("/auth/roles")
@requiere_rol("admin")
def auth_roles():
    return jsonify(usuarios().listar_roles())


@bp.post("/auth/roles")
@requiere_rol("admin")
def auth_create_role():
    data = cuerpo_json()
    return jsonify(usuarios().crear_rol(data.get("nombre"), data.get("permisos"), usuario_id())), 201


@bp.patch("/auth/roles/<codigo>")
@requiere_rol("admin")
def auth_update_role(codigo: str):
    data = cuerpo_json()
    return jsonify(usuarios().actualizar_rol(codigo, data.get("nombre"), data.get("permisos"), usuario_id()))


@bp.delete("/auth/roles/<codigo>")
@requiere_rol("admin")
def auth_delete_role(codigo: str):
    usuarios().eliminar_rol(codigo, usuario_id())
    return jsonify({"ok": True})


# --- Catálogos y auditoría -------------------------------------------------

@bp.get("/catalogos")
@requiere_permiso("ver_inventario", "gestionar_catalogos")
def catalogos():
    return jsonify(inventario().catalogos())


@bp.post("/catalogos/productos")
@requiere_permiso("gestionar_catalogos")
def crear_producto():
    data = cuerpo_json()
    return jsonify(inventario().crear_producto(data.get("nombre"), data.get("categoria"), usuario_id())), 201


@bp.patch("/catalogos/productos/<int:producto_id>")
@requiere_permiso("gestionar_catalogos")
def actualizar_producto(producto_id: int):
    return jsonify(inventario().actualizar_producto(producto_id, cuerpo_json(), usuario_id()))


@bp.delete("/catalogos/productos/<int:producto_id>")
@requiere_permiso("gestionar_catalogos")
def eliminar_producto(producto_id: int):
    return jsonify(inventario().eliminar_producto(producto_id, usuario_id()))


@bp.post("/catalogos/presentaciones")
@requiere_permiso("gestionar_catalogos")
def crear_presentacion():
    data = cuerpo_json()
    return jsonify(inventario().crear_presentacion(data.get("nombre"), usuario_id())), 201


@bp.get("/auditoria")
@requiere_permiso("ver_auditoria")
def auditoria():
    return jsonify(inventario().auditoria(request.args.get("limite", 100, type=int)))


@bp.get("/auditoria/exportar")
@requiere_permiso("ver_auditoria")
def exportar_auditoria():
    registros = inventario().auditoria(500)
    salida = io.StringIO()
    salida.write("\ufeff")
    escritor = csv.writer(salida)
    escritor.writerow(["Fecha", "Usuario", "Acción", "Detalle"])
    for registro in registros:
        escritor.writerow([
            registro["fecha"],
            registro["usuario"] or "Sistema",
            registro["accion"],
            registro["detalle"],
        ])
    return (
        salida.getvalue(),
        200,
        {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": "attachment; filename=auditoria_khemik.csv",
        },
    )


# --- Inventario ------------------------------------------------------------

@bp.get("/movimientos")
@requiere_permiso("ver_inventario")
def movimientos():
    return jsonify(inventario().listar())


@bp.post("/movimientos")
@requiere_permiso("gestionar_movimientos")
def crear_movimiento():
    data = cuerpo_json()
    data.pop("id", None)
    return jsonify(inventario().guardar_movimiento(data, usuario_id())), 201


@bp.put("/movimientos/<int:id_>")
@requiere_permiso("gestionar_movimientos")
def actualizar_movimiento(id_: int):
    data = cuerpo_json()
    data["id"] = id_
    return jsonify(inventario().guardar_movimiento(data, usuario_id()))


@bp.post("/traslados")
@requiere_permiso("gestionar_movimientos")
def crear_traslado():
    return jsonify(inventario().guardar_traslado(cuerpo_json(), usuario_id())), 201


@bp.delete("/movimientos/<int:id_>")
@requiere_permiso("gestionar_movimientos")
def eliminar_movimiento(id_: int):
    inventario().eliminar(id_, usuario_id())
    return jsonify({"ok": True})


@bp.delete("/movimientos")
@requiere_rol("admin")
def borrar_movimientos():
    return jsonify({"ok": True, "eliminados": inventario().borrar_todo(usuario_id())})


@bp.get("/stock")
@requiere_permiso("ver_inventario")
def stock():
    return jsonify(inventario().stock())


@bp.get("/estadisticas")
@requiere_permiso("ver_inventario")
def estadisticas():
    return jsonify(inventario().estadisticas())


@bp.get("/posiciones")
@requiere_permiso("ver_inventario")
def posiciones():
    return jsonify(inventario().mapa_posiciones())


@bp.patch("/posiciones/<path:codigo>/peligro")
@requiere_permiso("gestionar_lotes")
def actualizar_peligro_posicion(codigo: str):
    data = cuerpo_json()
    return jsonify(inventario().actualizar_peligro_posicion(
        codigo, data.get("peligrosa"), data.get("titulo"), usuario_id(),
    ))


@bp.get("/lotes/estados")
@requiere_permiso("ver_inventario")
def estados_lotes():
    return jsonify(inventario().estados_lotes())


@bp.patch("/lotes/estado")
@requiere_permiso("gestionar_lotes")
def actualizar_estado_lote():
    data = cuerpo_json()
    return jsonify(inventario().actualizar_estado_lote(
        data.get("producto"), data.get("lote"), data.get("estado"), usuario_id(),
    ))


@bp.post("/importar")
@requiere_permiso("importar_excel")
def importar():
    data = cuerpo_json(permitir_lista=True)
    registros = data.get("registros") if isinstance(data, dict) else data
    return jsonify(inventario().importar(registros, usuario_id()))


@bp.post("/restaurar")
@requiere_permiso("restaurar_backup")
def restaurar():
    data = cuerpo_json(permitir_lista=True)
    registros = data.get("registros") if isinstance(data, dict) else data
    return jsonify({"ok": True, **inventario().restaurar(registros, usuario_id())})
