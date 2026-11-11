"""按批次落盘、可续跑的整片翻译；编排器传入的共享 `kototoki.strata.Session` 在整批影片间（names 建表与翻译）共用一个 Strata 服务（ADR-0019、ADR-0022）。

`run_step` 复制自 `experiments/translation_v3/strata.py`（判定逻辑不变，去掉思考分支）。与研究侧的差别：

- 研究侧只连接执行者启动好的服务；这里由编排器持有的共享 `kototoki.strata.Session` 持有 `StrataServer`：第一次真正需要
  请求模型时才 `strata launch --no-tui --model iq3_s`、核对身份（可能已在 names 阶段启动），整批影片顺序共用，
  编排器退出 session 时 `strata launch --stop` 并核实显存释放。
- 研究侧按整场景落盘；这里每完成一批就向 `batches.jsonl` 追加一行，续跑从未完成的批次继续，
  末尾不完整的一行视为未写入并截掉；`scene.json` 只在全部批次完成后写出。
- 基础设施失败（OOM、传输／连接断开、server 错误、服务起不来）在同一次调用内停掉服务、重新启动新 session 重做，
  最多重启 `MAX_RESTARTS` 次；每次重启在 `run.json` 的 `sessions[]` 新增一项。身份不符（`StrataRefused`）不重试；共享
  session 的启动失败整批累计 `strata.MAX_START_FAILURES` 次后也不再尝试（`unavailable` 只由 `Session` 写，这里只读）。
- 每个 Strata session 首个 completion 的 `cache_n` 只记一次（`run.json` 的 `cache_reset`）；记录状态归本模块，
  按共享 session 与 `session.label` 分开记（`_cache_state`）。
- 两次尝试都失败的批次（生成触顶、解析失败、HTTP 报超出 context）按 `degrade.py` 拆批降级，单条仍失败保留日文；
  研究侧只空出该包的 cue。降级完成的批次照常写入 `batches.jsonl`，回退对该身份是终态，重跑不再尝试。

run 目录由本子系统的 `plan` 决定：`<work_dir>/translate/srt-<sha12>/<配方名>__s<seed>__n<表sha12>/`（`ja.srt` 的 SHA、
配方名、seed、注入行的 SHA 四项分键；同名配方内容变化时 `run.json` 的 hash 不符即拒绝续跑，删除该目录可重跑），下有
`run.json`、`batches.jsonl`、`degrade.jsonl`（降级中各节点的结果，续跑用）、`scene.json`、`report.json`、
`transport/session-NN/`（逐请求原始交换）、`infra-failures/`。`TranslatePlan.needs_model` 告诉编排器是否要取 GPU 锁：
零条目或 `run.json` 已记完成时不需要。Strata session 的证据在 `<工作根>/strata-sessions/<UTC戳>-<pid>/session-NN/`（归中间层）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any
import weakref
from urllib.error import HTTPError, URLError

from kototoki import artifacts
from kototoki.artifacts import atomic_write_json, object_hash, read_json, sha256_bytes, utc_now
from kototoki.config import Config
from kototoki.srt import SourceDocument

from kototoki.local_client import InfraFailure, explicit_oom
from kototoki.strata import Session, StrataRefused

from . import degrade
from . import recipes as R
from .batching import Batch, Scene, build_batches, cue_positions, scene_from_document, source_key

TRANSLATE_DIR = "translate"  # 工作目录内的翻译根目录
RUN_SCHEMA = "kototoki-translate-run-v1"
SCENE_SCHEMA = "kototoki-translate-scene-v1"
BATCHES = "batches.jsonl"
DEGRADE = "degrade.jsonl"
REPORT = "report.json"
MAX_RESTARTS = 2
CLIENT_TIMEOUT_SECONDS = 600.0
FATAL_KINDS = ("oom", "server")
# 基础设施失败：停掉当前服务、开新 session 重做，不形成终态。
INFRA_KINDS = ("oom", "server", "server_error")
CONTEXT_ERROR = re.compile(r"exceed[s]? the available context|context size|n_ctx|context length", re.IGNORECASE)

log = logging.getLogger(__name__)

# 共享 session → (session 名 → 首个 completion 的 cache 记录)。一次 Strata 启动即一个 `session.label`，记录随之重新开始；
# 同一 session 上的后续影片沿用同一份记录（首个请求已记过）。按对象分开，同一秒内构造的两个 `Session` 互不串。
_CACHE_STATES: "weakref.WeakKeyDictionary[Session, dict[str, dict[str, Any]]]" = weakref.WeakKeyDictionary()


def _cache_state(session: Session) -> dict[str, Any]:
    return _CACHE_STATES.setdefault(session, {}).setdefault(session.label, {"checked": False})


class StepFailed(RuntimeError):
    def __init__(self, message: str, kind: str):
        super().__init__(message)
        self.kind = kind
        self.record: dict[str, Any] | None = None


class TranslateError(RuntimeError):
    """该影片的翻译失败（编排器记为文件级失败）；证据在 run 目录。"""


@dataclass(frozen=True)
class TranslateResult:
    translations: dict[str, str]
    fallback_count: int
    report: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TranslatePlan:
    """一部影片的翻译计划：run 目录、期望身份（进编排器的 `published.json`）、是否需要模型。"""
    work_dir: Path
    run_dir: Path                  # <work_dir>/translate/srt-<sha12>/<配方名>__s<seed>__n<表sha12>
    identity: dict[str, Any]       # {"ja_srt_sha256", "recipe_hash", "seed", "names_sha256"}
    needs_model: bool              # 零条目或全部批次已完成时为 False
    document: SourceDocument
    names: list[dict[str, str]]    # 注入行（`recipes.name_rows`）

    @property
    def relative(self) -> str:
        """run 目录相对工作目录的 posix 路径（写进 `published.json` 的 `translate_dir`）。"""
        return self.run_dir.relative_to(self.work_dir).as_posix()


def plan(work_dir: Path, document: SourceDocument, name_table: dict[str, Any], config: Config) -> TranslatePlan:
    """只读：决定 run 目录、身份与 `needs_model`，不写文件。`name_table` 是该影片 `name-table.json` 的内容，
    只取其注入行（`recipes.name_rows`），注入行的 SHA 进身份与 run 目录键：表一变即另起 run、重译。
    run 目录已存在且配方／seed／来源／注入行不符时抛 `ValueError`。"""
    seed = config.translate.seed
    rows = R.name_rows(name_table)
    names = R.names_sha256(rows)
    run_dir = (Path(work_dir) / TRANSLATE_DIR / source_key(document.source_sha256)
               / f"{R.RECIPE_NAME}__s{seed}__n{names[:12]}")
    identity = {"ja_srt_sha256": document.source_sha256, "recipe_hash": R.RECIPE_HASH, "seed": seed,
                "names_sha256": names}
    needs_model = bool(document.cues)
    if needs_model and (run_dir / "run.json").is_file():
        run = _check_run(run_dir, seed, names, _source(document, scene_from_document(document)))
        needs_model = run["completion"].get("state") != "complete"
    return TranslatePlan(Path(work_dir), run_dir, identity, needs_model, document, rows)


# --- 单次请求（研究侧 strata.run_step） ----------------------------------------------------------

def whitespace_ratio(text: Any) -> float | None:
    if not isinstance(text, str) or not text:
        return None
    return sum(ch.isspace() for ch in text) / len(text)


def _http_body(client: Any) -> str:
    exchange = getattr(client, "last_exchange", None)
    if isinstance(exchange, str):
        raw = Path(exchange) / "response.raw"
        if raw.is_file():
            return raw.read_text(encoding="utf-8", errors="replace")
    return ""


def run_step(client: Any, messages: list[dict[str, str]], seed: int, ids: list[str], cache_state: dict[str, Any],
             record: dict[str, Any]) -> dict[str, str]:
    """一个包的 chat completion 与校验：不用 grammar、不查预算端点；最多两次（seed、seed＋1）。"""
    attempts: list[dict[str, Any]] = record.setdefault("attempts", [])
    last: StepFailed | None = None
    for number in range(1, R.MAX_ATTEMPTS + 1):
        started = time.perf_counter()
        used_seed = seed + (number - 1) * R.SEED_STEP
        body = R.request_body(messages, used_seed)
        attempt: dict[str, Any] = {"attempt": number, "seed": used_seed,
                                   "prompt_sha256": sha256_bytes(json.dumps(messages, ensure_ascii=False).encode()),
                                   "request_sha256": object_hash(body), "dispatched": True}
        attempts.append(attempt)
        try:
            completion_start = time.perf_counter()
            try:
                response = client.chat_completion(body)
            except HTTPError as exc:
                text = _http_body(client) + str(exc)
                kind = "oom" if explicit_oom(text) else "context" if CONTEXT_ERROR.search(text) else "server_error"
                # 消息只带状态码、分类与正文长度；正文在 transport 交换目录里。
                raise StepFailed(f"HTTP {exc.code} ({kind}): response body {len(text)} char(s)", kind) from exc
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
            prompt_tokens = usage.get("prompt_tokens")
            attempt.update(input_tokens=prompt_tokens, output_tokens=usage.get("completion_tokens"),
                           tokens_evaluated=prompt_tokens, timings=timings, stop_type=choice.get("finish_reason"),
                           stopped_limit=choice.get("finish_reason") == "length", truncated=False,
                           content_chars=len(content) if isinstance(content, str) else None,
                           reasoning_chars=len(reasoning) if isinstance(reasoning, str) else 0,
                           over_q1_budget=type(prompt_tokens) is int and prompt_tokens > R.Q1_INPUT_BUDGET)
            if not cache_state.get("checked"):  # 只记录：服务自带前缀缓存，研究侧同样不据此判失败
                reuse = timings.get("cache_n", (usage.get("prompt_tokens_details") or {}).get("cached_tokens"))
                cache_state.update(checked=True, first_cache_n=reuse, verified=type(reuse) is int and reuse == 0,
                                   recorded_only=True, exchange=attempt.get("exchange"))
                attempt["cache_reset_check"] = dict(cache_state)
            if response.get("error") is not None:
                text = json.dumps(response["error"], ensure_ascii=False)
                kind = "oom" if explicit_oom(text) else "server_error"
                raise StepFailed(f"server error ({kind}): {type(response['error']).__name__} of {len(text)} char(s)",
                                 kind)
            if attempt["stopped_limit"]:
                attempt["whitespace_ratio"] = whitespace_ratio(content)
                raise StepFailed("generation reached the output/context limit (or non-finite logits)", "limit")
            if not isinstance(content, str) or not content.strip():
                raise StepFailed("empty generated text", "parse")
            try:
                result = R.parse_translation(content, ids)
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


def _log_failed_attempts(batch_id: str, request: dict[str, Any], base: Path) -> None:
    """每次被拒绝（HTTP 错误、超出 context、server 报错）或格式不合格（非 JSON、ID 不符、空译文、触顶）的尝试记一行
    WARNING：分类、seed、错误首行、停止原因、输出 token、回复字符数与交换目录（相对工作根 `base`）。回复正文不进日志，
    在交换目录的 `response.raw` 里。"""
    attempts = request.get("attempts") or []
    for attempt in attempts:
        if attempt.get("status") != "failed":
            continue
        parts = [f"seed {attempt.get('seed')}"]
        if attempt.get("stop_type") is not None:
            parts.append(f"finish {attempt['stop_type']}")
        if attempt.get("output_tokens") is not None:
            parts.append(f"{attempt['output_tokens']} tok")
        if attempt.get("content_chars") is not None:
            parts.append(f"reply {attempt['content_chars']} char(s)")
        if attempt.get("exchange"):
            parts.append(f"exchange {Path(attempt['exchange']).relative_to(base).as_posix()}")
        error = (str(attempt.get("error") or "").splitlines() or [""])[0][:200]
        log.warning("[translate] batch %s attempt %d/%d failed (%s): %s; %s", batch_id, attempt.get("attempt"),
                    R.MAX_ATTEMPTS, attempt.get("error_kind"), error, ", ".join(parts))


def translate_batch(client: Any, scene: Scene, batch: Batch, rows: list[dict[str, str]], seed: int,
                    cache_state: dict[str, Any], base: Path) -> dict[str, Any]:
    ids = list(batch.target_ids)
    window = batch.to_window(scene)
    request: dict[str, Any] = {"stage": "translation", "batch_index": batch.index,
                               "names_injected": len(R.names_for_window(rows, window))}
    try:
        result = run_step(client, R.messages(window, rows), seed, ids, cache_state, request)
    except StepFailed as exc:
        exc.record = {**batch.record(), "request": request}
        raise
    finally:
        _log_failed_attempts(batch.batch_id, request, base)
    return {**batch.record(), "translations": result, "request": request}


# --- run 目录 ----------------------------------------------------------------------------------

def _source(document: SourceDocument, scene: Scene) -> dict[str, Any]:
    return {"ja_srt_sha256": document.source_sha256, "scene_id": scene.scene_id, "cue_ids": scene.ids}


def _check_run(root: Path, seed: int, names: str, source: dict[str, Any]) -> dict[str, Any]:
    """读已存在的 `run.json`，配方 hash／seed／注入行／来源必须与本次相同（同名配方内容变化即在此拒绝）。"""
    path = root / "run.json"
    run = read_json(path)
    if (run.get("recipe_hash") != R.RECIPE_HASH or run.get("seed") != seed
            or (run.get("names") or {}).get("sha256") != names or run.get("source") != source):
        raise ValueError(f"{path} differs in recipe/seed/names/source; the run directory is keyed by them. "
                         f"Delete {root} to translate this ja.srt again with the current recipe")
    return run


def _open_run(root: Path, seed: int, names: list[dict[str, str]], document: SourceDocument,
              scene: Scene) -> dict[str, Any]:
    path = root / "run.json"
    source = _source(document, scene)
    sha = R.names_sha256(names)
    if path.is_file():
        return _check_run(root, seed, sha, source)
    run = {"schema": RUN_SCHEMA, "recipe": {"name": R.RECIPE_NAME, **R.RECIPE}, "recipe_hash": R.RECIPE_HASH,
           "seed": seed, "names": {"sha256": sha, "rows": len(names)},
           "source": source, "created_at_utc": utc_now(), "sessions": [], "server_start_failures": [],
           "resumed": False, "completion": {"state": "not_started"}, "wall_clock_seconds": None}
    atomic_write_json(path, run)
    return run


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读出追加写的 JSONL；末尾不完整的一行（中断时写了一半）截掉，其余行损坏即报错。"""
    if not path.is_file():
        return []
    data = path.read_bytes()
    complete = data[:data.rfind(b"\n") + 1]
    lines = complete.splitlines()
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines, 1):
        try:
            rows.append(json.loads(line))
        except ValueError:
            if number < len(lines):
                raise ValueError(f"{path}: corrupt line {number}") from None
            complete = complete[:len(complete) - len(line) - 1]
    if len(complete) != len(data):
        with path.open("r+b") as stream:
            stream.truncate(len(complete))
    return rows


