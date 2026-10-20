"""Tests de analytics.py y /api/dashboard/stats (RF-14) — Fase P5."""
import os
import sys
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from conftest import ADMIN_EMAIL, CLIENT_EMAIL

from app.analytics import (
    bookings_by_status,
    collect_stats,
    frequent_clients,
    package_occupancy,
    peak_seasons,
    recent_alerts,
    revenue_by_month,
    top_destinations,
)


def _booking(status="Confirmada", destination="Cancún", total=1000, month="2026-06",
             deleted_at=None):
    return NS(booking_code="DDN-1", status=status, destination_name=destination,
              total_price=total, deleted_at=deleted_at, created_at=f"{month}-15")


def _payment(kind="pago", status="Completado", amount=500, month="2026-06"):
    return NS(kind=kind, status=status, amount=amount, created_at=f"{month}-10")


def _package(title="Tour Caribe", available=4, total=10):
    return NS(title=title, available_slots=available, total_slots=total, deleted_at=None)


def _client(name="Ana", trips=5, spent=4000):
    return NS(name=name, trips_count=trips, total_spent=spent, deleted_at=None)


def test_revenue_by_month_neto():
    payments = [_payment(amount=1000, month="2026-01"),
                _payment(kind="reembolso", amount=300, month="2026-01"),
                _payment(status="Anulado", amount=999, month="2026-01")]
    rows = revenue_by_month(payments, months=12)
    assert len(rows) == 12
    jan = next(r for r in rows if r["month"] == "2026-01")
    assert jan["total"] == 700


def test_revenue_by_month_devuelve_12_entradas():
    rows = revenue_by_month([], months=12)
    assert len(rows) == 12
    assert all(r["total"] == 0 for r in rows)


def test_bookings_by_status():
    bookings = [_booking(status="Confirmada"), _booking(status="Confirmada"),
                _booking(status="Pendiente"), _booking(deleted_at="x")]
    counts = bookings_by_status(bookings)
    assert counts == {"Confirmada": 2, "Pendiente": 1}


def test_top_destinations_ordena_por_reservas():
    bookings = [_booking(destination="Punta Cana"), _booking(destination="Punta Cana"),
                _booking(destination="Cancún", total=5000)]
    top = top_destinations(bookings)
    assert top[0]["destination"] == "Punta Cana"
    assert top[0]["bookings"] == 2


def test_package_occupancy_pct():
    rows = package_occupancy([_package(available=4, total=10)])
    assert rows[0]["sold"] == 6
    assert rows[0]["occupancy_pct"] == 60.0


def test_frequent_clients_min_trips():
    clients = [_client("Ana", trips=5), _client("Beto", trips=1), _client("Cira", trips=3)]
    frequent = frequent_clients(clients, min_trips=3)
    names = [c["client"] for c in frequent]
    assert names == ["Ana", "Cira"]


def test_peak_seasons_sobre_media():
    bookings = [_booking(month="2026-06") for _ in range(10)]
    bookings += [_booking(month="2026-07"), _booking(month="2026-07")]
    bookings += [_booking(month="2026-08")]
    peaks = peak_seasons(bookings, factor=1.25)
    assert "2026-06" in peaks
    assert "2026-07" not in peaks


def test_collect_stats_estructura():
    stats = collect_stats([_booking()], [_payment()], [_package()], [_client()])
    for key in ("revenue_by_month", "bookings_by_status", "top_destinations",
                "package_occupancy", "frequent_clients", "peak_seasons", "alerts"):
        assert key in stats


def test_recent_alerts_solo_staff():
    notifications = [
        NS(type="warning", visible_roles=["admin", "employee"],
           title="Alerta A", message="m", link_tab="bookings", date="hoy"),
        NS(type="warning", visible_roles=["client"],
           title="Alerta B", message="m", link_tab="catalog", date="hoy"),
        NS(type="info", visible_roles=["admin", "employee"],
           title="Info", message="m", link_tab="bookings", date="hoy"),
    ]
    alerts = recent_alerts(notifications)
    assert [a["title"] for a in alerts] == ["Alerta A"]


def test_endpoint_admin_200(client, login_as):
    login_as(client, ADMIN_EMAIL)
    resp = client.get("/api/dashboard/stats")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert "revenue_by_month" in data


def test_endpoint_cliente_403(client, login_as):
    login_as(client, CLIENT_EMAIL)
    resp = client.get("/api/dashboard/stats")
    assert resp.status_code == 403
