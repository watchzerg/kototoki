"""阶段计划模块（`kototoki.plan`）离线测试：阶段链逐级推进、无语音直达发布、已发布即 `done`、
最终文件改动即重新发布、连续调用结果相同且不改写入参、核对出错时标明阶段。
壳写出的身份与本模块相等由 `tests/test_stt_workers.py` 覆盖；整批运行中的调用次数由 `tests/test_job.py` 覆盖。
"""

from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock
import sys

from kototoki import artifacts, plan, srt
from kototoki.config import load

MODELS = {"fake-model": "b" * 64}
PCM = hashlib.sha256(b"pcm").hexdigest()
PROBE_IDENTITY = {"video": {"relative_path": "a.mkv", "size": 1, "mtime_ns": 2, "ffprobe": {}},
                  "recipe_hash": "c" * 64, "config": {"audio_language": "jpn"}}
SRT_JA = "1\n00:00:01,000 --> 00:00:02,000\nこんにちは\n"


def models(stage: str) -> dict[str, str]:
    return MODELS


class PlanCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        (self.root / "in").mkdir()
        toml = self.root / "kototoki.toml"
        toml.write_text('[paths]\ninput_dir = "in"\noutput_dir = "out"\n', encoding="utf-8")
        self.config = load(toml)
        self.work = self.root / "out" / ".work" / "0123456789ab"
        self.work.mkdir(parents=True)
        self.finals = artifacts.final_srt_paths(self.root / "out", "a.mkv")
        self.target = plan.Target(self.work, self.finals, PROBE_IDENTITY, PCM)
        translate = types.ModuleType("kototoki.translate")
        translate.RECIPE_HASH = "a" * 64
        self.enterContext(mock.patch.dict(sys.modules, {"kototoki.translate": translate}))

    # --- 逐级写出产物 ---------------------------------------------------------------------------

    def write_vad(self, chunks: list | None = None) -> None:
        artifacts.write_artifact(self.work / artifacts.VAD, plan.vad_identity(PCM, MODELS),
                                 {"offset_s": 0, "chunks": [{"start_s": 0.0}] if chunks is None else chunks})

    def write_asr(self) -> None:
        vad_sha = artifacts.sha256_file(self.work / artifacts.VAD)
        artifacts.write_artifact(self.work / artifacts.ASR, plan.asr_identity("w0", PCM, vad_sha, MODELS), {"offset_s": 0})

    def write_align(self) -> None:
        asr_sha = artifacts.sha256_file(self.work / artifacts.ASR)
        artifacts.write_artifact(self.work / artifacts.ALIGN, plan.align_identity(PCM, asr_sha, MODELS), {"offset_s": 0})

    def write_cues(self, text: str = SRT_JA) -> None:
        align_sha = artifacts.sha256_file(self.work / artifacts.ALIGN)
        srt.write_srt(text, self.work / plan.JA_SRT)
        artifacts.write_artifact(self.work / artifacts.JA_CUES, plan.cues_identity(align_sha, self.config), {"cues": []})

    def publish(self, current: plan.Plan) -> None:
        texts = {kind: "" if current.no_speech else SRT_JA for kind in artifacts.FINAL_SUFFIXES}
        for kind, path in self.finals.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(texts[kind].encode("utf-8"))
        artifacts.record_published(self.work, self.finals,
                                   {kind: artifacts.sha256_bytes(texts[kind].encode()) for kind in texts},
                                   current.sources | {"translate_fallback_cues": 0}, "translate/x")

    def next(self) -> plan.Plan:
        return plan.next_stage(self.target, self.config, models)


