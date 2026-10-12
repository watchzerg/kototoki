"""Offline public-contract tests; no model loads or downloads."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from . import RECIPES
from .chunks import MAX_SAMPLES, RATE, cut_merge_chunks, fixed_chunks, make_chunk, merge_short_chunks, validate_chunks
from .pipeline import build_result, validate_asr
from .run import orchestrate, parser
from .storage import ROOT, read_json, write_json

try:
    import numpy as np
except ImportError:
    np = None


def fixture(samples=1001, offset=3.25):
    chunks = fixed_chunks(samples)
    plan = {"input": {"samples": samples}, "offset_s": offset, "chunks": chunks,
            "recipe": RECIPES["fixed30"], "segmentation": "fixed30",
            "effective_parameters": {}, "source_sha256": {}}
    segments = [{**c, "text": "あ。"} for c in chunks]
    traces = [{"chunk_index": i, "start_sample": c["start_sample"], "end_sample": c["end_sample"],
               "pcm_float32_sha256": "fake", "token_limit_reached": False} for i, c in enumerate(chunks)]
    saved = {"original_segments": segments, "text": "".join(s["text"] for s in segments),
             "asr_traces": traces, "effective_parameters": {}}
    aligned = {"text": saved["text"], "records": [], "derived_segments": [], "units": []}
    for i, _ in enumerate(saved["text"]):
        aligned["units"].append({"char_start": i, "char_end": i+1, "granularity": "character", "time_source": "api",
                                 "status": "text_only", "start": None, "end": None})
    aligned["units"][0].update(status="ok", start=offset, end=offset+samples/RATE)
    return plan, saved, aligned


class ChunkTests(unittest.TestCase):
    def test_arbitrary_integer_tails_conserved(self):
        for samples in (1, 999, 1001, MAX_SAMPLES, MAX_SAMPLES+1001, MAX_SAMPLES*2+1):
            chunks = fixed_chunks(samples)
            self.assertEqual(sum(c["end_sample"]-c["start_sample"] for c in chunks), samples)
            self.assertEqual(chunks[-1]["end"], samples/RATE)

    def test_reject_malformed_windows(self):
        for chunks in ([make_chunk(0, 1000)], [make_chunk(0, 500), make_chunk(499, 1001)],
                       [make_chunk(1, 1001)], [make_chunk(0, MAX_SAMPLES+1)]):
            with self.assertRaises(ValueError):
                validate_chunks(chunks, 1001)
        bad = make_chunk(0, 1001)
        for key, value in (("start_sample", False), ("end_sample", 1001.0), ("end", float("nan")), ("end", 0.1)):
            with self.assertRaises(ValueError):
                validate_chunks([{**bad, key: value}], 1001)

    def test_real_adjacent_merge_and_bounded_tail(self):
        samples = 65*RATE+1001
        atomic = [make_chunk(s, min(samples, s+5*RATE)) for s in range(0, samples, 5*RATE)]
        merged = merge_short_chunks(atomic, samples)
        self.assertEqual([c["end_sample"]-c["start_sample"] for c in merged], [MAX_SAMPLES, MAX_SAMPLES, 5*RATE+1001])
        self.assertEqual(len(merged[0]["candidate_windows"]), 6)

    @unittest.skipIf(np is None, "NumPy absent in root environment; run pinned backend checks")
    def test_dense_cut_merge_silence_nonstop_latest_tie_and_odd_tail(self):
        for level in (0.0, .2):
            chunks = cut_merge_chunks(np.full(65*RATE+1001, level, dtype=np.float32))
            self.assertEqual([c["end_sample"] for c in chunks], [MAX_SAMPLES, 2*MAX_SAMPLES, 65*RATE+1001])
            self.assertEqual(chunks[0]["candidate_windows"][0]["end_sample"], 5*RATE)
            self.assertTrue(chunks[0]["merged_adjacent_candidates"])

    @unittest.skipIf(np is None, "NumPy absent in root environment; run pinned backend checks")
    def test_low_energy_candidates_change_boundary_without_losing_samples(self):
        audio = np.full(61*RATE+1001, .2, dtype=np.float32)
        audio[4*RATE-1600:4*RATE] = 0
        chunks = cut_merge_chunks(audio)
        self.assertEqual(chunks[0]["candidate_windows"][0]["end_sample"], 4*RATE)
        validate_chunks(chunks, len(audio))
        for bad in (np.array([], dtype=np.float32), np.zeros(2, dtype=np.float64),
                    np.array([float("nan")], dtype=np.float32)):
            with self.assertRaises(ValueError):
                cut_merge_chunks(bad)


class ResultTests(unittest.TestCase):
    def test_complete_text_text_only_and_source_offset(self):
        plan, saved, aligned = fixture()
        result = build_result(plan, saved, aligned, {}, {})
        self.assertEqual(result["text"], "あ。")
        self.assertEqual(result["units"][1]["status"], "text_only")
        self.assertEqual(result["source_end_seconds"], 3.25+1001/RATE)

    def test_alignment_cannot_drop_duplicate_or_change_text_or_fabricate_time(self):
        plan, saved, original = fixture()
        for alteration in ("drop", "duplicate", "text", "outside", "untimed"):
            aligned = copy.deepcopy(original)
            if alteration == "drop":
                aligned["units"].pop()
            elif alteration == "duplicate":
                aligned["units"].append(copy.deepcopy(aligned["units"][0]))
            elif alteration == "text":
                aligned["text"] = "あ"
            elif alteration == "outside":
                aligned["units"][0]["start"] = 0
            else:
                aligned["units"][1]["start"] = 3.25
            with self.assertRaises(ValueError):
                build_result(plan, saved, aligned, {}, {})

    def test_asr_caps_and_malformed_segment_contract(self):
        plan, original, _ = fixture()
        for change in ("text", "window", "cap", "trace"):
            saved = copy.deepcopy(original)
            if change == "text":
                saved["text"] = ""
            elif change == "window":
                saved["original_segments"][0]["end_sample"] = 1000
            elif change == "cap":
                saved["asr_traces"][0]["token_limit_reached"] = True
            else:
                saved["asr_traces"] = []
            with self.assertRaises(ValueError):
                validate_asr(saved, plan["chunks"], 1001)

    def test_alignment_inference_failure_is_partial_with_complete_text(self):
        plan, saved, aligned = fixture()
        aligned["records"] = [{"segment_index": 0, "failure": "RuntimeError: CUDA failure"}]
        result = build_result(plan, saved, aligned, {}, {})
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["alignment_failure_count"], 1)
        self.assertEqual(result["text"], saved["text"])


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / ".local/x0-demo"
        self.root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(self.temporary.cleanup)
        self.out = Path(self.temporary.name) / "run with 空格"
        self.args = parser().parse_args(["--audio", str(Path(self.temporary.name)/"音频.wav"), "--out", str(self.out),
                                        "--qwen-python", sys.executable, "--mms-python", sys.executable])

    def fake(self, command, out, stage, environment):
        self.assertEqual(command[-1], str(out))
        self.assertEqual(environment["HF_HUB_OFFLINE"], "1")
        self.assertTrue(Path(environment["TMP"]).is_relative_to(out))
        self.assertTrue((ROOT / ".local/gpu.lock").exists())
        if stage == "plan":
            write_json(out / "plan.json", {"status": "fake"})
        if stage == "asr":
            write_json(out / "asr.json", {"text": "私有全文"})
        if stage == "align":
            write_json(out / "alignment.json", {"text": "私有全文", "chunks": [], "recipe": "fake",
                                                "status": "ok", "stages": {}, "runtime_identity": {}})
        return {"stage": stage, "pid": 100, "wall_s": .25, "exit_code": 0, "process_count": 1}

    def test_one_command_fake_children_costs_private_text_and_no_overwrite(self):
        result = orchestrate(self.args, self.fake)
        self.assertEqual(result["process_count"], 3)
        self.assertEqual(result["stages"]["child_process_wall_s"], .75)
        self.assertEqual((self.out / "transcript.txt").read_text(encoding="utf-8"), "私有全文")
        self.assertFalse((self.out / "tmp").exists())
        with self.assertRaises(FileExistsError):
            orchestrate(self.args, self.fake)

    def test_failed_child_preserves_complete_prior_stage_and_partial_asr(self):
        def executor(command, out, stage, environment):
            cost = self.fake(command, out, stage, environment)
            if stage == "asr":
                write_json(out / "asr-partial.json", {"text": "partial", "token_limit_reached": True})
                cost["exit_code"] = 1
            return cost
        with self.assertRaises(RuntimeError):
            orchestrate(self.args, executor)
        failure = read_json(self.out / "failure.json")
        self.assertEqual(failure["stage"], "asr")
        self.assertEqual(failure["process_count"], 2)
        self.assertTrue((self.out / "plan.json").is_file())
        self.assertTrue((self.out / "asr-partial.json").is_file())
        self.assertFalse((self.out / "result.json").exists())

    def test_external_vad_manifest_bytes_and_identity_frozen_before_children(self):
        manifest = Path(self.temporary.name) / "external-vad.json"
        manifest.write_bytes(b'{"vad_id": "fake-vad"}\n')
        self.args.segmentation = "vad"
        self.args.vad_manifest = manifest
        def executor(command, out, stage, environment):
            request = read_json(out / "request.json")
            frozen = Path(request["vad_manifest"]["frozen_path"])
            self.assertEqual(frozen.read_bytes(), manifest.read_bytes())
            self.assertEqual(request["vad_manifest"]["sha256"], hashlib.sha256(manifest.read_bytes()).hexdigest())
            return self.fake(command, out, stage, environment)
        orchestrate(self.args, executor)

    def test_help_needs_no_backend_dependencies(self):
        done = subprocess.run([sys.executable, "-m", "experiments.x0_demo.run", "--help"], cwd=ROOT,
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("cut-merge", done.stdout)

    def test_interrupted_child_is_terminated_and_accounted_before_reraise(self):
        process = Mock(pid=123)
        process.poll.return_value = None
        process.wait.side_effect = [KeyboardInterrupt("cancelled"), -15]
        with patch("experiments.x0_demo.run.subprocess.Popen", return_value=process):
            with self.assertRaises(KeyboardInterrupt):
                orchestrate(self.args)
        process.terminate.assert_called_once()
        failure = read_json(self.out / "failure.json")
        self.assertEqual(failure["process_count"], 1)
        self.assertEqual(failure["processes"][0]["pid"], 123)
        self.assertTrue(failure["processes"][0]["interrupted"])
        self.assertGreaterEqual(failure["processes"][0]["wall_s"], 0)
        self.assertFalse((self.out / "tmp").exists())

    def test_exclusive_completed_json(self):
        file = Path(self.temporary.name)/"evidence.json"
        write_json(file, {"a": 1})
        with self.assertRaises(FileExistsError):
            write_json(file, {"a": 2})
        self.assertEqual(read_json(file), {"a": 1})


if __name__ == "__main__":
    unittest.main()