def _read_batches(root: Path, batches: list[Batch]) -> dict[int, dict[str, Any]]:
    """读出已完成的批次；行必须与批次计划一致。"""
    path = root / BATCHES
    done: dict[int, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        index = row.get("index")
        plan = batches[index] if type(index) is int and 0 <= index < len(batches) else None
        if plan is None or row.get("batch_id") != plan.batch_id or row.get("target_ids") != list(plan.target_ids) \
                or set(row.get("translations") or {}) != set(plan.target_ids) or index in done:
            raise ValueError(f"{path}: batch row {index!r} does not match the batch plan")
        done[index] = row
    return done


def _read_degrade(root: Path, batches: list[Batch], done: dict[int, dict[str, Any]]
                  ) -> dict[int, dict[str, dict[str, Any]]]:
    """读出未完成批次的降级节点（批次序号 → batch_id → 行）；已完成批次的节点只是证据，不再使用。"""
    path = root / DEGRADE
    recorded: dict[int, dict[str, dict[str, Any]]] = {}
    for row in _read_jsonl(path):
        index = row.get("parent_index")
        batch_id = str(row.get("batch_id"))
        if type(index) is not int or not 0 <= index < len(batches) or not (
                batch_id == batches[index].batch_id or batch_id.startswith(batches[index].batch_id + ".")):
            raise ValueError(f"{path}: degrade row {row.get('batch_id')!r} does not match the batch plan")
        if index in done:
            continue
        nodes = recorded.setdefault(index, {})
        if row["batch_id"] in nodes:
            raise ValueError(f"{path}: duplicate degrade row {row['batch_id']!r}")
        nodes[row["batch_id"]] = row
    return recorded


def _append_line(path: Path, row: dict[str, Any]) -> None:
    with path.open("ab") as stream:
        stream.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())


