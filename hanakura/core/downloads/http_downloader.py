"""Stream one file over HTTP into ``<name>.part``, with resume, hashing and an atomic rename."""

import hashlib
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from hanakura.core.downloads.job import JobControl, TransientError
from hanakura.core.errors import AuthRequiredError, ConflictError, HanakuraError, InvalidPathError, NotFoundError, SourceError
from hanakura.core.library.fsops import rename_no_overwrite
from hanakura.core.library.safety import validate_name
from hanakura.core.sources.base import parse_retry_after
from hanakura.core.sources.models import DownloadRequest

CHUNK_SIZE = 1024 * 1024
_CONTENT_RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+|\*)")


class HashMismatchError(HanakuraError):
    code = "hash_mismatch"


@dataclass
class HttpState:
    """The parts of the job the downloader reads and updates."""

    dest_dir: Path
    file_name: str | None
    etag: str | None
    initial_total: int | None
    expected_sha256: str | None
    overwrite: bool
    bytes_done: int = 0
    total_bytes: int | None = None
    sha256: str | None = None
    final_path: Path | None = None


def sanitize_file_name(name: str, fallback: str = "download.bin") -> str:
    name = unquote(name).replace("\\", "/").split("/")[-1]
    name = re.sub(r'[\x00-\x1f\x7f<>:"|?*]', "_", name).strip().strip(".")
    try:
        return validate_name(name)
    except InvalidPathError:
        return fallback


def file_name_from_headers(response: httpx.Response) -> str | None:
    cd = response.headers.get("Content-Disposition", "")
    match = re.search(r"filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)", cd)
    if match:
        return sanitize_file_name(match.group(1).strip().strip('"'))
    match = re.search(r'filename\s*=\s*"([^"]+)"', cd) or re.search(r"filename\s*=\s*([^;]+)", cd)
    if match:
        raw = match.group(1).strip()
        try:
            # Servers often send UTF-8 bytes in a latin-1 header.
            raw = raw.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        return sanitize_file_name(raw)
    return None


def file_name_from_url(url: str) -> str | None:
    path = urlparse(url).path
    name = path.rstrip("/").split("/")[-1]
    return sanitize_file_name(name) if name else None


def _classify_status(response: httpx.Response, what: str) -> None:
    status = response.status_code
    if status in (200, 206):
        return
    if status == 429 or status >= 500:
        raise TransientError(f"{what}: HTTP {status}", parse_retry_after(response.headers.get("Retry-After")))
    if status in (401, 403):
        raise AuthRequiredError(f"{what}: HTTP {status}. The file may need a token for this source.")
    if status == 404:
        raise NotFoundError(f"{what}: not found")
    raise SourceError(f"{what}: HTTP {status}")


def http_download(
    client: httpx.Client,
    request: DownloadRequest,
    state: HttpState,
    control: JobControl,
    on_progress: Callable[[HttpState], None],
    on_name: Callable[[HttpState], None] | None = None,
) -> HttpState:
    """Download ``request`` into ``state.dest_dir``. Raises JobStopped, TransientError or a domain error."""
    state.dest_dir.mkdir(parents=True, exist_ok=True)
    part: Path | None = state.dest_dir / f"{state.file_name}.part" if state.file_name else None
    offset = part.stat().st_size if part is not None and part.exists() else 0
    headers = dict(request.headers)
    if offset:
        headers["Range"] = f"bytes={offset}-"
        if state.etag:
            headers["If-Range"] = state.etag
    control.check()
    try:
        with client.stream("GET", request.url, headers=headers, follow_redirects=True) as response:
            if response.status_code == 416 and part is not None:
                # Our partial file does not fit the remote one: start again.
                part.unlink(missing_ok=True)
                raise TransientError("Range not satisfiable; restarting from zero", 0)
            _classify_status(response, "Download")

            if state.file_name is None:
                state.file_name = (
                    file_name_from_headers(response) or request.file_name and sanitize_file_name(request.file_name) or file_name_from_url(str(response.url)) or "download.bin"
                )
                part = state.dest_dir / f"{state.file_name}.part"
                if on_name is not None:
                    on_name(state)
            assert part is not None
            final = state.dest_dir / state.file_name
            if final.exists() and not state.overwrite:
                raise ConflictError(f"Target exists: {final.name}", {"target": str(final)})

            digest = hashlib.sha256()
            total: int | None
            if response.status_code == 206 and offset:
                match = _CONTENT_RANGE.match(response.headers.get("Content-Range", ""))
                remote_total = int(match.group(3)) if match and match.group(3) != "*" else None
                start_ok = match is not None and int(match.group(1)) == offset
                # Without a validator, resume only when the remote size equals the size seen when the job began.
                same_file = bool(state.etag) or (remote_total is not None and remote_total == state.initial_total)
                if not (start_ok and same_file):
                    part.unlink(missing_ok=True)
                    raise TransientError("Remote file changed; restarting from zero", 0)
                total = remote_total
                with open(part, "rb") as f:
                    while chunk := f.read(CHUNK_SIZE):
                        digest.update(chunk)
                mode = "ab"
            else:
                offset = 0
                length = response.headers.get("Content-Length")
                total = int(length) if length and length.isdigit() else request.size
                mode = "wb"
                state.etag = response.headers.get("ETag") or None
                state.initial_total = total

            state.total_bytes = total
            state.bytes_done = offset
            on_progress(state)
            with open(part, mode) as f:
                # Chunks as they arrive, so cancel and progress react without waiting for a large buffer.
                for chunk in response.iter_bytes():
                    control.check()
                    f.write(chunk)
                    digest.update(chunk)
                    state.bytes_done += len(chunk)
                    on_progress(state)
                f.flush()
                os.fsync(f.fileno())
    except httpx.TransportError as e:
        raise TransientError(f"Network error: {e}") from e

    if state.total_bytes is not None and state.bytes_done != state.total_bytes:
        raise TransientError(f"Connection ended at {state.bytes_done} of {state.total_bytes} bytes")
    state.sha256 = digest.hexdigest()
    if state.expected_sha256 and state.sha256 != state.expected_sha256.lower():
        part.unlink(missing_ok=True)
        raise HashMismatchError(f"SHA256 mismatch: expected {state.expected_sha256}, got {state.sha256}")
    final = state.dest_dir / state.file_name
    if state.overwrite:
        os.replace(part, final)
    else:
        rename_no_overwrite(part, final)
    state.final_path = final
    return state


def wait_backoff(control: JobControl, attempt: int, retry_after: float | None) -> None:
    delay = retry_after if retry_after is not None else min(60.0, 2.0**attempt)
    control.sleep(min(delay, 300.0))
