"""
Matriz de permisos de DDN Travel: única fuente de verdad de la autorización.

Este módulo reemplaza a los ``@role_required`` dispersos por las rutas. Dos
conceptos separados, a propósito:

1. **Permiso** (este módulo, ``PERMISSIONS``): qué roles pueden acceder a una
   funcionalidad. Se declara como dato y se expone con ``can()`` para que las
   plantillas oculten botones, y con ``permission_required()`` en las rutas.
2. **Propiedad** (``owns``): si un registro concreto pertenece al usuario en
   sesión. Un cliente puede tener el permiso "cancelar reservas" pero solo
   sobre las suyas, y solo si están Pendientes.

La matriz aplica el documento de requerimientos (roles de la sección 6) y las
decisiones tomadas para la fase P1:

| Acción                                     | admin | employee | client          |
|--------------------------------------------|:-----:|:--------:|:---------------:|
| Dashboard / reportes                       |  sí   |    sí    |      no         |
| Auditoría (ver)                            |  sí   |    no     |      no         |
| Clientes: ver / crear / editar             |  sí   |    sí     | solo su perfil  |
| Clientes: eliminar                         |  sí   |    no     |      no         |
| Catálogo: ver paquetes/destinos/actividades|  sí   |    sí     |      sí         |
| Catálogo: ver hoteles/vuelos/transporte    |  sí   |    sí     |      no         |
| Catálogo: crear / editar / eliminar        |  sí   |    no     |      no         |
| Reservas: ver / crear / estado             |  sí   |    sí     | crear solo suya |
| Reservas: cancelar                         |  sí   |    sí     | la suya, Pendiente |
| Pagos: registrar                           |  sí   |    sí     |      no         |
| Pagos: anular / reembolsar                  |  sí   |    no     |      no         |
| Factura de un pago                         |  sí   |    sí     | solo la suya    |
| Promociones: ver / aplicar código          |  sí   |    sí     |      sí         |
| Promociones: crear / activar               |  sí   |    no     |      no         |
| Documentos: ver / subir                    |  sí   |    sí     | solo los suyos  |
| Documentos: eliminar                       |  sí   |    no     |      no         |
| Usuarios: CRUD                             |  sí   |    no     |      no         |
| IA predictiva (consultar)                  |  sí   |    sí     |      sí         |
| IA predictiva (ejecutar análisis)         |  sí   |    sí     |      no         |
| IA recomendaciones / itinerarios           |  sí   |    sí     |      sí         |
| Restablecer datos                          |  sí   |    no     |      no         |
"""
from __future__ import annotations

from functools import wraps

from flask import abort, redirect, session, url_for

from . import store as store_module
from .models import Booking, Client, PaymentTransaction, TravelDocument

ROLES = ("admin", "employee", "client")

# Roles con acceso a la operación interna de la agencia.
STAFF_ROLES = frozenset({"admin", "employee"})

