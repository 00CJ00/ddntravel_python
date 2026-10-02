# Prompts para OpenCode — DDN Travel (plan completo hasta el 100 %)

Basado en la auditoría de `ddntravel_python` (Flask + Jinja2, datos en `state.json`).
Cada prompt es autocontenido, tiene criterios de aceptación verificables y asume que
`AGENTS.md` (sección 1) ya está en la raíz del proyecto.

## Cómo usarlos (para rendir más con OpenCode)

1. **Primero** reemplaza el `AGENTS.md` del repo por el de la sección 1. OpenCode lo lee en cada
   sesión, así los prompts no repiten reglas y gastas menos contexto.
2. **Una fase = una rama git = una sesión nueva.** `git checkout -b fase-P2`, pega el prompt,
   revisa el diff, `pytest`, commit, merge. No pegues dos prompts en la misma sesión.
3. **Plan antes de Build.** Empieza la sesión en el agente *plan* (Tab para cambiar de agente) con
   "Lee AGENTS.md y propón el plan de esta fase; no edites nada". Corrige el plan y luego pasa a *build*.
4. **Orden obligatorio:** P0 → P1 → P2 → … → P9. Usa el modelo más capaz que tengas en P2, P3 y P4
   (son las que más riesgo tienen de romper cosas).
5. Si el agente se desvía o rompe tests, usa `/undo` (o `git restore .`) y repite con una instrucción más acotada.
6. **Acciones que el agente NO puede hacer por ti:** revocar el token de ngrok (dashboard de ngrok)
   y purgar el historial de git si el repo ya se subió a algún remoto (`git filter-repo`).

### Mapa: tus 4 fases → este paquete

| Tu fase | Aquí | Qué se añadió |
|---|---|---|
| Fase 1 (higiene/seguridad) | P0 + P1 | CSRF, propiedad de datos (IDOR), fugas de datos, `/reset`, cookies, matriz de permisos, test roto, token ngrok |
| Fase 2 (SQLAlchemy/Alembic) | P2 | Tablas de pagos, NCF, promociones, transporte, actividades, documentos, notificaciones, inventario de hotel |
| Fase 3 (CRUD + reglas) | P3 | Política de inventario coherente, definición de "pago verificado", bugs de lógica detectados |
| Fase 4 (facturación/reportes/búsqueda) | P4 + P5 | Secuencia NCF atómica, estadísticas del dashboard |
| — (no cubierto) | P6 – P9 | Itinerarios, documentos, alertas, IA por reglas, **todo el frontend**, despliegue, cumplimiento |

---

## 1. `AGENTS.md` 

~~~markdown
# AGENTS.md — DDN Travel

## Stack
Flask 3 + Jinja2 (render en servidor), Tailwind, JS vanilla. Datos: SQLAlchemy + Alembic
(SQLite en desarrollo, PostgreSQL en producción) — antes de P2 aún es `state.json`.
IA: Gemini opcional con respaldo simulado. PDF: reportlab. Excel: openpyxl.

## Comandos

- `python run.py` → servidor en http://127.0.0.1:3000
- `python -m pytest tests -q` → suite completa (debe estar en verde antes de terminar)
- `GET /api/health` → {"status":"ok","app":"DDN Travel Server (Python)"}
- Callback de Google OAuth (si se configura): http://localhost:3000/login/google/authorized
- (desde P2) `flask db upgrade`, `flask seed`, `python scripts/backup.py`

## Reglas de trabajo
- Un prompt = una fase. No implementes cosas de otras fases; anótalas como pendientes.
- Antes de editar, lee los archivos afectados. Cambios mínimos y coherentes con el estilo existente
  (docstrings y comentarios en español).
- Todo cambio de comportamiento lleva test en `tests/`.
- Nunca imprimas, commitees ni copies secretos (`.env`, tokens). No edites `.env`.
- Toda dependencia nueva va a `requirements.txt` con versión fijada.
- Mantén los nombres de atributos que usan las plantillas Jinja (`price_usd`, `available_slots`…)
  salvo que actualices la plantilla en el mismo cambio.
- Textos visibles en español; archivos UTF-8 sin BOM.

## Reglas de negocio (fuente: documento de requerimientos)
- RN-01 No se reserva sin disponibilidad.
- RN-02 Toda reserva pertenece a un cliente.
- RN-03 Los pagos se registran antes de confirmar servicios.
- RN-04 Solo administradores eliminan información crítica.
- RN-05 Todo cambio queda en historial (auditoría con before/after).

