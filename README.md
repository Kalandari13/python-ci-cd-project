# Gather chat

Flask and PostgreSQL accounts, friend requests, private messages, and groups.

## Run

Keep your existing `.env` and secrets. For a new checkout only, copy `.env.example`
to `.env`, choose strong credentials and a random `FLASK_SECRET_KEY`, and set
`DATABASE_URL` to match `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB`.
Use hostname `db` and port `5432` in that URL; URL-encode special password characters.

```sh
docker compose up -d --build
```

Open http://localhost:5000. Create two accounts using separate browser profiles
or an incognito window (tabs share session cookies). Passwords require 10–128
characters. Open Friends, search for the other account's exact username, and send
a request. The recipient accepts it in Friends. Click Message next to a friend
to open a private conversation. Create groups under Groups and invite accepted
friends; recipients must join before they can read or send group messages.
Choose a conversation in Messages to read and send messages, including emojis.
The app refreshes lists and messages every four seconds while the page is visible.

Accounts and messages survive web-container restarts. PostgreSQL uses a named
volume; do not remove it if you want to retain data. New empty volumes initialize
from `db/schema.sql`. Existing volumes are not automatically migrated.

## API

All POST requests require `Content-Type: application/json`; empty actions use `{}`.
Except registration and login, social/account endpoints require a signed session.

| Method | Path | Input or behavior |
| --- | --- | --- |
| POST | `/api/register`, `/api/login` | `{ "username": "Alice", "password": "..." }` |
| POST | `/api/logout` | Clears browser session |
| GET | `/api/me` | Current account ID and username |
| GET | `/api/users/search?username=Alice` | Exact case-insensitive username; excludes self |
| GET | `/api/friends` | Accepted friends |
| GET/POST | `/api/friend-requests` | List pending requests / send `{ "user_id": "..." }` |
| POST | `/api/friend-requests/<id>/accept` or `/reject` | Recipient only; pending requests only |
| GET | `/api/conversations` | Current member's conversations |
| POST | `/api/conversations/direct` | `{ "user_id": "..." }`; accepted friend only; reuses existing chat |
| POST | `/api/conversations/groups` | `{ "name": "..." }`; creates group with owner membership |
| GET | `/api/conversations/<id>/members` | Members only |
| GET/POST | `/api/conversations/<id>/messages` | Members only; read with `?after=0` / send `{ "text": "..." }` |
| POST | `/api/conversations/<id>/invitations` | Owner invites accepted friend with `{ "user_id": "..." }` |
| GET | `/api/group-invitations` | Incoming pending invitations |
| POST | `/api/group-invitations/<id>/accept` or `/reject` | Invitee only; joining grants membership |
| GET | `/health`, `/health/db` | Process/database health |

Rejected friend requests and group invitations cannot be resent to the same
pair/group. Lists are capped at 500; message reads return at most 100 per cursor
page, and the browser loads more during polling. The legacy anonymous join and
in-memory messaging endpoints have been removed.

## Verification

Tests require PostgreSQL and `DATABASE_URL`; each test rolls back its data.
Run `node tests/check_frontend.cjs` for the DOM/API contract smoke check (no browser
installation required). This does not replace interactive browser testing.
CI creates a dedicated PostgreSQL service. To test with the running container:

```sh
tar -cf /tmp/gather-tests.tar tests db
docker compose exec -T web sh -c 'mkdir -p /tmp/gather-check; tar -xf - -C /tmp/gather-check; PYTHONPATH=/app python -m pytest /tmp/gather-check/tests -q' < /tmp/gather-tests.tar
```

For native Python development, install `requirements.txt`, set `DATABASE_URL`
and `FLASK_SECRET_KEY` in the process environment, and run `python app.py` or
`python -m pytest`. The app does not automatically load `.env` outside Compose.

## Security and deployment limits

SQL uses bound parameters. Sender/actor identity comes from the session; private
resources require membership. Friendships require recipient acceptance and group
invitations require invitee acceptance. User content is rendered as text. APIs
reject cross-origin browser POSTs and non-JSON submissions; cookies are HttpOnly
and SameSite=Lax. Responses include CSP, frame restrictions, no-sniff headers,
and no-store caching for account data.

The app limits authentication to 20 requests per 60-second window per client
address and social writes/searches to 120 per window per account. Buckets are
stored in PostgreSQL and shared across workers and restarts; client identifiers
are hashed. Proxy headers are ignored. Tunnel visitors share an authentication rate-limit
bucket because their requests arrive through the same connector. No blocking/reporting,
account recovery, email verification, message retention policy, or end-to-end
encryption is implemented. Group owners cannot remove members yet.

Docker runs Gunicorn as an unprivileged user with a read-only app filesystem.
The database is isolated on an internal network. The optional backup service
creates checked PostgreSQL dumps in the existing
`postgres_backups` volume. Run one backup with:

```sh
docker compose --profile backup run --rm backup --once
```

Existing backup files and volumes are retained. The normal stack has only web and
db; an already running backup service can be stopped with `docker compose stop backup`.
Never run `docker compose down -v`, remove the PostgreSQL volume, or change the
Compose project name when reusing your data. Backups have no automatic deletion.

## Temporary sharing

Install `cloudflared` separately if needed. Gather does not install or start it.
Keep the local stack running, then in a separate terminal run:

```sh
cloudflared tunnel --url http://localhost:5000
```

Copy the exact HTTPS URL it prints (no path) and configure the web container in
another terminal. Replace the example hostname with your generated hostname:

```sh
PUBLIC_ORIGIN=https://your-generated-host.trycloudflare.com SESSION_COOKIE_SECURE=false docker compose up -d --no-deps web
```

This overrides environment values for that command without editing `.env`.
Localhost and the exact configured origin can both make browser API requests.
Other origins remain blocked; forwarded host, scheme, and client IP headers are
not trusted. Cookies are host-only, HttpOnly, and SameSite=Lax. Separate hosts
have separate sessions, so log in again at the tunnel URL. `Secure=false` keeps
HTTP localhost usable alongside HTTPS sharing; the public connection uses HTTPS.
For a sharing-only session, set `SESSION_COOKIE_SECURE=true` in the command and
use the HTTPS URL exclusively. Restore false when returning to HTTP localhost.

Share only the generated HTTPS URL. Anyone who obtains it can reach registration
and attempt login; there is no email allowlist or Access gate. Authentication and
conversation membership still protect messages. This is a temporary learning
setup with no account recovery, moderation, or end-to-end encryption. Cloudflare
terminates public TLS. Quick Tunnels have no uptime guarantee and change hostname
on each run; see [Cloudflare documentation](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

Stop sharing with Ctrl-C in the cloudflared terminal, then clear the extra origin:

```sh
PUBLIC_ORIGIN= SESSION_COOKIE_SECURE=false docker compose up -d --no-deps web
```

## Troubleshooting

```sh
docker compose ps
docker compose logs --tail=100 web db
curl --fail http://localhost:5000/health
curl --fail http://localhost:5000/health/db
```

A 403 during tunnel login usually means `PUBLIC_ORIGIN` differs from the current
URL. A 429 can mean the shared tunnel authentication bucket is exhausted; wait
one minute. Missing database tables on an older volume require an explicit,
reviewed additive schema update; restarting does not migrate existing volumes.
