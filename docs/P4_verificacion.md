# P4 — Acta de cierre: Facturación, NCF y pagos

> Evidencia de la fase P4 (facturación RD, NCF secuencial y persistente,
> registro de pagos RF-11, factura PDF, anulación/reembolso). Incluye el
> diagnóstico de brechas sobre la implementación previa y las correcciones
> aplicadas en la rama `p4`. Todos los números son reproducibles con la
> sección final.
>
> Rama: `p4`. **Sin merge ni push**: queda pendiente de revisión.
> P3 se considera estable y no se refactoriza; P5 es de otro compañero y
> queda fuera de esta fase.

## 1. Veredicto

| Comprobación | Resultado |
|---|---|
| Suite automática | **258 passed, 1 failed** (el fallo es el test preexistente de Google OAuth, ajeno a P4; sección 7.5) |
| `next_ncf(prefix)` atómico y reversible | **PASS**: PG `FOR UPDATE`; SQLite `UPDATE ... WHERE` + `rowcount`; ante NCF agotado el pago revierte íntegro (sección 5.1) |
| `UNIQUE` de NCF y de `(booking_id, reference)` | **PASS**: restricción real en BD + modelo; NULL múltiples permitidos (sección 5.2) |
| RF-11: monto, saldo, método, referencia, reserva cancelada | **PASS**: Decimal, 422 sin persistencia (sección 5.3) |
| Factura PDF válida con importes del pago | **PASS**: `%PDF`, emisor desde config, NCF/fecha/referencia, subtotal y total del pago (sección 5.4) |
| Anulación/reembolso solo admin, vía `transition` | **PASS**: Anulado, recálculo, NCF B04 propio, FK al original, sin doble reembolso (sección 5.5) |
| Concurrencia: 20 hilos → 20 NCF únicos y consecutivos | **PASS** (`test_ncf_concurrente_20_pagos_unicos_y_consecutivos`) |
| Ninguna **ruta** asigna `booking.status` | **PASS** (`grep .status\s*= app/routes.py` → 0; solo `BookingService.transition`) |
| Sin `store.state`, `generar_ncf` ni campos inexistentes | **PASS** (grep → 0; sección 7.1) |
| Migración `flask db upgrade/downgrade` | **PASS** sobre SQLite (verificado por `tests/test_migrations.py`) |
| README documenta simulación académica (no DGII) | **PASS** (README + `.env.example` con `AGENCY_*`) |

## 2. Contexto

La fase P4 partía del acta P3 (`docs/P3_verificacion.md`), que dejaba como
deuda conocida: `app/billing.py` con referencias a `state.json`, factura sin
NCF persistente ni PDF descargable, y `generar_ncf` del sistema anterior.
La rama `p4` ya contenía una primera implementación
(`e1839ff`: NCF secuencial, factura PDF real, `/void` con reembolso B04);
el diagnóstico (sin editar) encontró estas brechas, que este acta cierra:

1. `next_ncf` hacía lectura-modificación-escritura con `flush`, sin
   protección contra carreras; no distinguía PostgreSQL de SQLite.
2. `register_payment` tragaba (`except: pass`) cualquier fallo de NCF y
   confirmaba el pago **sin NCF**; el agotamiento no revertía nada.
3. Los reembolsos (`kind=reembolso`, `Completado`) **sumaban** en el saldo
   pendiente y en el cómputo de confirmación de `BookingService.transition`.
4. `void_payment` decrementaba `amount_paid` aunque el pago anulado nunca
   hubiera sumado (pendiente de verificación), reutilizaba `reference` del
   original (colisión futura con la UNIQUE) y no enlazaba al pago original.
5. Sin restricción `UNIQUE(booking_id, reference)` a nivel de BD ni de modelo.
6. La factura mostraba la fecha de hoy en vez de la del pago y el pie tenía
   emisor hardcodeado.

## 3. Criterios de aceptación originales de P4 frente a la realidad

