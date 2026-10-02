"""Build the web UI, then the wheel and the source distribution.

    python scripts/build_wheel.py [--ci] [--keep-web-dist] [--outdir DIR]

The order matters: setuptools packages only the files that exist when it runs, so the web UI has
to be built first. A bare ``python -m build`` therefore produces a package with no web UI.

Standard library only, so it runs anywhere the project does, Windows included.
"""

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "hanakura" / "webui"


def run(command: Sequence[str], cwd: Path = ROOT) -> None:
    """Run one command, echoing it first. Raises SystemExit with its status when it fails."""
    print(f"\033[36m$ {' '.join(str(c) for c in command)}\033[0m", file=sys.stderr, flush=True)
    status = subprocess.call([str(c) for c in command], cwd=cwd)
    if status != 0:
        raise SystemExit(status)


def build_web(ci: bool) -> None:
    if shutil.which("bun") is None:
        raise SystemExit("bun is needed to build the web UI. Install it from https://bun.sh")
    run(["bun", "install", "--frozen-lockfile"], cwd=WEB)
    # In CI the type-check and the tests run as their own steps, so the build only bundles.
    run(["bun", "run", "build:only" if ci else "build"], cwd=WEB)


def build_package(outdir: Path) -> None:
    run([sys.executable, "-m", "build", "--outdir", str(outdir), str(ROOT)])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/build_wheel.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ci", action="store_true", default=bool(os.environ.get("CI")), help="skip the web type-check (CI runs it separately) and keep the built web UI")
    parser.add_argument("--keep-web-dist", action="store_true", default=bool(os.environ.get("KEEP_WEB_DIST")), help="keep hanakura/webui/dist afterwards")
    parser.add_argument("--outdir", type=Path, default=ROOT / "dist", help="where to write the wheel and sdist (default: dist/)")
    args = parser.parse_args(argv)

    build_web(args.ci)
    try:
        build_package(args.outdir)
    finally:
        if not args.ci and not args.keep_web_dist:
            # Leave a local checkout as it was.
            shutil.rmtree(WEB / "dist", ignore_errors=True)
    built = sorted(p.name for p in args.outdir.glob("hanakura-*"))
    print("\nBuilt: " + ", ".join(built) if built else "\nNothing was built", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
