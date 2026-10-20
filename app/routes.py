"""Rutas de la aplicación DDN Travel (equivalente a App.tsx + server.ts).

La autorización se resuelve con ``app/permissions.py``: cada ruta declara el
permiso que exige (``@permission_required``) y, cuando aplica, además verifica
la propiedad del registro (``owned_or_404``). La matriz de permisos es la
única fuente de verdad; aquí no se comprueban roles a mano.
"""
from __future__ import annotations

import os
import re
from datetime import date, timedelta

from flask import (
    Blueprint, render_template, request, redirect, url_for, session, jsonify,
    abort, flash, current_app
)
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import check_password_hash

from io import BytesIO
from flask import send_file

from .store import store
from . import ai_service
from . import permissions as _permissions
from .extensions import db, limiter
from .view import store_view
from .permissions import (
    ENDPOINT_PERMISSIONS, PERMISSIONS, PUBLIC_ENDPOINTS, can, client_record,
    get_current_user, get_store, owned_or_404, own_records, owns,
    permission_required,
)
from .repositories.base import to_decimal

bp = Blueprint("main", __name__)

# Endpoints accesibles sin haber iniciado sesión (definidos en app/permissions.py).
LOGIN_EXEMPT = set(PUBLIC_ENDPOINTS)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def int_field(form, key, default, minimum=None, maximum=None):
    """Lee un entero de un formulario de forma segura (nunca lanza ValueError)."""
    try:
        value = int(form.get(key, default))
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def float_field(form, key, default=0.0):
    """Lee un float de un formulario de forma segura (nunca lanza ValueError)."""
    try:
        return float(form.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _booking_quote(data, client_category=None, *, is_client=False):
    """Calcula en el servidor el mismo total que se guardará en la reserva."""
    def selected_id(name, maximum):
        value = (data.get(name) or "").strip()
        if not value:
            return None
        if not value.isdecimal():
            raise ValueError(f"El recurso seleccionado en '{name}' no es válido.")
        item = maximum(value)
        if item is None:
            raise ValueError(f"El recurso seleccionado en '{name}' ya no está disponible.")
        return item

    def bounded_int(name, default, minimum, maximum):
        value = data.get(name)
        if value in (None, ""):
            return default
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"El campo '{name}' debe ser un número entero.") from None
        if not minimum <= parsed <= maximum:
            raise ValueError(f"El campo '{name}' debe estar entre {minimum} y {maximum}.")
        return parsed

    travelers = bounded_int("travelers", 1, 1, 10)
    rooms_count = bounded_int("rooms_count", 1, 1, 20)
    package = selected_id("package_id", store.get_package)
    hotel_id = (data.get("hotel_id") or "").strip()
    flight_id = (data.get("flight_id") or "").strip()
    room_type_id = (data.get("room_type_id") or "").strip()
    if is_client and (hotel_id or flight_id):
        abort(403)
    hotel = selected_id("hotel_id", store.get_hotel)
    flight = selected_id("flight_id", store.get_flight)
    room_type = selected_id("room_type_id", store.get_room_type)
    if room_type and (hotel is None or room_type.hotel_id != hotel.id):
        raise ValueError("El tipo de habitación no corresponde al hotel seleccionado.")
    if hotel:
        if not hotel.room_types:
            raise ValueError("El hotel seleccionado no tiene tipos de habitación con tarifa.")
        if room_type is None:
            room_type = hotel.room_types[0]
    if package and package.available_slots < travelers:
        raise ValueError("No hay cupos suficientes para la cantidad de viajeros.")
    if flight and flight.seats_available < travelers:
        raise ValueError("No hay asientos suficientes para la cantidad de viajeros.")

    flight_addon = to_decimal(flight.price_usd or 0) * travelers if flight else 0
    nights = 1
    if package:
        subtotal = to_decimal(package.price_usd or 0) * travelers + flight_addon
    elif hotel:
        from datetime import date as _date

        check_in = data.get("check_in") or data.get("departure_date") or ""
        check_out = data.get("check_out") or data.get("return_date") or ""
        if not check_in or not check_out:
            raise ValueError("Debes indicar las fechas de entrada y salida del hotel.")
        try:
            nights = (_date.fromisoformat(check_out) - _date.fromisoformat(check_in)).days
        except (ValueError, TypeError):
            raise ValueError("Las fechas de entrada o salida del hotel no son válidas.") from None
        if nights < 1:
            raise ValueError("La salida del hotel debe ser posterior a la entrada.")
        nightly_rate = to_decimal(room_type.price_per_night or 0)
        subtotal = nightly_rate * nights * rooms_count + flight_addon
    else:
        subtotal = to_decimal("300") * travelers + flight_addon

    promo_code = (data.get("promo_code") or "").strip()
    promo_result = store.apply_promo_code(
        promo_code, subtotal, client_category=client_category
    ) if promo_code else {
        "valid": False,
        "discount_percentage": 0,
        "final_price": float(subtotal),
        "message": "",
    }
    if promo_result["valid"]:
        discount_rate = to_decimal(promo_result["discount_percentage"])
        total = (
            subtotal * (to_decimal("100") - discount_rate) / to_decimal("100")
        ).quantize(to_decimal("0.01"))
    else:
        total = subtotal
    return {
        "travelers": travelers,
        "rooms_count": rooms_count,
        "room_type_id": room_type.id if room_type else None,
        "room_type_name": room_type.name if room_type else "",
        "nights": nights,
        "subtotal": subtotal,
        "discount": subtotal - total,
        "total": total,
        "promo_code": promo_code if promo_result["valid"] else "",
        "promo_result": promo_result,
    }


def dev_switch_enabled():
    """El selector de usuario solo existe en desarrollo y con el flag puesto.

    Es una ayuda de demostración (RF-01) y una escalada de privilegios
    evidente, así que queda apagado salvo que se pida explícitamente.
    """
    from flask import current_app
    return bool(current_app.debug) and bool(current_app.config.get("ENABLE_DEV_SWITCH"))


@bp.before_request
def require_login():
    if request.endpoint in LOGIN_EXEMPT or request.endpoint == "static" or request.endpoint is None:
        return None
    if get_current_user() is None:
        return redirect(url_for("main.login"))
    return None


def redirect_back(default_endpoint: str):
    ref = request.referrer
    if ref and request.host_url.rstrip("/") in ref:
        return redirect(ref)
    return redirect(url_for(default_endpoint))


def find_payment(payment_id: str):
    """Busca un pago por su identificador a través del repositorio."""
    return store.get_payment(payment_id)


def payments_by_booking(bookings):
    """Devuelve solo los pagos de las reservas visibles en esta página."""
    booking_ids = {booking.id for booking in bookings}
    result = {}
    for payment in store.payments:
        if payment.booking_id in booking_ids:
            result.setdefault(payment.booking_id, []).append({
                "id": payment.id,
                "receipt_number": payment.receipt_number,
                "amount": str(payment.amount),
                "status": payment.status,
                "kind": payment.kind,
            })
    return result


def not_implemented_yet(feature: str):
    """501 explícito para funcionalidades planificadas en fases posteriores.

    Evita el 500 opaco de una ruta que todavía no tiene la lógica implementada
    (la autorización y la propiedad ya se han comprobado antes de llegar aquí).
    """
    message = (f"{feature} todavía no está disponible: queda implementada en la "
               f"fase P4 del proyecto (pendiente de fase P4).")
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": message, "estado": "pendiente_p4"}), 501
    return render_template("error.html", code=501, message=message), 501


@bp.app_context_processor
def inject_globals():
    """Inyecta en Jinja una vista **filtrada** del store, nunca el store crudo.

    Para el rol ``client`` el store exposé solo su propio registro y el catálogo
    público. Las opciones que el navegador necesita se renderizan en el servidor
    o se obtienen mediante endpoints que aplican permisos y propiedad.
    """
    current_user = get_current_user()
    view = store_view(store, current_user)
    if current_user is not None:
        visible_notifs = [
            n for n in view.notifications
            if n.visible_roles is None or current_user.role in n.visible_roles
        ]
        read_ids = store.notification_read_ids(current_user.id)
        for notification in visible_notifs:
            notification.read_for_current_user = notification.id in read_ids
    else:
        visible_notifs = []
    unread = [n for n in visible_notifs if not n.read_for_current_user]
    # Mapa permiso → bool para que el JS decida qué botones mostrar. Es la misma
    # matriz que aplica el servidor: solo oculta botones, nunca autoriza.
    client_permissions = {p: can(p, current_user) for p in PERMISSIONS}
    today = date.today()
    return {
        "store": view,
        "current_user": current_user,
        "available_users": view.available_users,
        "theme": session.get("theme", "deep-space"),
        "notifications": visible_notifs,
        "unread_notifications": unread,
        "client_permissions": client_permissions,
        "booking_default_departure": today.isoformat(),
        "booking_default_return": (today + timedelta(days=5)).isoformat(),
    }


# ----------------------------------------------------------------------
# Navegación principal
# ----------------------------------------------------------------------
@bp.route("/")
@permission_required("session:entry")
def index():
    user = get_current_user()
    if user is None:
        return redirect(url_for("main.login"))
    if user.role == "client":
        return redirect(url_for("main.client_portal"))
    return redirect(url_for("main.dashboard"))


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit(
    lambda: current_app.config["LOGIN_RATE_LIMIT"],
    methods=["POST"],
    key_func=lambda: (request.remote_addr or "desconocido").lower() + "|" +
                     (request.form.get("email") or "").strip().lower(),
)
def login():
    """Inicio de sesión con límite por IP+correo (anti fuerza bruta).

    El mensaje de error es genérico a propósito: no revela si el correo existe.
    """
    error = None
    if request.method == "POST":
        f = request.form
        email = (f.get("email") or "").strip().lower()
        password = f.get("password") or ""
        user = next((u for u in store.available_users if u.email.lower() == email), None)
        if user is not None and getattr(user, "password_hash", None) \
                and check_password_hash(user.password_hash, password):
            session["user_id"] = user.id
            store.record_event("INICIO_SESION", "Autenticación", user=user,
                               details=f"Inicio de sesión correcto de {user.email}.")
            flash(f"Bienvenido, {user.name.split(' (')[0]}.", "success")
            return redirect(url_for("main.index"))
        error = "Correo o contraseña incorrectos."
        store.record_event("INICIO_SESION_FALLIDO", "Autenticación", user_name=email or "(vacío)",
                           details=f"Intento de inicio de sesión fallido para {email or '(vacío)'}.")
    return render_template("login.html", error=error, google_enabled=google_bp_enabled)


