"""专名表后处理替换（票据 03）：按日文锚定的 cue，把译文里专名的各种写法整段替换成表里的统一中文。

纯 CPU，不调用模型。落点只有两层，找不到就不动、只记日志。
表为 name-table-v2：每个实体有若干写法 forms（日文 → 对应的中文目标），另有模型列的 zh_variants。
1. 锚定：cue 的日文里出现的最长 form.ja 锚定该 cue，替换目标是该 form 的 zh（シロウ → 士郎，衛宮士郎 → 卫宫士郎）；
   同一实体的短 form 不再处理已被长 form 锚定的 cue。
2. 落点：先在该 cue 译文里找 (a) 同实体其他 form 的 zh、(b) 过特异性过滤的 zh_variants
   （a ≥ 1 且 a / (a + b) ≥ MIN_RATIO，a／b 为本 form 锚定的 cue 与其余 cue 里的出现数）；
   再用 experiments.quality_v5.consistency 的跨 cue 统计（只统计本 form 锚定的 cue，粒度与目标一致）。
3. 替换：只在锚定 cue 内、整段替换成目标；两个实体的落点重叠时都不动，记为 overlap。
   落点是目标的真子串（远坂 之于 远坂凛）是省略形：不替换，记 partial_canonical；
   落点包含目标（卫宫士郎 之于 士郎）说明已是更长的写法：不缩短，记 already_canonical。

统计层落点会向左右扩展到周围连续汉字串内有跨 cue 支持的最长超串（因茨贝伦 → 艾因茨贝伦），
changes 里记 extended_from。落点（扩展后）紧邻 ·／・ 或拉丁字母时不替换，记 compound（可能是复合名的一段，如 安里·玛尤）。
--min-confidence 低于阈值的实体整条跳过，列在 summary 的 entries_skipped_confidence。

统计层候选含单字；互为子串的候选只留锚定 cue 最多的一个作主候选，扩展要求超串的支持不少于原落点的一半。
最终落点两侧若紧邻清单外的汉字（BOUNDARY_CHARS）说明没落在词边界上，不替换，记 boundary（变体层同样适用）。
目标名核对：form.zh 必须出现在同实体同目标的 form 锚定的 cue 里（appears），或与译者的主写法接近（near），
或是职阶的纯 ASCII 名（class_ascii）；否则整个 form 不动，记 unverified_name 并列入 summary 的 unverified_forms。
默认关闭（第二轮证明误拦多于拦对，已放弃），--name-check 打开，只作对照。

已知限制：单字的 form.ja（如 凛）会过度锚定（任何含该字的 cue 都被锚定），目前不处理。

命令（仓库根目录）：
  python -X utf8 -m experiments.name_consistency.apply_table --table table.json --ja ja.srt --zh zh.srt --out-dir DIR [--min-confidence low|medium|high]
  python -X utf8 -m experiments.name_consistency.apply_table measure --pair NAME JA.srt ZH.srt [--pair ...] --out FILE
"""

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from experiments.quality_v5 import consistency

SCHEMA = "name-table-v2"
CONFIDENCE_LEVELS = {"low": 0, "medium": 1, "high": 2}
MIN_SUPPORT = 2  # 统计候选至少在这么多条锚定 cue 内出现
MIN_RATIO = 0.8  # 候选出现的 cue 中，锚定 cue 至少占这个比例（特异性）
MIN_SHARE = 0.04  # 相对支持度：至少占锚定 cue 数的这个比例，防止锚定很多的条目被偶发短语带偏
MAX_EXTEND = 6  # 统计层落点向左右扩展时，最多比原落点长这么多字
EXTEND_SHARE = 0.5  # 扩展后的超串至少要有原落点这么大比例的锚定 cue 支持，否则 叫白 之类语境串会取代 白
# 可以紧挨在专名旁边的常见虚词／动词单字，属人工判断的经验清单，不是穷举；落点另一侧若是清单外的汉字，视为没落在词边界上
BOUNDARY_EXTRA = "叫是和跟与及或把被让给对向从为比像说想看听问找杀救帮爱恨等请快别来去回着了的吗吧呢啊呀哦嗯哟也都就才还又再只已"
BOUNDARY_CHARS = frozenset(consistency.EDGE_STOP) | frozenset(BOUNDARY_EXTRA)
BLOCK_SEPARATOR = re.compile(r"\r?\n(?:[ \t]*\r?\n)+")
BLOCK_HEAD = re.compile(r"(\d+)[ \t]*\r?\n([^\r\n]*-->[^\r\n]*)(?:\r?\n|\Z)")


