# P3 — Acta de cierre: CRUD backend, reglas de negocio y validación

> Evidencia de la fase P3 (CRUD backend, RN-01…RN-05, "pago verificado",
> validación de catálogo). Incluye el diagnóstico de brechas sobre la
> implementación ya existente y las correcciones aplicadas en la rama
> `fix-p3`. Todos los números son reproducibles con la sección final.
>
> Rama: `fix-p3` (levantada desde `main` @ `13ba260`). **Sin merge ni push**:
> queda pendiente de revisión.

## 1. Veredicto

| Comprobación | Resultado |
|---|---|
| Suite automática | **271 passed, 0 skipped**, 5 warnings (1 deprecación ajena de `google.genai`, 4 de `Query.get()` en tests) |
| Ninguna **ruta** asigna `booking.status` fuera de `BookingService.transition` | **PASS** (`grep .status\s*= app/routes.py` → 0) |
| Cobertura de la matriz de permisos | **PASS**: destinos añadidos al parametrize RN-04 (admin/employee/client) |
| CRUD crear corregido (catálogo y usuarios Google) | **PASS**: `assign_by_type` devolvía `None` → `save(None)` (sección 7.1) |
| Soft delete Cliente/Paquete/Hotel/Vuelo | **PASS** + migración Alembic idempotente (sección 7.2) |
| RN-01 atómico en vuelo y transporte | **PASS** (`UPDATE condicional` + rowcount, rollback total) |
| Validación de catálogo cableada | **PASS** (422 JSON en edición/módales; flash + redirect en crea) |
| Migración `flask db upgrade/downgrade` | **PASS** sobre SQLite (ciclo up → down → up verificado) |
| `state.json` en `app/` | solo deuda P4 ya conocida en `app/billing.py:64` y `:239` (comentarios) |

## 2. Contexto

La fase P3 se entregó originalmente en los commits `7ffa6f6` (Fase P3),
`bc0b53c`, `fc85ffb`, `89d8c88` y se fusionó a `main` en `13ba260`. El
diagnóstico (sin editar) encontró estas brechas, que este acta cierra en la
rama `fix-p3`:

1. OAuth de Google roto en tests: `main.google.login` / `main.google.authorized`
   (blueprint Flask-Dance) no estaban declarados públicos → 302 innecesario y
   un test rojo.
2. Faltaba la ruta de borrado de **Destino**; no existía guard de referencias.
   `delete_transport` no bloqueaba transportes referenciados **solo** por
   reservas canceladas.
3. **NO había soft delete**: se borraban físicamente Cliente, Paquete, Hotel y
   Vuelo (la PD planificada exigía `deleted_at`).
4. RN-01 atómico solo en paquetes; vuelos y transporte se descontaban con
   lectura-escritura no atómica (riesgo de sobreventa concurrente).
5. Validación solo conectada para clientes; el CRUD de catálogo aceptaba
   precios negativos y no validaba requeridos.

Además, al instrumentar las correcciones apareció un bug **preexistente** que
dejaba el "crear" de catálogo y de usuarios Google sin funcionar (sección 7.1).

## 3. Criterios de aceptación originales de P3 frente a la realidad

| Criterio del prompt | Estado | Evidencia |
|---|---|---|
| CRUD crear/editar/eliminar para los 7+1 recursos con permisos | Cubierto | rutas `/admin/<recurso>/new\|<id>\|<id>/delete`, matriz en `app/permissions.py` |
| Validación en `app/validators.py` (requeridos, tipos, rangos, precios ≥ 0) | Cubierto | `validate_catalog` + `validate_room_types`, conectado en 12 rutas (sección 5.5) |
| Lista blanca de campos por recurso | Cubierto | `assign_by_type` con `skip`/`allowed`; `edit_destination` no sobrescribe `id` (test existente) |
| Soft delete donde hay historial (Cliente, Reserva, Paquete, Hotel, Vuelo) | Cubierto | columna `deleted_at` + filtro en `get`/`all_of` (sección 5.2) |
| 409 con mensaje claro si el recurso está referenciado | Cubierto | `_guard_active` (409) en paquetes/hoteles/vuelos/transporte/destinos |
| RN-03: `BookingService.transition` único camino de estado | Cubierto | transiciones confirmar/pendiente/… por ahí; cancelación idempotente (nota 7.5) |
| RN-01 extendida: paquete, vuelo, transporte, hotel por fechas, todo atómico | Cubierto | `UPDATE` condicional en los 3 inventarios + hoteles por solapamiento (sección 5.1) |
| Promociones RF-12: redención y validación `valid_until`/categoría | Cubierto (de fases previas) | `PromotionRedemption` + `current_uses` (tests P3 existentes) |
| RN-05: toda ruta mutante registra auditoría before/after | Cubierto | `test_todas_las_rutas_mutantes_auditan` + audit con before/after en soft delete |
| Aceptación `grep -rn "\.status *=` en rutas | PASS | 0 coincidencias en `app/routes.py` |

