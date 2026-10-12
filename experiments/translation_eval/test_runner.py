"""Offline pipeline and arithmetic checks using synthetic subtitle text."""

from copy import deepcopy
import math
from pathlib import Path
import tempfile
import unittest

from .runner import (aggregate, disagree, dump, dump_jsonl, finalize, load_jsonl,
                     order_key, parse, prepare, read_json, select_review,
                     validate_judgment, prepare_synthetic, sha, AUDIT_SEED, P_FLOW_CONTRACT)


def window(wid: str, work: str = "作品甲", category: str = "movie", count: int = 4) -> tuple[dict, dict]:
    ids = [f"{wid}-{number}" for number in range(count)]
    context = [{"id": uid, "text": f"リンゴは{number}個。行かない。"} for number, uid in enumerate(ids)]
    context.insert(0, {"id": f"{wid}-context", "text": "明日の話です。"})
    request = {"id": wid, "context": context, "translate_ids": ids}
    ref = {"id": wid, "work": work, "category": category, "scored_ids": ids,
           "units": [{"id": item["id"], "ja": item["text"], "zh": "忠实译法", "original_zh": "旧译",
                      "score": item["id"] in ids} for item in context]}
    return request, ref


def judgment(packet: dict, semantic: int | None = 2, naturalness: int | None = 2) -> dict:
    return {"window_id": packet["window_id"], "candidate_alias": packet["candidate_alias"],
            "semantic": semantic, "naturalness": naturalness,
            "status": "scored" if semantic is not None else "source_ambiguous",
            "errors": [], "uncertainties": [] if semantic is not None else [
                {"ids": [packet["scored_ids"][0]], "reason_zh": "原文证据不足。"}],
            "summary_zh": "合成数据检查，不代表裁判准确率。"}


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = Path(__file__).resolve().parents[2] / ".local" / "translation-evaluation-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def prepare_run(self, windows: list[tuple[dict, dict]], results: list[dict], ledger: list[dict] | None = None,
                    schedule: list[dict] | None = None) -> Path:
        dump_jsonl(self.root / "inputs.jsonl", [item[0] for item in windows])
        dump_jsonl(self.root / "refs.jsonl", [item[1] for item in windows])
        dump_jsonl(self.root / "results.jsonl", results)
        if ledger is not None:
            dump_jsonl(self.root / "ledger.jsonl", ledger)
        if schedule is not None:
            dump_jsonl(self.root / "schedule.jsonl", schedule)
        output = self.root / "evaluation"
        prepare(self.root / "inputs.jsonl", self.root / "refs.jsonl", {"c1": self.root / "results.jsonl"}, output,
                candidate_ledgers={"c1": self.root / "ledger.jsonl"} if ledger is not None else None,
                candidate_schedules={"c1": self.root / "schedule.jsonl"} if schedule is not None else None)
        return output

    def test_interrupted_run_keeps_attempted_failure_and_unattempted_tail_distinct(self) -> None:
        windows = [window(wid) for wid in ("delivered", "failed", "tail")]
        translations = {uid: "忠实译文" for uid in windows[0][0]["translate_ids"]}
        results = [{"id": "delivered", "translations": translations}, {"id": "failed", "translations": {}}]
        ledger = [{"window_id": "delivered", "status": "delivered", "translations": translations,
                   "elapsed_seconds": 2, "generation_seconds": 2, "attempts": [{}]},
                  {"window_id": "failed", "status": "translation_failed", "reason": "实际请求 OOM。",
                   "translations": {}, "elapsed_seconds": 3, "generation_seconds": 3, "attempts": [{}]}]
        schedule = [{"window_id": "tail", "status": "not_run", "reason": "OOM 后停止，本窗尚未请求。"}]
        output = self.prepare_run(windows, results, ledger, schedule)
        self.assertEqual([row["window_id"] for row in load_jsonl(output / "jobs.jsonl")], ["delivered"])
        packet = read_json(output / "packets/c1/delivered.json")
        dump(output / "primary/c1/delivered.json", judgment(packet, 4))
        finalize(output, True)
        for job in load_jsonl(output / "jobs-review.jsonl"):
            self.assertEqual(job["window_id"], "delivered")
            dump(output / job["response"], judgment(packet, 4))
        finalize(output)
        final = {row["window_id"]: row for row in load_jsonl(output / "final.jsonl")}
        self.assertEqual(len(final), 3)
        self.assertEqual(final["failed"]["status"], "delivery_zero")
        self.assertEqual(final["failed"]["semantic"], 0)
        self.assertEqual(final["tail"]["status"], "not_run")
        self.assertIsNone(final["tail"]["semantic"])
        self.assertIsNone(final["tail"]["naturalness"])
        self.assertIsNone(final["tail"]["generation_seconds"])
        self.assertEqual(load_jsonl(output / "jobs-adjudication.jsonl"), [])
        candidate = read_json(output / "summary.json")["candidates"]["c1"]
        self.assertEqual(candidate["expected_windows"], 3)
        self.assertEqual(candidate["works"]["作品甲"]["expected_scored_ids"], 12)
        self.assertAlmostEqual(candidate["categories"]["movie"]["semantic_lower"], 4 / 3)
        self.assertAlmostEqual(candidate["categories"]["movie"]["semantic_upper"], 8 / 3)
        self.assertEqual(candidate["generation_seconds_measured"], 5)
        self.assertEqual(candidate["generation_timing_known_windows"], 2)
        self.assertEqual(candidate["not_run_windows"], 1)
        self.assertEqual(candidate["delivery_zero_windows"], 1)
        self.assertEqual((output / "originals/c1/ledger.jsonl").read_bytes(), (self.root / "ledger.jsonl").read_bytes())
        self.assertEqual((output / "originals/c1/schedule.jsonl").read_bytes(), (self.root / "schedule.jsonl").read_bytes())
        self.assertIn("未完成部分的已测耗时", (output / "report.md").read_text(encoding="utf-8"))

    def test_capacity_setup_failure_has_full_denominator_and_no_judge_jobs(self) -> None:
        windows = [window("first"), window("second", work="作品乙", category="anime_series")]
        schedule = [{"window_id": item[0]["id"], "status": "setup_failed", "reason": "加载容量预检失败，本窗未请求。"}
                    for item in windows]
        output = self.prepare_run(windows, [], [], schedule)
        self.assertEqual(load_jsonl(output / "jobs.jsonl"), [])
        finalize(output)
        for stage in ("review", "adjudication"):
            self.assertEqual(load_jsonl(output / f"jobs-{stage}.jsonl"), [])
        final = load_jsonl(output / "final.jsonl")
        self.assertEqual(len(final), 2)
        for row in final:
            self.assertEqual(row["status"], "setup_failed")
            self.assertIsNone(row["semantic"])
            self.assertIsNone(row["naturalness"])
        summary = read_json(output / "summary.json")
        candidate = summary["candidates"]["c1"]
        self.assertFalse(summary["comparison_complete"])
        self.assertEqual(candidate["setup_failed_windows"], 2)
        self.assertEqual(candidate["delivery_zero_windows"], 0)
        self.assertIsNone(candidate["generation_seconds_measured"])
        for category in candidate["categories"].values():
            self.assertEqual(category["semantic_lower"], 0)
            self.assertEqual(category["semantic_upper"], 4)
            self.assertEqual(category["expected_windows"], 1)
        corrupted = deepcopy(final)
        corrupted[0]["semantic"] = 0
        with self.assertRaisesRegex(ValueError, "must be null"):
            aggregate(corrupted)

    def test_schedule_validation_rejects_contradictions_and_missing_reasons(self) -> None:
        cases = [({"window_id": "w", "status": "not_run", "reason": ""}, [], None, "requires reason"),
                 ({"window_id": "w", "status": "translation_failed", "reason": "失败"}, [], None, "schedule status"),
                 ({"window_id": "unknown", "status": "not_run", "reason": "未执行"}, [], None, "unknown windows"),
                 ({"window_id": "w", "status": "not_run", "reason": "未执行", "translations": {}}, [], None, "not a translator ledger"),
                 ({"window_id": "w", "status": "not_run", "reason": "未执行"}, [{"id": "w", "translations": {}}], None, "delivered result"),
                 ({"window_id": "w", "status": "not_run", "reason": "未执行"}, [], [{"window_id": "w", "status": "translation_failed"}], "translator ledger")]
        for number, (state, results, ledger, error) in enumerate(cases):
            with self.subTest(number=number):
                self.root = self.root / str(number)
                self.root.mkdir()
                with self.assertRaisesRegex(ValueError, error):
                    self.prepare_run([window("w")], results, ledger, [state])

    def test_partial_ledger_without_schedule_still_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "cover every expected window"):
            self.prepare_run([window("w")], [], [])

    def test_missing_output_without_schedule_retains_delivery_zero(self) -> None:
        output = self.prepare_run([window("w")], [])
        finalize(output)
        self.assertEqual(load_jsonl(output / "final.jsonl")[0]["semantic"], 0)
        self.assertEqual(read_json(output / "summary.json")["candidates"]["c1"]["delivery_zero_windows"], 1)

    def test_packet_four_ids_and_reference_scope(self) -> None:
        request, ref = window("four")
        results = [{"id": "four", "translations": {uid: "没去，苹果有四个。" for uid in request["translate_ids"]}}]
        output = self.prepare_run([(request, ref)], results)
        packet = read_json(output / "packets/c1/four.json")
        self.assertEqual(len(packet["scored_ids"]), 4)
        self.assertEqual(len(packet["context"]), 5)
        self.assertEqual(set(packet["reference"]), set(request["translate_ids"]))
        self.assertNotIn("旧译", str(packet))
        self.assertEqual((output / "originals/c1/results.jsonl").read_bytes(), (self.root / "results.jsonl").read_bytes())
        self.assertIsNotNone(read_json(output / "run.json")["workflow_sha256"])
        with self.assertRaisesRegex(ValueError, "must be empty"):
            prepare(self.root / "inputs.jsonl", self.root / "refs.jsonl", {"c1": self.root / "results.jsonl"}, output)

    def flow_fixture(self) -> tuple[Path, dict]:
        from experiments.translation_flow.srt import read_srt

        request, ref = window("flow")
        # SRT indices deliberately differ from evaluation IDs and row numbers.
        text = "\n\n".join(f"{100 + number * 3}\n00:00:{number:02},000 --> 00:00:{number:02},900\n{cue['text']}"
                            for number, cue in enumerate(request["context"])) + "\n"
        source = self.root / "source.srt"
        source.write_text(text, encoding="utf-8")
        cues = read_srt(source).cues
        dump_jsonl(self.root / "inputs.jsonl", [request])
        dump_jsonl(self.root / "refs.jsonl", [ref, window("unused")[1]])
        dump(self.root / "corpus.json", {"version": "synthetic-flow-subset"})
        dump_jsonl(self.root / "results.jsonl", [{"id": "flow", "delivery_contract": P_FLOW_CONTRACT,
                   "translations": {uid: "逐ID原始译文。" for uid in request["translate_ids"]}}])
        dump_jsonl(self.root / "mapping.jsonl", [{"window_id": "flow", "work": ref["work"], "cues": [
            {"eval_id": item["id"], "source_cue_id": cue.id}
            for item, cue in zip(request["context"], cues)]}])
        raw = self.root / "raw.jsonl"
        dump_jsonl(raw, [{"source_ids": [cue.id for cue in cues], "native_result": "原始输出占位"}])
        contract = {"schema": P_FLOW_CONTRACT, "lane": "P-flow", "delivery_contract": P_FLOW_CONTRACT,
                    "inputs_sha256": sha(self.root / "inputs.jsonl"),
                    "references_sha256": sha(self.root / "refs.jsonl"),
                    "corpus_manifest_sha256": sha(self.root / "corpus.json"),
                    "mapping": {"path": "mapping.jsonl", "sha256": sha(self.root / "mapping.jsonl")},
                    "allowed_source_scope": [{"work": ref["work"], "path": "source.srt", "sha256": sha(source),
                                               "scope": "full-source", "encoding": "utf-8-sig"}],
                    "candidate_artifacts": {"c1": [{"path": "raw.jsonl", "sha256": sha(raw)}]}}
        path = self.root / "flow-contract.json"
        dump(path, contract)
        return path, contract

    def prepare_flow(self, contract: Path | None, lane: str = "P-flow", ledger: Path | None = None) -> Path:
        output = self.root / "evaluation"
        prepare(self.root / "inputs.jsonl", self.root / "refs.jsonl", {"c1": self.root / "results.jsonl"}, output,
                lane=lane, p_flow_contract=contract, corpus_manifest=self.root / "corpus.json",
                candidate_ledgers={"c1": ledger} if ledger else None)
        return output

    def test_flow_keeps_lane_source_identity_raw_artifacts_and_unknown_costs(self) -> None:
        contract, _ = self.flow_fixture()
        output = self.prepare_flow(contract)
        manifest = read_json(output / "run.json")
        self.assertEqual(manifest["lane"], "P-flow")
        self.assertEqual(manifest["reference_windows_used"], 1)
        self.assertEqual(manifest["reference_windows_in_file"], 2)
        self.assertEqual(manifest["p_flow_contract"]["allowed_source_scope"][0]["source_cue_count"], 5)
        expected = load_jsonl(output / "expected.jsonl")[0]
        self.assertEqual(expected["delivery_contract"], P_FLOW_CONTRACT)
        self.assertEqual(expected["lane"], "P-flow")
        self.assertIn("cue-100", expected["source_mapping"]["cues"][0]["source_cue_id"])
        self.assertEqual(expected["raw_flow_artifacts"][0]["sha256"], sha(self.root / "raw.jsonl"))
        self.assertIsNone(expected["generation_seconds"])
        self.assertIsNone(expected["translation_attempts"])
        packet = read_json(output / expected["packet"])
        self.assertEqual(packet["lane"], "P-flow")
        self.assertEqual(set(packet["reference"]), set(expected["scored_ids"]))
        self.assertNotIn("source_mapping", packet)  # Raw identities stay out of blind judge packets.
        self.assertEqual((output / "p-flow-contract.json").read_bytes(), contract.read_bytes())
        finalize(output)
        summary = read_json(output / "summary.json")
        self.assertEqual(summary["lane"], "P-flow")
        self.assertIsNone(summary["candidates"]["c1"]["evaluation_cost"])
        (output / "p-flow-mapping.jsonl").write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "frozen evaluation artifact changed"):
            finalize(output)

    def test_flow_requires_explicit_manifest_and_cannot_be_relabelled_v2(self) -> None:
        contract, _ = self.flow_fixture()
        for supplied, lane, error in ((None, "P-flow", "requires --p-flow-contract"),
                                      (contract, "V2-native-adapted", "requires the P-flow lane")):
            with self.subTest(lane=lane):
                with self.assertRaisesRegex(ValueError, error):
                    self.prepare_flow(supplied, lane)
                self.assertFalse((self.root / "evaluation").exists())

    def test_flow_preflight_rejects_unfrozen_or_missing_provenance(self) -> None:
        path, original = self.flow_fixture()
        changes = [("inputs_sha256", "0" * 64, "inputs freeze"),
                   ("references_sha256", "0" * 64, "references freeze"),
                   ("corpus_manifest_sha256", None, "corpus_manifest freeze"),
                   ("mapping", {"path": "mapping.jsonl", "sha256": "0" * 64}, "hash changed"),
                   ("allowed_source_scope", [], "full-source allowed"),
                   ("candidate_artifacts", {}, "artifact aliases")]
        for key, value, error in changes:
            with self.subTest(key=key):
                contract = deepcopy(original)
                contract[key] = value
                dump(path, contract)
                with self.assertRaisesRegex(ValueError, error):
                    self.prepare_flow(path)
                self.assertFalse((self.root / "evaluation").exists())

    def test_flow_rejects_row_number_or_source_text_mapping_guesses(self) -> None:
        path, contract = self.flow_fixture()
        original = load_jsonl(self.root / "mapping.jsonl")
        for variant in ("source_id", "evaluation_id", "order", "missing_window", "work"):
            with self.subTest(variant=variant):
                rows = deepcopy(original)
                if variant == "source_id":
                    rows[0]["cues"][0]["source_cue_id"] = "1"
                elif variant == "evaluation_id":
                    rows[0]["cues"][0]["eval_id"] = "100"
                elif variant == "order":
                    rows[0]["cues"][0]["source_cue_id"] = rows[0]["cues"][1]["source_cue_id"]
                elif variant == "work":
                    rows[0]["work"] = "unrelated"
                else:
                    rows = []
                dump_jsonl(self.root / "mapping.jsonl", rows)
                contract["mapping"]["sha256"] = sha(self.root / "mapping.jsonl")
                dump(path, contract)
                with self.assertRaisesRegex(ValueError, "P-flow"):
                    self.prepare_flow(path)
                self.assertFalse((self.root / "evaluation").exists())

    def test_flow_rejects_native_groups_and_undeclared_result_contract(self) -> None:
        path, _ = self.flow_fixture()
        original = load_jsonl(self.root / "results.jsonl")
        for grouped in (True, False):
            rows = deepcopy(original)
            if grouped:
                rows[0]["translation_groups"] = []
            else:
                del rows[0]["delivery_contract"]
            dump_jsonl(self.root / "results.jsonl", rows)
            with self.assertRaisesRegex(ValueError, "native groups are unsupported"):
                self.prepare_flow(path)
            self.assertFalse((self.root / "evaluation").exists())

    def test_flow_unattributable_mapping_stays_null_with_full_denominator(self) -> None:
        path, _ = self.flow_fixture()
        ledger = self.root / "ledger.jsonl"
        dump_jsonl(ledger, [{"window_id": "flow", "delivery_contract": P_FLOW_CONTRACT,
                            "status": "mapping_unjudgeable", "reason": "源ID存在但候选归属不可确定。"}])
        output = self.prepare_flow(path, ledger=ledger)
        self.assertEqual(load_jsonl(output / "jobs.jsonl"), [])
        finalize(output)
        final = load_jsonl(output / "final.jsonl")[0]
        self.assertEqual(final["status"], "mapping_unjudgeable")
        self.assertIsNone(final["semantic"])
        self.assertEqual(len(final["scored_ids"]), 4)

    def group_fixture(self) -> tuple[dict, dict, dict, dict]:
        request, ref = window("group", count=3)
        request["context"].insert(2, {"id": "excluded", "text": "関係ない話。"})
        ref["units"].insert(2, {"id": "excluded", "ja": "関係ない話。", "zh": "排除参考", "score": False})
        texts = ["前文。", "一组译文。", "排除中间。", "共享两句译文。"]
        source_runs = [["group-context"], ["group-0"], ["excluded"], ["group-1", "group-2"]]
        mapping, offset = [], 0
        for number, (text, source_ids) in enumerate(zip(texts, source_runs)):
            mapping.append({"group_id": f"g{number}", "source_ids": source_ids, "scored": number % 2 == 1,
                            "text": text, "target_spans": [[offset, offset + len(text)]]})
            offset += len(text)
        groups = [{key: item[key] for key in ("source_ids", "text", "target_spans")}
                  for item in mapping if item["scored"]]
        result = {"id": "group", "translations": {}, "translation_groups": groups}
        ledger = {"window_id": "group", "status": "delivered", "translations": {}, "translation_groups": groups,
                  "native_text": "".join(texts), "mapping_groups": mapping,
                  "source_span_to_target_span": [{key: item[key] for key in ("group_id", "source_ids", "scored", "target_spans")}
                                                 for item in mapping]}
        return request, ref, result, ledger

    def test_grouped_scope_preserves_excluded_middle_and_shared_evidence(self) -> None:
        request, ref, result, ledger = self.group_fixture()
        output = self.prepare_run([(request, ref)], [result], [ledger])
        packet = read_json(output / "packets/c1/group.json")
        self.assertEqual(packet["structural"]["status"], "valid")
        self.assertEqual(packet["translations"], {})
        self.assertEqual([uid for group in packet["translation_groups"] for uid in group["source_ids"]], request["translate_ids"])
        self.assertNotIn("排除中间", str(packet))
        self.assertFalse(packet["raw_v2_validator_applicable"])
        self.assertEqual(validate_judgment(judgment(packet, 4), packet)["semantic"], 4)
        response = judgment(packet)
        response["errors"] = [{"ids": ["group-1"], "type": "mistranslation", "severity": "major",
                               "source_evidence": "リンゴ", "candidate_evidence": "共享两句", "reason_zh": "合成证据。"}]
        validate_judgment(response, packet)
        response["errors"][0]["candidate_evidence"] = "排除中间"
        with self.assertRaisesRegex(ValueError, "candidate evidence"):
            validate_judgment(response, packet)
        response["errors"][0]["candidate_evidence"] = ""
        with self.assertRaisesRegex(ValueError, "empty candidate"):
            validate_judgment(response, packet)
        response["errors"][0]["type"] = "omission"
        validate_judgment(response, packet)
        response["errors"][0]["source_evidence"] = "不存在"
        with self.assertRaisesRegex(ValueError, "source evidence"):
            validate_judgment(response, packet)

    def test_group_provenance_absent_is_unjudgeable(self) -> None:
        request, ref, result, ledger = self.group_fixture()
        del ledger["native_text"]
        output = self.prepare_run([(request, ref)], [result], [ledger])
        self.assertEqual(load_jsonl(output / "expected.jsonl")[0]["structural_status"], "mapping_unjudgeable")
        self.assertEqual(load_jsonl(output / "jobs.jsonl"), [])
        finalize(output)
        self.assertIsNone(load_jsonl(output / "final.jsonl")[0]["semantic"])

    def test_group_native_failure_precedes_absent_mapping_provenance(self) -> None:
        request, ref, result, ledger = self.group_fixture()
        result["translation_groups"] = []
        ledger = {"window_id": "group", "status": "translation_failed", "reason": "原生生成失败。",
                  "translations": {}, "translation_groups": [], "native_attempts": [{}, {}]}
        output = self.prepare_run([(request, ref)], [result], [ledger])
        expected = load_jsonl(output / "expected.jsonl")[0]
        self.assertEqual(expected["structural_status"], "delivery_zero")
        self.assertIsNone(expected["mapping_reason"])
        self.assertEqual(load_jsonl(output / "jobs.jsonl"), [])
        finalize(output)
        final = load_jsonl(output / "final.jsonl")[0]
        self.assertEqual(final["semantic"], 0)
        self.assertIsNone(final["naturalness"])

    def test_explicit_group_mapping_failure_preserves_null(self) -> None:
        request, ref, result, ledger = self.group_fixture()
        ledger["status"] = "mapping_unjudgeable"
        ledger["reason"] = "原生文本已交付，边界无法可靠归属。"
        ledger["mapping_groups"][1]["text"] = "无效分组"
        output = self.prepare_run([(request, ref)], [result], [ledger])
        self.assertEqual(load_jsonl(output / "expected.jsonl")[0]["structural_status"], "mapping_unjudgeable")
        finalize(output)
        self.assertIsNone(load_jsonl(output / "final.jsonl")[0]["semantic"])

    def test_all_mapping_failures_retain_declared_group_contract(self) -> None:
        request, ref = window("failed")
        result = {"id": "failed", "translations": {}, "delivery_contract": "native-scored-groups-v4"}
        ledger = {"window_id": "failed", "translations": {}, "delivery_contract": "native-scored-groups-v4",
                  "status": "mapping_unjudgeable", "reason": "No reliable boundary."}
        output = self.prepare_run([(request, ref)], [result], [ledger])
        self.assertEqual(read_json(output / "run.json")["candidates"]["c1"]["delivery_contract"], "native-scored-groups-v4")
        expected = load_jsonl(output / "expected.jsonl")[0]
        self.assertEqual(expected["delivery_contract"], "native-scored-groups-v4")
        self.assertEqual(expected["structural_status"], "mapping_unjudgeable")
        finalize(output)
        self.assertIsNone(load_jsonl(output / "final.jsonl")[0]["semantic"])

    def test_malformed_group_delivery_is_not_silent_success(self) -> None:
        for mutation in ("text", "overlap", "order", "missing", "copy", "gap"):
            with self.subTest(mutation=mutation):
                request, ref, result, ledger = self.group_fixture()
                if mutation == "text":
                    ledger["mapping_groups"][1]["text"] = "改写"
                elif mutation == "overlap":
                    ledger["mapping_groups"][1]["target_spans"][0][0] = 0
                elif mutation == "order":
                    result["translation_groups"].reverse()
                elif mutation == "missing":
                    result["translation_groups"].clear()
                elif mutation == "copy":
                    result["translations"] = ledger["translations"] = {"group-0": "一组译文。"}
                else:
                    ledger["mapping_groups"].pop(2)
                output = self.prepare_run([(request, ref)], [result], [ledger])
                self.assertEqual(load_jsonl(output / "expected.jsonl")[0]["structural_status"], "delivery_zero")
                self.assertEqual(load_jsonl(output / "jobs.jsonl"), [])
                finalize(output)
                self.assertEqual(load_jsonl(output / "final.jsonl")[0]["semantic"], 0)
                # Each subcase is a separate run, preserving all original artifacts.
                self.root = self.root / mutation
                self.root.mkdir()

    def test_corpus_join_error_is_not_delivery_zero(self) -> None:
        request, ref = window("w")
        ref["units"][1]["ja"] = "別の文章"
        with self.assertRaisesRegex(ValueError, "mapping disagreement"):
            self.prepare_run([(request, ref)], [])

    def test_reference_superset_uses_selected_windows_only(self) -> None:
        first, second = window("selected"), window("unselected")
        dump_jsonl(self.root / "inputs.jsonl", [first[0]])
        dump_jsonl(self.root / "refs.jsonl", [first[1], second[1]])
        dump_jsonl(self.root / "results.jsonl", [])
        output = self.root / "evaluation"
        prepare(self.root / "inputs.jsonl", self.root / "refs.jsonl", {"c1": self.root / "results.jsonl"}, output)
        self.assertEqual([row["window_id"] for row in load_jsonl(output / "expected.jsonl")], ["selected"])
        self.assertFalse((output / "packets/c1/unselected.json").exists())
        self.assertEqual(read_json(output / "run.json")["reference_windows_in_file"], 2)

    def test_synthetic_judge_sanity_suite(self) -> None:
        output = self.root / "synthetic"
        prepare_synthetic(output)
        self.assertEqual(len(load_jsonl(output / "jobs.jsonl")), 3)
        self.assertEqual(len(load_jsonl(output / "expected.jsonl")), 4)
        packet = read_json(output / "packets/c01/equivalent.json")
        self.assertNotIn("semantic_expected", str(packet))
        self.assertEqual(read_json(output / "synthetic-expectations.json")["expectations"]["equivalent"]["semantic_expected"], 4)

    def test_corpus_animation_movie_category_is_preserved_and_grouped(self) -> None:
        request, ref = window("film", category="animation_movie")
        output = self.prepare_run([(request, ref)], [])
        expected = load_jsonl(output / "expected.jsonl")[0]
        self.assertEqual(expected["source_category"], "animation_movie")
        self.assertEqual(expected["category"], "movie")
        finalize(output)
        self.assertIn("movie", read_json(output / "summary.json")["candidates"]["c1"]["categories"])

    def test_all_terminal_paths_and_dispute_history(self) -> None:
        names = ["zero", "partial", "mapping", "judge", "review", "unresolved", "resolved", "agree", "ambiguous"]
        windows = [window(name) for name in names]
        results, ledger = [], []
        for request, _ in windows:
            wid = request["id"]
            trans = {uid: "苹果有三个，明天不去。" for uid in request["translate_ids"]}
            if wid in {"mapping", "zero"}:
                trans = {}
            elif wid == "partial":
                trans.pop(request["translate_ids"][-1])
            results.append({"id": wid, "translations": trans, "elapsed_seconds": 3})
            ledger.append({"window_id": wid, "status": "mapping_unjudgeable" if wid == "mapping" else
                           "translation_failed" if wid == "zero" else "delivered", "translations": trans,
                           "reason": "无法可靠归属原生段落。" if wid == "mapping" else "合成终态。",
                           "generation_seconds": 2, "auxiliary_seconds": 1, "elapsed_seconds": 3,
                           "attempts": [{}, {}]})
        output = self.prepare_run(windows, results, ledger)
        jobs = load_jsonl(output / "jobs.jsonl")
        self.assertEqual(len(jobs), 7)
        packets = {name: read_json(output / f"packets/c1/{name}.json") for name in names}
        for name in names:
            if name not in {"zero", "mapping", "judge"}:
                value = judgment(packets[name], None, None) if name == "ambiguous" else judgment(packets[name])
                dump(output / f"primary/c1/{name}.json", value)
        finalize(output, True)
        selected = read_json(output / "review-selection.json")["selected_ids"]
        self.assertTrue(set(names) - {"zero"} <= set(selected))
        for name in names:
            if name not in {"zero", "mapping", "judge", "review"}:
                value = judgment(packets[name], None, None) if name == "ambiguous" else judgment(packets[name])
                if name in {"unresolved", "resolved"}:
                    value["semantic"] = 3
                dump(output / f"review/c1/{name}.json", value)
        finalize(output)
        self.assertEqual(len(load_jsonl(output / "jobs-adjudication.jsonl")), 2)
        for name in ("unresolved", "resolved"):
            value = judgment(packets[name], 4)
            value.update(resolved=name == "resolved", resolution_zh="有明确证据。" if name == "resolved" else "证据不足。")
            dump(output / f"adjudication/c1/{name}.json", value)
        finalize(output)
        final = {row["window_id"]: row for row in load_jsonl(output / "final.jsonl")}
        expected = {"zero": "delivery_zero", "partial": "scored", "mapping": "mapping_unjudgeable",
                    "judge": "judge_failed", "review": "review_failed", "unresolved": "unresolved",
                    "resolved": "scored", "agree": "scored", "ambiguous": "source_ambiguous"}
        self.assertEqual({key: row["status"] for key, row in final.items()}, expected)
        self.assertEqual(final["zero"]["semantic"], 0)
        self.assertIsNone(final["review"]["semantic"])
        self.assertEqual(final["review"]["provisional_primary"]["semantic"], 2)
        self.assertEqual(final["resolved"]["semantic"], 4)
        self.assertTrue(final["unresolved"]["reviewed"])
        self.assertTrue(final["resolved"]["initial_disagreement"])
        self.assertIn("primary", final["resolved"])
        summary = read_json(output / "summary.json")["candidates"]["c1"]
        self.assertEqual(summary["expected_windows"], 9)
        self.assertEqual(summary["semantic_known_windows"], 4)
        self.assertEqual(summary["generation_seconds_measured"], 18)
        self.assertEqual(summary["auxiliary_seconds_measured"], 9)
        self.assertEqual(summary["translation_retries_measured"], 9)
        self.assertAlmostEqual(summary["works"]["作品甲"]["semantic_lower"], 8 / 9)
        self.assertAlmostEqual(summary["works"]["作品甲"]["semantic_upper"], 28 / 9)

    def test_freeze_detects_packet_and_primary_changes(self) -> None:
        request, ref = window("w")
        output = self.prepare_run([(request, ref)], [{"id": "w", "translations": {uid: "译文" for uid in request["translate_ids"]}}])
        packet_path = output / "packets/c1/w.json"
        packet = read_json(packet_path)
        dump(output / "primary/c1/w.json", judgment(packet, 3))
        finalize(output, True)
        dump(output / "primary/c1/w.json", judgment(packet, 2))
        with self.assertRaisesRegex(ValueError, "selection changed"):
            finalize(output)
        packet["translations"][packet["scored_ids"][0]] = "改变后的译文"
        dump(packet_path, packet)
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            finalize(output)

    def test_schema_traceability_and_missing_content(self) -> None:
        request, ref = window("w")
        output = self.prepare_run([(request, ref)], [{"id": "w", "translations": {request["translate_ids"][0]: "苹果为零个。"}}])
        packet = read_json(output / "packets/c1/w.json")
        value = judgment(packet)
        uid = packet["scored_ids"][0]
        value["errors"] = [{"ids": [uid], "type": "mistranslation", "severity": "major",
                           "source_evidence": "行かない", "candidate_evidence": "苹果为零个", "reason_zh": "否定内容缺失。"}]
        self.assertEqual(validate_judgment(value, packet), value)
        for field, replacement in [("semantic", True), ("semantic", 4), ("naturalness", 3),
                                   ("candidate_alias", "wrong"), ("uncertainties", {}), ("summary_zh", "")]:
            broken = deepcopy(value)
            broken[field] = replacement
            with self.subTest(field=field, replacement=replacement), self.assertRaises(ValueError):
                validate_judgment(broken, packet)
        for field, replacement in [("ids", ["unknown"]), ("source_evidence", "存在しない"),
                                   ("candidate_evidence", "编造译文"), ("candidate_evidence", "")]:
            broken = deepcopy(value)
            broken["errors"][0][field] = replacement
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_judgment(broken, packet)
        missing_uid = packet["scored_ids"][1]
        value["errors"] = [{"ids": [missing_uid], "type": "omission", "severity": "major",
                           "source_evidence": "リンゴ", "candidate_evidence": "", "reason_zh": "缺少译文。"}]
        validate_judgment(value, packet)
        value["errors"][0]["ids"] = [uid]
        value["errors"][0]["source_evidence"] = "行かない"
        value["errors"][0]["reason_zh"] = "已交付苹果数量，但否定动作含义未体现。"
        validate_judgment(value, packet)
        for error_type in ("mistranslation", "addition", "terminology", "fluency", "mapping"):
            broken = deepcopy(value)
            broken["errors"][0]["type"] = error_type
            with self.subTest(error_type=error_type), self.assertRaisesRegex(ValueError, "empty candidate"):
                validate_judgment(broken, packet)
        broken = deepcopy(value)
        broken["errors"][0]["reason_zh"] = ""
        with self.assertRaisesRegex(ValueError, "reason_zh"):
            validate_judgment(broken, packet)
        for text in ['{"semantic":1,"semantic":2}', '{"semantic":NaN}']:
            with self.assertRaises(ValueError):
                parse(text)

    def test_audit_per_work_and_risk_union(self) -> None:
        rows = [{"candidate_alias": alias, "window_id": f"{work}-{i}", "work": work,
                 "structural_status": "valid"} for alias in ("c1", "c2")
                for work, count in (("large", 11), ("small", 2)) for i in range(count)]
        primary = {(row["candidate_alias"], row["window_id"]): {"semantic": 4, "naturalness": 2,
                   "status": "scored", "uncertainties": [], "errors": []} for row in rows}
        risk = "large-9"
        primary["c2", risk]["semantic"] = 2
        selection = select_review(rows, primary)
        audit = {wid for work, count in (("large", 11), ("small", 2)) for wid in
                 sorted([f"{work}-{i}" for i in range(count)], key=lambda wid: order_key(wid, AUDIT_SEED))[:math.ceil(.2 * count)]}
        self.assertEqual(set(selection["selected_ids"]), audit | {risk})
        self.assertEqual(selection, select_review(list(reversed(rows)), primary))

    def test_same_counts_different_major_claims_disagree(self) -> None:
        first = {"semantic": 2, "naturalness": 2, "status": "scored", "errors": [
            {"ids": ["a"], "type": "mistranslation", "severity": "major", "source_evidence": "甲", "candidate_evidence": "乙"}]}
        second = deepcopy(first)
        second["errors"][0]["ids"] = ["b"]
        self.assertTrue(disagree(first, second))

    def test_absent_delivery_cannot_invent_naturalness(self) -> None:
        request, ref = window("missing")
        output = self.prepare_run([(request, ref)], [])
        packet = read_json(output / "packets/c1/missing.json")
        validate_judgment(judgment(packet, 0, None), packet)
        for semantic, naturalness in ((0, 2), (2, None), (None, None)):
            with self.subTest(semantic=semantic, naturalness=naturalness), self.assertRaises(ValueError):
                validate_judgment(judgment(packet, semantic, naturalness), packet)