def _finish(root: Path, run: dict[str, Any], batches: list[Batch], done: dict[int, dict[str, Any]],
            restarts: int) -> dict[str, Any]:
    state = "complete" if len(done) == len(batches) else "partial"
    working = [s for s in run["sessions"] if s.get("batches_written") or s.get("infra_failure")]
    run["resumed"] = len(working) > 1
    run["completion"] = {"state": state, "batches_total": len(batches), "batches_complete": len(done),
                         "cues_total": sum(len(b.target_ids) for b in batches), "restarts_last_call": restarts}
    run["wall_clock_seconds"] = sum(s.get("wall_seconds") or 0 for s in run["sessions"])
    if state == "complete":
        run["ended_at_utc"] = run.get("ended_at_utc") or utc_now()
    atomic_write_json(root / "run.json", run)
    return run["completion"]


def _write_scene(root: Path, scene: Scene, batches: list[Batch], done: dict[int, dict[str, Any]]) -> dict[str, str]:
    translations: dict[str, str] = {}
    for index in range(len(batches)):
        translations.update(done[index]["translations"])
    # 降级批次的节点含原批次请求，因此按节点计；未降级批次只有一个请求。
    requests = [node["request"] for row in done.values()
                for node in (row["degrade"]["nodes"] if "degrade" in row else [row])]
    attempts = [a for request in requests for a in request.get("attempts", [])]
    degraded = [done[index] for index in range(len(batches)) if "degrade" in done[index]]
    atomic_write_json(root / "scene.json", {
        "schema": SCENE_SCHEMA, "scene_id": scene.scene_id, "status": "complete", "cue_ids": scene.ids,
        "positions": cue_positions(batches), "batches": [b.record() for b in batches], "translations": translations,
        "degradation": [{"batch_id": row["batch_id"], **row["degrade"]} for row in degraded],
        "fallback_ids": [item["id"] for row in degraded for item in row["degrade"]["fallback"]],
        "totals": {"requests": len(requests), "attempts": len(attempts),
                   "input_tokens": sum(a.get("input_tokens") or 0 for a in attempts),
                   "output_tokens": sum(a.get("output_tokens") or 0 for a in attempts),
                   "limit_failures": sum(bool(a.get("stopped_limit")) for a in attempts)}})
    return translations


