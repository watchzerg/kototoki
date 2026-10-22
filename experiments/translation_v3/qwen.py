"""v9: Qwen3.8-27B UD-IQ3_S translating the same packs (docs/research/2026-10-21-general-model-translation-v9.md).

``qwen-joint-v1`` is the Hy-MT2 joint prompt split into chat messages without rewording: the system message is
the task text of ``adapters.render("hy-mt2-30b")`` with the joint sentence (everything before the read-only
context), the user message is the read-only context and the target JSON. The request goes to
``/v1/chat/completions`` (``--jinja``, ``--reasoning off``) with the unchanged ID GBNF as ``grammar`` (the same
constraint text as the control, so validation stays ``recipes.parse_translation`` plus the key order check).
The input budget is measured on the server-rendered chat prompt (``/apply-template`` + ``/tokenize``).

Server: ``kototoki.llama_server.ManagedServer`` with the names-stage ``ServerSpec`` values (official b11669
build, ``-b 512 -ub 512 -fa on --jinja --reasoning off``, 99 layers) and the v9 context; the v3 GPU lock and a
KILL_ON_JOB_CLOSE job are added here. Model identity and server values are copied from
``kototoki/names/recipes.py`` (2026-10-21) so a product change does not move the v9 recipe hashes.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import time
from typing import Any, Iterator
from urllib.error import HTTPError, URLError

from experiments.translation_demo import adapters

from . import recipes as R
from .common import REPO, object_hash, sha256_bytes

MODEL = R.QWEN_MODEL
MODEL_ASSET = {"repo": "unsloth/Qwen3.8-27B-GGUF", "revision": "4ca720788d1e01f1bff70c033e0d0028fd02e502",
               "file": "Qwen3.8-27B-UD-IQ3_S.gguf", "size": 12040883104,
               "sha256": "d847e2c1e4aa276e4b7b8e9ad7628050e61e165d49ab995407bc36677a6f3864"}
MODEL_PATH = REPO / ".local/models/glossary-v1/Qwen3.8-27B-UD-IQ3_S.gguf"
ENGINE = REPO / ".local/tools/llama.cpp/b11669-cuda13.4/llama-server.exe"
ENGINE_VERSION = "b11669-cuda13.4"
LAYERS = 99
EXTRA_ARGS = ("-b", "512", "-ub", "512", "-fa", "on", "--jinja", "--reasoning", "off")
MIN_FREE_MIB = 13000
LOAD_TIMEOUT_SECONDS = 180
NARROW_CONTEXT = 8192
WIDE_CONTEXT = 16384

PROMPT_VERSION = "qwen-joint-v1"
CONTEXT_HEADER = "【只读日文上下文】\n"
# Qwen official non-thinking sampling; presence_penalty 0 (§4.2: 1.5 only if the smoke shows repetition loops).
SAMPLING = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0, "presence_penalty": 0.0}
SEED_STEP = 1  # attempt N uses seed + (N - 1) * SEED_STEP, as in the names stage
REQUEST_SHAPE = "chat-completions+gbnf-grammar+apply-template-budget"


# --- v10 options (docs/research/2026-10-21-q0-exploration-v10.md) ---------------------------------
# ``Recipe.qwen_options`` changes one thing at a time on top of qwen-joint-v1; absent keys keep v1 behaviour and
# recipes without options keep their hash. Texts are versioned by name and their sha256 goes into the hash.
# "system": v2 keeps the whole v1 rule text verbatim and adds a translator role before it and subtitle
# naturalness requirements after it (§4.2 B1; no examples, no names, user message unchanged).
QWEN_JOINT_V2_ROLE = "你是日本动画影视作品的中文字幕译者，为中文观众制作字幕。"
QWEN_JOINT_V2_STYLE = ("字幕中文的要求：\n"
                       "- 用自然的中文口语，像中文母语者在同样情境下会说的话；在每条之内按中文习惯组织语序和用词，"
                       "避免翻译腔和逐词直译，不机械保留日文的句式、助词、敬语形式或多余的人称代词。\n"
                       "- 简洁易读，长度与原文相称，不为凑字添词。\n"
                       "- 语气词、称呼和口头禅换成中文里自然的说法，同一人物的口吻前后一致。\n"
                       "- 不解释、不加注、不加括号说明。")
# v2b: the one wording revision allowed by §4.2 after v2 improved unnatural but lost accuracy (meaning drift:
# modality stated as fact, idioms swapped for Chinese sayings of another meaning, referents rewritten). Same role;
# the style block keeps naturalness, drops the nudge to omit pronouns / honorific forms, adds "change wording only".
QWEN_JOINT_V2B_STYLE = ("字幕中文的要求：\n"
                        "- 用自然的中文口语，像中文母语者在同样情境下会说的话；在每条之内按中文习惯组织语序和用词，"
                        "避免翻译腔和逐词直译，不机械保留日文的句式和助词。\n"
                        "- 自然化只改说法、不改意思：谁对谁说、指代对象、推测／愿望／不确定等语气的强弱、否定与条件都与原文一致；"
                        "拿不准的惯用说法按原意翻译，不套用意思不同的中文俗语。\n"
                        "- 简洁易读，长度与原文相称，不为凑字添词。\n"
                        "- 语气词、称呼和口头禅换成中文里自然的说法，同一人物的口吻前后一致。\n"
                        "- 不解释、不加注、不加括号说明。")
SYSTEMS = {"qwen-joint-v2": (QWEN_JOINT_V2_ROLE, QWEN_JOINT_V2_STYLE),
           "qwen-joint-v2b": (QWEN_JOINT_V2_ROLE, QWEN_JOINT_V2B_STYLE)}
# "asr": a paragraph appended to the system text: the source is a speech-recognition transcript (§4.4 D1).
ASR_TEXTS = {"qwen-asr-aware-v1": (
    "注意：日文原文是语音识别自动生成的稿子，可能含有同音或近音误识、片假名人名与外来语的误读、断句错误和漏字。"
    "请结合上下文和你对这部作品的了解，按说话人最可能的原话来翻译；无法确定时按字面翻译。"
    "不得补写原文没有的内容，也不得因为纠正而改变各 ID 的承载范围。")}
# "names": {"filter": "window"|"all", "tables": {work_id: [{"source", "translation"}]}} (§4.4 D2).
NAMES_VERSION = "qwen-name-table-v1"
NAMES_HEADER = "本作品专名的固定中文译法（日文写法 → 中文）。原文出现这些写法时使用对应译法：\n"
# "brief": {work_id: text} (§4.5 E1); the text is produced per work beforehand and is not a translation.
BRIEF_VERSION = "qwen-work-brief-v1"
BRIEF_HEADER = "本作品的翻译简报（仅供理解，不要输出）：\n"
# "thinking": {"budget": N, "min_visible": K} (§4.6 F1): the server runs ``--reasoning on --reasoning-budget N``;
# packs with at least K target cues ask for thinking (``enable_thinking``) and get N more output tokens, the
# others are requested exactly as v1 (non-thinking). The thought goes to ``reasoning_content`` and is not parsed.
# The ID grammar applies from the first generated token, so a thinking pack gets it behind a free thought prefix
# (the template opens ``<think>``; the budget sampler forces ``</think>``); a thought may not contain "<".
THOUGHT_GRAMMAR_VERSION = "thought-prefix-v1"
OPTION_KEYS = ("system", "asr", "names", "brief", "context", "thinking")


def check_options(options: Any) -> None:
    if not isinstance(options, dict) or not options or set(options) - set(OPTION_KEYS):
        raise ValueError(f"qwen_options must be a non-empty object with keys from {OPTION_KEYS}")
    if "system" in options and options["system"] not in SYSTEMS:
        raise ValueError(f"qwen_options.system must be one of {sorted(SYSTEMS)}")
    if "asr" in options and options["asr"] not in ASR_TEXTS:
        raise ValueError(f"qwen_options.asr must be one of {sorted(ASR_TEXTS)}")
    names = options.get("names")
    if names is not None and (
            not isinstance(names, dict) or set(names) != {"filter", "tables"} or names["filter"] not in ("window", "all")
            or not isinstance(names["tables"], dict) or not names["tables"] or not all(
                isinstance(rows, list) and all(isinstance(r, dict) and set(r) == {"source", "translation"}
                                               and all(isinstance(v, str) and v.strip() for v in r.values()) for r in rows)
                for rows in names["tables"].values())):
        raise ValueError("qwen_options.names must be {filter: window|all, tables: {work: [{source, translation}]}}")
    brief = options.get("brief")
    if brief is not None and (not isinstance(brief, dict) or not brief
                              or not all(isinstance(v, str) and v.strip() for v in brief.values())):
        raise ValueError("qwen_options.brief must map work ids to non-empty texts")
    if "context" in options and (type(options["context"]) is not int or options["context"] < WIDE_CONTEXT):
        raise ValueError(f"qwen_options.context must be an integer >= {WIDE_CONTEXT}")
    thinking = options.get("thinking")
    if thinking is not None and (not isinstance(thinking, dict) or set(thinking) != {"budget", "min_visible"}
                                 or not all(type(v) is int and v > 0 for v in thinking.values())):
        raise ValueError("qwen_options.thinking must be {budget: int > 0, min_visible: int > 0}")


def _options(recipe: R.Recipe | None) -> dict[str, Any]:
    return (recipe.qwen_options or {}) if recipe is not None else {}


def system_text(recipe: R.Recipe | None) -> str:
    """The window-independent system text of a recipe (v1, or v1 with versioned additions)."""
    options = _options(recipe)
    text = system_template()
    if "system" in options:
        role, style = SYSTEMS[options["system"]]
        text = role + "\n\n" + text + "\n\n" + style
    if "asr" in options:
        text += "\n\n" + ASR_TEXTS[options["asr"]]
    return text


def names_for_window(recipe: R.Recipe | None, work_id: str | None, window: dict[str, Any]) -> list[dict[str, str]]:
    names = _options(recipe).get("names")
    if not names or work_id is None:
        return []
    rows = names["tables"].get(work_id, [])
    if names["filter"] == "window":
        text = "".join(item["text"] for item in window["context"])
        rows = [r for r in rows if r["source"] in text]
    return [dict(r) for r in rows]


def context_size(recipe: R.Recipe) -> int:
    if "context" in _options(recipe):
        return recipe.qwen_options["context"]
    return WIDE_CONTEXT if recipe.wide_context else NARROW_CONTEXT


def thinks(recipe: R.Recipe | None, ids: list[str]) -> bool:
    thinking = _options(recipe).get("thinking")
    return bool(thinking) and len(ids) >= thinking["min_visible"]


def max_tokens(recipe: R.Recipe | None, ids: list[str]) -> int:
    return R.N_PREDICT + (_options(recipe)["thinking"]["budget"] if thinks(recipe, ids) else 0)


def max_input_tokens(recipe: R.Recipe, ids: list[str] | None = None) -> int:
    return context_size(recipe) - max_tokens(recipe, ids or []) - R.GUARD_TOKENS


def think_grammar(grammar: str) -> str:
    return 'root ::= thought "</think>" ws answer\nthought ::= [^<]*\n' + grammar.replace("root ::=", "answer ::=", 1)


def extra_args(recipe: R.Recipe) -> tuple[str, ...]:
    thinking = _options(recipe).get("thinking")
    if not thinking:
        return EXTRA_ARGS
    assert EXTRA_ARGS[-2:] == ("--reasoning", "off")
    return (*EXTRA_ARGS[:-1], "on", "--reasoning-budget", str(thinking["budget"]))


def system_template() -> str:
    """The fixed system text (window-independent): the joint task text before the read-only context."""
    return messages({"id": "x", "source_language": "ja", "target_language": "zh-Hans",
                     "context": [{"id": "x", "text": "x"}], "translate_ids": ["x"]})[0]["content"]


def versions(recipe: R.Recipe) -> dict[str, Any]:
    out = {"model": MODEL, "asset_sha256": MODEL_ASSET["sha256"], "engine": ENGINE_VERSION,
           "server_args": [LAYERS, *extra_args(recipe)], "prompt": [PROMPT_VERSION, sha256_bytes(system_template().encode())],
           "request": REQUEST_SHAPE, "seed_step": SEED_STEP}
    options = _options(recipe)
    if options:
        extra: dict[str, Any] = {"system_text_sha256": sha256_bytes(system_text(recipe).encode())}
        if "names" in options:
            extra["names"] = [NAMES_VERSION, sha256_bytes(NAMES_HEADER.encode())]
        if "brief" in options:
            extra["brief"] = [BRIEF_VERSION, sha256_bytes(BRIEF_HEADER.encode())]
        if "thinking" in options:
            extra["thinking"] = dict(options["thinking"], grammar=[THOUGHT_GRAMMAR_VERSION,
                                                                   sha256_bytes(think_grammar("root ::= x").encode())])
        out["options"] = extra
    return out


def fixed(recipe: R.Recipe) -> dict[str, Any]:
    return {"sampling": SAMPLING | {"seed": "<run seed>"}, "n_predict": R.N_PREDICT, "context_size": context_size(recipe),
            "guard_tokens": R.GUARD_TOKENS, "cache_prompt": R.CACHE_PROMPT, "max_attempts": R.MAX_ATTEMPTS,
            "chat_template_kwargs": {"enable_thinking": False},
            **({"thinking": dict(_options(recipe)["thinking"], packs="target cues >= min_visible",
                                 max_tokens="n_predict + budget")} if "thinking" in _options(recipe) else {}),
            "overflow": "recorded-failure-no-truncation-no-auto-shrink"}


def messages(window: dict[str, Any], recipe: R.Recipe | None = None,
             work_id: str | None = None) -> list[dict[str, str]]:
    """v1 messages; with ``recipe.qwen_options`` the system text is replaced or extended (per work: brief,
    name table), the user message is unchanged."""
    system, user = _v1_messages(window)
    options = _options(recipe)
    if options:
        system = system_text(recipe)
        if "brief" in options:
            if work_id not in options["brief"]:
                raise ValueError(f"qwen_options.brief has no entry for work {work_id!r}")
            system += "\n\n" + BRIEF_HEADER + options["brief"][work_id]
        entries = names_for_window(recipe, work_id, window)
        if entries:
            system += "\n\n" + NAMES_HEADER + "\n".join(f"{e['source']} → {e['translation']}" for e in entries)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _v1_messages(window: dict[str, Any]) -> tuple[str, str]:
    native = adapters.render(R.FAMILY, window)
    if native.count(R.C0_INSTRUCTION) != 1:
        raise ValueError("Frozen C0 instruction changed; version the qwen prompt")
    native = native.replace(R.C0_INSTRUCTION, R.JOINT_INSTRUCTION, 1)
    task = native.split("<｜hy_User｜>", 1)[1].rsplit(R.ASSISTANT_MARKER, 1)[0]
    if task.count("\n" + CONTEXT_HEADER) != 1:
        raise ValueError("Frozen C0 task layout changed; version the qwen prompt")
    system, user = task.split("\n" + CONTEXT_HEADER, 1)
    return system, CONTEXT_HEADER + user


def request_body(messages_: list[dict[str, str]], seed: int, grammar: str, *, think: bool = False,
                 max_tokens_: int = R.N_PREDICT) -> dict[str, Any]:
    return {"messages": messages_, **SAMPLING, "seed": seed, "max_tokens": max_tokens_, "grammar": grammar,
            "cache_prompt": R.CACHE_PROMPT, "chat_template_kwargs": {"enable_thinking": think}, "stream": False}


def parse(text: str, ids: list[str]) -> dict[str, str]:
    """``recipes.parse_translation`` (ID set, non-empty values, one envelope) plus the target order."""
    result = R.parse_translation(text, ids)
    if list(result) != ids:
        raise ValueError("Translation ID order mismatch")
    return result


def run_step(client: Any, messages_: list[dict[str, str]], grammar: str, seed: int, ids: list[str],
             cache_state: dict[str, Any], record: dict[str, Any], recipe: R.Recipe) -> dict[str, str]:
    """``generate.run_step`` for chat completions: budget on the rendered prompt, at most two attempts
    (the second with seed + 1); attempt records use the same keys as the Hy-MT2 path."""
    from experiments.translation_demo.run import explicit_oom
    from .generate import CONTEXT_ERROR, FATAL_KINDS, StepFailed, _http_body, whitespace_ratio
    attempts: list[dict[str, Any]] = record.setdefault("attempts", [])
    last: StepFailed | None = None
    think = thinks(recipe, ids)
    if think:
        grammar = think_grammar(grammar)
    limit = max_tokens(recipe, ids)
    budget = max_input_tokens(recipe, ids)
    for number in range(1, R.MAX_ATTEMPTS + 1):
        started = time.perf_counter()
        used_seed = seed + (number - 1) * SEED_STEP
        body = request_body(messages_, used_seed, grammar, think=think, max_tokens_=limit)
        attempt: dict[str, Any] = {"attempt": number, "seed": used_seed, "thinking": think,
                                   "prompt_sha256": sha256_bytes(json.dumps(messages_, ensure_ascii=False).encode()),
                                   "grammar_sha256": sha256_bytes(grammar.encode("utf-8")), "dispatched": False}
        attempts.append(attempt)
        try:
            try:
                rendered = client.request("/apply-template", {"messages": messages_,
                                                              "chat_template_kwargs": {"enable_thinking": think}})
                tokens = client.tokenize(rendered["prompt"])
            except (URLError, ConnectionError, TimeoutError) as exc:
                raise StepFailed(f"tokenize transport: {exc}", "server") from exc
            attempt.update(input_tokens=len(tokens), rendered_prompt_sha256=sha256_bytes(rendered["prompt"].encode()))
            if len(tokens) > budget:
                raise StepFailed(f"context_budget: {len(tokens)} input tokens + {limit} + {R.GUARD_TOKENS} "
                                 f"> {context_size(recipe)}; no truncation or auto-shrink", "context")
            attempt["request_sha256"] = object_hash(body)
            attempt["dispatched"] = True
            completion_start = time.perf_counter()
            try:
                response = client.chat_completion(body)
            except HTTPError as exc:
                text = _http_body(client) + str(exc)
                kind = "oom" if explicit_oom(text) else "context" if CONTEXT_ERROR.search(text) else "server_error"
                raise StepFailed(f"HTTP {exc.code}: {text[:500]}", kind) from exc
            except (URLError, ConnectionError, TimeoutError) as exc:
                raise StepFailed(f"completion transport: {exc}", "server") from exc
            finally:
                attempt.update(completion_seconds=time.perf_counter() - completion_start,
                               exchange=getattr(client, "last_exchange", None))
            timings = response.get("timings") if isinstance(response.get("timings"), dict) else {}
            usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
            choice = (response.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            content = message.get("content")
            reasoning = message.get("reasoning_content")
            attempt.update(output_tokens=usage.get("completion_tokens"), tokens_evaluated=usage.get("prompt_tokens"),
                           timings=timings, stop_type=choice.get("finish_reason"),
                           stopped_limit=choice.get("finish_reason") == "length", truncated=False,
                           content_chars=len(content) if isinstance(content, str) else None,
                           reasoning_chars=len(reasoning) if isinstance(reasoning, str) else 0)
            if usage.get("prompt_tokens") is not None and usage["prompt_tokens"] != len(tokens):
                attempt["prompt_token_mismatch"] = [len(tokens), usage["prompt_tokens"]]
            if not cache_state.get("checked"):
                reuse = timings.get("cache_n")
                cache_state.update(checked=True, first_cache_n=reuse, verified=type(reuse) is int and reuse == 0,
                                   exchange=attempt.get("exchange"))
                attempt["cache_reset_check"] = dict(cache_state)
                if not cache_state["verified"]:
                    raise StepFailed(f"First completion lacks timings.cache_n == 0 (got {reuse!r})", "cache")
            if response.get("error") is not None:
                text = json.dumps(response["error"], ensure_ascii=False)
                raise StepFailed("server error: " + text, "oom" if explicit_oom(text) else "server_error")
            if attempt["stopped_limit"]:
                attempt["whitespace_ratio"] = whitespace_ratio(content)
                raise StepFailed("generation reached the output/context limit", "limit")
            if not isinstance(content, str) or not content.strip():
                raise StepFailed("empty generated text", "parse")
            try:
                result = parse(content, ids)
            except ValueError as exc:
                attempt["whitespace_ratio"] = whitespace_ratio(content)
                raise StepFailed(f"validation: {exc}", "parse") from exc
            attempt["status"] = "accepted"
            record["status"] = "accepted"
            return result
        except StepFailed as exc:
            attempt.update(status="failed", error=str(exc)[:2000], error_kind=exc.kind)
            last = exc
            if exc.kind in FATAL_KINDS or exc.kind == "context":
                break
        finally:
            attempt["elapsed_seconds"] = time.perf_counter() - started
    assert last is not None
    record.update(status="failed", error_kind=last.kind)
    raise last


def server_spec(recipe: R.Recipe):
    from kototoki.llama_server import ServerSpec
    return ServerSpec(stage="v9-translate", candidate=MODEL, model_asset=dict(MODEL_ASSET), layers=LAYERS,
                      context=context_size(recipe), extra_args=extra_args(recipe), min_free_mib=MIN_FREE_MIB,
                      load_timeout_s=LOAD_TIMEOUT_SECONDS)


def session_factory(root: Path, run_id: str, recipe: R.Recipe, *, port: int = 8080, break_stale_lock: bool = False,
                    timeout: float = 600.0):
    """Real GPU session: v3 gpu.lock + product ManagedServer (Qwen spec) in a kill-on-close job + loopback client."""
    @contextmanager
    def factory(run_dir: Path, index: int) -> Iterator[Any]:
        from kototoki.llama_server import LlamaClient, ManagedServer
        from .generate import SessionHandle
        from .procs import KillOnCloseJob, process_created
        from .server import GpuLock
        lock = GpuLock(run_id)
        lock.acquire(break_stale=break_stale_lock)
        job = KillOnCloseJob()
        holder: dict[str, Any] = {}

        def on_pid(pid: int | None) -> None:
            if pid is None:
                return
            holder["created"] = process_created(pid)
            holder["kill_on_job_close"] = job.assign(holder["server"].process)
            lock.update(server_pid=pid, server_created=holder["created"])
        try:
            server = ManagedServer(run_dir / "runtime" / f"session-{index:02d}", server_spec(recipe), engine=ENGINE,
                                   model=MODEL_PATH, port=port, model_cache=root / "cache/model-verification.json",
                                   on_pid=on_pid)
            holder["server"] = server
            with server:
                client = LlamaClient(server.url, timeout=timeout, trace_dir=run_dir / "transport" / f"session-{index:02d}")
                yield SessionHandle(client, dict(server.identity, server_created=holder.get("created"),
                                                 kill_on_job_close=holder.get("kill_on_job_close"),
                                                 gpu_lock_replaced_stale=lock.stale, owner_pid=lock.pid,
                                                 owner_created=lock.created))
        finally:
            job.close()
            lock.release()
    return factory
