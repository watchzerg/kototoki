"""专名表建表：整份日文 SRT 一次送入 llama-server，取回 `name-table-v2` 表并归一（票据 03，设计见
ADR-0014 与 `docs/architecture/modules/name-consistency.md`）。

移植自 `experiments/name_consistency/build_table.py`（历史实现只复制，不导入），配置照抄 ADR-0013 冻结的最佳
已知配置：提示 v5、no-think 官方采样、`name-table-v2` JSON schema、程序兜底全开（zh 形状、称呼词黑名单、
evidence<3 的 person 降级、日文写法形状），不调参。`SYSTEM_PROMPT` 与研究脚本逐字节相同，`names.recipes` 的
sha256 钉子守护。

本模块不碰 server、不写文件、不打日志：对 llama-server 的调用只经两个注入的回调 `chat(body) -> dict`
（POST `/v1/chat/completions`）与 `tokenize(text) -> int`（`/tokenize` 计数）。表里的条目是转写内容，调用方
不得写进日志。
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from kototoki.srt import SourceDocument

PROMPT_VERSION = "build-table-prompt-v5"
SCHEMA = "name-table-v2"
KINDS = ("person", "class", "org", "place", "other")
CONFIDENCES = ("high", "medium", "low")
MAX_FORMS = 12
MAX_ITEMS = 8
MAX_ZH_LEN = 12
# person 条目 evidence 里的 cue 少于此数，confidence 不得为 high（与提示里的规则一致）。
MIN_HIGH_PERSON_CUES = 3
# 称呼词黑名单：亲属称呼、人称代词、泛称。マスター／サーヴァント 在作品里是职阶，第一轮已决定可译，故不列。
HONORIFIC_JA = (
    "父さん", "父様", "お父さん", "父上", "母さん", "母様", "お母さん", "母上",
    "姉さん", "お姉ちゃん", "お姉さん", "姉上", "兄さん", "お兄ちゃん", "お兄さん", "兄上",
    "先輩", "後輩", "先生", "あの人", "あの方", "お主", "貴様", "お前", "あんた",
    "君", "僕", "俺", "私", "わたし", "あたし", "彼", "彼女", "皆", "みんな",
    "お嬢様", "お嬢さん", "坊や", "おじさん", "おばさん", "じいさん", "ばあさん",
)
_HONORIFIC_PREFIXES = ("お", "ご")
_HONORIFIC_SUFFIXES = ("さん", "さま", "様", "ちゃん", "くん", "君")
SEPARATORS = "·・"
# 中文译名只许由 CJK 统一表意文字（含扩展 A）、间隔号 ·／・、ASCII 字母组成；括号、空白、数字、冒号等
# 多半是模型夹带的注释（如"间桐(误识为Makiri)"）。长度按去掉间隔号后的字数算，1–12。
ZH_SHAPE = re.compile(r"[㐀-䶿一-鿿" + SEPARATORS + r"A-Za-z]+")

# 日文写法形状：只许汉字（含々）、平假名、片假名、长音符 ー、间隔号 ・／·；句子、短语、带助词或标点的写法一律不要。
MAX_JA_LEN = 20
_KANJI = "㐀-䶿一-鿿々𠀀-𯿿"
_KANJI_RUN = re.compile("[" + _KANJI + "]+")
_HIRAGANA_RE = re.compile("[ぁ-ゖ]")
JA_SHAPE = re.compile("[" + _KANJI + "ぁ-ゖァ-ヺー" + SEPARATORS + "]+")
# 含汉字或片假名的写法里，平假名只许作开头的 お／ご 或结尾的敬称；其余（助词、活用尾）说明是短语。
_JA_HIRAGANA_PREFIXES = ("お", "ご")
_JA_HIRAGANA_SUFFIXES = ("さん", "くん", "ちゃん", "さま", "たん")
# 汉字 的 紧邻片假名（的ミオリ、ミオリ的）是模型把中文的"的"夹进了日文名。的場 之类的姓不受影响。
_DE_NEXT_TO_KATAKANA = re.compile("的[ァ-ヺー]|[ァ-ヺー]的")


# 请求与预算常量（配方 `names.recipes.BUILD` 引用）：上下文 20480 减输出上限与 512 余量得到提示预算。
# `PROMPT_BUDGET` 是 system+user 两段文本的 token 总上限；512 余量留给 chat 模板与控制 token。
MAX_TOKENS = 4096
CONTEXT_SIZE = 20480
PROMPT_GUARD_TOKENS = 512
PROMPT_BUDGET = CONTEXT_SIZE - MAX_TOKENS - PROMPT_GUARD_TOKENS
ATTEMPTS = 2
SEED_STEP = 1
HONORIFIC_VERSION = "honorific-blacklist-v1"

SYSTEM_PROMPT = """你是日本动画／电影字幕的专名整理员。用户给出的是一部作品日语字幕轨的 ASR（自动语音识别）转写稿，每行格式为"cue 编号<TAB>日文台词"。
ASR 会把同一个专名写成不同形式，例如：汉字误替（彩波 对 綾波）、片假名变体（アスカ／アスカー）、写错的汉字（真司 对 真嗣）、片假名被转成平假名（あすか）等。

