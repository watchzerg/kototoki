"""Offline fixtures and fakes shared by the v3 tests (no GPU, model or network)."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError

from .common import atomic_write_json
from .data import Cue, ReferenceWindow, Scene, WindowMeta
from .generate import SessionHandle
from . import recipes as R


def make_scene(scene_id: str, n: int, *, work_id: str = "W01", category: str = "anime_series",
               text: str | None = None) -> Scene:
    return Scene(scene_id, tuple(Cue(f"{scene_id}-J{i:03d}", text or f"台詞{i}ですね", float(i), i + 0.5)
                                 for i in range(n)), work_id, category)


class FakeClient:
    """Tokens are code points; completions echo deterministic translations of the requested IDs."""

    def __init__(self, *, first_cache_n: int = 0, plan: dict[int, str] | None = None):
        self.first_cache_n = first_cache_n
        self.plan = plan or {}
        self.completions = 0
        self.tokenize_calls = 0
        self.requests: list[dict[str, Any]] = []
        self.last_exchange = None
        self.timeout = 0

    def tokenize(self, prompt: str) -> list[int]:
        self.tokenize_calls += 1
        return [ord(ch) for ch in prompt]

    def complete(self, request: dict[str, Any]) -> dict[str, Any]:
        self.completions += 1
        self.requests.append(request)
        prompt = "".join(chr(t) for t in request["prompt"])
        behaviour = self.plan.get(self.completions)
        if behaviour == "oom":
            raise HTTPError("http://127.0.0.1:8080/completion", 500, "CUDA error: out of memory", {}, None)
        timings = {"cache_n": self.first_cache_n if self.completions == 1 else 5, "prompt_n": len(request["prompt"])}
        base = {"tokens_predicted": 12, "tokens_evaluated": len(request["prompt"]), "timings": timings, "stop_type": "eos"}
        if behaviour == "bad_json":
            return base | {"content": "{not json"}
        if behaviour == "limit":
            return base | {"content": '{"translations":{' + " \n" * 50, "stop_type": "limit", "stopped_limit": True}
        if "【场景日文】" in prompt:
            lines = prompt.split("【场景日文】\n", 1)[1].split("<｜hy_Assistant｜>", 1)[0].split("\n")
            assert lines and all(lines), "terms prompt must list one source line per cue"
            return base | {"content": json.dumps({"terms": [{"source": "台詞", "translation": "台词"},
                                                            {"source": "唯一語", "translation": "x"}]},
                                                 ensure_ascii=False)}
        if "candidate_translation" in prompt:
            payload, _ = json.JSONDecoder().raw_decode(prompt.split(R.REVIEW_TASK, 1)[1])
            return base | {"content": json.dumps({"translations": {k: "审" + k for k in payload["translate_ids"]}}, ensure_ascii=False)}
        target, _ = json.JSONDecoder().raw_decode(prompt.split("【待译 JSON】\n", 1)[1])
        return base | {"content": json.dumps({"translations": {k: "译" + k for k in target["translations"]}}, ensure_ascii=False)}


class FakeSessions:
    def __init__(self, clients: list[FakeClient]):
        self.clients = list(clients)
        self.opened = 0

    @contextmanager
    def __call__(self, run_dir: Path, index: int) -> Iterator[SessionHandle]:
        self.opened += 1
        yield SessionHandle(self.clients.pop(0), {"server_pid": 1000 + index, "command": ["fake"]})


def reference_windows(per_work: int = 2) -> tuple[dict[str, ReferenceWindow], list[Scene]]:
    """Two series works and two movie works, screen-a/screen-b, 5 scored cues each."""
    reference: dict[str, ReferenceWindow] = {}
    scenes = []
    works = [("W01", "anime_series"), ("W02", "anime_series"), ("M01", "animation_movie"), ("M02", "animation_movie")]
    for work, category in works:
        scene = make_scene(f"F2-{work}-S001", 10 * per_work + 10, work_id=work, category=category)
        scenes.append(scene)
        for k in range(per_work * 2):
            ids = scene.ids[2 + 5 * k: 7 + 5 * k]
            split = "screen-a" if k % 2 == 0 else "screen-b"
            meta = WindowMeta(f"{scene.scene_id}-Q{k:03d}", scene.scene_id, split, work, work, category,
                              "risk" if k == 3 else "representative", (), tuple(ids))
            text = {c.id: c.text for c in scene.cues}
            units = tuple({"id": i, "ja": text[i], "zh": "参" + i, "confidence": "high", "ambiguity_zh": None} for i in ids)
            context = tuple({"id": i, "ja": text[i], "scored": i in ids} for i in scene.ids)
            reference[meta.window_id] = ReferenceWindow(meta, units, context)
    return reference, scenes


def write_fake_run(root: Path, run_id: str, scenes: list[Scene], *, seed: int = 1, scope: str = "screening",
                   translate: Any = None, failed: set[str] | None = None) -> Path:
    run_dir = root / "runs" / run_id
    for scene in scenes:
        status = "failed" if scene.scene_id in (failed or set()) else "complete"
        translations = {} if status == "failed" else {c.id: (translate(c.id) if translate else "译" + c.id) for c in scene.cues}
        atomic_write_json(run_dir / "scenes" / f"{scene.scene_id}.json",
                          {"scene_id": scene.scene_id, "status": status, "cue_ids": scene.ids, "translations": translations})
    atomic_write_json(run_dir / "run.json", {
        "schema": "hy30-flow-v3-run-v1", "run_id": run_id, "recipe": {"name": run_id.split("__")[0]}, "recipe_hash": "x",
        "seed": seed, "scope": scope, "sources": {}, "scene_ids": [s.scene_id for s in scenes], "sessions": [],
        "resumed": False, "wall_clock_seconds": 10.0, "performance_comparable": True,
        "completion": {"state": "complete", "missing_scene_ids": [], "failed_scene_ids": sorted(failed or [])}})
    return run_dir


def judgement_for(payload: dict[str, Any], errors: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    errors = errors or {}
    return {"windows": [{"window_id": w["window_id"], "cues": [
        {"id": c["id"], "no_error": not errors.get(c["id"]), "errors": errors.get(c["id"], [])}
        for c in w["scored_cues"]]} for w in payload["windows"]]}


def cli_stdout(structured: Any = None, *, is_error: bool = False, status: int | None = None,
               result: str | None = None, model: str = "claude-opus-5-5") -> bytes:
    """Mirror the observed `claude -p --output-format json` result shape."""
    body = {"type": "result", "subtype": "success", "is_error": is_error,
            "terminal_reason": "api_error" if is_error else "completed", "api_error_status": status,
            "result": result if result is not None else json.dumps(structured, ensure_ascii=False),
            "session_id": "s", "total_cost_usd": 0.12, "duration_ms": 3456,
            "usage": {"input_tokens": 10, "output_tokens": 20},
            "modelUsage": {} if is_error else {model: {"inputTokens": 10, "outputTokens": 20, "canonicalModel": model}}}
    if structured is not None and not is_error:
        body["structured_output"] = structured
    return json.dumps(body, ensure_ascii=False).encode("utf-8")
