"""读取 `kototoki.toml`（规格 §10.1）：缺省填默认、未知键报错、路径解析。

路径解析规则：

- 用户写出的相对路径按**配置文件所在目录**解析；省略的键用默认值，默认值里的相对路径按**仓库根**解析
  （配置文件放仓库外时默认模型目录与 ffmpeg 仍可用）。
- `[vad]`、`[asr.*]`、`[align]` 的模型路径为相对路径时相对于 `paths.models_root`。翻译与专名建表的模型由 Strata
  自己管理（ADR-0029「Strata session」），`[translate]` 与 `[names]` 都只有 `seed`（Strata 只接受正整数）；产品不起
  llama-server，没有 `[paths] llama_server`。
- `paths.input_dir` 没有默认值，必须写出；`paths.work_dir`（中间产物）默认仓库内 `.local/work`（ADR-0007「工作目录」）。

不进配置文件的两项：GPU 锁路径固定为仓库内 `.local/gpu.lock`；破除死锁只认环境变量
`KOTOTOKI_BREAK_STALE_LOCK=1`，只对本次运行生效。

模块页：docs/architecture/modules/config-and-media.md、docs/architecture/modules/config-reference.md。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import tomllib
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
GPU_LOCK = REPO_ROOT / ".local" / "gpu.lock"
BREAK_STALE_LOCK_ENV = "KOTOTOKI_BREAK_STALE_LOCK"
ENGINES = ("w0", "x0", "cross")  # cross 需要 asr.w0 与 asr.x0 两路模型，DEFAULTS 已都带默认

REQUIRED = object()  # 无默认值的键

# 结构与默认值同规格 §10.1；值的 Python 类型即该键接受的类型（float 键也接受整数）。
DEFAULTS: dict[str, dict[str, Any]] = {
    "paths": {
        "input_dir": REQUIRED,
        "work_dir": ".local/work",
        "models_root": ".local/models",
        "ffmpeg": ".local/tools/ffmpeg/9.0/bin/ffmpeg.exe",
        "ffprobe": ".local/tools/ffmpeg/9.0/bin/ffprobe.exe",
    },
    "input": {
        # 视频与音频；是否有视频流由 ffprobe 判定，不看扩展名（ADR-0007「输入范围」）。
        "extensions": [".mkv", ".mp4", ".m2ts", ".ts", ".mov", ".avi",
                       ".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".mka"],
        "audio_language": "jpn",
        # 有可用的日文文本字幕轨时跳过 STT，直接翻译字幕轨（ADR-0024）；false 时一律走 STT。
        "use_embedded_subtitles": True,
    },
    "run": {"extract_workers": 4, "stable_check_s": 10.0},
    "stt": {"engine": "w0"},
    "vad": {"model": "vad-comparison/pyannote-segmentation-3.0/pytorch_model.bin"},
    "asr.w0": {"model": "faster-whisper-large-v3", "mel_assets": "w0-assets"},
    "asr.x0": {"model": "qwen3-asr-1.7b-hf"},
    "align": {"model": "mms-1b-all"},
    "cues": {
        "max_chars": 24, "max_duration_s": 6.0, "min_duration_s": 0.8, "max_gap_s": 1.0,
        "sentence_endings": "。！？!?", "soft_breaks": "、，,", "lead_out_s": 0.3,
    },
    "translate": {"seed": 20261008},
    "names": {"seed": 20261019},
}
# 按配置文件目录（用户值）或仓库根（默认值）解析的键。
PATH_KEYS = {("paths", key) for key in ("input_dir", "work_dir", "models_root", "ffmpeg", "ffprobe")}
# 相对于 models_root 的模型键。
MODEL_KEYS = {("vad", "model"), ("asr.w0", "model"), ("asr.w0", "mel_assets"), ("asr.x0", "model"),
              ("align", "model")}


class ConfigError(ValueError):
    """配置文件无法使用；消息给出出错的键。"""


@dataclass(frozen=True)
class Paths:
    input_dir: Path
    work_dir: Path
    models_root: Path
    ffmpeg: Path
    ffprobe: Path


@dataclass(frozen=True)
class InputConfig:
    extensions: tuple[str, ...]
    audio_language: str
    use_embedded_subtitles: bool


@dataclass(frozen=True)
class RunConfig:
    extract_workers: int
    stable_check_s: float


@dataclass(frozen=True)
class Models:
    vad: Path
    w0: Path
    w0_mel_assets: Path
    x0: Path
    align: Path


@dataclass(frozen=True)
class CueRules:
    max_chars: int
    max_duration_s: float
    min_duration_s: float
    max_gap_s: float
    sentence_endings: str
    soft_breaks: str
    lead_out_s: float


@dataclass(frozen=True)
class TranslateConfig:
    seed: int


@dataclass(frozen=True)
class NamesConfig:
    seed: int


@dataclass(frozen=True)
class Config:
    source: Path
    paths: Paths
    input: InputConfig
    run: RunConfig
    engine: str
    models: Models
    cues: CueRules
    translate: TranslateConfig
    names: NamesConfig
    gpu_lock: Path
    break_stale_lock: bool


def _flatten(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """TOML 文档 → {节名: {键: 值}}；`[asr.w0]` 记作节名 `asr.w0`。未知节与未知键报错。"""
    sections: dict[str, dict[str, Any]] = {}
    for name, table in document.items():
        if name == "asr" and isinstance(table, dict):
            for engine, sub in table.items():
                if f"asr.{engine}" not in DEFAULTS:
                    raise ConfigError(f"Unknown config section [asr.{engine}]")
                if not isinstance(sub, dict):
                    raise ConfigError(f"[asr.{engine}] must be a table")
                sections[f"asr.{engine}"] = sub
            continue
        if name not in DEFAULTS:
            raise ConfigError(f"Unknown config section [{name}]")
        if not isinstance(table, dict):
            raise ConfigError(f"[{name}] must be a table")
        sections[name] = table
    for name, table in sections.items():
        unknown = sorted(set(table) - set(DEFAULTS[name]))
        if unknown:
            raise ConfigError(f"Unknown config key(s) in [{name}]: {', '.join(unknown)}")
    return sections


def _typed(section: str, key: str, value: Any, default: Any) -> Any:
    where = f"[{section}] {key}"
    if default is REQUIRED or isinstance(default, str):
        if not isinstance(value, str) or not value:
            raise ConfigError(f"{where} must be a nonempty string")
    elif isinstance(default, bool):
        if not isinstance(value, bool):
            raise ConfigError(f"{where} must be true or false")
    elif isinstance(default, int):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{where} must be an integer")
    elif isinstance(default, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{where} must be a number")
        value = float(value)
    elif isinstance(default, list):
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise ConfigError(f"{where} must be a list of nonempty strings")
    return value


def load(path: Path, *, environ: Mapping[str, str] = os.environ) -> Config:
    """读取并校验配置文件；返回全部路径已解析为绝对路径的 `Config`。"""
    source = Path(path).resolve()
    try:
        with source.open("rb") as stream:
            document = tomllib.load(stream)
    except OSError as error:
        raise ConfigError(f"Cannot read config file {source}: {error}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"Invalid TOML in {source}: {error}") from error
    sections = _flatten(document)

    values: dict[tuple[str, str], Any] = {}
    for section, defaults in DEFAULTS.items():
        given = sections.get(section, {})
        for key, default in defaults.items():
            if key in given:
                value = _typed(section, key, given[key], default)
                base = source.parent
            elif default is REQUIRED:
                raise ConfigError(f"[{section}] {key} is required")
            else:
                value = default
                base = REPO_ROOT
            if (section, key) in PATH_KEYS:
                value = (base / value).resolve()
            values[section, key] = value

    models_root = values["paths", "models_root"]
    for section, key in MODEL_KEYS:
        values[section, key] = (models_root / values[section, key]).resolve()

    engine = values["stt", "engine"]
    if engine not in ENGINES:
        raise ConfigError(f"[stt] engine must be one of {', '.join(ENGINES)}, got {engine!r}")
    if values["run", "extract_workers"] < 1:
        raise ConfigError("[run] extract_workers must be at least 1")
    for section in ("translate", "names"):  # Strata 只接受正整数 seed
        if not 0 < values[section, "seed"] < 2**31:
            raise ConfigError(f"[{section}] seed must be a positive integer below 2**31")

    return Config(
        source=source,
        paths=Paths(**{key: values["paths", key] for key in DEFAULTS["paths"]}),
        input=InputConfig(extensions=tuple(ext.lower() for ext in values["input", "extensions"]),
                          audio_language=values["input", "audio_language"],
                          use_embedded_subtitles=values["input", "use_embedded_subtitles"]),
        run=RunConfig(**{key: values["run", key] for key in DEFAULTS["run"]}),
        engine=engine,
        models=Models(vad=values["vad", "model"], w0=values["asr.w0", "model"],
                      w0_mel_assets=values["asr.w0", "mel_assets"], x0=values["asr.x0", "model"],
                      align=values["align", "model"]),
        cues=CueRules(**{key: values["cues", key] for key in DEFAULTS["cues"]}),
        translate=TranslateConfig(seed=values["translate", "seed"]),
        names=NamesConfig(seed=values["names", "seed"]),
        gpu_lock=GPU_LOCK,
        break_stale_lock=environ.get(BREAK_STALE_LOCK_ENV) == "1",
    )
