# DDN Travel — Versión Python (Flask)

Conversión a Python de la app generada originalmente en Google AI Studio
(React + TypeScript) para el proyecto académico **"Aplicación Inteligente
para la Gestión de Agencia de Viajes Turísticos"**.

Se buscó reproducir la app original lo más fielmente posible: mismo diseño
visual (tema oscuro "Deep Space" + tema claro), misma navegación, mismos
datos de demostración, mismas reglas de negocio (RN-01 a RN-05) y las
mismas 3 funciones de Inteligencia Artificial con Gemini (estadísticas
predictivas, recomendador inteligente y generador de itinerarios), ahora
usando **Python** en el backend en vez de TypeScript/Node.

## Arquitectura y estructura de la app

```
run.py                  # Punto de entrada: crea la app Flask y la inicia en el puerto 3000

app/
  __init__.py           # Fábrica create_app(): configura Flask, filtros Jinja2,
                        # extensión SQLAlchemy, Migrate (render_as_batch), CSRF,
                        # rate limiting y registra los comandos de la CLI
  config.py             # Config / DevelopmentConfig / ProductionConfig; todo se
                        # lee de variables de entorno (python-dotenv)
  extensions.py         # Instancias compartidas: db, migrate, csrf, limiter
  models/               # Modelos SQLAlchemy (uno por agregado): Client, Booking,
                        # Package, Hotel, RoomType, Flight, Transport, Activity,
                        # Payment, Promotion, AuditLog, TravelDocument, Notification,
                        # Itinerary, NcfSequence, Setting, User
                        # - BaseEntity aporta to_dict(), describe() y publicado()
                        # - Sin ñoñería de IDs: PK enteras autoincrementales
  repositories/         # Acceso a datos por agregado (create/update/delete/list).
                        # Toda mutación escribe auditoría (RN-05) en la misma
                        # transacción y devuelve entidades con los nombres de
                        # atributo que usan las plantillas.
  store.py               # Fachada DataStore: conserva las firmas que usan las
                        # rutas (create_booking, register_payment, add_client...)
                        # sobre los repositorios. El commit/rollback se
                        # centraliza aquí (_commit/_rollback), una sesión por
                        # petición.
  audit.py              # registro de auditoría con before/after, metadatos de
                        # petición (IP, user agent) y helpers de login/logout
  backup.py             # Respaldo y restauración: SQLite con
                        # sqlite3.Connection.backup(), PostgreSQL con pg_dump
  cli.py                # Comandos ``flask seed`` y ``flask backup``
  ai_service.py          # Gemini (google-genai) con fallback de datos simulados
                        # si no hay GEMINI_API_KEY. 3 funciones:
                        #   get_predictive_analytics(), get_recommendations(),
                        #   get_itinerary()
  routes.py              # Todas las rutas Flask (auth, bookings, AI, billing,
                        # documents, audit, OAuth). Define blueprint "main".
  permissions.py        # Matriz de permisos por rol (única fuente de verdad)
  seed.py               # Carga app/seed_data.json mapeando los ids antiguos a
                        # enteros y conservando las relaciones
  seed_data.json          # Datos iniciales de demo (portados del original).

migrations/            # Alembic: env.py, alembic.ini y versions/ (migraciones)
instance/              # ddn.db (SQLite de desarrollo); ignorado por git
backups/               # Respaldos generados por ``flask backup``; ignorado por git
scripts/backup.py      # Respaldo/restauración sin contexto de Flask
scripts/fix_mojibake.py # Corrección de codificación de app/seed_data.json

templates/               # Plantillas Jinja2 HTML (dashboard, login, bookings,
                        # ai_predictive, client_portal, audit, payments, etc.)
static/
  css/styles.css         # Estilos complementarios (temas, tamaños de texto)
  js/app.js               # Modales, cálculo de precios en vivo, llamadas a API IA

## Instalación

```bash
cd ddntravel_python
pip install -r requirements.txt        # Flask, python-dotenv, google-genai,
                                         # flask-dance, reportlab
