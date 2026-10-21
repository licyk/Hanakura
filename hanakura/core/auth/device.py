"""Device sign-in: the user approves on any device, and the server asks Civitai for the result.

It serves a browser on another machine than the server, and the command line, where no callback
can reach Hanakura. The device code stays on the server. One background thread per session does
the polling, so a page asking for the session's state, however often and from however many tabs,
never adds a request to Civitai. It honours the interval Civitai gives, adds five seconds on a 429
(Civitai's way of saying slow down) or a ``slow_down`` error, retries network failures and server
errors until the code's own deadline, and stops at once on denial, expiry or cancellation.
"""

import logging
import threading
from collections.abc import Callable

from hanakura.core.auth.clients import ResolvedClient
from hanakura.core.auth.models import SessionStatus
from hanakura.core.auth.oauth_client import CivitaiOAuthClient, reason_of
from hanakura.core.auth.store import OAuthCredentials
from hanakura.core.auth.transactions import Transaction, TransactionStore
from hanakura.core.errors import HanakuraError

logger = logging.getLogger(__name__)

# Sign-ins waiting on a device at once, per data directory; each costs Civitai a request every few seconds.
MAX_DEVICE_SESSIONS = 4
SLOW_DOWN_STEP = 5.0
MAX_RETRY_DELAY = 60.0

# Waits on the event for up to the given seconds; True when the event was set. Tests replace it with a clock.
Wait = Callable[[threading.Event, float], bool]


def _wait(event: threading.Event, seconds: float) -> bool:
    return event.wait(max(0.0, seconds))


class DevicePoller:
    def __init__(
        self,
        store: TransactionStore,
        client_for: Callable[[ResolvedClient], CivitaiOAuthClient],
        commit: Callable[[Transaction, OAuthCredentials], None],
        wait: Wait | None = None,
    ) -> None:
        self.store = store
        self._client_for = client_for
        self._commit = commit
        self._wait = wait or _wait
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}

    def start(self, transaction: Transaction) -> None:
        thread = threading.Thread(target=self._run, args=(transaction,), name=f"hanakura-civitai-device-{transaction.id[:6]}", daemon=True)
        with self._lock:
            self._threads[transaction.id] = thread
        thread.start()

    def close(self, timeout: float = 5.0) -> None:
        """Cancel every device sign-in and wait for the polling to stop."""
        self.store.cancel_all(error="The server stopped before the sign-in finished.", keep=lambda t: t.flow != "device")
        with self._lock:
            threads = list(self._threads.values())
        for thread in threads:
            thread.join(timeout)

    def _run(self, transaction: Transaction) -> None:
        try:
            self._poll(transaction)
        except Exception:  # a thread that dies silently would leave the session pending forever
            logger.exception("The Civitai device sign-in failed unexpectedly")
            self.store.finish(transaction, "failed", "failed", "The sign-in failed unexpectedly.")
        finally:
            with self._lock:
                self._threads.pop(transaction.id, None)

    def _poll(self, transaction: Transaction) -> None:
        client = self._client_for(transaction.client)
        delay = transaction.interval
        failures = 0
        while True:
            remaining = transaction.deadline - self.store.clock()
            if self._wait(transaction.cancelled, min(delay, max(remaining, 0.0))) or transaction.finished:
                return
            if self.store.clock() >= transaction.deadline:
                self.store.finish(transaction, "expired", "expired", "The code was not confirmed in time. Start again.")
                return
            try:
                result = client.poll_device(transaction.device_code or "")
            except HanakuraError as e:
                reason = reason_of(e)
                if reason == "network":
                    # Transient: try again, more slowly, until the code expires.
                    failures += 1
                    delay = min(transaction.interval * (2**failures), MAX_RETRY_DELAY)
                    logger.info("Polling Civitai for a device sign-in failed; retrying in %.0f s", delay)
                    continue
                status: SessionStatus = "denied" if reason == "denied" else "expired" if reason == "expired" else "failed"
                self.store.finish(transaction, status, reason, str(e))
                return
            failures = 0
            if result == "pending":
                delay = transaction.interval
                continue
            if result == "slow_down":
                transaction.interval += SLOW_DOWN_STEP
                delay = transaction.interval
                continue
            self._commit(transaction, result)
            return
