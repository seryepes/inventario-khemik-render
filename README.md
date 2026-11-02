# Khemik | Inventario en Python

Backend local para el sistema de inventario. Usa Flask para la API HTTP y SQLite para guardar los movimientos en `repository/inventario.db`. La carpeta `repository` contiene el acceso a datos y la base de datos local.

## Requisitos

- Windows 10/11
- Python 3.11 o superior

## Instalacion y uso

Abre PowerShell en esta carpeta y ejecuta:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest backend.test_auth backend.test_service
python app.py
```

Abre `http://127.0.0.1:5000` en el navegador. La base de datos se crea automaticamente dentro de `repository`. Si existe la base anterior `inventario.db` en la raiz, se mueve a la nueva ubicacion en el primer inicio, conservando sus registros.

El mapa incluye las posiciones **PISO PLANTA1** y **PISO PLANTA2**. Una posición no admite ingresos de un producto diferente mientras tenga existencias; la regla también se aplica a traslados e importaciones. Cada registro nuevo conserva automáticamente la fecha y hora de creación, visible en la tabla y en las exportaciones. Los registros anteriores a esta mejora no tienen una hora histórica disponible y se muestran como **No disponible**.

## Acceso y usuarios

En el primer inicio, Khemik solicita crear la cuenta del administrador. No hay una contraseña predeterminada: define el usuario y una contraseña de al menos 8 caracteres en esa pantalla. Después, el administrador puede abrir **Usuarios** para crear cuentas y asignarles contraseñas. Los usuarios pueden entrar al inventario, pero solo el administrador puede crear cuentas.

Las contraseñas se guardan como hashes en SQLite, no en texto legible. La sesión se firma con una clave guardada en la base local; también puedes definir `KHEMIK_SECRET_KEY` en el entorno antes de iniciar el servidor para proporcionar una clave propia.

Si PowerShell bloquea la activacion del entorno, ejecuta una vez:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Para detener el servidor usa `Ctrl+C`. Para hacer una copia de seguridad se puede usar el boton `Backup JSON` de la interfaz. No borres `repository/inventario.db`: es la base de datos del inventario.

## API principal

- `GET /api/health`
- `GET /api/auth/status`
- `POST /api/auth/setup` (crear el primer administrador)
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/users` (administrador)
- `POST /api/auth/users` (administrador)
- `GET /api/movimientos`
- `POST /api/movimientos`
- `PUT /api/movimientos/<id>`
- `POST /api/traslados`
- `DELETE /api/movimientos/<id>`
- `DELETE /api/movimientos`
- `GET /api/stock`
- `GET /api/estadisticas`
- `GET /api/posiciones`
- `POST /api/importar`
- `POST /api/restaurar`
