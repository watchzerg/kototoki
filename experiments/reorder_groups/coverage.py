"""v8 票据 01：grp1 注入 groups 的包比例与输入 token 增量（纯 CPU，不加载模型、不占 GPU）。

- 覆盖：dp10-cut 切包下，含 ≥2 条 R2+ 小组（即 grp1 会换 joint 句并注入 groups 行）的包比例、多 cue 组覆盖的 cue 比例。
- token：同一批次分别按 dp10-cut 与 grp1 渲染完整 prompt，差值拆成"joint 句 v1→v2"与"groups 行"两部分。
  计数用离线 BPE：从翻译 GGUF 的元数据（只读文件头，不读权重）取 ``tokenizer.ggml.*`` 词表与 merges，按
  llama.cpp ``hunyuan-dense`` 预分词规则重建；``--validate`` 用已有 run 的 ``/tokenize`` 交换记录（服务器的
  实际 token ID，即 translation_v3 的计数方式）逐条核对，须全部逐 ID 一致才可信。

运行（worktree 里没有 ``.local/``，用 ``--local-root`` 指向有数据的 checkout）：
    PYTHONPATH=. python -X utf8 -m experiments.reorder_groups.coverage --local-root D:/AI_Projects/kototoki/.local \\
        --validate <run 目录> [--validate <run 目录> ...] [--json <输出.json>]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import string
import struct
from typing import Any

from experiments.scene_batching_v6 import sim7
from experiments.translation_v3 import recipes as R
from experiments.translation_v3.batching import build_batches
from experiments.translation_v3.data import Scene

from .checks import load_set

GGUF = "models/translation/hy-mt2-30b-a3b-apex-i-compact/Hy-MT2-30B-A3B-APEX-I-Compact.gguf"
# llama.cpp LLAMA_VOCAB_PRE_TYPE_HUNYUAN_DENSE；第三条首段的 ASCII 标点类逐字转义，避免手写转义出错。
PRE_SPLITS = (r"\p{N}{1,3}", "[一-龥\u3040-ゟ゠-ヿ]+",
              "[" + "".join("\\" + c for c in string.punctuation) + "][A-Za-z]+"
              + r"|[^\r\n\p{L}\p{P}\p{S}]?[\p{L}\p{M}]+| ?[\p{P}\p{S}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+")
_SCALAR = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}


def gguf_tokenizer_metadata(path: Path) -> dict[str, Any]:
    """GGUF v3 元数据里的 ``tokenizer.*`` 键（chat_template 除外）；只读文件头，不读张量。"""
    with path.open("rb") as stream:
        def number(fmt: str) -> Any:
            return struct.unpack(fmt, stream.read(struct.calcsize(fmt)))[0]

        def value(kind: int) -> Any:
            if kind in _SCALAR:
                return number(_SCALAR[kind])
            if kind == 8:
                return stream.read(number("<Q")).decode("utf-8", "replace")
            if kind == 9:
                element, count = number("<I"), number("<Q")
                return [value(element) for _ in range(count)]
            raise ValueError(f"Unknown GGUF metadata type {kind}")

        if stream.read(4) != b"GGUF" or number("<I") != 3:
            raise ValueError(f"Not a GGUF v3 file: {path}")
        number("<Q")
        meta = {}
        for _ in range(number("<Q")):
            key = stream.read(number("<Q")).decode("utf-8")
            item = value(number("<I"))
            if key.startswith("tokenizer.") and key != "tokenizer.chat_template":
                meta[key] = item
    return meta


def build_tokenizer(meta: dict[str, Any]) -> Any:
    from tokenizers import AddedToken, Regex, Tokenizer, models, pre_tokenizers
    if (meta["tokenizer.ggml.model"], meta["tokenizer.ggml.pre"]) != ("gpt2", "hunyuan-dense"):
        raise ValueError("Only the gpt2 / hunyuan-dense vocabulary is reproduced")
    tokens, types = meta["tokenizer.ggml.tokens"], meta["tokenizer.ggml.token_type"]
    tokenizer = Tokenizer(models.BPE(vocab={t: i for i, t in enumerate(tokens)},
                                     merges=[tuple(m.split(" ", 1)) for m in meta["tokenizer.ggml.merges"]]))
    tokenizer.pre_tokenizer = pre_tokenizers.Sequence(
        [pre_tokenizers.Split(Regex(p), "isolated") for p in PRE_SPLITS]
        + [pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False)])
    # 控制（3）与用户定义（4）token 按特殊 token 整体匹配，对应 /tokenize 的 parse_special=true。
    tokenizer.add_special_tokens([AddedToken(t, special=True, normalized=False)
                                  for t, kind in zip(tokens, types) if kind in (3, 4)])
    return tokenizer


def count(tokenizer: Any, text: str) -> int:
    return len(tokenizer.encode(text, add_special_tokens=False).ids)


def validate(tokenizer: Any, run_dirs: list[Path]) -> dict[str, Any]:
    """与 run 的 ``transport/*/*`` 里 ``/tokenize`` 请求／响应逐 ID 比对。"""
    total = exact = 0
    for run in run_dirs:
        for folder in sorted(run.glob("transport/session-*/*")):
            request = folder / "request.json"
            if not request.is_file():
                continue
            body = json.loads(request.read_text(encoding="utf-8"))
            if body.get("endpoint") != "/tokenize":
                continue
            want = json.loads((folder / "response.raw").read_text(encoding="utf-8"))["tokens"]
            total += 1
            exact += tokenizer.encode(body["body"]["content"], add_special_tokens=False).ids == want
    return {"runs": [str(r) for r in run_dirs], "prompts": total, "exact": exact}