cp .env.example .env                     # Edita y coloca GEMINI_API_KEY (opcional)
# Opcional: configura GOOGLE_CLIENT_ID/SECRET en .env para login con Google
```

## Ejecutar

```bash
python run.py
```

La app estará disponible en **http://localhost:3000**.

## Base de datos: migraciones, seed y respaldos

La persistencia usa **SQLAlchemy + Alembic** (SQLite en desarrollo,
PostgreSQL en producción vía `DATABASE_URL`). Desde una instalación limpia:

```bash
flask db upgrade        # crea el esquema (migraciones/versions/)
flask seed              # carga app/seed_data.json de forma idempotente
python run.py
```

- `flask seed --reset` vuelve a sembrar desde cero, pero **solo en desarrollo**
  (`FLASK_ENV=development`); en producción el comando falla.
- La primera migración usa `render_as_batch=True` para que SQLite soporte los
  `ALTER TABLE` de fases posteriores.

### Respaldos

```bash
flask backup                          # respaldo en backups/ (marca de tiempo)
flask backup --keep 20                # conserva los 20 más recientes
flask backup --list                   # lista los respaldos existentes
flask backup --restore backups/ddn-20261005-151740.db

python scripts/backup.py              # equivalente sin contexto de Flask
python scripts/backup.py --restore <archivo>
```

- SQLite se copia con `sqlite3.Connection.backup()`, que genera una copia
  consistente aunque la base esté en uso. PostgreSQL se vuelca con `pg_dump`
  (formato `custom`) y se restaura con `pg_restore`.
- Solo se conservan los `BACKUP_KEEP` respaldos más recientes (10 por defecto).
- Antes de sobrescribir la base, `--restore` verifica la integridad del archivo
  (`PRAGMA integrity_check`) y que contenga el esquema esperado, y deja una copia
  de la base anterior en `backups/pre-restore-<marca>.db`.
- `backups/` está en `.gitignore`: los respaldos nunca se versionan.
- **El camino PostgreSQL está escrito pero sin probar en este entorno** (no hay
  servidor ni driver configurados). Se verificará en la fase P9, que instalará el
  driver y definirá `DATABASE_URL`. El camino SQLite sí está cubierto por pruebas
  reales en `tests/test_backup.py`.

## Configuración de IA (Gemini)

- **Sin GEMINI_API_KEY**: la app funciona completamente con datos simulados de
  alta fidelidad. Las 3 funciones IA (predicción, recomendaciones, itinerarios)
  retornan respuestas pre-definidas idénticas a la versión original cuando la IA
  no está disponible.

- **Con GEMINI_API_KEY**: coloca una clave válida en el archivo `.env` y la app
  usará Gemini real mediante el paquete `google-genai`.

Ejemplo `.env.example`:
```
GEMINI_API_KEY=pega_aqui_tu_clave
SECRET_KEY=genera_una_clave_aleatoria_larga
GOOGLE_CLIENT_ID=tu_client_id_de_google.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=tu_client_secret_de_google
```

## Usuarios de demostración

La app muestra una pantalla de login. La contraseña de las 3 cuentas demo es `ddn123`:

- **admin@ddntravel.com** — **Administrador**: acceso total, incluido módulo
  Auditoría (`/audit`), pagos (`/payments`), documentos (`/documents`),
  administración de destinos (`/admin/destinations`).

- **sofia.v@ddntravel.com** — **Agente / Empleado**: gestión del sistema sin
  acceso a auditoría. Puede ver/gestionar la mayoría de módulos pero no audit.

- **roberto.gomez@gmail.com** — **Cliente Viajero**: acceso al portal
  cliente-portal con catálogo, sus reservas propias y generación de itinerarios.

**Notas de rol:**
- El selector de perfil (cambiar de usuario) solo aparece para el Administrador
  y permite alternar entre Admin y Empleado.
- Clientes y empleados solo ven el botón de Cerrar Sesión.
- Permisos por ruta (`role_required` decorator en routes.py):
  - `admin`/`employee`: `/audit`, `/payments`, `/documents`, `/admin/destinations`,
    `/bookings`, `/clients`, `/hotels`, `/flights`, `/transports`, `/promotions`
  - `client`: `/client-portal` solo

## Inicio de sesión con Google (OAuth)

Opcional. Configurar en `.env`:
1. Crear OAuth Client ID (tipo "Web app") en Google Cloud Console.
2. URI de redirección autorizada: `http://localhost:3000/login/google/authorized`.
3. Agregar `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` al `.env`.
4. Reiniciar servidor (`python run.py`).

