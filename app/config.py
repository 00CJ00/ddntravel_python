"""
Configuración de la aplicación DDN Travel.

Toda la configuración se lee de variables de entorno vía python-dotenv.
El entorno real del proceso manda sobre el archivo .env (por eso se usa
``load_dotenv()`` sin ``override``).
"""
import os
import secrets
from datetime import timedelta

from dotenv import load_dotenv

# Carga .env si existe, sin sobreescribir variables ya definidas en el entorno.
load_dotenv()

# Texto de ejemplo usado en .env.example. Nunca debe usarse como clave real.
EXAMPLE_SECRET_KEY = "genera_una_clave_aleatoria_larga"


def _flag(name: str, default: str = "0") -> bool:
    """Lee un interruptor booleano del entorno (``1``/``true``/``si``)."""
    value = os.environ.get(name, default).strip().lower()
    return value in {"1", "true", "yes", "si", "sí"}


class Config:
    """Configuración base común a todos los entornos."""

    ENV = os.environ.get("FLASK_ENV", "development")
    DEBUG = os.environ.get("FLASK_DEBUG") == "1"
    HOST = os.environ.get("HOST", "127.0.0.1")
    PORT = int(os.environ.get("PORT", "3000"))
    SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()

    # --- Sesión y cookies (RNF-01) ---
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _flag("SESSION_COOKIE_SECURE", "0")
    SESSION_REFRESH_EACH_REQUEST = False

    # --- CSRF (toda ruta que muta datos lo exige) ---
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # 1 hora

    # --- Rate limiting ---
    RATELIMIT_ENABLED = _flag("RATELIMIT_ENABLED", "1")
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_DEFAULT = os.environ.get("RATELIMIT_DEFAULT", "120 per minute")
    RATELIMIT_HEADERS_ENABLED = True

    # Límites por endpoint. Los generativos son los más caros: se permiten pocas
    # llamadas por minuto y por usuario/IP para no abusar de Gemini ni del servidor.
    LOGIN_RATE_LIMIT = os.environ.get("LOGIN_RATE_LIMIT", "5 per minute")
    CONTACT_RATE_LIMIT = os.environ.get("CONTACT_RATE_LIMIT", "5 per hour")
    CHAT_RATE_LIMIT = os.environ.get("CHAT_RATE_LIMIT", "30 per minute")
    AI_GENERATIVE_RATE_LIMIT = os.environ.get("AI_GENERATIVE_RATE_LIMIT", "10 per minute")
    AI_PREDICTIVE_RATE_LIMIT = os.environ.get("AI_PREDICTIVE_RATE_LIMIT", "6 per hour")

    # --- Interruptores de operaciones peligrosas (P1) ---
    # /reset solo existe con ENABLE_RESET=1; /switch-user solo con
    # app.debug y ENABLE_DEV_SWITCH=1 (además de ser administrador).
    ENABLE_RESET = _flag("ENABLE_RESET", "0")
    ENABLE_DEV_SWITCH = _flag("ENABLE_DEV_SWITCH", "0")

    # --- Límites de entrada (anti abuso) ---
    CHAT_MESSAGE_MAX_LENGTH = int(os.environ.get("CHAT_MESSAGE_MAX_LENGTH", "500"))
    CONTACT_MESSAGE_MAX_LENGTH = int(os.environ.get("CONTACT_MESSAGE_MAX_LENGTH", "2000"))


class DevelopmentConfig(Config):
    """Configuración de desarrollo (por defecto)."""

    ENV = "development"


class ProductionConfig(Config):
    """Configuración de producción (FLASK_ENV=production)."""

    ENV = "production"

    # En producción la cookie de sesión solo viaja por HTTPS.
    SESSION_COOKIE_SECURE = True
    WTF_CSRF_SSL_STRICT = True



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