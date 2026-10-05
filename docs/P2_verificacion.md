# P2 — Acta de cierre: Migración a SQLAlchemy + Alembic

> Evidencia de la fase P2: reemplazo de `state.json` por base de datos.
> Todos los datos de este documento son reproducibles con los comandos de la
> sección final. Fase cerrada el 2026-10-05 sobre la rama `fase-P2`.
>
> Rama: `fase-P2` (10 commits desde `24c3015`). **No se ha hecho merge a `main`
> ni push**: queda pendiente de revisión.

## 1. Veredicto

| Comprobación | Resultado |
|---|---|
| Suite automática | **213 passed, 0 skipped**, 1 warning ajeno (`google.genai`) |
| Criterio 1 — clon limpio de punta a punta | **PASS** (venv nuevo, sin `instance/`, sin `.env`) |
| Criterio 2 — `grep -rn "state.json" app/` | **PASS**: 2 únicas coincidencias, ambas en `app/billing.py` (deuda P4) |
| Criterio 3 — pytest en verde | **PASS**: 213/213 |
| Smoke test manual (servidor real, 3 roles) | **0 fallos** en 56 comprobaciones |
| `flask db upgrade` desde cero | 21 tablas + `alembic_version` |
| `flask db downgrade base` + re-`upgrade` | OK (deja solo `alembic_version` y reconstruye) |
| `db.create_all()` en código de aplicación | ninguno (solo en `tests/conftest.py`) |
| Estado del árbol al cerrar | limpio salvo `app/seed_data.backup.json` (ajeno, sin commitear) |

## 2. Criterios de aceptación originales de P2

### 2.1 Clon limpio: `pip install -r requirements.txt && flask db upgrade && flask seed && python run.py`

Verificado en un entorno **realmente limpio**, no por inferencia:

```
git clone <repo> %TEMP%\opencode\ddn_limpio     # HEAD = 1dc6419, rama fase-P2
# comprobaciones previas: no existe instance\, ni backups\, ni .env
python -m venv .venv                             # Python 3.14.6, venv NUEVO
.venv\Scripts\Activate.ps1
pip install -r requirements.txt                  # 50 paquetes, 0 errores
flask db upgrade                                 # -> Running upgrade -> dd6986e58c40
flask seed                                       # Datos de demostración cargados correctamente
flask seed                                       # (2ª vez) ya contiene datos; no se modificó nada
python run.py                                    # servidor real, PORT=3111
```

- `flask seed` es **idempotente** (probado con la segunda ejecución).
- Lo único que se crea es `instance/ddn.db`.
- Sin `.env`: la `SECRET_KEY` se genera por proceso en desarrollo y la IA cae
  al respaldo simulado, como está previsto en P0.

### 2.2 `grep -rn "state.json" app/` → nada, salvo la deuda de P4

```
app\billing.py:64:  # El último NCF usado se guarda en `state.json` bajo la clave ``ultimo_ncf``.
app\billing.py:239: """Extrae el último NCF grabado en el diccionario state.json que la app usa."""
```

Son las **dos únicas** coincidencias y corresponden a la deuda de facturación
documentada desde P1 (NCF secuencial, fase P4). Durante el cierre se
reescribieron dos comentarios de `app/extensions.py` y `app/store.py` que
mencionaban el archivo antiguo para que el criterio sea literalmente cierto.

Fuera de `app/` sí aparece la palabra, y es correcto: `.gitignore` (mantiene
ignorado el archivo legacy), `AGENTS.md` (plan de fases) y las actas P1/P2.

### 2.3 `pytest` completo en verde

```
.\.venv\Scripts\python.exe -m pytest -q   ->  213 passed, 1 warning in 29.32s
```

**0 tests omitidos.** El único `skipif` del repo es el de PostgreSQL
(`tests/test_backup.py:428`) y **no se activa** en este entorno porque `pg_dump`
no está instalado: el test se ejecuta y verifica que el error reportado sea
accionable. Es decir, el camino PostgreSQL está sin probar a propósito y
documentado, pero el resto de la suite no esconde ninguna omisión.

## 3. Commits que componen la fase

