"""One fresh, text-only Codex process per judgment, with bounded retries."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
import tempfile
import time
from typing import Any, Callable

from experiments.translation_eval.runner import (
    dump, dump_jsonl, load_jsonl, parse, read_json, validate_judgment,
)

from .scheduling import classify_access_failure, schedule_jobs

from .integrity import accept_response, resume_success

MODEL = "gpt-6.1-sol"
EFFORT = "high"
DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "apps", "plugins", "multi_agent", "multi_agent_v2",
    "browser_use", "browser_use_external", "computer_use", "image_generation",
    "view_image", "goals", "hooks", "memories", "skill_search", "tool_suggest",
    "workspace_dependencies", "code_mode_host", "auth_elicitation",
)
OVERRIDES = (
    'model_reasoning_effort="high"', 'web_search="disabled"',
    "project_doc_max_bytes=0", "project_doc_fallback_filenames=[]",
    'approval_policy="never"', "mcp_servers={}", "notify=[]",
)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def response_schema(adjudication: bool = False) -> dict[str, Any]:
    def obj(properties: dict[str, Any]) -> dict[str, Any]:
        return {"type": "object", "properties": properties, "required": list(properties),
                "additionalProperties": False}

    string = {"type": "string"}
    ids = {"type": "array", "items": string}
    properties = {
        "window_id": string, "candidate_alias": string,
        "semantic": {"type": ["integer", "null"], "minimum": 0, "maximum": 4},
        "naturalness": {"type": ["integer", "null"], "minimum": 0, "maximum": 2},
        "status": {"type": "string", "enum": ["scored", "source_ambiguous", "reference_suspect"]},
        "errors": {"type": "array", "items": obj({
            "ids": ids,
            "type": {"type": "string", "enum": ["mistranslation", "omission", "addition", "terminology", "fluency", "mapping"]},
            "severity": {"type": "string", "enum": ["minor", "major", "critical"]},
            "source_evidence": string, "candidate_evidence": string, "reason_zh": string,
        })},
        "uncertainties": {"type": "array", "items": obj({"ids": ids, "reason_zh": string})},
        "summary_zh": string,
    }
    if adjudication:
        properties.update(resolved={"type": "boolean"}, resolution_zh=string)
    return obj(properties)


def command(executable: str, cwd: Path, schema: Path, last_message: Path) -> list[str]:
    args = [executable, "exec", "--model", MODEL, "--ephemeral", "--ignore-user-config",
            "--sandbox", "read-only", "--skip-git-repo-check", "--cd", str(cwd),
            "--color", "never", "--json", "--output-schema", str(schema),
            "--output-last-message", str(last_message)]
    for value in OVERRIDES:
        args += ["-c", value]
    for feature in DISABLED_FEATURES:
        args += ["--disable", feature]
    return args + ["-"]


def _comparison_path(path: Path) -> Path | PureWindowsPath:
    if os.name != 'nt':
        return path
    text = str(path)
    if text.lower().startswith('\\\\?\\unc\\'):
        text = '\\\\' + text[8:]
    elif (len(text) >= 7 and text.startswith('\\\\?\\')
          and text[4].lower() in 'abcdefghijklmnopqrstuvwxyz' and text[5:7] == ':\\'):
        text = text[4:]
    # Comparison only: unknown device namespaces retain their distinct anchors.
    return PureWindowsPath(text)


def local_path(root: Path, relative: str) -> Path:
    value = (root / relative).resolve()
    if not _comparison_path(value).is_relative_to(_comparison_path(root.resolve())):
        raise ValueError('job artifact path escapes evaluation directory')
    return value


def event_evidence(text: str) -> dict[str, Any]:
    """Keep observed identity/usage separate from configured identity."""
    models, efforts, usage, tools = [], [], [], []
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"model", "model_id", "model_slug"} and isinstance(item, str):
                    models.append(item)
                if key in {"reasoning_effort", "model_reasoning_effort"} and isinstance(item, str):
                    efforts.append(item)
                if key == "usage" and isinstance(item, dict):
                    usage.append(item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    for line in text.splitlines():
        try:
            event = parse(line)
        except ValueError:
            continue
        walk(event)
        item = event.get("item", {}) if isinstance(event, dict) else {}
        if item.get("type") and item["type"] not in {"agent_message", "reasoning", "error"}:
            tools.append(item["type"])
    return {"returned_models": sorted(set(models)), "returned_efforts": sorted(set(efforts)),
            "returned_identity_reason": "observed JSON events" if models else "CLI JSON events did not expose model identity; configured identity is not returned identity",
            "usage_events": usage, "tool_events": tools}


def execute(args: list[str], prompt: str, cwd: Path, attempt: Path,
            timeout: float) -> dict[str, Any]:
    env = os.environ.copy()
    removed = []
    # Prevent app/session association; leave Codex's existing authentication untouched.
    for key in list(env):
        if key.startswith("CODEX_") and key != "CODEX_HOME":
            removed.append(key)
            del env[key]
    started = time.perf_counter()
    try:
        completed = subprocess.run(args, input=prompt.encode("utf-8"), capture_output=True,
                                   cwd=cwd, env=env, timeout=timeout, check=False)
        stdout, stderr = completed.stdout, completed.stderr
        result = {"returncode": completed.returncode, "transport_status": "completed"}
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = exc.stdout or b"", exc.stderr or b""
        result = {"returncode": None, "transport_status": "timeout"}
    except OSError as exc:
        stdout, stderr = b"", str(exc).encode("utf-8")
        result = {"returncode": None, "transport_status": "spawn_failed"}
    (attempt / "stdout.jsonl").write_bytes(stdout)
    (attempt / "stderr.txt").write_bytes(stderr)
    result.update(elapsed_seconds=time.perf_counter() - started,
                  removed_session_environment_names=sorted(removed),
                  **event_evidence(stdout.decode("utf-8", errors="replace")))
    return result


def run_job(root: Path, job: dict[str, Any], executable: str, version: str,
            timeout: float, invoke: Callable[..., dict[str, Any]] = execute) -> dict[str, Any]:
    stage = job["job_id"].split("/")[0]
    if stage not in {"primary", "review", "adjudication"}:
        raise ValueError("unknown judgment stage")
    packet = read_json(local_path(root, job["packet"]))
    if (packet["window_id"], packet["candidate_alias"]) != (job["window_id"], job["candidate_alias"]):
        raise ValueError("job/packet identity mismatch")
    prompt = local_path(root, job["prompt"]).read_text(encoding="utf-8-sig")
    prompt += "\nUse only the supplied packet. Do not use tools, files, memory, external knowledge, or any other conversation.\nPACKET:\n"
    prompt += json.dumps(packet, ensure_ascii=False)
    adjudication = stage == "adjudication"
    if adjudication:
        dispute = read_json(local_path(root, job["dispute"]))
        prompt += "\nADJUDICATION:\n" + json.dumps({key: dispute[key] for key in ("judgments", "instruction")}, ensure_ascii=False)
    schema = response_schema(adjudication)
    fingerprint = hashlib.sha256(json.dumps({"prompt": prompt, "schema": schema,
        "model": MODEL, "effort": EFFORT, "overrides": OVERRIDES,
        "disabled_features": DISABLED_FEATURES}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    job_dir = local_path(root, "judge-execution/" + job["job_id"])
    job_dir.mkdir(parents=True, exist_ok=True)
    ledger = job_dir / "job.json"
    response = local_path(root, job["response"])
    previous = read_json(ledger) if ledger.exists() else None
    if response.exists() and (previous is None or previous.get("status") != "succeeded"):
        raise ValueError("canonical response has no successful transport ledger; preserve it in a separate run")
    if previous and previous["fingerprint"] != fingerprint:
        raise ValueError("judge packet/settings changed; use a new evaluation directory")
    attempts = sorted(job_dir.glob("attempt-*"))
    if previous and previous["status"] == "succeeded":
        return resume_success(previous, ledger, response,
            lambda value: validate_judgment(value, packet, adjudication), parse)
    state = {"job_id": job["job_id"], "fingerprint": fingerprint,
             "requested_model": MODEL, "requested_effort": EFFORT, "cli_version": version,
             "response": str(response), "status": "judge_failed", "attempts": []}
    for attempt_dir in attempts:
        metadata = attempt_dir / "attempt.json"
        state["attempts"].append(read_json(metadata) if metadata.exists() else {
            "status": "interrupted", "attempt": attempt_dir.name})
    for number in range(len(attempts) + 1, 3):
        attempt = job_dir / f"attempt-{number}"
        attempt.mkdir(exist_ok=False)
        dump(attempt / "schema.json", schema)
        (attempt / "prompt.txt").write_text(prompt, encoding="utf-8")
        raw = attempt / "last-message.txt"
        record = {"attempt": number, "started_at": utc(), "status": "started"}
        dump(attempt / "attempt.json", record)
        # Empty temporary cwd outside repository ancestry avoids project configuration.
        with tempfile.TemporaryDirectory(prefix="kototoki-judge-") as directory:
            cwd = Path(directory)
            args = command(executable, cwd, attempt / "schema.json", raw)
            record.update(command=args, isolated_cwd=str(cwd))
            dump(attempt / "attempt.json", record)
            record.update(invoke(args, prompt, cwd, attempt, timeout))
        record["finished_at"] = utc()
        try:
            if record["transport_status"] != "completed" or record["returncode"] != 0:
                raise ValueError("Codex transport failed")
            if record["returned_models"] and record["returned_models"] != [MODEL]:
                raise ValueError("returned model differs from frozen requested model")
            if record["returned_efforts"] and record["returned_efforts"] != [EFFORT]:
                raise ValueError("returned reasoning effort differs from requested effort")
            if record["tool_events"]:
                raise ValueError("judge invoked tools despite text-only contract")
            integrity = accept_response(raw, response,
                lambda value: validate_judgment(value, packet, adjudication), parse)
            record["status"] = "succeeded"
            state.update(status="succeeded", **integrity)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            record.update(status="failed", error=str(exc))
        if record['status'] == 'failed':
            record['access_failure'] = classify_access_failure(attempt, record)
        dump(attempt / "attempt.json", record)
        state["attempts"].append(record)
        dump(ledger, state)
        if state["status"] == "succeeded":
            break
    dump(ledger, state)
    return state


@contextmanager
def run_lock(root: Path):
    """OS lock releases after crashes; a second scheduler cannot spend extra retries."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".judge-scheduler.lock").open("a+b") as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("another judge scheduler is running for this evaluation directory") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def run(root: Path, jobs_path: Path, executable: str, workers: int, timeout: float) -> dict[str, Any]:
    if not 1 <= workers <= 6 or timeout <= 0:
        raise ValueError("workers must be 1..6 and timeout must be positive")
    with run_lock(root.resolve()):
        return _run(root, jobs_path, executable, workers, timeout)


