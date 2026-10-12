from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from experiments.translation_corpus.prepare import (
    audit_overlap, blocks, freeze, packet, read_json, reconcile, replace_excluded,
    snapshot_final_sources, validate_active_selection, validate_execution, validate_review, write_json, write_jsonl,
)

TEMP_ROOT = Path(__file__).resolve().parents[1] / ".local/tests/translation-corpus"


def temporary_directory():
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=TEMP_ROOT)


def fixture() -> dict:
    pairs = [{"start_ms": i * 1000, "end_ms": i * 1000 + 900,
              "ja_end_ms": i * 1000 + 900, "zh_end_ms": i * 1000 + 900,
              "ja": "来ない", "zh": "不会来", "ja_srt_index": i + 1,
              "zh_srt_index": i + 1, "flags": [], "source_events": {
                  lang: [{"Dialogue序号": i + 1}] for lang in ("ja", "zh")}}
             for i in range(30)]
    source = {"source_sha256": "synthetic", "episode_id": "W01_E001",
              "work": "Synthetic", "work_id": "W01", "selection_group": "test"}
    return blocks(pairs, source, set())[0][0]


def accepted(row: dict) -> dict:
    return {"window_id": row["id"], "status": "accept",
            "translations": {u["id"]: u["zh"] for u in row["units"] if u["score"]},
            "changes": [], "reason_zh": "原译保留否定，文本对应。", "diagnostic_tags": ["negation_condition"]}


