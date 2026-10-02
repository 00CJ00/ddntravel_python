"""Tests de la matriz de permisos de ``app/permissions.py``.

Se validan tres cosas que no dependen de HTTP: la coherencia interna de la
matriz, el cálculo de permisos por rol y las reglas de propiedad (anti-IDOR).
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.permissions as permissions  # noqa: E402
from app.models.legacy import UserSession  # noqa: E402


def _user(role: str, user_id: str = "usr-x", email: str = "x@example.com") -> UserSession:
    return UserSession(id=user_id, name=f"Usuario {role}", email=email, role=role)


# ----------------------------------------------------------------------
# Coherencia de la matriz
# ----------------------------------------------------------------------
def test_todos_los_permisos_declaran_solo_roles_validos():
    for permiso, roles in permissions.PERMISSIONS.items():
        assert roles, f"El permiso {permiso!r} no tiene ningún rol autorizado"
        assert roles <= set(permissions.ROLES), f"{permiso!r} tiene roles desconocidos: {roles}"


def test_los_permisios_de_las_rutas_existen_en_la_matriz():
    """Cada endpoint declarado debe apuntar a un permiso real de la matriz."""
    for endpoint, permiso in permissions.ENDPOINT_PERMISSIONS.items():
        assert permiso in permissions.PERMISSIONS, \
            f"{endpoint} usa el permiso {permiso!r}, que no está en la matriz"


def test_can_rechaza_permisos_no_declarados():
    with pytest.raises(KeyError):
        permissions.can("no:existe", _user("admin"))


def test_can_sin_sesion_devuelve_false(app):
    with app.test_request_context("/"):
        assert permissions.can("dashboard:view") is False


# ----------------------------------------------------------------------
# Cobertura de la matriz sobre el mapa de rutas real
# ----------------------------------------------------------------------
def test_toda_ruta_que_muta_declara_su_permiso(app):
    """Ninguna ruta POST/PUT/DELETE puede quedar sin permiso declarado.

    Evita que una ruta nueva heredada (``@route`` sin ``@permission_required``)
    quede abierta por descuido: o bien el decorador registra el permiso que
    exige, o bien el endpoint está documentado en ``ENDPOINT_PERMISSIONS``.
    """
    sin_permiso = []
    for regla in app.url_map.iter_rules():
        metodos = regla.methods - {"HEAD", "OPTIONS", "GET"}
        if not metodos:
            continue
        if regla.endpoint in permissions.ENDPOINT_PERMISSIONS:
            continue
        vista = app.view_functions[regla.endpoint]
        if getattr(vista, "required_permission", None):
            continue
        sin_permiso.append(f"{regla.endpoint} {sorted(metodos)}")
    assert not sin_permiso, f"rutas mutantes sin permiso declarado: {sin_permiso}"


def test_todo_endpoint_registrado_existe(app):
    """``ENDPOINT_PERMISSIONS`` no puede apuntar a endpoints inexistentes."""
    existentes = {r.endpoint for r in app.url_map.iter_rules()}
    huerfanos = set(permissions.ENDPOINT_PERMISSIONS) - existentes
    assert not huerfanos, f"endpoints registrados que no existen: {huerfanos}"


def test_todo_endpoint_con_permiso_usa_ese_mismo_permiso(app):
    """El decorador aplicado y el mapa documentado deben coincidir."""
    discrepancias = []
    for endpoint, permiso in permissions.ENDPOINT_PERMISSIONS.items():
        vista = app.view_functions.get(endpoint)
        if vista is None:
            continue
        declarado = getattr(vista, "required_permission", None)
        if declarado and declarado != permiso:
            discrepancias.append(f"{endpoint}: decorador={declarado} mapa={permiso}")
    assert not discrepancias, discrepancias


def test_ninguna_ruta_heredada_usa_el_decorador_old():
    """``role_required`` se eliminó: la matriz es la única fuente de verdad."""
    import app.routes as rutas
    assert not hasattr(rutas, "role_required"), "role_required deberia estar eliminado"


# ----------------------------------------------------------------------
# Permisos por rol (tabla de la fase P1)
# ----------------------------------------------------------------------
@pytest.mark.parametrize("permiso,admin,employee,client", [
    ("session:entry", True, True, True),
    ("session:logout", True, True, True),
    ("dashboard:view", True, True, False),
    ("reports:view", True, True, False),
    ("audit:view", True, False, False),
    ("clients:view", True, True, False),
    ("clients:create", True, True, False),
    ("clients:edit", True, True, False),
    ("clients:delete", True, False, False),
    ("catalog:view_packages", True, True, True),
    ("catalog:view_destinations", True, True, True),
    ("catalog:view_activities", True, True, True),
    ("catalog:view_hotels", True, True, False),
    ("catalog:view_flights", True, True, False),
    ("catalog:view_transports", True, True, False),
    ("catalog:create", True, False, False),
    ("catalog:edit", True, False, False),
    ("catalog:delete", True, False, False),
    ("bookings:view", True, True, False),
    ("bookings:create", True, True, True),
    ("bookings:edit", True, True, False),
    ("bookings:status", True, True, False),
    ("bookings:cancel", True, True, True),
    ("payments:view", True, True, False),
    ("payments:create", True, True, False),
    ("payments:void", True, False, False),
    ("payments:invoice", True, True, True),
    ("promotions:view", True, True, False),
    ("promotions:apply", True, True, True),
    ("promotions:create", True, False, False),
    ("promotions:toggle", True, False, False),
    ("documents:view", True, True, True),
    ("documents:create", True, True, True),
    ("documents:delete", True, False, False),
    ("users:manage", True, False, False),
    ("ai:predictive_view", True, True, True),
    ("ai:predictive_run", True, True, False),
    ("ai:recommend", True, True, True),
    ("ai:itinerary", True, True, True),
    ("data:reset", True, False, False),
])
def test_matriz_de_permisos_por_rol(permiso, admin, employee, client):
    esperado = {"admin": admin, "employee": employee, "client": client}
    for rol, debe_poder in esperado.items():
        assert permissions.can(permiso, _user(rol)) is debe_poder, \
            f"{rol} debería {'poder' if debe_poder else 'no poder'} usar {permiso}"


# ----------------------------------------------------------------------
# Propiedad de los datos
# ----------------------------------------------------------------------
def test_owns_para_internos_siempre_true(store):
    booking = store.bookings[0]
    assert permissions.owns(_user("admin"), booking) is True
    assert permissions.owns(_user("employee"), booking) is True


def test_owns_solo_para_la_reserva_del_cliente(store):
    cliente = store.clients[0]
    otro = store.clients[1]
    user = _user("client", email=cliente.email)

    booking_propio = next(b for b in store.bookings if b.client_id == cliente.id)
    booking_ajeno = next(b for b in store.bookings if b.client_id == otro.id)

    assert permissions.owns(user, booking_propio) is True
    assert permissions.owns(user, booking_ajeno) is False


def test_own_records_filtra_la_lista(store):
    cliente = store.clients[0]
    user = _user("client", email=cliente.email)
    propios = permissions.own_records(user, store.bookings)
    assert propios
    assert all(permissions.owns(user, b) for b in propios)
    assert len(propios) < len(store.bookings)


def test_owns_de_un_pago_se_resuelve_via_su_reserva(store):
    booking = store.bookings[0]
    pago = next(p for p in store.payments if p.booking_id == booking.id)
    dueno = _user("client", email=booking.client_email)
    intrusion = _user("client", email="nadie@example.com")
    assert permissions.owns(dueno, pago) is True
    assert permissions.owns(intrusion, pago) is False


def test_owned_or_404_responde_404_para_registros_ajenos(store, app):
    otro = store.clients[1]
    user = _user("client", email="nadie@example.com")
    with app.test_request_context("/"):
        with pytest.raises(Exception) as exc:
            permissions.owned_or_404(user, otro)
    assert getattr(exc.value, "code", None) == 404