def _batch_line(row: dict[str, Any], total: int) -> str:
    """批次完成的一行进度；字段取自已有记录，取不到的省略；降级批次只有 cue 数、请求数与回退数。"""
    last = (row["request"].get("attempts") or [{}])[-1] if "degrade" not in row else {}
    timings = last.get("timings") or {}
    parts = [f"{len(row['target_ids'])} cue(s)"]
    if "degrade" not in row:  # 降级批次的 tok、tok/s、cache 属于失败的原始请求，不报
        if last.get("output_tokens") is not None:
            parts.append(f"{last['output_tokens']} tok")
        if isinstance(timings.get("predicted_per_second"), (int, float)):
            parts.append(f"{timings['predicted_per_second']:.1f} tok/s")
        if timings.get("cache_n") is not None:
            parts.append(f"cache {timings['cache_n']}")
    else:
        parts.append(f"degraded ({len(row['degrade']['nodes'])} request(s), "
                     f"{len(row['degrade']['fallback'])} fallback)")
    return f"[translate] batch {row['index'] + 1}/{total}: " + ", ".join(parts)


def _first_line(exc: BaseException) -> str:
    return (str(exc).splitlines() or [""])[0][:200]


SESSION_ENGINE_KEYS = ("candidate", "strata", "cold_load_seconds", "free_vram_mib_before_start",
                       "available_ram_gib_before_start")