Cuando un usuario entra por primera vez con Google, se registra automáticamente
como **Cliente Viajero** (creando su perfil en el CRM). Sin credenciales, el
botón simplemente no se muestra y todo funciona con login/contraseña.

## Editar información de la cuenta

Los usuarios pueden actualizar su perfil (nombre, foto, teléfono, documento,
nacionalidad, etc.) a través de la interfaz de la aplicación. Los campos
disponibles para edición incluyen:

- **Nombre**: identificador principal del usuario
- **Teléfono**: número de contacto
- **Documento de identidad**: número de documento (RFC, pasaporte, etc.)
- **Nacionalidad**: país de origen
- **Categoría**: nivel de cliente (Estándar, Premium, etc.)
- **Presupuesto preferido**: límite de gasto aproximado
- **Fecha de vencimiento de pasaporte**: para viajes internacionales
- **Destinos preferidos**: lista de destinos favoritos
- **Notas**: información adicional sobre el cliente

### Para administradores:

Puede actualizar la información de cualquier cliente desde el panel de
administración (`/clients`), utilizando el método `update_client` del DataStore,
que persiste el cambio en la base de datos dentro de su transacción.

### Para clientes (portal):

Los clientes pueden modificar sus datos personales desde la sección de
configuración de su portal (`/client-portal`). Los cambios se guardan y
quedan registrados en el historial de la agencia.

Los cambios en la información de perfil se reflejan al instante en todos
los módulos de la aplicación y quedan auditados en el módulo de Auditoría
(RN-05) para el rol de administrador.

## Persistencia de datos

- Base de datos SQLAlchemy en `instance/ddn.db` (SQLite en desarrollo;
  `DATABASE_URL` apunta a PostgreSQL en producción). **No se usa `state.json`**:
  el esquema vive en `migrations/` y los datos sobreviven al reinicio del
  servidor porque cada operación se confirma en su transacción.
- Para volver al estado inicial: usar "Restablecer Datos Iniciales" en la UI
  (solo admin y con `ENABLE_RESET=1`), o `flask seed --reset` en desarrollo.
- Las reservas validan disponibilidad (RN-01), exigen cliente asociado (RN-02)
  y calculan estado de pago (RN-03) igual que la versión original.
- El módulo de Auditoría (RN-05) registra todas las acciones relevantes con su
  valor anterior y posterior, dentro de la misma transacción que el cambio;
  visible solo para el rol Administrador.

## Ejecutar los tests

```bash
python -m pytest tests -v
```

Cubren:
- Reglas de negocio RN-01 a RN-03 (disponibilidad, cliente obligatorio, cálculo de pago)
- Persistencia de datos y auditoría con before/after (RN-05)
- Flujo de login y permisos por rol
- Migraciones Alembic: `upgrade` desde cero, `downgrade base` y re-aplicación
- Respaldos: copia funcional, restauración, integridad y conservación de los
  `BACKUP_KEEP` más recientes
- Pruebas de aislamiento: cada test usa una base SQLite en memoria (o en
  `tmp_path`), nunca la base de desarrollo de `instance/`