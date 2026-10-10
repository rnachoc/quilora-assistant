-- Author: Ignacio Rodríguez Caro
-- Daily message counter behind the public demo's spending guard (ADR 0022).
-- Kept in Postgres, not in memory, because a free host restarts the process whenever it
-- sleeps; an in-memory counter would reset every time.
CREATE TABLE IF NOT EXISTS daily_usage (
    day      DATE    PRIMARY KEY,
    messages INTEGER NOT NULL DEFAULT 0 CHECK (messages >= 0)
);