@bp.route("/logout", methods=["POST"])
@permission_required("session:logout")
def logout():
    user = get_current_user()
    if user is not None:
        store.record_event("CIERRE_SESION", "Autenticación", user=user,
                           details=f"Cierre de sesión de {user.email}.")
    session.clear()
    for key in ("google_token", "google_oauth_state"):
        session.pop(key, None)
    flash("Sesión cerrada correctamente.", "success")
    return redirect(url_for("main.login"))


@bp.route("/dashboard")
@permission_required("dashboard:view")
def dashboard():
    if get_current_user().role == "client":
        return redirect(url_for("main.client_portal"))
    recent_bookings = list(reversed(store.bookings))[:5]
    total_revenue = sum(p.amount for p in store.payments)
    total_booked_value = sum(b.total_price for b in store.bookings if b.status != "Cancelada")
    active_bookings = [b for b in store.bookings if b.status in ("Confirmada", "En Progreso")]
    pending_payment = [b for b in store.bookings if b.payment_status != "Pagado" and b.status != "Cancelada"]
    total_capacity = sum(getattr(p, "max_capacity", 0) or 0 for p in store.packages)
    total_available = sum(p.available_slots for p in store.packages)
    occupancy = round(((total_capacity - total_available) / total_capacity) * 100) if total_capacity else 0
    return render_template(
        "dashboard.html", active_tab="dashboard", recent_bookings=recent_bookings,
        total_revenue=total_revenue, total_booked_value=total_booked_value,
        active_bookings_count=len(active_bookings), pending_payment_count=len(pending_payment),
        occupancy=occupancy, top_packages=store.packages[:4],
    )


@bp.route("/api/dashboard/stats")
@permission_required("dashboard:view")
def api_dashboard_stats():
    """Estadísticas del dashboard (RF-14). Admin/employee."""
    from .analytics import collect_stats
    stats = collect_stats(store.bookings, store.payments, store.packages,
                          store.clients, store.notifications)
    return jsonify({"success": True, "data": stats})


@bp.route("/ai-predictive")
@permission_required("ai:predictive_view")
def ai_predictive():
    timeframe = request.args.get("timeframe", "Próximos 6 meses (Q3 & Q4)")
    predictive_data = store.predictive_data
    if predictive_data is None:
        result = ai_service.get_predictive_analytics(
            store.clients, store.bookings, store.packages, timeframe)
        predictive_data = store.record_prediction(get_current_user(), timeframe, result)
    return render_template("ai_predictive.html", active_tab="ai-predictive",
                            predictive_data=predictive_data, timeframe=timeframe)


@bp.route("/bookings")
@permission_required("bookings:view")
def bookings():
    visible_bookings = list(reversed(store.bookings))
    return render_template("bookings.html", active_tab="bookings",
                           bookings=visible_bookings,
                           payments_by_booking=payments_by_booking(visible_bookings))


@bp.route("/clients")
@permission_required("clients:view")
def clients():
    return render_template("clients.html", active_tab="clients", clients=store.clients)


@bp.route("/packages")
@permission_required("catalog:view_packages")
def packages():
    return render_template("packages.html", active_tab="packages", packages=store.packages,
                            destinations=store.destinations)


@bp.route("/destinations")
@permission_required("catalog:view_destinations")
def destinations():
    return render_template("destinations.html", active_tab="destinations", destinations=store.destinations)


@bp.route("/admin/destinations", methods=["POST"])
@permission_required("catalog:create")
def admin_add_destination():
    data = request.form.to_dict()
    data["high_season_months"] = [
        int(value.strip()) for value in data.get("high_season_months", "").split(",")
        if value.strip().isdigit()
    ]
    data["popular_attractions"] = [
        value.strip() for value in data.get("popular_attractions", "").split(",")
        if value.strip()
    ]
    from . import validators
    errors = validators.validate_catalog("destination", dict(data))
    if errors:
        return jsonify({"success": False, "errors": errors, "error": errors[0]}), 422
    dest = store.add_destination(get_current_user(), **data)
    return jsonify({"success": True, "id": dest.id, "name": dest.name})


@bp.route("/admin/destinations/<int:dest_id>", methods=["POST"])
@permission_required("catalog:edit")
def admin_edit_destination(dest_id):
    data = request.form.to_dict()
    if "high_season_months" in data:
        data["high_season_months"] = [
            int(value.strip()) for value in data["high_season_months"].split(",")
            if value.strip().isdigit()
        ]
    if "popular_attractions" in data:
        data["popular_attractions"] = [
            value.strip() for value in data["popular_attractions"].split(",")
            if value.strip()
        ]
    from . import validators
    errors = validators.validate_catalog("destination", dict(data))
    if errors:
        return jsonify({"success": False, "errors": errors, "error": errors[0]}), 422
    dest = store.edit_destination(get_current_user(), dest_id, **data)
    if dest:
        return jsonify({"success": True, "name": dest.name})
    return jsonify({"success": False, "error": "Destino no encontrado"}), 404


@bp.route("/admin/destinations/<int:dest_id>/delete", methods=["POST"])
@permission_required("catalog:delete")
def admin_delete_destination(dest_id):
    return _guard_active(store.delete_destination(get_current_user(), dest_id))


# --- Catálogo: crear/editar/eliminar paquetes, hoteles, vuelos, transporte, actividades ---
def _guard_active(result):
    if result == "has_active_bookings":
        return jsonify({"success": False,
                        "error": "No se puede eliminar: tiene reservas vinculadas."}), 409
    if result in ("bookings", "catalog"):
        return jsonify({"success": False,
                        "error": "No se puede eliminar: tiene referencias vinculadas."}), 409
    if result == "not_found":
        return jsonify({"success": False, "error": "Recurso no encontrado"}), 404
    return jsonify({"success": True})


@bp.route("/admin/packages/new", methods=["POST"])
@permission_required("catalog:create")
def admin_new_package():
    f = request.form
    from . import validators
    errors = validators.validate_catalog("package", dict(f))
    if errors:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "errors": errors, "error": errors[0]}), 422
        flash("; ".join(errors), "error")
        return redirect(url_for("main.packages"))
    package = store.add_package(
        get_current_user(),
        title=f.get("title", ""), destination_id=f.get("destination_id", ""),
        destination_name=f.get("destination_name", ""), duration_days=int_field(f, "duration_days", 1),
        duration_nights=int_field(f, "duration_nights", 1), price_usd=float_field(f, "price_usd", 0.0),
        original_price_usd=float_field(f, "original_price_usd", 0.0), available_slots=int_field(f, "available_slots", 0),
        total_slots=int_field(f, "total_slots", 0), max_capacity=int_field(f, "max_capacity", 0),
        image=f.get("image", ""), image_url=f.get("image_url", ""),
        gallery=f.get("gallery", ""), category=f.get("category", "Estándar"),
        featured=bool(int_field(f, "featured", 0, minimum=0, maximum=1)),
        inclusions=f.get("inclusions", ""), departure_dates=f.get("departure_dates", ""),
        description=f.get("description", ""),
    )
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "id": package.id, "title": package.title})
    flash("Paquete turístico creado correctamente.", "success")
    return redirect(url_for("main.packages"))


@bp.route("/admin/packages/<int:pkg_id>", methods=["POST"])
@permission_required("catalog:edit")
def admin_edit_package(pkg_id):
    from . import validators
    errors = validators.validate_catalog("package", dict(request.form))
    if errors:
        return jsonify({"success": False, "errors": errors, "error": errors[0]}), 422
    allowed = {
        "title", "destination_name", "duration_days", "duration_nights", "price_usd",
        "original_price_usd", "available_slots", "total_slots", "max_capacity",
        "image", "image_url", "category", "description",
    }
    changes = {key: value for key, value in request.form.items() if key in allowed}
    if "image" in changes:
        changes["image_url"] = changes["image"]
    updated = store.edit_package(get_current_user(), pkg_id, **changes)
    if updated is None:
        return jsonify({"success": False, "error": "Paquete no encontrado"}), 404
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        flash("Paquete actualizado correctamente.", "success")
        return redirect(url_for("main.packages"))
    return jsonify({"success": True, "title": updated.title})


@bp.route("/admin/packages/<int:pkg_id>/delete", methods=["POST"])
@permission_required("catalog:delete")
def admin_delete_package(pkg_id):
    return _guard_active(store.delete_package(get_current_user(), pkg_id))


