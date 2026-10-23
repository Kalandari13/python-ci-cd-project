"""Account and social integration tests against PostgreSQL; every test rolls back."""
import os
from contextlib import contextmanager
from pathlib import Path
from secrets import token_hex
from unittest.mock import patch

import pytest
import psycopg

os.environ.setdefault('FLASK_SECRET_KEY', 'test-only-secret-do-not-deploy')
import app as application
import social
import security
from database import get_connection


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv('FLASK_SECRET_KEY', token_hex(32))
    with get_connection() as conn:
        try:
            conn.execute(Path(__file__).resolve().parents[1].joinpath('db/schema.sql').read_text())

            @contextmanager
            def connection():
                with conn.transaction():
                    yield conn

            monkeypatch.setattr(application, 'get_connection', connection)
            monkeypatch.setattr(social, 'get_connection', connection)
            monkeypatch.setattr(security, 'get_connection', connection)
            instance = application.create_app()
            instance.config['TESTING'] = True
            instance.test_connection = conn
            yield instance
        finally:
            conn.rollback()


@pytest.fixture
def client(app):
    return app.test_client()


def register(app, label='User'):
    client = app.test_client()
    name = label + token_hex(8)
    response = client.post('/api/register', json={'username': name, 'password': 'test-password-123'})
    assert response.status_code == 201
    return client, response.json


@pytest.fixture
def people(app):
    return [register(app, label) for label in ('Alice', 'Bob', 'Eve')]


def befriend(people):
    (alice, a), (bob, b), _ = people
    response = alice.post('/api/friend-requests', json={'user_id': b['id']})
    assert response.status_code == 201
    rid = response.json['id']
    assert bob.post(f'/api/friend-requests/{rid}/accept', json={}).status_code == 200
    return a, b


def direct(people):
    befriend(people)
    response = people[0][0].post('/api/conversations/direct', json={'user_id': people[1][1]['id']})
    assert response.status_code == 201
    return response.json['id']


def test_page_health_and_assets(client):
    assert b'friend-search' in client.get('/').data
    assert client.get('/health').json == {'status': 'ok'}
    assert client.get('/health/db').status_code == 200
    for path in ('/static/chat.js', '/static/style.css'):
        assert client.get(path).status_code == 200
    assert "frame-ancestors 'none'" in client.get('/').headers['Content-Security-Policy']
    assert client.get('/api/me').headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('path', ['/api/me', '/api/users/search?username=Alice', '/api/friends',
    '/api/friend-requests', '/api/conversations', '/api/group-invitations',
    '/api/conversations/1/messages', '/api/conversations/1/members'])
