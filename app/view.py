"""Vista filtrada del ``DataStore`` para las plantillas y para el navegador.

Motivo (invariante de AGENTS.md): *ninguna respuesta a un cliente contiene datos
de otros clientes*. Las plantillas y ``window.DDN_DATA`` acceden al store a través
de ``StoreView``, que entrega cada colección ya filtrada según el rol y la
propiedad, en lugar de exponer el store crudo.

Reglas aplicadas (matriz de ``app/permissions.py``):

- ``admin`` y ``employee``: gestión de toda la agencia, ven todo el store.
- ``client``:
    - ``clients``, ``bookings``, ``payments`` y ``documents``: solo los suyos.
    - ``packages``, ``destinations``, ``activities``: catálogo público.
    - ``hotels``, ``flights``, ``transports``: vacíos (uso interno).
    - ``audit_logs``, ``promotions``, ``available_users``: vacíos.
    - ``notifications``: solo las dirigidas a su correo.

Las mutaciones **no** pasan por aquí: las rutas siguen llamando al ``store`` real
(``app.store.store``), que es la única capa que escribe.
"""
from __future__ import annotations

from .permissions import get_current_user, own_records

# Colecciones públicas del catálogo que un cliente puede consultar (matriz).
CATALOGO_PUBLICO = ("packages", "destinations", "activities")
# Colecciones de uso interno que un cliente no debe ver en ningún caso.
SOLO_INTERNO = ("hotels", "flights", "transports", "audit_logs",
                "promotions", "available_users", "predictive_data")
# Colecciones con datos personales: se filtran por propiedad.
CON_DATOS_PERSONALES = ("clients", "bookings", "payments", "documents")


class StoreView:
    """Envoltorio de solo lectura que filtra el store según el usuario actual."""

    def __init__(self, store, user=None):
        self._store = store
        self._user = user

    # -- contexto ------------------------------------------------------
    @property
    def user(self):
        return self._user

    def _es_cliente(self) -> bool:
        return self._user is not None and self._user.role == "client"

    # -- colecciones con datos personales ------------------------------
    @property
    def clients(self) -> list:
        if not self._es_cliente():
            return self._store.clients
        return own_records(self._user, self._store.clients)

    @property
    def bookings(self) -> list:
        if not self._es_cliente():
            return self._store.bookings
        return own_records(self._user, self._store.bookings)

    @property
    def payments(self) -> list:
        if not self._es_cliente():
            return self._store.payments
        return own_records(self._user, self._store.payments)

    @property
    def documents(self) -> list:
        if not self._es_cliente():
            return self._store.documents
        return own_records(self._user, self._store.documents)

    # -- notificaciones ------------------------------------------------
    @property
    def notifications(self) -> list:
        if not self._es_cliente():
            return self._store.notifications
        email = (getattr(self._user, "email", "") or "").lower()
        propias = [n for n in self._store.notifications
                   if (getattr(n, "target_email", "") or "").lower() == email]
        return propias

    # -- delegate ------------------------------------------------------
    def __getattr__(self, name):
        """Delega en el store real, incluidas las mutaciones y los getters."""
        if name in CON_DATOS_PERSONALES or name in SOLO_INTERNO or name in CATALOGO_PUBLICO:
            if name in SOLO_INTERNO and self._es_cliente():
                # Sin sesión de cliente: nunca se entregan datos internos.
                return []
            return getattr(self._store, name)
        return getattr(self._store, name)

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        rol = getattr(self._user, "role", None)
        return f"<StoreView rol={rol!r}>"


def store_view(store=None, user=None) -> StoreView:
    """Devuelve la vista filtrada del store para el usuario indicado.

    Si no se indica usuario, se toma el de la sesión; si no hay sesión, la vista
    es la más restrictiva (catálogo público y ninguna colección interna).
    """
    from .store import store as store_real
    return StoreView(store or store_real, user if user is not None else get_current_user())
