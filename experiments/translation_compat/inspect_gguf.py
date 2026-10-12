"""Read GGUF tensor descriptors without loading tensors or modifying weights."""

import argparse
import json
from pathlib import Path
import struct


def inspect(path: Path) -> dict:
    with path.open("rb") as stream:
        def number(fmt):
            return struct.unpack(fmt, stream.read(struct.calcsize(fmt)))[0]

        def string(keep=True):
            length = number("<Q")
            if keep:
                return stream.read(length).decode("utf-8")
            stream.seek(length, 1)

        formats = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}

        def value(kind, keep):
            if kind in formats:
                return number(formats[kind])
            if kind == 8:
                return string(keep)
            if kind == 9:
                element_type, count = number("<I"), number("<Q")
                if not keep and element_type in formats:
                    stream.seek(struct.calcsize(formats[element_type]) * count, 1)
                    return
                result = [value(element_type, keep) for _ in range(count)]
                return result if keep else None
            raise ValueError(f"Unknown metadata type {kind}")

        if stream.read(4) != b"GGUF":
            raise ValueError("Not GGUF")
        version, tensor_count, metadata_count = number("<I"), number("<Q"), number("<Q")
        if version != 3:
            raise ValueError("Only GGUF v3 inspected")
        metadata = {}
        for _ in range(metadata_count):
            key, kind = string(), number("<I")
            keep = not key.startswith("tokenizer.")
            item = value(kind, keep)
            if keep:
                metadata[key] = item
        tensors = []
        for _ in range(tensor_count):
            name, dimensions = string(), number("<I")
            shape = [number("<Q") for _ in range(dimensions)]
            kind, offset = number("<I"), number("<Q")
            tensors.append({"name": name, "shape": shape, "type": kind, "offset": offset})
        return {"path": str(path.resolve()), "size": path.stat().st_size, "version": version, "tensor_count": tensor_count, "metadata": metadata, "tensors": tensors, "descriptor_end": stream.tell()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(inspect(args.model), stream, indent=2, ensure_ascii=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
