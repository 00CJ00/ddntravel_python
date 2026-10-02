"""Pruebas de la auditoría RN-05 (fase P2, paso 4).

Verifican que ``audit.record`` participa en la transacción abierta (no confirma
por sí solo), que las mutaciones dejan ``before``/``after``, que la IP es la real
de la petición y que login/logout/fallo y el reset se auditan correctamente.
"""
from __future__ import annotations

from conftest import ADMIN_EMAIL, DEMO_PASSWORD

from app import audit
from app import models as m
from app.extensions import db


def _admin(store):
    return next(u for u in store.available_users if u.email == ADMIN_EMAIL)


def _ultimo(action):
    return (db.session.query(m.AuditLog)
            .filter(m.AuditLog.action == action)
            .order_by(m.AuditLog.id.desc())
            .first())


def test_record_no_confirma_por_si_solo(app, store):
    """``audit.record`` deja la fila pendiente; sin commit no persiste."""
    base = db.session.query(m.AuditLog).count()
    audit.record("EVENTO_PRUEBA", "Pruebas", details="sin mutación")
    assert any(isinstance(obj, m.AuditLog) for obj in db.session.new)

    db.session.rollback()
    assert db.session.query(m.AuditLog).count() == base


def test_mutacion_registra_before_y_after(store):
    """Editar un cliente deja auditoría con el estado previo y el posterior."""
    admin = _admin(store)
    client = store.clients[0]
    antes = client.name
    store.update_client(admin, client.id, name="Nombre Auditado")

    db.session.expire_all()
    log = _ultimo("MODIFICAR_CLIENTE")
    assert log is not None
    assert log.entity_type == "Client"
    assert log.entity_id == str(client.id)
    assert log.before["name"] == antes
    assert log.after["name"] == "Nombre Auditado"
    assert log.user_id == admin.id
    assert log.user_role == "admin"


def test_ip_real_de_la_peticion(client, login_as, post_csrf, store):
    """La IP de auditoría es ``request.remote_addr``, no un valor aleatorio."""
    login_as(client, ADMIN_EMAIL)
    promo = store.promotions[0]
    res = post_csrf(client, f"/promotions/{promo.id}/toggle")
    assert res.status_code in (200, 302)

    log = _ultimo("CAMBIAR_ESTADO_PROMOCION")
    assert log is not None
    assert log.ip_address == "127.0.0.1"


def test_login_logout_y_fallo_se_auditan(client, post_csrf):
    post_csrf(client, "/login", {"email": ADMIN_EMAIL, "password": DEMO_PASSWORD})
    assert _ultimo("INICIO_SESION") is not None

    post_csrf(client, "/logout")
    assert _ultimo("CIERRE_SESION") is not None

    post_csrf(client, "/login", {"email": "nadie@example.com", "password": "mala"})
    fallido = _ultimo("INICIO_SESION_FALLIDO")
    assert fallido is not None
    assert fallido.user_name == "nadie@example.com"


def test_reset_no_borra_la_auditoria(store):
    """El reset de desarrollo conserva el historial (AuditLog solo inserción)."""
    admin = _admin(store)
    store.add_client(admin, name="Cliente Temporal", email="temporal@example.com",
                     phone="+1 000", document_id="TMP-1", category="Estándar")
    creado = _ultimo("CREAR_CLIENTE")
    assert creado is not None
    total_antes = db.session.query(m.AuditLog).count()

    db.session.expunge_all()
    store.reset_all_data()

    db.session.expire_all()
    total_despues = db.session.query(m.AuditLog).count()
    assert total_despues >= total_antes
    assert _ultimo("CREAR_CLIENTE") is not None
    assert _ultimo("RESET_DATOS") is not None
