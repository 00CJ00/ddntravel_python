"""Pruebas del cliente Gemini sin llamadas de red."""
from types import SimpleNamespace

from app import ai_service


def test_gemini_usa_38_flash_como_primer_modelo(monkeypatch):
    llamadas = []

    class Models:
        @staticmethod
        def generate_content(*, model, contents, config):
            llamadas.append((model, contents, config))
            return SimpleNamespace(text='{"ok": true}')

    class GenerateContentConfig:
        def __init__(self, **kwargs):
            self.options = kwargs

    monkeypatch.setattr(ai_service, "_get_client", lambda: SimpleNamespace(models=Models()))
    monkeypatch.setattr(
        ai_service,
        "genai_types",
        SimpleNamespace(GenerateContentConfig=GenerateContentConfig),
    )

    result = ai_service.generate_gemini_json("prompt de prueba", lambda: {"fallback": True})

    assert llamadas[0][0] == "gemini-3.8-flash"
    assert llamadas[0][1] == "prompt de prueba"
    assert llamadas[0][2].options == {"response_mime_type": "application/json"}
    assert result == {"ok": True}
