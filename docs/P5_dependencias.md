# P5 — Dependencias y decisiones

> El acta completa de verificación está en `docs/P5_verificacion.md`.

## Decisión: búsqueda restringida por rol → 0 resultados, nunca 403

**Regla:** Cuando un usuario no tiene permiso para ver un tipo de búsqueda, la respuesta es `{"items": [], "total": 0, ...}` (conjunto vacío), no un error 403.

**Razón:** Un 403 revela que el endpoint existe pero está prohibido (información útil para un atacante). Un conjunto vacío es una respuesta "silenciosa" más segura y consistente con la semántica de búsqueda (sin coincidencias = lista vacía, no error).

**Aplicación:**

| Tipo | Restricción | Comportamiento |
|------|-------------|----------------|
| `type=clients` | Solo admin/employee | Cliente obtiene `total: 0` |
| `type=bookings` | Cliente solo ve las suyas | Si no tiene reservas, `total: 0` |

**Tests que lo garantizan:**
- `tests/test_p5_search.py::test_search_clients_solo_staff` — aserta `total == 0` para rol cliente
- `tests/test_p5_search.py::test_search_bookings_cliente_ve_solo_suyas` — aserta que solo ve reservas propias

---

## Deuda heredada: Notification.read (booleano global)

**Estado en P5:** El campo `Notification.read` (Boolean global) existe en el modelo (`app/models/notification.py:19`) pero **no se usa** para el estado de lectura. El repositorio usa `NotificationRead` por usuario (`app/repositories/notifications.py`).

**Veredicto:** Deuda resuelta en la práctica (P6 la migró a `NotificationRead`), pero el campo viejo quedó como código muerto. No es una deuda abierta; es limpieza pendiente.

---

## Dependencias con P4 y P6 (ya cerradas)

P4 (facturación/NCF/pagos) y P6 (itinerarios/documentos/alertas/IA) están mergeados en `main`. Este plan se ejecuta sobre `main` sin riesgo de conflicto.

**Commit de base:** `d822914` (main con P4+P6 integradas).