def _run(root: Path, jobs_path: Path, executable: str, workers: int, timeout: float) -> dict[str, Any]:
    root = root.resolve()
    jobs = load_jsonl(jobs_path)
    if len({job["job_id"] for job in jobs}) != len(jobs):
        raise ValueError("duplicate judgment job IDs")
    executable = shutil.which(executable) or executable
    version_result = subprocess.run([executable, "--version"], capture_output=True, timeout=30, check=True)
    version = version_result.stdout.decode("utf-8", errors="replace").strip()
    started, states = time.perf_counter(), []
    def on_result(state: dict[str, Any]) -> None:
        print(json.dumps({"job_id": state["job_id"], "status": state["status"],
                          "resumed": state.get("resumed", False)}, ensure_ascii=False), flush=True)
    states, circuit = schedule_jobs(jobs, workers,
        lambda job: run_job(root, job, executable, version, timeout), on_result)
    states.sort(key=lambda item: item["job_id"])
    summary = {"requested_model": MODEL, "requested_effort": EFFORT, "cli_version": version,
               "jobs_file": str(jobs_path.resolve()), "workers": workers,
               "expected_jobs": len(jobs), "succeeded": sum(item["status"] == "succeeded" for item in states),
               "judge_failed": sum(item["status"] == "judge_failed" for item in states),
               "not_run": sum(item["status"] == "not_run" for item in states),
               "circuit_breaker": circuit,
               "elapsed_seconds_this_invocation": time.perf_counter() - started,
               "all_attempt_seconds": sum(attempt.get("elapsed_seconds", 0) for item in states for attempt in item["attempts"]),
               "cost": None, "cost_reason": "CLI does not expose billed cost; raw usage events are retained",
               "jobs": states}
    dump(root / "judge-execution" / (jobs_path.stem + "-summary.json"), summary)
    dump_jsonl(root / "judge-execution" / (jobs_path.stem + "-ledger.jsonl"), states)
    return summary


