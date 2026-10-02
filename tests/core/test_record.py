"""The record contract must work with native Pydantic v1 and v2 installations."""

import json
from datetime import datetime, timezone

import pytest
from pydantic import BaseModel

from hanakura.cli.output import to_jsonable
from hanakura.core.downloads.models import DownloadJob
from hanakura.core.events.models import DownloadQueuedEvent


@pytest.mark.parametrize("runner,can_pause", [("http", True), ("huggingface", False), ("modelscope", False)])
def test_job_serialization_and_persistence(runner, can_pause):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    job = DownloadJob.model_validate({"id": 1, "runner": runner, "title": "model", "dest_dir": "/models", "created_at": now, "can_pause": not can_pause})
    assert job.can_pause is can_pause
    assert job.model_dump()["created_at"] == now
    dumped = job.model_dump(mode="json")
    assert isinstance(dumped["created_at"], str)
    assert dumped["can_pause"] is can_pause
    assert "model_config" not in dumped
    assert to_jsonable(job) == dumped

    event = DownloadQueuedEvent(job=job)
    assert event.model_dump(mode="json")["job"] == dumped
    assert json.loads(event.model_dump_json())["job"] == dumped
    assert job.model_dump(include={"can_pause"}) == {"can_pause": can_pause}
    assert "can_pause" not in job.model_dump(exclude={"can_pause": True})
    assert "can_pause" not in event.model_dump(exclude={"job": {"can_pause"}})["job"]

    persisted = job.model_dump_json(exclude={"speed", "can_pause"})
    assert "can_pause" not in json.loads(persisted)
    restored = DownloadJob.model_validate_json(persisted)
    assert restored.model_dump() == job.model_dump()
    copied = job.model_copy(update={"runner": "modelscope" if runner == "http" else "http"}, deep=True)
    assert copied.can_pause is not can_pause
    assert "can_pause" not in copied.__dict__
    assert job.can_pause is can_pause


def test_cli_serializes_plain_pydantic_models():
    class Plain(BaseModel):
        created_at: datetime

    assert isinstance(to_jsonable(Plain(created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))["created_at"], str)
