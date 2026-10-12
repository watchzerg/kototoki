"""Offline orchestration tests using fake subprocess stages, no backend deps."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import wave

import run_combined as combined


def asr_fixture(source_hash, audio_hash, offset):
    return {"schema_version": 1, "route": "W0", "text": "A?", "original_segments": [
        {"id": 1, "text": "A?", "start": 0., "end": 1., "compression_ratio": 1., "tokens": [1,2]}],
        "input": {"file_sha256": audio_hash, "pcm_sha256": "pcm"}, "offset_s": offset,
        "implementation": {"sha256": source_hash}, "cached_inference": False, "offline_requested": True,
        "devices": {"asr": {"device": "cuda", "device_index": [0], "compute_type": "float16"}},
        "environment": {"packages": {"faster-whisper": "1.2.1", "ctranslate2": "4.8.2"}},
        "native": {"info": {"transcription_options": {"temperatures": [0.,.2,.4,.6,.8,1.], "compression_ratio_threshold": 2.4}}},
        "effective_parameters": {"transcribe": {"language": "ja", "task": "transcribe", "beam_size": 5,
            "word_timestamps": True, "vad_filter": False, "chunk_length": 30, "condition_on_previous_text": False}}}


def ctc_fixture(asr):
    return {**copy.deepcopy(asr), "route": "W1",
        "units": [{"char_start": 0, "char_end": 1, "start": asr["offset_s"], "end": asr["offset_s"] + .1,
                   "status": "ok", "granularity": "character", "time_source": "api"},
                  {"char_start": 1, "char_end": 2, "start": None, "end": None,
                   "status": "text_only", "granularity": "character", "time_source": "api"}],
        "effective_parameters": {"asr_reused": True, "ctc_normalize": True, "padding": 0., "interpolate_method": "nearest"},
        "devices": {"aligner": {"model": "cuda:0", "forward_observation": ["cuda:0"]}},
        "experimental_preprocessing": {"records": [{"segment_index": 0, "actual_input_device": "cuda:0"}]},
        "experimental_alignment": {"time_semantics": "ctc_nonblank_token_span", "records": [
            {"segment_index": 0, "failure": None, "decoder_input_device": "cuda:0", "decoder_output_device": "cuda:0"}]}}


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.asr = asr_fixture("src", "wav", 10.)

    def test_asr_identity_device_fallback_and_full_text_checks(self):
        combined.validate_asr(self.asr, "src", "wav", 10.)
        variants = []
        for key, value in (("text", "lost"), ("cached_inference", True), ("offset_s", 11.)):
            bad = copy.deepcopy(self.asr); bad[key] = value; variants.append(bad)
        bad = copy.deepcopy(self.asr); bad["devices"]["asr"]["device"] = "cpu"; variants.append(bad)
        bad = copy.deepcopy(self.asr); bad["native"]["info"]["transcription_options"]["temperatures"] = [0.]; variants.append(bad)
        for bad in variants:
            with self.assertRaises(ValueError): combined.validate_asr(bad, "src", "wav", 10.)

    def test_compression_risk_retained_without_cleaning(self):
        self.asr["original_segments"][0]["compression_ratio"] = 55.625
        evidence = combined.validate_asr(self.asr, "src", "wav", 10.)
        self.assertTrue(evidence["unresolved_generation_risk"])
        self.assertFalse(evidence["text_cleaned"])
        self.assertEqual(self.asr["text"], "A?")

    def test_ctc_identity_and_cuda_each_stage(self):
        ctc = ctc_fixture(self.asr)
        combined.validate_ctc_identity(ctc, self.asr, "src", "wav", 10.)
        validate, error = combined.load_ctc_validator(combined.PROJECT / "experiments/qwen/run_cross.py")
        self.assertTrue(validate(ctc)["executed"])
        for field in ("decoder_input_device", "decoder_output_device"):
            bad = copy.deepcopy(ctc); bad["experimental_alignment"]["records"][0][field] = "cpu"
            with self.assertRaises(error): validate(bad)
        bad = copy.deepcopy(ctc); bad["experimental_alignment"]["records"][0]["failure"] = "CTC failure"
        with self.assertRaises(error): validate(bad)
        bad = copy.deepcopy(ctc); bad["text"] = "A"
        with self.assertRaises(ValueError): combined.validate_ctc_identity(bad, self.asr, "src", "wav", 10.)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        for relative in combined.SOURCE_FILES:
            destination = self.project / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(combined.PROJECT / relative, destination)
        self.audio = self.project / "audio.wav"
        with wave.open(str(self.audio), "wb") as file:
            file.setnchannels(1); file.setsampwidth(2); file.setframerate(16000); file.writeframes(b"\0\0" * 16000)
        self.args = combined.parser().parse_args(["--audio", str(self.audio), "--offset", "10",
            "--output", str(self.project / ".local/run/result.json"), "--w0-python", sys.executable,
            "--whisper-python", sys.executable])
        self.failure = None

    def fake_run(self, command, **kwargs):
        path = Path(command[command.index("--output") + 1]); route = command[command.index("--route") + 1]
        if route == "W0":
            value = asr_fixture(combined.sha256(Path(command[1])), combined.sha256(self.audio), 10.)
        else:
            asr = json.loads(Path(command[command.index("--asr-result") + 1]).read_text())
            value = ctc_fixture(asr)
            if self.failure == "decoder": value["experimental_alignment"]["records"][0]["failure"] = "synthetic failure"
        combined.write_json(path, value)
        kwargs["stdout"].write("Synthetic stage log\n")
        return types.SimpleNamespace(returncode=4 if self.failure == "exit" and route == "W1" else 0)

    def run_pipeline(self):
        with patch.object(combined, "PROJECT", self.project), patch.object(combined.subprocess, "run", self.fake_run):
            return combined.run_pipeline(self.args)

    def test_fresh_pipeline_stage_hashes_and_text_only_preserved(self):
        result = self.run_pipeline()
        pipeline = result["pipeline"]
        self.assertEqual([s["stage"] for s in pipeline["stages"]], ["asr", "ctc"])
        self.assertTrue(pipeline["new_asr_inference"] and pipeline["new_alignment_inference"])
        self.assertEqual(pipeline["stage_cache"]["asr"], "fresh")
        self.assertEqual(result["text"], "A?")
        self.assertEqual(result["units"][1]["status"], "text_only")
        for artifact in list(pipeline["source_files"].values()) + [
                {"path": s["output"], "sha256": s["output_sha256"]} for s in pipeline["stages"]]:
            self.assertEqual(combined.sha256(Path(artifact["path"])), artifact["sha256"])
        from experiments.performance.report import pipeline_artifacts
        binding = pipeline_artifacts(result, {"audio_sha256": combined.sha256(self.audio), "fresh_subprocess": True})
        self.assertTrue(binding["verified_fresh_pipeline"], binding["issues"])
        with self.assertRaises(FileExistsError): self.run_pipeline()

    def test_decoder_failure_preserves_asr_ctc_and_logs(self):
        self.failure = "decoder"
        with self.assertRaises(ValueError): self.run_pipeline()
        result = json.loads(self.args.output.read_text())
        self.assertEqual(result["failure_classification"], "alignment_failure")
        self.assertEqual(result["text"], "A?")
        self.assertTrue(result["recognition_preserved"])
        for stage in result["pipeline"]["stages"]:
            self.assertTrue(Path(stage["output"]).is_file() and Path(stage["log"]).is_file())

    def test_subprocess_exit_preserves_completed_asr_text(self):
        self.failure = "exit"
        with self.assertRaises(RuntimeError): self.run_pipeline()
        result = json.loads(self.args.output.read_text())
        self.assertEqual(result["text"], "A?")
        self.assertEqual(result["pipeline"]["stages"][-1]["returncode"], 4)
        self.assertEqual(result["pipeline"]["status"], "failed")

    def test_output_outside_private_root_rejected_without_writing(self):
        self.args.output = self.project / "forbidden.json"
        with self.assertRaises(ValueError): self.run_pipeline()
        self.assertFalse(self.args.output.exists())


if __name__ == "__main__": unittest.main()
