"""MMS CTC 作为声学裁判：w0／x0 分歧区间二选一（Part A），以及 w0 单路的幻觉过滤（Part B）。

单元、规范化、字符对齐与分歧区间全部复用 `asr_pair_oracle`（同一单元口径）。GPU 只做一件事：产品 MMS
（`kototoki.align.MmsAligner`，mms-1b-all `jpn`，CUDA FP32）对每个音频跨度做一次前向，缓存 log_softmax
发射矩阵；之后的打分、判定与调参都在 CPU 上离线完成。不加载 Whisper／Qwen，不调用产品 worker。

跨度：
  A  有分歧区间的单元：该单元 w0∪x0 cue 的时间并集，两端各 PAD 秒，夹到音频范围内（不用参考 cue 的时间）。
  B  有 w0 文本的单元：该单元 w0 cue 的时间并集，同样加 PAD（只用 w0 自己的信息）。
打分：CTC 前向对数似然 log p(text | emission)（`torch.nn.functional.ctc_loss`，reduction="none"，
  zero_infinity=False——帧数不够时记 −inf 并显式处理，而不是让 zero_infinity 把不可行的假设记成损失 0）。
  空文本＝全 blank 路径。词表外字符（OOV）不用产品的通配列（非 blank 最大值，等于白给概率），改用常数列
  log(1/2268)（均匀分布，每帧固定罚分）；Part A 中区间本身含 OOV 的直接排除（保持 w0）。
判定：score_x − score_w > m + λ·(len_x − len_w) 时取 x0，否则保持 w0；λ、m 网格搜索，跨片调参。

命令（仓库根目录）：
  python -X utf8 -m experiments.quality_v5.asr_pair_ctc_judge emit      # GPU：MMS 前向，持有 .local/gpu.lock
  python -X utf8 -m experiments.quality_v5.asr_pair_ctc_judge analyze   # CPU：打分、调参、汇总
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time
import wave

from . import asr_pair_oracle as o
from .asr_source import load_reference, read_srt

OUT = o.V5 / "asr-pair-ctc-judge"
EMISSIONS = OUT / "emissions"
MODEL_DIR = o.LOCAL / "models/mms-1b-all"
GPU_LOCK = o.LOCAL / "gpu.lock"
WORK = o.LOCAL / "bilingual-fullfilm-08/out-w0/.work"
FILM_AUDIO = {"hf-ii": WORK / "8d2f3e76dd0c/audio-16k.wav", "hf-iii": WORK / "fb2e0da74018/audio-16k.wav"}
# 转写所用产品运行的 asr.json（w0 的 Whisper avg_logprob 基线、PCM 身份）
FILM_ASR = {"hf-ii": o.V5 / "01/out-w0/.work/8d2f3e76dd0c/asr.json",
            "hf-iii": o.V5 / "01/out-w0/.work/fb2e0da74018/asr.json"}
# 基线语料清单 fullfilm-v1/corpus/manifest.json 的 pcm_sha256
EXPECTED_PCM = {"hf-ii": "ee4e2da3e0b335f3d3f9d0b0a0b5bb301562846195e5419716b3ed83d76d604f",
                "hf-iii": "e8e841fde3c0fd85e42804cd6a574f1bb08c89fcec254f51f3449638fccb3ab6"}
SAMPLE_RATE = 16000
PAD = 0.2
VOCAB_SIZE = 2268
BLANK = 0
PENALTY_ID = VOCAB_SIZE  # OOV 字符的目标列：常数 log(1/2268)，不是产品的"非 blank 最大值"通配列
OOV_LOGPROB = -math.log(VOCAB_SIZE)
LAMBDAS = [x / 4 for x in range(-48, 17)]  # −12 … 4，步长 0.25
MARGINS = [x / 2 for x in range(-20, 61)]  # −10 … 30，步长 0.5


# ---------- 数据：单元与跨度 ----------

def load_film(film: str, root: Path = Path(".")) -> tuple[dict, list[o.Unit]]:
    spec = o.FILMS[film]
    tracks = {"ref": load_reference(root / spec["reference"])}
    for engine in ("w0", "x0"):
        tracks[engine] = read_srt(root / o.V5 / f"01/out-{engine}/{spec['name']}.ja.srt")
    return tracks, o.build_units(film, tracks)


def span_samples(cues: list[dict], pad: float, total_samples: int) -> tuple[int, int]:
    """cue 时间并集两端加 pad，夹到 [0, total_samples]，取整到样本。"""
    start = max(0.0, min(c["start"] for c in cues) - pad)
    end = min(total_samples / SAMPLE_RATE, max(c["end"] for c in cues) + pad)
    return int(round(start * SAMPLE_RATE)), int(round(end * SAMPLE_RATE))


def span_key(span: tuple[int, int]) -> str:
    return f"{span[0]}-{span[1]}"


def plan_spans(tracks: dict, units: list[o.Unit], total_samples: int) -> dict[str, dict[str, str]]:
    """{"A": {unit_id: key}, "B": {unit_id: key}}；相同样本范围共享一个 key（只前向一次）。"""
    plan = {"A": {}, "B": {}}
    for unit in units:
        if o.disagreement_intervals(unit.texts["w0"], unit.texts["x0"]):
            cues = [tracks[t][i] for t in ("w0", "x0") for i in unit.ids[t]]
            plan["A"][unit.unit_id] = span_key(span_samples(cues, PAD, total_samples))
        if unit.texts["w0"]:
            cues = [tracks["w0"][i] for i in unit.ids["w0"]]
            plan["B"][unit.unit_id] = span_key(span_samples(cues, PAD, total_samples))
    return plan


def wav_samples(path: Path) -> int:
    with wave.open(str(path), "rb") as source:
        return source.getnframes()


# ---------- GPU：MMS 发射矩阵 ----------

def emit(out_dir: Path) -> dict:
    import numpy as np
    import torch

    from kototoki.align import MmsAligner, mms_numeric_policy, normalize_window
    from kototoki.workers.gpu import read_wav

    os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    GPU_LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        with GPU_LOCK.open("x", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "job": "experiments.quality_v5.asr_pair_ctc_judge emit",
                       "created_at_utc": datetime.now(timezone.utc).isoformat()}, stream)
    except FileExistsError:
        raise SystemExit(f"{GPU_LOCK} exists; verify the owning process with Get-Process") from None
    try:
        started = time.perf_counter()
        aligner = MmsAligner(MODEL_DIR)
        load_s = time.perf_counter() - started
        torch.cuda.reset_peak_memory_stats()
        extractor = aligner.processor.feature_extractor
        index = {"meta": {"model_metadata": {k: v for k, v in aligner.metadata.items()
                                             if k != "feature_extractor_config"},
                          "load_s": load_s, "pad_s": PAD, "films": {}}, "spans": {}}
        for film, wav_path in FILM_AUDIO.items():
            audio, pcm = read_wav(wav_path)
            if pcm != EXPECTED_PCM[film]:
                raise ValueError(f"{film}: PCM SHA {pcm} differs from baseline manifest")
            tracks, units = load_film(film)
            plan = plan_spans(tracks, units, len(audio))
            keys = sorted(set(plan["A"].values()) | set(plan["B"].values()), key=lambda k: int(k.split("-")[0]))
            film_dir = out_dir / film
            film_dir.mkdir(parents=True, exist_ok=True)
            spans = index["spans"][film] = {}
            torch.cuda.synchronize()
            film_started = time.perf_counter()
            for key in keys:
                first, last = (int(x) for x in key.split("-"))
                values, _ = normalize_window(audio[first:last], extractor)
                tensor = torch.from_numpy(values.copy()).unsqueeze(0).to(aligner.device)
                with torch.inference_mode(), mms_numeric_policy(torch):
                    logits = aligner.model(tensor).logits
                    emission = logits.log_softmax(dim=-1)[0].cpu().numpy()
                if emission.shape[1] != VOCAB_SIZE:
                    raise ValueError("unexpected MMS vocabulary width")
                np.save(film_dir / f"{key}.npy", emission.astype(np.float32, copy=False))
                spans[key] = {"frames": int(emission.shape[0]),
                              "nonblank_frames": int((emission.argmax(axis=1) != BLANK).sum()),
                              "seconds": (last - first) / SAMPLE_RATE}
            torch.cuda.synchronize()
            index["meta"]["films"][film] = {
                "pcm_sha256": pcm, "pcm_matches_manifest": True, "wav": str(wav_path), "samples": len(audio),
                "plan": plan, "spans": len(keys), "frames": sum(s["frames"] for s in spans.values()),
                "seconds": sum(s["seconds"] for s in spans.values()),
                "forward_wall_s": time.perf_counter() - film_started}
        index["meta"]["vram"] = {"max_allocated_mib": torch.cuda.max_memory_allocated() / 2 ** 20,
                                 "max_reserved_mib": torch.cuda.max_memory_reserved() / 2 ** 20,
                                 "device": torch.cuda.get_device_name(0)}
        index["meta"]["total_wall_s"] = time.perf_counter() - started
        (out_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
        return index["meta"]
    finally:
        GPU_LOCK.unlink(missing_ok=True)


# ---------- 打分（CPU，纯函数，可用合成数据测试） ----------

def mms_dictionary(model_dir: Path = MODEL_DIR) -> dict[str, int]:
    """与 `kototoki.align.model_dictionary` 同规则：小写字符 → id，只保留 id < 2268。"""
    vocabulary = json.loads((model_dir / "vocab.json").read_text(encoding="utf-8"))["jpn"]
    return {char.lower(): code for char, code in vocabulary.items() if code < VOCAB_SIZE}


def target_ids(text: str, dictionary: dict[str, int]) -> list[int]:
    """规范化文本 → 目标 id；OOV 映射到 PENALTY_ID。规范化文本无空白，逐字一一对应。"""
    return [dictionary.get(char.lower(), PENALTY_ID) for char in text]


def has_oov(text: str, dictionary: dict[str, int]) -> bool:
    return any(char.lower() not in dictionary for char in text)


def _columns(emission, ids: list[int]):
    """抽出 blank 与目标列（OOV 用常数列），返回 (T×K float64 张量, 重映射后的目标)。"""
    import numpy as np
    import torch

    unique = sorted(set(ids) - {BLANK})
    remap = {BLANK: 0, **{code: k + 1 for k, code in enumerate(unique)}}
    columns = [emission[:, BLANK]]
    for code in unique:
        columns.append(np.full(len(emission), OOV_LOGPROB) if code == PENALTY_ID else emission[:, code])
    matrix = torch.from_numpy(np.stack(columns, axis=1).astype(np.float64))
    return matrix, [remap[code] for code in ids]


def frames_needed(ids: list[int]) -> int:
    """CTC 可行所需的最少帧数：目标长度＋相邻重复数。"""
    return len(ids) + sum(a == b for a, b in zip(ids, ids[1:]))


def ctc_loglik(emission, ids: list[int]) -> float:
    """log p(ids | emission)，对所有 CTC 路径求和；空目标＝全 blank；帧数不够返回 −inf。"""
    import torch

    if not ids:
        return float(emission[:, BLANK].astype("float64").sum())
    if len(emission) < frames_needed(ids):
        return -math.inf
    matrix, targets = _columns(emission, ids)
    loss = torch.nn.functional.ctc_loss(
        matrix.unsqueeze(1), torch.tensor([targets]), [len(emission)], [len(targets)],
        blank=0, reduction="none", zero_infinity=False)
    return -float(loss[0])


def viterbi_score(emission, ids: list[int]) -> float:
    """最优单条 CTC 路径的对数概率（torchaudio forced_align，与产品对齐同一路径定义）。"""
    import torch
    from torchaudio.functional import forced_align

    if not ids:
        return float(emission[:, BLANK].astype("float64").sum())
    if len(emission) < frames_needed(ids):
        return -math.inf
    matrix, targets = _columns(emission, ids)
    _, scores = forced_align(matrix.float().unsqueeze(0), torch.tensor([targets], dtype=torch.int32), blank=0)
    return float(scores[0].double().sum())


def hypothesis_x(w0: str, interval: dict) -> str:
    """w0 单元文本中只把该区间换成 x0 的文本。"""
    return o.compose(w0, [interval], ["x"])


def decide(d: float, dlen: int, lam: float, margin: float) -> bool:
    """True＝取 x0。d＝score_x − score_w；d 为 ±inf 时按符号决定；NaN（两者都不可行）保持 w0。"""
    if math.isnan(d):
        return False
    return d > margin + lam * dlen


def length_bucket(interval: dict) -> str:
    size = max(len(interval["w"]), len(interval["x"]))
    return "1" if size == 1 else "2" if size == 2 else "3–5" if size <= 5 else "6+"


def kana_fold(text: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)


def is_kana(text: str) -> bool:
    return bool(text) and all("ぁ" <= c <= "ゖ" or "ァ" <= c <= "ヺ" or c == "ー" for c in text)


def same_kana_reading(w: str, x: str) -> bool:
    """两侧都是纯假名且平片假名折叠后相同（さくら／サクラ）；汉字与假名之间无法判断（无读音词典）。"""
    return is_kana(w) and is_kana(x) and kana_fold(w) == kana_fold(x)


# ---------- 合并与调参 ----------

class FilmEvaluator:
    """按单元口径累计 S／D／I；每单元的取法组合做记忆化。"""

    def __init__(self, units: list[o.Unit], rows: list[dict]):
        self.by_unit: dict[str, list[int]] = {}
        for k, row in enumerate(rows):
            self.by_unit.setdefault(row["unit_id"], []).append(k)
        self.units = {u.unit_id: u for u in units}
        self.rows = rows
        self.base = o.new_total()
        for unit in units:
            if unit.unit_id not in self.by_unit:
                o.add(self.base, o.sdi(unit.texts["ref"], unit.texts["w0"]))
        self.ref_chars = sum(len(u.texts["ref"]) for u in units)
        self.memo: dict = {}
        self.cache: dict = {}

    def unit_sdi(self, unit_id: str, picks: tuple[str, ...]) -> dict[str, int]:
        key = (unit_id, picks)
        if key not in self.memo:
            unit = self.units[unit_id]
            intervals = [self.rows[k]["_interval"] for k in self.by_unit[unit_id]]
            self.memo[key] = o.sdi(unit.texts["ref"], o.compose(unit.texts["w0"], intervals, list(picks)))
        return self.memo[key]

    def total(self, choose_x: list[bool]) -> dict[str, int]:
        """choose_x 与 rows 对齐；返回整片 S／D／I。"""
        key = bytes(choose_x)
        if key not in self.cache:
            total = dict(self.base)
            for unit_id, ks in self.by_unit.items():
                o.add(total, self.unit_sdi(unit_id, tuple("x" if choose_x[k] else "w" for k in ks)))
            self.cache[key] = total
        return self.cache[key]

    def marginal(self, k: int) -> int:
        """只把第 k 个区间换成 x0、其余保持 w0 时，该单元编辑量的变化（负＝变好）。"""
        unit_id = self.rows[k]["unit_id"]
        ks = self.by_unit[unit_id]
        base = o.edits(self.unit_sdi(unit_id, ("w",) * len(ks)))
        flipped = o.edits(self.unit_sdi(unit_id, tuple("x" if j == k else "w" for j in ks)))
        return flipped - base


def picks_for(rows: list[dict], lam: float, margin: float, use_acoustic: bool = True) -> list[bool]:
    return [row["scorable"] and decide(row["d"] if use_acoustic else 0.0, row["dlen"], lam, margin)
            for row in rows]


def tune(rows: list[dict], evaluator: FilmEvaluator, lambdas=LAMBDAS, margins=MARGINS,
         use_acoustic: bool = True) -> dict:
    """最小化单元口径总编辑量；平局依次取改动更少、|λ| 更小、|m| 更小者。"""
    best = None
    for lam in lambdas:
        for margin in margins:
            choose = picks_for(rows, lam, margin, use_acoustic)
            key = (o.edits(evaluator.total(choose)), sum(choose), abs(lam), abs(margin))
            if best is None or key < best[0]:
                best = (key, lam, margin)
    (edit_count, changes, _, _), lam, margin = best
    return {"lambda": lam, "margin": margin, "edits": edit_count, "changes": changes,
            "on_grid_edge": lam in (lambdas[0], lambdas[-1]) or margin in (margins[0], margins[-1])}


def accuracy_table(rows: list[dict], choose: list[bool], key) -> dict:
    table: dict = {}
    for row, x in zip(rows, choose):
        cell = table.setdefault(key(row), {"n": 0, "correct": 0, "always_w0_correct": 0, "changed": 0})
        cell["n"] += 1
        cell["correct"] += (x == (row["oracle_pick"] == "x0"))
        cell["always_w0_correct"] += row["oracle_pick"] == "w0"
        cell["changed"] += x
    for cell in table.values():
        cell["accuracy"] = cell["correct"] / cell["n"]
        cell["always_w0_accuracy"] = cell["always_w0_correct"] / cell["n"]
    return dict(sorted(table.items()))


def change_breakdown(rows: list[dict], choose: list[bool]) -> dict:
    """judge 改成 x0 的区间：对照 oracle_pick 对／错，以及单独翻转的编辑量效果。"""
    out = Counter()
    for row, x in zip(rows, choose):
        if not x:
            continue
        out["changed"] += 1
        out["oracle_x0"] += row["oracle_pick"] == "x0"
        out["oracle_w0"] += row["oracle_pick"] == "w0"
        out["marginal_better"] += row["marginal"] < 0
        out["marginal_neutral"] += row["marginal"] == 0
        out["marginal_worse"] += row["marginal"] > 0
        out["marginal_sum"] += row["marginal"]
    return dict(out)


def auc_lower_is_positive(positive: list[float], negative: list[float]) -> float | None:
    """P(正例分数 < 负例分数) + 0.5·P(相等)。"""
    if not positive or not negative:
        return None
    wins = 0.0
    for p in positive:
        for n in negative:
            wins += 1.0 if p < n else 0.5 if p == n else 0.0
    return wins / (len(positive) * len(negative))


def drop_edits(ref: str, hyp: str) -> tuple[dict[str, int], dict[str, int]]:
    """(保留时的 S／D／I, 丢弃该单元 w0 文本后的 S／D／I)。"""
    return o.sdi(ref, hyp), {"S": 0, "D": len(ref), "I": 0}


def tune_drop_threshold(items: list[dict], feature: str) -> dict:
    """丢弃 feature < t 的单元，选使总编辑量最小的 t（平局取丢得更少者）；t 取相邻值的中点。"""
    ordered = sorted(items, key=lambda it: it[feature])
    keep_total = sum(o.edits(it["keep"]) for it in ordered)
    best_n, best_total, running = 0, keep_total, keep_total
    for n, it in enumerate(ordered, 1):
        running += o.edits(it["drop"]) - o.edits(it["keep"])
        if running < best_total and (n == len(ordered) or ordered[n][feature] != it[feature]):
            best_n, best_total = n, running
    if best_n == 0:
        threshold = -math.inf
    elif best_n == len(ordered):
        threshold = math.inf
    else:
        low, high = ordered[best_n - 1][feature], ordered[best_n][feature]
        threshold = low / 2 + high / 2 if math.isfinite(low) and math.isfinite(high) else high
    return {"threshold": threshold, "dropped": best_n, "edits": best_total, "keep_edits": keep_total}


def apply_drop(items: list[dict], feature: str, threshold: float) -> dict:
    total = o.new_total()
    stats = Counter()
    for it in items:
        dropped = it[feature] < threshold
        o.add(total, it["drop"] if dropped else it["keep"])
        if dropped:
            stats["dropped"] += 1
            stats["dropped_insertion"] += it["label"] == "insertion"
            stats["dropped_exact"] += it["label"] == "exact"
            stats["dropped_ref_chars"] += len(it["ref"])
        stats["insertion"] += it["label"] == "insertion"
        stats["exact"] += it["label"] == "exact"
    stats = dict(stats)
    stats["precision"] = stats.get("dropped_insertion", 0) / stats["dropped"] if stats.get("dropped") else None
    stats["recall"] = stats.get("dropped_insertion", 0) / stats["insertion"] if stats.get("insertion") else None
    return {"sdi": total, **stats}


# ---------- 分析（CPU） ----------

def load_emission(film: str, key: str):
    import numpy as np

    return np.load(EMISSIONS / film / f"{key}.npy")


def whisper_windows(film: str) -> list[dict]:
    doc = json.loads(FILM_ASR[film].read_text(encoding="utf-8"))
    if doc["input"]["pcm_sha256"] != EXPECTED_PCM[film]:
        raise ValueError(f"{film}: transcript run used different audio")
    return doc["original_segments"]


def window_logprob(windows: list[dict], start: float, end: float) -> float:
    """与单元 w0 跨度重叠最多的 Whisper 窗口的 avg_logprob（窗口 ≤30 s，比单元粗）。"""
    best, best_overlap = math.nan, 0.0
    for window in windows:
        overlap = min(end, window["end"]) - max(start, window["start"])
        if overlap > best_overlap and window.get("avg_logprob") is not None:
            best, best_overlap = window["avg_logprob"], overlap
    return best


def score_part_a(film: str, units: list[o.Unit], plan: dict, dictionary: dict, labeled: dict) -> list[dict]:
    rows = []
    oracle_rows = {(r["unit_id"], r["interval"]): r for r in read_oracle_intervals() if r["film"] == film}
    for unit in units:
        w0 = unit.texts["w0"]
        intervals = o.disagreement_intervals(w0, unit.texts["x0"])
        if not intervals:
            continue
        emission = load_emission(film, plan["A"][unit.unit_id])
        score_w = ctc_loglik(emission, target_ids(w0, dictionary))
        for k, it in enumerate(intervals):
            reference = oracle_rows[(unit.unit_id, k)]
            if (reference["w"], reference["x"]) != (it["w"], it["x"]):
                raise AssertionError(f"rebuilt interval differs from intervals.jsonl: {unit.unit_id}#{k}")
            hyp_x = hypothesis_x(w0, it)
            oov = has_oov(it["w"] + it["x"], dictionary)
            score_x = ctc_loglik(emission, target_ids(hyp_x, dictionary))
            feasible = math.isfinite(score_w) or math.isfinite(score_x)
            d = score_x - score_w if feasible else math.nan
            sample = labeled.get((film, unit.unit_id, k))
            rows.append({
                "film": film, "unit_id": unit.unit_id, "interval": k, "w": it["w"], "x": it["x"],
                "kind": reference["kind"], "position": reference["position"], "status": reference["status"],
                "length": length_bucket(it), "oracle_pick": reference["oracle_pick"],
                "frames": int(len(emission)), "score_w": score_w, "score_x": score_x, "d": d,
                "dlen": len(it["x"]) - len(it["w"]), "oov_interval": oov,
                "oov_context": has_oov(w0 + unit.texts["x0"], dictionary) and not oov,
                "infeasible": "both" if not feasible else "w" if not math.isfinite(score_w)
                else "x" if not math.isfinite(score_x) else None,
                "scorable": not oov and feasible,
                "same_kana": same_kana_reading(it["w"], it["x"]),
                "label": sample["label"] if sample else None,
                "orthographic_only": sample["orthographic_only"] if sample else None,
                "_interval": it})
    return rows


def score_part_b(film: str, tracks: dict, units: list[o.Unit], plan: dict, dictionary: dict,
                 spans: dict) -> list[dict]:
    windows = whisper_windows(film)
    items = []
    for unit in units:
        w0, ref = unit.texts["w0"], unit.texts["ref"]
        if not w0:
            continue
        key = plan["B"][unit.unit_id]
        emission = load_emission(film, key)
        ids = target_ids(w0, dictionary)
        ll = ctc_loglik(emission, ids)
        blank_only = ctc_loglik(emission, [])
        viterbi = viterbi_score(emission, ids)
        cues = [tracks["w0"][i] for i in unit.ids["w0"]]
        start, end = min(c["start"] for c in cues), max(c["end"] for c in cues)
        nonblank = spans[key]["nonblank_frames"]
        keep, drop = drop_edits(ref, w0)
        items.append({
            "film": film, "unit_id": unit.unit_id, "start": start, "end": end, "w0": w0, "ref": ref,
            "label": "insertion" if not ref else "exact" if ref == w0 else "other",
            "chars": len(w0), "frames": int(len(emission)), "nonblank_frames": nonblank,
            "oov": has_oov(w0, dictionary),
            "ll_total": ll, "ll_per_char": ll / len(w0),
            "llr_blank_per_char": (ll - blank_only) / len(w0),
            "viterbi_total": viterbi, "viterbi_per_char": viterbi / len(w0),
            # 文本长度对语音量：方向按数据（插入单元多为长 cue 上的一两个字，越低越可疑）
            "chars_per_nonblank": len(w0) / max(1, nonblank),
            "chars_per_second": len(w0) / max(1e-3, end - start),
            "whisper_avg_logprob": window_logprob(windows, start, end),
            "keep": keep, "drop": drop})
    return items


PART_B_FEATURES = ("ll_per_char", "llr_blank_per_char", "viterbi_per_char", "ll_total", "viterbi_total",
                   "chars_per_nonblank", "chars_per_second", "whisper_avg_logprob")


def read_oracle_intervals() -> list[dict]:
    path = o.V5 / "asr-pair-oracle/intervals.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def read_labeled() -> dict:
    samples = json.loads((o.V5 / "asr-pair-oracle/samples-labeled.json").read_text(encoding="utf-8"))
    return {(s["film"], s["unit_id"], s["interval"]): s for s in samples}


def cer_of(total: dict[str, int], ref_chars: int) -> dict:
    return o.cer_row(total, ref_chars)


def analyze(out_dir: Path) -> dict:
    index = json.loads((EMISSIONS / "index.json").read_text(encoding="utf-8"))
    dictionary = mms_dictionary()
    labeled = read_labeled()
    films = list(o.FILMS)
    data = {}
    for film in films:
        tracks, units = load_film(film)
        plan = index["meta"]["films"][film]["plan"]
        if plan != plan_spans(tracks, units, index["meta"]["films"][film]["samples"]):
            raise ValueError(f"{film}: span plan changed since emit")
        rows = score_part_a(film, units, plan, dictionary, labeled)
        evaluator = FilmEvaluator(units, rows)
        for k, row in enumerate(rows):
            row["marginal"] = evaluator.marginal(k)
        oracle = o.analyze_film(film, units)
        oracle.pop("_intervals")
        items = score_part_b(film, tracks, units, plan, dictionary, index["spans"][film])
        data[film] = {"units": units, "rows": rows, "evaluator": evaluator, "oracle": oracle, "items": items}

    # ---- Part A：调参 ----
    report: dict = {"meta": index["meta"], "grid": {"lambda": [LAMBDAS[0], LAMBDAS[-1], 0.25],
                                                   "margin": [MARGINS[0], MARGINS[-1], 0.5]},
                    "oov_logprob": OOV_LOGPROB, "part_a": {}, "part_b": {}}
    tuned = {}
    for mode, acoustic in (("ctc", True), ("length_only", False)):
        for film in films:
            tuned[(mode, film)] = tune(data[film]["rows"], data[film]["evaluator"], use_acoustic=acoustic)
    pooled_rows = [r for f in films for r in data[f]["rows"]]

    def pooled_total(lam, margin, acoustic=True):
        total = o.new_total()
        for f in films:
            o.add(total, data[f]["evaluator"].total(picks_for(data[f]["rows"], lam, margin, acoustic)))
        return total

    best_pooled = None
    for lam in LAMBDAS:
        for margin in MARGINS:
            total = pooled_total(lam, margin)
            changes = sum(sum(picks_for(data[f]["rows"], lam, margin)) for f in films)
            key = (o.edits(total), changes, abs(lam), abs(margin))
            if best_pooled is None or key < best_pooled[0]:
                best_pooled = (key, lam, margin)
    other = {films[0]: films[1], films[1]: films[0]}
    part_a = report["part_a"]
    part_a["tuned"] = {f"{mode}:{film}": value for (mode, film), value in tuned.items()}
    part_a["tuned"]["ctc:pooled"] = {"lambda": best_pooled[1], "margin": best_pooled[2],
                                      "edits": best_pooled[0][0], "changes": best_pooled[0][1]}
    choices = {}  # 各行在交叉调参下的取法
    cer_rows = {}
    for film in films:
        rows, evaluator = data[film]["rows"], data[film]["evaluator"]
        ref_chars = evaluator.ref_chars
        cross = tuned[("ctc", other[film])]
        cross_choose = picks_for(rows, cross["lambda"], cross["margin"])
        insample = tuned[("ctc", film)]
        length_cross = tuned[("length_only", other[film])]
        choices[film] = cross_choose
        cer_rows[film] = {
            "w0": cer_of(evaluator.total([False] * len(rows)), ref_chars),
            "judge_cross": cer_of(evaluator.total(cross_choose), ref_chars),
            "judge_insample": cer_of(evaluator.total(picks_for(rows, insample["lambda"], insample["margin"])),
                                     ref_chars),
            "judge_pooled_params": cer_of(evaluator.total(picks_for(rows, best_pooled[1], best_pooled[2])),
                                          ref_chars),
            "length_only_cross": cer_of(evaluator.total(
                picks_for(rows, length_cross["lambda"], length_cross["margin"], False)), ref_chars),
            "always_x0_scorable": cer_of(evaluator.total([r["scorable"] for r in rows]), ref_chars),
            "oracle_splice": data[film]["oracle"]["cer"]["splice"],
            "oracle_select": data[film]["oracle"]["cer"]["select"],
            "x0": data[film]["oracle"]["cer"]["x0"],
        }
        if cer_rows[film]["w0"]["edits"] != data[film]["oracle"]["cer"]["w0"]["edits"]:
            raise AssertionError("w0 edits differ from oracle script")
    total_ref = sum(data[f]["evaluator"].ref_chars for f in films)
    cer_rows["total"] = {name: cer_of({k: sum(cer_rows[f][name][k] for f in films) for k in "SDI"}, total_ref)
                         for name in cer_rows[films[0]]}
    part_a["cer"] = cer_rows
    all_choose = [x for f in films for x in choices[f]]
    part_a["counts"] = {
        "intervals": len(pooled_rows), "scorable": sum(r["scorable"] for r in pooled_rows),
        "oov_interval": sum(r["oov_interval"] for r in pooled_rows),
        "oov_context_only": sum(r["oov_context"] for r in pooled_rows),
        "infeasible": dict(Counter(r["infeasible"] for r in pooled_rows if r["infeasible"])),
        "indifferent_marginal": sum(r["marginal"] == 0 for r in pooled_rows),
        "frames": {"min": min(r["frames"] for r in pooled_rows), "max": max(r["frames"] for r in pooled_rows)},
    }
    part_a["accuracy"] = {
        "overall": accuracy_table(pooled_rows, all_choose, lambda r: "all"),
        "film": accuracy_table(pooled_rows, all_choose, lambda r: r["film"]),
        "kind": accuracy_table(pooled_rows, all_choose, lambda r: r["kind"]),
        "position": accuracy_table(pooled_rows, all_choose, lambda r: r["position"]),
        "length": accuracy_table(pooled_rows, all_choose, lambda r: r["length"]),
        "decisive": accuracy_table(pooled_rows, all_choose,
                                   lambda r: "marginal≠0" if r["marginal"] != 0 else "marginal=0"),
        "same_kana": accuracy_table(pooled_rows, all_choose, lambda r: "same_kana" if r["same_kana"] else "other"),
        "scorable": accuracy_table(pooled_rows, all_choose, lambda r: "scorable" if r["scorable"] else "excluded"),
        "labeled": accuracy_table([r for r in pooled_rows if r["label"]],
                                  [x for r, x in zip(pooled_rows, all_choose) if r["label"]],
                                  lambda r: r["label"] + ("（表记）" if r["orthographic_only"] else "")),
        "labeled_orthographic": accuracy_table(
            [r for r in pooled_rows if r["label"]], [x for r, x in zip(pooled_rows, all_choose) if r["label"]],
            lambda r: "表记" if r["orthographic_only"] else "非表记"),
    }
    part_a["changes"] = {"all": change_breakdown(pooled_rows, all_choose),
                         **{f: change_breakdown(data[f]["rows"], choices[f]) for f in films},
                         **{f"kind:{kind}": change_breakdown(
                             [r for r in pooled_rows if r["kind"] == kind],
                             [x for r, x in zip(pooled_rows, all_choose) if r["kind"] == kind])
                            for kind in ("替换", "w0 多出", "x0 多出")}}
    # 判别力：在 marginal ≠ 0 的可打分区间上，调整后分数对"x0 更好"的 AUC（λ 取交叉调参值）
    def auc_x_better(rows, value):
        return {"n": len(rows), "auc": auc_lower_is_positive([-value(r) for r in rows if r["marginal"] < 0],
                                                             [-value(r) for r in rows if r["marginal"] > 0])}

    auc = {}
    for film in films:
        lam = tuned[("ctc", other[film])]["lambda"]
        rows = [r for r in data[film]["rows"] if r["scorable"] and r["marginal"] != 0]
        adjusted = lambda r, lam=lam: r["d"] - lam * r["dlen"]  # noqa: E731
        auc[film] = {"lambda": lam, "adjusted": auc_x_better(rows, adjusted),
                     "raw_d": auc_x_better(rows, lambda r: r["d"]),
                     **{f"kind:{kind}": auc_x_better([r for r in rows if r["kind"] == kind], adjusted)
                        for kind in ("替换", "w0 多出", "x0 多出")},
                     "same_length": auc_x_better([r for r in rows if r["dlen"] == 0], lambda r: r["d"])}
    decisive = [r for r in pooled_rows if r["scorable"] and r["marginal"] != 0 and r["kind"] == "替换"]
    kana = [r for r in decisive if is_kana(r["w"]) and is_kana(r["x"]) and not r["same_kana"]]
    kanji = [r for r in decisive if not (is_kana(r["w"]) and is_kana(r["x"]))]
    auc["pooled_substitution"] = {"kana_only": auc_x_better(kana, lambda r: r["d"]),
                                  "with_kanji": auc_x_better(kanji, lambda r: r["d"])}
    part_a["auc"] = auc
    part_a["labeled_rows"] = [
        {k: r[k] for k in ("film", "unit_id", "interval", "w", "x", "label", "orthographic_only", "oracle_pick",
                           "d", "dlen", "marginal", "scorable")} | {"judge_x0": x}
        for r, x in zip(pooled_rows, all_choose) if r["label"]]

    # ---- Part B ----
    part_b = report["part_b"]
    pooled_items = [it for f in films for it in data[f]["items"]]
    part_b["counts"] = dict(Counter((it["film"], it["label"]) for it in pooled_items).items())
    part_b["counts"] = {f"{f}:{label}": n for (f, label), n in part_b["counts"].items()}
    part_b["counts"]["oov_units"] = sum(it["oov"] for it in pooled_items)
    part_b["auc"] = {}
    for feature in PART_B_FEATURES:
        row = {}
        for scope, scoped in (("pooled", pooled_items), *((f, data[f]["items"]) for f in films)):
            valid = [it for it in scoped if not math.isnan(it[feature])]
            row[scope] = auc_lower_is_positive([it[feature] for it in valid if it["label"] == "insertion"],
                                               [it[feature] for it in valid if it["label"] == "exact"])
        part_b["auc"][feature] = row
    for it in pooled_items:  # NaN（无 Whisper 窗口）视为不可疑
        for feature in PART_B_FEATURES:
            if math.isnan(it[feature]):
                it[feature] = math.inf
    part_b["cross"] = {}
    for feature in PART_B_FEATURES:
        entry = {}
        total = o.new_total()
        for film in films:
            tuned_on = tune_drop_threshold(data[other[film]]["items"], feature)
            applied = apply_drop(data[film]["items"], feature, tuned_on["threshold"])
            base = data[film]["evaluator"]
            keep_units = apply_drop(data[film]["items"], feature, -math.inf)
            # 无 w0 文本的单元不受影响：总 SDI ＝ 有 w0 文本单元的 SDI ＋ 其余单元
            rest = o.new_total()
            for unit in data[film]["units"]:
                if not unit.texts["w0"]:
                    o.add(rest, o.sdi(unit.texts["ref"], ""))
            film_total = {k: applied["sdi"][k] + rest[k] for k in "SDI"}
            w0_total = {k: keep_units["sdi"][k] + rest[k] for k in "SDI"}
            o.add(total, film_total)
            insample = tune_drop_threshold(data[film]["items"], feature)
            entry[film] = {"threshold_from": other[film], "threshold": tuned_on["threshold"],
                           "insample": {"threshold": insample["threshold"], "dropped": insample["dropped"],
                                        "delta_edits": insample["edits"] - insample["keep_edits"]},
                           "cer": cer_of(film_total, base.ref_chars), "w0": cer_of(w0_total, base.ref_chars),
                           **{k: v for k, v in applied.items() if k != "sdi"}}
        entry["total"] = cer_of(total, total_ref)
        part_b["cross"][feature] = entry
    # 上界：恰好丢掉全部"参考无字"的单元（用了参考答案）
    ceiling = o.new_total()
    for film in films:
        for unit in data[film]["units"]:
            o.add(ceiling, o.sdi(unit.texts["ref"], unit.texts["w0"] if unit.texts["ref"] else ""))
    part_b["oracle_drop_insertions"] = cer_of(ceiling, total_ref)
    # 精确率／召回：按合并后的召回分位取阈值
    part_b["pr"] = {}
    for feature in PART_B_FEATURES:
        positive = sorted(it[feature] for it in pooled_items if it["label"] == "insertion")
        points = []
        for recall in (0.25, 0.5, 0.75, 0.9, 1.0):
            n = max(1, math.ceil(recall * len(positive)))
            threshold = math.nextafter(positive[n - 1], math.inf)
            stats = Counter()
            for film in films:
                applied = apply_drop(data[film]["items"], feature, threshold)
                for key in ("dropped", "dropped_insertion", "dropped_exact", "dropped_ref_chars"):
                    stats[key] += applied.get(key, 0)
                stats["delta_edits"] += o.edits(applied["sdi"]) - o.edits(
                    apply_drop(data[film]["items"], feature, -math.inf)["sdi"])
            points.append({"target_recall": recall, "threshold": threshold, **stats,
                           "recall": stats["dropped_insertion"] / len(positive),
                           "precision": stats["dropped_insertion"] / stats["dropped"] if stats["dropped"] else None})
        part_b["pr"][feature] = points
    best_feature = min(PART_B_FEATURES, key=lambda f: part_b["cross"][f]["total"]["edits"])
    part_b["best_cross_feature"] = best_feature
    dropped = []
    for film in films:
        threshold = part_b["cross"][best_feature][film]["threshold"]
        dropped += [it for it in data[film]["items"] if it[best_feature] < threshold]
    dropped.sort(key=lambda it: it[best_feature])
    listing = [{k: it[k] for k in ("film", "unit_id", "start", "end", "label", "w0", "ref", "chars", "frames",
                                   "nonblank_frames", best_feature, "whisper_avg_logprob")} for it in dropped]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "partb-dropped.json").write_text(json.dumps(listing, ensure_ascii=False, indent=1), encoding="utf-8")
    part_b["dropped_count"] = len(listing)
    report["part_a_rows_file"] = "scores-a.jsonl"
    (out_dir / "scores-a.jsonl").write_text("".join(
        json.dumps({k: v for k, v in r.items() if k != "_interval"} | {"judge_x0": x}, ensure_ascii=False) + "\n"
        for r, x in zip(pooled_rows, all_choose)), encoding="utf-8")
    (out_dir / "scores-b.jsonl").write_text("".join(
        json.dumps({k: v for k, v in it.items() if k not in ("keep", "drop")}, ensure_ascii=False) + "\n"
        for it in pooled_items), encoding="utf-8")
    (out_dir / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str),
                                          encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="MMS CTC 声学裁判（Part A）与 w0 幻觉过滤（Part B）")
    parser.add_argument("command", choices=("emit", "analyze"))
    parser.add_argument("--out-dir", type=Path, default=OUT)
    args = parser.parse_args()
    if args.command == "emit":
        meta = emit(EMISSIONS)
        print(json.dumps({k: v for k, v in meta.items() if k != "model_metadata"}, default=str)[:2000])
        return 0
    report = analyze(args.out_dir)
    for film, rows in report["part_a"]["cer"].items():
        print(film, {k: round(v["CER"], 4) for k, v in rows.items()})
    print("tuned", report["part_a"]["tuned"])
    print("accuracy", report["part_a"]["accuracy"]["overall"])
    print("part_b best", report["part_b"]["best_cross_feature"], report["part_b"]["cross"][
        report["part_b"]["best_cross_feature"]]["total"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
