"""w0／x0 两路 ASR 交叉打分裁判：产品 Whisper large-v3 与 Qwen3-ASR-1.7B 用教师强制给两种假设打分。

单元、分歧区间、跨度、假设构造、判定形状与调参口径全部沿用 `asr_pair_ctc_judge`（同一单元口径、同一批
1253 个分歧区间、同一 w0∪x0 cue 并集＋0.2 s 跨度）。GPU 只做教师强制前向，不生成、不转写：
  score-whisper  产品 `WhisperAsr` 加载 CT2 模型；`features()` 建 mel（右补零到 30 s），`model.encode` 一次，
                 编码复制成批后调用 `Whisper.align(encoder, sot_sequence, text_tokens, num_frames)`，
                 分数＝Σ log text_token_probs（CT2 在 sot_sequence 后自动接 <|notimestamps|>；EOT 不在内）。
                 跨度 > 30 s 的单元不打分（保持 w0）。
  score-qwen     产品 `QwenAsr` 加载（BF16、SDPA）；`apply_transcription_request(language="ja")` 的提示
                 以 `language Japanese<asr_text>` 结尾，后接假设 token 与 <|im_end|>，单次前向取
                 log_softmax，分数＝Σ（含 <|im_end|>）。
  analyze        CPU：d_W、d_Q、缓存的 MMS d_M 与长度差，六种裁判跨片调参、准确率、AUC、自偏好与合并 CER。
两个 GPU 子命令一次只加载一个模型，运行期间持有 `.local/gpu.lock`，先写 Part A（分歧区间），再写 Part B
（w0 单元文本，可选的幻觉角度）。

文本形式：主口径 raw＝SRT cue 原文按单元拼接（去掉与非 ASCII 字符相邻的空白），区间按
`kototoki_eval.schema.normalize` 的偏移映射回原文后只替换区间字符，其余（含 w0 的标点）不动；
映射失败的单元回退到规范化文本。对照口径 norm＝规范化文本（与 MMS 实验相同）。两个假设总用同一形式。

命令（仓库根目录）：
  python -X utf8 -m experiments.quality_v5.asr_pair_cross_score score-whisper   # GPU
  python -X utf8 -m experiments.quality_v5.asr_pair_cross_score score-qwen      # GPU
  python -X utf8 -m experiments.quality_v5.asr_pair_cross_score analyze         # CPU
"""

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import itertools
import json
import math
import os
from pathlib import Path
import random
import re
import subprocess
import threading
import time

from kototoki_eval.schema import normalize

from . import asr_pair_ctc_judge as c
from . import asr_pair_oracle as o

OUT = o.V5 / "asr-pair-cross-score"
MODELS = o.LOCAL / "models"
WHISPER_DIR = MODELS / "faster-whisper-large-v3"
MEL_DIR = MODELS / "w0-assets"
QWEN_DIR = MODELS / "qwen3-asr-1.7b-hf"
ASR_JSON = {engine: {"hf-ii": o.V5 / f"01/out-{engine}/.work/8d2f3e76dd0c/asr.json",
                     "hf-iii": o.V5 / f"01/out-{engine}/.work/fb2e0da74018/asr.json"} for engine in ("w0", "x0")}
WHISPER_MAX_SAMPLES = 30 * c.SAMPLE_RATE
FORMS = ("raw", "norm")
SANITY_WINDOWS = 6  # 每部取的产品窗口数（自洽检查）
SANITY_SEED = 20261019

# 调参网格。线性：v > m + λ·Δlen；λ 网格同 MMS 实验，m 加宽到 −20…40（两模型之和的尺度更大）。
LAMBDAS = c.LAMBDAS
MARGINS = [x / 2 for x in range(-40, 81)]
AGREE_MARGINS = [float(x) for x in range(-20, 41)]
AGREE_LAMBDAS = [x / 2 for x in range(-12, 9)]  # −6 … 4，步长 0.5（三维网格，比线性粗）
MMS_WEIGHTS = (0.25, 0.5, 1.0, 2.0)


# ---------- 文本形式：raw 假设 ----------

_SPACE = re.compile(r"\s+")


def join_raw(texts: list[str]) -> str:
    """cue 原文按顺序相连；空白只在两侧都是 ASCII 时保留为一个空格（日语里的空白来自 SRT 换行）。"""
    joined = "".join(texts)
    out, last = [], 0
    for match in _SPACE.finditer(joined):
        out.append(joined[last:match.start()])
        before = joined[match.start() - 1] if match.start() else ""
        after = joined[match.end()] if match.end() < len(joined) else ""
        if before and after and before.isascii() and after.isascii():
            out.append(" ")
        last = match.end()
    out.append(joined[last:])
    return "".join(out).strip()


def raw_span(offsets: tuple, a: int, b: int) -> tuple[int, int]:
    """规范化字符区间 [a, b) → 原文区间。空区间（插入点）：在下一个规范化字符之前；在末尾则紧跟最后一个字符
    （即落在 w0 的句末标点之前）。"""
    if a < b:
        return offsets[a][0], offsets[b - 1][1]
    if a < len(offsets):
        return offsets[a][0], offsets[a][0]
    end = offsets[-1][1] if offsets else 0
    return end, end


def raw_hypothesis(raw_w: str, raw_x: str, interval: dict) -> str | None:
    """raw w0 单元文本中只把该区间的字符换成 x0 原文对应字符；规范化后必须等于 `compose` 的结果，否则 None。"""
    try:
        nw, nx = normalize(raw_w), normalize(raw_x)
        ws, we = raw_span(nw.raw_spans, interval["w_start"], interval["w_end"])
        replacement = ""
        if interval["x"]:
            xs, xe = raw_span(nx.raw_spans, interval["x_start"], interval["x_end"])
            replacement = raw_x[xs:xe]
        hypothesis = raw_w[:ws] + replacement + raw_w[we:]
        if normalize(hypothesis).text != o.compose(nw.text, [interval], ["x"]):
            return None
        return hypothesis
    except ValueError:
        return None


