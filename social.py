"""Database-backed friendships and conversations; every operation uses the session identity."""
from flask import Blueprint, jsonify, request, session
from psycopg.errors import UniqueViolation
from database import get_connection

social = Blueprint('social', __name__)


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def text(value, limit):
    return isinstance(value, str) and "\x00" not in value and 0 < len(value.strip()) <= limit


def rows(cursor):
    names = [column.name for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


@social.get('/api/users/search')
def search():
    username = request.args.get('username', '')
    if not text(username, 40):
        return jsonify(error='Enter an exact username (1–40 characters).'), 400
    with get_connection() as conn:
        result = rows(conn.execute(
            'SELECT id, username FROM users WHERE LOWER(username) = LOWER(%s) AND id <> %s',
            (username.strip(), session['user_id'])))
    return jsonify(users=result)


@social.get('/api/friends')
def friends():
    me = session['user_id']
    with get_connection() as conn:
        result = rows(conn.execute('''
            SELECT u.id, u.username FROM friendships f JOIN users u
            ON u.id = CASE WHEN f.requester_id = %s THEN f.addressee_id ELSE f.requester_id END
            WHERE %s IN (f.requester_id, f.addressee_id) AND f.status = 'accepted'
            ORDER BY LOWER(u.username) LIMIT 500
        ''', (me, me)))
    return jsonify(friends=result)


@social.get('/api/friend-requests')
def friend_requests():
    me = session['user_id']
    with get_connection() as conn:
        result = rows(conn.execute('''
            SELECT f.id, f.requester_id, f.addressee_id, u.username,
                   f.requester_id <> %s AS incoming
            FROM friendships f JOIN users u
            ON u.id = CASE WHEN f.requester_id = %s THEN f.addressee_id ELSE f.requester_id END
            WHERE %s IN (f.requester_id, f.addressee_id) AND f.status = 'pending'
            ORDER BY f.created_at DESC LIMIT 500
        ''', (me, me, me)))
    return jsonify(requests=result)


@social.post('/api/friend-requests')
def send_friend_request():
    target = body().get('user_id')
    me = session['user_id']
    if not text(target, 64) or target == me:
        return jsonify(error='Choose another account.'), 400
    # Rejected requests are final for this pair: no automatic repeat-request spam.
    try:
        with get_connection() as conn:
            if not conn.execute('SELECT id FROM users WHERE id = %s', (target,)).fetchone():
                return jsonify(error='Account not found.'), 404
            row = conn.execute('''INSERT INTO friendships (requester_id, addressee_id)
                                  VALUES (%s, %s) RETURNING id''', (me, target)).fetchone()
    except UniqueViolation:
        return jsonify(error='A request or friendship already exists for this account.'), 409
    return jsonify(id=row[0], status='pending'), 201


@social.post('/api/friend-requests/<int:request_id>/<action>')
def respond_friend_request(request_id, action):
    if action not in ('accept', 'reject'):
        return jsonify(error='Unknown action.'), 400
    status = 'accepted' if action == 'accept' else 'rejected'
    with get_connection() as conn:
        row = conn.execute('''UPDATE friendships SET status = %s, updated_at = NOW()
            WHERE id = %s AND addressee_id = %s AND status = 'pending' RETURNING id''',
            (status, request_id, session['user_id'])).fetchone()
    if not row:
        return jsonify(error='Pending request not found.'), 404
    return jsonify(id=row[0], status=status)


@social.get('/api/conversations')
def conversations():
    with get_connection() as conn:
        result = rows(conn.execute('''
            SELECT c.id, c.type, c.created_by, CASE WHEN c.type = 'group' THEN c.name ELSE
                (SELECT u.username FROM conversation_members cm JOIN users u ON u.id = cm.user_id
                 WHERE cm.conversation_id = c.id AND cm.user_id <> %s LIMIT 1) END AS name
            FROM conversations c JOIN conversation_members m ON m.conversation_id = c.id
            WHERE m.user_id = %s ORDER BY c.id DESC LIMIT 500
        ''', (session['user_id'], session['user_id'])))
    return jsonify(conversations=result)


@social.post('/api/conversations/direct')
def direct_conversation():
    me = session['user_id']
    target = body().get('user_id')
    if not text(target, 64) or target == me:
        return jsonify(error='Choose a friend.'), 400
    with get_connection() as conn:
        # Lock the unique friendship pair to serialize concurrent creation.
        friend = conn.execute('''SELECT id FROM friendships WHERE status = 'accepted'
            AND ((requester_id = %s AND addressee_id = %s)
              OR (requester_id = %s AND addressee_id = %s)) FOR UPDATE''',
            (me, target, target, me)).fetchone()
        if not friend:
            return jsonify(error='Only accepted friends can start a conversation.'), 403
        existing = conn.execute('''SELECT c.id FROM conversations c
            JOIN conversation_members a ON a.conversation_id = c.id AND a.user_id = %s
            JOIN conversation_members b ON b.conversation_id = c.id AND b.user_id = %s
            WHERE c.type = 'direct' LIMIT 1''', (me, target)).fetchone()
        if existing:
            return jsonify(id=existing[0]), 200
        cid = conn.execute("INSERT INTO conversations (type, created_by) VALUES ('direct', %s) RETURNING id", (me,)).fetchone()[0]
        conn.execute('INSERT INTO conversation_members (conversation_id, user_id) VALUES (%s, %s), (%s, %s)', (cid, me, cid, target))
    return jsonify(id=cid), 201


@social.post('/api/conversations/groups')
def create_group():
    name = body().get('name')
    if not text(name, 100):
        return jsonify(error='Group name must be 1–100 characters.'), 400
    with get_connection() as conn:
        cid = conn.execute("INSERT INTO conversations (type, name, created_by) VALUES ('group', %s, %s) RETURNING id", (name.strip(), session['user_id'])).fetchone()[0]
        conn.execute("INSERT INTO conversation_members (conversation_id, user_id, role) VALUES (%s, %s, 'owner')", (cid, session['user_id']))
    return jsonify(id=cid), 201


@social.get('/api/conversations/<int:cid>/members')
def members(cid):
    with get_connection() as conn:
        if not conn.execute('SELECT 1 FROM conversation_members WHERE conversation_id = %s AND user_id = %s', (cid, session['user_id'])).fetchone():
            return jsonify(error='Conversation not found.'), 404
        result = rows(conn.execute('''SELECT u.id, u.username, m.role FROM conversation_members m
            JOIN users u ON u.id = m.user_id WHERE m.conversation_id = %s ORDER BY u.username''', (cid,)))
    return jsonify(members=result)


@social.get('/api/conversations/<int:cid>/messages')
def messages(cid):
    try:
        after = int(request.args.get('after', '0'))
        if not 0 <= after <= 9223372036854775807:
            raise ValueError
    except ValueError:
        return jsonify(error='Invalid message cursor.'), 400
    with get_connection() as conn:
        if not conn.execute('SELECT 1 FROM conversation_members WHERE conversation_id = %s AND user_id = %s', (cid, session['user_id'])).fetchone():
            return jsonify(error='Conversation not found.'), 404
        result = rows(conn.execute('''SELECT m.id, m.sender_id, u.username, m.body AS text, m.created_at
            FROM messages m JOIN users u ON u.id = m.sender_id
            WHERE m.conversation_id = %s AND m.id > %s ORDER BY m.id LIMIT 100''', (cid, after)))
    return jsonify(messages=result)


@social.post('/api/conversations/<int:cid>/messages')
def send_message(cid):
    value = body().get('text')
    if not text(value, 1000):
        return jsonify(error='Message must be 1–1,000 characters.'), 400
    with get_connection() as conn:
        if not conn.execute('SELECT 1 FROM conversation_members WHERE conversation_id = %s AND user_id = %s', (cid, session['user_id'])).fetchone():
            return jsonify(error='Conversation not found.'), 404
        row = conn.execute('''INSERT INTO messages (conversation_id, sender_id, body)
            VALUES (%s, %s, %s) RETURNING id''', (cid, session['user_id'], value.strip())).fetchone()
    return jsonify(id=row[0]), 201


@social.post('/api/conversations/<int:cid>/invitations')
def invite(cid):
    target = body().get('user_id')
    me = session['user_id']
    if not text(target, 64) or target == me:
        return jsonify(error='Choose a friend.'), 400
    with get_connection() as conn:
        # Serialize invitations for this group; only its owner can invite.
        group = conn.execute("SELECT id FROM conversations WHERE id = %s AND type = 'group' AND created_by = %s FOR UPDATE", (cid, me)).fetchone()
        if not group:
            return jsonify(error='Group not found or you are not its owner.'), 404
        friend = conn.execute('''SELECT 1 FROM friendships WHERE status = 'accepted'
            AND ((requester_id = %s AND addressee_id = %s) OR (requester_id = %s AND addressee_id = %s))''', (me, target, target, me)).fetchone()
        if not friend:
            return jsonify(error='You can only invite accepted friends.'), 403
        if conn.execute('SELECT 1 FROM conversation_members WHERE conversation_id = %s AND user_id = %s', (cid, target)).fetchone() or conn.execute('SELECT 1 FROM group_invitations WHERE conversation_id = %s AND invitee_id = %s', (cid, target)).fetchone():
            return jsonify(error='This friend is already a member or has been invited.'), 409
        iid = conn.execute('''INSERT INTO group_invitations (conversation_id, inviter_id, invitee_id)
            VALUES (%s, %s, %s) RETURNING id''', (cid, me, target)).fetchone()[0]
    return jsonify(id=iid), 201


@social.get('/api/group-invitations')
def invitations():
    with get_connection() as conn:
        result = rows(conn.execute('''SELECT i.id, c.name, u.username FROM group_invitations i
            JOIN conversations c ON c.id = i.conversation_id JOIN users u ON u.id = i.inviter_id
            WHERE i.invitee_id = %s AND i.status = 'pending' ORDER BY i.id DESC LIMIT 500''', (session['user_id'],)))
    return jsonify(invitations=result)


@social.post('/api/group-invitations/<int:iid>/<action>')
def respond_invitation(iid, action):
    if action not in ('accept', 'reject'):
        return jsonify(error='Unknown action.'), 400
    with get_connection() as conn:
        row = conn.execute("SELECT conversation_id FROM group_invitations WHERE id = %s AND invitee_id = %s AND status = 'pending' FOR UPDATE", (iid, session['user_id'])).fetchone()
        if not row:
            return jsonify(error='Pending invitation not found.'), 404
        if action == 'accept':
            conn.execute('INSERT INTO conversation_members (conversation_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING', (row[0], session['user_id']))
        conn.execute('UPDATE group_invitations SET status = %s WHERE id = %s', ('accepted' if action == 'accept' else 'rejected', iid))
    return jsonify(status='accepted' if action == 'accept' else 'rejected')
