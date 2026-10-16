# Python CI/CD chat project

A small Python 3.12 Flask chat application with pytest, Docker, and GitHub Actions.
Enter a display name at http://localhost:5000, then choose someone in the left
sidebar to start a direct conversation. Try a second browser or an incognito
window for a second person: tabs in the same browser share an identity cookie.
JavaScript checks presence and messages every two seconds without a page refresh.
The sidebar shows online visitors first, offline visitors below, and unread badges.
Presence expires after 30 seconds without a request; closing a tab is not instant.
Names remain reserved until restart so a new visitor cannot take over an old name.
The layout adapts to narrow screens and uses no external fonts or UI libraries.

## Run locally

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest
python app.py
```

Open http://localhost:5000. Stop the server with Ctrl+C.

## Run with Docker

```bash
docker build -t python-ci-cd:v1 .
docker run --rm -p 5000:5000 python-ci-cd:v1
```

Open http://localhost:5000. Flask listens on `0.0.0.0:5000` in the container;
`-p 5000:5000` maps your host port to that container port. Stop with Ctrl+C.

## API

- `GET /health`: returns `{"status": "ok"}`.
- `POST /api/join`: accepts `{"name": "Alice"}` and sets a signed HttpOnly session
  cookie. Names must be unique (case-insensitive); duplicates return HTTP 409.
- `GET /api/users`: returns your ID and visitors with online/offline presence.
  Requests from your session also act as a heartbeat.
- `GET /api/messages`: returns only messages sent by or addressed to your session,
  oldest first. Other visitors cannot retrieve your conversation through this API.
- `POST /api/messages`: accepts `{"recipient_id": "<visitor ID>", "text": "Hello"}`
  and returns the stored message with its ID and UTC timestamp (HTTP 201).
  The sender comes from the session cookie, not from user-supplied JSON.

All API endpoints except join require the session cookie (HTTP 401 otherwise).

```bash
curl http://localhost:5000/health
curl -c /tmp/gather-alice.cookies -X POST http://localhost:5000/api/join -H 'Content-Type: application/json' -d '{"name":"Alice"}'
curl -b /tmp/gather-alice.cookies http://localhost:5000/api/users
# Have another visitor join, then use their ID from the users response:
curl -b /tmp/gather-alice.cookies -X POST http://localhost:5000/api/messages -H 'Content-Type: application/json' -d '{"recipient_id":"REPLACE_WITH_VISITOR_ID","text":"Hello"}'
curl -b /tmp/gather-alice.cookies http://localhost:5000/api/messages
```

Names and messages must be non-empty strings after trimming surrounding
whitespace. Names allow up to 40 characters; messages allow up to 1,000.
Invalid input returns JSON with HTTP 400; bodies over 16 KiB return HTTP 413.
The browser renders user input with `textContent`, so HTML is displayed as text.

## Learning project limits

Messages are stored only in server memory. They disappear when the server
restarts, along with visitor identities and name reservations, and are **not shared between multiple server processes or containers**.
Use one process/container for this demo. A lock keeps writes ordered within that
process. The message list grows until restart; it has no persistence or history
limit. This demo uses Flask's development server and has no authentication or
rate limiting. Display names are temporary identities, not verified accounts.
Messages are filtered by session, but are not end-to-end encrypted. Clearing your
browser cookies loses access to that identity and its history. It is intended for local learning, not public production hosting.

GitHub Actions keeps separate test and Docker build jobs. The build runs after
the pytest job succeeds. No external services or API credentials are needed.
