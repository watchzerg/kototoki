"""GPU-free tests for cached VAD-ASR provenance and unchanged CTC input boundaries."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.components import run_vad_ctc as runner
from experiments.components.run import write_new


class VadCtcTests(unittest.TestCase):
    def fixture(self):
        identity = {"file_sha256": "a" * 64, "pcm_sha256": "b" * 64, "samples": 64000,
                    "sample_rate": 16000, "channels": 1, "duration_s": 4}
        clip = {"id": "clip", "offset": 120}
        contract = {"clip_timestamps": [0, 4], "empty_speech": False, "sample_mapping_exact": True}
        segments = [{"text": "日本語", "start": 1, "end": 2,
                     "words": [{"word": "日本語", "start": .5, "end": 2, "probability": .9}]}]
        saved = {"route": "W0-pyannote-vad-clips", "cached_inference": False, "offline_requested": True,
            "input": identity, "offset_s": 120, "text": "日本語", "original_segments": segments,
            "native": {"segments": deepcopy(segments)},
            "experimental_vad": {**contract, "file_sha256": "v" * 64,
                "audio_transform": "original complete PCM; clips use original feature/time coordinates"},
            "effective_parameters": {"transcribe": {"language": "ja", "task": "transcribe", "beam_size": 5,
                "word_timestamps": True, "vad_filter": False, "chunk_length": 30,
                "condition_on_previous_text": False, "clip_timestamps": [0, 4]},
                "temperature": "unchanged native fallback defaults",
                "info": {"transcription_options": {"temperatures": [0, .2, .4, .6, .8, 1]}}},
            "devices": {"asr": {"device": "cuda", "compute_type": "float16", "device_index": [0], "inference_requested": True}},
            "environment": {"packages": {"faster-whisper": "1.2.1"}}}
        source = {"path": "original-vad-asr.json", "sha256": "s" * 64, "vad": {"path": "vad.json", "sha256": "v" * 64}}
        return saved, identity, clip, contract, source

    def test_bridge_preserves_vad_text_metadata_and_original_coordinates(self):
        saved, identity, clip, contract, source = self.fixture()
        before = deepcopy(saved)
        with patch.object(runner, "validate_vad", return_value=contract):
            runner.validate_cached_asr(saved, {}, identity, clip, "v" * 64)
        bridge = runner.build_bridge(saved, source)
        runner.verify_bridge(bridge, saved, 120)
        self.assertEqual(saved, before)
        self.assertEqual(bridge["original_asr"]["original_segments"], saved["original_segments"])
        self.assertEqual(bridge["text"], saved["text"])
        self.assertEqual(bridge["offset_s"], 120)
        self.assertEqual(bridge["input"], identity)
        expected = deepcopy(saved["original_segments"])
        expected[0]["start"] = .5
        self.assertEqual(bridge["original_segments"], expected)
        self.assertEqual(bridge["upstream_vad"], source["vad"])

    def test_wrong_route_text_gpu_source_or_decoding_options_fail_closed(self):
        saved, identity, clip, contract, _ = self.fixture()
        cases = []
        for key, value in (("route", "W0"), ("text", "日本"), ("offset_s", 121)):
            bad = deepcopy(saved); bad[key] = value; cases.append(bad)
        bad = deepcopy(saved); bad["devices"]["asr"]["device"] = "cpu"; cases.append(bad)
        bad = deepcopy(saved); bad["effective_parameters"]["transcribe"]["clip_timestamps"] = [0, 3]; cases.append(bad)
        bad = deepcopy(saved); bad["effective_parameters"]["transcribe"]["temperature"] = 0; cases.append(bad)
        bad = deepcopy(saved); bad["input"]["pcm_sha256"] = "other"; cases.append(bad)
        bad = deepcopy(saved); bad["experimental_vad"]["file_sha256"] = "other"; cases.append(bad)
        bad = deepcopy(saved); bad["original_segments"][0]["words"][0]["end"] = 5
        bad["native"]["segments"] = deepcopy(bad["original_segments"]); cases.append(bad)
        with patch.object(runner, "validate_vad", return_value=contract):
            for bad in cases:
                with self.assertRaises(ValueError):
                    runner.validate_cached_asr(bad, {}, identity, clip, "v" * 64)

    def test_empty_vad_retains_empty_text_and_no_asr_execution(self):
        saved, identity, clip, contract, source = self.fixture()
        contract.update(clip_timestamps=[], empty_speech=True)
        saved["experimental_vad"].update(contract)
        saved["effective_parameters"]["transcribe"]["clip_timestamps"] = []
        saved.update(text="", original_segments=[], native={"segments": []}, devices={"asr": {"inference_executed": False}})
        with patch.object(runner, "validate_vad", return_value=contract):
            runner.validate_cached_asr(saved, {}, identity, clip, "v" * 64)
            bridge = runner.build_bridge(saved, source)
            self.assertEqual(bridge["text"], "")
            self.assertEqual(bridge["original_segments"], [])
            saved["devices"]["asr"]["inference_executed"] = True
            with self.assertRaises(ValueError):
                runner.validate_cached_asr(saved, {}, identity, clip, "v" * 64)

    def test_incomplete_upstream_never_creates_new_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            local = Path(temporary)
            clips = [{"id": f"clip-{index}"} for index in range(12)]
            parent = {"clips": clips, "tasks": [], "source_sha256": {}}
            template = {"clips": clips, "tasks": [{"clip": c["id"]} for c in clips], "source_sha256": {}}
            write_new(local / runner.SOURCE_NAME / "plan.json", parent)
            write_new(local / runner.CTC_NAME / "plan.json", template)
            with (patch.object(runner, "LOCAL", local), patch.object(runner, "verify_sources"),
                  patch.object(runner, "source_cache", side_effect=ValueError("not completed"))):
                with self.assertRaises(ValueError):
                    runner.prepare("not-ready")
            self.assertFalse((local / "not-ready").exists())

    def test_ctc_output_cannot_change_complete_cached_vad_text(self):
        saved, identity, clip, _, source = self.fixture()
        bridge = runner.build_bridge(saved, source)
        clip.update(audio_sha256=identity["file_sha256"], pcm_sha256=identity["pcm_sha256"])
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "result.json"
            task = {"output": str(output), "bridge": {"path": "bridge.json"}}
            result = {"route": "W1", "input": identity, "offset_s": 120, "text": saved["text"],
                      "original_segments": bridge["original_segments"], "native": {"reused_asr_file": "bridge.json"},
                      "effective_parameters": {"asr_reused": True}}
            write_new(output, result)
            result["text"] = "日本"
            output.write_text(json.dumps(result), encoding="utf-8")
            with self.assertRaises(ValueError):
                runner.verify_result(task, clip, bridge)


if __name__ == "__main__":
    unittest.main()
