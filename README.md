# Inventario Kemik en Python

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
python -m unittest backend.test_service
python -m backend.app
```

Abre `http://127.0.0.1:5000` en el navegador. La base de datos se crea automaticamente dentro de `repository`. Si existe la base anterior `inventario.db` en la raiz, se mueve a la nueva ubicacion en el primer inicio, conservando sus registros.

Si PowerShell bloquea la activacion del entorno, ejecuta una vez:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Para detener el servidor usa `Ctrl+C`. Para hacer una copia de seguridad se puede usar el boton `Backup JSON` de la interfaz. No borres `repository/inventario.db`: es la base de datos del inventario.

## API principal

- `GET /api/health`
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
