"""Resized preview images, cached in the data directory."""

import hashlib
import os
from pathlib import Path

from PIL import Image, ImageOps

ALLOWED_SIZES = (128, 256, 384, 512, 768)


def nearest_size(size: int) -> int:
    return next((s for s in ALLOWED_SIZES if s >= size), ALLOWED_SIZES[-1])


def thumbnail(source: Path, cache_dir: Path, size: int) -> tuple[Path, str]:
    """Return a cached WebP thumbnail of ``source`` no larger than ``size`` pixels, and its media type.

    Animated GIFs keep their first frame. The cache key includes the file's size and mtime.
    """
    size = nearest_size(size)
    st = source.stat()
    key = hashlib.sha1(f"{source}|{st.st_size}|{st.st_mtime_ns}|{size}".encode()).hexdigest()
    target = cache_dir / key[:2] / f"{key}.webp"
    if target.exists():
        return target, "image/webp"
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as img:
        img = ImageOps.exif_transpose(img)
        img.thumbnail((size, size * 2))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")
        tmp = target.with_suffix(".tmp")
        img.save(tmp, "WEBP", quality=82, method=4)
    os.replace(tmp, target)
    return target, "image/webp"
