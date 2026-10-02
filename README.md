<div align="center">

# Hanakura 花蔵

<p align="center">
  <a href="https://github.com/licyk/Hanakura/stargazers">
    <img src="https://img.shields.io/github/stars/licyk/Hanakura?style=flat&logo=github&logoColor=silver&color=bluegreen&labelColor=grey" alt="Stars">
  </a>
  <a href="https://github.com/licyk/Hanakura/issues">
    <img src="https://img.shields.io/github/issues/licyk/Hanakura?style=flat&logo=github&logoColor=silver&color=bluegreen&labelColor=grey" alt="Issues">
  </a>
  <a href="https://github.com/licyk/Hanakura/commits/main">
    <img src="https://flat.badgen.net/github/last-commit/licyk/Hanakura/main?icon=github&color=green&label=last%20main%20commit" alt="Last main commit">
  </a>
  <a href="https://github.com/licyk/Hanakura/actions/workflows/release.yml">
    <img src="https://github.com/licyk/Hanakura/actions/workflows/release.yml/badge.svg" alt="Release">
  </a>
  <a href="https://pypi.org/project/hanakura/">
    <img src="https://img.shields.io/pypi/v/hanakura?style=flat&logo=pypi&logoColor=silver&color=bluegreen&labelColor=grey" alt="PyPI version">
  </a>
  <a href="https://pypi.org/project/hanakura/">
    <img src="https://img.shields.io/pypi/pyversions/hanakura?style=flat&logo=python&logoColor=silver&color=bluegreen&labelColor=grey" alt="Python versions">
  </a>
</p>

English | [简体中文](README_zh-CN.md)

</div>

Download and manage Stable Diffusion models, from the command line or a web UI.

- **Browse** Civitai, OpenModelDB and GitHub Releases, and download with resume, SHA256
  checks, preview images and metadata sidecars.
- **Hubs:** download files or whole repositories from Hugging Face (or a mirror such as
  hf-mirror) and ModelScope.
- **Link:** paste any download address and choose the folder it goes to, with an optional
  file name and SHA256 to check against.
- **Library:** point Hanakura at your ComfyUI or Stable Diffusion WebUI model folders. It
  identifies each model's type and base model from the safetensors header (never unpickling
  anything), shows previews, and imports, moves, renames and deletes models together with
  their preview images and sidecar files. Drag files into the browser to upload them.

The design, the conventions and the known gaps are in [AGENTS.md](AGENTS.md).

## Install

Install from PyPI:

```bash
python -m pip install hanakura
hanakura --help
```

Python 3.10 or newer. The web UI is bundled into the package; users do not need Node.

Pydantic v1 and v2 are supported. To keep Pydantic v1 in an existing environment, use
Python 3.10–3.13 and a compatible FastAPI:

```bash
python -m pip install hanakura "pydantic<2" "fastapi<0.126"
```

Python 3.14 and newer require Pydantic v2. Development checks and committed web API types
are generated with Pydantic v2; the release workflow also tests Pydantic v1 separately.

## Command line

```text
hanakura
├── webui                      start the server and open the web UI
├── version | env
├── config  show | get | set | path
├── source  list
├── auth    status | use <manual|oauth> | connect | disconnect
├── search <query>             --source --kind --base-model --sort --limit
├── info <source> <model-id>
├── download
│   ├── model <source> <model-id>    --version --file --root --dir --to
│   ├── url <url>                    --to --sha256 --name
│   ├── hf <repo-id>                 --revision --include --exclude --to
│   └── modelscope <repo-id>         --revision --include --exclude --to
└── library
    ├── root list | add | remove
    ├── list [path]            --root --recursive --kind
    ├── info <path>            --hash
    ├── identify <path>
    ├── scan                   --root
    ├── import <paths...>      --root --to --move --rename
    ├── move <src...> <dst>
    ├── rename <path> <new-name>
    └── delete <paths...>      --permanent --yes
```

Every listing command accepts `--json`, which prints the same records the API returns.
`--debug` works at every level. Errors exit with a code per kind: 2 not found, 3 conflict,
4 invalid path or input, 5 needs a token, 6 upstream failure.

Examples:

```bash
hanakura library root add ~/ComfyUI/models --layout comfyui
hanakura library list ~/ComfyUI/models/loras --recursive --kind lora
hanakura search "detail tweaker" --kind lora --base-model "SDXL 1.0"
hanakura download model civitai 122359           # into the layout's LoRA folder
hanakura download hf stabilityai/sdxl-turbo --include "*.safetensors" --to ./sdxl-turbo
hanakura config set sources.civitai.token <token>
hanakura webui --port 7865
```

Ctrl+C during an HTTP download pauses it and keeps the `.part` file; running the same command
again resumes. Hub downloads cannot pause (neither library resumes), so Ctrl+C cancels them.

## Embedding in another application

