"""Tests de la fase P6: itinerarios (RF-10), documentos, alertas e IA."""
from conftest import (
    ADMIN_EMAIL,
    CLIENT_EMAIL,
    EMPLOYEE_EMAIL,
    client_booking_of,
    read_csrf_token,
)

VALID_ITINERARY = {
    "destination": "Punta Cana",
    "overview": "Escapada de 2 días",
    "days": [
        {"dayNumber": 1, "title": "Llegada", "morning": "Vuelo",
         "afternoon": "Playa", "evening": "Cena"},
        {"dayNumber": 2, "title": "Salida", "morning": "Desayuno",
         "afternoon": "Traslado", "evening": "Vuelo"},
    ],
    "includedPerks": ["Seguro básico"],
    "estimatedBudgetUSD": 900,
}


def post_json(client, url, payload):
    token = read_csrf_token(client)
    return client.post(url, json=payload, headers={"X-CSRFToken": token})


def put_json(client, url, payload):
    token = read_csrf_token(client)
    return client.put(url, json=payload, headers={"X-CSRFToken": token})


def delete_json(client, url):
    token = read_csrf_token(client)
    return client.delete(url, headers={"X-CSRFToken": token})


# ----------------------------------------------------------------------
# Itinerarios (RF-10)
# ----------------------------------------------------------------------
def test_itinerary_create_and_get(client, store, login_as):
    login_as(client, ADMIN_EMAIL)
    booking = store.bookings[0]
    resp = post_json(client, f"/bookings/{booking.id}/itinerary",
                     {"content": VALID_ITINERARY, "source": "ia"})
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    assert body["content"]["destination"] == "Punta Cana"
    assert len(body["content"]["days"]) == 2

    got = client.get(f"/bookings/{booking.id}/itinerary")
    assert got.status_code == 200
    assert got.get_json()["content"]["days"][0]["title"] == "Llegada"


def test_itinerary_rejects_invalid_content(client, store, login_as):
    login_as(client, ADMIN_EMAIL)
    booking = store.bookings[0]
    before = len(store.audit_logs)
    for bad in ({"destination": "X"}, {"destination": "X", "days": "no-lista"},
                {"destination": "X", "days": [{"morning": "sin título"}]},
                {"destination": "", "days": []}, "cadena", [1, 2]):
        resp = post_json(client, f"/bookings/{booking.id}/itinerary", {"content": bad})
        assert resp.status_code == 422, bad
    assert store.get_itinerary(booking.id) is None
    assert len(store.audit_logs) == before, "el rechazo no debe auditar"


def test_itinerary_update_valid(client, store, login_as):
    login_as(client, ADMIN_EMAIL)
    booking = store.bookings[0]
    post_json(client, f"/bookings/{booking.id}/itinerary", {"content": VALID_ITINERARY})
    edited = dict(VALID_ITINERARY, overview="Editado")
    resp = put_json(client, f"/bookings/{booking.id}/itinerary", {"content": edited})
    assert resp.status_code == 200
    assert store.get_itinerary(booking.id).content["overview"] == "Editado"


def test_itinerary_ownership(client, store, login_as):
    """Un cliente no ve el itinerario de una reserva ajena (404, no 403)."""
    login_as(client, ADMIN_EMAIL)
    ajena = next(b for b in store.bookings if b.client_email != CLIENT_EMAIL)
    post_json(client, f"/bookings/{ajena.id}/itinerary", {"content": VALID_ITINERARY})
    login_as(client, CLIENT_EMAIL)
    assert client.get(f"/bookings/{ajena.id}/itinerary").status_code == 404
    assert post_json(client, f"/bookings/{ajena.id}/itinerary",
                     {"content": VALID_ITINERARY}).status_code == 404


def test_itinerary_client_owns_crud(client, store, login_as):
    login_as(client, CLIENT_EMAIL)
    propia = client_booking_of(store, CLIENT_EMAIL)
    assert post_json(client, f"/bookings/{propia.id}/itinerary",
                     {"content": VALID_ITINERARY}).status_code == 201
    assert client.get(f"/bookings/{propia.id}/itinerary").status_code == 200
    edited = dict(VALID_ITINERARY, overview="Mi edición")
    assert put_json(client, f"/bookings/{propia.id}/itinerary",
                    {"content": edited}).status_code == 200


