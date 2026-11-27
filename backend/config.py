from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SQLITE_PATH = BASE_DIR / "instance" / "khemik.db"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def cargar_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Construye la configuración a partir de variables de entorno.

    - DATABASE_URL: cadena de conexión. Sin ella se usa SQLite local en instance/khemik.db.
    - KHEMIK_ENV: "production" activa cookies seguras y exige KHEMIK_SECRET_KEY.
    - KHEMIK_SECRET_KEY: clave para firmar las sesiones.
    """
    overrides = overrides or {}
    production = overrides.get("PRODUCTION", _env("KHEMIK_ENV", "development").lower() == "production")
    config: dict[str, Any] = {
        "PRODUCTION": production,
        "DATABASE_URL": _env("DATABASE_URL") or f"sqlite:///{DEFAULT_SQLITE_PATH}",
        "SECRET_KEY": _env("KHEMIK_SECRET_KEY") or None,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": production,
        "SESSION_COOKIE_NAME": "khemik_session",
        "PERMANENT_SESSION_LIFETIME": timedelta(hours=int(_env("KHEMIK_SESSION_HOURS", "8"))),
        "MAX_CONTENT_LENGTH": 5 * 1024 * 1024,
        "LOGIN_MAX_INTENTOS": int(_env("KHEMIK_LOGIN_MAX_INTENTOS", "5")),
        "LOGIN_BLOQUEO_MINUTOS": int(_env("KHEMIK_LOGIN_BLOQUEO_MINUTOS", "15")),
    }
    config.update(overrides)
    if config["PRODUCTION"] and not config["SECRET_KEY"]:
        raise RuntimeError("En producción debes definir la variable de entorno KHEMIK_SECRET_KEY.")
    return config