```python
from hanakura import HanakuraServer, ModelRoot

hub = HanakuraServer(
    data_dir="./hub-data",                   # database and caches
    settings_path="./my-app/hanakura.toml", # the settings file, wherever you want it
    model_roots=[ModelRoot("/srv/models", layout="comfyui", name="Models")],
    lock_model_roots=True,                 # the user cannot add, change or remove folders
    port=0,                                # any free port; a number asks for that one
    api_prefix="/tools/hanakura",         # keeps our routes clear of yours
)

url = hub.start()      # returns as soon as it is listening, e.g. http://127.0.0.1:54123/tools/hanakura
...
hub.stop()
```

| Option | Effect |
| --- | --- |
| `data_dir` | Where the database, caches and (by default) the settings file live |
| `settings_path` | The settings file on its own, apart from `data_dir` |
| `model_roots` | Folders of models, each with its own `layout` and optional `kind` hint; supply an `id` to reference it in download settings |
| `lock_model_roots` | Fixes them: the API refuses changes and the interface hides those actions |
| `port` | `0` any free port, a number for that one (moving up unless `strict_port`), `None` for the configured one |
| `api_prefix` | Serves the API, the socket and the web UI under one path |
| `public_base_url` | Trusted browser-facing UI URL, including any proxy path, for OAuth callbacks and cookies; does not change routing |
| `settings` | Pins any other setting, e.g. `{"downloads": {"verify_hash": False}}`; pinned values cannot be changed in the UI |
| `host`, `access_token`, `open_browser`, `log_level` | As for the command line; a non-loopback host requires a token |

`hub.start()` is non-blocking and returns the URL; `hub.run()` serves in the foreground;
`with HanakuraServer(...) as hub:` does both ends. `hub.services` exposes the library, downloads
and settings for direct use, and `hub.url`, `hub.port` and `hub.running` describe the server.

Dedicated directories can live on different disks. For example, a host can supply
`ModelRoot("/models/lora", id="host-lora", kind="lora")` and pin the following settings:

```python
settings={
    "downloads": {
        "kind_destinations": {
            "lora": {"root_id": "host-lora", "rel_dir": ""},
        },
    },
}
```

`kind` is only a fallback folder hint: a layout's specific folder mapping takes precedence,
and file detection is still reported independently, including mismatches. It also helps choose
a default download root when no explicit default is configured. Host root IDs are preserved
when seeded into settings; omitted IDs are derived deterministically from the resolved path.

Download destination precedence is: an explicit destination/root, then the model kind's
`kind_destinations` entry, then `default_root`, then a root with the matching kind hint, then
the first root. An explicit relative directory, including `""`, wins over suggestions. Within
the selected root, a matching kind destination wins over the legacy `kind_folders` mapping
and the layout default. A missing configured root or an escaping relative path raises an error
instead of silently downloading elsewhere. Set an individual kind destination to `null` via
the settings API to clear it. Root locking fixes the root list; it does not disable absolute
download destinations or server-side imports.

The UI and download manager both use `LibraryService.suggest_destination(kind, root_id)`;
it is also available as `GET /api/v1/library/destination?kind=lora&root_id=...` (both parameters
are optional). Suggestions do not create directories.

For a host that already has an ASGI server, use the same Python environment and mount the
app directly; no extra listener or subprocess is needed:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from hanakura.api.app import create_app
from hanakura.core.context import build_services

services = build_services(data_dir=..., settings_overrides=..., roots_locked=True)
hub_app = create_app(services, bound_host="127.0.0.1")

@asynccontextmanager
async def lifespan(app):
    try:
        async with hub_app.router.lifespan_context(hub_app):
            yield
    finally:
        services.close()

app = FastAPI(lifespan=lifespan)
app.mount("/hanakura", hub_app)
```

The host must enter and exit the child lifespan on the serving event loop; mounting alone
does not start the download queue or event bridge. If the host is already running when it
loads an extension, enter that context explicitly on its existing loop and retain it until
unload/shutdown. Apply the host's authentication to both HTTP and WebSocket requests through
the mounted application; a host's route dependencies do not automatically protect a child
app. Keep origin checks and configure the intended host names (`extra_hosts` in `create_app`).

Mount paths, `root_path` and `api_prefix` contribute to OAuth cookie and redirect paths.
With a reverse proxy, `public_base_url="https://example.com/webui/hanakura"` sets the trusted
external UI URL. Its callback must also appear in `auth.civitai.redirect_uris` when that
allowlist is configured, and must be registered with the provider. Forwarded headers alone
cannot choose a callback URL. A manual source token continues to work without OAuth setup.

The command line can also take the prefix: `hanakura webui --api-prefix /tools/hanakura`.

## Settings

Settings live in `settings.toml` in the data directory (`hanakura config path`). Any setting
can be overridden with an environment variable: `HANAKURA_<GROUP>__<FIELD>`, for example
`HANAKURA_SERVER__PORT=8000` or `HANAKURA_NETWORK__PROXY=http://127.0.0.1:7890`.
`HANAKURA_DATA_DIR` moves the data directory. Tokens are never returned by the API.

The server listens on `127.0.0.1` by default. To listen on another address, set
`server.access_token` first; every request then needs it.

