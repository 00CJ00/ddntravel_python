"""Tests de voucher PDF y estado de vencimiento (RF-17) — Fase P6."""
from datetime import date, timedelta
import logging
import re

import pytest

from app import models as m
from app.models.document import TravelDocument


@pytest.fixture
def voucher_upload_dir(app, tmp_path):
    path = tmp_path / "uploads"
    app.config["UPLOAD_DIR"] = str(path)
    return path


def _admin(store):
    return m.User.query.filter_by(role="admin").first()


def _confirmed_booking(store):
    client = store.clients[0]
    result = store.create_booking(
        _admin(store),
        client_id=client.id,
        client_name=client.name,
        client_email=client.email,
        travelers=1,
        total_price=2500,
        initial_payment=2500,
    )
    assert result["success"]
    return result["booking"]


def test_confirmacion_actualiza_voucher_existente_con_pdf(store, voucher_upload_dir):
    booking = _confirmed_booking(store)
    vouchers = m.TravelDocument.query.filter_by(
        booking_id=booking.id, doc_type="Voucher de Reserva")

    assert vouchers.count() == 1
    voucher = vouchers.one()
    assert voucher.status == "Válido"
    assert re.fullmatch(r"[0-9a-f]{32}\.pdf", voucher.stored_name)
    pdf_path = voucher_upload_dir / voucher.stored_name
    assert pdf_path.is_file()
    assert pdf_path.read_bytes().startswith(b"%PDF")


def test_fallo_pdf_no_impide_confirmacion_y_deja_voucher_pendiente(
    store, voucher_upload_dir, monkeypatch, caplog
):
    import app.billing as billing

    def fail_pdf(*args, **kwargs):
        raise RuntimeError("fallo simulado de ReportLab")

    monkeypatch.setattr(billing, "generar_pdf_voucher", fail_pdf)
    caplog.set_level(logging.ERROR)
    booking = _confirmed_booking(store)
    voucher = m.TravelDocument.query.filter_by(
        booking_id=booking.id, doc_type="Voucher de Reserva").one()

    assert booking.status == "Confirmada"
    assert voucher.status == "Pendiente"
    assert voucher.stored_name is None
    assert "No se pudo generar el voucher PDF" in caplog.text
    assert not voucher_upload_dir.exists() or not list(voucher_upload_dir.iterdir())


def test_estado_calculado_de_vencimiento():
    assert TravelDocument(expiry_date=None).expiry_status == "Vigente"
    assert TravelDocument(expiry_date=date.today() - timedelta(days=1)).expiry_status == "Vencido"
    assert TravelDocument(expiry_date=date.today() + timedelta(days=30)).expiry_status == "Por vencer"
    assert TravelDocument(expiry_date=date.today() + timedelta(days=240)).expiry_status == "Vigente"
