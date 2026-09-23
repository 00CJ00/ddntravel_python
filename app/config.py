"""
Configuración de la aplicación DDN Travel.

Toda la configuración se lee de variables de entorno vía python-dotenv.
El entorno real del proceso manda sobre el archivo .env (por eso se usa
``load_dotenv()`` sin ``override``).
"""
import os
import secrets

from dotenv import load_dotenv

# Carga .env si existe, sin sobreescribir variables ya definidas en el entorno.
load_dotenv()

# Texto de ejemplo usado en .env.example. Nunca debe usarse como clave real.
EXAMPLE_SECRET_KEY = "genera_una_clave_aleatoria_larga"


class Config:
    """Configuración base común a todos los entornos."""

    ENV = os.environ.get("FLASK_ENV", "development")
    DEBUG = os.environ.get("FLASK_DEBUG") == "1"
    HOST = os.environ.get("HOST", "127.0.0.1")
    PORT = int(os.environ.get("PORT", "3000"))
    SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()


class DevelopmentConfig(Config):
    """Configuración de desarrollo (por defecto)."""

    ENV = "development"


class ProductionConfig(Config):
    """Configuración de producción (FLASK_ENV=production)."""

    ENV = "production"


def get_config():
    """Devuelve la clase de configuración según la variable FLASK_ENV."""
    if os.environ.get("FLASK_ENV") == "production":
        return ProductionConfig
    return DevelopmentConfig


def resolve_secret_key(secret_key: str, env: str, logger=None) -> str:
    """Valida y resuelve la SECRET_KEY que usará la aplicación.

    - En producción (``env == "production"``) la app se niega a arrancar si la
      clave falta, tiene menos de 32 caracteres o coincide con el texto de
      ejemplo de ``.env.example`` (lanza RuntimeError).
    - En desarrollo, si falta o coincide con el ejemplo, genera una clave
      aleatoria nueva por proceso y avisa por log.
    """
    if env == "production":
        if not secret_key:
            raise RuntimeError(
                "SECRET_KEY no definida: producción requiere una clave secreta.")
        if len(secret_key) < 32:
            raise RuntimeError(
                "SECRET_KEY demasiado corta: debe tener al menos 32 caracteres.")
        if secret_key == EXAMPLE_SECRET_KEY:
            raise RuntimeError(
                "SECRET_KEY no puede ser el texto de ejemplo de .env.example.")
        return secret_key

    if not secret_key or secret_key == EXAMPLE_SECRET_KEY:
        generated = secrets.token_hex(32)
        if logger is not None:
            logger.warning(
                "SECRET_KEY no definida (o con valor de ejemplo) en desarrollo: "
                "se generó una clave aleatoria nueva para este proceso.")
        return generated
    return secret_key