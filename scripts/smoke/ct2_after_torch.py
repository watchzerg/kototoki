"""smoke `ct2_after_torch`：同一进程先 `import torch` 并初始化 CUDA，再导入 ctranslate2 / faster_whisper，
验证 faster-whisper large-v3 在没有私有 DLL 目录的情况下可在 RTX 5080 上解码。

结构：父进程依次启动三个 `--child <tag>` 子进程（同一解释器、同一环境，tag 决定是否附加变量）：
- `cold`：第一次启动；
- `warm`：第二次启动，记录模型加载与解码耗时；
- `nojit`：附加 `CUDA_DISABLE_PTX_JIT=1`。解码成功说明 CT2 自带 sm_120 原生 kernel；
  以 "no kernel image" 一类错误失败则记录为依赖 PTX JIT（这是发现，不是失败）。
通过条件：`cold` 与 `warm` 均解码成功，PATH 与已加载模块均不含 `whisper-runtime-provisional`，
且已加载的 cudnn / cublas / cudart DLL 全部位于 torch 包的 `lib` 目录下。
结果只含版本、计数、哈希、布尔与耗时；不输出转写文本，也不保存解码文本。
"""

from __future__ import annotations

import ctypes
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import wave
from ctypes import wintypes
from pathlib import Path
from typing import Any

import smokelib

NAME = "ct2_after_torch"
CHILD_PREFIX = "CT2_CHILD "
PRIVATE_DLL_DIR = "whisper-runtime-provisional"
DLL_PREFIXES = ("cudnn", "cublas", "cudart")
FROZEN_RUN = smokelib.REPO / ".local/w0-demo/pyannote-gpu-v1-w0-pyannote-current-hf-ii-window-01/result.json"
AUDIO = smokelib.REPO / ".local/round2/corpus/audio/hf-ii-window-01.wav"
MODEL_PATH = smokelib.REPO / ".local/models/faster-whisper-large-v3"
MEL_PATH = smokelib.REPO / ".local/models/w0-assets/mel_filters.npz"
MEL_SHA256 = "7450ae70723a5ef9d341e3cee628c7cb0177f36ce42c44b7ed2bf3325f0f6d4c"  # 与 WhisperAsr._load 的固定值一致
WINDOW_INDEX = 0
CHILD_TIMEOUT_S = 1800
NO_KERNEL_PATTERN = re.compile(
    r"no kernel image|invalid device function|NoKernelImage|unsupported (gpu )?architecture|"
    r"PTX .*(unsupported|not supported)", re.IGNORECASE)
# 子进程序列：(tag, 额外环境变量)
CHILDREN = (("cold", {}), ("warm", {}), ("nojit", {"CUDA_DISABLE_PTX_JIT": "1"}))


def norm(path: str | Path) -> str:
    return os.path.normcase(os.path.realpath(str(path)))


def dll_file_version(path: str) -> str | None:
    """用 version.dll 读取 DLL 的文件版本；失败返回 None。"""
    try:
        version = ctypes.WinDLL("version", use_last_error=True)
        size = version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None
        buffer = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(path, 0, size, buffer):
            return None
        pointer, length = ctypes.c_void_p(), wintypes.UINT()
        if not version.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
            return None
        info = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32 * 13)).contents  # VS_FIXEDFILEINFO
        high, low = info[4], info[5]
        return f"{high >> 16}.{high & 0xFFFF}.{low >> 16}.{low & 0xFFFF}"
    except Exception:  # noqa: BLE001 - 版本信息只是参考
        return None


def read_pcm(path: Path) -> tuple[Any, str]:
    """与 experiments/w0_demo/run.py 的 read_audio 一致：pcm_sha256 是原始 PCM16 字节的 sha256。"""
    import numpy as np

    with wave.open(str(path), "rb") as source:
        if (source.getnchannels(), source.getframerate(), source.getsampwidth(), source.getcomptype()) != (1, 16000, 2, "NONE"):
            raise ValueError("Input must be mono 16000 Hz PCM16 WAV")
        pcm = source.readframes(source.getnframes())
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0, hashlib.sha256(pcm).hexdigest()


