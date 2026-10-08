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

[English](README.md) | 简体中文

</div>

下载和管理 Stable Diffusion 模型，可以使用命令行，也可以使用网页界面。

- **模型下载：** 浏览 Civitai、OpenModelDB 和 GitHub Releases，下载支持断点续传、SHA256
  校验、预览图和元数据附属文件。
- **抱脸 / 魔搭：** 从 Hugging Face（或 hf-mirror 等镜像站）和 ModelScope 下载单个文件或整个仓库。
- **链接下载：** 粘贴任意下载地址并选择保存的文件夹，可选填文件名和用于校验的 SHA256。
- **本地模型：** 把 Hanakura 指向 ComfyUI 或 Stable Diffusion WebUI 的模型文件夹。它根据
  safetensors 文件头识别每个模型的类型和基础模型（从不反序列化 pickle），显示预览图，并在导入、
  移动、重命名和删除模型时一并处理预览图和附属文件。把文件拖进浏览器即可上传。

设计、约定和已知缺陷见 [AGENTS.md](AGENTS.md)。

## 安装

从 PyPI 安装：

```bash
python -m pip install hanakura
hanakura --help
```

需要 Python 3.10 或更新版本。网页界面已打包在安装包内，用户不需要 Node。

支持 Pydantic v1 和 v2。如需在已有环境中保留 Pydantic v1，请使用 Python 3.10–3.13 和兼容的
FastAPI：

```bash
python -m pip install hanakura "pydantic<2" "fastapi<0.126"
```

Python 3.14 及更新版本需要 Pydantic v2。开发检查和仓库中提交的网页 API 类型均使用 Pydantic v2
生成；CI 还会单独测试 Pydantic v1。

## 命令行

```text
hanakura
├── webui                      启动服务器并打开网页界面
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

所有列表类命令都接受 `--json`，输出与 API 返回相同的记录。`--debug` 在每一级命令上都可用。
出错时按错误类型返回退出码：2 未找到，3 冲突，4 路径或输入无效，5 需要令牌，6 上游失败。

示例：

```bash
hanakura library root add ~/ComfyUI/models --layout comfyui
hanakura library list ~/ComfyUI/models/loras --recursive --kind lora
hanakura search "detail tweaker" --kind lora --base-model "SDXL 1.0"
hanakura download model civitai 122359           # 下载到该布局的 LoRA 文件夹
hanakura download hf stabilityai/sdxl-turbo --include "*.safetensors" --to ./sdxl-turbo
hanakura config set sources.civitai.token <token>
hanakura webui --port 7865
```

HTTP 下载过程中按 Ctrl+C 会暂停下载并保留 `.part` 文件，再次运行同一条命令即可继续。Hub
下载无法暂停（两个库都不支持续传），因此 Ctrl+C 会取消下载。

## 嵌入到其他应用

```python
from hanakura import HanakuraServer, ModelRoot

hub = HanakuraServer(
    data_dir="./hub-data",                   # 数据库和缓存
    settings_path="./my-app/hanakura.toml", # 设置文件，可放在任意位置
    model_roots=[ModelRoot("/srv/models", layout="comfyui", name="Models")],
    lock_model_roots=True,                 # 用户不能添加、修改或移除文件夹
    port=0,                                # 任意空闲端口；填数字则使用该端口
    api_prefix="/tools/hanakura",         # 避免与宿主自己的路由冲突
)

