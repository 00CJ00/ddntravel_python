# P5 — Acta de cierre: Reportes, búsqueda avanzada y estadísticas

> Evidencia de la fase P5 (RF-14 dashboard, RF-15 reportes PDF/XLSX, RF-16
> búsqueda avanzada). Rama `fase-P5`, base `main @ d822914` (P4 y P6 ya
> integradas). **Sin merge ni push**: queda pendiente de revisión.
>
> Todos los números son reproducibles con la sección final.

## 1. Veredicto

| Comprobación | Resultado |
|---|---|
| Suite automática | **388 passed** (`pytest tests -q`) |
| `/api/search` (RF-16) con filtros, paginación y 422 | **PASS** (`tests/test_p5_search.py`, 16 tests) |
| Alcance por rol en búsqueda | **PASS**: cliente → `clients`/`hotels`/`flights`/`transports` total 0; `bookings` solo suyas; `packages`/`destinations`/`activities` abiertos (catálogo público) |
| Sin caracteres CJK en `*.py`/`*.md` | **PASS** (`git grep -nP "[\x{4e00}-\x{9fff}]"` → 0) |
| Reportes PDF/XLSX (RF-15) bookings/clients/occupancy | **PASS** (`tests/test_p5_reports.py`, 12 tests) |
| Reportes payments/revenue | **PASS** (neto = pagos − reembolsos) |
| Anti-inyección de fórmulas XLSX | **PASS**: prefijo `'` en `=`, `+`, `-`, `@` |
| `analytics.py` puro y testeable (RF-14) | **PASS** (`tests/test_p5_analytics.py`, 11 tests) |
| `/api/dashboard/stats` | **PASS**: admin 200, cliente 403 |
| `FREQUENT_CLIENT_MIN` y `PEAK_SEASON_FACTOR` configurables | **PASS** (`app/config.py`) |
| Permisos declarados para todas las rutas nuevas | **PASS** (`tests/test_permissions.py`) |

## 2. Decisiones

### 2.1 Búsqueda restringida por rol → 0 resultados, nunca 403

Cuando un usuario no tiene permiso para un tipo de búsqueda, la respuesta es un
conjunto vacío (`total: 0`), no 403. Un 403 revela que el endpoint existe pero
está prohibido; un conjunto vacío es una respuesta silenciosa más segura y
consistente con la semántica de búsqueda. Aplica a `type=clients` (cliente → 0)
y a `type=bookings` (cliente sin reservas propias → 0). Detalle en
`docs/P5_dependencias.md`.

### 2.2 Ingresos netos en reportes y estadísticas

`revenue` y `revenue_by_month` = `SUM(amount)` de pagos `Completado` con
`kind='pago'` **menos** los `Completado` con `kind='reembolso'`. Los
`Anulado` y `Pendiente_verificacion` no cuentan.

### 2.3 `Payment.booking` como relación

Se añadió `db.relationship("Booking")` a `Payment` para que el reporte de
pagos muestre el código de reserva. No altera el esquema (no requiere
migración).

### 2.4 Alcance por rol del catálogo en `/api/search` (verificado antes del merge)

La matriz P1 distingue catálogo público de interno:

- **Público (todos los roles):** `packages`, `destinations`, `activities`.
- **Interno (solo admin/employee):** `hotels`, `flights`, `transports`
  (`catalog:view_hotels/flights/transports = STAFF_ROLES`).

Se corrigió la fuga: los tres searchers internos no filtraban por rol, así que
un cliente podía listar hoteles, vuelos y transporte. Ahora devuelven `total: 0`
para clientes (misma regla 0-vs-403 de la sección 2.1). De paso, el test
destapó un bug preexistente: `search_flights` no aceptaba `min_stars` y la rama
`else` de la ruta lo pasaba, por lo que `type=flights` devolvía 500; se añadió
`**kw`. Tests: `test_search_catalogo_interno_solo_staff` (parametrizado) y
`test_search_catalogo_publico_cliente` (parametrizado).

## 3. Alcance

**RF-14 (Dashboard):** `app/analytics.py` con funciones puras
(`revenue_by_month`, `bookings_by_status`, `top_destinations`,
`package_occupancy`, `frequent_clients`, `peak_seasons`, `recent_alerts`) y
`GET /api/dashboard/stats`. Config `FREQUENT_CLIENT_MIN=3` y
`PEAK_SEASON_FACTOR=1.25`.

**RF-15 (Reportes):** `GET /reports/<kind>.<fmt>` con `kind ∈ bookings|clients|
occupancy|payments|revenue` y `fmt ∈ pdf|xlsx`. Filtros `date_from`, `date_to`,
`status`, `destination`; tipo o formato inválido → 422. PDF con `reportlab`
(tabla `repeatRows=1`, pie con número de página) y XLSX con `openpyxl`
(encabezados estilizados, freeze panes, fila de totales, anti-inyección de
fórmulas). Límite 10 000 filas y auditoría por descarga.

**RF-16 (Búsqueda):** `GET /api/search` con `q`, `type`, `category`,
`destination`, `min_price`, `max_price`, `date_from`, `date_to`, `status`,
`min_stars`, `sort`, `order`, `page` y `per_page` (máx. 50). Respuesta
`{items, total, page, per_page, pages, has_next, filters_applied}`. SQLAlchemy
con parámetros y `LIKE` escapado. Alcance por rol: cliente → catálogo y sus
propias reservas.

## 4. Pendiente / fuera de alcance

- **Frontend (P7/P8):** la UI de búsqueda y la página `/reports` consumen estos
  endpoints; aquí solo se entregan el backend y los tests.
- **Graficos Chart.js del dashboard:** quedan para P8 (RF-14 frontend).
- **Merge/push:** la rama `fase-P5` no se fusiona ni se sube hasta revisión.

## 5. Reproducción

```powershell
$env:PYTHONIOENCODING="utf-8"
$env:SECRET_KEY="q12345678901234567890123456789012"
& ".venv\Scripts\python.exe" -m pytest tests -q        # 382 passed
git log --oneline main..fase-P5
```
