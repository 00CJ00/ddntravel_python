# P6 — Acta de cierre: Itinerarios, documentos, alertas e IA

> Evidencia de la fase P6 (servicios backend de RF-10, RF-13, RF-17 y
> RF-20), actualizada tras integrar `origin/main` el 2026-10-15.
>
> Rama: `fase_p6`. `origin/main` está integrado localmente; no se hizo push.
> P3/P4 se consideran estables y no se refactorizan; P5 es de otro
> compañero y queda fuera de esta fase. Las referencias de implementación
> anteriores al apartado 11 son el registro histórico de la rama; si difieren,
> el apartado 11 describe el estado integrado vigente.

## 1. Veredicto

| Comprobación | Resultado |
|---|---|
| Suite automática integrada | **322 passed, 0 failed** (156.92 s; 5 warnings deprecación) |
| Itinerarios CRUD por reserva con JSON validado | **PASS** (`POST\|GET\|PUT\|DELETE /bookings/<id>/itinerary`; 6 tests) |
| Documentos: extensiones, firmas, 5 MB, UUID, descarga con propiedad | **PASS** (8 tests; ajeno → 403) |
| Voucher PDF idempotente integrado a la confirmación | **PASS** (4 tests; fallo aislado con `VOUCHER_FALLIDO`) |
| Lectura de notificaciones por usuario | **PASS** (`NotificationRead`; 5 tests con correo/duplicados) |
| Alertas + `flask alerts run` idempotente | **PASS** (7 tests; CLI real `3 creadas` → `0 creadas, 3 omitidas`) |
| IA sin PII, esquema, timeout, persistencia, auditoría, chat | **PASS** (8 tests + `test_ai_service.py` intacto) |
| Ninguna **ruta** asigna `booking.status` | **PASS** (`grep .status\s*= app/routes.py` → 0; prisma P3 intacto) |
| Migraciones `flask db upgrade` desde cero | **PASS** (2 nuevas, reversibles, batch; `tests/test_migrations.py`) |
| `git diff --check` | **PASS** (limpio) |
| README + `.env.example` documentan P6 | **PASS** (sin secretos) |

## 2. Contexto

La fase P6 partía del acta P4 (`docs/P4_verificacion.md`), que dejaba como
deuda: `Notification.read` global con `NotificationRead` sin uso, subida
real de documentos, itinerarios guardables, correo, alertas e IA (RF-10,
RF-13, RF-17, RF-20). La rama `fase_p6` ya contenía P4 commiteado
(`3838c1c` + merges); el diagnóstico (sin editar) encontró estas brechas,
que este acta cierra por bloques:

1. Sin persistencia de itinerarios (modelo `Itinerary` huérfano, sin repo
   ni rutas) y prompts de Gemini con **nombres reales de clientes**.
2. Documentos solo-metadatos (`file_name` de formulario, sin archivo, sin
   descarga); voucher P4 sin PDF.
3. Lectura global compartida; sin correo, sin plantillas, sin claves
   anti-duplicado.
4. Sin detectores, sin CLI de alertas, sin scheduler.
5. `generate_gemini_json` sin timeout, sin validación de esquema y con
   reintentos solo ante saturación; predictivo sin marca temporal; llamadas
   de recomendaciones/itinerario sin auditar.

## 3. Criterios de aceptación originales de P6 frente a la realidad

