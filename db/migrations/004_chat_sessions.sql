-- 004: conversations persisted for the HTTP API.
-- Contains personal data (customer messages, emails): keep retention short. See
-- PostgresSessionStore.purge_older_than and docs/phases/09-api-widget-docker.md.

CREATE TABLE chat_sessions (
    id          TEXT PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Optimistic locking: an update only succeeds if nobody saved in between.
    version     INTEGER NOT NULL DEFAULT 1,
    turn_count  INTEGER NOT NULL DEFAULT 0,
    messages    JSONB NOT NULL DEFAULT '[]'::jsonb,
    state       JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX chat_sessions_updated_idx ON chat_sessions (updated_at);