@bp.route("/admin/hotels/new", methods=["POST"])
@permission_required("catalog:create")
def admin_new_hotel():
    f = request.form
    from . import validators
    errors = validators.validate_catalog("hotel", dict(f))
    if errors:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "errors": errors}), 422
        flash("; ".join(errors), "error")
        return redirect(url_for("main.hotels"))
    room_types = []
    rt_count = int_field(f, "room_types_count", 1, minimum=1, maximum=20)
    for i in range(rt_count):
        room_types.append({
            "type": f.get(f"room_type[{i}][type]", ""),
            "price_per_night": float_field(f, f"room_type[{i}][price_per_night]", 0.0),
            "available": int_field(f, f"room_type[{i}][available]", 0, minimum=0),
        })
    amenities = [value.strip() for value in f.get("amenities", "").split(",") if value.strip()]
    hotel = store.add_hotel(
        get_current_user(),
        name=f.get("name", ""), destination_id=f.get("destination_id", ""),
        destination_name=f.get("destination_name", ""), stars=int_field(f, "stars", 5, minimum=1, maximum=5),
        address=f.get("address", ""), rating=float_field(f, "rating", 0.0),
        image=f.get("image", ""), contact_phone=f.get("contact_phone", ""),
        amenities=amenities, room_types=room_types,
    )
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "id": hotel.id, "name": hotel.name})
    flash("Hotel creado correctamente.", "success")
    return redirect(url_for("main.hotels"))


@bp.route("/admin/hotels/<int:hotel_id>", methods=["POST"])
@permission_required("catalog:edit")
def admin_edit_hotel(hotel_id):
    f = request.form
    hotel = store.get_hotel(hotel_id)
    if hotel is None:
        return jsonify({"success": False, "error": "Hotel no encontrado"}), 404
    from . import validators
    errors = validators.validate_catalog("hotel", dict(f))
    if errors:
        return jsonify({"success": False, "errors": errors, "error": errors[0]}), 422
    rt_count = int_field(f, "room_types_count", len(hotel.room_types or []), minimum=1, maximum=20)
    room_types = []
    for i in range(rt_count):
        old = hotel.room_types[i] if hotel.room_types and i < len(hotel.room_types) else None
        room_types.append({
            "type": f.get(f"room_type[{i}][type]", old.type if old else ""),
            "price_per_night": float_field(f, f"room_type[{i}][price_per_night]",
                                           old.price_per_night if old else 0.0),
            "available": int_field(f, f"room_type[{i}][available]",
                                   old.rooms_total if old else 0, minimum=0),
        })
    changes = {k: v for k, v in f.items() if k in
               {"name", "destination_id", "destination_name", "stars", "address",
                "rating", "image", "contact_phone"}}
    changes["amenities"] = [value.strip() for value in f.get("amenities", "").split(",")
                            if value.strip()]
    updated = store.edit_hotel(get_current_user(), hotel_id, room_types=room_types, **changes)
    return jsonify({"success": True, "name": updated.name if updated else hotel.name})


@bp.route("/admin/hotels/<int:hotel_id>/delete", methods=["POST"])
@permission_required("catalog:delete")
def admin_delete_hotel(hotel_id):
    return _guard_active(store.delete_hotel_guarded(get_current_user(), hotel_id))


@bp.route("/admin/flights/new", methods=["POST"])
@permission_required("catalog:create")
def admin_new_flight():
    f = request.form
    from . import validators
    errors = validators.validate_catalog("flight", dict(f))
    if errors:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "errors": errors, "error": errors[0]}), 422
        flash("; ".join(errors), "error")
        return redirect(url_for("main.flights"))
    flight = store.add_flight(
        get_current_user(),
        airline=f.get("airline", ""), flight_number=f.get("flight_number", ""),
        origin=f.get("origin", ""), destination=f.get("destination", ""),
        departure_time=f.get("departure_time", ""), arrival_time=f.get("arrival_time", ""),
        price_usd=float_field(f, "price_usd", 0.0), seats_available=int_field(f, "seats_available", 0, minimum=0),
        total_seats=int_field(f, "total_seats", 0, minimum=1), flight_class=f.get("flight_class", "Económica"),
        status=f.get("status", "A tiempo"), baggage_allowance=f.get("baggage_allowance", ""),
        image=f.get("image", ""),
    )
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "id": flight.id, "flight_number": flight.flight_number})
    flash("Vuelo creado correctamente.", "success")
    return redirect(url_for("main.flights"))


@bp.route("/admin/flights/<int:flight_id>", methods=["POST"])
@permission_required("catalog:edit")
def admin_edit_flight(flight_id):
    from . import validators
    errors = validators.validate_catalog("flight", dict(request.form))
    if errors:
        return jsonify({"success": False, "errors": errors, "error": errors[0]}), 422
    allowed = {"airline", "flight_number", "origin", "destination", "departure_time", "arrival_time",
               "price_usd", "seats_available", "total_seats", "flight_class", "status", "baggage_allowance", "image"}
    updated = store.edit_flight(get_current_user(), flight_id,
                                **{k: v for k, v in request.form.items() if k in allowed})
    if updated is None:
        return jsonify({"success": False, "error": "Vuelo no encontrado"}), 404
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        flash("Vuelo actualizado correctamente.", "success")
        return redirect(url_for("main.flights"))
    return jsonify({"success": True, "airline": updated.airline, "flight_number": updated.flight_number})


@bp.route("/admin/flights/<int:flight_id>/delete", methods=["POST"])
@permission_required("catalog:delete")
def admin_delete_flight(flight_id):
    return _guard_active(store.delete_flight_guarded(get_current_user(), flight_id))


@bp.route("/admin/transports/new", methods=["POST"])
@permission_required("catalog:create")
def admin_new_transport():
    f = request.form
    from . import validators
    errors = validators.validate_catalog("transport", dict(f))
    if errors:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "errors": errors, "error": errors[0]}), 422
        flash("; ".join(errors), "error")
        return redirect(url_for("main.transports"))
    transport = store.add_transport(
        get_current_user(),
        type=f.get("type", ""), route=f.get("route", ""), vehicle_model=f.get("vehicle_model", ""),
        capacity=int_field(f, "capacity", 0, minimum=0), available_seats=int_field(f, "available_seats", 0, minimum=0),
        driver_name=f.get("driver_name", ""), price_usd=float_field(f, "price_usd", 0.0),
        status=f.get("status", "Operativo"),
        amenities=[item.strip() for item in f.get("amenities", "").split(",") if item.strip()],
        image=f.get("image", ""),
    )
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "id": transport.id, "type": transport.type})
    flash("Transporte creado correctamente.", "success")
    return redirect(url_for("main.transports"))


@bp.route("/admin/transports/<int:transport_id>", methods=["POST"])
@permission_required("catalog:edit")
def admin_edit_transport(transport_id):
    from . import validators
    errors = validators.validate_catalog("transport", dict(request.form))
    if errors:
        return jsonify({"success": False, "errors": errors, "error": errors[0]}), 422
    allowed = {"type", "route", "vehicle_model", "capacity", "available_seats", "driver_name",
               "price_usd", "status", "amenities", "image"}
    updated = store.edit_transport(
        get_current_user(),
        transport_id,
        **{
            k: ([item.strip() for item in v.split(",") if item.strip()] if k == "amenities" else v)
            for k, v in request.form.items() if k in allowed
        },
    )
    if updated is None:
        return jsonify({"success": False, "error": "Transporte no encontrado"}), 404
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        flash("Transporte actualizado correctamente.", "success")
        return redirect(url_for("main.transports"))
    return jsonify({"success": True, "type": updated.type})


@bp.route("/admin/transports/<int:transport_id>/delete", methods=["POST"])
@permission_required("catalog:delete")
def admin_delete_transport(transport_id):
    return _guard_active(store.delete_transport_guarded(get_current_user(), transport_id))


@bp.route("/admin/activities/new", methods=["POST"])
@permission_required("catalog:create")
def admin_new_activity():
    f = request.form
    from . import validators
    errors = validators.validate_catalog("activity", dict(f))
    if errors:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "errors": errors, "error": errors[0]}), 422
        flash("; ".join(errors), "error")
        return redirect(url_for("main.activities"))
    activity = store.add_activity(
        get_current_user(),
        title=f.get("title", ""), destination_id=f.get("destination_id", ""),
        destination_name=f.get("destination_name", ""), duration_hours=int_field(f, "duration_hours", 1),
        price_usd=float_field(f, "price_usd", 0.0), includes_guide=bool(int_field(f, "includes_guide", 0, minimum=0, maximum=1)),
        difficulty=f.get("difficulty", "Fácil"), image=f.get("image", ""),
        description=f.get("description", ""), category=f.get("category", "Turismo"),
        schedule=f.get("schedule", ""),
    )
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "id": activity.id, "title": activity.title})
    flash("Tour o actividad creado correctamente.", "success")
    return redirect(url_for("main.activities"))


@bp.route("/admin/activities/<int:activity_id>", methods=["POST"])
@permission_required("catalog:edit")
def admin_edit_activity(activity_id):
    from . import validators
    errors = validators.validate_catalog("activity", dict(request.form))
    if errors:
        return jsonify({"success": False, "errors": errors, "error": errors[0]}), 422
    allowed = {"title", "destination_id", "destination_name", "duration_hours", "price_usd",
               "includes_guide", "difficulty", "image", "description", "category", "schedule"}
    updated = store.edit_activity(get_current_user(), activity_id,
                                  **{k: v for k, v in request.form.items() if k in allowed})
    if updated is None:
        return jsonify({"success": False, "error": "Actividad no encontrada"}), 404
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        flash("Tour o actividad actualizado correctamente.", "success")
        return redirect(url_for("main.activities"))
    return jsonify({"success": True, "title": updated.title})


@bp.route("/admin/activities/<int:activity_id>/delete", methods=["POST"])
@permission_required("catalog:delete")
def admin_delete_activity(activity_id):
    activity = catalog_get_activity(activity_id)
    if activity is None:
        return jsonify({"success": False, "error": "Actividad no encontrada"}), 404
    ok = store.delete_activity(get_current_user(), activity_id)
    if not ok:
        return jsonify({"success": False, "error": "Actividad no encontrada"}), 404
    return jsonify({"success": True})