| Criterio del prompt | Estado | Evidencia |
|---|---|---|
| RF-10: conservar `/api/ai/generate-itinerary`; CRUD asociado a reserva, JSON validado, dueño sí / ajeno no, DELETE solo admin | Cubierto | 4 rutas + `validate_itinerary_content`, sección 5.1 |
| RF-17 subida: `pdf/jpg/png`, `secure_filename`, magic bytes, no exe/firmas falsas/vacíos, 5 MB, `UPLOAD_DIR` fuera de `static/`, UUID, errores gestionados | Cubierto | `app/repositories/documents.py`, `MAX_CONTENT_LENGTH`, sección 5.2 |
| RF-17 permisos: propia sí, ajena 403, eliminar solo admin | Cubierto | `download_document` (403 deliberado y documentado), matriz intacta |
| Voucher PDF real al confirmar, idempotente, sin corromper la transacción | Cubierto | `store.generate_booking_voucher`, sección 5.3 |
| Vencimiento `vigente/por vencer/vencido` calculado, con fronteras | Cubierto | `expiry_status` + propiedad del modelo, tests de límites |
| RF-13 `NotificationRead`, 3 eventos, Flask-Mail con respaldo, try/except, sin PII ajena, sin commits del correo | Cubierto | `app/email_service.py`, ganchos post-commit, sección 5.4 |
| Alertas: 4 detecciones, `flask alerts run`, idempotencia + UNIQUE, auditado; scheduler solo con flag | Cubierto | `app/alerts.py`, CLI y scheduler, sección 5.5 |
| RF-20: sin PII a Gemini, esquema + defaults + respaldo, timeout/reintentos, persistencia con fecha, auditoría sin PII, agregados, chat por palabras | Cubierto | `app/ai_service.py`, `Setting.updated_at`, sección 5.6 |
| Tests por bloque sin debilitar los existentes, sin credenciales reales | Cubierto | `tests/test_p6_*.py`, sección 6 |
| README + `.env.example` | Cubierto | sección P6 en README, vars ilustrativas |

## 4. Commits que componen el cierre de P6

| Commit | Contenido |
|---|---|
| `3838c1c` (+ merges) | Base previa en la rama: P4 y trabajo anterior ya integrados |
| `92f6c22` | Bloques 2–7: itinerarios, documentos, voucher, notificaciones/correo, alertas/scheduler, IA/chat, tests, docs y 2 migraciones |
| *(este commit)* | Acta `docs/P6_verificacion.md` |

## 5. Reglas de negocio verificadas (evidencia)

### 5.1 Itinerarios (RF-10)

- `validate_itinerary_content` (`app/validators.py`): esquema del generador
  real (`destination` + `days[{dayNumber,title,...}]` obligatorios; resto con
  defaults; tope 60 días). Con errores → 422 sin persistir ni auditar.
- Repo `itineraries.py` (upsert, solo `flush`) + `store` con auditoría y
  `_commit` central. Rutas con `booking_id` solo de la URL y `owned_or_404`
  (ajeno → 404, convención P1). POST duplica → 409; PUT hace upsert; DELETE
  exige `itinerary:delete` (admin, único permiso añadido a la matriz).
- Sin migración: la tabla `itineraries` existe desde P2.

### 5.2 Documentos (RF-17, sin voucher)

- `app/repositories/documents.py`: extensiones `pdf/jpg/jpeg/png`, firma por extensión
  (`%PDF`, `FF D8 FF`, PNG), vacíos y > 5 MB rechazados, verificación
  post-escritura (incompleto → borra y error), UUID hex + extensión,
  borrado defensivo, `expiry_status` con meses naturales estrictos
  (exactamente a 6 meses = `vigente`; hoy = `por vencer`; ayer = `vencido`).
- `store.upload_document`: disco→fila→commit; si la BD falla, borra el
  archivo; si el disco falla, no hay fila. `delete_document` borra además
  el físico (fallo → warning, sin romper).
- `GET .../download`: propiedad propia o vía reserva; ajeno → **403**
  (exigencia explícita RF-17; desviación deliberada del 404 documentada
  en el docstring). `stored_name` siempre vía `basename` (sin traversals).

### 5.3 Voucher PDF

- `generar_pdf_voucher` (ReportLab, solo datos del modelo) +
  `store_bytes`. `ensure_voucher_pdf` corre **después** de cada commit que
  puede confirmar (crear, pagar, verificar, cambiar estado, editar):
  no-Confirmada → nada; con archivo → no-op; fila P4 heredada → la adopta;
  si no → crea. Nunca lanza (`VOUCHER_FALLIDO` + rollback propio).
- Se retiró el voucher solo-metadatos dentro de la transacción del pago
  (ningún test lo exigía).

### 5.4 Notificaciones y correo (RF-13)

- Lectura por usuario (`get_read`/`mark_read_by` idempotente);
  `notification_read_by` = fila propia **o** flag global heredado; badge
  por usuario; plantillas intactas (P8 es dueño del UI fino).
- `notifications.event_key` UNIQUE (migración `e6ccd1447029`, reversible):
  confirmación/pago/cancelación no se duplican ante reprocesos
  (`_notify` omite si la clave existe).
- `app/email_service.py`: 3 plantillas (código/destino/importe/recibo, sin PII
  ajena); SMTP solo con `MAIL_SERVER` + remitente, si no consola/log;
  `try/except` en el envío y en los 3 ganchos post-commit del store.
