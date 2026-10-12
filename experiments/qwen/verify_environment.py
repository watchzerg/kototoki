"""Import and native processor checks without GPU inference or model weights."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess


def sha256(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asr-model", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HOME"] = str(Path(__file__).resolve().parents[2] / ".local/cache/qwen-hf")
    import nagisa
    import numpy as np
    import torch
    from transformers import AutoModelForMultimodalLM, AutoModelForTokenClassification, AutoProcessor
    processor = AutoProcessor.from_pretrained(args.asr_model, local_files_only=True)
    inputs = processor.apply_transcription_request(audio=np.zeros(16000, dtype=np.float32),
        language="ja", processor_kwargs={"audio_kwargs": {"sampling_rate": 16000}})
    synthetic = "今日は、晴れ。"
    words = processor.split_words_for_alignment(synthetic, "Japanese")
    tokens = torch.tensor([processor.tokenizer.encode("こんにちは", add_special_tokens=False)])
    decoded = processor.decode(tokens, return_format="transcription_only")
    distribution = importlib.metadata.distribution("transformers")
    files = {name: sha256(Path(distribution.locate_file(f"transformers/models/qwen3_asr/{name}")))
             for name in ["processing_qwen3_asr.py", "feature_extraction_qwen3_asr.py", "modeling_qwen3_asr.py"]}
    result = {"status": "cpu_import_and_processor_checks_passed", "gpu_inference_tested": False,
              "python": platform.python_version(), "platform": platform.platform(),
              "torch_cuda_build": torch.version.cuda, "torch_version": torch.__version__,
              "packages": {dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions()},
              "uv": subprocess.check_output(["uv", "--version"], text=True).strip(),
              "requirements_lock_sha256": sha256(Path(__file__).with_name("requirements.lock")),
              "adapter_sha256": sha256(Path(__file__).with_name("run_qwen.py")),
              "installed_transformers_source_sha256": files,
              "processor_input_shapes": {name: list(value.shape) for name, value in inputs.items()
                                         if isinstance(value, torch.Tensor)},
              "japanese_synthetic_words": words, "decode_batch_result": decoded,
              "processor_config": processor.to_dict(),
              "available_native_classes": [AutoModelForMultimodalLM.__name__, AutoModelForTokenClassification.__name__]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "python": result["python"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
