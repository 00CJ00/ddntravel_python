"""Rutas de la aplicación DDN Travel (equivalente a App.tsx + server.ts).

La autorización se resuelve con ``app/permissions.py``: cada ruta declara el
permiso que exige (``@permission_required``) y, cuando aplica, además verifica
la propiedad del registro (``owned_or_404``). La matriz de permisos es la
única fuente de verdad; aquí no se comprueban roles a mano.
"""
from __future__ import annotations
import os
import re
import datetime
from datetime import date

from flask import (
    Blueprint, render_template, request, redirect, url_for, session, jsonify,
    abort, flash, current_app
)
from werkzeug.security import check_password_hash

from .store import store
from .models import Client, UserSession, new_id
from . import ai_service
from .extensions import limiter
from .view import store_view
from .permissions import (
    PERMISSIONS, PUBLIC_ENDPOINTS, can, client_record, get_current_user,
    get_store, owned_or_404, own_records, owns, permission_required,
)

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
    """Busca un pago por su identificador.

    El repositorio definitivo (``store.get_payment``) llega en la fase P4,
    junto con la secuencia de NCF y el PDF de factura reales.
    """
    return next((p for p in store.payments if p.id == payment_id), None)


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
    público; ``window.DDN_DATA`` (en base.html) recibe esa misma vista, de modo
    que ninguna respuesta contiene datos de otros clientes. La eliminación de
    ``window.DDN_DATA`` por completo es trabajo de la fase P7.
    """
    current_user = get_current_user()
    view = store_view(store, current_user)
    if current_user is not None:
        visible_notifs = [
            n for n in view.notifications
            if n.visible_roles is None or current_user.role in n.visible_roles
        ]
    else:
        visible_notifs = []
    unread = [n for n in visible_notifs if not n.read]
    # Mapa permiso → bool para que el JS decida qué botones mostrar. Es la misma
    # matriz que aplica el servidor: solo oculta botones, nunca autoriza.
    client_permissions = {p: can(p, current_user) for p in PERMISSIONS}
    client_side_data = {
        "clients": [c.to_dict() for c in view.clients],
        "packages": [p.to_dict() for p in view.packages],
        "hotels": [h.to_dict() for h in view.hotels],
        "flights": [f.to_dict() for f in view.flights],
        "currentUser": current_user.to_dict() if current_user else None,
    }
    return {
        "store": view,
        "current_user": current_user,
        "available_users": view.available_users,
        "theme": session.get("theme", "deep-space"),
        "notifications": visible_notifs,
        "unread_notifications": unread,
        "client_side_data": client_side_data,
        "client_permissions": client_permissions,
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
                and getattr(user, "is_active", True) \
                and check_password_hash(user.password_hash, password):
            session["user_id"] = user.id
            flash(f"Bienvenido, {user.name.split(' (')[0]}.", "success")
            return redirect(url_for("main.index"))
        error = "Correo o contraseña incorrectos."
    return render_template("login.html", error=error, google_enabled=google_bp_enabled)


@bp.route("/logout", methods=["POST"])
@permission_required("session:logout")
def logout():
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


@bp.route("/ai-predictive")
@permission_required("ai:predictive_view")
def ai_predictive():
    timeframe = request.args.get("timeframe", "Próximos 6 meses (Q3 & Q4)")
    if store.predictive_data is None:
        store.predictive_data = ai_service.get_predictive_analytics(
            store.clients, store.bookings, store.packages, timeframe)
    return render_template("ai_predictive.html", active_tab="ai-predictive",
                            predictive_data=store.predictive_data, timeframe=timeframe)


@bp.route("/bookings")
@permission_required("bookings:view")
def bookings():
    return render_template("bookings.html", active_tab="bookings",
                            bookings=list(reversed(store.bookings)))


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
    data = request.form
    dest = store.add_destination(get_current_user(), **data)
    return jsonify({"success": True, "id": dest.id, "name": dest.name})


@bp.route("/admin/destinations/<dest_id>", methods=["POST"])
@permission_required("catalog:edit")
def admin_edit_destination(dest_id):
    data = request.form
    # White list: solo permitir actualizar campos del catálogo, no 'id' ni otros protegidos
    allowed = {"name", "country", "region", "cover_image", "description",
               "weather_type", "best_season", "high_season_months",
               "popular_attractions", "base_price_usd", "status", "rating"}
    data = {k: v for k, v in data.items() if k in allowed}
    dest = store.edit_destination(get_current_user(), dest_id, **data)
    if dest:
        return jsonify({"success": True, "name": dest.name})
    return jsonify({"success": False, "error": "Destino no encontrado"}), 404


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
                           packages=store.packages[:4])


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


@bp.route("/notifications/<notif_id>/read", methods=["POST"])
@permission_required("notifications:read")
def read_notification(notif_id):
    store.mark_notification_as_read(notif_id)
    return redirect_back("main.dashboard")


@bp.route("/notifications/read-all", methods=["POST"])
@permission_required("notifications:read")
def read_all_notifications():
    store.mark_all_notifications_as_read()
    return redirect_back("main.dashboard")


# ----------------------------------------------------------------------
# Clientes
# ----------------------------------------------------------------------
@bp.route("/clients/new", methods=["POST"])
@permission_required("clients:create")
def new_client():
    f = request.form
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
    destinations_list = [d.strip() for d in f.get("preferred_destinations", "").split(",") if d.strip()]
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
    package = store.get_package(f.get("package_id", "")) if f.get("package_id") else None
    hotel = store.get_hotel(f.get("hotel_id", "")) if f.get("hotel_id") else None
    flight = store.get_flight(f.get("flight_id", "")) if f.get("flight_id") else None
    travelers = int_field(f, "travelers", 1, minimum=1, maximum=10)

    if not client:
        return render_template("bookings.html", active_tab="bookings",
                                bookings=own_records(current_user, store.bookings),
                                error="Regla de Negocio (RN-02): Debe seleccionar o registrar un cliente para "
                                      "asociar a la reserva.")

    base_price = package.price_usd if package else (
        (hotel.room_types[0]["price_per_night"] if hotel and getattr(hotel, "room_types", None) else 300))
    flight_addon = (flight.price_usd * travelers) if flight else 0
    raw_total = (base_price * travelers) + flight_addon

    promo_code = f.get("promo_code", "").strip()
    discounted_total = raw_total
    promo_note = ""
    if promo_code:
        promo_result = store.apply_promo_code(promo_code, raw_total, client.category)
        if promo_result["valid"]:
            discounted_total = promo_result["final_price"]
            promo_note = f" [Cupón: {promo_code.upper()} - {promo_result['discount_percentage']}%]"
        else:
            flash(promo_result["message"], "error")
            return render_template("bookings.html", active_tab="bookings",
                                   bookings=own_records(current_user, store.bookings),
                                   error=promo_result["message"])

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
        hotel_name=hotel.name if hotel else None, flight_id=flight.id if flight else None,
        flight_number=flight.flight_number if flight else None, total_price=discounted_total,
        notes=(f.get("notes", "") + promo_note).strip(),
        initial_payment=float_field(f, "initial_payment"),
        payment_method=f.get("payment_method", "Tarjeta de Crédito"),
        transport_id=f.get("transport_id") or None,
        check_in=f.get("check_in") or f.get("departure_date", ""),
        check_out=f.get("check_out") or f.get("return_date", ""),
        rooms_count=int_field(f, "rooms_count", 1, minimum=1, maximum=20),
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


@bp.route("/bookings/<booking_id>/edit", methods=["POST"])
@permission_required("bookings:edit")
def edit_booking(booking_id):
    """Edita fechas, viajeros, notas (recalcula total y revalida inventario)."""
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
        changes["rooms_count"] = int_field(f, "rooms_count", getattr(booking, "rooms_count", 1), minimum=1, maximum=20)
    result = store.update_booking(user, booking_id, **changes)
    if request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json":
        return jsonify(result)
    flash(result["message"], "success" if result["success"] else "error")
    return redirect_back("main.bookings")


@bp.route("/bookings/<booking_id>/cancel", methods=["POST"])
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


@bp.route("/bookings/<booking_id>/status", methods=["POST"])
@permission_required("bookings:status")
def update_booking_status(booking_id):
    """Cambia el estado de una reserva pasando por BookingService.transition (RN-03)."""
    user = get_current_user()
    owned_or_404(user, store.get_booking(booking_id))
    nuevo_estado = request.form.get("status", "Pendiente")
    result = store.update_booking_status(user, booking_id, nuevo_estado)
    if not result["success"]:
        flash(result["message"], "error")
    else:
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
    flash(result.get("message", "Pago registrado."), "success" if result.get("success") else "error")
    # La asignación de NCF secuencial y persistente (RF-11 / P4) se hace dentro
    # de la transacción del pago; ver /payments/<id>/ncf (501 en esta fase).
    return redirect(url_for("main.payments"))


@bp.route("/payments/<payment_id>/verify", methods=["POST"])
@permission_required("payments:create")
def verify_payment(payment_id):
    """Verifica un pago Pendiente_verificacion (Transferencia/Efectivo). Admin/employee."""
    result = store.verify_payment(get_current_user(), payment_id)
    flash(result["message"], "success" if result["success"] else "error")
    return redirect_back("main.payments")


# ----------------------------------------------------------------------
# Paquetes (RF-05)
# ----------------------------------------------------------------------
@bp.route("/admin/packages/new", methods=["POST"])
@permission_required("catalog:create")
def admin_new_package():
    f = request.form
    store.add_package(
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
    )
    return redirect(url_for("main.packages"))


@bp.route("/admin/packages/<pkg_id>", methods=["POST"])
@permission_required("catalog:edit")
def admin_edit_package(pkg_id):
    f = request.form
    pkg = store.get_package(pkg_id)
    if not pkg:
        return jsonify({"success": False, "error": "Paquete no encontrado"}), 404
    updated = store.edit_package(get_current_user(), pkg_id, **dict(f))
    if updated is None:
        return jsonify({"success": False, "error": "Paquete no encontrado"}), 404
    return jsonify({"success": True, "title": updated.title})


@bp.route("/admin/packages/<pkg_id>/delete", methods=["POST"])
@permission_required("catalog:delete")
def admin_delete_package(pkg_id):
    pkg = store.get_package(pkg_id)
    if not pkg:
        return jsonify({"success": False, "error": "Paquete no encontrado"}), 404
    # Soft delete: verificar si hay reservas activas
    has_active_bookings = any(
        b.package_id == pkg_id and b.status != "Cancelada" for b in store.bookings
    )
    if has_active_bookings:
        return jsonify({"success": False, "error": "No se puede eliminar el paquete: tiene reservas activas."}), 409
    # Marcar como inactivo
    pkg.is_active = False
    pkg.deleted_at = datetime.datetime.now().isoformat()
    store.log_action(get_current_user().id, get_current_user().name, "ELIMINAR_PAQUETE", "Paquetes",
                      f"Desactivado paquete ID: {pkg_id}")
    return jsonify({"success": True, "title": pkg.title})


# ----------------------------------------------------------------------
# Hoteles y RoomTypes
# ----------------------------------------------------------------------
@bp.route("/admin/hotels/new", methods=["POST"])
@permission_required("catalog:create")
def admin_new_hotel():
    f = request.form
    # Los room_types vienen como lista de dicts desde el formulario
    room_types_data = []
    # Formato esperado: room_types[0][type], room_types[0][price_per_night], room_types[0][available], etc.
    # El frontend puede enviar room_types como JSON o campos planos
    rt_count = int_field(f, "room_types_count", 1, minimum=1, maximum=20)
    for i in range(rt_count):
        rt = {
            "type": f.get(f"room_type[{i}][type]", ""),
            "price_per_night": float_field(f, f"room_type[{i}][price_per_night]", 0.0),
            "available": int_field(f, f"room_type[{i}][available]", 0, minimum=0),
        }
        room_types_data.append(rt)
    store.add_hotel(
        get_current_user(),
        name=f.get("name", ""), destination_id=f.get("destination_id", ""),
        destination_name=f.get("destination_name", ""), stars=int_field(f, "stars", 5, minimum=1, maximum=5),
        address=f.get("address", ""), rating=float_field(f, "rating", 0.0, minimum=0, maximum=5),
        image=f.get("image", ""), contact_phone=f.get("contact_phone", ""),
        amenities=f.get("amenities", ""), room_types=room_types_data,
    )
    return redirect(url_for("main.hotels"))


@bp.route("/admin/hotels/<hotel_id>", methods=["POST"])
@permission_required("catalog:edit")
def admin_edit_hotel(hotel_id):
    f = request.form
    hotel = store.get_hotel(hotel_id)
    if not hotel:
        return jsonify({"success": False, "error": "Hotel no encontrado"}), 404
    rt_count = int_field(f, "room_types_count", len(hotel.room_types or []), minimum=1, maximum=20)
    new_room_types = []
    for i in range(rt_count):
        old = hotel.room_types[i] if hotel.room_types and i < len(hotel.room_types) else {}
        new_room_types.append({
            "type": f.get(f"room_type[{i}][type]", old.get("type", "")),
            "price_per_night": float_field(f, f"room_type[{i}][price_per_night]", old.get("price_per_night", 0.0)),
            "available": int_field(f, f"room_type[{i}][available]", old.get("available", 0), minimum=0),
        })
    updated = store.edit_hotel(get_current_user(), hotel_id, room_types=new_room_types,
                               **{k: v for k, v in f.items() if k in
                                  {"name", "destination_id", "destination_name", "stars", "address",
                                   "rating", "image", "contact_phone", "amenities"}})
    return jsonify({"success": True, "name": updated.name if updated else hotel.name})


@bp.route("/admin/hotels/<hotel_id>/delete", methods=["POST"])
@permission_required("catalog:delete")
def admin_delete_hotel(hotel_id):
    hotel = store.get_hotel(hotel_id)
    if not hotel:
        return jsonify({"success": False, "error": "Hotel no encontrado"}), 404
    # Soft delete: verificar si hay reservas activas que lo referencien
    has_active_bookings = any(
        b.hotel_id == hotel_id and b.status != "Cancelada" for b in store.bookings
    )
    if has_active_bookings:
        return jsonify({"success": False, "error": "No se puede desactivar el hotel: tiene reservas activas."}), 409
    # Soft delete
    hotel.is_active = False
    hotel.deleted_at = datetime.datetime.now().isoformat()
    store.log_action(get_current_user().id, get_current_user().name, "ELIMINAR_HOTEL", "Hoteles",
                      f"Desactivado hotel ID: {hotel_id}")
    return jsonify({"success": True, "name": hotel.name})


# ----------------------------------------------------------------------
# Vuelos
# ----------------------------------------------------------------------
@bp.route("/admin/flights/new", methods=["POST"])
@permission_required("catalog:create")
def admin_new_flight():
    f = request.form
    store.add_flight(
        get_current_user(),
        airline=f.get("airline", ""), flight_number=f.get("flight_number", ""),
        origin=f.get("origin", ""), destination=f.get("destination", ""),
        departure_time=f.get("departure_time", ""), arrival_time=f.get("arrival_time", ""),
        price_usd=float_field(f, "price_usd", 0.0), seats_available=int_field(f, "seats_available", 0,
                                                                         minimum=0),
        total_seats=int_field(f, "total_seats", 0, minimum=1), flight_class=f.get("flight_class", "Económica"),
        status=f.get("status", "A tiempo"), baggage_allowance=f.get("baggage_allowance", ""),
        image=f.get("image", ""),
    )
    return redirect(url_for("main.flights"))


@bp.route("/admin/flights/<flight_id>", methods=["POST"])
@permission_required("catalog:edit")
def admin_edit_flight(flight_id):
    f = request.form
    flight = store.get_flight(flight_id)
    if not flight:
        return jsonify({"success": False, "error": "Vuelo no encontrado"}), 404
    allowed = {"airline", "flight_number", "origin", "destination", "departure_time", "arrival_time",
               "price_usd", "seats_available", "total_seats", "flight_class", "status", "baggage_allowance", "image"}
    updated = store.edit_flight(get_current_user(), flight_id,
                                **{k: v for k, v in f.items() if k in allowed})
    return jsonify({"success": True, "airline": updated.airline, "flight_number": updated.flight_number})


@bp.route("/admin/flights/<flight_id>/delete", methods=["POST"])
@permission_required("catalog:delete")
def admin_delete_flight(flight_id):
    flight = store.get_flight(flight_id)
    if not flight:
        return jsonify({"success": False, "error": "Vuelo no encontrado"}), 404
    # Soft delete: verificar si hay reservas activas
    has_active_bookings = any(
        b.flight_id == flight_id and b.status != "Cancelada" for b in store.bookings
    )
    if has_active_bookings:
        return jsonify({"success": False, "error": "No se puede desactivar el vuelo: tiene reservas activas."}), 409
    # Soft delete
    flight.is_active = False
    flight.deleted_at = datetime.datetime.now().isoformat()
    store.log_action(get_current_user().id, get_current_user().name, "ELIMINAR_VUELO", "Vuelos",
                      f"Desactivado vuelo ID: {flight_id}")
    return jsonify({"success": True, "airline": flight.airline, "flight_number": flight.flight_number})


# ----------------------------------------------------------------------
# Transportes
# ----------------------------------------------------------------------
@bp.route("/admin/transports/new", methods=["POST"])
@permission_required("catalog:create")
def admin_new_transport():
    f = request.form
    store.add_transport(
        get_current_user(),
        type=f.get("type", ""), route=f.get("route", ""), vehicle_model=f.get("vehicle_model", ""),
        capacity=int_field(f, "capacity", 0, minimum=0), available_seats=int_field(f, "available_seats", 0,
                                                                             minimum=0),
        driver_name=f.get("driver_name", ""), price_usd=float_field(f, "price_usd", 0.0),
        status=f.get("status", "Operativo"), amenities=f.get("amenities", ""), image=f.get("image", ""),
    )
    return redirect(url_for("main.transports"))


@bp.route("/admin/transports/<transport_id>", methods=["POST"])
@permission_required("catalog:edit")
def admin_edit_transport(transport_id):
    f = request.form
    transport = store.get_transport(transport_id)
    if not transport:
        return jsonify({"success": False, "error": "Transporte no encontrado"}), 404
    allowed = {"type", "route", "vehicle_model", "capacity", "available_seats", "driver_name",
               "price_usd", "status", "amenities", "image"}
    updated = store.edit_transport(get_current_user(), transport_id,
                                   **{k: v for k, v in f.items() if k in allowed})
    return jsonify({"success": True, "type": updated.type})


@bp.route("/admin/transports/<transport_id>/delete", methods=["POST"])
@permission_required("catalog:delete")
def admin_delete_transport(transport_id):
    transport = store.get_transport(transport_id)
    if not transport:
        return jsonify({"success": False, "error": "Transporte no encontrado"}), 404
    # Soft delete: verificar si hay reservas activas
    has_active_bookings = any(
        b.transport_id == transport_id and b.status != "Cancelada" for b in store.bookings
    )
    if has_active_bookings:
        return jsonify({"success": False, "error": "No se puede desactivar el transporte: tiene reservas activas."}), 409
    # Soft delete
    transport.is_active = False
    transport.deleted_at = datetime.datetime.now().isoformat()
    store.log_action(get_current_user().id, get_current_user().name, "ELIMINAR_TRANSPORTE", "Transporte",
                      f"Desactivado transporte ID: {transport_id}")
    return jsonify({"success": True, "type": transport.type})


# ----------------------------------------------------------------------
# Actividades
# ----------------------------------------------------------------------
@bp.route("/admin/activities/new", methods=["POST"])
@permission_required("catalog:create")
def admin_new_activity():
    f = request.form
    store.add_activity(
        get_current_user(),
        title=f.get("title", ""), destination_id=f.get("destination_id", ""),
        destination_name=f.get("destination_name", ""), duration_hours=int_field(f, "duration_hours", 1),
        price_usd=float_field(f, "price_usd", 0.0), includes_guide=bool(int_field(f, "includes_guide", 0,
                                                                                  minimum=0, maximum=1)),
        difficulty=f.get("difficulty", "Fácil"), image=f.get("image", ""),
        description=f.get("description", ""), category=f.get("category", "Turismo"),
        schedule=f.get("schedule", ""),
    )
    return redirect(url_for("main.activities"))


@bp.route("/admin/activities/<activity_id>", methods=["POST"])
@permission_required("catalog:edit")
def admin_edit_activity(activity_id):
    f = request.form
    activity = next((a for a in store.activities if a.id == activity_id), None)
    if not activity:
        return jsonify({"success": False, "error": "Actividad no encontrada"}), 404
    allowed = {"title", "destination_id", "destination_name", "duration_hours", "price_usd",
               "includes_guide", "difficulty", "image", "description", "category", "schedule"}
    updated = store.edit_activity(get_current_user(), activity_id,
                                  **{k: v for k, v in f.items() if k in allowed})
    if updated is None:
        return jsonify({"success": False, "error": "Actividad no encontrada"}), 404
    return jsonify({"success": True, "title": updated.title})


@bp.route("/admin/activities/<activity_id>/delete", methods=["POST"])
@permission_required("catalog:delete")
def admin_delete_activity(activity_id):
    if store.delete_activity(get_current_user(), activity_id):
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Actividad no encontrada o no autorizado"}), 404


# ----------------------------------------------------------------------
# Clientes (edit y delete con soft delete)
# ----------------------------------------------------------------------
@bp.route("/admin/clients/<client_id>/edit", methods=["POST"])
@permission_required("clients:edit")
def admin_edit_client(client_id):
    f = request.form
    client = store.get_client(client_id)
    if not client:
        return jsonify({"success": False, "error": "Cliente no encontrado"}), 404
    # Campos permitidos para edición de perfil admin
    allowed = {"name", "email", "phone", "document_id", "nationality", "category",
               "budget_preference", "passport_expiry", "notes", "status"}
    changes = {k: v for k, v in f.items() if k in allowed}
    # Validación: email válido y único (RN de clientes), precios/documento únicos si cambian.
    from . import validators
    errors = []
    if "email" in changes:
        if not validators.validate_email(changes["email"]):
            errors.append("Email inválido.")
        errors += validators.validate_email_unique(changes["email"], client_id, store.clients)
    if "document_id" in changes and changes["document_id"]:
        errors += validators.validate_document_unique(changes["document_id"], client_id, store.clients)
    if errors:
        return jsonify({"success": False, "errors": errors}), 422
    store.update_client(get_current_user(), client_id, **changes)
    store.log_action(get_current_user().id, get_current_user().name, "EDITAR_CLIENTE", "Clientes",
                      f"Actualizado cliente ID: {client_id}")
    return jsonify({"success": True, "name": client.name})


@bp.route("/admin/clients/<client_id>/delete", methods=["POST"])
@permission_required("clients:delete")
def admin_delete_client(client_id):
    result = store.delete_client(get_current_user(), client_id)
    if not result:
        return jsonify({"success": False, "error": "Cliente no encontrado"}), 404
    return jsonify({"success": True})


# ----------------------------------------------------------------------
# Usuarios (RF-01): solo admin
# ----------------------------------------------------------------------
@bp.route("/admin/users")
@permission_required("users:manage")
def admin_users():
    return render_template("admin_users.html", active_tab="users", users=store.available_users,
                           clients=store.clients)


@bp.route("/admin/users/new", methods=["POST"])
@permission_required("users:manage")
def admin_new_user():
    f = request.form
    data = dict(name=f.get("name", ""), email=f.get("email", ""),
                role=f.get("role", "client"), department=f.get("department", ""),
                avatar=f.get("avatar", ""), client_id=f.get("client_id") or None,
                password=f.get("password", ""))
    result = store.create_user(get_current_user(), **data)
    if isinstance(result, dict):
        flash(result["message"], "error")
    else:
        flash(f"Usuario {result.email} creado.", "success")
    return redirect(url_for("main.admin_users"))


@bp.route("/admin/users/<user_id>/edit", methods=["POST"])
@permission_required("users:manage")
def admin_edit_user(user_id):
    f = request.form
    changes = {k: f[k] for k in ("name", "email", "role", "department", "client_id") if f.get(k)}
    result = store.update_user(get_current_user(), user_id, **changes)
    if isinstance(result, dict):
        flash(result["message"], "error")
    elif result is None:
        flash("Usuario no encontrado.", "error")
    else:
        flash("Usuario actualizado.", "success")
    return redirect(url_for("main.admin_users"))


@bp.route("/admin/users/<user_id>/password", methods=["POST"])
@permission_required("users:manage")
def admin_reset_password(user_id):
    result = store.reset_user_password(get_current_user(), user_id, request.form.get("password", ""))
    flash(result["message"], "success" if result["success"] else "error")
    return redirect(url_for("main.admin_users"))


@bp.route("/admin/users/<user_id>/delete", methods=["POST"])
@permission_required("users:manage")
def admin_delete_user(user_id):
    result = store.deactivate_user(get_current_user(), user_id)
    flash(result["message"], "success" if result["success"] else "error")
    return redirect(url_for("main.admin_users"))


@bp.route("/promotions/<promo_id>/toggle", methods=["POST"])
@permission_required("promotions:toggle")
def toggle_promotion(promo_id):
    store.toggle_promotion_status(promo_id)
    return redirect(url_for("main.promotions"))


@bp.route("/promotions/new", methods=["POST"])
@permission_required("promotions:create")
def new_promotion():
    f = request.form
    store.add_promotion(
        get_current_user(), code=f.get("code", "").strip().upper(),
        discount_percentage=float_field(f, "discount_percentage"),
        max_uses=int_field(f, "max_uses", 0, minimum=0), active=True,
        applicable_categories=[c.strip() for c in f.get("applicable_categories", "Todos").split(",") if c.strip()],
        valid_until=f.get("valid_until", ""),
    )
    return redirect(url_for("main.promotions"))


@bp.route("/api/promo/preview", methods=["POST"])
@permission_required("promotions:apply")
def preview_promo():
    data = request.get_json(force=True, silent=True) or {}
    result = store.apply_promo_code(data.get("code", ""), float(data.get("total", 0) or 0))
    return jsonify(result)


# ----------------------------------------------------------------------
# Documentos (RF-17)
# ----------------------------------------------------------------------
@bp.route("/documents/new", methods=["POST"])
@permission_required("documents:create")
def new_document():
    f = request.form
    user = get_current_user()
    # Un cliente sube documentos a su propio expediente, nunca al de otro (IDOR).
    if user.role == "client":
        client = client_record(user)
        if client is None:
            flash("No tienes un perfil de cliente asociado. Contacta a la agencia.", "error")
            return redirect(url_for("main.client_portal"))
    else:
        client = store.get_client(f.get("client_id", ""))
    store.add_document(
        user, client_id=client.id if client else "", client_name=client.name if client else "N/A",
        doc_type=f.get("doc_type", "Voucher de Reserva"), document_number=f.get("document_number", ""),
        file_name=f.get("file_name") or f"{f.get('doc_type', 'Documento')}_{f.get('document_number', '')}.pdf",
        file_size="1.1 MB", expiry_date=f.get("expiry_date", ""), status="Válido",
    )
    return redirect(url_for("main.documents"))


@bp.route("/documents/<doc_id>/delete", methods=["POST"])
@permission_required("documents:delete")
def delete_document(doc_id):
    """Elimina un documento. Solo administradores (RN-04).

    La comprobación vive en la ruta; ``store.delete_document`` todavía acepta
    empleados y su validación se refuerza en la fase P3.
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
    store.predictive_data = result
    store.persist()
    store.log_action(get_current_user().id, get_current_user().name, "EJECUCIÓN_PREDICCIÓN_IA",
                      "Motor IA Predictivo", f"Análisis de comportamiento de compra generado para periodo: {timeframe}")
    store.add_notification("Estadísticas Predictivas Actualizadas",
                            "El motor de Inteligencia Artificial completó la predicción de demanda y propensión de compra.",
                            "success", "ai-predictive")
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
    return jsonify({"success": True, "data": result})


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
    google_bp_enabled = True