@dataclass
class Cue:
    number: int
    text: str
    start: int  # 文本在原文件内容中的起止偏移，用于原样写回
    end: int


def parse_srt(content: str) -> list[Cue]:
    """按块解析；只记录文本的偏移，其余字节写回时原样保留。"""
    cues = []
    position = 0
    for separator in [*BLOCK_SEPARATOR.finditer(content), None]:
        end = separator.start() if separator else len(content.rstrip("\r\n"))
        if end > position:
            head = BLOCK_HEAD.match(content, position, end)
            if not head:
                raise ValueError(f"unparsable SRT block near offset {position}")
            cues.append(Cue(int(head.group(1)), content[head.end():end], head.end(), end))
        if separator:
            position = separator.end()
    return cues


def read_srt(path: Path) -> tuple[str, list[Cue]]:
    with open(path, encoding="utf-8-sig", newline="") as handle:  # 保留原换行符
        content = handle.read()
    return content, parse_srt(content)


def find_spans(text: str, candidates: list[str]) -> list[tuple[int, int, str]]:
    """候选串在 text 里的全部出现位置，长的优先占位，已占位置不再被短串重复匹配。"""
    occupied = [False] * len(text)
    spans = []
    for candidate in sorted({c for c in candidates if c}, key=lambda c: (-len(c), c)):
        start = text.find(candidate)
        while start != -1:
            end = start + len(candidate)
            if not any(occupied[start:end]):
                occupied[start:end] = [True] * len(candidate)
                spans.append((start, end, candidate))
                start = text.find(candidate, end)
            else:
                start = text.find(candidate, start + 1)
    return sorted(spans)


@dataclass
class Match:
    layer: str
    spans: list[tuple[int, int, str]]
    extended_from: dict[tuple[int, int], str] = field(default_factory=dict)  # 扩展后的落点 (起, 止) -> 原落点文本


def entity_forms(entity: dict) -> list[dict]:
    """实体的全部写法（按日文去重）；entity_ja 不在 forms 里时用实体的 zh 补一条。"""
    forms, seen = [], set()
    for form in [*entity.get("forms", []), {"ja": entity["entity_ja"], "zh": entity["zh"]}]:
        if form["ja"] and form["ja"] not in seen:
            seen.add(form["ja"])
            forms.append(form)
    return forms


def assign_forms(forms: list[dict], ja_cues: list[Cue]) -> list[list[int]]:
    """每个 cue 只由日文里出现的最长 form.ja 锚定（短 form 不重复处理同一 cue）；返回各 form 的锚定 cue 下标。"""
    order = sorted(range(len(forms)), key=lambda f: (-len(forms[f]["ja"]), f))
    anchored: list[list[int]] = [[] for _ in forms]
    for i, cue in enumerate(ja_cues):
        for f in order:
            if forms[f]["ja"] in cue.text:
                anchored[f].append(i)
                break
    return anchored


NAME_CHARS = re.compile(r"[一-鿿A-Za-z·・]+")


def shape_problem(candidate: str, zh: str, max_len: int | None) -> str | None:
    """候选的形状问题：字符集、长度、首尾虚词、是否 zh 的超串；没有问题返回 None。"""
    if not NAME_CHARS.fullmatch(candidate) or (max_len is not None and len(candidate) > max_len):
        return "shape"
    if candidate[0] in consistency.EDGE_STOP or candidate[-1] in consistency.EDGE_STOP:
        return "edge_stop"
    if candidate != zh and zh in candidate:
        return "superstring_of_zh"
    return None


def support(lowered: list[str], inside: set[int], candidate: str) -> tuple[int, int]:
    """候选出现在锚定 cue（a）与非锚定 cue（b）的 cue 数，不区分大小写。"""
    needle = candidate.lower()
    a = sum(1 for i in inside if needle in lowered[i])
    b = sum(1 for i, text in enumerate(lowered) if i not in inside and needle in text)
    return a, b


