"""cross 模式 T0 共驻显存探针：同一进程常驻产品 Whisper（CT2 FP16）与 Qwen3-ASR（BF16 SDPA），逐文件按
①Whisper 转写全部 VAD 窗口 ②Qwen 转写全部窗口 ③Whisper 对分歧区间的两种假设打分，测整卡显存峰值与墙钟。

设计依据 `docs/changes/cross-asr-judge.md` §2.1（流程形态、显存预算、回退阈值）与 §5（T0 标准）。
- 加载顺序：先 `import torch`，再导入 `kototoki.asr_whisper`（其内部 torch → ctranslate2 → faster_whisper），
  再导入 `kototoki.asr_qwen`（transformers）；先加载 `WhisperAsr`，再加载 `QwenAsr`，两者常驻。
- 打分：同 `asr_pair_cross_score.WhisperScorer`（`features()` 右补零到 30 s、`model.encode` 一次、编码复制成批调用
  `Whisper.align(encoder, sot_sequence, text_tokens, num_frames)`、分数＝Σ log `text_token_probs`、批上限 16），
  这里直接在同一个 `WhisperAsr` 句柄上做（只读访问其私有属性 `_model`、`_filters`）。
- 裁判（窗口级）：两路窗口文本 `kototoki_eval.schema.normalize` 后相同即取 w0、不打分；否则
  `asr_pair_oracle.disagreement_intervals` 求区间，hyp_w＝w0 窗口原文，每区间一个 hyp_x（`raw_hypothesis`
  只替换区间字符，任一失败则整窗回退规范化文本）；d＝score(hyp_x)−score(hyp_w)，d > −1 取 x0（无长度项），
  各区间独立判定后一起应用；合并为空而 w0 非空时保持 w0；任一路窗口失败时取 w0、不裁判。
  本探针测资源，不算 CER；逐窗口决定写 `judge-<film>.jsonl`，供之后与产品验收对照。
- 采样：旁路线程每 0.5 s 调用 `nvidia-smi` 取整卡已用显存（CT2 的显存 torch 统计不到），按当前阶段打标签；
  每个阶段开始时重置 torch 峰值统计，结束时记录 `max_memory_allocated`／`max_memory_reserved`。
- 最后释放 Qwen（del＋gc＋`torch.cuda.empty_cache`），观察"只剩 Whisper"的整卡残留；不重新加载。
- 阈值：整卡峰值（含桌面）＋1 GB ≤ 13.5 GB 才共驻，否则回退三段式；GB 按 1024 MiB 计，十进制口径另列。

运行期间持有 `.local/gpu.lock`（产品 `kototoki.job.ProcessLock` 格式），结束或失败时释放。
产物写 `.local/quality-exploration-v5/cross-coresidency-probe/`：`samples.csv`、`summary.json`、`judge-<film>.jsonl`；
控制台只打印计数与耗时，不打印窗口文字。

命令（仓库根目录；GPU，加载 Whisper 与 Qwen，约 25 分钟，须先经用户批准）：
  .venv/Scripts/python.exe -X utf8 -m experiments.quality_v5.coresidency_probe
"""

import argparse
import csv
from datetime import datetime, timezone
import gc
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time

from kototoki_eval.schema import normalize

from . import asr_pair_ctc_judge as c
from . import asr_pair_cross_score as cs
from . import asr_pair_oracle as o

OUT = o.V5 / "cross-coresidency-probe"
WORK = o.V5 / "01/out-w0/.work"
STORED_X0 = o.V5 / "01/out-x0/.work"
FILM_IDS = {"hf-ii": "8d2f3e76dd0c", "hf-iii": "fb2e0da74018"}
MARGIN = -1.0          # d > MARGIN 取 x0；无长度项
BATCH = 16             # align() 每批最多条数（WhisperScorer._align 内部分批）
BUDGET_GB = 13.5
HEADROOM_GB = 1.0
SAMPLE_INTERVAL_S = 0.5
SETTLE_S = 3.0         # idle 与 after-free 阶段的静置时长，保证至少几个样本
DLL_PATTERN = "cudnn|cublas|cudart|nvrtc|nvJitLink|ctranslate2|cufft|curand|cusparse|cusolver|nvcuda|torch_cuda|c10_cuda"


# ---------- 纯逻辑（离线测试覆盖） ----------