def test_itinerary_delete_admin_only(client, store, login_as, post_csrf):
    login_as(client, EMPLOYEE_EMAIL)
    booking = store.bookings[0]
    post_json(client, f"/bookings/{booking.id}/itinerary", {"content": VALID_ITINERARY})
    assert delete_json(client, f"/bookings/{booking.id}/itinerary").status_code == 403
    assert store.get_itinerary(booking.id) is not None

    login_as(client, ADMIN_EMAIL)
    assert delete_json(client, f"/bookings/{booking.id}/itinerary").status_code == 200
    assert store.get_itinerary(booking.id) is None
    assert client.get(f"/bookings/{booking.id}/itinerary").status_code == 404


# ----------------------------------------------------------------------
# Documentos con archivo (RF-17)
# ----------------------------------------------------------------------
import io
import os
from datetime import date, timedelta

from conftest import post_form

PDF_BYTES = b"%PDF-1.4\n% fake pdf content for tests\n"
JPG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 100
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def upload(client, app, tmp_path, filename, content, **fields):
    app.config["UPLOAD_DIR"] = str(tmp_path / "uploads")
    data = dict(fields)
    data["file"] = (io.BytesIO(content), filename)
    return post_form(client, "/documents/upload", data)


def test_upload_rejects_exe(client, app, store, login_as, tmp_path):
    login_as(client, ADMIN_EMAIL)
    before = len(store.documents)
    resp = upload(client, app, tmp_path, "malware.exe", b"MZ\x90\x00evil",
                  client_id=store.clients[0].id)
    assert resp.status_code == 422
    assert len(store.documents) == before


def test_upload_rejects_fake_signature(client, app, store, login_as, tmp_path):
    login_as(client, ADMIN_EMAIL)
    before = len(store.documents)
    resp = upload(client, app, tmp_path, "falso.pdf", b"MZ\x90\x00no es pdf",
                  client_id=store.clients[0].id)
    assert resp.status_code == 422
    assert b"no corresponde" in resp.data
    assert len(store.documents) == before


def test_upload_rejects_empty(client, app, store, login_as, tmp_path):
    login_as(client, ADMIN_EMAIL)
    resp = upload(client, app, tmp_path, "vacio.pdf", b"",
                  client_id=store.clients[0].id)
    assert resp.status_code == 422


def test_upload_accepts_valid_files(client, app, store, login_as, tmp_path):
    login_as(client, ADMIN_EMAIL)
    cli = store.clients[0]
    for filename, content, mime in (("doc.pdf", PDF_BYTES, "application/pdf"),
                                    ("foto.jpg", JPG_BYTES, "image/jpeg"),
                                    ("img.png", PNG_BYTES, "image/png")):
        resp = upload(client, app, tmp_path, filename, content,
                      client_id=cli.id, doc_type="Pasaporte")
        assert resp.status_code == 201, (filename, resp.get_json())
        body = resp.get_json()
        doc = next(d for d in store.documents if d.id == body["id"])
        assert doc.mime == mime
        assert doc.size_bytes == len(content)
        assert doc.stored_name != filename
        assert doc.stored_name.endswith(filename.rsplit(".", 1)[-1])
        path = os.path.join(str(tmp_path / "uploads"), doc.stored_name)
        assert os.path.isfile(path)
        with open(path, "rb") as fh:
            assert fh.read() == content


def test_upload_rejects_over_5mb(client, app, store, login_as, tmp_path):
    login_as(client, ADMIN_EMAIL)
    big = b"%PDF" + b"\x00" * (5 * 1024 * 1024)
    resp = upload(client, app, tmp_path, "grande.pdf", big,
                  client_id=store.clients[0].id)
    assert resp.status_code in (413, 422)


def test_download_own_ok_other_403(client, app, store, login_as, tmp_path):
    login_as(client, ADMIN_EMAIL)
    cli = store.clients[0]
    resp = upload(client, app, tmp_path, "mio.pdf", PDF_BYTES, client_id=cli.id)
    doc_id = resp.get_json()["id"]

    login_as(client, CLIENT_EMAIL)
    # El documento subido es de otro cliente -> 403; el propio -> 200.
    otro_cli = next(c for c in store.clients if c.email != CLIENT_EMAIL)
    login_as(client, ADMIN_EMAIL)
    resp2 = upload(client, app, tmp_path, "ajeno.pdf", PDF_BYTES, client_id=otro_cli.id)
    ajeno_id = resp2.get_json()["id"]
    login_as(client, CLIENT_EMAIL)
    r_ajeno = client.get(f"/documents/{ajeno_id}/download")
    assert r_ajeno.status_code == 403

    own_cli = next((c for c in store.clients if c.email == CLIENT_EMAIL), None)
    if own_cli is not None:
        login_as(client, ADMIN_EMAIL)
        r3 = upload(client, app, tmp_path, "propio.pdf", PDF_BYTES, client_id=own_cli.id)
        login_as(client, CLIENT_EMAIL)
        r_own = client.get(f"/documents/{r3.get_json()['id']}/download")
        assert r_own.status_code == 200
        assert r_own.data == PDF_BYTES


