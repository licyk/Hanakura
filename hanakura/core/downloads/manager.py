"""The download queue: one pool of worker threads for HTTP and hub jobs alike."""

import logging
import mimetypes
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from hanakura.core.db import Database
from hanakura.core.detection import DetectionService
from hanakura.core.downloads.http_downloader import HttpState, http_download, sanitize_file_name, wait_backoff
from hanakura.core.downloads.hub_runner import cleanup_incomplete, run_hub_download
from hanakura.core.downloads.job import JobControl, JobStopped, TransientError
from hanakura.core.downloads.models import FINISHED_STATES, DownloadCreate, DownloadJob, JobState
from hanakura.core.errors import AuthRequiredError, ConflictError, HanakuraError, InvalidPathError, NotFoundError, ValidationError
from hanakura.core.events import EventBus
from hanakura.core.events.models import (
    DownloadCancelledEvent,
    DownloadCompletedEvent,
    DownloadFailedEvent,
    DownloadPausedEvent,
    DownloadProgressEvent,
    DownloadQueuedEvent,
    DownloadRemovedEvent,
    DownloadStartedEvent,
)
from hanakura.core.hubs import HubRegistry
from hanakura.core.hubs.base import select_files
from hanakura.core.hubs.models import RepoFile
from hanakura.core.library import LibraryService, sidecar
from hanakura.core.library.safety import resolve_in_root, split_model_name, to_rel
from hanakura.core.net.http import HttpClientProvider
from hanakura.core.settings import SettingsService
from hanakura.core.sources import SourceRegistry
from hanakura.core.sources.models import DownloadRequest, ModelFile

logger = logging.getLogger(__name__)

