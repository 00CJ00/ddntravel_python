"""Pruebas de resiliencia, auditoría y contrato de IA (RF-20) — Fase P6."""
import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from conftest import ADMIN_EMAIL, read_csrf_token

from app import ai_service
from app import models as m


def test_respuesta_gemini_completa_claves_y_tipos_desde_el_esquema(monkeypatch):
    class Models:
        @staticmethod
        def generate_content(**_kwargs):
            return SimpleNamespace(text=json.dumps({
                "summary": 42,
                "score": "inválido",
                "segments": [{"segment": "Familias"}],
                "ignored": "no debe conservarse",
            }))

    monkeypatch.setattr(
        ai_service,
        "_get_client",
        lambda: SimpleNamespace(models=Models()),
    )
    monkeypatch.setattr(
        ai_service,
        "genai_types",
        SimpleNamespace(GenerateContentConfig=lambda **kwargs: kwargs),
    )
    defaults = {
        "summary": "Resumen de respaldo",
        "score": 86,
        "segments": [{"segment": "VIP", "propensity": 90}],
        "insights": ["Insight predeterminado"],
    }

    result = ai_service.generate_gemini_json(
        "prompt", lambda: defaults.copy(), validate=True)

    assert result == {
        "summary": "Resumen de respaldo",
        "score": 86,
        "segments": [{"segment": "Familias", "propensity": 90}],
        "insights": ["Insight predeterminado"],
    }


def test_cliente_gemini_configura_timeout(monkeypatch):
    captured = {}
    fake_client = object()
    monkeypatch.setattr(ai_service, "_client", None)
    monkeypatch.setattr(ai_service, "genai", SimpleNamespace(
        Client=lambda **kwargs: captured.update(kwargs) or fake_client))
    monkeypatch.setattr(ai_service, "genai_types", SimpleNamespace(
        HttpOptions=lambda **kwargs: kwargs))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    result = ai_service._get_client()

    assert result is fake_client
    assert captured["http_options"] == {"timeout": ai_service.GEMINI_TIMEOUT_MS}


def test_cliente_reintenta_una_falla_de_timeout(monkeypatch):
    calls = []

    class Models:
        @staticmethod
        def generate_content(**_kwargs):
            calls.append(True)
            if len(calls) == 1:
                raise TimeoutError("request timed out")
            return SimpleNamespace(text='{"summary":"respuesta válida"}')

    monkeypatch.setattr(
        ai_service,
        "_get_client",
        lambda: SimpleNamespace(models=Models()),
    )
    monkeypatch.setattr(
        ai_service,
        "genai_types",
        SimpleNamespace(GenerateContentConfig=lambda **kwargs: kwargs),
    )
    monkeypatch.setattr(ai_service.time, "sleep", lambda _duration: None)

    result = ai_service.generate_gemini_json(
        "prompt", lambda: {"summary": "respaldo", "count": 0}, validate=True)

    assert len(calls) == 2
    assert result == {"summary": "respuesta válida", "count": 0}


def _post_json(client, url, payload):
    return client.post(
        url,
        json=payload,
        headers={"X-CSRFToken": read_csrf_token(client, "/dashboard")},
    )


def test_resultado_predictivo_se_persiste_con_fecha_y_auditoria(
        client, login_as, monkeypatch):
    login_as(client, ADMIN_EMAIL)
    monkeypatch.setattr(
        ai_service,
        "get_predictive_analytics",
        lambda *_args: {"summary": "resultado de prueba"},
    )

    response = _post_json(
        client,
        "/api/ai/predictive-analytics",
        {"selectedTimeframe": "prueba"},
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    generated_at = datetime.fromisoformat(data["generatedAt"])
    setting = m.Setting.query.filter_by(key="predictive_data").one()
    audit_entry = m.AuditLog.query.filter_by(
        action="EJECUCIÓN_PREDICCIÓN_IA").one()
    assert generated_at.tzinfo is not None
    assert setting.value == data
    assert audit_entry.after == {"value": data}
    assert audit_entry.before == {"value": None}


def test_pagina_predictiva_persiste_el_respaldo_con_fecha(
        client, login_as, monkeypatch):
    login_as(client, ADMIN_EMAIL)

    def gemini_no_disponible():
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(ai_service, "_get_client", gemini_no_disponible)

    response = client.get("/ai-predictive")

    assert response.status_code == 200
    setting = m.Setting.query.filter_by(key="predictive_data").one()
    assert datetime.fromisoformat(setting.value["generatedAt"]).tzinfo is not None
    assert m.AuditLog.query.filter_by(
        action="EJECUCIÓN_PREDICCIÓN_IA").count() == 1


@pytest.mark.parametrize(
    ("url", "service_name", "action", "payload"),
    [
        ("/api/ai/recommendations", "get_recommendations",
         "EJECUCIÓN_RECOMENDACIONES_IA", {"clientProfile": {"name": "Dato privado"}}),
        ("/api/ai/generate-itinerary", "get_itinerary",
         "EJECUCIÓN_ITINERARIO_IA", {"notes": "Dato privado"}),
    ],
)
def test_llamadas_generativas_se_auditan_sin_guardar_entradas(
        client, login_as, monkeypatch, url, service_name, action, payload):
    login_as(client, ADMIN_EMAIL)
    monkeypatch.setattr(ai_service, service_name, lambda *_args: {"ok": True})

    response = _post_json(client, url, payload)

    assert response.status_code == 200
    audit_entry = m.AuditLog.query.filter_by(action=action).one()
    assert audit_entry.user_id == m.User.query.filter_by(email=ADMIN_EMAIL).one().id
    assert "Dato privado" not in (audit_entry.details or "")
    assert "Dato privado" not in json.dumps(audit_entry.after or {})


def test_chat_no_coincide_con_fragmentos_de_palabras(client, login_as):
    login_as(client, ADMIN_EMAIL)
    csrf_token = read_csrf_token(client, "/dashboard")

    for message in ("which", "holanda"):
        response = client.post(
            "/api/chat/message",
            json={"message": message},
            headers={"X-CSRFToken": csrf_token},
        )
        assert response.status_code == 200
        assert response.get_json().get("suggest_agent") is True

    greeting = client.post(
        "/api/chat/message",
        json={"message": "hi"},
        headers={"X-CSRFToken": csrf_token},
    )
    assert "Soy el asistente virtual" in greeting.get_json()["reply"]