def unit_hypotheses(tracks: dict, unit: o.Unit) -> dict:
    """{"intervals", "raw": [hyp_w, hyp_x0, …], "norm": […], "raw_fallback": bool}；下标 k+1 为第 k 个区间。"""
    w0, x0 = unit.texts["w0"], unit.texts["x0"]
    intervals = o.disagreement_intervals(w0, x0)
    norm = [w0] + [c.hypothesis_x(w0, it) for it in intervals]
    raw_w = join_raw([tracks["w0"][i]["text"] for i in unit.ids["w0"]])
    raw_x = join_raw([tracks["x0"][i]["text"] for i in unit.ids["x0"]])
    raw = None
    try:
        consistent = normalize(raw_w).text == w0 and normalize(raw_x).text == x0
    except ValueError:
        consistent = False
    if consistent:
        raw = [raw_w] + [raw_hypothesis(raw_w, raw_x, it) for it in intervals]
        if any(h is None for h in raw):
            raw = None
    return {"intervals": intervals, "norm": norm, "raw": raw or norm, "raw_fallback": raw is None}


# ---------- GPU 公共部分 ----------

@contextmanager
def gpu_lock(job: str):
    c.GPU_LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        with c.GPU_LOCK.open("x", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "job": job, "created_at_utc": datetime.now(timezone.utc).isoformat()},
                      stream)
    except FileExistsError:
        raise SystemExit(f"{c.GPU_LOCK} exists; verify the owning process with Get-Process") from None
    try:
        yield
    finally:
        c.GPU_LOCK.unlink(missing_ok=True)


class VramSampler(threading.Thread):
    """每秒用 nvidia-smi 采样整卡已用显存（CT2 的显存 torch 统计不到）。"""

    def __init__(self, interval: float = 1.0):
        super().__init__(daemon=True)
        self.interval, self.peak, self.samples, self._stop = interval, 0, [], threading.Event()

    def run(self):
        while not self._stop.is_set():
            try:
                used = int(subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=10).stdout.split()[0])
                self.samples.append(used)
                self.peak = max(self.peak, used)
            except (OSError, ValueError, IndexError, subprocess.SubprocessError):
                pass
            self._stop.wait(self.interval)

    def stop(self) -> dict:
        self._stop.set()
        self.join(timeout=15)
        return {"peak_used_mib": self.peak, "first_used_mib": self.samples[0] if self.samples else None,
                "samples": len(self.samples)}


def load_inputs(film: str):
    """音频（PCM SHA 对照基线清单）、轨道、单元与跨度计划（与 MMS 实验的 index.json 逐项相同）。"""
    from kototoki.workers.gpu import read_wav

    audio, pcm = read_wav(c.FILM_AUDIO[film])
    if pcm != c.EXPECTED_PCM[film]:
        raise ValueError(f"{film}: PCM SHA {pcm} differs from baseline manifest")
    tracks, units = c.load_film(film)
    plan = c.plan_spans(tracks, units, len(audio))
    index = json.loads((c.EMISSIONS / "index.json").read_text(encoding="utf-8"))
    if index["meta"]["films"][film]["plan"] != plan:
        raise ValueError(f"{film}: span plan differs from the MMS experiment")
    return audio, pcm, tracks, units, plan


def score_jobs(tracks: dict, units: list[o.Unit], plan: dict, part: str) -> list[dict]:
    """[{unit_id, key, texts: {(form, index): text}}]；A：分歧单元的两种形式全部假设；B：有 w0 文本单元的 raw w0。"""
    jobs = []
    for unit in units:
        if part == "A" and unit.unit_id in plan["A"]:
            hyps = unit_hypotheses(tracks, unit)
            texts = {(form, k): text for form in FORMS for k, text in enumerate(hyps[form])}
            jobs.append({"unit_id": unit.unit_id, "key": plan["A"][unit.unit_id], "texts": texts,
                         "raw_fallback": hyps["raw_fallback"]})
        elif part == "B" and unit.unit_id in plan["B"]:
            raw_w = join_raw([tracks["w0"][i]["text"] for i in unit.ids["w0"]])
            text = raw_w if normalize(raw_w).text == unit.texts["w0"] else unit.texts["w0"]
            jobs.append({"unit_id": unit.unit_id, "key": plan["B"][unit.unit_id], "texts": {("raw", 0): text},
                         "raw_fallback": text != raw_w})
    return jobs


def run_scoring(engine: str, scorer, out_dir: Path) -> dict:
    """对两部、两部分逐单元打分并写 jsonl；scorer.score(audio, texts) → [{n_tokens, logprob, token_logprobs}]。"""
    import torch

    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {"engine": engine, "films": {}, "parts": {}}
    for part in ("A", "B"):
        rows_path = out_dir / f"{engine}-{part.lower()}.jsonl"
        started = time.perf_counter()
        counts = Counter()
        with rows_path.open("w", encoding="utf-8") as sink:
            for film in o.FILMS:
                audio, pcm, tracks, units, plan = load_inputs(film)
                meta["films"][film] = {"pcm_sha256": pcm, "pcm_matches_manifest": True, "samples": len(audio)}
                for job in score_jobs(tracks, units, plan, part):
                    first, last = (int(x) for x in job["key"].split("-"))
                    span = audio[first:last]
                    unique = sorted(set(job["texts"].values()))
                    if engine == "whisper" and len(span) > WHISPER_MAX_SAMPLES:
                        scores = {t: None for t in unique}
                        counts["skipped_units_over_30s"] += 1
                    else:
                        scores = dict(zip(unique, scorer.score(span, unique)))
                    counts["units"] += 1
                    counts["sequences"] += len(unique)
                    counts["seconds"] += len(span) / c.SAMPLE_RATE
                    for (form, k), text in sorted(job["texts"].items()):
                        result = scores[text]
                        sink.write(json.dumps({
                            "film": film, "part": part, "unit_id": job["unit_id"], "key": job["key"], "form": form,
                            "index": k, "text_sha": _sha(text), "chars": len(text),
                            "raw_fallback": job["raw_fallback"],
                            **(result if result else {"n_tokens": None, "logprob": None, "token_logprobs": None,
                                                      "skipped": "span over 30 s"})},
                            ensure_ascii=False) + "\n")
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        meta["parts"][part] = {**counts, "wall_s": time.perf_counter() - started, "rows_file": rows_path.name}
    return meta