# ---------------------------------------------------------------- 子进程

def child_main(tag: str, out: Path) -> int:
    """单个子进程：torch 在前，ctranslate2 / faster_whisper 在后；结果以 CT2_CHILD 行输出。"""
    sys.path.insert(0, str(smokelib.REPO))  # 为了 import experiments.w0_demo.asr（导入无副作用，仅 stdlib）
    result: dict[str, Any] = {"tag": tag, "ok": False, "stage": "start", "failures": [],
                              "ptx_jit_disabled": os.environ.get("CUDA_DISABLE_PTX_JIT") == "1"}
    failures: list[str] = result["failures"]
    started = time.perf_counter()
    try:
        path_entries = [entry for entry in os.environ.get("PATH", "").split(os.pathsep) if PRIVATE_DLL_DIR in entry.lower()]
        result["private_dll_dir_in_path"] = bool(path_entries)
        if path_entries:
            failures.append("PATH contains whisper-runtime-provisional")

        result["stage"] = "import_torch"
        import torch

        torch.zeros(1, device="cuda").add_(1).item()  # 初始化 CUDA，让 cudnn / cublas 的加载先于 CT2
        result["torch"] = {"version": torch.__version__, "cuda": torch.version.cuda,
                           "cudnn_version": torch.backends.cudnn.version(),
                           "device": torch.cuda.get_device_name(0),
                           "capability": list(torch.cuda.get_device_capability(0)),
                           "arch_list": torch.cuda.get_arch_list()}
        modules_after_torch = smokelib.modules_matching(DLL_PREFIXES)

        result["stage"] = "import_ct2"
        import ctranslate2
        import faster_whisper
        from faster_whisper import WhisperModel

        result["ct2"] = {"version": ctranslate2.__version__, "faster_whisper": faster_whisper.__version__,
                         "cuda_device_count": ctranslate2.get_cuda_device_count(),
                         "supported_compute_types_cuda": sorted(ctranslate2.get_supported_compute_types("cuda"))}
        from experiments.w0_demo.asr import features, generate

        result["stage"] = "prepare_input"
        import numpy as np

        frozen = json.loads(FROZEN_RUN.read_text(encoding="utf-8"))
        trace = frozen["asr_traces"][WINDOW_INDEX]
        options = frozen["effective_parameters"]["asr"]["options"]
        audio, pcm_sha = read_pcm(AUDIO)
        result["pcm_sha256_matches_frozen_input"] = pcm_sha == frozen["input"]["pcm_sha256"]
        if not result["pcm_sha256_matches_frozen_input"]:
            failures.append("audio pcm_sha256 differs from the frozen run input")
            raise RuntimeError("input identity mismatch")
        mel_sha = hashlib.sha256(MEL_PATH.read_bytes()).hexdigest()
        if mel_sha != MEL_SHA256:
            failures.append("mel_filters.npz sha256 differs from the pinned W0 filterbank")
            raise RuntimeError("mel asset mismatch")
        with np.load(MEL_PATH, allow_pickle=False) as archive:
            filters = torch.from_numpy(archive["mel_128"].copy())
        window = audio[trace["start_sample"]:trace["end_sample"]]
        mel = features(window, filters)
        feature_sha = hashlib.sha256(mel.tobytes()).hexdigest()
        result["feature"] = {"window_samples": int(len(window)), "mel_shape": list(mel.shape),
                             "feature_sha256": feature_sha,
                             "feature_sha256_equal_frozen": feature_sha == trace["feature_sha256"]}

        result["stage"] = "load_model"
        started_load = time.perf_counter()
        model = WhisperModel(str(MODEL_PATH), device="cuda", device_index=0, compute_type="float16",
                             local_files_only=True, cpu_threads=4)
        if model.model.device != "cuda" or model.model.compute_type != "float16":
            failures.append("model is not running CUDA float16")
        result["model_load_s"] = round(time.perf_counter() - started_load, 3)

        result["stage"] = "decode"
        started_decode = time.perf_counter()
        decoded = generate(model, mel, options)
        result["decode_s"] = round(time.perf_counter() - started_decode, 3)
        tokens = decoded.pop("tokens")
        decoded.pop("text", None)  # 不保留任何转写文本
        expected = trace["tokens"]
        first_diff = next((i for i, (a, b) in enumerate(zip(tokens, expected)) if a != b), None)
        if first_diff is None and len(tokens) != len(expected):
            first_diff = min(len(tokens), len(expected))
        result["decode"] = {"token_count": len(tokens), "frozen_token_count": len(expected),
                            "tokens_equal_frozen": tokens == expected, "first_differing_index": first_diff,
                            "tokens_sha256": hashlib.sha256(json.dumps(tokens).encode()).hexdigest(),
                            "prompt_equal_frozen": decoded["prompt"] == trace["prompt"],
                            "avg_logprob": decoded["avg_logprob"]}
        if not tokens:
            failures.append("decode produced no tokens")

        result["stage"] = "inspect_modules"
        torch_lib = norm(Path(torch.__file__).parent / "lib")
        loaded = smokelib.modules_matching(DLL_PREFIXES)
        outside = [path for path in loaded if not norm(path).startswith(torch_lib + os.sep)]
        private = [path for path in smokelib.loaded_modules() if PRIVATE_DLL_DIR in path.lower()]
        result["dlls"] = {
            "torch_lib_dir": str(Path(torch.__file__).parent / "lib"),
            "loaded": [{"name": Path(path).name, "path": path, "file_version": dll_file_version(path)} for path in loaded],
            "loaded_after_torch_only": [Path(path).name for path in modules_after_torch],
            "new_after_ct2": sorted(set(Path(p).name.lower() for p in loaded) - set(Path(p).name.lower() for p in modules_after_torch)),
            "outside_torch_lib": outside,
            "all_under_torch_lib": bool(loaded) and not outside,
            "private_dll_dir_modules": private,
        }
        if not loaded:
            failures.append("no cudnn/cublas/cudart module loaded")
        if outside:
            failures.append(f"{len(outside)} cuda dll(s) loaded from outside the torch lib directory")
        if private:
            failures.append("a loaded module comes from whisper-runtime-provisional")
        result["stage"] = "done"
        result["ok"] = not failures
    except Exception as error:  # noqa: BLE001 - 记录阶段与错误，父进程负责分类
        failures.append(f"{type(error).__name__} at stage {result['stage']}: {error}")
        result["error"] = {"type": type(error).__name__, "message": str(error)[:500], "stage": result["stage"]}
    result["child_elapsed_s"] = round(time.perf_counter() - started, 3)
    (out / f"{NAME}.child-{tag}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(CHILD_PREFIX + json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["ok"] else 1


# ---------------------------------------------------------------- 父进程

def run_child(tag: str, extra_env: dict[str, str], out: Path) -> dict[str, Any]:
    env = dict(os.environ)
    env.update(extra_env)
    command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--child", tag, "--out", str(out)]
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, cwd=smokelib.REPO, env=env, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=CHILD_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"tag": tag, "ok": False, "failures": [f"child timed out after {CHILD_TIMEOUT_S}s"], "wall_s": CHILD_TIMEOUT_S}
    lines = [line for line in completed.stdout.splitlines() if line.startswith(CHILD_PREFIX)]
    wall = round(time.perf_counter() - started, 3)
    if not lines:
        tail = completed.stdout[-1500:]  # 子进程崩溃时保留尾部输出以便诊断（其中只有日志与异常）
        return {"tag": tag, "ok": False, "exit_code": completed.returncode, "wall_s": wall,
                "failures": [f"child produced no result line (exit {completed.returncode})"], "output_tail": tail}
    child = json.loads(lines[-1][len(CHILD_PREFIX):])
    child.update(exit_code=completed.returncode, wall_s=wall)
    return child


