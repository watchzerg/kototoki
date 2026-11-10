"""ASR 整窗复读守卫的纯逻辑（基础层，只依赖标准库与 `recipes`、`judge.normalize`；ADR-0023）。

规则 `repeat-strict`，在规范化文本（NFKC、去标点与空白）上看两个信号，任一成立且覆盖该窗规范化文字的
`min_coverage` 以上即命中：

- 相邻重复：同一个长 p（p ≥ `min_period`）的单元连续重复 ≥ `min_copies` 份；取覆盖字符最多的一段（并列取 p 小）。
  同一字符连写同时满足所有周期，按 p = 2 计。
- 非相邻复现：长度 ≥ `min_length` 的子串不重叠出现 ≥ `min_count` 次；取 次数 × 长度 最大的（并列取更长）。

动作：命中窗口在**原文**上折叠相邻重复——保留第一个单元，删掉其后各次重复所占的原文区间（含夹在其中的标点），
其余照抄；折叠后仍命中，或只有非相邻复现命中（没有可折叠的区段），则该窗置空（由调用方按 `failed_windows` 记）。

算法移植自研究脚本 `experiments/asr_robustness_v15/repeat.py`（产品包只复制不引用），
`tests/core/test_guard.py` 核对两者在同一组文本上结果相同。参数是 `recipes.W0["guard"]`，不是配置项。
"""

from __future__ import annotations

from typing import Any

from kototoki import recipes
from kototoki.judge import normalize

RULE: dict[str, Any] = {key: recipes.W0["guard"][key] for key in
                        ("rule", "min_period", "min_copies", "min_count", "min_length", "min_coverage")}


def _tandem(text: str) -> dict[str, int] | None:
    """覆盖最多的相邻重复区段 `{period, start, copies, run_chars}`（规范化文本下标）；没有合格区段时为 None。"""
    n = len(text)
    best: dict[str, int] | None = None
    for period in range(max(1, RULE["min_period"]), n // RULE["min_copies"] + 1):
        j = 0
        while j + period < n:
            if text[j] != text[j + period]:
                j += 1
                continue
            k = j
            while k + period < n and text[k] == text[k + period]:
                k += 1
            copies = (k - j) // period + 1  # text[j:k] 与 text[j+period:k+period] 相同
            if copies >= RULE["min_copies"] and (best is None or copies * period > best["run_chars"]):
                best = {"period": period, "start": j, "copies": copies, "run_chars": copies * period}
            j = k + 1
    return best


def _recurring_chars(text: str) -> int:
    """合格的非相邻复现子串覆盖的字符数（次数 × 长度）的最大值；没有时为 0。"""
    n = len(text)
    best = 0
    for length in range(RULE["min_length"], n // RULE["min_count"] + 1):
        for sub in {text[i:i + length] for i in range(n - length + 1)}:
            count = text.count(sub)  # str.count 即不重叠计数
            if count >= RULE["min_count"]:
                best = max(best, count * length)
    return best


def _covers(chars: int, total: int) -> bool:
    return total > 0 and round(chars / total, 4) >= RULE["min_coverage"]  # 四舍五入到 4 位，同研究侧


def check(text: str) -> bool:
    """窗口文字是否命中 `repeat-strict`。无法规范化的文字（跨簇 NFKC 组合）不命中。"""
    try:
        norm = normalize(text).text
    except ValueError:
        return False
    run = _tandem(norm)
    return (run is not None and _covers(run["run_chars"], len(norm))) or _covers(_recurring_chars(norm), len(norm))


def apply(text: str) -> tuple[str, dict[str, Any] | None]:
    """未命中返回 (原文, None)。命中返回 (新文字, 记录 `{rule, action, period, copies, removed_raw_chars}`)：

    - `action = "collapse"`：新文字为折叠后的原文；
    - `action = "blank"`：折叠后仍命中或没有可折叠的相邻重复，调用方应把该窗置空，返回的文字仍是原文。
      此时 `period`／`copies`／`removed_raw_chars` 描述被放弃的折叠，没有可折叠区段时为 None／None／0。
    """
    if not check(text):
        return text, None
    norm = normalize(text)
    run = _tandem(norm.text)
    if run is None or not _covers(run["run_chars"], len(norm.text)):
        return text, {"rule": RULE["rule"], "action": "blank", "period": None, "copies": None, "removed_raw_chars": 0}
    first_end = run["start"] + run["period"]
    cut_start = norm.raw_spans[first_end - 1][1]                      # 第一个单元在原文里的结束
    cut_end = norm.raw_spans[run["start"] + run["run_chars"] - 1][1]  # 整段重复在原文里的结束
    collapsed = text[:cut_start] + text[cut_end:]
    record = {"rule": RULE["rule"], "action": "collapse", "period": run["period"], "copies": run["copies"],
              "removed_raw_chars": cut_end - cut_start}
    if check(collapsed):
        return text, {**record, "action": "blank"}
    return collapsed, record