def translate_document(plan: TranslatePlan, session: Session | None, *, relative: str) -> TranslateResult:
    """按计划翻译一部影片的 `ja.srt`，返回 cue id → 译文；零条目文档不请求模型。`relative` 是输入目录内的相对路径，
    只进 session start 日志行，让多集批次里的批次与告警能归到某一集。

    已完成的批次（含降级完成的）直接复用；全部完成时不启动 Strata。`session` 只在 `plan.needs_model` 时使用，
    编排器在不需要模型时可传 None；计划说不需要而批次仍未完成（`run.json` 与 `batches.jsonl` 不一致）时抛
    `TranslateError`，不会在没有 GPU 锁的情况下启动 Strata。批次终态失败按 `degrade` 降级，回退条数进
    `fallback_count`，`report` 即写入 `report.json` 的内容。基础设施失败用尽重启抛 `TranslateError`（证据留在 run 目录）。
    """
    document, root, seed = plan.document, plan.run_dir, plan.identity["seed"]
    scene = scene_from_document(document)
    run = _open_run(root, seed, plan.names, document, scene)
    if not scene.cues:
        run["completion"] = {"state": "complete", "batches_total": 0, "batches_complete": 0, "cues_total": 0,
                             "restarts_last_call": 0}
        atomic_write_json(root / "run.json", run)
        report = degrade.build_report([], run["completion"])
        atomic_write_json(root / REPORT, report)
        return TranslateResult({}, 0, report)
    batches = build_batches(scene)
    done = _read_batches(root, batches)
    recorded = _read_degrade(root, batches, done)
    if len(done) < len(batches) and (session is None or not plan.needs_model):
        raise TranslateError(f"{root} is recorded as complete but {len(batches) - len(done)} batch(es) are missing "
                             f"from {BATCHES}; delete the run directory to translate again")

    def record(row: dict[str, Any]) -> None:
        _append_line(root / DEGRADE, row)
        recorded.setdefault(row["parent_index"], {})[row["batch_id"]] = row
    restarts = 0
    while len(done) < len(batches):
        entry: dict[str, Any] | None = None
        current: Batch | None = None  # 正在翻译的批次（意外异常行带它的 ID）
        started = time.perf_counter()
        if session.unavailable is not None:
            # 原因由 `Session` 写：启动额度耗尽（"failed to start N times … (start budget exhausted)"）或被拒（身份不符等）。
            raise TranslateError(f"Strata is unavailable for the rest of this batch: {session.unavailable}")
        try:
            server = session.ensure_started()
            cache_state = _cache_state(session)
            entry = {"index": len(run["sessions"]) + 1, "server_session": session.label, "started_at_utc": utc_now(),
                     "engine": {key: server.identity.get(key) for key in SESSION_ENGINE_KEYS},
                     "pending_at_start": len(batches) - len(done), "batches_written": 0,
                     "stop_reason": None, "infra_failure": None}
            run["sessions"].append(entry)
            atomic_write_json(root / "run.json", run)
            log.info("[translate] session %d start %s (%s): %d of %d batch(es) pending", entry["index"], relative,
                     entry["server_session"], entry["pending_at_start"], len(batches))
            client = session.client(root / "transport" / f"session-{entry['index']:02d}",
                                    timeout=CLIENT_TIMEOUT_SECONDS)
            number = entry["index"]

            def attempt(node: Batch) -> dict[str, Any]:
                try:
                    return (translate_batch(client, scene, node, plan.names, seed, cache_state, plan.work_dir.parent)
                            | {"session": number})
                except StepFailed as exc:
                    if exc.kind in INFRA_KINDS:
                        raise
                    assert exc.record is not None
                    return exc.record | {"error_kind": exc.kind, "error": str(exc)[:2000], "session": number}

            for batch in batches:
                if batch.index in done:
                    continue
                current = batch
                row = degrade.translate_with_degrade(scene, batch, attempt, recorded.setdefault(batch.index, {}),
                                                     record)
                row = row | {"session": number}
                _append_line(root / BATCHES, row)
                done[batch.index] = row
                log.info("%s", _batch_line(row, len(batches)))
                entry["batches_written"] += 1
                entry["wall_seconds"] = time.perf_counter() - started
                atomic_write_json(root / "run.json", run)  # 进程被强杀时 sessions[] 仍反映已写批次
        except (StepFailed, InfraFailure) as exc:
            kind = exc.kind if isinstance(exc, StepFailed) else "server_start"
            failure = {"kind": kind, "error": str(exc)[:2000], "at_utc": utc_now()}
            if entry is None:
                run["server_start_failures"].append(failure)
            else:
                if isinstance(exc, StepFailed) and exc.record is not None:
                    evidence = root / "infra-failures" / f"{exc.record['batch_id']}--session-{entry['index']:02d}.json"
                    atomic_write_json(evidence, exc.record)
                    failure["evidence"] = evidence.relative_to(root).as_posix()
                entry.update(stop_reason=kind, infra_failure=failure)
            session.stop()
            restarts += 1
            if restarts > MAX_RESTARTS:
                log.error("[translate] giving up after %d Strata restart(s): %s: %s", MAX_RESTARTS, kind,
                          _first_line(exc))
                raise TranslateError(f"Infrastructure failure persisted after {MAX_RESTARTS} Strata restarts "
                                     f"({kind}): {exc}") from exc
            log.warning("[translate] Strata restart %d/%d: %s: %s", restarts, MAX_RESTARTS, kind, _first_line(exc))
        except StrataRefused as exc:
            # 身份不符或已有别的 launch 在服务：重启无济于事；`Session` 已置 unavailable，本批其余需要模型的影片也不再尝试。
            session.stop()
            log.error("[translate] Strata refused: %s", _first_line(exc))
            raise TranslateError(f"Strata refused: {exc}") from exc
        except Exception as exc:
            # 意外异常（非 JSON 响应、写盘失败等）：记录后停掉可能不健康的 server，原样上抛给编排器。
            if entry is not None:
                entry["stop_reason"] = f"session_error: {type(exc).__name__}: {exc}"[:2000]
            # traceback 由编排器的 ctx.fail 记一次，这里不再附 exc_info，避免运行日志里出现两份。
            log.error("[translate] unexpected %s during translation%s; stopping Strata", type(exc).__name__,
                      f" (batch {current.batch_id})" if current is not None else "")
            session.stop()
            raise
        finally:
            if entry is not None:
                entry.update(ended_at_utc=utc_now(), wall_seconds=time.perf_counter() - started,
                             cache_reset=dict(_cache_state(session)))
                log.info("[translate] session %d end: %d batch(es) written in %.1fs", entry["index"],
                         entry["batches_written"], entry["wall_seconds"])
            _finish(root, run, batches, done, restarts)
    completion = _finish(root, run, batches, done, restarts)
    translations = _write_scene(root, scene, batches, done)
    report = degrade.build_report([done[index] for index in range(len(batches))], completion)
    atomic_write_json(root / REPORT, report)
    return TranslateResult(translations, report["counts"]["fallback_cues"], report)