#: Matriz de permisos: permiso -> roles autorizados. Única fuente de verdad.
PERMISSIONS: dict[str, frozenset[str]] = {
    # --- Dashboard y reportes (RF-14) ---
    "dashboard:view": STAFF_ROLES,
    "reports:view": STAFF_ROLES,
    "audit:view": frozenset({"admin"}),

    # --- Perfil y usuarios (RF-01) ---
    "profile:edit": frozenset({"admin", "employee", "client"}),
    "users:manage": frozenset({"admin"}),

    # --- Clientes (RF-03) ---
    "clients:view": STAFF_ROLES,
    "clients:create": STAFF_ROLES,
    "clients:edit": STAFF_ROLES,
    "clients:delete": frozenset({"admin"}),

    # --- Catálogo (RF-04, RF-05, RF-07, RF-08, RF-09, RF-18) ---
    "catalog:view_packages": frozenset({"admin", "employee", "client"}),
    "catalog:view_destinations": frozenset({"admin", "employee", "client"}),
    "catalog:view_activities": frozenset({"admin", "employee", "client"}),
    "catalog:view_hotels": STAFF_ROLES,
    "catalog:view_flights": STAFF_ROLES,
    "catalog:view_transports": STAFF_ROLES,
    "catalog:create": frozenset({"admin"}),
    "catalog:edit": frozenset({"admin"}),
    "catalog:delete": frozenset({"admin"}),

    # --- Reservas (RF-06, RN-01 a RN-03) ---
    "bookings:view": STAFF_ROLES,
    "bookings:create": frozenset({"admin", "employee", "client"}),
    "bookings:edit": STAFF_ROLES,
    "bookings:status": STAFF_ROLES,
    "bookings:cancel": frozenset({"admin", "employee", "client"}),

    # --- Pagos y facturación (RF-11, RN-03) ---
    "payments:view": STAFF_ROLES,
    "payments:create": STAFF_ROLES,
    "payments:void": frozenset({"admin"}),
    "payments:invoice": frozenset({"admin", "employee", "client"}),

    # --- Promociones (RF-12) ---
    "promotions:view": STAFF_ROLES,
    "promotions:apply": frozenset({"admin", "employee", "client"}),
    "promotions:create": frozenset({"admin"}),
    "promotions:toggle": frozenset({"admin"}),

    # --- Documentos (RF-17) ---
    "documents:view": frozenset({"admin", "employee", "client"}),
    "documents:create": frozenset({"admin", "employee", "client"}),
    "documents:delete": frozenset({"admin"}),

    # --- Inteligencia artificial (RF-20) ---
    "ai:predictive_view": frozenset({"admin", "employee", "client"}),
    "ai:predictive_run": STAFF_ROLES,
    "ai:recommend": frozenset({"admin", "employee", "client"}),
    "ai:itinerary": frozenset({"admin", "employee", "client"}),

    # --- Portal y varios ---
    "portal:view": frozenset({"client"}),
    "theme:set": frozenset({"admin", "employee", "client"}),
    "notifications:read": frozenset({"admin", "employee", "client"}),
    "profile:callback": frozenset({"client"}),

    # --- Datos de demostración (protegido además por ENABLE_RESET) ---
    "data:reset": frozenset({"admin"}),
    "session:logout": frozenset({"admin", "employee", "client"}),
}

#: Endpoints accesibles sin sesión (públicos por diseño).
PUBLIC_ENDPOINTS = frozenset({
    "main.login",
    "main.health",
    "main.contact",
    "main.chat_message",
    "main.set_theme",
    "main.google_login",
    "main.google_authorized",
    "google.login",
    "google.authorized",
})

#: Endpoint -> permiso requerido. Debe cubrir TODAS las rutas de la aplicación;
#: ``tests/test_permissions.py`` falla si alguna queda fuera.
ENDPOINT_PERMISSIONS: dict[str, str] = {
    "main.index": "dashboard:view",
    "main.login": "session:logout",  # público: se ignora por estar en PUBLIC_ENDPOINTS
    "main.logout": "session:logout",
    "main.dashboard": "dashboard:view",
    "main.ai_predictive": "ai:predictive_view",
    "main.bookings": "bookings:view",
    "main.clients": "clients:view",
    "main.packages": "catalog:view_packages",
    "main.destinations": "catalog:view_destinations",
    "main.admin_add_destination": "catalog:create",
    "main.admin_edit_destination": "catalog:edit",
    "main.hotels": "catalog:view_hotels",
    "main.flights": "catalog:view_flights",
    "main.transports": "catalog:view_transports",
    "main.activities": "catalog:view_activities",
    "main.payments": "payments:view",
    "main.promotions": "promotions:view",
    "main.documents": "documents:view",
    "main.audit": "audit:view",
    "main.client_portal": "portal:view",
    "main.set_theme": "theme:set",
    "main.edit_profile": "profile:edit",
    "main.reset_data": "data:reset",
    "main.read_notification": "notifications:read",
    "main.read_all_notifications": "notifications:read",
    "main.new_client": "clients:create",
    "main.new_booking": "bookings:create",
    "main.cancel_booking": "bookings:cancel",
    "main.update_booking_status": "bookings:status",
    "main.new_payment": "payments:create",
    "main.new_promotion": "promotions:create",
    "main.toggle_promotion": "promotions:toggle",
    "main.preview_promo": "promotions:apply",
    "main.new_document": "documents:create",
    "main.delete_document": "documents:delete",
    "main.api_predictive_analytics": "ai:predictive_run",
    "main.api_recommendations": "ai:recommend",
    "main.api_generate_itinerary": "ai:itinerary",
    "main.health": "dashboard:view",  # público: se ignora por estar en PUBLIC_ENDPOINTS
    "main.google_login": "profile:edit",
    "main.google_authorized": "profile:edit",
    "main.contact": "profile:callback",
    "main.request_callback": "profile:callback",
    "main.chat_message": "ai:recommend",
    "main.payment_ncf": "payments:invoice",
    "main.payment_factura": "payments:invoice",
}


