import os
from secrets import token_hex

from flask import Flask, jsonify, render_template, request, session
from werkzeug.exceptions import RequestEntityTooLarge
from psycopg.errors import UniqueViolation
from psycopg import OperationalError
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_connection
from social import social
from security import allow_request, client_address
from urllib.parse import urlsplit


def create_app():
    app = Flask(__name__)
    app.config.update(SECRET_KEY=os.environ["FLASK_SECRET_KEY"], MAX_CONTENT_LENGTH=16 * 1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true")
    app.register_blueprint(social)
    public_origin = os.environ.get('PUBLIC_ORIGIN', '').rstrip('/')
    if public_origin:
        origin = urlsplit(public_origin)
        if (origin.scheme != 'https' or not origin.hostname or origin.username or origin.password
                or origin.path or origin.query or origin.fragment):
            raise ValueError('PUBLIC_ORIGIN must be an HTTPS origin without a path.')
    app.config['PUBLIC_ORIGIN'] = public_origin

    #user identifier, password hash, registration

    @app.post("/api/register")
    def register():
        data = json_body()

        username = data.get("username")
        password = data.get("password")

        if not valid_text(username, 40):
            return jsonify(error="Username must be 1-40 characters."), 400

        if not isinstance(password, str) or not 10 <= len(password) <= 128:
            return jsonify(error="Password must be 10-128 characters."), 400

        username = username.strip()
        user_id = token_hex(16)
        password_hash = generate_password_hash(password)

        try:
            with get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO users (id, username, password_hash)
                    VALUES (%s, %s, %s)
                    """,
                    (user_id, username, password_hash)
                )

        except UniqueViolation:
            return jsonify(error="Username already taken."), 409

        session.clear()
        session["user_id"] = user_id

        return jsonify(id=user_id, username=username), 201
    #login checking

    @app.post("/api/login")
    def login():
        data = json_body()

        username = data.get("username")
        password = data.get("password")

        if not valid_text(username, 40) or not isinstance(password, str) or not 1 <= len(password) <= 128:
            return jsonify(error="Invalid username or password."), 401

        with get_connection() as conn:
            user = conn.execute(
                """
                SELECT id, username, password_hash
                FROM users
                WHERE LOWER(username) = LOWER(%s)
                """,
                (username.strip(),)
            ).fetchone()

        if user is None or not check_password_hash(user[2], password):
            return jsonify(error="Invalid username or password."), 401

        session.clear()
        session["user_id"] = user[0]

        return jsonify(id=user[0], username=user[1]), 200

    #logout

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(message="Logged out successfully."), 200

    #logged in use account info

    @app.get("/api/me")
    def current_user():
        user_id = session["user_id"]

        with get_connection() as conn:
            user = conn.execute(
                """
                SELECT id, username
                FROM users
                WHERE id = %s
                """,
                (user_id,)
            ).fetchone()

        return jsonify(id=user[0], username=user[1])

    #connect to databse

    @app.get("/health/db")
    def database_health():
        try:
            with get_connection() as conn:
                result = conn.execute("SELECT 1").fetchone()
            return jsonify(database="connected", result=result[0])
        except Exception:
            app.logger.exception("Database health check failed")
            return jsonify(database="unavailable"), 503




    def json_body():
        data = request.get_json(silent=True) if request.is_json else None
        return data if isinstance(data, dict) else {}

    def valid_text(value, limit):
        return isinstance(value, str) and "\x00" not in value and 0 < len(value.strip()) <= limit

    @app.before_request
    def request_security():
        if not request.path.startswith('/api/'):
            return None
        if any(isinstance(value, int) and value > 9223372036854775807
               for value in (request.view_args or {}).values()):
            return jsonify(error='Invalid identifier.'), 400
        if request.method == 'POST':
            origin = request.headers.get('Origin')
            allowed_origins = {'http://localhost:5000', 'http://127.0.0.1:5000'}
            if app.config['TESTING']:
                allowed_origins.add('http://localhost')
            if app.config['PUBLIC_ORIGIN']:
                allowed_origins.add(app.config['PUBLIC_ORIGIN'])
            if (request.headers.get('Sec-Fetch-Site') == 'cross-site'
                    or (origin and origin not in allowed_origins)):
                return jsonify(error='Cross-origin requests are not allowed.'), 403
            if not request.is_json:
                return jsonify(error='Send an application/json request.'), 415
        address = client_address()
        if request.method == 'POST' or request.path == '/api/users/search':
            auth = request.path in ('/api/login', '/api/register')
            actor = address if auth else session.get('user_id', address)
            if not allow_request('auth' if auth else 'social', actor, 20 if auth else 120):
                return jsonify(error='Too many requests. Try again in a minute.'), 429, {'Retry-After': '60'}
        return None

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.before_request
    def identify_visitor():
        protected = (
            request.path.startswith("/api/")
            and request.path not in (
                "/api/register",
                "/api/login",
                "/api/logout",
            )
        )

        if not protected:
            return None

        user_id = session.get("user_id")

        if not user_id:
            return jsonify(error="Login required."), 401

        with get_connection() as conn:
            user = conn.execute(
                "SELECT id FROM users WHERE id = %s",
                (user_id,)
            ).fetchone()

            if user is None:
                session.clear()
                return jsonify(error="Login required."), 401

            conn.execute(
                "UPDATE users SET last_seen = NOW() WHERE id = %s",
                (user_id,)
            )

        return None

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(error):
        return jsonify(error="Request body must be at most 16 KiB."), 413

    @app.errorhandler(OperationalError)
    def database_unavailable(error):
        app.logger.exception("Database connection failed")
        return jsonify(error="Account service is temporarily unavailable. Please try again."), 503

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
