import json
import logging

import pytest
from typer.testing import CliRunner

from hanakura.cli.app import get_app
from hanakura.logger import LOGGER_NAME
from tests.conftest import LORA_SDXL, write_safetensors

EXPECTED_TREE = {
    "auth": {"connect": None, "disconnect": None, "status": None, "use": None},
    "config": {"get": None, "path": None, "set": None, "show": None},
    "download": {"hf": None, "model": None, "modelscope": None, "url": None},
    "env": None,
    "info": None,
    "library": {
        "delete": None,
        "identify": None,
        "import": None,
        "info": None,
        "list": None,
        "move": None,
        "rename": None,
        "root": {"add": None, "list": None, "remove": None},
        "scan": None,
    },
    "search": None,
    "source": {"list": None},
    "version": None,
    "webui": None,
}


def _tree(group):
    import typer

    click_group = typer.main.get_command(group) if not hasattr(group, "commands") else group
    out = {}
    for name, cmd in click_group.commands.items():
        out[name] = _tree(cmd) if hasattr(cmd, "commands") else None
    return out


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("HANAKURA_DATA_DIR", str(tmp_path / "data"))
    # --debug sets the application logger to DEBUG for the whole process; reset it so one test's
    # log lines cannot end up in another's captured output.
    logger = logging.getLogger(LOGGER_NAME)
    level = logger.level
    yield CliRunner()
    logger.setLevel(level)


def test_command_tree_snapshot():
    assert _tree(get_app()) == EXPECTED_TREE


@pytest.mark.parametrize("args", [["--debug", "env"], ["env", "--debug"], ["library", "--debug", "root", "list"], ["library", "root", "list", "--debug"]])
def test_debug_option_everywhere(runner, args):
    result = runner.invoke(get_app(), args)
    assert result.exit_code == 0, result.output


def test_help_is_alphabetical(runner):
    out = runner.invoke(get_app(), ["--help"]).output
    names = [line.split()[0] for line in out.split("Commands:")[1].strip().splitlines()]
    assert names == sorted(names)


def test_version_json(runner):
    result = runner.invoke(get_app(), ["version", "--json"])
    assert json.loads(result.output)["hanakura"]


def test_config_roundtrip_and_error_exit_code(runner):
    assert runner.invoke(get_app(), ["config", "set", "server.port", "8001"]).exit_code == 0
    assert json.loads(runner.invoke(get_app(), ["config", "get", "server.port"]).output) == 8001
    from hanakura.core.errors import ValidationError

    result = runner.invoke(get_app(), ["config", "get", "nope"])
    assert isinstance(result.exception, ValidationError) and result.exception.exit_code == 4


def test_library_flow(runner, tmp_path):
    models = tmp_path / "models"
    (models / "loras").mkdir(parents=True)
    write_safetensors(tmp_path / "in" / "x.safetensors", LORA_SDXL)
    app = get_app()
    assert runner.invoke(app, ["library", "root", "add", str(models), "--layout", "comfyui"]).exit_code == 0
    result = runner.invoke(app, ["library", "import", str(tmp_path / "in" / "x.safetensors")])
    assert result.exit_code == 0, result.output
    assert (models / "loras" / "x.safetensors").exists()
    listing = json.loads(runner.invoke(app, ["library", "list", str(models / "loras"), "--json"]).output)
    assert listing["models"][0]["detection"]["base_model"] == "sdxl"
    info = json.loads(runner.invoke(app, ["library", "info", str(models / "loras" / "x.safetensors"), "--json", "--hash"]).output)
    assert len(info["sha256"]) == 64
    assert runner.invoke(app, ["library", "rename", str(models / "loras" / "x.safetensors"), "y"]).exit_code == 0
    assert (models / "loras" / "y.safetensors").exists()
    assert runner.invoke(app, ["library", "delete", str(models / "loras" / "y.safetensors"), "--permanent", "--yes"]).exit_code == 0
    assert not (models / "loras" / "y.safetensors").exists()


def test_library_list_all_roots(runner, tmp_path):
    from hanakura.core.errors import ValidationError

    app = get_app()
    for name in ("a", "b"):
        (tmp_path / name / "loras").mkdir(parents=True)
        assert runner.invoke(app, ["library", "root", "add", str(tmp_path / name), "--name", name]).exit_code == 0
    result = runner.invoke(app, ["library", "list", "--all-roots", "--json"])
    assert result.exit_code == 0, result.output
    assert sorted(f["label"] for f in json.loads(result.output)["folders"]) == ["loras (a)", "loras (b)"]
    assert "loras (a)" in runner.invoke(app, ["library", "list", "--all-roots"]).output
    refused = runner.invoke(app, ["library", "list", "--all-roots", "--recursive"])
    assert isinstance(refused.exception, ValidationError) and refused.exception.exit_code == 4


def test_path_outside_roots_is_not_found(runner, tmp_path):
    from hanakura.core.errors import NotFoundError

    result = runner.invoke(get_app(), ["library", "info", str(tmp_path)])
    assert isinstance(result.exception, NotFoundError) and result.exception.exit_code == 2


def test_invalid_root_layout_is_validated(runner, tmp_path):
    from pydantic import ValidationError

    result = runner.invoke(get_app(), ["library", "root", "add", str(tmp_path), "--layout", "invalid"])
    assert isinstance(result.exception, ValidationError)
    assert result.exception.errors()[0]["loc"] == ("layout",)


def test_logging_setup_does_not_duplicate_handlers(monkeypatch):
    from hanakura.logger import setup_logging

    logger = logging.getLogger(LOGGER_NAME)
    monkeypatch.setattr(logger, "handlers", [])
    monkeypatch.setattr(logger, "level", logging.NOTSET)
    monkeypatch.setattr(logger, "propagate", True)
    setup_logging("INFO")
    setup_logging("DEBUG")
    assert len(logger.handlers) == 1
    assert logger.handlers[0].name == LOGGER_NAME
    assert logger.level == logging.DEBUG
