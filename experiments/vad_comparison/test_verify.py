"""Independent audit fault detection with synthetic data; no model execution."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from . import verify


class AuditTests(unittest.TestCase):
    def setUp(self):
        private = verify.ROOT / ".local/vad-comparison/audit-tests"
        private.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=private)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pcm = struct.pack("<8h", -32768, -1001, -1, 0, 1, 17, 1001, 32767)
        self.clip = {"offset": 4}
        self.windows = [(1, 4), (6, 8)]
        self.manifest = {"chunks": [{"start_sample": lo, "end_sample": hi} for lo, hi in self.windows]}
        self.document = {"text": "あ", "input": {"pcm_sha256": hashlib.sha256(self.pcm).hexdigest()}, "offset_s": 4,
            "chunks": copy.deepcopy(self.manifest["chunks"]),
            "original_segments": [{**self.manifest["chunks"][0], "text": "あ"},
                                  {**self.manifest["chunks"][1], "text": ""}],
            "asr_traces": [], "alignment_records": [], "units": [{"char_start": 0, "char_end": 1}]}
        for index, (lo, hi) in enumerate(self.windows):
            digest = hashlib.sha256(verify.float32_pcm(self.pcm[lo*2:hi*2])).hexdigest()
            self.document["asr_traces"].append({"start_sample": lo, "end_sample": hi, "pcm_float32_sha256": digest})
            self.document["alignment_records"].append({"segment_index": index, "tokens": [],
                "normalization": {"source_sample_start": lo, "source_sample_end": hi,
                                  "valid_samples": hi-lo, "raw_float32_sha256": digest}} if index == 0
                else {"segment_index": index, "tokens": [], "skip_reason": "no_eligible_characters"})

    def test_stdlib_float32_matches_exact_binary_values(self):
        expected = struct.pack("<8f", -1, -1001/32768, -1/32768, 0, 1/32768, 17/32768, 1001/32768, 32767/32768)
        self.assertEqual(verify.float32_pcm(self.pcm), expected)

    def test_exact_vad_crops_and_explained_empty_mms_skip(self):
        issues = []
        result = verify.audit_crops(self.document, self.clip, self.pcm, self.manifest, issues)
        self.assertEqual(issues, [])
        self.assertEqual(result["asr_pcm_hashes_checked"], 2)
        self.assertEqual(result["mms_pcm_hashes_checked"], 1)
        self.assertEqual(result["mms_no_text_skips"], 1)

    def test_corrupt_pcm_window_alignment_and_character_accounting_detected(self):
        for change, expected in (("hash", "asr_source_float32_pcm_hash_mismatch"),
            ("window", "manifest_asr_segment_windows_differ"), ("mms", "manifest_mms_source_windows_differ"),
            ("unit", "character_accounting_incomplete_or_duplicate"), ("normalization", "mms_normalization_unexplained_missing")):
            document = copy.deepcopy(self.document)
            if change == "hash":
                document["asr_traces"][0]["pcm_float32_sha256"] = "wrong"
            elif change == "window":
                document["original_segments"][0]["start_sample"] = 0
            elif change == "mms":
                document["alignment_records"][0]["normalization"]["source_sample_start"] = 0
            elif change == "unit":
                document["units"] = []
            else:
                document["alignment_records"][0].pop("normalization")
            issues = []
            verify.audit_crops(document, self.clip, self.pcm, self.manifest, issues)
            self.assertIn(expected, issues)

    def test_original_comparison_excludes_timing_but_preserves_tokens_and_records(self):
        folder = self.root / ".local/x0-demo/verified-v1-hf-ii-window-01-fixed30"
        folder.mkdir(parents=True)
        original = {"text": "あ", "units": [], "chunks": [], "original_segments": [], "alignment_records": [],
                    "asr_traces": [{"token_ids": [1, 2], "inference_s": 3, "preprocess_s": 1}]}
        (folder / "result.json").write_text(json.dumps(original), encoding="utf-8")
        fresh = copy.deepcopy(original)
        fresh["asr_traces"][0]["inference_s"] = 42
        with patch.object(verify, "ROOT", self.root):
            self.assertEqual(verify.compare_original(fresh, "x0", "hf-ii-window-01")["status"], "identical")
            fresh["asr_traces"][0]["token_ids"] = [1]
            self.assertEqual(verify.compare_original(fresh, "x0", "hf-ii-window-01")["status"], "changed")

    def test_pending_and_blocked_slots_never_count_as_passes(self):
        clips = [{"id": f"clip-{i}"} for i in range(12)]
        routes = [{"id": route, "model_metadata": {"family": route.split("-", 1)[0], "vad": route.split("-", 1)[1]},
                   "runs": [{"clip_id": clip["id"], "status": "blocked" if route.endswith("current") else "pending"}
                            for clip in clips]} for route in verify.ROUTES]
        path = self.root / "study.json"
        path.write_text(json.dumps({"study_id": "synthetic", "clips": clips, "routes": routes}), encoding="utf-8")
        report = verify.audit_study(path)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["passed_artifact_slots"], 0)
        self.assertEqual(report["not_executed_slots"], 120)
        self.assertEqual(report["execution_status_counts"]["blocked"], 24)
        routes[0]["runs"][0].update(status="completed", result_path=str(self.root / "missing.json"))
        path.write_text(json.dumps({"study_id": "synthetic", "clips": clips, "routes": routes}), encoding="utf-8")
        report = verify.audit_study(path)
        self.assertEqual(report["failed_artifact_slots"], 1)

    def test_runtime_package_names_follow_python_distribution_normalization(self):
        metadata = self.root / "env/Lib/site-packages/pyannote_audio-4.0.7.dist-info/METADATA"
        metadata.parent.mkdir(parents=True)
        metadata.write_text("Name: pyannote-audio\nVersion: 4.0.7\n\n", encoding="utf-8")
        document = {"runtime_identity": {"packages": {"pyannote.audio": "4.0.7"}}}
        issues = []
        result = verify.audit_runtime(document, [str(self.root / "env/Scripts/python.exe")], verify.Files(), issues)
        self.assertEqual(issues, [])
        self.assertEqual(result["runtime_package_versions_checked"], 1)

    def test_vad_provisioning_pins_and_asset_hashes_reject_changed_identity(self):
        folder = self.root / ".local/vad-comparison/provision"
        folder.mkdir(parents=True)
        model = self.root / "model"
        model.mkdir()
        (model / "model.pt").write_bytes(b"synthetic model asset")
        cache = model / ".cache/huggingface/download"
        cache.mkdir(parents=True)
        (cache / "model.pt.metadata").write_bytes(b"cache identity")
        digest = verify.Files().digest(model / "model.pt")
        cache_digest = verify.Files().digest(cache / "model.pt.metadata")
        (folder / "models-manifest.json").write_text(json.dumps([{"id": "fsmn", "revision": "revision",
            "files": [{"path": "model.pt", "sha256": digest}]}]), encoding="utf-8")
        (folder / "packages-manifest.json").write_text(json.dumps([{"package": "funasr", "version": "1.4.16"}]), encoding="utf-8")
        manifest = {"vad_id": "fsmn", "metadata": {"model_path": str(model), "model_revision": "revision",
            "model_files_sha256": {"model.pt": digest, ".cache/huggingface/download/model.pt.metadata": cache_digest},
            "package_versions": {"funasr": "1.4.16"}}}
        with patch.object(verify, "ROOT", self.root):
            issues = []
            result = verify.audit_vad_assets(manifest, verify.Files(), issues)
            self.assertEqual(issues, [])
            self.assertEqual(result["vad_download_cache_hashes_checked"], 1)
            manifest["metadata"]["model_revision"] = "different"
            manifest["metadata"]["package_versions"]["funasr"] = "0"
            issues = []
            verify.audit_vad_assets(manifest, verify.Files(), issues)
            self.assertIn("vad_provisioned_model_revision_mismatch", issues)
            self.assertIn("vad_provisioned_package_pin_mismatch", issues)

    def test_candidate_override_checks_cuda_pins_and_keeps_cpu_default(self):
        cpu = self.root / ".local/vad-comparison/provision"
        gpu = self.root / ".local/vad-comparison/provision-gpu"
        model = self.root / "model"
        model.mkdir()
        (model / "model.pt").write_bytes(b"same frozen model for cpu and gpu")
        digest = verify.Files().digest(model / "model.pt")
        models = [{"id": candidate, "revision": "revision", "files": [{"path": "model.pt", "sha256": digest}]}
                  for candidate in ("pyannote-current", "fsmn")]
        for folder, torch_version in ((cpu, "2.10.0+cpu"), (gpu, "2.10.0+cu128")):
            folder.mkdir(parents=True)
            (folder / "models-manifest.json").write_text(json.dumps(models), encoding="utf-8")
            (folder / "packages-manifest.json").write_text(json.dumps([
                {"package": "pyannote.audio", "version": "4.0.7"},
                {"package": "torch", "version": torch_version}]), encoding="utf-8")
        manifest = {"vad_id": "pyannote-current", "metadata": {"model_path": str(model),
            "model_revision": "revision", "model_files_sha256": {"model.pt": digest},
            "package_versions": {"pyannote.audio": "4.0.7", "torch": "2.10.0+cu128"}}}
        with patch.object(verify, "ROOT", self.root):
            folders = verify.study_provision_dirs({"vad_provision_dirs": {
                "pyannote-current": ".local/vad-comparison/provision-gpu"}})
            issues = []
            result = verify.audit_vad_assets(manifest, verify.Files(), issues,
                                             provision_dir=folders.get("pyannote-current"))
            self.assertEqual(issues, [])
            self.assertEqual(result["vad_package_pins_checked"], 2)
            self.assertEqual(result["vad_provision_dir"], str(gpu))
            self.assertEqual(result["vad_provisioned_package_pins"]["torch"], "2.10.0+cu128")
            self.assertEqual(result["vad_provisioned_model_identity"], {"id": "pyannote-current", "revision": "revision"})
            self.assertEqual(result["vad_provision_manifest_sha256"]["packages-manifest.json"],
                             verify.Files().digest(gpu / "packages-manifest.json"))
            issues = []
            verify.audit_vad_assets(manifest, verify.Files(), issues)
            self.assertIn("vad_provisioned_package_pin_mismatch", issues)
            cpu_manifest = copy.deepcopy(manifest)
            cpu_manifest["vad_id"] = "fsmn"
            cpu_manifest["metadata"]["package_versions"]["torch"] = "2.10.0+cpu"
            issues = []
            cpu_result = verify.audit_vad_assets(cpu_manifest, verify.Files(), issues,
                                                 provision_dir=folders.get("fsmn"))
            self.assertEqual(issues, [])
            self.assertEqual(cpu_result["vad_provision_dir"], str(cpu))
            manifest["metadata"]["package_versions"].pop("torch")
            issues = []
            verify.audit_vad_assets(manifest, verify.Files(), issues, provision_dir=gpu)
            self.assertIn("vad_provisioned_package_pin_not_observed", issues)
            (gpu / "packages-manifest.json").write_text("[]", encoding="utf-8")
            issues = []
            verify.audit_vad_assets(manifest, verify.Files(), issues, provision_dir=gpu)
            self.assertIn("vad_provisioned_package_pins_missing", issues)

    def test_invalid_provision_override_fails_without_cpu_fallback(self):
        for overrides in (None, [], {"unknown": str(self.root)}, {"original": str(self.root)},
                          {"pyannote-current": ""}, {"pyannote-current": 123},
                          {"pyannote-current": str(self.root)}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                verify.study_provision_dirs({"vad_provision_dirs": overrides})
        self.assertEqual(verify.study_provision_dirs({}), {})


if __name__ == "__main__":
    unittest.main()
