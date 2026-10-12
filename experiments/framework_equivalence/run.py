"""Frozen same-VAD framework comparison; all detailed outputs remain private."""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import wave

ROOT = Path(os.environ.get("KOTOTOKI_EXPERIMENT_ROOT", Path(__file__).resolve().parents[2])).resolve()


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def setup(out: Path) -> list[object]:
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY"):
        os.environ[name] = "1"
    os.environ.update(HF_HOME=str(out / "cache"), TORCH_HOME=str(out / "cache/torch"),
                      NLTK_DATA=str(ROOT / ".local/cache/whisper-nltk"), PYANNOTE_METRICS_ENABLED="0",
                      TOKENIZERS_PARALLELISM="false")
    dll = ROOT / ".local/tools/whisper-runtime-provisional"
    os.environ["PATH"] = str(dll) + os.pathsep + os.environ["PATH"]
    return [os.add_dll_directory(str(dll))] if os.name == "nt" else []


def audio(path: Path):
    import numpy as np
    with wave.open(str(path), "rb") as stream:
        if (stream.getnchannels(), stream.getframerate(), stream.getsampwidth()) != (1, 16000, 2):
            raise ValueError("Prepared PCM16 mono16k required")
        return np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2").astype(np.float32) / 32768


class Capture:
    def __init__(self, inner):
        self.inner, self.calls = inner, []

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def generate(self, encoded, prompts, **kwargs):
        results = self.inner.generate(encoded, prompts, **kwargs)
        self.calls.append({"prompts": prompts, "kwargs": kwargs,
                           "results": [{"tokens": r.sequences_ids[0], "scores": r.scores} for r in results]})
        return results


def wx(out: Path, clips: list[dict]):
    handles = setup(out)
    import numpy as np
    import torch
    import whisperx
    from whisperx.vads import Pyannote
    mark = time.perf_counter()
    model = whisperx.load_model(str(ROOT / ".local/models/faster-whisper-large-v3"), "cuda",
                               compute_type="float16", language="ja", task="transcribe", local_files_only=True,
                               asr_options={"beam_size": 5}, vad_method="pyannote")
    if model.model.model.device != "cuda" or next(model.vad_model.vad_pipeline._segmentation.model.parameters()).device.type != "cuda":
        raise RuntimeError("GPU-only contract failed")
    timing = {"load_s": time.perf_counter() - mark}
    write(out / "options.json", dataclasses.asdict(model.options))
    shutil.copyfile(Path(whisperx.__file__).parent / "assets/mel_filters.npz", out / "mel_filters.npz")
    identity = {"versions": {p: importlib.metadata.version(p) for p in ("whisperx", "faster-whisper", "ctranslate2", "torch", "pyannote.audio")},
                "python": sys.version, "platform": platform.platform(), "asr_device": str(model.model.model.device),
                "compute_type": model.model.model.compute_type,
                "vad_device": str(next(model.vad_model.vad_pipeline._segmentation.model.parameters()).device),
                "vad_sha256": sha(Path(whisperx.__file__).parent / "assets/pytorch_model.bin"),
                "mel_sha256": sha(out / "mel_filters.npz"), "vad_params": model._vad_params}
    actual_vad = model.vad_model
    captured = Capture(model.model.model)
    model.model.model = captured
    preprocess = model.preprocess
    observed = []
    def save_features(item):
        result = preprocess(item)
        observed.append(result["inputs"].numpy())
        return result
    model.preprocess = save_features
    results = []
    for clip in clips:
        pcm = audio(Path(clip["audio"]))
        mark = time.perf_counter()
        scores = actual_vad({"waveform": actual_vad.preprocess_audio(pcm), "sample_rate": 16000})
        timing[clip["id"] + "_vad_s"] = time.perf_counter() - mark
        np.save(out / (clip["id"] + "-vad.npy"), scores.data)
        chunks = Pyannote.merge_chunks(scores, 30, onset=.5, offset=.363)
        write(out / (clip["id"] + "-chunks.json"), chunks)
        class FrozenVad:
            def __call__(self, ignored):
                return scores
        model.vad_model = FrozenVad()
        begin, call_begin = len(observed), len(captured.calls)
        mark = time.perf_counter()
        native = model.transcribe(pcm, batch_size=1, chunk_size=30, num_workers=0)
        timing[clip["id"] + "_asr_s"] = time.perf_counter() - mark
        for index, mel in enumerate(observed[begin:]):
            np.save(out / f'{clip["id"]}-mel-{index:02d}.npy', mel)
        results.append({"clip": clip, "scores_window": {"start": scores.sliding_window.start, "duration": scores.sliding_window.duration, "step": scores.sliding_window.step},
                        "native": native, "chunks": chunks, "calls": captured.calls[call_begin:]})
    write(out / "wx.json", {"identity": identity, "timing": timing, "results": results})
    print(json.dumps({"wx_chunks": sum(len(r["chunks"]) for r in results), "timing": timing}))


