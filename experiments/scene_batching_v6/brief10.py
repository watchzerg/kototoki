"""v10 stage E1: one work brief per work (``work-brief-v1``, §4.5), injected through ``qwen_options.brief``.

One request per work on the Qwen server with the names-stage request values (context 20480, ``--reasoning off``,
sampling 0.7 / 0.8 / 20 / 0 with presence_penalty 1.5, prompt budget context − max_tokens − 512, at most two
attempts with seed + 1). Input: the whole Japanese of the work (dev: its dev scenes in scene order, one cue per
line, a blank line between scenes; product: the film's ``ja.srt``). Output: free text of at most 300 Chinese
characters; it is not a translation and no subtitle is produced. A reply over the limit or cut by the token
limit or an empty reply is a failed attempt; the length is asked for in the prompt and recorded (Han characters),
not enforced. Briefs are transcript content: they stay under ``.local`` and are not printed.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from experiments.translation_v3 import qwen
from experiments.translation_v3 import recipes as R
from experiments.translation_v3.common import atomic_write_json, sha256_bytes, utc_now

from .v10 import V10_ROOT

VERSION = "work-brief-v1"
MAX_CHARS = 300  # asked for in the prompt
HAN = re.compile(r"[一-鿿]")
MAX_TOKENS = 1024
CONTEXT = 20480
BUDGET = CONTEXT - MAX_TOKENS - 512
SAMPLING = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0, "presence_penalty": 1.5}
SEED = 20261022
SYSTEM = ("你是日本动画影视作品的中文字幕翻译统筹。用户给出一部作品的日文台词全文（一行一条，空行分隔场景）。"
          "请为逐段翻译这部作品的译者写一份不超过 300 字的中文翻译简报，内容只包括：\n"
          "1. 作品类型与整体语体（如校园日常、热血战斗、悬疑；口语程度）；\n"
          "2. 主要角色：日文写法、通行或合适的中文译名、身份，以及角色之间的称呼方式；\n"
          "3. 人称与敬语习惯（谁对谁用敬语、谁的口头禅或自称有特点）；\n"
          "4. 应保持统一的术语风格。\n"
          "不翻译台词，不复述剧情，不推测原文没有的信息；不确定的内容不写。只输出简报正文。")
USER = "以下是作品的日文台词全文：\n\n{lines}\n\n请输出翻译简报。"


def messages(lines: list[str]) -> list[dict[str, str]]:
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER.format(lines="\n".join(lines))}]


def dev_lines() -> dict[str, list[str]]:
    from experiments.translation_v4.common import DEFAULT_ROOT as V4_ROOT
    from experiments.translation_v4.gen import set_scenes
    from . import q2, v9
    out: dict[str, list[str]] = {}
    scenes = sorted((s for seed in v9.MAIN_SEEDS for s in set_scenes(V4_ROOT, q2.SET, seed)[0]),
                    key=lambda s: s.scene_id)
    for scene in scenes:
        rows = out.setdefault(scene.work_id, [])
        if rows:
            rows.append("")
        rows += [c.text.replace("\n", " ") for c in scene.cues]
    return out


def product_lines() -> dict[str, list[str]]:
    from experiments.quality_v5 import asr_source as A
    from .asr10 import FILMS
    return {film: [c["text"] for c in A.read_srt(paths["ja"])] for film, paths in FILMS.items()}


def build(kind: str, *, root: Path = V10_ROOT, port: int = 8080, break_stale_lock: bool = False) -> dict[str, Any]:
    """GPU: one brief per work of ``kind`` ("dev" or "product") -> ``E/briefs-<kind>.json``."""
    works = dev_lines() if kind == "dev" else product_lines()
    recipe = R.compose("brief-server", "qwen-wide", qwen_options={"context": CONTEXT})
    out_path = root / "E" / f"briefs-{kind}.json"
    run_dir = root / "E" / f"session-{kind}"
    factory = qwen.session_factory(root, f"brief-{kind}", recipe, port=port, break_stale_lock=break_stale_lock)
    result: dict[str, Any] = {"version": VERSION, "system_sha256": sha256_bytes(SYSTEM.encode()),
                              "started_at_utc": utc_now(), "briefs": {}, "meta": {}}
    started = time.perf_counter()
    index = len(list((run_dir / "runtime").glob("session-*"))) + 1 if (run_dir / "runtime").is_dir() else 1
    with factory(run_dir, index) as handle:
        client = handle.client
        for work, lines in sorted(works.items()):
            msgs = messages(lines)
            rendered = client.request("/apply-template", {"messages": msgs, "chat_template_kwargs": {"enable_thinking": False}})
            tokens = len(client.tokenize(rendered["prompt"]))
            meta: dict[str, Any] = {"lines": len(lines), "prompt_tokens": tokens, "attempts": []}
            result["meta"][work] = meta
            if tokens > BUDGET:
                meta["status"] = "too_long"
                continue
            for attempt in range(2):
                body = {"messages": msgs, **SAMPLING, "seed": SEED + attempt, "max_tokens": MAX_TOKENS,
                        "chat_template_kwargs": {"enable_thinking": False}, "stream": False}
                t0 = time.perf_counter()
                reply = client.chat_completion(body)
                choice = reply["choices"][0]
                text = ((choice.get("message") or {}).get("content") or "").strip()
                row = {"seed": SEED + attempt, "seconds": time.perf_counter() - t0, "finish": choice.get("finish_reason"),
                       "chars": len(text), "han_chars": len(HAN.findall(text)),
                       "completion_tokens": (reply.get("usage") or {}).get("completion_tokens")}
                meta["attempts"].append(row)
                if choice.get("finish_reason") != "length" and text:
                    result["briefs"][work] = text
                    meta["status"] = "ok"
                    break
            else:
                meta["status"] = "failed"
    result["wall_seconds"] = time.perf_counter() - started
    atomic_write_json(out_path, result)
    return {"works": len(works), "ok": len(result["briefs"]), "wall_seconds": result["wall_seconds"],
            "status": {w: m["status"] for w, m in result["meta"].items()}}
