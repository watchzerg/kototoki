"""票据 04：C 臂——Strata 上的 Flash-Next 只读前后文（C2 另给专名表）修正日文转写错字；单元口径评估与改动分类。

- 输入：对照 `ja.srt`（cue 文字与时间）。按 cue 顺序切包：每包 20 条待校正，前 10、后 5 条只读邻文。
- 提示 `ja-correct-v1`（§4.3）：system 说明只修错字、不改说法、不补漏、不删句、没把握保持原文；user 给只读邻文与
  待校正 JSON；输出 `{id: 修正后文字}` 只列有改动的条目。C2 在 system 末尾加专名表：表里没有"规范日文写法"字段，
  按 §4.3 注入每个 `confidence: high` 实体的全部 `forms[]` 日文写法并说明这些写法指同一人物。
- 采样 `temperature 0.3, top_p 0.8, top_k 20, min_p 0, presence_penalty 0`，seed 20261109，`max_tokens` 2048，思考关闭。
- 程序守卫：只接受字符级编辑比 ≤0.5 且非空的改动；JSON 解析失败或触顶的包换 seed＋1 重试一次，仍失败整包保持原文。
- Strata：复用产品 `kototoki.strata.StrataServer`（`strata launch --no-tui --model iq3_s`、ADR-0017 接入检查、专家区未锁进
  内存即拒绝、`--stop` 与显存释放核实）；开跑前 `--plan` 确认下载量为 0，可用内存 ≥52 GiB，无 gpu.lock／llama-server／
  Strata 实例。一次 session 内跑完 C1、C2 两部。
- 评估（无 GPU）：校正后 `ja.srt` 对参考的单元 CER 与对照比；逐被改 cue 判改好／改坏／无影响；改写倾向＝改动引入的字符里
  参考单元没有的比例。
校正输出与转写只写 `.local/`，报告只含计数与指标。
"""

from __future__ import annotations

import json
import random
import re
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Iterator
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from experiments.asr_robustness_v14 import common
from experiments.quality_v5 import asr_source
from kototoki import artifacts
from kototoki.artifacts import object_hash
from kototoki.srt import format_srt
from kototoki.translate.recipes import strict_json
from kototoki_eval.schema import normalize

TICKET = common.ROOT / "04"
PACK = 20
BEFORE = 10
AFTER = 5
SEED = 20261109
MAX_TOKENS = 2048
MAX_EDIT_RATIO = 0.5
SAMPLING = {"temperature": 0.3, "top_p": 0.8, "top_k": 20, "min_p": 0.0, "presence_penalty": 0.0}
BASE = "http://127.0.0.1:8080"

PROMPTS: dict[str, str] = {
    "ja-correct-v1": (
        "你是日语语音识别（ASR）转写字幕的校对员。任务：只修正转写里的错字——同音／近音误识、人名误识、明显不成词的片段。"
        "规则：不改说法、不润色、不补漏、不删句、不合并或拆分条目；除错字外不改任何正确的文字，标点保持原样；"
        "只读邻文只用来理解上下文（人名、话题），不要输出它们；没有把握就保持原文。"
        "输出一个 JSON 对象：键是待校正条目的 id，值是修正后的整条文字；只列有改动的条目，没有改动就输出 {}。"
        "不输出解释或代码围栏。"),
    # v2：v1 的改动里约四成是改写（改助词、语序、敬体、补词），引入的字六成以上不在参考里；v2 把「只改错字」收紧为
    # 「只改读音相同或极近的字」，并把口语、省略、语气词、重复明确列为不改对象（§4.3 允许的一次提示修订）。
    "ja-correct-v2": (
        "你是日语语音识别（ASR）转写字幕的校对员。任务：只修正转写里「听错的字」——同音／近音误识（如「以外／意外」「橋／箸」）、"
        "人名误识、明显不成词的片段。判定标准：修正后的读音必须与原文相同或极其接近；改动会让读音变化的，就不是听错，不要改。"
        "明确不改：助词、语序、敬体／常体、句尾语气词、口语省略、重复与结巴、方言、断句位置；不润色、不补漏、不删句、不合并或拆分条目；"
        "标点保持原样；只读邻文只用来理解上下文（人名、话题），不要输出它们。宁可漏改，不可误改：没有十足把握就保持原文。"
        "输出一个 JSON 对象：键是待校正条目的 id，值是修正后的整条文字；只列有改动的条目，没有改动就输出 {}。"
        "不输出解释或代码围栏。"),
}
NAMES_HEADER = "本作品专名的日文写法（同一行的写法指同一人物或事物；转写里与之同音或近音的片段应修正为这些写法）：\n"
CONTEXT_BEFORE = "【只读邻文（前）】\n"
TARGET_HEADER = "\n【待校正条目（JSON，键为 id）】\n"
CONTEXT_AFTER = "\n【只读邻文（后）】\n"


