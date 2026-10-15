"""阶段计划：阶段链、各阶段的产物与输入、模型文件清单、期望身份，以及"下一个要跑的阶段"的唯一归属。

编排器（`job`）与三个 worker 壳（`workers/{vad,asr,align}`）都从这里取身份：壳把它写进产物，编排用它核对
产物是否当前（`artifacts.is_current`）。本模块只产出期望身份，不比对产物内容、不写文件、不加载模型；
模型文件 SHA256 由调用方经 `ModelSha` 回调提供（编排用 `workers/gpu.verify_models` 加 size+mtime 缓存）。
不依赖 torch、ffmpeg 与网络；翻译阶段的 run 目录、身份与"是否需要模型"归翻译子系统（`translate.plan`），
核对到该阶段时才导入它。

阶段链（规格 §3）::

    probe/extract ─► vad ─► asr ─► align ─► cues ─► translate ─► publish
                      vad.json 无语音时直接 ─────────────────────► publish

`next_stage` 对一个文件从 vad 起逐阶段核对，返回第一个需要运行的阶段与此前各阶段的期望身份；
某阶段跑完后用 `advance` 从该阶段继续核对，不再从头重算。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
import importlib
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from kototoki import artifacts, recipes, srt
from kototoki.config import Config

if TYPE_CHECKING:  # 运行时延迟导入，见 translate_plan
    from kototoki.translate import TranslatePlan

JA_SRT = "ja.srt"  # cues 阶段写出、翻译读取的日文 SRT（工作目录内）

GPU_STAGES = ("vad", "asr", "align")
# 需要核对身份的阶段，按链上顺序；`publish`／`done` 是计划的终态，不是阶段。
STAGES = (*GPU_STAGES, "cues", "translate")
# 阶段产物（工作目录内文件名）。
STAGE_OUTPUT = {"vad": artifacts.VAD, "asr": artifacts.ASR, "align": artifacts.ALIGN, "cues": artifacts.JA_CUES}
# GPU 阶段 worker 的 jobs 输入：(输入名 → 工作目录内文件)。
STAGE_INPUTS = {"vad": (("wav", artifacts.AUDIO_16K),),
                "asr": (("wav", artifacts.AUDIO_16K), ("vad", artifacts.VAD)),
                "align": (("wav", artifacts.AUDIO_16K), ("asr", artifacts.ASR))}
# `published.json` 的 `sources` 里各阶段身份的键（`cues` 阶段的产物是 `ja-cues.json`）。
IDENTITY_KEY = {"vad": "vad", "asr": "asr", "align": "align", "cues": "ja_cues", "translate": "translate"}

ASR_RECIPES = {"w0": recipes.W0, "x0": recipes.X0}

# --- 模型文件：路径键（`Config.models` 的同名键）与固定 SHA256 ----------------------------------------

VAD_CHECKPOINT_SHA256 = "da85c29829d4002daedd676e012936488234d9255e65e86dfab9bec6b1729298"
# faster-whisper large-v3（CT2）目录内参与推理的文件，SHA256 取自 W0 基线运行记录。
W0_FILES = {
    "config.json": "a9306624f5ec14270a014b647e5c316b6e03a662c369758d1b90697a7b0655b9",
    "model.bin": "69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1",
    "preprocessor_config.json": "7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711",
    "tokenizer.json": "6d8cbd7cd0d8d5815e478dac67b85a26bbe77c1f5e0c6d76d1ce2abc0e5f21ca",
    "vocabulary.json": "c69260f2ab26d659b7c398f9a2b2b48ed0df16c3b47d7326782fd9cba71690c1",
}
# Qwen3-ASR-1.7B-hf 目录内参与推理的文件（权重与全部 .json／.jinja；README 与下载残留不参与），
# SHA256 取自 X0 基线运行记录（`model_files_sha256.asr`）。
X0_FILES = {
    "model.safetensors": "2db53c7d81bd9b8cbc6a074e89be2c968a0d373fb4ee68bb1b1e14f7042dfee1",
    "chat_template.jinja": "f50e6b694fbf4a683206e37869990d68333fe95d285730f084c838a34b0d98c2",
    "config.json": "117ac8e63e2af7cae3665e5a632d6eb03f5f384915519ceb6403c15ec6533f63",
    "generation_config.json": "9939fc9388b79bd70757f938b87381e817173d6a6158f5af6506c0b73e775c3c",
    "processor_config.json": "bc0b230081b44e629dd5b9045b78495615c1831b4b9f4cffe97bd37e82a6156a",
    "tokenizer.json": "fe1fad59be22a41ee293363fcf95fdedbc7c93f3b49270b1d2e18bd1399a7a05",
    "tokenizer_config.json": "945e980986de2ca7768f3326bfdbb4fbea3406f972b8ae0be233089f2b253c11",
}
# mms-1b-all 目录内参与推理的文件，SHA256 取自 W0 基线运行记录。
MMS_FILES = {
    "adapter.jpn.safetensors": "0d67ea38940d2c539d7c60b603d134ae7ce7af5314e103a8a9506c6476bbaca3",
    "config.json": "ee172ef39a0e40c55403fb811fa0f56c6198c7ed21a2bdf5bd0e72e52c07a41c",
    "model.safetensors": "0f1d95ce43d27e03d5d8dd56c697c805460f967c793dd2cbec2e8e8012deda98",
    "preprocessor_config.json": "f724fdad65341e79bd9741888fe4e8ce1bb2e7b44fc8216c28c591afb1e202f4",
    "special_tokens_map.json": "9046da57c270c8e74d0f38832b4adce269c9d914ef21d2a0925e7772152dd793",
    "tokenizer_config.json": "42a65547cf0654d12263ece7c909c4b0c574b660c78658f806c772cc223bc01b",
    "vocab.json": "0375a07a977a599040a7ff333b6974996965cd93754020619518c15db7691f01",
}


def worker_models(config: Config) -> dict[str, str]:
    """jobs `config.models`：worker 用到的模型路径（字符串）。"""
    m = config.models
    return {"vad": str(m.vad), "w0": str(m.w0), "w0_mel_assets": str(m.w0_mel_assets), "x0": str(m.x0),
            "align": str(m.align)}


def model_files(stage: str, models: Mapping[str, str], *, engine: str | None = None) -> dict[str, tuple[Path, str]]:
    """GPU 阶段加载前要核对的模型文件：{名称: (路径, 期望 SHA256)}；只有 asr 需要 `engine`。"""
    if stage == "vad":
        return {"pyannote-segmentation-3.0/pytorch_model.bin": (Path(models["vad"]), VAD_CHECKPOINT_SHA256)}
    if stage == "align":
        return {f"mms-1b-all/{name}": (Path(models["align"]) / name, sha256) for name, sha256 in MMS_FILES.items()}
    if stage != "asr":
        raise ValueError(f"{stage!r} is not a GPU stage")
    if engine not in ASR_RECIPES:
        raise ValueError(f"ASR engine {engine!r} is not available")
    if engine == "x0":
        return {f"qwen3-asr-1.7b-hf/{name}": (Path(models["x0"]) / name, sha256) for name, sha256 in X0_FILES.items()}
    files = {f"faster-whisper-large-v3/{name}": (Path(models["w0"]) / name, sha256) for name, sha256 in W0_FILES.items()}
    files["w0-assets/mel_filters.npz"] = (Path(models["w0_mel_assets"]) / "mel_filters.npz",
                                          recipes.W0["features"]["mel_sha256"])
    return files


def recipe_hash(stage: str, *, engine: str | None = None) -> str:
    """GPU 阶段写进身份与 jobs 文件的配方 hash；只有 asr 需要 `engine`。"""
    if stage == "vad":
        return recipes.recipe_hash(recipes.VAD)
    if stage == "align":
        return recipes.recipe_hash(recipes.MMS)
    if stage == "asr":
        if engine not in ASR_RECIPES:
            raise ValueError(f"ASR engine {engine!r} is not available")
        return recipes.recipe_hash(ASR_RECIPES[engine])
    raise ValueError(f"{stage!r} is not a GPU stage")


# --- 各阶段期望身份（字段、键名与取值不变：现有产物目录续跑必须全部命中） --------------------------------

def probe_identity(config: Config, relative: str | PurePosixPath, ffprobe: Mapping[str, Any]) -> dict[str, Any]:
    return {"video": artifacts.video_identity(config.paths.input_dir, relative, ffprobe),
            "recipe_hash": recipes.recipe_hash(recipes.MEDIA),
            "config": {"audio_language": config.input.audio_language}}


def vad_identity(pcm_sha256: str, model_sha256: Mapping[str, str]) -> dict[str, Any]:
    return artifacts.derived_identity(upstream={artifacts.AUDIO_16K: pcm_sha256},
                                      recipe_hash=recipe_hash("vad"), models=model_sha256)


def asr_identity(engine: str, pcm_sha256: str, vad_sha256: str, model_sha256: Mapping[str, str]) -> dict[str, Any]:
    return artifacts.derived_identity(upstream={artifacts.AUDIO_16K: pcm_sha256, artifacts.VAD: vad_sha256},
                                      recipe_hash=recipe_hash("asr", engine=engine), models=model_sha256)


def align_identity(pcm_sha256: str, asr_sha256: str, model_sha256: Mapping[str, str]) -> dict[str, Any]:
    return artifacts.derived_identity(upstream={artifacts.AUDIO_16K: pcm_sha256, artifacts.ASR: asr_sha256},
                                      recipe_hash=recipe_hash("align"), models=model_sha256)


def cues_identity(align_sha256: str, config: Config) -> dict[str, Any]:
    return artifacts.derived_identity(upstream={artifacts.ALIGN: align_sha256},
                                      recipe_hash=recipes.recipe_hash(recipes.CUES), config=asdict(config.cues))


def translate_plan(work_dir: Path, config: Config) -> TranslatePlan:
    """翻译子系统的 `TranslatePlan`（run 目录、`identity`、`needs_model`）；读 `ja.srt`，不写文件。"""
    translate = importlib.import_module("kototoki.translate")
    return translate.plan(work_dir, srt.read_srt(work_dir / JA_SRT), config)


# --- 计划 -------------------------------------------------------------------------------------------

ModelSha = Callable[[str], Mapping[str, str]]  # GPU 阶段名 → {模型文件名: SHA256}


class PlanError(RuntimeError):
    """核对某阶段期望身份时出错（如读不了上游产物）；`stage` 是正在核对的阶段。"""

    def __init__(self, stage: str, error: Exception):
        super().__init__(f"{type(error).__name__}: {error}")
        self.stage = stage


@dataclass(frozen=True)
class Target:
    """一个文件的计划输入：CPU 阶段之后已知的常量。"""
    work_dir: Path
    finals: Mapping[str, Path]        # 三份最终 SRT 的路径
    probe: Mapping[str, Any]          # `probe.json` 的期望身份（已当前）
    pcm_sha256: str


@dataclass(frozen=True)
class Plan:
    """`stage` 是第一个需要运行的阶段（`vad`／`asr`／`align`／`cues`／`translate`），或终态
    `publish`（无语音，直接发布零条目 SRT）／`done`（已发布且身份匹配、最终文件未改动）。
    `identities` 是 `probe` 与从 vad 起到 `stage`（含）各阶段的期望身份，键同 `published.json` 的 `sources`；
    `translate` 是核对到翻译阶段后翻译子系统给出的计划（run 目录、是否需要模型），此前为 None。
    """
    stage: str
    identities: Mapping[str, Any]
    no_speech: bool
    translate: TranslatePlan | None = None  # 核对到翻译阶段后才有

    @property
    def sources(self) -> dict[str, Any]:
        """`published.json` 的 `sources`：参与"已是最新"判定的全部身份与 `no_speech`。"""
        keys = ("probe", "vad") if self.no_speech else ("probe", "vad", "asr", "align", "ja_cues", "translate")
        return {key: self.identities[key] for key in keys} | {"no_speech": self.no_speech}


def next_stage(target: Target, config: Config, models: ModelSha) -> Plan:
    """从 vad 起逐阶段核对，返回第一个需要运行的阶段；每文件每次运行调用一次。出错抛 `PlanError`。"""
    return _check_from(target, config, models, Plan("vad", {"probe": target.probe}, False))


def advance(previous: Plan, target: Target, config: Config, models: ModelSha) -> Plan:
    """`previous.stage` 跑完之后从该阶段继续核对：其产物不当前时返回的 `stage` 不变（调用方据此记失败）。"""
    if previous.stage not in STAGES:
        raise ValueError(f"Plan is already at {previous.stage!r}; nothing to advance from")
    return _check_from(target, config, models, previous)


def _check_from(target: Target, config: Config, models: ModelSha, plan: Plan) -> Plan:
    work, pcm = target.work_dir, target.pcm_sha256
    ids = dict(plan.identities)
    stage = plan.stage
    try:
        for stage in STAGES[STAGES.index(plan.stage):]:
            key = IDENTITY_KEY[stage]
            if stage == "translate":
                translate = translate_plan(work, config)
                ids[key] = translate.identity
                return _publish_state(target, Plan(stage, ids, False, translate))
            if stage == "vad":
                ids[key] = vad_identity(pcm, models("vad"))
            elif stage == "asr":
                ids[key] = asr_identity(config.engine, pcm, artifacts.sha256_file(work / artifacts.VAD), models("asr"))
            elif stage == "align":
                ids[key] = align_identity(pcm, artifacts.sha256_file(work / artifacts.ASR), models("align"))
            else:
                ids[key] = cues_identity(artifacts.sha256_file(work / artifacts.ALIGN), config)
            current = artifacts.is_current(work / STAGE_OUTPUT[stage], ids[key])
            if stage == "cues":
                current = current and (work / JA_SRT).is_file()
            if not current:
                return Plan(stage, ids, False)
            if stage == "vad" and artifacts.read_json(work / artifacts.VAD).get("chunks") == []:
                return _publish_state(target, Plan("publish", {k: ids[k] for k in ("probe", "vad")}, True))
        raise AssertionError(f"stage chain ended without reaching translate (from {plan.stage!r})")
    except Exception as error:
        raise PlanError(stage, error) from error


def _publish_state(target: Target, plan: Plan) -> Plan:
    """已发布记录的 `sources` 等于期望且三份最终文件未改动即 `done`；否则维持 `publish`／`translate`。"""
    record = artifacts.read_published(target.work_dir)
    expected = plan.sources
    if record is not None and artifacts.canonical({key: record["sources"].get(key) for key in expected}) \
            == artifacts.canonical(expected):
        if all(path.is_file() and artifacts.sha256_file(path) == record["sha256"][kind]
               for kind, path in target.finals.items()):
            return replace(plan, stage="done")
    return plan