class ArithmeticTests(unittest.TestCase):
    def row(self, wid: str, work: str, semantic: int | None, category: str = "movie", naturalness: int | None = None) -> dict:
        return {"window_id": wid, "candidate_alias": "c1", "work": work, "category": category,
                "semantic": semantic, "naturalness": naturalness, "scored_ids": [wid + "-a"],
                "status": "scored" if semantic is not None else "unresolved", "errors": [],
                "structural_status": "valid", "missing_ids": [], "reviewed": False,
                "initial_disagreement": False, "elapsed_seconds": None}

    def test_hierarchical_full_denominators(self) -> None:
        rows = [self.row("a1", "long", 4, naturalness=2), self.row("a2", "long", 0),
                self.row("a3", "long", None), self.row("b", "short", 2),
                self.row("c", "series", 3, "anime_series", 1)]
        summary = aggregate(rows)
        candidate = summary["candidates"]["c1"]
        movies = candidate["categories"]["movie"]
        self.assertAlmostEqual(movies["semantic_lower"], (4 / 3 + 2) / 2)
        self.assertAlmostEqual(movies["semantic_upper"], (8 / 3 + 2) / 2)
        self.assertEqual(movies["naturalness_mean"], 2)
        self.assertEqual(movies["naturalness_omitted_works"], ["short"])
        self.assertEqual(candidate["categories"]["anime_series"]["semantic_lower"], 3)
        self.assertFalse(summary["comparison_complete"])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            aggregate(rows + [rows[0]])
        other = deepcopy(rows[:-1])
        for row in other:
            row["candidate_alias"] = "c2"
        with self.assertRaisesRegex(ValueError, "scopes differ"):
            aggregate(rows + other)

    def test_native_and_mapping_retries_are_both_counted(self) -> None:
        row = self.row("w", "film", 3)
        row.update(native_phase_present=True, native_attempts=[{}, {}], translation_attempts=[{}, {}],
                   generation_seconds=2, auxiliary_seconds=1)
        candidate = aggregate([row])["candidates"]["c1"]
        self.assertEqual(candidate["translation_retries_measured"], 2)
        self.assertEqual(candidate["generation_retries_measured"], 1)
        self.assertEqual(candidate["mapping_retries_measured"], 1)
        self.assertEqual(candidate["translation_attempts_known_windows"], 1)
        row["native_attempts"] = None
        row["generation_seconds"] = None
        candidate = aggregate([row])["candidates"]["c1"]
        self.assertIsNone(candidate["generation_retries_measured"])
        self.assertIsNone(candidate["generation_seconds_measured"])
        self.assertEqual(candidate["translation_attempts_known_windows"], 0)


if __name__ == "__main__":
    unittest.main()
