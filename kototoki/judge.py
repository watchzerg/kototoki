"""w0／x0 两路 ASR 的窗口级裁判纯逻辑（基础层，只依赖标准库）。

一个 VAD 窗口有 w0（Whisper）与 x0（Qwen）两份原文。流程见增量说明 cross-asr-judge §2.2：
规范化 → 字符级对齐找分歧区间 → 每区间构造"只翻转该区间"的假设 → 调用方提供的打分器（Whisper
教师强制 Σ log prob）打分 → d ＝ score_x − score_w > margin 时取 x0 → 全部被接受的翻转一起应用。

算法从研究脚本复制而来（产品包不导入 experiments 与 kototoki_eval，只复制不引用）：
  - `normalize`／`Normalized`：`kototoki_eval/schema.py`，原样复制；
  - `align_ops`、`disagreement_intervals`、`compose`：`experiments/quality_v5/asr_pair_oracle.py`；
  - 原文偏移映射与 raw 假设（`_raw_span`、`_raw_hypothesis`）：`experiments/quality_v5/asr_pair_cross_score.py`。
研究以 cue 并集为单元并先用 `join_raw` 拼接 SRT cue；这里单元是单个窗口的 ASR 原文，不拼接，也不改写空白，
hyp_w 就是 w0 窗口原文（§2.2 第 3 条）。
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass

KINDS = ("substitution", "w0_extra", "x0_extra")


# ---------- 规范化（复制自 kototoki_eval/schema.py，保持逐字一致） ----------

@dataclass(frozen=True)
class Normalized:
    text: str
    raw_spans: tuple[tuple[int, int], ...]


def normalize(text: str) -> Normalized:
    """NFKC, remove Unicode punctuation/whitespace, retain source offsets.

    Combining marks and halfwidth Japanese voicing marks share a source cluster.
    Reject uncommon cross-cluster compositions rather than misrepresent offsets.
    """
    clusters: list[tuple[str, int, int]] = []
    for index, char in enumerate(text):
        if clusters and (unicodedata.combining(char) or char in "ﾞﾟ"):
            prior, start, _ = clusters[-1]
            clusters[-1] = (prior + char, start, index + 1)
        else:
            clusters.append((char, index, index + 1))
    parts = [(unicodedata.normalize("NFKC", value), start, end)
             for value, start, end in clusters]
    if "".join(value for value, _, _ in parts) != unicodedata.normalize("NFKC", text):
        raise ValueError("Unsupported cross-cluster NFKC composition; review source mapping")
    chars: list[str] = []
    offsets: list[tuple[int, int]] = []
    for value, start, end in parts:
        for char in value:
            if char.isspace() or unicodedata.category(char).startswith("P"):
                continue
            chars.append(char)
            offsets.append((start, end))
    return Normalized("".join(chars), tuple(offsets))


# ---------- 字符级对齐与分歧区间（复制自 asr_pair_oracle.py） ----------

@dataclass(frozen=True)
class Interval:
    """规范化文本上的分歧区间；下标为规范化字符下标，end 不含。"""

    w_start: int
    w_end: int
    x_start: int
    x_end: int
    w: str
    x: str
    kind: str  # "substitution" | "w0_extra" | "x0_extra"


def align_ops(a: str, b: str) -> list[tuple[str, int, int]]:
    """Levenshtein 回溯，返回 (op, i, j)：M 匹配、S 替换、D（a 有 b 无）、I（b 有 a 无）。i／j 为 a／b 中字符下标
    （D 的 j、I 的 i 为该处的对应位置）。平局优先对角，其次 D，最后 I。"""
    n, m = len(a), len(b)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        table[i][0] = i
    for j in range(m + 1):
        table[0][j] = j
    for i in range(1, n + 1):
        row, prev = table[i], table[i - 1]
        for j in range(1, m + 1):
            row[j] = min(prev[j - 1] + (a[i - 1] != b[j - 1]), prev[j] + 1, row[j - 1] + 1)
    ops = []
    i, j = n, m
    while i or j:
        if i and j and table[i][j] == table[i - 1][j - 1] + (a[i - 1] != b[j - 1]):
            ops.append(("M" if a[i - 1] == b[j - 1] else "S", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i and table[i][j] == table[i - 1][j] + 1:
            ops.append(("D", i - 1, j))
            i -= 1
        else:
            ops.append(("I", i, j - 1))
            j -= 1
    ops.reverse()
    return ops


def disagreement_intervals(w: str, x: str) -> list[Interval]:
    """规范化文本 w（w0）与 x（x0）字符级对齐，非匹配操作的极大连续段为一个区间（相隔至少一个匹配字符才分开）。"""
    spans: list[list[int]] = []  # [w_start, w_end, x_start, x_end]
    current = None
    for op, i, j in align_ops(w, x):
        if op == "M":
            current = None
            continue
        if current is None:
            current = [i, i, j, j]
            spans.append(current)
        if op in ("S", "D"):
            current[1] = i + 1
        if op in ("S", "I"):
            current[3] = j + 1
    intervals = []
    for ws, we, xs, xe in spans:
        a, b = w[ws:we], x[xs:xe]
        kind = "substitution" if a and b else "w0_extra" if a else "x0_extra"
        intervals.append(Interval(ws, we, xs, xe, a, b, kind))
    return intervals


def compose(w: str, intervals: list[Interval], picks: list[bool]) -> str:
    """规范化 w 中把 picks 为 True 的区间换成 x0 文本。"""
    out = []
    cursor = 0
    for it, pick in zip(intervals, picks, strict=True):
        out.append(w[cursor:it.w_start])
        out.append(it.x if pick else it.w)
        cursor = it.w_end
    out.append(w[cursor:])
    return "".join(out)


# ---------- 原文偏移映射（复制自 asr_pair_cross_score.py） ----------

def _raw_span(offsets: tuple[tuple[int, int], ...], a: int, b: int) -> tuple[int, int]:
    """规范化字符区间 [a, b) → 原文区间。空区间（插入点）：在下一个规范化字符之前；在末尾则紧跟最后一个字符
    （即落在 w0 的句末标点之前）。"""
    if a < b:
        return offsets[a][0], offsets[b - 1][1]
    if a < len(offsets):
        return offsets[a][0], offsets[a][0]
    end = offsets[-1][1] if offsets else 0
    return end, end


def _raw_edit(raw_x: str, nw: Normalized, nx: Normalized, it: Interval) -> tuple[int, int, str]:
    """区间在 w0 原文中的 [start, end) 与替换用的 x0 原文字符。"""
    start, end = _raw_span(nw.raw_spans, it.w_start, it.w_end)
    replacement = ""
    if it.x:
        xs, xe = _raw_span(nx.raw_spans, it.x_start, it.x_end)
        replacement = raw_x[xs:xe]
    return start, end, replacement


def _raw_hypothesis(raw_w: str, raw_x: str, nw: Normalized, nx: Normalized, it: Interval) -> str | None:
    """w0 原文中只把该区间的字符换成 x0 原文对应字符，其余（含 w0 标点）不动；规范化后必须等于 `compose`
    的结果，否则映射失败返回 None。"""
    start, end, replacement = _raw_edit(raw_x, nw, nx, it)
    hypothesis = raw_w[:start] + replacement + raw_w[end:]
    try:
        consistent = normalize(hypothesis).text == compose(nw.text, [it], [True])
    except ValueError:
        return None
    return hypothesis if consistent else None


# ---------- 假设、判定与合并 ----------

def hypotheses(raw_w: str, raw_x: str) -> tuple[list[Interval], str, list[str], str]:
    """返回 (区间, hyp_w, 每区间的 hyp_x, 文本形式)。

    raw 形式：hyp_w 为 w0 原文，hyp_x 按偏移把该区间换成 x0 原文字符；任一区间映射失败时整窗回退到
    normalized 形式（hyp_w 为规范化 w0，hyp_x 为 `compose` 单区间翻转），两种形式不混用。
    原文无法规范化（跨簇 NFKC 组合）时 `normalize` 抛 ValueError，由调用方处理。
    """
    nw, nx = normalize(raw_w), normalize(raw_x)
    intervals = disagreement_intervals(nw.text, nx.text)
    raw = [_raw_hypothesis(raw_w, raw_x, nw, nx, it) for it in intervals]
    if all(h is not None for h in raw):
        return intervals, raw_w, raw, "raw"
    return intervals, nw.text, [compose(nw.text, [it], [True]) for it in intervals], "normalized"


def decide(d: float, *, margin: float) -> bool:
    """True＝取 x0：d ＝ score_x − score_w 严格大于 margin；相等保持 w0，NaN 保持 w0。"""
    return d > margin


def merge(hyp_w: str, intervals: list[Interval], picks: list[bool], text_form: str,
          raw_w: str, raw_x: str) -> str:
    """把全部被接受的翻转一次性应用到 hyp_w，形式与假设相同（各区间独立判定，§2.2 第 6 条）。

    raw 形式按偏移在 w0 原文上从右到左替换（区间相隔至少一个匹配字符，原文区间不重叠）；
    normalized 形式即 `compose`。
    """
    if text_form != "raw":
        return compose(hyp_w, intervals, picks)
    nw, nx = normalize(raw_w), normalize(raw_x)
    text = raw_w
    for it, pick in reversed(list(zip(intervals, picks, strict=True))):
        if pick:
            start, end, replacement = _raw_edit(raw_x, nw, nx, it)
            text = text[:start] + replacement + text[end:]
    return text


# ---------- 窗口级裁判与汇总 ----------

@dataclass(frozen=True)
class WindowJudgement:
    text: str                     # 合并后的窗口文本；无翻转或守卫触发时为 w0 原文
    identical: bool               # 两路规范化相同：text 为 w0 原文，不打分
    text_form: str                # 打分所用形式："raw" | "normalized" | "unscored"
    intervals: tuple[dict, ...]   # 每区间：w, x, kind, score_w, score_x, d, switched（最终是否取 x0）
    guard: str | None             # "empty_result"：合并后为空而 w0 非空，回退 w0；"normalize_failed"：原文无法规范化，取 w0


def judge_window(raw_w: str, raw_x: str, score: Callable[[list[str]], list[float]], *,
                 margin: float, max_batch: int) -> WindowJudgement:
    """裁判一个窗口。score 对一批文本返回同序分数（score("") 约定为 0.0，这里不特判）。

    hyp_w 只打一次分，放在第一批；全部假设按每批 ≤ max_batch 条依次送入。
    没有区间被接受时 text 直接取 w0 原文（normalized 形式下也保留 w0 标点）。
    """
    try:
        identical = normalize(raw_w).text == normalize(raw_x).text
    except ValueError:
        return WindowJudgement(raw_w, False, "unscored", (), "normalize_failed")
    if identical:
        return WindowJudgement(raw_w, True, "unscored", (), None)
    intervals, hyp_w, hyp_xs, text_form = hypotheses(raw_w, raw_x)
    first = max_batch - 1
    scores = list(score([hyp_w, *hyp_xs[:first]]))
    for k in range(first, len(hyp_xs), max_batch):
        scores.extend(score(hyp_xs[k:k + max_batch]))
    score_w = scores[0]
    ds = [s - score_w for s in scores[1:]]
    picks = [decide(d, margin=margin) for d in ds]
    if len(picks) != len(intervals):
        raise ValueError(f"scorer returned {len(scores)} scores for {len(intervals) + 1} texts")
    guard = None
    text = merge(hyp_w, intervals, picks, text_form, raw_w, raw_x) if any(picks) else raw_w
    if not normalize(text).text and normalize(raw_w).text:
        text, picks, guard = raw_w, [False] * len(picks), "empty_result"
    records = tuple({"w": it.w, "x": it.x, "kind": it.kind, "score_w": score_w, "score_x": s,
                     "d": d, "switched": pick}
                    for it, s, d, pick in zip(intervals, scores[1:], ds, picks, strict=True))
    return WindowJudgement(text, False, text_form, records, guard)


def summarize(judgements: Iterable[WindowJudgement]) -> dict:
    """文件级计数：窗口、相同、已打分、normalized 回退、区间、改为 x0、守卫（按名）、按类型的改动／总数。"""
    summary = {"windows": 0, "identical": 0, "scored": 0, "normalized_form": 0, "intervals": 0,
               "switched": 0, "guards": {}, "by_kind": {kind: {"switched": 0, "total": 0} for kind in KINDS}}
    for judgement in judgements:
        summary["windows"] += 1
        summary["identical"] += judgement.identical
        summary["scored"] += judgement.text_form != "unscored"
        summary["normalized_form"] += judgement.text_form == "normalized"
        if judgement.guard:
            summary["guards"][judgement.guard] = summary["guards"].get(judgement.guard, 0) + 1
        for record in judgement.intervals:
            summary["intervals"] += 1
            summary["switched"] += record["switched"]
            summary["by_kind"][record["kind"]]["total"] += 1
            summary["by_kind"][record["kind"]]["switched"] += record["switched"]
    return summary
