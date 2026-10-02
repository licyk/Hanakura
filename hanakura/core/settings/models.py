"""Settings models."""

from typing import Literal

from pydantic import Field

from hanakura.core.record import Record

LayoutName = Literal["comfyui", "sd-webui", "custom"]
NsfwMode = Literal["hide", "blur", "show"]

DEFAULT_MODEL_EXTENSIONS = [".safetensors", ".sft", ".ckpt", ".pt", ".pt2", ".pth", ".bin", ".pkl", ".gguf"]
DEFAULT_PREVIEW_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".gif"]


class ServerSettings(Record):
    host: str = "127.0.0.1"
    port: int = Field(default=7865, ge=1, le=65535)
    strict_port: bool = False
    open_browser: bool = True
    access_token: str | None = None
    allowed_origins: list[str] = Field(default_factory=list)


class ModelRoot(Record):
    id: str
    name: str
    path: str
    layout: LayoutName = "custom"
    kind: str | None = None
    """Fallback folder hint for a root dedicated to one model kind; never overrides detection."""


class PathSettings(Record):
    model_roots: list[ModelRoot] = Field(default_factory=list)


class SourceSettings(Record):
    enabled: bool = True
    token: str | None = None
    base_url: str | None = None
    endpoint: str | None = None


def _default_sources() -> dict[str, SourceSettings]:
    return {name: SourceSettings() for name in ("civitai", "openmodeldb", "github", "huggingface", "modelscope")}


class NetworkSettings(Record):
    proxy: str | None = None
    timeout: float = Field(default=30.0, gt=0)
    max_concurrent_downloads: int = Field(default=2, ge=1, le=16)
    max_retries: int = Field(default=3, ge=0, le=20)


class DownloadDestination(Record):
    root_id: str
    rel_dir: str = ""


class DownloadSettings(Record):
    default_root: str | None = None
    kind_folders: dict[str, str] = Field(default_factory=dict)
    kind_destinations: dict[str, DownloadDestination | None] = Field(default_factory=dict)
    save_preview: bool = True
    save_metadata: bool = True
    write_webui_metadata: bool = False
    verify_hash: bool = True


class ContentSettings(Record):
    nsfw_mode: NsfwMode = "blur"


class LibrarySettings(Record):
    delete_to_trash: bool = True
    # On by default: a linked model folder — a WebUI's LoRAs on another disk — is what the user
    # put there, and hiding it only looks like the files are missing. Links are followed for
    # browsing and for downloads, and operations act on the files where they really are. Off,
    # anything a link leads outside the root is hidden and refused.
    follow_symlinks: bool = True
    # Off by default: the library is a model browser first, and a folder full of notes, archives
    # and loose text files hides the models in it. On, every file a model does not already carry
    # as a companion is listed too, so a folder can be managed like one in a file manager.
    show_all_files: bool = False
    # Off by default: most installations have one root, where a view of every root adds nothing.
    # On, the Library offers "All folders" first: the top level of every root side by side.
    combined_view: bool = False
    model_extensions: list[str] = Field(default_factory=lambda: list(DEFAULT_MODEL_EXTENSIONS))
    preview_extensions: list[str] = Field(default_factory=lambda: list(DEFAULT_PREVIEW_EXTENSIONS))


AuthMethod = Literal["manual", "oauth"]

# UserRead | ModelsRead, the minimum for browsing and downloading (plan section 4).
DEFAULT_OAUTH_SCOPE = 5
CIVITAI_AUTH_BASE_URL = "https://auth.civitai.com"


class CivitaiAuthSettings(Record):
    """Non-secret OAuth configuration. Tokens live in the credential store, never here.

    ``method`` is the authentication the user chose. It only ever changes when the user saves a
    manual token or completes an OAuth connection, never because something failed.
    """

    method: AuthMethod = "manual"
    oauth_client_id: str | None = None
    oauth_scope: int = Field(default=DEFAULT_OAUTH_SCOPE, ge=1)
    # The authorization service, kept apart from the model API's base_url on purpose.
    oauth_base_url: str = CIVITAI_AUTH_BASE_URL
    # Callback URLs this installation accepts, exactly as registered with Civitai. Empty means
    # only the address the server is bound to, which the server builds itself.
    redirect_uris: list[str] = Field(default_factory=list)
    use_keyring: bool = True


class AuthSettings(Record):
    civitai: CivitaiAuthSettings = Field(default_factory=CivitaiAuthSettings)


class Settings(Record):
    """Everything saved in ``settings.toml``."""

    server: ServerSettings = Field(default_factory=ServerSettings)
    paths: PathSettings = Field(default_factory=PathSettings)
    sources: dict[str, SourceSettings] = Field(default_factory=_default_sources)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    network: NetworkSettings = Field(default_factory=NetworkSettings)
    downloads: DownloadSettings = Field(default_factory=DownloadSettings)
    content: ContentSettings = Field(default_factory=ContentSettings)
    library: LibrarySettings = Field(default_factory=LibrarySettings)


# Public views: tokens never leave the server.


class ServerSettingsView(Record):
    host: str
    port: int
    strict_port: bool
    open_browser: bool
    access_token_configured: bool
    allowed_origins: list[str]


class SourceSettingsView(Record):
    enabled: bool
    token_configured: bool
    base_url: str | None
    endpoint: str | None


class SettingsView(Record):
    """Settings as returned to clients, with secrets replaced by flags."""

    data_dir: str
    settings_file: str
    server: ServerSettingsView
    paths: PathSettings
    sources: dict[str, SourceSettingsView]
    auth: AuthSettings
    network: NetworkSettings
    downloads: DownloadSettings
    content: ContentSettings
    library: LibrarySettings
    env_overrides: list[str]
    pinned: list[str] = Field(default_factory=list)
    """Dotted names of the settings a host application pinned; changing them has no effect."""
