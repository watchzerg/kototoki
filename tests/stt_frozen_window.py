"""票据 03 冻结窗口门禁（full：占 GPU、加载三个模型，运行前须经用户批准）。

入口：`just test-full stt_frozen_window`（`scripts/smoke/run_all.py` 持有 `.local/gpu.lock` 并以
`python -m tests.stt_frozen_window --out <dir>` 启动本脚本；锁不存在时拒绝运行）。不在 `just test` 的发现范围内
（文件名不以 `test_` 开头）。依次以子进程运行三个产品 worker（`python -m kototoki.workers.<stage>`），
输入是冻结窗口 `round2/corpus/audio/hf-ii-window-01.wav`，再与现有同窗 W0 结果对照：

- VAD 窗口整数边界逐个相等；
- ASR 每窗文字逐字符相等（不相等即不通过，阻塞票据 03）；
- 对齐 units 字符范围与状态一致，有时间的 unit 起止与现有结果（减去其 `offset_s`）差 ≤20 ms；
  超差单独标记，不阻塞 05／06。

产物写入 `<out>/stt_frozen_window/`（含 `.work/`），结果写 `<out>/stt_frozen_window.json`；
结果只含计数、差值、耗时与版本，不含转写文字。
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from kototoki import artifacts, config, plan
from kototoki.workers.protocol import FileJob, Jobs, write_jobs

REPO = Path(__file__).resolve().parent.parent
LOCAL = REPO / ".local"
NAME = "stt_frozen_window"
AUDIO = "round2/corpus/audio/hf-ii-window-01.wav"
REFERENCE = "w0-demo/pyannote-gpu-v1-w0-pyannote-current-hf-ii-window-01/result.json"
TOLERANCE_S = 0.020
PRIVATE_DLL_DIR = "whisper-runtime-provisional"


def child_env(cache: Path) -> dict[str, str]:
    """编排器将来传给 worker 的环境：UTF-8、离线、共用缓存；去掉历史私有 DLL 目录。"""
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join(entry for entry in env.get("PATH", "").split(os.pathsep)
                                  if entry and PRIVATE_DLL_DIR not in entry.lower())
    env.update(PYTHONUTF8="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1",
               HF_HUB_DISABLE_TELEMETRY="1", PYANNOTE_METRICS_ENABLED="0", TOKENIZERS_PARALLELISM="false",
               HF_HOME=str(cache), TORCH_HOME=str(cache))
    return env


def run_stage(stage: str, jobs: Jobs, out: Path, env: dict[str, str]) -> dict[str, Any]:
    jobs_path = out / f"jobs-{stage}.json"
    write_jobs(jobs_path, jobs)
    started = time.perf_counter()
    with (out / f"{stage}.stderr.log").open("w", encoding="utf-8") as log:
        result = subprocess.run([sys.executable, "-m", f"kototoki.workers.{stage}", "--jobs", str(jobs_path)],
                                cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=log, check=False)
    events = [json.loads(line) for line in result.stdout.decode("utf-8").splitlines() if line.strip()]
    print(f"[{stage}] exit {result.returncode} {events}", flush=True)
    return {"exit_code": result.returncode, "events": events, "wall_s": round(time.perf_counter() - started, 3)}


def compare(work_dir: Path, reference: dict[str, Any]) -> dict[str, Any]:
    vad = artifacts.read_json(work_dir / artifacts.VAD)
    asr = artifacts.read_json(work_dir / artifacts.ASR)
    align = artifacts.read_json(work_dir / artifacts.ALIGN)
    windows = [(c["start_sample"], c["end_sample"]) for c in vad["chunks"]]
    expected_windows = [(c["start_sample"], c["end_sample"]) for c in reference["chunks"]]
    texts = [s["text"] for s in asr["original_segments"]]
    expected_texts = [s["text"] for s in reference["original_segments"]]
    tokens_equal = [None if new is None else new["tokens"] == old["tokens"]
                    for new, old in zip(asr["asr_traces"], reference["asr_traces"])]
    offset = reference["offset_s"]
    units, expected_units = align["units"], reference["units"]
    ranges_equal = [(u["char_start"], u["char_end"]) for u in units] == \
                   [(u["char_start"], u["char_end"]) for u in expected_units]
    status_mismatch = sum(1 for new, old in zip(units, expected_units) if new["status"] != old["status"])
    differences = [abs(new[key] - (old[key] - offset)) for new, old in zip(units, expected_units)
                   if new["status"] == old["status"] == "ok" for key in ("start", "end")]
    over = sum(1 for difference in differences if difference > TOLERANCE_S + 1e-9)
    return {
        "windows": {"count": len(windows), "expected_count": len(expected_windows),
                    "integer_bounds_equal": windows == expected_windows},
        "asr": {"windows_text_equal": sum(a == b for a, b in zip(texts, expected_texts)),
                "text_equal": texts == expected_texts,
                "mismatched_windows": [i for i, (a, b) in enumerate(zip(texts, expected_texts)) if a != b],
                "windows_tokens_equal": sum(1 for value in tokens_equal if value),
                "failed_windows": len(asr["failed_windows"]), "characters": len(asr["text"])},
        "align": {"units": len(units), "expected_units": len(expected_units), "char_ranges_equal": ranges_equal,
                  "status_mismatch": status_mismatch,
                  "text_only_units": sum(1 for u in units if u["status"] == "text_only"),
                  "expected_text_only_units": sum(1 for u in expected_units if u["status"] == "text_only"),
                  "compared_boundaries": len(differences),
                  "max_abs_diff_s": round(max(differences, default=0.0), 6),
                  "exactly_equal_boundaries": sum(1 for d in differences if d < 1e-9),
                  "over_tolerance": over, "tolerance_s": TOLERANCE_S,
                  "offset_s": align["offset_s"], "reference_offset_s": offset},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="本次 test-full 的输出目录（由 run_all.py 新建）")
    args = parser.parse_args()
    if not (LOCAL / "gpu.lock").is_file():
        print(f"{LOCAL / 'gpu.lock'} absent; run via `just test-full {NAME}`, which holds the GPU lock", file=sys.stderr)
        return 1
    audio, reference_path = LOCAL / AUDIO, LOCAL / REFERENCE
    models_root = LOCAL / "models"
    models = {"vad": str(models_root / config.DEFAULTS["vad"]["model"]),
              "w0": str(models_root / config.DEFAULTS["asr.w0"]["model"]),
              "w0_mel_assets": str(models_root / config.DEFAULTS["asr.w0"]["mel_assets"]),
              "align": str(models_root / config.DEFAULTS["align"]["model"])}
    out = args.out.resolve() / NAME
    work_dir = artifacts.register_work_dir(out, audio.name)
    model_cache = str(artifacts.model_cache_path(out))
    env = child_env(artifacts.work_root(out) / artifacts.CACHE_DIR)

    stages: dict[str, Any] = {}
    chain = (
        ("vad", plan.recipe_hash("vad", ""), {"models": models, "model_cache": model_cache},
         {"wav": str(audio)}),
        ("asr", plan.recipe_hash("asr", "w0"), {"engine": "w0", "models": models, "model_cache": model_cache},
         {"wav": str(audio), "vad": str(work_dir / artifacts.VAD)}),
        ("align", plan.recipe_hash("align", ""), {"models": models, "model_cache": model_cache},
         {"wav": str(audio), "asr": str(work_dir / artifacts.ASR)}),
    )
    for stage, recipe_hash, stage_config, inputs in chain:
        job = FileJob(work_dir.name, work_dir, {name: Path(path) for name, path in inputs.items()})
        stages[stage] = run_stage(stage, Jobs(stage, recipe_hash, stage_config, (job,)), out, env)
        if stages[stage]["exit_code"] != 0:
            break

    result: dict[str, Any] = {"stages": stages, "out": str(out), "audio": AUDIO, "reference": REFERENCE,
                              "versions": {name: importlib.metadata.version(name) for name in (
                                  "torch", "torchaudio", "transformers", "pyannote.audio", "faster-whisper",
                                  "ctranslate2", "numpy")}}
    if all(stage["exit_code"] == 0 for stage in stages.values()) and len(stages) == 3:
        comparison = compare(work_dir, json.loads(reference_path.read_text(encoding="utf-8")))
        result["comparison"] = comparison
        result["blocking_passed"] = (comparison["windows"]["integer_bounds_equal"] and comparison["asr"]["text_equal"]
                                     and comparison["align"]["char_ranges_equal"])
        result["time_within_tolerance"] = comparison["align"]["over_tolerance"] == 0
        result["stage_seconds"] = {name: artifacts.read_json(work_dir / file)["stages"] for name, file in (
            ("vad", artifacts.VAD), ("asr", artifacts.ASR), ("align", artifacts.ALIGN))}
    else:
        result["blocking_passed"] = False
    (args.out / f"{NAME}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result.get(key) for key in ("blocking_passed", "time_within_tolerance", "comparison")},
                     ensure_ascii=False, indent=2))
    return 0 if result["blocking_passed"] else 1

if __name__ == "__main__":
    sys.exit(main())
