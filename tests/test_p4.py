"""Tests de la fase P4: NCF secuencial, factura PDF y anulación/reembolso."""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from conftest import ADMIN_EMAIL, EMPLOYEE_EMAIL, CLIENT_EMAIL, post_form


def _admin(store):
    return next(u for u in store.available_users if u.role == "admin")


def _crear_reserva(store, total=1000):
    cli = store.clients[0]
    r = store.create_booking(_admin(store), client_id=cli.id, client_name=cli.name,
                             client_email=cli.email, travelers=1, total_price=total)
    assert r["success"] is True, r["message"]
    return r["booking"]


def test_ncf_asignado_y_formato(store):
    booking = _crear_reserva(store, 500)
    r = store.register_payment(_admin(store), booking.id, 500, "Tarjeta de Crédito")
    assert r["success"] is True
    ncf = r["payment"].ncf
    assert ncf and len(ncf) >= 11
    assert ncf[:2] in ("B0", "B1", "B4")


def test_ncf_secuencial_y_unico(store):
    booking = _crear_reserva(store, 2000)
    r1 = store.register_payment(_admin(store), booking.id, 1000, "Tarjeta de Crédito")
    r2 = store.register_payment(_admin(store), booking.id, 1000, "Tarjeta de Crédito")
    n1, n2 = r1["payment"].ncf, r2["payment"].ncf
    assert n1 and n2 and n1 != n2
    assert n1[:-8] == n2[:-8]
    assert int(n2[-8:]) == int(n1[-8:]) + 1


def test_sobrepago_rechazado(store):
    booking = _crear_reserva(store, 1000)
    r = store.register_payment(_admin(store), booking.id, 1500, "Tarjeta de Crédito")
    assert r["success"] is False and "excede" in r["message"]


def test_factura_pdf_valida(client, store, login_as):
    login_as(client, ADMIN_EMAIL)
    booking = _crear_reserva(store, 800)
    r = store.register_payment(_admin(store), booking.id, 800, "Tarjeta de Crédito")
    resp = client.get(f"/payments/{r['payment'].id}/factura")
    assert resp.status_code == 200
    body = resp.get_data()
    assert body.startswith(b"%PDF")


def test_anulacion_revierte_estado_y_emite_nota(client, store, login_as, post_csrf):
    login_as(client, ADMIN_EMAIL)
    booking = _crear_reserva(store, 600)
    r = store.register_payment(_admin(store), booking.id, 600, "Tarjeta de Crédito")
    assert booking.status == "Confirmada"
    resp = post_csrf(client, f"/payments/{r['payment'].id}/void", {"reason": "Cliente se arrepiente"})
    assert r["payment"].status == "Anulado"
    assert booking.status == "Pendiente"
    from app import models as m
    refund = m.Payment.query.filter_by(kind="reembolso").first()
    assert refund is not None
    assert refund.ncf and refund.ncf != r["payment"].ncf


def test_anulacion_exige_motivo(client, store, login_as, post_csrf):
    login_as(client, ADMIN_EMAIL)
    booking = _crear_reserva(store, 600)
    r = store.register_payment(_admin(store), booking.id, 600, "Tarjeta de Crédito")
    post_csrf(client, f"/payments/{r['payment'].id}/void", {"reason": ""})
    assert r["payment"].status == "Completado"


def test_employee_no_anula(client, store, login_as, post_csrf):
    login_as(client, EMPLOYEE_EMAIL)
    booking = _crear_reserva(store, 600)
    r = store.register_payment(_admin(store), booking.id, 600, "Tarjeta de Crédito")
    resp = post_csrf(client, f"/payments/{r['payment'].id}/void", {"reason": "x"})
    assert resp.status_code == 403
