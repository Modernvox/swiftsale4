import os
from flask_server_qt import FlaskServer
from stripe_service_qt import StripeService

server = FlaskServer(
    port=int(os.getenv("PORT", 10000)),
    stripe_service=StripeService(),
    api_token=os.getenv("API_TOKEN", "test_token"),
    latest_bin_assignment_callback=None,
    secret_key=os.getenv("SECRET_KEY", "dev_secret"),
    log_info=print,
    log_error=print
)

app = server.app