## Documento de requerimientos
Ver docs/requerimientos.md — fuente oficial de RF-01…RF-20, RNF-01…RNF-10, RN-01…RN-05.
Los prompts de cada fase citan los códigos relevantes; ante cualquier duda de alcance,
este documento es la referencia final.

## Seguridad (invariantes que nunca se rompen)
- Toda ruta que muta datos: sesión + permiso (`app/permissions.py`, única fuente de verdad) + CSRF.
- Un cliente solo ve y modifica lo suyo; la propiedad se verifica en el servidor.
- Ninguna respuesta (HTML o JSON) a un cliente contiene datos de otros clientes.
- Ningún dato personal se envía a servicios de IA externos.
- Toda mutación escribe auditoría con before/after.

## Cierre de cada tarea
Ejecuta `pytest`, muestra `git diff --stat`, resume decisiones tomadas y lista lo que quedó
pendiente. No inicies otra fase.
~~~

---

## P0 — Higiene y red de seguridad de tests (tu Fase 1: puntos 1, 2 y 4)

~~~
Fase P0. Lee AGENTS.md. Esta fase NO cambia comportamiento de negocio.

1. run.py: crea run.py en la raíz (usa create_app; HOST/PORT desde entorno, por defecto
   127.0.0.1:3000; debug solo si FLASK_DEBUG=1).
2. Configuración: crea app/config.py (Config/Dev/Prod) leyendo todo de os.environ vía python-dotenv.
   - Cambia load_dotenv(override=True) por load_dotenv() (el entorno real manda sobre .env).
   - En producción (FLASK_ENV=production) la app debe negarse a arrancar si SECRET_KEY falta,
     tiene menos de 32 caracteres o coincide con el texto de ejemplo de .env.example.
   - En desarrollo, si falta, genera una clave aleatoria por proceso y avisa por log.
     Elimina la clave fija "ddn-travel-dev-secret-key".
3. Secretos y repo: `git rm --cached ngrok.yml`, añádelo a .gitignore y crea ngrok.example.yml
   con placeholder. .gitignore debe incluir .env, .venv/, state.json, *.db, backups/, uploads/.
   No imprimas ningún token. Deja en tu resumen final la nota: "el usuario debe revocar el token de
   ngrok y purgar el historial si hubo remoto".
4. Mojibake: crea scripts/fix_mojibake.py que recorra todos los strings de app/seed_data.json y, a los
   que contengan 'Ã' o 'Â' seguidos de un carácter U+0080–U+00BF, aplique
   s.encode('latin-1').decode('utf-8') dentro de try/except (si falla, deja el original y repórtalo).
   Reescribe el JSON con ensure_ascii=False, indent=2, UTF-8 sin BOM. Ejecútalo.
   Añade tests/test_seed_encoding.py: ningún string del seed contiene 'Ã', 'Â' ni '\ufffd'.
   Revisa con grep plantillas y .py por el mismo patrón e infórmalo (no reescribas .py automáticamente).
5. Tests: arregla test_login_admin_ok (la app redirige a "/" y luego a /dashboard). Arregla el fixture
   para aislar el store también en app.routes (routes hace `from .store import store` al importar).
6. Dependencias: crea requirements.txt con versiones fijas de las dependencias directas (+ openpyxl,
   gunicorn) y requirements-dev.txt (pytest, pytest-cov, ruff).
7. README: elimina la sección duplicada de OAuth y corrige nombres de carpeta (ddn_python → ddntravel_python).

Aceptación:
- `python run.py` arranca y GET /api/health → 200.
- `pytest -q` → 0 fallos.
- `grep -c "Ã" app/seed_data.json` → 0.
- `git ls-files` no contiene .env ni ngrok.yml.
~~~

---

## P1 — Seguridad de rutas (tu Fase 1: punto 3, ampliado)

~~~
Fase P1. Lee AGENTS.md. Trabajas solo en la capa de rutas/plantillas; NO cambies la lógica del store
(eso es P2/P3). Importante: NO pongas @role_required('admin') a todas las rutas mutables; los
empleados gestionan clientes y reservas según el documento. Usa esta matriz, definida como datos
en app/permissions.py (única fuente de verdad):

| Acción                                              | admin | employee | client |
|-----------------------------------------------------|:-----:|:--------:|:------:|
| Dashboard / reportes                                | sí    | sí       | no     |
| Auditoría (ver)                                     | sí    | no       | no     |
| Clientes: ver / crear / editar                      | sí    | sí       | solo su perfil (editar) |
| Clientes: eliminar                                  | sí    | no       | no     |
| Catálogo (destinos, paquetes, hoteles, vuelos,
  transporte, actividades): ver                       | sí    | sí       | paquetes, destinos, actividades |
