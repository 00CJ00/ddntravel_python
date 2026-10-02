"""Tests de la lógica de negocio (reglas RN-01 a RN-03) del DataStore."""
from app.extensions import db
from app.models import Booking, User


def _admin():
    return User(name="Carlos Mendoza", role="admin")


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


def test_persistencia_en_base_de_datos(store):
    cli = store.clients[0]
    result = store.create_booking(
        _admin(),
        client_id=cli.id, client_name=cli.name, client_email=cli.email,
        travelers=1, total_price=900)
    codigo = result["booking"].booking_code
    # La reserva queda confirmada en la BD, no solo en memoria.
    db.session.remove()
    assert Booking.query.filter_by(booking_code=codigo).first() is not None
    assert any(b.booking_code == codigo for b in store.bookings)