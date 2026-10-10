"""Access control for the public demo: HTTP Basic Auth, a login throttle and a daily cap.

These guard a demo deployment against bots and runaway API spending (ADR 0022). They are
not customer authentication: the assistant's own authorisation (order number + email,
checked inside the tools) is unchanged.

Author: Ignacio Rodríguez Caro
"""

from __future__ import annotations

import base64
import binascii
import logging
import secrets
import time
from collections.abc import Callable, Iterable
from datetime import date

from quilora.db import Database

log = logging.getLogger("quilora.access")

Scope = dict
Receive = Callable
Send = Callable


class LoginThrottle:
    """Blocks a client after too many wrong passwords within a time window.

    In memory and per process: enough for a single small instance. A restart clears it,
    which only gives an attacker a few more guesses; the password itself is the real defence.
    """

    def __init__(self, max_failures: int = 10, window_s: float = 900.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.max_failures = max_failures
        self.window_s = window_s
        self._clock = clock
        self._failures: dict[str, list[float]] = {}

    def _recent(self, key: str) -> list[float]:
        cutoff = self._clock() - self.window_s
        recent = [t for t in self._failures.get(key, []) if t > cutoff]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def retry_after(self, key: str) -> int:
        """Seconds until `key` may try again; 0 if it is not blocked."""
        recent = self._recent(key)
        if len(recent) < self.max_failures:
            return 0
        return max(1, int(recent[0] + self.window_s - self._clock()) + 1)

    def record_failure(self, key: str) -> None:
        """Count one wrong password for `key`."""
        self._recent(key)
        self._failures.setdefault(key, []).append(self._clock())

    def reset(self, key: str) -> None:
        """Forget the failures of `key` after a successful login."""
        self._failures.pop(key, None)


def _parse_basic(header: bytes | None) -> tuple[str, str] | None:
    """Decode an `Authorization: Basic ...` header into (username, password)."""
    if not header:
        return None
    scheme, _, encoded = header.decode("latin-1").partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return None
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    username, sep, password = decoded.partition(":")
    return (username, password) if sep else None


class BasicAuthMiddleware:
    """ASGI middleware that puts the whole site (widget and API) behind one login.

    Browsers show their native username/password dialog on the 401 challenge and then send
    the credentials with every same-origin request, including the widget's API calls.
    """

    def __init__(self, app, username: str, password: str, *,
                 exempt_paths: Iterable[str] = ("/healthz",),
                 throttle: LoginThrottle | None = None,
                 realm: str = "Assistant demo") -> None:
        self.app = app
        self._username = username.encode("utf-8")
        self._password = password.encode("utf-8")
        self.exempt_paths = frozenset(exempt_paths)
        self.throttle = throttle or LoginThrottle()
        self.realm = realm

    def _valid(self, creds: tuple[str, str]) -> bool:
        # Compare both fields in constant time and without short-circuiting, so timing does
        # not reveal whether the username alone was right.
        user_ok = secrets.compare_digest(creds[0].encode("utf-8"), self._username)
        pass_ok = secrets.compare_digest(creds[1].encode("utf-8"), self._password)
        return user_ok & pass_ok

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        # With `uvicorn --proxy-headers` the client address comes from X-Forwarded-For.
        client = (scope.get("client") or ("unknown", 0))[0]
        wait = self.throttle.retry_after(client)
        if wait:
            await _plain(send, 429, "Too many failed logins. Try again later.\n",
                         [(b"retry-after", str(wait).encode())])
            return

        header = dict(scope.get("headers") or []).get(b"authorization")
        creds = _parse_basic(header)
        if creds is not None and self._valid(creds):
            self.throttle.reset(client)
            await self.app(scope, receive, send)
            return

        if header is not None:  # the first, credential-less request is not a failure
            self.throttle.record_failure(client)
            log.warning("failed demo login from %s", client)
        challenge = f'Basic realm="{self.realm}", charset="UTF-8"'.encode()
        await _plain(send, 401, "Authentication required.\n",
                     [(b"www-authenticate", challenge)])


async def _plain(send: Send, status: int, body: str,
                 headers: list[tuple[bytes, bytes]]) -> None:
    payload = body.encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(payload)).encode()),
                    (b"cache-control", b"no-store"), *headers],
    })
    await send({"type": "http.response.body", "body": payload})


def consume_daily_message(db: Database, day: date, limit: int) -> bool:
    """Count one customer message for `day`; False once `limit` messages were already used.

    A single atomic upsert, so concurrent requests cannot both take the last slot. When the
    limit is reached the conditional update matches no row and nothing is returned.
    """
    with db.connection() as conn:
        row = conn.execute(
            "INSERT INTO daily_usage (day, messages) VALUES (%s, 1)"
            " ON CONFLICT (day) DO UPDATE SET messages = daily_usage.messages + 1"
            " WHERE daily_usage.messages < %s"
            " RETURNING messages",
            (day, limit),
        ).fetchone()
    return row is not None
