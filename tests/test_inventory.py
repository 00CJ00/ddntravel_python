"""Patrón atómico de inventario (RN-01), reutilizable, fase P2.

Se prueba ``repositories.base.decrement_if_available`` directamente: es el
único patrón de descuento de existencias. En P2 solo lo usa el paquete
(``catalog.reserve_slots_atomic``); vuelos/transporte/habitaciones son P3.
"""
from app import models as m
from app.repositories.base import decrement_if_available


def _slots(store, pkg_id):
    return store.get_package(pkg_id).available_slots


def test_descuenta_y_devuelve_true(store):
    pkg = store.packages[0]
    before = pkg.available_slots
    assert decrement_if_available(m.Package, pkg.id, m.Package.available_slots, 2) is True
    assert _slots(store, pkg.id) == before - 2


def test_sin_cupos_devuelve_false_y_no_cambia(store):
    pkg = store.packages[0]
    before = pkg.available_slots
    assert decrement_if_available(
        m.Package, pkg.id, m.Package.available_slots, before + 1) is False
    assert _slots(store, pkg.id) == before


def test_limite_exacto_se_permite(store):
    pkg = store.packages[0]
    before = pkg.available_slots
    assert decrement_if_available(m.Package, pkg.id, m.Package.available_slots, before) is True
    assert _slots(store, pkg.id) == 0


def test_id_inexistente_devuelve_false(store):
    assert decrement_if_available(m.Package, 999999, m.Package.available_slots, 1) is False


def test_cantidad_no_positiva_no_toca_la_fila(store):
    pkg = store.packages[0]
    before = pkg.available_slots
    assert decrement_if_available(m.Package, pkg.id, m.Package.available_slots, 0) is True
    assert decrement_if_available(m.Package, pkg.id, m.Package.available_slots, -3) is False
    assert _slots(store, pkg.id) == before