def test_delete_document_removes_file(client, app, store, login_as, tmp_path, post_csrf):
    login_as(client, ADMIN_EMAIL)
    cli = store.clients[0]
    resp = upload(client, app, tmp_path, "borrar.pdf", PDF_BYTES, client_id=cli.id)
    doc_id = resp.get_json()["id"]
    doc = next(d for d in store.documents if d.id == doc_id)
    path = os.path.join(str(tmp_path / "uploads"), doc.stored_name)
    assert os.path.isfile(path)
    post_csrf(client, f"/documents/{doc_id}/delete", {})
    assert all(d.id != doc_id for d in store.documents)
    assert not os.path.isfile(path)


def test_expiry_status_boundaries():
    from app.documents import expiry_status, add_months
    today = date.today()
    assert expiry_status(None) == "vigente"
    assert expiry_status(today - timedelta(days=1)) == "vencido"
    assert expiry_status(today) == "por vencer"
    assert expiry_status(add_months(today, 6) - timedelta(days=1)) == "por vencer"
    assert expiry_status(add_months(today, 6)) == "vigente"
    assert expiry_status(add_months(today, 7)) == "vigente"


# ----------------------------------------------------------------------
# Voucher PDF en la confirmación (RF-17)
# ----------------------------------------------------------------------
def _confirmada_con_pago(store, total=800):
    admin = next(u for u in store.available_users if u.role == "admin")
    cli = store.clients[0]
    r = store.create_booking(
        admin, client_id=cli.id, client_name=cli.name, client_email=cli.email,
        travelers=1, total_price=total)
    booking = r["booking"]
    store.register_payment(admin, booking.id, total, "Tarjeta de Crédito")
    assert booking.status == "Confirmada"
    return booking


def _vouchers_de(store, booking_id):
    return [d for d in store.documents
            if getattr(d, "booking_id", None) == booking_id
            and (d.doc_type or "") == "Voucher de Reserva"]


def test_voucher_pdf_valido_al_confirmar(client, app, store, login_as, tmp_path):
    app.config["UPLOAD_DIR"] = str(tmp_path / "uploads")
    booking = _confirmada_con_pago(store)
    vouchers = _vouchers_de(store, booking.id)
    assert len(vouchers) == 1
    path = os.path.join(str(tmp_path / "uploads"), vouchers[0].stored_name)
    assert os.path.isfile(path)
    with open(path, "rb") as fh:
        assert fh.read().startswith(b"%PDF")
    assert vouchers[0].mime == "application/pdf"


def test_voucher_idempotente(client, app, store, login_as, tmp_path, post_csrf):
    app.config["UPLOAD_DIR"] = str(tmp_path / "uploads")
    booking = _confirmada_con_pago(store)
    assert len(_vouchers_de(store, booking.id)) == 1
    # Repetir la transición y el ensure no duplica.
    login_as(client, ADMIN_EMAIL)
    admin = next(u for u in store.available_users if u.role == "admin")
    store.update_booking_status(admin, booking.id, "Confirmada")
    store.ensure_voucher_pdf(booking, admin)
    assert len(_vouchers_de(store, booking.id)) == 1