### Civitai authentication

Two ways, side by side. Neither replaces the other, and nothing switches between them by itself.

**A personal API token** (the default, and all most people need):

```bash
hanakura config set sources.civitai.token <token>       # or HANAKURA_SOURCES__CIVITAI__TOKEN
```

**A connected account** (OAuth, Authorization Code with PKCE). It needs an OAuth application
registered with Civitai, because the client id identifies *this installation*:

```bash
hanakura config set auth.civitai.oauth_client_id <client id>
hanakura webui        # then Settings → Civitai authentication → Connect
hanakura auth status  # which credential is in use, and where it is kept
```

Register the callback with Civitai exactly as the server uses it, by default
`http://127.0.0.1:7865/api/v1/auth/civitai/callback`. On another port or host, or when working
on the UI with the Vite dev server, list the exact URLs:

```bash
hanakura config set auth.civitai.redirect_uris '["http://127.0.0.1:7865/api/v1/auth/civitai/callback", "http://localhost:5173/api/v1/auth/civitai/callback"]'
```

Tokens stay on the server: in the operating system's credential store when there is one, else a
file in the data directory readable only by you. They are never in `settings.toml`, never sent
to the browser, and never written into download records. Access tokens are refreshed about a
minute before they expire, once even if several downloads ask at the same time, and the rotated
pair is stored as a whole. `hanakura auth disconnect` revokes the authorization and forgets
it locally, leaving any API token untouched.

An environment variable takes precedence over both, and the settings page says so while it does.

### Symbolic links

A model folder whose contents are symbolic links to another disk — as a WebUI install often has
for its LoRAs — works out of the box: links are followed by default, so a linked folder is
listed, opens and keeps the path you navigate with, and can be downloaded into. Deleting, moving
and renaming then act on the files where they really are.

Turn that off if you would rather nothing outside a model folder can be touched through the
interface:

```bash
hanakura config set library.follow_symlinks false
```

It is also in Settings, under Content & Library. Off, anything a link leads outside its root is
hidden from listings rather than shown and then refused on the way in. Paths containing `..`,
absolute paths and reserved names are refused in either mode, and a folder reached twice through
a loop of links is walked once.

## Files Hanakura writes next to a model

| File | Purpose |
| --- | --- |
| `<name>.hanakura.json` | Source metadata: model and version ids, base model, trigger words, SHA256 |
| `<name>.preview.<ext>` | Preview image, found by the WebUI's own lookup |
| `<name>.json` | Only when `downloads.write_webui_metadata` is on, and only if absent: the WebUI's user metadata |

## Development

```bash
pip install -e ".[dev]"
python scripts/dev.py              # list the developer tasks
python scripts/dev.py dev          # API server and web UI together, with hot reload
python scripts/dev.py check        # what CI runs: lint, ty, tests, generated types
python scripts/dev.py typecheck-py # Python types; targets Python 3.10 by default
python scripts/dev.py test         # pytest, vitest and vue-tsc
python scripts/dev.py format       # ruff fixes and formatting
python scripts/dev.py typegen      # regenerate src/api/schema.d.ts from the OpenAPI schema
```

`dev` is the one to use while working on the UI: it starts the API server and the Vite dev
server together, tags each line of output with `api` or `web`, and stops both on Ctrl+C. Open
the address it prints (http://localhost:5173 by default); Vite proxies `/api` and `/ws` to the
API server, so one address serves both and the UI hot-reloads.

While the API server is restarting, the page's socket reconnects on its own and the proxy says
so once:

```text
[api proxy] http://127.0.0.1:7865 is not answering (ECONNREFUSED). Start it with: hanakura webui --no-open
```

Data reappears by itself once the server is back; there is no need to reload the page.

```bash
python scripts/dev.py dev --api-port 8000 --web-port 3000 --data-dir ./dev-data
python scripts/dev.py web-dev      # only the UI, against an API server you started yourself
hanakura webui --no-open       # only the API server
```

The tasks are a small Python script rather than a Makefile, so they work the same on Windows.
Each one prints the command it runs, so the underlying tools stay easy to call directly.

The web UI uses [bun](https://bun.sh). Layers: `hanakura/core` holds all logic and imports
no web or CLI framework (a test enforces it); `hanakura/api` (FastAPI) and `hanakura/cli`
(Typer) are thin wrappers over it.

Detection rules are JSON files in `hanakura/core/detection/rules_data/`. To add a test
fixture from a real file: `python scripts/extract_header_fixture.py <file> <name>`.

## Building

```bash
python scripts/build_wheel.py            # web UI with bun, then the wheel and sdist into dist/
python scripts/build_wheel.py --ci       # for CI: skips the type-check, keeps the built web UI
python scripts/build_wheel.py --outdir out --keep-web-dist
python scripts/dev.py wheel              # the same, through the task runner
```

A bare `python -m build` produces a wheel without the web UI, because setuptools packages only
the files that exist when it runs; the server then logs a warning and serves the API only.
