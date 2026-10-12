"""CLI for offline W0 inference; invoke with python -m experiments.w0_demo.run."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import time
import wave

from . import RECIPE
from .pipeline import run_pipeline

ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def read_audio(path: Path):
    import numpy as np
    with wave.open(str(path), "rb") as source:
        if (source.getnchannels(), source.getframerate(), source.getsampwidth(), source.getcomptype()) != (1, 16000, 2, "NONE"):
            raise ValueError("Input must be mono 16000 Hz PCM16 WAV; prepare a separate copy first")
        expected = source.getnframes() * 2
        pcm = source.readframes(source.getnframes())
    if not pcm or len(pcm) != expected:
        raise ValueError("Input WAV is empty or truncated")
    audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    return audio, {"path": str(path.resolve()), "file_sha256": sha256(path),
                   "pcm_sha256": hashlib.sha256(pcm).hexdigest(), "sample_rate": 16000,
                   "channels": 1, "samples": len(audio), "duration_s": len(audio) / 16000,
                   "representation": "float32 PCM16 / 32768"}


def setup_runtime(out: Path, dll_dir: Path) -> list:
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY"):
        os.environ[name] = "1"
    os.environ.update(HF_HOME=str(out / "cache/huggingface"), TORCH_HOME=str(out / "cache/torch"),
                      PYANNOTE_METRICS_ENABLED="0", TOKENIZERS_PARALLELISM="false")
    if os.name == "nt":
        if not dll_dir.is_dir():
            raise FileNotFoundError(f"Provisioned CUDA DLL directory required: {dll_dir}")
        os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ["PATH"]
        return [os.add_dll_directory(str(dll_dir))]
    return []


@contextmanager
def gpu_lock(path: Path, recipe: str = RECIPE):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, json.dumps({"pid": os.getpid(), "recipe": recipe}).encode())
        os.close(fd)
        fd = None
        yield
    finally:
        if fd is not None:
            os.close(fd)
        path.unlink()


def frozen_chunks(path: Path, identity: dict, offset: float) -> list[dict]:
    saved = json.loads(path.read_text(encoding="utf-8"))
    if (saved.get("input", {}).get("pcm_sha256") != identity["pcm_sha256"]
            or saved.get("input", {}).get("file_sha256") != identity["file_sha256"]
            or saved.get("offset_s") != offset):
        raise ValueError("Frozen VAD input identity/source offset differs")
    return saved["chunks"]


def read_vad_manifest(path: Path, identity: dict, offset: float) -> dict:
    """Validate standalone VAD evidence without importing inference dependencies."""
    saved = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(saved, dict) or isinstance(saved.get("schema_version"), bool)
            or saved.get("schema_version") != 1 or saved.get("status") != "ok"):
        raise ValueError("VAD manifest requires schema_version=1 and status=ok")
    source = saved.get("input")
    keys = ("file_sha256", "pcm_sha256", "sample_rate", "channels", "samples", "duration_s")
    if not isinstance(source, dict) or any(
            key not in source or key not in identity or isinstance(source[key], bool)
            or source[key] != identity[key] for key in keys):
        raise ValueError("VAD manifest input identity differs or is incomplete")
    if "representation" in source and source["representation"] != identity.get("representation"):
        raise ValueError("VAD manifest input representation differs")
    source_offset = saved.get("offset_s")
    if (isinstance(source_offset, bool) or not isinstance(source_offset, (int, float))
            or not math.isfinite(source_offset) or source_offset < 0 or source_offset != offset):
        raise ValueError("VAD manifest source offset differs or is invalid")
    vad_id = saved.get("vad_id")
    if not isinstance(vad_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", vad_id):
        raise ValueError("VAD manifest vad_id must be a lowercase alphanumeric/hyphen identity")
    if not isinstance(saved.get("recipe"), str) or not saved["recipe"].strip():
        raise ValueError("VAD manifest recipe is required")
    if not isinstance(saved.get("metadata"), dict):
        raise ValueError("VAD manifest metadata must be an object")
    stages = saved.get("stages")
    if (not isinstance(stages, dict) or not {"vad_load_s", "vad_inference_s"}.issubset(stages)
            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not math.isfinite(value) or value < 0 for value in stages.values())):
        raise ValueError("VAD manifest requires finite nonnegative load/inference stage costs")
    chunks = saved.get("chunks")
    if not isinstance(chunks, list):
        raise ValueError("VAD manifest chunks must be a list")
    previous = 0.0
    from .alignment import sample_window
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            raise ValueError(f"VAD manifest chunk {index} must be an object")
        start, end = chunk.get("start"), chunk.get("end")
        exact = sample_window(chunk, identity["samples"])
        if (any(isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) for value in (start, end))
                or not previous <= start < end <= identity["duration_s"]
                or not 0 < (exact[1] - exact[0] if exact else
                            int(end * 16000) - int(start * 16000)) <= 480000):
            raise ValueError(f"VAD manifest chunk {index} is outside ordered source sample bounds")
        previous = end
        spans = chunk.get("segments")
        if not isinstance(spans, list):
            raise ValueError(f"VAD manifest chunk {index} requires constituent segments")
        span_end = start
        for span in spans:
            if (not isinstance(span, list) or len(span) != 2
                    or any(isinstance(value, bool) or not isinstance(value, (int, float))
                           or not math.isfinite(value) for value in span)
                    or not span_end <= span[0] < span[1] <= end):
                raise ValueError(f"VAD manifest chunk {index} has invalid constituent segments")
            span_end = span[1]
    return saved


def attach_vad_manifest(result: dict, manifest: dict, path: Path, digest: str) -> None:
    """Link external neural VAD costs while leaving runner replay costs intact."""
    result["recipe"] = f"w0-{manifest['vad_id']}-mms-v1"
    result["vad_manifest_source"] = {"path": str(path.resolve()), "sha256": digest,
                                     "snapshot": "vad-manifest.json", "recipe": manifest["recipe"],
                                     "vad_id": manifest["vad_id"]}
    result["precomputed_vad"] = {
        "fresh_inference_in_runner": False, "stages": dict(manifest["stages"]),
        "accounting": "External VAD process costs; excluded from runner stages and wall_s",
        "input": dict(manifest["input"]), "offset_s": manifest["offset_s"],
    }


def private_output(path: Path) -> Path:
    resolved = path.resolve()
    private_root = (ROOT / ".local/w0-demo").resolve()
    if not resolved.is_relative_to(private_root) or resolved == private_root:
        raise ValueError("Run output must be a new child directory of .local/w0-demo")
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser(description="Reusable offline W0 baseline (prepared PCM16 mono16k WAV)")
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="New private run directory; existing paths are rejected")
    parser.add_argument("--offset", type=float, default=0)
    parser.add_argument("--asr-model", type=Path, default=ROOT / ".local/models/faster-whisper-large-v3")
    parser.add_argument("--mms-model", type=Path, default=ROOT / ".local/models/mms-1b-all")
    parser.add_argument("--vad-checkpoint", type=Path, default=ROOT / ".local/models/w0-assets/pytorch_model.bin")
    parser.add_argument("--mel-filters", type=Path, default=ROOT / ".local/models/w0-assets/mel_filters.npz")
    vad_source = parser.add_mutually_exclusive_group()
    vad_source.add_argument("--frozen-vad", type=Path, help="Replay chunks from a prior W0 result with identical input identity")
    vad_source.add_argument("--vad-manifest", type=Path, help="Standalone VAD manifest with source identity and external stage costs")
    parser.add_argument("--dll-dir", type=Path, default=ROOT / ".local/tools/whisper-runtime-provisional")
    args = parser.parse_args()
    if not math.isfinite(args.offset) or args.offset < 0:
        parser.error("--offset must be finite and nonnegative")
    args.out = private_output(args.out)
    args.out.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    handles = []
    recipe = RECIPE
    try:
        handles = setup_runtime(args.out, args.dll_dir)
        source_dir = args.out / "source"
        source_dir.mkdir()
        sources = {}
        for path in Path(__file__).parent.glob("*.py"):
            shutil.copy2(path, source_dir / path.name)
            sources[path.name] = sha256(path)
        shutil.copy2(Path(__file__).with_name("THIRD_PARTY_NOTICES.txt"), source_dir / "THIRD_PARTY_NOTICES.txt")
        schema_path = ROOT / "kototoki_eval/schema.py"
        shutil.copy2(schema_path, source_dir / "kototoki_eval_schema.py")
        shared_sources = {"kototoki_eval/schema.py": sha256(schema_path)}
        audio, identity = read_audio(args.audio)
        manifest = None
        manifest_digest = None
        if args.vad_manifest:
            mark = time.perf_counter()
            manifest = read_vad_manifest(args.vad_manifest, identity, args.offset)
            snapshot = args.out / "vad-manifest.json"
            shutil.copy2(args.vad_manifest, snapshot)
            if json.loads(snapshot.read_text(encoding="utf-8")) != manifest:
                raise RuntimeError("VAD manifest changed while validating; rerun with an immutable manifest")
            manifest_digest = sha256(snapshot)
            manifest_read = time.perf_counter() - mark
            recipe = f"w0-{manifest['vad_id']}-mms-v1"
        from .asr import WhisperAsr
        from .vad import FrozenVad, PyannoteVad
        from .alignment import MmsAligner
        with gpu_lock(ROOT / ".local/gpu.lock", recipe):
            mark = time.perf_counter()
            vad = (FrozenVad(manifest["chunks"]) if manifest is not None else
                   FrozenVad(frozen_chunks(args.frozen_vad, identity, args.offset)) if args.frozen_vad
                   else PyannoteVad(args.vad_checkpoint))
            if manifest is not None:
                vad.metadata.update(source_kind="standalone-vad-manifest", vad_id=manifest["vad_id"],
                                    origin_metadata=manifest["metadata"], origin_recipe=manifest["recipe"])
            vad_load = time.perf_counter() - mark
            result = run_pipeline(audio, vad, lambda: WhisperAsr(args.asr_model, args.mel_filters),
                                  lambda: MmsAligner(args.mms_model), offset=args.offset)
        result["input"] = identity
        result["stages"]["vad_load_s"] = vad_load
        if manifest is not None:
            attach_vad_manifest(result, manifest, args.vad_manifest, manifest_digest)
            result["stages"]["vad_manifest_read_s"] = manifest_read
        result["stages"]["wall_s"] = time.perf_counter() - started
        result["runtime_identity"] = {"python": sys.version, "packages": {
            name: importlib.metadata.version(name) for name in
            ("faster-whisper", "ctranslate2", "pyannote.audio", "torch", "torchaudio", "transformers")},
            "whisperx_imported": any(k == "whisperx" or k.startswith("whisperx.") for k in sys.modules)}
        if any(sha256(Path(__file__).parent / name) != digest for name, digest in sources.items()):
            raise RuntimeError("W0 source changed during inference; keep this run as failed and rerun a frozen version")
        if any(sha256(ROOT / name) != digest for name, digest in shared_sources.items()):
            raise RuntimeError("Shared validation source changed during inference")
        result["source_sha256"] = sources
        result["shared_source_sha256"] = shared_sources
        result["asset_sha256"] = {"mel_filters": sha256(args.mel_filters),
            "asr_model": sha256(args.asr_model / "model.bin"),
            "mms_adapter": sha256(args.mms_model / "adapter.jpn.safetensors")}
        result["model_files_sha256"] = {
            label: {str(path.relative_to(folder)): sha256(path) for path in sorted(folder.rglob("*"))
                    if path.is_file() and path.suffix in {".json", ".safetensors", ".bin", ".txt"}}
            for label, folder in (("asr", args.asr_model), ("mms", args.mms_model))}
        if args.frozen_vad:
            result["frozen_vad_source"] = {"path": str(args.frozen_vad.resolve()), "sha256": sha256(args.frozen_vad)}
        if manifest is not None and sha256(args.vad_manifest) != manifest_digest:
            raise RuntimeError("VAD manifest changed during inference")
        if not args.frozen_vad and manifest is None:
            result["asset_sha256"]["vad_checkpoint"] = sha256(args.vad_checkpoint)
        write_json(args.out / "result.json", result)
        (args.out / "transcript.txt").write_text(result["text"], encoding="utf-8")
        print(json.dumps({"status": "ok", "recipe": recipe, "segments": len(result["original_segments"]),
                          "characters": len(result["text"]), "stages": result["stages"],
                          "result": str((args.out / "result.json").resolve())}))
    except Exception as error:
        write_json(args.out / "failure.json", {"status": "failed", "exception": type(error).__name__,
                                              "message": str(error), "recipe": recipe})
        raise
    finally:
        for handle in handles:
            handle.close()


if __name__ == "__main__":
    main()
