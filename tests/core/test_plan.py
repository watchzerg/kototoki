"""阶段计划模块（`kototoki.plan`）离线测试：阶段链逐级推进（cues → names → translate）、无语音直达发布、
计划从不返回 `done`（翻译阶段总要经过，`published.json` 不参与判定）、专名表只有注入行进翻译身份、
连续调用结果相同且不改写入参、核对出错时标明阶段。
壳写出的身份与本模块相等由 `tests/core/test_stt_workers.py` 覆盖；整批运行中的调用次数由 `tests/core/test_job.py` 覆盖。
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

from kototoki import artifacts, plan, srt
from kototoki.config import load

MODELS = {"fake-model": "b" * 64}
PCM = hashlib.sha256(b"pcm").hexdigest()
PROBE_IDENTITY = {"video": {"relative_path": "a.mkv", "size": 1, "mtime_ns": 2, "ffprobe": {}},
                  "recipe_hash": "c" * 64, "config": {"audio_language": "jpn"}}
SRT_JA = "1\n00:00:01,000 --> 00:00:02,000\nこんにちは\n"
YAMADA = {"entity_ja": "山田", "kind": "person", "confidence": "high", "zh": "山田",
          "forms": [{"ja": "山田", "zh": "山田"}], "zh_variants": [], "evidence": [1]}
TOKYO = {"entity_ja": "東京", "kind": "place", "confidence": "medium", "zh": "东京",
         "forms": [{"ja": "東京", "zh": "东京"}], "zh_variants": [], "evidence": [1]}


def models(stage: str) -> dict[str, str]:
    return MODELS


def injected_sha256(table: dict) -> str:
    """伪注入行身份：同真实子系统，只取 `confidence: high` 条目的 `forms`（缺 entries 即抛）。"""
    rows = [form for entry in table["entries"] if entry["confidence"] == "high" for form in entry["forms"]]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


class PlanCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        (self.root / "in").mkdir()
        toml = self.root / "kototoki.toml"
        toml.write_text('[paths]\ninput_dir = "in"\nwork_dir = "out"\n', encoding="utf-8")
        self.config = load(toml)
        self.work = self.root / "out" / "in-0123456789ab" / "0123456789ab"
        self.work.mkdir(parents=True)
        self.final = artifacts.final_srt_path(self.root / "in", "a.mkv")
        self.target = plan.Target(self.work, PROBE_IDENTITY, PCM)
        self.tables: list[dict] = []  # 伪 translate.plan 收到的专名表
        # 属性 patch 真实模块：`plan` 经延迟导入取到的是同一模块对象。
        self.enterContext(mock.patch("kototoki.translate.plan", self._translate_plan))
        self.enterContext(mock.patch("kototoki.names.recipes.BUILD_RECIPE_HASH", "d" * 64))

    def _translate_plan(self, work_dir, document, name_table, config):
        self.tables.append(name_table)
        return types.SimpleNamespace(
            work_dir=work_dir, run_dir=work_dir / "translate" / "x", document=document, needs_model=bool(document.cues),
            identity=self.translate_identity(document.source_sha256, name_table, config.translate.seed))

    @staticmethod
    def translate_identity(ja_sha: str, table: dict, seed: int) -> dict:
        return {"ja_srt_sha256": ja_sha, "recipe_hash": "a" * 64, "seed": seed, "names_sha256": injected_sha256(table)}

    # --- 逐级写出产物 ---------------------------------------------------------------------------

    def write_vad(self, chunks: list | None = None) -> None:
        artifacts.write_artifact(self.work / artifacts.VAD, plan.vad_identity(PCM, MODELS),
                                 {"offset_s": 0, "chunks": [{"start_s": 0.0}] if chunks is None else chunks})

    def write_asr(self) -> None:
        vad_sha = artifacts.sha256_file(self.work / artifacts.VAD)
        artifacts.write_artifact(self.work / artifacts.ASR, plan.asr_identity(self.config.engine, PCM, vad_sha, MODELS), {"offset_s": 0})

    def write_align(self) -> None:
        asr_sha = artifacts.sha256_file(self.work / artifacts.ASR)
        artifacts.write_artifact(self.work / artifacts.ALIGN, plan.align_identity(PCM, asr_sha, MODELS), {"offset_s": 0})

    def write_cues(self, text: str = SRT_JA) -> None:
        align_sha = artifacts.sha256_file(self.work / artifacts.ALIGN)
        srt.write_srt(text, self.work / plan.JA_SRT)
        artifacts.write_artifact(self.work / artifacts.JA_CUES, plan.cues_identity(align_sha, self.config),
                                 {"cues": [], "ja_srt_sha256": artifacts.sha256_file(self.work / plan.JA_SRT)})

    def write_names(self, entries: list | None = None) -> None:
        identity = plan.names_identity(artifacts.sha256_file(self.work / plan.JA_SRT), self.config)
        artifacts.write_artifact(self.work / artifacts.NAME_TABLE, identity, {"entries": entries or []})

    def edit_entries(self, entries: list) -> None:
        """用户手改表：只改 entries，不动 identity 块（表仍当前，不回到 names）。"""
        table = artifacts.read_json(self.work / artifacts.NAME_TABLE)
        table["entries"] = entries
        (self.work / artifacts.NAME_TABLE).write_text(artifacts.canonical(table), encoding="utf-8")

    def write_upstream(self, entries: list | None = None) -> None:
        """vad → names 全部当前：下一步是 translate。"""
        self.write_vad()
        self.write_asr()
        self.write_align()
        self.write_cues()
        self.write_names(entries)

    def publish(self, current: plan.Plan) -> None:
        """模拟已发布：字幕写在源文件旁并写 `published.json`；计划不应受此影响。"""
        text = "" if current.no_speech else SRT_JA
        self.final.parent.mkdir(parents=True, exist_ok=True)
        self.final.write_bytes(text.encode("utf-8"))
        artifacts.record_published(self.work, self.final, artifacts.sha256_bytes(text.encode()),
                                   current.sources | {"translate_untranslated_cues": 0}, "translate/x")

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
        self.assertEqual(self.next().stage, "names")
        self.write_names()
        current = self.next()
        self.assertEqual(current.stage, "translate")
        self.assertEqual(current.identities["translate"],
                         self.translate_identity(artifacts.sha256_file(self.work / plan.JA_SRT), {"entries": []},
                                                 self.config.translate.seed))
        self.assertIs(current.translate.identity, current.identities["translate"])
        self.assertTrue(current.translate.needs_model)
        self.assertEqual(set(current.sources),
                         {"probe", "vad", "asr", "align", "ja_cues", "names", "translate", "no_speech"})
        self.publish(current)
        self.assertEqual(self.next().stage, "translate")  # 已发布与否不归计划

    def test_hand_edited_ja_srt_reruns_cues(self) -> None:
        self.write_upstream()
        self.assertEqual(self.next().stage, "translate")
        srt.write_srt(SRT_JA.replace("こんにちは", "さようなら"), self.work / plan.JA_SRT)  # 用户手改 ja.srt
        current = self.next()
        self.assertEqual(current.stage, "cues")
        self.assertNotIn("names", current.identities)

    def test_no_speech_goes_straight_to_publish(self) -> None:
        self.write_vad(chunks=[])
        current = self.next()
        self.assertEqual((current.stage, current.no_speech), ("publish", True))
        self.assertEqual(current.sources, {"probe": PROBE_IDENTITY, "vad": plan.vad_identity(PCM, MODELS),
                                           "no_speech": True})
        self.publish(current)
        self.assertEqual(self.next().stage, "publish")  # published.json 存在也不改变

    def test_stale_upstream_restarts_from_that_stage(self) -> None:
        self.write_upstream()
        self.write_vad()  # vad.json 重写（内容不变但身份链按文件 SHA 判定；这里 payload 相同故仍当前）
        self.assertEqual(self.next().stage, "translate")
        artifacts.write_artifact(self.work / artifacts.VAD, plan.vad_identity(PCM, MODELS),
                                 {"offset_s": 0, "chunks": [{"start_s": 1.0}]})
        self.assertEqual(self.next().stage, "asr")


class NamesChainTests(PlanCase):
    """names 恒在链上：cues → names → translate；表的注入行（high）进翻译身份，其余条目不影响任何身份。"""

    def test_stale_table_stops_at_names(self) -> None:
        self.write_upstream()
        self.assertEqual(self.next().stage, "translate")
        self.write_cues(SRT_JA.replace("こんにちは", "さようなら"))  # ja.srt 变了：表身份不再匹配
        self.assertEqual(self.next().stage, "names")
        self.write_cues()
        changed = replace(self.config, names=replace(self.config.names, seed=1))
        self.assertEqual(plan.next_stage(self.target, changed, models).stage, "names")
        (self.work / artifacts.NAME_TABLE).unlink()
        self.assertEqual(self.next().stage, "names")

    def test_editing_a_high_confidence_entry_changes_the_translate_identity(self) -> None:
        self.write_upstream([YAMADA, TOKYO])
        first = self.next()
        self.publish(first)
        # 改 high 条目的写法：表仍当前（不回到 names），但注入行变了，翻译身份随之变化。
        self.edit_entries([dict(YAMADA, forms=[{"ja": "山田", "zh": "山田君"}]), TOKYO])
        second = self.next()
        self.assertEqual(second.stage, "translate")
        self.assertEqual(second.identities["names"], first.identities["names"])
        self.assertNotEqual(second.identities["translate"]["names_sha256"],
                            first.identities["translate"]["names_sha256"])

    def test_editing_only_medium_or_low_entries_changes_nothing(self) -> None:
        self.write_upstream([YAMADA, TOKYO])
        first = self.next()
        self.publish(first)
        low = dict(TOKYO, entity_ja="大阪", confidence="low", forms=[{"ja": "大阪", "zh": "大阪"}])
        self.edit_entries([YAMADA, dict(TOKYO, forms=[{"ja": "東京", "zh": "东京都"}]), low])
        second = self.next()
        self.assertEqual(second.stage, "translate")  # 注入行不变：翻译身份不变
        self.assertEqual(second.identities, first.identities)


class EmbeddedChainTests(PlanCase):
    """采用内嵌日文字幕的文件（ADR-0024）：`ja.srt` 已由 CPU 阶段写出，计划从 names 起，不经 vad／asr／align／cues。"""

    def setUp(self) -> None:
        super().setUp()
        self.embedded = plan.embedded_identity(PROBE_IDENTITY, 3)
        self.target = plan.Target(self.work, PROBE_IDENTITY, None, self.embedded)
        srt.write_srt(SRT_JA, self.work / plan.JA_SRT)

    def test_chain_starts_at_names_and_never_asks_for_gpu_models(self) -> None:
        def no_models(stage: str) -> dict[str, str]:
            raise AssertionError(f"embedded path must not verify {stage} models")

        current = plan.next_stage(self.target, self.config, no_models)
        self.assertEqual(current.stage, "names")
        self.assertEqual(set(current.identities), {"probe", "ja_embedded", "names"})
        self.write_names()
        current = plan.advance(current, self.target, self.config, no_models)
        self.assertEqual((current.stage, current.no_speech), ("translate", False))
        self.assertEqual(current.sources, {
            "probe": PROBE_IDENTITY, "ja_embedded": self.embedded,
            "names": plan.names_identity(artifacts.sha256_file(self.work / plan.JA_SRT), self.config),
            "translate": current.identities["translate"], "no_speech": False})


if __name__ == "__main__":
    unittest.main()