任务：通读全片，抽取"固定专名"，把指同一对象的各种写法归并为一条，并为每个日文写法分别给出中文。
收录：人名、角色名；职阶名／称号（如 チルドレン、エヴァ初号機）；反复出现的组织名、地名。反复出现、指代固定身份的称号也要收，即使它在普通语境里是普通名词（如 使徒），因为译文里这类称号的译法最容易摇摆。
不收：亲属称呼和人称称呼（お兄ちゃん、先輩、あの人、お主、父さん 等），这类称呼词一律不收；祷词、咒文、台词片段（如 キリエ・エレイソン 这类祷词）不是人名，不收；作品名的片段；单个泛用词；只出现一次且无法确认是专名的片段。
两个不同角色即使名字读音或字形相近，也绝不能合并成一个实体（例如 シンジ 与 シロウ 是两个人，各自成条）。

每条给出：
- entity_ja：该对象的正确日文全称（若你认出作品，用官方写法；否则用转写稿中最可信的写法）。
- zh：该对象在这部作品的中文官方译名或中文圈通行译名全称（认出作品时必须用通行写法；认不出作品时给出合理的音译）。仅用于展示。
- forms：转写稿里实际出现的每一个日文写法（包括正确的和被 ASR 误识的），每个写法单独给出它对应的中文 {"ja": 日文写法, "zh": 中文}。最多 12 个，不要重复列出同一个写法，entity_ja 本身也必须是其中一个写法。
  * 粒度必须一致：每个日文写法单独给中文。写法只说姓，就只给姓的中文；只说名，就只给名的中文；绝不把全名填给只说了姓或名的写法。原因：之后的替换只能把句子里的这个写法换成它的 zh，不能给句子添上原文没说的字。被误识的写法同样按它所指的那一部分给中文（误识的只有名，就映射到名）。
  * 例如碇シンジ：forms 为 {"ja": "碇シンジ", "zh": "碇真嗣"}、{"ja": "シンジ", "zh": "真嗣"}、{"ja": "碇", "zh": "碇"}、{"ja": "真司", "zh": "真嗣"}（真司是 ASR 把"名"写错的汉字）。
  * 只收指同一对象的写法。别的角色、别的称号，即使读音或字形相似，也不要放进来（例如 アスカ 不属于 碇シンジ，エヴァ弐号機 不属于 エヴァ初号機）。
  * ja 只写专名本身的裸形式：不带助词（の、は、を、に、が、と 等），不带前后的其他词，不写成短语或句子，不带残留的中文字或标点（反例：シンジを呼んでいる、アスカの代わりに?、的レイ、素人シンジ）。
  * forms 里的 zh 只写中文译名本身，不要括号、冒号、加号、空格，不要附带任何注释或说明。
- zh_variants：只收"同一个词的不同写法"，最多 8 个，不要重复。可收：音译的异写、英文原文、字面意译、繁简异体。绝不收该角色的真名、别名、称号，也不收其他角色的名字。
  * 正例：写法 シンジ→真嗣 的 zh_variants 可为 ["真司", "真治", "Shinji"]；写法 綾波レイ→绫波丽 的可为 ["绫波零", "綾波丽", "Rei Ayanami"]；初号機→初号机 的可为 ["EVA初号机", "Evangelion Unit-01"]。
  * 反例：真嗣的 zh_variants 里不能放"第三适格者"（称号）；绫波丽的不能放"明日香"（其他角色名）。这些不是同一个词的写法，替换后会改变句意。
