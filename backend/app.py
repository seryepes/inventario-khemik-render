from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, request, session, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash

from .service import InventarioService

ROOT = Path(__file__).resolve().parent.parent
app = Flask(__name__, static_folder=None)
service = InventarioService()
app.config.update(
    SECRET_KEY=os.environ.get("KHEMIK_SECRET_KEY") or service.repository.get_or_create_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

PUBLIC_API_ENDPOINTS = {
    "health", "auth_status", "auth_setup", "auth_login",
}


@app.before_request
def require_authentication():
    if not request.path.startswith("/api/") or request.endpoint in PUBLIC_API_ENDPOINTS:
        return None
    if "username" not in session:
        return jsonify({"error": "Debes iniciar sesión para continuar."}), 401
    if request.endpoint in {"auth_users", "auth_create_user"} and session.get("role") != "admin":
        return jsonify({"error": "Se requiere una cuenta de administrador."}), 403
    return None


def error_response(error: Exception, status: int = 400):
    return jsonify({"error": str(error)}), status


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "inventario-kemik"})


def validar_credenciales(username: object, password: object) -> tuple[str, str]:
    clean_username = str(username or "").strip()
    clean_password = str(password or "")
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,40}", clean_username):
        raise ValueError("El usuario debe tener entre 3 y 40 caracteres: letras, números, punto, guion o guion bajo.")
    if len(clean_password) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres.")
    return clean_username, clean_password


@app.get("/api/auth/status")
def auth_status():
    users = service.repository.listar_usuarios()
    current_user = None
    if "username" in session:
        current_user = {"username": session["username"], "role": session["role"]}
    return jsonify({"setupRequired": not users, "user": current_user})


@app.post("/api/auth/setup")
def auth_setup():
    data = request.get_json(silent=True) or {}
    try:
        username, password = validar_credenciales(data.get("username"), data.get("password"))
        created = service.repository.crear_administrador_inicial(username, generate_password_hash(password))
        if not created:
            return error_response(ValueError("El administrador inicial ya fue creado."), 409)
    except ValueError as error:
        return error_response(error)
    session.clear()
    session["username"] = username
    session["role"] = "admin"
    return jsonify({"user": {"username": username, "role": "admin"}}), 201


@app.post("/api/auth/login")
def auth_login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "")
    user = service.repository.obtener_usuario(username)
    if not user or not check_password_hash(user["password_hash"], password):
        return error_response(ValueError("Usuario o contraseña incorrectos."), 401)
    session.clear()
    session["username"] = user["username"]
    session["role"] = user["role"]
    return jsonify({"user": {"username": user["username"], "role": user["role"]}})


@app.post("/api/auth/logout")
def auth_logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/auth/users")
def auth_users():
    return jsonify(service.repository.listar_usuarios())


@app.post("/api/auth/users")
def auth_create_user():
    data = request.get_json(silent=True) or {}
    try:
        username, password = validar_credenciales(data.get("username"), data.get("password"))
        service.repository.crear_usuario(username, generate_password_hash(password))
    except ValueError as error:
        return error_response(error)
    except sqlite3.IntegrityError:
        return error_response(ValueError("Ya existe una cuenta con ese usuario."), 409)
    return jsonify({"username": username, "role": "user"}), 201


@app.get("/api/movimientos")
def movimientos():
    return jsonify([item.to_dict() for item in service.listar()])


@app.post("/api/movimientos")
def crear_movimiento():
    try:
        return jsonify(service.guardar_movimiento(request.get_json(force=True)).to_dict()), 201
    except ValueError as error:
        return error_response(error)


@app.put("/api/movimientos/<int:id_>")
def actualizar_movimiento(id_: int):
    try:
        data = request.get_json(force=True)
        data["id"] = id_
        return jsonify(service.guardar_movimiento(data))
    except ValueError as error:
        return error_response(error)


@app.post("/api/traslados")
def crear_traslado():
    try:
        return jsonify([item.to_dict() for item in service.guardar_traslado(request.get_json(force=True))]), 201
    except ValueError as error:
        return error_response(error)


@app.delete("/api/movimientos/<int:id_>")
def eliminar_movimiento(id_: int):
    service.eliminar(id_)
    return jsonify({"ok": True})


@app.delete("/api/movimientos")
def borrar_movimientos():
    service.borrar_todo()
    return jsonify({"ok": True})


@app.get("/api/stock")
def stock():
    return jsonify(service.stock())


@app.get("/api/estadisticas")
def estadisticas():
    return jsonify(service.estadisticas())


@app.get("/api/posiciones")
def posiciones():
    return jsonify(service.mapa_posiciones())


@app.post("/api/importar")
def importar():
    try:
        return jsonify(service.importar(request.get_json(force=True).get("registros", [])))
    except ValueError as error:
        return error_response(error)


@app.post("/api/restaurar")
def restaurar():
    try:
        payload = request.get_json(force=True)
        registros = payload if isinstance(payload, list) else payload.get("registros", [])
        service.restaurar(registros)
        return jsonify({"ok": True, "importados": len(registros)})
    except (ValueError, TypeError, KeyError) as error:
        return error_response(error)


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def frontend(path: str):
    view_dir = ROOT / "vista y stilo"
    if path:
        candidates = [ROOT / path, view_dir / path]
        for candidate in candidates:
            if candidate.is_file():
                return send_from_directory(str(candidate.parent), candidate.name)
        if "." in Path(path).name:
            return error_response(ValueError(f"No se encontró el archivo solicitado: {path}"), 404)
    return send_from_directory(str(view_dir), "index.html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
