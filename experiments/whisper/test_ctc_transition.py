"""GPU-free regression tests for an explicit CTC diagnostic; no model assets."""
import ast
from pathlib import Path
import types
import unittest
import dataclasses

from ctc_transition import TransitionRecorder, capture_transitions

try:
    import torch
except ImportError:
    torch = None


@unittest.skipUnless(torch is not None, "Run CTC tests in the pinned WhisperX environment")
class TransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        package = importlib.util.find_spec("whisperx")
        if package is None:
            raise unittest.SkipTest("WhisperX package not installed")
        source = Path(package.origin).parent / "alignment.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        names = {"get_trellis", "backtrack", "merge_repeats", "Point", "Segment"}
        selected = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
        namespace = {"torch": torch, "dataclass": dataclasses.dataclass}
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"), namespace)
        cls.functions = namespace

    def setUp(self):
        self.module = types.SimpleNamespace(backtrack=self.functions["backtrack"])
        probabilities = torch.full((106, 4), .0001, device="cpu")
        probabilities[:, 0] = .9997
        for frame, token in ((1, 1), (102, 2), (104, 3)):
            probabilities[frame] = .0001
            probabilities[frame, token] = .9997
        self.emission = torch.log(probabilities)
        self.tokens = [1, 2, 3]
        self.trellis = self.functions["get_trellis"](self.emission, self.tokens, 0)
        self.segments = [{"text": "ABC", "start": 5.0, "end": 7.12}]
        self.dictionary = {"a": 1, "b": 2, "c": 3}

    def test_native_unchanged_and_blank_frames_excluded(self):
        native = self.module.backtrack(self.trellis, self.emission, self.tokens, 0)
        original_function = self.module.backtrack
        with capture_transitions(self.module, self.segments, self.dictionary, 10, enabled=True) as recorder:
            observed = self.module.backtrack(self.trellis, self.emission, self.tokens, 0)
        self.assertEqual(observed, native)
        self.assertIs(self.module.backtrack, original_function)
        upstream = self.functions["merge_repeats"](native, "ABC")
        self.assertEqual((upstream[0].start, upstream[0].end), (1, 102))
        self.assertEqual(recorder.records[0]["tokens"][0]["blank_stay_frames"], 100)
        derived = recorder.derived_segments()[0]["chars"]
        self.assertEqual((derived[0]["start"], derived[0]["end"]), (5.02, 5.04))
        self.assertEqual((derived[1]["start"], derived[1]["end"]), (7.04, 7.06))
        self.assertEqual(derived[0]["time_semantics"], "ctc_transition_frame_interval")

    def test_default_disabled_does_not_patch(self):
        original_function = self.module.backtrack
        with capture_transitions(self.module, self.segments, self.dictionary, 10, enabled=False) as recorder:
            self.assertIsNone(recorder)
            self.assertIs(self.module.backtrack, original_function)
        self.assertIs(self.module.backtrack, original_function)

    def test_failed_path_preserves_text_without_timing(self):
        recorder = TransitionRecorder(self.segments, self.dictionary, 10)
        recorder.observe(self.trellis, self.emission, self.tokens, 0, None)
        result = recorder.derived_segments()[0]
        self.assertEqual(result["text"], "ABC")
        self.assertTrue(all(char["start"] is None and char["end"] is None for char in result["chars"]))

    def test_source_offset(self):
        with capture_transitions(self.module, self.segments, self.dictionary, 10, enabled=True) as recorder:
            self.module.backtrack(self.trellis, self.emission, self.tokens, 0)
        import test_run
        derived = test_run.run.evaluation(self.segments, recorder.derived_segments(), 100, character=True)
        self.assertEqual(derived["units"][0]["start"], 105.02)
        self.assertEqual(derived["units"][0]["end"], 105.04)


if __name__ == "__main__":
    unittest.main()