def test_voucher_adopta_fila_heredada(client, app, store, login_as, tmp_path):
    """Una fila P4 solo-metadatos se completa en vez de duplicarse."""
    app.config["UPLOAD_DIR"] = str(tmp_path / "uploads")
    admin = next(u for u in store.available_users if u.role == "admin")
    cli = store.clients[0]
    r = store.create_booking(
        admin, client_id=cli.id, client_name=cli.name, client_email=cli.email,
        travelers=1, total_price=500)
    booking = r["booking"]
    assert booking.status == "Pendiente"
    legacy = store.add_document(
        admin, client_id=cli.id, booking_id=booking.id, doc_type="Voucher de Reserva",
        file_name=f"Voucher_Oficial_{booking.booking_code}.pdf", status="Válido")
    assert not getattr(legacy, "stored_name", None)
    # Al confirmar, el ensure adopta la fila heredada en vez de crear otra.
    store.register_payment(admin, booking.id, 500, "Tarjeta de Crédito")
    assert booking.status == "Confirmada"
    vouchers = _vouchers_de(store, booking.id)
    assert len(vouchers) == 1
    assert vouchers[0].id == legacy.id
    assert vouchers[0].stored_name
    path = os.path.join(str(tmp_path / "uploads"), vouchers[0].stored_name)
    with open(path, "rb") as fh:
        assert fh.read().startswith(b"%PDF")


def test_fallo_voucher_no_rompe_confirmacion(client, app, store, login_as, tmp_path, monkeypatch):
    import app.documents as documents_module
    app.config["UPLOAD_DIR"] = str(tmp_path / "uploads")

    def _roto(booking, client_name):
        raise RuntimeError("disco lleno (simulado)")

    monkeypatch.setattr(documents_module, "generar_pdf_voucher", _roto)
    admin = next(u for u in store.available_users if u.role == "admin")
    cli = store.clients[0]
    r = store.create_booking(
        admin, client_id=cli.id, client_name=cli.name, client_email=cli.email,
        travelers=1, total_price=700)
    booking = r["booking"]
    assert r["success"] is True
    result = store.register_payment(admin, booking.id, 700, "Tarjeta de Crédito")
    assert result["success"] is True
    assert booking.status == "Confirmada"
    assert any(log.action == "VOUCHER_FALLIDO" for log in store.audit_logs)


# ----------------------------------------------------------------------
# Notificaciones por usuario y correo (RF-13)
# ----------------------------------------------------------------------
def _admin(store):
    return next(u for u in store.available_users if u.role == "admin")


def _employee(store):
    return next(u for u in store.available_users if u.role == "employee")


def test_lectura_es_por_usuario(client, store, login_as, post_csrf):
    admin, employee = _admin(store), _employee(store)
    store.add_notification("Aviso", "Contenido", "info", "bookings")
    notif = store.notifications[0]
    assert store.notification_read_by(admin, notif) is False
    assert store.notification_read_by(employee, notif) is False

    login_as(client, ADMIN_EMAIL)
    post_csrf(client, f"/notifications/{notif.id}/read", {})
    assert store.notification_read_by(admin, notif) is True
    assert store.notification_read_by(employee, notif) is False

    login_as(client, EMPLOYEE_EMAIL)
    post_csrf(client, f"/notifications/{notif.id}/read", {})
    assert store.notification_read_by(employee, notif) is True


def test_tres_eventos_crean_notificaciones(store):
    admin = _admin(store)
    cli = store.clients[0]
    r = store.create_booking(
        admin, client_id=cli.id, client_name=cli.name, client_email=cli.email,
        travelers=1, total_price=600)
    booking = r["booking"]
    store.register_payment(admin, booking.id, 600, "Tarjeta de Crédito")
    titles = [n.title for n in store.notifications]
    assert "Reserva Confirmada" in titles
    assert "Pago Recibido" in titles
    store.cancel_booking(admin, booking.id, "prueba")
    assert "Reserva Cancelada" in [n.title for n in store.notifications]


def test_eventos_repetidos_no_duplican(store):
    admin = _admin(store)
    cli = store.clients[0]
    r = store.create_booking(
        admin, client_id=cli.id, client_name=cli.name, client_email=cli.email,
        travelers=1, total_price=600)
    booking = r["booking"]
    store.register_payment(admin, booking.id, 600, "Tarjeta de Crédito")
    store.update_booking_status(admin, booking.id, "Confirmada")
    store.update_booking_status(admin, booking.id, "Confirmada")
    confirmadas = [n for n in store.notifications if n.title == "Reserva Confirmada"
                   and (n.event_key or "") == f"booking-confirmed:{booking.id}"]
    assert len(confirmadas) == 1
    store.cancel_booking(admin, booking.id, "x")
    store.cancel_booking(admin, booking.id, "x")
    canceladas = [n for n in store.notifications if n.title == "Reserva Cancelada"]
    assert len(canceladas) == 1