| Catálogo: crear / editar / eliminar                 | sí    | no       | no     |
| Reservas: ver                                       | todas | todas    | solo las suyas |
| Reservas: crear                                     | sí    | sí       | solo para sí |
| Reservas: editar / cambiar estado                   | sí    | sí       | no     |
| Reservas: cancelar                                  | sí    | sí       | la suya, solo si está Pendiente |
| Pagos: registrar                                    | sí    | sí       | no     |
| Pagos: anular / reembolsar                          | sí    | no       | no     |
| Promociones: crear / activar                        | sí    | no       | no     |
| Promociones: aplicar código                         | sí    | sí       | sí     |
| Documentos: subir                                   | sí    | sí       | propios |
| Documentos: eliminar                                | sí    | no       | no     |
| Usuarios: CRUD                                      | sí    | no       | no     |
| IA predictiva                                       | sí    | sí       | no     |
| IA recomendaciones / itinerarios                    | sí    | sí       | sí     |
| Reset de datos                                      | sí, solo si ENABLE_RESET=1 | no | no |

Tareas:
1. app/permissions.py con la matriz + decoradores `login_required`, `permission_required("recurso:acción")`
   y helper `owns(user, obj)`. Expón `can(permiso)` como global de Jinja para ocultar botones.
   Aplícalos a TODAS las rutas existentes (incluye /reservas/<id>/status, /cancel, /payments/new,
   /promotions/*, /documents/*, /clients/new, /bookings/new, /notifications/*, /api/*).
2. /switch-user: elimínalo y quita el selector de la UI (base.html). Solo puede existir si
   app.debug y ENABLE_DEV_SWITCH=1 y el usuario es admin.
3. /reset: solo admin y solo si ENABLE_RESET=1; pide confirmación explícita en el formulario.
4. Propiedad (IDOR): un cliente solo puede crear/ver/cancelar reservas de su propio client_id,
   ver sus documentos y facturas. /documents y /client-portal filtran por dueño.
5. Fugas: `window.DDN_DATA` (base.html + inject_globals) NO puede incluir clientes, emails ni datos de
   otros usuarios. Para rol client incluye solo catálogo y su propio registro; para admin/employee
   mantén lo actual por ahora (P7 lo elimina).
6. IA: /ai-predictive y /api/ai/predictive-analytics → admin/employee. /api/ai/recommendations y
   /api/ai/generate-itinerary → sesión + rate limit. /api/chat/message y /contacto → rate limit y
   longitud máxima; arregla `f.get('message')[:120]` (falla si falta el campo).
7. CSRF: Flask-WTF `CSRFProtect`. Crea macro `csrf_input()` y añádelo a TODOS los <form method="post">.
   Para fetch: <meta name="csrf-token"> y cabecera X-CSRFToken en static/js/app.js.
8. Sesión: SESSION_COOKIE_HTTPONLY, SAMESITE=Lax, SECURE en producción, PERMANENT_SESSION_LIFETIME=8h.
   Flask-Limiter en /login (5/min por IP+email) y mensaje genérico de error.
9. Tests (tests/test_permissions.py): matriz parametrizada ruta × rol → 200/302/403 esperado;
   test de escalada (/switch-user ya no existe); test de que un cliente no puede confirmar una reserva ni
   ver la de otro; POST sin token CSRF → 400; test que recorre app.url_map y falla si alguna ruta no-GET
   (salvo /login, /contacto, /api/chat/message, /set-theme) no tiene permiso declarado.

Aceptación: pytest verde; script de humo con rol client recibiendo 403 en /audit, /clients, /reset,
/bookings/<ajena>/status; HTML de /client-portal sin emails de otros clientes.
~~~

---

## P2 — Migración a SQLAlchemy + Alembic (tu Fase 2, ampliada)

~~~
Fase P2. Lee AGENTS.md. Es el cambio más grande: trabaja por pasos, corre pytest tras cada uno y haz
un commit por paso. Objetivo: reemplazar state.json por base de datos SIN romper rutas ni plantillas.

1. Dependencias: Flask-SQLAlchemy, Flask-Migrate (Alembic). DATABASE_URL por defecto
   sqlite:///instance/ddn.db; código compatible con PostgreSQL (sin funciones solo-SQLite;
   Alembic con render_as_batch=True para SQLite).
2. Modelos (app/models/, un módulo por agregado). PK entera autoincremental; dinero en Numeric(12,2)
   (Decimal); fechas como Date/DateTime UTC; listas (amenities, inclusions, gallery,
   preferred_destinations) como JSON:
   - User(email único, password_hash, role: admin|employee|client, department, avatar, is_active,
     google_id, client_id FK opcional, created_at)
   - Client, Destination, Package(available_slots, total_slots), Hotel + RoomType(hotel_id, name,
     price_per_night, rooms_total), Flight(seats_available, total_seats), Transport(available_seats),
     Activity
   - Itinerary(booking_id FK opcional, client_id, destination, days, source ia|manual, content JSON,
     created_by, created_at)
   - Booking(code único, client_id, package_id, hotel_id, room_type_id, rooms_count, check_in, check_out,
     flight_id, transport_id, departure_date, return_date, travelers, total_price, amount_paid, status,
     payment_status, notes, created_by, created_at, deleted_at) + BookingPassenger
   - Payment(booking_id, kind pago|reembolso, receipt_number único, amount, method, status
     Completado|Pendiente_verificacion|Anulado, reference, ncf único nullable, invoice_number,
     created_by, created_at, voided_at, void_reason)
   - NcfSequence(prefix PK, current, max_number, expires_on, active)
   - Promotion + PromotionRedemption(promotion_id, booking_id, único por reserva)
   - TravelDocument(client_id, booking_id opcional, doc_type, file_name, stored_name, mime, size_bytes,
     status, expiry_date, uploaded_by)
   - Notification + NotificationRead(notification_id, user_id) (el "leído" es por usuario)
   - Setting(key, value JSON) para predictive_data y contadores
   - AuditLog(timestamp UTC, user_id nullable, user_name, user_role, action, module, entity_type,
     entity_id, before JSON, after JSON, ip_address REAL (request.remote_addr con ProxyFix),
     user_agent, details). Solo inserción: ningún camino de código actualiza ni borra filas.
   Índices en: email, code, status, destination_name, created_at, client_id, booking_id.
3. Capa de repositorio (app/repositories/) + fachada `DataStore` en app/store.py que conserve los
   nombres y firmas actuales (create_booking, register_payment, add_client, …) para que las rutas sigan
   funcionando. Las entidades devueltas deben conservar los nombres de atributos que usan las plantillas
   (`price_usd`, `available_slots`, `booking_code`…), `to_dict()` y `describe()`. Elimina auto_save,
   persist(), STATE_PATH y todo uso de state.json.
4. Auditoría (RN-05): helper `audit.record(action, module, entity, before, after)` invocado desde los
   repositorios en create/update/delete, dentro de la MISMA transacción que el cambio (before = snapshot
   previo a mutar, after = snapshot tras flush). Registra también login, logout y login fallido.
5. IDs: rutas `<int:booking_id>` etc. y plantillas actualizadas. Sustituye new_id() y el código de
   reserva aleatorio por `DDN-{año}-{id:05d}` generado desde la BD (único).
6. Transacciones: una sesión por petición, commit/rollback centralizado en un solo lugar. Para inventario
   usa UPDATE condicional atómico (`SET x = x - n WHERE id=:id AND x >= n`) y comprueba rowcount.
7. Seed: `flask seed` idempotente que cargue app/seed_data.json (mapea ids antiguos → enteros y conserva
   relaciones; incluye el usuario demo con sus hashes actuales). `flask seed --reset` solo en dev.
8. Alembic: migración inicial versionada en migrations/. `flask db upgrade` debe funcionar desde cero.
9. Respaldo: scripts/backup.py (y `flask backup`): SQLite con sqlite3.Connection.backup(), PostgreSQL con
   pg_dump; archivo con marca de tiempo en backups/, conserva los últimos BACKUP_KEEP (10) y soporta
   `--restore <archivo>`. Documenta en README.
10. Tests: fixtures con SQLite en memoria por test; los 18+ tests existentes deben pasar con ediciones
    mínimas. Añade: seed idempotente, upgrade desde cero, actualizar un cliente escribe AuditLog con
    before/after, humo: cada GET de cada rol devuelve 200 o 403 (nunca 500).

Aceptación: clon limpio → `pip install -r requirements.txt && flask db upgrade && flask seed && python run.py`
funciona sin state.json; `grep -rn "state.json" app/` → nada; pytest verde.
~~~

---

## P3 — CRUD backend y reglas de negocio (tu Fase 3, ampliada)

~~~
Fase P3. Lee AGENTS.md y app/permissions.py. Decisiones ya tomadas (no las cambies):
- Editar/eliminar del catálogo, de usuarios y de pagos anulados: solo admin (RN-04 y matriz).
- Los empleados SÍ editan clientes y reservas (documento: "Empleado: gestión de reservas y clientes").
- Inventario: se RESERVA (hold) al crear la reserva y se LIBERA al cancelar/anular, de forma idempotente.
  NO se vuelve a descontar al confirmar (evita sobreventa entre creación y confirmación).
- "Pago verificado" = Payment.status == "Completado". Tarjeta/PayPal nacen Completado (simulado);
  Transferencia/Efectivo nacen Pendiente_verificacion hasta que admin/employee lo verifique
  (POST /payments/<id>/verify).

Tareas:
1. CRUD (crear/editar/eliminar) para Destino, Paquete, Hotel(+RoomType), Vuelo, Transporte, Actividad,
   Cliente y Usuario. Rutas `/admin/<recurso>/new|<id>/edit|<id>/delete` con permisos de la matriz.
   - Validación en app/validators.py (requeridos, tipos, rangos, email válido, email/documento únicos en
     clientes, precios ≥ 0, return_date > departure_date). Errores → 422 (JSON) o flash + formulario.
   - Lista blanca de campos por recurso (arregla edit_destination, que permite sobrescribir `id`).
   - Eliminación: soft delete (deleted_at/is_active) en entidades con historial (Cliente, Reserva,
     Paquete, Hotel, Vuelo). Si están referenciadas por reservas activas → 409 con mensaje claro.
2. Usuarios (RF-01): admin crea usuarios con rol, restablece contraseña (hash), desactiva. No se puede
   eliminar/desactivar al último admin. Contraseña mínima 8 caracteres. Clientes se vinculan a Client.
3. Reservas: `update_booking` (fechas, viajeros, notas; recalcula total y revalida inventario),
   `cancel_booking` idempotente (si ya está cancelada no vuelve a liberar cupos), validación de fechas
   (salida ≥ hoy), precio de hotel = price_per_night × noches × habitaciones (hoy ignora noches).
4. RN-03: crea BookingService.transition(booking, nuevo_estado) como ÚNICO camino para cambiar estado.
   "Confirmada" exige ≥1 pago Completado y suma de pagos Completados ≥ MIN_DEPOSIT_PCT × total
   (config; por defecto 100, para conservar el comportamiento actual). update_booking_status,
   apply_payment y create_booking deben pasar por ahí. Prueba que POST /status "Confirmada" sin pago → 422.
5. RN-01 extendida (todo atómico; si algo falla, rollback de toda la reserva con mensaje RN-01):
   paquetes (available_slots), vuelos (seats_available × travelers), transporte (available_seats) con
   UPDATE condicional; hoteles por solapamiento de fechas:
   rooms_total − sum(rooms_count de reservas activas que se solapan en [check_in, check_out)) ≥ solicitadas.
6. Promociones (RF-12): al crear reserva con cupón registra PromotionRedemption y suma current_uses;
   valida valid_until y applicable_categories contra la categoría del cliente.
7. RN-05: toda creación/edición/eliminación/transición registra AuditLog con before/after.
   Añade test que recorre app.url_map: cada ruta mutante (salvo /api/chat, /contacto, /set-theme) debe
   producir ≥1 fila de auditoría.
8. Tests por regla: RN-01 (paquete, vuelo, hotel con fechas solapadas y no solapadas), RN-02,
   RN-03 (intentos de bypass), RN-04 (employee → 403 al eliminar cada recurso), RN-05.

Aceptación: pytest verde; ninguna ruta cambia `booking.status` fuera de BookingService.transition
(`grep -rn "\.status *=" app/` lo demuestra).
~~~

---

## P4 — Facturación, NCF y pagos (tu Fase 4: punto 1)

~~~
Fase P4. Lee AGENTS.md. Arregla y completa el módulo de facturación.

1. Bugs existentes: elimina el uso de `store.state` (no existe), añade `get_payment` al repositorio,
   importa `date`, `send_file`, `BytesIO` en routes, importa `ParagraphStyle` en billing.py, usa campos
   reales de Payment/Booking/Client (no `total_price`/`client_email`/`creation_date` inexistentes en el
   pago) y quita la fila vacía [None, None] del encabezado del PDF.
2. NCF secuencial y persistente: función `next_ncf(prefix)` sobre NcfSequence, atómica dentro de la
   transacción del pago (PostgreSQL: SELECT ... FOR UPDATE; SQLite: UPDATE ... WHERE current < max_number
   con comprobación de rowcount). Formato configurable: prefijo + 8 dígitos con ceros (por defecto B02 →
   "B0200000001", 11 caracteres); B01 si el cliente tiene RNC válido (validar_rnc), B04 para notas de
   crédito. Error claro si la secuencia está agotada o vencida. Único a nivel de BD. Elimina el antiguo
   generar_ncf. Documenta en README que es una simulación académica (no autorizada por la DGII).
3. Datos del emisor desde configuración (AGENCY_RNC, AGENCY_NAME, AGENCY_ADDRESS, AGENCY_PHONE), no
   hardcodeados.
4. Registro de pago (RF-11): monto > 0 y ≤ saldo pendiente (422 si excede), aritmética con Decimal,
   no se paga una reserva cancelada, método dentro de una lista válida, única (booking_id, reference) si
   hay referencia (evita doble envío). El NCF se asigna en la misma transacción.
5. PDF de factura: GET /payments/<id>/factura (admin/employee, y el cliente dueño). Debe devolver un PDF
   válido con emisor, cliente, NCF, fecha, ítems, subtotal y total.
6. Anulación / reembolso: POST /payments/<id>/void (solo admin, motivo obligatorio): marca Anulado,
   recalcula amount_paid y estado de la reserva vía BookingService.transition (puede volver a Pendiente),
   NUNCA reutiliza el NCF, y crea un Payment kind=reembolso con su recibo y NCF de nota de crédito (B04)
   referenciando el pago original. Todo con auditoría.
7. Tests: 20 pagos concurrentes (threads) → 20 NCF únicos y consecutivos; sobrepago rechazado; anulación
   revierte estado; el PDF empieza con %PDF; permisos y propiedad de factura.

Aceptación: pytest verde; flujo manual: reserva → pago parcial → pago final → confirmada → factura PDF
descargable → anulación → estado y NCF de nota de crédito correctos.
~~~

---

## P5 — Reportes, búsqueda avanzada y estadísticas (tu Fase 4: puntos 2 y 3)

~~~
Fase P5. Lee AGENTS.md.

1. Reportes (RF-15): GET /reports/<kind>.<fmt> con kind ∈ bookings|payments|clients|occupancy|revenue y
   fmt ∈ pdf|xlsx; filtros date_from, date_to, status, destination. Permiso admin/employee.
   - Excel (openpyxl): encabezados con estilo, anchos automáticos, freeze panes, formato de moneda y fecha,
     fila de totales con fórmula SUM y hoja "Resumen". Neutraliza inyección de fórmulas: prefija con
     comilla simple los strings que empiecen por = + - @.
   - PDF (reportlab platypus): encabezado con título, rango de fechas y usuario generador; tabla con
     repeatRows=1; pie con número de página; totales.
   - Límite de 10 000 filas, nombre de archivo con fecha, y cada descarga registra auditoría.
2. Búsqueda (RF-16): GET /api/search con q, type (packages|destinations|hotels|flights|activities|
   transports|bookings|clients), category, destination, min_price, max_price, date_from, date_to, status,
   min_stars, sort (price|date|name), order (asc|desc), page (1), per_page (12, máximo 50).
   Respuesta: {items, total, page, per_page, pages, has_next, filters_applied}.
   - Paginación y filtros en SQL (SQLAlchemy con parámetros, LIKE escapado). Parámetros inválidos → 422.
   - Alcance por rol: cliente → catálogo público y sus propias reservas; admin/employee → todo, incluido
     clientes (por nombre, email, documento).
3. Estadísticas: app/analytics.py con funciones puras (testeables) y GET /api/dashboard/stats
   (admin/employee): ingresos por mes (12 m), reservas por estado, top destinos, ocupación de paquetes,
   clientes frecuentes (trips_count ≥ FREQUENT_CLIENT_MIN=3, configurable) y temporadas altas (meses con
   reservas > 1.25 × la media mensual).
4. Tests: cada filtro, límites de paginación, alcance por rol, cadenas tipo `' OR 1=1 --` sin efecto,
   contenido de los xlsx (abrir con openpyxl y comprobar totales), PDF válido, y funciones de analytics
   con datos sintéticos.

Aceptación: pytest verde; descarga real de un .xlsx y un .pdf de cada kind con datos del seed.
~~~

---

## P6 — Servicios restantes: itinerarios, documentos, alertas, IA por reglas

~~~
Fase P6. Lee AGENTS.md. Backend de RF-10, RF-13, RF-17 y RF-20.

1. Itinerarios (RF-10): mantén /api/ai/generate-itinerary y añade POST /bookings/<id>/itinerary
   (guardar, contenido JSON validado), GET, PUT (edición manual) y DELETE (solo admin). El cliente puede
   guardar/ver el de su propia reserva.
2. Documentos (RF-17): subida multipart con secure_filename, lista de extensiones (pdf, jpg, png),
   verificación de firma de archivo (magic bytes), MAX_CONTENT_LENGTH=5 MB, almacenamiento en UPLOAD_DIR
   FUERA de static/ con nombre UUID, descarga con comprobación de propiedad, eliminación solo admin.
   Al confirmar una reserva se genera un voucher PDF real (reportlab) y se guarda como documento.
   Estado de vencimiento calculado (vigente / por vencer < 6 meses / vencido).
3. Notificaciones (RF-13): leídas por usuario (NotificationRead). Envío de email con Flask-Mail (MAIL_* en
   entorno); si no está configurado usa un backend de consola/log. Plantillas: reserva confirmada, pago
   recibido, reserva cancelada. Un fallo de correo NUNCA rompe la petición (try/except + log).
4. Alertas automáticas: comando `flask alerts run` (y job diario APScheduler solo si ENABLE_SCHEDULER=1):
   pasaporte que vence < 6 meses antes de la salida, saldo pendiente con salida ≤ 15 días, paquete con
   cupos ≤ 20 %, reserva Pendiente sin pago > 72 h. Sin duplicados (clave única entidad + tipo + fecha).
5. IA (RF-20): mantén Gemini opcional con respaldo. Cambios: NO envíes nombres, emails ni documentos a
   Gemini (usa alias "Cliente A", categoría, presupuesto, conteos); valida el JSON devuelto contra un
   esquema con valores por defecto si faltan claves; timeout y reintentos; guarda el resultado predictivo
   en BD con marca de tiempo; registra cada llamada en auditoría. Enriquece recomendaciones con
   app/analytics.py (clientes frecuentes, temporadas altas). Arregla el chat: coincidencia por palabras
   completas (hoy "hi" coincide dentro de "which").
6. Tests: subida rechaza .exe y archivos con firma falsa; descarga ajena → 403; alertas sin duplicados;
   el prompt enviado a Gemini (mockeado) no contiene emails ni nombres reales; esquema de IA con datos
   incompletos no rompe la página.

Aceptación: pytest verde; `flask alerts run` crea notificaciones sobre los datos del seed.
~~~

---

## P7 — Frontend I: CRUD completo, CSRF, usuarios y reservas

~~~
Fase P7. Lee AGENTS.md. Mantén el diseño existente (tema Deep Space / claro, clases Tailwind actuales).

1. Componentes reutilizables en templates/macros.html: form_field, modal (con aria y cierre con Esc),
   confirm_delete, pagination, csrf_input, badge de estado. Oculta acciones según `can()`.
2. Para destinos, paquetes, hoteles (+ tipos de habitación), vuelos, transporte y actividades: botón
   "Nuevo" y modales de editar/eliminar (solo admin), errores de validación del servidor junto a cada
   campo, mensajes flash de éxito/error.
3. Clientes: tabla con búsqueda, detalle, editar (admin/employee) y eliminar (admin). Perfil propio para
   clientes.
4. Página /admin/users (RF-01): listar, crear, cambiar rol, restablecer contraseña, activar/desactivar.
5. Reservas: modal de edición, acciones de estado según rol, panel de pagos en el detalle (lista, registrar
   pago, verificar, anular/reembolsar solo admin, descargar factura PDF) e itinerario. Sustituye la
   factura armada en JS (openInvoice) por la del servidor.
6. static/js/api.js: wrapper de fetch con cabecera CSRF, manejo de errores y JSON. Elimina
   `window.DDN_DATA` por completo: los selects (cliente, paquete, hotel, vuelo) se renderizan en el
   servidor o se cargan con /api/lookup/<recurso>?q= (autocompletado con debounce).
7. El total de la reserva lo calcula el servidor (GET /api/bookings/quote); quita la lógica de precios
   duplicada de app.js.
8. Responsive: tablas dentro de contenedor overflow-x-auto, formularios en una columna bajo 640 px,
   botones táctiles ≥ 44 px.
9. Tests: cada página renderiza para cada rol sin 500; todo <form method="post"> renderizado contiene el
   token CSRF; los botones de eliminar no aparecen para employee/client.

Aceptación: pytest verde; recorrido manual: admin crea, edita y elimina un destino, un hotel y un vuelo
desde la UI; employee no ve los botones de eliminar.
~~~

---

## P8 — Frontend II: dashboard, reportes, búsqueda, auditoría, documentos, notificaciones

~~~
Fase P8. Lee AGENTS.md. Consume los endpoints de P5 y P6.

1. Dashboard (RF-14): gráficos con Chart.js (versión fijada, auto-alojado en static/vendor/ o CDN con SRI)
   desde /api/dashboard/stats: línea de ingresos por mes, dona de estados, barras de top destinos,
   indicador de ocupación, y clientes frecuentes / temporadas altas. Selector de periodo, estados de
   carga y vacíos, colores que respeten el tema claro y oscuro.
2. Página /reports: filtros y botones "Descargar PDF / Excel" por tipo de reporte.
3. Búsqueda (RF-16): reemplaza el filtro por DOM (data-searchable) por un buscador que consulta
   /api/search (debounce 300 ms), panel de filtros (drawer en móvil), chips de filtros activos,
   paginación y parámetros sincronizados en la URL. El buscador global muestra los 5 primeros por tipo
   con "ver todos".
4. Auditoría (RF-19): filtros por usuario, módulo, acción y fecha; paginación; visor de before/after con
   diff legible; exportar a Excel.
5. Documentos: subida con arrastrar y soltar, progreso, validación previa en el cliente, descarga,
   insignias de vencimiento.
6. Notificaciones: centro con paginación, "leída" por usuario, contador en la campana.
7. Portal del cliente: mis reservas, pagos, facturas descargables, documentos, itinerarios y perfil.
8. Tests de humo por rol; ningún 500; ningún dato de otros clientes en el portal.

Aceptación: pytest verde; con los datos del seed, el dashboard muestra los 4 gráficos y la búsqueda
filtra y pagina desde el servidor.
~~~

---

## P9 — Cierre: responsive, despliegue, calidad y cumplimiento

~~~
Fase P9. Lee AGENTS.md.

1. Responsive QA: con Playwright (instálalo en requirements-dev.txt) captura cada página y rol a 360,
   768 y 1280 px en docs/qa/. Corrige desbordes horizontales, sidebar colapsable con menú hamburguesa,
   tablas que pasan a tarjetas bajo 640 px. Añade reglas @media en static/css/styles.css.
2. Tailwind: sustituye el CDN por compilación con Tailwind CLI (`npm run build:css` →
   static/css/tailwind.css minificado). Imágenes remotas con onerror y placeholder local.
3. Producción: Flask-Talisman (HTTPS, HSTS, CSP compatible con lo que se usa), TRUSTED_PROXIES
   configurable (hoy ProxyFix confía a ciegas en un proxy), páginas de error y respuestas JSON para /api,
   logging sin datos personales.
4. Despliegue: Dockerfile (python slim, usuario no root, gunicorn con varios workers),
   docker-compose (app + PostgreSQL + volumen de backups), .dockerignore, healthcheck de /api/health que
   compruebe la BD, y variables documentadas en .env.example.
5. JWT — SOLO si tu rúbrica lo exige literalmente: Flask-JWT-Extended para /api/* (POST /api/auth/token con
   access de 15 min + refresh), aceptando Authorization: Bearer además de la sesión y con los mismos
   permisos. Si no lo exige, documenta en README por qué se usan sesiones firmadas con CSRF.
6. Calidad: pytest-cov con mínimo 80 % en app/, ruff configurado y un workflow de GitHub Actions que corra
   ruff y pytest.
7. Documentación (RNF-09): README completo (instalación, .env, migraciones, seed, backup, tests,
   credenciales demo, arquitectura con diagrama Mermaid) y docs/CUMPLIMIENTO.md con una tabla
   RF-01…RF-20, RNF-01…RNF-10 y RN-01…RN-05 indicando archivo/endpoint/test que lo demuestra y estado
   (Cubierto / Parcial + motivo). No maquilles: lista los pendientes reales.

Aceptación: `docker compose up` levanta la app con PostgreSQL y datos del seed; pytest verde con cobertura
≥ 80 %; docs/CUMPLIMIENTO.md completo.
~~~

---

## Verificación final (opcional, en el agente *plan*, solo lectura)

~~~
Audita el proyecto contra el documento de requerimientos (RF-01…RF-20, RNF-01…RNF-10, RN-01…RN-05).
Sin editar nada, entrega una tabla por requisito con estado, evidencia (archivo, endpoint o test) y
brechas restantes, y verifica que docs/CUMPLIMIENTO.md coincide con la realidad del código.
~~~