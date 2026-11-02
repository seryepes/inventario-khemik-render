from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app, g, jsonify, request, session
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException

from .seguridad import ESCRITURA, error, requiere_rol, solicitud_sin_csrf
from .service import ConflictoError, InventarioService
from .usuarios import CredencialesInvalidas, UsuarioService

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
    usuario = UsuarioService.publico(g.usuario) if g.usuario else None
    return jsonify({"setupRequired": not usuarios().hay_usuarios(), "user": usuario})


@bp.post("/auth/setup")
def auth_setup():
    data = cuerpo_json()
    usuario = usuarios().crear_admin_inicial(data.get("username"), data.get("password"))
    if usuario is None:
        return error("El administrador inicial ya fue creado.", 409)
    iniciar_sesion(usuario)
    return jsonify({"user": UsuarioService.publico(usuario)}), 201


@bp.post("/auth/login")
def auth_login():
    data = cuerpo_json()
    usuario = usuarios().autenticar(data.get("username"), data.get("password"), request.remote_addr or "")
    iniciar_sesion(usuario)
    return jsonify({"user": UsuarioService.publico(usuario)})


@bp.post("/auth/logout")
def auth_logout():
    session.clear()
    return jsonify({"ok": True})


@bp.get("/auth/users")
@requiere_rol("admin")
def auth_users():
    return jsonify(usuarios().listar())


@bp.post("/auth/users")
@requiere_rol("admin")
def auth_create_user():
    data = cuerpo_json()
    usuario = usuarios().crear(data.get("username"), data.get("password"), data.get("role"), usuario_id())
    return jsonify(usuario), 201


@bp.patch("/auth/users/<username>")
@requiere_rol("admin")
def auth_update_user(username: str):
    return jsonify(usuarios().actualizar(username, cuerpo_json(), usuario_id()))


# --- Catálogos y auditoría -------------------------------------------------

@bp.get("/catalogos")
def catalogos():
    return jsonify(inventario().catalogos())


@bp.post("/catalogos/productos")
@requiere_rol("admin")
def crear_producto():
    return jsonify(inventario().crear_producto(cuerpo_json().get("nombre"), usuario_id())), 201


@bp.post("/catalogos/presentaciones")
@requiere_rol("admin")
def crear_presentacion():
    data = cuerpo_json()
    return jsonify(inventario().crear_presentacion(data.get("nombre"), data.get("capacidad"), usuario_id())), 201


@bp.get("/auditoria")
@requiere_rol("admin")
def auditoria():
    return jsonify(inventario().auditoria(request.args.get("limite", 100, type=int)))


# --- Inventario ------------------------------------------------------------

@bp.get("/movimientos")
def movimientos():
    return jsonify(inventario().listar())


@bp.post("/movimientos")
@requiere_rol(*ESCRITURA)
def crear_movimiento():
    data = cuerpo_json()
    data.pop("id", None)
    return jsonify(inventario().guardar_movimiento(data, usuario_id())), 201


@bp.put("/movimientos/<int:id_>")
@requiere_rol(*ESCRITURA)
def actualizar_movimiento(id_: int):
    data = cuerpo_json()
    data["id"] = id_
    return jsonify(inventario().guardar_movimiento(data, usuario_id()))


@bp.post("/traslados")
@requiere_rol(*ESCRITURA)
def crear_traslado():
    return jsonify(inventario().guardar_traslado(cuerpo_json(), usuario_id())), 201


@bp.delete("/movimientos/<int:id_>")
@requiere_rol(*ESCRITURA)
def eliminar_movimiento(id_: int):
    inventario().eliminar(id_, usuario_id())
    return jsonify({"ok": True})


@bp.delete("/movimientos")
@requiere_rol("admin")
def borrar_movimientos():
    return jsonify({"ok": True, "eliminados": inventario().borrar_todo(usuario_id())})


@bp.get("/stock")
def stock():
    return jsonify(inventario().stock())


@bp.get("/estadisticas")
def estadisticas():
    return jsonify(inventario().estadisticas())


@bp.get("/posiciones")
def posiciones():
    return jsonify(inventario().mapa_posiciones())


@bp.post("/importar")
@requiere_rol("admin")
def importar():
    data = cuerpo_json(permitir_lista=True)
    registros = data.get("registros") if isinstance(data, dict) else data
    return jsonify(inventario().importar(registros, usuario_id()))


@bp.post("/restaurar")
@requiere_rol("admin")
def restaurar():
    data = cuerpo_json(permitir_lista=True)
    registros = data.get("registros") if isinstance(data, dict) else data
    return jsonify({"ok": True, **inventario().restaurar(registros, usuario_id())})