def test_fallo_correo_no_rompe_pago(client, app, store, login_as, tmp_path, monkeypatch):
    import app.notify as notify_module
    app.config["UPLOAD_DIR"] = str(tmp_path / "uploads")

    def _caido(event, to_email, context):
        raise RuntimeError("SMTP caído (simulado)")

    monkeypatch.setattr(notify_module, "send_event_mail", _caido)
    admin = _admin(store)
    cli = store.clients[0]
    r = store.create_booking(
        admin, client_id=cli.id, client_name=cli.name, client_email=cli.email,
        travelers=1, total_price=500)
    # create_booking no llama al correo con fallo: el pago sí pasa por el hook.
    result = store.register_payment(admin, r["booking"].id, 500, "Tarjeta de Crédito")
    assert result["success"] is True
    assert r["booking"].status == "Confirmada"


def test_sin_mail_configurado_usa_respaldo(app):
    from app.notify import is_mail_configured, send_event_mail
    app.config["MAIL_SERVER"] = ""
    app.config["MAIL_DEFAULT_SENDER"] = ""
    assert is_mail_configured(app.config) is False
    assert send_event_mail("payment_received", "cliente@example.com",
                           {"booking_code": "DDN-1", "destination": "X",
                            "amount": 10, "receipt": "R"}) == "console"
    assert send_event_mail("booking_confirmed", "", {"booking_code": "DDN-1"}) == "console"


# ----------------------------------------------------------------------
# Alertas automáticas (fase P6)
# ----------------------------------------------------------------------
import datetime as _dt

from app import alerts as alerts_module


def _mk_client(store, db, name="Alerta Test", email="alerta@example.com", passport=None):
    from app import models as m
    cli = m.Client(name=name, email=email, category="Estándar",
                   passport_expiry=passport)
    db.session.add(cli)
    db.session.flush()
    return cli


def _mk_booking(store, db, client, code, departure, total=1000, paid=0,
                status="Pendiente", created=None):
    from app import models as m
    booking = m.Booking(
        booking_code=code, client_id=client.id,
        destination_name="Destino X", departure_date=departure,
        return_date=departure + _dt.timedelta(days=3) if departure else None,
        travelers=1, total_price=total, amount_paid=paid, status=status,
        payment_status="Pendiente",
        created_at=created or _dt.datetime.now(_dt.timezone.utc))
    db.session.add(booking)
    db.session.flush()
    return booking


def test_alerta_pasaporte(store, app):
    from app.extensions import db
    from app.documents import add_months
    today = _dt.date.today()
    cli = _mk_client(store, db, passport=today + _dt.timedelta(days=30))
    _mk_booking(store, db, cli, "DDN-T-1", today + _dt.timedelta(days=60))
    cli2 = _mk_client(store, db, name="Otro", email="otro@example.com",
                      passport=add_months(today, 24))
    _mk_booking(store, db, cli2, "DDN-T-2", today + _dt.timedelta(days=60))
    db.session.commit()
    b1 = next(b for b in store.bookings if b.booking_code == "DDN-T-1")
    b2 = next(b for b in store.bookings if b.booking_code == "DDN-T-2")
    ids = {a["entity_id"] for a in alerts_module.detect_passport_expiry(store)
           if a["kind"] == "passport_expiry"}
    assert b1.id in ids and b2.id not in ids


def test_alerta_saldo_salida_cercana(store, app):
    from app.extensions import db
    today = _dt.date.today()
    cli = _mk_client(store, db)
    b1 = _mk_booking(store, db, cli, "DDN-T-10", today + _dt.timedelta(days=10),
                     total=1000, paid=200)
    _mk_booking(store, db, cli, "DDN-T-11", today + _dt.timedelta(days=30),
                total=1000, paid=200)
    _mk_booking(store, db, cli, "DDN-T-12", today, total=1000, paid=200)
    _mk_booking(store, db, cli, "DDN-T-13", today + _dt.timedelta(days=5),
                total=1000, paid=1000)
    db.session.commit()
    ids = {a["entity_id"] for a in alerts_module.detect_pending_balance(store)}
    assert b1.id in ids
    # Hoy incluido, 30 días no, pagada no.
    b_hoy = next(b for b in store.bookings if b.booking_code == "DDN-T-12")
    b_lejos = next(b for b in store.bookings if b.booking_code == "DDN-T-11")
    b_pagada = next(b for b in store.bookings if b.booking_code == "DDN-T-13")
    assert b_hoy.id in ids and b_lejos.id not in ids and b_pagada.id not in ids