def classify_nojit(child: dict[str, Any]) -> str:
    if child.get("ok"):
        return "native_sm120_kernels"
    error = child.get("error") or {}
    if error.get("stage") in ("load_model", "decode") and NO_KERNEL_PATTERN.search(error.get("message", "")):
        return "relies_on_ptx_jit"
    return "inconclusive_failure"


def package_dll_listing() -> dict[str, Any]:
    """不导入 ctranslate2，直接列出其 wheel 目录里附带的 DLL 名称。"""
    spec = importlib.util.find_spec("ctranslate2")
    if spec is None or not spec.submodule_search_locations:
        return {"found": False}
    package_dir = Path(list(spec.submodule_search_locations)[0])
    roots = [package_dir, package_dir.parent / "ctranslate2.libs"]
    listing = {str(root.name): sorted(item.name for item in root.glob("*.dll")) for root in roots if root.is_dir()}
    shipped = sorted(name for names in listing.values() for name in names if name.lower().startswith(DLL_PREFIXES))
    return {"found": True, "package_dir": str(package_dir), "dlls": listing, "ships_cuda_runtime_dlls": shipped}


def main() -> int:
    args_list = sys.argv[1:]
    child_tag = None
    if "--child" in args_list:  # --child <tag> 由本脚本自行取走，其余交给 smokelib.parse_args
        index = args_list.index("--child")
        child_tag = args_list[index + 1]
        del sys.argv[index + 1:index + 3]  # sys.argv[0] 是脚本名，故偏移 +1
    args = smokelib.parse_args("Smoke: torch first, then CTranslate2 / faster-whisper on CUDA.")
    if child_tag is not None:
        return child_main(child_tag, args.out)

    timer = smokelib.Timer()
    failures: list[str] = []
    result: dict[str, Any] = {"passed": False, "versions": smokelib.package_versions(
        "torch", "ctranslate2", "faster-whisper", "transformers", "numpy", "torchaudio"), "device": "unavailable",
        "failures": failures, "path_has_private_dll_dir": any(
            PRIVATE_DLL_DIR in entry.lower() for entry in os.environ.get("PATH", "").split(os.pathsep))}
    if result["path_has_private_dll_dir"]:
        failures.append("PATH contains whisper-runtime-provisional")
    result["ctranslate2_wheel"] = package_dll_listing()

    children: dict[str, dict[str, Any]] = {}
    for tag, extra_env in CHILDREN:
        children[tag] = run_child(tag, extra_env, args.out)
    result["children"] = {tag: {key: value for key, value in child.items() if key != "dlls"} for tag, child in children.items()}
    cold, warm, nojit = children["cold"], children["warm"], children["nojit"]
    for tag in ("cold", "warm"):
        if not children[tag].get("ok"):
            failures.append(f"child {tag} failed: " + "; ".join(children[tag].get("failures", [])))
    for tag in ("cold", "warm"):
        dlls = children[tag].get("dlls")
        if dlls:
            result.setdefault("dlls", {})[tag] = dlls
    first = cold if cold.get("torch") else warm
    if first.get("torch"):
        result["device"] = first["torch"]["device"]
        result["torch_runtime"] = {key: first["torch"][key] for key in ("version", "cuda", "cudnn_version", "capability", "arch_list")}
    if first.get("ct2"):
        result["ct2_runtime"] = first["ct2"]
    result["timings_s"] = {tag: {"model_load_s": child.get("model_load_s"), "decode_s": child.get("decode_s"),
                                 "wall_s": child.get("wall_s")} for tag, child in children.items()}
    result["ptx_jit"] = {"finding": classify_nojit(nojit), "nojit_child_ok": bool(nojit.get("ok")),
                         "nojit_error": nojit.get("error")}
    result["decode_matches_frozen"] = {tag: (child.get("decode") or {}).get("tokens_equal_frozen")
                                       for tag, child in children.items()}
    result["feature_sha_matches_frozen"] = {tag: (child.get("feature") or {}).get("feature_sha256_equal_frozen")
                                            for tag, child in children.items()}
    result["elapsed_s"] = round(time.perf_counter() - timer.started, 3)
    result["passed"] = not failures
    return smokelib.finish(args.out, NAME, result)


if __name__ == "__main__":
    sys.exit(main())
