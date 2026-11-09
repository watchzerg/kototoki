"""公共部分：路径、两部影片的对照产物、读写工具、参考字幕与官方／单元口径 CER。

只导入标准库、`kototoki_eval`、`kototoki.artifacts`／`kototoki.workers.protocol`（纯逻辑）与
`experiments.quality_v5.asr_source`（单元口径）。不在导入时加载 torch／numpy。
转写内容只在内存里处理，写盘的 JSON 报告只含计数与指标（`counts_only` 过滤）。
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from experiments.quality_v5 import asr_source
from kototoki import artifacts
from kototoki_eval.schema import normalize
from kototoki_eval.scoring import evaluate

REPO = Path(__file__).resolve().parents[2]
LOCAL = REPO / ".local"
ROOT = LOCAL / "asr-robustness-v14"
GPU_LOCK = LOCAL / "gpu.lock"
PRODUCT_II = LOCAL / "q3-product-fullfilm" / "work" / "input-7c924c80249b"
REFERENCES = LOCAL / "fullfilm-comparison" / "fullfilm-v1" / "corpus" / "references"
BASELINE_EVAL = LOCAL / "quality-exploration-v5" / "01" / "eval"
HF_III_WAV_SOURCE = (LOCAL / "quality-exploration-v5" / "12" / "runs" / "anime-whisper" / "fb2e0da74018"
                     / artifacts.AUDIO_16K)

# 两部影片：产品形状的对照工作目录（vad.json、asr.json、align.json、ja.srt、audio-16k.wav）、参考、基线评分、专名表。
FILMS: dict[str, dict[str, Path]] = {
    "hf-ii": {
        "work": PRODUCT_II / "8d2f3e76dd0c",
        "reference": REFERENCES / "hf-ii-full.json",
        "baseline_eval": BASELINE_EVAL / "product-w0-hf-ii.json",
        "name_table": PRODUCT_II / "8d2f3e76dd0c" / artifacts.NAME_TABLE,
    },
    "hf-iii": {
        "work": ROOT / "01" / "hf-iii" / "fb2e0da74018",
        "reference": REFERENCES / "hf-iii-full.json",
        "baseline_eval": BASELINE_EVAL / "product-w0-hf-iii.json",
        "name_table": LOCAL / "name-consistency-product" / "after" / "HF-III" / artifacts.NAME_TABLE,
    },
}
PCM_SHA256 = {"hf-ii": "ee4e2da3e0b335f3d3f9d0b0a0b5bb301562846195e5419716b3ed83d76d604f",
              "hf-iii": "e8e841fde3c0fd85e42804cd6a574f1bb08c89fcec254f51f3449638fccb3ab6"}
SAMPLE_RATE = 16000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    """UTF-8、LF、缩进 1；父目录自动建立。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=1, allow_nan=False)
        handle.write("\n")


def write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def product_models() -> dict[str, Any]:
    """产品运行的 worker 配置（模型路径）；研究侧另用自己的核对缓存。"""
    config = read_json(PRODUCT_II / "jobs-asr.json")["config"]
    return {"engine": "w0", "models": config["models"], "model_cache": str(ROOT / "cache" / "model-verification.json")}


# --- 参考与 CER -----------------------------------------------------------------------------------

def load_reference_doc(film: str) -> dict[str, Any]:
    return read_json(FILMS[film]["reference"])


def reference_cues(film: str) -> list[dict[str, Any]]:
    """参考 cue：`{index, start, end, text}`（同 `asr_source.load_reference`）。"""
    return asr_source.load_reference(FILMS[film]["reference"])


def official_cer(reference: dict[str, Any], transcript: dict[str, Any]) -> dict[str, Any]:
    """官方整片口径（`kototoki_eval.scoring.evaluate`）的 `text` 块：S／D／I、CER、字符数。"""
    return dict(evaluate(reference, transcript)["text"])


def cer_summary(text: dict[str, Any]) -> dict[str, Any]:
    return {"CER": round(text["CER"] * 100, 4), "S": text["S"], "D": text["D"], "I": text["I"],
            "reference_characters": text["reference_characters"], "candidate_characters": text["candidate_characters"]}


def unit_cer(reference: list[dict[str, Any]], cues: list[dict[str, Any]]) -> dict[str, Any]:
    """单元口径（`asr_source.build_units` 的时间重叠单元）：整体 CER 为全部单元编辑距离之和／参考字符之和，
    另给桶表。`cues` 为 `{start, end, text}`。"""
    units = asr_source.build_units("x", reference, cues, [], [])
    edits = ref_chars = 0
    for unit in units:
        ref = normalize(unit.ref_ja).text
        hyp = normalize(unit.asr_ja).text
        ref_chars += len(ref)
        edits += asr_source.edit_distance(ref, hyp)
    return {"CER": round(edits / ref_chars * 100, 4) if ref_chars else None, "edits": edits,
            "reference_characters": ref_chars, "units": len(units),
            "buckets": asr_source.bucket_table(units)}


# --- 产物工具 -------------------------------------------------------------------------------------

def research_identity(label: str, upstream: dict[str, str], models: dict[str, str]) -> dict[str, Any]:
    """研究侧配方：`recipe_hash` 为配方标签的 SHA256（不是产品配方），上游与模型照抄。"""
    return artifacts.derived_identity(upstream=upstream, recipe_hash=artifacts.sha256_bytes(label.encode("utf-8")),
                                      models=models)


def strip_identity(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key != "identity"}


# --- GPU 作业公共部分 ----------------------------------------------------------------------------

@contextmanager
def gpu_lock(job: str) -> Iterator[None]:
    """`.local/gpu.lock`（`O_EXCL`）；已存在即退出，不抢占、不杀进程。格式同 `kototoki.job.ProcessLock`。"""
    GPU_LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(GPU_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit(f"{GPU_LOCK} exists; verify the owning process with Get-Process, do not kill it") from None
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump({"pid": os.getpid(), "job": job, "created_at_utc": utc_now(), "owner": "experiments.asr_robustness_v14"},
                  stream)
    try:
        yield
    finally:
        GPU_LOCK.unlink(missing_ok=True)


class VramSampler(threading.Thread):
    """每秒用 nvidia-smi 采整卡已用显存（CT2 的显存 torch 统计不到）；`peak` 为 MiB。"""

    def __init__(self, interval: float = 1.0):
        super().__init__(daemon=True)
        self.interval, self.peak, self.samples, self._stop = interval, 0, 0, threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                used = int(subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                          capture_output=True, text=True, timeout=10).stdout.split()[0])
                self.samples += 1
                self.peak = max(self.peak, used)
            except (OSError, ValueError, IndexError, subprocess.SubprocessError):
                pass
            self._stop.wait(self.interval)

    def stop(self) -> int:
        self._stop.set()
        self.join(timeout=15)
        return self.peak


def vram_used_mib() -> int | None:
    try:
        return int(subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                  capture_output=True, text=True, timeout=10).stdout.split()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def other_gpu_jobs() -> dict[str, Any]:
    """开跑前只读核对：llama-server／Strata／其他 python 进程与 `gpu.lock`；只报告，不动任何进程。"""
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, errors="replace").stdout
    names = [line.split(",")[0].strip('"') for line in out.splitlines() if line.strip()]
    suspects = sorted({n for n in names if any(k in n.lower() for k in ("llama", "strata", "python"))})
    return {"gpu_lock": GPU_LOCK.is_file(), "suspect_processes": suspects, "vram_used_mib": vram_used_mib(),
            "checked_at_utc": utc_now()}


def timed() -> float:
    return time.perf_counter()
