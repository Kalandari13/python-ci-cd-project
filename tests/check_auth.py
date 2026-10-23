"""Run inside the web container: python < tests/check_auth.py.

Uses the real database, rolling back all test accounts on completion.
"""
from contextlib import contextmanager
from secrets import token_hex
from unittest.mock import patch

import psycopg
import app as application
import security
from database import get_connection


def check():
    with get_connection() as conn:
        try:
            @contextmanager
            def test_connection():
                # Each request gets a savepoint, so rejected duplicates don't
                # invalidate the outer transaction containing the test data.
                with conn.transaction():
                    yield conn

            # Start an outer transaction before request savepoints.
            conn.execute("SELECT 1")
            with patch.object(application, 'get_connection', test_connection), patch.object(security, 'get_connection', test_connection):
                app = application.create_app()
                app.config['TESTING'] = True
                client = app.test_client()
                name = 'auth_check_' + token_hex(8)
                password = token_hex(16)
                assert client.get('/api/me').status_code == 401
                assert client.post('/api/register', json={
                    'username': name, 'password': 'short'}).status_code == 400
                response = client.post('/api/register', json={
                    'username': name, 'password': password})
                assert response.status_code == 201, response.status_code
                identity = response.json
                assert client.get('/api/me').json == identity
                stored = conn.execute(
                    'SELECT password_hash FROM users WHERE id = %s',
                    (identity['id'],)).fetchone()[0]
                assert stored != password
                assert application.check_password_hash(stored, password)
                assert app.test_client().post('/api/register', json={
                    'username': name.upper(), 'password': password}).status_code == 409
                assert client.post('/api/logout', json={}).status_code == 200
                assert client.get('/api/me').status_code == 401
                assert client.post('/api/login', json={
                    'username': name, 'password': 'wrong'}).status_code == 401
                assert client.post('/api/login', json={
                    'username': name.upper(), 'password': password}).status_code == 200
                restored = application.create_app().test_client()
                restored.set_cookie('session', client.get_cookie('session').value)
                assert restored.get('/api/me').json == identity
                with patch.object(application, 'get_connection', side_effect=psycopg.OperationalError('test outage')):
                    app.logger.disabled = True
                    try:
                        response = client.post('/api/login', json={
                            'username': name, 'password': password})
                        assert response.status_code == 503
                        assert 'temporarily unavailable' in response.json['error']
                    finally:
                        app.logger.disabled = False
                print('PASS: registration, validation, password hashing, duplicate username, '
                      'logout, wrong password, case-insensitive login, session restoration, '
                      'and database outage response.')
        finally:
            conn.rollback()
            print('Rolled back test data; no test accounts retained.')


if __name__ == '__main__':
    check()
