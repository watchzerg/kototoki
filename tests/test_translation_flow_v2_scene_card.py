"""Offline source scope, provenance and uncertainty tests for scene cards."""

from copy import deepcopy
import hashlib
import json
import unittest

from experiments.translation_demo import adapters
from experiments.translation_flow.v2_scene_card import PROTOCOL, project_scene_card, render_card, validate_projection
from experiments.translation_flow.v2_source_preparation import parse_response


def fixture():
    texts = ["もし雨なら中止です。", "今日は晴れです。", "準備します。", "どうしますか。",
             "明日を待ちます。", "まだ決めていません。", "風が強いです。", "中止とは限りません。"]
    source = [{"id": f"scene-a-{number}", "text": text} for number, text in enumerate(texts)]
    scene = {"id": "scene-a", "source_language": "ja", "target_language": "zh-Hans",
             "context": source, "translate_ids": [cue["id"] for cue in source]}
    raw = {"background": [
        {"text": "如果下雨则取消，但不一定取消。", "uncertain": True,
         "evidence": [{"id": "scene-a-0", "quote": "もし雨なら中止"},
                      {"id": "scene-a-7", "quote": "中止とは限りません"}]},
        {"text": "今天是晴天。", "uncertain": False,
         "evidence": [{"id": "scene-a-1", "quote": "今日は晴れです。"}]}]}
    prepared = parse_response(json.dumps(raw, ensure_ascii=False), "background", scene)
    window = {"id": "batch-a", "source_language": "ja", "target_language": "zh-Hans",
              "context": deepcopy(source[2:6]), "translate_ids": ["scene-a-3", "scene-a-4"]}
    return prepared, window, scene


