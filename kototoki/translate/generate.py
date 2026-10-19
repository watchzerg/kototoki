"""按批次落盘、可续跑的整片翻译；编排器传入的 `Session` 在整批影片间共用一个 llama-server。

`run_step` 复制自 `experiments/translation_v3/generate.py`（判定逻辑不变，去掉 v4 采样覆盖）。与 v3 的差别：

- v3 每次 `run_generation` 新开 server；这里由 `Session` 持有 server，整批影片顺序共用，`cache_n == 0`
  校验在每个 server session 的首个 completion 做一次。
- v3 按整场景落盘；这里每完成一批就向 `batches.jsonl` 追加一行，续跑从未完成的批次继续，
  末尾不完整的一行视为未写入并截掉；`scene.json` 只在全部批次完成后写出。
- 基础设施失败（OOM、传输、`cache_n` 校验、server 错误、server 启动失败）在同一次调用内停掉 server、
  启动新 session 重做，最多重启 `MAX_RESTARTS` 次；每次重启在 `run.json` 的 `sessions[]` 新增一项。
- 批次终态失败（超出 context、生成触顶、解析失败）按 `degrade.py` 拆批降级，单条仍失败保留日文；
  降级完成的批次照常写入 `batches.jsonl`，回退对该配方 hash 与 seed 是终态，重跑不再尝试。

run 目录由本子系统的 `plan` 决定：`<work_dir>/translate/srt-<sha12>/<配方名>__s<seed>/`（`ja.srt` 的 SHA、配方名、
seed 三级分键；同名配方内容变化时 `run.json` 的 hash 不符即拒绝续跑，删除该目录可重跑），下有 `run.json`、
`batches.jsonl`、`degrade.jsonl`（降级中各节点的结果，续跑用）、`scene.json`、`report.json`、`transport/session-NN/`
（逐请求原始交换）、`infra-failures/`。`TranslatePlan.needs_model` 告诉编排器是否要取 GPU 锁：零条目或 `run.json`
已记完成时不需要。server 的运行日志在 `<output_dir>/.work/translate-sessions/<UTC戳>-<pid>/session-NN/`，被整批影片共用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError

from kototoki import artifacts
from kototoki.artifacts import atomic_write_json, object_hash, read_json, sha256_bytes, utc_now
from kototoki.config import Config
from kototoki.srt import SourceDocument

from . import degrade
from . import recipes as R
from .batching import Batch, Scene, build_batches, cue_positions, scene_from_document, source_key
from kototoki.llama_server import InfraFailure, LlamaClient, ManagedServer, explicit_oom

from .server import TRANSLATE_SPEC

TRANSLATE_DIR = "translate"  # 工作目录内的翻译根目录
RUN_SCHEMA = "kototoki-translate-run-v1"
SCENE_SCHEMA = "kototoki-translate-scene-v1"
BATCHES = "batches.jsonl"
DEGRADE = "degrade.jsonl"
REPORT = "report.json"
SESSIONS_DIR = "translate-sessions"
MAX_RESTARTS = 2
CLIENT_TIMEOUT_SECONDS = 600.0
FATAL_KINDS = ("oom", "cache", "server")
# 基础设施失败：停掉当前 server、开新 session 重做，不形成终态。
INFRA_KINDS = ("oom", "cache", "server", "server_error")
CONTEXT_ERROR = re.compile(r"exceed[s]? the available context|context size|n_ctx|context length", re.IGNORECASE)

log = logging.getLogger(__name__)


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
    run_dir: Path                  # <work_dir>/translate/srt-<sha12>/<配方名>__s<seed>
    identity: dict[str, Any]       # {"ja_srt_sha256", "recipe_hash", "seed"}
    needs_model: bool              # 零条目或全部批次已完成时为 False
    document: SourceDocument

    @property
    def relative(self) -> str:
        """run 目录相对工作目录的 posix 路径（写进 `published.json` 的 `translate_dir`）。"""
        return self.run_dir.relative_to(self.work_dir).as_posix()


def plan(work_dir: Path, document: SourceDocument, config: Config) -> TranslatePlan:
    """只读：决定 run 目录、身份与 `needs_model`，不写文件。run 目录已存在且配方／seed／来源不符时抛 `ValueError`。"""
    seed = config.translate.seed
    run_dir = Path(work_dir) / TRANSLATE_DIR / source_key(document.source_sha256) / f"{R.PRODUCT.name}__s{seed}"
    identity = {"ja_srt_sha256": document.source_sha256, "recipe_hash": R.PRODUCT.recipe_hash, "seed": seed}
    needs_model = bool(document.cues)
    if needs_model and (run_dir / "run.json").is_file():
        run = _check_run(run_dir, seed, _source(document, scene_from_document(document)))
        needs_model = run["completion"].get("state") != "complete"
    return TranslatePlan(Path(work_dir), run_dir, identity, needs_model, document)


# --- session --------------------------------------------------------------------------------

class Session:
    """整批翻译共用的 server 生命周期：首次需要时才启动 server，`restart` 即新 session。

    `on_server_pid(pid)` 在 server 启动后以 pid、停止后以 None 回调，供编排器写进 GPU 锁。
    `server_factory`／`client_factory` 是只供测试的内部接缝。
    """

    def __init__(self, config: Config, *, on_server_pid: Callable[[int | None], None] | None = None,
                 server_factory: Callable[[Path, Callable[[int | None], None]], Any] | None = None,
                 client_factory: Callable[..., Any] = LlamaClient):
        self.config = config
        self.on_server_pid = on_server_pid or (lambda pid: None)
        self.server_factory = server_factory or self._managed_server
        self.client_factory = client_factory
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())  # UTC，与运行日志 `run-<戳>.log` 同一时间基准
        self.runtime_root = artifacts.work_root(config.paths.output_dir) / SESSIONS_DIR / f"{stamp}-{os.getpid()}"
        self.server: Any = None
        self.ordinal = 0
        self.cache_state: dict[str, Any] = {}
        # 某部影片因 server 一直起不来（显存被占、加载失败）用尽重启后，本批其余影片不再等待，直接失败。
        self.unavailable: str | None = None

    def _managed_server(self, runtime_dir: Path, on_pid: Callable[[int | None], None]) -> ManagedServer:
        return ManagedServer(runtime_dir, TRANSLATE_SPEC, engine=self.config.paths.llama_server,
                             model=self.config.models.translate,
                             port=self.config.translate.port,
                             model_cache=artifacts.model_cache_path(self.config.paths.output_dir), on_pid=on_pid)

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    def ensure_started(self) -> Any:
        if self.server is None:
            self.ordinal += 1
            self.cache_state = {"checked": False}
            server = self.server_factory(self.runtime_root / f"session-{self.ordinal:02d}", self.on_server_pid)
            server.__enter__()  # 进程一启动即以 pid 回调；加载失败时自行清理并以 None 回调
            self.server = server
        return self.server

    def stop(self) -> None:
        server, self.server = self.server, None
        if server is not None:
            server.__exit__(None, None, None)  # 进程结束后以 None 回调


# --- 单次请求（v3 run_step） ---------------------------------------------------------------------

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


def run_step(client: Any, prompt: str, grammar: str, seed: int, parse: Callable[[str], Any],
             cache_state: dict[str, Any], record: dict[str, Any]) -> Any:
    """tokenize、预算守卫、completion、校验；同一请求最多两次。"""
    attempts: list[dict[str, Any]] = record.setdefault("attempts", [])
    last: StepFailed | None = None
    for number in range(1, R.MAX_ATTEMPTS + 1):
        started = time.perf_counter()
        attempt: dict[str, Any] = {"attempt": number, "prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
                                   "grammar_sha256": sha256_bytes(grammar.encode("utf-8")), "dispatched": False}
        attempts.append(attempt)
        try:
            try:
                tokens = client.tokenize(prompt)
            except (URLError, ConnectionError, TimeoutError) as exc:
                raise StepFailed(f"tokenize transport: {exc}", "server") from exc
            attempt.update(input_tokens=len(tokens), tokenize_exchange=getattr(client, "last_exchange", None))
            if len(tokens) > R.MAX_INPUT_TOKENS:
                raise StepFailed(f"context_budget: {len(tokens)} input tokens + {R.N_PREDICT} + {R.GUARD_TOKENS} "
                                 f"> {R.CONTEXT_SIZE}; no truncation or auto-shrink", "context")
            request = R.completion_request(tokens, seed, grammar)
            attempt["request_sha256"] = object_hash(request)
            attempt["dispatched"] = True
            completion_start = time.perf_counter()
            try:
                response = client.complete(request)
            except HTTPError as exc:
                body = _http_body(client) + str(exc)
                kind = "oom" if explicit_oom(body) else "context" if CONTEXT_ERROR.search(body) else "server_error"
                # 消息只带状态码、分类与正文长度；正文在 transport 交换目录里。
                raise StepFailed(f"HTTP {exc.code} ({kind}): response body {len(body)} char(s)", kind) from exc
            except (URLError, ConnectionError, TimeoutError) as exc:
                raise StepFailed(f"completion transport: {exc}", "server") from exc
            finally:
                attempt.update(completion_seconds=time.perf_counter() - completion_start,
                               exchange=getattr(client, "last_exchange", None))
            timings = response.get("timings") if isinstance(response.get("timings"), dict) else {}
            content = response.get("content")
            attempt.update(output_tokens=response.get("tokens_predicted"), tokens_evaluated=response.get("tokens_evaluated"),
                           timings=timings, stop_type=response.get("stop_type"),
                           stopped_limit=bool(response.get("stopped_limit") or response.get("stop_type") == "limit"),
                           truncated=bool(response.get("truncated")),
                           content_chars=len(content) if isinstance(content, str) else None)
            if not cache_state.get("checked"):
                reuse = timings.get("cache_n")
                cache_state.update(checked=True, first_cache_n=reuse, verified=type(reuse) is int and reuse == 0,
                                   exchange=attempt.get("exchange"))
                attempt["cache_reset_check"] = dict(cache_state)
                if not cache_state["verified"]:
                    raise StepFailed(f"First completion lacks timings.cache_n == 0 (got {reuse!r})", "cache")
            if response.get("error") is not None:
                text = json.dumps(response["error"], ensure_ascii=False)
                kind = "oom" if explicit_oom(text) else "server_error"
                raise StepFailed(f"server error ({kind}): {type(response['error']).__name__} of {len(text)} char(s)",
                                 kind)
            if response.get("tokens_evaluated") is not None and response["tokens_evaluated"] != len(tokens):
                raise StepFailed("server evaluated a different token count", "server_error")
            if attempt["stopped_limit"] or attempt["truncated"]:
                attempt["whitespace_ratio"] = whitespace_ratio(content)
                raise StepFailed("generation reached the output/context limit", "limit")
            if not isinstance(content, str) or not content.strip():
                raise StepFailed("empty generated text", "parse")
            try:
                result = parse(content)
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


def translate_batch(client: Any, scene: Scene, batch: Batch, seed: int, cache_state: dict[str, Any]) -> dict[str, Any]:
    ids = list(batch.target_ids)
    request: dict[str, Any] = {"stage": "translation", "batch_index": batch.index}
    try:
        result = run_step(client, R.render_translation(batch.to_window(scene)), R.translation_grammar(ids), seed,
                          lambda text: R.parse_translation(text, ids), cache_state, request)
    except StepFailed as exc:
        exc.record = {**batch.record(), "request": request}
        raise
    return {**batch.record(), "translations": result, "request": request}


# --- run 目录 ----------------------------------------------------------------------------------

def _source(document: SourceDocument, scene: Scene) -> dict[str, Any]:
    return {"ja_srt_sha256": document.source_sha256, "scene_id": scene.scene_id, "cue_ids": scene.ids}


def _check_run(root: Path, seed: int, source: dict[str, Any]) -> dict[str, Any]:
    """读已存在的 `run.json`，配方 hash／seed／来源必须与本次相同（同名配方内容变化即在此拒绝）。"""
    path = root / "run.json"
    run = read_json(path)
    if run["recipe_hash"] != R.PRODUCT.recipe_hash or run["seed"] != seed or run["source"] != source:
        raise ValueError(f"{path} differs in recipe/seed/source; the run directory is keyed by them. "
                         f"Delete {root} to translate this ja.srt again with the current recipe")
    return run


def _open_run(root: Path, seed: int, document: SourceDocument, scene: Scene) -> dict[str, Any]:
    path = root / "run.json"
    source = _source(document, scene)
    if path.is_file():
        return _check_run(root, seed, source)
    run = {"schema": RUN_SCHEMA, "recipe": R.PRODUCT.to_json(), "recipe_hash": R.PRODUCT.recipe_hash, "seed": seed,
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
    """批次完成的一行进度；字段取自已有记录（降级批次取原批次请求的末次尝试），取不到的省略。"""
    request = row["degrade"]["nodes"][0]["request"] if "degrade" in row else row["request"]
    attempts = request.get("attempts") or [{}]
    last = attempts[-1]
    timings = last.get("timings") or {}
    parts = [f"{len(row['target_ids'])} cue(s)"]
    if last.get("output_tokens") is not None:
        parts.append(f"{last['output_tokens']} tok")
    if isinstance(timings.get("predicted_per_second"), (int, float)):
        parts.append(f"{timings['predicted_per_second']:.1f} tok/s")
    if timings.get("cache_n") is not None:
        parts.append(f"cache {timings['cache_n']}")
    if "degrade" in row:
        parts.append(f"degraded ({len(row['degrade']['nodes'])} request(s), "
                     f"{len(row['degrade']['fallback'])} fallback)")
    return f"[translate] batch {row['index'] + 1}/{total}: " + ", ".join(parts)


def _first_line(exc: BaseException) -> str:
    return (str(exc).splitlines() or [""])[0][:200]


SESSION_ENGINE_KEYS = ("candidate", "model_path", "engine_sha256", "engine_identity_sha256", "command", "server_pid",
                       "cold_load_seconds", "residency", "model_verification", "free_vram_mib_before_start")


def translate_document(plan: TranslatePlan, session: Session | None) -> TranslateResult:
    """按计划翻译一部影片的 `ja.srt`，返回 cue id → 译文；零条目文档不请求模型。

    已完成的批次（含降级完成的）直接复用；全部完成时不启动 server。`session` 只在 `plan.needs_model` 时使用，
    编排器在不需要模型时可传 None；计划说不需要而批次仍未完成（`run.json` 与 `batches.jsonl` 不一致）时抛
    `TranslateError`，不会在没有 GPU 锁的情况下起 server。批次终态失败按 `degrade` 降级，回退条数进
    `fallback_count`，`report` 即写入 `report.json` 的内容。基础设施失败用尽重启抛 `TranslateError`（证据留在 run 目录）。
    """
    document, root, seed = plan.document, plan.run_dir, plan.identity["seed"]
    scene = scene_from_document(document)
    run = _open_run(root, seed, document, scene)
    if not scene.cues:
        run["completion"] = {"state": "complete", "batches_total": 0, "batches_complete": 0, "cues_total": 0,
                             "restarts_last_call": 0}
        atomic_write_json(root / "run.json", run)
        report = degrade.build_report([], run["completion"])
        atomic_write_json(root / REPORT, report)
        return TranslateResult({}, 0, report)
    batches = build_batches(scene, R.PRODUCT)
    done = _read_batches(root, batches)
    recorded = _read_degrade(root, batches, done)
    if len(done) < len(batches) and (session is None or not plan.needs_model):
        raise TranslateError(f"{root} is recorded as complete but {len(batches) - len(done)} batch(es) are missing "
                             f"from {BATCHES}; delete the run directory to translate again")

    def record(row: dict[str, Any]) -> None:
        _append_line(root / DEGRADE, row)
        recorded.setdefault(row["parent_index"], {})[row["batch_id"]] = row
    restarts = 0
    failure_kinds: list[str] = []
    while len(done) < len(batches):
        entry: dict[str, Any] | None = None
        started = time.perf_counter()
        if session.unavailable is not None:
            raise TranslateError(f"llama-server could not start earlier in this batch: {session.unavailable}")
        try:
            server = session.ensure_started()
            entry = {"index": len(run["sessions"]) + 1, "server_session": str(session.runtime_root.name)
                     + f"/session-{session.ordinal:02d}", "started_at_utc": utc_now(),
                     "engine": {key: server.identity.get(key) for key in SESSION_ENGINE_KEYS},
                     "pending_at_start": len(batches) - len(done), "batches_written": 0,
                     "stop_reason": None, "infra_failure": None}
            run["sessions"].append(entry)
            atomic_write_json(root / "run.json", run)
            log.info("[translate] session %d start (%s): %d of %d batch(es) pending", entry["index"],
                     entry["server_session"], entry["pending_at_start"], len(batches))
            client = session.client_factory(server.url, timeout=CLIENT_TIMEOUT_SECONDS,
                                            trace_dir=root / "transport" / f"session-{entry['index']:02d}")
            number = entry["index"]

            def attempt(node: Batch) -> dict[str, Any]:
                try:
                    return translate_batch(client, scene, node, seed, session.cache_state) | {"session": number}
                except StepFailed as exc:
                    if exc.kind in INFRA_KINDS:
                        raise
                    assert exc.record is not None
                    return exc.record | {"error_kind": exc.kind, "error": str(exc)[:2000], "session": number}

            for batch in batches:
                if batch.index in done:
                    continue
                row = degrade.translate_with_degrade(scene, batch, R.PRODUCT, attempt,
                                                     recorded.setdefault(batch.index, {}), record)
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
            failure_kinds.append(kind)
            if restarts > MAX_RESTARTS:
                log.error("[translate] giving up after %d server restart(s): %s: %s", MAX_RESTARTS, kind,
                          _first_line(exc))
                if set(failure_kinds) == {"server_start"}:
                    session.unavailable = failure["error"]
                raise TranslateError(f"Infrastructure failure persisted after {MAX_RESTARTS} server restarts "
                                     f"({kind}): {exc}") from exc
            log.warning("[translate] server restart %d/%d: %s: %s", restarts, MAX_RESTARTS, kind, _first_line(exc))
        except Exception as exc:
            # 意外异常（非 JSON 响应、写盘失败等）：记录后停掉可能不健康的 server，原样上抛给编排器。
            if entry is not None:
                entry["stop_reason"] = f"session_error: {type(exc).__name__}: {exc}"[:2000]
            # traceback 由编排器的 ctx.fail 记一次，这里不再附 exc_info，避免运行日志里出现两份。
            log.error("[translate] unexpected %s during translation; stopping the server", type(exc).__name__)
            session.stop()
            raise
        finally:
            if entry is not None:
                entry.update(ended_at_utc=utc_now(), wall_seconds=time.perf_counter() - started,
                             cache_reset=dict(session.cache_state))
                log.info("[translate] session %d end: %d batch(es) written in %.1f s", entry["index"],
                         entry["batches_written"], entry["wall_seconds"])
            _finish(root, run, batches, done, restarts)
    completion = _finish(root, run, batches, done, restarts)
    translations = _write_scene(root, scene, batches, done)
    report = degrade.build_report([done[index] for index in range(len(batches))], completion)
    atomic_write_json(root / REPORT, report)
    return TranslateResult(translations, report["counts"]["fallback_cues"], report)