def usable_variants(variants: list[str], zh: str, lowered: list[str], inside: set[int]) -> tuple[list[str], list[dict]]:
    """过滤模型给的 zh_variants：同一角色的别名或无关词不能当成该专名的写法去替换。

    形状同统计候选（不限长度，复合名可以很长）；特异性 a ≥ 1 且 a / (a + b) ≥ MIN_RATIO。
    a／b 是该候选在本 form 锚定的 cue 与其余全部 cue 里的出现数。
    zh（本 form 的目标）本身与 zh 的真子串（省略形）不过滤：前者无需替换，后者靠它识别 partial_canonical。
    """
    kept, dropped = [], []
    for variant in dict.fromkeys(variants):
        if not variant or variant == zh:
            continue
        if variant in zh:
            kept.append(variant)
            continue
        a, b = support(lowered, inside, variant)
        reason = shape_problem(variant, zh, None)
        if reason is None and (a < 1 or a / (a + b) < MIN_RATIO):
            reason = "specificity"
        if reason:
            dropped.append({"text": variant, "reason": reason, "anchored": a, "other": b})
        else:
            kept.append(variant)
    return kept, dropped


class StatLayer:
    """某个条目在其锚定 cue 内的跨 cue 统计：主译法、替代译法。

    consistency 给出的 alternatives 带大量语境 n-gram，所以每个候选先过形状与特异性过滤才能当落点：
    形状：1–6 字，只含 CJK／拉丁／间隔点，首尾不是虚词，不是 zh 的超串；
    特异性：锚定 cue 内含它的 cue 数 a ≥ 2，且 a / (a + b) ≥ 0.8（b 为非锚定 cue 内含它的数）；
    另加相对支持度：a ≥ 锚定 cue 数的 4%（锚定很多的条目，如单字日文变体过度锚定的，偶发 2 次的语境短语不算）。
    """

    RUN_CHAR = re.compile(r"[一-鿿A-Za-z·・]")

    def __init__(self, zh: str, zh_texts: list[str], anchored: list[int]):
        inside = set(anchored)
        self.min_anchored = max(MIN_SUPPORT, math.ceil(MIN_SHARE * len(inside)))
        self.lowered = [text.lower() for text in zh_texts]
        self.inside = inside
        background: dict[str, int] = defaultdict(int)
        for i, text in enumerate(zh_texts):
            if i not in inside:
                for gram in consistency.zh_grams(text):
                    background[gram] += 1
        result = consistency.analyze_term("", [zh_texts[i] for i in anchored], background)
        self.kept: list[dict] = []
        self.dropped: list[dict] = []
        self.zh = zh
        self.rendering: str | None = None
        self.alternatives: list[str] = []
        # 候选池：consistency 的主译法与替代译法（2–6 字），加上锚定 cue 里反复出现的单个汉字（如 白）
        pool = [c for c in [result.rendering, *result.alternatives] if c]
        accepted = [c for c in dict.fromkeys(pool) if self.accept(c)]
        char_cues: dict[str, int] = defaultdict(int)
        for i in inside:
            for ch in {ch for ch in zh_texts[i] if "一" <= ch <= "鿿"}:
                char_cues[ch] += 1
        singles = [ch for ch, n in sorted(char_cues.items()) if n >= self.min_anchored and ch not in pool]
        accepted += [ch for ch in singles if self.accept(ch, record=False)]
        # 互为子串的候选算一族，每族只留锚定 cue 数最多的（并列取更长的）作主候选；族内其余串只在扩展时参考
        bases: list[str] = []
        for candidate in sorted(accepted, key=lambda c: (-self.counts(c)[0], -len(c), c)):
            if not any(candidate in base or base in candidate for base in bases):
                bases.append(candidate)
                if candidate in singles:
                    a_count, b_count = self.counts(candidate)
                    self.kept.append({"text": candidate, "anchored": a_count, "other": b_count})
        self.rendering, self.alternatives = (bases[0], bases[1:]) if bases else (None, [])
        # 近形变体（亚丝娜／亚斯娜）以最长且支持最多的多字候选为参照，不受单字主候选影响
        long_ones = [c for c in accepted if len(c) >= 3]
        self.near_base = max(long_ones, key=lambda c: (self.counts(c)[0], len(c), c)) if long_ones else None

    def counts(self, candidate: str) -> tuple[int, int]:
        return support(self.lowered, self.inside, candidate)

    def accept(self, candidate: str, near: bool = False, record: bool = True) -> bool:
        """过滤并记录；near 为近形变体（只在个别 cue 出现，不要求 a ≥ 2）；record=False 时不记落选（单字池太大）。"""
        a, b = self.counts(candidate)
        reason = shape_problem(candidate, self.zh, 6)
        if reason is None and (a < (1 if near else self.min_anchored) or a / max(a + b, 1) < MIN_RATIO):
            reason = "specificity"
        item = {"text": candidate, "anchored": a, "other": b}
        record_it = record
        if reason:
            if not near and record_it:
                self.dropped.append({**item, "reason": reason})
            return False
        if not near and record_it:
            self.kept.append(item)
        return True

    def extend(self, text: str, start: int, end: int) -> tuple[int, int]:
        """把落点向左右扩展到周围连续 CJK／拉丁／间隔点串内的最长且有统计支持的超串；没有则原样返回。

        支持度口径同候选过滤（锚定 cue 数、特异性、相对支持度），另要求不少于原落点锚定 cue 数的 EXTEND_SHARE；
        超串首尾不是虚词，也不含整个 zh。
        含间隔点的超串必须覆盖整段连续串（两端都到 CJK／拉丁／间隔点串的边界），否则会把 艾米亚·希罗 截成 米亚·希罗。
        """
        run_start, run_end = start, end
        while run_start > 0 and self.RUN_CHAR.match(text[run_start - 1]):
            run_start -= 1
        while run_end < len(text) and self.RUN_CHAR.match(text[run_end]):
            run_end += 1
        best, best_key = (start, end), (0, 0)
        needed = max(self.min_anchored, EXTEND_SHARE * self.counts(text[start:end])[0])
        for left in range(0, min(start - run_start, MAX_EXTEND) + 1):
            for right in range(0, min(run_end - end, MAX_EXTEND - left) + 1):
                if left + right == 0:
                    continue
                superstring = text[start - left:end + right]
                if (superstring[0] in consistency.EDGE_STOP or superstring[-1] in consistency.EDGE_STOP
                        or superstring[0] in "·・" or superstring[-1] in "·・"
                        or (self.zh in superstring and superstring != self.zh)):
                    continue
                if ("·" in superstring or "・" in superstring) and (start - left, end + right) != (run_start, run_end):
                    continue
                a, b = self.counts(superstring)
                if a >= needed and a / (a + b) >= MIN_RATIO and (len(superstring), a) > best_key:
                    best, best_key = (start - left, end + right), (len(superstring), a)
        return best

    def candidates(self, text: str) -> list[str]:
        found = [a for a in self.alternatives if a in text]
        if self.rendering and self.rendering in text:
            found.append(self.rendering)
        if self.near_base and self.near_base not in text:
            near = consistency.variant_in(self.near_base, text)
            if near and self.accept(near, near=True):
                found.append(near)
        return found


