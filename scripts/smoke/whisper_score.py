"""smoke `whisper_score`：验证 `WhisperAsr.score` 教师强制打分（真实模型验证：占 GPU、加载 faster-whisper，
运行前须经用户批准）。

入口：`just smoke whisper_score`（`scripts/smoke/run_all.py` 持有 `.local/gpu.lock` 并以
`python scripts/smoke/whisper_score.py --out <dir>` 启动本脚本；锁不存在时拒绝运行）。

冻结窗口 `round2/corpus/audio/hf-ii-window-01.wav` 约 300 s，超过 Whisper 的 30 s 窗口上限，所以不能整个文件当一个窗口；
改用现有同窗 W0 结果（`REFERENCE`）里的前 `WINDOWS` 个 VAD 窗口（与 `stt_frozen_window` 门禁里整数边界逐个相等的窗口同一份），
每个窗口先用产品 `WhisperAsr.transcribe` 转写，再对该窗口音频给三段文本打分：

- (a) 产品转写文本；
- (b) 同一文本的字符打乱（固定种子，保证与原文不同）；
- (c) 空文本。

每个窗口的通过条件：score(a) 比 score(b) 至少高 `MIN_GAP_NAT`（20 nat）；score(c) 恰为 0.0；
|score(a)/n_tokens − 产品 avg_logprob| < `MAX_AVG_DIFF_NAT`（0.5 nat；调研测得约 0.14，n_tokens 为文本 token 数，
不含 EOT，而产品 avg_logprob 分母含一个 EOT，因此另记 score(a)/(n_tokens+1) 供参考）。三个窗口全部通过才算通过。

冷启动首窗解码约 27 s（CT2 在 sm_120 上的 PTX JIT）。结果写 `<out>/whisper_score.json`，只含 token 数、分数、
差值、耗时与版本，不含转写文字。
"""

from __future__ import annotations

import json
from pathlib import Path
import random
import sys
from typing import Any

import smokelib

sys.path.insert(0, str(smokelib.REPO))

from kototoki import asr_whisper  # noqa: E402  先 torch 再 ctranslate2 再 faster_whisper（模块内保证）
from kototoki import config  # noqa: E402
from kototoki.recipes import W0  # noqa: E402
from kototoki.workers.gpu import read_wav  # noqa: E402

NAME = "whisper_score"
LOCAL = smokelib.REPO / ".local"
AUDIO = LOCAL / "round2/corpus/audio/hf-ii-window-01.wav"
REFERENCE = LOCAL / "w0-demo/pyannote-gpu-v1-w0-pyannote-current-hf-ii-window-01/result.json"
WINDOWS = 3
SEED = 20261019
MIN_GAP_NAT = 20.0
MAX_AVG_DIFF_NAT = 0.5


def shuffled(text: str) -> str:
    """固定种子打乱字符；打乱结果与原文相同（极短文本）时换一个种子重试。"""
    chars = list(text)
    for attempt in range(100):
        random.Random(SEED + attempt).shuffle(chars)
        if "".join(chars) != text:
            break
    return "".join(chars)


def main() -> int:
    args = smokelib.parse_args(__doc__)
    if not (LOCAL / "gpu.lock").is_file():
        print(f"{LOCAL / 'gpu.lock'} absent; run via `just smoke {NAME}`, which holds the GPU lock", file=sys.stderr)
        return 1
    timer = smokelib.Timer()
    models_root = LOCAL / "models"
    asr = asr_whisper.WhisperAsr(models_root / config.DEFAULTS["asr.w0"]["model"],
                                 models_root / config.DEFAULTS["asr.w0"]["mel_assets"])
    timer.mark("load")
    tokenizer = asr_whisper.Tokenizer(asr._model.hf_tokenizer, asr._model.model.is_multilingual,
                                      task=W0["task"], language=W0["language"])
    audio, _ = read_wav(AUDIO)
    chunks = json.loads(REFERENCE.read_text(encoding="utf-8"))["chunks"][:WINDOWS]
    segments, _, failures = asr.transcribe(audio, chunks)
    timer.mark("transcribe")

    windows: list[dict[str, Any]] = []
    for index, (chunk, segment) in enumerate(zip(chunks, segments)):
        text = segment["text"]
        n_tokens = len(tokenizer.encode(text)) if text else 0
        entry: dict[str, Any] = {"window": index, "characters": len(text), "n_tokens": n_tokens,
                                 "product_avg_logprob": segment["avg_logprob"], "passed": False}
        if text and segment["avg_logprob"] is not None:
            score_a, score_b, score_c = asr.score(audio, chunk, [text, shuffled(text), ""])
            gap = score_a - score_b
            diff = abs(score_a / n_tokens - segment["avg_logprob"])
            entry.update(score_text=score_a, score_shuffled=score_b, score_empty=score_c, gap_nat=gap,
                         avg_logprob_diff_nat=diff,
                         avg_logprob_diff_nat_with_eot=abs(score_a / (n_tokens + 1) - segment["avg_logprob"]),
                         passed=gap >= MIN_GAP_NAT and score_c == 0.0 and diff < MAX_AVG_DIFF_NAT)
        windows.append(entry)
    timer.mark("score")

    passed = not failures and len(windows) == WINDOWS and all(entry["passed"] for entry in windows)
    result = {"passed": passed, "windows": windows, "failed_windows": len(failures),
              "thresholds": {"min_gap_nat": MIN_GAP_NAT, "max_avg_logprob_diff_nat": MAX_AVG_DIFF_NAT},
              "audio": str(AUDIO.relative_to(LOCAL)), "reference": str(REFERENCE.relative_to(LOCAL)),
              "device": asr.metadata["device"], "versions": asr.metadata["package_versions"],
              "elapsed_s": timer.marks}
    return smokelib.finish(args.out, NAME, result)


if __name__ == "__main__":
    sys.exit(main())
