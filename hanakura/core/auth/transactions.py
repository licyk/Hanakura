"""Short-lived sign-in sessions, held in memory.

A session is created when the user starts an authorization and ends once: connected, refused,
expired, cancelled or failed. Each is bound to the browser that began it by a secret kept in an
HttpOnly cookie, so a callback nobody asked for, a replayed one, or a read from another browser is
refused; a session id alone grants nothing. It also carries a snapshot of the client it runs as,
so a configuration change cannot have an old code exchanged through a new client. Restarting the
server loses them, which only means the user starts again.
"""

import hashlib
import hmac
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from hanakura.core.auth.clients import Flow, ResolvedClient
from hanakura.core.auth.models import AuthErrorReason, LoginSession, SessionStatus
from hanakura.core.auth.oauth_client import DeviceAuthorization, make_verifier

DEFAULT_TTL_SECONDS = 300.0
MAX_TRANSACTIONS = 32
# A finished session stays readable this long, so the page that started it can learn the outcome.
RETAIN_FINISHED_SECONDS = 120.0
TERMINAL: frozenset[SessionStatus] = frozenset({"connected", "denied", "expired", "cancelled", "failed"})
# What secrets.token_urlsafe(32) produces; a cookie that looks like anything else is not reused.
_BINDING_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43,128}$")


@dataclass
class Transaction:
    id: str
    flow: Flow
    client: ResolvedClient
    binding_digest: str
    deadline: float
    expires_at: datetime
    return_to: str = "/#/settings"
    # Browser sign-in.
    state: str | None = None
    verifier: str | None = None
    redirect_uri: str | None = None
    # Device sign-in. The device code never leaves the server.
    device_code: str | None = None
    user_code: str | None = None
    verification_uri: str | None = None
    verification_uri_complete: str | None = None
    interval: float = 5.0
    status: SessionStatus = "pending"
    error: str | None = None
    error_code: AuthErrorReason | None = None
    finished_at: float | None = None
    # Set once the credentials are being stored; from then on only the committer may end the session.
    committing: bool = False
    # Set on cancellation, so a device poll waiting out its interval stops at once.
    cancelled: threading.Event = field(default_factory=threading.Event)
    # Set when the session ends, however it ends.
    done: threading.Event = field(default_factory=threading.Event)

    @property
    def scope(self) -> int:
        return self.client.scope

    @property
    def finished(self) -> bool:
        return self.status in TERMINAL

    def view(self) -> LoginSession:
        return LoginSession(
            id=self.id,
            flow=self.flow,
            status=self.status,
            expires_at=self.expires_at,
            user_code=self.user_code,
            verification_uri=self.verification_uri,
            verification_uri_complete=self.verification_uri_complete,
            error=self.error,
            error_code=self.error_code,
        )