## 4. Commits que componen el cierre de P3

| Commit | Contenido |
|---|---|
| `ac226c2` | C1 — endpoints OAuth Google declarados públicos (`PUBLIC_ENDPOINTS`, `ENDPOINT_PERMISSIONS`, `LOGIN_EXEMPT`) |
| `f57fe72` | C2 — borrado de Destino con guard (`destination_reference_status`) + guard estricto para Transporte + fix raíz `assign_by_type` |
| `1f2a5a8` | C3 — soft delete Cliente/Paquete/Hotel/Vuelo + migración `7502a2a67959` + filtros en repos |
| `1f6a4ee` | C4 — RN-01 atómico para vuelo y transporte (`reserve_flight_seats_atomic`, `reserve_transport_seats_atomic`) |
| `bebf6ff` | C5 — validación de catálogo cableada en crear/editar (422 JSON / flash) |
| *(este commit)* | Cierre — refuerzo RN-04 en `store.delete_document`, eliminación de `apply_fields` muerto, acta |

## 5. Reglas de negocio verificadas (evidencia)

### 5.1 RN-01 — No se reserva sin disponibilidad

- Paquete, vuelo, transporte: `UPDATE col = col - n WHERE id = :id AND col >= n`
  con comprobación de `rowcount` (`app/repositories/base.py:decrement_if_available`),
  dentro de la transacción de la reserva. Si un recurso falla, **rollback total**
  con mensaje RN-01 (`test_rn01_paquete_y_vuelo_se_revierten_juntos_si_falla_el_vuelo`).
- Hotel: disponibilidad por solapamiento de fechas
  (`test_rn01_hotel_fechas_solapadas_y_no_solapadas`).
- Un paquete dado de baja (o inexistente) no se puede reservar (`test_baja_logica_no_se_puede_editar_ni_reservar`).

### 5.2 Soft delete (baja lógica)

- `deleted_at` en `packages`, `hotels`, `flights` (migración `7502a2a67959`);
  Cliente y Reserva ya lo tenían.
- `get` y `all_of` excluyen filas con `deleted_at IS NOT NULL` cuando el modelo
  tiene la columna: lo borrado no se lista, no se edita (404) ni se reserva.
- Los 4 `delete_*` marcan `deleted_at` y registran auditoría con **before/after**
  (la diferencia visible es el propio `deleted_at`).
- Los 5 tipos de ocupación ("tiene reservas vinculadas" / "referencias") usan
  guard durante la operación: 409 si hay reservas activas o (Destino/Transporte)
  cualquier referencia.

### 5.3 RN-02 — Toda reserva pertenece a un cliente

Cubierto por las comprobaciones de `create_booking` (cliente obligatorio) y la
tabla `bookings.client_id` (tests de P2/P3 existentes).

### 5.4 RN-03 — Pagos antes de confirmar / "pago verificado"

- "Pago verificado" = `Payment.status == "Completado"`. Tarjeta/PayPal nacen
  Completado; Transferencia/Efectivo `Pendiente_verificacion` hasta
  `POST /payments/<id>/verify`.
- `BookingService.transition` es el único camino de transición de estado usado
  por rutas: confirmar exige ≥1 pago Completado y suma ≥ `MIN_DEPOSIT_PCT` %
  del total (por defecto 100).
- `POST /status` con "Confirmada" sin pago → 422 (cubierto por tests existentes).

### 5.5 C5 — Validación de catálogo

`validators.validate_catalog(kind, data)` y `validate_room_types(data)` con
reglas por recurso (requeridos, importes ≥ 0, enteros no negativos) sobre los
datos **en bruto** del formulario. Cableado en las 12 rutas crear/editar:

- **Edición** (JSON / modal): 422 con `{success:false, errors:[...]}`.
- **Creación con redirect**: `flash(errors)` y vuelve a la lista sin crear.
- Destinos (creación JSON en modal): 422 igual que la edición.

### 5.6 Matriz de permisos (RN-04)

- `app/permissions.py` es la única fuente de verdad; `delete_*` de todos los
  recursos exige `catalog:delete`/`clients:delete` (solo admin). El parametrize
  de RN-04 cubre ahora también Destinos.
- Refuerzo en profundidad: `store.delete_document` vuelve a exigir `admin`
  (deuda P2 → P3 cerrada); `store.delete_activity` ya lo exigía.

## 6. Pruebas (271)

| Bloque | Cubre (añadido en este cierre) |
|---|---|
| `tests/test_p3.py` (54) | RN-01 atómico vuelo/transporte (4), soft delete (6), validación catálogo (7), guard de transporte y destinos (5), create destino por HTTP (1), refuerzo store (1) |
| Resto de la suite (217) | todas las fases anteriores siguen verdes (permisos, IDOR, CSRF, rate limit, seeds, migraciones, respaldo, N+1…) |

