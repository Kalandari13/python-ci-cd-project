from unittest.mock import patch

import pytest

from app import create_app


@pytest.fixture
def app():
    app = create_app()
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def join(client, name='Alice'):
    response = client.post('/api/join', json={'name': name})
    assert response.status_code == 201
    return response.json['id']


def test_page_health_and_assets(client):
    assert b'Display name' in client.get('/').data
    assert client.get('/health').json == {'status': 'ok'}
    for path in ('/static/chat.js', '/static/style.css'):
        assert client.get(path).status_code == 200


@pytest.mark.parametrize('method,path', [('get', '/api/users'), ('get', '/api/messages'), ('post', '/api/messages')])
def test_name_required(client, method, path):
    assert getattr(client, method)(path).status_code == 401


@pytest.mark.parametrize('name', ['', '  ', 42, None, [], 'x' * 41])
def test_invalid_names(client, name):
    assert client.post('/api/join', json={'name': name}).status_code == 400


def test_names_unique_and_cookie_restores_identity(app, client):
    user_id = join(client, ' Alice ')
    assert client.get('/api/users').json['me'] == user_id
    other = app.test_client()
    assert other.post('/api/join', json={'name': 'alice'}).status_code == 409
    response = client.post('/api/join', json={'name': 'New name'})
    assert response.json == {'id': user_id, 'name': 'Alice'}
    assert client.get('/api/users').json['users'][0]['name'] == 'Alice'


def test_presence_expiration_and_return(app, client):
    with patch('app.monotonic', return_value=100):
        alice = join(client)
        other = app.test_client()
        join(other, 'Bob')
    with patch('app.monotonic', return_value=131):
        users = other.get('/api/users').json['users']
        assert next(u for u in users if u['id'] == alice)['online'] is False
        assert next(u for u in users if u['name'] == 'Bob')['online'] is True
        client.get('/api/users')
        assert all(u['online'] for u in other.get('/api/users').json['users'])


def test_direct_messages_are_ordered_and_private(app, client):
    alice = join(client)
    bob_client = app.test_client()
    bob = join(bob_client, 'Bob')
    eve = app.test_client()
    join(eve, 'Eve')
    for sender, recipient, text in [(client, bob, ' Hello '), (bob_client, alice, 'Hi')]:
        response = sender.post('/api/messages', json={'recipient_id': recipient, 'text': text})
        assert response.status_code == 201
        assert response.json['created_at'].endswith('+00:00')
    messages = client.get('/api/messages').json
    assert [m['text'] for m in messages] == ['Hello', 'Hi']
    assert [m['id'] for m in messages] == [1, 2]
    assert messages == bob_client.get('/api/messages').json
    assert eve.get('/api/messages').json == []
    # A query parameter cannot impersonate another session.
    assert eve.get(f'/api/messages?user_id={alice}').json == []
    response = client.post('/api/messages', json={'recipient_id': bob, 'text': 'Real sender', 'sender_id': 'forged'})
    assert response.json['sender_id'] == alice


@pytest.mark.parametrize('text', [None, '', ' ', 42, [], 'a' * 1001])
def test_invalid_messages(app, client, text):
    join(client)
    bob = join(app.test_client(), 'Bob')
    assert client.post('/api/messages', json={'recipient_id': bob, 'text': text}).status_code == 400
    assert client.get('/api/messages').json == []


@pytest.mark.parametrize('recipient', [None, [], {}, 'missing'])
def test_invalid_recipient(client, recipient):
    join(client)
    assert client.post('/api/messages', json={'recipient_id': recipient, 'text': 'Hi'}).status_code == 400


def test_self_message_rejected(client):
    user_id = join(client)
    assert client.post('/api/messages', json={'recipient_id': user_id, 'text': 'Hi'}).status_code == 400


def test_limits_and_html_preserved_as_text(app, client):
    join(client, 'a' * 40)
    bob = join(app.test_client(), '<script>alert(1)</script>')
    assert client.post('/api/messages', json={'recipient_id': bob, 'text': 'x' * 1000}).status_code == 201
    payload = '<img src=x onerror=alert(1)>'
    response = client.post('/api/messages', json={'recipient_id': bob, 'text': payload})
    assert response.json['text'] == payload


@pytest.mark.parametrize('body,content_type', [('{"name":', 'application/json'), ('hello', 'text/plain'), ('[]', 'application/json')])
def test_malformed_join(client, body, content_type):
    assert client.post('/api/join', data=body, content_type=content_type).status_code == 400


def test_request_size_limit(client):
    assert client.post('/api/join', json={'name': 'x' * 17000}).status_code == 413


def test_restart_clears_identity(client):
    join(client)
    restarted = create_app().test_client()
    cookie = client.get_cookie('session')
    restarted.set_cookie('session', cookie.value)
    assert restarted.get('/api/users').status_code == 401
