# Khemik | Control de inventario

Sistema web para controlar el inventario de bodega (aluminio y magnesio en presentaciones de 125 kg y 200 kg) por posición, lote y movimiento. Backend en Flask + SQLAlchemy; usa **SQLite en local** y **PostgreSQL (Neon) en producción**, sin cambiar código.

## Estructura

```
app.py                     Punto de entrada (python app.py / gunicorn app:app)
backend/
  __init__.py              create_app(): arma la aplicación
  config.py                Configuración desde variables de entorno
  database.py              Conexión (SQLite o PostgreSQL) y creación de tablas
  models.py                Modelo de datos (tablas)
  seed.py                  Catálogos iniciales: productos, presentaciones, 266 posiciones
  domain.py                Movimiento (formato de la API) y normalización de datos
  repository.py            Consultas a la base
  service.py               Reglas de negocio de inventario
  usuarios.py              Cuentas, roles, contraseñas y bloqueo por intentos
  api.py                   Endpoints REST (/api/...)
  seguridad.py             Permisos por rol, CSRF y encabezados de seguridad
frontend/                  Única carpeta publicada por URL
  index.html, css/, js/
scripts/
  migrar_base_anterior.py  Copia los datos de la versión anterior al nuevo modelo
tests/                     Pruebas automáticas
render.yaml                Despliegue en Render
```

## Modelo de datos

```
productos ──┐        presentaciones ──┐        ubicaciones ──┐
            │ 1..n                    │ 1..n                 │ 0..n
            └──────────► movimientos ◄┴──────────────────────┘
                             │  creado_por / actualizado_por
usuarios ◄───────────────────┘
   ▲
auditoria (quién hizo qué y cuándo)          ajustes (clave/valor)
```

| Tabla | Para qué |
|---|---|
| `productos` | Catálogo de productos (Aluminio, Magnesio, Otro…). |
| `presentaciones` | Catálogo de presentaciones (125 kg, 200 kg, Otra…). |
| `ubicaciones` | Posiciones de la bodega: 44 filas × columnas A–F (`12C`) y dos posiciones de piso. |
| `estados_lote` | Estado de cada lote de producto, fecha de primer ingreso y cambios manuales. |
| `movimientos` | Libro de ingresos y salidas. El stock **se calcula** sumando ingresos y restando salidas. |
| `usuarios` | Cuentas con rol, estado activo, intentos fallidos y último acceso. |
| `auditoria` | Registro de cada operación: crear, editar, eliminar, importar, restaurar, logins y bloqueos. |

Reglas que aplica el sistema:

- Cada posición admite cualquier cantidad de unidades y puede contener varios productos, presentaciones y lotes. La disponibilidad de stock sigue validándose al registrar salidas y traslados.
- El administrador puede editar nombre y categoría de los productos. Al borrar un producto se desactiva para nuevos movimientos, conservando el historial y permitiendo reactivarlo.
- Ningún lote puede quedar con saldo negativo, ni al registrar una salida ni al editar o eliminar un movimiento.
- Un lote que salió de la bodega no puede volver a ingresar (los traslados internos no cuentan como salida).
- Los lotes ingresan en cuarentena y pasan automáticamente a aprobado al cumplir 10 días; administradores y operadores pueden establecer manualmente cualquiera de los dos estados mientras el lote tenga existencias.
- Un traslado son dos movimientos enlazados: no se editan, se eliminan juntos.
- Producto, presentación y posición deben existir en el catálogo. Las posiciones se normalizan: `c12`, `C12` y `12-c` se guardan como `12C`.
- Las posiciones peligrosas se resaltan en rojo con un título de advertencia; administradores y operadores pueden activar o quitar esa alerta desde el detalle de la posición.

## Roles

| Rol | Puede |
|---|---|
| `admin` | Todos los permisos, incluido asignar roles privilegiados y borrar todos los movimientos. |
| `coordinador` | Acceso completo a inventario, catálogos, importaciones, restauración, auditoría y gestión limitada de usuarios. No puede borrar todos los movimientos, asignar roles de administrador/coordinador ni modificar cuentas privilegiadas. Solo un administrador puede asignarle este rol. |
| `operador` | Ver, registrar, editar y eliminar movimientos y traslados; cambiar estados de lotes y marcar posiciones peligrosas. |
| `consulta` | Solo ver. |

Desde **Administración**, el administrador puede crear roles personalizados, elegir sus permisos y asignarlos a usuarios nuevos o existentes. Los permisos disponibles cubren consulta del inventario, movimientos, lotes y posiciones, catálogos, importación, restauración, auditoría y gestión limitada de usuarios. `Borrar Todo` no se puede asignar a roles personalizados; queda reservado al administrador. No se puede eliminar un rol personalizado mientras esté asignado.

Las bases de datos existentes se actualizan automáticamente al iniciar la nueva versión para admitir roles personalizados.

## Uso local (Windows)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -t .
python app.py
```

Abre `http://127.0.0.1:5000`. En el primer inicio se crea la cuenta de administrador. Los datos locales quedan en `instance/khemik.db`.

**Si vienes de la versión anterior**, copia tus datos con:

```powershell
python -m scripts.migrar_base_anterior
```

## Despliegue gratuito: Render + Neon

1. **Base de datos (Neon).** Crea una cuenta en <https://neon.tech>, crea un proyecto (región cercana, por ejemplo `us-east`) y copia la *connection string* (`postgresql://...?sslmode=require`).
2. **Aplicación (Render).** En <https://render.com>, ve a **New → Blueprint**, conecta este repositorio de GitHub y pega la cadena de Neon en `DATABASE_URL` cuando te la pida. `render.yaml` define el resto: genera la `KHEMIK_SECRET_KEY` y activa el modo producción.
3. Al primer arranque las tablas y los catálogos se crean solos. Abre la URL de Render y crea el administrador.
4. Para subir datos que ya tengas en local, define `DATABASE_URL` con la cadena de Neon y ejecuta `python -m scripts.migrar_base_anterior`.

En el plan gratuito, Render apaga la app tras unos 15 minutos sin uso: la primera visita después tarda entre 30 y 60 segundos. Los datos no se pierden porque viven en Neon.

Variables de entorno disponibles: ver [.env.example](.env.example).

El mapa incluye **PISO PLANTA1** y **PISO PLANTA2**. Las materias primas usan un color común en el mapa; una posición peligrosa aparece en rojo con el título de la advertencia. Cada movimiento conserva su fecha y hora de creación, que se muestra en la tabla y queda disponible en los datos de la API. Como la versión anterior no guardaba la hora de registro, al migrar esos movimientos se les asigna la hora de migración, no una hora histórica.

## API principal

`GET /api/health` · `GET /api/auth/status` · `POST /api/auth/setup` · `POST /api/auth/login` · `POST /api/auth/logout` · `GET|POST /api/auth/users` · `PATCH /api/auth/users/<usuario>` · `GET /api/catalogos` · `POST /api/catalogos/productos` · `POST /api/catalogos/presentaciones` · `GET /api/auditoria` · `GET|POST|DELETE /api/movimientos` · `PUT|DELETE /api/movimientos/<id>` · `POST /api/traslados` · `GET /api/stock` · `GET /api/estadisticas` · `GET /api/posiciones` · `PATCH /api/posiciones/<codigo>/peligro` · `GET /api/lotes/estados` · `PATCH /api/lotes/estado` · `POST /api/importar` · `POST /api/restaurar`

Toda petición que modifica datos debe incluir el encabezado `X-Khemik-Request: 1` (protección CSRF); el frontend lo envía automáticamente.
