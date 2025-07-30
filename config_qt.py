"""
Enhanced configuration utilities for the SwiftSale Qt client.

This module refactors and tidies up the original ``config_qt.py`` to
improve logging behaviour, avoid duplicate handlers, and provide
clearer separation between production and development settings.  It
retains the original public API (``load_config``, ``save_config``,
``get_or_create_install_info``, etc.), so it can be used as a drop‑in
replacement.  It also introduces support for per‑user promotional
expirations by accepting an optional ``promo_expiration`` parameter when
saving install information and by deserializing ISO‑8601 timestamps
when loading install information.
"""

from __future__ import annotations

import os
import sys
import json
import logging
import uuid
from datetime import datetime  # Used for promo_expiration handling
from cryptography.fernet import Fernet


# ----------------------------------------------------------------------
# Paths and constants
# ----------------------------------------------------------------------
INSTALL_INFO_PATH = os.path.join(
    os.getenv("LOCALAPPDATA", os.path.expanduser("~")),
    "SwiftSaleApp",
    "install_info.json",
)

# Base directory for storing config files and other persistent data
DEFAULT_DATA_DIR = os.path.join(
    os.getenv("LOCALAPPDATA", os.path.expanduser("~")), "SwiftSaleApp"
)
CONFIG_PATH = os.path.join(DEFAULT_DATA_DIR, "config.json")
NGROK_PATH = os.getenv(
    "NGROK_PATH", os.path.join(DEFAULT_DATA_DIR, "ngrok.exe")
)

DEFAULT_TRIAL_EMAIL = "trial@swiftsaleapp.com"

# Stripe price mappings
PRICE_MAP = {
    "Bronze": "price_1RLcP4J7WrcpTNl6a8aHdSgv",
    "Silver": "price_1RLcKcJ7WrcpTNl6jT7sLvmU",
    "Gold": "price_1RQefvJ7WrcpTNl68QwN2zEj",
}
REVERSE_PRICE_MAP = {v: k for k, v in PRICE_MAP.items()}

# Bin limits per tier
TIER_LIMITS = {
    "Trial": {"bins": 20},
    "Bronze": {"bins": 50},
    "Silver": {"bins": 150},
    "Gold": {"bins": 600},
}

# ----------------------------------------------------------------------
# Logger setup
# ----------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Dedicated debug logger for verbose output in development
debug_logger = logging.getLogger("config_qt_debug")
debug_logger.setLevel(logging.DEBUG)
if not debug_logger.handlers:
    debug_logger.addHandler(logging.StreamHandler())


