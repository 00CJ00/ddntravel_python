"""Estadísticas del dashboard (RF-14) — funciones puras y testeables.

Todas las funciones reciben listas de objetos (modelos ORM o simples objetos
con los mismos atributos), así se pueden probar con datos sintéticos sin
tocar la base de datos. ``collect_stats`` es la única que lee del store.
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timezone

FREQUENT_CLIENT_MIN = int(os.environ.get("FREQUENT_CLIENT_MIN", "3"))
PEAK_SEASON_FACTOR = float(os.environ.get("PEAK_SEASON_FACTOR", "1.25"))


def _attr(obj, name, default=None):
    """Lee un atributo de un objeto o una clave de un dict."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _month_key(value) -> str:
    """Normaliza una fecha/datetime a la clave 'YYYY-MM'."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:7]
    if isinstance(value, datetime):
        return value.strftime("%Y-%m")
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m")
    return str(value)[:7]


def revenue_by_month(payments, months=12) -> list[dict]:
    """Ingresos netos (pagos Completado menos reembolsos Completados) por mes.

    Devuelve exactamente ``months`` entradas consecutivas terminando en el mes
    actual, para que la gráfica del dashboard sea estable.
    """
    by_month = defaultdict(float)
    for p in payments:
        if _attr(p, "status") != "Completado":
            continue
        kind = _attr(p, "kind", "pago") or "pago"
        amount = float(_attr(p, "amount", 0) or 0)
        key = _month_key(_attr(p, "created_at"))
        if not key:
            continue
        by_month[key] += amount if kind == "pago" else -amount

    now = datetime.now(timezone.utc).strftime("%Y-%m")
    keys = []
    year, month = int(now[:4]), int(now[5:7])
    for _ in range(months):
        keys.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    return [{"month": k, "total": round(by_month.get(k, 0.0), 2)} for k in reversed(keys)]


def bookings_by_status(bookings) -> dict[str, int]:
    """Cuenta reservas por estado (ignora las borradas lógicamente)."""
    counts = defaultdict(int)
    for b in bookings:
        if _attr(b, "deleted_at") is not None:
            continue
        counts[_attr(b, "status", "Pendiente") or "Pendiente"] += 1
    return dict(counts)


def top_destinations(bookings, limit=5) -> list[dict]:
    """Destinos con más reservas e ingresos."""
    agg = defaultdict(lambda: {"bookings": 0, "revenue": 0.0})
    for b in bookings:
        if _attr(b, "deleted_at") is not None:
            continue
        dest = _attr(b, "destination_name") or "Sin destino"
        agg[dest]["bookings"] += 1
        agg[dest]["revenue"] += float(_attr(b, "total_price", 0) or 0)
    ranked = sorted(agg.items(), key=lambda kv: (kv[1]["bookings"], kv[1]["revenue"]),
                    reverse=True)[:limit]
    return [{"destination": name, "bookings": data["bookings"],
             "revenue": round(data["revenue"], 2)} for name, data in ranked]


def package_occupancy(packages) -> list[dict]:
    """Ocupación de cada paquete: disponibles / totales y porcentaje vendido."""
    rows = []
    for p in packages:
        if _attr(p, "deleted_at") is not None:
            continue
        available = int(_attr(p, "available_slots", 0) or 0)
        total = int(_attr(p, "total_slots", 0) or 0)
        sold = max(0, total - available)
        pct = round((sold / total) * 100, 1) if total else 0.0
        rows.append({"package": _attr(p, "title") or _attr(p, "package"),
                     "available_slots": available, "total_slots": total,
                     "sold": sold, "occupancy_pct": pct})
    return rows


def frequent_clients(clients, min_trips=FREQUENT_CLIENT_MIN) -> list[dict]:
    """Clientes con ``trips_count >= min_trips`` (configurable)."""
    rows = []
    for c in clients:
        if _attr(c, "deleted_at") is not None:
            continue
        trips = int(_attr(c, "trips_count", 0) or 0)
        if trips >= min_trips:
            rows.append({"client": _attr(c, "name"), "trips_count": trips,
                         "total_spent": round(float(_attr(c, "total_spent", 0) or 0), 2)})
    return sorted(rows, key=lambda r: r["trips_count"], reverse=True)


def peak_seasons(bookings, factor=PEAK_SEASON_FACTOR) -> list[str]:
    """Meses cuya cantidad de reservas supera ``factor`` × la media mensual."""
    counts = defaultdict(int)
    for b in bookings:
        if _attr(b, "deleted_at") is not None:
            continue
        key = _month_key(_attr(b, "created_at"))
        if key:
            counts[key] += 1
    if not counts:
        return []
    average = sum(counts.values()) / len(counts)
    if average <= 0:
        return []
    threshold = average * factor
    return sorted(key for key, n in counts.items() if n > threshold)


def recent_alerts(notifications, limit=10) -> list[dict]:
    """Alertas automáticas recientes visibles para el personal (RF-14).

    Las alertas se generan con ``type='warning'`` y ``visible_roles`` de
    staff. Se devuelven las más recientes (la lista ya viene ordenada).
    """
    rows = []
    for n in notifications:
        if _attr(n, "type") != "warning":
            continue
        roles = _attr(n, "visible_roles") or []
        if roles and not ({"admin", "employee"} & set(roles)):
            continue
        rows.append({
            "title": _attr(n, "title"),
            "message": _attr(n, "message"),
            "link_tab": _attr(n, "link_tab"),
            "date": _attr(n, "date"),
        })
        if len(rows) >= limit:
            break
    return rows


def collect_stats(bookings, payments, packages, clients, notifications=None) -> dict:
    """Agrupa todas las estadísticas del dashboard (RF-14)."""
    return {
        "revenue_by_month": revenue_by_month(payments),
        "bookings_by_status": bookings_by_status(bookings),
        "top_destinations": top_destinations(bookings),
        "package_occupancy": package_occupancy(packages),
        "frequent_clients": frequent_clients(clients),
        "peak_seasons": peak_seasons(bookings),
        "alerts": recent_alerts(notifications or []),
    }