- `Flask-Mail==0.10.0` fijada; `mail.init_app` inofensivo sin config.

### 5.5 Alertas y scheduler

- `app/alerts.py`: pasaporte (`expiry < salida + 6 meses`, salida futura),
  saldo > 0 con salida hoy…+15 (hoy incluido), `available/total ≤ 0.2`
  (total `total_slots` o `max_capacity`; total 0 se ignora), `Pendiente`
  > 72 h sin `Completado` (sin reembolsos; `created_at` ausente se omite).
- Clave `alert:tipo:entidad:id:fecha` sobre el UNIQUE + commit por alerta
  con rollback ante carrera + auditoría `ALERTAS_GENERADAS` por corrida.
- `flask alerts run` (grupo registrado en la fábrica) verificado en BD
  fresca con seed: `3 creadas` → `0 creadas, 3 omitidas`. Scheduler diario
  solo con `ENABLE_SCHEDULER=1`, nunca en tests ni en el padre del
  reloader, instancia única, fallos a log (`APScheduler==3.11.3` fijada).

### 5.6 IA (RF-20)

- Privacidad: `anonymize_clients` (alias `Cliente A` + categoría/
  presupuesto/conteos) y `sanitize_profile` (el dict del frontend nunca
  sale); agregados (`aggregate_signals`: frecuentes ≥ 3 viajes, top
  destinos, meses > 1.25× media) en `ai_service`, sin crear
  `app/analytics.py` (P5 ajeno).
- `generate_gemini_json` con `schema=`: timeout por llamada vía hilo
  (firma SDK intacta para el mock existente), como máximo 2 intentos por
  modelo solo ante fallos transitorios, salida inválida → siguiente
  modelo → respaldo; `last_provider/last_used_model` para auditoría.
- Esquemas: predictivo (requeridos + clamp 0–100), recomendaciones
  (paquetes válidos o respaldo), itinerario (reutiliza RF-10).
- `Setting.updated_at` (migración `4743e90aee9d`) para la marca temporal
  del predictivo; recomendaciones/itinerario auditan proveedor/modelo/
  parámetros no identificativos.
- Chat: ya comparaba por palabras completas; cubierto con tests
  (`hi` vs `which`, mayúsculas, subcadenas como `Holanda`).

## 6. Pruebas P6 por bloque + resto de suite

| Bloque | Cubre |
|---|---|
| Itinerarios (6) | crear+consultar, 6 inválidos → 422, edición, propiedad 404, CRUD del dueño, DELETE 403/200 |
| Documentos (8) | `.exe`, firma falsa, vacío, pdf/jpg/png con bytes idénticos, > 5 MB, descarga 200/403, borrado fila+archivo, fronteras de vencimiento |
| Voucher (4) | PDF válido, idempotencia, adopción heredada, fallo aislado con auditoría |
| Notificaciones | lectura individual, eventos y correo, SMTP caído, respaldo consola; incluye prueba de `event_key` |
| Alertas | 4 detectores, CLI idempotente, UNIQUE en BD, scheduler apagado por defecto |
| IA | prompts sin PII, normalización de respuestas, respaldo ante caída/JSON, timeout, persistencia, auditoría sin PII, chat |

La suite antigua consolidada `tests/test_p6.py` fue retirada al integrarse los
tests P6 actualizados, separados por bloque (`tests/test_p6_*.py`). El resultado
final de la suite integrada se registra en el apartado 11.

## 7. Hallazgos corregidos en esta fase