# ----------------------------------------------------------------------
# Install information utilities
# ----------------------------------------------------------------------
def load_install_info() -> dict:
    """Load installation info from disk, returning an empty dict if missing or invalid.

    The returned dictionary can contain ``email``, ``install_id``, ``tier`` and
    an optional ``promo_expiration`` ISO‑8601 string.  When reading, the
    ``promo_expiration`` string is converted to a :class:`datetime` object if
    possible; otherwise it is left unchanged.
    """
    if not os.path.exists(INSTALL_INFO_PATH):
        return {}
    try:
        with open(INSTALL_INFO_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Convert promo_expiration to datetime if present
        promo_exp = data.get("promo_expiration")
        if promo_exp:
            try:
                data["promo_expiration"] = datetime.fromisoformat(promo_exp)
            except Exception:
                # Leave as string if parsing fails
                pass
        return data
    except Exception as e:
        logger.error(f"Failed to load install info: {e}")
        return {}


def save_install_info(
    email: str,
    install_id: str,
    tier: str,
    promo_expiration: datetime | None = None,
) -> None:
    """Persist the current installation information to disk.

    Accepts an optional ``promo_expiration`` datetime.  If provided, it
    will be serialized as an ISO‑8601 string and written to the
    ``install_info.json`` file.  If not provided, any existing
    ``promo_expiration`` entry will be removed.
    """
    try:
        os.makedirs(os.path.dirname(INSTALL_INFO_PATH), exist_ok=True)
        data = {
            "email": email,
            "install_id": install_id,
            "tier": tier,
        }
        if promo_expiration:
            data["promo_expiration"] = promo_expiration.isoformat()
        with open(INSTALL_INFO_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save install info: {e}")


def get_or_create_install_info() -> dict:
    """Ensure ``install_info.json`` exists and contains required keys.

    If the file does not exist it will be created with default values.  If
    the file exists but is missing required keys, they will be added
    (including a ``promo_expiration`` key set to ``None``).
    """
    if not os.path.exists(INSTALL_INFO_PATH):
        os.makedirs(os.path.dirname(INSTALL_INFO_PATH), exist_ok=True)
        install_id = str(uuid.uuid4())[:8]
        info = {
            "email": DEFAULT_TRIAL_EMAIL,
            "install_id": install_id,
            "tier": "Trial",
            "promo_expiration": None,
        }
        with open(INSTALL_INFO_PATH, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2)
        return info

    info = load_install_info()
    changed = False
    if not info.get("install_id"):
        info["install_id"] = str(uuid.uuid4())[:8]
        changed = True
    if not info.get("email"):
        info["email"] = DEFAULT_TRIAL_EMAIL
        changed = True
    if not info.get("tier"):
        info["tier"] = "Trial"
        changed = True
    # Ensure the promo_expiration key exists (use None if not present)
    if "promo_expiration" not in info:
        info["promo_expiration"] = None
        changed = True
    if changed:
        save_install_info(
            info["email"],
            info["install_id"],
            info["tier"],
            promo_expiration=info.get("promo_expiration"),
        )
    return info


# ----------------------------------------------------------------------
# Config loading and saving
# ----------------------------------------------------------------------
def ensure_data_dir() -> None:
    """Create the default data directory if it does not already exist."""
    os.makedirs(DEFAULT_DATA_DIR, exist_ok=True)
    debug_logger.debug(f"Ensured data directory exists: {DEFAULT_DATA_DIR}")


def load_config() -> dict:
    """Load application configuration, decrypting secrets when needed."""
    ensure_data_dir()

    env = os.getenv("FLASK_ENV", "development").lower()
    debug_logger.debug(f"Running in environment: {env}")

    config: dict = {
        "FLASK_ENV": env,
        "PORT": os.getenv("PORT", "5000"),
        "APP_BASE_URL": os.getenv("APP_BASE_URL", "http://localhost:5000"),
        # Use SQLite locally by default; allow override via env
        "DATABASE_URL": os.getenv(
            "DATABASE_URL",
            f"sqlite:///{os.path.join(DEFAULT_DATA_DIR, 'subscriptions_qt.db')}",
        ),
        "TELEGRAM_BOT_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "TELEGRAM_CHAT_ID": os.getenv("TELEGRAM_CHAT_ID", ""),
        "API_TOKEN": os.getenv("API_TOKEN", ""),
        "SECRET_KEY": os.getenv("SECRET_KEY"),
        # These may be overridden later
        "USER_EMAIL": "",
        "INSTALL_ID": "",
        "TIER": "Trial",
    }

    # Decrypt Stripe secrets if provided via Fernet
    fernet_key = os.getenv("FERNET_KEY")
    enc_secret = os.getenv("ENCRYPTED_STRIPE_SECRET_KEY", "")
    enc_webhook = os.getenv("ENCRYPTED_STRIPE_WEBHOOK_SECRET", "")

    debug_logger.debug(f"FERNET_KEY present: {bool(fernet_key)}")
    debug_logger.debug(f"Encrypted secret key present: {bool(enc_secret)}")
    debug_logger.debug(f"Encrypted webhook secret present: {bool(enc_webhook)}")

    if fernet_key:
        try:
            fernet = Fernet(fernet_key.encode())
            config["STRIPE_SECRET_KEY"] = (
                fernet.decrypt(enc_secret.encode()).decode()
                if enc_secret
                else None
            )
            config["STRIPE_WEBHOOK_SECRET"] = (
                fernet.decrypt(enc_webhook.encode()).decode()
                if enc_webhook
                else None
            )
        except Exception as e:
            logger.critical(f"Fernet decryption failed: {e}")
            raise RuntimeError("Critical: Unable to decrypt Stripe keys.")
    else:
        config["STRIPE_SECRET_KEY"] = os.getenv("STRIPE_SECRET_KEY")
        config["STRIPE_WEBHOOK_SECRET"] = os.getenv("STRIPE_WEBHOOK_SECRET")

    config["STRIPE_PUBLIC_KEY"] = os.getenv("STRIPE_PUBLIC_KEY")

    # Validate required secrets in production
    if env == "production":
        for key in [
            "STRIPE_SECRET_KEY",
            "STRIPE_WEBHOOK_SECRET",
            "STRIPE_PUBLIC_KEY",
            "SECRET_KEY",
            "APP_BASE_URL",
            "DATABASE_URL",
        ]:
            if not config.get(key):
                raise RuntimeError(f"Missing required env var in production: {key}")

    # Compose success and cancel URLs for Stripe
    config["SUCCESS_URL"] = f"{config['APP_BASE_URL']}/success"
    config["CANCEL_URL"] = f"{config['APP_BASE_URL']}/cancel"

    # Load local overrides from config.json in non-production environments
    if os.path.exists(CONFIG_PATH) and env != "production":
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                file_config = json.load(f)
            config.update(file_config)
            debug_logger.info(f"Loaded config overrides from {CONFIG_PATH}")
        except Exception as e:
            debug_logger.warning(f"Failed to load config.json overrides: {e}")

    # Optionally decrypt a development database URL
    enc_dev_db_url = os.getenv("ENCRYPTED_DEV_DB_URL", "")
    if fernet_key and enc_dev_db_url:
        try:
            fernet = Fernet(fernet_key.encode())
            config["DEV_DB_URL"] = fernet.decrypt(enc_dev_db_url.encode()).decode()
        except Exception as e:
            logger.critical(f"Failed to decrypt DEV_DB_URL: {e}")
            config["DEV_DB_URL"] = ""
    else:
        config["DEV_DB_URL"] = ""

    return config


def save_config(config_dict: dict) -> None:
    """Persist configuration overrides to disk (non‑production use)."""
    try:
        ensure_data_dir()
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, indent=4)
        logger.info(f"Saved config to {CONFIG_PATH}")
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        raise


# ----------------------------------------------------------------------
# Caching helpers
# ----------------------------------------------------------------------
_app_config_cache: dict | None = None


def get_config_value(key: str):
    """Retrieve a configuration value, preferring environment variables."""
    if key in os.environ:
        return os.environ[key]
    global _app_config_cache
    if _app_config_cache is None:
        _app_config_cache = load_config()
    return _app_config_cache.get(key)


def reload_config_cache() -> None:
    """Force a fresh reload of the application configuration."""
    global _app_config_cache
    _app_config_cache = load_config()


# ----------------------------------------------------------------------
# Resource path helper
# ----------------------------------------------------------------------
def get_resource_path(relative_path: str) -> str:
    """Return the absolute path to a resource bundled with the application.

    In a frozen (bundled) application, ``sys._MEIPASS`` points to the
    temporary directory containing bundled resources.  When running from
    source, resources live relative to the module's directory.  This
    function constructs an absolute path accordingly.

    Args:
        relative_path: The relative path to the resource inside the
            bundle or project directory.

    Returns:
        An absolute filesystem path to the requested resource.
    """
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


__all__ = [
    "PRICE_MAP",
    "REVERSE_PRICE_MAP",
    "TIER_LIMITS",
    "load_config",
    "save_config",
    "get_config_value",
    "reload_config_cache",
    "load_install_info",
    "save_install_info",
    "get_or_create_install_info",
    "get_resource_path",
]
