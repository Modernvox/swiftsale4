# flask_server_qt.py — production-ready entrypoint (Waitress+polling by default; Eventlet switchable)
import sys
import os
import logging
import uuid
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template, jsonify, request, g, make_response, has_request_context
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from waitress import serve
from config_qt import (
    load_config,
    get_resource_path,
    DEFAULT_DATA_DIR,
    get_config_value,
    sanitize_username,  # <- for safe username handling
)
from bidder_manager_qt import BidderManager
import hashlib
from urllib.parse import urlparse
from datetime import datetime
import re
import time
import json
from collections import deque

# -----------------------------
# Log filter to ensure %(request_id)s always exists
# -----------------------------
class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True

def _reqid() -> str:
    try:
        if has_request_context():
            return getattr(g, "request_id", "-")
    except Exception:
        pass
    return "-"

# -----------------------------
# JSON helpers
# -----------------------------
def json_success(data=None, status=200):
    response = {"status": "success"}
    if data is not None:
        response.update(data)
    return jsonify(response), status

def json_error(message, status=400):
    return jsonify({"status": "error", "error": message}), status

# -----------------------------
# Cloud DB helper (Render only)
# -----------------------------
def get_db_connection():
    """Return a PostgreSQL connection only if running on Render."""
    if os.getenv("RENDER", "").lower() != "true":
        return None
    try:
        db_url = os.getenv("DATABASE_URL")
        if not db_url or not db_url.startswith("postgres"):
            logging.getLogger(__name__).warning("Invalid or missing DATABASE_URL on Render")
            return None
        # Lazy import psycopg2 so desktop builds without it don't crash
        import psycopg2  # type: ignore
        parsed_url = urlparse(db_url)
        return psycopg2.connect(
            dbname=parsed_url.path[1:],
            user=parsed_url.username,
            password=parsed_url.password,
            host=parsed_url.hostname,
            port=parsed_url.port,
        )
    except Exception as e:
        logging.getLogger(__name__).error(f"Database connection error: {e}", exc_info=True)
        return None

# -----------------------------
# Env helpers / updater
# -----------------------------
def _bool_env(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}

def _manifest_payload():
    latest_version = get_config_value("LATEST_VERSION") or "4.0.0"
    installer_url  = get_config_value("INSTALLER_URL") or ""
    sha256         = get_config_value("INSTALLER_SHA256") or ""
    notes          = get_config_value("RELEASE_NOTES") or ""
    force          = _bool_env("FORCE_UPDATE", False)
    min_os = "Windows-10"
    if not installer_url or not sha256:
        return None
    return {
        "version": str(latest_version),
        "url": str(installer_url),
        "sha256": str(sha256),
        "notes": str(notes),
        "force": bool(force),
        "min_os": min_os,
    }

# -----------------------------
# Local-only request check
# -----------------------------
_LOCAL_ADDRS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

def _is_local_request(req: request) -> bool:
    ra = (req.remote_addr or "").strip()
    return ra in _LOCAL_ADDRS

# -----------------------------
# Bridge config knobs
# -----------------------------
def _get_bridge_enabled_default() -> bool:
    # Default ON locally, OFF on Render unless explicitly enabled
    if os.getenv("RENDER", "").lower() == "true":
        return _bool_env("BROWSER_BRIDGE_ENABLED", False)
    return _bool_env("BROWSER_BRIDGE_ENABLED", True)

def _get_bridge_secret_default(default_secret: str) -> str:
    return os.getenv("BROWSER_BRIDGE_SECRET", default_secret)

def _get_bridge_cors_origin() -> str:
    return os.getenv("BROWSER_BRIDGE_CORS", "*")

def _get_bridge_rate() -> str:
    return os.getenv("BROWSER_BRIDGE_RATE", "120/minute")

# -----------------------------
# In-memory de-dup (recent winners)
# -----------------------------
class RecentWins:
    def __init__(self, ttl_seconds: int = 5, max_items: int = 500):
        self.ttl = ttl_seconds
        self.max_items = max_items
        self._dq = deque()  # holds (key, ts)
        self._set = set()

    def seen(self, username_key: str, lot_id):
        now = time.time()
        key = (username_key, lot_id or "")
        while self._dq and (now - self._dq[0][1] > self.ttl or len(self._dq) > self.max_items):
            k, _ = self._dq.popleft()
            self._set.discard(k)
        if key in self._set:
            return True
        self._set.add(key)
        self._dq.append((key, now))
        return False

