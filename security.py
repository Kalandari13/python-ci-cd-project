"""Database-backed rate limiting shared across application workers."""
import hashlib
import hmac

from flask import current_app, request
from database import get_connection


def client_address():
    # Proxy headers are untrusted, including through a temporary tunnel.
    return request.remote_addr or 'unknown'


def allow_request(scope, actor, limit):
    key = hmac.new(current_app.secret_key.encode(), f'{scope}:{actor}'.encode(), hashlib.sha256).hexdigest()
    with get_connection() as conn:
        # A single UPSERT locks the bucket across all threads/workers/containers.
        # Old buckets expire lazily; an index also keeps cleanup bounded by age.
        conn.execute("DELETE FROM rate_limits WHERE window_start < clock_timestamp() - INTERVAL '2 minutes'")
        row = conn.execute('''
            INSERT INTO rate_limits (key, window_start, requests)
            VALUES (%s, clock_timestamp(), 1)
            ON CONFLICT (key) DO UPDATE SET
                requests = CASE WHEN rate_limits.window_start <= clock_timestamp() - INTERVAL '60 seconds'
                    THEN 1 ELSE LEAST(rate_limits.requests + 1, %s) END,
                window_start = CASE WHEN rate_limits.window_start <= clock_timestamp() - INTERVAL '60 seconds'
                    THEN clock_timestamp() ELSE rate_limits.window_start END
            RETURNING requests
        ''', (key, limit + 1)).fetchone()
    return row[0] <= limit
