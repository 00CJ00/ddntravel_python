"""Tests de privacidad: NO enviar nombres/emails de clientes a Gemini (RF-20)."""
import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import ai_service


class _Models:
    def __init__(self):
        self.captures = []

    def generate_content(self, model, contents, config=None):
        self.captures.append(contents)
        return SimpleNamespace(text=json.dumps({"ok": True}))


@pytest.fixture
def gemini_captura(monkeypatch):
    """Mockea el cliente de Gemini y captura el prompt enviado."""
    models = _Models()
    client = SimpleNamespace(models=models)
    monkeypatch.setattr(ai_service, "_get_client", lambda: client)
    return models.captures


def _cliente(nombre="Roberto Gomez", category="VIP", budget="Premium",
             trips=5, destinos=None):
    return SimpleNamespace(name=nombre, category=category,
                            budget_preference=budget, trips_count=trips,
                            preferred_destinations=destinos or [])


def test_predictive_analytics_no_envia_nombres_reales(gemini_captura):
    clientes = [_cliente("Roberto Gomez"), _cliente("Maria Lopez")]
    ai_service.get_predictive_analytics(clientes, [], [], "2026-Q1")
    assert gemini_captura, "Gemini no fue llamado"
    prompt = gemini_captura[0]
    assert "Roberto Gomez" not in prompt
    assert "Maria Lopez" not in prompt
    assert "Cliente A" in prompt
    assert "Cliente B" in prompt


def test_recommendations_no_envia_nombre_real(gemini_captura):
    perfil = {"name": "Roberto Gomez", "email": "roberto@example.com"}
    ai_service.get_recommendations(perfil, 2500, "Playa", 2, "Cultura")
    assert gemini_captura
    prompt = gemini_captura[0]
    assert "Roberto Gomez" not in prompt
    assert "roberto@example.com" not in prompt
