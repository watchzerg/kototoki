"""Offline cached-transcript Japanese CTC experiments; never acquire assets."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# Frozen helpers intentionally use sibling imports. No old sources are edited.
sys.path.insert(0, str(ROOT / "experiments/whisper"))
legacy = importlib.import_module("experiments.whisper.run")


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_cached(saved: dict, identity: dict, offset: float) -> list[dict]:
    segments = saved.get("original_segments")
    if (saved.get("status", "ok") != "ok" or not isinstance(segments, list)
            or not isinstance(saved.get("text"), str)
            or any(not isinstance(s, dict) or not isinstance(s.get("text"), str) for s in segments)
            or "".join(s["text"] for s in segments) != saved["text"]):
        raise ValueError("A complete successful cached ASR/CTC input with original_segments is required")
    if (saved.get("input", {}).get("pcm_sha256") != identity["pcm_sha256"]
            or saved.get("input", {}).get("file_sha256") != identity["file_sha256"]
            or saved.get("offset_s") != offset):
        raise ValueError("Cached input audio or source offset differs")
    for segment in segments:
        start, end = segment.get("start"), segment.get("end")
        if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                for v in (start, end)) or not 0 <= start <= end <= identity["duration_s"]):
            raise ValueError("Cached segment bounds must be finite and inside the input")
    return copy.deepcopy(segments)


def token_spans(text: str, tokenizer: Any, blank_id: int) -> list[dict]:
    """Map native tokenizer pieces back to exact original spans, with no char splitting."""
    output, cursor = [], 0
    for token in tokenizer.tokenize(text):
        label = token.replace(tokenizer.word_delimiter_token, " ")
        # Added-token lstrip/rstrip may omit source whitespace. It remains untimed.
        pos = text.find(label, cursor)
        if not label or pos < 0:
            raise ValueError("Native tokenizer piece cannot be mapped exactly to original text")
        token_id = tokenizer.convert_tokens_to_ids(token)
        known = token_id not in {blank_id, tokenizer.unk_token_id} and token not in tokenizer.all_special_tokens
        output.append({"char_start": pos, "char_end": pos + len(label), "text": label,
                       "token": token, "token_id": token_id, "lexical_interval_accepted": known})
        cursor = pos + len(label)
    return output


def complete_units(text: str, units: list[dict]) -> list[dict]:
    covered = [False] * len(text)
    for unit in units:
        for i in range(unit["char_start"], unit["char_end"]):
            covered[i] = True
    units = list(units)
    for i, is_covered in enumerate(covered):
        if not is_covered:
            units.append({"char_start": i, "char_end": i + 1, "start": None, "end": None,
                          "granularity": "character", "time_source": "fallback", "status": "text_only"})
    return sorted(units, key=lambda unit: unit["char_start"])


def verify_mms_head(model: Any, path: str) -> dict:
    """Require the final classifier to exactly equal the provisioned jpn adapter."""
    import torch
    from safetensors import safe_open
    adapter_path = Path(path) / "adapter.jpn.safetensors"
    if not adapter_path.is_file():
        raise FileNotFoundError(f"Provisioned Japanese adapter required: {adapter_path}")
    evidence = {"path": str(adapter_path.resolve()), "sha256": sha256(adapter_path)}
    with safe_open(str(adapter_path), framework="pt", device="cpu") as checkpoint:
        for name in ("weight", "bias"):
            actual = getattr(model.lm_head, name).detach().cpu()
            expected = checkpoint.get_tensor(f"lm_head.{name}").to(dtype=actual.dtype)
            if not torch.equal(actual, expected):
                raise ValueError(f"Final MMS jpn lm_head.{name} differs from local adapter")
            evidence[f"head_{name}_exact_match"] = True
    return evidence


def load_mms(path: str, device: str) -> tuple[Any, dict]:
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
    processor = Wav2Vec2Processor.from_pretrained(path, target_lang="jpn", local_files_only=True)
    processor.tokenizer.set_target_lang("jpn")
    # Selecting jpn during base loading lets tie_weights resize the classifier
    # before the base 154-way head is loaded. Load base first, then replace the
    # complete adapter/head using the public language-switching API.
    model = Wav2Vec2ForCTC.from_pretrained(path, target_lang=None, local_files_only=True)
    model.load_adapter("jpn", local_files_only=True)
    model = model.float()
    adapter_verification = verify_mms_head(model, path)
    model = model.to(device).eval()
    dictionary = {char.lower(): code for char, code in processor.tokenizer.get_vocab().items()}
    if (model.target_lang != "jpn" or processor.tokenizer.target_lang != "jpn"
            or model.config.vocab_size != len(processor.tokenizer.get_vocab())
            or model.lm_head.out_features != model.config.vocab_size):
        raise ValueError("MMS jpn adapter/tokenizer language or output vocabulary mismatch")
    if dictionary.get("<pad>") != model.config.pad_token_id:
        raise ValueError("MMS jpn tokenizer blank differs from model blank")
    return model, {"language": "ja", "dictionary": dictionary, "type": "huggingface",
                   "mms_adapter_verification": adapter_verification}


@contextmanager
def observed_loader(whisperx: Any, candidate: str, observation: dict) -> Iterator[None]:
    original = whisperx.load_align_model
    handles = []

    def wrapped(language_code: str, device: str, **kwargs: Any) -> tuple[Any, dict]:
        model, metadata = (load_mms(kwargs["model_name"], device) if candidate == "mms"
                           else original(language_code, device, **kwargs))
        if any(p.device.type != "cuda" or p.dtype.__str__() != "torch.float32" for p in model.parameters()):
            raise RuntimeError("CTC parameters must all be CUDA FP32; CPU fallback prohibited")
        observation.update(parameter_count=sum(p.numel() for p in model.parameters()),
                           blank_id=model.config.pad_token_id, model=str(next(model.parameters()).device),
                           dtype=str(next(model.parameters()).dtype), forward=[])
        if candidate == "mms":
            observation.update(adapter_target_lang=model.target_lang, vocabulary_size=model.config.vocab_size,
                               output_head_size=model.lm_head.out_features,
                               adapter_verification=metadata["mms_adapter_verification"])

        def hook(module: Any, inputs: Any, output: Any) -> None:
            logits = output.logits
            if inputs[0].device.type != "cuda" or logits.device.type != "cuda":
                raise RuntimeError("CTC forward must remain on CUDA")
            observation["forward"].append({"input_device": str(inputs[0].device),
                "input_dtype": str(inputs[0].dtype), "output_device": str(logits.device),
                "output_dtype": str(logits.dtype), "output_shape": list(logits.shape)})
        handles.append(model.register_forward_hook(hook))
        return model, metadata

    whisperx.load_align_model = wrapped
    try:
        yield
    finally:
        whisperx.load_align_model = original
        for handle in handles:
            handle.remove()


def native_tokens(args: argparse.Namespace, audio: Any, identity: dict, original: list[dict]) -> dict:
    """Native pieces and config blank, preserving token or reading-word granularity."""
    import numpy as np
    import torch
    from torchaudio.functional import forced_align, merge_tokens
    from transformers import Wav2Vec2Processor, Wav2Vec2ForCTC
    device = f"cuda:{args.device_index}"
    mark = time.perf_counter()
    processor = Wav2Vec2Processor.from_pretrained(args.align_model, local_files_only=True)
    model = Wav2Vec2ForCTC.from_pretrained(args.align_model, local_files_only=True).float().to(device).eval()
    if any(p.device.type != "cuda" or p.dtype != torch.float32 for p in model.parameters()):
        raise RuntimeError("CTC parameters must all be CUDA FP32")
    blank = model.config.pad_token_id
    if not isinstance(blank, int) or not 0 <= blank < model.config.vocab_size:
        raise ValueError("Native CTC blank must be a valid model output vocabulary ID")
    extractor = processor.feature_extractor
    if (not extractor.do_normalize or extractor.sampling_rate != 16000
            or extractor.padding_side != "right" or extractor.padding_value != 0):
        raise ValueError("Native token arm requires normalized mono 16 kHz with right-zero padding")
    torch.cuda.synchronize()
    stages = {"align_load_s": time.perf_counter() - mark}
    records, normalization, units, cues, forward = [], [], [], [], []
    base = 0
    if args.candidate == "hiragana":
        sys.path.insert(0, str(args.reading_packages.resolve()))
        from experiments.japanese_ctc.phonetic import convert_to_hiragana, map_reading_spans
    mark = time.perf_counter()
    for index, segment in enumerate(original):
        start, end = max(0, segment["start"] - args.padding), min(identity["duration_s"], segment["end"] + args.padding)
        text = segment["text"]
        record = {"segment_index": index, "failure": None, "blank_id": blank, "tokens": []}
        records.append(record)
        segment_units = []
        try:
            reading = convert_to_hiragana(text) if args.candidate == "hiragana" else None
            target_text = reading.target_text if reading is not None else text
            targets = token_spans(target_text, processor.tokenizer, blank)
            if targets:
                f1, f2 = int(start * 16000), int(end * 16000)
                waveform = audio[f1:f2]
                if not len(waveform):
                    raise ValueError("Empty alignment waveform")
                source_samples = len(waveform)
                zero_samples = round(args.zero_pad_seconds * 16000)
                zero_seconds = zero_samples / 16000
                waveform = np.pad(waveform, (zero_samples, zero_samples))
                processed = extractor(waveform, sampling_rate=16000, padding="max_length",
                    max_length=max(400, len(waveform)), return_attention_mask=True, return_tensors="np")
                values = processed["input_values"][0].astype(np.float32)
                tensor = torch.from_numpy(values.copy()).unsqueeze(0).to(device)
                normalization.append({"segment_index": index, "source_sample_start": f1,
                    "source_sample_end": f2, "source_samples": source_samples,
                    "valid_samples": len(waveform), "padded_samples": len(values), "zero_padding_each_side_samples": zero_samples,
                    "normalized_float32_sha256": hashlib.sha256(values.astype("<f4").tobytes()).hexdigest(),
                    "actual_input_device": str(tensor.device), "actual_input_dtype": str(tensor.dtype)})
                model_kwargs = {}
                if extractor.return_attention_mask:
                    model_kwargs["attention_mask"] = torch.from_numpy(processed["attention_mask"].copy()).to(device)
                with torch.inference_mode():
                    logits = model(tensor, **model_kwargs).logits
                    emission = logits[0].log_softmax(dim=-1)
                if logits.device.type != "cuda" or logits.dtype != torch.float32:
                    raise RuntimeError("CTC forward logits must remain CUDA FP32")
                forward.append(str(tensor.device))
                record.update(frame_count=len(emission), emission_shape=list(emission.shape),
                    emission_sha256=hashlib.sha256(emission.detach().cpu().numpy().tobytes()).hexdigest(),
                    model_output_device=str(logits.device), model_output_dtype=str(logits.dtype))
                if any(not target["lexical_interval_accepted"] for target in targets):
                    mask = torch.ones(emission.shape[1], dtype=torch.bool, device=device)
                    mask[blank] = False
                    emission = torch.cat([emission, emission[:, mask].max(dim=1).values.unsqueeze(1)], dim=1)
                ids = [target["token_id"] if target["lexical_interval_accepted"] else emission.shape[1] - 1 for target in targets]
                labels, scores = forced_align(emission.unsqueeze(0), torch.tensor([ids], device=device), blank=blank)
                if labels.device.type != "cuda":
                    raise RuntimeError("CTC decoder output left CUDA")
                record.update(decoder_input_device=str(emission.device), decoder_output_device=str(labels.device),
                    path_sha256=hashlib.sha256(labels.detach().cpu().numpy().tobytes()).hexdigest())
                spans = merge_tokens(labels[0], scores[0].exp(), blank=blank)
                if len(spans) != len(ids) or any(span.token != expected for span, expected in zip(spans, ids)):
                    raise ValueError("Collapsed CTC path differs from token targets")
                ratio = (end - start + 2 * zero_seconds) / len(emission)
                reading_spans = []
                for target, span in zip(targets, spans):
                    begin = start - zero_seconds + span.start * ratio
                    finish = start - zero_seconds + span.end * ratio
                    valid = target["lexical_interval_accepted"] and begin < end and finish > start
                    begin, finish = max(start, begin), min(end, finish)
                    valid = valid and round(begin, 3) < round(finish, 3)
                    record["tokens"].append({**target, "start_frame": span.start, "end_frame": span.end,
                        "token_probability": span.score, "source_interval_accepted": valid,
                        "evidence_kind": "vocabulary_token" if target["lexical_interval_accepted"] else "wildcard"})
                    reading_spans.append({**target, "start": round(begin, 3) if valid else None,
                        "end": round(finish, 3) if valid else None, "score": span.score,
                        "lexical_interval_accepted": valid})
                    segment_units.append({"char_start": base + target["char_start"], "char_end": base + target["char_end"],
                        "start": round(begin, 3) + args.offset if valid else None,
                        "end": round(finish, 3) + args.offset if valid else None,
                        "granularity": "character" if target["char_end"] - target["char_start"] == 1 else "word",
                        "time_source": "api", "status": "ok" if valid else "text_only",
                        "time_semantics": "ctc_nonblank_token_span", "experimental_not_acoustic_duration": True})
                if reading is not None:
                    mapped = map_reading_spans(reading, reading_spans)
                    record["reading_target_sha256"] = hashlib.sha256(reading.target_text.encode()).hexdigest()
                    record["reading_mapping"] = mapped["reading_mapping"]
                    segment_units = [{"char_start": base + row["original_start"], "char_end": base + row["original_end"],
                        "start": row["start"] + args.offset if row["status"] == "ok" else None,
                        "end": row["end"] + args.offset if row["status"] == "ok" else None,
                        "granularity": row["granularity"], "time_source": "api",
                        "status": "ok" if row["status"] == "ok" else "text_only",
                        "time_semantics": "phonetic_ctc_nonblank_span"} for row in mapped["reading_mapping"]]
        except (RuntimeError, ValueError) as error:
            record["failure"] = f"{type(error).__name__}: {error}"
            segment_units = []
        units.extend(segment_units)
        valid_units = [unit for unit in segment_units if unit["status"] == "ok"]
        if valid_units:
            cues.append({"text": text, "start": min(u["start"] for u in valid_units),
                         "end": max(u["end"] for u in valid_units)})
        base += len(text)
    torch.cuda.synchronize()
    stages["align_s"] = time.perf_counter() - mark
    text = "".join(segment["text"] for segment in original)
    return {"schema_version": 1, "text": text, "units": complete_units(text, units), "cues": cues,
        "route": args.route, "input": identity, "offset_s": args.offset, "source_start_seconds": args.offset,
        "duration_seconds": identity["duration_s"], "original_segments": original,
        "effective_parameters": {"asr_reused": True, "ctc_normalize": True, "ctc_forced_align": True,
            "padding": args.padding, "zero_pad_seconds": args.zero_pad_seconds,
            "model_attention_mask": bool(extractor.return_attention_mask)},
        "experimental_alignment": {"time_semantics": "ctc_nonblank_token_span", "records": records,
            "tokenization": "native tokenizer pieces with exact original spans", "blank_source": "model.config.pad_token_id",
            "multi_character_policy": "one word-granularity interval; no fabricated character timestamps"},
        "experimental_preprocessing": {"records": normalization, "feature_extractor_config": extractor.to_dict()},
        "devices": {"aligner": {"model": str(next(model.parameters()).device), "dtype": str(next(model.parameters()).dtype),
            "forward_observation": forward, "parameter_count": sum(p.numel() for p in model.parameters())}},
        "stages": stages, "native": {"reused_asr_file": str(args.asr_result.resolve())}}


def execute(args: argparse.Namespace) -> dict:
    started = time.perf_counter()
    if (not math.isfinite(args.offset) or args.offset < 0 or not math.isfinite(args.padding) or args.padding < 0
            or not math.isfinite(args.zero_pad_seconds) or args.zero_pad_seconds < 0):
        raise ValueError("Offset and search padding must be finite and nonnegative")
    if args.device_index < 0:
        raise ValueError("Device index must be nonnegative")
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY"):
        os.environ[name] = "1"
    os.environ["HF_HOME"] = str(args.cache.resolve())
    os.environ["TORCH_HOME"] = str(args.cache.resolve() / "torch")
    os.environ["NLTK_DATA"] = str(args.nltk_data.resolve())
    source_hash = sha256(args.asr_result)
    audio, identity = legacy.read_audio(args.audio)
    saved = json.loads(args.asr_result.read_text(encoding="utf-8"))
    original = validate_cached(saved, identity, args.offset)
    bridge = None
    if args.word_envelope:
        from experiments.components.word_envelope_ctc import envelope, mapping_hash
        original, mapping = envelope(original, identity["duration_s"])
        bridge = {**saved, "original_segments": original}
        bridge_path = args.output.parent / (args.output.stem + "-input.json")
        if bridge_path.exists():
            raise FileExistsError(bridge_path)
        with bridge_path.open("x", encoding="utf-8") as stream:
            json.dump(bridge, stream, ensure_ascii=False, indent=2, allow_nan=False)
        window_repair = {"method": "parent-and-own-native-word-envelope-v1", "mapping": mapping,
                         "mapping_sha256": mapping_hash(mapping), "input_path": str(bridge_path), "input_sha256": sha256(bridge_path)}
    mode = args.tokenization if args.tokenization != "auto" else ("native-token" if args.candidate in {"reazon", "hiragana"} else "whisperx-char")
    import torch
    if not torch.cuda.is_available() or args.device_index >= torch.cuda.device_count():
        raise RuntimeError("Requested CUDA device unavailable; CPU fallback prohibited")
    if importlib.metadata.version("torchaudio").split("+")[0] != "2.8.0":
        raise ValueError("This experiment requires frozen TorchAudio 2.8.0 forced_align")
    torch.cuda.set_device(args.device_index)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats(args.device_index)
    if mode == "native-token":
        if args.candidate not in {"reazon", "hiragana"}:
            raise ValueError("Native-token arm is bounded to Reazon and hiragana checkpoints")
        result = native_tokens(args, audio, identity, original)
    else:
        if args.zero_pad_seconds:
            raise ValueError("Physical zero padding applies only to the native-token arm")
        import whisperx
        old = legacy.parser().parse_args(["--route", "W1", "--audio", str(args.audio), "--output", str(args.output),
            "--asr-result", str(bridge_path if bridge is not None else args.asr_result), "--align-model", str(args.align_model),
            "--offset", str(args.offset), "--device-index", str(args.device_index), "--padding", str(args.padding),
            "--ctc-normalize", "--ctc-forced-align", "--cache", str(args.cache), "--nltk-data", str(args.nltk_data)])
        old.dll_dir = [str(path) for path in args.dll_dir]
        observation: dict = {}
        with observed_loader(whisperx, args.candidate, observation):
            result = legacy.execute(old)
        result["model_forward_evidence"] = observation
        result["route"] = args.route
    torch.cuda.synchronize()
    failures = [{"segment_index": r["segment_index"], "failure": r["failure"]}
                for r in result["experimental_alignment"]["records"] if r.get("failure")]
    result.update(status="ok", candidate=args.candidate, tokenization_mode=mode,
        cached_inference=True, new_asr_inference=False, new_alignment_inference=bool(result["devices"]["aligner"]["forward_observation"]),
        cache_classification="cached_asr_component_comparison", original_asr_segments=saved["original_segments"],
        source_asr={"path": str(args.asr_result.resolve()), "sha256": source_hash},
        alignment_summary={"segments": len(original), "decoder_records": len(result["experimental_alignment"]["records"]),
            "segment_failures": failures, "timed_units": sum(u["status"] == "ok" for u in result["units"]),
            "untimed_characters": sum(u["char_end"] - u["char_start"] for u in result["units"] if u["status"] != "ok")},
        resource_measurement={"device": torch.cuda.get_device_name(args.device_index),
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(args.device_index),
            "peak_reserved_bytes": torch.cuda.max_memory_reserved(args.device_index),
            "wall_scope": "cached alignment only, includes validation and model load; excludes original ASR"},
        implementation={"path": str(Path(__file__).resolve()), "sha256": sha256(Path(__file__))},
        source_sha256={str(ROOT / f"experiments/whisper/{name}"): sha256(ROOT / f"experiments/whisper/{name}")
            for name in ("run.py", "ctc_audio.py", "ctc_forced.py", "ctc_transition.py")},
        model_asset_sha256={path.name: sha256(path) for path in args.align_model.iterdir()
            if path.is_file() and not path.name.endswith(".partial")}, offline_requested=True)
    result.setdefault("model_identity", {"aligner": legacy.model_identity(str(args.align_model.resolve()))})
    result.setdefault("environment", {"python": sys.version,
        "packages": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}})
    if mode == "native-token":
        import inspect
        from torchaudio.functional import forced_align
        from transformers import Wav2Vec2FeatureExtractor
        result["experimental_alignment"]["decoder_source_sha256"] = sha256(Path(inspect.getfile(forced_align)))
        result["experimental_preprocessing"]["feature_extractor_source_sha256"] = sha256(Path(inspect.getfile(Wav2Vec2FeatureExtractor)))
    if bridge is not None:
        result["window_repair"] = window_repair
    if sha256(args.asr_result) != source_hash or sha256(args.audio) != identity["file_sha256"]:
        raise ValueError("Source ASR or audio changed during alignment")
    result["stages"]["cached_alignment_total_s"] = time.perf_counter() - started
    return legacy.plain(result)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--candidate", choices=("jonatas", "reazon", "mms", "hiragana"), required=True)
    value.add_argument("--route", choices=("W0", "W1", "X0"), required=True)
    for key in ("audio", "asr-result", "align-model", "output"):
        value.add_argument("--" + key, type=Path, required=True)
    value.add_argument("--offset", type=float, default=0)
    value.add_argument("--padding", type=float, default=0)
    value.add_argument("--zero-pad-seconds", type=float, default=0)
    value.add_argument("--word-envelope", action="store_true")
    value.add_argument("--tokenization", choices=("auto", "whisperx-char", "native-token"), default="auto")
    value.add_argument("--device-index", type=int, default=0)
    value.add_argument("--cache", type=Path, default=ROOT / ".local/cache/whisper-runtime")
    value.add_argument("--nltk-data", type=Path, default=ROOT / ".local/cache/whisper-nltk")
    value.add_argument("--dll-dir", type=Path, action="append", default=[])
    value.add_argument("--reading-packages", type=Path, default=ROOT / ".local/japanese-ctc/reading-packages")
    return value


def main() -> int:
    args = parser().parse_args()
    if not args.output.resolve().is_relative_to(ROOT / ".local") or args.output.exists():
        print("Output must be a fresh file under project .local", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = execute(args)
        code = 0
    except Exception as error:
        result = {"status": "failed", "route": args.route, "candidate": args.candidate,
                  "error_type": type(error).__name__, "error": str(error)}
        # Retain every cached character even when loading or native integration fails.
        try:
            source = json.loads(args.asr_result.read_text(encoding="utf-8"))
            result.update(text=source["text"], units=complete_units(source["text"], []), cues=[],
                          original_segments=source["original_segments"])
        except (OSError, ValueError, KeyError):
            pass
        code = 1
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    with args.output.with_suffix(".sha256").open("x", encoding="ascii") as stream:
        stream.write(sha256(args.output) + "\n")
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve()),
                      "alignment_summary": result.get("alignment_summary")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