class SceneCardTests(unittest.TestCase):
    def test_far_support_union_full_source_order_and_targets_remain_contiguous(self):
        prepared, window, _ = fixture()
        projection = project_scene_card(prepared, window)
        actual = projection["window"]
        adapters.validate_window(actual)
        self.assertEqual(set(actual), {"id", "source_language", "target_language", "context", "translate_ids"})
        self.assertEqual(actual["translate_ids"], window["translate_ids"])
        self.assertEqual([cue["id"] for cue in actual["context"]],
                         [f"scene-a-{index}" for index in (0, 1, 2, 3, 4, 5, 7)])
        self.assertEqual(actual["context"][0]["text"], "もし雨なら中止です。")
        card = projection["scene_card"]
        self.assertEqual(card["protocol"], PROTOCOL)
        self.assertEqual(card["original_local_context_ids"], [f"scene-a-{index}" for index in (2, 3, 4, 5)])
        self.assertEqual(card["new_readonly_ids"], ["scene-a-0", "scene-a-1", "scene-a-7"])
        self.assertEqual(card["broader_before_ids"], ["scene-a-0", "scene-a-1"])
        self.assertEqual(card["broader_after_ids"], ["scene-a-7"])
        self.assertEqual(card["background"], prepared["records"])

    def test_uncertain_records_preserve_quotes_flags_and_prompt_ownership_instruction(self):
        prepared, window, _ = fixture()
        card = project_scene_card(prepared, window)["scene_card"]
        prompt = render_card(card)
        self.assertTrue(card["background"][0]["uncertain"])
        self.assertFalse(card["background"][1]["uncertain"])
        self.assertIn("不把不确定背景当成确定事实", prompt)
        self.assertIn("信息揭示顺序", prompt)
        self.assertIn("不能把未来证据的事实提前写入当前目标", prompt)
        self.assertIn("未展示完整场景原文", prompt)
        self.assertIn("引用仅证明原文出处", prompt)
        data = json.loads(prompt.split("\n")[-1])
        self.assertEqual(data["translate_ids"], card["translate_ids"])
        self.assertEqual(data["supporting_source_context"], card["supporting_source_context"])
        for name in ("protocol", "full_scene_source_hash", "source_preparation_record_sha256", "cost_attribution", "semantic_quality_checked"):
            self.assertNotIn(name, data)
        self.assertEqual(data["background"][0]["evidence"], prepared["records"][0]["evidence"])

    def test_hashes_bind_full_scene_and_entire_checked_preparation(self):
        prepared, window, _ = fixture()
        card = project_scene_card(prepared, window)["scene_card"]
        def digest(value):
            return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                             separators=(",", ":")).encode("utf-8")).hexdigest()
        self.assertEqual(card["full_scene_source_hash"], digest(prepared["source_context"]))
        self.assertEqual(card["source_preparation_record_sha256"], digest(prepared))
        self.assertEqual(card["cost_attribution"], "shared preparation counted once; augmented batch prompt counted by main runtime")
        self.assertFalse(card["semantic_quality_checked"])

    def test_original_inputs_and_provenance_remain_independent_of_outputs(self):
        prepared, window, _ = fixture()
        originals = deepcopy((prepared, window))
        projection = project_scene_card(prepared, window)
        self.assertEqual((prepared, window), originals)
        projection["window"]["context"][0]["text"] = "changed"
        projection["scene_card"]["background"][0]["evidence"][0]["quote"] = "changed"
        projection["scene_card"]["translate_ids"].append("changed")
        self.assertEqual((prepared, window), originals)

    def test_invalid_quote_evidence_provenance_and_duplicate_records_rejected(self):
        mutations = {
            "quote": lambda p: p["records"][0]["evidence"][0].update(quote="雨なので中止"),
            "foreign": lambda p: p["records"][0]["evidence"][0].update(id="other-scene-0"),
            "missing": lambda p: p["records"][0].update(evidence=[]),
            "duplicate evidence": lambda p: p["records"][0]["evidence"].append(deepcopy(p["records"][0]["evidence"][0])),
            "evidence order": lambda p: p["records"][0]["evidence"].reverse(),
            "derived ids": lambda p: p["records"][0].update(evidence_ids=["scene-a-7"]),
            "origin": lambda p: p["records"][0].update(origin="reference"),
            "duplicate records": lambda p: p["records"].append(deepcopy(p["records"][0])),
            "uncertainty type": lambda p: p["records"][0].update(uncertain="true"),
            "unknown reference": lambda p: p["records"][0].update(reference_translation="forbidden"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                prepared, window, _ = fixture()
                mutate(prepared)
                with self.assertRaises(ValueError):
                    project_scene_card(prepared, window)

    def test_modified_foreign_duplicate_or_reordered_local_context_rejected(self):
        mutations = (
            lambda w: w["context"][0].update(text="別の発言"),
            lambda w: w["context"][0].update(id="other-scene-0"),
            lambda w: w["context"].append(deepcopy(w["context"][0])),
            lambda w: w["context"].reverse(),
            lambda w: w.update(reference="forbidden"),
        )
        for number, mutate in enumerate(mutations):
            with self.subTest(number=number):
                prepared, window, _ = fixture()
                mutate(window)
                with self.assertRaises(ValueError):
                    project_scene_card(prepared, window)

    def test_targets_must_be_contiguous_in_frozen_scene_even_if_adjacent_in_local_window(self):
        prepared, window, _ = fixture()
        window["context"] = [window["context"][0], window["context"][2]]
        window["translate_ids"] = ["scene-a-2", "scene-a-4"]
        with self.assertRaisesRegex(ValueError, "full frozen scene"):
            project_scene_card(prepared, window)
        prepared, window, _ = fixture()
        window["translate_ids"].reverse()
        with self.assertRaisesRegex(ValueError, "contiguous"):
            project_scene_card(prepared, window)

    def test_empty_background_adds_nothing_and_never_invents_scopes_or_reference(self):
        _, window, scene = fixture()
        prepared = parse_response('{"background":[]}', "background", scene)
        projection = project_scene_card(prepared, window)
        self.assertEqual(projection["window"], window)
        card = projection["scene_card"]
        self.assertEqual(card["new_readonly_ids"], [])
        self.assertEqual(card["supporting_source_context"], [])
        self.assertEqual(card["background"], [])
        render_card(card)
        for field in ("reference", "judge_feedback", "other_scene", "scope"):
            with self.subTest(field=field):
                bad = deepcopy(prepared)
                bad[field] = "forbidden"
                with self.assertRaises(ValueError):
                    project_scene_card(bad, window)

    def test_render_rejects_hidden_fields_added_source_and_modified_quotes(self):
        prepared, window, _ = fixture()
        card = project_scene_card(prepared, window)["scene_card"]
        mutations = (
            lambda c: c.update(reference="forbidden"),
            lambda c: c["supporting_source_context"][0].update(text="変更"),
            lambda c: c["background"][0]["evidence"][0].update(quote="不一致"),
            lambda c: c["broader_after_ids"].clear(),
            lambda c: c["actual_context_ids"].append("unrequested"),
            lambda c: c.update(full_scene_source_hash="invalid"),
        )
        for number, mutate in enumerate(mutations):
            with self.subTest(number=number):
                bad = deepcopy(card)
                mutate(bad)
                with self.assertRaises(ValueError):
                    render_card(bad)

    def test_full_scene_visibility_when_local_or_support_union_covers_every_cue(self):
        prepared, window, scene = fixture()
        full = {**window, "context": deepcopy(scene["context"])}
        card = project_scene_card(prepared, full)["scene_card"]
        self.assertTrue(card["full_scene_visible"])
        self.assertIn("已覆盖完整场景原文", render_card(card))
        self.assertNotIn("未展示完整场景原文", render_card(card))
        projection = project_scene_card(prepared, window)
        card = projection["scene_card"]
        self.assertEqual(card["full_scene_visible"], len(card["actual_context_ids"]) == len(scene["context"]))
        bad = deepcopy(card)
        bad["full_scene_visible"] = not bad["full_scene_visible"]
        with self.assertRaisesRegex(ValueError, "full source visibility"):
            render_card(bad)

    def test_projection_validation_binds_original_hashes_context_and_json_types(self):
        prepared, window, _ = fixture()
        projection = project_scene_card(prepared, window)
        self.assertIsNone(validate_projection(projection, prepared, window))
        mutations = (
            lambda p: p["scene_card"].update(full_scene_source_hash="a" * 64),
            lambda p: p["scene_card"].update(source_preparation_record_sha256="b" * 64),
            lambda p: p["scene_card"]["new_readonly_ids"].append("other-scene-0"),
            lambda p: p["window"]["context"][0].update(text="変更"),
            lambda p: p["scene_card"]["background"][0]["evidence"][0].update(quote="変更"),
            lambda p: p["scene_card"]["background"][0].update(uncertain=1),
            lambda p: p["scene_card"].update(semantic_quality_checked=0),
        )
        for number, mutate in enumerate(mutations):
            with self.subTest(number=number):
                bad = deepcopy(projection)
                mutate(bad)
                with self.assertRaisesRegex(ValueError, "original frozen"):
                    validate_projection(bad, prepared, window)


if __name__ == "__main__":
    unittest.main()
