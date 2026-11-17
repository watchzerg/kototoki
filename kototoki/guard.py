"""ASR 整窗守卫的纯逻辑（基础层，只依赖标准库与 `recipes`、`judge.normalize`；ADR-0023、ADR-0030）。

三条规则都在规范化文本（NFKC、去标点与空白）上判定，参数是 `recipes.W0["guard"]`，不是配置项。按顺序：

1. **复读 `repeat-strict`**（ADR-0023）：两个信号任一成立且覆盖该窗规范化文字的 `min_coverage` 以上即命中——
   - 相邻重复：同一个长 p（p ≥ `min_period`）的单元连续重复 ≥ `min_copies` 份；取覆盖字符最多的一段（并列取 p 小）。
     同一字符连写同时满足所有周期，按 p = 2 计。
   - 非相邻复现：长度 ≥ `min_length` 的子串不重叠出现 ≥ `min_count` 次；取 次数 × 长度 最大的（并列取更长）。

   命中窗口在**原文**上折叠相邻重复——保留第一个单元，删掉其后各次重复所占的原文区间（含夹在其中的标点），
   其余照抄；折叠后仍命中，或只有非相邻复现命中（没有可折叠的区段），则该窗置空。算法移植自研究脚本
   `experiments/asr_robustness_v15/repeat.py`（产品包只复制不引用），`tests/equivalence/test_guard.py` 实时对照。
2. **语速 `speech-rate`**（ADR-0030）：（折叠后的）规范化字数 ÷ 窗口时长 > `max_chars_per_s` 即置空。
3. **已知幻听句 `hallucination-phrase`**（ADR-0030）：（折叠后的）整窗规范化文字等于名单中的一句即置空。

置空由调用方按 `failed_windows` 记。无法规范化的文字（跨簇 NFKC 组合）三条规则都不命中。

模块页：docs/architecture/modules/stt-asr.md。
"""

from __future__ import annotations

from typing import Any

from kototoki import recipes
from kototoki.judge import normalize

_BLOCK = recipes.W0["guard"]
REPEAT: dict[str, Any] = {key: _BLOCK["repeat"][key] for key in
                          ("rule", "min_period", "min_copies", "min_count", "min_length", "min_coverage")}
SPEECH_RATE: dict[str, Any] = {key: _BLOCK["speech_rate"][key] for key in ("rule", "max_chars_per_s")}
PHRASES: dict[str, Any] = {"rule": _BLOCK["hallucination_phrases"]["rule"],
                           "phrases": tuple(_BLOCK["hallucination_phrases"]["phrases"])}


def _tandem(text: str) -> dict[str, int] | None:
    """覆盖最多的相邻重复区段 `{period, start, copies, run_chars}`（规范化文本下标）；没有合格区段时为 None。"""
    n = len(text)
    best: dict[str, int] | None = None
    for period in range(max(1, REPEAT["min_period"]), n // REPEAT["min_copies"] + 1):
        j = 0
        while j + period < n:
            if text[j] != text[j + period]:
                j += 1
                continue
            k = j
            while k + period < n and text[k] == text[k + period]:
                k += 1
            copies = (k - j) // period + 1  # text[j:k] 与 text[j+period:k+period] 相同
            if copies >= REPEAT["min_copies"] and (best is None or copies * period > best["run_chars"]):
                best = {"period": period, "start": j, "copies": copies, "run_chars": copies * period}
            j = k + 1
    return best


def _recurring_chars(text: str) -> int:
    """合格的非相邻复现子串覆盖的字符数（次数 × 长度）的最大值；没有时为 0。"""
    n = len(text)
    best = 0
    for length in range(REPEAT["min_length"], n // REPEAT["min_count"] + 1):
        for sub in {text[i:i + length] for i in range(n - length + 1)}:
            count = text.count(sub)  # str.count 即不重叠计数
            if count >= REPEAT["min_count"]:
                best = max(best, count * length)
    return best


def _covers(chars: int, total: int) -> bool:
    return total > 0 and round(chars / total, 4) >= REPEAT["min_coverage"]  # 四舍五入到 4 位，同研究侧


def _normalized(text: str) -> str | None:
    try:
        return normalize(text).text
    except ValueError:
        return None


def check_repeat(text: str) -> bool:
    """窗口文字是否命中 `repeat-strict`。无法规范化的文字不命中。"""
    norm = _normalized(text)
    if norm is None:
        return False
    run = _tandem(norm)
    return (run is not None and _covers(run["run_chars"], len(norm))) or _covers(_recurring_chars(norm), len(norm))


def apply_repeat(text: str) -> tuple[str, dict[str, Any] | None]:
    """只跑 `repeat-strict`。未命中返回 (原文, None)；命中返回 (新文字, `{rule, action, period, copies, removed_raw_chars}`)：

    - `action = "collapse"`：新文字为折叠后的原文；
    - `action = "blank"`：折叠后仍命中或没有可折叠的相邻重复，返回的文字仍是原文。
      此时 `period`／`copies`／`removed_raw_chars` 描述被放弃的折叠，没有可折叠区段时为 None／None／0。
    """
    if not check_repeat(text):
        return text, None
    norm = normalize(text)
    run = _tandem(norm.text)
    if run is None or not _covers(run["run_chars"], len(norm.text)):
        return text, {"rule": REPEAT["rule"], "action": "blank", "period": None, "copies": None,
                      "removed_raw_chars": 0}
    first_end = run["start"] + run["period"]
    cut_start = norm.raw_spans[first_end - 1][1]                      # 第一个单元在原文里的结束
    cut_end = norm.raw_spans[run["start"] + run["run_chars"] - 1][1]  # 整段重复在原文里的结束
    collapsed = text[:cut_start] + text[cut_end:]
    record = {"rule": REPEAT["rule"], "action": "collapse", "period": run["period"], "copies": run["copies"],
              "removed_raw_chars": cut_end - cut_start}
    if check_repeat(collapsed):
        return text, {**record, "action": "blank"}
    return collapsed, record


def apply(text: str, duration_s: float) -> tuple[str, dict[str, Any] | None]:
    """按顺序过三条规则。未命中返回 (原文, None)；否则返回 (新文字, 记录)，记录的 `action` 为：

    - `collapse`（只有复读）：新文字为折叠后的文字，记录同 `apply_repeat`；
    - `blank`：调用方应把该窗置空，返回的文字仍是原文。记录是第一个置空的规则：复读同 `apply_repeat`；
      语速 `{rule, action, chars, duration_s}`；幻听句 `{rule, action, phrase_index}`。记录不含文字。
    """
    if duration_s <= 0:
        raise ValueError("Guard window duration must be positive")
    collapsed, record = apply_repeat(text)
    if record is not None and record["action"] == "blank":
        return text, record
    norm = _normalized(collapsed)
    if norm:
        if len(norm) / duration_s > SPEECH_RATE["max_chars_per_s"]:
            return text, {"rule": SPEECH_RATE["rule"], "action": "blank", "chars": len(norm),
                          "duration_s": round(duration_s, 3)}
        if norm in PHRASES["phrases"]:
            return text, {"rule": PHRASES["rule"], "action": "blank", "phrase_index": PHRASES["phrases"].index(norm)}
    return collapsed, record
