"""从整片日文 SRT 建多对一专名表（name-table-v2：每个日文写法各带一个同粒度的中文）。

读 `ja.srt`，剥掉时间轴，整片一次放进提示，经 llama-server 的 OpenAI 兼容接口取回 JSON 表，
校验、归一后写 `table.json`，并在旁边留下原始请求、原始回复。不加载模型，只发 HTTP。

提示 v6 的示例全部用虚构作品的人名，避免真实作品的名字污染模型输出；归一时对每个日文写法再做形状过滤（`_clean_ja`：
只留裸名字，丢句子、带助词、带空白或标点的写法），丢弃项记入 `meta.dropped_ja_shape`。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.request import ProxyHandler, Request, build_opener

SCHEMA = "name-table-v2"
KINDS = ("person", "class", "org", "place", "other")
SRT_BLOCK = re.compile(r"(\d+)\s*\n[\d:,]+ --> [\d:,]+\s*\n(.*?)(?:\n\s*\n|\Z)", re.S)
PROMPT_VERSION = "build-table-prompt-v6"
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

SYSTEM_PROMPT = """你是日本动画／电影字幕的专名整理员。用户给出的是一部作品日语字幕轨的 ASR（自动语音识别）转写稿，每行格式为"cue 编号<TAB>日文台词"。
ASR 会把同一个专名写成不同形式，例如：汉字误替（月隅 对 月隈）、片假名变体（ミオリ／ミオリー）、写错的汉字（拓巳 对 拓海）、片假名被转成平假名（みおり）等。

任务：通读全片，抽取"固定专名"，把指同一对象的各种写法归并为一条，并为每个日文写法分别给出中文。
收录：人名、角色名；职阶名／称号（如 第七観測者、灯守一番機）；反复出现的组织名、地名。反复出现、指代固定身份的称号也要收，即使它在普通语境里是普通名词（如 灯守），因为译文里这类称号的译法最容易摇摆。
不收：亲属称呼和人称称呼（お兄ちゃん、先輩、あの人、お主、父さん 等），这类称呼词一律不收；祷词、咒文、台词片段（如 ソルヴェ・テネブラス 这类祷词）不是人名，不收；作品名的片段；单个泛用词；只出现一次且无法确认是专名的片段。
两个不同角色即使名字读音或字形相近，也绝不能合并成一个实体（例如 タクミ 与 タクマ 是两个人，各自成条）。

每条给出：
- entity_ja：该对象的正确日文全称（若你认出作品，用官方写法；否则用转写稿中最可信的写法）。
- zh：该对象在这部作品的中文官方译名或中文圈通行译名全称（认出作品时必须用通行写法；认不出作品时给出合理的音译）。仅用于展示。
- forms：转写稿里实际出现的每一个日文写法（包括正确的和被 ASR 误识的），每个写法单独给出它对应的中文 {"ja": 日文写法, "zh": 中文}。最多 12 个，不要重复列出同一个写法，entity_ja 本身也必须是其中一个写法。
  * 粒度必须一致：每个日文写法单独给中文。写法只说姓，就只给姓的中文；只说名，就只给名的中文；绝不把全名填给只说了姓或名的写法。原因：之后的替换只能把句子里的这个写法换成它的 zh，不能给句子添上原文没说的字。被误识的写法同样按它所指的那一部分给中文（误识的只有名，就映射到名）。
  * 例如鷺宮タクミ：forms 为 {"ja": "鷺宮タクミ", "zh": "鹭宫拓海"}、{"ja": "タクミ", "zh": "拓海"}、{"ja": "鷺宮", "zh": "鹭宫"}、{"ja": "拓巳", "zh": "拓海"}（拓巳是 ASR 把"名"写错的汉字）。
  * 只收指同一对象的写法。别的角色、别的称号，即使读音或字形相似，也不要放进来（例如 ミオリ 不属于 鷺宮タクミ，灯守二番機 不属于 灯守一番機）。
  * ja 只写专名本身的裸形式：不带助词（の、は、を、に、が、と 等），不带前后的其他词，不写成短语或句子，不带残留的中文字或标点（反例：タクミを呼んでいる、ミオリの代わりに?、的ミオリ、素人タクミ）。
  * forms 里的 zh 只写中文译名本身，不要括号、冒号、加号、空格，不要附带任何注释或说明。
- zh_variants：只收"同一个词的不同写法"，最多 8 个，不要重复。可收：音译的异写、英文原文、字面意译、繁简异体。绝不收该角色的真名、别名、称号，也不收其他角色的名字。
  * 正例：写法 タクミ→拓海 的 zh_variants 可为 ["拓美", "托米", "Takumi"]；写法 月隈ミオリ→月隈澪织 的可为 ["月隈美织", "月隈澪織", "Miori Tsukikuma"]；灯守一番機→灯守一号机 的可为 ["灯守壹号机", "Lampkeeper"]。
  * 反例：拓海的 zh_variants 里不能放"第七观测者"（称号）；澪织的不能放"灰谷"（其他角色名）。这些不是同一个词的写法，替换后会改变句意。