def fw(out: Path):
    handles = setup(out)
    import numpy as np
    import torch
    from faster_whisper import WhisperModel, BatchedInferencePipeline
    from adapter import features, generate
    prior = json.loads((out / "wx.json").read_text(encoding="utf-8"))
    options = json.loads((out / "options.json").read_text(encoding="utf-8"))
    with np.load(out / "mel_filters.npz") as filters:
        bank = torch.from_numpy(filters["mel_128"].copy())
    mark = time.perf_counter()
    model = WhisperModel(str(ROOT / ".local/models/faster-whisper-large-v3"), device="cuda", compute_type="float16", local_files_only=True, cpu_threads=4)
    if model.model.device != "cuda":
        raise RuntimeError("GPU-only contract failed")
    timings = {"load_s": time.perf_counter() - mark}
    results = []
    for saved in prior["results"]:
        clip = saved["clip"]
        pcm = audio(Path(clip["audio"]))
        records = []
        for index, chunk in enumerate(saved["chunks"]):
            cropped = pcm[int(chunk["start"] * 16000):int(chunk["end"] * 16000)]
            mark = time.perf_counter()
            mel = features(cropped, bank)
            wx_mel = np.load(out / f'{clip["id"]}-mel-{index:02d}.npy')
            direct = generate(model, mel, options)
            elapsed = time.perf_counter() - mark
            expected = saved["calls"][index]
            direct.update(start=round(chunk["start"], 3), end=round(chunk["end"], 3))
            native = saved["native"]["segments"][index]
            records.append({"index": index, "samples": len(cropped), "feature_equal": bool(np.array_equal(mel, wx_mel)),
                            "feature_max_abs_diff": float(np.max(np.abs(mel - wx_mel))),
                            "tokens_equal": direct["tokens"] == expected["results"][0]["tokens"],
                            "prompt_equal": [direct["prompt"]] == expected["prompts"],
                            "kwargs_equal": direct["generate_kwargs"] == expected["kwargs"],
                            "segment_equal": {k: direct[k] for k in native} == native,
                            "adapter": direct, "adapter_s": elapsed,
                            "wx_token_length": len(expected["results"][0]["tokens"])})
        # Unmodified FW APIs operate on identical frozen crop audio. No VAD rerun.
        standard = []
        mark = time.perf_counter()
        for chunk in saved["chunks"]:
            cropped = pcm[int(chunk["start"] * 16000):int(chunk["end"] * 16000)]
            segments, info = model.transcribe(cropped, language="ja", task="transcribe", beam_size=5,
                condition_on_previous_text=False, without_timestamps=True, word_timestamps=False,
                vad_filter=False, temperature=0.0)
            rows = [dataclasses.asdict(s) for s in segments]
            standard.append({"segments": rows, "text": "".join(s["text"] for s in rows),
                             "options": dataclasses.asdict(info.transcription_options)})
        timings[clip["id"] + "_standard_zero_s"] = time.perf_counter() - mark
        mark = time.perf_counter()
        pipeline = BatchedInferencePipeline(model)
        segments, info = pipeline.transcribe(pcm, language="ja", task="transcribe", beam_size=5, batch_size=1,
            without_timestamps=True, word_timestamps=False, vad_filter=False, temperature=0.0,
            clip_timestamps=[{"start": c["start"], "end": c["end"]} for c in saved["chunks"]])
        batch = [dataclasses.asdict(s) for s in segments]
        timings[clip["id"] + "_native_batch_s"] = time.perf_counter() - mark
        results.append({"clip_id": clip["id"], "chunks": records, "standard": standard, "batch": batch,
                        "batch_options": dataclasses.asdict(info.transcription_options),
                        "standard_text_equal_chunks": sum(a["text"] == b["adapter"]["text"] for a, b in zip(standard, records)),
                        "batch_full_text_equal": "".join(s["text"] for s in batch) == "".join(r["adapter"]["text"] for r in records)})
    imported = [name for name in sys.modules if name == "whisperx" or name.startswith("whisperx.")]
    if imported:
        raise RuntimeError("Independent adapter imported WhisperX")
    write(out / "fw.json", {"whisperx_imports": imported, "timing": timings, "results": results})
    summary = {"chunks": sum(len(r["chunks"]) for r in results), "equal": {name: sum(c[name] for r in results for c in r["chunks"]) for name in ("feature_equal", "tokens_equal", "prompt_equal", "kwargs_equal", "segment_equal")},
               "standard_equal_chunks": sum(r["standard_text_equal_chunks"] for r in results),
               "batch_equal_windows": sum(r["batch_full_text_equal"] for r in results), "timing": timings}
    write(out / "summary.json", summary)
    print(json.dumps(summary))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("wx", "fw", "all"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    permitted = (ROOT / ".local/framework-equivalence").resolve()
    if not out.is_relative_to(permitted) or out == permitted:
        parser.error("Output must be a new child directory within .local/framework-equivalence")
    if args.mode != "all":
        if (out / (args.mode + ".json")).exists():
            parser.error("Stage result already exists; use a new experimental identity")
        return wx(out, json.loads((out / "inputs.json").read_text(encoding="utf-8"))) if args.mode == "wx" else fw(out)
    out.mkdir(parents=True, exist_ok=False)
    corpus = ROOT / ".local/round2/corpus/manifest.json"
    clips = [c for c in json.loads(corpus.read_text(encoding="utf-8"))["clips"] if c["id"] in ("hf-ii-window-01", "hf-iii-window-01")]
    for clip in clips:
        if sha(Path(clip["audio"])) != clip["audio_sha256"]:
            raise RuntimeError("Frozen input hash mismatch")
    write(out / "inputs.json", clips)
    manifest = {"status": "running", "selection": "first chronological frozen 300s window of each primary film, no outcome selection",
                "source_sha256": {p.name: sha(p) for p in Path(__file__).parent.glob("*.py")},
                "corpus_sha256": sha(corpus), "python": sys.version, "model_sha256": sha(ROOT / ".local/models/faster-whisper-large-v3/model.bin"),
                "model_config": json.loads((ROOT / ".local/models/faster-whisper-large-v3/config.json").read_text()), "gpu_samples": []}
    shutil.copytree(Path(__file__).parent, out / "source", ignore=shutil.ignore_patterns("__pycache__"))
    lock = ROOT / ".local/gpu.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w") as stream:
        json.dump({"pid": os.getpid(), "run": str(out)}, stream)
    started = time.perf_counter()
    process = None
    try:
        for mode in ("wx", "fw"):
            with (out / (mode + "-stdout.log")).open("wb") as stdout, (out / (mode + "-stderr.log")).open("wb") as stderr:
                env = {**os.environ, "KOTOTOKI_EXPERIMENT_ROOT": str(ROOT)}
                process = subprocess.Popen([sys.executable, str(out / "source/run.py"), mode, "--output", str(out)], stdout=stdout, stderr=stderr, cwd=ROOT, env=env)
                while process.poll() is None:
                    smi = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.used,utilization.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True)
                    manifest["gpu_samples"].append({"mode": mode, "elapsed": time.perf_counter()-started, "csv": smi.stdout.strip(), "returncode": smi.returncode})
                    write(out / "manifest.json", manifest)
                    time.sleep(1)
                manifest[mode + "_returncode"] = process.returncode
                if process.returncode:
                    raise RuntimeError(f"{mode} failed; private stderr retained")
        manifest["status"] = "completed"
    except BaseException as exc:
        manifest["status"] = "failed"
        manifest["error"] = str(exc)
        raise
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        manifest["wall_s"] = time.perf_counter() - started
        manifest["input_unchanged"] = all(sha(Path(c["audio"])) == c["audio_sha256"] for c in clips)
        write(out / "manifest.json", manifest)
        lock.unlink()
    print((out / "summary.json").read_text())


if __name__ == "__main__":
    main()