# ----------------------------------------------------------------------
# Sesión y consulta de permisos
# ----------------------------------------------------------------------
def get_store():
    """Devuelve el DataStore activo.

    Se resuelve en cada llamada a propósito, para que las pruebas puedan aislar
    el estado sustituyendo la instancia del módulo ``app.store``.
    """
    return store_module.store


def get_current_user():
    """Devuelve el usuario de la sesión actual o ``None`` si no hay sesión."""
    user_id = session.get("user_id")
    return get_store().get_user(user_id) if user_id else None


def can(permission: str, user=None) -> bool:
    """Indica si el usuario (por defecto, el de la sesión) tiene el permiso.

    Se expone como global de Jinja para ocultar botones y enlaces que el
    usuario no puede usar, sin sustituir la validación del servidor.
    """
    user = get_current_user() if user is None else user
    if user is None:
        return False
    roles = PERMISSIONS.get(permission)
    if roles is None:
        raise KeyError(f"Permiso no declarado en la matriz: {permission!r}")
    return user.role in roles


def roles_with(permission: str) -> frozenset[str]:
    """Devuelve los roles autorizados para un permiso."""
    try:
        return PERMISSIONS[permission]
    except KeyError as exc:  # pragma: no cover - error de programación
        raise KeyError(f"Permiso no declarado en la matriz: {permission!r}") from exc


# ----------------------------------------------------------------------
# Decoradores
# ----------------------------------------------------------------------
def login_required(fn):
    """Exige sesión iniciada; si no hay, redirige al login."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if get_current_user() is None:
            return redirect(url_for("main.login"))
        return fn(*args, **kwargs)
    return wrapper


def permission_required(permission: str):
    """Exige sesión y el permiso indicado. 302 al login sin sesión, 403 sin permiso."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if user is None:
                return redirect(url_for("main.login"))
            if not can(permission, user):
                abort(403)
            return fn(*args, **kwargs)
        wrapper.required_permission = permission
        return wrapper
    return decorator


# ----------------------------------------------------------------------
# Propiedad de los datos (anti-IDOR)
# ----------------------------------------------------------------------
def client_record(user):
    """Devuelve el registro ``Client`` asociado a un usuario cliente.

    Hasta la fase P2 (migración a base de datos) el vínculo usuario ↔ cliente es
    el correo electrónico; en P2 pasa a ser ``User.client_id``.
    """
    if user is None:
        return None
    email = (getattr(user, "email", "") or "").strip().lower()
    if not email:
        return None
    return next((c for c in get_store().clients if (c.email or "").strip().lower() == email), None)


def owns(user, obj) -> bool:
    """Indica si ``user`` es propietario del registro ``obj``.

    Los roles internos (admin/employee) gestionan toda la agencia, así que
    ``owns`` devuelve ``True`` para ellos. Para el rol ``client`` la propiedad
    se verifica en el servidor, nunca se deduce de la URL ni del formulario.
    """
    if user is None or obj is None:
        return False
    if user.role in STAFF_ROLES:
        return True
    if user.role != "client":
        return False

    client = client_record(user)
    if client is None:
        return False

    if isinstance(obj, Client):
        return obj.id == client.id
    if isinstance(obj, Booking):
        same_email = (getattr(obj, "client_email", "") or "").strip().lower() == \
            (getattr(user, "email", "") or "").strip().lower()
        return obj.client_id == client.id or same_email
    if isinstance(obj, TravelDocument):
        return getattr(obj, "client_id", None) == client.id
    if isinstance(obj, PaymentTransaction):
        booking = get_store().get_booking(obj.booking_id)
        return booking is not None and owns(user, booking)

    client_id = getattr(obj, "client_id", None)
    return client_id is not None and client_id == client.id


def own_records(user, records) -> list:
    """Filtra una lista de registros dejando solo los del usuario."""
    return [r for r in records if owns(user, r)]


def owned_or_404(user, obj):
    """Devuelve el registro si el usuario lo posee; 404 en caso contrario.

    Se responde 404 (y no 403) para no revelar la existencia de registros
    ajenos.
    """
    if obj is None or not owns(user, obj):
        abort(404)
    return obj