def extend_spans(match: Match, target: str, found: list[str], text: str, stat: StatLayer) -> Match:
    """统计层落点尝试向外扩展（艾因茨贝伦 而不是 因茨贝伦）；目标本身和它的省略形不扩展。"""
    spans, last_end = [], 0
    for start, end, span_text in match.spans:
        if start < last_end:
            continue  # 已被前一个扩展后的落点吞并
        if span_text in found and span_text not in target:
            new_start, new_end = stat.extend(text, start, end)
            if (new_start, new_end) != (start, end):
                match.extended_from[(new_start, new_end)] = span_text
                start, end, span_text = new_start, new_end, text[new_start:new_end]
        spans.append((start, end, span_text))
        last_end = end
    match.spans = spans
    return match


@dataclass
class Unit:
    """一个实体的一种写法（form）：该写法锚定的 cue 都以它的 zh 为替换目标。"""
    entity: int
    form_ja: str
    target: str
    others: list[str]  # 同一实体其他写法的 zh 中与目标互相包含的，也是候选落点
    anchored: list[int]
    variants: list[str]  # 过滤后的 zh_variants
    variants_dropped: list[dict]
    stat: "StatLayer | None" = None
    name_check: str | None = None


def locate(unit: Unit, text: str, stat: StatLayer | None) -> Match | None:
    """先找过滤后的 zh_variants 与同实体其他写法的 zh（含目标本身），再用统计层；都没有返回 None。"""
    spans = find_spans(text, [*unit.variants, *unit.others, unit.target])
    if spans:
        return Match("variant", spans)
    if stat is not None:
        found = stat.candidates(text)
        if found:
            match = Match("stat", find_spans(text, [*found, *unit.others, unit.target]))
            return extend_spans(match, unit.target, found, text, stat)
    return None