Comando: `.\.venv\Scripts\python.exe -m pytest tests -q` → **271 passed**.

## 7. Hallazgos corregidos en esta fase

1. **`assign_by_type` no devolvía el objeto** (`app/repositories/base.py`):
   `create_destination/create_flight/create_transport/create_activity/create_user`
   llamaban `save(None)` → el "crear" de catálogo y el alta de usuarios Google
   fallaban con `UnmappedInstanceError`. Ningún test previo pasaba por la
   creación. Corregido con `return obj` (compatible con los otros usos que
   ignoraban el retorno) y cubierto con `test_crear_destino_via_http`.
2. **Baja lógica inexistente** sobre entidades de catálogo: volaba el historial.
   Corregido con `deleted_at` + migración (ciclo up→down→up probado).
3. **Vuelos/transporte con descuento no atómico**: se sustituyó por `UPDATE`
   condicional y se simplificó el `except` de `create_booking` (la restauración
   manual era redundante contra el rollback).
4. **`store.delete_document` aceptaba empleados** (deuda P2→P3): ahora exige
   admin, igual que la ruta.
5. **`apply_fields` (duplicado de `assign_by_type`) removido** (deuda P2→P3).

## 8. Decisiones tomadas

| Decisión | Motivo |
|---|---|
| Soft delete **solo** para Cliente, Reserva, Paquete, Hotel y Vuelo | Texto de la fase 3 P0/P2: "entidades con historial"; Transporte/Actividad son catálogo volátil y sus referencias se tratan con guard estricto |
| Destino se borra físicamente, pero con guard doble (`bookings` y `catalog`) que bloquea **cualquier** reserva (incl. cancelada) | Un destino con reservas canceladas haría que éstas dejen de renderizar `destination_name`; Cuentan el historial |
| Transporte usa guard estricto (`has_referencing_bookings`, cualquier estado); Paquete/Hotel/Vuelo conservan "reservas activas" | El borrado físico de un transporte rompería reservas; los soft-deleted no rompen nada |
| **422 JSON en edición/módal; flash + redirect al crear** | Coherente con el patrón de clientes y con que el modal consulta JSON |
| El `except` de `create_booking` solo revierte | Los descuentos viven en la misma transacción; restaurar a mano era incorrecto |
| `booking.status = "Cancelada"` se escribe en `bookings_repo.cancel` (no vía `transition`) | Decisión de diseño ya presente: `transition("Cancelada")` delega en `cancel_booking` (que libera cupos de forma idempotente). Ninguna **ruta** toca `status`; el criterio de aceptación se cumple (grep = 0 en `routes.py`). Se deja constancia para revisión en P4 |
| `_catalog_references_destination` excluye paquetes soft-deleted al consultar | Un paquete dado de baja no debe impedir limpiar el destino; el soft-deleted queda con `destination_id` colgando (aceptado, no es visible) |

## 9. Deuda trasladada a fases siguientes

| Pendiente | Fase | Detalle |
|---|---|---|
| `app/billing.py:64` y `:239` mencionan `state.json`; factura sin NCF persistente ni PDF descargable | P4 | NCF secuencial sobre `NcfSequence`, 12 rf actual |
| `update_booking` sin recálculo completo del total por noches de hotel | P4 | precio hotel = `price_per_night × noches × habitaciones` (hoy ignora noches) |
| Notificación "leída" sigue siendo booleana global aunque existe `NotificationRead` | P6 | leído por usuario |
| IA/chat, itinerarios guardables, correo, alertas, subida real de documentos | P6 | RF-10, RF-13, RF-17, RF-20 |
| Los 4 tests SQLAlchemy `Query.get()` marcados "legacy" (1.x) | limpieza | sustituir por `db.session.get` |
| `window.DDN_DATA` sigue existiendo (filtrado por rol) | P7 | eliminar y usar `/api/lookup` |
| PostgreSQL/pg_dump y Dockerfile/despliegue | P9 | driver, Docker, CI, cobertura ≥ 80 % |

## 10. Cómo reproducir

```powershell
# 1) Suite completa (271)
.\.venv\Scripts\python.exe -m pytest tests -q

# 2) Migración de soft delete (ciclo completo sobre SQLite)
$env:FLASK_APP="run.py"
.\.venv\Scripts\python.exe -m flask db upgrade
.\.venv\Scripts\python.exe -m flask db downgrade dd6986e58c40
.\.venv\Scripts\python.exe -m flask db upgrade

# 3) Aceptaciones de P3
#    - ninguna ruta cambia booking.status:
git grep -n '\.status *=' -- app/routes.py     # -> 0 coincidencias
#    - state.json solo en la deuda P4 conocida:
git grep -n 'state\.json' -- app/              # -> app/billing.py:64 y :239
```

Credenciales demo (README): `admin@ddntravel.com`, `sofia.v@ddntravel.com`,
`roberto.gomez@gmail.com` — clave `ddn123`.