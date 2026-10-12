"""Synthetic-only risk reconciliation tests, no inference or real subtitle reads."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from . import v2_risk_reconciliation as r


class RiskReconciliationTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[2] / ".local/translation-evaluation-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.protocol = self.write("protocol.json", {"version": r.VERSION,
            "state": "frozen_before_candidate_quality", "new_calls_currently_authorized": False})
        self.seals = []
        for seed in r.SEEDS:
            for alias in ("A", "B"):
                prefix = f"{seed}-{alias}"
                artifact = self.write(f"{prefix}/final.json", {"synthetic": True})
                seal = self.write(f"{prefix}/seal.json", {
                    "version": "hy30-flow-v2-evaluation-finalization-v1",
                    "state": "required_fresh_judgments_completed",
                    "accepted_raw_canonical_integrity_verified": True,
                    "files": [{"path": "final.json", "sha256": artifact["sha256"]}]})
                self.seals.append({**seal, "seed": seed, "alias": alias})
        self.pairs = [self.pair(seed) for seed in r.SEEDS]
        self.packet = self.build()

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def pair(self, seed, window="window", cue="j1"):
        claim = {"claim_id": "local-root", "ids": [cue], "severity": "major",
                 "source_evidence": "行かない", "candidate_evidence": "去",
                 "reason_zh": "合成否定反转。"}
        return {"seed": seed, "window_id": window, "scene_id": "synthetic-scene",
                "scored_ids": [cue], "source_events": [{"id": "j1", "text": "私は行かない。"},
                                                         {"id": "j2", "text": "明日も行かない。"}],
                "sides": {"A": {"translations": {cue: "我不去。"}, "claims": []},
                          "B": {"translations": {cue: "我去。"}, "claims": [claim]}}}

    def build(self, **options):
        defaults = {"protocol_pointer": self.protocol, "final_seal_pointers": self.seals,
                    "protocol_reviewed_safe": True}
        defaults.update(options)
        return r.build_packet(self.pairs, **defaults)

    def response(self, packet=None):
        packet = packet or self.packet
        occurrences = []
        for index, pair in enumerate(packet["judge_packet"]["pairs"]):
            evidence, claims = {}, []
            for side, data in pair["sides"].items():
                present = bool(data["claims"])
                cue = pair["scored_ids"][0]
                evidence[side] = {"state": "present" if present else "absent",
                    "severity": "major" if present else "none",
                    "quotes": [{"id": cue, "quote": data["translations"][cue]}],
                    "reason_zh": "合成证据直接支持该错误存在／不存在。"}
                claims.extend(claim["claim_id"] for claim in data["claims"])
            cue = pair["scored_ids"][0]
            source = next(item["text"] for item in pair["context"] if item["id"] == cue)
            occurrences.append({"occurrence_id": f"o{index}", "pair_id": pair["pair_id"],
                "source_event_ids": [cue], "source_quotes": [{"id": cue, "quote": source}],
                "side_evidence": evidence, "claim_ids": claims})
        return {"version": r.VERSION, "packet_sha256": packet["packet_sha256"],
                "roots": [{"identity_id": "r1", "proposition_zh": "合成未去事实。",
                           "cause_zh": "合成否定反转。", "occurrences": occurrences, "source_links": []}],
                "summary_zh": "仅为合成管道检查。"}

    def passes(self, responses):
        records, pointers = [], {}
        for index, response in enumerate(responses):
            invocation = f"fresh-{index}"
            records.append({"phase": ("identity_match", "independent_review", "adjudication", "extra")[index],
                "response": response, "fresh_invocation_id": invocation,
                "model": "gpt-6.1-sol", "effort": "high"})
            pointers[invocation] = self.write(f"accepted-{index}.json", response)
        return records, pointers

    def freeze(self, responses, name="registry.json"):
        passes, pointers = self.passes(responses)
        return r.freeze_registry(self.packet, passes, pointers=pointers, output=self.root / name)

    def test_anonymous_allowlist_hides_scores_references_roles_and_real_seeds(self):
        self.pairs[0]["sides"]["A"].update(semantic=4, reference="private-reference", family="C0")
        self.pairs[0]["sides"]["B"]["claims"][0]["reason_zh"] = "private-reference private-family private-score"
        packet = self.build()
        rendered = r.prompt(packet)
        for private in ("private-reference", "private-family", "private-score", '"baseline_alias"',
                        '"candidate_alias"', '"family"', "20261008"):
            self.assertNotIn(private, rendered)
        self.assertEqual(self.packet["judge_packet"], packet["judge_packet"])
        self.assertIn("S1", rendered)

    def test_valid_three_seed_new_root_is_counted_once(self):
        response = self.response()
        self.assertEqual(r.validate_response(response, self.packet), response)
        registry = self.freeze([response, deepcopy(response)])
        summary = r.aggregate_safe(registry)
        self.assertEqual(summary["root_count"], 1)
        self.assertEqual(summary["transitions"]["new"], {
            "root_count": 1, "window_presence": 1, "seed_presence": 3, "paired_occurrence_count": 3})
        self.assertNotIn("行かない", json.dumps(summary, ensure_ascii=False))
        with self.assertRaises(FileExistsError):
            self.freeze([response, deepcopy(response)])

    def test_required_claim_coverage_and_exact_ja_both_zh(self):
        mutations = []
        missing = self.response(); missing["roots"][0]["occurrences"].pop(); mutations.append(missing)
        ja = self.response(); ja["roots"][0]["occurrences"][0]["source_quotes"][0]["quote"] = "行く"; mutations.append(ja)
        zh = self.response(); zh["roots"][0]["occurrences"][0]["side_evidence"]["L"]["quotes"] = []; mutations.append(zh)
        other = self.response(); other["roots"][0]["occurrences"][0]["side_evidence"]["R"]["quotes"][0]["quote"] = "不来"; mutations.append(other)
        for response in mutations:
            with self.subTest(response=response):
                with self.assertRaises(ValueError): r.validate_response(response, self.packet)

    def test_absent_baseline_claim_alone_is_unknown_not_new(self):
        response = self.response()
        for occurrence in response["roots"][0]["occurrences"]:
            for evidence in occurrence["side_evidence"].values():
                if evidence["state"] == "absent":
                    evidence.update(state="unknown", severity="unknown", quotes=[],
                                    reason_zh="没有直接证据，保留未知。")
        registry = self.freeze([response, deepcopy(response)])
        self.assertEqual(r.aggregate_safe(registry)["transitions"]["unresolved"]["root_count"], 1)
        self.assertEqual(r.aggregate_safe(registry)["transitions"]["new"]["root_count"], 0)

    def test_fails_before_all_six_seals_and_safe_protocol(self):
        for options in ({"protocol_reviewed_safe": False}, {"final_seal_pointers": self.seals[:-1]},
                        {"seeds": (1, 2)}):
            with self.assertRaises(ValueError): self.build(**options)
        Path(self.seals[0]["path"]).with_name("final.json").write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError): self.build()

    def test_equal_window_grid_and_frozen_scene_required(self):
        self.pairs.pop()
        with self.assertRaises(ValueError): self.build()
        self.pairs = [self.pair(seed) for seed in r.SEEDS]
        self.pairs[1]["source_events"][0]["text"] = "違う。"
        with self.assertRaises(ValueError): self.build()

    def test_severity_worsening_uses_accepted_minor_baseline(self):
        for pair in self.pairs:
            pair["sides"]["A"]["claims"] = [{"claim_id": "minor-root", "ids": ["j1"],
                "severity": "minor", "source_evidence": "行かない", "candidate_evidence": "不去",
                "reason_zh": "合成 minor。"}]
        self.packet = self.build()
        response = self.response()
        for occurrence in response["roots"][0]["occurrences"]:
            aliases = self.packet["custody"]["pairs"][occurrence["pair_id"]]["side_aliases"]
            side = next(side for side in aliases if aliases[side] == "A")
            occurrence["side_evidence"][side]["severity"] = "minor"
        registry = self.freeze([response, deepcopy(response)])
        self.assertEqual(r.aggregate_safe(registry)["transitions"]["worsened"]["root_count"], 1)
        response["roots"][0]["occurrences"][0]["side_evidence"][side]["severity"] = "critical"
        with self.assertRaises(ValueError): r.validate_response(response, self.packet)

    def test_same_and_improved_are_derived_from_private_roles(self):
        for pair in self.pairs:
            pair["sides"]["A"] = deepcopy(pair["sides"]["B"])
        self.packet = self.build()
        response = self.response()
        registry = self.freeze([response, deepcopy(response)], "same.json")
        self.assertEqual(r.aggregate_safe(registry)["transitions"]["same"]["root_count"], 1)
        for pair in self.pairs:
            pair["sides"]["B"] = {"translations": {"j1": "我不去。"}, "claims": []}
        self.packet = self.build()
        response = self.response()
        registry = self.freeze([response, deepcopy(response)], "improved.json")
        summary = r.aggregate_safe(registry)
        self.assertEqual(summary["transitions"]["improved"]["root_count"], 1)
        self.assertEqual(summary["severity_transitions"], {"major->none": 1})

    def test_minor_only_roots_are_not_inflated_into_severe_union(self):
        for pair in self.pairs:
            pair["sides"]["B"]["claims"][0]["severity"] = "minor"
        packet = self.build(); response = self.response(packet)
        for occurrence in response["roots"][0]["occurrences"]:
            for evidence in occurrence["side_evidence"].values():
                if evidence["state"] == "present": evidence["severity"] = "minor"
        with self.assertRaises(ValueError): r.validate_response(response, packet)
        response["roots"] = []
        self.assertEqual(r.validate_response(response, packet), response)

    def test_disagreement_is_unresolved_and_only_one_adjudication_allowed(self):
        response = self.response()
        review = deepcopy(response)
        for item in review["roots"][0]["occurrences"]:
            item["side_evidence"]["L"].update(state="unknown", severity="unknown", quotes=[])
        registry = self.freeze([response, review])
        self.assertTrue(registry["initial_disagreement"])
        self.assertTrue(all(i["transition"] == "unresolved" for i in registry["roots"][0]["occurrences"]))
        adjudicated = self.freeze([response, review, response], "adjudicated.json")
        self.assertEqual(r.aggregate_safe(adjudicated)["transitions"]["new"]["root_count"], 1)
        with self.assertRaises(ValueError): self.freeze([response, response, response], "extra.json")
        with self.assertRaises(ValueError): self.freeze([response] * 4, "four.json")
        with self.assertRaises(ValueError): r.prompt(self.packet, prior_responses=[response, review])
        self.assertIn("ANONYMOUS_PRIOR_RESPONSES", r.prompt(self.packet, phase="adjudication", prior_responses=[response, review]))

    def test_root_names_do_not_create_fresh_pass_disagreement(self):
        response = self.response(); review = deepcopy(response)
        review["roots"][0]["identity_id"] = "different-local-root"
        registry = self.freeze([response, review])
        self.assertFalse(registry["initial_disagreement"])

    def test_causal_or_proposition_disagreement_is_not_silently_matched_by_claim_ids(self):
        response = self.response(); review = deepcopy(response)
        review["roots"][0]["cause_zh"] = "不同的合成因果解释。"
        registry = self.freeze([response, review])
        self.assertTrue(registry["initial_disagreement"])
        self.assertEqual(r.aggregate_safe(registry)["transitions"]["unresolved"]["root_count"], 1)

    def test_unsupported_cross_window_merge_rejected_but_evidence_link_permitted(self):
        self.pairs = [self.pair(seed, window, cue) for seed in r.SEEDS
                      for window, cue in (("w1", "j1"), ("w2", "j2"))]
        packet = self.build(); response = self.response(packet)
        with self.assertRaises(ValueError): r.validate_response(response, packet)
        occurrences = response["roots"][0]["occurrences"]
        first = next(item for item in occurrences if item["source_event_ids"] == ["j1"])
        second = next(item for item in occurrences if item["source_event_ids"] == ["j2"])
        response["roots"][0]["source_links"] = [{"left_occurrence_id": first["occurrence_id"],
            "right_occurrence_id": second["occurrence_id"], "source_quotes": first["source_quotes"] + second["source_quotes"],
            "reason_zh": "合成同一否定事实在后句明确持续。"}]
        self.assertEqual(r.validate_response(response, packet), response)

    def test_fresh_passes_and_accepted_response_pointer_binding(self):
        response = self.response(); records, pointers = self.passes([response, response])
        records[1]["fresh_invocation_id"] = records[0]["fresh_invocation_id"]
        with self.assertRaises(ValueError): r.freeze_registry(self.packet, records, pointers=pointers, output=self.root / "bad.json")
        records, pointers = self.passes([response, response])
        pointers["fresh-0"] = self.write("unrelated.json", {"unrelated": True})
        with self.assertRaises(ValueError): r.freeze_registry(self.packet, records, pointers=pointers, output=self.root / "bad.json")

    def test_export_hash_frozen_bundle_and_reject_overwrite(self):
        output = self.root / "bundle"
        bundle = r.export_bundle(output)
        self.assertFalse(bundle["dispatch_implemented"])
        for item in bundle["files"]:
            self.assertEqual(item["sha256"], hashlib.sha256((output / item["path"]).read_bytes()).hexdigest())
        with self.assertRaises(FileExistsError): r.export_bundle(output)


if __name__ == "__main__":
    unittest.main()