def test_alerta_paquete_pocos_cupos(store, app):
    from app import models as m
    from app.extensions import db
    lleno = m.Package(title="Casi lleno", destination_name="X",
                      available_slots=2, total_slots=10)
    bien = m.Package(title="Con cupos", destination_name="X",
                     available_slots=5, total_slots=10)
    sintotal = m.Package(title="Sin total", destination_name="X",
                         available_slots=0, total_slots=0)
    db.session.add_all([lleno, bien, sintotal])
    db.session.commit()
    ids = {a["entity_id"] for a in alerts_module.detect_low_availability(store)}
    assert lleno.id in ids and bien.id not in ids and sintotal.id not in ids


def test_alerta_pendiente_sin_pago_72h(store, app):
    from app import models as m
    from app.extensions import db
    admin = _admin(store)
    cli = store.clients[0]
    vieja = _mk_booking(store, db, cli, "DDN-T-20",
                        _dt.date.today() + _dt.timedelta(days=40),
                        created=_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=100))
    reciente = _mk_booking(store, db, cli, "DDN-T-21",
                           _dt.date.today() + _dt.timedelta(days=40),
                           created=_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=1))
    con_pago = _mk_booking(store, db, cli, "DDN-T-22",
                           _dt.date.today() + _dt.timedelta(days=40),
                           created=_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=100))
    db.session.add(m.Payment(booking_id=con_pago.id, kind="pago", amount=100,
                             method="Tarjeta de Crédito", status="Completado",
                             receipt_number="REC-T-1"))
    db.session.commit()
    ids = {a["entity_id"] for a in alerts_module.detect_stale_pending(store)}
    assert vieja.id in ids and reciente.id not in ids and con_pago.id not in ids


def test_cli_alerts_idempotente(app):
    runner = app.test_cli_runner()
    r1 = runner.invoke(args=["alerts", "run"])
    assert r1.exit_code == 0, r1.output
    assert "Alertas:" in r1.output
    from app import models as m
    n1 = m.Notification.query.count()
    r2 = runner.invoke(args=["alerts", "run"])
    assert r2.exit_code == 0
    assert "0 creadas" in r2.output
    assert m.Notification.query.count() == n1


def test_event_key_unico_en_bd(store, app):
    import pytest
    from sqlalchemy.exc import IntegrityError
    from app import models as m
    from app.extensions import db
    db.session.add(m.Notification(title="A", message="m", event_key="dup-1"))
    db.session.flush()
    db.session.add(m.Notification(title="B", message="m", event_key="dup-1"))
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_alerts_sobre_seed(store):
    counts = alerts_module.run_alerts(store)
    assert set(counts) == {"created", "skipped", "total"}
    assert counts["total"] >= 0


# ----------------------------------------------------------------------
# IA: privacidad, esquema, persistencia y chat (RF-20)
# ----------------------------------------------------------------------
from types import SimpleNamespace

from app import ai_service


def _mock_gemini(monkeypatch, text=None, exc=None):
    captured = {}

    class Models:
        @staticmethod
        def generate_content(*, model, contents, config):
            captured["contents"] = contents
            captured["model"] = model
            if exc is not None:
                raise exc
            return SimpleNamespace(text=text)

    class GenerateContentConfig:
        def __init__(self, **kwargs):
            self.options = kwargs

    monkeypatch.setattr(ai_service, "_get_client",
                        lambda: SimpleNamespace(models=Models()))
    monkeypatch.setattr(ai_service, "genai_types",
                        SimpleNamespace(GenerateContentConfig=GenerateContentConfig))
    return captured


def _persona(name="Roberto Gómez", email="roberto.gomez@gmail.com"):
    return SimpleNamespace(
        name=name, email=email, document_id="001-1234567-8",
        phone="+18095550000", category="VIP", budget_preference="Premium",
        trips_count=5, preferred_destinations=["Punta Cana"])


def test_prompt_predictivo_sin_pii(monkeypatch):
    captured = _mock_gemini(monkeypatch, text=None)
    ai_service.get_predictive_analytics(
        [_persona()], [SimpleNamespace(destination_name="X", total_price=100,
                                       status="Confirmada", travelers=2)], [],
        "Q1")
    prompt = captured["contents"]
    for secreto in ("Roberto", "roberto.gomez@gmail.com", "001-1234567",
                    "809555", "Pasaporte"):
        assert secreto not in prompt
    assert "Cliente A" in prompt


