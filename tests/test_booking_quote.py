"""Pruebas para cotizaciones de reservas calculadas por el servidor."""
from decimal import Decimal

from conftest import ADMIN_EMAIL, DEMO_PASSWORD

from app.models import PromotionRedemption


def _login(client, email=ADMIN_EMAIL):
    from conftest import login

    return login(client, email, DEMO_PASSWORD)


def test_quote_calculates_package_and_flight_prices_from_database(client, store):
    _login(client)
    package = next(p for p in store.packages if p.available_slots >= 3)
    flight = store.flights[0]

    response = client.get("/api/bookings/quote", query_string={
        "package_id": package.id,
        "flight_id": flight.id,
        "travelers": 3,
    })

    assert response.status_code == 200
    quote = response.get_json()
    expected = (Decimal(str(package.price_usd)) + Decimal(str(flight.price_usd))) * 3
    assert quote["success"] is True
    assert Decimal(str(quote["total"])) == expected
    assert quote["travelers"] == 3


def test_quote_hotel_uses_nights_and_rooms(client, store):
    _login(client)
    hotel = next(h for h in store.hotels if h.room_types)
    nightly_rate = Decimal(str(hotel.room_types[0].price_per_night))

    response = client.get("/api/bookings/quote", query_string={
        "hotel_id": hotel.id,
        "departure_date": "2030-06-01",
        "return_date": "2030-06-06",
        "rooms_count": 2,
        "travelers": 2,
    })

    assert response.status_code == 200
    quote = response.get_json()
    assert Decimal(str(quote["total"])) == nightly_rate * 5 * 2
    assert quote["nights"] == 5
    assert quote["rooms_count"] == 2


def test_quote_uses_selected_room_type_and_rejects_type_from_another_hotel(client, store):
    _login(client)
    hotels = [hotel for hotel in store.hotels if hotel.room_types]
    hotel, other_hotel = hotels[:2]
    room_type = hotel.room_types[-1]

    response = client.get("/api/bookings/quote", query_string={
        "hotel_id": hotel.id,
        "room_type_id": room_type.id,
        "departure_date": "2030-06-01",
        "return_date": "2030-06-06",
        "rooms_count": 2,
    })
    assert response.status_code == 200
    quote = response.get_json()
    expected = Decimal(str(room_type.price_per_night)) * 5 * 2
    assert Decimal(str(quote["total"])) == expected
    assert quote["room_type_id"] == room_type.id
    assert quote["room_type_name"] == room_type.name

    mismatch = client.get("/api/bookings/quote", query_string={
        "hotel_id": hotel.id,
        "room_type_id": other_hotel.room_types[0].id,
        "departure_date": "2030-06-01",
        "return_date": "2030-06-06",
    })
    assert mismatch.status_code == 422


def test_booking_persists_selected_room_type_and_room_count(client, store, post_csrf):
    _login(client)
    hotel = next(h for h in store.hotels if h.room_types)
    room_type = hotel.room_types[-1]
    customer = store.clients[0]
    price = Decimal(str(room_type.price_per_night)) * 5 * 2

    response = post_csrf(client, "/bookings/new", {
        "client_id": str(customer.id),
        "hotel_id": str(hotel.id),
        "room_type_id": str(room_type.id),
        "departure_date": "2030-06-01",
        "return_date": "2030-06-06",
        "rooms_count": "2",
        "travelers": "2",
        "initial_payment": "0",
    })
    assert response.status_code == 302
    booking = max(
        (b for b in store.bookings if b.hotel_id == hotel.id),
        key=lambda b: b.id,
    )
    assert booking.room_type_id == room_type.id
    assert booking.rooms_count == 2
    assert Decimal(str(booking.total_price)) == price

    admin = next(user for user in store.available_users if user.role == "admin")
    result = store.update_booking(admin, booking.id, notes="Revisión")
    assert result["success"] is True
    assert Decimal(str(booking.total_price)) == price


def test_quote_rejects_hotel_dates_that_do_not_form_a_positive_stay(client, store):
    _login(client)
    hotel = next(h for h in store.hotels if h.room_types)

    response = client.get("/api/bookings/quote", query_string={
        "hotel_id": hotel.id,
        "departure_date": "2030-06-05",
        "return_date": "2030-06-01",
    })

    assert response.status_code == 422
    assert "posterior" in response.get_json()["error"]


def test_quote_requires_both_hotel_stay_dates(client, store):
    _login(client)
    hotel = next(h for h in store.hotels if h.room_types)

    response = client.get("/api/bookings/quote", query_string={
        "hotel_id": hotel.id,
        "departure_date": "2030-06-01",
    })

    assert response.status_code == 422
    assert "fechas" in response.get_json()["error"]


def test_quote_rejects_invalid_catalog_ids_and_numbers(client):
    _login(client)
    for params in (
        {"package_id": "999999"},
        {"flight_id": "not-an-id"},
        {"travelers": "11"},
        {"travelers": "not-a-number"},
    ):
        response = client.get("/api/bookings/quote", query_string=params)
        assert response.status_code == 422
        assert response.get_json()["success"] is False
        assert response.get_json()["error"]


def test_booking_rejects_unknown_selected_package_without_creating_booking(
    client, store, post_csrf
):
    _login(client)
    customer = store.clients[0]
    previous_count = len(store.bookings)

    response = post_csrf(client, "/bookings/new", {
        "client_id": str(customer.id),
        "package_id": "999999",
        "travelers": "1",
        "initial_payment": "0",
    })

    assert response.status_code == 302
    assert len(store.bookings) == previous_count


