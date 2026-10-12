"""Bounded same-file parallel Range transfer, preserving a downloaded prefix."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import time

import acquire_models as assets


def transfer(url: str, chunk: dict, limit: int | None = None) -> dict:
    path = Path(chunk["path"])
    desired = chunk["end"] - chunk["start"] + 1
    initial = path.stat().st_size if path.exists() else 0
    desired = min(desired, initial + limit) if limit else desired
    started = time.monotonic()
    for attempt in range(5):
        current = path.stat().st_size if path.exists() else 0
        if current == desired:
            return {"bytes": current - initial, "elapsed_s": time.monotonic() - started}
        try:
            requested_start = chunk["start"] + current
            requested_end = chunk["start"] + desired - 1
            with assets.request(url, {"Range": f"bytes={requested_start}-{requested_end}"}) as response:
                expected = f"bytes {requested_start}-{requested_end}/{chunk['total']}"
                if response.status != 206 or response.headers.get("Content-Range") != expected:
                    raise RuntimeError(f"Range response mismatch: {response.status}, {response.headers.get('Content-Range')}")
                last = time.monotonic()
                with path.open("ab" if current else "wb") as stream:
                    while current < desired:
                        data = response.read(min(1024 * 1024, desired - current))
                        if not data:
                            raise RuntimeError("Range response ended early")
                        stream.write(data)
                        current += len(data)
                        now = time.monotonic()
                        if now - last > 20:
                            print(json.dumps({"chunk_start": chunk["start"], "downloaded": current, "chunk_size": desired, "MiB_s": round((current - initial) / (now - started) / 1048576, 2)}), flush=True)
                            last = now
        except Exception as exc:
            print(json.dumps({"chunk_start": chunk["start"], "attempt": attempt + 1, "error": str(exc)}), flush=True)
            if attempt == 4:
                raise
            time.sleep(min(5 * 2 ** attempt, 60))
    return {"bytes": desired - initial, "elapsed_s": time.monotonic() - started}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, choices=[x[0] for x in assets.SPECS])
    parser.add_argument("--connections", type=int, choices=[2, 3, 4], default=2)
    parser.add_argument("--probe-mib", type=int)
    args = parser.parse_args()
    spec = next(x for x in assets.SPECS if x[0] == args.model)
    name, repo, revision, selection = spec
    metadata = assets.metadata_request(f"https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true")
    if metadata["sha"] != revision:
        raise RuntimeError("Pinned metadata revision mismatch")
    entries = [x for x in metadata["siblings"] if selection is None or x["rfilename"] in selection]
    entry = max(entries, key=lambda x: x["size"])
    if "lfs" not in entry:
        raise RuntimeError("Parallel acquisition requires upstream full-file SHA256")
    target = assets.ROOT / ".local/models" / name / entry["rfilename"]
    target.parent.mkdir(parents=True, exist_ok=True)
    prefix = target.with_suffix(target.suffix + ".partial")
    directory = assets.ROOT / ".local/downloads/models" / name
    directory.mkdir(parents=True, exist_ok=True)
    state_path = directory / "range-state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state["revision"] != revision or state["sha256"] != entry["lfs"]["sha256"]:
            raise RuntimeError("Existing chunk source identity mismatch")
        if state["complete"]:
            if not assets.valid(target, entry):
                raise RuntimeError("Completed chunk transfer failed re-verification")
            assets.acquire(spec)
            return
    else:
        offset = prefix.stat().st_size if prefix.exists() else 0
        size = entry["size"]
        remaining = size - offset
        if remaining <= 0:
            if offset != size or not assets.valid(prefix, entry):
                raise RuntimeError("Complete preserved prefix failed size or SHA256 check")
            prefix.replace(target)
            assets.acquire(spec)
            return
        connections = min(args.connections, remaining)
        chunks = []
        for index in range(connections):
            start = offset + remaining * index // connections
            end = offset + remaining * (index + 1) // connections - 1
            chunks.append({"start": start, "end": end, "total": size, "path": str(directory / f"range-{start}-{end}.partial")})
        state = {"repo": repo, "revision": revision, "filename": entry["rfilename"], "sha256": entry["lfs"]["sha256"], "size": size, "prefix_bytes": offset, "connections": connections, "chunks": chunks, "complete": False, "probes": []}
        assets.write_json(state_path, state)
    if (prefix.stat().st_size if prefix.exists() else 0) != state["prefix_bytes"]:
        raise RuntimeError("Original partial prefix changed while chunk acquisition active")
    url = f"https://huggingface.co/{repo}/resolve/{revision}/{entry['rfilename']}"
    began = time.monotonic()
    with ThreadPoolExecutor(max_workers=state["connections"]) as pool:
        results = list(pool.map(lambda chunk: transfer(url, chunk, args.probe_mib * 1048576 if args.probe_mib else None), state["chunks"]))
    seconds = max(time.monotonic() - began, 1e-9)
    record = {"bytes": sum(x["bytes"] for x in results), "elapsed_s": seconds, "MiB_s": sum(x["bytes"] for x in results) / seconds / 1048576, "connections": state["connections"]}
    print(json.dumps(record), flush=True)
    if args.probe_mib:
        state["probes"].append(record)
        assets.write_json(state_path, state)
        return
    assembled = target.with_suffix(target.suffix + ".assembling")
    with assembled.open("wb") as output:
        if state["prefix_bytes"]:
            with prefix.open("rb") as stream:
                shutil.copyfileobj(stream, output, 8 * 1024 * 1024)
        for chunk in state["chunks"]:
            path = Path(chunk["path"])
            if path.stat().st_size != chunk["end"] - chunk["start"] + 1:
                raise RuntimeError("Chunk length mismatch")
            with path.open("rb") as stream:
                shutil.copyfileobj(stream, output, 8 * 1024 * 1024)
    if not assets.valid(assembled, entry):
        raise RuntimeError("Assembled model failed upstream SHA256 check")
    assembled.replace(target)
    state["complete"] = True
    state["transfer"] = record
    assets.write_json(state_path, state)
    assets.acquire(spec)
    manifest_path = assets.ROOT / ".local/manifests" / f"model-{name}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for file in manifest["files"]:
        if file["path"] == str(target.relative_to(assets.ROOT)):
            file["mode"] = "verified_parallel_range_download"
            file["range_state"] = str(state_path.relative_to(assets.ROOT))
    assets.write_json(manifest_path, manifest)


if __name__ == "__main__":
    main()