@bp.route("/login/google")
def google_login():
    if google is None or not google_bp_enabled:
        flash("El acceso con Google no está configurado.", "error")
        return redirect(url_for("main.login"))
    return redirect(url_for("main.google.login"))


def _find_or_create_client_session(email: str, name: str, avatar: str | None = None) -> UserSession:
    """Crea (o reutiliza) la sesión de cliente para el correo de Google."""
    existing = next((u for u in store.available_users if u.email.lower() == email.lower()), None)
    if existing:
        if avatar:
            existing.avatar = avatar
        return existing
    user = UserSession(
        id=new_id("usr-g"),
        name=f"{name} (Cliente Viajero)",
        email=email,
        role="client",
        department="Cliente Registrado",
        avatar=avatar or "",
        google_id=email,
    )
    store.available_users.append(user)
    if not any(c.email.lower() == email.lower() for c in store.clients):
        store.clients.append(Client(
            id=new_id("cli"),
            name=name,
            email=email,
            phone="+1 (000) 000-0000",
            document_id=f"GGL-{email}",
            category="Estándar",
            status="Activo",
            trips_count=0,
            total_spent=0,
            registration_date=date.today().isoformat(),
            preferred_destinations=[],
            avatar=avatar or "",
        ))
    store.persist()
    return user


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
        flash("No se pudo leer tu información de Google.", "error")
        return redirect(url_for("main.login"))
    email = data.get("email", "")
    if not email:
        flash("El correo de Google no está disponible.", "error")
        return redirect(url_for("main.login"))
    name = data.get("name", email.split("@")[0])
    user = _find_or_create_client_session(email, name, avatar=data.get("picture"))
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
@bp.route("/payments/<payment_id>/ncf", methods=["GET"])
@permission_required("payments:invoice")
def payment_ncf(payment_id):
    """NCF de un pago. Autorización y propiedad ya comprobadas; la emisión
    real del NCF secuencial y persistente es de la fase P4 (ver P4 punto 2)."""
    user = get_current_user()
    payment = find_payment(payment_id)
    owned_or_404(user, payment)
    return not_implemented_yet("La emisión del NCF")


@bp.route("/payments/<payment_id>/factura", methods=["GET"])
@permission_required("payments:invoice")
def payment_factura(payment_id):
    """Factura PDF de un pago. Autorización y propiedad ya comprobadas; el
    PDF real (emisor desde configuración, ítems, NCF) es de la fase P4."""
    user = get_current_user()
    payment = find_payment(payment_id)
    owned_or_404(user, payment)
    return not_implemented_yet("La factura en PDF")


# ----------------------------------------------------------------------
# Manejo de errores
# ----------------------------------------------------------------------