url = hub.start()      # 开始监听后立即返回，例如 http://127.0.0.1:54123/tools/hanakura
...
hub.stop()
```

| 选项 | 作用 |
| --- | --- |
| `data_dir` | 数据库、缓存以及（默认情况下）设置文件的存放位置 |
| `settings_path` | 单独指定设置文件，与 `data_dir` 分开 |
| `model_roots` | 模型文件夹，每个都有自己的 `layout` 和可选的 `kind` 提示；提供 `id` 后可在下载设置中引用 |
| `lock_model_roots` | 固定模型文件夹：API 拒绝修改，界面隐藏相关操作 |
| `port` | `0` 为任意空闲端口，数字为指定端口（被占用时向上递增，除非设置了 `strict_port`），`None` 使用设置中的端口 |
| `api_prefix` | 把 API、套接字和网页界面放在同一个路径下 |
| `public_base_url` | 受信任的、面向浏览器的界面地址（含代理路径），用于 OAuth 回调和 Cookie；不改变路由 |
| `settings` | 固定其他任意设置，例如 `{"downloads": {"verify_hash": False}}`；被固定的值无法在界面中修改 |
| `host`、`access_token`、`open_browser`、`log_level` | 与命令行相同；非回环地址需要令牌 |

`hub.start()` 不阻塞并返回地址；`hub.run()` 在前台运行；`with HanakuraServer(...) as hub:`
负责启动和停止。`hub.services` 提供模型库、下载和设置供直接调用，`hub.url`、`hub.port` 和
`hub.running` 描述服务器状态。

专用目录可以位于不同的磁盘。例如，宿主可以提供
`ModelRoot("/models/lora", id="host-lora", kind="lora")` 并固定以下设置：

```python
settings={
    "downloads": {
        "kind_destinations": {
            "lora": {"root_id": "host-lora", "rel_dir": ""},
        },
    },
}
```

`kind` 只是一个备用的文件夹提示：布局中具体的文件夹映射优先于它，文件检测结果仍然独立报告，包括
不一致的情况。在没有明确配置默认值时，它也用于选择默认的下载根目录。宿主提供的根目录 ID
在写入设置时保持不变；未提供的 ID 由解析后的路径确定性地生成。

下载目标的优先级依次为：明确指定的目标或根目录，该模型类型的 `kind_destinations` 条目，
`default_root`，带有匹配类型提示的根目录，第一个根目录。明确指定的相对目录（包括 `""`）
优先于建议值。在选定的根目录内，匹配的类型目标优先于旧的 `kind_folders` 映射和布局默认值。
配置的根目录不存在或相对路径越界时会报错，而不是悄悄下载到别处。通过设置 API 把某个类型目标设为
`null` 可清除它。锁定根目录只固定根目录列表，不会禁用绝对路径的下载目标或服务器端导入。

界面和下载管理器都使用 `LibraryService.suggest_destination(kind, root_id)`；它也可通过
`GET /api/v1/library/destination?kind=lora&root_id=...` 调用（两个参数都可省略）。
获取建议不会创建目录。

如果宿主已有 ASGI 服务器，使用同一个 Python 环境直接挂载应用即可，不需要额外的监听端口或子进程：

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

宿主必须在提供服务的事件循环上进入和退出子应用的 lifespan；仅仅挂载不会启动下载队列和事件桥。
如果宿主在加载扩展时已经在运行，请在它现有的事件循环上显式进入该上下文，并保持到卸载或关闭为止。
宿主的认证要通过挂载的应用同时作用于 HTTP 和 WebSocket 请求；宿主的路由依赖不会自动保护子应用。
请保留来源检查，并配置预期的主机名（`create_app` 的 `extra_hosts`）。

挂载路径、`root_path` 和 `api_prefix` 都会影响 OAuth 的 Cookie 和重定向路径。使用反向代理时，
`public_base_url="https://example.com/webui/hanakura"` 用于设置受信任的外部界面地址。配置了
`auth.civitai.redirect_uris` 白名单时，它的回调地址也必须在其中，并且必须在服务提供方处注册。
仅凭转发头不能决定回调地址。手动填写的来源令牌无需配置 OAuth 即可继续使用。

命令行同样可以指定前缀：`hanakura webui --api-prefix /tools/hanakura`。

## 设置

设置保存在数据目录的 `settings.toml` 中（`hanakura config path`）。任何设置都可以用环境变量覆盖：
`HANAKURA_<GROUP>__<FIELD>`，例如 `HANAKURA_SERVER__PORT=8000` 或
`HANAKURA_NETWORK__PROXY=http://127.0.0.1:7890`。`HANAKURA_DATA_DIR` 用于更改数据目录。
API 从不返回令牌。

服务器默认监听 `127.0.0.1`。要监听其他地址，请先设置 `server.access_token`，之后每个请求都需要它。

### Civitai 认证

有两种方式，可以并存。两者互不替代，也不会自动相互切换。

**个人 API 令牌**（默认方式，大多数人只需要它）：

```bash
hanakura config set sources.civitai.token <token>       # 或 HANAKURA_SOURCES__CIVITAI__TOKEN
```

**已连接账号**（OAuth，带 PKCE 的授权码流程）。它需要在 Civitai 注册一个 OAuth 应用，因为
client id 标识的是*这一份安装*：

```bash
hanakura config set auth.civitai.oauth_client_id <client id>
hanakura webui        # 然后在 设置 → Civitai 认证 中点击连接
hanakura auth status  # 当前使用哪种凭据，以及它保存在哪里
```

在 Civitai 注册的回调地址必须与服务器实际使用的完全一致，默认是
`http://127.0.0.1:7865/api/v1/auth/civitai/callback`。使用其他端口或主机，或者用 Vite
开发服务器开发界面时，请列出确切的地址：

```bash
hanakura config set auth.civitai.redirect_uris '["http://127.0.0.1:7865/api/v1/auth/civitai/callback", "http://localhost:5173/api/v1/auth/civitai/callback"]'
```