def catalog_get_activity(activity_id):
    from .repositories import catalog as _c
    return _c.get_activity(activity_id)


# --- Clientes: edición y eliminación (admin/employee editan; solo admin elimina) ---
@bp.route("/admin/clients/<int:client_id>/edit", methods=["POST"])
@permission_required("clients:edit")
def admin_edit_client(client_id):
    f = request.form
    client = store.get_client(client_id)
    if not client:
        return jsonify({"success": False, "error": "Cliente no encontrado"}), 404
    allowed = {"name", "email", "phone", "document_id", "nationality", "category",
               "budget_preference", "passport_expiry", "notes", "status"}
    from . import validators
    errors = []
    changes = {k: v for k, v in f.items() if k in allowed}
    if "email" in changes:
        if not validators.validate_email(changes["email"]):
            errors.append("Email inválido.")
        errors += validators.validate_email_unique(changes["email"], client_id, store.clients)
    if changes.get("document_id"):
        errors += validators.validate_document_unique(changes["document_id"], client_id, store.clients)
    if errors:
        return jsonify({"success": False, "errors": errors}), 422
    store.update_client(get_current_user(), client_id, **changes)
    return jsonify({"success": True, "name": client.name})


@bp.route("/admin/clients/<int:client_id>/delete", methods=["POST"])
@permission_required("clients:delete")
def admin_delete_client(client_id):
    result = store.delete_client(get_current_user(), client_id)
    if not result:
        return jsonify({"success": False, "error": "Cliente no encontrado"}), 404
    return jsonify({"success": True})


# --- Usuarios (RF-01): solo admin ---
@bp.route("/admin/users")
@permission_required("users:manage")
def admin_users():
    return render_template("admin_users.html", active_tab="users", users=store.available_users,
                           clients=store.clients)


@bp.route("/admin/users/new", methods=["POST"])
@permission_required("users:manage")
def admin_new_user():
    f = request.form
    result = store.create_user(get_current_user(), name=f.get("name", ""),
                               email=f.get("email", ""), password=f.get("password", ""),
                               role=f.get("role", "client"), department=f.get("department", ""),
                               client_id=f.get("client_id") or None)
    flash(result["message"], "success" if result["success"] else "error")
    return redirect(url_for("main.admin_users"))


@bp.route("/admin/users/<int:user_id>/edit", methods=["POST"])
@permission_required("users:manage")
def admin_edit_user(user_id):
    changes = {k: v for k, v in request.form.items()
               if k in {"name", "email", "role", "department", "client_id"} and v}
    result = store.update_user(get_current_user(), user_id, **changes)
    flash(result["message"], "success" if result["success"] else "error")
    return redirect(url_for("main.admin_users"))


@bp.route("/admin/users/<int:user_id>/password", methods=["POST"])
@permission_required("users:manage")
def admin_reset_password(user_id):
    result = store.reset_user_password(get_current_user(), user_id, request.form.get("password", ""))
    flash(result["message"], "success" if result["success"] else "error")
    return redirect(url_for("main.admin_users"))


@bp.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@permission_required("users:manage")
def admin_delete_user(user_id):
    result = store.deactivate_user(get_current_user(), user_id)
    flash(result["message"], "success" if result["success"] else "error")
    return redirect(url_for("main.admin_users"))


@bp.route("/admin/users/<int:user_id>/status", methods=["POST"])
@permission_required("users:manage")
def admin_set_user_status(user_id):
    user = store.get_user(user_id)
    if user is None:
        flash("Usuario no encontrado.", "error")
    elif request.form.get("is_active") == "1":
        result = store.update_user(get_current_user(), user_id, is_active=True)
        flash(result["message"], "success" if result["success"] else "error")
    else:
        result = store.deactivate_user(get_current_user(), user_id)
        flash(result["message"], "success" if result["success"] else "error")
    return redirect(url_for("main.admin_users"))


# --- Reserva: edición (fechas, viajeros, notas; recalcula total e inventario) ---
@bp.route("/bookings/<int:booking_id>/edit", methods=["POST"])
@permission_required("bookings:edit")
def edit_booking(booking_id):
    user = get_current_user()
    booking = store.get_booking(booking_id)
    if booking is None:
        return jsonify({"success": False, "message": "Reserva no encontrada."}), 404
    f = request.form
    changes = {}
    for key in ("departure_date", "return_date", "notes", "check_in", "check_out"):
        if f.get(key):
            changes[key] = f.get(key)
    if f.get("travelers"):
        changes["travelers"] = int_field(f, "travelers", booking.travelers, minimum=1, maximum=50)
    if f.get("rooms_count"):
        changes["rooms_count"] = int_field(f, "rooms_count", booking.rooms_count or 1, minimum=1, maximum=20)
    result = store.update_booking(user, booking_id, **changes)
    flash(result["message"], "success" if result["success"] else "error")
    return redirect_back("main.bookings")


# --- Pago verificado (spec P3) ---
@bp.route("/payments/<int:payment_id>/verify", methods=["POST"])
@permission_required("payments:create")
def verify_payment(payment_id):
    result = store.verify_payment(get_current_user(), payment_id)
    flash(result["message"], "success" if result["success"] else "error")
    return redirect_back("main.payments")


@bp.route("/hotels")
@permission_required("catalog:view_hotels")
def hotels():
    return render_template("hotels.html", active_tab="hotels", hotels=store.hotels)


@bp.route("/flights")
@permission_required("catalog:view_flights")
def flights():
    return render_template("flights.html", active_tab="flights", flights=store.flights)


@bp.route("/transports")
@permission_required("catalog:view_transports")
def transports():
    return render_template("transports.html", active_tab="transports", transports=store.transports)


@bp.route("/activities")
@permission_required("catalog:view_activities")
def activities():
    return render_template("activities.html", active_tab="activities", activities=store.activities)


@bp.route("/payments")
@permission_required("payments:view")
def payments():
    return render_template("payments.html", active_tab="payments", payments=store.payments,
                            pending_bookings=[b for b in store.bookings if b.payment_status != "Pagado"
                                              and b.status != "Cancelada"])


@bp.route("/promotions")
@permission_required("promotions:view")
def promotions():
    return render_template("promotions.html", active_tab="promotions", promotions=store.promotions)


@bp.route("/documents")
@permission_required("documents:view")
def documents():
    """Listado de documentos: el cliente solo ve los suyos (propiedad)."""
    user = get_current_user()
    visibles = own_records(user, store.documents)
    return render_template("documents.html", active_tab="documents", documents=visibles,
                            clients=own_records(user, store.clients))


@bp.route("/audit")
@permission_required("audit:view")
def audit():
    return render_template("audit.html", active_tab="audit", logs=store.audit_logs)


@bp.route("/client-portal")
@permission_required("portal:view")
def client_portal():
    """Portal del cliente: únicamente sus reservas, nunca las de otros (IDOR)."""
    user = get_current_user()
    my_bookings = own_records(user, store.bookings)
    return render_template("client_portal.html", active_tab="client-portal", my_bookings=my_bookings,
                           packages=store.packages[:4],
                           payments_by_booking=payments_by_booking(my_bookings))


# ----------------------------------------------------------------------
# Sesión: tema / perfil / reset
# ----------------------------------------------------------------------
# Nota: /switch-user se eliminó en la fase P1. Era una escalada de privilegios
# (cualquiera con sesión podía convertirse en otro usuario con solo un POST).
# Se ha retirado también el selector de la interfaz (templates/base.html).
# La demostración de roles se hace con las tres credenciales del seed.


@bp.route("/set-theme/<theme>", methods=["POST"])
@permission_required("theme:set")
def set_theme(theme):
    session["theme"] = "light" if theme == "light" else "deep-space"
    user = get_current_user()
    default_endpoint = "main.client_portal" if user and user.role == "client" else "main.dashboard"
    return redirect_back(default_endpoint)


@bp.route("/edit-profile", methods=["GET", "POST"])
@permission_required("profile:edit")
def edit_profile():
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("main.login"))

    # Determinamos sobre qué ficha de cliente se puede escribir.
    if current_user.role == "client":
        # El cliente solo edita su propio perfil; el id del formulario se ignora.
        client = client_record(current_user)
        if client is None:
            flash("No tienes un perfil de cliente asociado. Contacta a la agencia.", "error")
            return redirect(url_for("main.client_portal"))
    else:
        # Admin/empleado: elige la ficha del formulario o, en GET, la primera.
        client_id = request.form.get("client_id") if request.method == "POST" else request.args.get("client_id")
        client = store.get_client(client_id) if client_id else None
        if client is None and request.method == "POST":
            flash("Selecciona un cliente válido para editar su perfil.", "error")
            return redirect(url_for("main.dashboard"))
        if client is None:
            client = store.clients[0] if store.clients else None
    if client is None:
        flash("No hay clientes registrados todavía.", "error")
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        # Collect form data
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        document_id = request.form.get("document_id", "").strip()
        nationality = request.form.get("nationality", "").strip()
        category = request.form.get("category", "").strip()
        budget_preference = request.form.get("budget_preference", "").strip()
        passport_expiry = request.form.get("passport_expiry", "").strip()
        notes = request.form.get("notes", "").strip()

        # Update the client
        store.update_client(current_user, client.id, name=name or client.name,
                            phone=phone or client.phone,
                            document_id=document_id or client.document_id,
                            nationality=nationality or client.nationality,
                            category=category or client.category,
                            budget_preference=budget_preference or client.budget_preference,
                            passport_expiry=passport_expiry or client.passport_expiry,
                            notes=notes or client.notes)

        flash("Perfil actualizado correctamente.", "success")
        # Redirect based on role
        if current_user.role == "client":
            return redirect(url_for("main.client_portal"))
        return redirect(url_for("main.dashboard"))

    # GET: muestra el formulario con los datos actuales. La lista de fichas
    # editables la inyecta el store filtrado de la fase P1 (nunca todos).
    return render_template("edit_profile.html", current_user=current_user,
                           client=client, available_users=own_records(current_user, store.clients),
                           is_admin=current_user.role in ("admin", "employee"))