def threshold_decision(peak_mib: float, budget_gb: float = BUDGET_GB, headroom_gb: float = HEADROOM_GB) -> dict:
    """整卡峰值＋余量 ≤ 预算 → 共驻；主口径 GB＝1024 MiB，十进制口径（GB＝10^9 B）另列。"""
    binary = {"budget_mib": budget_gb * 1024, "headroom_mib": headroom_gb * 1024}
    decimal = {"budget_mib": budget_gb * 1e9 / 2**20, "headroom_mib": headroom_gb * 1e9 / 2**20}
    out = {"peak_mib": peak_mib}
    for name, unit in (("binary", binary), ("decimal", decimal)):
        total = peak_mib + unit["headroom_mib"]
        out[name] = {**{k: round(v, 1) for k, v in unit.items()}, "peak_plus_headroom_mib": round(total, 1),
                     "slack_mib": round(unit["budget_mib"] - total, 1), "co_resident": total <= unit["budget_mib"]}
    out["co_resident"] = out["binary"]["co_resident"]
    out["verdict"] = "co-resident" if out["co_resident"] else "fallback-three-pass"
    return out


class PhaseRecorder:
    """当前阶段标签、整卡样本与每阶段的 torch 峰值。`torch_stats()` 返回 None（CUDA 未初始化）或
    {max_allocated, max_reserved, allocated, reserved}（字节）；`reset()` 重置 torch 峰值统计。线程安全。"""

    def __init__(self, clock=time.perf_counter, torch_stats=lambda: None, reset=lambda: None):
        self.clock, self.torch_stats, self.reset = clock, torch_stats, reset
        self.t0 = clock()
        self.samples: list[tuple[float, str, float]] = []
        self.phases: list[dict] = []
        self._lock = threading.Lock()
        self._current: dict | None = None

    @property
    def phase(self) -> str | None:
        return self._current["phase"] if self._current else None

    def enter(self, phase: str) -> None:
        self.close()
        self.reset()
        with self._lock:
            self._current = {"phase": phase, "start_s": self.clock() - self.t0}

    def close(self) -> None:
        with self._lock:
            current, self._current = self._current, None
        if current is None:
            return
        current["end_s"] = self.clock() - self.t0
        current["wall_s"] = current["end_s"] - current["start_s"]
        current["torch"] = self.torch_stats()
        self.phases.append(current)

    def sample(self, used_mib: float) -> None:
        with self._lock:
            phase = self._current["phase"] if self._current else "between"
            self.samples.append((self.clock() - self.t0, phase, used_mib))

    def summary(self) -> list[dict]:
        rows = []
        for item in self.phases:
            inside = [u for _, p, u in self.samples if p == item["phase"]]
            stats = item.get("torch")
            mib = (lambda key: round(stats[key] / 2**20, 1)) if stats else (lambda key: None)
            rows.append({"phase": item["phase"], "wall_s": round(item["wall_s"], 2),
                         "samples": len(inside), "card_peak_mib": max(inside) if inside else None,
                         "card_min_mib": min(inside) if inside else None,
                         "card_last_mib": inside[-1] if inside else None,
                         "torch_max_allocated_mib": mib("max_allocated"), "torch_max_reserved_mib": mib("max_reserved"),
                         "torch_allocated_end_mib": mib("allocated"), "torch_reserved_end_mib": mib("reserved")})
        return rows


def raw_hypotheses(raw_w: str, raw_x: str, nw: str, nx: str, intervals: list[dict]) -> tuple[list[str], str]:
    """[hyp_w, hyp_x0, …] 与形式（raw／norm）；任一 raw 假设失败则整窗用规范化文本。"""
    try:
        consistent = normalize(raw_w).text == nw and normalize(raw_x).text == nx
    except ValueError:
        consistent = False
    if consistent:
        hyps = [cs.raw_hypothesis(raw_w, raw_x, it) for it in intervals]
        if all(h is not None for h in hyps):
            return [raw_w, *hyps], "raw"
    return [nw, *(o.compose(nw, [it], ["x"]) for it in intervals)], "norm"


def merge_raw(raw_w: str, raw_x: str, intervals: list[dict], picks: list[bool]) -> str:
    """把被接受的区间一起应用到 w0 原文（从右到左替换，偏移不受前面替换影响）。"""
    nw, nx = normalize(raw_w), normalize(raw_x)
    out = raw_w
    for it, pick in sorted(zip(intervals, picks), key=lambda pair: pair[0]["w_start"], reverse=True):
        if not pick:
            continue
        ws, we = cs.raw_span(nw.raw_spans, it["w_start"], it["w_end"])
        replacement = ""
        if it["x"]:
            xs, xe = cs.raw_span(nx.raw_spans, it["x_start"], it["x_end"])
            replacement = raw_x[xs:xe]
        out = out[:ws] + replacement + out[we:]
    return out


