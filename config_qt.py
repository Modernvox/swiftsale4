"""
Enhanced configuration utilities for the SwiftSale Qt client & local server.

- Keeps the public API used across the app (load_config, save_config, etc.).
- Safely handles promo_expiration as datetime on load.
- Updater: exposes get_update_manifest_url().
- Production key enforcement happens only when running the server
  (RENDER=true or SERVER_MODE=true), not for the desktop client.
- Adds APP_ENV and a username sanitizer. Auto-capture stays OFF by default.
"""

from __future__ import annotations

import os
import sys
import json
import logging
import uuid
import re
from datetime import datetime
from typing import Optional
try:
    from cryptography.fernet import Fernet  # optional; only used if envs provided
except Exception:  # cryptography may not be bundled in some client builds
    Fernet = None  # type: ignore

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
NGROK_PATH = os.getenv("NGROK_PATH", os.path.join(DEFAULT_DATA_DIR, "ngrok.exe"))

DEFAULT_TRIAL_EMAIL = "trial@swiftsaleapp.com"

# Stripe price mappings
PRICE_MAP = {
    "Bronze": "price_1RLcP4J7WrcpTNl6a8aHdSgv",
    "Silver": "price_1RLcKcJ7WrcpTNl6jT7sLvmU",
    "Gold":   "price_1RQefvJ7WrcpTNl68QwN2zEj",
}
REVERSE_PRICE_MAP = {v: k for k, v in PRICE_MAP.items()}

# Bin limits per tier
TIER_LIMITS = {
    "Trial":  {"bins": 20},
    "Bronze": {"bins": 50},
    "Silver": {"bins": 150},
    "Gold":   {"bins": 600},
}

# Updater: default manifest URL (can be overridden by env UPDATE_MANIFEST_URL)
DEFAULT_UPDATE_MANIFEST_URL = "https://swiftsale4.onrender.com/updates/latest.json"

# Optional Browser Bridge defaults (desktop client)
BRIDGE_DEFAULTS = {
    "enabled": False,
    "mode": "auto",       # "auto" | "manual"
    "port": 15555,        # local port the bridge listens on (if used)
    "token": "",          # optional shared secret
}

# Username capture defaults (manual by default)
AUTO_CAPTURE_USERNAMES_DEFAULT = False
_USERNAME_RE = re.compile(r'^[A-Za-z0-9_.-]{2,30}$')

def sanitize_username(raw: Optional[str]) -> Optional[str]:
    """Normalize and validate Whatnot usernames. Returns lowercased username or None."""
    if not raw:
        return None
    u = re.sub(r'[^A-Za-z0-9_.-]', '', raw).strip()
    if not _USERNAME_RE.match(u):
        return None
    return u.lower()

# ----------------------------------------------------------------------
# Logger setup (avoid duplicate handlers)
# ----------------------------------------------------------------------
_root = logging.getLogger()
if not _root.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

logger = logging.getLogger(__name__)

debug_logger = logging.getLogger("config_qt_debug")
debug_logger.setLevel(logging.DEBUG)
if not any(isinstance(h, logging.StreamHandler) for h in debug_logger.handlers):
    debug_logger.addHandler(logging.StreamHandler())

# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------
def parse_bool_env(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable."""
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


def get_update_manifest_url() -> str:
    """Return the update manifest URL (env override or default)."""
    return os.getenv("UPDATE_MANIFEST_URL", DEFAULT_UPDATE_MANIFEST_URL)


def _is_server_runtime() -> bool:
    """
    Decide if we should enforce server-side secrets.
    We treat as 'server' when running on Render or when SERVER_MODE=true.
    The desktop client (even if FLASK_ENV=production for frozen exe) should not enforce.
    """
    if os.getenv("RENDER", "").lower() == "true":
        return True
    if parse_bool_env("SERVER_MODE", False):
        return True
    # Some devs set FLASK_ENV=production in the client; don't enforce just for that.
    return False


# ----------------------------------------------------------------------
# Install information utilities
# ----------------------------------------------------------------------
def load_install_info() -> dict:
    """Load installation info from disk, returning an empty dict if missing or invalid.

    Returns keys: email, install_id, tier, optional promo_expiration (datetime if parseable).
    """
    if not os.path.exists(INSTALL_INFO_PATH):
        return {}
    try:
        with open(INSTALL_INFO_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
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
    promo_expiration: Optional[datetime] = None,
) -> None:
    """Persist installation info to disk (promo_expiration serialized to ISO-8601 if provided)."""
    try:
        os.makedirs(os.path.dirname(INSTALL_INFO_PATH), exist_ok=True)
        data = {"email": email, "install_id": install_id, "tier": tier}
        if promo_expiration:
            data["promo_expiration"] = promo_expiration.isoformat()
        with open(INSTALL_INFO_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save install info: {e}")


def get_or_create_install_info() -> dict:
    """Ensure install_info.json exists and contains required keys."""
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
    """Load application configuration, decrypting secrets when envs are provided."""
    ensure_data_dir()

    flask_env = os.getenv("FLASK_ENV", "development").lower()
    # Provide APP_ENV for other modules; prefer explicit env var, else mirror FLASK_ENV,
    # and if server mode is detected force 'production'.
    app_env = os.getenv("APP_ENV", flask_env).lower()
    if _is_server_runtime():
        app_env = "production"

    debug_logger.debug(f"Running in FLASK_ENV={flask_env}, APP_ENV={app_env}")

    # Desktop-friendly defaults
    config: dict = {
        "FLASK_ENV": flask_env,
        "APP_ENV": app_env,
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
        # Updater URL exposed to app code (can be read from config if preferred)
        "UPDATE_MANIFEST_URL": get_update_manifest_url(),
        # Bridge defaults (app can read if desired)
        "BRIDGE_ENABLED_DEFAULT": parse_bool_env("BRIDGE_ENABLED_DEFAULT", BRIDGE_DEFAULTS["enabled"]),
        "BRIDGE_MODE_DEFAULT": os.getenv("BRIDGE_MODE_DEFAULT", BRIDGE_DEFAULTS["mode"]),
        "BRIDGE_PORT_DEFAULT": int(os.getenv("BRIDGE_PORT_DEFAULT", BRIDGE_DEFAULTS["port"])),
        "BRIDGE_TOKEN_DEFAULT": os.getenv("BRIDGE_TOKEN_DEFAULT", BRIDGE_DEFAULTS["token"]),
        # Username capture default (manual mode)
        "AUTO_CAPTURE_USERNAMES_DEFAULT": AUTO_CAPTURE_USERNAMES_DEFAULT,
    }

    # Decrypt Stripe secrets if provided via Fernet
    fernet_key = os.getenv("FERNET_KEY")
    enc_secret = os.getenv("ENCRYPTED_STRIPE_SECRET_KEY", "")
    enc_webhook = os.getenv("ENCRYPTED_STRIPE_WEBHOOK_SECRET", "")

    debug_logger.debug(f"FERNET_KEY present: {bool(fernet_key)}")
    debug_logger.debug(f"Encrypted secret key present: {bool(enc_secret)}")
    debug_logger.debug(f"Encrypted webhook secret present: {bool(enc_webhook)}")

    if fernet_key and Fernet:
        try:
            fernet = Fernet(fernet_key.encode())
            config["STRIPE_SECRET_KEY"] = (
                fernet.decrypt(enc_secret.encode()).decode() if enc_secret else None
            )
            config["STRIPE_WEBHOOK_SECRET"] = (
                fernet.decrypt(enc_webhook.encode()).decode() if enc_webhook else None
            )
        except Exception as e:
            logger.critical(f"Fernet decryption failed: {e}")
            # In client mode we can proceed; in server mode we will enforce below
            config["STRIPE_SECRET_KEY"] = None
            config["STRIPE_WEBHOOK_SECRET"] = None
    else:
        config["STRIPE_SECRET_KEY"] = os.getenv("STRIPE_SECRET_KEY")
        config["STRIPE_WEBHOOK_SECRET"] = os.getenv("STRIPE_WEBHOOK_SECRET")

    config["STRIPE_PUBLIC_KEY"] = os.getenv("STRIPE_PUBLIC_KEY")

    # Strict checks ONLY when acting as the server
    if _is_server_runtime():
        required = [
            "STRIPE_SECRET_KEY",
            "STRIPE_WEBHOOK_SECRET",
            "STRIPE_PUBLIC_KEY",
            "SECRET_KEY",
            "APP_BASE_URL",
            "DATABASE_URL",
        ]
        missing = [k for k in required if not config.get(k)]
        if missing:
            raise RuntimeError(f"Missing required env var(s) for server mode: {', '.join(missing)}")

    # Compose success and cancel URLs for Stripe (harmless for client)
    config["SUCCESS_URL"] = f"{config['APP_BASE_URL']}/success"
    config["CANCEL_URL"] = f"{config['APP_BASE_URL']}/cancel"

    # Load local overrides from config.json in non-server dev runs
    if os.path.exists(CONFIG_PATH) and not _is_server_runtime():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                file_config = json.load(f)
            config.update(file_config)
            debug_logger.info(f"Loaded config overrides from {CONFIG_PATH}")
        except Exception as e:
            debug_logger.warning(f"Failed to load config.json overrides: {e}")

    # Optional: decrypt a development database URL
    enc_dev_db_url = os.getenv("ENCRYPTED_DEV_DB_URL", "")
    if fernet_key and Fernet and enc_dev_db_url:
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
    """Persist configuration overrides to disk (non-server / dev use)."""
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
    """Return the absolute path to a resource bundled with the application."""
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


__all__ = [
    "PRICE_MAP",
    "REVERSE_PRICE_MAP",
    "TIER_LIMITS",
    "DEFAULT_DATA_DIR",
    "DEFAULT_UPDATE_MANIFEST_URL",
    "load_config",
    "save_config",
    "get_config_value",
    "reload_config_cache",
    "load_install_info",
    "save_install_info",
    "get_or_create_install_info",
    "get_resource_path",
    "get_update_manifest_url",
    "parse_bool_env",
    "sanitize_username",
    "AUTO_CAPTURE_USERNAMES_DEFAULT",
]
