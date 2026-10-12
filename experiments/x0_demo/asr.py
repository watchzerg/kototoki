"""Native Qwen boundary promoted from frozen x0_flow/asr.py.

Generation defaults retain the measured historical path; integer windows and
progress persistence belong to the current reusable demo.
"""
from __future__ import annotations

import gc
import hashlib
import importlib.metadata
from pathlib import Path
import time

from experiments.qwen.run_qwen import ASR_ID, ASR_REVISION, ASR_SHA256, checkpoint_identity, check_gpu
from .chunks import validate_chunks


class QwenAsr:
    def __init__(self, model_path: Path):
        import torch
        from transformers import AutoModelForMultimodalLM, AutoProcessor

        if not torch.cuda.is_available():
            raise RuntimeError("Qwen ASR requires CUDA; CPU fallback is prohibited")
        self.model_path = Path(model_path).resolve()
        identity = checkpoint_identity(self.model_path, ASR_SHA256)
        self.processor = AutoProcessor.from_pretrained(self.model_path, local_files_only=True)
        self.model = AutoModelForMultimodalLM.from_pretrained(
            self.model_path, dtype=torch.bfloat16, attn_implementation="sdpa",
            device_map={"": "cuda:0"}, local_files_only=True).eval()
        torch.cuda.synchronize()
        distribution = importlib.metadata.distribution("transformers")
        implementation = {}
        for name in ("processing_qwen3_asr.py", "feature_extraction_qwen3_asr.py", "modeling_qwen3_asr.py"):
            path = Path(distribution.locate_file(f"transformers/models/qwen3_asr/{name}"))
            with path.open("rb") as stream:
                implementation[name] = hashlib.file_digest(stream, "sha256").hexdigest()
        self.metadata = {"model": ASR_ID, "revision": ASR_REVISION, "path": str(self.model_path),
                         "model_files_sha256": identity, "language": "ja", "dtype": "bfloat16",
                         "attention": "sdpa", "max_new_tokens": 4096, "do_sample": False,
                         "batch_size": 1, "independent_chunks": True, "previous_text_conditioning": False,
                         "padding_to_30s": False, "mel_source": "native Qwen processor",
                         "generation_config": self.model.generation_config.to_dict(),
                         "installed_implementation_sha256": implementation}

    def transcribe(self, audio, chunks: list[dict], progress=None, *, retain_all: bool = True) -> tuple[list[dict], list[dict]]:
        import torch

        validate_chunks(chunks, len(audio), retain_all=retain_all)
        segments, traces = [], []
        torch.cuda.reset_peak_memory_stats()
        for index, chunk in enumerate(chunks):
            data = audio[chunk["start_sample"]:chunk["end_sample"]]
            mark = time.perf_counter()
            inputs = self.processor.apply_transcription_request(
                audio=data, language="ja", processor_kwargs={"audio_kwargs": {"sampling_rate": 16000}}
            ).to("cuda:0", torch.bfloat16)
            evidence = check_gpu(self.model, inputs, torch)
            if inputs["input_ids"].ndim != 2 or inputs["input_ids"].shape[0] != 1:
                raise ValueError("Qwen processor must produce a single independent request")
            for name, tensor in inputs.items():
                if hasattr(tensor, "is_floating_point") and tensor.is_floating_point() and not torch.isfinite(tensor).all():
                    raise ValueError(f"Qwen processor produced non-finite input: {name}")
            evidence["native_input_shapes"] = {name: list(value.shape) for name, value in inputs.items()
                                               if hasattr(value, "shape")}
            torch.cuda.synchronize()
            preprocess = time.perf_counter() - mark
            mark = time.perf_counter()
            with torch.inference_mode():
                output = self.model.generate(**inputs, max_new_tokens=4096, do_sample=False)
            torch.cuda.synchronize()
            inference = time.perf_counter() - mark
            if output.device.type != "cuda":
                raise RuntimeError("Qwen output token IDs were not produced on CUDA")
            generated = output[:, inputs["input_ids"].shape[1]:]
            parsed = self.processor.decode(generated, return_format="parsed")[0]
            segments.append({"start": chunk["start"], "end": chunk["end"],
                             "start_sample": chunk["start_sample"], "end_sample": chunk["end_sample"],
                             "text": parsed["transcription"]})
            traces.append({"chunk_index": index, "start_sample": chunk["start_sample"],
                           "end_sample": chunk["end_sample"],
                           "pcm_float32_sha256": hashlib.sha256(data.tobytes()).hexdigest(),
                           "token_ids": generated[0].detach().cpu().tolist(),
                           "generated_tokens": generated.shape[1], "token_limit_reached": generated.shape[1] >= 4096,
                           "raw_asr": self.processor.decode(generated)[0], "detected_language": parsed["language"],
                           "asr_input_evidence": {**evidence, "output_device": str(output.device)},
                           "preprocess_s": preprocess, "inference_s": inference})
            if progress:
                progress(segments, traces, self.metadata)
            if generated.shape[1] >= 4096:
                raise ValueError("Qwen generation reached 4096-token cap; partial output retained")
            del inputs, output, generated
        self.metadata.update(peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                             peak_reserved_bytes=torch.cuda.max_memory_reserved())
        return segments, traces

    def close(self) -> None:
        import torch

        self.model = self.processor = None
        gc.collect()
        torch.cuda.empty_cache()
