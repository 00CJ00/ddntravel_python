"""Formateo de filas de reportes (RF-15)."""
from __future__ import annotations

from ..repositories import reports as reports_repo


def _as_date(value):
    if not value:
        return None
    try:
        from datetime import date as _d
        return _d.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _bookings_rows(bookings):
    rows = [[b.booking_code, b.destination_name or "", b.client_name or "",
             b.travelers, float(b.total_price or 0), b.status]
            for b in bookings]
    total = sum(float(b.total_price or 0) for b in bookings)
    return rows, ["", "", "", "", f"${total:,.2f}", ""]


def _clients_rows(clients):
    rows = [[c.name, c.email or "", c.document_id or "", c.category or "",
             c.trips_count or 0, float(c.total_spent or 0)] for c in clients]
    total = sum(float(c.total_spent or 0) for c in clients)
    return rows, ["", "", "", "", "", f"${total:,.2f}"]


def _occupancy_rows(data):
    rows = [[d["hotel"], d["destination"] or "", d["total_rooms"], d["occupied"], f"{d['pct']}%"]
            for d in data]
    return rows, ["", "", "", "", ""]


def _payments_rows(payments):
    rows = []
    for p in payments:
        booking = getattr(p, "booking", None)
        rows.append([p.receipt_number, p.ncf or "", getattr(booking, "booking_code", ""),
                     p.method, p.kind, float(p.amount or 0), p.status])
    total = sum(float(p.amount or 0) for p in payments if p.status == "Completado")
    return rows, ["", "", "", "", "", f"${total:,.2f}", ""]


def _revenue_rows(payments):
    rows = [[p.receipt_number, p.ncf or "", p.kind, p.method, float(p.amount or 0),
             p.created_at.strftime("%Y-%m-%d") if getattr(p, "created_at", None) else ""]
            for p in payments]
    net = sum(float(p.amount or 0) for p in payments if p.kind == "pago") - \
        sum(float(p.amount or 0) for p in payments if p.kind == "reembolso")
    return rows, ["", "", "", "", f"${net:,.2f}", ""]


def build_report(kind, date_from=None, date_to=None, status="", destination=""):
    """Devuelve (headers, rows, totals) para el tipo de reporte pedido."""
    if kind == "bookings":
        items = reports_repo.bookings_report(date_from, date_to, status, destination)
        headers = ["Código", "Destino", "Cliente", "Viajeros", "Total", "Estado"]
        rows, totals = _bookings_rows(items)
    elif kind == "clients":
        items = reports_repo.clients_report(date_from, date_to, status, destination)
        headers = ["Nombre", "Email", "Documento", "Categoría", "Viajes", "Total gastado"]
        rows, totals = _clients_rows(items)
    elif kind == "occupancy":
        items = reports_repo.occupancy_report(date_from, date_to, status, destination)
        headers = ["Hotel", "Destino", "Habitaciones", "Ocupadas", "Ocupación"]
        rows, totals = _occupancy_rows(items)
    elif kind == "payments":
        items = reports_repo.payments_report(date_from, date_to, status, destination)
        headers = ["Recibo", "NCF", "Reserva", "Método", "Tipo", "Monto", "Estado"]
        rows, totals = _payments_rows(items)
    elif kind == "revenue":
        items = reports_repo.revenue_report(date_from, date_to, status, destination)
        headers = ["Recibo", "NCF", "Tipo", "Método", "Monto", "Fecha"]
        rows, totals = _revenue_rows(items)
    else:
        raise ValueError(kind)
    return headers, rows, totals
