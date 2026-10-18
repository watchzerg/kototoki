"""翻译配方：提示、grammar、采样与 completion 请求，及配方 hash（翻译配方的唯一归属，规格 §7.3）。

复制自 `experiments/translation_v3/recipes.py`，只保留 `b10-joint` 与 `dp10-cut` 用到的字段与函数；去掉
terms／review／多样本／类别路由与配方文件加载。`Recipe.spec()` 的结构与 v3 相同（`gap_pack` 为 None 时不进
`recipe`，有值时 `versions["gap_pack"]` 记 `gap-pack-v2`），因此 `B10_JOINT`、`DP10_CUT` 的 `recipe_hash` 等于
v3 `BUILTIN` 同名配方的原 hash（`tests/core/test_translate_recipes.py` 钉住），请求字节同样逐字节对照 v3。
产品配方只把 `overflow` 策略换成拆批降级与单条保留日文（见 `degrade.py`），因而另算 hash；提示、grammar、
采样与请求字节不变：`b10-joint-degrade-v1`（票据 09）对应 `b10-joint`，`dp10-cut-degrade-v1`（票据 16，
ADR-0011）对应 `dp10-cut`。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from kototoki.artifacts import object_hash, sha256_bytes

from . import adapters

RECIPE_SCHEMA = "hy30-flow-v3-recipe-v1"
STOP = ["<eos:6124c78e>"]
N_PREDICT = 4096
CONTEXT_SIZE = 8192
GUARD_TOKENS = 64
MAX_INPUT_TOKENS = CONTEXT_SIZE - N_PREDICT - GUARD_TOKENS  # 4032
CACHE_PROMPT = True
MAX_ATTEMPTS = 2

# 冻结的 C0 逐值指令与 v3 joint-understanding 替换文本（与 v2 `joint-json` 相同）。
C0_INSTRUCTION = "每个值独立对应一个 ID，不要将相邻值合成一句，不要将多个条目的译文放进同一个值。"
JOINT_VERSION = "joint-understanding-v1"
JOINT_INSTRUCTION = ("先共同理解全部可见台词及跨条目的条件、否定、指代和语气，再分别表达各源 ID 的信息。"
                     "保留原文歧义和信息揭示顺序；每个值只承载对应源 ID，不搬运邻条事实、不提前补完后文。")

SAMPLING_PROFILE = "official30b-cached-v1"
OVERFLOW_V3 = "recorded-failure-no-truncation-no-auto-shrink"
OVERFLOW_DEGRADE = "degrade-10-5-1-keep-source"
# v3 gap-pack-v2（ADR-0010）：按停顿切包，切点按停顿长短分级加罚（`batching.gap_pack_cuts`）。
GAP_PACK_VERSION = "gap-pack-v2"
# `dp10-cut` 的切包参数，逐字照抄 v3 `BUILTIN["dp10-cut"]`（整个 dict 进 hash）。产品只实现 `group_gap=None`
# 这条分支，`group_gap`／`group_max` 两键只为保持身份而保留。
DP10_CUT_PACK: dict[str, Any] = {
    "min": 6, "max": 10, "soft_gap": 2.0, "hard_gap": 20.0, "soft_weight": 1.0, "small_penalty": 1000.0,
    "group_gap": None, "group_max": 10, "context_both_below": 1.0, "context_before_below": 5.0,
    "max_visible": 12, "cut_penalty": [[0.5, 6.0], [1.0, 3.0], [2.0, 1.0]]}


def sampling(seed: int) -> dict[str, Any]:
    """官方 C0 采样，键序与 v2 `sampling_settings('official', seed)` 相同。"""
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("seed must be an integer in [0, 2**32)")
    return {"temperature": 0.7, "top_p": 1.0, "top_k": 0, "min_p": 0.0, "repeat_penalty": 1.0,
            "frequency_penalty": 0.0, "presence_penalty": 0.0, "dynatemp_range": 0.0, "mirostat": 0,
            "samplers": ["temperature"], "seed": seed}


def completion_request(tokens: list[int], seed: int, grammar: str) -> dict[str, Any]:
    return {"prompt": tokens, "n_predict": N_PREDICT, **sampling(seed), "cache_prompt": CACHE_PROMPT,
            "stream": False, "stop": list(STOP), "grammar": grammar}


@dataclass(frozen=True)
class Recipe:
    """v3 配方字段（`b10-joint` 的取值）；`name` 是标签，不进身份；`overflow` 进 `fixed`（与 v3 位置相同）。

    `gap_pack`：None 时按源顺序每批 `batch_count` 条、前后各 `context_before`／`context_after` 条邻文；有值时
    按 `batching.gap_pack_cuts` 切包、邻文按停顿取舍（`batch_count` 成为目标条数、`context_*` 成为上限）。
    """

    name: str
    batch_count: int = 10
    token_target: None = None
    context_before: int = 1
    context_after: int = 1
    prompt: str = "joint"
    grammar_ws: str = "unbounded"
    preanalysis: None = None
    review: None = None
    overflow: str = OVERFLOW_V3
    gap_pack: dict[str, Any] | None = None

    def spec(self) -> dict[str, Any]:
        data = {key: value for key, value in asdict(self).items()
                if key not in ("name", "overflow") and not (key == "gap_pack" and value is None)}
        versions = {"adapters_render": "adapters.render(hy-mt2-30b)+id_grammar",
                    "joint": [JOINT_VERSION, sha256_bytes(JOINT_INSTRUCTION.encode())]}
        if self.gap_pack:
            versions["gap_pack"] = GAP_PACK_VERSION
        return {"schema": RECIPE_SCHEMA, "recipe": data, "versions": versions,
                "fixed": {"sampling_profile": SAMPLING_PROFILE, "sampling": sampling(0) | {"seed": "<run seed>"},
                          "n_predict": N_PREDICT, "context_size": CONTEXT_SIZE, "guard_tokens": GUARD_TOKENS,
                          "cache_prompt": CACHE_PROMPT, "max_attempts": MAX_ATTEMPTS, "stop": STOP,
                          "overflow": self.overflow}}

    @property
    def recipe_hash(self) -> str:
        return object_hash(self.spec())

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, **self.spec(), "recipe_hash": self.recipe_hash}


# 2026-10-11..16 的翻译流程基线（ADR-0006）：按源顺序每批 10 条。
B10_JOINT = Recipe("b10-joint")
# 2026-10-14..18 的产品配方（票据 09）：b10-joint 加拆批降级。保留并钉住 hash，作为旧 run 目录的身份对照。
B10_JOINT_DEGRADE_V1 = Recipe("b10-joint-degrade-v1", overflow=OVERFLOW_DEGRADE)
# 2026-10-17 起的翻译流程基线（ADR-0010）：gap-pack-v2 切包，每批 ≤10 条、可见 ≤12 条。
DP10_CUT = Recipe("dp10-cut", gap_pack=DP10_CUT_PACK)
# 产品配方（规格 §1.2，ADR-0011）：dp10-cut 切包，批次终态失败按 `degrade.py` 拆批，单条仍失败保留日文。
DP10_CUT_DEGRADE_V1 = Recipe("dp10-cut-degrade-v1", overflow=OVERFLOW_DEGRADE, gap_pack=DP10_CUT_PACK)
PRODUCT = DP10_CUT_DEGRADE_V1
RECIPE_HASH = PRODUCT.recipe_hash


def render_translation(window: dict[str, Any]) -> str:
    prompt = adapters.render(window)
    if prompt.count(C0_INSTRUCTION) != 1:
        raise ValueError("Frozen C0 instruction changed; version the joint prompt")
    return prompt.replace(C0_INSTRUCTION, JOINT_INSTRUCTION, 1)


def translation_grammar(ids: list[str]) -> str:
    return adapters.id_grammar(ids)


def parse_translation(text: str, ids: list[str]) -> dict[str, str]:
    """v3 校验之外再拒绝含空行的译文（规格 §5.2"v3 只禁空行"）：空行会让 SRT 断块，按解析失败处理。"""
    result = adapters.translations(text, ids)
    for key, value in result.items():
        if any(not line.strip() for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")):
            raise ValueError(f"Blank line inside translation of {key}")
    return result
