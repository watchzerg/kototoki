"""Smoke #4：官方 stock llama-server（b11583 win-cuda-13.4）替换 compat 构建（b11429 + router-bias 补丁）的环境验证。

由 `run_all.py` 在独立子进程中启动（已持有 `.local/gpu.lock`，本脚本不再取 v3 的 GpuLock）。
依次用 v3 的 `ManagedServer` 启动 compat 与 stock 两个会话（同一份 `server_command` 命令行、同一模型
APEX-I-Compact），每个会话发出完全相同的请求序列：

1. `/tokenize` 固定探针串与 b10-joint 第 0、1 批 prompt；
2. `run_step` 跑第 0 批（新 cache_state，检验假设 A：首个 completion 的 timings.cache_n == 0）；
3. `run_step` 跑第 1 批（同会话第二个 cache_prompt 请求，检验 tokens_evaluated == len(tokens)）；
4. 固定种子短生成（n_predict 48、cache_prompt false、return_tokens），跨引擎比较输出 token；
5. 受限请求（n_predict 8）：原始 `/completion` 看 stop_type／stopped_limit／truncated，再经 `run_step` 看是否判为 limit。

结果只记录哈希、计数、自定义探针串的 token id、耗时与响应元数据字段，不记录字幕、prompt 或译文。
`-lv 4` 的运行日志在会话结束后脱敏：加载段（到 "listening on" 行）原样保留，之后只留纯 ASCII 且不含引号的行；
stock 的加载段另存为 `<out>/stock-load.log`，供以后做 residency_evidence 回归 fixture。
"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import smokelib

sys.path.insert(0, str(smokelib.REPO))

from experiments.translation_demo.client import LlamaClient  # noqa: E402
import experiments.translation_demo_runtime as runtime_mod  # noqa: E402
from experiments.translation_v3 import recipes as R  # noqa: E402
from experiments.translation_v3.batching import build_batches  # noqa: E402
from experiments.translation_v3.common import ENGINE, ENGINE_IDENTITY, object_hash, sha256_bytes  # noqa: E402
from experiments.translation_v3.data import load_screening  # noqa: E402
from experiments.translation_v3.generate import StepFailed, run_step  # noqa: E402
from experiments.translation_v3.server import LAYERS, ManagedServer, port_free  # noqa: E402

NAME = "llama_stock"
STOCK_ENGINE = smokelib.REPO / ".local/tools/llama.cpp/b11583-cuda13.4/llama-server.exe"
STOCK_IDENTITY = STOCK_ENGINE.with_name("identity.json")
GPU_LOCK = smokelib.REPO / ".local/gpu.lock"
PORT = 8080
SEED = 1
RECIPE = "b10-joint"
SCENE_INDEX = 0  # screening 源顺序第一个场景
GEN_N_PREDICT = 48
LIMIT_N_PREDICT = 8
CLIENT_TIMEOUT = 600.0

# 自定义固定探针串（不是字幕）：日文、中文、模型特殊标记、混合标点数字。
PROBES = {
    "ja": "今日はいい天気ですね。明日も晴れるといいな。",
    "zh": "今天天气很好，希望明天也是晴天。",
    "markers": R.ASSISTANT_MARKER + R.STOP[0],
    "mixed": "ID 0001: 「待って！」——行くぞ、3、2、1。",
}

LISTEN = re.compile(r"listening on http|server is listening")
CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯＀-￯]")
WARN_WORDS = re.compile(r"unknown|invalid|unrecognized|deprecated|obsolete|no longer|not supported|ignored|removed",
                        re.IGNORECASE)
UNKNOWN_ARG = re.compile(r"(unknown|invalid|unrecognized) (argument|option)", re.IGNORECASE)
# 本 smoke 必须确认仍被接受的三个参数。
HARD_FLAGS = {"--fit": re.compile(r"--fit\b|\bfit[ _-]?(off|params)\b", re.IGNORECASE),
              "--cache-ram": re.compile(r"--cache-ram\b|\bcache[ _-]ram\b", re.IGNORECASE),
              "-lv": re.compile(r"(?<![\w-])-lv\b|--log-verbosity\b|--verbosity\b", re.IGNORECASE)}
RESIDENCY_LINE = re.compile(r"offload|model buffer size", re.IGNORECASE)
RESPONSE_FIELDS = ("content", "tokens", "stop", "stop_type", "stopped_limit", "stopped_eos", "stopped_word",
                   "stopping_word", "truncated", "tokens_predicted", "tokens_evaluated", "tokens_cached", "timings",
                   "generation_settings", "error")
TIMING_FIELDS = ("cache_n", "prompt_n", "prompt_ms", "predicted_n", "predicted_ms")
ATTEMPT_KEYS = ("attempt", "prompt_sha256", "grammar_sha256", "request_sha256", "dispatched", "input_tokens",
                "output_tokens", "tokens_evaluated", "timings", "stop_type", "stopped_limit", "truncated",
                "content_chars", "cache_reset_check", "status", "error_kind", "whitespace_ratio",
                "completion_seconds", "elapsed_seconds")


# --- GPU -------------------------------------------------------------------------------

def nvidia_smi(query: str) -> list[str] | None:
    try:
        result = subprocess.run(["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                                capture_output=True, text=True, timeout=10,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return [field.strip() for field in result.stdout.splitlines()[0].split(",")]


def memory_used() -> int | None:
    fields = nvidia_smi("memory.used")
    return int(fields[0]) if fields and fields[0].isdigit() else None


def idle_baseline(samples: int = 5) -> dict[str, Any]:
    readings = []
    for _ in range(samples):
        if (value := memory_used()) is not None:
            readings.append(value)
        time.sleep(1.0)
    return {"samples_mib": readings, "min_mib": min(readings, default=None), "max_mib": max(readings, default=None)}


class GpuPeak:
    """在一段请求期间每 0.5 s 采 nvidia-smi memory.used，记录峰值（与 ManagedServer 的 2 s 会话采样互补）。"""

    def __init__(self) -> None:
        self.samples: list[int] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while True:
            if (value := memory_used()) is not None:
                self.samples.append(value)
            if self._stop.wait(0.5):
                return

    def __enter__(self) -> "GpuPeak":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        self._thread.join(timeout=15)

    def record(self) -> dict[str, Any]:
        return {"peak_mib": max(self.samples, default=None), "samples": len(self.samples)}


# --- 响应与 run_step 记录（只留元数据） ------------------------------------------------------

def response_meta(response: dict[str, Any], prompt_tokens: int) -> dict[str, Any]:
    timings = response.get("timings") if isinstance(response.get("timings"), dict) else {}
    content = response.get("content")
    evaluated = response.get("tokens_evaluated")
    return {
        "top_level_keys": sorted(response),
        "fields_present": {key: key in response for key in RESPONSE_FIELDS},
        "timing_fields_present": {key: key in timings for key in TIMING_FIELDS},
        "stop_type": response.get("stop_type"), "stopped_limit": response.get("stopped_limit"),
        "stopped_eos": response.get("stopped_eos"), "stopped_word": response.get("stopped_word"),
        "truncated": response.get("truncated"), "tokens_predicted": response.get("tokens_predicted"),
        "tokens_evaluated": evaluated, "tokens_cached": response.get("tokens_cached"),
        "prompt_tokens": prompt_tokens, "tokens_evaluated_equals_prompt": evaluated == prompt_tokens,
        "timings": {key: timings.get(key) for key in TIMING_FIELDS},
        # 与 generate.run_step 完全相同的推导式
        "run_step_stopped_limit": bool(response.get("stopped_limit") or response.get("stop_type") == "limit"),
        "run_step_truncated": bool(response.get("truncated")),
        "has_error": response.get("error") is not None,
        "content_chars": len(content) if isinstance(content, str) else None,
        "content_sha256": sha256_bytes(content.encode("utf-8")) if isinstance(content, str) else None,
    }


def safe_attempts(record: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for attempt in record.get("attempts", []):
        row = {key: attempt.get(key) for key in ATTEMPT_KEYS if key in attempt}
        error = attempt.get("error")
        if isinstance(error, str):
            # parse 失败的消息可能带出模型输出，只留哈希；其余是固定文案或服务端错误信息
            row["error"] = ("sha256:" + sha256_bytes(error.encode("utf-8")) if attempt.get("error_kind") == "parse"
                            else error[:300])
        rows.append(row)
    return rows


def step(client: LlamaClient, prompt: str, grammar: str, ids: list[str], cache_state: dict[str, Any],
         overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {"stage": "translation"}
    evidence: dict[str, Any] = {"accepted": False}
    started = time.perf_counter()
    with GpuPeak() as peak:
        try:
            result = run_step(client, prompt, grammar, SEED, lambda text: R.parse_translation(text, ids),
                              cache_state, record, overrides)
            evidence.update(accepted=True, result_ids=len(result), result_sha256=object_hash(result))
        except StepFailed as exc:
            evidence.update(error_kind=exc.kind, error=(str(exc)[:300] if exc.kind != "parse" else "parse failure"))
    evidence.update(seconds=round(time.perf_counter() - started, 3), vram=peak.record(),
                    attempts=safe_attempts(record), cache_state=dict(cache_state))
    return evidence


# --- 日志：告警扫描、脱敏、加载段 fixture ----------------------------------------------------

def split_loader(lines: list[str]) -> tuple[list[str], list[str], bool]:
    for index, line in enumerate(lines):
        if LISTEN.search(line):
            return lines[:index + 1], lines[index + 1:], True
    return lines, [], False


def scan_flag_warnings(lines: list[str]) -> dict[str, Any]:
    hard, other, unknown = [], [], []
    for line in lines:
        if UNKNOWN_ARG.search(line):
            unknown.append(line[:300])
        if not WARN_WORDS.search(line):
            continue
        flags = [flag for flag, pattern in HARD_FLAGS.items() if pattern.search(line)]
        (hard if flags else other).append({"line": line[:300], "flags": flags} if flags else line[:300])
    return {"hard_flag_warnings": hard, "unknown_argument_lines": unknown, "other_warning_lines": other[:40]}


def process_logs(runtime: Path) -> dict[str, Any]:
    """会话结束后扫描并脱敏三个日志；返回统计、告警与加载段文本。"""
    report: dict[str, Any] = {"files": {}}
    loaders: dict[str, str] = {}
    for name in ("server.log", "stderr.log", "stdout.log"):
        path = runtime / name
        if not path.is_file():
            continue
        lines = path.read_bytes().decode("utf-8", errors="replace").splitlines()
        loader, post, found = split_loader(lines)
        kept = [line for line in post if line.isascii() and '"' not in line and len(line) <= 400]
        report["files"][name] = {
            "lines": len(lines), "loader_lines": len(loader), "listen_marker_found": found,
            "post_listen_lines": len(post), "post_listen_dropped": len(post) - len(kept),
            "post_listen_cjk_lines": sum(bool(CJK.search(line)) for line in post),
            "post_listen_body_like_lines": sum(bool(re.search(r'"(content|prompt)"\s*:', line)) for line in post),
            "warnings": scan_flag_warnings(loader if found else lines)}
        loaders[name] = "\n".join(loader) + "\n"
        path.write_text("\n".join(loader + kept) + "\n", encoding="utf-8")
    files = report["files"].values()
    report["lv4_logs_text_after_listen"] = any(f["post_listen_cjk_lines"] or f["post_listen_body_like_lines"]
                                               for f in files)
    report["hard_flag_warnings"] = [w for f in files for w in f["warnings"]["hard_flag_warnings"]]
    report["unknown_argument_lines"] = [w for f in files for w in f["warnings"]["unknown_argument_lines"]]
    report["other_warning_lines"] = sorted({w for f in files for w in f["warnings"]["other_warning_lines"]})
    joined = "".join(loaders.values())
    report["positive_flag_evidence"] = {
        "verbosity_4": [l[:200] for l in joined.splitlines() if re.search(r"verbosity\s*=\s*4", l)][:2],
        "cache_ram_8192": [l[:200] for l in joined.splitlines() if re.search(r"prompt cache.*8192 MiB", l)][:2],
        "fit_lines": [l[:200] for l in joined.splitlines() if re.search(r"params_fit|\bfit(ting)?\b", l, re.I)][:10]}
    report["residency_lines"] = [l[:200] for l in joined.splitlines() if RESIDENCY_LINE.search(l)][:40]
    report["residency_after_exit"] = runtime_mod.residency_evidence(joined)
    # fixture 优先取 --log-file 的加载段；它缺少 listening 行时退回 stderr
    source = "server.log" if report["files"].get("server.log", {}).get("listen_marker_found") else "stderr.log"
    report["loader_source"] = source if source in loaders else None
    report["_loader_text"] = loaders.get(source)
    return report


def wait_port_free(seconds: float = 20.0) -> bool:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        if port_free(PORT):
            return True
        time.sleep(0.5)
    return port_free(PORT)


# --- 会话 -------------------------------------------------------------------------------

def props_subset(props: dict[str, Any]) -> dict[str, Any]:
    settings = props.get("default_generation_settings") if isinstance(props.get("default_generation_settings"), dict) else {}
    template = props.get("chat_template")
    return {"keys": sorted(props), "build_info": props.get("build_info"), "model_alias": props.get("model_alias"),
            "model_path_name": Path(str(props.get("model_path", ""))).name or None,
            "total_slots": props.get("total_slots"), "n_ctx": props.get("n_ctx", settings.get("n_ctx")),
            "chat_template_sha256": sha256_bytes(template.encode("utf-8")) if isinstance(template, str) else None}


def run_session(label: str, engine: Path, identity: Path, out: Path, work: dict[str, Any],
                strict_residency: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    """一个引擎会话的完整请求序列；返回（结果证据，仅内存保留的 token 列表）。"""
    runtime = out / label / "runtime"
    evidence: dict[str, Any] = {"engine": str(engine), "steps": {}}
    memory: dict[str, Any] = {"tokens": {}}
    validation: dict[str, Any] = {}
    original = runtime_mod.validate_residency

    def recording_validate(residency: dict[str, Any], layers: int, allow_cpu: bool) -> None:
        validation.update(requested_layers=layers, allow_cpu_offload=allow_cpu)
        try:
            original(residency, layers, allow_cpu)
            validation["ok"] = True
        except RuntimeError as exc:
            validation.update(ok=False, error=str(exc))
            if strict_residency:
                raise

    evidence["idle_before_load"] = idle_baseline()
    server = ManagedServer(runtime, port=PORT, root=out, engine=engine, engine_identity=identity)
    # ManagedServer 在 __enter__ 内按模块属性取 validate_residency；stock 失败时记录而不中断会话以继续收集证据
    runtime_mod.validate_residency = recording_validate
    started = time.perf_counter()
    try:
        with server:
            evidence["load_seconds"] = round(time.perf_counter() - started, 3)
            client = LlamaClient(server.url, timeout=CLIENT_TIMEOUT)
            steps = evidence["steps"]
            # 1. tokenize
            tokenize: dict[str, Any] = {}
            for name, text in PROBES.items():
                t0 = time.perf_counter()
                ids = client.tokenize(text)
                memory["tokens"][name] = ids
                tokenize[name] = {"ids": ids, "count": len(ids), "seconds": round(time.perf_counter() - t0, 3)}
            for batch in work["batches"]:
                t0 = time.perf_counter()
                ids = client.tokenize(batch["prompt"])
                memory["tokens"][batch["name"]] = ids
                tokenize[batch["name"]] = {"count": len(ids), "ids_sha256": object_hash(ids),
                                           "seconds": round(time.perf_counter() - t0, 3)}
            steps["tokenize"] = tokenize
            b0, b1 = work["batches"]
            cache_state: dict[str, Any] = {"checked": False}
            # 2./3. 真实 run_step：第 0 批（假设 A）与第 1 批（第二个 cache 请求）
            steps["batch0_run_step"] = step(client, b0["prompt"], b0["grammar"], b0["ids"], cache_state)
            steps["batch1_run_step"] = step(client, b1["prompt"], b1["grammar"], b1["ids"], cache_state)
            # 4. 固定种子短生成：关闭 prompt cache 以全量重算，两个引擎请求完全一致
            tokens0 = memory["tokens"][b0["name"]]
            request = R.completion_request(tokens0, SEED, b0["grammar"])
            request.update(n_predict=GEN_N_PREDICT, cache_prompt=False, return_tokens=True)
            t0 = time.perf_counter()
            response = client.complete(request)
            output = response.get("tokens") if isinstance(response.get("tokens"), list) else None
            memory["gen_tokens"] = output
            steps["generation_probe"] = response_meta(response, len(tokens0)) | {
                "request_sha256": object_hash(request), "seconds": round(time.perf_counter() - t0, 3),
                "output_token_count": len(output) if output is not None else None,
                "output_tokens_sha256": object_hash(output) if output is not None else None}
            # 5. 受限请求：原始响应字段 + run_step 的分类
            request = R.completion_request(tokens0, SEED, b0["grammar"])
            request["n_predict"] = LIMIT_N_PREDICT
            t0 = time.perf_counter()
            response = client.complete(request)
            steps["limited_raw"] = response_meta(response, len(tokens0)) | {
                "request_sha256": object_hash(request), "seconds": round(time.perf_counter() - t0, 3)}
            # overrides 会与采样参数合并后展开到 n_predict 之后，因此能覆盖 n_predict
            steps["limited_run_step"] = step(client, b0["prompt"], b0["grammar"], b0["ids"], cache_state,
                                             {"n_predict": LIMIT_N_PREDICT})
    except Exception as exc:  # 记录后继续，由调用方汇总为失败
        evidence["error"] = f"{type(exc).__name__}: {exc}"[:800]
    finally:
        runtime_mod.validate_residency = original
    identity_data = server.identity
    evidence["residency"] = identity_data.get("residency")
    evidence["residency_validation"] = validation
    evidence["props"] = props_subset(identity_data["props"]) if isinstance(identity_data.get("props"), dict) else None
    verification = identity_data.get("model_verification") or {}
    evidence["identity"] = {
        "engine_sha256": identity_data.get("engine_sha256"), "engine_identity": identity_data.get("engine_identity"),
        "engine_identity_sha256": identity_data.get("engine_identity_sha256"), "command": identity_data.get("command"),
        "cold_load_seconds": identity_data.get("cold_load_seconds"), "server_pid": identity_data.get("server_pid"),
        "kill_on_job_close": identity_data.get("kill_on_job_close"),
        "server_exit_code": identity_data.get("server_exit_code"),
        "session_peak_device_memory_mib": identity_data.get("peak_device_memory_mib"),
        "model_verification": {k: verification.get(k) for k in ("sha256", "method", "seconds", "size")}}
    logs = process_logs(runtime) if runtime.is_dir() else {}
    loader_text = logs.pop("_loader_text", None)
    if loader_text is not None:
        memory["loader_text"] = loader_text
    evidence["logs"] = logs
    evidence["port_free_after"] = wait_port_free()
    return evidence, memory


def prepare_work() -> dict[str, Any]:
    """b10-joint 在 screening 第一个场景上的第 0、1 批（prompt 只留在内存）。"""
    scenes, _, hashes = load_screening()
    scene = scenes[SCENE_INDEX]
    recipe = R.load_recipe(RECIPE).for_category(scene.category)
    batches = build_batches(scene, recipe)
    work = []
    for batch in batches[:2]:
        ids = list(batch.target_ids)
        work.append({"name": f"b10_batch{batch.index}_prompt", "ids": ids,
                     "prompt": R.render_translation(recipe, batch.to_window(scene)),
                     "grammar": R.translation_grammar(recipe, ids)})
    meta = {"source_hashes": hashes, "scene_id": scene.scene_id, "category": scene.category,
            "cues": len(scene.cues), "batches_total": len(batches), "recipe": recipe.name,
            "recipe_hash": recipe.recipe_hash, "seed": SEED,
            "used_batches": [{"index": b.index, "targets": len(b.target_ids), "before": len(b.before_ids),
                              "after": len(b.after_ids)} for b in batches[:2]],
            "prompt_sha256": [sha256_bytes(w["prompt"].encode("utf-8")) for w in work],
            "grammar_sha256": [sha256_bytes(w["grammar"].encode("utf-8")) for w in work]}
    return {"batches": work, "meta": meta}


def first_difference(a: list[int] | None, b: list[int] | None) -> int | None:
    if a is None or b is None:
        return None
    for index, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return index
    return None if len(a) == len(b) else min(len(a), len(b))


def check_session(label: str, ev: dict[str, Any], failures: list[str]) -> None:
    if "error" in ev:
        failures.append(f"{label}: session error: {ev['error']}")
    steps = ev.get("steps", {})
    for key in ("batch0_run_step", "batch1_run_step"):
        s = steps.get(key)
        if s is None:
            continue
        if not s["accepted"]:
            last = s["attempts"][-1] if s["attempts"] else {}
            timings = last.get("timings") or {}
            failures.append(
                f"{label}: {key} rejected ({s.get('error_kind')}: {s.get('error')}); input_tokens={last.get('input_tokens')} "
                f"tokens_evaluated={last.get('tokens_evaluated')} prompt_n={timings.get('prompt_n')} "
                f"cache_n={timings.get('cache_n')} first_cache_n={s['cache_state'].get('first_cache_n')}")
    raw = steps.get("limited_raw")
    if raw is not None and not raw["run_step_stopped_limit"]:
        failures.append(f"{label}: n_predict={LIMIT_N_PREDICT} response not derived as limit "
                        f"(stop_type={raw['stop_type']!r}, stopped_limit={raw['stopped_limit']!r}, "
                        f"truncated={raw['truncated']!r})")
    limited = steps.get("limited_run_step")
    if limited is not None and limited.get("error_kind") != "limit":
        failures.append(f"{label}: run_step did not classify the limited request as 'limit' "
                        f"(accepted={limited['accepted']}, kind={limited.get('error_kind')})")
    if not ev.get("port_free_after", True):
        failures.append(f"{label}: port {PORT} still occupied after server stop")


def main() -> int:
    args = smokelib.parse_args(__doc__.splitlines()[0])
    out: Path = args.out.resolve()
    timer = smokelib.Timer()
    result: dict[str, Any] = {"passed": False, "failures": [], "versions": {}, "device": None}
    failures: list[str] = result["failures"]

    def done() -> int:
        result["elapsed_s"] = timer.mark("total")
        result["timeline_s"] = dict(timer.marks)
        result["passed"] = not failures
        return smokelib.finish(out, NAME, result)

    missing = [str(p) for p in (STOCK_ENGINE, STOCK_IDENTITY, ENGINE, ENGINE_IDENTITY) if not p.is_file()]
    if missing:
        failures.append("missing engine files (download/extract stock b11583 win-cuda-13.4 and write its "
                        f"identity.json first): {missing}")
        return done()
    if not GPU_LOCK.is_file():
        failures.append(f"{GPU_LOCK} absent; run via `python scripts/smoke/run_all.py {NAME}` which holds the GPU lock")
        return done()
    if not port_free(PORT):
        failures.append(f"port {PORT} occupied before start; another model server is running")
        return done()
    gpu = nvidia_smi("name,driver_version,memory.total")
    result["device"] = {"name": gpu[0], "driver_version": gpu[1], "memory_total_mib": gpu[2]} if gpu else None
    work = prepare_work()
    result["workload"] = work["meta"] | {"probes": {k: sha256_bytes(v.encode("utf-8")) for k, v in PROBES.items()},
                                         "generation_probe": {"n_predict": GEN_N_PREDICT, "cache_prompt": False},
                                         "limited_n_predict": LIMIT_N_PREDICT}
    result["idle_baseline_mib"] = idle_baseline()
    timer.mark("preflight")

    compat, compat_mem = run_session("compat", ENGINE, ENGINE_IDENTITY, out, work, strict_residency=True)
    timer.mark("compat_done")
    stock, stock_mem = run_session("stock", STOCK_ENGINE, STOCK_IDENTITY, out, work, strict_residency=False)
    timer.mark("stock_done")
    result["compat"], result["stock"] = compat, stock

    loader_text = stock_mem.get("loader_text")
    if loader_text:
        (out / "stock-load.log").write_text(loader_text, encoding="utf-8")
        result["stock_load_log"] = {"path": str(out / "stock-load.log"), "lines": loader_text.count("\n"),
                                    "sha256": sha256_bytes(loader_text.encode("utf-8")),
                                    "residency_from_fixture": runtime_mod.residency_evidence(loader_text),
                                    "matches_session_residency":
                                        runtime_mod.residency_evidence(loader_text) == stock.get("residency")}
    for label, ev in (("compat", compat), ("stock", stock)):
        identity = ev["identity"]
        result["versions"][label] = {
            "engine": ev["engine"], "engine_sha256": identity["engine_sha256"],
            "engine_identity_sha256": identity["engine_identity_sha256"],
            "identity": identity["engine_identity"].get("identity") if isinstance(identity["engine_identity"], dict) else None,
            "build_info": (ev.get("props") or {}).get("build_info")}

    check_session("compat", compat, failures)
    check_session("stock", stock, failures)
    validation = stock.get("residency_validation") or {}
    if validation.get("ok") is False or (not validation and "error" not in stock):
        failures.append(f"stock: validate_residency(..., {LAYERS}, False) failed: {validation.get('error')}; "
                        f"loader lines: {stock.get('logs', {}).get('residency_lines')}")
    stock_logs = stock.get("logs", {})
    if stock_logs.get("hard_flag_warnings") or stock_logs.get("unknown_argument_lines"):
        failures.append(f"stock: flag warnings for --fit/--cache-ram/-lv or unknown arguments: "
                        f"{stock_logs.get('hard_flag_warnings')} {stock_logs.get('unknown_argument_lines')}")

    # 跨引擎比较：tokenize 必须一致；生成一致只作信息
    names = list(PROBES) + [b["name"] for b in work["batches"]]
    comparison: dict[str, Any] = {"tokenize_equal": {}}
    for name in names:
        a, b = compat_mem["tokens"].get(name), stock_mem["tokens"].get(name)
        comparison["tokenize_equal"][name] = (a == b) if a is not None and b is not None else None
        if a is None or b is None or a != b:
            failures.append(f"tokenize mismatch or missing for probe {name!r} "
                            f"(first differing index {first_difference(a, b)})")
    ga, gb = compat_mem.get("gen_tokens"), stock_mem.get("gen_tokens")
    comparison["generation_equal"] = ga == gb if ga is not None and gb is not None else None
    comparison["generation_first_difference"] = first_difference(ga, gb)
    for key in ("batch0_run_step", "batch1_run_step"):
        ca, sa = compat["steps"].get(key, {}), stock["steps"].get(key, {})
        comparison[f"{key}_result_equal"] = (ca.get("result_sha256") == sa.get("result_sha256")
                                             if ca.get("accepted") and sa.get("accepted") else None)
        comparison[f"{key}_vram_peak_mib"] = {"compat": (ca.get("vram") or {}).get("peak_mib"),
                                              "stock": (sa.get("vram") or {}).get("peak_mib")}
    comparison["session_peak_mib"] = {label: ev["identity"]["session_peak_device_memory_mib"]
                                      for label, ev in (("compat", compat), ("stock", stock))}
    comparison["batch1_cache_n"] = {
        label: (((ev["steps"].get("batch1_run_step") or {}).get("attempts") or [{}])[-1].get("timings") or {}).get("cache_n")
        for label, ev in (("compat", compat), ("stock", stock))}
    result["comparison"] = comparison
    return done()


if __name__ == "__main__":
    sys.exit(main())
