import sys
import os
import socket
import logging
import traceback
import uuid
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template, jsonify, request, g
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from waitress import serve
from config_qt import PRICE_MAP, REVERSE_PRICE_MAP, TIER_LIMITS, load_config, get_resource_path, DEFAULT_DATA_DIR, get_config_value
from stripe_service_qt import StripeService
from bidder_manager_qt import BidderManager
import stripe
import zipfile
import io
import requests
import hashlib
from urllib.parse import urlparse
import psycopg2
from datetime import datetime
import re

ASYNC_MODE = "threading"

def json_success(data=None, status=200):
    response = {"status": "success"}
    if data is not None:
        response.update(data)
    return jsonify(response), status

def json_error(message, status=400):
    return jsonify({"status": "error", "error": message}), status

def get_db_connection():
    if os.getenv("RENDER") != "true":
        raise RuntimeError("Attempted to access cloud DB outside of Render environment")
    try:
        db_url = os.getenv("DATABASE_URL")
        parsed_url = urlparse(db_url)
        return psycopg2.connect(
            dbname=parsed_url.path[1:],
            user=parsed_url.username,
            password=parsed_url.password,
            host=parsed_url.hostname,
            port=parsed_url.port
        )    

    except Exception as e:
        logging.getLogger(__name__).error(f"Database connection error: {e}", exc_info=True)
        raise

