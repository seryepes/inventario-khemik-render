from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from werkzeug.security import check_password_hash, generate_password_hash

from . import models as m
from .permisos import (
    NOMBRES_ROLES, PERMISOS, PERMISOS_POR_ROL, PERMISOS_QUE_REQUIEREN_INVENTARIO,
)
from .service import ConflictoError, ServicioBase

_USERNAME = re.compile(r"[a-z0-9._-]{3,40}")
# Se compara contra este hash cuando el usuario no existe, para que la respuesta
# tarde lo mismo y no revele qué usuarios están registrados.
_HASH_FICTICIO = generate_password_hash("khemik-usuario-inexistente")


class CredencialesInvalidas(Exception):
    def __init__(self, mensaje: str, status: int = 401) -> None:
        super().__init__(mensaje)
        self.status = status


class PermisoUsuarioError(Exception):
    pass


def _utc(valor: Optional[datetime]) -> Optional[datetime]:
    # SQLite devuelve fechas sin zona horaria; se interpretan como UTC.
    if valor is not None and valor.tzinfo is None:
        return valor.replace(tzinfo=timezone.utc)
    return valor


def huella(password_hash: str) -> str:
    """Cambia cuando cambia la contraseña: invalida las sesiones abiertas con la anterior."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


class UsuarioService(ServicioBase):
    def __init__(self, session_factory: sessionmaker, max_intentos: int = 5, bloqueo_minutos: int = 15) -> None:
        super().__init__(session_factory)
        self.max_intentos = max_intentos
        self.bloqueo_minutos = bloqueo_minutos

    @staticmethod
    def validar_username(username: Any) -> str:
        limpio = str(username or "").strip().lower()
        if not _USERNAME.fullmatch(limpio):
            raise ValueError("El usuario debe tener entre 3 y 40 caracteres: letras, números, punto, guion o guion bajo.")
        return limpio

    @staticmethod
    def validar_password(password: Any, username: str) -> str:
        clave = str(password or "")
        if not 8 <= len(clave) <= 128:
            raise ValueError("La contraseña debe tener entre 8 y 128 caracteres.")
        if clave.lower() == username.lower():
            raise ValueError("La contraseña no puede ser igual al usuario.")
        return clave

    @staticmethod
    def _normalizar_rol(rol: Any) -> str:
        limpio = str(rol or "").strip().lower()
        return limpio

    def _validar_rol_en_repo(self, repo, rol: Any) -> str:
        limpio = self._normalizar_rol(rol)
        if limpio in m.ROLES or repo.session.scalar(
            select(m.RolPersonalizado.id).where(m.RolPersonalizado.codigo == limpio)
        ):
            return limpio
        raise ValueError("El rol seleccionado no existe.")

    def validar_rol(self, rol: Any) -> str:
        limpio = self._normalizar_rol(rol)
        if limpio in m.ROLES:
            return limpio
        with self.transaccion() as repo:
            return self._validar_rol_en_repo(repo, limpio)

    @staticmethod
    def a_dict(usuario: m.Usuario) -> dict[str, Any]:
        ultimo = _utc(usuario.ultimo_acceso)
        return {
            "id": usuario.id, "username": usuario.username, "role": usuario.rol, "activo": usuario.activo,
            "ultimoAcceso": ultimo.isoformat() if ultimo else None, "huella": huella(usuario.password_hash),
        }

    @staticmethod
    def publico(usuario: dict[str, Any]) -> dict[str, Any]:
        publico = {key: usuario[key] for key in ("username", "role", "activo", "ultimoAcceso")}
        if "roleName" in usuario:
            publico["roleName"] = usuario["roleName"]
        if "permissions" in usuario:
            publico["permissions"] = usuario["permissions"]
        return publico

    def informacion_rol(self, rol: str) -> dict[str, Any]:
        if rol in PERMISOS_POR_ROL:
            return {
                "roleName": NOMBRES_ROLES[rol],
                "permissions": sorted(PERMISOS_POR_ROL[rol]),
            }
        with self.transaccion() as repo:
            personalizado = repo.session.scalar(
                select(m.RolPersonalizado).where(m.RolPersonalizado.codigo == rol)
            )
            if personalizado is None:
                return {"roleName": rol, "permissions": []}
            return {
                "roleName": personalizado.nombre,
                "permissions": json.loads(personalizado.permisos),
            }

    @staticmethod
    def _validar_nombre_rol(nombre: Any) -> str:
        limpio = str(nombre or "").strip()
        if not 3 <= len(limpio) <= 60:
            raise ValueError("El nombre del rol debe tener entre 3 y 60 caracteres.")
        if limpio.casefold() in {nombre.casefold() for nombre in NOMBRES_ROLES.values()}:
            raise ValueError("Ese nombre está reservado para un rol del sistema.")
        return limpio

    @staticmethod
    def _validar_permisos(permisos: Any) -> list[str]:
        if not isinstance(permisos, list) or any(not isinstance(permiso, str) for permiso in permisos):
            raise ValueError("Selecciona una lista válida de permisos.")
        seleccionados = set(permisos)
        desconocidos = seleccionados.difference(PERMISOS)
        if desconocidos:
            raise ValueError("La lista contiene permisos no disponibles.")
        if not seleccionados:
            raise ValueError("Selecciona al menos un permiso para el rol.")
        if PERMISOS_QUE_REQUIEREN_INVENTARIO.intersection(seleccionados) and "ver_inventario" not in seleccionados:
            raise ValueError("Para operar movimientos, lotes, importaciones o restauraciones también se requiere consultar el inventario.")
        return [permiso for permiso in PERMISOS if permiso in seleccionados]

    def listar_roles(self) -> dict[str, Any]:
        with self.transaccion() as repo:
            personalizados = repo.session.scalars(
                select(m.RolPersonalizado).order_by(func.lower(m.RolPersonalizado.nombre))
            )
            roles = [
                {
                    "codigo": codigo,
                    "nombre": NOMBRES_ROLES[codigo],
                    "permisos": sorted(PERMISOS_POR_ROL[codigo]),
                    "sistema": True,
                }
                for codigo in m.ROLES
            ]
            roles.extend({
                "codigo": rol.codigo,
                "nombre": rol.nombre,
                "permisos": json.loads(rol.permisos),
                "sistema": False,
            } for rol in personalizados)
            return {
                "permisos": [{"codigo": codigo, "nombre": nombre} for codigo, nombre in PERMISOS.items()],
                "roles": roles,
            }

    def crear_rol(self, nombre: Any, permisos: Any, actor_id: Optional[int]) -> dict[str, Any]:
        nombre = self._validar_nombre_rol(nombre)
        permisos = self._validar_permisos(permisos)
        with self.transaccion() as repo:
            duplicado = repo.session.scalar(
                select(m.RolPersonalizado.id).where(func.lower(m.RolPersonalizado.nombre) == nombre.casefold())
            )
            if duplicado:
                raise ConflictoError("Ya existe un rol personalizado con ese nombre.")
            rol = repo.agregar(m.RolPersonalizado(
                codigo=f"r_{uuid.uuid4().hex[:16]}",
                nombre=nombre,
                permisos=json.dumps(permisos, ensure_ascii=False),
            ))
            repo.registrar_auditoria(actor_id, "rol.crear", f"{nombre}: {', '.join(permisos)}")
            return {
                "codigo": rol.codigo,
                "nombre": rol.nombre,
                "permisos": permisos,
                "sistema": False,
            }

    def actualizar_rol(
        self, codigo: str, nombre: Any, permisos: Any, actor_id: Optional[int],
    ) -> dict[str, Any]:
        nombre = self._validar_nombre_rol(nombre)
        permisos = self._validar_permisos(permisos)
        with self.transaccion() as repo:
            rol = repo.session.scalar(
                select(m.RolPersonalizado).where(m.RolPersonalizado.codigo == codigo)
            )
            if rol is None:
                raise LookupError("El rol personalizado no existe.")
            duplicado = repo.session.scalar(
                select(m.RolPersonalizado.id).where(
                    func.lower(m.RolPersonalizado.nombre) == nombre.casefold(),
                    m.RolPersonalizado.id != rol.id,
                )
            )
            if duplicado:
                raise ConflictoError("Ya existe un rol personalizado con ese nombre.")
            rol.nombre = nombre
            rol.permisos = json.dumps(permisos, ensure_ascii=False)
            repo.registrar_auditoria(actor_id, "rol.actualizar", f"{nombre}: {', '.join(permisos)}")
            return {"codigo": rol.codigo, "nombre": rol.nombre, "permisos": permisos, "sistema": False}

    def eliminar_rol(self, codigo: str, actor_id: Optional[int]) -> None:
        with self.transaccion() as repo:
            rol = repo.session.scalar(
                select(m.RolPersonalizado).where(m.RolPersonalizado.codigo == codigo)
            )
            if rol is None:
                raise LookupError("El rol personalizado no existe.")
            en_uso = repo.session.scalar(
                select(m.Usuario.id).where(m.Usuario.rol == codigo).limit(1)
            )
            if en_uso is not None:
                raise ConflictoError("No se puede eliminar un rol que está asignado a usuarios.")
            repo.session.delete(rol)
            repo.registrar_auditoria(actor_id, "rol.eliminar", rol.nombre)

    def hay_usuarios(self) -> bool:
        with self.transaccion() as repo:
            return repo.hay_usuarios()

    def crear_admin_inicial(self, username: Any, password: Any) -> Optional[dict[str, Any]]:
        nombre = self.validar_username(username)
        clave = self.validar_password(password, nombre)
        with self.transaccion() as repo:
            repo.bloquear_tabla_usuarios()
            if repo.hay_usuarios():
                return None
            usuario = repo.agregar(m.Usuario(
                username=nombre, password_hash=generate_password_hash(clave), rol="admin", ultimo_acceso=m.ahora(),
            ))
            repo.registrar_auditoria(usuario.id, "usuario.setup", f"Administrador inicial: {nombre}")
            return self.a_dict(usuario)

    def autenticar(self, username: Any, password: Any, ip: str = "") -> dict[str, Any]:
        nombre = str(username or "").strip().lower()
        clave = str(password or "")
        error: Optional[CredencialesInvalidas] = None
        with self.transaccion() as repo:
            usuario = repo.usuario_por_username(nombre) if nombre else None
            if usuario is None:
                check_password_hash(_HASH_FICTICIO, clave)
                raise CredencialesInvalidas("Usuario o contraseña incorrectos.")
            ahora = m.ahora()
            bloqueado_hasta = _utc(usuario.bloqueado_hasta)
            if bloqueado_hasta and bloqueado_hasta > ahora:
                minutos = math.ceil((bloqueado_hasta - ahora).total_seconds() / 60)
                raise CredencialesInvalidas(
                    f"Cuenta bloqueada por intentos fallidos. Intenta de nuevo en {minutos} min.", 429,
                )
            if not check_password_hash(usuario.password_hash, clave):
                # No se lanza aquí para que el contador quede guardado al cerrar la transacción.
                usuario.intentos_fallidos += 1
                error = CredencialesInvalidas("Usuario o contraseña incorrectos.")
                if usuario.intentos_fallidos >= self.max_intentos:
                    usuario.intentos_fallidos = 0
                    usuario.bloqueado_hasta = ahora + timedelta(minutes=self.bloqueo_minutos)
                    repo.registrar_auditoria(usuario.id, "auth.bloqueo", f"Cuenta bloqueada {self.bloqueo_minutos} min. IP {ip}")
                    error = CredencialesInvalidas(
                        f"Demasiados intentos fallidos. La cuenta quedó bloqueada {self.bloqueo_minutos} min.", 429,
                    )
            elif not usuario.activo:
                raise CredencialesInvalidas("La cuenta está desactivada. Contacta al administrador.", 403)
            else:
                usuario.intentos_fallidos, usuario.bloqueado_hasta, usuario.ultimo_acceso = 0, None, ahora
                repo.registrar_auditoria(usuario.id, "auth.login", f"IP {ip}")
                return self.a_dict(usuario)
        raise error

    def obtener_activo(self, usuario_id: Any) -> Optional[dict[str, Any]]:
        try:
            usuario_id = int(usuario_id)
        except (TypeError, ValueError):
            return None
        with self.transaccion() as repo:
            usuario = repo.usuario_por_id(usuario_id)
            return self.a_dict(usuario) if usuario and usuario.activo else None

    def listar(self) -> list[dict[str, Any]]:
        with self.transaccion() as repo:
            nombres = dict(NOMBRES_ROLES)
            nombres.update({
                rol.codigo: rol.nombre
                for rol in repo.session.scalars(select(m.RolPersonalizado))
            })
            return [
                {**self.publico(self.a_dict(usuario)), "roleName": nombres.get(usuario.rol, usuario.rol)}
                for usuario in repo.listar_usuarios()
            ]

    def crear(
        self, username: Any, password: Any, rol: Any, actor_id: Optional[int], actor_rol: str,
    ) -> dict[str, Any]:
        nombre = self.validar_username(username)
        clave = self.validar_password(password, nombre)
        rol = self._normalizar_rol(rol or "operador")
        with self.transaccion() as repo:
            rol = self._validar_rol_en_repo(repo, rol)
            if actor_rol != "admin" and rol not in {"operador", "consulta"}:
                raise PermisoUsuarioError("Solo un administrador puede asignar roles personalizados o privilegiados.")
            if repo.usuario_por_username(nombre):
                raise ConflictoError("Ya existe una cuenta con ese usuario.")
            usuario = repo.agregar(m.Usuario(username=nombre, password_hash=generate_password_hash(clave), rol=rol))
            repo.registrar_auditoria(actor_id, "usuario.crear", f"{nombre} ({rol})")
            return self.publico(self.a_dict(usuario))

    def actualizar(
        self, username: str, cambios: dict[str, Any], actor_id: Optional[int], actor_rol: str,
    ) -> dict[str, Any]:
        with self.transaccion() as repo:
            usuario = repo.usuario_por_username(username)
            if usuario is None:
                raise LookupError("El usuario no existe.")
            if actor_rol != "admin":
                if usuario.rol in {"admin", "coordinador"}:
                    raise PermisoUsuarioError("Solo un administrador puede modificar cuentas privilegiadas.")
                if "role" in cambios:
                    raise PermisoUsuarioError("Solo un administrador puede asignar o cambiar roles.")
            detalle = []
            if "role" in cambios:
                usuario.rol = self._validar_rol_en_repo(repo, cambios["role"])
                detalle.append(f"rol={usuario.rol}")
            if "activo" in cambios:
                usuario.activo = bool(cambios["activo"])
                usuario.intentos_fallidos, usuario.bloqueado_hasta = 0, None
                detalle.append(f"activo={usuario.activo}")
            if cambios.get("password"):
                clave = self.validar_password(cambios["password"], usuario.username)
                usuario.password_hash = generate_password_hash(clave)
                usuario.intentos_fallidos, usuario.bloqueado_hasta = 0, None
                detalle.append("contraseña restablecida")
            repo.session.flush()
            if repo.contar_admins_activos() == 0:
                raise ValueError("Debe quedar al menos un administrador activo.")
            repo.registrar_auditoria(actor_id, "usuario.actualizar", f"{usuario.username}: {', '.join(detalle) or 'sin cambios'}")
            return self.publico(self.a_dict(usuario))

    def importar_existente(self, username: str, password_hash: str, rol: str) -> bool:
        """Usado por la migración desde la base anterior: conserva el hash de la contraseña."""
        nombre = self.validar_username(username)
        with self.transaccion() as repo:
            if repo.usuario_por_username(nombre):
                return False
            repo.agregar(m.Usuario(username=nombre, password_hash=password_hash, rol=self.validar_rol(rol)))
            repo.registrar_auditoria(None, "usuario.migrar", f"{nombre} ({rol})")
            return True
