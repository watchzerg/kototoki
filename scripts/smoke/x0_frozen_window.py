"""票据 07 冻结窗口门禁（真实模型验证：占 GPU、加载 VAD／Qwen3-ASR／MMS 三个模型，运行前须经用户批准）。

与票据 03 的 `stt_frozen_window` 同法同标准，只是 ASR 引擎取 `x0`，对照现有同窗 X0 结果：
VAD 窗口整数边界逐个相等；ASR 每窗文字逐字符相等（不相等即不通过）；对齐 units 字符范围与状态一致，
有时间的 unit 起止与对照差 ≤20 ms（超差单独标记）。另记触顶窗口数（对照中为 0）。

入口：`just smoke x0_frozen_window`（`run_all.py` 持锁并以 `python scripts/smoke/x0_frozen_window.py --out <dir>`
启动本脚本；锁不存在时拒绝运行）。产物写入 `<out>/x0_frozen_window/`，
结果写 `<out>/x0_frozen_window.json`，只含计数、差值、耗时与版本，不含转写文字。
"""

from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path
import sys
from typing import Any

import smokelib
from stt_frozen_window import AUDIO, LOCAL, child_env, compare, run_stage  # 同目录脚本；它把仓库根加入 sys.path

from kototoki import artifacts, config, plan  # noqa: E402
from kototoki.workers.protocol import FileJob, Jobs  # noqa: E402

NAME = "x0_frozen_window"
REFERENCE = "x0-demo/pyannote-gpu-v1-x0-pyannote-current-hf-ii-window-01/result.json"


def main() -> int:
    args = smokelib.parse_args(__doc__)
    if not (LOCAL / "gpu.lock").is_file():
        print(f"{LOCAL / 'gpu.lock'} absent; run via `just smoke {NAME}`, which holds the GPU lock", file=sys.stderr)
        return 1
    audio = LOCAL / AUDIO
    models_root = LOCAL / "models"
    models = {"vad": str(models_root / config.DEFAULTS["vad"]["model"]),
              "x0": str(models_root / config.DEFAULTS["asr.x0"]["model"]),
              "align": str(models_root / config.DEFAULTS["align"]["model"])}
    out = args.out.resolve() / NAME
    work_dir = artifacts.register_work_dir(out, audio.name)
    model_cache = str(artifacts.model_cache_path(out))
    env = child_env(artifacts.work_root(out) / artifacts.CACHE_DIR)

    stages: dict[str, Any] = {}
    chain = (
        ("vad", plan.recipe_hash("vad"), {"models": models, "model_cache": model_cache}, {"wav": str(audio)}),
        ("asr", plan.recipe_hash("asr", engine="x0"), {"engine": "x0", "models": models, "model_cache": model_cache},
         {"wav": str(audio), "vad": str(work_dir / artifacts.VAD)}),
        ("align", plan.recipe_hash("align"), {"models": models, "model_cache": model_cache},
         {"wav": str(audio), "asr": str(work_dir / artifacts.ASR)}),
    )
    for stage, recipe_hash, stage_config, inputs in chain:
        job = FileJob(work_dir.name, work_dir, {name: Path(path) for name, path in inputs.items()})
        stages[stage] = run_stage(stage, Jobs(stage, recipe_hash, stage_config, (job,)), out, env)
        if stages[stage]["exit_code"] != 0:
            break

    result: dict[str, Any] = {"stages": stages, "out": str(out), "audio": AUDIO, "reference": REFERENCE,
                              "versions": {name: importlib.metadata.version(name) for name in (
                                  "torch", "torchaudio", "transformers", "pyannote.audio", "numpy")}}
    if all(stage["exit_code"] == 0 for stage in stages.values()) and len(stages) == 3:
        reference = json.loads((LOCAL / REFERENCE).read_text(encoding="utf-8"))
        for trace in reference["asr_traces"]:  # 研究期 trace 的 token 字段名不同
            trace["tokens"] = trace["token_ids"]
        comparison = compare(work_dir, reference)
        traces = artifacts.read_json(work_dir / artifacts.ASR)["asr_traces"]
        comparison["asr"]["token_limit_windows"] = sum(1 for t in traces if t and t["token_limit_reached"])
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
