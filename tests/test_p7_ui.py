"""Pruebas de los flujos de interfaz incorporados en la fase P7."""
from datetime import date

from conftest import ADMIN_EMAIL, CLIENT_EMAIL, DEMO_PASSWORD, login, post_form


def test_booking_form_defaults_to_non_past_dates(client, store):
    login(client, ADMIN_EMAIL, DEMO_PASSWORD)
    html = client.get("/bookings").get_data(as_text=True)
    departure = date.fromisoformat(_input_value(html, "booking-departure-date"))
    return_date = date.fromisoformat(_input_value(html, "booking-return-date"))
    assert departure >= date.today()
    assert return_date > departure


def test_client_html_no_longer_contains_global_store_data(client, store):
    login(client, CLIENT_EMAIL, DEMO_PASSWORD)
    html = client.get("/client-portal").get_data(as_text=True)
    assert "DDN_DATA" not in html


def test_admin_can_manage_destination_and_hotel_from_catalog_forms(client, store):
    login(client, ADMIN_EMAIL, DEMO_PASSWORD)

    destination_response = post_form(client, "/admin/destinations", {
        "name": "P7 Destino de prueba",
        "country": "República Dominicana",
        "region": "Este",
        "high_season_months": "12,1",
        "popular_attractions": "Playa, Centro",
        "base_price_usd": "125.50",
    })
    assert destination_response.status_code == 200
    destination_id = destination_response.get_json()["id"]
    destination = next(item for item in store.destinations if item.id == destination_id)
    assert destination.high_season_months == [12, 1]
    assert destination.popular_attractions == ["Playa", "Centro"]

    edit_response = post_form(client, f"/admin/destinations/{destination_id}", {
        "name": "P7 Destino editado",
        "country": "República Dominicana",
        "high_season_months": "7",
        "popular_attractions": "Parque",
        "base_price_usd": "200",
    })
    assert edit_response.status_code == 200
    assert next(item for item in store.destinations if item.id == destination_id).name == "P7 Destino editado"

    hotel_response = post_form(client, "/admin/hotels/new", {
        "name": "Hotel P7 de prueba",
        "destination_name": "P7 Destino editado",
        "stars": "4",
        "rating": "4.5",
        "amenities": "Piscina, Wi-Fi",
        "room_types_count": "1",
        "room_type[0][type]": "Suite",
        "room_type[0][price_per_night]": "150",
        "room_type[0][available]": "8",
    }, headers={"X-Requested-With": "XMLHttpRequest"})
    assert hotel_response.status_code == 200
    hotel_id = hotel_response.get_json()["id"]
    hotel = next(item for item in store.hotels if item.id == hotel_id)
    assert hotel.amenities == ["Piscina", "Wi-Fi"]
    assert hotel.room_types[0].name == "Suite"

    hotel_edit = post_form(client, f"/admin/hotels/{hotel_id}", {
        "name": "Hotel P7 editado",
        "destination_name": "P7 Destino editado",
        "stars": "5",
        "rating": "4.8",
        "amenities": "Piscina",
        "room_types_count": "1",
        "room_type[0][type]": "Suite",
        "room_type[0][price_per_night]": "175",
        "room_type[0][available]": "7",
    })
    assert hotel_edit.status_code == 200
    assert next(item for item in store.hotels if item.id == hotel_id).name == "Hotel P7 editado"

    hotel_delete = post_form(client, f"/admin/hotels/{hotel_id}/delete")
    destination_delete = post_form(client, f"/admin/destinations/{destination_id}/delete")
    assert hotel_delete.get_json()["success"] is True
    assert destination_delete.get_json()["success"] is True


def test_catalog_modal_create_endpoints_return_json_for_ajax(client, store):
    """Los formularios del modal esperan JSON, incluso al crear o validar."""
    login(client, ADMIN_EMAIL, DEMO_PASSWORD)
    ajax = {"X-Requested-With": "XMLHttpRequest"}
    forms = [
        ("/admin/packages/new", {"title": "Paquete P7", "price_usd": "250"}),
        ("/admin/flights/new", {
            "airline": "Aerolínea P7", "flight_number": "P7-101", "origin": "SDQ",
            "destination": "PUJ", "price_usd": "100", "total_seats": "10",
        }),
        ("/admin/transports/new", {
            "type": "Van", "vehicle_model": "P7", "price_usd": "20",
        }),
        ("/admin/activities/new", {"title": "Tour P7", "price_usd": "30"}),
    ]
    for path, data in forms:
        response = post_form(client, path, data, headers=ajax)
        assert response.status_code == 200, (path, response.get_data(as_text=True))
        result = response.get_json()
        assert result and result["success"] and result["id"]

    invalid_forms = [
        ("/admin/packages/new", {"price_usd": "abc"}),
        ("/admin/flights/new", {"airline": "", "price_usd": "abc"}),
        ("/admin/transports/new", {"type": "", "price_usd": "abc"}),
        ("/admin/activities/new", {"title": "", "price_usd": "abc"}),
    ]
    for path, data in invalid_forms:
        response = post_form(client, path, data, headers=ajax)
        assert response.status_code == 422, (path, response.get_data(as_text=True))
        result = response.get_json()
        assert result and result["success"] is False and result["errors"]


def test_user_role_and_activation_controls_are_functional(client, store):
    login(client, ADMIN_EMAIL, DEMO_PASSWORD)
    employee = next(user for user in store.available_users if user.role == "employee")

    role_response = post_form(client, f"/admin/users/{employee.id}/edit", {"role": "client"})
    assert role_response.status_code == 302
    assert store.get_user(employee.id).role == "client"

    deactivate_response = post_form(client, f"/admin/users/{employee.id}/status", {"is_active": "0"})
    assert deactivate_response.status_code == 302
    assert store.get_user(employee.id).is_active is False

    activate_response = post_form(client, f"/admin/users/{employee.id}/status", {"is_active": "1"})
    assert activate_response.status_code == 302
    assert store.get_user(employee.id).is_active is True


def test_catalog_and_client_actions_follow_the_role(client, store):
    login(client, ADMIN_EMAIL, DEMO_PASSWORD)
    for route in ("/destinations", "/hotels", "/clients"):
        response = client.get(route)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        if route == "/destinations":
            assert "data-destination-edit" in html
        elif route == "/hotels":
            assert "data-hotel-edit" in html
        else:
            assert "data-client-edit" in html

    from conftest import EMPLOYEE_EMAIL
    login(client, EMPLOYEE_EMAIL, DEMO_PASSWORD)
    assert "data-destination-edit" not in client.get("/destinations").get_data(as_text=True)
    assert "data-hotel-edit" not in client.get("/hotels").get_data(as_text=True)
    employee_clients = client.get("/clients").get_data(as_text=True)
    assert "data-client-edit" in employee_clients
    assert "data-client-delete" not in employee_clients


def _input_value(html: str, element_id: str) -> str:
    import re

    match = re.search(
        rf'<input[^>]*id="{re.escape(element_id)}"[^>]*value="([^"]+)"',
        html,
    )
    assert match, f"No se encontró el input #{element_id}"
    return match.group(1)