def summary(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    q = statistics.quantiles(values, n=10, method="inclusive") if len(values) > 1 else [values[0]] * 9
    return {"n": len(values), "mean": statistics.fmean(values), "p50": statistics.median(values), "p90": q[8],
            "max": max(values)}


def coverage(scenes: list[Scene], tokenizer: Any) -> dict[str, Any]:
    control, candidate = R.BUILTIN["dp10-cut"], R.BUILTIN["grp1"]
    packs = injected = cues = grouped_cues = 0
    swap, line, total_delta, base_tokens, grp_tokens = [], [], [], [], []
    for scene in scenes:
        for batch in build_batches(scene, candidate):
            packs += 1
            cues += len(batch.target_ids)
            window = batch.to_window(scene)
            base = R.render_translation(control, window)
            full = R.render_translation(candidate, window, groups=batch.groups)
            base_n = count(tokenizer, base)
            base_tokens.append(base_n)
            if not batch.groups:
                if full != base:
                    raise AssertionError(f"{batch.batch_id}: no groups but the prompt differs from dp10-cut")
                grp_tokens.append(base_n)
                continue
            injected += 1
            grouped_cues += sum(len(g) for g in batch.groups)
            swapped_n = count(tokenizer, base.replace(R.JOINT_INSTRUCTION, R.JOINT2_INSTRUCTION, 1))
            full_n = count(tokenizer, full)
            grp_tokens.append(full_n)
            swap.append(swapped_n - base_n)
            line.append(full_n - swapped_n)
            total_delta.append(full_n - base_n)
    return {"packs": packs, "injected_packs": injected, "injected_share": injected / packs if packs else None,
            "cues": cues, "grouped_cues": grouped_cues, "grouped_cue_share": grouped_cues / cues if cues else None,
            "delta_per_injected_pack": {"joint_v1_to_v2": summary(swap), "groups_line": summary(line),
                                        "total": summary(total_delta)},
            "input_tokens": {"dp10_cut": summary(base_tokens), "grp1": summary(grp_tokens),
                             "relative_increase": (sum(grp_tokens) - sum(base_tokens)) / sum(base_tokens)
                             if base_tokens else None,
                             "grp1_over_limit": sum(n > R.MAX_INPUT_TOKENS for n in grp_tokens),
                             "limit": R.MAX_INPUT_TOKENS}}


def analyse(local: Path, validate_runs: list[Path]) -> dict[str, Any]:
    tokenizer = build_tokenizer(gguf_tokenizer_metadata(local / GGUF))
    report: dict[str, Any] = {"recipe": "grp1", "recipe_hash": R.BUILTIN["grp1"].recipe_hash,
                              "control": "dp10-cut", "control_hash": R.BUILTIN["dp10-cut"].recipe_hash,
                              "tokenizer_check": validate(tokenizer, validate_runs), "sets": {}}
    dev = load_set("dev", local)
    sets = {"dev": dev, "dev_series": [s for s in dev if s.category == "anime_series"],
            "dev_movie": [s for s in dev if s.category == "animation_movie"], "product": load_set("product", local)}
    for name, scenes in sets.items():
        report["sets"][name] = coverage(scenes, tokenizer)
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--local-root", type=Path, default=sim7.REPO / ".local")
    parser.add_argument("--validate", type=Path, action="append", default=[],
                        help="用其 /tokenize 交换记录核对离线 token 计数的 run 目录（可多次）")
    parser.add_argument("--json", type=Path, help="可选：完整结果写入此 JSON（放 .local 下）")
    args = parser.parse_args(argv)
    report = analyse(args.local_root, args.validate)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