class FlaskServer:
    def __init__(self, port, stripe_service, api_token: str,
                 latest_bin_assignment_callback, secret_key: str,
                 log_info, log_error, user_data_dir=None,
                 bidder_manager=None, telegram_service=None):
        self.env = os.getenv("FLASK_ENV", "development").lower()
        self.port = int(os.getenv("PORT", port))
        self.api_token = os.getenv("API_TOKEN", api_token)
        self.secret_key = os.getenv("SECRET_KEY", secret_key)
        user_data_dir = os.getenv("RENDER_DATA_DIR", "/opt/render/project/swiftsale_data" if os.getenv("RENDER") == "true" else
                                 os.path.join(os.getenv('LOCALAPPDATA', os.path.expanduser("~")), 'SwiftSaleApp'))

        os.makedirs(user_data_dir, exist_ok=True)
        log_file = os.path.join(user_data_dir, "swiftsale_flask_server.log")

        logging.basicConfig(
            level=logging.DEBUG if self.env == "development" else logging.INFO,
            format="%(asctime)s [%(levelname)s] [RequestID: %(request_id)s] %(message)s",
            handlers=[
                RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)

        self.log_info = log_info
        self.log_error = log_error
        self.stripe_service = stripe_service
        self.latest_bin_assignment_callback = latest_bin_assignment_callback
        self.bidder_manager = bidder_manager
        self.telegram_service = telegram_service

        template_dir = get_resource_path("templates")
        static_dir = get_resource_path("static")
        self.app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
        self.app.config['SECRET_KEY'] = self.secret_key

        self.limiter = Limiter(key_func=get_remote_address, storage_uri=os.getenv("LIMITER_STORAGE_URI", "memory://"))
        self.limiter.init_app(self.app)

        cors_origins = ["https://swiftsale4.onrender.com"] if self.env == "production" else "*"
        transports = ["polling", "websocket"]
        self.socketio = SocketIO(self.app, cors_allowed_origins=cors_origins, async_mode=ASYNC_MODE, transports=transports)

        self._register_routes()
        self._register_socketio_events()
        self._register_error_handlers()

    def _register_error_handlers(self):
        @self.app.errorhandler(Exception)
        def handle_error(error):
            request_id = getattr(g, 'request_id', 'unknown')
            self.logger.error(f"Unhandled error [RequestID: {request_id}]: {str(error)}", exc_info=True)
            return json_error("Internal server error", 500)

    def _register_routes(self):
        @self.app.before_request
        def before_request():
            g.request_id = str(uuid.uuid4())
            g.start_time = datetime.utcnow()
            self.logger.info(f"Request started: {request.method} {request.path} [RequestID: {g.request_id}]",
                             extra={"request_id": g.request_id})

        @self.app.after_request
        def after_request(response):
            duration = (datetime.utcnow() - g.start_time).total_seconds() * 1000
            self.logger.info(
                f"Request completed: {request.method} {request.path} [Status: {response.status_code}] [Duration: {duration:.2f}ms]",
                extra={"request_id": g.request_id}
            )
            return response

        @self.app.route('/health', methods=['GET'])
        def health():
            return json_success(status=200)

        @self.app.route('/env-check', methods=['GET'])
        def env_check():
            stripe_mode = "live" if self.env == "production" else "test"
            return json_success({"stripe_mode": stripe_mode, "flask_env": self.env}, 200)

        @self.app.route('/', methods=['GET'])
        def index():
            return render_template("index.html")

        @self.app.route('/create-checkout-session', methods=['POST'])
        def create_checkout_session():
            if os.getenv("RENDER") != "true":
                return json_error("Checkout is disabled in local mode", 403)
            data = request.get_json() or {}
            tier = data.get('tier')
            user_email = data.get('user_email')
            if not tier or not user_email:
                return json_error("Missing tier or user_email", 400)
            try:
                session, status = self.stripe_service.create_checkout_session(tier, user_email, request.url_root)
                return json_success(session, status)
            except Exception as e:
                self.logger.error(f"Stripe session error: {e}", exc_info=True, extra={"request_id": g.request_id})
                return json_error(str(e), 500)

        @self.app.route('/subscription-status', methods=['GET'])
        def subscription_status():
            email = request.args.get('email')
            if not email:
                return json_error("Missing email", 400)
            try:
                if not self.stripe_service.db_manager:
                    self.logger.warning("DB manager not available, falling back to Trial tier", extra={"request_id": g.request_id})
                    return json_success({"tier": "Trial", "status": "Unavailable", "next_billing_date": "N/A"}, 200)

                tier = self.stripe_service.db_manager.get_user_tier(email)
                license_key = self.stripe_service.db_manager.get_user_license_key(email)
                status, next_billing_date = self.stripe_service.get_subscription_status(license_key) if license_key else ("N/A", "N/A")
                return json_success({"tier": tier or "Trial", "status": status, "next_billing_date": next_billing_date}, 200)
            except Exception as e:
                self.logger.error(f"Subscription status error for {email}: {e}", exc_info=True, extra={"request_id": g.request_id})
                return json_error(str(e), 500)

        @self.app.route('/stripe/webhook', methods=['POST'])
        def stripe_webhook():
            if os.getenv("RENDER") != "true":
                return "", 200
            try:
                payload = request.get_data(cache=False)
                sig_header = request.headers.get('Stripe-Signature')
                if not payload or not sig_header:
                    self.logger.error("Webhook missing payload or signature header", extra={"request_id": g.request_id})
                    return json_error("Missing signature or payload", 400)
                status_code, response = self.stripe_service.handle_webhook(payload, sig_header)
                if isinstance(response, dict):
                    return json_success(response, status_code)
                return response, status_code
            except Exception as e:
                self.logger.error(f"Webhook endpoint error: {e}", exc_info=True, extra={"request_id": g.request_id})
                return json_error("Webhook endpoint failure", 500)

        @self.app.route('/register-install', methods=['POST'])
        def register_install():
            if os.getenv("RENDER") != "true":
                return json_error("Install registration only available in cloud environment", 403)
            try:
                data = request.get_json() or {}
                email = data.get('email')
                if not email:
                    return json_error("Email is required", 400)
                email = email.strip().lower()
                if not re.match(r"[^@]+@[^@]+\\.[^@]+", email):
                    return json_error("Invalid email address", 400)
                hashed_email = hashlib.sha256(email.encode()).hexdigest()
                with get_db_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT install_id, tier FROM installs WHERE hashed_email = %s", (hashed_email,))
                        existing_install = cur.fetchone()
                        if existing_install:
                            self.logger.info(f"Existing install found for hashed_email: {hashed_email}", extra={"request_id": g.request_id})
                            return json_success({"install_id": existing_install[0], "tier": existing_install[1]}, 200)
                        cur.execute("SELECT install_id FROM installs ORDER BY install_id DESC LIMIT 1")
                        last_install = cur.fetchone()
                        new_id = f"{int(last_install[0]) + 1:07d}" if last_install else "0000001"
                        cur.execute("INSERT INTO installs (hashed_email, install_id, tier) VALUES (%s, %s, %s)", (hashed_email, new_id, "free"))
                        conn.commit()
                self.logger.info(f"New install registered: {new_id} for hashed_email: {hashed_email}", extra={"request_id": g.request_id})
                return json_success({"install_id": new_id, "tier": "free"}, 200)
            except Exception as e:
                self.logger.error(f"Error registering install: {e}", exc_info=True, extra={"request_id": g.request_id})
                return json_error("Internal server error", 500)

        @self.app.route('/api/validate-dev-code', methods=['GET'])
        def validate_dev_code():
            code = request.args.get("code")
            if not code:
                return json_error("Missing code", 400)
            try:
                with get_db_connection() as conn:
                    with conn.cursor() as cur:
                        code = code.strip().lower()
                        cur.execute("""
                            SELECT email, expires_at, used, assigned_to, device_id
                            FROM dev_codes
                            WHERE code = %s
                        """, (code,))
                        row = cur.fetchone()
                        if not row:
                            return json_error("Invalid or expired developer code. Try again or contact support", 404)

                        email, expires_at, used, assigned_to, bound_device = row
                        now = datetime.utcnow()

                        if used:
                            if expires_at and datetime.utcnow() > expires_at:
                                return json_error("Developer code expired. Contact support.", 403)
                            return json_error("Developer code already used. Contact support.", 403)

                        return json_success({"valid": True, "email": email}, 200)

            except Exception as e:
                self.logger.error(f"Dev code validation error: {e}", exc_info=True, extra={"request_id": g.request_id})
                return json_error("Server error. Launching in trial mode.", 500)

    def _register_socketio_events(self):
        @self.socketio.on('connect')
        def on_connect():
            self.logger.info("Client connected via SocketIO", extra={"request_id": getattr(g, 'request_id', 'unknown')})

    def start(self):
        """Start the Flask server using Waitress."""
        self.logger.info(f"Starting Flask server on port {self.port}")
        serve(self.app, host="0.0.0.0", port=self.port, threads=8)


    def shutdown(self):
        self.logger.info("Shutting down Flask server")

if __name__ == "__main__":
    cfg = load_config()
    port = int(cfg.get("PORT", 10000))

    bidders_db_path = os.path.join(DEFAULT_DATA_DIR, "bidders_qt.db")
    subs_db_path = os.path.join(DEFAULT_DATA_DIR, "subscriptions_qt.db")

    bidder_manager = BidderManager(bidders_db_path, subs_db_path)
    stripe_service = StripeService(
        stripe_secret_key=cfg.get("STRIPE_SECRET_KEY", ""),
        webhook_secret=cfg.get("STRIPE_WEBHOOK_SECRET", ""),
        db_manager=bidder_manager,
        api_token=cfg.get("API_TOKEN", "")
    )

    server = FlaskServer(
        port=port,
        stripe_service=stripe_service,
        api_token=cfg.get("API_TOKEN", ""),
        latest_bin_assignment_callback=None,
        secret_key=cfg.get("SECRET_KEY", os.urandom(24).hex()),
        log_info=print,
        log_error=print,
        bidder_manager=bidder_manager
    )
    server.start()