令牌只保存在服务器上：有操作系统凭据存储时存入其中，否则存为数据目录中仅本人可读的文件。它们不会
出现在 `settings.toml` 中，不会发送给浏览器，也不会写入下载记录。访问令牌在过期前约一分钟刷新，
即使多个下载同时请求也只刷新一次，轮换后的一对令牌作为整体保存。`hanakura auth disconnect`
会撤销授权并在本地清除它，API 令牌不受影响。

环境变量优先于以上两者，生效期间设置页会有相应提示。

### 符号链接

模型文件夹中的内容是指向另一块硬盘的符号链接（WebUI 的 LoRA 文件夹常常如此）时，无需额外配置即可
使用：默认跟随链接，因此链接的文件夹会被列出、可以打开并保持你浏览时的路径，也可以作为下载目标。
此时删除、移动和重命名会作用于文件的真实位置。

如果你希望界面无法触及模型文件夹之外的任何内容，可以关闭它：

```bash
hanakura config set library.follow_symlinks false
```

它也在「设置」的“内容”和“本地模型”部分中。关闭后，链接指向根目录之外的内容会直接从列表中隐藏，
而不是先显示出来再在打开时拒绝。无论哪种模式，包含 `..` 的路径、绝对路径和保留名称都会被拒绝，
通过链接环路重复到达的文件夹只遍历一次。

## Hanakura 在模型旁写入的文件

| 文件 | 用途 |
| --- | --- |
| `<name>.hanakura.json` | 来源元数据：模型和版本 ID、基础模型、触发词、SHA256 |
| `<name>.preview.<ext>` | 预览图，WebUI 自身的查找规则可以找到它 |
| `<name>.json` | 仅在开启 `downloads.write_webui_metadata` 且文件不存在时写入：WebUI 的用户元数据 |

## 开发

```bash
pip install -e ".[dev]"
python scripts/dev.py              # 列出开发任务
python scripts/dev.py dev          # 同时启动 API 服务器和网页界面，支持热重载
python scripts/dev.py check        # CI 运行的内容：lint、ty、测试、生成的类型
python scripts/dev.py typecheck-py # Python 类型检查；默认以 Python 3.10 为目标
python scripts/dev.py test         # pytest、vitest 和 vue-tsc
python scripts/dev.py format       # ruff 修复和格式化
python scripts/dev.py typegen      # 根据 OpenAPI 模式重新生成 src/api/schema.d.ts
```

开发界面时使用 `dev`：它同时启动 API 服务器和 Vite 开发服务器，在每行输出前标注 `api` 或
`web`，按 Ctrl+C 时两者一起停止。打开它输出的地址（默认 http://localhost:5173）；Vite 会把
`/api` 和 `/ws` 代理到 API 服务器，因此一个地址即可访问两者，界面支持热重载。

API 服务器重启期间，页面的套接字会自动重连，代理只提示一次：

```text
[api proxy] http://127.0.0.1:7865 is not answering (ECONNREFUSED). Start it with: hanakura webui --no-open
```

服务器恢复后数据会自动重新出现，不需要刷新页面。

```bash
python scripts/dev.py dev --api-port 8000 --web-port 3000 --data-dir ./dev-data
python scripts/dev.py web-dev      # 只启动界面，连接你自己启动的 API 服务器
hanakura webui --no-open       # 只启动 API 服务器
```

这些任务是一个小型 Python 脚本而不是 Makefile，因此在 Windows 上的用法完全相同。每个任务都会输出
它运行的命令，方便直接调用底层工具。

网页界面使用 [bun](https://bun.sh)。分层：`hanakura/core` 包含全部逻辑，不导入任何 Web 或 CLI
框架（有测试保证）；`hanakura/api`（FastAPI）和 `hanakura/cli`（Typer）是它之上的薄封装。

检测规则是 `hanakura/core/detection/rules_data/` 中的 JSON 文件。从真实文件添加测试夹具：
`python scripts/extract_header_fixture.py <file> <name>`。

## 构建

```bash
python scripts/build_wheel.py            # 先用 bun 构建网页界面，再把 wheel 和 sdist 输出到 dist/
python scripts/build_wheel.py --ci       # 用于 CI：跳过类型检查，保留已构建的网页界面
python scripts/build_wheel.py --outdir out --keep-web-dist
python scripts/dev.py wheel              # 同上，通过任务脚本运行
```

直接运行 `python -m build` 得到的 wheel 不含网页界面，因为 setuptools 只打包运行时已存在的文件；
此时服务器会记录一条警告，只提供 API。