- kind：person（人名、角色名）、class（职阶名／称号）、org（组织）、place（地名）、other（其他）之一。
- evidence：该对象（含各种误识写法）出现的 cue 编号，整数列表，最多 8 个，取有代表性的几条即可，必须是输入里真实存在的编号。
- confidence：high、medium、low 之一，按下列可操作的判据给，宁可给低也不要给错的 high：
  * high：只给你能凭作品知识说出该角色身份（他/她是谁、与主角的关系）、并且确定其通行中文译名的条目；并且该名字（含各种写法）在转写稿里出现在 ≥3 条 cue 里。
  * medium：认出作品，但说不出这一条具体是谁，或中文译名只是你推断的；或者这个名字是从 ASR 误识碎片拼出来的（如 マトウ増健、造剣 这类不成词的碎片）。次要角色、只出现两三次的名字通常是 medium，这是正常输出。
  * low：认不出作品，zh 只是音译。

条目总数最多约 60 条，优先收录在片中反复出现的专名；只出现一两次的次要名字可以省略。

请先判断这是哪部作品，写入 work_guess；认不出则为 null。认出作品后，才能据此纠正误识并使用通行译名。

输出要求：严格的 JSON 对象，不要任何解释文字，不要 markdown 代码块标记。格式：
{"work_guess": "作品名或 null", "entries": [{"entity_ja": "", "kind": "person", "confidence": "high", "zh": "", "forms": [{"ja": "", "zh": ""}], "zh_variants": [], "evidence": []}, {"entity_ja": "", "kind": "person", "confidence": "medium", "zh": "", "forms": [{"ja": "", "zh": ""}], "zh_variants": [], "evidence": []}]}
（第二条是次要角色的示例：confidence 为 medium 是正常输出，不是缺陷。）"""

# Qwen3 官方 non-thinking 推荐采样；贪心解码会陷入无休止重复。
SAMPLING = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0, "presence_penalty": 1.5}
_NAME = {"type": "string", "maxLength": 40}
RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["work_guess", "entries"],
    "properties": {
        "work_guess": {"type": ["string", "null"]},
        "entries": {"type": "array", "maxItems": 80, "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["entity_ja", "kind", "confidence", "zh", "forms", "zh_variants", "evidence"],
            "properties": {
                "entity_ja": _NAME,
                "kind": {"type": "string", "enum": list(KINDS)},
                "confidence": {"type": "string", "enum": list(CONFIDENCES)},
                "zh": _NAME,
                "forms": {"type": "array", "maxItems": MAX_FORMS, "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["ja", "zh"],
                    "properties": {"ja": _NAME, "zh": _NAME},
                }},
                "zh_variants": {"type": "array", "maxItems": MAX_ITEMS, "items": _NAME},
                "evidence": {"type": "array", "maxItems": MAX_ITEMS, "items": {"type": "integer"}},
            },
        }},
    },
}

USER_TEMPLATE = "以下是全片的 ASR 转写稿（共 {count} 条）：\n\n{lines}\n\n请按要求输出专名表 JSON。"


def _json_text(reply: str) -> str:
    """去掉思考块与围栏，截取最外层 `{...}`。"""
    reply = re.sub(r"<think>.*?</think>", "", reply, flags=re.S)
    start, end = reply.find("{"), reply.rfind("}")
    if start < 0 or end < start:
        raise ValueError("reply contains no JSON object")
    return reply[start:end + 1]


def _strings(values: Any) -> list[str]:
    """去空白、去空串、保序去重。"""
    out: list[str] = []
    for value in values if isinstance(values, list) else []:
        if isinstance(value, str) and value.strip() and value.strip() not in out:
            out.append(value.strip())
    return out


def _clean_zh(value: Any) -> str | None:
    """中文译名合格（见 ZH_SHAPE）则返回去空白后的串，否则 None。"""
    if not isinstance(value, str):
        return None
    value = value.strip()
    length = len(value.translate({ord(c): None for c in SEPARATORS}))
    if not 1 <= length <= MAX_ZH_LEN or not ZH_SHAPE.fullmatch(value):
        return None
    return value


def _clean_ja(value: Any) -> str | None:
    """日文写法形状合格则返回规范化后的串，否则 None。

    NFKC 规范化后：内部有空白时，仅当被空白隔开的每一段都全是汉字才去掉空白（间桐 桜 → 间桐桜），否则丢弃；
    只许 JA_SHAPE 里的字符（ASCII 字母数字、标点、空白一律丢弃）；含汉字或片假名的写法，平假名只许是开头的
    お／ご 或结尾的 さん／くん／ちゃん／さま／たん，全平假名的写法（しろ）原样保留；长度 1–20（含间隔号）。
    不区分日文汉字与中文汉字。
    """
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFKC", value).strip()
    parts = text.split()
    if len(parts) > 1:
        if not all(_KANJI_RUN.fullmatch(part) for part in parts):
            return None
        text = "".join(parts)
    if not 1 <= len(text) <= MAX_JA_LEN or not JA_SHAPE.fullmatch(text) or _DE_NEXT_TO_KATAKANA.search(text):
        return None
    # ー 和间隔号不算文字：全由它们组成的串不是名字；平假名加长音（あすかー）仍算全平假名。
    letters = text.translate({ord(c): None for c in SEPARATORS + "ー"})
    if not letters:
        return None
    if _HIRAGANA_RE.search(letters) and not all(_HIRAGANA_RE.fullmatch(c) for c in letters):
        body = text[1:] if text[0] in _JA_HIRAGANA_PREFIXES else text
        for suffix in _JA_HIRAGANA_SUFFIXES:
            if body.endswith(suffix):
                body = body[:-len(suffix)]
                break
        if _HIRAGANA_RE.search(body):
            return None
    return text


def _honorific_stem(word: str) -> str:
    """NFKC 规范化并去空白，再剥掉前缀 お／ご 与后缀 さん／さま／様／ちゃん／くん／君（剥后须非空）。"""
    word = "".join(unicodedata.normalize("NFKC", word).split())
    for prefix in _HONORIFIC_PREFIXES:
        if word.startswith(prefix) and len(word) > len(prefix):
            word = word[len(prefix):]
            break
    for suffix in _HONORIFIC_SUFFIXES:
        if word.endswith(suffix) and len(word) > len(suffix):
            return word[:-len(suffix)]
    return word


_HONORIFIC_STEMS = {_honorific_stem(w) for w in HONORIFIC_JA}


def is_honorific(ja: str) -> bool:
    """写法的词干等于黑名单某项的词干（完全相等是其特例）：父さん／お父さん／父様 命中，衛宮くん／衛宮君 不命中。
    君 作后缀时只剥不匹配（词干须非空，剥后为空则原样），单独的 君 仍命中。"""
    return _honorific_stem(ja) in _HONORIFIC_STEMS


def _drop(dropped: list[dict[str, Any]] | None, entity: str, field: str, value: Any, **extra: Any) -> None:
    if dropped is not None:
        dropped.append({"entity_ja": entity, "field": field, **extra, "value": value})


def _forms(raw_forms: Any, entity: str, entity_zh: str, dropped: list[dict[str, Any]] | None = None
           ) -> list[dict[str, str]]:
    """校验、按 ja 去重（先到先得）；entity_ja 缺席时以实体全称补到最前。zh 形状不合的写法丢弃并记录。"""
    forms: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in raw_forms if isinstance(raw_forms, list) else []:
        if not isinstance(raw, dict) or not isinstance(raw.get("ja"), str):
            continue
        ja, zh = raw["ja"].strip(), _clean_zh(raw.get("zh"))
        if ja and zh is None:
            _drop(dropped, entity, "form.zh", raw.get("zh"), ja=ja)
        elif ja and ja not in seen:
            seen.add(ja)
            forms.append({"ja": ja, "zh": zh})
    zh = _clean_zh(entity_zh)
    if entity not in seen and zh:
        forms.insert(0, {"ja": entity, "zh": zh})
    return forms[:MAX_FORMS]


def _clean_forms_ja(forms: list[dict[str, str]], entity: str, dropped_ja_shape: list[dict[str, Any]] | None
                    ) -> list[dict[str, str]]:
    """对每个写法的 ja 做 `_clean_ja`：不合格的丢弃并记录，清洗后重复的按先到先得去重。"""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for form in forms:
        ja = _clean_ja(form["ja"])
        if ja is None:
            if dropped_ja_shape is not None:
                dropped_ja_shape.append({"entity_ja": entity, "ja": form["ja"]})
        elif ja not in seen:
            seen.add(ja)
            out.append({"ja": ja, "zh": form["zh"]})
    return out


def _zh_variants(values: Any, entity: str, dropped: list[dict[str, Any]] | None) -> list[str]:
    """去空白、保序去重；形状不合的变体丢弃并记录。"""
    out: list[str] = []
    for value in _strings(values):
        if _clean_zh(value) is None:
            _drop(dropped, entity, "zh_variants", value)
        else:
            out.append(value)
    return out[:MAX_ITEMS]


def _downgrade_thin_person(entry: dict[str, Any]) -> dict[str, Any]:
    """person 条目的 evidence（已校验、去重的 cue 编号）少于 3 条时，high 降为 medium 并留下 confidence_note。"""
    if entry["kind"] == "person" and entry["confidence"] == "high" and len(entry["evidence"]) < MIN_HIGH_PERSON_CUES:
        entry["confidence"] = "medium"
        entry["confidence_note"] = "downgraded: evidence<3"
    return entry


def parse_reply(reply: str, cue_count: int, dropped: list[dict[str, Any]] | None = None,
                dropped_honorific: list[dict[str, Any]] | None = None,
                dropped_ja_shape: list[dict[str, Any]] | None = None
                ) -> tuple[str | None, list[dict[str, Any]]]:
    """解析并校验回复，返回 (work_guess, entries)。缺关键字段的条目丢弃，全部丢光则抛 ValueError。
    因 zh 形状不合被丢的实体／写法／变体追加进 `dropped`（若给出）；日文写法是称呼词（HONORIFIC_JA）而被丢的
    写法追加进 `dropped_honorific`，丢光写法的实体整条丢弃。日文写法先过形状过滤（`_clean_ja`）再查称呼词，
    形状不合的写法追加进 `dropped_ja_shape`；entity_ja 本身不合格时，取清洗后的串（空白被去掉）或第一个保留写法的
    ja，一个写法都不剩则整条丢弃并以 field="entity" 记录。"""
    data = json.loads(_json_text(reply))
    raw_entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError("entries must be a non-empty list")
    guess = data.get("work_guess")
    guess = guess.strip() if isinstance(guess, str) and guess.strip() else None
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        entity, zh = raw.get("entity_ja"), raw.get("zh")
        if not (isinstance(entity, str) and entity.strip() and isinstance(zh, str) and zh.strip()):
            continue
        entity, zh = entity.strip(), zh.strip()
        if _clean_zh(zh) is None:
            _drop(dropped, entity, "zh", zh)
            continue
        forms = _clean_forms_ja(_forms(raw.get("forms"), entity, zh, dropped), entity, dropped_ja_shape)
        kept = [f for f in forms if not is_honorific(f["ja"])]
        if dropped_honorific is not None:
            dropped_honorific.extend({"entity_ja": entity, "ja": f["ja"]} for f in forms if f not in kept)
        forms = kept
        clean_entity = _clean_ja(entity)
        if clean_entity is None and not forms and dropped_ja_shape is not None:
            dropped_ja_shape.append({"entity_ja": entity, "field": "entity", "ja": entity})
        if clean_entity is None and forms:
            clean_entity = forms[0]["ja"]
        if clean_entity is None or clean_entity in seen or not forms:
            continue
        entity = clean_entity
        seen.add(entity)
        kind = raw.get("kind")
        evidence = [i for i in raw.get("evidence", []) if type(i) is int and 1 <= i <= cue_count] \
            if isinstance(raw.get("evidence"), list) else []
        entries.append(_downgrade_thin_person({
            "entity_ja": entity,
            "kind": kind if kind in KINDS else "other",
            "confidence": raw.get("confidence") if raw.get("confidence") in CONFIDENCES else "medium",
            "zh": zh,
            "forms": forms,
            "zh_variants": _zh_variants(raw.get("zh_variants"), entity, dropped),
            "evidence": sorted(set(evidence))[:MAX_ITEMS],
        }))
    if not entries:
        raise ValueError("no valid entries after validation")
    return guess, entries


def _render_text(text: str) -> str:
    """cue 文本里的换行替换为空格（一行一条）。"""
    return text.strip().replace("\r\n", "\n").replace("\n", " ")


def build_messages(document: SourceDocument) -> list[dict[str, str]]:
    """整份文档渲染成提示：每行 `编号<TAB>文本`，编号取 SRT 序号，时间轴丢弃。"""
    lines = "\n".join(f"{cue.index}\t{_render_text(cue.text)}" for cue in document.cues)
    user = USER_TEMPLATE.format(count=len(document.cues), lines=lines)
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


Chat = Callable[[dict[str, Any]], dict[str, Any]]
Tokenize = Callable[[str], int]


@dataclass(frozen=True)
class BuildResult:
    """建表结果。`payload` 即 `name-table.json` 的内容（不含身份块）；`attempts` 为实际请求次数。"""

    payload: dict[str, Any]
    attempts: int
    seconds: float
    status: str  # ok | failed | too_long


def _payload(seed: int, attempt: int, guess: str | None, entries: list[dict[str, Any]], dropped: tuple[list, list, list],
             usage: dict[str, Any], seconds: float, status: str, reason: str | None) -> dict[str, Any]:
    shape, honorific, ja_shape = dropped
    return {
        "schema": SCHEMA,
        "prompt_version": PROMPT_VERSION,
        "work_guess": guess,
        "entries": entries,
        "meta": {"seed": seed, "attempt": attempt, "dropped_shape": shape, "dropped_honorific": honorific,
                 "dropped_ja_shape": ja_shape, "prompt_tokens": usage.get("prompt_tokens"),
                 "completion_tokens": usage.get("completion_tokens"), "seconds": round(seconds, 2)},
        "build": {"status": status, "reason": reason},
    }


def _request_body(messages: list[dict[str, str]], seed: int) -> dict[str, Any]:
    """no-think 请求体，与研究脚本 `run_once` 的非思考分支相同。"""
    return {"messages": messages, **SAMPLING, "seed": seed, "max_tokens": MAX_TOKENS,
            "response_format": {"type": "json_schema", "json_schema": {"name": "name_table", "schema": RESPONSE_SCHEMA}},
            "chat_template_kwargs": {"enable_thinking": False}, "stream": False}


def build_table(document: SourceDocument, chat: Chat, tokenize: Tokenize, seed: int) -> BuildResult:
    """建表。零条目文档不请求；system+user 提示的 token 总数超预算返回 `too_long` 空表；否则最多 `ATTEMPTS` 次，第 N 次 seed 加
    `(N-1) * SEED_STEP`，回复被截断（`finish_reason == length`）或 `parse_reply` 抛 `ValueError` 即重试，
    全部失败返回 `failed` 空表（原因取最后一次错误的首行）。传输层异常不在此处理，直接抛给调用方。"""
    none_dropped: tuple[list, list, list] = ([], [], [])
    if not document.cues:
        payload = _payload(seed, 0, None, [], none_dropped, {}, 0.0, "ok", None)
        return BuildResult(payload, 0, 0.0, "ok")
    messages = build_messages(document)
    # system 与 user 各数一次再相加：预算约束的是整个提示（研究期的 13.7K prompt tokens 即两者之和）。
    tokens = sum(tokenize(message["content"]) for message in messages)
    if tokens > PROMPT_BUDGET:
        reason = f"prompt tokens {tokens} exceed budget {PROMPT_BUDGET}"
        payload = _payload(seed, 0, None, [], none_dropped, {}, 0.0, "too_long", reason)
        return BuildResult(payload, 0, 0.0, "too_long")

    cue_count = max(cue.index for cue in document.cues)
    total_seconds = 0.0
    last_error: ValueError | None = None
    used_seed, usage = seed, {}
    for attempt in range(1, ATTEMPTS + 1):
        used_seed = seed + (attempt - 1) * SEED_STEP
        start = perf_counter()
        response = chat(_request_body(messages, used_seed))
        total_seconds += perf_counter() - start
        choice = response["choices"][0]
        usage = response.get("usage") or {}
        try:
            if choice.get("finish_reason") == "length":
                raise ValueError("reply truncated (finish_reason=length), refusing to parse")
            dropped: tuple[list, list, list] = ([], [], [])
            guess, entries = parse_reply((choice.get("message") or {}).get("content") or "", cue_count, *dropped)
        except ValueError as exc:  # json.JSONDecodeError 是其子类
            last_error = exc
            continue
        payload = _payload(used_seed, attempt, guess, entries, dropped, usage, total_seconds, "ok", None)
        return BuildResult(payload, attempt, total_seconds, "ok")
    reason = (str(last_error).splitlines() or [type(last_error).__name__])[0]
    payload = _payload(used_seed, ATTEMPTS, None, [], none_dropped, usage, total_seconds, "failed", reason)
    return BuildResult(payload, ATTEMPTS, total_seconds, "failed")
