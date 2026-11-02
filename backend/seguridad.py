from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import Flask, g, jsonify, request

CSRF_HEADER = "X-Khemik-Request"
METODOS_SEGUROS = {"GET", "HEAD", "OPTIONS"}
ESCRITURA = ("admin", "operador")

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://cdn.jsdelivr.net https://cdn.sheetjs.com",
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com",
    "font-src 'self' https://cdnjs.cloudflare.com data:",
    "img-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


def error(mensaje: str, status: int):
    return jsonify({"error": mensaje}), status


def solicitud_sin_csrf() -> bool:
    """Las peticiones que modifican datos deben traer el encabezado propio de la app.

    Un sitio externo no puede agregar encabezados personalizados a una petición
    hacia otro dominio sin que el navegador la bloquee (CORS), así que esto
    impide que otra página use la sesión de un usuario para escribir datos.
    """
    return request.method not in METODOS_SEGUROS and request.headers.get(CSRF_HEADER) != "1"


def requiere_rol(*roles: str) -> Callable:
    def decorador(vista: Callable) -> Callable:
        @wraps(vista)
        def envoltura(*args, **kwargs):
            if g.usuario is None or g.usuario["role"] not in roles:
                return error("No tienes permisos para realizar esta acción.", 403)
            return vista(*args, **kwargs)
        return envoltura
    return decorador


def registrar_encabezados(app: Flask) -> None:
    if app.config["PRODUCTION"]:
        # Render/Railway terminan HTTPS en un proxy: así Flask ve la IP y el esquema reales.
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    @app.after_request
    def encabezados(respuesta):
        respuesta.headers.setdefault("Content-Security-Policy", CSP)
        respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
        respuesta.headers.setdefault("X-Frame-Options", "DENY")
        respuesta.headers.setdefault("Referrer-Policy", "same-origin")
        respuesta.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if app.config["PRODUCTION"]:
            respuesta.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        # La API nunca se guarda en caché; el frontend se revalida para recibir actualizaciones.
        respuesta.headers["Cache-Control"] = "no-store" if request.path.startswith("/api/") else "no-cache"
        return respuesta