class CorpusTests(unittest.TestCase):
    def test_context_overlap_including_unscored_units_rejected(self):
        row = fixture()
        other = {**row, "id": "another"}
        with self.assertRaisesRegex(ValueError, "New-context overlap"):
            audit_overlap([row, other], set())
        with self.assertRaisesRegex(ValueError, "Old-context overlap"):
            audit_overlap([row], {row["source_event_keys"][0]})

    def test_packet_has_no_context_reference_or_model_identity(self):
        row = fixture()
        p = packet(row)
        self.assertEqual(len(p["context"]), 7)
        self.assertEqual(len(p["scored_ids"]), 5)
        self.assertNotIn("original_zh", p["context"][0])
        self.assertNotIn("original_zh", p["context"][-1])
        self.assertNotIn("candidate", p)

    def test_accept_and_source_grounded_edit(self):
        row = fixture()
        result = accepted(row)
        validate_review(row, result)
        key = row["scored_ids"][0]
        result["status"] = "edit"
        result["translations"][key] = "不来"
        result["changes"] = [{"id": key, "original_zh": "不会来", "revised_zh": "不来",
                              "source_evidence": "来ない", "reason_zh": "测试修改记录。"}]
        validate_review(row, result)
        result["changes"][0]["source_evidence"] = "来る"
        with self.assertRaisesRegex(ValueError, "provenance/evidence"):
            validate_review(row, result)

    def test_missing_scored_translation_and_unexplained_edit_rejected(self):
        row = fixture()
        result = accepted(row)
        del result["translations"][row["scored_ids"][0]]
        with self.assertRaisesRegex(ValueError, "exactly scored IDs"):
            validate_review(row, result)
        result = accepted(row)
        result["translations"][row["scored_ids"][0]] = "会来"
        with self.assertRaisesRegex(ValueError, "changed IDs"):
            validate_review(row, result)

    def test_exclusion_cannot_guess_reference(self):
        row = fixture()
        result = accepted(row)
        result["status"] = "exclude"
        with self.assertRaisesRegex(ValueError, "cannot invent"):
            validate_review(row, result)
        result["translations"] = {}
        validate_review(row, result)

    def test_duplicate_keys_rejected(self):
        with temporary_directory() as temp:
            p = Path(temp) / "bad.json"
            p.write_text('{"status":"accept","status":"exclude"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
                read_json(p)

    def test_freeze_cannot_create_inputs_without_both_reviews(self):
        with temporary_directory() as temp:
            out = Path(temp)
            (out / "staging").mkdir()
            row = fixture()
            (out / "staging/selected-candidates.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "incomplete 1200-window double review"):
                freeze(out)
            self.assertFalse((out / "model-input/expanded.jsonl").exists())

    def test_fresh_review_disagreement_requires_bounded_adjudication(self):
        with temporary_directory() as temp:
            out = Path(temp)
            row = fixture()
            write_jsonl(out / "staging/selected-candidates.jsonl", [row])
            write_json(out / f"reviews/primary/{row['id']}.json", accepted(row))
            exclusion = {**accepted(row), "status": "exclude", "translations": {}, "reason_zh": "上下文不足。"}
            write_json(out / f"reviews/review/{row['id']}.json", exclusion)
            result = reconcile(out)
            self.assertEqual(result["counts"], {"dispute": 1})
            job = read_json(out / "adjudication-jobs.jsonl")
            self.assertEqual(job["maximum_adjudications"], 1)
            write_json(out / f"reviews/adjudication/{row['id']}.json", {**exclusion, "resolved": False, "resolution_zh": "无法凭文本决定。"})
            result = reconcile(out)
            self.assertEqual(result["counts"], {"excluded": 1})

    def test_replacement_uses_first_frozen_same_group_reserve(self):
        with temporary_directory() as temp:
            out = Path(temp)
            row = fixture()
            replacement = {**row, "id": "reserve-1", "reserve_tier": "same_episode_or_position"}
            later = {**row, "id": "reserve-2", "reserve_tier": "same_episode_or_position"}
            # Real rows have their own unique units; identity is sufficient to test reserve order.
            write_jsonl(out / "staging/selected-candidates.jsonl", [row])
            write_jsonl(out / "audit/frame.jsonl", [row, replacement, later])
            write_json(out / f"review-packets/{row['id']}.json", packet(row))
            write_jsonl(out / "staging/reserve-candidates.jsonl", [replacement, later])
            write_jsonl(out / "review-jobs.jsonl", [])
            exclusion = {**accepted(row), "status": "exclude", "translations": {}, "reason_zh": "上下文不足。"}
            for phase in ("primary", "review"):
                write_json(out / f"reviews/{phase}/{row['id']}.json", exclusion)
            result = replace_excluded(out)
            self.assertEqual(result["replaced"], 1)
            self.assertIn('"id": "reserve-1"', (out / "staging/selected-candidates.jsonl").read_text(encoding="utf-8"))
            self.assertTrue((out / f"reviews/primary/{row['id']}.json").exists())
            self.assertFalse((out / "reviews/primary/reserve-1.json").exists())

    def test_active_rows_and_packets_must_match_original_frame(self):
        with temporary_directory() as temp:
            out = Path(temp)
            row = fixture()
            write_jsonl(out / "audit/frame.jsonl", [row])
            write_json(out / f"review-packets/{row['id']}.json", packet(row))
            validate_active_selection(out, [row])
            changed = {**row, "work": "Changed"}
            with self.assertRaisesRegex(ValueError, "row differs"):
                validate_active_selection(out, [changed])
            modified_packet = packet(row)
            modified_packet["context"][1]["original_zh"] = "篡改"
            write_json(out / f"review-packets/{row['id']}.json", modified_packet)
            with self.assertRaisesRegex(ValueError, "packet differs"):
                validate_active_selection(out, [row])

    def test_duplicate_active_or_frame_ids_refused(self):
        with temporary_directory() as temp:
            out = Path(temp)
            row = fixture()
            write_jsonl(out / "audit/frame.jsonl", [row, row])
            with self.assertRaisesRegex(ValueError, "Duplicate original"):
                validate_active_selection(out, [row])
            write_jsonl(out / "audit/frame.jsonl", [row])
            with self.assertRaisesRegex(ValueError, "Duplicate active"):
                validate_active_selection(out, [row, row])

    def test_unresolved_adjudication_cannot_publish_accepted_reference(self):
        with temporary_directory() as temp:
            out = Path(temp)
            row = fixture()
            write_jsonl(out / "staging/selected-candidates.jsonl", [row])
            write_json(out / f"reviews/primary/{row['id']}.json", accepted(row))
            exclusion = {**accepted(row), "status": "exclude", "translations": {}}
            write_json(out / f"reviews/review/{row['id']}.json", exclusion)
            write_json(out / f"reviews/adjudication/{row['id']}.json", {**accepted(row), "resolved": False, "resolution_zh": "未决"})
            with self.assertRaisesRegex(ValueError, "Unresolved adjudication must exclude"):
                reconcile(out)

    def test_replacement_refuses_already_frozen_corpus(self):
        with temporary_directory() as temp:
            out = Path(temp)
            write_json(out / "freeze-manifest.json", {"state": "frozen"})
            with self.assertRaisesRegex(ValueError, "Frozen corpus cannot change"):
                replace_excluded(out)

    def test_freeze_export_has_demo_five_field_input_contract(self):
        from unittest.mock import patch
        import sys
        from experiments.translation_demo.adapters import validate_window
        with temporary_directory() as temp:
            out = Path(temp)
            original_snapshot = out / "builder-snapshot/prepare.py"
            original_snapshot.parent.mkdir()
            original_snapshot.write_bytes(b"original immutable builder snapshot")
            prompt = out / "reference-review-prompt.md"
            prompt.write_text("Synthetic frozen prompt", encoding="utf-8")
            import hashlib
            write_json(out / "manifest.json", {"external_corpus": str(out), "sources": [],
                       "prompt_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest()})
            resolved = []
            for i in range(1200):
                row = {**fixture(), "id": f"synthetic-{i}", "work_id": f"work-{i // 80}",
                       "category": "anime_series", "episode": "synthetic"}
                resolved.append({"row": row, "decision": accepted(row)})
            write_jsonl(out / "staging/resolved-references.jsonl", resolved)
            write_jsonl(out / "staging/selected-candidates.jsonl", [r["row"] for r in resolved])
            write_json(out / "audit/forbidden-event-keys.json", [])
            module = sys.modules[freeze.__module__]
            with patch.object(module, "reconcile", return_value={"counts": {"agreed": 1200}}), \
                 patch.object(module, "validate_active_selection"), \
                 patch.object(module, "validate_execution"), patch.object(module, "audit_overlap"):
                freeze(out)
            first = json.loads((out / "model-input/expanded.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(set(first), {"id", "source_language", "target_language", "context", "translate_ids"})
            self.assertEqual(first["source_language"], "ja")
            self.assertEqual(first["target_language"], "zh-Hans")
            validate_window(first)
            self.assertEqual(original_snapshot.read_bytes(), b"original immutable builder snapshot")
            frozen = read_json(out / "freeze-manifest.json")
            identity = frozen["reference_review_prompt_identity"]
            self.assertEqual(identity["actual_execution_prompt_sha256"], hashlib.sha256(prompt.read_bytes()).hexdigest())
            self.assertEqual(identity["newline_conversion"], "none")
            self.assertEqual(identity["historical_sampling_manifest_sha256"], hashlib.sha256((out / "manifest.json").read_bytes()).hexdigest())
            self.assertEqual(frozen["original_builder_snapshots"][0]["path"], "builder-snapshot/prepare.py")
            final_directory = out / frozen["final_builder_snapshot"]["directory"]
            self.assertTrue((final_directory / "corpus/prepare.py").exists())
            frozen_paths = {r["path"] for r in frozen["files"]}
            self.assertIn("builder-snapshot/prepare.py", frozen_paths)
            self.assertIn((final_directory / "corpus/prepare.py").relative_to(out).as_posix(), frozen_paths)

    def test_content_addressed_final_snapshot_never_overwrites_existing_bytes(self):
        with temporary_directory() as temp:
            out = Path(temp)
            first = snapshot_final_sources(out)
            self.assertEqual(snapshot_final_sources(out), first)
            target = out / first["directory"] / "corpus/prepare.py"
            target.write_bytes(target.read_bytes() + b"# tampered")
            with self.assertRaisesRegex(ValueError, "snapshot already differs"):
                snapshot_final_sources(out)

    def test_execution_evidence_required_before_freeze(self):
        with temporary_directory() as temp:
            with self.assertRaisesRegex(ValueError, "Missing exact-model fresh execution"):
                validate_execution(Path(temp), "primary", "synthetic")



class PromptNewlineIdentityTests(unittest.TestCase):
    def test_full_freeze_preserves_manifest_execution_prompt_and_source_snapshot(self):
        from unittest.mock import patch
        import hashlib
        import sys
        module = sys.modules[freeze.__module__]
        source = Path(module.__file__).with_name("reference-review-prompt.md").read_bytes()
        self.assertNotIn(b"\r", source)
        copied = source.replace(b"\n", b"\r\n")
        with temporary_directory() as temp:
            out = Path(temp)
            (out / "reference-review-prompt.md").write_bytes(copied)
            (out / ".reference-orchestration.lock").write_bytes(b"0")
            (out / ".judge-scheduler.lock").write_bytes(b"0")
            write_json(out / "manifest.json", {"external_corpus": str(out), "sources": [],
                       "prompt_sha256": hashlib.sha256(source).hexdigest()})
            manifest_bytes = (out / "manifest.json").read_bytes()
            resolved = []
            for i in range(1200):
                row = {**fixture(), "id": f"synthetic-{i}", "work_id": f"work-{i // 80}",
                       "category": "anime_series", "episode": "synthetic"}
                resolved.append({"row": row, "decision": accepted(row)})
            write_jsonl(out / "staging/resolved-references.jsonl", resolved)
            write_jsonl(out / "staging/selected-candidates.jsonl", [r["row"] for r in resolved])
            write_json(out / "audit/forbidden-event-keys.json", [])
            with patch.object(module, "reconcile", return_value={"counts": {"agreed": 1200}}), \
                 patch.object(module, "validate_active_selection"), \
                 patch.object(module, "validate_execution"), patch.object(module, "audit_overlap"):
                freeze(out)
            frozen = read_json(out / "freeze-manifest.json")
            identity = frozen["reference_review_prompt_identity"]
            self.assertEqual(identity["newline_conversion"], "windows_text_copy_lf_to_crlf")
            self.assertEqual(identity["historical_sampling_manifest_sha256"], hashlib.sha256(manifest_bytes).hexdigest())
            self.assertEqual((out / "manifest.json").read_bytes(), manifest_bytes)
            self.assertEqual((out / "reference-review-prompt.md").read_bytes(), copied)
            snapshot = out / frozen["final_builder_snapshot"]["directory"] / "corpus/reference-review-prompt.md"
            self.assertEqual(snapshot.read_bytes(), source)
            identities = {record["path"]: record["sha256"] for record in frozen["files"]}
            self.assertEqual(identities["reference-review-prompt.md"], hashlib.sha256(copied).hexdigest())
            self.assertEqual({r["path"] for r in frozen["excluded_control_artifacts"]},
                             {".reference-orchestration.lock", ".judge-scheduler.lock"})
            self.assertNotIn(".reference-orchestration.lock", identities)
            self.assertNotIn(".judge-scheduler.lock", identities)

    def test_exact_prompt_and_proven_windows_copy(self):
        from experiments.translation_corpus.prepare import review_prompt_identity
        import hashlib
        source = "指示A\n指示B\n".encode("utf-8")
        expected = hashlib.sha256(source).hexdigest()
        exact = review_prompt_identity(source, source, expected)
        copied = source.replace(b"\n", b"\r\n")
        converted = review_prompt_identity(copied, source, expected)
        self.assertEqual(exact["newline_conversion"], "none")
        self.assertEqual(converted["newline_conversion"], "windows_text_copy_lf_to_crlf")
        self.assertEqual(converted["declared_sampling_source_sha256"], expected)
        self.assertEqual(converted["actual_execution_prompt_sha256"], hashlib.sha256(copied).hexdigest())
        self.assertEqual(converted["source_snapshot_sha256"], expected)

    def test_non_copy_mutations_and_unproven_source_rejected(self):
        from experiments.translation_corpus.prepare import review_prompt_identity
        import hashlib
        source = "指示A\n指示B\n".encode("utf-8")
        expected = hashlib.sha256(source).hexdigest()
        copied = source.replace(b"\n", b"\r\n")
        mutations = [copied.replace(b"A", b"C"), copied + b"\r\n",
                     copied[:-2], copied.replace(b"\r\n", b"\n", 1),
                     copied.replace(b"\r\n", b"\r"), b"\xef\xbb\xbf" + copied,
                     copied.replace(b"\r\n", b"\r\r\n"),
                     copied.replace(b"\r\n", "\u2028".encode("utf-8")),
                     copied + b" "]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                review_prompt_identity(mutation, source, expected)
        with self.assertRaises(ValueError):
            review_prompt_identity(copied, source.replace(b"A", b"C"), expected)
        with self.assertRaises(ValueError):
            review_prompt_identity(copied, copied, expected)
        with self.assertRaises(ValueError):
            review_prompt_identity(copied, source, "0" * 64)

    def test_execution_provenance_still_requires_actual_crlf_bytes(self):
        import hashlib
        source = b"Synthetic instructions\n"
        copied = source.replace(b"\n", b"\r\n")
        with temporary_directory() as temp:
            out = Path(temp)
            (out / "reference-review-prompt.md").write_bytes(copied)
            response = out / "reviews/primary/synthetic.json"
            write_json(response, {"synthetic": True})
            metadata = {"status": "succeeded", "requested_model": "gpt-6.1-sol",
                        "requested_effort": "high", "fresh": True,
                        "response_sha256": hashlib.sha256(response.read_bytes()).hexdigest(),
                        "prompt_sha256": hashlib.sha256(source).hexdigest()}
            write_json(out / "reference-execution/primary/synthetic/job.json", metadata)
            with self.assertRaisesRegex(ValueError, "instructions provenance hash mismatch"):
                validate_execution(out, "primary", "synthetic")


class FreezeLockInventoryTests(unittest.TestCase):
    def test_only_exact_root_controls_excluded_and_substantive_hashes_retained(self):
        import hashlib
        from experiments.translation_corpus.prepare import freeze_evidence_inventory
        with temporary_directory() as temp:
            out = Path(temp)
            names = [".reference-orchestration.lock", ".judge-scheduler.lock", "freeze-manifest.json",
                     "audit/.reference-orchestration.lock", "audit/.judge-scheduler.lock",
                     "audit/freeze-manifest.json", ".judge-global-six.lock", "unknown.lock", "reviews/proof.json"]
            for name in names:
                path = out / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"substantive-or-control")
            files, excluded = freeze_evidence_inventory(out)
            excluded_names = {r["path"] for r in excluded}
            self.assertEqual(excluded_names, {".reference-orchestration.lock", ".judge-scheduler.lock"})
            identities = {r["path"]: r["sha256"] for r in files}
            expected_names = set(names) - excluded_names - {"freeze-manifest.json"}
            self.assertEqual(set(identities), expected_names)
            for name in expected_names:
                self.assertEqual(identities[name], hashlib.sha256((out / name).read_bytes()).hexdigest())

    def test_substantive_permission_error_is_not_suppressed(self):
        from experiments.translation_corpus.prepare import freeze_evidence_inventory
        from unittest.mock import patch
        import sys
        module = sys.modules[freeze.__module__]
        with temporary_directory() as temp:
            out = Path(temp)
            write_json(out / "reviews/proof.json", {"synthetic": True})
            with patch.object(module, "digest", side_effect=PermissionError("synthetic blocked evidence")):
                with self.assertRaisesRegex(PermissionError, "blocked evidence"):
                    freeze_evidence_inventory(out)

    @unittest.skipUnless(__import__("os").name == "nt", "Native Windows byte-lock regression")
    def test_native_windows_controls_are_excluded_but_locked_evidence_fails(self):
        import msvcrt
        import subprocess
        import sys
        module = sys.modules[freeze.__module__]
        child = '''import importlib.util,json,sys
from pathlib import Path
root,module_path,mode=map(str,sys.argv[1:])
spec=importlib.util.spec_from_file_location("private_inventory",module_path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
try:
    if mode=="legacy":
        files=[]
        for path in sorted(Path(root).rglob("*")):
            if path.is_file() and path.name!="freeze-manifest.json":
                try: module.digest(path)
                except PermissionError:
                    print(json.dumps({"blocked_path":path.relative_to(root).as_posix()}));sys.exit(13)
    else:
        files,excluded=module.freeze_evidence_inventory(Path(root))
except PermissionError:
    sys.exit(13)
'''
        for name in (".reference-orchestration.lock", ".judge-scheduler.lock",
                     "audit/.reference-orchestration.lock", "unknown.lock", "reviews/proof.json"):
            with self.subTest(path=name), temporary_directory() as temp:
                out = Path(temp)
                path = out / name
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w+b") as stream:
                    stream.write(b"0")
                    stream.flush()
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    try:
                        legacy = subprocess.run([sys.executable, "-B", "-c", child, str(out), module.__file__, "legacy"], capture_output=True, text=True)
                        self.assertEqual(legacy.returncode, 13, legacy.stderr)
                        self.assertEqual(json.loads(legacy.stdout)["blocked_path"], name)
                        proposed = subprocess.run([sys.executable, "-B", "-c", child, str(out), module.__file__, "proposed"], capture_output=True, text=True)
                        self.assertEqual(proposed.returncode, 0 if name.startswith(".") and name != "unknown.lock" else 13, proposed.stderr)
                    finally:
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == "__main__":
    unittest.main()