PROGRESS_INTERVAL = 0.25  # at most four progress events per second per job
PERSIST_INTERVAL = 2.0
WEBUI_SD_VERSION = {"sd1": "SD1", "sd2": "SD2", "sdxl": "SDXL", "sdxl-refiner": "SDXL"}
_TAGS = re.compile(r"<[^>]+>")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DownloadManager:
    def __init__(
        self,
        settings: SettingsService,
        db: Database,
        events: EventBus,
        sources: SourceRegistry,
        hubs: HubRegistry,
        library: LibraryService,
        detection: DetectionService,
        http: HttpClientProvider,
        owned_only: bool = False,
    ) -> None:
        """Create the manager. With ``owned_only`` it runs only jobs created in this process (the CLI)."""
        self.settings = settings
        self.db = db
        self.events = events
        self.sources = sources
        self.hubs = hubs
        self.library = library
        self.detection = detection
        self.http = http
        self.owned_only = owned_only
        self._lock = threading.RLock()
        self._wake = threading.Condition(self._lock)
        self._live: dict[int, DownloadJob] = {}
        self._controls: dict[int, JobControl] = {}
        self._owned: set[int] = set()
        self._finished = threading.Condition(self._lock)
        self._threads: list[threading.Thread] = []
        self._stopping = False
        self._last_progress: dict[int, float] = {}
        self._last_persist: dict[int, float] = {}

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._threads:
                return
            if not self.owned_only:
                self._recover()
            self._stopping = False
            count = self.settings.settings.network.max_concurrent_downloads
            for i in range(count):
                t = threading.Thread(target=self._worker, name=f"download-{i}", daemon=True)
                t.start()
                self._threads.append(t)

    def _recover(self) -> None:
        """Jobs left running by a previous process become paused (HTTP) or failed (hub), never silently repeated."""
        for row in self.db.fetchall("SELECT data FROM download_jobs WHERE state = 'running'"):
            job = DownloadJob.model_validate_json(row["data"])
            if job.can_pause:
                job.state = "paused"
            else:
                job.state = "failed"
                job.error = "Interrupted by a restart; hub downloads start again from zero"
            self._save(job)

    def shutdown(self, timeout: float = 10.0) -> None:
        with self._lock:
            self._stopping = True
            for job_id, control in self._controls.items():
                job = self._live.get(job_id)
                control.request("paused" if job is not None and job.can_pause else "cancelled")
            self._wake.notify_all()
            threads = list(self._threads)
            self._threads.clear()
        for t in threads:
            t.join(timeout)

    # -- persistence ----------------------------------------------------------

    def _save(self, job: DownloadJob) -> None:
        data = job.model_dump_json(exclude={"speed", "can_pause"})
        self.db.execute(
            """INSERT INTO download_jobs(id, runner, source, state, data, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(id) DO UPDATE SET state = excluded.state, data = excluded.data, updated_at = excluded.updated_at""",
            (job.id, job.runner, job.source, job.state, data, job.created_at.isoformat()),
        )

    def _load(self, job_id: int) -> DownloadJob:
        with self._lock:
            live = self._live.get(job_id)
            if live is not None:
                return live
        row = self.db.fetchone("SELECT data FROM download_jobs WHERE id = ?", (job_id,))
        if row is None:
            raise NotFoundError(f"No download job {job_id}")
        return DownloadJob.model_validate_json(row["data"])

    def _next_id(self) -> int:
        row = self.db.fetchone("SELECT COALESCE(MAX(id), 0) + 1 AS n FROM download_jobs")
        return int(row["n"]) if row else 1

    # -- queries --------------------------------------------------------------

    def list_jobs(self) -> list[DownloadJob]:
        rows = self.db.fetchall("SELECT data FROM download_jobs ORDER BY id DESC")
        with self._lock:
            return [self._live.get(j.id, j) for j in (DownloadJob.model_validate_json(r["data"]) for r in rows)]

    def get(self, job_id: int) -> DownloadJob:
        return self._load(job_id)

    # -- creation -------------------------------------------------------------

    def _resolve_dest(self, req: DownloadCreate, kind: str | None) -> tuple[str | None, str, Path]:
        """Return ``(root_id, rel_dir, absolute dest dir)``."""
        if req.dest_dir:
            dest = Path(req.dest_dir).expanduser()
            if not dest.is_absolute():
                raise InvalidPathError("dest_dir must be absolute")
            dest = dest.resolve()
            try:
                root_id, rel = self.library.locate(dest)
            except NotFoundError:
                return None, "", dest
            return root_id, rel, dest
        destination = self.library.suggest_destination(kind, req.root_id, rel_dir=req.rel_dir)
        root_id = destination.root_id
        root_path = self.library.root_path(root_id)
        rel = req.rel_dir if req.rel_dir is not None else destination.rel_dir
        target = resolve_in_root(root_path, rel, follow_symlinks=self.library.follow_symlinks)
        return root_id, to_rel(root_path, target) if rel else "", target

    def create(self, req: DownloadCreate) -> DownloadJob:
        given = [x for x in (req.source_file, req.hub, req.url) if x]
        if len(given) != 1:
            raise ValidationError("Give exactly one of source_file, hub or url")
        meta: dict[str, Any] = {}
        kind: str | None = None
        title = req.title
        file_name = sanitize_file_name(req.file_name) if req.file_name else None
        expected = req.expected_sha256
        total: int | None = None
        if req.source_file:
            ref = req.source_file
            detail, file = self.sources.find_file(ref.source, ref.model_id, ref.version_id, ref.file_id, ref.file_name)
            version = next((v for v in detail.versions if any(f.id == file.id for f in v.files)), detail.versions[0])
            ref = ref.model_copy(update={"version_id": version.id, "file_id": file.id, "file_name": file.name})
            req = req.model_copy(update={"source_file": ref})
            # A Civitai checkpoint can ship its VAE as a separate file of type "VAE".
            kind = "vae" if file.kind == "VAE" else (detail.kind or None)
            title = title or f"{detail.name} — {version.name}"
            file_name = file_name or (sanitize_file_name(file.name) if file.name else None)
            expected = expected or file.sha256
            total = file.size
            preview = next((i.url for i in version.images if not i.is_video), None) or detail.preview_url
            meta = {
                "model_name": detail.name,
                "version_name": version.name,
                "kind": kind,
                "base_model": version.base_model or detail.base_model,
                "base_model_label": version.base_model_label or detail.base_model_label,
                "trained_words": version.trained_words,
                "preview_url": preview,
                "page_url": detail.page_url,
                "description": detail.description,
                "creator": detail.creator,
            }
        elif req.hub:
            adapter = self.hubs.get(req.hub.hub)
            files = select_files(adapter.list_files(req.hub.repo_id, req.hub.revision), req.hub.include, req.hub.exclude)
            if not files:
                raise ValidationError("The selection matches no files in the repository")
            total = sum(f.size or 0 for f in files) or None
            title = title or f"{req.hub.repo_id}" + (f" ({len(files)} files)" if len(files) > 1 else f" — {files[0].path}")
            meta = {"files": [f.model_dump() for f in files]}
        else:
            parsed = urlparse(req.url or "")
            if parsed.scheme not in ("http", "https"):
                raise ValidationError("Only http and https URLs can be downloaded")
            title = title or req.url

        root_id, rel_dir, dest = self._resolve_dest(req, kind)
        if req.hub and not req.overwrite:
            clashes = [f["path"] for f in meta["files"] if (dest / f["path"]).exists()]
            if clashes:
                raise ConflictError(f"Target exists: {clashes[0]}", {"targets": clashes})
        if file_name and not req.overwrite and (dest / file_name).exists():
            raise ConflictError(f"Target exists: {file_name}", {"target": str(dest / file_name)})

        existing = self._find_resumable(req, dest)
        if existing is not None:
            return self.resume(existing.id)

        with self._lock:
            job = DownloadJob(
                id=self._next_id(),
                runner=req.hub.hub if req.hub else "http",
                title=title or "download",
                source=req.source_file.source if req.source_file else (req.hub.hub if req.hub else None),
                source_file=req.source_file,
                hub=req.hub,
                url=req.url,
                root_id=root_id,
                rel_dir=rel_dir,
                dest_dir=str(dest),
                file_name=file_name,
                overwrite=req.overwrite,
                total_bytes=total,
                expected_sha256=expected.lower() if expected else None,
                meta=meta,
                created_at=_now(),
            )
            self._save(job)
            self._owned.add(job.id)
            self._wake.notify_all()
        self.events.publish(DownloadQueuedEvent(job=job.model_copy()))
        return job

    def _find_resumable(self, req: DownloadCreate, dest: Path) -> DownloadJob | None:
        """A paused or failed HTTP job for the same file and folder is resumed instead of duplicated."""
        if req.hub:
            return None
        for job in self.list_jobs():
            if job.state not in ("paused", "failed") or job.runner != "http" or job.dest_dir != str(dest):
                continue
            if req.url and job.url == req.url:
                return job
            if (
                req.source_file
                and job.source_file
                and (job.source_file.source, job.source_file.model_id, job.source_file.file_id)
                == (
                    req.source_file.source,
                    req.source_file.model_id,
                    req.source_file.file_id,
                )
            ):
                return job
        return None

    # -- control --------------------------------------------------------------

    def _transition(self, job: DownloadJob, state: JobState, error: str | None = None) -> DownloadJob:
        job.state = state
        if state in FINISHED_STATES:
            job.finished_at = _now()
            job.speed = 0.0
        if error is not None:
            job.error = error
        self._save(job)
        event_cls = {
            "queued": DownloadQueuedEvent,
            "running": DownloadStartedEvent,
            "paused": DownloadPausedEvent,
            "completed": DownloadCompletedEvent,
            "failed": DownloadFailedEvent,
            "cancelled": DownloadCancelledEvent,
        }[state]
        # A snapshot, not the live job: a subscriber may serialize the event later, on another
        # thread, while this one keeps writing progress into the same object.
        self.events.publish(event_cls(job=job.model_copy()))
        with self._lock:
            self._finished.notify_all()
        return job

    def pause(self, job_id: int) -> DownloadJob:
        job = self._load(job_id)
        if not job.can_pause:
            raise ConflictError("Hub downloads cannot pause; cancel and restart instead")
        with self._lock:
            control = self._controls.get(job_id)
            if control is not None:
                control.request("paused")
                return job
        if job.state == "queued":
            return self._transition(job, "paused")
        raise ConflictError(f"Cannot pause a {job.state} job")

    def resume(self, job_id: int) -> DownloadJob:
        job = self._load(job_id)
        if job.state not in ("paused", "failed", "cancelled"):
            if job.state in ("queued", "running"):
                return job
            raise ConflictError(f"Cannot resume a {job.state} job")
        job.error = None
        with self._lock:
            self._owned.add(job.id)
            self._transition(job, "queued")
            self._wake.notify_all()
        return job

    def cancel(self, job_id: int) -> DownloadJob:
        job = self._load(job_id)
        with self._lock:
            control = self._controls.get(job_id)
            if control is not None:
                control.request("cancelled")
                return job
        if job.state in FINISHED_STATES and job.state != "failed":
            raise ConflictError(f"Cannot cancel a {job.state} job")
        self._discard_partial(job)
        return self._transition(job, "cancelled")

    def restart(self, job_id: int) -> DownloadJob:
        job = self._load(job_id)
        if job.state in ("running", "queued"):
            raise ConflictError("Cancel the job before restarting it")
        self._discard_partial(job)
        job.bytes_done = 0
        job.etag = None
        job.initial_total = None
        job.sha256 = None
        job.error = None
        job.attempts = 0
        return self.resume(job.id) if job.state != "completed" else self._requeue_completed(job)

    def _requeue_completed(self, job: DownloadJob) -> DownloadJob:
        with self._lock:
            self._owned.add(job.id)
            job.final_path = None
            self._transition(job, "queued")
            self._wake.notify_all()
        return job

    def remove(self, job_id: int) -> None:
        job = self._load(job_id)
        if job.state in ("running", "queued"):
            raise ConflictError("Cancel the job before removing it")
        if job.state != "completed":
            self._discard_partial(job)
        self.db.execute("DELETE FROM download_jobs WHERE id = ?", (job_id,))
        self.events.publish(DownloadRemovedEvent(job_ids=[job_id]))

    def clear_finished(self) -> list[int]:
        ids = [j.id for j in self.list_jobs() if j.state in ("completed", "cancelled")]
        if ids:
            self.db.execute(f"DELETE FROM download_jobs WHERE id IN ({','.join('?' * len(ids))})", tuple(ids))
            self.events.publish(DownloadRemovedEvent(job_ids=ids))
        return ids

    def _discard_partial(self, job: DownloadJob) -> None:
        dest = Path(job.dest_dir)
        if job.runner == "http":
            if job.file_name:
                (dest / f"{job.file_name}.part").unlink(missing_ok=True)
        else:
            cleanup_incomplete(dest, [RepoFile.model_validate(f) for f in job.meta.get("files", [])])

    def wait(self, job_id: int, timeout: float | None = None) -> DownloadJob:
        """Block until the job leaves the queued and running states."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._lock:
            while True:
                job = self._load(job_id)
                if job.state not in ("queued", "running"):
                    return job
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return job
                self._finished.wait(remaining if remaining is not None else 1.0)

    # -- workers --------------------------------------------------------------

    def _claim(self) -> DownloadJob | None:
        rows = self.db.fetchall("SELECT data FROM download_jobs WHERE state = 'queued' ORDER BY id")
        for row in rows:
            job = DownloadJob.model_validate_json(row["data"])
            if job.id in self._controls or (self.owned_only and job.id not in self._owned):
                continue
            return job
        return None

    def _worker(self) -> None:
        while True:
            with self._lock:
                job = None
                while not self._stopping:
                    job = self._claim()
                    if job is not None:
                        break
                    self._wake.wait(2.0)
                if self._stopping or job is None:
                    return
                control = JobControl()
                self._controls[job.id] = control
                self._live[job.id] = job
                job.started_at = _now()
                job.attempts = 0
                self._transition(job, "running")
            try:
                self._run(job, control)
            except Exception:
                logger.exception("Download job %s crashed", job.id)
                self._transition(job, "failed", "Internal error; see the server log")
            finally:
                with self._lock:
                    self._controls.pop(job.id, None)
                    self._live.pop(job.id, None)
                    self._last_progress.pop(job.id, None)
                    self._last_persist.pop(job.id, None)
                    self._finished.notify_all()

    def _progress(self, job: DownloadJob, bytes_done: int, total: int | None, started: float, start_bytes: int) -> None:
        now = time.monotonic()
        job.bytes_done = bytes_done
        job.total_bytes = total
        elapsed = now - started
        job.speed = (bytes_done - start_bytes) / elapsed if elapsed > 0.5 else 0.0
        if now - self._last_progress.get(job.id, 0.0) >= PROGRESS_INTERVAL:
            self._last_progress[job.id] = now
            self.events.publish(DownloadProgressEvent(job_id=job.id, bytes_done=bytes_done, total_bytes=total, speed=job.speed))
        if now - self._last_persist.get(job.id, 0.0) >= PERSIST_INTERVAL:
            self._last_persist[job.id] = now
            self._save(job)

    def _run(self, job: DownloadJob, control: JobControl) -> None:
        try:
            if job.runner == "http":
                self._run_http(job, control)
            else:
                self._run_hub(job, control)
        except JobStopped as stop:
            if stop.reason == "cancelled":
                self._discard_partial(job)
            self._transition(job, stop.reason)
            return
        except HanakuraError as e:
            self._transition(job, "failed", e.message)
            return
        self._transition(job, "completed")
        if job.root_id:
            self.library.notify_changed(job.root_id, job.rel_dir)

    def _request(self, job: DownloadJob) -> tuple[DownloadRequest, ModelFile | None]:
        if job.source_file:
            ref = job.source_file
            adapter = self.sources.get(ref.source)
            _, file = self.sources.find_file(ref.source, ref.model_id, ref.version_id, ref.file_id, ref.file_name)
            return adapter.resolve_download(file), file
        assert job.url
        return DownloadRequest(url=job.url), None

    def _run_http(self, job: DownloadJob, control: JobControl) -> None:
        max_retries = self.settings.settings.network.max_retries
        verify = self.settings.settings.downloads.verify_hash
        state = HttpState(
            dest_dir=Path(job.dest_dir),
            file_name=job.file_name,
            etag=job.etag,
            initial_total=job.initial_total,
            expected_sha256=job.expected_sha256 if verify else None,
            overwrite=job.overwrite,
        )
        started = time.monotonic()
        start_bytes = job.bytes_done

        def on_progress(s: HttpState) -> None:
            job.etag = s.etag
            job.initial_total = s.initial_total
            self._progress(job, s.bytes_done, s.total_bytes, started, start_bytes)

        def on_name(s: HttpState) -> None:
            job.file_name = s.file_name
            self._save(job)

        renewed = False
        while True:
            try:
                # Resolve immediately before each attempt: Civitai's links expire, and the
                # authorization header is taken fresh, never from the stored job.
                request, _ = self._request(job)
                http_download(self.http.get(), request, state, control, on_progress, on_name)
                break
            except AuthRequiredError:
                # One chance to renew an expired OAuth token, then the job fails as before.
                if renewed or not job.source or not self.sources.on_unauthorized(job.source):
                    raise
                renewed = True
                logger.info("Job %s: renewed the %s credential after a 401", job.id, job.source)
            except TransientError as e:
                job.attempts += 1
                if job.attempts > max_retries:
                    raise HanakuraError(f"{e} (gave up after {max_retries} retries)") from e
                logger.info("Job %s: %s; retry %s of %s", job.id, e, job.attempts, max_retries)
                wait_backoff(control, job.attempts, e.retry_after)
        job.sha256 = state.sha256
        job.final_path = str(state.final_path)
        job.bytes_done = state.bytes_done
        job.total_bytes = state.total_bytes
        self._after_http(job, Path(job.final_path))

    def _after_http(self, job: DownloadJob, final: Path) -> None:
        """Sidecars and the detection cache. Failures here never fail the download."""
        dl = self.settings.settings.downloads
        meta = job.meta
        try:
            result, kept = self.detection.detect_path(final)
            self.detection.store(final, result, kept, sha256=job.sha256)
            if job.source_file and dl.save_metadata:
                sidecar.write_hanakura(
                    final,
                    {
                        "source": job.source_file.source,
                        "model_id": job.source_file.model_id,
                        "version_id": job.source_file.version_id,
                        "file_id": job.source_file.file_id,
                        "name": meta.get("model_name"),
                        "version_name": meta.get("version_name"),
                        "kind": meta.get("kind"),
                        "base_model": meta.get("base_model"),
                        "base_model_label": meta.get("base_model_label"),
                        "trained_words": meta.get("trained_words") or [],
                        "creator": meta.get("creator"),
                        "page_url": meta.get("page_url"),
                        "sha256": job.sha256,
                        "downloaded_at": _now().isoformat(),
                        "detected": result.model_dump(),
                    },
                )
            elif job.url and dl.save_metadata:
                sidecar.write_hanakura(final, {"url": job.url, "sha256": job.sha256, "downloaded_at": _now().isoformat(), "detected": result.model_dump()})
            if job.source_file and dl.write_webui_metadata:
                description = _TAGS.sub("", meta.get("description") or "").strip()
                sidecar.write_webui_if_absent(final, description, WEBUI_SD_VERSION.get(meta.get("base_model") or "", "Unknown"), ", ".join(meta.get("trained_words") or []))
            if dl.save_preview and meta.get("preview_url"):
                self._save_preview(final, meta["preview_url"])
        except Exception:
            logger.exception("Post-download steps failed for job %s", job.id)

    def _save_preview(self, final: Path, url: str) -> None:
        response = self.http.get().get(url)
        if response.status_code != 200:
            return
        content_type = response.headers.get("Content-Type", "").split(";")[0]
        ext = mimetypes.guess_extension(content_type) or Path(urlparse(url).path).suffix or ".png"
        ext = {".jpe": ".jpg", ".jpeg": ".jpeg"}.get(ext, ext)
        if ext.lower() not in self.settings.settings.library.preview_extensions:
            return
        stem = split_model_name(final.name)[0]
        target = final.with_name(f"{stem}.preview{ext}")
        if not target.exists():
            target.write_bytes(response.content)

    def _run_hub(self, job: DownloadJob, control: JobControl) -> None:
        assert job.hub is not None
        adapter = self.hubs.get(job.hub.hub)
        files = [RepoFile.model_validate(f) for f in job.meta.get("files", [])]
        started = time.monotonic()
        run_hub_download(
            adapter,
            job.hub.repo_id,
            job.hub.revision,
            files,
            Path(job.dest_dir),
            job.overwrite,
            control,
            lambda done, total: self._progress(job, done, total, started, 0),
        )
        job.final_path = job.dest_dir
        for f in files:
            if f.path.lower().endswith((".safetensors", ".sft", ".gguf")):
                try:
                    self.detection.detect(Path(job.dest_dir) / f.path)
                except Exception:
                    logger.debug("Detection after hub download failed", exc_info=True)
