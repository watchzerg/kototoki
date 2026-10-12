"""Acquire pinned experiment assets sequentially, with integrity and resume checks."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
SPECS = [
    ("faster-whisper-large-v3", "Systran/faster-whisper-large-v3", "edaa852ec7e145841d8ffdb056a99866b5f0a478", None),
    ("qwen3-asr-1.7b-hf", "Qwen/Qwen3-ASR-1.7B-hf", "bcd2b5b7f32b480ab5790554cfa8347f246a14f3", None),
    ("qwen3-forcedaligner-0.6b-hf", "Qwen/Qwen3-ForcedAligner-0.6B-hf", "c07281df297b9905d24a508279258cccf987a064", None),
    ("wav2vec2-large-xlsr-53-japanese", "jonatasgrosman/wav2vec2-large-xlsr-53-japanese", "cf031e020336460d15a417eba710bbc5bb43be9a", ["README.md", "config.json", "preprocessor_config.json", "special_tokens_map.json", "vocab.json", "tokenizer_config.json", "pytorch_model.bin"]),
    ("crisp-qwen3-asr-1.7b-f16", "cstr/qwen3-asr-1.7b-GGUF", "674df5d44b50a63e7102a18895ed20e3f91de301", ["qwen3-asr-1.7b-f16.gguf", "README.md"]),
    ("crisp-qwen3-forced-aligner-0.6b-f16", "cstr/qwen3-forced-aligner-0.6b-GGUF", "1ec5110602ccab18c878ddebedab0891e290a95c", ["qwen3-forced-aligner-0.6b-f16.gguf", "README.md"]),
    ("crisp-silero-v6.2.0", "ggml-org/whisper-vad", "9ffd54a1e1ee413ddf265af9913beaf518d1639b", ["README.md", "ggml-silero-v6.2.0.bin"]),
]

def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)

def digests(path: Path) -> tuple[str, str]:
    sha = hashlib.sha256()
    git = hashlib.sha1(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            sha.update(chunk)
            git.update(chunk)
    return sha.hexdigest(), git.hexdigest()

def valid(path: Path, entry: dict) -> bool:
    if not path.is_file() or path.stat().st_size != entry["size"]:
        return False
    sha, git = digests(path)
    return sha == entry["lfs"]["sha256"] if "lfs" in entry else git == entry["blobId"]

def request(url: str, headers: dict | None = None):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Kototoki-local-experiment/1", **(headers or {})}), timeout=90)

def metadata_request(url: str) -> dict:
    for attempt in range(5):
        try:
            with request(url) as stream:
                return json.load(stream)
        except Exception:
            if attempt == 4:
                raise
            time.sleep(min(5 * 2 ** attempt, 60))
    raise AssertionError("unreachable")

def download(url: str, target: Path, entry: dict) -> dict:
    partial = target.with_suffix(target.suffix + ".partial")
    target.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    initial = partial.stat().st_size if partial.exists() else 0
    for attempt in range(5):
        offset = partial.stat().st_size if partial.exists() else 0
        try:
            if offset < entry["size"]:
                with request(url, {"Range": f"bytes={offset}-"} if offset else {}) as response:
                    if offset and response.status != 206:
                        raise RuntimeError("Server refused range; partial retained to avoid silent restart")
                    if offset and not response.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                        raise RuntimeError("Wrong Content-Range")
                    last = time.monotonic()
                    with partial.open("ab" if offset else "wb") as stream:
                        while chunk := response.read(1024 * 1024):
                            stream.write(chunk)
                            offset += len(chunk)
                            now = time.monotonic()
                            if now - last >= 15:
                                elapsed = now - started
                                rate = max((offset - initial) / elapsed, 1)
                                print(json.dumps({"file": target.name, "bytes": offset, "total": entry["size"], "MiB_s": round(rate / 1048576, 2), "eta_s": round((entry["size"] - offset) / rate)}), flush=True)
                                last = now
            if not valid(partial, entry):
                raise RuntimeError("Downloaded file integrity mismatch; partial retained for diagnosis")
            partial.replace(target)
            return {"mode": "download", "elapsed_s": round(time.monotonic() - started, 3), "new_bytes": entry["size"] - initial}
        except Exception as exc:
            print(json.dumps({"file": target.name, "attempt": attempt + 1, "error": str(exc), "partial_bytes": partial.stat().st_size if partial.exists() else 0}), flush=True)
            if attempt == 4:
                raise
            time.sleep(min(5 * 2 ** attempt, 60))
    raise AssertionError("unreachable")

def candidates(repo: str, revision: str, filename: str) -> list[Path]:
    cache = Path.home() / ".cache/huggingface/hub" / ("models--" + repo.replace("/", "--"))
    choices = [cache / "snapshots" / revision / filename]
    if filename.endswith((".json", ".jinja", ".txt")):
        choices.extend((ROOT / ".local/models").glob("*/" + filename))
    if filename.endswith(".safetensors"):
        for sibling in ("Qwen/Qwen3-ASR-1.7B", "Qwen/Qwen3-ForcedAligner-0.6B"):
            sibling_cache = cache.parent / ("models--" + sibling.replace("/", "--"))
            choices.extend(sibling_cache.glob("snapshots/*/" + filename))
    if filename.endswith(".gguf"):
        choices.append(ROOT.parent / "subtitle-edit-fix/models/diagnostic" / filename)
        choices.append(Path.home() / "AppData/Roaming/Subtitle Edit/CrispASR/models" / filename)
    return choices

def acquire(spec: tuple) -> None:
    name, repo, revision, selection = spec
    api = f"https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true"
    metadata = metadata_request(api)
    if metadata["sha"] != revision:
        raise RuntimeError("Revision mismatch")
    meta_path = ROOT / ".local/manifests" / f"model-{name}-source.json"
    write_json(meta_path, metadata)
    files = [x for x in metadata["siblings"] if x["rfilename"] != ".gitattributes" and (selection is None or x["rfilename"] in selection)]
    # Only one compatible weight representation is required for HF/CTC.
    if any(x["rfilename"].endswith(".safetensors") for x in files):
        files = [x for x in files if not x["rfilename"].endswith((".bin", ".h5", ".msgpack"))]
    files.sort(key=lambda item: (item["size"] > 100_000_000, item["rfilename"]))
    manifest = {"repo": repo, "revision": revision, "license": metadata.get("cardData", {}).get("license"), "source_api": api, "checked_date": "2026-10-04", "files": [], "complete": False}
    manifest_path = ROOT / ".local/manifests" / f"model-{name}.json"
    previous = {}
    if manifest_path.exists():
        saved = json.loads(manifest_path.read_text(encoding="utf-8"))
        if saved.get("revision") == revision:
            previous = {record["path"]: record for record in saved.get("files", [])}
    for entry in files:
        filename = entry["rfilename"]
        target = ROOT / ".local/models" / name / filename
        url = f"https://huggingface.co/{repo}/resolve/{revision}/{filename}"
        operation = {"mode": "existing_verified"}
        if not valid(target, entry):
            reused = False
            for source in candidates(repo, revision, filename):
                if valid(source, entry):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    if not valid(target, entry):
                        raise RuntimeError("Local copied file integrity mismatch")
                    operation = {"mode": "verified_local_copy", "copy_source": str(source)}
                    reused = True
                    break
            if not reused:
                operation = download(url, target, entry)
        sha, git = digests(target)
        saved_record = previous.get(str(target.relative_to(ROOT)))
        if operation["mode"] == "existing_verified" and saved_record and saved_record.get("sha256") == sha:
            operation = {key: saved_record[key] for key in ("mode", "copy_source", "elapsed_s", "new_bytes", "range_state") if key in saved_record}
            operation["reverified"] = True
        manifest["files"].append({"path": str(target.relative_to(ROOT)), "source_url": url, "size": entry["size"], "sha256": sha, "git_blob": git, "upstream_lfs_sha256": entry.get("lfs", {}).get("sha256"), **operation})
        write_json(manifest_path, manifest)
        print(json.dumps({"ready": str(target), **operation}), flush=True)
    manifest["complete"] = True
    write_json(manifest_path, manifest)
    print(json.dumps({"model_ready": name, "manifest": str(manifest_path)}), flush=True)

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", action="append", choices=[spec[0] for spec in SPECS])
    args = parser.parse_args()
    failures = []
    for spec in SPECS:
        if not args.only or spec[0] in args.only:
            try:
                acquire(spec)
            except Exception as exc:
                failure = {"model": spec[0], "repo": spec[1], "revision": spec[2], "error": str(exc), "partial_files_retained": True}
                write_json(ROOT / ".local/manifests" / f"model-{spec[0]}-failure.json", failure)
                print(json.dumps(failure), flush=True)
                failures.append(spec[0])
    if failures:
        raise SystemExit("Acquisition failed for: " + ", ".join(failures))

if __name__ == "__main__":
    main()
