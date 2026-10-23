CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username VARCHAR(40) NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS users_username_unique
ON users (LOWER(username));


CREATE TABLE IF NOT EXISTS friendships (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    requester_id TEXT NOT NULL REFERENCES users(id),
    addressee_id TEXT NOT NULL REFERENCES users(id),
    status VARCHAR(10) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT different_friendship_users
        CHECK (requester_id <> addressee_id),

    CONSTRAINT valid_friendship_status
        CHECK (status IN ('pending', 'accepted', 'rejected'))
);

CREATE UNIQUE INDEX IF NOT EXISTS unique_friendship_pair
ON friendships (
    LEAST(requester_id, addressee_id),
    GREATEST(requester_id, addressee_id)
);


CREATE TABLE IF NOT EXISTS conversations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    type VARCHAR(10) NOT NULL,
    name VARCHAR(100),
    created_by TEXT REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT valid_conversation_type
        CHECK (type IN ('direct', 'group')),

    CONSTRAINT group_requires_name
        CHECK (type <> 'group' OR NULLIF(BTRIM(name), '') IS NOT NULL)
);


CREATE TABLE IF NOT EXISTS conversation_members (
    conversation_id BIGINT NOT NULL REFERENCES conversations(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    role VARCHAR(10) NOT NULL DEFAULT 'member',
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (conversation_id, user_id),

    CONSTRAINT valid_member_role
        CHECK (role IN ('owner', 'admin', 'member'))
);


CREATE TABLE IF NOT EXISTS group_invitations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversations(id),
    inviter_id TEXT NOT NULL REFERENCES users(id),
    invitee_id TEXT NOT NULL REFERENCES users(id),
    status VARCHAR(10) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT different_invitation_users
        CHECK (inviter_id <> invitee_id),

    CONSTRAINT valid_invitation_status
        CHECK (status IN ('pending', 'accepted', 'rejected'))
);


CREATE TABLE IF NOT EXISTS messages (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversations(id),
    sender_id TEXT NOT NULL REFERENCES users(id),
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT valid_message_body
        CHECK (char_length(body) BETWEEN 1 AND 1000),

    CONSTRAINT sender_is_conversation_member
        FOREIGN KEY (conversation_id, sender_id)
        REFERENCES conversation_members(conversation_id, user_id)
);

CREATE INDEX IF NOT EXISTS messages_conversation_idx
ON messages (conversation_id, created_at, id);

CREATE INDEX IF NOT EXISTS conversation_members_user_idx
ON conversation_members (user_id);

-- Shared across Gunicorn workers, with hashed client identifiers.
CREATE TABLE IF NOT EXISTS rate_limits (
    key TEXT PRIMARY KEY,
    window_start TIMESTAMPTZ NOT NULL,
    requests INTEGER NOT NULL CHECK (requests > 0)
);
CREATE INDEX IF NOT EXISTS rate_limits_window_start_idx ON rate_limits(window_start);
