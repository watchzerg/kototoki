"""Shared paths, hashing and atomic file helpers (stdlib only, no side effects)."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, Iterable

REPO = Path(__file__).resolve().parents[2]
PACKAGE_DIR = Path(__file__).resolve().parent
V2_ROOT = REPO / ".local/translation-evaluation/hy30-flow-v2-20261008"
SOURCE_DIR = V2_ROOT / "source/screening-qualified-v1"
REFERENCE_V1_DIR = V2_ROOT / "evaluation-only/reference-v1"
DEFAULT_ROOT = REPO / ".local/translation-evaluation/hy30-flow-v3"
ENGINE = REPO / ".local/translation-evaluation/20261006-v1/hy30-compat/runtime/llama-server.exe"
ENGINE_IDENTITY = REPO / ".local/translation-evaluation/20261006-v1/hy30-compat/runtime/identity.json"
GPU_LOCK = REPO / ".local/gpu.lock"
CANDIDATE = "hy-mt2-30b-a3b-apex-i-compact"
EXPECTED_MODEL_SHA256 = "8a51a390b285fb1eb566a1683f8da476be9e87c1fbee5507967d6129872dfa1a"
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def object_hash(value: Any) -> str:
    return sha256_bytes(canonical(value).encode("utf-8"))


def atomic_write_text(path: Path, text: str) -> None:
    """Write a temporary sibling, fsync it, then atomically replace the target."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    replace_with_retry(temporary, path)


REPLACE_ATTEMPTS = 20


def replace_with_retry(source: Path, target: Path, *, replace: Callable[[Any, Any], None] = os.replace,
                       sleep: Callable[[float], None] = time.sleep) -> None:
    """os.replace, retried when Windows readers/scanners briefly hold the target (PermissionError)."""
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            replace(source, target)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            sleep(min(0.5, 0.1 * (attempt + 1)))


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def atomic_write_jsonl(path: Path, rows: Iterable[Any]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path) -> list[Any]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def safe_name(value: str, what: str) -> str:
    if not isinstance(value, str) or not SAFE_NAME.fullmatch(value) or "__" in value:
        raise ValueError(f"Unsafe {what}: {value!r} (use letters, digits, '.', '-', '_' and no '__')")
    return value


LOCKED_CANDIDATES = "locked-candidates.json"


def check_locked_candidate(root: Path, name: str, recipe_hash: str | None) -> dict[str, Any]:
    """Confirmation gate: {"recipes": [{"name": ..., "recipe_hash": ...}]} must list this exact recipe."""
    path = Path(root) / LOCKED_CANDIDATES
    if not path.is_file():
        raise PermissionError(f"Confirmation requires {path} listing the locked recipe with its recipe_hash")
    for entry in read_json(path).get("recipes", []):
        if isinstance(entry, dict) and entry.get("name") == name:
            if not recipe_hash or entry.get("recipe_hash") != recipe_hash:
                raise PermissionError(f"Locked candidate {name} has a different recipe_hash; a modified recipe "
                                      "loses confirmation eligibility")
            return entry
    raise PermissionError(f"{name} is not listed (with recipe_hash) in {path}")


def code_identity() -> dict[str, Any]:
    """Hash every non-test module of this package; recorded in each run."""
    files = {path.name: sha256_file(path) for path in sorted(PACKAGE_DIR.glob("*.py"))
             if not path.name.startswith("test_")}
    return {"files": files, "package_sha256": object_hash(files)}
