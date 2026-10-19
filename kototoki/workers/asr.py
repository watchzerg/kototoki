"""ASR worker：`python -m kototoki.workers.asr --jobs <path>`，逐文件写 `asr.json`。

按 `config.engine` 选择适配器：`w0` → `kototoki.asr_whisper`，`x0` → `kototoki.asr_qwen`，`cross` → 两者都加载并
常驻到进程退出（先 Whisper 后 Qwen），逐文件 ① Whisper 转写写 `asr-w0.json`、② Qwen 转写写 `asr-x0.json`、
③ 逐窗口裁判（`kototoki.judge.judge_window`，打分器为 `WhisperAsr.score`）写 `asr-judge.json` 与合并结果 `asr.json`。
三种引擎写出同一种 `asr.json`。jobs：`config` 需要 `engine`、`models`（w0 用 `w0`、`w0_mel_assets`，x0 用 `x0`，
cross 三者都要）与 `model_cache`；`inputs` 需要 `wav` 与 `vad`（`vad.json`）。

`asr.json`（坐标为 WAV 本地）：身份 = PCM SHA256＋`vad.json` SHA256＋引擎配方 hash＋模型文件 SHA256（取自 `kototoki.plan`）；
payload 为 `schema_version`、`engine`、`offset_s`、`input`、`chunks`（照抄 `vad.json`）、
`original_segments`（与窗口一一对应）、`asr_traces`、`failed_windows`（协议 `fail_window` 写法）、
保留文本 `text`、`metadata`、`stages`。cross 的 `asr.json` 取 w0 的段结构、trace 与失败窗口，段文字换成合并文本；
三个审计产物不参与 `is_current`，窗口文字只写进 `.work/` 产物，不进日志。
本模块导入时不加载 torch／CT2，适配器在 `start` 里才导入。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
from pathlib import Path
import re
import sys
import time
from typing import Any

from kototoki import artifacts, judge, plan, recipes
from kototoki.workers import gpu
from kototoki.workers.protocol import FileJob, Jobs, fail_window, retained_text, validate_failed_windows

STAGE = "asr"

logger = logging.getLogger(f"kototoki.workers.{STAGE}")  # 以 `python -m` 运行时 __name__ 是 __main__，不在 INFO 级的 kototoki 之下

_SPACE = re.compile(r"\s+")


def transcript_document(engine: str, vad: Mapping[str, Any], segments: list[dict[str, Any]], traces: list[Any],
                        failures: list[tuple[int, str]], metadata: Mapping[str, Any],
                        stages: Mapping[str, float]) -> dict[str, Any]:
    """一路转写 → 完整 `asr.json` payload；段先复制，失败窗口按协议移出文字，调用方的段不被改动。"""
    document: dict[str, Any] = {
        "schema_version": 1, "engine": engine, "offset_s": vad["offset_s"], "input": vad["input"],
        "chunks": vad["chunks"], "original_segments": [dict(segment) for segment in segments],
        "asr_traces": traces, "failed_windows": [],
    }
    for index, reason in failures:
        fail_window(document, index, reason)
    validate_failed_windows(document)
    document.update(text=retained_text(document), metadata=dict(metadata), stages=dict(stages))
    return document


def log_failures(job_id: str, failures: list[tuple[int, str]], label: str = "") -> None:
    for index, reason in failures:  # 不记窗口文字
        logger.warning("[%s] %s: %swindow %d failed: %s", STAGE, job_id, label, index, reason)


def compute(asr: Any, engine: str, model_sha256: Mapping[str, str], load_s: float) -> gpu.Compute:
    def run(job: FileJob) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
        audio, pcm_sha256 = gpu.read_wav(job.inputs["wav"])
        vad, vad_sha256 = gpu.read_input_artifact(job.inputs["vad"], pcm_sha256)
        started = time.perf_counter()
        segments, traces, failures = asr.transcribe(audio, vad["chunks"])
        inference_s = time.perf_counter() - started
        log_failures(job.id, failures)
        document = transcript_document(engine, vad, segments, traces, failures, asr.metadata,
                                       {"load_s": load_s, "inference_s": inference_s})
        fields = {"windows": len(segments), "failed_windows": len(failures)}
        logger.info("[%s] %s: %d window(s), %d failed, inference %.1fs",
                    STAGE, job.id, len(segments), len(failures), inference_s)
        return (job.work_dir / artifacts.ASR, plan.asr_identity(engine, pcm_sha256, vad_sha256, model_sha256),
                document, fields)
    return run


def clean_x0(text: str) -> str:
    """x0 原文去掉与非 ASCII 字符相邻的空白（两侧都是 ASCII 时保留为一个空格，首尾去掉），同研究 `join_raw`。

    Qwen 在日文字符之间会输出空格；不清理时 raw 假设会把这些空格一并换进 w0 原文。只用于 x0，w0 原文不动。
    """
    out, last = [], 0
    for match in _SPACE.finditer(text):
        out.append(text[last:match.start()])
        before = text[match.start() - 1] if match.start() else ""
        after = text[match.end()] if match.end() < len(text) else ""
        if before and after and before.isascii() and after.isascii():
            out.append(" ")
        last = match.end()
    out.append(text[last:])
    return "".join(out).strip()


def window_record(index: int, decision: str, raw_w: str, raw_x: str,
                  judgement: judge.WindowJudgement | None = None) -> dict[str, Any]:
    return {"index": index, "identical": judgement.identical if judgement else False,
            "text_form": judgement.text_form if judgement else "unscored",
            "guard": judgement.guard if judgement else None, "w0_text": raw_w, "x0_text": raw_x,
            "intervals": list(judgement.intervals) if judgement else [], "decision": decision}


def compute_cross(whisper: Any, qwen: Any, model_sha256: Mapping[str, str], w0_sha256: Mapping[str, str],
                  x0_sha256: Mapping[str, str], loads: Mapping[str, float], *,
                  check: Callable[[], None] = gpu.check_cuda) -> gpu.Compute:
    """cross 的逐文件三步。审计产物在 `compute` 内写出，写前同样先 `check()`（与 `gpu.file_processor` 的
    "写产物前确认 CUDA 可用"一致）；合并的 `asr.json` 最后由 `file_processor` 写出，所以中途失败时没有新的
    `asr.json`，阶段会整段重算。`asr-w0.json`／`asr-x0.json` 的身份按单引擎（只含该路模型文件）计算，
    `asr-judge.json` 与 `asr.json` 用 cross 身份。"""
    margin, max_batch = recipes.CROSS["judge"]["margin"], recipes.CROSS["judge"]["max_batch"]

    def run(job: FileJob) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
        audio, pcm_sha256 = gpu.read_wav(job.inputs["wav"])
        vad, vad_sha256 = gpu.read_input_artifact(job.inputs["vad"], pcm_sha256)
        chunks = vad["chunks"]

        started = time.perf_counter()
        segments_w, traces_w, failures_w = whisper.transcribe(audio, chunks)
        inference_w0_s = time.perf_counter() - started
        log_failures(job.id, failures_w, "w0 ")
        document_w = transcript_document("w0", vad, segments_w, traces_w, failures_w, whisper.metadata,
                                         {"load_s": loads["load_w0_s"], "inference_s": inference_w0_s})
        check()
        artifacts.write_artifact(job.work_dir / artifacts.ASR_W0,
                                 plan.asr_identity("w0", pcm_sha256, vad_sha256, w0_sha256), document_w)

        started = time.perf_counter()
        segments_x, traces_x, failures_x = qwen.transcribe(audio, chunks)
        inference_x0_s = time.perf_counter() - started
        log_failures(job.id, failures_x, "x0 ")
        document_x = transcript_document("x0", vad, segments_x, traces_x, failures_x, qwen.metadata,
                                         {"load_s": loads["load_x0_s"], "inference_s": inference_x0_s})
        check()
        artifacts.write_artifact(job.work_dir / artifacts.ASR_X0,
                                 plan.asr_identity("x0", pcm_sha256, vad_sha256, x0_sha256), document_x)

        started = time.perf_counter()
        failed_w, failed_x = dict(failures_w), dict(failures_x)
        merged: list[str] = []
        records: list[dict[str, Any]] = []
        judgements: list[judge.WindowJudgement] = []
        counts = {"w0_failed": 0, "x0_failed": 0, "score_error": 0}
        for index, chunk in enumerate(chunks):
            raw_w, raw_x = segments_w[index]["text"], segments_x[index]["text"]
            if index in failed_w:  # 窗口仍记失败，不以 x0 替代；文字由 fail_window 移入 failed_windows
                merged.append(raw_w)
                records.append(window_record(index, "w0_failed", raw_w, raw_x))
                counts["w0_failed"] += 1
                continue
            if index in failed_x:
                merged.append(raw_w)
                records.append(window_record(index, "x0_failed", raw_w, raw_x))
                counts["x0_failed"] += 1
                continue

            def score(texts: list[str], chunk: dict[str, Any] = chunk) -> list[float]:
                return whisper.score(audio, chunk, texts, max_batch)
            try:
                judgement = judge.judge_window(raw_w, clean_x0(raw_x), score, margin=margin, max_batch=max_batch)
            except (RuntimeError, ValueError) as error:  # 打分出错（含数量不符）：取 w0，不算窗口级失败
                logger.warning("[%s] %s: window %d score error, keeping w0: %s: %s",
                               STAGE, job.id, index, type(error).__name__, error)
                merged.append(raw_w)
                records.append(window_record(index, "score_error", raw_w, raw_x))
                counts["score_error"] += 1
                continue
            judgements.append(judgement)
            merged.append(judgement.text)
            records.append(window_record(index, "identical" if judgement.identical else "judged",
                                         raw_w, raw_x, judgement))
        score_s = time.perf_counter() - started
        # windows 为全部窗口；identical／scored／intervals／switched 等只统计进入裁判的窗口
        summary = {**judge.summarize(judgements), "windows": len(chunks), **counts, "score_s": score_s}

        segments = [{**segment, "text": text} for segment, text in zip(segments_w, merged, strict=True)]
        judge_meta = {"id": recipes.CROSS["id"], "margin": margin, "max_batch": max_batch,
                      "text_form": recipes.CROSS["judge"]["text_form"], **summary}
        stages = {"load_s": loads["load_s"], "load_w0_s": loads["load_w0_s"], "load_x0_s": loads["load_x0_s"],
                  "inference_w0_s": inference_w0_s, "inference_x0_s": inference_x0_s, "score_s": score_s}
        document = transcript_document("cross", vad, segments, traces_w, failures_w,
                                       {"w0": whisper.metadata, "x0": qwen.metadata, "judge": judge_meta}, stages)
        identity = plan.asr_identity("cross", pcm_sha256, vad_sha256, model_sha256)
        check()
        artifacts.write_artifact(job.work_dir / artifacts.ASR_JUDGE, identity,
                                 {"offset_s": vad["offset_s"], "windows": records, "summary": summary})

        fields = {"windows": len(chunks), "failed_windows": len(failures_w), "identical": summary["identical"],
                  "intervals": summary["intervals"], "switched": summary["switched"],
                  "x0_failed": counts["x0_failed"], "score_error": counts["score_error"]}
        logger.info("[%s] %s: cross windows %d, identical %d, intervals %d, switched %d, x0_failed %d, "
                    "score_error %d, w0 %.1fs, x0 %.1fs, score %.1fs",
                    STAGE, job.id, len(chunks), summary["identical"], summary["intervals"], summary["switched"],
                    counts["x0_failed"], counts["score_error"], inference_w0_s, inference_x0_s, score_s)
        return job.work_dir / artifacts.ASR, identity, document, fields
    return run


def start(jobs: Jobs) -> Any:
    engine, models = jobs.config["engine"], jobs.config["models"]
    gpu.require_recipe(jobs, plan.recipe_hash(STAGE, engine=engine))  # 引擎不可用即启动失败
    model_sha256 = gpu.verify_models(plan.model_files(STAGE, models, engine=engine), Path(jobs.config["model_cache"]))
    logger.info("[%s] engine %s: verified %d model file(s)", STAGE, engine, len(model_sha256))
    if engine == "cross":
        # 先 Whisper：asr_whisper 按 torch → ctranslate2 → faster_whisper 的顺序导入；再 Qwen
        from kototoki.asr_whisper import WhisperAsr

        started = time.perf_counter()
        whisper = WhisperAsr(Path(models["w0"]), Path(models["w0_mel_assets"]))
        load_w0_s = time.perf_counter() - started
        logger.info("[%s] w0 model loaded in %.1fs", STAGE, load_w0_s)
        from kototoki.asr_qwen import QwenAsr

        started = time.perf_counter()
        qwen = QwenAsr(Path(models["x0"]))
        load_x0_s = time.perf_counter() - started
        logger.info("[%s] x0 model loaded in %.1fs", STAGE, load_x0_s)
        w0_sha256, x0_sha256 = ({name: model_sha256[name] for name in plan.model_files(STAGE, models, engine=part)}
                                for part in ("w0", "x0"))
        loads = {"load_s": load_w0_s + load_x0_s, "load_w0_s": load_w0_s, "load_x0_s": load_x0_s}
        return gpu.file_processor(compute_cross(whisper, qwen, model_sha256, w0_sha256, x0_sha256, loads))
    started = time.perf_counter()
    if engine == "x0":
        from kototoki.asr_qwen import QwenAsr

        asr: Any = QwenAsr(Path(models["x0"]))
    else:
        from kototoki.asr_whisper import WhisperAsr

        asr = WhisperAsr(Path(models["w0"]), Path(models["w0_mel_assets"]))
    load_s = time.perf_counter() - started
    logger.info("[%s] model loaded in %.1fs", STAGE, load_s)
    return gpu.file_processor(compute(asr, engine, model_sha256, load_s))


if __name__ == "__main__":
    sys.exit(gpu.main(start))
