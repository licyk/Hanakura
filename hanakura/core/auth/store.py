"""Where OAuth credentials live.

They are kept apart from ``settings.toml``: the settings API returns the whole settings file to
the browser, and a refresh token must never travel with it. The operating system's credential
store is preferred; where there is none, a file in the data directory is used, created before
anything is written to it and readable only by its owner.
"""

import json
import logging
import os
import stat
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import Field

from hanakura.core.auth.models import OAuthAccount
from hanakura.core.record import Record

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "hanakura"
KEYRING_USERNAME = "civitai-oauth"
FILE_NAME = "civitai_oauth.json"


class OAuthCredentials(Record):
    """One token pair. Rotated as a whole: the provider invalidates the old pair on refresh."""

    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    scope: int | None = None
    client_id: str | None = None
    account: OAuthAccount = Field(default_factory=OAuthAccount)
    obtained_at: datetime | None = None

    def expires_within(self, seconds: float) -> bool:
        if self.expires_at is None:
            return False
        return (self.expires_at - datetime.now(tz=timezone.utc)).total_seconds() <= seconds


class CredentialStore(ABC):
    @abstractmethod
    def load(self) -> OAuthCredentials | None: ...

    @abstractmethod
    def save(self, credentials: OAuthCredentials) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Where credentials are kept, for the settings page and the log."""


class FileCredentialStore(CredentialStore):
    """A private file in the data directory.

    The file is not encrypted: a key shipped with the application would protect nothing. It is
    created with owner-only permissions, and a file that is readable by others is reported.
    """

    def __init__(self, data_dir: Path) -> None:
        self.directory = data_dir / "credentials"
        self.path = self.directory / FILE_NAME

    def load(self) -> OAuthCredentials | None:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except (OSError, ValueError):
            return None
        try:
            self._warn_if_readable()
            return OAuthCredentials.model_validate_json(raw)
        except ValueError:
            logger.warning("Ignoring unreadable OAuth credentials at %s", self.path)
            return None

    def save(self, credentials: OAuthCredentials) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(self.directory, 0o700)
        # Written through a private temporary file, so the token is never briefly world-readable.
        fd, tmp = tempfile.mkstemp(dir=self.directory, prefix=".civitai_oauth", suffix=".tmp")
        try:
            os.write(fd, credentials.model_dump_json().encode("utf-8"))
        finally:
            os.close(fd)
        if os.name != "nt":
            os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    def _warn_if_readable(self) -> None:
        if os.name == "nt":
            return
        mode = self.path.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            logger.warning("%s can be read by other users; fix it with: chmod 600 %s", self.path, self.path)

    @property
    def description(self) -> str:
        return f"file {self.path}"


class KeyringCredentialStore(CredentialStore):
    """The operating system's credential store, through the optional ``keyring`` package."""

    def __init__(self, keyring_module: Any) -> None:
        self._keyring = keyring_module

    def load(self) -> OAuthCredentials | None:
        raw = self._keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        if not raw:
            return None
        try:
            return OAuthCredentials.model_validate_json(raw)
        except ValueError:
            logger.warning("Ignoring unreadable OAuth credentials in the system credential store")
            return None

    def save(self, credentials: OAuthCredentials) -> None:
        self._keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, credentials.model_dump_json())

    def clear(self) -> None:
        try:
            self._keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
        except Exception:
            logger.debug("No OAuth credentials to delete from the system credential store", exc_info=True)

    @property
    def description(self) -> str:
        return "the system credential store"


def open_store(data_dir: Path, use_keyring: bool = True) -> CredentialStore:
    """Return the best store available: the system one when it works, else a private file."""
    if use_keyring:
        try:
            import keyring

            backend = keyring.get_keyring()
            # A keyring that fails on use is worse than a file, so it is tried once here.
            keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
            logger.debug("Using the system credential store (%s)", type(backend).__name__)
            return KeyringCredentialStore(keyring)
        except Exception as e:  # noqa: BLE001 - any failure falls back to the file store
            logger.debug("No usable system credential store (%s); using a file", e)
    return FileCredentialStore(data_dir)


class CredentialLock:
    """A lock shared by every process using this data directory, so two do not refresh at once.

    The provider rotates the token pair on refresh, so a second refresh with the old token would
    fail and could lose the pair. Within one process a thread lock is enough; the file makes it
    work between the server and the command line too.
    """

    def __init__(self, data_dir: Path, stale_after: float = 30.0) -> None:
        self.path = data_dir / "credentials" / ".civitai_oauth.lock"
        self.stale_after = stale_after
        self._thread_lock = threading.RLock()

    # typing.Self needs Python 3.11; this package supports 3.10.
    def __enter__(self) -> "CredentialLock":  # noqa: PYI034
        self._thread_lock.acquire()
        try:
            self._acquire_file()
        except BaseException:
            self._thread_lock.release()
            raise
        return self

    def __exit__(self, *_exc: object) -> None:
        try:
            self.path.unlink(missing_ok=True)
        finally:
            self._thread_lock.release()

    def _acquire_file(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.stale_after
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                if self._is_stale():
                    logger.info("Breaking a stale credential lock at %s", self.path)
                    self.path.unlink(missing_ok=True)
                    continue
                if time.monotonic() > deadline:
                    logger.warning("Waited too long for the credential lock; continuing without it")
                    return
                time.sleep(0.05)
                continue
            except OSError as e:
                logger.debug("Could not take the credential lock (%s); continuing without it", e)
                return
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "at": datetime.now(tz=timezone.utc).isoformat()}, f)
            return

    def _is_stale(self) -> bool:
        try:
            return time.time() - self.path.stat().st_mtime > self.stale_after
        except OSError:
            return False