def to_replace(target: str, match: Match) -> list[tuple[int, int, str]]:
    """需要替换的落点：不等于目标、不是目标的真子串（省略形）、也不包含目标（已是更长的写法）。"""
    return [span for span in match.spans if span[2] not in target and target not in span[2]]


COMPOUND_JOINER = re.compile(r"[·・A-Za-z]")


def in_compound(text: str, start: int, end: int) -> bool:
    """落点紧邻间隔点或拉丁字母：可能只是 安里·玛尤 之类复合名的一段，整段替换会拼坏。"""
    return bool((start > 0 and COMPOUND_JOINER.match(text[start - 1])) or
                (end < len(text) and COMPOUND_JOINER.match(text[end])))


def overlapping(a: Match, b: Match) -> bool:
    return any(s1 < e2 and s2 < e1 for s1, e1, _ in a.spans for s2, e2, _ in b.spans)


def bad_boundary(text: str, start: int, end: int) -> bool:
    """落点紧邻的汉字不在 BOUNDARY_CHARS 里：它多半只是更长词（或更长名字）的一段，不是完整的名字。"""
    return any("一" <= text[k] <= "鿿" and text[k] not in BOUNDARY_CHARS
               for k in (start - 1, end) if 0 <= k < len(text))


def is_near_name(target: str, rendering: str) -> bool:
    """目标与译者实际用的主写法接近：等长且编辑距离 ≤ 1（伊莉亚／伊莉雅），或目标至少一半汉字出现在主写法里。"""
    if len(target) == len(rendering) and consistency.edit_distance(target, rendering) <= 1:
        return True
    chars = [ch for ch in target if "一" <= ch <= "鿿"]
    return bool(chars) and sum(ch in rendering for ch in chars) / len(chars) >= 0.5


COUNTERS = ("anchored", "replaced_variant", "replaced_stat", "already_canonical", "partial_canonical",
            "unresolved_not_found", "unresolved_overlap", "unresolved_compound", "unresolved_boundary",
            "unresolved_unverified_name")


