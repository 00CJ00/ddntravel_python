"""Tests de la lógica de negocio (reglas RN-01 a RN-03) del DataStore."""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.store as store_module
from app.models import UserSession


@pytest.fixture
def store(tmp_path, monkeypatch):
    """DataStore limpio a partir de los datos de semilla, sin tocar el estado real."""
    monkeypatch.setattr(store_module, "STATE_PATH", tmp_path / "state.json")
    st = store_module.DataStore()
    st.reset_all_data(log=False)
    return st


def _admin():
    return UserSession(id="usr-admin-1", name="Carlos Mendoza", role="admin")


def test_reset_data_carga_las_semillas(store):
    assert len(store.clients) > 0
    assert len(store.packages) > 0
    assert len(store.bookings) > 0


def test_rn01_reserva_con_sin_disponibilidad_rechazada(store):
    pkg = store.packages[0]
    too_many = pkg.available_slots + 1
    cli = store.clients[0]
    result = store.create_booking(
        _admin(),
        client_id=cli.id, client_name=cli.name, client_email=cli.email,
        package_id=pkg.id, travelers=too_many, total_price=1000)
    assert result["success"] is False
    assert "RN-01" in result["message"]


def test_rn01_reserva_con_cupos_resta_disponibilidad(store):
    pkg = store.packages[0]
    before = pkg.available_slots
    cli = store.clients[0]
    result = store.create_booking(
        _admin(),
        client_id=cli.id, client_name=cli.name, client_email=cli.email,
        package_id=pkg.id, travelers=1, total_price=1000)
    assert result["success"] is True
    assert pkg.available_slots == before - 1


def test_rn02_reserva_sin_cliente_rechazada(store):
    result = store.create_booking(_admin(), client_id="", client_name="", client_email="")
    assert result["success"] is False
    assert "RN-02" in result["message"]


def test_rn03_pago_completo_confirma_reserva(store):
    cli = store.clients[0]
    result = store.create_booking(
        _admin(),
        client_id=cli.id, client_name=cli.name, client_email=cli.email,
        travelers=1, total_price=2500, initial_payment=2500)
    assert result["success"] is True
    booking = result["booking"]
    assert booking.status == "Confirmada"
    assert booking.payment_status == "Pagado"
    assert booking.is_fully_paid()


def test_rn03_pago_parcial_deja_reserva_pendiente(store):
    cli = store.clients[0]
    result = store.create_booking(
        _admin(),
        client_id=cli.id, client_name=cli.name, client_email=cli.email,
        travelers=1, total_price=2500, initial_payment=1000)
    assert result["success"] is True
    assert result["booking"].payment_status == "Parcial"
    assert not result["booking"].is_fully_paid()


def test_rn03_registrar_pago_completa_reserva(store):
    cli = store.clients[0]
    result = store.create_booking(
        _admin(),
        client_id=cli.id, client_name=cli.name, client_email=cli.email,
        travelers=1, total_price=1500, initial_payment=500)
    booking = result["booking"]
    store.register_payment(_admin(), booking.id, 1000, "Tarjeta de Crédito")
    assert booking.status == "Confirmada"
    assert booking.payment_status == "Pagado"


def test_persistencia_sobrevive_al_reinicio(store):
    cli = store.clients[0]
    store.create_booking(
        _admin(),
        client_id=cli.id, client_name=cli.name, client_email=cli.email,
        travelers=1, total_price=900)
    # Simula el reinicio: queda la misma ruta de estado (tmp_path) y se vuelve a cargar
    reloaded = store_module.DataStore()
    assert len(reloaded.bookings) == len(store.bookings)
    assert reloaded.bookings[0].total_price == 900