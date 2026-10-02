"""Per-job control flags and the exceptions that stop a job."""

import subprocess
import threading
from typing import Literal

StopReason = Literal["paused", "cancelled"]


class JobStopped(Exception):
    """Raised inside a runner when the job was paused or cancelled."""

    def __init__(self, reason: StopReason) -> None:
        super().__init__(reason)
        self.reason = reason


class TransientError(Exception):
    """A failure worth retrying, with an optional delay the server asked for."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class JobControl:
    def __init__(self) -> None:
        self.stop_reason: StopReason | None = None
        self.event = threading.Event()
        self.process: subprocess.Popen[bytes] | None = None

    def request(self, reason: StopReason) -> None:
        if self.stop_reason is None:
            self.stop_reason = reason
        self.event.set()

    def check(self) -> None:
        if self.stop_reason is not None:
            raise JobStopped(self.stop_reason)

    def sleep(self, seconds: float) -> None:
        """Sleep, waking early when the job is stopped."""
        if self.event.wait(seconds):
            self.check()
