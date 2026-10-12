"""Frozen-window local generation and separate assisted mapping CLI."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from time import perf_counter
from typing import Any

from . import adapters
from .client import LlamaClient
from .gguf import metadata
from .profiles import GUARD_TOKENS, LEGACY_PROFILE, OFFICIAL_PROFILE, PROFILE_NAMES, generation_parameters, resolve_profile


CANDIDATES = {
    "hy-mt2-7b-q8": "hy-mt2",
    "hy-mt2-30b-a3b-q3-k-m": "hy-mt2-30b",
    "hy-mt2-30b-a3b-q4-k-m-official": "hy-mt2-30b",
    "hy-mt2-30b-a3b-apex-i-compact": "hy-mt2-30b",
    "hy-mt2-30b-a3b-i1-q3-k-l": "hy-mt2-30b",
    "hy-mt2-30b-a3b-i1-q3-k-m": "hy-mt2-30b",
    "tower-plus-9b-q8": "tower-plus",
    "translategemma-12b-q8": "translategemma",
    "translategemma-27b-q3-k-l": "translategemma",
}
MAPPERS = ("hy-mt2-7b-q8", "tower-plus-9b-q8")
MAPPING_RECIPES = ("native-boundary-anchors-v2", "native-exact-partition-v1", "native-boundary-anchors-gbnf-v3", "native-scored-groups-gbnf-v4")
ASSET_IDENTITY_FIELDS = ("repo", "revision", "file", "size", "sha256")
# These are fixed artifact identities, not a claim of runtime compatibility.
HY30_ASSET_IDENTITIES = {
    "hy-mt2-30b-a3b-q3-k-m": (
        "GrahLnn/Hy-MT2-30B-A3B-4bit-GGUF", "4ae7787177f6d4f2d54ec2d543d9fe5f9114d1c9",
        "Hy-MT2-30B-A3B-Q3_K_M.gguf", 14446329888,
        "9398dedb6f783963f0e9b7fc6ecb16a0158a92aa9a4c0a25eab29ba9704c19d5"),
    "hy-mt2-30b-a3b-apex-i-compact": (
        "alphaZimuth/Hy-MT2-30B-A3B-APEX-GGUF", "312cce865e03a0718e36cfd1077e6307957aef72",
        "Hy-MT2-30B-A3B-APEX-I-Compact.gguf", 15035838080,
        "8a51a390b285fb1eb566a1683f8da476be9e87c1fbee5507967d6129872dfa1a"),
    "hy-mt2-30b-a3b-i1-q3-k-l": (
        "mradermacher/Hy-MT2-30B-A3B-i1-GGUF", "c36beb0d9a93b2790313f6beff90482b492ce820",
        "Hy-MT2-30B-A3B.i1-Q3_K_L.gguf", 15644000768,
        "e63046e3379cc2cd43116146c42c2b433e8a6a7d86e85b13924f4a479c94395b"),
    "hy-mt2-30b-a3b-i1-q3-k-m": (
        "mradermacher/Hy-MT2-30B-A3B-i1-GGUF", "c36beb0d9a93b2790313f6beff90482b492ce820",
        "Hy-MT2-30B-A3B.i1-Q3_K_M.gguf", 14446330368,
        "a70d7755b52cc96999c9d5645f881647c598967a5142b0177d7a6c018a4a3a46"),
}


def asset_manifest_paths(paths: list[Path] | None, root: Path) -> list[Path]:
    """Explicit manifests replace defaults; the optional shortlist preserves old setups."""
    if paths:
        return [path.resolve() for path in paths]
    primary = root / ".local/manifests/translation-download-plan.json"
    shortlist = root / ".local/manifests/hy30-shortlist-downloads.json"
    return [primary] + ([shortlist] if shortlist.exists() else [])


def load_assets(paths: list[Path]) -> dict[str, dict[str, Any]]:
    """Merge manifests without accepting ambiguous or relabelled model identities."""
    assets: dict[str, dict[str, Any]] = {}
    seen_paths: set[Path] = set()
    seen_hashes: set[str] = set()
    for path in paths:
        rows = adapters.strict_json(path.read_text(encoding="utf-8-sig"))
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"Asset manifest must contain a nonempty list: {path}")
        for asset in rows:
            if not isinstance(asset, dict) or not isinstance(asset.get("id"), str) or asset["id"] not in CANDIDATES:
                raise ValueError(f"Unregistered model asset in manifest: {path}")
            model_id = asset["id"]
            if model_id in assets:
                raise ValueError(f"Duplicate asset ID: {model_id}")
            if any(not isinstance(asset.get(key), str) or not asset[key] for key in
                   ("repo", "revision", "file", "sha256", "directory", "status")):
                raise ValueError(f"Incomplete asset identity: {model_id}")
            if (type(asset.get("size")) is not int or asset["size"] <= 0
                    or not re.fullmatch(r"[0-9a-f]{64}", asset["sha256"])
                    or not re.fullmatch(r"[0-9a-f]{40}", asset["revision"])
                    or Path(asset["file"]).name != asset["file"]
                    or not asset["file"].endswith(".gguf")
                    or not Path(asset["directory"]).is_absolute()):
                raise ValueError(f"Invalid asset file identity: {model_id}")
            expected = HY30_ASSET_IDENTITIES.get(model_id)
            if expected and tuple(asset[key] for key in ASSET_IDENTITY_FIELDS) != expected:
                raise ValueError(f"Asset identity differs from frozen candidate: {model_id}")
            model_path = (Path(asset["directory"]) / asset["file"]).resolve()
            if model_path in seen_paths or asset["sha256"] in seen_hashes:
                raise ValueError(f"Duplicate asset file identity: {model_id}")
            seen_paths.add(model_path)
            seen_hashes.add(asset["sha256"])
            assets[model_id] = asset
    return assets


def select_asset(assets: dict[str, dict[str, Any]], model_id: str) -> dict[str, Any]:
    if model_id not in assets:
        raise ValueError(f"Candidate asset missing from selected manifests: {model_id}")
    asset = assets[model_id]
    if asset["status"] != "verified":
        raise ValueError(f"Model asset is not verified: {model_id}")
    model_path = Path(asset["directory"]) / asset["file"]
    if model_path.stat().st_size != asset["size"]:
        raise ValueError("Model size no longer matches verified asset manifest")
    return asset


def model_digest(path: Path) -> str:
    """Hash large weights in bounded memory before inference."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, obj: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(obj, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def read_inputs(path: Path) -> list[dict[str, Any]]:
    rows = [adapters.strict_json(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    ids = []
    for row in rows:
        adapters.validate_window(row)
        ids.append(row["id"])
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", row["id"]):
            raise ValueError("Window ID must be safe for artifact names")
    if not rows or len(set(ids)) != len(ids):
        raise ValueError("Empty input or duplicate window IDs")
    return rows


def validate_template(family: str, template: str) -> None:
    if family == "hy-mt2":
        required = ["<|startoftext|>", "<|extra_0|>"]
    elif family == "hy-mt2-30b":
        required = ["<｜hy_begin▁of▁sentence｜>", "<｜hy_User｜>", "<｜hy_Assistant｜>", "<｜reasoning_mode｜>", "no_think", "<eos:6124c78e>"]
    else:
        required = ["<start_of_turn>", "<end_of_turn>", "model"]
    if family == "translategemma":
        required += ['"ja": "Japanese"', '"zh-Hans": "Chinese"', "Produce only the ", "cultural sensitivities.", "source_lang_code", "target_lang_code"]
    if any(part not in template for part in required):
        raise ValueError("GGUF template does not match the frozen native renderer; inspect and version the adapter")


def explicit_oom(message: str) -> bool:
    return bool(re.search(r"out of memory|cuda_error_out_of_memory|cudaerrormemoryallocation|vk_error_out_of_device_memory|std::bad_alloc", message, re.IGNORECASE))


def attempt_generation(client: Any, prompt: str, settings: dict[str, Any], validate: Any, attempts: list[dict[str, Any]]) -> Any:
    """Retry the identical frozen request once; keep every transport and parse failure."""
    for number in range(settings["max_attempts"]):
        start = perf_counter()
        response = None
        record: dict[str, Any] = {"attempt": number + 1, "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()}
        try:
            token_ids = client.tokenize(prompt)
            tokens = len(token_ids)
            record["tokenize_exchange"] = client.last_exchange
            record["prompt_transport"] = "token-ids-v1"
            record["input_token_ids_sha256"] = hashlib.sha256(json.dumps(token_ids, separators=(",", ":")).encode("utf-8")).hexdigest()
            record["input_tokens"] = tokens
            if settings.get("input_limit") and tokens > settings["input_limit"]:
                raise ValueError("Rendered input exceeds native input limit; source context cannot be silently truncated")
            if tokens + settings["n_predict"] + GUARD_TOKENS > settings["context_size"]:
                raise ValueError("Rendered input plus output reserve exceeds runtime context")
            # Numeric prompt arrays bypass server-side BOS insertion. The original
            # text and tokenization flags remain in the preceding /tokenize trace.
            request = dict(generation_parameters(settings), prompt=token_ids, stop=settings["stop"])
            record["sampling_profile"] = settings.get("sampling_profile", LEGACY_PROFILE)
            record["generation_parameters"] = generation_parameters(settings)
            if settings.get("grammar"):
                request["grammar"] = settings["grammar"]
            response = client.complete(request)
            record["original_response"] = client.last_exchange
            record["response"] = response
            effective_prompt = response.get("prompt")
            effective_tokens = response.get("tokens_evaluated")
            if effective_prompt is not None and effective_prompt != prompt:
                raise ValueError("Effective server prompt differs from frozen native prompt")
            if effective_tokens is not None and (type(effective_tokens) is not int or effective_tokens != tokens):
                raise ValueError("Effective server prompt token count differs from supplied token IDs")
            record["effective_prompt_verified"] = effective_prompt is not None
            record["effective_token_count_verified"] = effective_tokens is not None
            if effective_prompt is None or effective_tokens is None:
                record["effective_prompt_evidence_reason"] = "Server response did not expose all prompt/token count fields"
            content = response.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Empty or invalid generated text")
            if response.get("truncated") or response.get("stopped_limit") or response.get("stop_type") == "limit":
                raise ValueError("Generation reached output/context limit")
            result = validate(content)
            record["status"] = "accepted"
            return result
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = f"{type(exc).__name__}: {exc}"
            record.setdefault("original_response", client.last_exchange)
            error_evidence = record["error"]
            if isinstance(response, dict) and response.get("error") is not None:
                error_evidence += "\n" + json.dumps(response["error"], ensure_ascii=False)
            # A generated phrase is never allocation evidence. Read the raw
            # error body only for an unsuccessful HTTP response.
            status = getattr(exc, "code", None)
            if type(status) is int and status >= 400 and isinstance(client.last_exchange, str):
                response_path = Path(client.last_exchange) / "response.raw"
                if response_path.is_file():
                    error_evidence += "\n" + response_path.read_text(encoding="utf-8", errors="replace")
            if explicit_oom(error_evidence):
                record["error_kind"] = "oom"
                if settings.get("stop_on_oom"):
                    break
            if "exceeds" in str(exc):
                break
        finally:
            record["elapsed_seconds"] = perf_counter() - start
            attempts.append(record)
    raise ValueError(attempts[-1]["error"])


def run_window(client: Any, window: dict[str, Any], family: str, settings: dict[str, Any], native: dict[str, Any] | None = None) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    start = perf_counter()
    row: dict[str, Any] = {"window_id": window["id"], "translations": {}, "attempts": attempts, "generation_seconds": 0.0, "auxiliary_seconds": 0.0}
    row["started_at_utc"] = datetime.now(timezone.utc).isoformat()
    if native is not None and settings.get("mapping_recipe") == "native-scored-groups-gbnf-v4":
        # Preserve the declared contract even if no mapping succeeds in this run.
        row["delivery_contract"] = "native-scored-groups-v4"
    if native is not None:
        row["generation_seconds"] = native.get("generation_seconds", native.get("elapsed_seconds"))
        if row["generation_seconds"] is None:
            row["generation_timing_reason"] = "Native generation duration absent from source artifact"
        row["native_text"] = native.get("native_text")
        row["native_original_response"] = native.get("original_response")
        row["native_attempts"] = native.get("attempts")
        row["native_window_artifact"] = native.get("native_window_artifact")
        if native.get("status") != "native_delivered":
            row.update(status="translation_failed", reason=native.get("reason", "Native translation unavailable"))
            row["elapsed_seconds"] = row["generation_seconds"]
            row["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
            return row
    try:
        if native is not None:
            recipe = settings.get("mapping_recipe", "native-boundary-anchors-v2")
            mapper_family = settings.get("mapper_family", "hy-mt2")
            constrained = dict(settings)
            if recipe == "native-boundary-anchors-v2":
                prompt = adapters.boundary_mapping_prompt(window, native["native_text"], mapper_family)
                constrained["grammar"] = adapters.boundary_mapping_grammar(window)
                validate = adapters.validate_boundary_mapping
            elif recipe == "native-boundary-anchors-gbnf-v3":
                prompt = adapters.native_boundary_mapping_prompt(window, native["native_text"], mapper_family)
                constrained["grammar"] = adapters.native_boundary_mapping_grammar(window, native["native_text"])
                validate = adapters.validate_native_boundary_mapping
            elif recipe == "native-scored-groups-gbnf-v4":
                prompt = adapters.grouped_mapping_prompt(window, native["native_text"], mapper_family)
                constrained["grammar"] = adapters.native_boundary_mapping_grammar(adapters.grouped_mapping_window(window), native["native_text"])
                validate = adapters.validate_grouped_mapping
            elif recipe == "native-exact-partition-v1":
                if mapper_family != "hy-mt2":
                    raise ValueError("Legacy exact-partition v1 requires Hy-MT2-7B")
                prompt = adapters.mapping_prompt(window, native["native_text"])
                validate = adapters.validate_mapping
            else:
                raise ValueError("Unknown mapping recipe")
            result, spans = attempt_generation(client, prompt, constrained, lambda content: validate(content, window, native["native_text"]), attempts)
            if recipe == "native-scored-groups-gbnf-v4":
                row.update(status="delivered", translation_groups=result, mapping_groups=spans,
                           source_span_to_target_span=[{key: value for key, value in group.items() if key != "text"} for group in spans])
            else:
                row.update(status="delivered", translations=result, source_span_to_target_span=spans)
        elif family == "translategemma":
            draft = attempt_generation(client, adapters.render(family, window), settings, lambda content: content, attempts)
            row.update(status="native_delivered", native_text=draft, reason="Awaiting separate explicitly configured local pure mapping phase")
        else:
            constrained = dict(settings, grammar=adapters.id_grammar(window["translate_ids"]))
            result = attempt_generation(client, adapters.render(family, window), constrained, lambda content: adapters.translations(content, window["translate_ids"]), attempts)
            row.update(status="delivered", translations=result)
    except Exception as exc:
        row.update(status="mapping_unjudgeable" if native is not None else "translation_failed", reason=str(exc))
    spent = perf_counter() - start
    row["auxiliary_seconds" if native is not None else "generation_seconds"] = spent
    row["elapsed_seconds"] = None if row["generation_seconds"] is None else row["generation_seconds"] + row["auxiliary_seconds"]
    row["original_response"] = attempts[-1].get("original_response") if attempts else None
    if any(attempt.get("error_kind") == "oom" for attempt in attempts):
        row["error_kind"] = "oom"
    row["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    return row


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="本地冻结窗口翻译；TranslateGemma 原生输出后需单独映射。")
    result.add_argument("--candidate", choices=CANDIDATES, required=True)
    result.add_argument("--inputs", type=Path, required=True)
    result.add_argument("--output-dir", type=Path, required=True)
    result.add_argument("--server-url", default="http://127.0.0.1:8080")
    result.add_argument("--engine-manifest", type=Path, required=True)
    result.add_argument("--asset-manifest", type=Path, action="append",
                        help="可重复指定资产清单；显式指定时替代默认原清单＋存在的 shortlist")
    result.add_argument("--mapping-only", type=Path, help="TranslateGemma 原生运行目录；当前服务器须载入显式选择的 mapper")
    result.add_argument("--mapper", choices=MAPPERS, default="hy-mt2-7b-q8", help="独立纯映射模型；不会自动切换")
    result.add_argument("--mapping-recipe", choices=MAPPING_RECIPES, default="native-boundary-anchors-v2")
    result.add_argument("--sampling-profile", choices=PROFILE_NAMES, default=LEGACY_PROFILE,
                        help="版本化采样配置；通用入口默认历史 greedy，新 APEX 基线显式选择 official30b-cached-v1")
    result.add_argument("--n-predict", type=int, help="最大输出 tokens；历史默认 1024，新基线固定 4096")
    result.add_argument("--context-size", type=int, help="总 context tokens；历史默认 4096，新基线默认 8192")
    result.add_argument("--max-attempts", type=int, choices=[1, 2], default=2)
    result.add_argument("--timeout", type=float, default=300.0)
    result.add_argument("--stop-on-oom", action="store_true", help="显式 OOM 后停止重试与后续窗口；保留已尝试行")
    result.add_argument("--limit", type=int, help="开发用前 N 窗口；完整 test 不设置")
    return result


def main() -> int:
    args = parser().parse_args()
    profile = resolve_profile(args.sampling_profile, args.candidate, n_predict=args.n_predict,
                              context_size=args.context_size, mapping_only=bool(args.mapping_only))
    args.n_predict, args.context_size = profile["n_predict"], profile["context_size"]
    family = CANDIDATES[args.candidate]
    if args.mapping_only and family != "translategemma":
        raise ValueError("Mapping phase requires a TranslateGemma candidate")
    if args.mapping_only and args.mapping_recipe == "native-exact-partition-v1" and args.mapper != "hy-mt2-7b-q8":
        raise ValueError("Legacy exact-partition v1 requires Hy-MT2-7B")
    if args.n_predict <= 0 or args.context_size <= 0 or (args.limit is not None and args.limit <= 0):
        raise ValueError("Token budgets and limit must be positive")
    windows = read_inputs(args.inputs)
    if args.limit:
        windows = windows[:args.limit]
    manifest_paths = asset_manifest_paths(args.asset_manifest, Path(__file__).resolve().parents[2])
    assets = load_assets(manifest_paths)
    active_id = args.mapper if args.mapping_only else args.candidate
    asset = select_asset(assets, active_id)
    model_path = Path(asset["directory"]) / asset["file"]
    engine = adapters.strict_json(args.engine_manifest.read_text(encoding="utf-8-sig"))
    if args.sampling_profile == OFFICIAL_PROFILE and engine.get("context_size") != args.context_size:
        raise ValueError("Engine manifest must prove the official baseline context size")
    recorded_path = engine.get("model_path", engine.get("model"))
    if recorded_path and Path(recorded_path).resolve() != model_path.resolve():
        raise ValueError("Engine manifest model does not match requested active candidate")
    if engine.get("asset") and any(engine["asset"].get(key) != asset[key] for key in ("id", *ASSET_IDENTITY_FIELDS)):
        raise ValueError("Engine manifest asset identity differs from selected manifest")
    # The managed runtime hashes before loading. A standalone server needs its
    # own check unless its matching engine record contains that verified digest.
    if not recorded_path or engine.get("model_sha256") != asset["sha256"]:
        if model_digest(model_path) != asset["sha256"]:
            raise ValueError("Model SHA256 no longer matches verified asset manifest")
    model_metadata = metadata(model_path)
    template = model_metadata.get("tokenizer.chat_template", "")
    validate_template(CANDIDATES[active_id], template)
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if (out / "run.json").exists() or (out / "ledger.jsonl").exists():
        raise ValueError("Output already contains a run; choose a new directory to preserve immutable evidence")
    client = LlamaClient(args.server_url, args.timeout, out / "transport")
    props = client.request("/props")
    actual_context = props.get("default_generation_settings", {}).get("n_ctx")
    if (args.sampling_profile == OFFICIAL_PROFILE and actual_context is not None
            and (type(actual_context) is not int or actual_context != args.context_size)):
        raise ValueError("Server context size differs from official baseline runtime context")
    # The local server model path is an independent guard against stale manifests.
    actual_path = props.get("model_path", props.get("model_alias", props.get("default_generation_settings", {}).get("model")))
    if actual_path and Path(actual_path).resolve() != model_path.resolve() and actual_path != active_id:
        raise ValueError(f"Server model identity mismatch: {actual_path}")
    if not actual_path and not recorded_path:
        raise ValueError("Neither server props nor engine manifest identifies the model path")
    stops = {"hy-mt2": ["<|eos|>"], "hy-mt2-30b": ["<eos:6124c78e>"], "tower-plus": ["<end_of_turn>", "<eos>"], "translategemma": ["<end_of_turn>", "<eos>"]}
    settings = {"n_predict": args.n_predict, "context_size": args.context_size, "max_attempts": args.max_attempts, "input_limit": 2048 if family == "translategemma" and not args.mapping_only else None, "stop": stops[CANDIDATES[active_id]], "prompt_transport": "token-ids-v1"}
    settings.update(profile)
    settings["stop_on_oom"] = args.stop_on_oom
    if args.mapping_only:
        settings.update(mapper_candidate=active_id, mapper_family=CANDIDATES[active_id], mapping_recipe=args.mapping_recipe)
    write_json(out / "run.json", {"created_at": datetime.now(timezone.utc).isoformat(), "lane": "V2-native-adapted", "candidate": args.candidate, "phase": "pure-mapping" if args.mapping_only else "translation", "recipe": (args.mapping_recipe if args.mapping_only else "full-window-native-paragraph-v1") if family == "translategemma" else "native-target-json-gbnf-v3", "settings": settings, "input_path": str(args.inputs.resolve()), "input_sha256": digest(args.inputs), "expected_window_ids": [w["id"] for w in windows], "asset": asset, "engine": engine, "engine_manifest_sha256": digest(args.engine_manifest), "server_props": props, "template_sha256": hashlib.sha256(template.encode("utf-8")).hexdigest(), "code_sha256": {p.name: digest(p) for p in Path(__file__).parent.glob("*.py")}, "mapping_source": str(args.mapping_only.resolve()) if args.mapping_only else None})
    source_dir = out / "source"
    source_dir.mkdir()
    for source in Path(__file__).parent.glob("*.py"):
        (source_dir / source.name).write_bytes(source.read_bytes())
    write_json(out / "asset-manifests.json", [{"path": str(path), "sha256": digest(path)} for path in manifest_paths])
    write_json(out / "gguf-metadata.json", model_metadata)
    (out / "inputs.jsonl").write_bytes(args.inputs.read_bytes())
    native_rows = None
    if args.mapping_only:
        native_run = adapters.strict_json((args.mapping_only / "run.json").read_text(encoding="utf-8"))
        if native_run["candidate"] != args.candidate or native_run["input_sha256"] != digest(args.inputs):
            raise ValueError("Mapping source candidate or frozen input differs")
        native_rows = {row["window_id"]: dict(row, native_window_artifact=str((args.mapping_only / f"window-{row['window_id']}.json").resolve())) for row in (adapters.strict_json(line) for line in (args.mapping_only / "ledger.jsonl").read_text(encoding="utf-8").splitlines())}
    failures = 0
    completed = 0
    stopped_reason = None
    with (out / "ledger.jsonl").open("x", encoding="utf-8") as ledger, (out / "results.jsonl").open("x", encoding="utf-8") as results:
        for index, window in enumerate(windows):
            row = run_window(client, window, family, settings, native_rows.get(window["id"], {"status": "translation_failed", "reason": "Native window missing"}) if native_rows is not None else None)
            row["candidate"] = args.candidate
            row["scored_ids"] = window["translate_ids"]
            write_json(out / f"window-{window['id']}.json", row)
            ledger.write(json.dumps(row, ensure_ascii=False) + "\n")
            ledger.flush()
            result_row = {"id": window["id"], "translations": row["translations"], "elapsed_seconds": row["elapsed_seconds"]}
            if "translation_groups" in row:
                result_row["translation_groups"] = row["translation_groups"]
            if "delivery_contract" in row:
                result_row["delivery_contract"] = row["delivery_contract"]
            results.write(json.dumps(result_row, ensure_ascii=False) + "\n")
            results.flush()
            completed += 1
            failures += row["status"] not in ("delivered", "native_delivered")
            elapsed_label = "unknown" if row["elapsed_seconds"] is None else f"{row['elapsed_seconds']:.2f}s"
            print(f"{index + 1}/{len(windows)} {window['id']} {row['status']} {elapsed_label}", flush=True)
            if args.stop_on_oom and row.get("error_kind") == "oom":
                stopped_reason = "oom"
                break
    write_json(out / "completion.json", {"windows": completed, "expected_windows": len(windows), "failures": failures,
               "stopped_reason": stopped_reason, "remaining_window_ids": [window["id"] for window in windows[completed:]],
               "mapping_required": family == "translategemma" and not args.mapping_only})
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