| Commit | Paso |
|---|---|
| `dc3131c` | 1 — dependencias SQLAlchemy/Alembic y configuración de base de datos |
| `3c823bd` | 2 — modelos ORM (paquete `app/models`) con alias de compatibilidad |
| `4be70ba` | 3 — repositorios y fachada `DataStore` sobre SQLAlchemy (sin `state.json`) |
| `1e25806` | 4 — auditoría RN-05 con before/after en la misma transacción (IP real, login/logout) |
| `5d9b247` | 5 — elimina `new_id()` y el módulo legacy (IDs enteros ya migrados) |
| `654d667` | 6 — patrón reutilizable de inventario atómico (`decrement_if_available`) |
| `cbb23c8` | 7 — comando `flask seed` idempotente; `--reset` solo en desarrollo |
| `7eb09d8` | 8 — migración inicial Alembic (`render_as_batch`) y pruebas de upgrade/downgrade |
| `1dc6419` | 9 — respaldos (SQLite/PostgreSQL) con restauración verificada y documentación |
| `e6b9a09` | 10 — verificación de aceptación (clon limpio, smoke 3 roles) y formato de códigos fijado con tests |

## 4. Pruebas automáticas (213)

| Archivo | Pruebas | Cubre |
|---|---:|---|
| `tests/test_permissions.py` | 53 | matriz por rol, `owns`, rutas mutantes sin permiso (P1) |
| `tests/test_backup.py` | 23 | copia SQLite funcional, restore, integridad, `BACKUP_KEEP`, argumentos de `pg_dump` |
| `tests/test_matriz_http.py` | 22 | ruta × rol por HTTP, nunca 500 (P1) |
| `tests/test_idor.py` | 21 | propiedad de reservas, pagos y documentos (P1) |
| `tests/test_ratelimit.py` | 20 | 429 por endpoint, límites de entrada (P1) |
| `tests/test_store_view.py` | 13 | fugas en HTML y en `DDN_DATA` (P1) |
| `tests/test_templates_csrf.py` | 12 | todo `<form method="post">` con token (P1) |
| `tests/test_app.py` | 10 | rutas y permisos base |
| `tests/test_store.py` | 8 | RN-01, RN-02, RN-03 y persistencia real en BD |
| `tests/test_seed.py` | 7 | idempotencia, `--reset`, CLI, formato de códigos de reserva |
| `tests/test_csrf_client.py` | 7 | `X-CSRFToken` en `fetch` (P1) |
| `tests/test_audit.py` | 5 | before/after, login/logout, insert-only de `AuditLog` |
| `tests/test_inventory.py` | 5 | `decrement_if_available` y hold de cupos de paquetes |
| `tests/test_seed_encoding.py` | 4 | codificación de la semilla (P0) |
| `tests/test_migrations.py` | 3 | `upgrade` desde cero, `downgrade base` + re-`upgrade`, `render_as_batch` |
| **Total** | **213** | **0 omitidas** |

## 5. Smoke test manual con los 3 roles

Servidor real arrancado desde el clon limpio (`python run.py`, `PORT=3111`) y
recorrido por HTTP con sesión y token CSRF: **56 comprobaciones, 0 fallos**.

| Rol | Rutas comprobadas | Resultado |
|---|---:|---|
| admin (`admin@ddntravel.com`) | 16 | todas 200 salvo `/client-portal` → **403** |
| employee (`sofia.v@ddntravel.com`) | 9 | 200 en su perímetro; **403** en `/audit` y `/client-portal` |
| client (`roberto.gomez@gmail.com`) | 15 | 200 en portal, documentos, catálogo público, IA y perfil; **403** en dashboard, clientes, reservas, pagos, promociones, hoteles, vuelos y transporte |

Controles comprobados:

| Control | Evidencia |
|---|---|
| Salud | `/api/health` → 200 con `{"status":"ok","app":"DDN Travel Server (Python)"}` |
| Login | los 3 roles entran con la clave demo y la sesión queda establecida |
| Sin fugas | el portal del cliente no contiene el correo del admin ni del empleado |
| Datos reales | `/clients` lista correos; el portal y `/documents` renderizan contenido de la BD |
| Respuestas 5xx | **0** |

La app se comporta **igual que antes de la migración**: mismas rutas, mismos
200/403 y datos servidos desde la base de datos en lugar del JSON.

## 6. Hallazgos corregidos durante la fase

Bugs y trampas reales encontrados al ejecutar la fase:

1. **La base local no estaba creada por Alembic.** `instance/ddn.db` tenía las 21
   tablas pero **sin `alembic_version`**. Hoy no hay ningún camino en `app/` que
   cree tablas fuera de Alembic: `create_all` solo existe en `tests/conftest.py`
   (`git log -S 'create_all' -- app/` no devuelve nada) y esa suite siempre usó
   `sqlite:///:memory:`, nunca el archivo de desarrollo. Ese archivo se generó
   con una invocación manual de `db.create_all()` contra la URI por defecto
   durante los pasos 3–7; no hay registro que permita afirmar quién la ejecutó.
   Se borró para autogenerar la migración contra un estado limpio. Verificado
   empíricamente en el clon limpio: sin `flask db upgrade` la app **crea el
   archivo vacío** (`instance/ddn.db`, 0 tablas) y falla con
   `OperationalError: no such table: clients`; el esquema completo (22 tablas con
   `alembic_version`) aparece solo al correr `flask db upgrade`.