| Criterio del prompt | Estado | Evidencia |
|---|---|---|
| Bugs: sin `store.state`, `get_payment`, imports `date`/`send_file`/`BytesIO`/`ParagraphStyle`, campos reales, sin fila `[None, None]` | Cubierto | `app/billing.py`, `app/routes.py`, `repositories/payments.py:get_payment`, `store.get_payment` |
| `next_ncf(prefix)` sobre `NcfSequence`, atómico en la transacción del pago; B02/B01(RNC)/B04; error claro; UNIQUE; eliminar `generar_ncf` | Cubierto | `app/billing.py:next_ncf`, `validar_rnc`, UNIQUE `ncf` (migración inicial), sección 5.1 |
| Emisor desde config (`AGENCY_*`), no hardcodeado | Cubierto | `app/config.py`, `payment_factura`, pie del PDF parametrizado |
| RF-11: monto > 0 y ≤ saldo (422), Decimal, no pagar cancelada, método válido, UNIQUE por referencia, NCF en la misma transacción | Cubierto | `store.register_payment` + `POST /payments/new` → 422, sección 5.3 |
| PDF en `GET /payments/<id>/factura` (admin/employee/dueño) con emisor, cliente, NCF, fecha, ítems, subtotal y total | Cubierto | `%PDF` verificado en test; importes del pago, no del total de la reserva |
| `POST /payments/<id>/void` solo admin, motivo obligatorio, Anulado, recálculo vía `transition` (puede volver a Pendiente), NCF nunca reutilizado, reembolso B04 referenciando el original, auditoría | Cubierto | `store.void_payment`, FK `original_payment_id`, sección 5.5 |
| Tests: 20 concurrentes, sobrepago, anulación, `%PDF`, permisos/propiedad | Cubierto | `tests/test_p4.py` (12 tests), sección 6 |
| Aceptación manual reserva → pagos → confirmada → PDF → anulación | Cubierto por tests equivalentes | flujo en `test_anulacion_reviste_estado_y_emite_nota` + factura + reembolso B04 |

## 4. Commits que componen el cierre de P4

| Commit | Contenido |
|---|---|
| `e1839ff` | Base previa en la rama: NCF secuencial inicial, NCF en `register_payment`, factura PDF real, `/void` con reembolso B04 |
| *(cambios locales sin commit)* | A — `next_ncf` atómico real (FOR UPDATE / UPDATE+rowcount, agotada/inactiva/vencida) |
| *(cambios locales sin commit)* | C — `register_payment` transaccional (422, rollback integral, exclusión de reembolsos) + 422 en ruta |
| *(cambios locales sin commit)* | D — `void_payment` endurecido (`was_completed`, sin doble reembolso, FK al original, triple auditoría) |
| *(cambios locales sin commit)* | B — migración `430e52d52ac7` (FK + UNIQUE) + UNIQUE en el modelo |
| *(cambios locales sin commit)* | E — 5 tests nuevos (concurrencia 20 hilos, doble anulación, pendiente, B04, 422 HTTP) |
| *(cambios locales sin commit)* | F — factura con fecha/referencia del pago, pie desde config, README + `.env.example` (DGII) |

## 5. Reglas de negocio verificadas (evidencia)

### 5.1 NCF secuencial, atómico y reversible