def plan_window(raw_w: str, raw_x: str, w_failed: bool, x_failed: bool) -> dict:
    """窗口级裁判计划：status ∈ w0_failed／x0_failed／normalize_error／identical／judge；judge 时给出区间与待打分假设。"""
    if w_failed:
        return {"status": "w0_failed"}
    if x_failed:
        return {"status": "x0_failed"}
    try:
        nw, nx = normalize(raw_w).text, normalize(raw_x).text
    except ValueError:
        return {"status": "normalize_error"}
    if nw == nx:
        return {"status": "identical"}
    intervals = o.disagreement_intervals(nw, nx)
    hyps, form = raw_hypotheses(raw_w, raw_x, nw, nx, intervals)
    return {"status": "judge", "nw": nw, "nx": nx, "intervals": intervals, "hyps": hyps, "form": form}


def decide_window(plan: dict, raw_w: str, raw_x: str, scores: list[float], margin: float = MARGIN) -> dict:
    """scores 与 plan["hyps"] 对齐；各区间独立判定（d > margin 取 x0）后一起应用；空结果守卫。"""
    base = scores[0]
    picks = [s - base > margin for s in scores[1:]]
    composed = o.compose(plan["nw"], plan["intervals"], ["x" if p else "w" for p in picks])
    merged = merge_raw(raw_w, raw_x, plan["intervals"], picks) if plan["form"] == "raw" else composed
    if normalize(merged).text != composed:  # raw 合并与规范化拼接不一致时退回规范化文本
        merged = composed
    guarded = bool(raw_w.strip()) and not normalize(merged).text and any(picks)
    if guarded:
        picks, merged = [False] * len(picks), raw_w
    return {"picks": picks, "merged": merged, "empty_guard": guarded,
            "intervals": [{"w": it["w"], "x": it["x"], "w_start": it["w_start"], "w_end": it["w_end"],
                           "score_w": base, "score_x": s, "d": s - base, "switch": p}
                          for it, s, p in zip(plan["intervals"], scores[1:], picks)]}


# ---------- GPU 部分 ----------

class Scorer:
    """`asr_pair_cross_score.WhisperScorer` 的打分路径，套在已加载的产品 `WhisperAsr` 句柄上（不再加载第二份）。"""

    def __init__(self, asr):
        from kototoki import asr_whisper as aw
        from kototoki.recipes import W0

        self.aw, self.asr = aw, asr
        self.model, self.filters = asr._model, asr._filters
        self.tokenizer = aw.Tokenizer(self.model.hf_tokenizer, self.model.model.is_multilingual,
                                      task=W0["task"], language=W0["language"])
        self.sot = list(self.tokenizer.sot_sequence)

    encode_text = cs.WhisperScorer.encode_text
    _align = cs.WhisperScorer._align

    def scores(self, audio, texts: list[str]) -> list[float]:
        """唯一文本只算一次；一窗一次 encode，批上限 16。"""
        unique = sorted(set(texts))
        logprobs = self._align(audio, [self.encode_text(t) for t in unique])
        table = {t: float(sum(lp)) for t, lp in zip(unique, logprobs)}
        return [table[t] for t in texts]


def nvidia_smi_used() -> float | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        return float(out.split()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def sampler(recorder: PhaseRecorder, stop: threading.Event) -> threading.Thread:
    def run():
        while not stop.is_set():
            used = nvidia_smi_used()
            if used is not None:
                recorder.sample(used)
            stop.wait(SAMPLE_INTERVAL_S)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def powershell(command: str) -> str:
    return subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True,
                          timeout=60).stdout