def test_authentication_required(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize('username,password', [('', 'valid-password'), ('bad\x00name', 'valid-password'), ('x'*41, 'valid-password'),
    (None, 'valid-password'), ([], 'valid-password'), ('Alice', 'short'), ('Alice', 'x'*129)])
def test_registration_validation(client, username, password):
    assert client.post('/api/register', json={'username': username, 'password': password}).status_code == 400


def test_authentication_and_restart(app):
    client, user = register(app)
    assert client.get('/api/me').json == user
    stored = app.test_connection.execute('SELECT password_hash FROM users WHERE id = %s', (user['id'],)).fetchone()[0]
    assert stored != 'test-password-123'
    assert application.check_password_hash(stored, 'test-password-123')
    assert app.test_client().post('/api/register', json={'username': user['username'].upper(), 'password': 'valid-password'}).status_code == 409
    assert client.post('/api/logout', json={}).status_code == 200
    assert client.get('/api/me').status_code == 401
    assert client.post('/api/login', json={'username': user['username'], 'password': 'wrong'}).status_code == 401
    assert client.post('/api/login', json={'username': user['username'].upper(), 'password': 'test-password-123'}).status_code == 200
    restarted = application.create_app().test_client()
    restarted.set_cookie('session', client.get_cookie('session').value)
    assert restarted.get('/api/me').json == user


def test_stale_session(client):
    with client.session_transaction() as session:
        session['user_id'] = 'nonexistent'
    assert client.get('/api/friends').status_code == 401
    with client.session_transaction() as session:
        assert 'user_id' not in session


def test_exact_private_search(people):
    (alice, a), (_, b), _ = people
    result = alice.get('/api/users/search', query_string={'username': '  '+b['username'].upper()+'  '}).json
    assert result == {'users': [b]}
    assert alice.get('/api/users/search', query_string={'username': b['username'][:3]}).json == {'users': []}
    assert alice.get('/api/users/search', query_string={'username': a['username']}).json == {'users': []}
    assert alice.get('/api/users/search', query_string={'username': "' OR 1=1 --"}).json == {'users': []}
    assert alice.get('/api/users/search?username=').status_code == 400


def test_request_permissions_duplicates_and_acceptance(people):
    (alice, a), (bob, b), (eve, _) = people
    rid = alice.post('/api/friend-requests', json={'user_id': b['id'], 'requester_id': 'forged'}).json['id']
    assert alice.get('/api/friend-requests').json['requests'][0]['incoming'] is False
    assert bob.get('/api/friend-requests').json['requests'][0]['incoming'] is True
    assert eve.get('/api/friend-requests').json == {'requests': []}
    assert bob.post('/api/friend-requests', json={'user_id': a['id']}).status_code == 409
    assert alice.post(f'/api/friend-requests/{rid}/accept', json={}).status_code == 404
    assert eve.post(f'/api/friend-requests/{rid}/accept', json={}).status_code == 404
    assert bob.post(f'/api/friend-requests/{rid}/accept', json={}).status_code == 200
    assert bob.post(f'/api/friend-requests/{rid}/reject', json={}).status_code == 404
    assert alice.get('/api/friends').json == {'friends': [b]}
    assert bob.get('/api/friends').json == {'friends': [a]}


def test_rejection_and_invalid_targets(people):
    (alice, a), (bob, b), _ = people
    assert alice.post('/api/friend-requests', json={'user_id': a['id']}).status_code == 400
    assert alice.post('/api/friend-requests', json={'user_id': []}).status_code == 400
    assert alice.post('/api/friend-requests', json={'user_id': 'missing'}).status_code == 404
    rid = alice.post('/api/friend-requests', json={'user_id': b['id']}).json['id']
    assert bob.post(f'/api/friend-requests/{rid}/reject', json={}).status_code == 200
    assert alice.get('/api/friends').json == {'friends': []}
    assert alice.post('/api/friend-requests', json={'user_id': b['id']}).status_code == 409


def test_messages_private_persistent_and_sender_not_forgeable(people, app):
    (alice, a), (bob, b), (eve, e) = people
    assert alice.post('/api/conversations/direct', json={'user_id': b['id']}).status_code == 403
    cid = direct(people)
    assert bob.post('/api/conversations/direct', json={'user_id': a['id']}).json['id'] == cid
    assert alice.get('/api/conversations').json['conversations'][0]['name'] == b['username']
    assert eve.get('/api/conversations').json == {'conversations': []}
    for suffix in ('messages', 'members'):
        assert eve.get(f'/api/conversations/{cid}/{suffix}').status_code == 404
    assert eve.post(f'/api/conversations/{cid}/messages', json={'text': 'attack'}).status_code == 404
    payload = '<img src=x onerror=alert(1)> 👋'
    assert alice.post(f'/api/conversations/{cid}/messages', json={'text': payload, 'sender_id': e['id']}).status_code == 201
    message = bob.get(f'/api/conversations/{cid}/messages').json['messages'][0]
    assert message['text'] == payload
    assert message['sender_id'] == a['id']
    assert bob.get(f'/api/conversations/{cid}/messages?after={message["id"]}').json == {'messages': []}
    assert bob.get(f'/api/conversations/{cid}/messages?after=bad').status_code == 400
    restarted = application.create_app().test_client()
    restarted.set_cookie('session', alice.get_cookie('session').value)
    assert restarted.get(f'/api/conversations/{cid}/messages').json['messages'][0]['text'] == payload


@pytest.mark.parametrize('value', ['', ' ', None, [], 'a'*1001, 'bad\x00message'])
def test_message_validation(people, value):
    cid = direct(people)
    assert people[0][0].post(f'/api/conversations/{cid}/messages', json={'text': value}).status_code == 400


def test_group_invitation_consent_and_permissions(people):
    (alice, a), (bob, b), (eve, e) = people
    befriend(people)
    cid = alice.post('/api/conversations/groups', json={'name': 'Test group'}).json['id']
    assert alice.post(f'/api/conversations/{cid}/invitations', json={'user_id': e['id']}).status_code == 403
    iid = alice.post(f'/api/conversations/{cid}/invitations', json={'user_id': b['id']}).json['id']
    assert alice.post(f'/api/conversations/{cid}/invitations', json={'user_id': b['id']}).status_code == 409
    assert bob.get(f'/api/conversations/{cid}/messages').status_code == 404
    assert alice.post(f'/api/group-invitations/{iid}/accept', json={}).status_code == 404
    assert eve.post(f'/api/group-invitations/{iid}/accept', json={}).status_code == 404
    assert len(bob.get('/api/group-invitations').json['invitations']) == 1
    assert bob.post(f'/api/group-invitations/{iid}/accept', json={}).status_code == 200
    assert bob.post(f'/api/group-invitations/{iid}/accept', json={}).status_code == 404
    assert bob.post(f'/api/conversations/{cid}/messages', json={'text': 'hello group'}).status_code == 201
    assert len(alice.get(f'/api/conversations/{cid}/members').json['members']) == 2
    assert bob.post(f'/api/conversations/{cid}/invitations', json={'user_id': e['id']}).status_code == 404
    assert eve.get(f'/api/conversations/{cid}/messages').status_code == 404


def test_declined_invitation_does_not_grant_access(people):
    (alice, _), (bob, b), _ = people
    befriend(people)
    cid = alice.post('/api/conversations/groups', json={'name': 'Test group'}).json['id']
    iid = alice.post(f'/api/conversations/{cid}/invitations', json={'user_id': b['id']}).json['id']
    assert bob.post(f'/api/group-invitations/{iid}/reject', json={}).status_code == 200
    assert bob.get(f'/api/conversations/{cid}/messages').status_code == 404


@pytest.mark.parametrize('headers', [{'Origin': 'https://evil.example'}, {'Sec-Fetch-Site': 'cross-site'}, {'Origin': 'null'}])
def test_cross_origin_blocked(client, headers):
    assert client.post('/api/login', json={}, headers=headers).status_code == 403


def test_json_required_limits_and_same_origin(client):
    assert client.post('/api/login', data='username=alice').status_code == 415
    assert client.post('/api/login', json={}, headers={'Origin': 'http://localhost'}).status_code == 401
    assert client.post('/api/register', json={'username': 'x'*17000}).status_code == 413
    for _ in range(18):
        client.post('/api/login', json={})
    response = client.post('/api/login', json={})
    assert response.status_code == 429
    assert response.headers['Retry-After'] == '60'


def test_database_outage_json(client):
    with patch.object(application, 'get_connection', side_effect=psycopg.OperationalError('test outage')):
        response = client.post('/api/login', json={'username': 'Alice', 'password': 'test-password'})
    assert response.status_code == 503
    assert 'temporarily unavailable' in response.json['error']


@pytest.mark.parametrize('path', ['/api/friend-requests', '/api/conversations/direct',
    '/api/conversations/groups', '/api/conversations/1/messages',
    '/api/conversations/1/invitations', '/api/friend-requests/1/accept',
    '/api/group-invitations/1/accept'])
def test_write_authentication_required(client, path):
    assert client.post(path, json={}).status_code == 401


def test_identifier_bounds_and_public_origin(client, monkeypatch):
    assert client.get('/api/conversations/9999999999999999999999999/messages').status_code == 400
    client.application.config['PUBLIC_ORIGIN'] = 'https://gather.example'
    assert client.post('/api/login', json={}, headers={'Origin': 'https://gather.example'}).status_code == 401
    assert client.post('/api/login', json={}, headers={'Origin': 'https://other.example'}).status_code == 403


def test_social_rate_limit(people):
    alice = people[0][0]
    for _ in range(120):
        assert alice.get('/api/users/search?username=nobody').status_code == 200
    assert alice.get('/api/users/search?username=nobody').status_code == 429



def test_rate_limit_shared_across_app_instances(app, client):
    for _ in range(20):
        assert client.post('/api/login', json={}).status_code == 401
    other_worker = application.create_app().test_client()
    assert other_worker.post('/api/login', json={}).status_code == 429
    # A proxy-header forgery cannot create a new bucket in normal local mode.
    assert other_worker.post('/api/login', json={}, headers={
        'CF-Connecting-IP': '203.0.113.1', 'X-Forwarded-For': '203.0.113.2'}).status_code == 429


def test_rate_limit_expiry(app):
    with app.app_context():
        for _ in range(2):
            assert security.allow_request('test', 'expiry-test', 2)
        assert not security.allow_request('test', 'expiry-test', 2)
        import hashlib
        import hmac
        key = hmac.new(app.secret_key.encode(), b'test:expiry-test', hashlib.sha256).hexdigest()
        app.test_connection.execute("UPDATE rate_limits SET window_start = clock_timestamp() - INTERVAL '61 seconds' WHERE key = %s", (key,))
        assert security.allow_request('test', 'expiry-test', 2)



def test_tunnel_and_local_sessions(app):
    origin = 'https://example.trycloudflare.com'
    app.config['PUBLIC_ORIGIN'] = origin
    client = app.test_client()
    response = client.post('/api/register', base_url=origin, headers={'Origin': origin},
                           json={'username': 'Tunnel'+token_hex(8), 'password': 'test-password-123'})
    assert response.status_code == 201
    assert 'HttpOnly' in response.headers['Set-Cookie']
    assert 'SameSite=Lax' in response.headers['Set-Cookie']
    assert client.get('/api/me', base_url=origin).json == response.json
    assert client.post('/api/logout', base_url=origin, headers={'Origin': origin}, json={}).status_code == 200
    assert client.post('/api/login', headers={'Origin': 'http://localhost:5000'}, json={}).status_code == 401
    assert client.post('/api/login', base_url='https://evil.example',
                       headers={'Origin': 'https://evil.example'}, json={}).status_code == 403


@pytest.mark.parametrize('origin', ['http://example.com', 'https://example.com/path', 'https://user@example.com', 'https://example.com?x=1'])
def test_invalid_public_origin(monkeypatch, origin):
    monkeypatch.setenv('PUBLIC_ORIGIN', origin)
    with pytest.raises(ValueError, match='PUBLIC_ORIGIN'):
        application.create_app()
