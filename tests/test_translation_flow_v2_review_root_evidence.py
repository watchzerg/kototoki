"""Native-style synthetic byte chains and pure F8 root mechanics; no model/native calls."""
from copy import deepcopy
from pathlib import Path
import json
import unittest

from experiments.translation_eval import runner as e
from experiments.translation_judge import integrity, runner as judge
from experiments.translation_flow import test_v2_evaluation as fixtures
from experiments.translation_flow import v2_delivery as delivery
from experiments.translation_flow import v2_review_diagnostics as views
from experiments.translation_flow import v2_review_evaluation as bridge
from experiments.translation_flow import v2_review_root_evidence as roots


def anchor(uid, quote):
    return {"ids": [uid], "quote": quote, "occurrence": 1}


def response(packet):
    return {"profile": roots.PROFILE, "task_stage": packet["task_stage"], "pair_alias": packet["pair_alias"],
            "packet_sha256": roots.object_hash(packet), "status": "assessed", "complete_scored_scope_checked": True,
            "obligation_coverage": [{"obligation_id": c["obligation_id"], "disposition": "rejected", "root_ids": [],
                                     "explanation_zh": "仅用于合成流程；该既有假设需独立源证据，未直接接受。"}
                                    for c in packet["accepted_evidence"]],
            "roots": [], "root_reviews": [], "additional_roots": [], "uncertainties": []}


def root_record(packet, rid="new-root", severity="major"):
    uid = packet["scored_ids"][0]
    source = next(c["text"] for c in packet["context"] if c["id"] == uid)
    phases = {}
    for phase, values in packet["phases"].items():
        erroneous = values[uid] == "他会来。"
        phases[phase] = {"state": "supported_error" if erroneous else "supported_absence",
                         "error": {"type": "mistranslation", "severity": severity} if erroneous else None,
                         "anchors": [anchor(uid, values[uid])], "explanation_zh": "合成否定命题的原文和译文直接核对。"}
    return {"root_id": rid, "ids": [uid], "source_anchors": [anchor(uid, source)],
            "source_proposition_zh": "句子明确陈述他不会来。", "cause_zh": "源命题的否定极性。",
            **phases, "reason_zh": "合成例用来核验存在性及时间顺序，不代表真实裁判准确率。"}


