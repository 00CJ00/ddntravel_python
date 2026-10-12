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


def test_segunda_anulacion_no_duplica_reembolso(store):
    from app import models as m
    booking = _crear_reserva(store, 600)
    r = store.register_payment(_admin(store), booking.id, 600, "Tarjeta de Crédito")
    r1 = store.void_payment(_admin(store), r["payment"].id, "motivo")
    assert r1["success"] is True
    r2 = store.void_payment(_admin(store), r["payment"].id, "motivo otra vez")
    assert r2["success"] is False
    reembolsos = m.Payment.query.filter_by(
        kind="reembolso", original_payment_id=r["payment"].id).all()
    assert len(reembolsos) == 1


def test_anular_pago_pendiente_no_descuenta_ni_reembolsa(store):
    from app import models as m
    booking = _crear_reserva(store, 1000)
    r = store.register_payment(_admin(store), booking.id, 400, "Efectivo")
    assert r["payment"].status == "Pendiente_verificacion"
    r2 = store.void_payment(_admin(store), r["payment"].id, "referencia inválida")
    assert r2["success"] is True
    assert r["payment"].status == "Anulado"
    assert float(booking.amount_paid or 0) == 0  # nunca sumó: nada que restar
    assert r2["refund"] is None
    assert m.Payment.query.filter_by(
        kind="reembolso", original_payment_id=r["payment"].id).count() == 0


def test_reembolso_con_ncf_b04_distinto_del_original(store):
    booking = _crear_reserva(store, 600)
    r = store.register_payment(_admin(store), booking.id, 600, "Tarjeta de Crédito")
    ncf_original = r["payment"].ncf
    r2 = store.void_payment(_admin(store), r["payment"].id, "duplicado")
    refund = r2["refund"]
    assert refund is not None
    assert refund.kind == "reembolso"
    assert refund.original_payment_id == r["payment"].id
    assert refund.ncf and refund.ncf.startswith("B04") and refund.ncf != ncf_original
    assert refund.receipt_number != r["payment"].receipt_number


def test_sobrepago_http_422_sin_persistencia(client, store, login_as, post_csrf):
    login_as(client, ADMIN_EMAIL)
    booking = _crear_reserva(store, 1000)
    antes = len(store.payments)
    resp = post_csrf(client, "/payments/new", {
        "booking_id": str(booking.id), "amount": "1500",
        "payment_method": "Tarjeta de Crédito", "reference": ""})
    assert resp.status_code == 422
    assert len(store.payments) == antes


def test_ncf_concurrente_20_pagos_unicos_y_consecutivos(tmp_path, make_app):
    """20 hilos × 1 pago real cada uno → 20 NCF únicos, consecutivos y persistidos."""
    import threading
    import time

    from sqlalchemy.exc import OperationalError

    from app import models as m
    from app import store as store_module
    from app.config import DevelopmentConfig
    from app.extensions import db
    from app.repositories import people

    db_file = (tmp_path / "conc.db").as_posix()

    class ConcConfig(DevelopmentConfig):
        ENV = "development"
        DEBUG = False
        TESTING = True
        SECRET_KEY = "clave-privada-de-pruebas-ddn-travel-0000000000"
        WTF_CSRF_ENABLED = True
        RATELIMIT_ENABLED = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_file}"
        SQLALCHEMY_ENGINE_OPTIONS = {
            "connect_args": {"check_same_thread": False, "timeout": 30},
        }

    application = make_app(ConcConfig)
    with application.app_context():
        db.create_all()
        admin = m.User(name="Admin Conc", email="conc@ddntravel.com",
                       role="admin", is_active=True)
        db.session.add(admin)
        client = m.Client(name="Cliente Conc", email="conc.cli@example.com",
                          category="Estándar")
        db.session.add(client)
        db.session.flush()
        booking = m.Booking(
            booking_code="DDN-2026-90001", client_id=client.id,
            destination_name="Destino Conc", travelers=1,
            total_price=20000, amount_paid=0,
            status="Pendiente", payment_status="Pendiente")
        db.session.add(booking)
        db.session.commit()
        booking_id, admin_id = booking.id, admin.id

    ncfs, errores = [], []

    def _pagar(i):
        try:
            for _ in range(200):
                try:
                    with application.app_context():
                        admin = people.get_user(admin_id)
                        r = store_module.store.register_payment(
                            admin, booking_id, 100, "Tarjeta de Crédito",
                            ref_number=f"CONC-{i:02d}")
                        assert r["success"], r
                        ncfs.append(r["payment"].ncf)
                        return
                except OperationalError:
                    time.sleep(0.05)
            errores.append(f"hilo {i}: sin éxito tras reintentos")
        except Exception as exc:  # noqa: BLE001
            errores.append(f"hilo {i}: {exc!r}")

    hilos = [threading.Thread(target=_pagar, args=(i,)) for i in range(20)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=120)

    assert not errores, errores[:3]
    assert len(ncfs) == 20
    assert len(set(ncfs)) == 20, "NCF duplicados bajo concurrencia"
    prefijos = {n[:3] for n in ncfs}
    assert len(prefijos) == 1, f"varios prefijos: {prefijos}"
    numeros = sorted(int(n[3:]) for n in ncfs)
    assert numeros[-1] - numeros[0] == 19, "NCF no consecutivos (pérdida de actualización)"
    assert numeros == list(range(numeros[0], numeros[0] + 20))

    with application.app_context():
        assert m.Payment.query.filter_by(booking_id=booking_id).count() == 20
        db.session.remove()