def binding_digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class TransactionStore:
    def __init__(self, ttl: float = DEFAULT_TTL_SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl = ttl
        self.clock = clock
        self._lock = threading.Lock()
        self._items: dict[str, Transaction] = {}

    @staticmethod
    def binding(existing: str | None = None) -> str:
        """The browser-binding secret: the one the browser already holds, else a new one.

        Reusing it keeps two tabs, or two local instances sharing a cookie host, from overwriting
        each other's binding. A page on another site cannot set this cookie, so reuse grants nothing.
        """
        if existing and _BINDING_PATTERN.match(existing):
            return existing
        return secrets.token_urlsafe(32)

    def _new(self, client: ResolvedClient, flow: Flow, binding_secret: str, return_to: str, lifetime: float) -> Transaction:
        return Transaction(
            id=secrets.token_urlsafe(16),
            flow=flow,
            client=client,
            binding_digest=binding_digest(binding_secret),
            deadline=self.clock() + lifetime,
            expires_at=datetime.now(tz=timezone.utc) + timedelta(seconds=lifetime),
            return_to=return_to,
        )

    def _add(self, transaction: Transaction) -> Transaction:
        with self._lock:
            self._purge()
            while len(self._items) >= MAX_TRANSACTIONS:
                victims = [t for t in self._items.values() if t.finished] or list(self._items.values())
                oldest = min(victims, key=lambda t: t.deadline)
                self._finish(oldest, "cancelled", "cancelled", "Too many sign-ins were started at once.")
                del self._items[oldest.id]
            self._items[transaction.id] = transaction
        return transaction

    def create_browser(self, client: ResolvedClient, redirect_uri: str, return_to: str, binding_secret: str | None = None) -> tuple[Transaction, str]:
        """Create a browser sign-in. Returns it with the browser-binding secret for the cookie."""
        secret = self.binding(binding_secret)
        transaction = self._new(client, "browser", secret, return_to, self.ttl)
        transaction.state = secrets.token_urlsafe(24)
        transaction.verifier = make_verifier()
        transaction.redirect_uri = redirect_uri
        return self._add(transaction), secret

    def create_device(self, client: ResolvedClient, grant: DeviceAuthorization, return_to: str, binding_secret: str | None = None) -> tuple[Transaction, str]:
        """Record a device sign-in Civitai has granted a code for; it lasts as long as the code."""
        secret = self.binding(binding_secret)
        transaction = self._new(client, "device", secret, return_to, grant.expires_in)
        transaction.device_code = grant.device_code
        transaction.user_code = grant.user_code
        transaction.verification_uri = grant.verification_uri
        transaction.verification_uri_complete = grant.verification_uri_complete
        transaction.interval = grant.interval
        return self._add(transaction), secret

    # -- reading ------------------------------------------------------------

    def get(self, session_id: str, binding_secret: str | None) -> Transaction | None:
        """The session, only for the browser that started it."""
        with self._lock:
            self._purge()
            transaction = self._items.get(session_id)
        if transaction is None or not self._bound(transaction, binding_secret):
            return None
        return transaction

    def claim(self, state: str, binding_secret: str | None) -> Transaction | None:
        """Take the browser sign-in for ``state``, once. Returns None when it must be refused.

        A callback that names a live session but comes from another browser ends that session:
        whoever holds its state should not get a second try.
        """
        with self._lock:
            self._purge()
            transaction = next((t for t in self._items.values() if t.state == state and t.flow == "browser"), None) if state else None
            if transaction is None or transaction.status != "pending":
                return None
            if not self._bound(transaction, binding_secret):
                self._finish(transaction, "failed", "binding", "The authorization could not be matched to the browser that started it.")
                return None
            transaction.status = "exchanging"
            return transaction

    def deny(self, state: str, binding_secret: str | None, error_code: AuthErrorReason, error: str) -> Transaction | None:
        """End the browser sign-in for ``state`` after Civitai refused it, if it is this browser's."""
        with self._lock:
            transaction = next((t for t in self._items.values() if t.state == state and t.flow == "browser"), None) if state else None
            if transaction is None or not self._bound(transaction, binding_secret):
                return None
            self._finish(transaction, "denied" if error_code == "denied" else "failed", error_code, error)
            return transaction

    # -- ending -------------------------------------------------------------

    def begin_commit(self, transaction: Transaction) -> bool:
        """Claim an exchanging session for storing its credentials. False when it was cancelled first."""
        with self._lock:
            if transaction.status != "exchanging" or transaction.committing:
                return False
            transaction.committing = True
            return True

    def begin_exchange(self, transaction: Transaction) -> bool:
        """Move a session from waiting to exchanging, once. False when it already ended or moved."""
        with self._lock:
            if transaction.status != "pending":
                return False
            transaction.status = "exchanging"
            return True

    def finish(self, transaction: Transaction, status: SessionStatus, error_code: AuthErrorReason | None = None, error: str | None = None, committed: bool = False) -> bool:
        """End a session. False when it had already ended, or is being committed by someone else."""
        with self._lock:
            return self._finish(transaction, status, error_code, error, committed)

    def cancel(self, session_id: str, binding_secret: str | None) -> Transaction | None:
        """Cancel the session for the browser that started it. Cancelling an ended one changes nothing."""
        transaction = self.get(session_id, binding_secret)
        if transaction is not None:
            self.finish(transaction, "cancelled", "cancelled", "The sign-in was cancelled.")
        return transaction

    def cancel_all(self, error_code: AuthErrorReason = "cancelled", error: str = "The sign-in was cancelled.", keep: Callable[[Transaction], bool] | None = None) -> int:
        """End every unfinished session, except those ``keep`` spares. Returns how many ended."""
        with self._lock:
            ended = [t for t in self._items.values() if not t.finished and not t.committing and not (keep and keep(t))]
            for transaction in ended:
                self._finish(transaction, "cancelled", error_code, error)
        return len(ended)

    def active(self, flow: Flow | None = None) -> list[Transaction]:
        with self._lock:
            self._purge()
            return [t for t in self._items.values() if not t.finished and (flow is None or t.flow == flow)]

    def binding_in_use(self, binding_secret: str | None) -> bool:
        """Whether an unfinished session still needs this browser's binding cookie."""
        return bool(binding_secret) and any(self._bound(t, binding_secret) for t in self.active())

    @property
    def pending(self) -> int:
        return len(self.active())

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _bound(transaction: Transaction, binding_secret: str | None) -> bool:
        return bool(binding_secret) and hmac.compare_digest(binding_digest(binding_secret or ""), transaction.binding_digest)

    def _finish(self, transaction: Transaction, status: SessionStatus, error_code: AuthErrorReason | None, error: str | None, committed: bool = False) -> bool:
        if transaction.finished or (transaction.committing and not committed):
            return False
        transaction.status = status
        transaction.error_code = error_code
        transaction.error = error
        transaction.finished_at = self.clock()
        if status != "connected":
            transaction.cancelled.set()
        transaction.done.set()
        return True

    def _purge(self) -> None:
        now = self.clock()
        for key, transaction in list(self._items.items()):
            if transaction.status == "pending" and now > transaction.deadline:
                self._finish(transaction, "expired", "expired", "The sign-in took too long and expired. Start again.")
            if transaction.finished_at is not None and now - transaction.finished_at > RETAIN_FINISHED_SECONDS:
                del self._items[key]
