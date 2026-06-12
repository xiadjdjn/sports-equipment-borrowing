from flask import Flask, g

from .admin import register_admin_routes
from .auth import current_user, register_auth_routes
from .borrowing import equipment_image, register_borrow_routes
from .config import CATEGORIES, RECORD_STATUS, SECRET_KEY
from .db import activate_due_reservations, close_db, init_db, refresh_overdue_records


def create_app():
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config["SECRET_KEY"] = SECRET_KEY
    app.teardown_appcontext(close_db)

    @app.before_request
    def prepare_request():
        init_db()
        activate_due_reservations()
        refresh_overdue_records()
        g.user = current_user()

    @app.context_processor
    def inject_common_data():
        return {
            "current_user": g.get("user"),
            "categories": CATEGORIES,
            "record_status": RECORD_STATUS,
            "equipment_image": equipment_image,
        }

    register_auth_routes(app)
    register_borrow_routes(app)
    register_admin_routes(app)
    return app
