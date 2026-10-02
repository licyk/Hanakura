"""Short-lived authorization transactions, held in memory.

One transaction is created when the user starts an authorization and claimed once when the
callback arrives. It ties the callback to the browser that began it, so a callback nobody asked
for, a replayed one, or one from another browser is refused. Restarting the server loses them,
which only means the user starts again.
"""

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass, field

DEFAULT_TTL_SECONDS = 300.0
MAX_TRANSACTIONS = 32


@dataclass
class Transaction:
    state: str
    verifier: str
    redirect_uri: str
    return_to: str
    binding_digest: str
    scope: int
    client_id: str
    created_at: float = field(default_factory=time.monotonic)


def binding_digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class TransactionStore:
    def __init__(self, ttl: float = DEFAULT_TTL_SECONDS) -> None:
        self.ttl = ttl
        self._lock = threading.Lock()
        self._items: dict[str, Transaction] = {}

    def create(self, redirect_uri: str, return_to: str, scope: int, client_id: str) -> tuple[Transaction, str]:
        """Create a transaction. Returns it with the browser-binding secret for the cookie."""
        from hanakura.core.auth.oauth_client import make_verifier

        secret = secrets.token_urlsafe(32)
        transaction = Transaction(
            state=secrets.token_urlsafe(24),
            verifier=make_verifier(),
            redirect_uri=redirect_uri,
            return_to=return_to,
            binding_digest=binding_digest(secret),
            scope=scope,
            client_id=client_id,
        )
        with self._lock:
            self._purge()
            if len(self._items) >= MAX_TRANSACTIONS:
                oldest = min(self._items.values(), key=lambda t: t.created_at)
                self._items.pop(oldest.state, None)
            self._items[transaction.state] = transaction
        return transaction, secret

    def claim(self, state: str, binding_secret: str | None) -> Transaction | None:
        """Take the transaction for ``state``, once. Returns None when it must be refused."""
        with self._lock:
            self._purge()
            transaction = self._items.pop(state, None)
        if transaction is None:
            return None
        if not binding_secret or not hmac.compare_digest(binding_digest(binding_secret), transaction.binding_digest):
            return None
        return transaction

    def discard(self, state: str) -> None:
        with self._lock:
            self._items.pop(state, None)

    @property
    def pending(self) -> int:
        with self._lock:
            self._purge()
            return len(self._items)

    def _purge(self) -> None:
        now = time.monotonic()
        for state, transaction in list(self._items.items()):
            if now - transaction.created_at > self.ttl:
                del self._items[state]