2. **`env.py` usaba `db.get_engine()`**, deprecado en Flask-SQLAlchemy 3.1 y
   eliminado en 3.2. Corregido.
3. **`render_as_batch` no llegaba al modo offline** de Alembic: `env.py` solo
   pasaba `configure_args` en el modo online. Ahora se aplica en ambos.
4. **El primer test de migraciones conectaba a la base de desarrollo.** Flask-SQLAlchemy
   crea el motor en `init_app`, así que cambiar `SQLALCHEMY_DATABASE_URI` después
   de `create_app` no surte efecto. La URI ahora se inyecta en una subclase de
   configuración **antes** de crear la app (el fallo se detectó porque las tablas
   ya existían).
5. **`flask seed` fallaba por falta de contexto de aplicación.** `app.cli.add_command`
   no lo inyecta; se añadió `@with_appcontext`.
6. **`Package.itinerary_summary` no era `db.JSON`**, lo que rompía la
   serialización y la comparación de itinerarios.
7. **`app/repositories/base.py get()` no soportaba PK de texto** (`Setting.key`).
8. **Códigos de reserva con dos formatos.** El smoke del portal no encontraba
   códigos: el demo conserva los del `seed_data.json` original (`DDN-2026-881`)
   porque 7 referencias cruzadas de pagos y auditoría dependen de ellos, mientras
   las reservas nuevas usan `DDN-{año}-{id:05d}`. Decisión **deliberada** y ahora
   fijada con dos tests, no un descuido.
9. **`to_int` importado y sin usar** en `app/store.py` (resto del módulo legacy).
10. **Dos comentarios rompían el criterio 2** (`state.json` en `app/extensions.py`
    y `app/store.py`): reescritos sin pérdida de sentido.

## 7. Deuda trasladada a fases siguientes

| Pendiente | Fase | Detalle |
|---|---|---|
| No hay `update_*`/`delete_*` de catálogo (destinos, paquetes, hoteles, vuelos, transporte, actividades) | P3 | CRUD completo con lista blanca de campos |
| `Booking.set_status` directo en `bookings.py`: RN-03 no tiene todavía un único camino (`BookingService.transition`) | P3 | confirmar exige pago `Completado` |
| Inventario atómico solo en **paquetes**; vuelos, transporte y hotel por solapamiento de fechas no se descuentan | P3 | `decrement_if_available` ya sirve de patrón |
| `update_booking` / `cancel_booking` sin idempotencia ni recálculo de total | P3 | validación de fechas y precio por noches |
| `app/repositories/base.py apply_fields` sin uso (duplica `assign_by_type`) | P3 | eliminar o usar |
| `store.delete_document` sigue aceptando empleados (la ruta ya es solo admin) | P3 | coherencia en el store (deuda heredada de P1) |
| `app/billing.py:64` y `:239` con referencias a `state.json`; factura PDF en 501 | P4 | NCF secuencial, PDF real, anulación/reembolso |
| `Notification.read` sigue siendo un booleano global aunque existe `NotificationRead` | P6 | "leído" por usuario |
| Sin alertas automáticas, sin itinerarios guardables, sin correo con Flask-Mail | P6 | RF-10, RF-13, RF-17, RF-20 |
| **Driver PostgreSQL no instalado y `pg_dump` sin probar** (no hay servidor en este entorno) | P9 | instalar driver y verificar el camino completo |
| `ruff` sin configuración propia: 43 avisos de base en `app/` | P9 | configuración y puerta de calidad en CI |
| Cobertura sin medir (objetivo ≥ 80 % en `app/`) | P9 | `pytest-cov` |
| `window.DDN_DATA` sigue existiendo (ya filtrado por rol) | P7 | eliminarlo y usar `/api/lookup` |

## 8. Cómo reproducir la verificación

```powershell
# 1) Suite completa
.\.venv\Scripts\python.exe -m pytest -q

# 2) Instalación limpia de referencia
git clone <repo> ddn_limpio && cd ddn_limpio
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
flask db upgrade
flask seed
python run.py

# 3) Esquema y respaldo
flask db current
flask db downgrade base ; flask db upgrade
flask backup ; flask backup --list
flask backup --restore <archivo>

# 4) Criterio 2
git grep -n "state.json" -- app/
```

Credenciales demo (README): `admin@ddntravel.com`, `sofia.v@ddntravel.com`,
`roberto.gomez@gmail.com` — clave `ddn123`.