def preflight() -> dict:
    """无 GPU 锁、无 llama-server、无其他 python 作业（排除自身与 venv 启动器父进程；命令行含 `unittest` 的
    离线测试及其子进程不占 GPU，只记录）。WDDM 下 `nvidia-smi` 的 compute 列表含全部桌面进程，只看其中的 python／llama。"""
    own = {os.getpid(), os.getppid()}
    listing = powershell(
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(python|pythonw|llama-server)[.]exe$' } "
        "| ForEach-Object { \"$($_.ProcessId)`t$($_.ParentProcessId)`t$($_.Name)`t$($_.CommandLine)\" }")
    processes = {}
    for line in listing.splitlines():
        fields = line.split("\t", 3)
        if len(fields) == 4 and fields[0].isdigit() and int(fields[0]) not in own:
            processes[int(fields[0])] = {"pid": int(fields[0]), "parent": int(fields[1] or 0), "name": fields[2],
                                         "command": fields[3].strip()}
    allowed = {pid for pid, proc in processes.items() if "unittest" in proc["command"]}
    while True:  # 离线测试的子孙进程（测试里起的子进程，命令行常读不到）
        more = {pid for pid, proc in processes.items() if proc["parent"] in allowed} - allowed
        if not more:
            break
        allowed |= more
    blocking = [proc for pid, proc in processes.items() if "llama" in proc["name"] or pid not in allowed]
    compute = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
                              "--format=csv,noheader"], capture_output=True, text=True, timeout=10).stdout
    gpu_apps = [line for line in compute.splitlines() if "python" in line.lower() or "llama" in line.lower()]
    from kototoki.config import GPU_LOCK

    if blocking or gpu_apps or GPU_LOCK.exists():
        raise SystemExit(f"GPU not free: processes={blocking} compute={gpu_apps} lock_exists={GPU_LOCK.exists()}")
    return {"offline_test_processes": list(processes.values()), "gpu_compute_apps": gpu_apps, "lock_existed": False}


def loaded_dlls() -> list[str]:
    command = (f"(Get-Process -Id {os.getpid()}).Modules | Where-Object {{ $_.ModuleName -match '{DLL_PATTERN}' }} "
               "| ForEach-Object { $_.FileName }")
    return sorted(set(line.strip() for line in powershell(command).splitlines() if line.strip()))


def versions() -> dict:
    import torch

    names = ("torch", "ctranslate2", "faster-whisper", "transformers", "numpy", "tokenizers")
    driver = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
                            capture_output=True, text=True, timeout=10).stdout.strip()
    return {"python": platform.python_version(), "platform": platform.platform(),
            "packages": {n: importlib.metadata.version(n) for n in names},
            "torch_cuda": torch.version.cuda, "cudnn": torch.backends.cudnn.version(), "gpu": driver}


def model_paths() -> dict:
    """按产品 `kototoki.config.DEFAULTS` 解析模型目录（models_root 相对仓库根）。"""
    from kototoki.config import DEFAULTS, REPO_ROOT

    root = (REPO_ROOT / DEFAULTS["paths"]["models_root"]).resolve()
    return {"w0": root / DEFAULTS["asr.w0"]["model"], "w0_mel_assets": root / DEFAULTS["asr.w0"]["mel_assets"],
            "x0": root / DEFAULTS["asr.x0"]["model"]}


def verify_model_files(models: dict, cache: Path) -> dict:
    from kototoki import plan
    from kototoki.workers.gpu import verify_models

    out = {}
    for engine in ("w0", "x0"):
        out.update(verify_models(plan.model_files("asr", {k: str(v) for k, v in models.items()}, engine=engine),
                                 cache))
    return out