def test_client_can_quote_public_packages_but_not_internal_hotel_or_flight(
    client, store, login_as
):
    login_as(client, "roberto.gomez@gmail.com")
    package = next(p for p in store.packages if p.available_slots >= 1)
    public_quote = client.get("/api/bookings/quote", query_string={
        "package_id": package.id,
        "travelers": 1,
    })
    assert public_quote.status_code == 200

    hotel = next(h for h in store.hotels if h.room_types)
    forbidden_hotel_quote = client.get("/api/bookings/quote", query_string={
        "hotel_id": hotel.id,
        "travelers": 1,
    })
    assert forbidden_hotel_quote.status_code == 403

    flight = store.flights[0]
    forbidden_flight_quote = client.get("/api/bookings/quote", query_string={
        "flight_id": flight.id,
        "travelers": 1,
    })
    assert forbidden_flight_quote.status_code == 403


def test_booking_post_uses_server_quote_not_submitted_total(client, store, post_csrf):
    _login(client)
    package = next(p for p in store.packages if p.available_slots >= 2)
    customer = store.clients[0]
    expected = Decimal(str(package.price_usd)) * 2

    response = post_csrf(client, "/bookings/new", {
        "client_id": str(customer.id),
        "package_id": str(package.id),
        "travelers": "2",
        "total_price": "0.01",
        "initial_payment": "0",
    })

    assert response.status_code == 302
    booking = max(
        (b for b in store.bookings if b.package_id == package.id),
        key=lambda b: b.id,
    )
    assert Decimal(str(booking.total_price)) == expected


def test_quote_and_booking_apply_only_client_eligible_promotion(client, store, post_csrf):
    _login(client)
    customer = next(c for c in store.clients if c.category != "VIP")
    package = next(p for p in store.packages if p.available_slots >= 1)
    promo = store.add_promotion(
        store.available_users[0],
        code="VIPQUOTE",
        title="Solo VIP",
        discount_percentage=20,
        max_uses=10,
        applicable_categories=["VIP"],
        active=True,
    )
    subtotal = Decimal(str(package.price_usd))

    quote = client.get("/api/bookings/quote", query_string={
        "client_id": customer.id,
        "package_id": package.id,
        "travelers": 1,
        "promo_code": promo.code,
    })
    assert quote.status_code == 200
    assert quote.get_json()["promo_valid"] is False
    assert Decimal(str(quote.get_json()["total"])) == subtotal

    response = post_csrf(client, "/bookings/new", {
        "client_id": str(customer.id),
        "package_id": str(package.id),
        "travelers": "1",
        "promo_code": promo.code,
        "total_price": "0.01",
        "initial_payment": "0",
    })
    assert response.status_code == 302
    booking = max(
        (b for b in store.bookings if b.package_id == package.id),
        key=lambda b: b.id,
    )
    assert Decimal(str(booking.total_price)) == subtotal
    assert promo.current_uses == 0
    assert PromotionRedemption.query.filter_by(promotion_id=promo.id).count() == 0


def test_quote_and_booking_use_the_same_valid_promotion(client, store, post_csrf):
    _login(client)
    customer = store.clients[0]
    package = next(p for p in store.packages if p.available_slots >= 1)
    admin = next(user for user in store.available_users if user.role == "admin")
    promo = store.add_promotion(
        admin,
        code="QUOTE10",
        title="Descuento de prueba",
        discount_percentage=10,
        max_uses=10,
        applicable_categories=["Todos"],
        active=True,
    )
    subtotal = Decimal(str(package.price_usd))
    expected_total = subtotal * Decimal("0.90")

    quote_response = client.get("/api/bookings/quote", query_string={
        "client_id": customer.id,
        "package_id": package.id,
        "travelers": 1,
        "promo_code": promo.code,
    })
    assert quote_response.status_code == 200
    quote = quote_response.get_json()
    assert quote["promo_valid"] is True
    assert Decimal(str(quote["total"])) == expected_total

    response = post_csrf(client, "/bookings/new", {
        "client_id": str(customer.id),
        "package_id": str(package.id),
        "travelers": "1",
        "promo_code": promo.code,
        "total_price": "0.01",
        "initial_payment": "0",
    })
    assert response.status_code == 302
    booking = max(
        (b for b in store.bookings if b.package_id == package.id),
        key=lambda b: b.id,
    )
    assert Decimal(str(booking.total_price)) == expected_total
    assert promo.current_uses == 1
    assert PromotionRedemption.query.filter_by(
        promotion_id=promo.id, booking_id=booking.id
    ).count() == 1


def test_category_limited_promotion_is_not_valid_without_client_category(client, store):
    _login(client)
    package = next(p for p in store.packages if p.available_slots >= 1)
    admin = next(user for user in store.available_users if user.role == "admin")
    promo = store.add_promotion(
        admin,
        code="CATEGORYQUOTE",
        title="Solo categoría",
        discount_percentage=15,
        max_uses=10,
        applicable_categories=["VIP"],
        active=True,
    )

    response = client.get("/api/bookings/quote", query_string={
        "package_id": package.id,
        "travelers": 1,
        "promo_code": promo.code,
    })

    assert response.status_code == 200
    assert response.get_json()["promo_valid"] is False