def test_prompt_recomendaciones_sin_pii(monkeypatch):
    captured = _mock_gemini(monkeypatch, text=None)
    ai_service.get_recommendations(
        {"name": "Roberto Gómez", "email": "roberto.gomez@gmail.com",
         "document_id": "001-1", "category": "VIP"},
        3000, "Playa", 2, "buceo")
    prompt = captured["contents"]
    for secreto in ("Roberto", "roberto.gomez@gmail.com", "001-1"):
        assert secreto not in prompt
    assert "Cliente interesado" in prompt


def test_salida_incompleta_usa_defaults():
    parcial = {"affinityScore": 150, "recommendedPackages": [
        {"title": "  Tour X  ", "destination": "Y"}]}
    limpio = ai_service.validate_recommendations(parcial)
    assert limpio is not None
    assert limpio["affinityScore"] == 100  # acotado
    assert limpio["profileSummary"] == ""
    assert limpio["recommendedPackages"][0]["title"] == "Tour X"
    assert limpio["recommendedPackages"][0]["estimatedPricePerPerson"] == 0
    assert ai_service.validate_recommendations({"nada": 1}) is None
    assert ai_service.validate_predictive({"summary": "ok"}) is None


def test_proveedor_caido_activa_respaldo(monkeypatch):
    _mock_gemini(monkeypatch, exc=RuntimeError("conexión rechazada"))
    result = ai_service.get_recommendations({}, 2000, "", 2, "")
    assert result["affinityScore"] == 96  # respaldo por reglas
    assert ai_service.last_provider == "fallback"
    _mock_gemini(monkeypatch, text="esto no es json{{{")
    result2 = ai_service.get_itinerary("X", 2, 2, "", "", "")
    assert result2["destination"] == "X"  # respaldo válido


def test_timeout_acotado(monkeypatch):
    import time
    def _lento(*, model, contents, config):
        time.sleep(3)
        return SimpleNamespace(text='{"ok": true}')

    class Models:
        generate_content = staticmethod(_lento)

    class GenerateContentConfig:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr(ai_service, "_get_client",
                        lambda: SimpleNamespace(models=Models()))
    monkeypatch.setattr(ai_service, "genai_types",
                        SimpleNamespace(GenerateContentConfig=GenerateContentConfig))
    inicio = time.monotonic()
    result = ai_service.generate_gemini_json(
        "hola", lambda: {"fallback": True}, timeout=0.2)
    assert time.monotonic() - inicio < 2.5
    assert result == {"fallback": True}


def test_predictivo_persiste_con_marca_tiempo(store):
    admin = _admin(store)
    store.record_prediction(admin, "Q1", {"summary": "s"})
    from app import models as m
    setting = m.Setting.query.filter_by(key="predictive_data").first()
    assert setting is not None and setting.value == {"summary": "s"}
    assert setting.updated_at is not None


def test_auditoria_ia_sin_pii(client, store, login_as):
    login_as(client, EMPLOYEE_EMAIL)
    token = read_csrf_token(client)
    client.post("/api/ai/recommendations",
                json={"budget": 2000, "travelersCount": 2,
                      "clientProfile": {"name": "Roberto Gómez",
                                        "email": "roberto.gomez@gmail.com"}},
                headers={"X-CSRFToken": token})
    ia_logs = [log for log in store.audit_logs if log.module == "Motor IA"]
    assert ia_logs, "la llamada debe auditarse"
    for log in ia_logs:
        assert "Roberto" not in (log.details or "")
        assert "roberto.gomez@gmail.com" not in (log.details or "")


def test_chat_palabras_completas(client, login_as):
    login_as(client, CLIENT_EMAIL)
    token = read_csrf_token(client)

    def _preguntar(texto):
        return client.post("/api/chat/message", json={"message": texto},
                           headers={"X-CSRFToken": token}).get_json()

    assert _preguntar("which package is best?")["reply"] != \
        "¡Hola! 👋 Soy el asistente virtual de DDN Travel. ¿En qué puedo ayudarte hoy? Puedes preguntarme sobre reservas, pagos, documentos, seguros, itinerarios..."
    assert _preguntar("HI")["faq"] is False
    assert "Hola" in _preguntar("hi")["reply"]
    assert "Holanda" not in _preguntar("quiero viajar a Holanda")["reply"] \
        or _preguntar("quiero viajar a Holanda")["faq"] is False