class NativeFixture:
    def __init__(self):
        self.fixture = fixtures.SceneEvaluationTests()
        self.fixture.setUp()
        self.root = self.fixture.root
        f = self.fixture
        for scene in f.scenes:
            for cue, text in zip(scene["context"], ("彼は来ない。", "もし雨なら行かない。", "三つあります。")):
                old = cue["text"]
                cue["text"] = text
                for w in f.windows:
                    if w["scene_id"] != scene["id"]:
                        continue
                    srt = Path(w["source_srt"])
                    srt.write_text(srt.read_text(encoding="utf-8").replace(old, text), encoding="utf-8")
                    mapping = Path(w["source_mapping"])
                    data = e.read_json(mapping)
                    for row in data["语言轨"]["ja"]:
                        if row["文本"] == old:
                            row["文本"] = text
                    e.dump(mapping, data)
        samples = {w["scene_id"]: w for w in f.windows}
        old_refs = {w["id"]: r for w, r in zip(f.windows, f.refs)}
        f.windows, f.inputs, f.refs = [], [], []
        for sid, count in (("scene-a", 30), ("scene-b", 18)):
            sample = samples[sid]
            context = next(s["context"] for s in f.scenes if s["id"] == sid)
            for number in range(1, count + 1):
                w = deepcopy(sample)
                w["id"] = w["window_id"] = f"{sid}-Q{number:03d}"
                if sid == "scene-a":
                    w["scored_ids"] = ["scene-a-J1"]
                    for unit in w["units"]:
                        unit["score"] = unit["id"] in w["scored_ids"]
                w["source_srt_sha256"], w["source_mapping_sha256"] = e.sha(Path(w["source_srt"])), e.sha(Path(w["source_mapping"]))
                w.update(selection_type="representative", risk_tags=[])
                ref = deepcopy(old_refs[sample["id"]])
                ref.update(id=w["id"], scored_ids=w["scored_ids"])
                for unit in ref["units"]:
                    unit["ja"] = next(c["text"] for c in context if c["id"] == unit["id"])
                    unit["score"] = unit["id"] in w["scored_ids"]
                    if unit["score"]:
                        unit["zh"] = "合成参考，仅用于现有原生契约认证。"
                    else:
                        unit.pop("zh", None)
                f.windows.append(w)
                f.refs.append(ref)
                f.inputs.append({"id": w["id"], "source_language": "ja", "target_language": "zh-Hans",
                                 "context": [{"id": c["id"], "text": c["text"]} for c in context], "translate_ids": w["scored_ids"]})
        e.dump(f.manifest_path, {"version": "synthetic-source-v2", "external_corpus": str(f.source), "windows": f.windows})
        e.dump_jsonl(f.scene_path, f.scenes)
        e.dump_jsonl(f.input_path, f.inputs)
        e.dump_jsonl(f.reference_path, f.refs)
        f.freeze()
        self.custody_root = self.root / "evaluation-only"
        self.code = roots._code_pins({name: e.sha(Path(module.__file__)) for name, module in {
            "review_diagnostics": views, "review_evaluation": bridge, "native_dispatch": roots.native}.items()})
        drain = self.custody_root / "synthetic-native-drain.json"
        e.dump(drain, {"schema": "hy30-native-judge-custody-v1", "owner": "evaluation_custodian", "state": "drained_released",
                       "active_callbacks": 0, "owned_job_objects": 0, "workers_reserved": 6,
                       "module_sha256": self.code["native_dispatch"]["sha256"],
                       "global_lock": str(self.custody_root / ".judge-global-six.lock"), "fixture": "no native execution occurred"})
        self.drain = roots.universal.identity(drain)
        proposal = self.root / "synthetic-split.json"
        e.dump(proposal, {"groups": [{"source_group_id": "episode:episode-1", "assignment": "development",
                                     "window_ids": [w["id"] for w in f.windows[:30]]},
                                    {"source_group_id": "episode:episode-2", "assignment": "locked_internal_holdout",
                                     "window_ids": [w["id"] for w in f.windows[30:]]}],
                         "window_metadata": [{k: w[k] for k in ("window_id", "scene_id", "scored_ids", "category", "episode_id",
                                                                 "work_id", "selection_type", "risk_tags")} for w in f.windows],
                         "source_scene_metadata": [{"scene_id": s["id"], "source_cues": [{"id": c["id"]} for c in s["context"]]} for s in f.scenes]})
        registration = self.root / "synthetic-split-registration.json"
        e.dump(registration, {"schema": "F8-trigger-source-group-split-external-registration-v1",
                              "state": "frozen_before_F8_generation_and_quality", "proposal": roots.universal.identity(proposal)})
        self.registration = roots.universal.identity(registration)
        self.prepare_calls = 0

    def close(self):
        self.fixture.doCleanups()

    def native_run(self, seed, suffix, failed=False):
        f = self.fixture
        old = f.delivery(f"native-{seed}-{suffix}")
        metadata = e.read_json(old / "delivery.json")
        packed_path = Path(metadata["packed_mapping"]["path"])
        packed = e.read_json(packed_path)
        packed["seed"] = seed
        e.dump(packed_path, packed)
        directory = Path(metadata["run"])
        run = e.read_json(directory / "run.json")
        run.update(recipe="c0", settings={"recipe": "c0", "review": True}, packed_mapping_sha256=e.sha(packed_path))
        e.dump(directory / "run.json", run)
        ledger, results = e.load_jsonl(directory / "ledger.jsonl"), e.load_jsonl(directory / "results.jsonl")
        for number, row in enumerate(ledger):
            values = {uid: ("他不会来。" if uid.endswith("J1") else "如果下雨就不去。" if uid.endswith("J2") else "三个。") for uid in row["translations"]}
            before = {uid: ("他会来。" if uid.endswith("J1") else text) for uid, text in values.items()}
            row.update(before_review=before, translations=values, attempts=[])
            results[number]["translations"] = values
            for stage, text in (("translation", before), ("source-review", values)):
                request = {"prompt": [1], "n_predict": 4096}
                reply = {"content": json.dumps({"translations": text}, ensure_ascii=False), "tokens_predicted": 5}
                exchange = directory / "transport" / f"{number}-{stage}"
                e.dump(exchange / "request.json", {"endpoint": "/completion", "body": request})
                e.dump(exchange / "response.raw", reply)
                e.dump(exchange / "transport.json", {"status": 200})
                row["attempts"].append({"stage": stage, "status": "accepted", "completion_dispatched": True,
                    "request": request, "response": reply, "original_response": str(exchange), "input_tokens": 10, "elapsed_seconds": .01})
            if failed and "scene-a-J1" in values:
                row.update(status="translation_failed", translations={}, failure_stage="source-review", reason="Synthetic terminal review failure")
                row["attempts"][-1]["status"] = "failed"
                results[number].update(status="translation_failed", translations={})
        e.dump_jsonl(directory / "ledger.jsonl", ledger)
        e.dump_jsonl(directory / "results.jsonl", results)
        output = self.root / f"original-{seed}-{suffix}"
        delivery.deliver(f.manifest_path, packed_path, directory, output)
        return output

    def fake(self, args, prompt, cwd, attempt, timeout):
        self.prepare_calls += 1
        packet = json.loads(prompt.split("\nPACKET:\n", 1)[1].split("\nADJUDICATION:\n", 1)[0])
        value = {"window_id": packet["window_id"], "candidate_alias": packet["candidate_alias"], "semantic": 4,
                 "naturalness": 2, "status": "scored", "errors": [], "uncertainties": [], "summary_zh": "合成接受历史，不是模型推断。"}
        if packet["window_id"].endswith("Q001"):
            uid = packet["scored_ids"][0]
            value.update(semantic=3, errors=[{"ids": [uid], "type": "mistranslation", "severity": "minor",
                "source_evidence": next(c["text"] for c in packet["context"] if c["id"] == uid),
                "candidate_evidence": packet["translations"][uid], "reason_zh": "PRIVATE UPSTREAM REASON MUST NEVER ENTER ROOT PACKET"}])
        e.dump(attempt / "last-message.txt", value)
        return {"transport_status": "completed", "returncode": 0, "returned_models": [judge.MODEL],
                "returned_efforts": [judge.EFFORT], "tool_events": [], "elapsed_seconds": .01}

    def authenticate(self, suffix="complete", failed=False):
        scopes, eval_roots = [], {}
        f = self.fixture
        for seed in roots.SEEDS:
            original = self.native_run(seed, suffix, failed)
            directory = self.root / f"views-{seed}-{suffix}"
            views.export_review_views(original, directory)
            scopes.append(bridge.freeze_scope(f.manifest_path, f.input_path, f.reference_path, f.freeze_path,
                directory / "before", directory / "after", self.root / f"scope-{seed}-{suffix}.json",
                window_ids=[w["id"] for w in f.windows]))
        pointer = bridge.freeze_frame(scopes, self.root / f"frame-{suffix}.json")
        seals = {}
        for seed in roots.SEEDS:
            directory = self.root / f"phase-evaluation-{seed}-{suffix}"
            bridge.prepare(pointer, directory, seed=seed, registered_frame_sha256=pointer["sha256"])
            for filename in ("jobs.jsonl", "jobs-review.jsonl"):
                for job in e.load_jsonl(directory / filename):
                    self_assert = judge.run_job(directory, job, "offline-fake", "synthetic", 1, self.fake)
                    if self_assert["status"] != "succeeded":
                        raise AssertionError(self_assert)
                bridge.finalize(directory, registered_frame_sha256=pointer["sha256"])
            eval_roots[seed] = directory
            seal_path = directory / "root-phase-inventory.json"
            e.dump(seal_path, {"schema": "f8-root-phase-inventory-v1", "frame": pointer, "seed": seed, "code": self.code,
                "expected_records": 96, "native_drain_receipt": self.drain,
                "files": [{"path": p.relative_to(directory).as_posix(), "sha256": e.sha(p)} for p in sorted(directory.rglob("*"))
                          if p.is_file() and p.name != ".judge-scheduler.lock"]})
            seals[seed] = roots.universal.identity(seal_path)
        args = {"registered_frame_sha256": pointer["sha256"], "registered_split_sha256": self.registration["sha256"],
                "registered_phase_seal_sha256": {seed: p["sha256"] for seed, p in seals.items()},
                "expected_code_sha256": {name: p["sha256"] for name, p in self.code.items()}, "custody_root": self.custody_root}
        result = roots.prepare_frame(pointer, eval_roots, seals, self.registration, **args)
        return result, (pointer, eval_roots, seals, self.registration, args)


class RootEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native = NativeFixture()
        cls.frame, cls.native_args = cls.native.authenticate()
        cls.directory = cls.native.root / "custom-root"
        cls.directory.mkdir()
        cls.protocol = {"schema": "f8-root-hypothesis-review-protocol-v1", "profile": roots.PROFILE,
            "frame_sha256": cls.frame._hash, "split_registration_sha256": cls.native.registration["sha256"],
            "adapter_sha256": e.sha(Path(roots.__file__)), "model": "gpt-6.1-sol", "effort": "high", "attempts_per_job_max": 2,
            "classification_adjudication_jobs": 0, "expected_pairs": 144, "custody_root": str(cls.native.custody_root),
            "transport_settings": {"cli_version": "synthetic", "executable": "offline-fake", "surface": "codex-cli",
                "model": "gpt-6.1-sol", "effort": "high", "tool_policy": "disabled", "fresh_session": True}}
        protocol_path = cls.directory / "protocol.json"
        e.dump(protocol_path, cls.protocol)
        cls.protocol_pointer = roots.universal.identity(protocol_path)
        cls.aliases = {p["pair_key"]: f"anon-{i:032x}" for i, p in enumerate(cls.frame._data["pairs"], 1)}
        cls.orders = {p["pair_key"]: ["after", "before"] if i % 2 else ["before", "after"] for i, p in enumerate(cls.frame._data["pairs"])}
        cls.plan = roots.freeze_plan(cls.frame, cls.protocol_pointer, registered_protocol_sha256=cls.protocol_pointer["sha256"], aliases=cls.aliases, phase_orders=cls.orders)
        plan_path = cls.directory / "prepared-plan.json"
        e.dump(plan_path, cls.plan)
        cls.plan_pointer = roots.universal.identity(plan_path)
        cls.key = cls.frame._data["pairs"][0]["pair_key"]

    @classmethod
    def tearDownClass(cls):
        cls.native.close()

    def packet(self, order=None):
        return roots.build_evidence_packet(self.frame, self.key, anonymous_alias=self.aliases[self.key],
                                          phase_order=tuple(order or self.orders[self.key]))

    def opinions(self, first_roots=True):
        packet, private = self.packet()
        first = response(packet)
        if first_roots:
            first["roots"] = [root_record(packet)]
        review, mapping = roots.build_review_packet(packet, first)
        second = response(review)
        if first_roots:
            other = root_record(review, "independent-spelling")
            second["root_reviews"] = [{"hypothesis_id": "hypothesis-0001", "correspondence": "accepted",
                                       "root": other, "alternative_mapping_zh": ""}]
        return packet, private, first, review, mapping, second

    def reconcile(self, parts):
        packet, private, first, review, mapping, second = parts
        return roots.reconcile_pair(packet, first, review, second, private, mapping)

    def accepted_job(self, packet, value, label, status="succeeded"):
        job_id = f"{packet['task_stage']}/{packet['pair_alias']}"
        folder = self.directory / label / "execution" / job_id
        folder.mkdir(parents=True)
        ledger = folder / "job.json"
        fp = roots.task_fingerprint(packet, self.protocol_pointer, self.protocol)
        state = {"job_id": job_id, "profile": roots.PROFILE, "fingerprint": fp, "requested_model": "gpt-6.1-sol",
                 "requested_effort": "high", "cli_version": "synthetic", "status": status, "attempts": []}
        if status == "succeeded":
            attempt = folder / "attempt-1"
            attempt.mkdir()
            raw = attempt / "last-message.txt"
            raw.write_bytes(integrity.canonical_bytes(value))
            canonical = self.directory / label / "responses" / f"{job_id}.json"
            accepted = integrity.accept_response(raw, canonical, lambda v: roots.validate_response(packet, v))
            (attempt / "prompt.txt").write_bytes(roots.prompt(packet).encode())
            (attempt / "schema.json").write_bytes(integrity.canonical_bytes(roots.response_schema(packet["task_stage"])))
            (attempt / "stdout.jsonl").write_bytes(b'{"type":"synthetic-transport"}\n')
            (attempt / "stderr.txt").write_bytes(b"")
            state.update(response=str(canonical), **accepted)
            state["attempts"] = [{"attempt": 1, "status": "succeeded", "transport_status": "completed", "returncode": 0,
                "native_drain_proven": True, "native_active_processes_after_drain": 0,
                "containment": "suspended-assign-resume-kill-on-close-job", "returned_models": ["gpt-6.1-sol"],
                "returned_efforts": ["high"], "tool_events": [], "whole_attempt_seconds": .01,
                "stdout_sha256": e.sha(attempt / "stdout.jsonl"), "stderr_sha256": e.sha(attempt / "stderr.txt"),
                "global_harmed_count_must_not_leak": 12345}]
        e.dump(ledger, state)
        return {"ledger": roots.universal.identity(ledger), "registered_ledger_sha256": e.sha(ledger),
                "expected_fingerprint": fp, "expected_job_id": job_id}

    def snapshot(self, bundles):
        return roots.finalize_snapshot(self.frame, bundles, root_plan_pointer=self.plan_pointer,
            registered_plan_sha256=self.plan_pointer["sha256"], registered_protocol_sha256=self.protocol_pointer["sha256"])

    def test_native_authentication_and_private_reasons_are_not_exported(self):
        self.assertEqual(self.frame.metadata()["expected_pairs"], 144)
        packet, _ = self.packet(["after", "before"])
        serialized = json.dumps(packet, ensure_ascii=False)
        self.assertNotIn("PRIVATE UPSTREAM", serialized)
        self.assertNotIn("reference", serialized)
        self.assertNotIn("semantic", packet)
        self.assertEqual([c["phase"] for c in packet["accepted_evidence"]], ["phase_A", "phase_B"])

    def test_corrected_and_reversed_private_order(self):
        result = self.reconcile(self.opinions())
        self.assertTrue(result["complete"])
        self.assertEqual(result["roots"][0]["category"], "corrected")
        self.assertEqual(result["net_presence_bounds"], [1, 1])
        packet, private = self.packet(["after", "before"])
        first = response(packet)
        first["roots"] = [root_record(packet)]
        review, mapping = roots.build_review_packet(packet, first)
        second = response(review)
        second["root_reviews"] = [{"hypothesis_id": "hypothesis-0001", "correspondence": "accepted",
            "root": root_record(review, "independent"), "alternative_mapping_zh": ""}]
        self.assertEqual(roots.reconcile_pair(packet, first, review, second, private, mapping)["roots"][0]["category"], "corrected")

    def test_exact_neutral_whitelist_no_first_verdict_or_reason(self):
        parts = self.opinions()
        hypothesis = parts[3]["hypotheses"][0]
        self.assertEqual(set(hypothesis), {"hypothesis_id", "ids", "source_anchors", "candidate_anchors", "source_proposition_zh", "cause_zh"})
        self.assertNotIn("合成例用来核验", json.dumps(parts[3], ensure_ascii=False))
        bad = deepcopy(parts[2])
        bad["roots"][0]["cause_zh"] = "审校后 major 错误"
        with self.assertRaises(ValueError):
            roots.build_review_packet(parts[0], bad)

    def test_same_quote_different_cause_or_alternative_mapping_stays_unknown(self):
        for alternative, correspondence in (("另一个源原因，不能对应。", "rejected"), ("拆分成两个不同源根。", "accepted")):
            parts = list(self.opinions())
            parts[-1]["root_reviews"][0].update(correspondence=correspondence, alternative_mapping_zh=alternative)
            parts[-1]["root_reviews"][0]["root"]["cause_zh"] = "主体指代的源范围。"
            result = self.reconcile(parts)
            self.assertFalse(result["complete"])
            self.assertEqual(result["roots"][0]["category"], "unresolved")
            self.assertEqual(result["net_presence_bounds"], [-1, 1])

    def test_valid_correspondence_uncertainty_not_format_retry(self):
        parts = list(self.opinions())
        parts[-1]["status"] = "unknown"
        parts[-1]["root_reviews"][0].update(correspondence="unresolved", alternative_mapping_zh="无法确认同一个错误原因。")
        roots.validate_response(parts[3], parts[-1])
        self.assertFalse(self.reconcile(parts)["complete"])

    def test_first_failure_still_has_review_packet_and_single_pass_unknown(self):
        packet, private = self.packet()
        review, mapping = roots.build_review_packet(packet, None)
        self.assertEqual(review["hypotheses"], [])
        second = response(review)
        second["additional_roots"] = [root_record(review)]
        result = roots.reconcile_pair(packet, None, review, second, private, mapping)
        self.assertFalse(result["complete"])
        self.assertEqual(result["classification_adjudication_jobs"], 0)

    def test_review_failure_keeps_provisional_first_evidence_unconfirmed(self):
        parts = list(self.opinions())
        parts[-1] = None
        result = self.reconcile(parts)
        self.assertFalse(result["complete"])
        self.assertEqual(result["provisional_first_roots"], parts[2]["roots"])
        self.assertFalse(result["corrected_presence"])
        self.assertEqual(result["net_presence_bounds"], [-1, 1])

    def test_actual_rendered_prompt_supplies_exact_machine_identity(self):
        parts = self.opinions()
        for packet in (parts[0], parts[3]):
            submitted = roots.prompt(packet)
            binding_text, packet_text = submitted.split("RESPONSE_BINDING:\n", 1)[1].split("\nPACKET:\n", 1)
            binding = json.loads(binding_text)
            self.assertEqual(binding, {**{k: packet[k] for k in ("profile", "task_stage", "pair_alias")},
                                       "packet_sha256": roots.object_hash(packet)})
            self.assertEqual(json.loads(packet_text), packet)
            self.assertIn("never calculate the digest", submitted)
            self.assertIn("Copy every obligation_id and hypothesis_id literally", submitted)

    def test_both_zero_and_review_only_new_root(self):
        parts = list(self.opinions(False))
        self.assertTrue(self.reconcile(parts)["complete"])
        parts[-1]["additional_roots"] = [root_record(parts[3])]
        self.assertFalse(self.reconcile(parts)["complete"])
        self.assertEqual(self.reconcile(parts)["net_presence_bounds"], [-1, 1])

    def test_unknown_is_not_supported_absence(self):
        parts = list(self.opinions())
        for record in (parts[2]["roots"][0], parts[-1]["root_reviews"][0]["root"]):
            record["phase_A"].update(state="unknown", error=None, anchors=[], explanation_zh="源支持关系不确定。")
        review, mapping = roots.build_review_packet(parts[0], parts[2])
        parts[3], parts[4] = review, mapping
        parts[-1]["packet_sha256"] = roots.object_hash(review)
        self.assertFalse(self.reconcile(parts)["complete"])

    def test_severity_aggravation_is_harmed_and_persisted_without_double_missed(self):
        parts = list(self.opinions())
        after_label = "phase_" + "AB"[parts[1]["phase_order"].index("after")]
        for record in (parts[2]["roots"][0], parts[-1]["root_reviews"][0]["root"]):
            record[after_label].update(state="supported_error", error={"type": "mistranslation", "severity": "critical"})
        parts[3], parts[4] = roots.build_review_packet(parts[0], parts[2])
        parts[-1]["packet_sha256"] = roots.object_hash(parts[3])
        result = self.reconcile(parts)
        self.assertEqual(result["roots"][0]["category"], "harmed")
        self.assertTrue(result["roots"][0]["persisted"])
        self.assertFalse(result["missed_presence"])

    def test_schema_and_exact_quote_identity_duplicates_extra_fields(self):
        packet, _, first, _, _, _ = self.opinions()
        self.assertNotIn("uniqueItems", json.dumps(roots.response_schema("evidence")))
        for mutate in (lambda r: r.update(packet_sha256="0" * 64),
                       lambda r: r.update(score=4),
                       lambda r: r["roots"][0]["source_anchors"][0].update(quote="不存在的字面引用"),
                       lambda r: r["obligation_coverage"].append(deepcopy(r["obligation_coverage"][0]))):
            value = deepcopy(first)
            mutate(value)
            with self.assertRaises(ValueError):
                roots.validate_response(packet, value)
        malformed = deepcopy(packet)
        malformed["hypotheses"] = ""
        with self.assertRaises(ValueError):
            roots.validate_packet(malformed)

    def test_anchor_group_order_cannot_invent_source_text(self):
        with self.assertRaises(ValueError):
            roots._anchor({"ids": ["b", "a"], "quote": "二\n一", "occurrence": 1}, {"a": "一", "b": "二"}, ["a", "b"])

    def test_snapshot_full144_dev90_and_subtraction_leak_blocked(self):
        packet, private, first, review, mapping, second = self.opinions()
        bundle = {"evidence_job": self.accepted_job(packet, first, "good-first"),
                  "review_job": self.accepted_job(review, second, "good-second")}
        snapshot = self.snapshot({self.key: bundle})
        self.assertEqual(len(snapshot["records"]), 144)
        self.assertEqual(snapshot["expected_root_job_slots"], 288)
        release = roots.release_development(snapshot, self.frame, registered_snapshot_sha256=snapshot["snapshot_sha256"])
        self.assertEqual(len(release["records"]), 90)
        self.assertEqual(release["expected_root_job_slots"], 180)
        text = json.dumps(release, ensure_ascii=False)
        self.assertNotIn("scene-b", text)
        self.assertNotIn("12345", text)
        self.assertNotIn("original_generation_cost_identities_count_once", release)
        ledger = e.read_json(Path(bundle["evidence_job"]["ledger"]["path"]))
        raw = Path(ledger["accepted_raw_response"])
        original = raw.read_bytes()
        try:
            raw.write_bytes(b"{}")
            with self.assertRaises(ValueError):
                roots.release_development(snapshot, self.frame, registered_snapshot_sha256=snapshot["snapshot_sha256"])
        finally:
            raw.write_bytes(original)
        tampered = deepcopy(snapshot)
        tampered["records"][0]["complete"] = False
        tampered.pop("snapshot_sha256")
        tampered["snapshot_sha256"] = roots.object_hash(tampered)
        with self.assertRaises(ValueError):
            roots.release_development(tampered, self.frame, registered_snapshot_sha256=snapshot["snapshot_sha256"])

    def test_root_plan_mapping_fingerprint_and_accepted_raw_tamper(self):
        packet, _, first, review, _, second = self.opinions()
        first_job = self.accepted_job(packet, first, "tamper-first")
        second_job = self.accepted_job(review, second, "tamper-second")
        bundles = {self.key: {"evidence_job": first_job, "review_job": second_job}}
        bad = deepcopy(bundles)
        bad[self.key]["evidence_job"]["expected_fingerprint"] = "0" * 64
        with self.assertRaises(ValueError):
            self.snapshot(bad)
        ledger = e.read_json(Path(first_job["ledger"]["path"]))
        raw = Path(ledger["accepted_raw_response"])
        original = raw.read_bytes()
        try:
            raw.write_bytes(b"{}")
            with self.assertRaises(ValueError):
                self.snapshot(bundles)
        finally:
            raw.write_bytes(original)
        plan = deepcopy(self.plan)
        plan["pairs"][0]["phase_order"].reverse()
        alternate = self.directory / "changed-plan.json"
        e.dump(alternate, plan)
        with self.assertRaises(ValueError):
            roots.finalize_snapshot(self.frame, bundles, root_plan_pointer=roots.universal.identity(alternate),
                registered_plan_sha256=self.plan_pointer["sha256"], registered_protocol_sha256=self.protocol_pointer["sha256"])

    def test_live_native_dependency_and_phase_inventory_extras_fail_closed(self):
        pointer, directories, _, _, _ = self.native_args
        original = self.frame._data["original_cost_identities"][0]
        native_run = Path(original["path"]).parent
        raw = next(native_run.glob("transport/*/response.raw"))
        original_bytes = raw.read_bytes()
        try:
            raw.write_bytes(b"{}")
            with self.assertRaises(ValueError):
                self.packet()
        finally:
            raw.write_bytes(original_bytes)
        extra = directories[roots.SEEDS[0]] / "unregistered.json"
        try:
            extra.write_bytes(b"{}")
            with self.assertRaises(ValueError):
                self.packet()
        finally:
            extra.unlink()

    def test_upstream_second_uncertainty_preserved_despite_matching_scores(self):
        row = {"candidate_alias": "c01", "window_id": "w", "structural_status": "valid"}
        first = {"semantic": 4, "naturalness": 2, "status": "scored", "errors": [], "uncertainties": []}
        second = {**first, "uncertainties": [{"ids": ["x"], "reason_zh": "合成源歧义。"}]}
        final = {**first, "reviewed": True}
        _, clear = roots._used_evidence(row, final, {("primary", "c01", "w"): first, ("review", "c01", "w"): second})
        self.assertFalse(clear)

    def test_terminal_failed_review_preserves144_and_dev_zero_calls(self):
        frame, _ = self.native.authenticate("failed", failed=True)
        eligible = [p for p in frame._data["pairs"] if p["mechanically_eligible"]]
        self.assertEqual(len(eligible), 54)
        failed_pair = next(p for p in frame._data["pairs"] if not p["mechanically_eligible"])
        with self.assertRaises(ValueError):
            roots.build_evidence_packet(frame, failed_pair["pair_key"], anonymous_alias="anon-" + "f" * 32, phase_order=("before", "after"))
        self.assertEqual(len(frame._data["pairs"]), 144)
        self.assertTrue(all(not p["mechanically_eligible"] for p in frame._data["pairs"] if p["assignment"] == "development"))
        protocol = deepcopy(self.protocol)
        protocol["frame_sha256"] = frame._hash
        path = self.directory / "failed-protocol.json"
        e.dump(path, protocol)
        pointer = roots.universal.identity(path)
        plan = roots.freeze_plan(frame, pointer, registered_protocol_sha256=pointer["sha256"],
                                 aliases=self.aliases, phase_orders=self.orders)
        plan_path = self.directory / "failed-plan.json"
        e.dump(plan_path, plan)
        plan_pointer = roots.universal.identity(plan_path)
        snapshot = roots.finalize_snapshot(frame, {}, root_plan_pointer=plan_pointer,
            registered_plan_sha256=plan_pointer["sha256"], registered_protocol_sha256=pointer["sha256"])
        self.assertEqual(len(snapshot["records"]), 144)
        self.assertEqual(sum(r["unknown_reasons"] == ["mechanical_unknown"] for r in snapshot["records"]), 90)
        self.assertTrue(all(not r["jobs"] for r in snapshot["records"]))
        release = roots.release_development(snapshot, frame, registered_snapshot_sha256=snapshot["snapshot_sha256"])
        self.assertEqual(len(release["records"]), 90)
        self.assertEqual(release["net_presence_bounds"], [-90, 90])
        self.assertTrue(all(not r["jobs"] for r in release["records"]))


if __name__ == "__main__":
    unittest.main()