- `next_ncf(prefix)` (`app/billing.py:63-117`): auto-crea la secuencia si no
  existe; rechaza inactiva/vencida/agotada con `ValueError` claro; en
  PostgreSQL bloquea la fila (`FOR UPDATE`); en SQLite incrementa con
  `UPDATE ... WHERE current < max_number` (+ `rowcount`, con semántica "sin
  tope" si `max_number` es 0/None como antes). Devuelve exactamente el número
  reservado (`prefijo + 8 dígitos`, p. ej. `B0200000001`, 11 caracteres).
- No confirma: participa de la transacción del llamador. Verificación
  empírica con secuencia B02 agotada (5/5): `register_payment` → 422
  "agotada", pagos 2→2 (sin pago parcial persistido), secuencia 5/5
  (contador sin avanzar), reserva intacta (0.00/Pendiente/Pendiente).
- Prefijo: `B01` si `validar_rnc(client.document_id)`, si no `B02`
  (`NCF_PREFIX*` por config); `B04` (`NCF_CREDITO_PREFIX`) para reembolsos.

### 5.2 Unicidad

- `ncf` UNIQUE (migración inicial P2, conservada).
- `uq_payments_booking_reference` en modelo (`app/models/payment.py`) y
  migración `430e52d52ac7` (batch, SQLite/PG, con `downgrade`). La migración
  aborta con mensaje claro si hay duplicados históricos (seed limpio: 2
  pagos con referencias distintas). `reference ""` se guarda como `NULL`
  (`reference or None`), y los NULL no colisionan en ningún motor —
  probado por toda la suite (decenas de pagos sin referencia conviven).

### 5.3 Registro de pago (RF-11)

- `store.register_payment`: `amount > 0`, método en `PAYMENT_METHODS`, no
  pagar `Cancelada`, `amount ≤ saldo` (solo `Completado` de `kind="pago"`;
  anulados y reembolsos excluidos), referencia única por reserva; todo con
  `Decimal`. Fallos de validación → `{"success": False, "status": 422}`.
- `POST /payments/new` traduce esos fallos a **HTTP 422** con la misma
  plantilla (el resto de fallos conserva flash + redirect P3).
- Toda la mutación (pago, NCF, transición, voucher, auditoría,
  notificación) va en un `try` con `_rollback()` ante `IntegrityError`
  (referencia duplicada en carrera), `ValueError` (NCF) o excepción
  inesperada. Repositorios solo hacen `flush`; `audit.record` solo `add`;
  commit único en `DataStore._commit` (sin commits prematuros ni dobles).

### 5.4 Factura PDF

- `GET /payments/<id>/factura` (`payments:invoice` + `owned_or_404`): emisor
  (`AGENCY_*`), cliente (nombre + documento), NCF, **fecha del pago**,
  referencia y código de reserva en el concepto, un ítem por el **importe
  del pago** (un parcial no muestra el total de la reserva como cobrado),
  subtotal y total coherentes. `BytesIO` + `send_file`, pie con dirección y
  teléfono desde config.

### 5.5 Anulación y reembolso

- `POST /payments/<id>/void` solo admin (`payments:void`), motivo
  obligatorio. Marca `Anulado` (+ `voided_at`/`void_reason`), sin borrado
  físico. Recalcula `amount_paid` **solo si el pago estaba Completado** y
  retransita vía `BookingService.transition` (Confirmada→Pendiente;
  la rama `Pendiente` ya existía en P3, no se añadió transición nueva).
- NCF original intacto y nunca reutilizado. Reembolso `kind="reembolso"`
  con recibo propio, NCF B04 propio y `original_payment_id` → pago original
  (FK autorreferenciada + relación). Referencia `NC-<original>` (o NULL)
  para no colisionar con la UNIQUE. Sin pago verificado no hay reembolso
  (nada que devolver) pero la anulación queda auditada.
- Segunda anulación imposible por partida doble: `status` + comprobación de
  reembolso existente (`test_segunda_anulacion_no_duplica_reembolso`).
- Auditoría: `ANULAR_PAGO` (before/after), `REEMBOLSO_CREADO`,
  `ACTUALIZAR_PAGO_RESERVA`.

## 6. Pruebas (12 en `tests/test_p4.py` + resto de suite)

| Bloque | Cubre |
|---|---|
| NCF formato/secuencia, sobrepago store, PDF `%PDF`, anulación, motivo, employee→403 (7, base previa) | comportamiento P4 ya existente |
| Concurrencia 20 hilos (sesiones independientes, BD en disco) | 20 NCF únicos, mismo prefijo, consecutivos, 20 pagos persistidos |
| Doble anulación, anular pendiente, reembolso B04, sobrepago HTTP 422 | reglas endurecidas en este cierre |

Comando: `python -m pytest tests -q` → **258 passed, 1 failed**
(el fallo es OAuth preexistente, sección 7.5). P4 relevantes:
`test_p4 + test_p3 + test_idor + test_permissions + test_migrations + test_seed + test_store`
→ 134 passed salvo el OAuth.

## 7. Hallazgos corregidos en esta fase

1. **`next_ncf` con condición de carrera** (`app/billing.py`): leer-modificar-
   escribir con `flush` permitía duplicados concurrentes. Corregido con
   incremento condicional + `rowcount` (SQLite) y `FOR UPDATE` (PG).
2. **`except: pass` alrededor del NCF** (`store.register_payment`): un fallo
   de secuencia dejaba el pago confirmado sin NCF. Ahora propaga, revierte
   todo y responde 422.
3. **Reembolsos contados como pagos** (saldo y `transition`): un reembolso
   `Completado` inflaba el "verificado". Excluidos por `kind != "reembolso"`
   en ambos cómputos (anulados ya se excluían por `status`).
4. **Anulación de pago no verificado restaba importe** que nunca se sumó y
   creaba un reembolso sin deuda real. Ahora solo descuenta/crea reembolso
   si estaba `Completado`.
5. **Reembolso con la misma `reference`** que el original: colisionaría con
   la nueva UNIQUE. Ahora usa `NC-<ref>` o NULL y enlaza por FK.
6. **Factura con fecha de hoy y pie hardcodeado**: ahora fecha del pago y
   emisor 100 % desde config.
7. **Fallo OAuth preexistente** (`test_permissions.py::test_google_oauth_es_publico_y_redirige_al_proveedor`):
   exige `main.google.login/authorized` en `PUBLIC_ENDPOINTS`, retirados en
   el merge P3. Reproducido con los cambios de P4 guardados (`stash`) con
   idéntica firma → **no es regresión de P4**; asignado a otro compañero,
   no se toca aquí.

## 8. Decisiones tomadas

| Decisión | Motivo |
|---|---|
| Timeout de Gemini fuera del SDK (no se toca la firma `generate_content`) | P6/AI; aquí solo se deja constancia: el mock de `test_ai_service.py` fija esa firma |
| `max_number` 0/None = sin tope (como antes) | No cambiar semántica de secuencias existentes |
| Reembolso sin NCF propio si `next_ncf(B04)` falla → revierte toda la anulación | La anulación es atómica: o todo (incluida nota) o nada |
| Anular pendiente-verificación no crea reembolso | No hay importe verificado que devolver; solo marca + auditoría |
| UNIQUE incluye NULL sin colisión | Comportamiento estándar SQLite/PG; `""` se normaliza a NULL |
| 422 solo para rechazos RF-11 en `/payments/new` | El resto de fallos conserva el patrón P3 (flash + redirect) |
| Sin `analytics.py` propio | P5 es de otro compañero; los agregados vivirán en P6 sin invadirlo |

## 9. Deuda trasladada a fases siguientes

| Pendiente | Fase | Detalle |
|---|---|---|
| Camino PostgreSQL `FOR UPDATE` sin cobertura automatizada aquí | P9/infra | probado SQLite + file-DB multihilo; falta PG real |
| Pagos históricos del seed sin NCF (`ncf` nullable) | — | `/ncf` devuelve `""`; backfill opcional no realizado |
| Fallo OAuth preexistente | compañero asignado | restaurar 4 líneas en `app/permissions.py` o ajustar el test |
| `Notification.read` global + `NotificationRead` sin uso, subida real de documentos, itinerarios, alertas, IA | P6 | RF-10/13/17/20 en curso en `fase_p6` |

## 10. Cómo reproducir

```powershell
# 1) Suite completa (258 passed + 1 fallo OAuth preexistente)
python -m pytest tests -q

# 2) Solo P4 (12 tests, incluye concurrencia de 20 hilos)
python -m pytest tests/test_p4.py -q

# 3) Migración P4 (ciclo completo sobre SQLite)
$env:FLASK_APP="run.py"
python -m flask db upgrade
python -m flask db downgrade dd6986e58c40
python -m flask db upgrade

# 4) Aceptaciones de P4
git grep -n '\.status *=' -- app/routes.py     # -> 0 coincidencias
git grep -n 'generar_ncf\|store\.state' -- app/ # -> 0 coincidencias
git grep -n 'payment\.total_price\|payment\.client_email\|payment\.creation_date' -- app/ # -> 0

# 5) Flujo manual: reserva → pago parcial → pago final → Confirmada
#    → GET /payments/<id>/factura (PDF) → POST /payments/<id>/void
#    (motivo) → Pendiente + reembolso B04
```

Credenciales demo (README): `admin@ddntravel.com`, `sofia.v@ddntravel.com`,
`roberto.gomez@gmail.com` — clave `ddn123`.
