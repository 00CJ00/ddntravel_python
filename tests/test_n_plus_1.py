"""Guard contra N+1 en el listado de reservas (fase P2, arreglo 3).

``Booking.passengers`` se carga con ``lazy="selectin"``: el número de consultas
de ``/bookings`` debe ser independiente del número de reservas y pasajeros.
Sin esa estrategia cada reserva emitía su propia consulta SELECT sobre
``booking_passengers`` (22 consultas con 3 reservas y 79 con 60).
"""
from __future__ import annotations

import re
from collections import Counter

import pytest
from conftest import ADMIN_EMAIL

from sqlalchemy import event
from sqlalchemy.engine import Engine

from app import models as m
from app.extensions import db


@pytest.fixture
def contar_consultas():
    """Recuento de consultas SQL emitidas dentro de una petición."""
    stats = {"total": 0, "tablas": Counter()}

    def _antes(conn, cursor, statement, parameters, context, executemany):
        stats["total"] += 1
        for nombre in re.findall(r'FROM\s+["\`]?(\w+)', statement, flags=re.IGNORECASE):
            stats["tablas"][nombre] += 1

    event.listen(Engine, "before_cursor_execute", _antes)
    yield stats
    event.remove(Engine, "before_cursor_execute", _antes)


def _get_bookings(client, stats):
    """Resetea el recuento y devuelve el resultado de GET /bookings."""
    stats["total"] = 0
    stats["tablas"].clear()
    res = client.get("/bookings", follow_redirects=False)
    assert res.status_code == 200
    return stats["tablas"]["booking_passengers"]


def _anadir_reservas_con_pasajero(cantidad):
    base = db.session.query(m.Booking).first()
    for i in range(cantidad):
        nueva = m.Booking(
            booking_code=f"N1-TEST-{i:04d}", client_id=base.client_id,
            package_id=base.package_id, package_name=base.package_name,
            destination_name=base.destination_name, travelers=1,
            total_price=base.total_price, amount_paid=base.amount_paid,
            status=base.status, payment_status=base.payment_status,
            departure_date=base.departure_date, return_date=base.return_date)
        db.session.add(nueva)
        db.session.flush()
        db.session.add(m.BookingPassenger(booking_id=nueva.id,
                                          full_name=f"Viajero {i}",
                                          document=f"T-{i}"))
    db.session.commit()


def test_bookings_consultas_independientes_del_numero_de_filas(
        client, login_as, contar_consultas):
    """Las consultas de /bookings no escalan con reservas ni con pasajeros."""
    login_as(client, ADMIN_EMAIL)

    con_pasajeros_semilla = _get_bookings(client, contar_consultas)
    consultas_semilla = contar_consultas["total"]

    _anadir_reservas_con_pasajero(9)

    con_pasajeros_ampliada = _get_bookings(client, contar_consultas)
    consultas_ampliada = contar_consultas["total"]

    # El recuento por tabla se mantiene: ninguna consulta se repite por reserva.
    assert con_pasajeros_ampliada == con_pasajeros_semilla
    assert consultas_ampliada == consultas_semilla, (
        f"/bookings emitió {consultas_semilla} consultas con las reservas de la "
        f"semilla y {consultas_ampliada} con 9 más: N+1 otra vez")