def apply_table(table: dict, ja_cues: list[Cue], zh_cues: list[Cue], min_confidence: str = "low",
                name_check: bool = False) -> dict:
    zh_texts = [cue.text for cue in zh_cues]
    lowered = [text.lower() for text in zh_texts]
    entities = table["entries"]
    threshold = CONFIDENCE_LEVELS[min_confidence]
    skipped = [{"entity_ja": entity["entity_ja"], "confidence": entity.get("confidence")} for entity in entities
               if CONFIDENCE_LEVELS.get(entity.get("confidence", "high"), 2) < threshold]
    skipped_names = {item["entity_ja"] for item in skipped}

    units: list[Unit] = []
    for e, entity in enumerate(entities):
        if entity["entity_ja"] in skipped_names:
            continue
        forms = entity_forms(entity)
        for form, anchored in zip(forms, assign_forms(forms, ja_cues)):
            target = form["zh"]
            kept, dropped = usable_variants(entity.get("zh_variants", []), target, lowered, set(anchored))
            # 其他 form 的 zh 只在与目标互相包含时才是候选（卫宫士郎 之于 士郎）；互不相干的（卫宫 之于 士郎）不是
            others = [f["zh"] for f in forms if f["zh"] and f["zh"] != target and (target in f["zh"] or f["zh"] in target)]
            units.append(Unit(e, form["ja"], target, others, anchored, kept, dropped))

    def stat_of(unit: Unit) -> StatLayer | None:
        if unit.stat is None and unit.anchored:
            unit.stat = StatLayer(unit.target, zh_texts, unit.anchored)
        return unit.stat

    # 目标名核对：目标 zh 必须得到译者自己用法的佐证，否则整个 form 不动
    unverified: list[dict] = []
    for unit in units:
        if not unit.anchored:
            continue
        if not name_check:
            unit.name_check = "disabled"
            continue
        siblings = [v for v in units if v.entity == unit.entity and v.target == unit.target]
        if any(unit.target in zh_texts[i] for v in siblings for i in v.anchored):
            unit.name_check = "appears"
        elif any(is_near_name(unit.target, rendering) for v in siblings if stat_of(v)
                 for rendering in [stat_of(v).rendering, stat_of(v).near_base, *stat_of(v).alternatives] if rendering):
            unit.name_check = "near"
        elif entities[unit.entity].get("kind") == "class" and unit.target.isascii():
            unit.name_check = "class_ascii"
        else:
            unit.name_check = "unverified"
            stat = stat_of(unit)
            unverified.append({"entity_ja": entities[unit.entity]["entity_ja"], "form_ja": unit.form_ja,
                               "target": unit.target, "anchored": len(unit.anchored),
                               "dominant_rendering": stat.rendering if stat else None})

    matches: dict[tuple[int, int], Match | None] = {}
    for u, unit in enumerate(units):
        if unit.name_check == "unverified":
            continue
        pending = []
        for i in unit.anchored:
            matches[(u, i)] = locate(unit, zh_texts[i], None)
            if matches[(u, i)] is None:
                pending.append(i)
        if pending:
            stat = stat_of(unit)
            for i in pending:
                matches[(u, i)] = locate(unit, zh_texts[i], stat)

    per_cue: dict[int, list[int]] = defaultdict(list)
    for (u, i), match in matches.items():
        if match is not None:
            per_cue[i].append(u)
    overlapped: set[tuple[int, int]] = set()
    for i, us in per_cue.items():
        for x in us:
            for y in us:
                if x < y and overlapping(matches[(x, i)], matches[(y, i)]):
                    for u in (x, y):
                        if to_replace(units[u].target, matches[(u, i)]):
                            overlapped.add((u, i))

    changes, unresolved = [], []
    edits: dict[int, list[tuple[int, int, str]]] = defaultdict(list)
    rows = []
    for u, unit in enumerate(units):
        entity = entities[unit.entity]
        stat = unit.stat
        row = {"form_ja": unit.form_ja, "target": unit.target, **dict.fromkeys(COUNTERS, 0),
               "anchored": len(unit.anchored), "name_check": unit.name_check,
               "stat_rendering": stat.rendering if stat else None,
               "stat_alternatives": stat.alternatives if stat else [],
               "zh_variants_dropped": unit.variants_dropped,
               "stat_candidates_kept": stat.kept if stat else [],
               "stat_candidates_dropped": stat.dropped if stat else []}
        for i in unit.anchored:
            match = matches.get((u, i))
            record = {"index": ja_cues[i].number, "ja": ja_cues[i].text, "zh": zh_cues[i].text,
                      "entry": entity["entity_ja"], "form_ja": unit.form_ja, "target": unit.target}
            if unit.name_check == "unverified":
                row["unresolved_unverified_name"] += 1
                unresolved.append({**record, "reason": "unverified_name"})
            elif match is None:
                row["unresolved_not_found"] += 1
                unresolved.append({**record, "reason": "not_found"})
            elif (u, i) in overlapped:
                row["unresolved_overlap"] += 1
                unresolved.append({**record, "reason": "overlap"})
            else:
                todo = to_replace(unit.target, match)
                if not todo:
                    full = any(unit.target in span[2] for span in match.spans)
                    row["already_canonical" if full else "partial_canonical"] += 1
                    continue
                if any(in_compound(zh_cues[i].text, start, end) for start, end, _ in todo):
                    row["unresolved_compound"] += 1
                    unresolved.append({**record, "reason": "compound"})
                    continue
                # 边界：紧邻清单外的汉字说明落点只是更长词的一段，该落点不动；一个落点都不剩才记 boundary
                todo = [span for span in todo if not bad_boundary(zh_cues[i].text, span[0], span[1])]
                if not todo:
                    row["unresolved_boundary"] += 1
                    unresolved.append({**record, "reason": "boundary"})
                    continue
                row[f"replaced_{match.layer}"] += 1
                edits[i].extend((start, end, unit.target) for start, end, _ in todo)
                for text in sorted({span[2] for span in todo}):
                    change = {"_cue": i, "index": ja_cues[i].number, "ja": ja_cues[i].text,
                              "zh_before": zh_cues[i].text, "entry": entity["entity_ja"], "form_ja": unit.form_ja,
                              "target": unit.target, "span": text, "count": sum(s[2] == text for s in todo),
                              "layer": match.layer}
                    origins = {match.extended_from[s[:2]] for s in todo if s[2] == text and s[:2] in match.extended_from}
                    if origins:
                        change["extended_from"] = sorted(origins)[0]
                    changes.append(change)
        rows.append(row)

    new_texts = list(zh_texts)
    for i, spans in edits.items():
        text = zh_texts[i]
        for start, end, replacement in sorted(spans, reverse=True):
            text = text[:start] + replacement + text[end:]
        new_texts[i] = text
    for change in changes:
        change["zh_after"] = new_texts[change.pop("_cue")]

    per_entity = []
    for e, entity in enumerate(entities):
        forms_rows = [row for unit, row in zip(units, rows) if unit.entity == e]
        if not forms_rows:
            continue
        per_entity.append({"entity_ja": entity["entity_ja"], "zh": entity["zh"], "kind": entity.get("kind"),
                           "confidence": entity.get("confidence"),
                           **{key: sum(row[key] for row in forms_rows) for key in COUNTERS}, "forms": forms_rows})
    totals = {key: sum(row[key] for row in per_entity) for key in COUNTERS}
    totals["cues_changed"] = len(edits)
    totals["entries_with_replacements"] = sum(1 for row in per_entity if row["replaced_variant"] + row["replaced_stat"])
    return {"new_texts": new_texts, "changes": changes, "unresolved": unresolved,
            "summary": {"entries": per_entity, "entries_skipped_confidence": skipped,
                        "unverified_forms": unverified, "totals": totals}}


