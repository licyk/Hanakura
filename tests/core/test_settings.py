import pytest

from hanakura.core.errors import ValidationError
from hanakura.core.settings import SettingsService


def test_defaults_and_save(tmp_path):
    s = SettingsService(data_dir=tmp_path, environ={})
    assert s.settings.server.host == "127.0.0.1"
    s.update({"server": {"port": 9000}, "sources": {"civitai": {"token": "secret"}}})
    again = SettingsService(data_dir=tmp_path, environ={})
    assert again.settings.server.port == 9000
    assert again.settings.sources["civitai"].token == "secret"


def test_the_oauth_scope_defaults_to_user_read_and_a_saved_one_is_kept(tmp_path):
    assert SettingsService(data_dir=tmp_path / "fresh", environ={}).settings.auth.civitai.oauth_scope == 1
    (tmp_path / "old").mkdir()
    (tmp_path / "old" / "settings.toml").write_text("[auth.civitai]\noauth_scope = 5\n")
    old = SettingsService(data_dir=tmp_path / "old", environ={})
    assert old.settings.auth.civitai.oauth_scope == 5
    old.update({"network": {"timeout": 5}})
    assert SettingsService(data_dir=tmp_path / "old", environ={}).settings.auth.civitai.oauth_scope == 5
    assert SettingsService(data_dir=tmp_path / "old", environ={"HANAKURA_AUTH__CIVITAI__OAUTH_SCOPE": "1"}).settings.auth.civitai.oauth_scope == 1
    assert SettingsService(data_dir=tmp_path / "fresh", environ={}, overrides={"auth": {"civitai": {"oauth_scope": 5}}}).settings.auth.civitai.oauth_scope == 5


def test_view_hides_tokens(tmp_path):
    s = SettingsService(data_dir=tmp_path, environ={})
    s.update({"sources": {"civitai": {"token": "secret"}}, "server": {"access_token": "t"}})
    dumped = s.view().model_dump_json()
    assert "secret" not in dumped and '"t"' not in dumped
    assert s.view().sources["civitai"].token_configured is True
    assert s.view().server.access_token_configured is True


def test_token_cleared_with_null_and_kept_when_omitted(tmp_path):
    s = SettingsService(data_dir=tmp_path, environ={})
    s.update({"sources": {"civitai": {"token": "secret"}}})
    s.update({"sources": {"civitai": {"enabled": False}}})
    assert s.settings.sources["civitai"].token == "secret"
    s.update({"sources": {"civitai": {"token": None}}})
    assert s.settings.sources["civitai"].token is None


def test_env_overrides_file_but_is_not_saved(tmp_path):
    s = SettingsService(data_dir=tmp_path, environ={"HANAKURA_SERVER__PORT": "8123", "HANAKURA_CONTENT__NSFW_MODE": "hide"})
    assert s.settings.server.port == 8123
    assert s.settings.content.nsfw_mode == "hide"
    s.update({"network": {"timeout": 5}})
    assert "8123" not in s.path.read_text()
    assert s.view().env_overrides == ["HANAKURA_CONTENT__NSFW_MODE", "HANAKURA_SERVER__PORT"]


def test_pinned_settings_are_named_in_the_view(tmp_path):
    s = SettingsService(data_dir=tmp_path, environ={}, overrides={"library": {"combined_view": True}, "server": {"access_token": "secret"}})
    view = s.view()
    assert view.pinned == ["library.combined_view", "server.access_token"]
    assert "secret" not in view.model_dump_json()
    assert SettingsService(data_dir=tmp_path / "other", environ={}).view().pinned == []


def test_invalid_values_rejected(tmp_path):
    s = SettingsService(data_dir=tmp_path, environ={})
    with pytest.raises(ValidationError):
        s.update({"server": {"port": 70000}})
    with pytest.raises(ValidationError):
        s.set_value("nope.nothing", "1")


def test_set_value_parses_json(tmp_path):
    s = SettingsService(data_dir=tmp_path, environ={})
    s.set_value("library.delete_to_trash", "false")
    s.set_value("downloads.kind_folders.lora", "loras/new")
    assert s.settings.library.delete_to_trash is False
    assert s.settings.downloads.kind_folders == {"lora": "loras/new"}
    assert s.get_value("library.delete_to_trash") is False
