"""Read tensor names and shapes from model files without loading weights."""

import json
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

MAX_HEADER_BYTES = 100 * 1024 * 1024


class HeaderError(ValueError):
    """The file is not a readable safetensors or GGUF file."""


@dataclass
class ModelHeader:
    """Tensor names mapped to shapes, plus the file's own metadata."""

    format: str
    tensors: dict[str, list[int]]
    metadata: dict[str, Any] = field(default_factory=dict)


def parse_safetensors_header(data: bytes, file_size: int | None = None, max_header_bytes: int = MAX_HEADER_BYTES) -> ModelHeader:
    """Parse a safetensors header from the first bytes of a file.

    ``data`` must hold the 8-byte length and the whole JSON header. ``file_size`` enables the
    length check against the real file.
    """
    if len(data) < 8:
        raise HeaderError("file too short for a safetensors header")
    (length,) = struct.unpack("<Q", data[:8])
    if length < 2 or length > max_header_bytes or (file_size is not None and length > file_size - 8):
        raise HeaderError(f"implausible header length {length}")
    if len(data) < 8 + length:
        raise HeaderError("header truncated")
    try:
        header = json.loads(data[8 : 8 + length])
    except (UnicodeDecodeError, ValueError) as e:
        raise HeaderError(f"header is not JSON: {e}") from e
    if not isinstance(header, dict):
        raise HeaderError("header is not a JSON object")
    metadata = header.pop("__metadata__", None) or {}
    tensors: dict[str, list[int]] = {}
    for name, info in header.items():
        if isinstance(info, dict) and isinstance(info.get("shape"), list):
            tensors[name] = [int(x) for x in info["shape"]]
    return ModelHeader(format="safetensors", tensors=tensors, metadata=metadata if isinstance(metadata, dict) else {})


def read_safetensors_header(path: Path | str, max_header_bytes: int = MAX_HEADER_BYTES) -> ModelHeader:
    """Read only the header of a safetensors file."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(8)
        if len(head) < 8:
            raise HeaderError("file too short for a safetensors header")
        (length,) = struct.unpack("<Q", head)
        if length < 2 or length > max_header_bytes or length > size - 8:
            raise HeaderError(f"implausible header length {length}")
        return parse_safetensors_header(head + f.read(length), size, max_header_bytes)


# -- GGUF ---------------------------------------------------------------------

_GGUF_MAGIC = b"GGUF"
_GGUF_SCALARS = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
_GGUF_STRING, _GGUF_ARRAY = 8, 9
_MAX_ITEMS = 1_000_000
_MAX_STRING = 16 * 1024 * 1024


class _Reader:
    def __init__(self, f: BinaryIO) -> None:
        self.f = f

    def read(self, n: int) -> bytes:
        data = self.f.read(n)
        if len(data) != n:
            raise HeaderError("GGUF file truncated")
        return data

    def unpack(self, fmt: str) -> Any:
        return struct.unpack(fmt, self.read(struct.calcsize(fmt)))[0]

    def string(self) -> str:
        n = self.unpack("<Q")
        if n > _MAX_STRING:
            raise HeaderError("implausible GGUF string length")
        return self.read(n).decode("utf-8", errors="replace")

    def value(self, vtype: int, keep: bool = True) -> Any:
        if vtype in _GGUF_SCALARS:
            return self.unpack(_GGUF_SCALARS[vtype])
        if vtype == _GGUF_STRING:
            return self.string()
        if vtype == _GGUF_ARRAY:
            itype = self.unpack("<I")
            count = self.unpack("<Q")
            if count > _MAX_ITEMS * 100:
                raise HeaderError("implausible GGUF array length")
            items = [self.value(itype, keep) for _ in range(count)]
            # Large arrays such as tokenizer vocabularies are not useful for detection.
            return items if keep and count <= 64 else None
        raise HeaderError(f"unknown GGUF value type {vtype}")


def read_gguf_header(path: Path | str) -> ModelHeader:
    """Read the metadata and tensor table of a GGUF file. Shapes are returned in PyTorch order."""
    with open(path, "rb") as f:
        r = _Reader(f)
        if r.read(4) != _GGUF_MAGIC:
            raise HeaderError("not a GGUF file")
        version = r.unpack("<I")
        if version < 2:
            raise HeaderError(f"unsupported GGUF version {version}")
        n_tensors = r.unpack("<Q")
        n_kv = r.unpack("<Q")
        if n_tensors > _MAX_ITEMS or n_kv > _MAX_ITEMS:
            raise HeaderError("implausible GGUF counts")
        metadata: dict[str, Any] = {}
        for _ in range(n_kv):
            key = r.string()
            vtype = r.unpack("<I")
            value = r.value(vtype)
            if value is not None:
                metadata[key] = value
        tensors: dict[str, list[int]] = {}
        for _ in range(n_tensors):
            name = r.string()
            n_dims = r.unpack("<I")
            if n_dims > 8:
                raise HeaderError("implausible GGUF tensor rank")
            dims = [r.unpack("<Q") for _ in range(n_dims)]
            r.unpack("<I")  # type
            r.unpack("<Q")  # offset
            tensors[name] = list(reversed(dims))
    return ModelHeader(format="gguf", tensors=tensors, metadata=metadata)


def read_header(path: Path | str) -> ModelHeader:
    """Read the header of a safetensors or GGUF file, chosen by extension."""
    suffix = Path(path).suffix.lower()
    if suffix == ".gguf":
        return read_gguf_header(path)
    if suffix in (".safetensors", ".sft"):
        return read_safetensors_header(path)
    raise HeaderError(f"no readable header for {suffix} files")
