import sys
import os
import socket
import logging
import traceback
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from waitress import serve
from config_qt import PRICE_MAP, REVERSE_PRICE_MAP, TIER_LIMITS, load_config, get_resource_path
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

ASYNC_MODE = "threading"

class FlaskServer:
    def __init__(self, port, stripe_service, api_token: str,
                 latest_bin_assignment_callback, secret_key: str,
                 log_info, log_error, user_data_dir=None,
                 bidder_manager=None, telegram_service=None):
        if user_data_dir is None:
            user_data_dir = os.getenv("RENDER_DATA_DIR", "/opt/render/project/swiftsale_data")
            if os.getenv("RENDER") == "true":
                user_data_dir = "/opt/render/project/swiftsale_data"
            else:
                user_data_dir = os.path.join(os.getenv('LOCALAPPDATA', os.path.expanduser("~")), 'SwiftSaleApp')
        os.makedirs(user_data_dir, exist_ok=True)
        log_file = os.path.join(user_data_dir, "swiftsale_flask_server.log")

        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5),
                logging.StreamHandler(sys.stdout)
            ]
        )
        logger = logging.getLogger(__name__)

        self.log_info = log_info
        self.log_error = log_error
        self.port = port
        self.stripe_service = stripe_service
        self.api_token = api_token
        self.latest_bin_assignment_callback = latest_bin_assignment_callback
        self.env = os.environ.get('FLASK_ENV', 'development').lower()

        template_dir = get_resource_path("templates")
        static_dir = get_resource_path("static")

        self.bidder_manager = bidder_manager
        self.telegram_service = telegram_service

        self.app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
        self.app.config['SECRET_KEY'] = secret_key

        self.limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
        self.limiter.init_app(self.app)

        cors_origins = [f"http://localhost:{port}"] if self.env == 'production' else "*"
        transports = ["polling", "websocket"]
        self.socketio = SocketIO(self.app, cors_allowed_origins=cors_origins, async_mode=ASYNC_MODE, transports=transports)

        self._register_routes()
        self._register_socketio_events()

    def _get_ngrok_path(self) -> str:
        if os.getenv("RENDER") == "true":
            raise RuntimeError("ngrok is not used in Render environment")
        base = get_resource_path("")
        ngrok_local = os.path.join(base, "ngrok.exe")
        if os.path.isfile(ngrok_local):
            if not os.access(ngrok_local, os.X_OK):
                raise PermissionError(f"ngrok.exe at {ngrok_local} is not executable")
            return ngrok_local
        url = "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        zf.extract("ngrok.exe", base)
        return ngrok_local

    def start(self):
        self.log_info("Starting Flask server")
        port = int(os.getenv("PORT", 10000))
        serve(self.app, host="0.0.0.0", port=port, threads=8)

    def _register_routes(self):
        @self.app.route('/health')
        def health():
            return jsonify(status="ok"), 200

        @self.app.route('/env-check')
        def env_check():
            stripe_mode = "live" if self.env == "production" else "test"
            return jsonify({
                "stripe_mode": stripe_mode,
                "flask_env": self.env
            }), 200

        @self.app.route('/')
        def index():
            return render_template("index.html")

        @self.app.route('/create-checkout-session', methods=['POST'])
        def create_checkout_session():
            data = request.get_json() or {}
            tier = data.get('tier')
            user_email = data.get('user_email')
            if not tier or not user_email:
                return jsonify(error="Missing tier or user_email"), 400
            try:
                session, status = self.stripe_service.create_checkout_session(tier, user_email, request.url_root)
                return jsonify(session), status
            except Exception as e:
                logging.getLogger(__name__).error(f"Stripe session error: {e}", exc_info=True)
                return jsonify(error=str(e)), 500

        @self.app.route('/subscription-status')
        def subscription_status():
            email = request.args.get('email')
            if not email:
                return jsonify(error="Missing email"), 400
            try:
                tier = self.stripe_service.db_manager.get_user_tier(email)
                license_key = self.stripe_service.db_manager.get_user_license_key(email)
                if license_key:
                    status, next_billing_date = self.stripe_service.get_subscription_status(license_key)
                else:
                    status, next_billing_date = "N/A", "N/A"
                return jsonify({"tier": tier or "Trial", "status": status, "next_billing_date": next_billing_date}), 200
            except Exception as e:
                logging.getLogger(__name__).error(f"Subscription status error for {email}: {e}", exc_info=True)
                return jsonify(error=str(e)), 500

        @self.app.route('/stripe/webhook', methods=['POST'])
        def stripe_webhook():
            try:
                payload = request.get_data(cache=False)
                sig_header = request.headers.get('Stripe-Signature')
                if not payload or not sig_header:
                    logging.error("Webhook missing payload or signature header")
                    return jsonify({"error": "Missing signature or payload"}), 400
                status_code, response = self.stripe_service.handle_webhook(payload, sig_header)
                if isinstance(response, dict):
                    return jsonify(response), status_code
                elif isinstance(response, str):
                    return response, status_code
                else:
                    return "", status_code
            except Exception as e:
                logging.error(f"Webhook endpoint error: {e}", exc_info=True)
                return jsonify({"error": "Webhook endpoint failure"}), 500

        @self.app.route('/register-install', methods=['POST'])
        def register_install():
            try:
                data = request.get_json() or {}
                if not data or 'email' not in data:
                    return jsonify({"error": "Email is required"}), 400

                email = data['email'].strip().lower()
                if '@' not in email:
                    return jsonify({"error": "Invalid email address"}), 400

                hashed_email = hashlib.sha256(email.encode()).hexdigest()
                existing_install = self.stripe_service.db_manager.get_install_by_hashed_email(hashed_email)
                if existing_install:
                    return jsonify({
                        "install_id": existing_install['install_id'],
                        "tier": existing_install['tier']
                    }), 200

                last_install = self.stripe_service.db_manager.get_last_install()
                if last_install:
                    last_id = int(last_install['install_id'])
                    new_id = f"{last_id + 1:07d}"
                else:
                    new_id = "0000001"

                self.stripe_service.db_manager.save_install({
                    "hashed_email": hashed_email,
                    "install_id": new_id,
                    "tier": "free"
                })

                return jsonify({
                    "install_id": new_id,
                    "tier": "free"
                }), 200

            except Exception as e:
                logging.getLogger(__name__).error(f"Error registering install: {e}", exc_info=True)
                return jsonify({"error": "Internal server error"}), 500

        @self.app.route('/api/validate-dev-code')
        def validate_dev_code():
            code = request.args.get("code")
            if not code:
                return jsonify({"valid": False, "error": "Missing code"}), 400
            try:
                database_url = os.getenv("DATABASE_URL")
                if database_url and os.getenv("RENDER") == "true":
                    parsed_url = urlparse(database_url)
                    conn = psycopg2.connect(
                        dbname=parsed_url.path[1:],
                        user=parsed_url.username,
                        password=parsed_url.password,
                        host=parsed_url.hostname,
                        port=parsed_url.port
                    )
                else:
                    conn = psycopg2.connect(
                        dbname=os.getenv("CLOUD_DB_NAME"),
                        user=os.getenv("CLOUD_DB_USER"),
                        password=os.getenv("CLOUD_DB_PASSWORD"),
                        host=os.getenv("CLOUD_DB_HOST"),
                        port=os.getenv("CLOUD_DB_PORT", "5432")
                    )
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT email, expires_at, used FROM dev_codes
                        WHERE code = %s
                    """, (code,))
                    row = cur.fetchone()
                    if not row:
                        return jsonify({"valid": False, "error": "Invalid code"}), 404
                    email, expires_at, used = row
                    if used:
                        return jsonify({"valid": False, "error": "Code already used"}), 403
                    if expires_at and datetime.utcnow() > expires_at:
                        return jsonify({"valid": False, "error": "Code expired"}), 403
                    return jsonify({"valid": True, "email": email}), 200
            except Exception as e:
                logging.getLogger(__name__).error(f"Dev code validation error: {e}", exc_info=True)
                return jsonify({"valid": False, "error": "Server error"}), 500

    def _register_socketio_events(self):
        @self.socketio.on('connect')
        def on_connect():
            self.log_info("Client connected via SocketIO")

    def shutdown(self):
        self.log_info("Shutting down Flask server")