class ChainTests(PlanCase):
    def test_first_needed_stage_follows_the_artifacts(self) -> None:
        self.assertEqual(self.next().stage, "vad")
        self.write_vad()
        current = self.next()
        self.assertEqual(current.stage, "asr")
        self.assertEqual(set(current.identities), {"probe", "vad", "asr"})
        self.assertEqual(current.identities["asr"]["upstream"][artifacts.VAD],
                         artifacts.sha256_file(self.work / artifacts.VAD))
        self.write_asr()
        self.assertEqual(self.next().stage, "align")
        self.write_align()
        self.assertEqual(self.next().stage, "cues")
        self.write_cues()
        current = self.next()
        self.assertEqual(current.stage, "translate")
        self.assertEqual(current.identities["translate"],
                         {"ja_srt_sha256": artifacts.sha256_file(self.work / plan.JA_SRT), "recipe_hash": "a" * 64,
                          "seed": self.config.translate.seed})
        self.assertEqual(set(current.sources), {"probe", "vad", "asr", "align", "ja_cues", "translate", "no_speech"})
        self.publish(current)
        self.assertEqual(self.next().stage, "done")

    def test_cues_stage_needs_both_ja_cues_and_ja_srt(self) -> None:
        self.write_vad()
        self.write_asr()
        self.write_align()
        self.write_cues()
        (self.work / plan.JA_SRT).unlink()
        self.assertEqual(self.next().stage, "cues")

    def test_advance_continues_from_the_finished_stage(self) -> None:
        current = self.next()
        self.write_vad()
        current = plan.advance(current, self.target, self.config, models)
        self.assertEqual(current.stage, "asr")
        # 产物没写出来：stage 不变，调用方据此记失败。
        self.assertEqual(plan.advance(current, self.target, self.config, models).stage, "asr")
        self.write_asr()
        self.write_align()
        self.write_cues()
        current = plan.advance(current, self.target, self.config, models)
        self.assertEqual(current.stage, "translate")
        self.publish(current)
        done = plan.advance(current, self.target, self.config, models)
        self.assertEqual(done.stage, "done")
        self.assertIs(plan.advance(done, self.target, self.config, models), done)

    def test_no_speech_goes_straight_to_publish_then_done(self) -> None:
        self.write_vad(chunks=[])
        current = self.next()
        self.assertEqual((current.stage, current.no_speech), ("publish", True))
        self.assertEqual(current.sources, {"probe": PROBE_IDENTITY, "vad": plan.vad_identity(PCM, MODELS),
                                           "no_speech": True})
        self.publish(current)
        self.assertEqual(self.next().stage, "done")

    def test_changed_final_or_changed_identity_republishes(self) -> None:
        self.write_vad()
        self.write_asr()
        self.write_align()
        self.write_cues()
        self.publish(self.next())
        self.finals["zh"].write_text("edited\n", encoding="utf-8")
        self.assertEqual(self.next().stage, "translate")
        self.finals["zh"].write_bytes(SRT_JA.encode("utf-8"))
        self.assertEqual(self.next().stage, "done")
        changed = replace(self.config, translate=replace(self.config.translate, seed=1))
        self.assertEqual(plan.next_stage(self.target, changed, models).stage, "translate")
        self.write_cues(SRT_JA.replace("こんにちは", "さようなら"))
        self.assertEqual(self.next().stage, "translate")

    def test_stale_upstream_restarts_from_that_stage(self) -> None:
        self.write_vad()
        self.write_asr()
        self.write_align()
        self.write_cues()
        self.write_vad()  # vad.json 重写（内容不变但身份链按文件 SHA 判定；这里 payload 相同故仍当前）
        self.assertEqual(self.next().stage, "translate")
        artifacts.write_artifact(self.work / artifacts.VAD, plan.vad_identity(PCM, MODELS),
                                 {"offset_s": 0, "chunks": [{"start_s": 1.0}]})
        self.assertEqual(self.next().stage, "asr")


class PurityTests(PlanCase):
    def test_repeated_calls_agree_and_leave_inputs_untouched(self) -> None:
        self.write_vad()
        self.write_asr()
        before = (copy.deepcopy(self.target), copy.deepcopy(PROBE_IDENTITY))
        first = self.next()
        second = self.next()
        self.assertEqual(first, second)
        self.assertEqual((self.target, PROBE_IDENTITY), before)
        advanced = plan.advance(first, self.target, self.config, models)
        self.assertEqual(first, second)  # advance 不改写传入的计划
        self.assertEqual(advanced, plan.advance(first, self.target, self.config, models))

    def test_errors_name_the_stage_being_checked(self) -> None:
        self.write_vad()

        def broken(stage: str) -> dict[str, str]:
            if stage == "asr":
                raise ValueError("asr model missing")
            return MODELS

        with self.assertRaises(plan.PlanError) as context:
            plan.next_stage(self.target, self.config, broken)
        self.assertEqual(context.exception.stage, "asr")
        self.assertIn("asr model missing", str(context.exception))
        (self.work / artifacts.VAD).write_text("{not json", encoding="utf-8")
        self.assertEqual(self.next().stage, "vad")  # 损坏的产物不是错误，而是"不当前"


class StageTableTests(unittest.TestCase):
    def test_inputs_outputs_and_identity_keys(self) -> None:
        self.assertEqual(plan.STAGE_INPUTS["align"], (("wav", artifacts.AUDIO_16K), ("asr", artifacts.ASR)))
        self.assertEqual(plan.STAGE_OUTPUT["cues"], artifacts.JA_CUES)
        self.assertEqual([plan.IDENTITY_KEY[s] for s in plan.STAGES], ["vad", "asr", "align", "ja_cues", "translate"])
        with self.assertRaises(ValueError):
            plan.recipe_hash("cues", "w0")
        with self.assertRaises(ValueError):
            plan.model_files("cues", "w0", {})


if __name__ == "__main__":
    unittest.main()