def _sha(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def sanity_windows(engine: str, film: str) -> list[int]:
    doc = json.loads(ASR_JSON[engine][film].read_text(encoding="utf-8"))
    nonempty = [k for k, s in enumerate(doc["original_segments"]) if s["text"]]
    return sorted(random.Random(SANITY_SEED).sample(nonempty, SANITY_WINDOWS))


def shuffled(text: str, seed: int) -> str:
    chars = list(text)
    random.Random(seed).shuffle(chars)
    return "".join(chars)


# ---------- Whisper ----------

class WhisperScorer:
    """产品 `WhisperAsr` 的模型句柄上做 `align()` 教师强制（只读访问其私有属性 `_model`、`_filters`）。"""

    def __init__(self):
        from kototoki import asr_whisper as aw  # 先 torch 再 ctranslate2 再 faster_whisper（模块内保证）
        from kototoki.recipes import W0

        self.aw = aw
        self.asr = aw.WhisperAsr(WHISPER_DIR, MEL_DIR)
        self.model, self.filters = self.asr._model, self.asr._filters
        self.tokenizer = aw.Tokenizer(self.model.hf_tokenizer, self.model.model.is_multilingual,
                                      task=W0["task"], language=W0["language"])
        self.sot = list(self.tokenizer.sot_sequence)
        # 产品生成提示（无时间戳、无 initial prompt）；align 内部在 sot_sequence 后自动补 <|notimestamps|>
        self.product_prompt = self.model.get_prompt(self.tokenizer, [], without_timestamps=True, prefix=None,
                                                    hotwords=None)

    def encode_text(self, text: str) -> list[int]:
        return self.tokenizer.encode(text) if text else []

    def _align(self, audio, token_lists: list[list[int]], start_sequence=None) -> list[list[float]]:
        import numpy as np
        import torch

        mel = self.aw.features(audio, self.filters)
        encoded = self.model.encode(mel)
        base = torch.as_tensor(encoded, device="cuda")
        out: list[list[float]] = [[] for _ in token_lists]
        todo = [k for k, toks in enumerate(token_lists) if toks]
        num_frames = min(mel.shape[-1], -(-len(audio) // 160))
        for start in range(0, len(todo), 16):
            chunk = todo[start:start + 16]
            batch = base.expand(len(chunk), *base.shape[1:]).contiguous()
            view = self.aw.ctranslate2.StorageView.from_array(batch)
            results = self.model.model.align(view, start_sequence or self.sot, [token_lists[k] for k in chunk],
                                             [num_frames] * len(chunk))
            for k, result in zip(chunk, results):
                probs = np.asarray(result.text_token_probs, dtype=np.float64)
                if len(probs) != len(token_lists[k]):
                    raise RuntimeError("text_token_probs length differs from text tokens")
                out[k] = np.log(np.maximum(probs, 1e-45)).tolist()
            del view, batch
        return out

    def score(self, audio, texts: list[str]) -> list[dict]:
        token_lists = [self.encode_text(t) for t in texts]
        logprobs = self._align(audio, token_lists)
        return [{"n_tokens": len(toks), "logprob": float(sum(lp)), "token_logprobs": [round(x, 5) for x in lp]}
                for toks, lp in zip(token_lists, logprobs)]

    def sanity(self) -> dict:
        """产品窗口上：重新编码＝产品 token；sot 与产品提示两种 start_sequence；与产品 avg_logprob 对照；
        打乱文字的分数应远低。"""
        from kototoki.workers.gpu import read_wav

        report = []
        for film in o.FILMS:
            audio, _ = read_wav(c.FILM_AUDIO[film])
            doc = json.loads(ASR_JSON["w0"][film].read_text(encoding="utf-8"))
            for k in sanity_windows("w0", film):
                segment, trace = doc["original_segments"][k], doc["asr_traces"][k]
                span = audio[trace["start_sample"]:trace["end_sample"]]
                product = [t for t in trace["tokens"] if t < self.tokenizer.eot]
                text = segment["text"]
                own = self.encode_text(text)
                mixed = self.encode_text(shuffled(text, k))
                [lp_own, lp_mixed] = self._align(span, [own, mixed])
                [lp_prompt] = self._align(span, [own], start_sequence=self.product_prompt)
                length = len(trace["tokens"])
                report.append({
                    "film": film, "window": k, "tokens": len(own), "reencode_equals_product": own == product,
                    "prompt_equals_product": list(trace["prompt"]) == list(self.product_prompt),
                    "sum_logprob_sot": sum(lp_own), "sum_logprob_product_prompt_doubled_notimestamps": sum(lp_prompt),
                    "product_cum_logprob": segment["avg_logprob"] * (length + 1),
                    "sum_logprob_shuffled": sum(lp_mixed), "min_token_prob_own": math.exp(min(lp_own))})
        return {"windows": report, "sot_sequence": self.sot, "product_prompt": list(self.product_prompt)}


# ---------- Qwen ----------

class QwenScorer:
    """产品 `QwenAsr` 的 processor 与模型（只读访问私有属性 `_processor`、`_model`）上做单次前向教师强制。"""

    def __init__(self):
        import torch
        from kototoki.asr_qwen import QwenAsr

        self.torch = torch
        self.asr = QwenAsr(QWEN_DIR)
        self.processor, self.model = self.asr._processor, self.asr._model
        self.tokenizer = self.processor.tokenizer
        self.end = self.tokenizer.convert_tokens_to_ids("<|im_end|>")

    def inputs(self, audio):
        from kototoki.recipes import SAMPLE_RATE, X0

        return self.processor.apply_transcription_request(
            audio=audio, language=X0["language"],
            processor_kwargs={"audio_kwargs": {"sampling_rate": SAMPLE_RATE}}).to("cuda", self.torch.bfloat16)

    def target(self, text: str) -> list[int]:
        return (self.tokenizer.encode(text, add_special_tokens=False) if text else []) + [self.end]

    def forward(self, inputs, target: list[int]) -> tuple[list[float], float]:
        torch = self.torch
        tail = torch.tensor([target], device="cuda")
        ids = torch.cat([inputs["input_ids"], tail], dim=1)
        with torch.inference_mode():
            logits = self.model(input_ids=ids, attention_mask=torch.ones_like(ids),
                                input_features=inputs["input_features"],
                                input_features_mask=inputs["input_features_mask"],
                                logits_to_keep=len(target) + 1).logits[0, :-1].float()
        logprobs = logits.log_softmax(dim=-1)
        picked = logprobs.gather(1, tail[0][:, None])[:, 0]
        argmax_match = (logprobs.argmax(dim=-1) == tail[0]).float().mean().item()
        return picked.cpu().tolist(), argmax_match

    def score(self, audio, texts: list[str]) -> list[dict]:
        inputs = self.inputs(audio)
        out = []
        for text in texts:
            target = self.target(text)
            lp, _ = self.forward(inputs, target)
            out.append({"n_tokens": len(target), "logprob": float(sum(lp)), "end_logprob": lp[-1],
                        "token_logprobs": [round(x, 5) for x in lp]})
        return out

    def sanity(self) -> dict:
        """产品窗口上：重新编码＝产品 token；教师强制产品 greedy 输出时逐位 argmax 是否等于该 token；打乱更低。"""
        from kototoki.workers.gpu import read_wav

        report = []
        for film in o.FILMS:
            audio, _ = read_wav(c.FILM_AUDIO[film])
            doc = json.loads(ASR_JSON["x0"][film].read_text(encoding="utf-8"))
            for k in sanity_windows("x0", film):
                segment, trace = doc["original_segments"][k], doc["asr_traces"][k]
                span = audio[trace["start_sample"]:trace["end_sample"]]
                inputs = self.inputs(span)
                prompt_tail = self.tokenizer.decode(inputs["input_ids"][0][-6:])
                own = self.target(segment["text"])
                lp_own, match = self.forward(inputs, list(trace["tokens"]))
                lp_mixed, _ = self.forward(inputs, self.target(shuffled(segment["text"], k)))
                lp_empty, _ = self.forward(inputs, [self.end])
                report.append({
                    "film": film, "window": k, "tokens": len(own), "reencode_equals_product": own == trace["tokens"],
                    "raw_asr_ends_with_im_end": trace["raw_asr"].endswith("<|im_end|>"),
                    "prompt_tail": prompt_tail, "argmax_match_product_tokens": match,
                    "sum_logprob_own": sum(lp_own), "end_logprob_own": lp_own[-1],
                    "sum_logprob_shuffled": sum(lp_mixed), "sum_logprob_empty": sum(lp_empty)})
        return {"windows": report, "end_token": self.end}


def score_engine(engine: str, out_dir: Path) -> dict:
    import torch

    os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    with gpu_lock(f"experiments.quality_v5.asr_pair_cross_score score-{engine}"):
        sampler = VramSampler()
        sampler.start()
        started = time.perf_counter()
        scorer = WhisperScorer() if engine == "whisper" else QwenScorer()
        load_s = time.perf_counter() - started
        torch.cuda.reset_peak_memory_stats()
        mark = time.perf_counter()
        sanity = scorer.sanity()
        sanity_s = time.perf_counter() - mark
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{engine}-sanity.json").write_text(json.dumps(sanity, ensure_ascii=False, indent=1),
                                                        encoding="utf-8")
        meta = run_scoring(engine, scorer, out_dir)
        meta.update(load_s=load_s, sanity_s=sanity_s, total_wall_s=time.perf_counter() - started,
                    metadata={k: v for k, v in scorer.asr.metadata.items() if k != "generation_config"},
                    torch_max_allocated_mib=torch.cuda.max_memory_allocated() / 2 ** 20,
                    torch_max_reserved_mib=torch.cuda.max_memory_reserved() / 2 ** 20,
                    device=torch.cuda.get_device_name(0), vram=sampler.stop())
        (out_dir / f"{engine}-meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str),
                                                      encoding="utf-8")
        return meta


# ---------- 判定、组合与调参（纯函数，可用合成数据测试） ----------

def combine(signals: dict[str, list[float]], weights: dict[str, float]):
    """加权和（numpy 数组）；缺失（NaN）的分量记 0，全部缺失时为 NaN（保持 w0）。"""
    import numpy as np

    stack = np.array([[math.nan if v is None else v for v in signals[name]] for name in weights], dtype=float)
    w = np.array([weights[name] for name in weights], dtype=float)[:, None]
    present = ~np.isnan(stack)
    total = np.where(present, stack * w, 0.0).sum(axis=0)
    return np.where(present.any(axis=0), total, math.nan)


def linear_choose(values, dlen, lam: float, margin: float):
    """取 x0 当且仅当 v > m + λ·Δlen；NaN 保持 w0（numpy 比较对 NaN 为 False）。返回 bool 数组。"""
    import numpy as np

    return np.asarray(values, dtype=float) > margin + lam * np.asarray(dlen, dtype=float)


def agree_choose(d_w, d_q, dlen, lam: float, m_w: float, m_q: float):
    """两模型都同意才取 x0：d_W > m_W + λ·Δlen 且 d_Q > m_Q + λ·Δlen；任一缺失保持 w0。"""
    return linear_choose(d_w, dlen, lam, m_w) & linear_choose(d_q, dlen, lam, m_q)


def tune_grid(evaluators: list, candidates) -> dict:
    """candidates: 可迭代的 (params, [每片的 choose])；最小化各片总编辑量之和；
    平局依次取改动更少、Σ|参数| 更小者。"""
    best = None
    for params, chooses in candidates:
        edit_count = sum(o.edits(ev.total(ch)) for ev, ch in zip(evaluators, chooses))
        changes = int(sum(ch.sum() for ch in chooses))
        key = (edit_count, changes, sum(abs(v) for v in params.values()))
        if best is None or key < best[0]:
            best = (key, params)
    (edit_count, changes, _), params = best
    return {"params": params, "edits": edit_count, "changes": changes}


def on_edge(params: dict, grids: dict) -> bool:
    return any(len(grids[k]) > 1 and v in (grids[k][0], grids[k][-1]) for k, v in params.items() if k in grids)


class Judge:
    """裁判规格：linear（weights 中的信号加权和，可选调 MMS 权重）或 agree（两模型都同意）。"""

    def __init__(self, name: str, rule: str, weights: dict | None = None, use_length: bool = True,
                 tune_mms_weight: bool = False, lambdas=None, margins=None):
        self.name, self.rule, self.weights, self.use_length = name, rule, weights or {}, use_length
        self.tune_mms_weight = tune_mms_weight
        if rule == "agree":
            self.grids = {"lambda": (lambdas or AGREE_LAMBDAS) if use_length else [0.0],
                          "m_w": margins or AGREE_MARGINS, "m_q": margins or AGREE_MARGINS}
        else:
            self.grids = {"lambda": (lambdas or LAMBDAS) if use_length else [0.0], "margin": margins or MARGINS}
            if tune_mms_weight:
                self.grids["w_mms"] = list(MMS_WEIGHTS)

    def values(self, rows: list[dict], w_mms: float | None = None) -> list[float]:
        weights = dict(self.weights)
        if w_mms is not None:
            weights["d_M"] = w_mms
        return combine({name: [r[name] for r in rows] for name in weights}, weights)

    def choose(self, rows: list[dict], params: dict, cached_values=None):
        """bool 数组（与 rows 对齐）。"""
        dlen = [r["dlen"] for r in rows]
        if self.rule == "agree":
            return agree_choose([r["d_W"] for r in rows], [r["d_Q"] for r in rows], dlen, params["lambda"],
                                params["m_w"], params["m_q"])
        values = cached_values if cached_values is not None else self.values(rows, params.get("w_mms"))
        return linear_choose(values, dlen, params["lambda"], params["margin"])

    def candidates(self, film_rows: list[list[dict]]):
        if self.rule == "agree":
            arrays = [([r["d_W"] for r in rows], [r["d_Q"] for r in rows], [r["dlen"] for r in rows])
                      for rows in film_rows]
            for lam, m_w, m_q in itertools.product(self.grids["lambda"], self.grids["m_w"], self.grids["m_q"]):
                params = {"lambda": lam, "m_w": m_w, "m_q": m_q}
                yield params, [agree_choose(a, b, d, lam, m_w, m_q) for a, b, d in arrays]
            return
        for w_mms in self.grids.get("w_mms", [None]):
            cached = [self.values(rows, w_mms) for rows in film_rows]
            for lam, margin in itertools.product(self.grids["lambda"], self.grids["margin"]):
                params = {"lambda": lam, "margin": margin} | ({"w_mms": w_mms} if w_mms is not None else {})
                yield params, [self.choose(rows, params, v) for rows, v in zip(film_rows, cached)]


# ---------- 统计 ----------

def pearson(xs: list[float], ys: list[float]) -> float | None:
    pairs = [(x, y) for x, y in zip(xs, ys) if math.isfinite(x) and math.isfinite(y)]
    if len(pairs) < 3:
        return None
    mx = sum(x for x, _ in pairs) / len(pairs)
    my = sum(y for _, y in pairs) / len(pairs)
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    syy = sum((y - my) ** 2 for _, y in pairs)
    return sxy / math.sqrt(sxx * syy) if sxx and syy else None


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda k: values[k])
    out = [0.0] * len(values)
    k = 0
    while k < len(order):
        j = k
        while j + 1 < len(order) and values[order[j + 1]] == values[order[k]]:
            j += 1
        for t in range(k, j + 1):
            out[order[t]] = (k + j) / 2
        k = j + 1
    return out


def spearman(xs: list[float], ys: list[float]) -> float | None:
    pairs = [(x, y) for x, y in zip(xs, ys) if math.isfinite(x) and math.isfinite(y)]
    if len(pairs) < 3:
        return None
    return pearson(ranks([x for x, _ in pairs]), ranks([y for _, y in pairs]))


def auc_higher_is_x(rows: list[dict], value) -> dict:
    """在 marginal ≠ 0 的区间上，"x0 更好"（marginal < 0）相对"w0 更好"的 AUC；分数越高越偏 x0；NaN 排除。"""
    valid = [r for r in rows if r["marginal"] != 0 and math.isfinite(value(r))]
    positive = [-value(r) for r in valid if r["marginal"] < 0]
    negative = [-value(r) for r in valid if r["marginal"] > 0]
    return {"n": len(valid), "n_x_better": len(positive), "auc": c.auc_lower_is_positive(positive, negative)}


def preference(rows: list[dict], signal: str, own_sign: int) -> dict:
    """某模型的偏好方向：own_sign＝−1 表示 d < 0 偏向自己（Whisper，自己＝w0），+1 表示 d > 0 偏向自己（Qwen）。
    按 oracle 标签（marginal < 0：x0 更好；> 0：w0 更好；= 0：两者等价）分组统计偏自己／偏对方／平。"""
    out = {}
    for label, test in (("x0_better", lambda m: m < 0), ("w0_better", lambda m: m > 0),
                        ("equivalent", lambda m: m == 0)):
        cell = Counter()
        for r in rows:
            d = r[signal]
            if not test(r["marginal"]) or d is None or math.isnan(d):
                continue
            cell["n"] += 1
            cell["own"] += own_sign * d > 0
            cell["other"] += own_sign * d < 0
            cell["tie"] += d == 0
        cell = dict(cell)
        if cell.get("n"):
            cell["own_share"] = cell.get("own", 0) / cell["n"]
            cell["other_share"] = cell.get("other", 0) / cell["n"]
        out[label] = cell
    return out


# ---------- 分析（CPU） ----------

def read_scores(out_dir: Path, engine: str, part: str) -> dict:
    path = out_dir / f"{engine}-{part.lower()}.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return {(r["film"], r["unit_id"], r["form"], r["index"]): r for r in rows}


def read_mms() -> dict:
    path = c.OUT / "scores-a.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return {(r["film"], r["unit_id"], r["interval"]): r for r in rows}


def _logprob(scores: dict, key) -> float:
    value = scores[key]["logprob"]
    return math.nan if value is None else value


def build_rows(film: str, tracks: dict, units: list[o.Unit], whisper: dict, qwen: dict, mms: dict,
               labeled: dict) -> list[dict]:
    oracle = {(r["unit_id"], r["interval"]): r for r in c.read_oracle_intervals() if r["film"] == film}
    rows = []
    for unit in units:
        hyps = unit_hypotheses(tracks, unit)
        for k, it in enumerate(hyps["intervals"]):
            reference = oracle[(unit.unit_id, k)]
            if (reference["w"], reference["x"]) != (it["w"], it["x"]):
                raise AssertionError(f"rebuilt interval differs from intervals.jsonl: {unit.unit_id}#{k}")
            m = mms[(film, unit.unit_id, k)]
            if (m["w"], m["x"]) != (it["w"], it["x"]):
                raise AssertionError(f"MMS cache differs: {unit.unit_id}#{k}")
            row = {"film": film, "unit_id": unit.unit_id, "interval": k, "w": it["w"], "x": it["x"],
                   "kind": reference["kind"], "position": reference["position"], "status": reference["status"],
                   "length": c.length_bucket(it), "oracle_pick": reference["oracle_pick"],
                   "dlen": len(it["x"]) - len(it["w"]), "raw_fallback": hyps["raw_fallback"],
                   "same_kana": c.same_kana_reading(it["w"], it["x"]),
                   "d_M": m["d"] if m["scorable"] else math.nan, "mms_scorable": m["scorable"],
                   "mms_judge_x0": m["judge_x0"], "_interval": it}
            for form, suffix in (("raw", ""), ("norm", "_norm")):
                for name, scores in (("W", whisper), ("Q", qwen)):
                    sw = _logprob(scores, (film, unit.unit_id, form, 0))
                    sx = _logprob(scores, (film, unit.unit_id, form, k + 1))
                    row[f"s{name}w{suffix}"], row[f"s{name}x{suffix}"] = sw, sx
                    row[f"d_{name}{suffix}"] = sx - sw
            row["q_end_w"] = qwen[(film, unit.unit_id, "raw", 0)].get("end_logprob")
            row["q_end_x"] = qwen[(film, unit.unit_id, "raw", k + 1)].get("end_logprob")
            sample = labeled.get((film, unit.unit_id, k))
            row["label"] = sample["label"] if sample else None
            row["orthographic_only"] = sample["orthographic_only"] if sample else None
            rows.append(row)
    return rows


def judges() -> list[Judge]:
    out = []
    for use_length, tag in ((True, ""), (False, "（无长度项）")):
        out += [
            Judge("Whisper" + tag, "linear", {"d_W": 1.0}, use_length),
            Judge("Qwen" + tag, "linear", {"d_Q": 1.0}, use_length),
            Judge("Whisper＋Qwen" + tag, "linear", {"d_W": 1.0, "d_Q": 1.0}, use_length),
            Judge("两者都同意" + tag, "agree", use_length=use_length),
            Judge("Whisper＋Qwen＋w·MMS" + tag, "linear", {"d_W": 1.0, "d_Q": 1.0}, use_length,
                  tune_mms_weight=True),
            Judge("MMS（复算）" + tag, "linear", {"d_M": 1.0}, use_length, lambdas=c.LAMBDAS, margins=c.MARGINS),
            Judge("Whisper（norm 文本）" + tag, "linear", {"d_W_norm": 1.0}, use_length),
            Judge("Qwen（norm 文本）" + tag, "linear", {"d_Q_norm": 1.0}, use_length),
            Judge("Whisper＋Qwen（norm 文本）" + tag, "linear", {"d_W_norm": 1.0, "d_Q_norm": 1.0}, use_length),
        ]
    return out


def judge_signal(judge: Judge, params: dict):
    """AUC 用的连续分数：线性裁判为 v − λ·Δlen；agree 为 min(d_W − m_W, d_Q − m_Q) − λ·Δlen。"""
    if judge.rule == "agree":
        return lambda r: min(r["d_W"] - params["m_w"], r["d_Q"] - params["m_q"]) - params["lambda"] * r["dlen"]
    weights = dict(judge.weights) | ({"d_M": params["w_mms"]} if "w_mms" in params else {})

    def value(r):
        present = [(w, r[n]) for n, w in weights.items() if not math.isnan(r[n])]
        return (sum(w * v for w, v in present) if present else math.nan) - params["lambda"] * r["dlen"]
    return value


def analyze(out_dir: Path) -> dict:
    whisper, qwen = read_scores(out_dir, "whisper", "A"), read_scores(out_dir, "qwen", "A")
    mms, labeled = read_mms(), c.read_labeled()
    films = list(o.FILMS)
    other = {films[0]: films[1], films[1]: films[0]}
    data = {}
    for film in films:
        tracks, units = c.load_film(film)
        rows = build_rows(film, tracks, units, whisper, qwen, mms, labeled)
        evaluator = c.FilmEvaluator(units, rows)
        for k, row in enumerate(rows):
            row["marginal"] = evaluator.marginal(k)
            if row["marginal"] != mms[(film, row["unit_id"], row["interval"])]["marginal"]:
                raise AssertionError("marginal differs from the MMS experiment")
        oracle = o.analyze_film(film, units)
        oracle.pop("_intervals")
        data[film] = {"tracks": tracks, "units": units, "rows": rows, "evaluator": evaluator, "oracle": oracle}
    pooled = [r for f in films for r in data[f]["rows"]]
    total_ref = sum(data[f]["evaluator"].ref_chars for f in films)
    report: dict = {"counts": {
        "intervals": len(pooled), "raw_fallback_intervals": sum(r["raw_fallback"] for r in pooled),
        "whisper_missing": sum(math.isnan(r["d_W"]) for r in pooled),
        "qwen_missing": sum(math.isnan(r["d_Q"]) for r in pooled),
        "mms_missing": sum(math.isnan(r["d_M"]) for r in pooled),
        "d_W_zero": sum(r["d_W"] == 0 for r in pooled), "d_Q_zero": sum(r["d_Q"] == 0 for r in pooled),
        "indifferent_marginal": sum(r["marginal"] == 0 for r in pooled)}, "judges": {}}

    def cer(film, choose):
        return o.cer_row(data[film]["evaluator"].total(choose), data[film]["evaluator"].ref_chars)

    baseline = {f: {"w0": cer(f, [False] * len(data[f]["rows"])), "oracle_splice": data[f]["oracle"]["cer"]["splice"],
                    "oracle_select": data[f]["oracle"]["cer"]["select"], "x0": data[f]["oracle"]["cer"]["x0"]}
                for f in films}
    for f in films:
        if baseline[f]["w0"]["edits"] != data[f]["oracle"]["cer"]["w0"]["edits"]:
            raise AssertionError("w0 edits differ from oracle script")
    baseline["total"] = {name: o.cer_row({k: sum(baseline[f][name][k] for f in films) for k in "SDI"}, total_ref)
                         for name in baseline[films[0]]}
    report["baseline"] = baseline

    for judge in judges():
        started = time.perf_counter()
        evaluators = {f: data[f]["evaluator"] for f in films}
        tuned = {f: tune_grid([evaluators[f]], judge.candidates([data[f]["rows"]])) for f in films}
        pooled_best = tune_grid([evaluators[f] for f in films], judge.candidates([data[f]["rows"] for f in films]))
        choices, cer_rows = {}, {}
        for film in films:
            rows = data[film]["rows"]
            cross = tuned[other[film]]["params"]
            choices[film] = judge.choose(rows, cross).tolist()
            cer_rows[film] = {"cross": cer(film, choices[film]),
                              "insample": cer(film, judge.choose(rows, tuned[film]["params"])),
                              "pooled_params": cer(film, judge.choose(rows, pooled_best["params"]))}
        cer_rows["total"] = {name: o.cer_row({k: sum(cer_rows[f][name][k] for f in films) for k in "SDI"}, total_ref)
                             for name in cer_rows[films[0]]}
        all_choose = [x for f in films for x in choices[f]]
        entry = {
            "rule": judge.rule, "weights": judge.weights, "use_length": judge.use_length,
            "grids": {k: [v[0], v[-1], len(v)] for k, v in judge.grids.items()},
            "tuned": {f: tuned[f] | {"on_grid_edge": on_edge(tuned[f]["params"], judge.grids)} for f in films},
            "pooled": pooled_best | {"on_grid_edge": on_edge(pooled_best["params"], judge.grids)},
            "cer": cer_rows,
            "accuracy": {
                "overall": c.accuracy_table(pooled, all_choose, lambda r: "all"),
                "film": c.accuracy_table(pooled, all_choose, lambda r: r["film"]),
                "kind": c.accuracy_table(pooled, all_choose, lambda r: r["kind"]),
                "position": c.accuracy_table(pooled, all_choose, lambda r: r["position"]),
                "length": c.accuracy_table(pooled, all_choose, lambda r: r["length"]),
                "decisive": c.accuracy_table(pooled, all_choose,
                                             lambda r: "marginal≠0" if r["marginal"] != 0 else "marginal=0"),
                "labeled": c.accuracy_table([r for r in pooled if r["label"]],
                                            [x for r, x in zip(pooled, all_choose) if r["label"]],
                                            lambda r: r["label"] + ("（表记）" if r["orthographic_only"] else "")),
                "labeled_orthographic": c.accuracy_table(
                    [r for r in pooled if r["label"]], [x for r, x in zip(pooled, all_choose) if r["label"]],
                    lambda r: "表记" if r["orthographic_only"] else "非表记")},
            "changes": {"all": c.change_breakdown(pooled, all_choose),
                        **{f"kind:{kind}": c.change_breakdown(
                            [r for r in pooled if r["kind"] == kind],
                            [x for r, x in zip(pooled, all_choose) if r["kind"] == kind])
                           for kind in ("替换", "w0 多出", "x0 多出")}},
            "tune_s": time.perf_counter() - started}
        # 跨片取法下的 AUC（分数用调参片的参数）
        auc = {}
        for film in films:
            value = judge_signal(judge, tuned[other[film]]["params"])
            rows = data[film]["rows"]
            auc[film] = {"all": auc_higher_is_x(rows, value),
                         **{f"kind:{kind}": auc_higher_is_x([r for r in rows if r["kind"] == kind], value)
                            for kind in ("替换", "w0 多出", "x0 多出")}}
        entry["auc"] = auc
        entry["labeled_rows"] = [{k: r[k] for k in ("film", "unit_id", "interval", "w", "x", "label",
                                                    "orthographic_only", "oracle_pick", "marginal", "d_W", "d_Q",
                                                    "d_M", "dlen")} | {"judge_x0": x}
                                 for r, x in zip(pooled, all_choose) if r["label"]]
        report["judges"][judge.name] = entry
        if judge.name == "Whisper＋Qwen":
            for r, x in zip(pooled, all_choose):
                r["sum_judge_x0"] = x
        print(f"{judge.name}: total {cer_rows['total']['cross']['CER']:.4f} "
              f"params {[tuned[f]['params'] for f in films]} ({entry['tune_s']:.0f} s)", flush=True)

    # ---- 原始信号的判别力（不调参） ----
    signals = {"d_W": lambda r: r["d_W"], "d_Q": lambda r: r["d_Q"], "d_W+d_Q": lambda r: r["d_W"] + r["d_Q"],
               "d_M": lambda r: r["d_M"], "d_W_norm": lambda r: r["d_W_norm"], "d_Q_norm": lambda r: r["d_Q_norm"],
               "d_W+d_Q+d_M": lambda r: r["d_W"] + r["d_Q"] + (0.0 if math.isnan(r["d_M"]) else r["d_M"])}
    decisive_sub = [r for r in pooled if r["kind"] == "替换"]
    kana = [r for r in decisive_sub if c.is_kana(r["w"]) and c.is_kana(r["x"]) and not r["same_kana"]]
    kanji = [r for r in decisive_sub if not (c.is_kana(r["w"]) and c.is_kana(r["x"]))]
    same_len = [r for r in decisive_sub if r["dlen"] == 0]
    raw_auc = {}
    for name, value in signals.items():
        raw_auc[name] = {
            "all": auc_higher_is_x(pooled, value),
            **{f"kind:{kind}": auc_higher_is_x([r for r in pooled if r["kind"] == kind], value)
               for kind in ("替换", "w0 多出", "x0 多出")},
            **{f"sub:{film}": auc_higher_is_x([r for r in decisive_sub if r["film"] == film], value)
               for film in films},
            "sub:kana_only": auc_higher_is_x(kana, value), "sub:with_kanji": auc_higher_is_x(kanji, value),
            "sub:same_length": auc_higher_is_x(same_len, value)}
    report["raw_auc"] = raw_auc

    # ---- 自偏好 ----
    pref = {}
    for scope, rows in (("all", pooled), *((f"kind:{k}", [r for r in pooled if r["kind"] == k])
                                           for k in ("替换", "w0 多出", "x0 多出")),
                        ("sub:same_length", same_len)):
        pref[scope] = {"whisper": preference(rows, "d_W", -1), "qwen": preference(rows, "d_Q", +1),
                       "mms_toward_x0": preference(rows, "d_M", +1)}
    report["preference"] = pref

    # ---- 相关性 ----
    corr = {}
    for scope, rows in (("all", pooled), *((f"kind:{k}", [r for r in pooled if r["kind"] == k])
                                           for k in ("替换", "w0 多出", "x0 多出"))):
        corr[scope] = {"pearson_W_Q": pearson([r["d_W"] for r in rows], [r["d_Q"] for r in rows]),
                       "spearman_W_Q": spearman([r["d_W"] for r in rows], [r["d_Q"] for r in rows]),
                       "spearman_W_M": spearman([r["d_W"] for r in rows], [r["d_M"] for r in rows]),
                       "spearman_Q_M": spearman([r["d_Q"] for r in rows], [r["d_M"] for r in rows]),
                       "sign_agree_W_Q": sum((r["d_W"] > 0) == (r["d_Q"] > 0) for r in rows
                                             if math.isfinite(r["d_W"]) and math.isfinite(r["d_Q"])) /
                       max(1, sum(math.isfinite(r["d_W"]) and math.isfinite(r["d_Q"]) for r in rows)),
                       "n": len(rows)}
    report["correlation"] = corr
    report["raw_vs_norm"] = {"spearman_W": spearman([r["d_W"] for r in pooled], [r["d_W_norm"] for r in pooled]),
                             "spearman_Q": spearman([r["d_Q"] for r in pooled], [r["d_Q_norm"] for r in pooled])}

    # ---- Part B：幻觉角度（可选，有分数才做） ----
    if (out_dir / "whisper-b.jsonl").exists() and (out_dir / "qwen-b.jsonl").exists():
        report["part_b"] = part_b(out_dir, data, films, other, total_ref)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "scores-a.jsonl").write_text("".join(
        json.dumps({k: v for k, v in r.items() if k != "_interval"}, ensure_ascii=False) + "\n" for r in pooled),
        encoding="utf-8")
    (out_dir / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str),
                                          encoding="utf-8")
    return report


