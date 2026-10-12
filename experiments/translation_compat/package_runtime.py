"""Package a visibly identified patched core with unchanged CUDA runtime DLLs."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--patched-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    for path in args.base.iterdir():
        if path.is_file() and path.suffix in (".dll", ".exe"):
            shutil.copy2(path, args.output / path.name)
    original_hashes = {p.name: file_hash(p) for p in args.output.glob("*.dll")}
    shutil.copy2(args.core, args.output / "llama.dll")
    hashes = {p.name: file_hash(p) for p in args.output.glob("*.dll")}
    changed = sorted(name for name in hashes if hashes[name] != original_hashes[name])
    if changed != ["llama.dll"]:
        raise ValueError("Runtime packaging must change only llama.dll")
    patch = Path(__file__).with_name("hy-v3-router-bias.patch")
    identity = {
        "identity": "llama-b11429-hyv3-router-bias-v1",
        "status": "custom-runtime-awaiting-gpu-smoke",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "upstream_commit": "d81235049384534c167caea52b85a694f6103d14",
        "upstream_tag": "b11429",
        "source_url": "https://codeload.github.com/ggml-org/llama.cpp/zip/refs/tags/b11429",
        "source_archive_sha256": file_hash(args.source_archive),
        "compatibility_patch_sha256": file_hash(patch),
        "patched_hy_v3_source_sha256": file_hash(args.patched_source),
        "compiler": "MSVC 19.29.30159.0 / VS2019 BuildTools 14.29.30133",
        "cmake": "3.20.21032501-MSVC_2",
        "build_flags": {"generator": "Visual Studio 16 2019", "architecture": "x64", "configuration": "Release", "target": "llama", "BUILD_SHARED_LIBS": True, "GGML_CUDA": False, "GGML_BACKEND_DL": True, "GGML_NATIVE": False, "GGML_CPU_ALL_VARIANTS": False, "LLAMA_BUILD_TESTS": False, "LLAMA_BUILD_EXAMPLES": False, "LLAMA_BUILD_SERVER": False, "LLAMA_CURL": False},
        "cuda_backend": "unchanged official b11429 CUDA13.4 ggml-cuda.dll",
        "original_core_sha256": original_hashes["llama.dll"],
        "patched_core_sha256": hashes["llama.dll"],
        "changed_runtime_files": changed,
        "runtime_dll_sha256": hashes,
        "model_weights_modified": False,
        "model_file_renamed": False,
        "note_zh": "仅修改 HYV3 router 偏置 tensor 的兼容命名。编译关闭 CUDA，运行仍使用原 CUDA backend；实际 GPU 驻留与推理尚待验证。",
    }
    with (args.output / "identity.json").open("x", encoding="utf-8") as stream:
        json.dump(identity, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(args.output / "llama-server.exe")
    print(args.output / "identity.json")


if __name__ == "__main__":
    main()
