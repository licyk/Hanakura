"""Developer tasks, in one place: ``python scripts/dev.py <task>``.

A Python task runner rather than a Makefile, because this project is installed and developed on
Windows as often as on Linux, and ``make`` is not there. It uses only the standard library and
runs the same tools CI runs. Tool configuration lives in ``pyproject.toml``.

Run ``python scripts/dev.py`` with no arguments to list the tasks.
"""

import argparse
import inspect
import os
import shutil
import signal
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "hanakura" / "webui"
PYTHON_PATHS = ["hanakura", "tests", "scripts"]
SCHEMA = WEB / "src" / "api" / "schema.d.ts"
DEFAULT_API_PORT = 7865
DEFAULT_WEB_PORT = 5173

# A task takes the options left on the command line, which most ignore.
TASKS: dict[str, Callable[[list[str]], int]] = {}
HELP: dict[str, str] = {}


def task(name: str, help_text: str) -> Callable[[Callable[..., int]], Callable[..., int]]:
    def register(fn: Callable[..., int]) -> Callable[..., int]:
        takes_options = bool(inspect.signature(fn).parameters)

        def call(options: list[str]) -> int:
            if takes_options:
                return fn(options)
            if options:
                print(f"{name} takes no options, but got: {' '.join(options)}", file=sys.stderr)
                return 2
            return fn()

        TASKS[name] = call
        HELP[name] = help_text
        return fn

    return register


def run(command: Sequence[str], cwd: Path = ROOT, stdout: int | None = None, env: dict[str, str] | None = None) -> int:
    """Run one command, echoing it first. Returns its exit status."""
    print(f"\033[36m$ {' '.join(str(c) for c in command)}\033[0m", file=sys.stderr, flush=True)
    return subprocess.call([str(c) for c in command], cwd=cwd, stdout=stdout, env={**os.environ, **(env or {})})


def python(*args: str, **kwargs: object) -> int:
    """Run a module with the interpreter running this script, not whatever is on PATH."""
    return run([sys.executable, *args], **kwargs)  # type: ignore[arg-type]


def bun(*args: str, cwd: Path = WEB) -> int:
    """Run bun in the web UI folder. Missing bun is a clear error, not a traceback."""
    if shutil.which("bun") is None:
        print("bun is needed for the web UI tasks. Install it from https://bun.sh, or skip them.", file=sys.stderr)
        return 127
    return run(["bun", *args], cwd=cwd)


def first_failure(*results: int) -> int:
    return next((r for r in results if r != 0), 0)


COLOURS = ["\033[35m", "\033[36m", "\033[33m"]


def run_parallel(processes: list[tuple[str, Sequence[str], Path, dict[str, str]]]) -> int:
    """Run several long-lived commands together, tagging each line with the name of its process.

    They stop together: when one exits, the others are stopped too, and Ctrl+C stops all of them.
    Returns the exit status of the first one that failed.
    """
    started: list[tuple[str, subprocess.Popen[bytes]]] = []
    readers: list[threading.Thread] = []
    lock = threading.Lock()
    stop = threading.Event()
    # Handle the signals here rather than relying on KeyboardInterrupt: a process started in the
    # background inherits SIGINT ignored, and a plain SIGTERM would otherwise orphan the children.
    previous: dict[int, object] = {}

    def on_signal(signum: int, _frame: object) -> None:
        print(f"\n\033[33mStopping ({signal.Signals(signum).name}).\033[0m", file=sys.stderr)
        stop.set()

    def pump(name: str, colour: str, proc: subprocess.Popen[bytes]) -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            with lock:
                print(f"{colour}{name:>3}\033[0m │ {line}", flush=True)

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, on_signal)
        for i, (name, command, cwd, env) in enumerate(processes):
            print(f"\033[36m$ {' '.join(str(c) for c in command)}\033[0m", file=sys.stderr, flush=True)
            proc = subprocess.Popen(
                [str(c) for c in command],
                cwd=cwd,
                env={**os.environ, **env},
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                # Its own process group, so Ctrl+C in this terminal is delivered by us, once.
                start_new_session=os.name != "nt",
            )
            started.append((name, proc))
            reader = threading.Thread(target=pump, args=(name, COLOURS[i % len(COLOURS)], proc), daemon=True)
            reader.start()
            readers.append(reader)

        while not stop.is_set():
            for name, proc in started:
                status = proc.poll()
                if status is not None:
                    print(f"\n\033[33m{name} exited with status {status}; stopping the rest.\033[0m", file=sys.stderr)
                    return status
            stop.wait(0.2)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)  # type: ignore[arg-type]
        _stop_all(started)
        for reader in readers:
            reader.join(timeout=2)


def _stop_all(started: list[tuple[str, subprocess.Popen[bytes]]]) -> None:
    for _, proc in started:
        if proc.poll() is None:
            if os.name != "nt":
                os.killpg(proc.pid, signal.SIGTERM)
            else:
                proc.terminate()
    for _, proc in started:
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


# -- Python ------------------------------------------------------------------


@task("lint", "Check formatting and lint rules (ruff), changing nothing")
def lint() -> int:
    return first_failure(
        python("-m", "ruff", "check", *PYTHON_PATHS),
        python("-m", "ruff", "format", "--check", *PYTHON_PATHS),
    )


@task("format", "Apply ruff's safe fixes and format the Python code")
def format_code() -> int:
    return first_failure(
        python("-m", "ruff", "check", "--fix", *PYTHON_PATHS),
        python("-m", "ruff", "format", *PYTHON_PATHS),
    )