def prepare_probe(root: Path) -> None:
    if root.exists() and any(root.iterdir()):
        raise ValueError("probe directory must be empty; use run to resume")
    from experiments.translation_eval.runner import PROMPT
    root.mkdir(parents=True, exist_ok=True)
    (root / "judge-prompt.txt").write_text(PROMPT, encoding="utf-8")
    cases = [("equivalent", "明日は来ません。", "明天我不来。", "我明天不会来。"),
             ("negation", "明日は来ません。", "明天我不来。", "我明天会来。"),
             ("number", "三人が来ました。", "来了三个人。", "来了五个人。"),
             ("missing", "三人が来ました。", "来了三个人。", None)]
    jobs = []
    for name, source, reference, candidate in cases:
        uid = "synthetic-1"
        packet = {"window_id": name, "candidate_alias": "candidate-a", "context": [{"id": uid, "text": source}],
                  "scored_ids": [uid], "translations": {uid: candidate}, "reference": {uid: reference},
                  "structural": {"status": "partial_delivery" if candidate is None else "valid",
                                 "missing_ids": [uid] if candidate is None else [], "extra_ids": [], "issues": []}}
        packet_path = f"packets/{name}.json"
        dump(root / packet_path, packet)
        jobs.append({"job_id": f"primary/candidate-a/{name}", "window_id": name,
                     "candidate_alias": "candidate-a", "packet": packet_path,
                     "prompt": "judge-prompt.txt", "response": f"primary/candidate-a/{name}.json"})
    dump_jsonl(root / "jobs.jsonl", jobs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Isolated fresh Codex Sol/high subtitle judgments")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare-probe")
    prepare.add_argument("--output", type=Path, required=True)
    execute_parser = subparsers.add_parser("run")
    execute_parser.add_argument("--output", type=Path, required=True)
    execute_parser.add_argument("--jobs", type=Path, required=True)
    execute_parser.add_argument("--codex", default="codex.exe")
    execute_parser.add_argument("--workers", type=int, choices=range(1, 7), default=6)
    execute_parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    try:
        if args.command == "prepare-probe":
            prepare_probe(args.output)
        else:
            if args.timeout <= 0:
                raise ValueError("timeout must be positive")
            summary = run(args.output, args.jobs, args.codex, args.workers, args.timeout)
            if summary["judge_failed"] or summary["not_run"]:
                parser.exit(1, "部分裁判任务失败；原始尝试已保留。\n")
    except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"裁判执行错误：{exc}\n")
