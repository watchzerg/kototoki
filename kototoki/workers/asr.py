"""ASR worker：`python -m kototoki.workers.asr --jobs <path>`，逐文件写 `asr.json`。

按 `plan.ENGINE_PARTS[config.engine]` 加载适配器：`w0` → `kototoki.asr_whisper`，`x0` → `kototoki.asr_qwen`，`cross` → 两者
都加载并常驻到进程退出（先 Whisper 后 Qwen），逐文件 ① Whisper 转写得 `asr-w0.json`、② Qwen 转写得 `asr-x0.json`、
③ 整文件裁判（`kototoki.judge.judge_file`，打分器为 `WhisperAsr.score`）得 `asr-judge.json` 与合并结果 `asr.json`，
四个产物由 `gpu.file_processor` 依次写出、`asr.json` 最后。每一路都经同一个 `transcribe`（转写 → 计时 → 守卫 → 记失败 → 组文档）。
三种引擎写出同一种 `asr.json`。jobs：`config` 需要 `engine`、`models`（w0 用 `w0`、`w0_mel_assets`，x0 用 `x0`，
cross 三者都要）与 `model_cache`；`inputs` 需要 `wav` 与 `vad`（`vad.json`）。

`asr.json`（坐标为 WAV 本地）：身份 = PCM SHA256＋`vad.json` SHA256＋引擎配方 hash＋模型文件 SHA256（取自 `kototoki.plan`）；
payload 为 `schema_version`、`engine`、`offset_s`、`input`、`chunks`（照抄 `vad.json`）、
`original_segments`（与窗口一一对应）、`asr_traces`、`failed_windows`（协议 `fail_window` 写法）、
保留文本 `text`、`metadata`、`stages`。cross 的 `asr.json` 取 w0 的段结构、trace 与失败窗口，段文字换成合并文本；
三个审计产物不参与 `is_current`，窗口文字只写进 `.work/` 产物，不进日志。

w0 的转写（w0 引擎，以及 cross 的 w0 那一路）在解码之后过一遍整窗守卫（`kototoki.guard`，ADR-0030）：
复读窗口折叠后改写段文字；复读折叠后仍命中、语速超限或整窗是已知幻听句的作为失败窗口（原因 `guard:<规则名>`）置空；
两种情况都在该窗 trace 里记 `guard`。x0 的转写不过守卫。
本模块导入时不加载 torch／CT2，适配器在 `start` 里才导入。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
from pathlib import Path
import sys
import time
from typing import Any, NamedTuple

from kototoki import artifacts, guard, judge, plan, recipes
from kototoki.workers import gpu
from kototoki.workers.protocol import FileJob, Jobs, fail_window, retained_text, validate_failed_windows

STAGE = "asr"

logger = logging.getLogger(f"kototoki.workers.{STAGE}")  # 以 `python -m` 运行时 __name__ 是 __main__，不在 INFO 级的 kototoki 之下


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


def apply_guard(job_id: str, segments: list[dict[str, Any]], traces: list[Any],
                failures: list[tuple[int, str]]) -> int:
    """对未失败的 w0 窗口逐个过整窗守卫，就地改 `segments`／`traces`／`failures`，返回被守卫改动的窗口数。

    折叠：换掉该段文字；置空：文字不动，追加一条失败（之后由 `fail_window` 移入 `failed_windows`）。
    两者都把守卫记录写进该窗 trace 的 `guard`。日志只记窗口号、动作与计数。
    """
    failed = {index for index, _ in failures}
    guarded = 0
    for index, segment in enumerate(segments):
        if index in failed:
            continue
        text, record = guard.apply(segment["text"], segment["end"] - segment["start"])
        if record is None:
            continue
        guarded += 1
        traces[index] = {**(traces[index] or {}), "guard": record}
        if record["action"] == "blank":
            failures.append((index, f"guard:{record['rule']}"))
        else:
            segments[index] = {**segment, "text": text}
            logger.warning("[%s] %s: window %d guard %s collapsed: period %d, copies %d, removed %d chars",
                           STAGE, job_id, index, record["rule"], record["period"], record["copies"],
                           record["removed_raw_chars"])
    return guarded


class Transcript(NamedTuple):
    """一路转写的结果：守卫后的段、trace、失败窗口（`segments` 里失败窗口的文字仍在）与组好的文档。"""
    segments: list[dict[str, Any]]
    traces: list[Any]
    failures: list[tuple[int, str]]
    guarded: int
    inference_s: float
    document: dict[str, Any]


def transcribe(job_id: str, asr: Any, part: str, audio: Any, vad: Mapping[str, Any], load_s: float,
               label: str = "") -> Transcript:
    """一路转写 → 计时 → 守卫 → 记失败 → 组文档；`part` 是 `plan.ENGINE_PARTS` 的部件名，只有 w0 过整窗守卫。"""
    started = time.perf_counter()
    segments, traces, failures = asr.transcribe(audio, vad["chunks"])
    inference_s = time.perf_counter() - started
    guarded = apply_guard(job_id, segments, traces, failures) if part == "w0" else 0  # x0 不过守卫
    log_failures(job_id, failures, label)
    document = transcript_document(part, vad, segments, traces, failures, asr.metadata,
                                   {"load_s": load_s, "inference_s": inference_s})
    return Transcript(segments, traces, failures, guarded, inference_s, document)


def compute(asr: Any, engine: str, model_sha256: Mapping[str, str], load_s: float) -> gpu.Compute:
    def run(job: FileJob) -> tuple[list[gpu.Output], dict[str, Any]]:
        audio, pcm_sha256 = gpu.read_wav(job.inputs["wav"])
        vad, vad_sha256 = gpu.read_input_artifact(job.inputs["vad"], pcm_sha256)
        result = transcribe(job.id, asr, engine, audio, vad, load_s)
        windows, failed = len(result.segments), len(result.failures)
        fields = {"windows": windows, "failed_windows": failed, "guarded_windows": result.guarded}
        logger.info("[%s] %s: %d window(s), %d failed, %d guarded, inference %.1fs",
                    STAGE, job.id, windows, failed, result.guarded, result.inference_s)
        identity = plan.asr_identity(engine, pcm_sha256, vad_sha256, model_sha256)
        return [(job.work_dir / artifacts.ASR, identity, result.document)], fields
    return run


def compute_cross(whisper: Any, qwen: Any, model_sha256: Mapping[str, str], w0_sha256: Mapping[str, str],
                  x0_sha256: Mapping[str, str], loads: Mapping[str, float]) -> gpu.Compute:
    """cross 的逐文件三步：两路转写、整文件裁判（`judge.judge_file`），返回四个产物，合并的 `asr.json` 在最后。

    `gpu.file_processor` 查一次 CUDA 后依次写出，中途失败时没有新的 `asr.json`，阶段会整段重算。
    `asr-w0.json`／`asr-x0.json` 的身份按单引擎（只含该路模型文件）计算，`asr-judge.json` 与 `asr.json` 用 cross 身份。
    """
    margin, max_batch = recipes.CROSS["judge"]["margin"], recipes.CROSS["judge"]["max_batch"]

    def run(job: FileJob) -> tuple[list[gpu.Output], dict[str, Any]]:
        audio, pcm_sha256 = gpu.read_wav(job.inputs["wav"])
        vad, vad_sha256 = gpu.read_input_artifact(job.inputs["vad"], pcm_sha256)
        chunks = vad["chunks"]
        w0 = transcribe(job.id, whisper, "w0", audio, vad, loads["load_w0_s"], "w0 ")  # 裁判与合并用守卫后的 w0 文字
        x0 = transcribe(job.id, qwen, "x0", audio, vad, loads["load_x0_s"], "x0 ")

        def score_for(index: int) -> Callable[[list[str]], list[float]]:
            return lambda texts: whisper.score(audio, chunks[index], texts, max_batch)

        def score_error(index: int, error: Exception) -> None:  # 只记序号与异常，不记文字
            logger.warning("[%s] %s: window %d score error, keeping w0: %s: %s",
                           STAGE, job.id, index, type(error).__name__, error)

        started = time.perf_counter()
        judged = judge.judge_file([s["text"] for s in w0.segments], [s["text"] for s in x0.segments],
                                  {index for index, _ in w0.failures}, {index for index, _ in x0.failures},
                                  score_for, margin=margin, max_batch=max_batch, on_score_error=score_error)
        score_s = time.perf_counter() - started
        # windows 为全部窗口；identical／scored／intervals／switched 等只统计进入裁判的窗口
        summary = {**judged.summary, "score_s": score_s}

        segments = [{**segment, "text": text} for segment, text in zip(w0.segments, judged.texts, strict=True)]
        judge_meta = {"id": recipes.CROSS["id"], "margin": margin, "max_batch": max_batch,
                      "text_form": recipes.CROSS["judge"]["text_form"], **summary}
        stages = {"load_s": loads["load_s"], "load_w0_s": loads["load_w0_s"], "load_x0_s": loads["load_x0_s"],
                  "inference_w0_s": w0.inference_s, "inference_x0_s": x0.inference_s, "score_s": score_s}
        document = transcript_document("cross", vad, segments, w0.traces, w0.failures,
                                       {"w0": whisper.metadata, "x0": qwen.metadata, "judge": judge_meta}, stages)
        identity = plan.asr_identity("cross", pcm_sha256, vad_sha256, model_sha256)
        outputs = [
            (job.work_dir / artifacts.ASR_W0, plan.asr_identity("w0", pcm_sha256, vad_sha256, w0_sha256), w0.document),
            (job.work_dir / artifacts.ASR_X0, plan.asr_identity("x0", pcm_sha256, vad_sha256, x0_sha256), x0.document),
            (job.work_dir / artifacts.ASR_JUDGE, identity,
             {"offset_s": vad["offset_s"], "windows": judged.records, "summary": summary}),
            (job.work_dir / artifacts.ASR, identity, document),
        ]
        fields = {"windows": len(chunks), "failed_windows": len(w0.failures), "guarded_windows": w0.guarded,
                  "identical": summary["identical"],
                  "intervals": summary["intervals"], "switched": summary["switched"],
                  "x0_failed": summary["x0_failed"], "score_error": summary["score_error"]}
        logger.info("[%s] %s: cross windows %d, identical %d, intervals %d, switched %d, x0_failed %d, "
                    "score_error %d, guarded %d, w0 %.1fs, x0 %.1fs, score %.1fs",
                    STAGE, job.id, len(chunks), summary["identical"], summary["intervals"], summary["switched"],
                    summary["x0_failed"], summary["score_error"], w0.guarded, w0.inference_s, x0.inference_s,
                    score_s)
        return outputs, fields
    return run


def load_adapter(part: str, models: Mapping[str, str]) -> Any:
    """按部件名加载适配器；导入放在这里，壳模块导入时不加载 torch／CT2。"""
    if part == "w0":
        from kototoki.asr_whisper import WhisperAsr  # 按 torch → ctranslate2 → faster_whisper 的顺序导入

        return WhisperAsr(Path(models["w0"]), Path(models["w0_mel_assets"]))
    from kototoki.asr_qwen import QwenAsr

    return QwenAsr(Path(models["x0"]))


def start(jobs: Jobs) -> Any:
    engine, models = jobs.config["engine"], jobs.config["models"]
    gpu.require_recipe(jobs, plan.recipe_hash(STAGE, engine=engine))  # 引擎不可用即启动失败
    model_sha256 = gpu.verify_models(plan.model_files(STAGE, models, engine=engine), Path(jobs.config["model_cache"]))
    logger.info("[%s] engine %s: verified %d model file(s)", STAGE, engine, len(model_sha256))
    parts = plan.ENGINE_PARTS[engine]
    adapters, load_s = {}, {}
    for part in parts:  # 按 ENGINE_PARTS 的次序：cross 先 Whisper 后 Qwen
        started = time.perf_counter()
        adapters[part] = load_adapter(part, models)
        load_s[part] = time.perf_counter() - started
        logger.info("[%s] %smodel loaded in %.1fs", STAGE, f"{part} " if len(parts) > 1 else "", load_s[part])
    if len(parts) == 1:
        return gpu.file_processor(compute(adapters[engine], engine, model_sha256, load_s[engine]))
    # 两路各自的模型身份只含该路模型文件（部件名同单引擎名）
    w0_sha256, x0_sha256 = ({name: model_sha256[name] for name in plan.model_files(STAGE, models, engine=part)}
                            for part in parts)
    loads = {"load_s": load_s["w0"] + load_s["x0"], "load_w0_s": load_s["w0"], "load_x0_s": load_s["x0"]}
    return gpu.file_processor(compute_cross(adapters["w0"], adapters["x0"], model_sha256, w0_sha256, x0_sha256,
                                            loads))


if __name__ == "__main__":
    sys.exit(gpu.main(start))