def stored_texts(path: Path) -> tuple[list[str], set[int]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return [s["text"] for s in doc["original_segments"]], {w["chunk_index"] for w in doc["failed_windows"]}


def run_film(film: str, whisper, qwen, scorer: Scorer, recorder: PhaseRecorder, out_dir: Path, sync) -> dict:
    from kototoki.workers.gpu import read_input_artifact, read_wav

    work = WORK / FILM_IDS[film]
    recorder.enter(f"{film}-read")
    audio, pcm = read_wav(work / "audio-16k.wav")
    if pcm != c.EXPECTED_PCM[film]:
        raise ValueError(f"{film}: PCM SHA {pcm} differs from baseline manifest")
    vad, vad_sha = read_input_artifact(work / "vad.json", pcm)
    chunks = vad["chunks"]
    stats: dict = {"pcm_sha256": pcm, "pcm_matches_baseline": True, "vad_sha256": vad_sha, "windows": len(chunks),
                   "audio_s": len(audio) / c.SAMPLE_RATE}

    recorder.enter(f"{film}-w0")
    started = time.perf_counter()
    w_segments, _, w_failures = whisper.transcribe(audio, chunks)
    sync()
    stats["w0_wall_s"] = time.perf_counter() - started

    recorder.enter(f"{film}-x0")
    started = time.perf_counter()
    x_segments, _, x_failures = qwen.transcribe(audio, chunks)
    sync()
    stats["x0_wall_s"] = time.perf_counter() - started

    recorder.enter(f"{film}-score")
    started = time.perf_counter()
    w_failed, x_failed = {i for i, _ in w_failures}, {i for i, _ in x_failures}
    counts = {"identical": 0, "judged_windows": 0, "intervals": 0, "switched": 0, "switched_windows": 0,
              "raw_fallback_windows": 0, "empty_guard": 0, "score_failed_windows": 0, "sequences": 0,
              "w0_failed": len(w_failed), "x0_failed": len(x_failed)}
    with (out_dir / f"judge-{film}.jsonl").open("w", encoding="utf-8") as sink:
        for k, chunk in enumerate(chunks):
            raw_w, raw_x = w_segments[k]["text"], x_segments[k]["text"]
            plan = plan_window(raw_w, raw_x, k in w_failed, k in x_failed)
            row = {"film": film, "window": k, "start_sample": chunk["start_sample"], "end_sample": chunk["end_sample"],
                   "status": plan["status"], "w0": raw_w, "x0": raw_x, "merged": raw_w}
            if plan["status"] == "identical":
                counts["identical"] += 1
            elif plan["status"] == "judge":
                counts["judged_windows"] += 1
                counts["intervals"] += len(plan["intervals"])
                counts["raw_fallback_windows"] += plan["form"] == "norm"
                try:
                    scores = scorer.scores(audio[chunk["start_sample"]:chunk["end_sample"]], plan["hyps"])
                except RuntimeError as error:
                    counts["score_failed_windows"] += 1
                    row.update(status="score_failed", error=f"{type(error).__name__}: {error}")
                else:
                    counts["sequences"] += len(set(plan["hyps"]))
                    decision = decide_window(plan, raw_w, raw_x, scores)
                    counts["switched"] += sum(decision["picks"])
                    counts["switched_windows"] += any(decision["picks"])
                    counts["empty_guard"] += decision["empty_guard"]
                    row.update(form=plan["form"], merged=decision["merged"], intervals=decision["intervals"],
                               empty_guard=decision["empty_guard"])
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
    sync()
    stats["score_wall_s"] = time.perf_counter() - started
    stats.update(counts)
    stats["w0_failures"] = [[i, r] for i, r in w_failures]
    stats["x0_failures"] = [[i, r] for i, r in x_failures]

    # 与 v5 第 1 步单独运行的产物对照（文字是否逐窗一致；不打印文字）
    comparison = {}
    for name, segments, failed, path in (("w0", w_segments, w_failed, work / "asr.json"),
                                         ("x0", x_segments, x_failed, STORED_X0 / FILM_IDS[film] / "asr.json")):
        texts, stored_failed = stored_texts(path)
        both = [k for k in range(len(chunks)) if k not in failed and k not in stored_failed]
        comparison[name] = {"compared": len(both), "equal": sum(segments[k]["text"] == texts[k] for k in both),
                            "stored_failed": len(stored_failed)}
    stats["vs_stored_run"] = comparison
    print(f"[probe] {film}: windows {len(chunks)}, identical {counts['identical']}, intervals {counts['intervals']}, "
          f"switched {counts['switched']}, w0 {stats['w0_wall_s']:.1f}s, x0 {stats['x0_wall_s']:.1f}s, "
          f"score {stats['score_wall_s']:.1f}s", flush=True)
    return stats


def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    from kototoki.config import GPU_LOCK
    from kototoki.job import ProcessLock

    summary: dict = {"started_at_utc": datetime.now(timezone.utc).isoformat(), "preflight": preflight(),
                     "errors": [], "films": {}, "dlls": {}}
    lock = ProcessLock(GPU_LOCK, "GPU lock", {"job": "cross-coresidency-probe"})
    lock.acquire()
    stop = threading.Event()
    torch_mod: dict = {}

    def torch_stats():
        torch = torch_mod.get("torch")
        if torch is None or not torch.cuda.is_initialized():
            return None
        return {"max_allocated": torch.cuda.max_memory_allocated(), "max_reserved": torch.cuda.max_memory_reserved(),
                "allocated": torch.cuda.memory_allocated(), "reserved": torch.cuda.memory_reserved()}

    def reset():
        torch = torch_mod.get("torch")
        if torch is not None and torch.cuda.is_initialized():
            torch.cuda.reset_peak_memory_stats()

    def sync():
        torch = torch_mod.get("torch")
        if torch is not None and torch.cuda.is_initialized():
            torch.cuda.synchronize()

    recorder = PhaseRecorder(torch_stats=torch_stats, reset=reset)
    thread = sampler(recorder, stop)
    try:
        recorder.enter("idle")
        time.sleep(SETTLE_S)
        recorder.enter("import")
        timings = {}
        mark = time.perf_counter()
        import torch  # 先 torch，再 ctranslate2／faster_whisper（asr_whisper 模块内保证），最后 transformers
        torch_mod["torch"] = torch
        timings["import_torch_s"] = time.perf_counter() - mark
        mark = time.perf_counter()
        from kototoki.asr_whisper import WhisperAsr
        timings["import_asr_whisper_s"] = time.perf_counter() - mark
        mark = time.perf_counter()
        from kototoki.asr_qwen import QwenAsr
        timings["import_asr_qwen_s"] = time.perf_counter() - mark
        summary["import_order"] = [name for name in ("torch", "ctranslate2", "faster_whisper", "transformers")
                                   if name in sys.modules]
        summary["versions"] = versions()

        recorder.enter("verify-models")
        models = model_paths()
        mark = time.perf_counter()
        summary["model_sha256"] = verify_model_files(models, out_dir / "model-cache.json")
        timings["verify_models_s"] = time.perf_counter() - mark
        summary["model_paths"] = {k: str(v) for k, v in models.items()}

        recorder.enter("load-whisper")
        mark = time.perf_counter()
        whisper = WhisperAsr(models["w0"], models["w0_mel_assets"])
        sync()
        timings["load_whisper_s"] = time.perf_counter() - mark
        recorder.enter("load-qwen")
        mark = time.perf_counter()
        qwen = QwenAsr(models["x0"])
        sync()
        timings["load_qwen_s"] = time.perf_counter() - mark
        scorer = Scorer(whisper)
        summary["timings"] = timings
        summary["dlls"]["after_load"] = loaded_dlls()
        summary["metadata"] = {"w0": whisper.metadata, "x0": {k: v for k, v in qwen.metadata.items()
                                                              if k != "generation_config"}}
        print(f"[probe] loaded whisper {timings['load_whisper_s']:.1f}s, qwen {timings['load_qwen_s']:.1f}s",
              flush=True)

        for film in FILM_IDS:
            summary["films"][film] = run_film(film, whisper, qwen, scorer, recorder, out_dir, sync)
        summary["dlls"]["after_films"] = loaded_dlls()
        summary["metadata"]["x0"].update(peak_allocated_bytes=qwen.metadata.get("peak_allocated_bytes"),
                                         peak_reserved_bytes=qwen.metadata.get("peak_reserved_bytes"))

        recorder.enter("free-qwen")
        del qwen
        gc.collect()
        torch.cuda.empty_cache()
        sync()
        recorder.enter("after-free")
        time.sleep(SETTLE_S)
        recorder.close()
    except Exception as error:  # noqa: BLE001 - 失败也写出已有样本与错误
        summary["errors"].append(f"{type(error).__name__}: {error}")
        recorder.close()
        raise
    finally:
        stop.set()
        thread.join(timeout=15)
        lock.release()
        summary["gpu_lock_released"] = not GPU_LOCK.exists()
        phases = recorder.summary()
        peak = max((u for _, _, u in recorder.samples), default=None)
        summary["phases"] = phases
        summary["card_peak_mib"] = peak
        summary["idle_mib"] = next((r["card_peak_mib"] for r in phases if r["phase"] == "idle"), None)
        summary["threshold"] = threshold_decision(peak) if peak is not None else None
        summary["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        with (out_dir / "samples.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["t_s", "phase", "memory_used_mib"])
            writer.writerows((round(t, 3), p, u) for t, p, u in recorder.samples)
        (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str),
                                              encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=OUT)
    args = parser.parse_args()
    if args.out_dir.exists() and any(args.out_dir.glob("summary.json")):
        raise SystemExit(f"{args.out_dir} already has a summary.json; pick a new --out-dir")
    summary = run(args.out_dir)
    t = summary["threshold"]
    print(f"[probe] card peak {summary['card_peak_mib']} MiB, idle {summary['idle_mib']} MiB, "
          f"verdict {t['verdict']} (peak+1GB {t['binary']['peak_plus_headroom_mib']} / {t['binary']['budget_mib']} MiB)",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
