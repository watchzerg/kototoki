"""Read GGUF identity/template metadata without loading tensors or dependencies."""

from pathlib import Path
import struct
from typing import BinaryIO, Any


def metadata(path: Path) -> dict[str, Any]:
    def number(stream: BinaryIO, fmt: str) -> int:
        size = struct.calcsize(fmt)
        value = stream.read(size)
        if len(value) != size:
            raise ValueError("Truncated GGUF metadata")
        return struct.unpack(fmt, value)[0]

    def string(stream: BinaryIO, keep: bool = True) -> str | None:
        length = number(stream, "<Q")
        if keep:
            return stream.read(length).decode("utf-8")
        stream.seek(length, 1)
        return None

    def value(stream: BinaryIO, kind: int, keep: bool) -> Any:
        formats = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
        if kind in formats:
            return number(stream, formats[kind])
        if kind == 8:
            return string(stream, keep)
        if kind == 9:
            item_type, count = number(stream, "<I"), number(stream, "<Q")
            if item_type in formats and not keep:
                stream.seek(struct.calcsize(formats[item_type]) * count, 1)
                return None
            items = [value(stream, item_type, keep) for _ in range(count)]
            return items if keep else None
        raise ValueError(f"Unknown GGUF type {kind}")

    with path.open("rb") as stream:
        if stream.read(4) != b"GGUF":
            raise ValueError("Not a GGUF model")
        version = number(stream, "<I")
        if version not in (2, 3):
            raise ValueError(f"Unsupported GGUF version {version}")
        number(stream, "<Q")
        result = {}
        for _ in range(number(stream, "<Q")):
            key = string(stream)
            kind = number(stream, "<I")
            keep = key.startswith("general.") or "chat_template" in key or key.endswith("_token_id") or key.endswith("add_bos_token")
            item = value(stream, kind, keep)
            if keep:
                result[key] = item
        return result