def render_srt(content: str, cues: list[Cue], new_texts: list[str]) -> str:
    out, position = [], 0
    for cue, text in zip(cues, new_texts):
        out.append(content[position:cue.start])
        out.append(text)
        position = cue.end
    out.append(content[position:])
    return "".join(out)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_apply(args: argparse.Namespace) -> int:
    table = json.loads(args.table.read_text(encoding="utf-8"))
    if table.get("schema") != SCHEMA:
        raise SystemExit(f"unexpected table schema: {table.get('schema')!r} (expected {SCHEMA})")
    ja_content, ja_cues = read_srt(args.ja)
    zh_content, zh_cues = read_srt(args.zh)
    if len(ja_cues) != len(zh_cues):
        raise SystemExit(f"cue count differs: ja {len(ja_cues)} vs zh {len(zh_cues)}")
    result = apply_table(table, ja_cues, zh_cues, args.min_confidence, args.name_check)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "zh.replaced.srt").write_bytes(render_srt(zh_content, zh_cues, result["new_texts"]).encode("utf-8"))
    write_jsonl(args.out_dir / "changes.jsonl", result["changes"])
    write_jsonl(args.out_dir / "unresolved.jsonl", result["unresolved"])
    summary = {"work": table.get("work"), "cues": len(zh_cues), **result["summary"]}
    (args.out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result["summary"]["totals"]))
    return 0


def run_measure(args: argparse.Namespace) -> int:
    """对每对 ja/zh 跑 consistency 的 srt 模式（进程内调用），记录不一致率，便于替换前后比较。"""
    report = {}
    for name, ja_path, zh_path in args.pair:
        ja, zh = consistency.read_srt_texts(Path(ja_path)), consistency.read_srt_texts(Path(zh_path))
        if len(ja) != len(zh):
            raise SystemExit(f"{name}: cue count differs ({len(ja)} vs {len(zh)})")
        results = consistency.analyze_work(list(zip(ja, zh)))
        report[name] = {**consistency.work_summary(results),
                        "alt_terms": [{"term": r.term, "rendering": r.rendering, "alternatives": r.alternatives,
                                       "main": r.main, "alt": r.alt, "alt_examples": r.alt_examples}
                                      for r in results if r.alt]}
        print(name, json.dumps({k: v for k, v in report[name].items() if k != "alt_terms"}))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "measure":
        parser = argparse.ArgumentParser(prog="apply_table measure", description="不一致率（替换前后各跑一次）")
        parser.add_argument("--pair", nargs=3, action="append", metavar=("NAME", "JA", "ZH"), required=True)
        parser.add_argument("--out", type=Path, required=True)
        return run_measure(parser.parse_args(argv[1:]))
    parser = argparse.ArgumentParser(description="按专名表对中文译文做后处理替换")
    parser.add_argument("--table", type=Path, required=True)
    parser.add_argument("--ja", type=Path, required=True)
    parser.add_argument("--zh", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--min-confidence", choices=list(CONFIDENCE_LEVELS), default="low",
                        help="低于该置信度的条目整条跳过（默认 low：全部应用）")
    parser.add_argument("--name-check", action="store_true", help="核对目标名是否得到译者用法的佐证（第二轮已放弃，只作对照）")
    return run_apply(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
