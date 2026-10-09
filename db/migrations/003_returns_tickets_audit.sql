-- 003: the only data the assistant writes: return requests, support tickets, audit log.

CREATE TABLE return_requests (
    id               TEXT PRIMARY KEY,                -- RR-XXXXXXXX
    order_id         INTEGER NOT NULL REFERENCES orders (id),
    -- Same order + same items + same prior-return state => same key. A retried or duplicated
    -- confirmation can never create a second return.
    idempotency_key  TEXT NOT NULL UNIQUE,
    items            JSONB NOT NULL,                  -- [{"line_no": 1, "quantity": 1}]
    reason           TEXT NOT NULL CHECK (reason IN ('doesnt_fit', 'not_as_expected',
                                                     'changed_mind', 'other')),
    reason_details   TEXT,
    status           TEXT NOT NULL DEFAULT 'requested'
                     CHECK (status IN ('requested', 'received', 'refunded', 'rejected')),
    session_id       TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX return_requests_order_idx ON return_requests (order_id);

CREATE TABLE support_tickets (
    id              TEXT PRIMARY KEY,                 -- HT-XXXXXXXX
    session_id      TEXT NOT NULL,
    reason          TEXT NOT NULL,
    priority        TEXT NOT NULL CHECK (priority IN ('normal', 'high')),
    summary         TEXT NOT NULL,
    order_id        INTEGER REFERENCES orders (id),
    order_verified  BOOLEAN NOT NULL DEFAULT false,
    customer_email  TEXT,
    language        TEXT,
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- At most one open ticket per conversation: repeated handoffs update it (idempotent).
CREATE UNIQUE INDEX support_tickets_one_open_per_session
    ON support_tickets (session_id) WHERE status = 'open';

CREATE TABLE audit_log (
    id           BIGSERIAL PRIMARY KEY,
    occurred_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    session_id   TEXT NOT NULL,
    action       TEXT NOT NULL,
    entity_id    TEXT,
    payload      JSONB NOT NULL
);
CREATE INDEX audit_log_session_idx ON audit_log (session_id, occurred_at);
