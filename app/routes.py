"""Rutas de la aplicación DDN Travel (equivalente a App.tsx + server.ts)."""
from __future__ import annotations
import os
import datetime
from functools import wraps

from flask import (
    Blueprint, render_template, request, redirect, url_for, session, jsonify,
    abort, flash
)
from werkzeug.security import check_password_hash

from .store import store
from .models import Client, UserSession, new_id
from . import ai_service
from .billing import generar_ncf, generar_pdf_factura, validar_rnc, ultimo_ncf_desde_state

bp = Blueprint("main", __name__)

CLIENT_ALLOWED_TABS = {"client-portal", "packages", "destinations", "ai-predictive", "activities", "documents"}

# Endpoints accesibles sin haber iniciado sesión
LOGIN_EXEMPT = {
    "main.login", "main.logout", "main.health",
    "main.google_login", "main.google_authorized",
    "main.set_theme",
    "main.google.login", "main.google.authorized",
    "main.contact", "main.request_callback", "main.chat_message",
}


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def get_current_user():
    user_id = session.get("user_id")
    return store.get_user(user_id) if user_id else None


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


def role_required(*roles):
    """Restringe una ruta a ciertos roles. Redirige al login si no hay sesión
    y devuelve 403 si el rol actual no está entre los permitidos."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if user is None:
                return redirect(url_for("main.login"))
            if roles and user.role not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


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


@bp.app_context_processor
def inject_globals():
    current_user = get_current_user()
    if current_user is not None:
        visible_notifs = [
            n for n in store.notifications
            if n.visible_roles is None or current_user.role in n.visible_roles
        ]
    else:
        visible_notifs = []
    unread = [n for n in visible_notifs if not n.read]
    client_side_data = {
        "clients": [c.to_dict() for c in store.clients],
        "packages": [p.to_dict() for p in store.packages],
        "hotels": [h.to_dict() for h in store.hotels],
        "flights": [f.to_dict() for f in store.flights],
        "currentUser": current_user.to_dict() if current_user else None,
    }
    return {
        "store": store,
        "current_user": current_user,
        "available_users": store.available_users,
        "theme": session.get("theme", "deep-space"),
        "notifications": visible_notifs,
        "unread_notifications": unread,
        "client_side_data": client_side_data,
    }


# ----------------------------------------------------------------------
# Navegación principal
# ----------------------------------------------------------------------
@bp.route("/")
def index():
    user = get_current_user()
    if user is None:
        return redirect(url_for("main.login"))
    if user.role == "client":
        return redirect(url_for("main.client_portal"))
    return redirect(url_for("main.dashboard"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        f = request.form
        user = next((u for u in store.available_users if u.email.lower() == f.get("email", "").strip().lower()), None)
        if user and getattr(user, "password_hash", None) and check_password_hash(user.password_hash, f.get("password", "")):
            session["user_id"] = user.id
            flash(f"Bienvenido, {user.name.split(' (')[0]}.", "success")
            return redirect(url_for("main.index"))
        error = "Correo o contraseña incorrectos."
    return render_template("login.html", error=error, google_enabled=google_bp_enabled)


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    for key in ("google_token", "google_oauth_state"):
        session.pop(key, None)
    flash("Sesión cerrada correctamente.", "success")
    return redirect(url_for("main.login"))


@bp.route("/dashboard")
@role_required("admin", "employee")
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
@role_required()
def ai_predictive():
    timeframe = request.args.get("timeframe", "Próximos 6 meses (Q3 & Q4)")
    if store.predictive_data is None:
        store.predictive_data = ai_service.get_predictive_analytics(
            store.clients, store.bookings, store.packages, timeframe)
    return render_template("ai_predictive.html", active_tab="ai-predictive",
                            predictive_data=store.predictive_data, timeframe=timeframe)


@bp.route("/bookings")
@role_required("admin", "employee")
def bookings():
    return render_template("bookings.html", active_tab="bookings",
                            bookings=list(reversed(store.bookings)))


@bp.route("/clients")
@role_required("admin", "employee")
def clients():
    return render_template("clients.html", active_tab="clients", clients=store.clients)


@bp.route("/packages")
@role_required()
def packages():
    return render_template("packages.html", active_tab="packages", packages=store.packages,
                            destinations=store.destinations)


@bp.route("/destinations")
@role_required()
def destinations():
    return render_template("destinations.html", active_tab="destinations", destinations=store.destinations)


@bp.route("/admin/destinations", methods=["POST"])
@role_required("admin")
def admin_add_destination():
    data = request.form
    dest = store.add_destination(current_user, **data)
    return jsonify({"success": True, "id": dest.id, "name": dest.name})


@bp.route("/admin/destinations/<dest_id>", methods=["POST"])
@role_required("admin")
def admin_edit_destination(dest_id):
    data = request.form
    dest = store.edit_destination(current_user, dest_id, **data)
    if dest:
        return jsonify({"success": True, "name": dest.name})
    return jsonify({"success": False, "error": "Destino no encontrado"}), 404


@bp.route("/hotels")
@role_required("admin", "employee")
def hotels():
    return render_template("hotels.html", active_tab="hotels", hotels=store.hotels)


@bp.route("/flights")
@role_required("admin", "employee")
def flights():
    return render_template("flights.html", active_tab="flights", flights=store.flights)


@bp.route("/transports")
@role_required("admin", "employee")
def transports():
    return render_template("transports.html", active_tab="transports", transports=store.transports)


@bp.route("/activities")
@role_required()
def activities():
    return render_template("activities.html", active_tab="activities", activities=store.activities)


@bp.route("/payments")
@role_required("admin", "employee")
def payments():
    return render_template("payments.html", active_tab="payments", payments=store.payments,
                            pending_bookings=[b for b in store.bookings if b.payment_status != "Pagado"
                                              and b.status != "Cancelada"])


@bp.route("/promotions")
@role_required("admin", "employee")
def promotions():
    return render_template("promotions.html", active_tab="promotions", promotions=store.promotions)


@bp.route("/documents")
@role_required()
def documents():
    return render_template("documents.html", active_tab="documents", documents=store.documents,
                            clients=store.clients)


@bp.route("/audit")
@role_required("admin")
def audit():
    return render_template("audit.html", active_tab="audit", logs=store.audit_logs)


@bp.route("/client-portal")
@role_required("client")
def client_portal():
    user = get_current_user()
    my_bookings = [b for b in store.bookings if b.client_email == user.email]
    return render_template("client_portal.html", active_tab="client-portal", my_bookings=my_bookings,
                            packages=store.packages[:4])


# ----------------------------------------------------------------------
# Sesión: usuario / tema / reset
# ----------------------------------------------------------------------
@bp.route("/switch-user", methods=["POST"])
def switch_user():
    user_id = request.form.get("user_id")
    session["user_id"] = user_id
    user = store.get_user(user_id)
    if user and user.role == "client":
        return redirect(url_for("main.client_portal"))
    return redirect(url_for("main.dashboard"))


@bp.route("/set-theme/<theme>", methods=["POST"])
def set_theme(theme):
    session["theme"] = "light" if theme == "light" else "deep-space"
    user = get_current_user()
    default_endpoint = "main.client_portal" if user and user.role == "client" else "main.dashboard"
    return redirect_back(default_endpoint)


@bp.route("/edit-profile", methods=["GET", "POST"])
def edit_profile():
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("main.login"))

    # Determine which client record to edit
    client = None
    if current_user.role == "client":
        # Find the client associated with this user session
        client = next((c for c in store.clients if c.email == current_user.email), None)
    else:
        # Admin/employee: pick client from form or first active client
        client_id = request.form.get("client_id") if request.method == "POST" else None
        if client_id:
            client = store.get_client(client_id)
        if not client:
            client = store.clients[1] if len(store.clients) > 1 else store.clients[0]

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

    # GET: show the form with current data
    return render_template("edit_profile.html", current_user=current_user,
                           client=client, available_users=store.available_users,
                           is_admin=current_user.role in ("admin", "employee"))


@bp.route("/reset", methods=["POST"])
def reset_data():
    store.reset_all_data()
    session.pop("user_id", None)
    return redirect(url_for("main.dashboard"))


@bp.route("/notifications/<notif_id>/read", methods=["POST"])
def read_notification(notif_id):
    store.mark_notification_as_read(notif_id)
    return redirect_back("main.dashboard")


@bp.route("/notifications/read-all", methods=["POST"])
def read_all_notifications():
    store.mark_all_notifications_as_read()
    return redirect_back("main.dashboard")


# ----------------------------------------------------------------------
# Clientes
# ----------------------------------------------------------------------
@bp.route("/clients/new", methods=["POST"])
def new_client():
    f = request.form
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
def new_booking():
    f = request.form
    current_user = get_current_user()
    client = store.get_client(f.get("client_id", ""))
    package = store.get_package(f.get("package_id", "")) if f.get("package_id") else None
    hotel = store.get_hotel(f.get("hotel_id", "")) if f.get("hotel_id") else None
    flight = store.get_flight(f.get("flight_id", "")) if f.get("flight_id") else None
    travelers = int_field(f, "travelers", 1, minimum=1, maximum=10)

    if not client:
        return render_template("bookings.html", active_tab="bookings", bookings=list(reversed(store.bookings)),
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
        promo_result = store.apply_promo_code(promo_code, raw_total)
        if promo_result["valid"]:
            discounted_total = promo_result["final_price"]
            promo_note = f" [Cupón: {promo_code.upper()} - {promo_result['discount_percentage']}%]"

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
    )

    if not result["success"]:
        flash(result["message"], "error")
        return render_template("bookings.html", active_tab="bookings", bookings=list(reversed(store.bookings)),
                                error=result["message"])
    flash(result["message"], "success")
    return redirect(url_for("main.bookings"))


@bp.route("/bookings/<booking_id>/cancel", methods=["POST"])
def cancel_booking(booking_id):
    store.cancel_booking(get_current_user(), booking_id, request.form.get("reason", ""))
    return redirect_back("main.bookings")


@bp.route("/bookings/<booking_id>/status", methods=["POST"])
def update_booking_status(booking_id):
    store.update_booking_status(get_current_user(), booking_id, request.form.get("status", "Pendiente"))
    return redirect_back("main.bookings")


# ----------------------------------------------------------------------
# Pagos (RF-11, RN-03)
# ----------------------------------------------------------------------
@bp.route("/payments/new", methods=["POST"])
def new_payment():
    f = request.form
    result = store.register_payment(
        get_current_user(), f.get("booking_id", ""),
        float_field(f, "amount"), f.get("payment_method", "Tarjeta de Crédito"),
        f.get("reference", ""))
    flash(result.get("message", "Pago registrado."), "success" if result.get("success") else "error")
    # Generación automática de NCF si el pago no tiene uno aún
    if result.get("success") and result.get("payment"):
        payment = result.get("payment")  # PaymentTransaction object
        if not payment.is_ncf_generated():
            estado = store.state if hasattr(store, 'state') else {}
            ultimo = ultimo_ncf_desde_state(estado)
            nuevo_ncf = generar_ncf("A", ultimo)
            payment.ncf = nuevo_ncf
            estado["ultimo_ncf"] = nuevo_ncf
            store.persist()
    return redirect(url_for("main.payments"))


# ----------------------------------------------------------------------
# Promociones (RF-12)
# ----------------------------------------------------------------------
@bp.route("/promotions/new", methods=["POST"])
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


@bp.route("/promotions/<promo_id>/toggle", methods=["POST"])
def toggle_promotion(promo_id):
    store.toggle_promotion_status(promo_id)
    return redirect(url_for("main.promotions"))


@bp.route("/api/promo/preview", methods=["POST"])
def preview_promo():
    data = request.get_json(force=True, silent=True) or {}
    result = store.apply_promo_code(data.get("code", ""), float(data.get("total", 0) or 0))
    return jsonify(result)


# ----------------------------------------------------------------------
# Documentos (RF-17)
# ----------------------------------------------------------------------
@bp.route("/documents/new", methods=["POST"])
def new_document():
    f = request.form
    client = store.get_client(f.get("client_id", ""))
    store.add_document(
        get_current_user(), client_id=client.id if client else "", client_name=client.name if client else "N/A",
        doc_type=f.get("doc_type", "Voucher de Reserva"), document_number=f.get("document_number", ""),
        file_name=f.get("file_name") or f"{f.get('doc_type', 'Documento')}_{f.get('document_number', '')}.pdf",
        file_size="1.1 MB", expiry_date=f.get("expiry_date", ""), status="Válido",
    )
    return redirect(url_for("main.documents"))


@bp.route("/documents/<doc_id>/delete", methods=["POST"])
def delete_document(doc_id):
    store.delete_document(get_current_user(), doc_id)
    return redirect(url_for("main.documents"))


# ----------------------------------------------------------------------
# API de Inteligencia Artificial (RF-20) — igual que server.ts
# ----------------------------------------------------------------------
@bp.route("/api/ai/predictive-analytics", methods=["POST"])
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
def api_recommendations():
    data = request.get_json(force=True, silent=True) or {}
    result = ai_service.get_recommendations(
        data.get("clientProfile", {}) or {}, data.get("budget", 2500), data.get("travelStyle", ""),
        data.get("travelersCount", 2), data.get("interests", ""),
    )
    return jsonify({"success": True, "data": result})


@bp.route("/api/ai/generate-itinerary", methods=["POST"])
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
            registration_date=datetime.date.today().isoformat(),
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
def contact():
    if request.method == "POST":
        f = request.form
        store.log_action(
            "public", "Visitante Web", "CONTACT_FORM",
            "Contacto", f"Mensaje de {f.get('name')} ({f.get('email')}): {f.get('subject')}"
        )
        store.add_notification(
            "Nuevo mensaje de contacto",
            f"{f.get('name')} ({f.get('email')}) - {f.get('subject')}: {f.get('message')[:120]}...",
            "info", "contact"
        )
        flash("¡Gracias! Tu mensaje ha sido enviado. Te responderemos en menos de 24 horas.", "success")
        return redirect(url_for("main.contact"))
    return render_template("contact.html", faqs=FAQS)


@bp.route("/contacto/callback", methods=["POST"])
@role_required("client")
def request_callback():
    f = request.form
    reason = f.get("reason", "").strip()
    phone = f.get("phone", "").strip()
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
def chat_message():
    data = request.get_json(force=True, silent=True) or {}
    user_msg = (data.get("message") or "").strip().lower()
    if not user_msg:
        return jsonify({"reply": "Escribe algo para que pueda ayudarte.", "faq": False})
    for faq in FAQS:
        keywords = faq["question"].lower().split()
        if any(kw in user_msg for kw in keywords if len(kw) > 3):
            return jsonify({"reply": faq["answer"], "faq": True, "matched": faq["question"]})
    if any(w in user_msg for w in ["hola", "buenas", "hello", "hi"]):
        return jsonify({"reply": "¡Hola! 👋 Soy el asistente virtual de DDN Travel. ¿En qué puedo ayudarte hoy? Puedes preguntarme sobre reservas, pagos, documentos, seguros, itinerarios...", "faq": False})
    if any(w in user_msg for w in ["gracias", "thanks", "thx"]):
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
@role_required("admin", "employee")
def payment_ncf(payment_id):
    """Endpoint para obtener o generar el NCF de un pago."""
    payment = store.get_payment(payment_id)
    if not payment:
        return "Pago no encontrado", 404
    # Si no tiene NCF, lo generamos secuencialmente
    if not payment.is_ncf_generated():
        estado = store.state if hasattr(store, 'state') else {}
        ultimo = ultimo_ncf_desde_state(estado)
        nuevo_ncf = generar_ncf("A", ultimo)
        payment.ncf = nuevo_ncf
        # Guardamos el último NCF usado en el state global
        if "ultimo_ncf" not in estado:
            estado["ultimo_ncf"] = nuevo_ncf
        store.persist()
    return jsonify({
        "ncf": payment.ncf,
        "generado": not bool(ultimo) if 'ultimo' in (store.state or {}) else True,
        "fecha": date.today().isoformat()
    })


@bp.route("/payments/<payment_id>/factura", methods=["GET"])
@role_required("admin", "employee")
def payment_factura(payment_id):
    """Descarga la factura PDF asociada a un pago."""
    payment = store.get_payment(payment_id)
    if not payment or not payment.is_ncf_generated():
        flash("Este pago no tiene NCF generado todavía.", "error")
        return redirect(url_for("main.payments"))
    # Datos para el PDF (usar datos reales de la reserva asociada)
    items = [
        {"description": f"Reserva #{payment.booking_code}", "quantity": 1, "price": payment.total_price or 0},
    ]
    pdf_bytes = generar_pdf_factura(
        titulo="Factura DDN Travel",
        rnc_emitter="J302010123",  # RNC de la agencia (ejemplo dominicano)
        nombre_emitter="DDN Travel Tours",
        rnc_client=payment.client_email or "—",
        nombre_client=payment.client_name or "—",
        items=items,
        total=payment.total_price or 0,
        ncf=payment.ncf,
        fecha=payment.creation_date or date.today().isoformat(),
    )
    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"Factura_NCF-{payment.ncf}.pdf"
    )


# ----------------------------------------------------------------------
# Manejo de errores
# ----------------------------------------------------------------------
