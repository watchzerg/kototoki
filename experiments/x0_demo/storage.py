"""Private artifact identity and source freezing; stdlib only."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    """Create final artifacts exclusively; never overwrite completed evidence."""
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def private_output(path: Path) -> Path:
    resolved, root = path.resolve(), (ROOT / ".local/x0-demo").resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError("Output must be a new child directory of .local/x0-demo")
    return resolved


def freeze_sources(out: Path) -> dict:
    files = sorted([*Path(__file__).parent.glob("*.py"),
                    *(ROOT / "experiments/w0_demo").glob("*.py"),
                    ROOT / "experiments/qwen/run_qwen.py", ROOT / "kototoki_eval/schema.py"])
    manifest = {}
    for path in files:
        relative = path.relative_to(ROOT)
        target = out / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        manifest[relative.as_posix()] = sha256(path)
    notice = ROOT / "experiments/w0_demo/THIRD_PARTY_NOTICES.txt"
    shutil.copy2(notice, out / "source" / notice.relative_to(ROOT))
    write_json(out / "source-manifest.json", manifest)
    return manifest


def check_sources(manifest: dict) -> None:
    for name, expected in manifest.items():
        if sha256(ROOT / name) != expected:
            raise ValueError(f"Source changed after freeze: {name}; create a new run")


def runtime_identity() -> dict:
    packages = {}
    for name in ("numpy", "torch", "torchaudio", "transformers", "accelerate"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    identity = {"python": sys.version, "executable": sys.executable,
                "platform": platform.platform(), "packages": packages,
                "whisperx_imported": any(k == "whisperx" or k.startswith("whisperx.") for k in sys.modules)}
    if "torch" in sys.modules:
        torch = sys.modules["torch"]
        identity.update(cuda_runtime=torch.version.cuda,
                        gpu=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)
    return identity
