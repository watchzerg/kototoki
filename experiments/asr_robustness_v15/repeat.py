"""显式重复检测器（票据 01 定义，02 的"折叠重复"动作与之一致）。

在规范化文本（`kototoki_eval.schema.normalize`：NFKC、去标点与空白）上算两个信号：

- **tandem（相邻重复）**：对每个周期 p（1 ≤ p ≤ n/3），找满足 s[j] == s[j+p] 的最长连续区段，得到一段由同一个
  长度 p 的单元连续重复 copies = ⌊L/p⌋ + 1 次的区间，run_chars = copies × p。取 run_chars 最大（并列取 p 小）的一段。
  例：`うっ…うっ…うっ…`（HF III 第 51 窗）规范化后为 `うっうっうっ…`，p = 2、copies ≈ 21。
- **recurring（非相邻复现）**：长度 L ≥ 3 的某个子串在文本里不重叠地出现 count ≥ 3 次，取 count × L 最大的子串。
  覆盖 `A B A B A` 这种交替复读。

coverage = 该信号覆盖的字符数 / 规范化字符数。规则参数：`min_period`（tandem 单元最短长度；p = 1 的 `ああああ` 多为
真实呼喊，但同一字符连写 ≥ 2 × min_copies 个时仍以 p = 2 计入）、`min_copies`、`min_coverage`；recurring 另有
`min_length`、`min_count`。信号按规则参数计算（`signals(text, rule)`），再由 `flagged` 查覆盖率。

折叠（`collapse`）：在**原文**上做——先找到规范化文本里被标记的 tandem 区段，把规范化字符位置映射回原文位置
（`normalize` 的 `raw_spans`），保留第一个重复单元之前的原文与第一个单元本身，删掉其后各次重复所占的原文区间
（含夹在其中的标点），区段之后的原文照抄。
"""

from __future__ import annotations

from typing import Any

from kototoki_eval.schema import normalize

RULE_DEFAULT = {"min_period": 2, "min_copies": 6, "min_coverage": 0.5, "min_count": 6, "min_length": 3}


def tandem_runs(text: str, *, min_copies: int = 3) -> list[dict[str, Any]]:
    """全部满足 copies ≥ min_copies 的极大相邻重复区段：`{period, start, copies, run_chars}`（位置为规范化文本下标）。"""
    n = len(text)
    runs = []
    for p in range(1, n // min_copies + 1):
        j = 0
        while j + p < n:
            if text[j] != text[j + p]:
                j += 1
                continue
            k = j
            while k + p < n and text[k] == text[k + p]:
                k += 1
            matched = k - j  # s[j..k) 与 s[j+p..k+p) 相同
            copies = matched // p + 1
            if copies >= min_copies:
                runs.append({"period": p, "start": j, "copies": copies, "run_chars": copies * p})
            j = k + 1
    return runs


def best_tandem(text: str, *, min_period: int = 1, min_copies: int = 3) -> dict[str, Any] | None:
    runs = [r for r in tandem_runs(text, min_copies=min_copies) if r["period"] >= min_period]
    if not runs:
        return None
    best = max(runs, key=lambda r: (r["run_chars"], -r["period"]))
    return {**best, "coverage": round(best["run_chars"] / len(text), 4) if text else 0.0}


def best_recurring(text: str, *, min_length: int = 3, min_count: int = 3) -> dict[str, Any] | None:
    """不重叠出现 ≥ min_count 次、count × L 最大的子串；并列取更长的。"""
    n = len(text)
    best: dict[str, Any] | None = None
    for length in range(min_length, n // min_count + 1):
        seen: dict[str, int] = {}
        for i in range(n - length + 1):
            seen[text[i:i + length]] = seen.get(text[i:i + length], 0) + 1
        for sub, overlapping in seen.items():
            if overlapping < min_count:
                continue
            count, i = 0, 0
            while True:
                i = text.find(sub, i)
                if i < 0:
                    break
                count += 1
                i += length
            if count >= min_count and (best is None or count * length > best["covered"]
                                       or (count * length == best["covered"] and length > best["length"])):
                best = {"length": length, "count": count, "covered": count * length}
    if best is None:
        return None
    return {**best, "coverage": round(best["covered"] / n, 4)}


def signals(raw_text: str, rule: dict[str, Any] = RULE_DEFAULT) -> dict[str, Any]:
    """按规则参数算信号：tandem 只在 period ≥ min_period、copies ≥ min_copies 的区段里取最长，recurring 只在
    count ≥ min_count 的子串里取覆盖最大。参数不同，"最佳"区段可能不同（纯重复字符 `あああ…` 同时满足所有周期，
    默认取最小周期），所以每条规则各算一份，而不是从一份"最佳"上再筛阈值。"""
    text = normalize(raw_text).text
    return {"norm_chars": len(text), "rule": {k: rule[k] for k in ("min_period", "min_copies", "min_length", "min_count")},
            "tandem": best_tandem(text, min_period=rule["min_period"], min_copies=rule["min_copies"]),
            "recurring": best_recurring(text, min_length=rule["min_length"], min_count=rule["min_count"])}


def flagged(signal: dict[str, Any], rule: dict[str, Any] = RULE_DEFAULT) -> bool:
    t, r = signal.get("tandem"), signal.get("recurring")
    if t and t["period"] >= rule["min_period"] and t["copies"] >= rule["min_copies"] and t["coverage"] >= rule["min_coverage"]:
        return True
    if r and r["length"] >= rule["min_length"] and r["count"] >= rule["min_count"] and r["coverage"] >= rule["min_coverage"]:
        return True
    return False


def collapse(raw_text: str, rule: dict[str, Any] = RULE_DEFAULT) -> tuple[str, dict[str, Any]]:
    """折叠被规则标记的 tandem 区段（只折叠 tandem；recurring 单独命中时不改文字）。返回 (新文字, 记录)。"""
    norm = normalize(raw_text)
    text = norm.text
    t = best_tandem(text, min_period=rule["min_period"], min_copies=rule["min_copies"])
    if t is None or t["coverage"] < rule["min_coverage"]:
        return raw_text, {"collapsed": False}
    first_end = t["start"] + t["period"]            # 第一个单元之后（规范化下标）
    run_end = t["start"] + t["run_chars"]           # 区段结束（规范化下标）
    spans = norm.raw_spans                            # 每个规范化字符对应的原文 [start, end)
    raw_cut_start = spans[first_end - 1][1]           # 第一个单元最后一个字符在原文里的结束
    raw_cut_end = spans[run_end - 1][1]               # 区段最后一个字符在原文里的结束
    collapsed = raw_text[:raw_cut_start] + raw_text[raw_cut_end:]
    return collapsed, {"collapsed": True, "period": t["period"], "copies": t["copies"],
                       "removed_raw_chars": raw_cut_end - raw_cut_start, "removed_norm_chars": run_end - first_end,
                       "chars_before": len(raw_text), "chars_after": len(collapsed)}


__all__ = ["RULE_DEFAULT", "best_recurring", "best_tandem", "collapse", "flagged", "signals", "tandem_runs"]
