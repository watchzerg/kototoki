"""Synthetic source/preparation/delivery contracts; no inference or real data."""

from copy import deepcopy
import json
import unittest

from . import v2_consistency as c
from .v2_source_projection import SCENE_CARD, SOURCE_CONTROL, TERMS, project


class ConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.scene = {"id": "synthetic-scene", "source_language": "ja", "target_language": "zh-Hans",
                      "context": [{"id": "j1", "text": "翼がある。"}, {"id": "j2", "text": "翼を広げる。"},
                                  {"id": "j3", "text": "彼は来るかもしれない。"}, {"id": "j4", "text": "まだ分からない。"}],
                      "translate_ids": ["j1", "j2", "j3", "j4"]}
        self.batches = [{"id": f"batch{i}", "scene_id": self.scene["id"], "target_ids": [uid], "readonly_ids": []}
                        for i, uid in enumerate(self.scene["translate_ids"])]
        self.aliases = ("anon-1111111111111111", "anon-2222222222222222")
        self.good = ["有翅膀。", "展开翅膀。", "他可能会来。", "还不知道。"]
        self.bad = ["有脚。", "张开脚。", "他肯定会来。", "还不知道。"]

    def frame(self, *, mode="terms", rows=None, missing_seed=None, max_items=32):
        if rows is None:
            rows = [{"source": "翼", "translation": "脚", "uncertain": True},
                    {"source": "来る", "translation": "来", "uncertain": False}]
        raw = json.dumps({mode: rows}, ensure_ascii=False)
        preparations = {seed: [{"scene_id": self.scene["id"], "status": "prepared", "raw_response": raw,
                                "reason": None}] for seed in c.SEEDS}
        if missing_seed is not None:
            preparations[missing_seed][0].update(status="preparation_failed", raw_response=None, reason="synthetic failure")
        metadata = {"split": "screening", "quality_inspected": False, "max_items": max_items,
                    "source_manifest_sha256": "1" * 64, "scene_file_sha256": "2" * 64,
                    "source_freeze_sha256": "3" * 64,
                    "preparation_set_sha256": {str(s): c.object_hash(preparations[s]) for s in c.SEEDS}}
        return c.freeze_frame([self.scene], preparations, self.batches, mode=mode, metadata=metadata)

    def deliveries(self, *, missing=False, alternatives=None):
        values = [self.good, self.bad if alternatives is None else alternatives]
        result = {}
        for alias, texts in zip(self.aliases, values, strict=True):
            states = {uid: {"status": "delivered", "text": text, "batch_id": self.batches[i]["id"]}
                      for i, (uid, text) in enumerate(zip(self.scene["translate_ids"], texts, strict=True))}
            if missing and alias == self.aliases[0]:
                states["j1"].update(status="mapping_unjudgeable", text=None)
            result[alias] = {"source_view_sha256": c.object_hash(self.scene), "provenance_sha256": "4" * 64,
                             "cue_states": states}
        return result

    def b_packet(self, frame=None, *, projection=TERMS, missing_proof=False, deliveries=None):
        frame = frame or self.frame()
        prepared = frame["parsed"][str(c.SEEDS[0])][self.scene["id"]]
        mode = frame["inputs"]["mode"]
        protocol = "eligibility-filtered-proposals-v1" if mode == "terms" else "quoted-background-with-uncertainty-v1"
        proofs = {}
        for batch in self.batches:
            window = {**self.scene, "id": batch["id"], "translate_ids": batch["target_ids"],
                      "context": [x for x in self.scene["context"] if x["id"] in batch["target_ids"] + batch["readonly_ids"]]}
            if prepared is None:
                proof = {"status": "missing", "options_sha256": None, "visibility_sha256": None}
            else:
                projected = project(mode, protocol, projection, prepared, window)
                proof = {"status": "verified", "options_sha256": c.object_hash(projected["options"]),
                         "visibility_sha256": c.object_hash(projected["visibility"])}
            proofs[batch["id"]] = proof
        if missing_proof:
            proofs[self.batches[0]["id"]] = {"status": "missing", "options_sha256": None, "visibility_sha256": None}
        return c.build_phase_b(frame, self.scene["id"], c.SEEDS[0], deliveries or self.deliveries(),
                               prepared_alias=self.aliases[1], batches=self.batches, projection=projection,
                               exposure_proofs=proofs)

    def source_quote(self, uid):
        text = next(x["text"] for x in self.scene["context"] if x["id"] == uid)
        return {"id": uid, "quote": text, "start": 0, "end": len(text)}

    def evidence(self, bundle, side, ids, state):
        states = {r["id"]: r for r in bundle["judge_packet"]["sides"][side]}
        return {"state": state, "candidate_evidence": [{"id": uid, "quote": states[uid]["text"]}
                for uid in ids if states[uid]["status"] == "delivered"], "reason_zh": "合成直接证据。"}

    def a_response(self, bundle, *, classifications=None, left_state="no_supported_inconsistency",
                   right_state="consistently_wrong", relation="new_on_R"):
        p = bundle["judge_packet"]
        side_for_good = next(s for s, a in bundle["custody"]["side_aliases"].items() if a == self.aliases[0])
        rows = []
        for anchor in p["anchors"]:
            judgments, groups = [], {}
            for i, occurrence in enumerate(anchor["occurrences"]):
                kind, group = classifications[i] if classifications is not None else ("term", "sense1")
                judgments.append({"occurrence_id": occurrence["occurrence_id"], "kind": kind,
                                  "sense_group": group, "source_evidence": [self.source_quote(occurrence["id"])],
                                  "reason_zh": "合成词义/指称判断，不代表真实字幕证据。"})
                if kind == "term":
                    groups.setdefault(group, []).append(occurrence)
            chains = []
            for group, occurrences in groups.items():
                ids = list(dict.fromkeys(o["id"] for o in occurrences))
                sides = {s: self.evidence(bundle, s, ids, left_state if s == side_for_good else right_state)
                         for s in ("L", "R")}
                if len(ids) == 1:
                    for e in sides.values():
                        e["state"] = "not_comparable"
                    actual_relation = "same"
                elif relation == "new_on_R":
                    actual_relation = "new_on_R" if side_for_good == "L" else "new_on_L"
                else:
                    actual_relation = relation
                chains.append({"sense_group": group, "occurrence_ids": [o["occurrence_id"] for o in occurrences],
                               "sides": sides, "relation": actual_relation,
                               "proposition_zh": "将翅膀误解为脚。", "reason_zh": "合成明确概念变化。"})
            rows.append({"anchor_id": anchor["anchor_id"], "occurrences": judgments, "chains": chains})
        unknown = (p["inventory_state"] == "incomplete" or any(r["status"] != "delivered" for ss in p["sides"].values() for r in ss)
                   or any(o["kind"] == "unknown" for r in rows for o in r["occurrences"]))
        return {"profile": p["profile"], "packet_sha256": bundle["packet_sha256"],
                "status": "unknown" if unknown else "assessed", "rows": rows, "summary_zh": "合成检查。"}

    def b_response(self, bundle, *, uncertainty=False, all_unknown=False):
        p = bundle["judge_packet"]
        treated = p["prepared_side"]
        other = "R" if treated == "L" else "L"
        rows = []
        for record in p["records"]:
            root = "将源文可能性转为无依据确定事实。" if uncertainty else "将翅膀误译为脚。"
            observations = []
            for uid in p["expected_ids"]:
                present = uid in (("j3",) if uncertainty else ("j1", "j2"))
                state = "present" if present else "not_applicable"
                sides = {treated: self.evidence(bundle, treated, [uid], state),
                         other: self.evidence(bundle, other, [uid], "absent" if present else "not_applicable")}
                if all_unknown:
                    for e in sides.values():
                        e.update(state="unknown", candidate_evidence=[])
                observations.append({"ids": [uid], "source_evidence": [self.source_quote(uid)],
                                     "sides": sides, "relation": ("unknown" if all_unknown else
                                         f"new_on_{treated}" if present else "same"),
                                     "proposition_zh": root, "reason_zh": "合成两侧直接对照。"})
            rows.append({"record_id": record["record_id"], "preparation_status": "unknown" if all_unknown else "uncertainty_lost" if uncertainty else "source_conflicting",
                         "source_evidence": [] if all_unknown else [self.source_quote(q["id"]) for q in record["evidence"]],
                         "reason_zh": "合成准备错误；原样引文不证明含义正确。", "root_proposition_zh": root,
                         "link_type": "unknown" if all_unknown else "uncertainty_to_certainty" if uncertainty else "prepared_error",
                         "observations": observations, "pattern": "unknown" if all_unknown else "local_pattern" if uncertainty else "cross_batch_pattern"})
        unknown = (all_unknown or p["preparation_state"] == "missing" or any(e["status"] == "missing" for e in p["exposures"])
                   or any(r["status"] != "delivered" for ss in p["sides"].values() for r in ss))
        return {"profile": p["profile"], "packet_sha256": bundle["packet_sha256"],
                "status": "unknown" if unknown else "assessed", "rows": rows, "summary_zh": "合成传播模式，不是因果证明。"}

    def test_shared_three_seed_union_and_declined_preserved(self):
        frame = self.frame()
        self.assertEqual(frame["coverage"][self.scene["id"]]["proposal_counts"][str(c.SEEDS[0])],
                         {"returned_count": 2, "accepted_count": 1, "declined_count": 1})
        inputs = deepcopy(frame["inputs"])
        inputs["preparations"][str(c.SEEDS[1])][0]["raw_response"] = json.dumps({"terms": [{"source": "。", "translation": "。", "uncertain": False}]})
        inputs["metadata"]["preparation_set_sha256"][str(c.SEEDS[1])] = c.object_hash(inputs["preparations"][str(c.SEEDS[1])])
        changed = c.freeze_frame(**inputs)
        self.assertEqual({a["source"] for a in changed["inventory"][self.scene["id"]]}, {"。", "翼"})
        packets = [c.build_phase_a(changed, self.scene["id"], seed, self.deliveries()) for seed in c.SEEDS]
        self.assertEqual(packets[0]["judge_packet"]["anchors"], packets[2]["judge_packet"]["anchors"])

    def test_explicit_max32_not_legacy16(self):
        texts = "abcdefghijklmnopqrstuvwxyz012345"
        self.scene["context"][0]["text"] = texts
        self.scene["context"][1]["text"] = texts
        rows = [{"source": char, "translation": "合成", "uncertain": False} for char in texts]
        self.assertEqual(len(self.frame(rows=rows)["inventory"][self.scene["id"]]), 32)
        with self.assertRaises(ValueError):
            self.frame(rows=rows, max_items=16)
        with self.assertRaises(ValueError):
            self.frame(max_items=33)

    def test_source_frame_rejects_quality_confirmation_missing_seed_or_changed_raw(self):
        inputs = deepcopy(self.frame()["inputs"])
        for name, value in (("split", "confirmation"), ("quality_inspected", True)):
            bad = deepcopy(inputs)
            bad["metadata"][name] = value
            with self.assertRaises(ValueError):
                c.freeze_frame(**bad)
        del inputs["preparations"][str(c.SEEDS[2])]
        with self.assertRaises(ValueError):
            c.freeze_frame(**inputs)
        changed = self.frame()
        changed["inventory"][self.scene["id"]][0]["occurrences"][0]["start"] = 1
        with self.assertRaises(ValueError):
            c.validate_frame(changed)

    def test_zero_and_missing_preparation_not_successful_coverage(self):
        empty = self.frame(rows=[])
        packet = c.build_phase_a(empty, self.scene["id"], c.SEEDS[0], self.deliveries())
        self.assertEqual(packet["judge_packet"]["anchors"], [])
        self.assertEqual(packet["custody"]["frame_coverage"]["expected_seed_slots"], 3)
        missing = self.frame(missing_seed=c.SEEDS[1])
        packet = c.build_phase_a(missing, self.scene["id"], c.SEEDS[0], self.deliveries())
        response = self.a_response(packet)
        c.validate_response(packet, response)
        response["status"] = "assessed"
        with self.assertRaises(ValueError):
            c.validate_response(packet, response)

    def test_A_hides_preparation_and_custody_identity(self):
        packet = c.build_phase_a(self.frame(), self.scene["id"], c.SEEDS[0], self.deliveries())
        rendered = c.prompt(packet)
        for secret in (self.aliases[0], "20261008", '"prepared_side": "L"', '"translation": "脚"', '"scores"'):
            self.assertNotIn(secret, rendered)
        c.validate_response(packet, self.a_response(packet))

    def test_polysemy_split_into_singletons_has_no_consistency_penalty(self):
        self.scene["context"][0]["text"] = "花を飾る。"
        self.scene["context"][1]["text"] = "話に花が咲く。"
        packet = c.build_phase_a(self.frame(rows=[{"source": "花", "translation": "花", "uncertain": True}]),
                                 self.scene["id"], c.SEEDS[0], self.deliveries())
        response = self.a_response(packet, classifications=[("term", "literal"), ("term", "metaphor")])
        c.validate_response(packet, response)
        response["rows"][0]["chains"][0]["sides"]["L"]["state"] = "consistently_wrong"
        with self.assertRaises(ValueError):
            c.validate_response(packet, response)

    def test_overlapping_substrings_and_unknown_remain_literal_denominator(self):
        self.scene["context"][0]["text"] = "aaaa"
        self.scene["context"][1]["text"] = "aaaa"
        packet = c.build_phase_a(self.frame(rows=[{"source": "aa", "translation": "合成", "uncertain": True}]),
                                 self.scene["id"], c.SEEDS[0], self.deliveries())
        occs = packet["judge_packet"]["anchors"][0]["occurrences"]
        self.assertEqual([o["start"] for o in occs], [0, 1, 2, 0, 1, 2])
        response = self.a_response(packet, classifications=[("substring_not_term", None)] * 5 + [("unknown", None)])
        c.validate_response(packet, response)
        self.assertEqual(response["status"], "unknown")
        response["rows"][0]["occurrences"].pop()
        with self.assertRaises(ValueError):
            c.validate_response(packet, response)

    def test_harmless_alias_and_both_consistently_wrong_are_distinct(self):
        packet = c.build_phase_a(self.frame(), self.scene["id"], c.SEEDS[0], self.deliveries(alternatives=self.good))
        response = self.a_response(packet, left_state="harmless_variant", right_state="harmless_variant", relation="same")
        c.validate_response(packet, response)
        packet = c.build_phase_a(self.frame(), self.scene["id"], c.SEEDS[0], self.deliveries())
        response = self.a_response(packet, left_state="consistently_wrong", right_state="consistently_wrong", relation="same")
        # Acceptance is traceability, not an assertion that this synthetic allegation is true.
        c.validate_response(packet, response)
        self.assertNotIn("score", c.response_schema("A")["properties"])

    def test_unknown_or_missing_C0_cannot_prove_new_error(self):
        packet = c.build_phase_a(self.frame(), self.scene["id"], c.SEEDS[0], self.deliveries(missing=True))
        response = self.a_response(packet)
        with self.assertRaises(ValueError):
            c.validate_response(packet, response)
        good_side = next(s for s, a in packet["custody"]["side_aliases"].items() if a == self.aliases[0])
        chain = response["rows"][0]["chains"][0]
        chain["sides"][good_side]["state"] = "unknown"
        chain["relation"] = "unknown"
        c.validate_response(packet, response)
        chain["relation"] = "new_on_R" if good_side == "L" else "new_on_L"
        with self.assertRaises(ValueError):
            c.validate_response(packet, response)

    def test_wrong_occurrence_source_offset_and_candidate_quote_rejected(self):
        packet = c.build_phase_a(self.frame(), self.scene["id"], c.SEEDS[0], self.deliveries())
        response = self.a_response(packet)
        response["rows"][0]["occurrences"][0]["source_evidence"][0]["start"] = 1
        with self.assertRaises(ValueError):
            c.validate_response(packet, response)
        response = self.a_response(packet)
        response["rows"][0]["chains"][0]["sides"]["L"]["candidate_evidence"][0]["quote"] = "不在提供译文里的文字"
        with self.assertRaises(ValueError):
            c.validate_response(packet, response)

    def test_B_uncertain_terms_exposure_and_cross_batch_pattern(self):
        packet = self.b_packet()
        p = packet["judge_packet"]
        self.assertEqual(p["blindness"], "exposure_partially_unblinds_treatment")
        self.assertEqual(sum(e["uncertain_injected_items"] for e in p["exposures"]), 2)
        c.validate_response(packet, self.b_response(packet))
        changed = self.b_response(packet)
        changed["rows"][0]["observations"][1]["proposition_zh"] = "另一种不相关错误"
        with self.assertRaises(ValueError):
            c.validate_response(packet, changed)

    def test_B_background_uncertainty_into_certainty_and_source_only_control(self):
        rows = [{"text": "他一定会来。", "uncertain": True,
                 "evidence": [{"id": "j3", "quote": "来るかもしれない"}]}]
        frame = self.frame(mode="background", rows=rows)
        packet = self.b_packet(frame, projection=SCENE_CARD)
        self.assertEqual(sum(e["uncertain_injected_items"] for e in packet["judge_packet"]["exposures"]), 4)
        c.validate_response(packet, self.b_response(packet, uncertainty=True))
        source_control = self.b_packet(frame, projection=SOURCE_CONTROL)
        self.assertTrue(all(not e["record_ids"] for e in source_control["judge_packet"]["exposures"]))
        with self.assertRaises(ValueError):
            c.validate_response(source_control, self.b_response(source_control, uncertainty=True))

    def test_B_missing_proof_or_preparation_preserves_unknown(self):
        packet = self.b_packet(missing_proof=True)
        response = self.b_response(packet, all_unknown=True)
        c.validate_response(packet, response)
        response["status"] = "assessed"
        with self.assertRaises(ValueError):
            c.validate_response(packet, response)
        packet = self.b_packet(self.frame(missing_seed=c.SEEDS[0]))
        self.assertEqual(packet["judge_packet"]["records"], [])
        c.validate_response(packet, self.b_response(packet))

    def test_B_unexposed_or_readonly_match_is_not_propagation(self):
        packet = self.b_packet()
        response = self.b_response(packet)
        row = response["rows"][0]
        row["observations"][1]["sides"][packet["judge_packet"]["prepared_side"]]["state"] = "absent"
        row["observations"][1]["relation"] = "same"
        with self.assertRaises(ValueError):
            c.validate_response(packet, response)
        row["pattern"] = "local_pattern"
        c.validate_response(packet, response)
        row["pattern"] = "not_demonstrated"
        with self.assertRaises(ValueError):
            c.validate_response(packet, response)

    def test_B_all_ids_and_direct_absence_evidence_required(self):
        packet = self.b_packet()
        response = self.b_response(packet)
        response["rows"][0]["observations"].pop()
        with self.assertRaises(ValueError):
            c.validate_response(packet, response)
        response = self.b_response(packet)
        other = "R" if packet["judge_packet"]["prepared_side"] == "L" else "L"
        response["rows"][0]["observations"][0]["sides"][other]["candidate_evidence"] = []
        with self.assertRaises(ValueError):
            c.validate_response(packet, response)

    def test_response_identity_schema_duplicate_keys_and_packet_tamper(self):
        packet = c.build_phase_a(self.frame(), self.scene["id"], c.SEEDS[0], self.deliveries())
        for change in (lambda r: r.update(packet_sha256="0" * 64), lambda r: r.update(score=4),
                       lambda r: r.update(profile=c.PROFILES["B"])):
            response = self.a_response(packet)
            change(response)
            with self.assertRaises(ValueError):
                c.validate_response(packet, response)
        with self.assertRaises(ValueError):
            c.validate_response(packet, '{"profile":"x","profile":"y"}')
        packet["judge_packet"]["sides"]["L"][0]["text"] = "被修改"
        with self.assertRaises(ValueError):
            c.validate_packet(packet)
        self.assertNotIn("uniqueItems", json.dumps(c.response_schema("A")))

    def test_json_roundtrip_frame_and_packets_retain_missing_denominators(self):
        frame = json.loads(json.dumps(self.frame(missing_seed=c.SEEDS[1]), ensure_ascii=False))
        c.validate_frame(frame)
        counts = c.coverage_summary(frame)
        self.assertEqual(counts["expected_scene_seed_slots"], 3)
        self.assertEqual(counts["missing_preparation_slots"], 1)
        self.assertEqual(counts["scene_coverage"][self.scene["id"]]["record_counts"][str(c.SEEDS[1])], None)
        packet = c.build_phase_a(frame, self.scene["id"], c.SEEDS[0], self.deliveries())
        c.validate_response(json.loads(json.dumps(packet)), self.a_response(packet))

    def test_projection_proof_and_actual_batch_join_reject_tamper(self):
        frame = self.frame()
        bad = self.deliveries()
        bad[self.aliases[1]]["cue_states"]["j1"]["batch_id"] = "unrelated-batch"
        with self.assertRaises(ValueError):
            self.b_packet(frame, deliveries=bad)
        packet = self.b_packet(missing_proof=True)
        response = self.b_response(packet)
        response["rows"][0]["pattern"] = "local_pattern"
        c.validate_response(packet, response)
        response["rows"][0]["pattern"] = "not_demonstrated"
        with self.assertRaises(ValueError):
            c.validate_response(packet, response)

    def test_original_input_rebind_rejects_coherently_rehashed_omissions(self):
        frame, deliveries = self.frame(), self.deliveries()
        packet = c.build_phase_a(frame, self.scene["id"], c.SEEDS[0], deliveries)
        c.validate_bindings(packet, frame, deliveries)
        for mutate in (lambda p: p["judge_packet"]["anchors"].clear(),
                       lambda p: p["judge_packet"]["sides"]["L"][0].update(text="完整但被替换的合成译文"),
                       lambda p: p["custody"].update(generation_seed=c.SEEDS[1])):
            forged = deepcopy(packet)
            mutate(forged)
            forged["packet_sha256"] = c.object_hash(forged["judge_packet"])
            with self.assertRaises(ValueError):
                c.validate_bindings(forged, frame, deliveries)

    def test_known_source_claim_cannot_quote_only_unrelated_punctuation(self):
        packet = self.b_packet()
        response = self.b_response(packet)
        response["rows"][0]["source_evidence"][0] = {"id": "j1", "quote": "。", "start": 4, "end": 5}
        with self.assertRaises(ValueError):
            c.validate_response(packet, response)

    def test_forged_projection_hash_and_duplicate_anchor_response_rejected(self):
        frame = self.frame()
        proofs = {b["id"]: {"status": "verified", "options_sha256": "0" * 64,
                            "visibility_sha256": "0" * 64} for b in self.batches}
        with self.assertRaises(ValueError):
            c.build_phase_b(frame, self.scene["id"], c.SEEDS[0], self.deliveries(),
                           prepared_alias=self.aliases[1], batches=self.batches, projection=TERMS,
                           exposure_proofs=proofs)
        packet = c.build_phase_a(frame, self.scene["id"], c.SEEDS[0], self.deliveries())
        response = self.a_response(packet)
        response["rows"].append(deepcopy(response["rows"][0]))
        with self.assertRaises(ValueError):
            c.validate_response(packet, response)


if __name__ == "__main__":
    unittest.main()