- kind：person（人名、角色名）、class（职阶名／称号）、org（组织）、place（地名）、other（其他）之一。
- evidence：该对象（含各种误识写法）出现的 cue 编号，整数列表，最多 8 个，取有代表性的几条即可，必须是输入里真实存在的编号。
- confidence：high、medium、low 之一，按下列可操作的判据给，宁可给低也不要给错的 high：
  * high：只给你能凭作品知识说出该角色身份（他/她是谁、与主角的关系）、并且确定其通行中文译名的条目；并且该名字（含各种写法）在转写稿里出现在 ≥3 条 cue 里。
  * medium：认出作品，但说不出这一条具体是谁，或中文译名只是你推断的；或者这个名字是从 ASR 误识碎片拼出来的（如 ホズミ増尋、燈織 这类不成词的碎片）。次要角色、只出现两三次的名字通常是 medium，这是正常输出。
  * low：认不出作品，zh 只是音译。

条目总数最多约 60 条，优先收录在片中反复出现的专名；只出现一两次的次要名字可以省略。

请先判断这是哪部作品，写入 work_guess；认不出则为 null。认出作品后，才能据此纠正误识并使用通行译名。

输出要求：严格的 JSON 对象，不要任何解释文字，不要 markdown 代码块标记。格式：
{"work_guess": "作品名或 null", "entries": [{"entity_ja": "", "kind": "person", "confidence": "high", "zh": "", "forms": [{"ja": "", "zh": ""}], "zh_variants": [], "evidence": []}, {"entity_ja": "", "kind": "person", "confidence": "medium", "zh": "", "forms": [{"ja": "", "zh": ""}], "zh_variants": [], "evidence": []}]}
（第二条是次要角色的示例：confidence 为 medium 是正常输出，不是缺陷。）"""

SEED = 20261019
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


def read_srt_cues(path: Path) -> list[tuple[int, str]]:
    """返回 (cue 编号, 文本)；多行 cue 以空格连接，时间轴丢弃。"""
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    cues = []
    for index, body in SRT_BLOCK.findall(text + "\n\n"):
        cues.append((int(index), body.strip().replace("\n", " ")))
    return cues


def render_lines(cues: list[tuple[int, str]]) -> str:
    return "\n".join(f"{index}\t{text}" for index, text in cues)


def build_messages(cues: list[tuple[int, str]]) -> list[dict[str, str]]:
    user = USER_TEMPLATE.format(count=len(cues), lines=render_lines(cues))
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


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


def post_chat(url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    """POST 到 llama-server；绕过系统代理。测试里整体替换本函数。"""
    request = Request(url.rstrip("/") + "/v1/chat/completions",
                      data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json"})
    with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("expected server JSON object")
    return result


def run_once(url: str, messages: list[dict[str, str]], think: bool, out: Path, attempt: int, seed: int = SEED
             ) -> tuple[str, dict[str, Any], float]:
    """发一次请求，原样落盘请求与回复文本，返回 (回复文本, 响应, 秒数)。重试时 seed 加一。"""
    # 思考模式下思考本身会吃掉输出预算（实测 4096 全被思考用光），给 8192；服务器端用 --reasoning-budget 限制思考长度。
    body = {"messages": messages, **SAMPLING, "seed": seed + attempt - 1, "max_tokens": 8192 if think else 4096,
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "name_table", "schema": RESPONSE_SCHEMA}},
            "chat_template_kwargs": {"enable_thinking": think}, "stream": False}
    suffix = "" if attempt == 1 else f".{attempt}"
    Path(f"{out}.request{suffix}.json").write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
    start = perf_counter()
    response = post_chat(url, body, 1800.0)
    seconds = perf_counter() - start
    reply = response["choices"][0]["message"].get("content") or ""
    Path(f"{out}.reply{suffix}.txt").write_text(reply, encoding="utf-8")
    return reply, response, seconds


def _original_seed(old: dict[str, Any], reply_path: Path) -> int | None:
    """旧表 meta 里的 seed；没有就从与回复配对的请求文件（`.reply[.N].txt` ↔ `.request[.N].json`）里读。"""
    seed = (old.get("meta") or {}).get("seed")
    if seed is None:
        request = reply_path.with_name(reply_path.name.replace(".reply", ".request", 1).removesuffix(".txt") + ".json")
        try:
            seed = json.loads(request.read_text(encoding="utf-8")).get("seed")
        except (OSError, ValueError, AttributeError):
            seed = None
    return seed


def renormalize_table(old_table: Path, out: Path) -> dict[str, Any]:
    """不重跑模型：读旧表指向的原始回复（`raw_reply_path`），按当前规则重新校验归一，写新表。

    work、model、timing、prompt_version 沿用旧表（回复仍是当时那版提示产生的），cue 总数取自旧表的 source_srt。
    """
    old = json.loads(old_table.read_text(encoding="utf-8"))
    reply_path = Path(old.get("raw_reply_path") or f"{old_table}.reply.txt")
    if not reply_path.is_absolute() and not reply_path.exists():
        reply_path = old_table.parent / reply_path.name
    cue_count = max(index for index, _ in read_srt_cues(Path(old["source_srt"])))
    dropped: list[dict[str, Any]] = []
    honorific: list[dict[str, Any]] = []
    ja_shape: list[dict[str, Any]] = []
    guess, entries = parse_reply(reply_path.read_text(encoding="utf-8"), cue_count, dropped, honorific, ja_shape)
    meta = {"seed": _original_seed(old, reply_path), "dropped_shape": dropped, "dropped_honorific": honorific,
            "dropped_ja_shape": ja_shape}
    table = {**old, "work_guess": guess, "entries": entries, "meta": meta, "renormalized_from": str(old_table)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    return table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从整片 ja.srt 建专名表")
    parser.add_argument("--srt", type=Path)
    parser.add_argument("--work")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--renormalize", type=Path, metavar="OLD_TABLE",
                        help="不重跑模型：对旧表的原始回复按当前规则重新归一，写到 --out")
    parser.add_argument("--url", default="http://127.0.0.1:8081")
    parser.add_argument("--seed", type=int, default=SEED, help="采样 seed，重试时加 attempt-1")
    parser.add_argument("--think", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="只写出渲染好的提示，不发请求")
    args = parser.parse_args(argv)

    if args.renormalize:
        table = renormalize_table(args.renormalize, args.out)
        print(f"entries={len(table['entries'])} dropped_shape={len(table['meta']['dropped_shape'])} "
              f"dropped_ja_shape={len(table['meta']['dropped_ja_shape'])}")
        return 0
    if not (args.srt and args.work):
        parser.error("--srt and --work are required unless --renormalize is given")

    cues = read_srt_cues(args.srt)
    if not cues:
        print(f"no cues in {args.srt}", file=sys.stderr)
        return 2
    cue_count = max(index for index, _ in cues)
    messages = build_messages(cues)
    prompt_chars = sum(len(m["content"]) for m in messages)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        prompt_path = Path(f"{args.out}.prompt.txt")
        prompt_path.write_text("\n\n".join(f"[{m['role']}]\n{m['content']}" for m in messages), encoding="utf-8")
        print(f"prompt_chars={prompt_chars} cues={len(cues)} -> {prompt_path}")
        return 0

    total_seconds = 0.0
    dropped: list[dict[str, Any]] = []
    honorific: list[dict[str, Any]] = []
    ja_shape: list[dict[str, Any]] = []
    last_error: Exception | None = None
    for attempt in (1, 2):
        reply, response, seconds = run_once(args.url, messages, args.think, args.out, attempt, args.seed)
        total_seconds += seconds
        finish_reason = response["choices"][0].get("finish_reason")
        try:
            if finish_reason == "length":
                raise ValueError("reply truncated (finish_reason=length), refusing to parse")
            dropped, honorific, ja_shape = [], [], []
            guess, entries = parse_reply(reply, cue_count, dropped, honorific, ja_shape)
            break
        except ValueError as exc:  # json.JSONDecodeError 是其子类
            last_error = exc
            print(f"attempt {attempt}: reply rejected: {exc}", file=sys.stderr)
    else:
        print(f"giving up; raw replies kept next to {args.out}: {last_error}", file=sys.stderr)
        return 1

    usage = response.get("usage") or {}
    table = {
        "schema": SCHEMA,
        "work": args.work,
        "prompt_version": PROMPT_VERSION,
        "source_srt": str(args.srt),
        "model": {"url": args.url, "model_id_from_server": response.get("model"), "think": args.think},
        "work_guess": guess,
        "entries": entries,
        "meta": {"seed": args.seed + attempt - 1, "dropped_shape": dropped, "dropped_honorific": honorific,
                 "dropped_ja_shape": ja_shape},
        "timing": {"prompt_chars": prompt_chars, "prompt_tokens": usage.get("prompt_tokens", 0),
                   "completion_tokens": usage.get("completion_tokens", 0), "seconds": round(total_seconds, 2),
                   "finish_reason": finish_reason},
        "raw_reply_path": f"{args.out}.reply{'' if attempt == 1 else f'.{attempt}'}.txt",
    }
    args.out.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"entries={len(entries)} dropped_shape={len(dropped)} dropped_ja_shape={len(ja_shape)} work_guess={guess} seconds={table['timing']['seconds']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