def recipe(prompt: str, arm: str) -> dict[str, Any]:
    from kototoki import strata

    return {"schema": "v14-ja-correct-v1", "prompt": prompt, "system_sha256": artifacts.sha256_bytes(PROMPTS[prompt].encode()),
            "pack": {"targets": PACK, "before": BEFORE, "after": AFTER}, "arm": arm,
            "names": None if arm == "c1" else {"header_sha256": artifacts.sha256_bytes(NAMES_HEADER.encode()),
                                                "rows": "confidence high; entity_ja: all forms[].ja"},
            "model": strata.MODEL, "runtime": {"strata": strata.STRATA_VERSION, "engine_build": strata.STRATA_ENGINE_BUILD,
                                               "launch": strata.STRATA_LAUNCH},
            "request": {"sampling": SAMPLING, "seed": SEED, "max_tokens": MAX_TOKENS,
                        "chat_template_kwargs": {"enable_thinking": False}, "attempts": 2, "seed_step": 1},
            "guard": {"max_edit_ratio": MAX_EDIT_RATIO, "nonempty": True}}


# --- 切包与提示 -----------------------------------------------------------------------------------

def cue_id(cue: dict[str, Any]) -> str:
    return f"c{cue['index']}"


def packs(cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for start in range(0, len(cues), PACK):
        out.append({"number": len(out) + 1, "before": cues[max(0, start - BEFORE):start],
                    "targets": cues[start:start + PACK], "after": cues[start + PACK:start + PACK + AFTER]})
    return out


def name_lines(table: dict[str, Any]) -> list[str]:
    lines = []
    for entity in table["entries"]:
        if entity.get("confidence") != "high":
            continue
        forms = []
        for form in [{"ja": entity["entity_ja"]}, *entity.get("forms", [])]:
            ja = (form.get("ja") or "").strip()
            if ja and ja not in forms:
                forms.append(ja)
        if forms:
            lines.append("／".join(forms))
    return lines


def messages(pack: dict[str, Any], prompt: str, names: list[str] | None) -> list[dict[str, str]]:
    system = PROMPTS[prompt]
    if names:
        system += "\n\n" + NAMES_HEADER + "\n".join(names)
    lines = lambda cues: "\n".join(f"{cue_id(c)}: {c['text']}" for c in cues) or "（无）"  # noqa: E731
    target = json.dumps({cue_id(c): c["text"] for c in pack["targets"]}, ensure_ascii=False)
    user = CONTEXT_BEFORE + lines(pack["before"]) + TARGET_HEADER + target + CONTEXT_AFTER + lines(pack["after"])
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def request_body(messages_: list[dict[str, str]], seed: int) -> dict[str, Any]:
    from kototoki import strata

    return {"model": strata.MODEL, "messages": messages_, **SAMPLING, "seed": seed, "max_tokens": MAX_TOKENS,
            "chat_template_kwargs": {"enable_thinking": False}, "stream": False}


# --- 回复守卫 -------------------------------------------------------------------------------------

def edit_ratio(before: str, after: str) -> float:
    return asr_source.edit_distance(before, after) / max(1, len(before))


def apply_reply(pack: dict[str, Any], content: str) -> tuple[dict[str, str], dict[str, int]]:
    """解析回复 → (接受的 {id: 新文字}, 计数)；解析失败抛 ValueError。"""
    obj = strict_json(content)
    if not isinstance(obj, dict):
        raise ValueError("reply is not a JSON object")
    targets = {cue_id(c): c["text"] for c in pack["targets"]}
    counts = {"proposed": 0, "unknown_id": 0, "not_string": 0, "empty": 0, "unchanged": 0, "ratio_rejected": 0, "accepted": 0}
    accepted: dict[str, str] = {}
    for key, value in obj.items():
        counts["proposed"] += 1
        if key not in targets:
            counts["unknown_id"] += 1
        elif not isinstance(value, str):
            counts["not_string"] += 1
        elif not value.strip():
            counts["empty"] += 1
        elif value == targets[key]:
            counts["unchanged"] += 1
        elif edit_ratio(targets[key], value) > MAX_EDIT_RATIO:
            counts["ratio_rejected"] += 1
        else:
            counts["accepted"] += 1
            accepted[key] = value
    return accepted, counts


# --- Strata 客户端 -------------------------------------------------------------------------------

def _post(url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    opener = build_opener(ProxyHandler({}))
    request = Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class Client:
    def __init__(self, post: Callable[[str, dict, float], dict] = _post, base: str = BASE, timeout: float = 600.0):
        self.post, self.base, self.timeout = post, base, timeout

    def chat(self, body: dict[str, Any]) -> dict[str, Any]:
        """一次请求 → 记录（无文字）＋ content。"""
        started = perf_counter()
        try:
            response = self.post(self.base + "/v1/chat/completions", body, self.timeout)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
            return {"record": {"seconds": round(perf_counter() - started, 2), "http_status": exc.code,
                               "error": detail[:300], "finish_reason": "http_error"}, "content": None}
        choice = (response.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content, reasoning = message.get("content"), message.get("reasoning_content")
        usage, timings = response.get("usage") or {}, response.get("timings") or {}
        record = {"seconds": round(perf_counter() - started, 2), "finish_reason": choice.get("finish_reason"),
                  "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
                  "content_chars": len(content) if isinstance(content, str) else None,
                  "reasoning_chars": len(reasoning) if isinstance(reasoning, str) else 0,
                  "think_tag": isinstance(content, str) and "<think>" in content,
                  "cache_n": timings.get("cache_n"), "prompt_n": timings.get("prompt_n"),
                  "predicted_per_second": timings.get("predicted_per_second")}
        return {"record": record, "content": content if isinstance(content, str) else None}


def correct_film(cues: list[dict[str, Any]], client: Client, prompt: str, names: list[str] | None,
                 *, seed: int = SEED) -> dict[str, Any]:
    """整部 cue 逐包校正 → {cues（新文字）, changes, packets（计数）, summary}。"""
    corrected = [dict(c) for c in cues]
    by_id = {cue_id(c): i for i, c in enumerate(cues)}
    changes, packets = [], []
    for pack in packs(cues):
        body_messages = messages(pack, prompt, names)
        outcome: dict[str, Any] = {"pack": pack["number"], "targets": len(pack["targets"]), "attempts": []}
        accepted: dict[str, str] = {}
        for attempt in range(2):
            reply = client.chat(request_body(body_messages, seed + attempt))
            record = {"seed": seed + attempt, **reply["record"]}
            if reply["content"] is None or record.get("finish_reason") == "length":
                record["failure"] = "length" if record.get("finish_reason") == "length" else "no_content"
                outcome["attempts"].append(record)
                continue
            try:
                accepted, counts = apply_reply(pack, reply["content"])
            except ValueError as exc:
                record["failure"] = f"parse: {type(exc).__name__}"
                outcome["attempts"].append(record)
                continue
            record.update(counts)
            outcome["attempts"].append(record)
            break
        else:
            outcome["pack_failed"] = True
        for key, text in accepted.items():
            i = by_id[key]
            changes.append({"id": key, "index": cues[i]["index"], "start": cues[i]["start"], "end": cues[i]["end"],
                            "before": cues[i]["text"], "after": text, "pack": pack["number"]})
            corrected[i]["text"] = text
        packets.append(outcome)
    attempts = [a for p in packets for a in p["attempts"]]
    summary = {
        "cues": len(cues), "packs": len(packets), "requests": len(attempts),
        "pack_failed": sum(1 for p in packets if p.get("pack_failed")),
        "retried": sum(1 for p in packets if len(p["attempts"]) > 1),
        "length_failures": sum(1 for a in attempts if a.get("failure") == "length"),
        "parse_failures": sum(1 for a in attempts if str(a.get("failure", "")).startswith("parse")),
        "http_errors": sum(1 for a in attempts if a.get("finish_reason") == "http_error"),
        "reasoning_nonempty": sum(1 for a in attempts if a.get("reasoning_chars")),
        "think_tags": sum(1 for a in attempts if a.get("think_tag")),
        "proposed": sum(a.get("proposed", 0) for a in attempts), "accepted": len(changes),
        "ratio_rejected": sum(a.get("ratio_rejected", 0) for a in attempts),
        "unknown_id": sum(a.get("unknown_id", 0) for a in attempts),
        "unchanged": sum(a.get("unchanged", 0) for a in attempts), "empty": sum(a.get("empty", 0) for a in attempts),
        "seconds": round(sum(a["seconds"] for a in attempts), 1),
        "seconds_per_pack": round(sum(a["seconds"] for a in attempts) / max(1, len(packets)), 2),
        "prompt_tokens": sum(a.get("prompt_tokens") or 0 for a in attempts),
        "completion_tokens": sum(a.get("completion_tokens") or 0 for a in attempts),
        "cache_n_first": attempts[0].get("cache_n") if attempts else None,
    }
    return {"cues": corrected, "changes": changes, "packets": packets, "summary": summary}


# --- Strata session ------------------------------------------------------------------------------

def plan_download_mib(text: str) -> float | None:
    """`strata launch --plan` 输出里的下载量（MiB）；找不到下载行为 None（视为需要人工核对）。"""
    total = 0.0
    found = False
    for line in text.splitlines():
        if "download" not in line.lower():
            continue
        for value, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(GiB|GB|MiB|MB|KiB|KB|B)\b", line):
            found = True
            total += float(value) * {"GiB": 1024, "GB": 1024, "MiB": 1, "MB": 1, "KiB": 1 / 1024, "KB": 1 / 1024, "B": 0}[unit]
        if re.search(r"\b(nothing|no files?|0 files?) to download|download(?:s)?:\s*(none|0)\b", line.lower()):
            found = True
    return total if found else None


def preflight(session_dir: Path) -> dict[str, Any]:
    """§5：无 gpu.lock、无 llama-server、无 Strata 实例、可用内存 ≥52 GiB、`--plan` 下载量为 0。任一不满足即退出，不动任何进程。"""
    from kototoki import strata

    found = common.other_gpu_jobs()
    found["strata_running"] = strata.running(strata.run_cli)
    found["available_ram_gib"] = strata.available_ram_gib()
    plan_text = strata.run_cli(*strata.LAUNCH_ARGS, "--plan", timeout=300.0)
    common.write_text(session_dir / "plan.txt", plan_text)
    found["plan_download_mib"] = plan_download_mib(plan_text)
    blocking = [p for p in found["suspect_processes"] if "llama" in p.lower() or "strata" in p.lower()]
    problems = []
    if found["gpu_lock"]:
        problems.append("gpu_lock")
    if blocking:
        problems.append(f"processes {blocking}")
    if found["strata_running"]:
        problems.append("strata_running")
    if found["available_ram_gib"] is None or found["available_ram_gib"] < strata.MIN_AVAILABLE_RAM_GIB:
        problems.append(f"ram {found['available_ram_gib']}")
    if found["plan_download_mib"] is None or found["plan_download_mib"] > 0:
        problems.append(f"plan_download {found['plan_download_mib']}")
    common.write_json(session_dir / "preflight.json", found)
    if problems:
        raise SystemExit(f"preflight failed: {problems}")
    return found


@contextmanager
def serve(run_dir: Path) -> Iterator[Any]:
    from kototoki.strata import StrataServer

    index = len(list(run_dir.glob("session-*"))) + 1 if run_dir.is_dir() else 1
    session = run_dir / f"session-{index:02d}"
    session.mkdir(parents=True, exist_ok=True)
    preflight(session)
    with common.gpu_lock("v14-04 C ja-correct on Strata"):
        with StrataServer(session) as server:
            yield server


def control_cues(film: str) -> list[dict[str, Any]]:
    return asr_source.read_srt(common.FILMS[film]["work"] / "ja.srt")


def run(arms: tuple[str, ...] = ("c1", "c2"), prompt: str = "ja-correct-v1",
        films: tuple[str, ...] = ("hf-ii", "hf-iii"), *, client: Client | None = None,
        run_name: str | None = None) -> dict[str, Any]:
    run_dir = TICKET / (run_name or prompt)
    recipes = {arm: recipe(prompt, arm) for arm in arms}
    common.write_json(run_dir / "recipes.json", {arm: {**r, "hash": object_hash(r)} for arm, r in recipes.items()})
    results: dict[str, Any] = {}
    started = common.timed()

    def work(server_identity: dict[str, Any]) -> None:
        api = client or Client()
        for arm in arms:
            for film in films:
                names = name_lines(common.read_json(common.FILMS[film]["name_table"])) if arm == "c2" else None
                cues = control_cues(film)
                result = correct_film(cues, api, prompt, names)
                out = run_dir / arm / film
                common.write_text(out / "ja.srt", format_srt([(c["start"], c["end"], c["text"]) for c in result["cues"]]))
                common.write_json(out / "changes.json", result["changes"])
                common.write_json(out / "packets.json", result["packets"])
                results.setdefault(arm, {})[film] = {**result["summary"], "name_rows": len(names) if names else 0}
                common.write_json(run_dir / "progress.json", {"results": results, "identity": server_identity,
                                                              "elapsed_s": round(common.timed() - started, 1)})

    if client is not None:  # 测试：不起 Strata
        work({})
        session_info: dict[str, Any] = {}
    else:
        with serve(run_dir) as server:
            work(server.identity)
            session_info = {k: v for k, v in server.identity.items() if k != "strata"}
            session_info["strata"] = {k: server.identity["strata"].get(k) for k in ("version", "drafting", "expert_arena", "kv")}
    report = {"prompt": prompt, "arms": arms, "films": films, "results": results, "session": session_info,
              "wall_s": round(common.timed() - started, 1), "gpu_run": 1 if client is None else 0}
    common.write_json(run_dir / "run.json", report)
    return report


# --- 评估 -----------------------------------------------------------------------------------------

def unit_index(reference: list[dict[str, Any]], cues: list[dict[str, Any]]) -> tuple[list[tuple[list[int], list[int]]], dict[int, int]]:
    units = asr_source.overlap_units(reference, cues)
    owner = {j: n for n, (_, prods) in enumerate(units) for j in prods}
    return units, owner


def classify_changes(reference: list[dict[str, Any]], control: list[dict[str, Any]], changes: list[dict[str, Any]]
                     ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """逐被改 cue：所在单元 CER 改前／改后（其他 cue 保持对照文字）→ improved／worsened／neutral；改写倾向。"""
    units, owner = unit_index(reference, control)
    by_index = {c["index"]: j for j, c in enumerate(control)}
    rows = []
    for change in changes:
        j = by_index[change["index"]]
        refs, prods = units[owner[j]]
        ref_text = normalize("".join(reference[i]["text"] for i in refs)).text
        before_text = normalize("".join(control[k]["text"] for k in prods)).text
        after_text = normalize("".join(change["after"] if k == j else control[k]["text"] for k in prods)).text
        e_before, e_after = asr_source.edit_distance(ref_text, before_text), asr_source.edit_distance(ref_text, after_text)
        b, a = normalize(change["before"]).text, normalize(change["after"]).text
        introduced = list(a)
        for ch in b:
            if ch in introduced:
                introduced.remove(ch)
        absent = sum(1 for ch in introduced if ch not in ref_text)
        rows.append({**change, "unit": owner[j], "ref_chars": len(ref_text), "edits_before": e_before, "edits_after": e_after,
                     "delta": e_after - e_before,
                     "verdict": "improved" if e_after < e_before else "worsened" if e_after > e_before else "neutral",
                     "introduced_chars": len(introduced), "introduced_absent": absent,
                     "rewrite": bool(introduced) and absent * 2 >= len(introduced),
                     "bucket_before": asr_source.bucket_of("".join(reference[i]["text"] for i in refs),
                                                           "".join(control[k]["text"] for k in prods),
                                                           e_before / len(ref_text) if ref_text else None)})
    introduced = sum(r["introduced_chars"] for r in rows)
    summary = {"changes": len(rows), "improved": sum(1 for r in rows if r["verdict"] == "improved"),
               "worsened": sum(1 for r in rows if r["verdict"] == "worsened"),
               "neutral": sum(1 for r in rows if r["verdict"] == "neutral"),
               "delta_edits_sum": sum(r["delta"] for r in rows),
               "rewrite_cues": sum(1 for r in rows if r["rewrite"]),
               "introduced_chars": introduced, "introduced_absent_from_reference": sum(r["introduced_absent"] for r in rows),
               "introduced_absent_share": round(sum(r["introduced_absent"] for r in rows) / introduced, 4) if introduced else None,
               "by_bucket_before": {b: {"changes": sum(1 for r in rows if r["bucket_before"] == b),
                                        "improved": sum(1 for r in rows if r["bucket_before"] == b and r["verdict"] == "improved"),
                                        "worsened": sum(1 for r in rows if r["bucket_before"] == b and r["verdict"] == "worsened")}
                                    for b in ("exact", "light", "heavy", "inserted")}}
    return rows, summary


def evaluate_run(run_name: str, films: tuple[str, ...] = ("hf-ii", "hf-iii")) -> dict[str, Any]:
    run_dir = TICKET / run_name
    report: dict[str, Any] = {"run": run_name, "arms": {}}
    for arm_dir in sorted(p for p in run_dir.iterdir() if p.is_dir() and p.name.startswith("c")):
        arm = arm_dir.name
        report["arms"][arm] = {}
        for film in films:
            out = arm_dir / film
            if not (out / "ja.srt").is_file():
                continue
            reference = common.reference_cues(film)
            control = control_cues(film)
            corrected = asr_source.read_srt(out / "ja.srt")
            changes = common.read_json(out / "changes.json")
            before, after = common.unit_cer(reference, control), common.unit_cer(reference, corrected)
            rows, summary = classify_changes(reference, control, changes)
            common.write_json(out / "changes-classified.json", rows)
            report["arms"][arm][film] = {
                "control": {k: before[k] for k in ("CER", "edits", "reference_characters", "units")},
                "corrected": {k: after[k] for k in ("CER", "edits", "reference_characters", "units")},
                "delta_edits": after["edits"] - before["edits"],
                "delta_cer_pp": round(after["CER"] - before["CER"], 4) if after["CER"] is not None else None,
                "control_buckets": before["buckets"], "corrected_buckets": after["buckets"], "changes": summary}
        # 门（§4.0，单元口径）：两部都降且合计编辑量降幅 ≥0.3 pp
        rows = report["arms"][arm]
        if len(rows) == 2:
            total_ref = sum(r["control"]["reference_characters"] for r in rows.values())
            drop = -sum(r["delta_edits"] for r in rows.values())
            both = all(r["delta_edits"] < 0 for r in rows.values())
            pp = round(drop / total_ref * 100, 4)
            rows["gate"] = {"both_drop": both, "combined_drop_pp": pp, "passes": both and pp >= 0.3,
                            "verdict": "candidate" if both and pp >= 0.3 else "effective-but-insufficient" if both else "no-gain"}
    common.write_json(run_dir / "eval.json", report)
    return report


def sample_changes(run_name: str, n: int = 30, seed: int = SEED) -> dict[str, Any]:
    """从全部臂与影片的已分类改动里抽 n 条（改好／改坏各半），写 `sample.json`（含文字，只在 .local）供 Opus 抽看。"""
    run_dir = TICKET / run_name
    pool: dict[str, list[dict[str, Any]]] = {"improved": [], "worsened": []}
    for path in sorted(run_dir.glob("c*/*/changes-classified.json")):
        arm, film = path.parent.parent.name, path.parent.name
        for row in common.read_json(path):
            if row["verdict"] in pool:
                pool[row["verdict"]].append({**row, "arm": arm, "film": film})
    rng = random.Random(seed)
    picked = []
    for verdict, rows in pool.items():
        rng.shuffle(rows)
        picked.extend(rows[:n // 2])
    rng.shuffle(picked)
    reference_by_film = {film: common.reference_cues(film) for film in ("hf-ii", "hf-iii")}
    items = []
    for k, row in enumerate(picked, 1):
        control = control_cues(row["film"])
        units, owner = unit_index(reference_by_film[row["film"]], control)
        j = next(i for i, c in enumerate(control) if c["index"] == row["index"])
        refs, _ = units[owner[j]]
        items.append({"n": k, "arm": row["arm"], "film": row["film"], "id": row["id"], "verdict": row["verdict"],
                      "before": row["before"], "after": row["after"],
                      "reference": "".join(reference_by_film[row["film"]][i]["text"] for i in refs)})
    common.write_json(run_dir / "sample.json", {"items": items, "pool": {k: len(v) for k, v in pool.items()}})
    return {"sampled": len(items), "pool": {k: len(v) for k, v in pool.items()}, "path": str(run_dir / "sample.json")}


__all__ = ["Client", "MAX_EDIT_RATIO", "PROMPTS", "apply_reply", "classify_changes", "correct_film", "evaluate_run",
           "messages", "name_lines", "packs", "plan_download_mib", "recipe", "request_body", "run", "sample_changes"]
