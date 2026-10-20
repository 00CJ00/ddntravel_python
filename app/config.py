"""
Configuración de la aplicación DDN Travel.

Toda la configuración se lee de variables de entorno vía python-dotenv.
El entorno real del proceso manda sobre el archivo .env (por eso se usa
``load_dotenv()`` sin ``override``).
"""
import os
import secrets
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

# Carga .env si existe, sin sobreescribir variables ya definidas en el entorno.
load_dotenv()

# Raíz del proyecto (carpeta que contiene ``app/``) y carpeta de datos.
BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"
DEFAULT_DATABASE_URI = f"sqlite:///{(INSTANCE_DIR / 'ddn.db').as_posix()}"

# Texto de ejemplo usado en .env.example. Nunca debe usarse como clave real.
EXAMPLE_SECRET_KEY = "genera_una_clave_aleatoria_larga"


def _flag(name: str, default: str = "0") -> bool:
    """Lee un interruptor booleano del entorno (``1``/``true``/``si``)."""
    value = os.environ.get(name, default).strip().lower()
    return value in {"1", "true", "yes", "si", "sí"}


class Config:
    """Configuración base común a todos los entornos."""

    ENV = os.environ.get("FLASK_ENV", "development")
    DEBUG = (
        os.environ.get("FLASK_ENV") != "production"
        and os.environ.get("FLASK_DEBUG") == "1"
    )
    HOST = os.environ.get("HOST", "127.0.0.1")
    PORT = int(os.environ.get("PORT", "3000"))
    SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()

    # --- Base de datos (P2). PostgreSQL en producción vía DATABASE_URL ---
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URI
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    # Número de respaldos que conserva scripts/backup.py y ``flask backup``.
    BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "10"))
    BACKUP_DIR = os.environ.get("BACKUP_DIR") or str(BASE_DIR / "backups")

    # --- Subida de documentos (RF-17) ---
    UPLOAD_DIR = os.environ.get("UPLOAD_DIR") or str(BASE_DIR / "instance" / "uploads")
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 5 * 1024 * 1024))

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

    # --- Correo transaccional de notificaciones (RF-13) ---
    MAIL_SERVER = os.environ.get("MAIL_SERVER") or None
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = _flag("MAIL_USE_TLS", "1")
    MAIL_USE_SSL = _flag("MAIL_USE_SSL", "0")
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME") or None
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD") or None
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER") or None

    # --- Interruptores de operaciones peligrosas (P1) ---
    # /reset solo existe con ENABLE_RESET=1; /switch-user solo con
    # app.debug y ENABLE_DEV_SWITCH=1 (además de ser administrador).
    ENABLE_RESET = _flag("ENABLE_RESET", "0")
    ENABLE_DEV_SWITCH = _flag("ENABLE_DEV_SWITCH", "0")
    ENABLE_SCHEDULER = _flag("ENABLE_SCHEDULER", "0")

    # --- Alertas automáticas (fase P6): job diario solo si ENABLE_SCHEDULER=1 ---
    ENABLE_SCHEDULER = _flag("ENABLE_SCHEDULER", "0")
    ALERTS_INTERVAL_HOURS = int(os.environ.get("ALERTS_INTERVAL_HOURS", "24"))

    # --- Estadísticas del dashboard (fase P5, RF-14) ---
    # Viajes mínimos para considerar un cliente "frecuente".
    FREQUENT_CLIENT_MIN = int(os.environ.get("FREQUENT_CLIENT_MIN", "3"))
    # Factor sobre la media mensual de reservas que define una "temporada alta".
    PEAK_SEASON_FACTOR = float(os.environ.get("PEAK_SEASON_FACTOR", "1.25"))

    # --- Emisor de facturas (RF-11) ---
    AGENCY_RNC = os.environ.get("AGENCY_RNC", "131456789")
    AGENCY_NAME = os.environ.get("AGENCY_NAME", "DDN Travel S.R.L.")
    AGENCY_ADDRESS = os.environ.get("AGENCY_ADDRESS", "Av. Winston Churchill 1052, Santo Domingo")
    AGENCY_PHONE = os.environ.get("AGENCY_PHONE", "+1 (809) 555-0123")
    NCF_PREFIX = os.environ.get("NCF_PREFIX", "B02")
    NCF_PREFIX_RNC = os.environ.get("NCF_PREFIX_RNC", "B01")
    NCF_CREDITO_PREFIX = os.environ.get("NCF_CREDITO_PREFIX", "B04")

    # --- Documentos (RF-17, fase P6): fuera de static/, tope 5 MB ---
    UPLOAD_DIR = os.environ.get("UPLOAD_DIR") or str(BASE_DIR / "uploads")
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", str(5 * 1024 * 1024)))

    # --- Correo transaccional (RF-13, fase P6): sin MAIL_* se usa consola/log ---
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = _flag("MAIL_USE_TLS", "1")
    MAIL_USE_SSL = _flag("MAIL_USE_SSL", "0")
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "")
    MAIL_SUPPRESS_SEND = _flag("MAIL_SUPPRESS_SEND", "0")

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