@bp.route("/reset", methods=["POST"])
@permission_required("data:reset")
def reset_data():
    """Restablece los datos de demostración.

    Doble protección: solo administradores (permiso ``data:reset``) y solo si
    la instalación tiene ``ENABLE_RESET=1``. Además exige una confirmación
    explícita enviada por el formulario, para que un POST aislado no borre nada.
    """
    from flask import current_app
    if not current_app.config.get("ENABLE_RESET"):
        abort(404)
    if request.form.get("confirm") != "RESTABLECER":
        flash("Para restablecer los datos debes confirmar la operación.", "error")
        return redirect_back("main.dashboard")
    store.reset_all_data()
    session.pop("user_id", None)
    flash("Datos de demostración restablecidos.", "success")
    return redirect(url_for("main.login"))


@bp.route("/notifications/<int:notif_id>/read", methods=["POST"])
@permission_required("notifications:read")
def read_notification(notif_id):
    store.mark_notification_as_read(get_current_user(), notif_id)
    return redirect_back("main.dashboard")


@bp.route("/notifications/read-all", methods=["POST"])
@permission_required("notifications:read")
def read_all_notifications():
    store.mark_all_notifications_as_read(get_current_user())
    return redirect_back("main.dashboard")


# ----------------------------------------------------------------------
# Clientes
# ----------------------------------------------------------------------
@bp.route("/clients/new", methods=["POST"])
@permission_required("clients:create")
def new_client():
    f = request.form
    destinations_list = [d.strip() for d in f.get("preferred_destinations", "").split(",") if d.strip()]
    from . import validators
    errors = []
    if not validators.validate_email(f.get("email", "")):
        errors.append("Email inválido.")
    errors += validators.validate_email_unique(f.get("email", ""), None, store.clients)
    if f.get("document_id"):
        errors += validators.validate_document_unique(f.get("document_id", ""), None, store.clients)
    if errors:
        for e in errors:
            flash(e, "error")
        return redirect(url_for("main.clients"))
    store.add_client(
        get_current_user(), name=f.get("name", ""), email=f.get("email", ""), phone=f.get("phone", ""),
        document_id=f.get("document_id", ""), nationality=f.get("nationality", "República Dominicana"),
        category=f.get("category", "Estándar"), budget_preference=f.get("budget_preference", "Premium"),
        preferred_destinations=destinations_list, passport_expiry=f.get("passport_expiry", ""),
        notes=f.get("notes", ""),
    )
    return redirect(url_for("main.clients"))


