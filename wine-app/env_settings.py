from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

APP_DIR = Path(__file__).resolve().parent


def load_app_env() -> None:
    """Load `.env`, then fill any missing keys from `.env.auth`."""
    app_dir = Path(APP_DIR)
    load_dotenv(app_dir / ".env", override=False)
    auth_values = dotenv_values(app_dir / ".env.auth")
    for key, value in auth_values.items():
        if value is not None and not os.getenv(key, "").strip():
            os.environ[key] = value


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    path = Path(value) if value else default
    return path if path.is_absolute() else APP_DIR / path


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return value


def _session_ttl_hours() -> int:
    hours = os.getenv("CELLAR_SESSION_TTL_HOURS", "").strip()
    if hours:
        return _env_int("CELLAR_SESSION_TTL_HOURS", 0)
    return _env_int("WINE_APP_TTL_DAYS", 30) * 24


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{name} must be 'true' or 'false'.")
    return value == "true"


@dataclass(frozen=True)
class AppSettings:
    app_dir: Path
    data_dir: Path
    database_url: str
    cellar_username: str
    cellar_password: str
    cellar_session_secret: str
    cellar_admin_email: str
    session_ttl_hours: int
    password_reset_ttl_hours: int
    account_activation_ttl_hours: int
    cookie_secure: bool
    public_base_url: str
    wine_labels_dir: Path
    email_log_file: Path
    enrichment_cache_file: Path
    enrichment_usage_file: Path
    qr_labels_dir: Path
    grapeminds_api_key: str
    grapeminds_base_url: str
    grapeminds_mock_mode: bool
    grapeminds_monthly_limit: int
    wineapiio_api_key: str
    wineapiio_base_url: str
    wineapiio_daily_limit: int
    ollama_url: str
    ollama_vision_model: str
    ollama_timeout_seconds: int
    openrouter_api_key: str
    openrouter_vision_model: str
    openrouter_base_url: str
    openrouter_site_url: str
    openrouter_app_name: str
    cloud_vision_timeout_seconds: int
    catalog_timeout_seconds: int
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    smtp_tls: bool
    smtp_ssl: bool
    smtp_timeout_seconds: int
    max_label_size_mb: int


def get_settings() -> AppSettings:
    """Return typed settings from `.env`, `.env.auth`, and the process environment."""
    app_dir = APP_DIR
    data_dir = _env_path("WINE_APP_DATA_DIR", app_dir)
    username = os.getenv("CELLAR_USERNAME", "").strip()
    database_url = os.getenv(
        "CELLAR_DATABASE_URL", f"sqlite:///{data_dir / 'wine_cellar.db'}"
    ).strip()
    if not database_url:
        raise ValueError("CELLAR_DATABASE_URL must not be empty.")
    return AppSettings(
        app_dir=app_dir,
        data_dir=data_dir,
        database_url=database_url,
        cellar_username=username,
        cellar_password=os.getenv("CELLAR_PASSWORD", "").strip(),
        cellar_session_secret=os.getenv("CELLAR_SESSION_SECRET", "").strip(),
        cellar_admin_email=os.getenv(
            "CELLAR_ADMIN_EMAIL", f"{username}@local" if username else ""
        ).strip(),
        session_ttl_hours=_session_ttl_hours(),
        password_reset_ttl_hours=_env_int("PASSWORD_RESET_TTL_HOURS", 1),
        account_activation_ttl_hours=_env_int(
            "ACCOUNT_ACTIVATION_TTL_HOURS", 48
        ),
        cookie_secure=_env_bool("CELLAR_COOKIE_SECURE", False),
        public_base_url=os.getenv("WINE_APP_BASE_URL", "").strip().rstrip("/"),
        wine_labels_dir=_env_path(
            "WINE_LABELS_DIR", data_dir / "wine-labels"
        ),
        email_log_file=_env_path(
            "WINE_EMAIL_LOG_FILE", data_dir / "sent_emails.log"
        ),
        enrichment_cache_file=_env_path(
            "ENRICHMENT_CACHE_FILE", data_dir / "enrichment_cache.json"
        ),
        enrichment_usage_file=_env_path(
            "ENRICHMENT_USAGE_FILE", data_dir / "enrichment_usage.json"
        ),
        qr_labels_dir=_env_path(
            "WINE_QR_LABELS_DIR", data_dir / "wine-bottle-QR-codes"
        ),
        grapeminds_api_key=os.getenv("GRAPEMINDS_API_KEY", "").strip(),
        grapeminds_base_url=os.getenv(
            "GRAPEMINDS_BASE_URL", "https://api.grapeminds.eu/public/v1"
        ).strip().rstrip("/"),
        grapeminds_mock_mode=_env_bool("GRAPEMINDS_MOCK_MODE", False),
        grapeminds_monthly_limit=_env_int("GRAPEMINDS_MONTHLY_LIMIT", 200),
        wineapiio_api_key=os.getenv("WINEAPIIO_KEY", "").strip(),
        wineapiio_base_url=os.getenv(
            "WINEAPIIO_BASE_URL", "https://api.wineapi.io"
        ).strip().rstrip("/"),
        wineapiio_daily_limit=_env_int("WINEAPIIO_REQUESTS_PER_DAY", 100),
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434").strip().rstrip("/"),
        ollama_vision_model=os.getenv(
            "OLLAMA_VISION_MODEL", "qwen2.5vl:7b"
        ).strip(),
        ollama_timeout_seconds=_env_int("OLLAMA_TIMEOUT_SECONDS", 120),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
        openrouter_vision_model=os.getenv(
            "OPENROUTER_VISION_MODEL", "qwen/qwen2.5-vl-72b-instruct:free"
        ).strip(),
        openrouter_base_url=os.getenv(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ).strip().rstrip("/"),
        openrouter_site_url=os.getenv("OPENROUTER_SITE_URL", "").strip(),
        openrouter_app_name=os.getenv("OPENROUTER_APP_NAME", "").strip(),
        cloud_vision_timeout_seconds=_env_int(
            "CLOUD_VISION_TIMEOUT_SECONDS", 60
        ),
        catalog_timeout_seconds=_env_int("CATALOG_TIMEOUT_SECONDS", 15),
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_port=_env_int("SMTP_PORT", 587),
        smtp_user=os.getenv("SMTP_USER", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", "").strip(),
        smtp_from=os.getenv("SMTP_FROM", "cellar@local").strip(),
        smtp_tls=_env_bool("SMTP_TLS", True),
        smtp_ssl=_env_bool("SMTP_SSL", False),
        smtp_timeout_seconds=_env_int("SMTP_TIMEOUT_SECONDS", 10),
        max_label_size_mb=_env_int("WINE_LABEL_MAX_SIZE_MB", 10),
    )


load_app_env()