def part_b(out_dir: Path, data: dict, films: list[str], other: dict, total_ref: int) -> dict:
    whisper, qwen = read_scores(out_dir, "whisper", "B"), read_scores(out_dir, "qwen", "B")
    mms_b = {(r["film"], r["unit_id"]): r for r in (json.loads(line) for line in
             (c.OUT / "scores-b.jsonl").read_text(encoding="utf-8").splitlines() if line)}
    items = {f: [] for f in films}
    for film in films:
        for unit in data[film]["units"]:
            w0, ref = unit.texts["w0"], unit.texts["ref"]
            if not w0:
                continue
            sw = whisper[(film, unit.unit_id, "raw", 0)]["logprob"]
            sq = qwen[(film, unit.unit_id, "raw", 0)]["logprob"]
            keep, drop = c.drop_edits(ref, w0)
            items[film].append({
                "film": film, "unit_id": unit.unit_id, "chars": len(w0), "ref": ref,
                "label": "insertion" if not ref else "exact" if ref == w0 else "other",
                "whisper_per_char": math.nan if sw is None else sw / len(w0), "qwen_per_char": sq / len(w0),
                "whisper_total": math.nan if sw is None else sw, "qwen_total": sq,
                "mms_viterbi_per_char": mms_b[(film, unit.unit_id)]["viterbi_per_char"],
                "keep": keep, "drop": drop})
    features = ("whisper_per_char", "qwen_per_char", "whisper_total", "qwen_total", "mms_viterbi_per_char")
    pooled = [it for f in films for it in items[f]]
    out = {"counts": dict(Counter(it["label"] for it in pooled)),
           "whisper_missing": sum(math.isnan(it["whisper_per_char"]) for it in pooled), "auc": {}, "cross": {}}
    for feature in features:
        row = {}
        for scope, scoped in (("pooled", pooled), *((f, items[f]) for f in films)):
            valid = [it for it in scoped if not math.isnan(it[feature])]
            row[scope] = c.auc_lower_is_positive([it[feature] for it in valid if it["label"] == "insertion"],
                                                 [it[feature] for it in valid if it["label"] == "exact"])
        out["auc"][feature] = row
    for it in pooled:
        for feature in features:
            if math.isnan(it[feature]):
                it[feature] = math.inf
    for feature in features:
        total = o.new_total()
        entry = {}
        for film in films:
            threshold = c.tune_drop_threshold(items[other[film]], feature)["threshold"]
            applied = c.apply_drop(items[film], feature, threshold)
            rest = o.new_total()
            for unit in data[film]["units"]:
                if not unit.texts["w0"]:
                    o.add(rest, o.sdi(unit.texts["ref"], ""))
            film_total = {k: applied["sdi"][k] + rest[k] for k in "SDI"}
            o.add(total, film_total)
            entry[film] = {"threshold": threshold, **{k: v for k, v in applied.items() if k != "sdi"},
                           "cer": o.cer_row(film_total, data[film]["evaluator"].ref_chars)}
        entry["total"] = o.cer_row(total, total_ref)
        out["cross"][feature] = entry
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="w0／x0 交叉打分裁判（Whisper align／Qwen 教师强制）")
    parser.add_argument("command", choices=("score-whisper", "score-qwen", "analyze"))
    parser.add_argument("--out-dir", type=Path, default=OUT)
    args = parser.parse_args()
    if args.command in ("score-whisper", "score-qwen"):
        meta = score_engine(args.command.split("-")[1], args.out_dir)
        print(json.dumps({k: v for k, v in meta.items() if k != "metadata"}, default=str)[:3000])
        return 0
    report = analyze(args.out_dir)
    print(json.dumps(report["baseline"]["total"], default=str)[:600])
    for name, entry in report["judges"].items():
        print(name, round(entry["cer"]["total"]["cross"]["CER"], 4), entry["accuracy"]["overall"]["all"]["accuracy"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