class FlaskServer:
    def __init__(self, port,
                 latest_bin_assignment_callback,
                 secret_key: str,
                 log_info, log_error,
                 user_data_dir=None,
                 bidder_manager=None,
                 telegram_service=None):
        # -----------------------------
        # Environment / paths
        # -----------------------------
        self.env = os.getenv("FLASK_ENV", "development").lower()
        self.port = int(os.getenv("PORT", port))
        self.secret_key = os.getenv("SECRET_KEY", secret_key)
        user_data_dir = os.getenv(
            "RENDER_DATA_DIR",
            "/opt/render/project/swiftsale_data" if os.getenv("RENDER", "").lower() == "true" else
            os.path.join(os.getenv('LOCALAPPDATA', os.path.expanduser("~")), 'SwiftSaleApp')
        )
        os.makedirs(user_data_dir, exist_ok=True)

        # -----------------------------
        # Logging (file + stdout) with safe request_id filter
        # -----------------------------
        log_file = os.path.join(user_data_dir, "swiftsale_flask_server.log")
        logging.basicConfig(
            level=logging.DEBUG if self.env == "development" else logging.INFO,
            format="%(asctime)s [%(levelname)s] [RequestID: %(request_id)s] %(message)s",
            handlers=[
                RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
        for h in logging.getLogger().handlers:
            h.addFilter(_RequestIdFilter())

        # Quiet Socket.IO/Engine.IO log noise when using polling-only
        logging.getLogger("engineio").setLevel(logging.WARNING)
        logging.getLogger("engineio.server").setLevel(logging.WARNING)
        logging.getLogger("socketio").setLevel(logging.WARNING)
        logging.getLogger("socketio.server").setLevel(logging.WARNING)

        # -----------------------------
        # Services / state
        # -----------------------------
        self.log_info = log_info
        self.log_error = log_error
        self.latest_bin_assignment_callback = latest_bin_assignment_callback
        self.bidder_manager = bidder_manager
        self.telegram_service = telegram_service

        template_dir = get_resource_path("templates")
        static_dir = get_resource_path("static")
        self.app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
        self.app.config['SECRET_KEY'] = self.secret_key

        # Rate limiting (storage can be overridden by env var, e.g., redis://)
        self.limiter = Limiter(key_func=get_remote_address, storage_uri=os.getenv("LIMITER_STORAGE_URI", "memory://"))
        self.limiter.init_app(self.app)

        # CORS for Socket.IO (override via CORS_ALLOWED_ORIGINS or fallback to env/production rule)
        cors_env = os.getenv("CORS_ALLOWED_ORIGINS")
        if cors_env:
            cors_origins = [o.strip() for o in cors_env.split(",") if o.strip()]
        else:
            cors_origins = ["https://swiftsale4.onrender.com"] if self.env == "production" else "*"

        # Socket transport mode (Eventlet for websockets, else Waitress+polling)
        use_eventlet = _bool_env("USE_EVENTLET", False)
        socketio_kwargs = dict(
            cors_allowed_origins=cors_origins,
            logger=False,
            engineio_logger=False,
            ping_interval=25,
            ping_timeout=20
        )
        if use_eventlet:
            socketio_kwargs.update(async_mode="eventlet")  # allow upgrades by default
        else:
            socketio_kwargs.update(async_mode="threading", allow_upgrades=False, transports=["polling"])  # Waitress-safe

        self.socketio = SocketIO(self.app, **socketio_kwargs)

        # Bridge defaults & state
        self.bridge_secret = _get_bridge_secret_default(self.secret_key)
        self.bridge_cors_origin = _get_bridge_cors_origin()
        self.recent_wins = RecentWins(ttl_seconds=5, max_items=500)

        # Persistent settings (enabled/mode)
        self._bridge_enabled = _get_bridge_enabled_default()
        self._bridge_mode = "auto"  # "auto" | "manual"
        self._settings_path = os.path.join(user_data_dir, "bridge_settings.json")
        self._load_bridge_settings()

        # Wire routes, sockets, errors
        self._register_routes()
        self._register_socketio_events()
        self._register_error_handlers()

    # -----------------------------
    # Settings persistence
    # -----------------------------
    def _load_bridge_settings(self):
        try:
            if os.path.exists(self._settings_path):
                with open(self._settings_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._bridge_enabled = bool(data.get("enabled", self._bridge_enabled))
                    mode = str(data.get("mode", self._bridge_mode)).lower()
                    if mode in ("auto", "manual"):
                        self._bridge_mode = mode
        except Exception as e:
            self.logger.warning(f"Failed to load bridge settings: {e}", extra={"request_id": _reqid()})
        self._save_bridge_settings()

    def _save_bridge_settings(self):
        try:
            payload = {"enabled": bool(self._bridge_enabled), "mode": str(self._bridge_mode)}
            with open(self._settings_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            self.logger.warning(f"Failed to save bridge settings: {e}", extra={"request_id": _reqid()})

    # -----------------------------
    # Error handlers
    # -----------------------------
    def _register_error_handlers(self):
        @self.app.errorhandler(Exception)
        def handle_error(error):
            request_id = getattr(g, 'request_id', 'unknown')
            self.logger.error(f"Unhandled error [RequestID: {request_id}]: {str(error)}", exc_info=True)
            return json_error("Internal server error", 500)

    # -----------------------------
    # Routes
    # -----------------------------
    def _register_routes(self):
        @self.app.before_request
        def before_request():
            g.request_id = str(uuid.uuid4())
            g.start_time = datetime.utcnow()
            self.logger.info(
                f"Request started: {request.method} {request.path} [RequestID: {g.request_id}]",
                extra={"request_id": g.request_id}
            )

        @self.app.after_request
        def after_request(response):
            # Security headers
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
            response.headers.setdefault("Referrer-Policy", "no-referrer-when-downgrade")
            response.headers.setdefault("X-Request-ID", getattr(g, 'request_id', '-'))

            try:
                if request.path in ("/won", "/bridge/status", "/bridge/mode"):
                    response.headers["Access-Control-Allow-Origin"] = self.bridge_cors_origin
                    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Bridge-Secret"
                    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS, GET"
                    response.headers["Access-Control-Max-Age"] = "600"
            except Exception:
                pass

            started = getattr(g, 'start_time', datetime.utcnow())
            duration = (datetime.utcnow() - started).total_seconds() * 1000
            self.logger.info(
                f"Request completed: {request.method} {request.path} [Status: {response.status_code}] [Duration: {duration:.2f}ms]",
                extra={"request_id": getattr(g, 'request_id', '-')}
            )
            return response

        @self.app.route('/health', methods=['GET'])
        def health():
            return json_success(status=200)

        # ------------------------------------------------------------------
        # Token-gated ENV CHECK (redacts secrets; verifies required variables)
        # ------------------------------------------------------------------
        @self.app.route('/env-check', methods=['GET'])
        def env_check():
            """
            Token-gated env inspector.
            Accepts:
              - Header:  X-API-Token: <token>
              - Header:  Authorization: Bearer <token>
              - Query:   ?api_token=<token>  or  ?token=<token>
            Always reads API_TOKEN from environment at request time.
            """
            import hmac

            expected = os.getenv("API_TOKEN", "").strip()
            supplied = (
                request.headers.get("X-API-Token")
                or (request.headers.get("Authorization", "").split("Bearer ", 1)[1].strip()
                    if "Bearer " in (request.headers.get("Authorization") or "") else "")
                or request.args.get("api_token")
                or request.args.get("token")
                or ""
            )

            if not expected or not hmac.compare_digest(str(supplied), str(expected)):
                return jsonify({"ok": False, "error": "unauthorized"}), 401

            server_mode = (os.getenv("RENDER", "").lower() == "true") or _bool_env("SERVER_MODE", False)
            use_webhooks = _bool_env("USE_STRIPE_WEBHOOKS", False)
            require_public_for_templates = _bool_env("REQUIRE_STRIPE_PUBLIC_FOR_TEMPLATES", False)

            # Required vars (Stripe removed unless you explicitly enable flags above)
            required = ["SECRET_KEY", "APP_BASE_URL", "DATABASE_URL", "API_TOKEN"]
            if use_webhooks:
                required += ["STRIPE_PUBLIC_KEY", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"]
            elif require_public_for_templates:
                required += ["STRIPE_PUBLIC_KEY"]

            missing = [k for k in required if not os.getenv(k)]

            redact = {
                "SECRET_KEY", "API_TOKEN", "DATABASE_URL",
                "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "BROWSER_BRIDGE_SECRET"
            }
            peek = sorted(set(required + [
                "STRIPE_PUBLIC_KEY", "LATEST_VERSION", "INSTALLER_URL", "INSTALLER_SHA256",
                "FORCE_UPDATE", "RELEASE_NOTES", "APP_BASE_URL", "CORS_ALLOWED_ORIGINS",
                "RENDER", "FLASK_ENV", "USE_EVENTLET"
            ]))
            safe = {k: ("********" if (os.getenv(k) and k in redact) else os.getenv(k)) for k in peek}

            return jsonify({
                "ok": len(missing) == 0,
                "missing": missing,
                "server_mode": server_mode,
                "use_webhooks": use_webhooks,
                "require_public_for_templates": require_public_for_templates,
                "vars": safe
            }), 200

        # Home / dashboard
        @self.app.route('/', methods=['GET'])
        def index():
            return render_template(
                "index.html",
                stripe_publishable_key=os.getenv("STRIPE_PUBLIC_KEY", ""),  # harmless if unused in UI
            )

        # -------- Updater manifest --------
        @self.app.route('/updates/latest.json', methods=['GET'])
        @self.limiter.limit("30/minute")
        def updates_latest():
            payload = _manifest_payload()
            if not payload:
                return jsonify({"available": False, "reason": "manifest_incomplete"}), 200
            resp = jsonify(payload)
            resp.headers["Cache-Control"] = "public, max-age=120"
            return resp, 200

        # -------- Register install (cloud only) --------
        @self.app.route('/register-install', methods=['POST'])
        def register_install():
            if os.getenv("RENDER", "").lower() != "true":
                return json_error("Install registration only available in cloud environment", 403)

            conn = get_db_connection()
            if not conn:
                self.logger.error("Cloud database connection unavailable")
                return json_error("Cloud database connection unavailable", 500)

            try:
                data = request.get_json(silent=True) or {}
                email = data.get('email')
                if not email:
                    return json_error("Email is required", 400)
                email = email.strip().lower()
                if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                    return json_error("Invalid email address", 400)

                hashed_email = hashlib.sha256(email.encode()).hexdigest()
                with conn.cursor() as cur:
                    cur.execute("SELECT install_id, tier FROM installs WHERE hashed_email = %s", (hashed_email,))
                    existing_install = cur.fetchone()
                    if existing_install:
                        self.logger.info(f"Existing install found for hashed_email: {hashed_email}", extra={"request_id": _reqid()})
                        return json_success({"install_id": existing_install[0], "tier": existing_install[1]}, 200)

                    cur.execute("SELECT install_id FROM installs ORDER BY install_id DESC LIMIT 1")
                    last_install = cur.fetchone()
                    new_id = f"{int(last_install[0]) + 1:07d}" if last_install else "0000001"
                    cur.execute(
                        "INSERT INTO installs (hashed_email, install_id, tier) VALUES (%s, %s, %s)",
                        (hashed_email, new_id, "free")
                    )
                    conn.commit()

                self.logger.info(f"New install registered: {new_id} for hashed_email: {hashed_email}", extra={"request_id": _reqid()})
                return json_success({"install_id": new_id, "tier": "free"}, 200)

            except Exception as e:
                self.logger.error(f"Error registering install: {e}", exc_info=True, extra={"request_id": _reqid()})
                return json_error("Internal server error", 500)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        @self.app.route('/api/validate-dev-code', methods=['GET'])
        def validate_dev_code():
            if os.getenv("RENDER", "").lower() != "true":
                return json_error("Developer code validation only available in cloud environment", 403)
            code = request.args.get("code")
            if not code:
                return json_error("Missing code", 400)
            try:
                conn = get_db_connection()
                if not conn:
                    return json_error("Cloud database connection unavailable", 500)
                with conn:
                    with conn.cursor() as cur:
                        code_norm = code.strip().lower()
                        cur.execute("""
                            SELECT email, expires_at, used, assigned_to, device_id
                            FROM dev_codes
                            WHERE code = %s
                        """, (code_norm,))
                        row = cur.fetchone()
                        if not row:
                            return json_error("Invalid or expired developer code. Try again or contact support", 404)

                        email, expires_at, used, assigned_to, bound_device = row
                        if used:
                            if expires_at and datetime.utcnow() > expires_at:
                                return json_error("Developer code expired. Contact support.", 403)
                            return json_error("Developer code already used. Contact support.", 403)

                        return json_success({"valid": True, "email": email}, 200)
            except Exception as e:
                self.logger.error(f"Dev code validation error: {e}", exc_info=True, extra={"request_id": _reqid()})
                return json_error("Server error. Launching in trial mode.", 500)

        # -------- Bridge status / mode --------
        @self.app.route('/bridge/status', methods=['GET', 'OPTIONS'])
        def bridge_status():
            if request.method == "OPTIONS":
                return make_response("", 204)
            if not _is_local_request(request):
                return json_error("forbidden", 403)
            return json_success({
                "enabled": bool(self._bridge_enabled),
                "mode": self._bridge_mode,
                "port": self.port
            }, 200)

        @self.app.route('/bridge/mode', methods=['POST', 'OPTIONS'])
        def bridge_mode():
            """
            Local-only endpoint to toggle capture mode and enabled flag.
            Body (any subset):
              { "enabled": true|false, "mode": "auto"|"manual" }
            """
            if request.method == "OPTIONS":
                return make_response("", 204)
            if not _is_local_request(request):
                return json_error("forbidden", 403)

            data = request.get_json(silent=True) or {}
            if "enabled" in data:
                self._bridge_enabled = bool(data["enabled"])
            if "mode" in data:
                mode = str(data["mode"]).lower().strip()
                if mode in ("auto", "manual"):
                    self._bridge_mode = mode
                else:
                    return json_error("invalid mode", 400)
            self._save_bridge_settings()
            return json_success({"enabled": self._bridge_enabled, "mode": self._bridge_mode}, 200)

        # -------- Winner ingestion --------
        @self.app.route('/won', methods=['POST', 'OPTIONS'])
        @self.limiter.limit(_get_bridge_rate)
        def won():
            """
            Local-only ingestion endpoint for winner events from the browser.
            Honors the current bridge mode:
              - auto: normal auto-assign behavior
              - manual: queue-only (no auto-assign), action='queued_manual_mode'
            Security:
              - Local address only
              - Requires header: X-Bridge-Secret
            """
            if request.method == "OPTIONS":
                return make_response("", 204)

            if not self._bridge_enabled:
                return json_error("bridge_disabled", 403)
            if not _is_local_request(request):
                self.logger.warning("Non-local request to /won blocked", extra={"request_id": _reqid()})
                return json_error("forbidden", 403)

            provided = request.headers.get("X-Bridge-Secret")
            if not provided or provided != self.bridge_secret:
                self.logger.warning("Bad or missing X-Bridge-Secret", extra={"request_id": _reqid()})
                return json_error("unauthorized", 401)

            data = request.get_json(silent=True) or {}
            raw_username = data.get("username") or ""
            lot_id = data.get("lot_id")
            source = (data.get("source") or "unknown").strip().lower()
            try:
                confidence = float(data.get("confidence") or 0.0)
            except Exception:
                confidence = 0.0
            try:
                ts = int(data.get("ts") or int(time.time() * 1000))
            except Exception:
                ts = int(time.time() * 1000)

            # Accept with or without '@', sanitize, and never crash
            raw_username = raw_username.lstrip("@").strip()
            username_core = sanitize_username(raw_username)  # lowercased, validated or None
            if not username_core:
                return json_error("bad_username", 400)
            username_display = f"@{username_core}"

            if confidence < 0 or confidence > 1:
                confidence = max(0.0, min(1.0, confidence))

            # Dedup on normalized username
            if self.recent_wins.seen(username_core, lot_id):
                return json_success({"dedup": True}, 200)

            result = {"action": "noop"}
            try:
                if self.bidder_manager and hasattr(self.bidder_manager, "record_winner"):
                    force_queue = (self._bridge_mode == "manual")
                    result = self.bidder_manager.record_winner(
                        username=username_display,
                        lot_id=lot_id,
                        source=source,
                        confidence=confidence,
                        ts=ts,
                        force_queue=force_queue
                    ) or {"action": "recorded"}
                elif callable(self.latest_bin_assignment_callback):
                    if self._bridge_mode == "manual":
                        result = {"action": "queued_manual_mode", "lot_id": lot_id}
                    else:
                        try:
                            self.latest_bin_assignment_callback(username_display)
                            result = {"action": "callback"}
                        except Exception as cb_ex:
                            self.logger.error(f"latest_bin_assignment_callback failed: {cb_ex}", exc_info=True,
                                              extra={"request_id": _reqid()})
                else:
                    result = {"action": "queued_manual_mode" if self._bridge_mode == "manual" else "received_no_handler",
                              "lot_id": lot_id}
            except Exception as e:
                self.logger.error(f"/won handler failure: {e}", exc_info=True, extra={"request_id": _reqid()})
                return json_error("handler_failure", 500)

            try:
                self.socketio.emit("winner", {
                    "username": username_display,
                    "lot_id": lot_id,
                    "source": source,
                    "confidence": confidence,
                    "ts": ts,
                    "mode": self._bridge_mode,
                    "result": result
                })
            except Exception as e:
                self.logger.error(f"socket emit failed: {e}", exc_info=True, extra={"request_id": _reqid()})

            return json_success({"ok": True, "mode": self._bridge_mode, "result": result}, 200)

    # -----------------------------
    # Socket.IO events
    # -----------------------------
    def _register_socketio_events(self):
        @self.socketio.on('connect')
        def on_connect():
            self.logger.info("Client connected via SocketIO", extra={"request_id": _reqid()})

        @self.socketio.on('disconnect')
        def on_disconnect():
            self.logger.info("Client disconnected", extra={"request_id": _reqid()})

    # -----------------------------
    # Lifecycle
    # -----------------------------
    def start(self):
        self.logger.info(f"Starting Flask server on port {self.port}")
        if _bool_env("USE_EVENTLET", False):
            try:
                import eventlet
                eventlet.monkey_patch()
            except Exception:
                self.logger.error("Eventlet start failed; is eventlet installed? pip install eventlet", exc_info=True)
                raise
            # Run with native websockets
            self.socketio.run(self.app, host="0.0.0.0", port=self.port)
        else:
            # Waitress + polling (no websockets)
            serve(self.app, host="0.0.0.0", port=self.port, threads=8)

    def shutdown(self):
        self.logger.info("Shutting down Flask server")

# -----------------------------
# Entrypoint
# -----------------------------
if __name__ == "__main__":
    # --- .env loader (works for both source & PyInstaller exe) --------------
    try:
        from dotenv import load_dotenv
        import sys as _sys, os as _os

        def _load_env_robust():
            """Load .env without overriding existing OS env vars."""
            paths = []
            try:
                here = _os.path.abspath(_os.path.dirname(__file__))
            except Exception:
                here = _os.getcwd()

            if getattr(_sys, "frozen", False):
                paths.append(_os.path.join(_os.path.dirname(_sys.executable), ".env"))

            paths.extend([
                _os.path.join(here, ".env"),
                _os.path.join(_os.path.dirname(here), ".env"),
                _os.path.join(_os.getcwd(), ".env"),
                _os.path.join(_os.getenv('LOCALAPPDATA', _os.path.expanduser("~")), 'SwiftSaleApp', '.env'),
            ])

            for p in paths:
                if _os.path.exists(p):
                    load_dotenv(dotenv_path=p, override=False)

        _load_env_robust()
    except Exception:
        pass
    # ------------------------------------------------------------------------

    cfg = load_config()
    port = int(cfg.get("PORT", 10000))

    bidders_db_path = os.path.join(DEFAULT_DATA_DIR, "bidders_qt.db")
    subs_db_path = os.path.join(DEFAULT_DATA_DIR, "subscriptions_qt.db")

    bidder_manager = BidderManager(bidders_db_path, subs_db_path)

    # No StripeService — payment links (if any) handled client-side only

    server = FlaskServer(
        port=port,
        latest_bin_assignment_callback=None,
        secret_key=cfg.get("SECRET_KEY", os.urandom(24).hex()),
        log_info=print,
        log_error=print,
        bidder_manager=bidder_manager
    )
    server.start()
