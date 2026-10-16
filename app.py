from datetime import datetime, timezone
from secrets import token_hex
from threading import Lock
from time import monotonic

from flask import Flask, jsonify, render_template, request, session
from werkzeug.exceptions import RequestEntityTooLarge


def create_app():
    app = Flask(__name__)
    # Ephemeral identities, like messages, intentionally reset on restart.
    app.config.update(SECRET_KEY=token_hex(32), MAX_CONTENT_LENGTH=16 * 1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
    users = {}
    messages = []
    lock = Lock()

    def json_body():
        data = request.get_json(silent=True) if request.is_json else None
        return data if isinstance(data, dict) else {}

    def valid_text(value, limit):
        return isinstance(value, str) and 0 < len(value.strip()) <= limit

    @app.before_request
    def identify_visitor():
        if request.path.startswith("/api/") and request.path != "/api/join":
            with lock:
                user = users.get(session.get("user_id"))
                if user is None:
                    return jsonify(error="Enter your name to join."), 401
                user["last_seen"] = monotonic()

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.post("/api/join")
    def join():
        name = json_body().get("name")
        if not valid_text(name, 40):
            return jsonify(error="Enter a name between 1 and 40 characters."), 400
        name = name.strip()
        with lock:
            existing = users.get(session.get("user_id"))
            if existing:
                existing["last_seen"] = monotonic()
                return jsonify(id=existing["id"], name=existing["name"])
            if any(u["name"].casefold() == name.casefold() for u in users.values()):
                return jsonify(error="That name is taken. Choose another name."), 409
            user_id = token_hex(16)
            users[user_id] = {"id": user_id, "name": name, "last_seen": monotonic()}
            session["user_id"] = user_id
        return jsonify(id=user_id, name=name), 201

    @app.get("/api/users")
    def get_users():
        with lock:
            # Keep offline identities for conversation history, but mark presence.
            visitors = [{"id": u["id"], "name": u["name"],
                         "online": monotonic() - u["last_seen"] < 30}
                        for u in users.values()]
        return jsonify(me=session["user_id"], users=visitors)

    @app.get("/api/messages")
    def get_messages():
        user_id = session["user_id"]
        with lock:
            return jsonify([m for m in messages
                            if user_id in (m["sender_id"], m["recipient_id"])])

    @app.post("/api/messages")
    def post_message():
        data = json_body()
        text = data.get("text")
        recipient = data.get("recipient_id")
        if not valid_text(text, 1000):
            return jsonify(error="Message must be between 1 and 1,000 characters."), 400
        if not isinstance(recipient, str):
            return jsonify(error="Choose a person to message."), 400
        with lock:
            if recipient not in users or recipient == session["user_id"]:
                return jsonify(error="Choose another visitor to message."), 400
            message = {"id": len(messages) + 1, "sender_id": session["user_id"],
                       "recipient_id": recipient, "text": text.strip(),
                       "created_at": datetime.now(timezone.utc).isoformat()}
            messages.append(message)
        return jsonify(message), 201

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(error):
        return jsonify(error="Request body must be at most 16 KiB."), 413

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
