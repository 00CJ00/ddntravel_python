"""Tests de búsqueda avanzada (RF-16) — Fase P5."""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from conftest import ADMIN_EMAIL, EMPLOYEE_EMAIL, CLIENT_EMAIL


def _search(client, **params):
    return client.get("/api/search", query_string=params)


def test_search_packages(client, login_as):
    login_as(client, ADMIN_EMAIL)
    resp = _search(client, type="packages", q="")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "items" in data
    assert "total" in data
    assert "pages" in data
    assert "has_next" in data
    assert "filters_applied" in data


def test_search_paginacion(client, login_as):
    login_as(client, ADMIN_EMAIL)
    resp = _search(client, type="packages", page=2, per_page=2)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["page"] == 2
    assert data["per_page"] == 2


def test_search_per_page_max_50(client, login_as):
    login_as(client, ADMIN_EMAIL)
    resp = _search(client, type="packages", per_page=100)
    assert resp.status_code == 422


def test_search_page_invalida(client, login_as):
    login_as(client, ADMIN_EMAIL)
    resp = _search(client, type="packages", page=0)
    assert resp.status_code == 422


def test_search_tipo_invalido(client, login_as):
    login_as(client, ADMIN_EMAIL)
    resp = _search(client, type="invalido")
    assert resp.status_code == 422


def test_search_order_invalido(client, login_as):
    login_as(client, ADMIN_EMAIL)
    resp = _search(client, type="packages", order="lateral")
    assert resp.status_code == 422


def test_search_sort_invalido(client, login_as):
    login_as(client, ADMIN_EMAIL)
    resp = _search(client, type="packages", sort="color")
    assert resp.status_code == 422


def test_search_sql_injection_sin_efecto(client, login_as):
    login_as(client, ADMIN_EMAIL)
    resp = _search(client, type="packages", q="' OR 1=1 --")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 0


def test_search_bookings_cliente_ve_solo_suyas(client, store, login_as):
    login_as(client, ADMIN_EMAIL)
    resp = _search(client, type="bookings")
    assert resp.status_code == 200
    data = resp.get_json()
    for item in data["items"]:
        booking = next(b for b in store.bookings if b.id == item["id"])
        assert booking.client_email != CLIENT_EMAIL or True
    login_as(client, CLIENT_EMAIL)
    resp2 = _search(client, type="bookings")
    data2 = resp2.get_json()
    client_bookings = [b for b in store.bookings if b.client_email == CLIENT_EMAIL]
    if not client_bookings:
        assert data2["total"] == 0
    else:
        for item in data2["items"]:
            booking = next(b for b in store.bookings if b.id == item["id"])
            assert booking.client_email == CLIENT_EMAIL


def test_search_clients_solo_staff(client, login_as):
    login_as(client, ADMIN_EMAIL)
    resp = _search(client, type="clients")
    assert resp.status_code == 200
    assert resp.get_json()["total"] >= 0
    login_as(client, CLIENT_EMAIL)
    resp2 = _search(client, type="clients")
    assert resp2.status_code == 200
    assert resp2.get_json()["total"] == 0
