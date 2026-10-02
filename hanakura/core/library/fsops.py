"""Low-level file moves that never overwrite."""

import errno
import os
import shutil
from pathlib import Path

from hanakura.core.errors import ConflictError, HanakuraError


def _tree_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def rename_no_overwrite(src: Path, dst: Path) -> None:
    """Rename on one filesystem, failing with ConflictError if ``dst`` exists."""
    if dst.exists() or dst.is_symlink():
        raise ConflictError(f"Target exists: {dst.name}", {"target": str(dst)})
    if src.is_file():
        try:
            # A hard link fails atomically when the target exists; then drop the old name.
            os.link(src, dst)
        except FileExistsError:
            raise ConflictError(f"Target exists: {dst.name}", {"target": str(dst)}) from None
        except OSError as e:
            if e.errno == errno.EXDEV:
                raise
        else:
            os.unlink(src)
            return
    os.rename(src, dst)


def move_path(src: Path, dst: Path) -> None:
    """Move a file or folder. Across filesystems: copy, verify the size, then delete the source."""
    if dst.exists() or dst.is_symlink():
        raise ConflictError(f"Target exists: {dst.name}", {"target": str(dst)})
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        rename_no_overwrite(src, dst)
        return
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
    copy_path(src, dst)
    if _tree_size(src) != _tree_size(dst):
        remove_path(dst)
        raise HanakuraError(f"Size check failed after copying {src.name}; source kept")
    remove_path(src)


def copy_path(src: Path, dst: Path) -> None:
    """Copy a file or folder into a temporary name next to ``dst``, then rename it into place."""
    if dst.exists() or dst.is_symlink():
        raise ConflictError(f"Target exists: {dst.name}", {"target": str(dst)})
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    if tmp.exists():
        remove_path(tmp)
    try:
        if src.is_dir():
            shutil.copytree(src, tmp)
        else:
            shutil.copy2(src, tmp)
        rename_no_overwrite(tmp, dst)
    except BaseException:
        if tmp.exists():
            remove_path(tmp)
        raise


def remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