1. **Contador de alertas mentía** (`run_alerts`): `_notify` omitía duplicados
   pero el contador sumaba igual (CLI real: segunda corrida decía "3
   creadas" con 0 filas nuevas). `_notify`/`add_notification` ahora devuelven
   si crearon; test CLI exige "0 creadas" en la repetición.
2. **Nombres reales al proveedor** (`ai_service.get_predictive_analytics` y
   `get_recommendations`): se anonimizan antes del prompt; verificado con
   proveedor mockeado capturando el contenido.
3. **`Booking.client_name` sin setter** (propiedad derivada): los tests
   construyen reservas sin ese kwarg.
4. **Dos ediciones erróneas propias** (docstrings recortados en
   `validators.py` y `store.py`): revertidas en el acto con diff vacío
   verificado antes de continuar.
5. **Chat**: se confirmó que ya usaba palabras completas; no hubo que
   corregirlo, solo cubrirlo.
6. **Fallo OAuth preexistente**: no reprodujo en esta ejecución; no se modificó.

## 8. Decisiones tomadas

| Decisión | Motivo |
|---|---|
| PUT de itinerario hace upsert; POST duplica → 409 | Semántica crear/editar limpia + idempotencia de reintentos |
| Descarga ajena → 403 (no 404) | Exigencia explícita RF-17; documentado como desviación deliberada |
| Sin fecha de vencimiento → `vigente` | Un voucher/pasaporte sin fecha no tiene qué vencer |
| Voucher post-commit con auditoría propia | Un fallo de PDF/disco nunca corrompe pago ni reserva |
| Fila global `read` conservada como "leído para todos" | Compatibilidad con UI y datos existentes; lo nuevo es por usuario |
| Agregados en `ai_service`, no en `app/analytics.py` | No invadir P5 |
| Timeout fuera del SDK | El mock existente fija la firma `generate_content` |
| Scheduler apagado por defecto y fuera de tests | Evitar procesos colgados e instancias dobles |

## 9. Deuda trasladada a fases siguientes

| Pendiente | Fase | Detalle |
|---|---|---|
| Scheduler y `FOR UPDATE` en PostgreSQL real | P9/infra | probado SQLite + multihilo; falta PG |
| Resaltado de fila de notificaciones por usuario | P8 | el badge ya es por usuario; el UI fino es frontend |
| Fallo OAuth sensible al entorno | compañero asignado | sin tocar |
| `window.DDN_DATA`, Tailwind, Docker, cobertura | P7–P9 | fuera de alcance |

## 10. Cómo reproducir

```powershell
# 1) Suite completa
python -m pytest tests -q

# 2) Tests P6 por bloque
python -m pytest tests/test_p6_*.py tests/test_ai_privacy.py -q

# 3) Migraciones P6 sobre SQLite
$env:FLASK_APP="run.py"
python -m flask db upgrade
python -m flask db downgrade b7a4d915c2f0
python -m flask db upgrade

# 4) Alertas en BD fresca con seed (idempotencia real)
$env:DATABASE_URL="sqlite:///$env:TEMP/p6alerts.db"
python -m flask --app run db upgrade
python -m flask --app run seed
python -m flask --app run alerts run   # -> N creadas
python -m flask --app run alerts run   # -> 0 creadas

# 5) Aceptaciones P6
git grep -n '\.status *=' -- app/routes.py          # -> 0 coincidencias
git grep -n 'c\.name\|c\.email' -- app/ai_service.py # -> 0 (prompts sin PII)
```

Credenciales demo (README): `admin@ddntravel.com`, `sofia.v@ddntravel.com`,
`roberto.gomez@gmail.com` — clave `ddn123`.

## 11. Integración con `origin/main` (2026-10-15)

- Se integraron los cambios más recientes de `origin/main` con los dos commits
  de `fase_p6`. Para las implementaciones duplicadas se conservaron los
  archivos P6 más recientes y sus pruebas separadas por bloque.
- Se mantuvieron además las migraciones locales `e6ccd1447029` (clave única
  `notifications.event_key`) y `4743e90aee9d` (`settings.updated_at`).
  `c914e8a73d20` une esas revisiones con la migración de alertas
  `a41bd9e7206c`; Alembic queda con una sola cabeza.
- Se preservó la idempotencia de notificaciones por `event_key` en el
  repositorio y el store, con cobertura en
  `test_event_key_hace_idempotente_la_creacion_de_notificaciones`.
- Al combinarse, quedó duplicada una versión antigua de
  `validate_itinerary_content`; se retiró para que las rutas usen el contrato
  de lista de errores y los itinerarios vuelvan a aceptar los payloads válidos.
- El test consolidado `tests/test_p6.py` comprobaba rutas y contratos de la
  implementación previa y fallaba contra las API P6 actuales. Se retiró y se
  conservaron los tests mantenidos en `tests/test_p6_*.py`.
- `python -m pytest tests -q`: **322 passed, 0 failed**, 5 warnings en 156.92 s.
- `flask db heads`: una sola cabeza, `c914e8a73d20`.
- `git diff --check`: limpio tras resolver la última línea en blanco.
