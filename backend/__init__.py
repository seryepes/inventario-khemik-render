from __future__ import annotations

import mimetypes
from typing import Any

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException, NotFound

from .api import bp as api_bp
from .config import BASE_DIR, cargar_config
from .database import inicializar_base
from .seguridad import registrar_encabezados
from .service import InventarioService
from .usuarios import UsuarioService

FRONTEND_DIR = BASE_DIR / "frontend"

# En algunos Windows el registro asocia .js a text/plain y el navegador rechaza los módulos.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")


def create_app(overrides: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config.update(cargar_config(overrides))

    session_factory = inicializar_base(app.config["DATABASE_URL"])
    inventario = InventarioService(session_factory)
    app.extensions["khemik"] = {
        "inventario": inventario,
        "usuarios": UsuarioService(session_factory, app.config["LOGIN_MAX_INTENTOS"], app.config["LOGIN_BLOQUEO_MINUTOS"]),
    }
    if not app.config["SECRET_KEY"]:
        app.config["SECRET_KEY"] = inventario.obtener_secret_key_local()

    app.register_blueprint(api_bp)
    registrar_encabezados(app)
    registrar_frontend(app)
    return app


def registrar_frontend(app: Flask) -> None:
    # Solo se publica la carpeta frontend/: el código y la base de datos nunca son accesibles por URL.
    @app.get("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/<path:ruta>")
    def frontend(ruta: str):
        if ruta.startswith("api/"):
            raise NotFound()
        return send_from_directory(FRONTEND_DIR, ruta)

    @app.errorhandler(HTTPException)
    def error_http(exc: HTTPException):
        if request.path.startswith("/api/"):
            return jsonify({"error": exc.description or exc.name}), exc.code
        return exc