@task("test-py", "Run the Python tests")
def test_py() -> int:
    return python("-m", "pytest")


@task("typecheck-py", "Check Python types with ty")
def typecheck_py(options: list[str] | None = None) -> int:
    return python("-m", "ty", "check", "--python", sys.executable, *(options or []))


# -- Web UI ------------------------------------------------------------------


@task("web-install", "Install the web UI dependencies")
def web_install() -> int:
    return bun("install")


@task("web", "Build the web UI into hanakura/webui/dist")
def web_build() -> int:
    return bun("run", "build")


@task("web-dev", "Serve only the web UI (expects an API server already running)")
def web_dev() -> int:
    return bun("run", "dev")


@task("dev", "Run the API server and the web UI together, with hot reload (Ctrl+C stops both)")
def dev(options: list[str]) -> int:
    """The Vite dev server proxies /api and /ws to the API server, so one address serves both."""
    parser = argparse.ArgumentParser(prog="python scripts/dev.py dev", description="Run the API server and the web UI together.")
    parser.add_argument("--api-port", type=int, default=DEFAULT_API_PORT, help=f"port for the API server (default: {DEFAULT_API_PORT})")
    parser.add_argument("--web-port", type=int, default=DEFAULT_WEB_PORT, help=f"port for the web UI (default: {DEFAULT_WEB_PORT})")
    parser.add_argument("--data-dir", help="data directory for the API server (settings, database, caches)")
    args = parser.parse_args(options)

    if shutil.which("bun") is None:
        print("bun is needed for the web UI. Install it from https://bun.sh", file=sys.stderr)
        return 127
    if not (WEB / "node_modules").is_dir():
        print("The web UI dependencies are missing. Run: python scripts/dev.py web-install", file=sys.stderr)
        return 1

    api_command = [sys.executable, "-m", "hanakura", "webui", "--no-open", "--port", str(args.api_port), "--strict-port"]
    if args.data_dir:
        api_command += ["--data-dir", args.data_dir]
    api_env = {"PYTHONUNBUFFERED": "1", "PYTHONPATH": str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    # The dev server proxies to the API port chosen here.
    web_env = {"HANAKURA_BACKEND": f"http://127.0.0.1:{args.api_port}", "FORCE_COLOR": "1"}

    # The dev server binds localhost, which is IPv6 on some machines, so it is named as localhost.
    print(f"\n  Web UI  http://localhost:{args.web_port}\n  API     http://127.0.0.1:{args.api_port}\n", file=sys.stderr)
    return run_parallel(
        [
            ("api", api_command, ROOT, api_env),
            ("web", ["bun", "run", "dev", "--port", str(args.web_port), "--strictPort"], WEB, web_env),
        ]
    )


@task("test-web", "Run the web UI tests and type-check")
def test_web() -> int:
    return first_failure(bun("run", "test"), bun("run", "typecheck"))


# -- The OpenAPI contract ----------------------------------------------------


@task("openapi", "Print the OpenAPI schema on standard output")
def openapi() -> int:
    return python(str(ROOT / "scripts" / "generate_openapi.py"))


@task("typegen", "Regenerate the web UI's types from the OpenAPI schema (commit the result)")
def typegen() -> int:
    tmp = WEB / "openapi.json"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            status = python(str(ROOT / "scripts" / "generate_openapi.py"), stdout=f.fileno())
        if status != 0:
            return status
        return bun("x", "openapi-typescript", tmp.name, "-o", str(SCHEMA.relative_to(WEB)))
    finally:
        tmp.unlink(missing_ok=True)


@task("typegen-check", "Fail when the committed types are out of date (for CI)")
def typegen_check() -> int:
    status = typegen()
    if status != 0:
        return status
    return run(["git", "diff", "--exit-code", "--", str(SCHEMA.relative_to(ROOT))])


# -- Release -----------------------------------------------------------------


@task("wheel", "Build the web UI, then the wheel and sdist into dist/")
def wheel() -> int:
    """Delegates to scripts/build_wheel.py, which is also runnable on its own (CI, release)."""
    return python(str(ROOT / "scripts" / "build_wheel.py"))


# -- Groups ------------------------------------------------------------------


@task("test", "Run every test: Python, web UI and the type-check")
def test_all() -> int:
    return first_failure(test_py(), test_web())


@task("check", "Everything CI runs: lint, Python types, tests, and the generated types")
def check() -> int:
    return first_failure(lint(), typecheck_py(), test_py(), test_web(), typegen_check())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python scripts/dev.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="tasks:\n" + "\n".join(f"  {name:<14} {HELP[name]}" for name in TASKS),
    )
    parser.add_argument("tasks", nargs="*", metavar="task", help="one or more tasks to run, in order")
    # Task names come first; everything from the first option onwards belongs to that task,
    # for example: dev.py dev --api-port 8000
    argv = sys.argv[1:] if argv is None else argv
    split = next((i for i, a in enumerate(argv) if a.startswith("-")), len(argv))
    names, options = argv[:split], argv[split:]
    args = parser.parse_args(argv if not names else names)
    if not args.tasks:
        parser.print_help()
        return 0
    unknown = [t for t in args.tasks if t not in TASKS]
    if unknown:
        parser.error(f"unknown task {unknown[0]!r}. Tasks: {', '.join(TASKS)}")
    if options and len(args.tasks) > 1:
        parser.error("options can only be given when running a single task")
    for name in args.tasks:
        status = TASKS[name](options)
        if status != 0:
            print(f"\033[31m{name} failed with status {status}\033[0m", file=sys.stderr)
            return status
    return 0


if __name__ == "__main__":
    sys.exit(main())