# ----------------------------------------------------------------------
# Reservas (RN-01, RN-02, RN-03)
# ----------------------------------------------------------------------
@bp.route("/api/bookings/quote", methods=["GET"])
@permission_required("bookings:create")
def booking_quote():
    """Cotiza una reserva usando precios consultados exclusivamente en la BD."""
    user = get_current_user()
    if user.role == "client":
        client = client_record(user)
    else:
        client = store.get_client(request.args.get("client_id", ""))
    try:
        quote = _booking_quote(
            request.args,
            client_category=getattr(client, "category", None),
            is_client=user.role == "client",
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 422
    promo_result = quote["promo_result"]
    return jsonify({
        "success": True,
        "currency": "USD",
        "travelers": quote["travelers"],
        "rooms_count": quote["rooms_count"],
        "room_type_id": quote["room_type_id"],
        "room_type_name": quote["room_type_name"],
        "nights": quote["nights"],
        "subtotal": float(quote["subtotal"]),
        "discount": float(quote["discount"]),
        "total": float(quote["total"]),
        "final_price": float(quote["total"]),
        "promo_valid": bool(promo_result["valid"]),
        "promo_message": promo_result["message"],
    })


@bp.route("/bookings/new", methods=["POST"])
@permission_required("bookings:create")
def new_booking():
    f = request.form
    current_user = get_current_user()
    # Un cliente solo puede reservar a su propio nombre: aunque manipule el
    # formulario, el cliente se toma de la sesión y no del POST (IDOR).
    if current_user.role == "client":
        client = client_record(current_user)
        if client is None:
            flash("No tienes un perfil de cliente asociado. Contacta a la agencia.", "error")
            return redirect(url_for("main.client_portal"))
    else:
        client = store.get_client(f.get("client_id", ""))
    if not client:
        flash(
            "Regla de Negocio (RN-02): Debe seleccionar o registrar un cliente para asociar a la reserva.",
            "error",
        )
        return redirect(
            url_for("main.client_portal" if current_user.role == "client" else "main.bookings")
        )

    try:
        quote = _booking_quote(
            f,
            client_category=getattr(client, "category", None),
            is_client=current_user.role == "client",
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(
            url_for("main.client_portal" if current_user.role == "client" else "main.bookings")
        )
    package = store.get_package(f.get("package_id", "")) if f.get("package_id") else None
    hotel = store.get_hotel(f.get("hotel_id", "")) if f.get("hotel_id") else None
    flight = store.get_flight(f.get("flight_id", "")) if f.get("flight_id") else None
    travelers = quote["travelers"]

    promo_code = quote["promo_code"]
    promo_note = (
        f" [Cupón: {promo_code.upper()} - "
        f"{quote['promo_result']['discount_percentage']}%]"
        if promo_code else ""
    )

    names = request.form.getlist("passenger_name[]")
    docs = request.form.getlist("passenger_document[]")
    ages = request.form.getlist("passenger_age[]")
    passengers = []
    for i in range(travelers):
        name = names[i].strip() if i < len(names) and names[i].strip() else (
            client.name if i == 0 else f"Pasajero {i + 1}")
        doc = docs[i].strip() if i < len(docs) and docs[i].strip() else (
            client.document_id if i == 0 else f"DOC-{100000 + i}")
        try:
            age = int(ages[i]) if i < len(ages) and ages[i] else 30
        except ValueError:
            age = 30
        passengers.append({"full_name": name, "document": doc, "age": age})

    result = store.create_booking(
        current_user, client_id=client.id, client_name=client.name, client_email=client.email,
        package_id=package.id if package else None, package_name=package.title if package else "Itinerario Personalizado",
        destination_name=(package.destination_name if package else (hotel.destination_name if hotel else "Destino Exclusivo")),
        departure_date=f.get("departure_date", ""), return_date=f.get("return_date", ""),
        travelers=travelers, passengers=passengers, hotel_id=hotel.id if hotel else None,
        check_in=f.get("check_in") or f.get("departure_date", ""),
        check_out=f.get("check_out") or f.get("return_date", ""),
        rooms_count=quote["rooms_count"],
        room_type_id=quote["room_type_id"],
        hotel_name=hotel.name if hotel else None, flight_id=flight.id if flight else None,
        flight_number=flight.flight_number if flight else None, total_price=quote["total"],
        notes=(f.get("notes", "") + promo_note).strip(),
        initial_payment=float_field(f, "initial_payment"),
        payment_method=f.get("payment_method", "Tarjeta de Crédito"),
        promo_code=promo_code,
    )

    if not result["success"]:
        flash(result["message"], "error")
        return render_template("bookings.html", active_tab="bookings",
                                bookings=own_records(current_user, store.bookings),
                                error=result["message"])
    flash(result["message"], "success")
    if current_user.role == "client":
        return redirect(url_for("main.client_portal"))
    return redirect(url_for("main.bookings"))


def _json_or_form():
    """Acepta JSON (fetch) o form-data (formularios tradicionales).

    Si es form-data, intenta parsear 'content' como JSON.
    """
    data = request.get_json(force=True, silent=True)
    if data is not None:
        return data
    form = request.form
    if "content" in form:
        import json as _json
        try:
            return {"content": _json.loads(form["content"]), "source": form.get("source", "ia")}
        except (ValueError, TypeError):
            return form
    return form


@bp.route("/bookings/<int:booking_id>/itinerary", methods=["POST"])
@permission_required("itineraries:create")
def save_booking_itinerary(booking_id):
    """Guarda un itinerario (generado por IA o manual) para una reserva."""
    user = get_current_user()
    booking = owned_or_404(user, store.get_booking(booking_id))
    data = _json_or_form()
    content = data.get("content", data)
    from . import validators
    errors = validators.validate_itinerary_content(content)
    if errors:
        return jsonify({"success": False, "errors": errors, "error": errors[0]}), 422
    itinerary = store.save_itinerary(user, booking.id, content,
                                     source=data.get("source", "ia"))
    if itinerary is None:
        return jsonify({"success": False, "error": "Reserva no encontrada"}), 404
    return jsonify({"success": True, "id": itinerary.id})


@bp.route("/bookings/<int:booking_id>/itinerary", methods=["GET"])
@permission_required("itineraries:view")
def get_booking_itinerary(booking_id):
    """Obtiene el itinerario de una reserva (solo dueño o staff)."""
    user = get_current_user()
    booking = owned_or_404(user, store.get_booking(booking_id))
    itinerary = store.get_booking_itinerary(booking.id)
    if itinerary is None:
        return jsonify({"success": False, "error": "Itinerario no encontrado"}), 404
    return jsonify({"success": True, "content": itinerary.content, "source": itinerary.source})


@bp.route("/itineraries/<int:itinerary_id>", methods=["PUT"])
@permission_required("itineraries:edit")
def update_itinerary(itinerary_id):
    """Edita el contenido JSON de un itinerario (sobrescribe completo)."""
    user = get_current_user()
    data = _json_or_form()
    content = data.get("content", data)
    from . import validators
    errors = validators.validate_itinerary_content(content)
    if errors:
        return jsonify({"success": False, "errors": errors, "error": errors[0]}), 422
    itinerary = store.update_itinerary(user, itinerary_id, content)
    if itinerary is None:
        return jsonify({"success": False, "error": "Itinerario no encontrado"}), 404
    return jsonify({"success": True})


@bp.route("/itineraries/<int:itinerary_id>", methods=["DELETE"])
@permission_required("itineraries:delete")
def delete_itinerary(itinerary_id):
    """Elimina un itinerario (solo admin)."""
    user = get_current_user()
    if not store.delete_itinerary(user, itinerary_id):
        return jsonify({"success": False, "error": "Itinerario no encontrado"}), 404
    return jsonify({"success": True})


@bp.route("/bookings/<int:booking_id>/cancel", methods=["POST"])
@permission_required("bookings:cancel")
def cancel_booking(booking_id):
    """Cancela una reserva verificando propiedad y estado (IDOR)."""
    user = get_current_user()
    booking = owned_or_404(user, store.get_booking(booking_id))
    if user.role == "client" and booking.status != "Pendiente":
        flash("Solo puedes cancelar reservas que estén en estado Pendiente.", "error")
        return redirect_back("main.client_portal")
    store.cancel_booking(user, booking_id, request.form.get("reason", ""))
    default = "main.client_portal" if user.role == "client" else "main.bookings"
    return redirect_back(default)


@bp.route("/bookings/<int:booking_id>/status", methods=["POST"])
@permission_required("bookings:status")
def update_booking_status(booking_id):
    """Cambia el estado de una reserva (solo personal interno; RN-03 en P3)."""
    user = get_current_user()
    owned_or_404(user, store.get_booking(booking_id))
    result = store.update_booking_status(user, booking_id, request.form.get("status", "Pendiente"))
    if not result.get("success"):
        flash(result["message"], "error")
        visible_bookings = own_records(user, store.bookings)
        return render_template("bookings.html", active_tab="bookings",
                               bookings=visible_bookings,
                               payments_by_booking=payments_by_booking(visible_bookings),
                               error=result["message"]), 422
    flash(result["message"], "success")
    return redirect_back("main.bookings")


# ----------------------------------------------------------------------
# Pagos (RF-11, RN-03)
# ----------------------------------------------------------------------
@bp.route("/payments/new", methods=["POST"])
@permission_required("payments:create")
def new_payment():
    """Registra un pago (RF-11, solo personal interno)."""
    f = request.form
    user = get_current_user()
    booking_id = f.get("booking_id", "")
    if store.get_booking(booking_id) is None:
        flash("La reserva indicada no existe.", "error")
        return redirect(url_for("main.payments"))
    result = store.register_payment(
        user, booking_id,
        float_field(f, "amount"), f.get("payment_method", "Tarjeta de Crédito"),
        f.get("reference", ""))
    if not result.get("success") and result.get("status") == 422:
        # RF-11: validación de negocio rechazada (monto, saldo, método,
        # referencia o NCF) → 422 sin cambios persistidos.
        flash(result.get("message", "Pago rechazado."), "error")
        return render_template("payments.html", active_tab="payments", payments=store.payments,
                               pending_bookings=[b for b in store.bookings if b.payment_status != "Pagado"
                                                 and b.status != "Cancelada"],
                               error=result.get("message")), 422
    flash(result.get("message", "Pago registrado."), "success" if result.get("success") else "error")
    return redirect(url_for("main.payments"))


@bp.route("/payments/<int:payment_id>/void", methods=["POST"])
@permission_required("payments:void")
def payment_void(payment_id):
    """Anula un pago (solo admin) y emite nota de crédito. Motivo obligatorio."""
    result = store.void_payment(get_current_user(), payment_id,
                                (request.form.get("reason") or "").strip())
    flash(result["message"], "success" if result["success"] else "error")
    return redirect_back("main.payments")


# ----------------------------------------------------------------------
# Promociones (RF-12)
# ----------------------------------------------------------------------
@bp.route("/promotions/new", methods=["POST"])
@permission_required("promotions:create")
def new_promotion():
    f = request.form
    categories = [c.strip() for c in f.get("applicable_categories", "").split(",") if c.strip()]
    store.add_promotion(
        get_current_user(), code=f.get("code", "").upper(), title=f.get("title", ""),
        description=f.get("description", ""),
        discount_percentage=int_field(f, "discount_percentage", 10, minimum=0, maximum=100),
        valid_until=f.get("valid_until", ""),
        max_uses=int_field(f, "max_uses", 50, minimum=1),
        applicable_categories=categories or ["Todos"], active=True,
    )
    return redirect(url_for("main.promotions"))


@bp.route("/promotions/<int:promo_id>/toggle", methods=["POST"])
@permission_required("promotions:toggle")
def toggle_promotion(promo_id):
    store.toggle_promotion_status(get_current_user(), promo_id)
    return redirect(url_for("main.promotions"))


@bp.route("/api/promo/preview", methods=["POST"])
@permission_required("promotions:apply")
def preview_promo():
    data = request.get_json(force=True, silent=True) or {}
    user = get_current_user()
    if user.role == "client":
        client = client_record(user)
    else:
        client = store.get_client(data.get("client_id", ""))
    quote_data = dict(data)
    quote_data["promo_code"] = data.get("promo_code") or data.get("code", "")
    quote = _booking_quote(quote_data, client_category=getattr(client, "category", None))
    result = dict(quote["promo_result"])
    result["subtotal"] = float(quote["subtotal"])
    result["final_price"] = float(quote["total"])
    return jsonify(result)


# ----------------------------------------------------------------------
# Documentos (RF-17)
# ----------------------------------------------------------------------
@bp.route("/documents/new", methods=["POST"])
@permission_required("documents:create")
def new_document():
    """Sube un documento real (multipart) con validación de extensión y firma."""
    f = request.form
    user = get_current_user()
    if user.role == "client":
        client = client_record(user)
        if client is None:
            flash("No tienes un perfil de cliente asociado. Contacta a la agencia.", "error")
            return redirect(url_for("main.client_portal"))
    else:
        client = store.get_client(f.get("client_id", ""))
    if client is None:
        flash("Debe indicar un cliente válido.", "error")
        return redirect(url_for("main.documents"))
    file = request.files.get("file")
    if file is None:
        flash("Debe adjuntar un archivo.", "error")
        return redirect(url_for("main.documents"))
    result = store.upload_document(
        user, file, client.id,
        doc_type=f.get("doc_type", "Documento"),
        expiry_date=f.get("expiry_date", ""),
    )
    if not result.get("success"):
        flash(result.get("message", "No se pudo subir el archivo."), "error")
        return redirect(url_for("main.documents"))
    flash("Documento subido exitosamente.", "success")
    return redirect(url_for("main.documents"))


@bp.route("/documents/<int:doc_id>/download")
@permission_required("documents:view")
def download_document(doc_id):
    """Descarga un documento verificando propiedad (IDOR)."""
    user = get_current_user()
    try:
        result = store.get_document_for_download(user, doc_id)
    except PermissionError:
        return jsonify({"success": False, "error": "No tienes permiso para descargar este documento"}), 403
    if result is None:
        return jsonify({"success": False, "error": "Documento no encontrado"}), 404
    doc, path = result
    return send_file(path, mimetype=doc.mime or "application/octet-stream",
                     as_attachment=True, download_name=doc.file_name)


@bp.route("/documents/<int:doc_id>/delete", methods=["POST"])
@permission_required("documents:delete")
def delete_document(doc_id):
    """Elimina un documento. Solo administradores (RN-04).

    ``permission_required("documents:delete")`` cierra el paso a empleados y
    ``store.delete_document`` añade la misma comprobación (defensa en
    profundidad) desde la fase P3.
    """
    store.delete_document(get_current_user(), doc_id)
    return redirect(url_for("main.documents"))


# ----------------------------------------------------------------------
# API de Inteligencia Artificial (RF-20) — igual que server.ts
# ----------------------------------------------------------------------
@bp.route("/api/ai/predictive-analytics", methods=["POST"])
@permission_required("ai:predictive_run")
@limiter.limit(lambda: current_app.config["AI_PREDICTIVE_RATE_LIMIT"])
def api_predictive_analytics():
    data = request.get_json(force=True, silent=True) or {}
    timeframe = data.get("selectedTimeframe", "Próximos 6 meses")
    result = ai_service.get_predictive_analytics(store.clients, store.bookings, store.packages, timeframe)
    result = store.record_prediction(get_current_user(), timeframe, result)
    return jsonify({"success": True, "data": result})


@bp.route("/api/ai/recommendations", methods=["POST"])
@permission_required("ai:recommend")
@limiter.limit(lambda: current_app.config["AI_GENERATIVE_RATE_LIMIT"])
def api_recommendations():
    data = request.get_json(force=True, silent=True) or {}
    result = ai_service.get_recommendations(
        data.get("clientProfile", {}) or {}, data.get("budget", 2500), data.get("travelStyle", ""),
        data.get("travelersCount", 2), data.get("interests", ""),
    )
    store.record_ai_call(
        get_current_user(),
        "EJECUCIÓN_RECOMENDACIONES_IA",
        "Motor IA Recomendaciones",
    )
    return jsonify({"success": True, "data": result})


@bp.route("/api/ai/generate-itinerary", methods=["POST"])
@permission_required("ai:itinerary")
@limiter.limit(lambda: current_app.config["AI_GENERATIVE_RATE_LIMIT"])
def api_generate_itinerary():
    data = request.get_json(force=True, silent=True) or {}
    result = ai_service.get_itinerary(
        data.get("destination", ""), data.get("days", 4), data.get("travelers", 2),
        data.get("travelType", ""), data.get("pace", ""), data.get("notes", ""),
    )
    store.record_ai_call(
        get_current_user(),
        "EJECUCIÓN_ITINERARIO_IA",
        "Motor IA Itinerarios",
    )
    return jsonify({"success": True, "data": result})


@bp.route("/api/search", methods=["GET"])
def api_search():
    """Búsqueda avanzada (RF-16): type, q, filtros, paginación, alcance por rol."""
    from .repositories import search as search_repo
    data = request.args
    q = (data.get("q") or "").strip()
    search_type = (data.get("type") or "packages").strip().lower()
    category = data.get("category", "").strip()
    destination = data.get("destination", "").strip()
    status = data.get("status", "").strip()
    sort = (data.get("sort") or "name").strip().lower()
    order = (data.get("order") or "asc").strip().lower()

    try:
        page = int(data.get("page", 1))
        per_page = int(data.get("per_page", 12))
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Parámetros de paginación inválidos."}), 422

    if page < 1:
        return jsonify({"success": False, "error": "La página debe ser >= 1."}), 422
    if per_page < 1 or per_page > 50:
        return jsonify({"success": False, "error": "per_page debe estar entre 1 y 50."}), 422
    if order not in ("asc", "desc"):
        return jsonify({"success": False, "error": "order debe ser 'asc' o 'desc'."}), 422
    if sort not in ("price", "date", "name"):
        return jsonify({"success": False, "error": "sort debe ser 'price', 'date' o 'name'."}), 422

    try:
        min_price = float(data["min_price"]) if data.get("min_price") else None
        max_price = float(data["max_price"]) if data.get("max_price") else None
        min_stars = int(data["min_stars"]) if data.get("min_stars") else None
        date_from = data.get("date_from") or None
        date_to = data.get("date_to") or None
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Filtros numéricos inválidos."}), 422

    searcher = search_repo.SEARCHERS.get(search_type)
    if searcher is None:
        return jsonify({"success": False,
                        "error": f"Tipo de búsqueda inválido: '{search_type}'. "
                                 f"Usa: {', '.join(search_repo.SEARCHERS.keys())}."}), 422

    user = get_current_user()
    is_staff = user is not None and user.role in ("admin", "employee")

    try:
        if search_type == "bookings":
            query = searcher(q=q, category=category, destination=destination,
                             status=status, current_user=user, is_staff=is_staff)
        elif search_type == "clients":
            query = searcher(q=q, category=category, destination=destination,
                             current_user=user, is_staff=is_staff)
        else:
            query = searcher(q=q, category=category, destination=destination,
                             min_price=min_price, max_price=max_price,
                             min_stars=min_stars, current_user=user, is_staff=is_staff)
    except Exception:
        return jsonify({"success": False, "error": "Error en la búsqueda."}), 500

    items, total, pages = search_repo._paginate(query, page, per_page)

    # Serializar según tipo
    if search_type == "bookings":
        items_data = [{"id": b.id, "booking_code": b.booking_code,
                       "destination_name": b.destination_name,
                       "status": b.status, "total_price": float(b.total_price or 0),
                       "travelers": b.travelers} for b in items]
    elif search_type == "clients":
        items_data = [{"id": c.id, "name": c.name, "email": c.email,
                       "document_id": c.document_id, "category": c.category,
                       "trips_count": c.trips_count} for c in items]
    elif search_type in ("packages", "flights"):
        items_data = [{"id": it.id, "title": getattr(it, "title", getattr(it, "airline", "")),
                       "destination_name": getattr(it, "destination_name", getattr(it, "destination", "")),
                       "price_usd": float(getattr(it, "price_usd", 0) or 0)}
                      for it in items]
    else:
        items_data = [{"id": it.id, "name": getattr(it, "name", getattr(it, "title", ""))}
                      for it in items]

    return jsonify({
        "items": items_data,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
        "has_next": page < pages,
        "filters_applied": {
            "q": q, "type": search_type, "category": category,
            "destination": destination, "status": status,
            "min_price": min_price, "max_price": max_price,
            "date_from": date_from, "date_to": date_to, "min_stars": min_stars,
            "sort": sort, "order": order,
        }
    })


@bp.route("/reports/<kind>.<fmt>")
@permission_required("reports:view")
def download_report(kind, fmt):
    """Descarga un reporte en PDF o XLSX (RF-15). Admin/employee."""
    from .reports import formatters, generators
    user = get_current_user()
    data = request.args
    date_from = data.get("date_from") or None
    date_to = data.get("date_to") or None
    status = data.get("status", "").strip()
    destination = data.get("destination", "").strip()

    if fmt not in ("pdf", "xlsx"):
        return jsonify({"success": False, "error": "Formato inválido (usa pdf o xlsx)."}), 422
    try:
        headers, rows, totals = formatters.build_report(
            kind, date_from=date_from, date_to=date_to,
            status=status, destination=destination)
    except ValueError:
        return jsonify({"success": False,
                        "error": f"Tipo de reporte inválido: '{kind}'."}), 422

    filename = f"reporte_{kind}_{date.today().isoformat()}.{fmt}"
    if fmt == "xlsx":
        buf = generators.generate_xlsx(f"Reporte {kind}", headers, rows, totals=totals)
        mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        buf = generators.generate_pdf(f"Reporte {kind}", headers, rows, totals=totals,
                                      user=user.name if user else "", date_from=date_from,
                                      date_to=date_to)
        mimetype = "application/pdf"

    store.record_event("DESCARGAR_REPORTE", "Reportes", user_id=user.id, user_name=user.name,
                       details=f"Reporte {kind} en {fmt} descargado.")
    return send_file(buf, mimetype=mimetype, as_attachment=True, download_name=filename)


@bp.route("/api/health")
def health():
    return jsonify({"status": "ok", "app": "DDN Travel Server (Python)"})


# ----------------------------------------------------------------------
# Inicio de sesión con Google (OAuth médiante flask-dance)
# ----------------------------------------------------------------------
google_bp_enabled = False
google_bp = None

GOOGLE_OAUTH_SCOPES = ["https://www.googleapis.com/auth/userinfo.email",
                       "https://www.googleapis.com/auth/userinfo.profile"]

try:
    from flask_dance.consumer import oauth_authorized
    from flask_dance.contrib.google import make_google_blueprint, google
except ImportError:
    google = None

if google is not None and os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"):
    google_bp = make_google_blueprint(
        client_id=os.environ.get("GOOGLE_CLIENT_ID"),
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
        scope=GOOGLE_OAUTH_SCOPES,
        authorized_url="/login/google/authorized",
        redirect_to="main.google_authorized",
    )
    bp.register_blueprint(google_bp)
    ENDPOINT_PERMISSIONS.update({
        "main.google.login": "session:entry",
        "main.google.authorized": "session:entry",
    })
    google_bp_enabled = True
    # El blueprint de flask-dance publica sus endpoints bajo "main.google.*".
    # Se declaran públicos (y con permiso nominal en el mapa) aquí, porque esta
    # rama solo se ejecuta cuando el OAuth está configurado en el entorno; si no
    # hay claves, esos endpoints no existen y no deben quedar registrados.
    _permissions.PUBLIC_ENDPOINTS = _permissions.PUBLIC_ENDPOINTS | {
        "main.google.login", "main.google.authorized"}
    _permissions.ENDPOINT_PERMISSIONS.update({
        "main.google.login": "session:entry",
        "main.google.authorized": "session:entry",
    })
    LOGIN_EXEMPT.update({"main.google.login", "main.google.authorized"})


@bp.route("/login/google")
def google_login():
    if google is None or not google_bp_enabled:
        flash("El acceso con Google no está configurado.", "error")
        return redirect(url_for("main.login"))
    return redirect(url_for("main.google.login"))


def _find_or_create_client_session(email: str, name: str, avatar: str | None = None):
    """Reutiliza o crea la cuenta y la ficha del cliente que entra con Google."""
    return store.find_or_create_google_user(email, name, avatar=avatar or "")


@bp.route("/login/google/complete")
def google_authorized():
    if not google.authorized:
        flash("No se pudo autenticar con Google.", "error")
        return redirect(url_for("main.login"))
    try:
        info = google.get("/oauth2/v2/userinfo")
        info.raise_for_status()
        data = info.json()
    except Exception as _e:  # noqa: BLE001
        current_app.logger.exception("No se pudo obtener el perfil de Google.")
        flash("No se pudo leer tu información de Google.", "error")
        return redirect(url_for("main.login"))
    if not isinstance(data, dict):
        current_app.logger.error("Google devolvió un perfil con formato inesperado.")
        flash("Google devolvió información de perfil inválida.", "error")
        return redirect(url_for("main.login"))

    email_value = data.get("email")
    if not isinstance(email_value, str) or not email_value.strip():
        flash("El correo de Google no está disponible.", "error")
        return redirect(url_for("main.login"))
    email = email_value.strip().lower()
    name_value = data.get("name")
    name = name_value.strip()[:100] if isinstance(name_value, str) else ""
    name = name or email.split("@", 1)[0]
    avatar_value = data.get("picture")
    avatar = avatar_value[:500] if isinstance(avatar_value, str) else ""

    try:
        user = _find_or_create_client_session(email, name, avatar=avatar)
        if not user.is_active:
            flash("Esta cuenta está desactivada. Contacta a la agencia.", "error")
            return redirect(url_for("main.login"))
        store.record_event("INICIO_SESION", "Autenticación", user=user,
                           details=f"Inicio de sesión con Google de {user.email}.")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("No se pudo completar el inicio de sesión con Google.")
        flash("No se pudo completar el inicio de sesión. Inténtalo de nuevo más tarde.", "error")
        return redirect(url_for("main.login"))

    session["user_id"] = user.id
    flash(f"Bienvenido, {user.name.split(' (')[0]} (acceso con Google).", "success")
    return redirect(url_for("main.client_portal"))


# ----------------------------------------------------------------------
# Contacto, Chat en vivo & FAQ
# ----------------------------------------------------------------------
FAQS = [
    {"question": "¿Cómo hago una reserva?", "answer": "Inicia sesión, ve al catálogo de paquetes, elige uno y haz clic en «Reservar». Completa los datos y confirma."},
    {"question": "¿Puedo modificar mi reserva después de confirmada?", "answer": "Sí, contacta a tu agente o usa la opción «Solicitar llamada» en Contacto. Los cambios están sujetos a disponibilidad y políticas del proveedor."},
    {"question": "¿Qué métodos de pago aceptan?", "answer": "Tarjeta de crédito/débito, transferencia bancaria, efectivo (en oficina), cripto (USDT/USDC) y PayPal."},
    {"question": "¿Cómo recibo mis documentos de viaje?", "answer": "Se suben a tu portal en «Mis Documentos» y te llega un email. También puedes descargarlos desde la app."},
    {"question": "¿Ofrecen seguros de viaje?", "answer": "Sí, al reservar puedes añadir seguro de cancelación, médico y equipaje. Pregunta a tu agente por las coberturas."},
    {"question": "¿Hay atención 24/7 durante mi viaje?", "answer": "Sí, la línea de emergencia +1 (809) 555-0124 está activa las 24 horas para clientes en viaje."},
    {"question": "¿Puedo cancelar mi reserva?", "answer": "Depende de la tarifa. Algunas son reembolsables, otras no. Revisa las condiciones en el detalle de tu reserva o contacta soporte."},
    {"question": "¿Cómo uso el generador de itinerarios con IA?", "answer": "En tu portal, haz clic en «Generar Itinerario IA», elige destino, días, tipo de viaje y ritmo. La IA crea un plan día a día."},
]


@bp.route("/contacto", methods=["GET", "POST"])
@limiter.limit(lambda: current_app.config["CONTACT_RATE_LIMIT"])
def contact():
    if request.method == "POST":
        f = request.form
        # ``.get`` puede devolver None y los POST automatizados no traen todos
        # los campos: se normalizan a cadena y se corta por longitud.
        nombre = (f.get("name") or "").strip()[:120]
        email = (f.get("email") or "").strip()[:120]
        asunto = (f.get("subject") or "").strip()[:200]
        mensaje = (f.get("message") or "").strip()
        if not mensaje:
            flash("Escribe tu mensaje antes de enviarlo.", "error")
            return render_template("contact.html", faqs=FAQS)
        if len(mensaje) > current_app.config["CONTACT_MESSAGE_MAX_LENGTH"]:
            flash(f"El mensaje es demasiado largo (máximo {current_app.config['CONTACT_MESSAGE_MAX_LENGTH']} caracteres).", "error")
            return render_template("contact.html", faqs=FAQS)
        store.log_action(
            "public", "Visitante Web", "CONTACT_FORM",
            "Contacto", f"Mensaje de {nombre} ({email}): {asunto}"
        )
        store.add_notification(
            "Nuevo mensaje de contacto",
            f"{nombre} ({email}) - {asunto}: {mensaje[:120]}...",
            "info", "contact"
        )
        flash("¡Gracias! Tu mensaje ha sido enviado. Te responderemos en menos de 24 horas.", "success")
        return redirect(url_for("main.contact"))
    return render_template("contact.html", faqs=FAQS)


@bp.route("/contacto/callback", methods=["POST"])
@permission_required("profile:callback")
@limiter.limit(lambda: current_app.config["CONTACT_RATE_LIMIT"])
def request_callback():
    f = request.form
    reason = (f.get("reason") or "").strip()[:500]
    phone = (f.get("phone") or "").strip()[:40]
    if not reason or not phone:
        flash("Completa todos los campos.", "error")
        return redirect(url_for("main.contact"))
    user = get_current_user()
    store.log_action(
        user.id, user.name, "CALLBACK_REQUEST", "Contacto",
        f"Cliente solicita llamada: {reason} - Tel: {phone}"
    )
    store.add_notification(
        "📞 Solicitud de llamada urgente",
        f"{user.name} ({user.email}) necesita que le llamen. Motivo: {reason}. Tel: {phone}",
        "warning", "contact", visible_roles=["admin", "employee"]
    )
    flash("Solicitud registrada. Un agente te llamará en los próximos 15 minutos al número indicado.", "success")
    return redirect(url_for("main.contact"))


@bp.route("/api/chat/message", methods=["POST"])
@limiter.limit(lambda: current_app.config["CHAT_RATE_LIMIT"])
def chat_message():
    """Asistente virtual: solo responde con la FAQ, sin datos de clientes.

    La coincidencia es por **palabras completas**: comparar subcadenas hacía que
    «hi» encajara dentro de «which» y «hola» dentro de «holanda».
    """
    data = request.get_json(force=True, silent=True) or {}
    user_msg = (data.get("message") or "").strip()
    if len(user_msg) > current_app.config["CHAT_MESSAGE_MAX_LENGTH"]:
        return jsonify({
            "success": False,
            "reply": f"El mensaje es demasiado largo (máximo {current_app.config['CHAT_MESSAGE_MAX_LENGTH']} caracteres).",
        }), 422
    palabras = set(re.findall(r"[a-záéíóúñü]+", user_msg.lower()))
    if not palabras:
        return jsonify({"reply": "Escribe algo para que pueda ayudarte.", "faq": False})

    for faq in FAQS:
        # Palabras completas de la pregunta (se ignoran las de menos de 4 letras).
        clave = {p for p in re.findall(r"[a-záéíóúñü]+", faq["question"].lower()) if len(p) > 3}
        if clave & palabras:
            return jsonify({"reply": faq["answer"], "faq": True, "matched": faq["question"]})
    if palabras & {"hola", "buenas", "buenos", "hello", "hi", "hey", "saludos"}:
        return jsonify({"reply": "¡Hola! 👋 Soy el asistente virtual de DDN Travel. ¿En qué puedo ayudarte hoy? Puedes preguntarme sobre reservas, pagos, documentos, seguros, itinerarios...", "faq": False})
    if palabras & {"gracias", "thanks", "thx"}:
        return jsonify({"reply": "¡De nada! 😊 Si necesitas algo más, aquí estoy. También puedes llamarnos al +1 (809) 555-0123.", "faq": False})
    return jsonify({"reply": "No tengo una respuesta exacta para eso. ¿Quieres que te conecte con un agente humano? Escribe «agente» o ve a la página de Contacto.", "faq": False, "suggest_agent": True})


# ----------------------------------------------------------------------
# Manejo de errores
# ----------------------------------------------------------------------
@bp.app_errorhandler(403)
def forbidden(_e):
    return render_template("error.html", code=403,
                           message="No tienes permisos para acceder a este módulo."), 403


@bp.app_errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404,
                           message="La página que buscas no existe."), 404


@bp.app_errorhandler(500)
def server_error(_e):
    return render_template("error.html", code=500,
                           message="Ocurrió un error interno en el servidor."), 500


# ----------------------------------------------------------------------
# Facturación RD: NCF y PDF de factura
# ----------------------------------------------------------------------
@bp.route("/payments/<int:payment_id>/ncf", methods=["GET"])
@permission_required("payments:invoice")
def payment_ncf(payment_id):
    """NCF de un pago. Autorización y propiedad ya comprobadas; la emisión
    real del NCF secuencial y persistente es de la fase P4 (ver P4 punto 2)."""
    user = get_current_user()
    payment = find_payment(payment_id)
    owned_or_404(user, payment)
    return jsonify({"payment_id": payment.id, "ncf": payment.ncf or "",
                    "invoice_number": payment.invoice_number or "",
                    "amount": float(payment.amount or 0)})


@bp.route("/payments/<int:payment_id>/factura", methods=["GET"])
@permission_required("payments:invoice")
def payment_factura(payment_id):
    """Factura PDF de un pago. Autorización y propiedad ya comprobadas; el
    PDF real (emisor desde configuración, ítems, NCF) es de la fase P4."""
    user = get_current_user()
    payment = find_payment(payment_id)
    owned_or_404(user, payment)
    from .billing import generar_pdf_factura
    booking = store.get_booking(payment.booking_id)
    client = store.get_client(booking.client_id) if booking is not None else None
    concepto = (booking.destination_name or "Reserva de viaje") if booking else "Reserva"
    if booking is not None:
        concepto += f" ({booking.booking_code})"
    if payment.reference:
        concepto += f" · Ref: {payment.reference}"
    # Importes del PAGO (no del total de la reserva: un pago parcial solo
    # muestra lo efectivamente cobrado en esta factura).
    items = [{
        "description": concepto,
        "quantity": 1,
        "price": float(payment.amount or 0),
    }]
    pdf = generar_pdf_factura(
        titulo="Factura",
        rnc_emitter=current_app.config.get("AGENCY_RNC", ""),
        nombre_emitter=current_app.config.get("AGENCY_NAME", "DDN Travel"),
        rnc_client=(client.document_id if client is not None else "") or "",
        nombre_client=(client.name if client is not None else "Cliente"),
        items=items,
        total=float(payment.amount or 0),
        ncf=payment.ncf or "N/D",
        fecha=payment.date or None,
        direccion_emitter=current_app.config.get("AGENCY_ADDRESS", ""),
        telefono_emitter=current_app.config.get("AGENCY_PHONE", ""),
    )
    return send_file(BytesIO(pdf), mimetype="application/pdf",
                     as_attachment=True, download_name=f"factura_{payment.invoice_number or payment.id}.pdf")


# ----------------------------------------------------------------------
# Manejo de errores
# ----------------------------------------------------------------------
