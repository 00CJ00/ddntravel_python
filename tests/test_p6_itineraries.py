"""Tests de itinerarios (RF-10) — Fase P6."""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from conftest import ADMIN_EMAIL, EMPLOYEE_EMAIL, CLIENT_EMAIL


def _sample_content():
    return {
        "days": [
            {"dayNumber": 1, "title": "Llegada", "morning": "Vuelo", "afternoon": "Check-in"},
            {"dayNumber": 2, "title": "Tour", "morning": "Excursión", "afternoon": "Playa"},
        ]
    }


def _booking_id(store):
    return store.bookings[0].id


def _post_json(client, url, payload):
    """Envía JSON con token CSRF como header X-CSRFToken."""
    resp = client.get("/dashboard")
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"',
                      resp.get_data(as_text=True)).group(1)
    return client.post(url, data=json.dumps(payload),
                       content_type="application/json",
                       headers={"X-CSRFToken": token})


def _put_json(client, url, payload):
    """Envía PUT JSON con token CSRF."""
    resp = client.get("/dashboard")
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"',
                      resp.get_data(as_text=True)).group(1)
    return client.put(url, data=json.dumps(payload),
                      content_type="application/json",
                      headers={"X-CSRFToken": token})


def _delete_json(client, url):
    """Envía DELETE con token CSRF."""
    resp = client.get("/dashboard")
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"',
                      resp.get_data(as_text=True)).group(1)
    return client.delete(url, headers={"X-CSRFToken": token})


def test_crear_itinerario(client, store, login_as):
    login_as(client, ADMIN_EMAIL)
    resp = _post_json(client, f"/bookings/{_booking_id(store)}/itinerary",
                      {"content": _sample_content(), "source": "ia"})
    assert resp.status_code == 200
    assert b"id" in resp.data


def test_obtener_itinerario(client, store, login_as):
    login_as(client, ADMIN_EMAIL)
    booking_id = _booking_id(store)
    _post_json(client, f"/bookings/{booking_id}/itinerary",
               {"content": _sample_content(), "source": "ia"})
    resp = client.get(f"/bookings/{booking_id}/itinerary")
    assert resp.status_code == 200
    assert b"days" in resp.data


def test_cliente_no_ve_itinerario_ajeno(client, store, login_as):
    login_as(client, ADMIN_EMAIL)
    client_user = next(u for u in store.available_users if u.role == "client")
    ajena = next(b for b in store.bookings if b.client_email != client_user.email)
    _post_json(client, f"/bookings/{ajena.id}/itinerary",
               {"content": _sample_content(), "source": "ia"})
    login_as(client, CLIENT_EMAIL)
    resp = client.get(f"/bookings/{ajena.id}/itinerary")
    assert resp.status_code == 404


def test_editar_itinerary_put(client, store, login_as):
    login_as(client, ADMIN_EMAIL)
    booking_id = _booking_id(store)
    resp = _post_json(client, f"/bookings/{booking_id}/itinerary",
                      {"content": _sample_content(), "source": "ia"})
    itinerary_id = resp.get_json()["id"]
    new_content = {"days": [{"dayNumber": 1, "title": "Cambiado"}]}
    resp2 = _put_json(client, f"/itineraries/{itinerary_id}", new_content)
    assert resp2.status_code == 200


def test_eliminar_itinerario_solo_admin(client, store, login_as):
    login_as(client, ADMIN_EMAIL)
    booking_id = _booking_id(store)
    resp = _post_json(client, f"/bookings/{booking_id}/itinerary",
                      {"content": _sample_content(), "source": "ia"})
    itinerary_id = resp.get_json()["id"]
    login_as(client, EMPLOYEE_EMAIL)
    resp2 = _delete_json(client, f"/itineraries/{itinerary_id}")
    assert resp2.status_code == 403
    login_as(client, ADMIN_EMAIL)
    resp3 = _delete_json(client, f"/itineraries/{itinerary_id}")
    assert resp3.status_code == 200


def test_itinerario_json_invalido_422(client, store, login_as):
    login_as(client, ADMIN_EMAIL)
    resp = _post_json(client, f"/bookings/{_booking_id(store)}/itinerary",
                      {"content": {"days": []}})
    assert resp.status_code == 422
