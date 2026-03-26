from flask import Flask, request, jsonify, render_template
import logging
from flask_wtf.csrf import CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .extensions import jwt, mail, oauth, csrf, limiter  # ❌ removed migrate


def create_app():
    app = Flask(
        __name__,
        static_folder="../static",
        static_url_path="/static"
    )

    app.config.from_object(Config)
    Config.validate()

    # INIT EXTENSIONS

    jwt.init_app(app)
    mail.init_app(app)
    oauth.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    _configure_logging(app)
    _register_security_headers(app)
    _register_error_handlers(app)

    from .auth.routes import auth_bp, init_oauth
    from .student.routes import student_bp
    from .company.routes import company_bp
    from .admin.routes import admin_bp
    from .public.routes import public_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(company_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(public_bp)

    init_oauth(app)

    from .db import init_db

    with app.app_context():
        init_db()

    return app


# =========================
# 🔧 LOGGING
# =========================
def _configure_logging(app):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    app.logger.setLevel(logging.INFO)


# =========================
# 🚨 ERROR HANDLERS (FIXED)
# =========================
def _register_error_handlers(app):

    def wants_json():
        return request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest"

    @app.errorhandler(400)
    def bad_request(error):
        if wants_json():
            return jsonify({"success": False, "message": "Bad request"}), 400
        return render_template("public/error.html", code=400), 400

    @app.errorhandler(403)
    def forbidden(error):
        if wants_json():
            return jsonify({"success": False, "message": "Forbidden"}), 403
        return render_template("public/error.html", code=403), 403

    @app.errorhandler(404)
    def not_found(error):
        if wants_json():
            return jsonify({"success": False, "message": "Page not found"}), 404
        return render_template("public/error.html", code=404), 404

    @app.errorhandler(413)
    def too_large(error):
        if wants_json():
            return jsonify({"success": False, "message": "File too large"}), 413
        return render_template("public/error.html", code=413), 413

    @app.errorhandler(429)
    def rate_limited(error):
        if wants_json():
            return jsonify({
                "success": False,
                "message": "Too many requests. Please try again later."
            }), 429
        return render_template("public/error.html", code=429), 429

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        if wants_json():
            return jsonify({
                "success": False,
                "message": "CSRF validation failed."
            }), 400
        return render_template("public/error.html", code="csrf"), 400


# =========================
# 🔐 SECURITY HEADERS
# =========================
def _register_security_headers(app):
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        csp = (
            "default-src 'self'; "
            "img-src 'self' data: https:; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
            "style-src 'self' 'unsafe-inline' https:; "
            "font-src 'self' https: data:; "
            "connect-src 'self' https:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self' https://accounts.google.com"
        )
        response.headers["Content-Security-Policy"] = csp

        if request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response